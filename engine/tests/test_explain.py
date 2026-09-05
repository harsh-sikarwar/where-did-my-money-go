"""The explanation stage. ADR-050.

The tests that matter here are not "does it write a nice sentence" — they are:

  1. Can a model put a number on the verdict screen? (It must not.)
  2. Does the screen still render when the model is absent, slow, or broken?

Everything else is copy. These two are the contract, and they are tested with a stub
client that returns deliberately hostile output, because the real model behaving well on
a Tuesday proves nothing about the Wednesday it does not.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from finctl.classify.classifier import Classification
from finctl.explain import (
    LLMConfig,
    explain,
    explain_detailed,
    guard,
    has_numerals,
    template,
)
from finctl.explain.client import ExplainUnavailable, complete
from finctl.explain.render import SYSTEM_PROMPT, _facts, redact_figures
from finctl.rank.ranker import LINE_COPY, Verdict, VerdictLine

DISABLED = LLMConfig(api_key=None)
ENABLED = LLMConfig(api_key="test-key-not-real")


def _verdict(gap_paise: int = 7_872_053, *, lines: list[VerdictLine] | None = None) -> Verdict:
    if lines is None:
        lines = [
            VerdictLine(
                classification=Classification.TIMING,
                label="on its way — settled, not yet in your bank",
                explanation="It arrives on its own.",
                count=12,
                amount_paise=3_100_000,
                actionable=False,
            ),
            VerdictLine(
                classification=Classification.HALTED_SUBSCRIPTION,
                label="subscriptions died silently — recoverable",
                explanation="Razorpay stopped attempting charges.",
                count=6,
                amount_paise=380_000,
                actionable=True,
            ),
        ]
    return Verdict(
        expected_paise=10_000_000,
        received_paise=10_000_000 - gap_paise,
        gap_paise=gap_paise,
        lines=lines,
    )


class TestTheModelCannotPutANumberOnScreen:
    """The whole reason an LLM is allowed anywhere near this product.

    Every accuracy figure in METRICS.md describes deterministic code. If a model can
    write a rupee amount onto the verdict screen, none of those numbers describe what
    the merchant actually reads.
    """

    @pytest.mark.parametrize(
        "hostile",
        [
            "You are short ₹4,200 this week.",
            "You lost 4200 rupees.",
            "Six customers need chasing.",
            "About two lakh is missing.",
            "Roughly 15% of your revenue did not arrive.",
            "3 subscriptions stopped.",
        ],
    )
    def test_prose_containing_a_figure_is_discarded(self, hostile: str) -> None:
        assert guard(hostile) is None, f"a figure survived the guard: {hostile!r}"

    def test_a_hallucinated_amount_never_reaches_the_merchant(self, monkeypatch) -> None:
        """The test this stage exists for.

        A model that invents "₹9,99,999" must not be able to show it to anyone. The
        engine's real figure is rendered separately by `format_rupees`; the model's is
        deleted.
        """
        monkeypatch.setattr(
            "finctl.explain.render.complete",
            lambda *a, **k: "Your shortfall is ₹9,99,999 this week. Act now.",
        )
        prose, source = explain(_verdict(), ENABLED)
        assert "9,99,999" not in prose
        assert "999" not in prose
        assert source == "template", "hallucinated figures must fall back, not be edited"

    def test_a_mixed_response_is_discarded_whole(self, monkeypatch) -> None:
        """One fabricated figure discards the entire response, not just its sentence.

        Salvaging the clean half is the tempting behaviour and the wrong one: the
        surviving sentence was written in the belief that the invented number was true,
        so "act now" would follow from a shortfall the engine never found.
        """
        monkeypatch.setattr(
            "finctl.explain.render.complete",
            lambda *a, **k: (
                "Your bank is short by ₹4,200 this week. "
                "The halted subscriptions are recoverable if you act."
            ),
        )
        prose, source = explain(_verdict(), ENABLED)
        assert source == "template"
        assert "4,200" not in prose
        assert prose == template(_verdict())

    @pytest.mark.parametrize(
        "clean",
        [
            "Your bank received less than your ledger expected.",
            "The halted subscriptions are recoverable if you act.",
        ],
    )
    def test_clean_prose_is_left_alone(self, clean: str) -> None:
        assert guard(clean) == clean

    def test_number_words_count_as_numbers(self) -> None:
        """"six customers" is a figure. A model told not to use digits reaches for these."""
        assert has_numerals("six customers need chasing")
        assert has_numerals("about two lakh")
        assert not has_numerals("several customers need chasing")


class TestItAlwaysRenders:
    """A reconciliation summary must not fail because an inference endpoint was slow."""

    def test_no_key_uses_the_template(self) -> None:
        prose, source = explain(_verdict(), DISABLED)
        assert source == "template"
        assert prose == template(_verdict())

    @pytest.mark.parametrize(
        "failure",
        [
            ExplainUnavailable("timeout"),
            ExplainUnavailable("HTTP 403"),
            ExplainUnavailable("model returned no content (finish_reason=length)"),
        ],
    )
    def test_every_client_failure_falls_back(self, monkeypatch, failure) -> None:
        def boom(*a, **k):
            raise failure

        monkeypatch.setattr("finctl.explain.render.complete", boom)
        prose, source = explain(_verdict(), ENABLED)
        assert source == "template"
        assert prose == template(_verdict())

    def test_an_empty_model_response_falls_back(self, monkeypatch) -> None:
        """GPT-OSS is a reasoning model: at default effort it returns empty content."""
        monkeypatch.setattr("finctl.explain.render.complete", lambda *a, **k: "   ")
        _, source = explain(_verdict(), ENABLED)
        assert source == "template"

    def test_prose_that_is_entirely_numeric_falls_back(self, monkeypatch) -> None:
        monkeypatch.setattr("finctl.explain.render.complete", lambda *a, **k: "₹4,200.")
        _, source = explain(_verdict(), ENABLED)
        assert source == "template"

    def test_the_source_is_reported_not_hidden(self, monkeypatch) -> None:
        """A product that cannot say whether a model wrote something is not auditable."""
        monkeypatch.setattr(
            "finctl.explain.render.complete",
            lambda *a, **k: "The halted subscriptions are recoverable.",
        )
        assert explain(_verdict(), ENABLED)[1] == "model"
        assert explain(_verdict(), DISABLED)[1] == "template"


class TestItSaysWhyNotJustThat:
    """Every fallback used to be silent and identical. Two of them are not the same
    situation, and the difference cost an afternoon: a rate-limited endpoint and a
    missing key both rendered "I can't reach the model right now" while the model was
    reachable and answering. ADR-050."""

    def test_a_missing_key_is_named_as_such(self) -> None:
        assert explain_detailed(_verdict(), DISABLED)[2] == "no_key"

    def test_the_switch_is_not_reported_as_a_missing_key(self) -> None:
        """Offline on purpose and offline by accident read identically otherwise."""
        cfg = LLMConfig.from_env({"GROQ_API_KEY": "k", "FINCTL_NO_LLM": "1"})
        prose, source, reason = explain_detailed(_verdict(), cfg)
        assert (source, reason) == ("template", "disabled")
        assert prose == template(_verdict())

    def test_a_rate_limit_is_not_reported_as_an_outage(self, monkeypatch) -> None:
        """429 means the endpoint is up, the key is good, and we are out of budget."""

        def limited(*a, **k):
            raise ExplainUnavailable("HTTP 429", reason="rate_limited")

        monkeypatch.setattr("finctl.explain.render.complete", limited)
        prose, source, reason = explain_detailed(_verdict(), ENABLED)
        assert (source, reason) == ("template", "rate_limited")
        assert prose == template(_verdict())

    def test_the_guard_firing_is_not_an_outage_either(self, monkeypatch) -> None:
        """The model wrote a figure and was refused. That is the guard succeeding."""
        monkeypatch.setattr("finctl.explain.render.complete", lambda *a, **k: "You lost ₹4,200.")
        assert explain_detailed(_verdict(), ENABLED)[2] == "guarded"

    def test_a_good_answer_reports_model(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "finctl.explain.render.complete",
            lambda *a, **k: "The halted subscriptions are recoverable.",
        )
        assert explain_detailed(_verdict(), ENABLED)[1:] == ("model", "model")

    def test_the_client_tags_a_429_without_being_asked(self, monkeypatch) -> None:
        """The tag comes from the client, so every caller gets it for free."""
        import urllib.error

        def http_429(*a, **k):
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", http_429)
        with pytest.raises(ExplainUnavailable) as caught:
            complete("s", "u", ENABLED)
        assert caught.value.reason == "rate_limited"

    def test_the_two_value_form_still_works(self) -> None:
        """`explain` is what every existing caller reads; it must not have changed."""
        assert explain(_verdict(), DISABLED) == explain_detailed(_verdict(), DISABLED)[:2]


class TestTheTemplateIsCorrectOnItsOwn:
    """It is the default path, not a degraded one, so it is tested as a first-class output."""

    def test_a_shortfall_is_described_as_less(self) -> None:
        assert "less than" in template(_verdict(gap_paise=7_872_053))

    def test_a_surplus_is_described_as_more(self) -> None:
        assert "more than" in template(_verdict(gap_paise=-5_000))

    def test_it_names_what_needs_action(self) -> None:
        assert "subscriptions died silently" in template(_verdict())

    def test_nothing_actionable_says_so(self) -> None:
        quiet = _verdict(lines=[
            VerdictLine(
                classification=Classification.TIMING,
                label="on its way",
                explanation="It arrives on its own.",
                count=3,
                amount_paise=1000,
                actionable=False,
            )
        ])
        assert "needs anything from you" in template(quiet)

    def test_it_carries_the_engines_own_figure(self) -> None:
        """The template may state amounts — it is engine code, not model output."""
        assert "₹78,720.53" in template(_verdict(gap_paise=7_872_053))


class TestThePromptDoesNotLeaveTheModelGuessing:
    """A fact the model needs and is not given is a fact it will invent.

    The guard catches numbers. It cannot catch a wrong DIRECTION, and the first live run
    produced "You have a net gain this week" over a ₹78,720 shortfall for exactly that
    reason: the prompt described lines and rankings but never which way the money went.
    """

    def test_a_shortfall_is_stated_in_the_prompt(self) -> None:
        facts = _facts(_verdict(gap_paise=7_872_053))
        assert "LESS" in facts
        assert "Never describe this week as a gain" in facts

    def test_a_surplus_is_stated_in_the_prompt(self) -> None:
        facts = _facts(_verdict(gap_paise=-5_000))
        assert "MORE" in facts

    def test_the_prompt_carries_no_figures(self) -> None:
        """The model cannot echo a number it was never shown.

        Asserted with `has_numerals` — the guard's own predicate — rather than a search
        for "₹". The weaker check is what let this bug live behind a green test: the
        shipped FEE copy reads "plus the 18% GST charged on that fee", which carries no
        rupee sign and every bit of a figure.
        """
        assert not has_numerals(_facts(_verdict()))

    def test_the_prompt_carries_no_figures_from_the_real_taxonomy(self) -> None:
        """Every line the engine can actually emit, not a fixture written to pass.

        The fixture's explanations were hand-written for these tests and happened to be
        figure-free, so the prompt builder was never shown the copy it quotes in
        production. Measured consequence: eleven of twelve fee questions to the copilot
        returned the template, because the model repeated the figure it had just been
        handed and `guard` discarded the whole answer.
        """
        lines = [
            VerdictLine(
                classification=classification,
                label=label,
                explanation=explanation,
                count=1,
                amount_paise=1_000,
                actionable=False,
            )
            for classification, (label, explanation) in LINE_COPY.items()
        ]
        assert not has_numerals(_facts(_verdict(lines=lines)))

    def test_redaction_leaves_the_sentence_readable(self) -> None:
        """Stripping the figure must not strip the meaning, or the model loses the fact."""
        redacted = redact_figures(LINE_COPY[Classification.FEE][1])
        assert not has_numerals(redacted)
        assert "GST charged on that fee" in redacted
        assert "  " not in redacted

    def test_the_system_prompt_forbids_numbers(self) -> None:
        assert "NEVER write a number" in SYSTEM_PROMPT


class TestTheClient:
    def test_no_key_raises_rather_than_calling_out(self) -> None:
        with pytest.raises(ExplainUnavailable):
            complete("s", "u", DISABLED)

    def test_config_prefers_the_neutral_key_name(self) -> None:
        cfg = LLMConfig.from_env({
            "FINCTL_LLM_API_KEY": "neutral",
            "GROQ_API_KEY": "vendor",
        })
        assert cfg.api_key == "neutral"

    def test_config_falls_back_to_the_vendor_key(self) -> None:
        assert LLMConfig.from_env({"GROQ_API_KEY": "vendor"}).api_key == "vendor"

    def test_an_absent_key_disables_the_stage(self) -> None:
        assert not LLMConfig.from_env({}).enabled

    def test_the_kill_switch_beats_a_perfectly_good_key(self) -> None:
        """`--no-llm` has to win, or it is a preference rather than a switch."""
        cfg = LLMConfig.from_env({"GROQ_API_KEY": "k", "FINCTL_NO_LLM": "1"})
        assert cfg.api_key == "k"       # the key is still there
        assert cfg.disabled
        assert not cfg.enabled          # and still never used

    def test_the_switch_makes_no_network_call(self, monkeypatch) -> None:
        """The point of the flag is the call that does not happen."""
        def explode(*a, **k):
            raise AssertionError("a request was made with FINCTL_NO_LLM set")

        monkeypatch.setattr(urllib.request, "urlopen", explode)
        cfg = LLMConfig.from_env({"GROQ_API_KEY": "k", "FINCTL_NO_LLM": "1"})
        with pytest.raises(ExplainUnavailable) as caught:
            complete("s", "u", cfg)
        assert caught.value.reason == "disabled"

    def test_off_by_choice_is_not_reported_as_off_by_accident(self) -> None:
        """An operator told "no key" while holding a key goes hunting for nothing."""
        assert LLMConfig.from_env({"GROQ_API_KEY": "k", "FINCTL_NO_LLM": "1"}).off_reason == (
            "disabled"
        )
        assert LLMConfig.from_env({}).off_reason == "no_key"

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
    def test_the_switch_accepts_the_spellings_people_actually_type(self, value) -> None:
        assert LLMConfig.from_env({"GROQ_API_KEY": "k", "FINCTL_NO_LLM": value}).disabled

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
    def test_a_falsey_value_does_not_silently_turn_the_model_off(self, value) -> None:
        """`bool("0")` is True in Python, and a switch that inverts on "false" is a trap."""
        assert not LLMConfig.from_env({"GROQ_API_KEY": "k", "FINCTL_NO_LLM": value}).disabled

    def test_a_bad_timeout_does_not_crash_startup(self) -> None:
        cfg = LLMConfig.from_env({"GROQ_API_KEY": "k", "FINCTL_LLM_TIMEOUT_SECONDS": "soon"})
        assert cfg.timeout_seconds > 0

    def test_the_provider_is_configuration_not_code(self) -> None:
        cfg = LLMConfig.from_env({
            "FINCTL_LLM_API_KEY": "k",
            "FINCTL_LLM_BASE_URL": "http://localhost:8000/v1/",
            "FINCTL_LLM_MODEL": "qwen2.5",
        })
        assert cfg.base_url == "http://localhost:8000/v1"   # trailing slash trimmed
        assert cfg.model == "qwen2.5"

    def test_an_http_error_names_the_endpoint(self, monkeypatch) -> None:
        """"HTTP 404" alone sends someone hunting for a network fault that is a typo."""
        def raise_404(*a, **k):
            raise urllib.error.HTTPError(
                "http://x", 404, "Not Found", {}, None  # type: ignore[arg-type]
            )

        monkeypatch.setattr("urllib.request.urlopen", raise_404)
        with pytest.raises(ExplainUnavailable, match="404"):
            complete("s", "u", ENABLED)

    def test_an_empty_content_response_is_a_failure_not_an_answer(self, monkeypatch) -> None:
        """The GPT-OSS reasoning trap: content empty, finish_reason 'length'."""
        class FakeResponse:
            def read(self):
                return json.dumps({
                    "choices": [{"message": {"content": ""}, "finish_reason": "length"}]
                }).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResponse())
        with pytest.raises(ExplainUnavailable, match="no content"):
            complete("s", "u", ENABLED)
