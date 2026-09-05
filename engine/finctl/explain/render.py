"""Explanation prose. The model writes sentences; the engine writes every number.

THE ONE RULE. No figure a merchant reads comes from a language model. The facts are
already resolved by the time a prompt is built — matched, classified, correlated, and
decomposed into a gap that is asserted to balance — so the model is given finished
arithmetic and asked only to say it in English. `guard` then enforces that: any prose
carrying a figure is discarded outright, because a plausible wrong number is
far more dangerous here than a missing one.

That is a strange-looking rule until you consider what this product claims. Every
accuracy figure in `METRICS.md` describes deterministic code. If a model can put a
rupee amount on the verdict screen, none of those numbers describe what the merchant
actually sees, and the honest-residual argument collapses. A reconciliation engine that
hallucinates is worse than no engine — so the model is placed where hallucination cannot
reach a number. See ADR-050.

WHY IT IS WORTH HAVING AT ALL. The templates are good and were written by hand, but they
are per-classification: they describe a category, not a batch. The model sees the shape of
THIS week — that the timing lag dwarfs the halted subscriptions, that one dispute has a
deadline — and writes the two sentences tying them together. That is genuinely the thing
rules cannot do, and it is the only thing asked of it.

FALLBACK IS THE DEFAULT PATH, NOT THE ERROR PATH. No key, no network, a timeout, an empty
reasoning-model response, or prose that fails the guard all produce the deterministic
summary instead. The demo runs on a laptop with no internet, exactly as before.
"""

from __future__ import annotations

import re

from finctl.explain.client import ExplainUnavailable, LLMConfig, complete
from finctl.money import format_rupees
from finctl.rank.ranker import Verdict

SYSTEM_PROMPT = """You write two sentences for an Indian merchant reading a payment \
reconciliation summary.

Rules, all of them absolute:
- NEVER write a number, an amount, a count, or a currency figure. Not in digits, not in \
words. The interface renders every figure itself; anything numeric you write is deleted \
before display and will leave a hole in your sentence.
- Only use facts given to you. Do not speculate about causes. If you are told a \
subscription was halted, do not guess why.
- Do not restate a line's mechanism in your own words. Reuse the wording you were given, \
or name the line and stop. A compressed explanation invents claims the engine never made.
- Plain English. No jargon the merchant has not already been shown, no greeting, no \
sign-off, no bullet points, no markdown.
- Two sentences. The first says what this week's money looks like; the second says what \
deserves attention and why.
- Address the merchant as "you". Be calm and specific, never alarming."""

# Anything a merchant could read as a quantity. Digits are the obvious case; number words
# are the one a model reaches for when told not to use digits ("six customers"), and a
# spelled-out amount is exactly as wrong as a written one.
_DIGITS = re.compile(r"\d")
_NUMBER_WORDS = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
    r"forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|lakh|lakhs|crore|"
    r"crores|million|billion)\b",
    re.IGNORECASE,
)


def has_numerals(text: str) -> bool:
    """Does this prose contain anything a merchant could read as a figure?"""
    return bool(_DIGITS.search(text) or _NUMBER_WORDS.search(text))


# A figure as it appears inside merchant-facing copy: an optional symbol, digits with
# separators, an optional trailing percent. "18%", "₹1,200", "2.15%".
_FIGURE_TOKEN = re.compile(r"[₹$]?\d[\d,.]*\s*%?")
_LOOSE_SPACE = re.compile(r"\s{2,}")
# Only the punctuation that must hug the word before it. An em dash takes its space.
_ORPHAN_PUNCT = re.compile(r"\s+([,.;:])")


def redact_figures(text: str) -> str:
    """Strip from prompt text anything `guard` would later reject.

    The prompt builders quote `line.explanation`, which is merchant-facing copy and
    carries a figure where a figure helps a human: "plus the 18% GST charged on that
    fee". Handing that to a model told never to write a number is an invitation to
    repeat the one it was just shown — and a repeated figure discards the WHOLE answer,
    so the copilot fell back to the template on precisely the question a merchant is
    most likely to ask.

    That was measured, not feared: before this existed, eleven of twelve fee questions
    returned the template while every other question returned model prose. The failure
    was invisible because the fallback is correct prose — the product looked like it had
    no model rather than like it had a bad prompt.

    So the screen keeps its figure and the model is never shown one. Feeding the model
    only what the guard would accept is the same rule stated once at each end, which is
    the point: a prompt that can trip its own guard is a prompt bug, not a model failure.
    """
    out = _NUMBER_WORDS.sub("", _FIGURE_TOKEN.sub("", text))
    out = _ORPHAN_PUNCT.sub(r"\1", _LOOSE_SPACE.sub(" ", out))
    return out.strip()


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def guard(text: str) -> str | None:
    """Return prose safe to display, or None if it must be discarded.

    A sentence containing a numeral is dropped whole rather than edited: deleting the
    digits from "you lost 4,200 rupees this week" leaves a sentence that still reads as a
    claim about an amount, and a mangled one. If nothing survives, the caller falls back
    to the template.
    """
    if not text:
        return None

    # Models occasionally wrap prose in quotes or a markdown fence despite instructions.
    cleaned = text.strip().strip("`").strip()
    if cleaned.startswith(('"', "'")) and cleaned.endswith(('"', "'")):
        cleaned = cleaned[1:-1].strip()

    # ONE numeral discards the WHOLE response. Not the offending sentence — all of it.
    #
    # Salvaging the clean half is the tempting behaviour and the wrong one. A model that
    # wrote "you are short ₹4,200" invented that figure, and the sentence beside it was
    # written in the belief that it was true: "act now" means something different after a
    # shortfall the engine never found. Keeping the remainder produces prose that reads
    # as though it followed from a number the merchant cannot see and that never existed.
    #
    # It is also the rule that is easy to reason about. "Any fabricated figure means the
    # response is discarded" is a sentence a reviewer can check against the code in one
    # pass; a partial-salvage heuristic needs a paragraph and still has edge cases. This
    # engine refuses to guess everywhere else, and a half-kept explanation is a guess
    # about which half was honest.
    #
    # The cost is nil: the template is always correct and always available.
    if has_numerals(cleaned):
        return None

    out = " ".join(_sentences(cleaned)[:3])
    if not out:
        return None
    # A model that ignored "two sentences" and wrote an essay is not following the brief;
    # the verdict screen has room for a short paragraph, not a report.
    if len(out) > 600:
        out = out[:600].rsplit(".", 1)[0] + "."
    return out or None


def _facts(verdict: Verdict) -> str:
    """The prompt's entire factual content, in words, with no figures.

    Amounts are described by their RANK rather than their value — "the largest line",
    "smaller than" — so the model has the shape of the week without ever seeing a number
    it could echo back. Nothing here is a judgement: every ordering is computed.
    """
    lines = sorted(verdict.lines, key=lambda line: -abs(line.amount_paise))
    if not lines:
        return "This batch has no discrepancies at all."

    # The DIRECTION of the gap, stated in words. Omitting it is how the model came to
    # write "you have a net gain this week" over a batch where the merchant received
    # ₹78,720 LESS than expected: given only line labels and rankings, it had no way to
    # know which way the money went, so it guessed. A fact the model needs and is not
    # given is a fact it will invent — the guard catches numbers, not wrong directions.
    if verdict.gap_paise > 0:
        direction = (
            "Your bank received LESS than your ledger expected. This is a shortfall, "
            "not a gain. Never describe this week as a gain or a surplus."
        )
    elif verdict.gap_paise < 0:
        direction = (
            "Your bank received MORE than your ledger expected. Never describe this "
            "week as a shortfall or a loss."
        )
    else:
        direction = "Your bank received exactly what your ledger expected."

    parts: list[str] = []
    for index, line in enumerate(lines):
        rank = "largest" if index == 0 else ("second largest" if index == 1 else "smaller")
        status = "needs action" if line.actionable else "needs no action"
        parts.append(
            f"- {redact_figures(line.label)} ({rank} line, {status}): "
            f"{redact_figures(line.explanation)}"
        )

    actionable = verdict.actionable_lines
    if actionable:
        top = max(actionable, key=lambda line: line.amount_paise)
        focus = f"The item that most deserves attention is: {top.label}."
    else:
        focus = "Nothing in this batch needs action."

    return "\n".join([
        direction,
        "",
        "The lines on this week's reconciliation, largest first:",
        *parts,
        "",
        focus,
    ])


def template(verdict: Verdict) -> str:
    """The deterministic explanation. Always available, and always correct.

    This is what shipped before there was a model, and it remains the fallback for every
    failure path. It states the shape of the week from the same verdict the screen
    renders, so it can never disagree with the figures beside it.
    """
    gap = format_rupees(abs(verdict.gap_paise))
    direction = "less than" if verdict.gap_paise > 0 else "more than"

    if not verdict.lines:
        return (
            f"Your bank received {gap} {direction} your ledger expected, and the engine "
            f"found nothing to explain it."
        )

    actionable = verdict.actionable_lines
    benign = [line for line in verdict.lines if not line.actionable]

    first = (
        f"Your bank received {gap} {direction} your ledger expected, "
        f"and every rupee of that difference is accounted for below."
    )

    if not actionable:
        return first + " None of it needs anything from you this week."

    top = max(actionable, key=lambda line: line.amount_paise)
    biggest = max(verdict.lines, key=lambda line: abs(line.amount_paise))

    # When the largest line IS the one that needs you, saying so twice in one sentence
    # produced "The largest line is no record at Razorpay at all and it needs you; what
    # needs you this week is no record at Razorpay at all." One clause, once.
    if biggest.classification is top.classification:
        second = f"The largest line is {top.label}, and it needs you this week."
    elif benign and biggest.actionable:
        second = f"What needs you this week is {top.label}."
    else:
        second = (
            f"The largest line is {biggest.label}"
            + (
                " and it resolves on its own"
                if not biggest.actionable
                else " and it needs you"
            )
            + f"; what needs you this week is {top.label}."
        )
    return f"{first} {second}"


def explain_detailed(
    verdict: Verdict, config: LLMConfig | None = None
) -> tuple[str, str, str]:
    """Explain this verdict. Returns `(prose, source, reason)`.

    `source` is "model" or "template". `reason` says WHY the template was used — "no_key",
    "disabled", "rate_limited", "timeout", "guarded", and so on — and is "model" when
    none was needed.

    The reason exists because every fallback path used to be silent and identical. A
    product serving template prose because it has no key and one serving template prose
    because it exceeded a token budget look the same on screen, and the second one had
    us reading a diff for a bug that was an HTTP 429. If the product cannot say which
    path produced the sentence, neither can the person operating it.
    """
    cfg = config if config is not None else LLMConfig.from_env()
    fallback = template(verdict)

    if not cfg.enabled:
        # "no_key" and "disabled" are both "there will be no model call", and they are
        # reported apart on purpose: one is a gap in the setup, the other is the setup.
        return fallback, "template", cfg.off_reason

    try:
        raw = complete(SYSTEM_PROMPT, _facts(verdict), cfg)
    except ExplainUnavailable as exc:
        # Deliberately swallowed. The caller wants a sentence, and the engine has one
        # that is always correct; a reconciliation summary must not fail to render
        # because an inference endpoint was slow. The reason is kept, not the exception.
        return fallback, "template", getattr(exc, "reason", "unavailable")

    safe = guard(raw)
    if safe is None:
        # The model wrote a figure and the guard did its job. This is the one fallback
        # that is a success rather than a fault, and it should not read as an outage.
        return fallback, "template", "guarded"
    return safe, "model", "model"


def explain(verdict: Verdict, config: LLMConfig | None = None) -> tuple[str, str]:
    """Explain this verdict. Returns `(prose, source)`.

    `source` is "model" or "template", and it is returned rather than hidden so the API
    and the audit log can record which path produced the sentence a merchant read. A
    product that cannot say whether a model wrote something is not one you can audit.

    Kept as the two-value form because that is what every caller and test already reads;
    `explain_detailed` is for the callers that also want to know why.
    """
    prose, source, _ = explain_detailed(verdict, config)
    return prose, source
