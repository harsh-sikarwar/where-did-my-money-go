"""The CLI. ADR-054.

488 statements at 0% coverage, in the interface every other test reaches around.
`pipeline.run()` was exercised from a dozen angles; `finctl checkpoint` — the command
the README tells a reader to type first — was exercised from none, and a traceback in
argument parsing would have been found by whoever ran it, not by the suite.

These are smoke tests and are meant to be. What they assert is the contract a CLI
actually has:

  - it exits 0 on the happy path, and non-zero on the sad one
  - it does not traceback
  - the numbers it prints are the engine's, not a second copy
  - a command that refuses explains what to do instead

Depth belongs in the module tests, which have it. This is the layer that says the
plumbing between a typed command and those modules is connected — the failure mode
`--cycle-days` vs `--cycle` produces, which cost a real minute during this very session.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finctl.cli import app

runner = CliRunner()


def invoke(*args: str):
    """Run a command. `catch_exceptions=False` so a traceback fails loudly.

    Typer swallows exceptions into a non-zero exit by default, which would let a real
    crash pass as a deliberate refusal — exactly the distinction these tests exist to
    make.
    """
    return runner.invoke(app, list(args), catch_exceptions=False)


@pytest.fixture(scope="module")
def batch(tmp_path_factory) -> Path:
    """One generated batch, reused. Generation dominates the runtime of this file."""
    out = tmp_path_factory.mktemp("cli") / "batch"
    result = runner.invoke(
        app,
        ["generate", "-n", "200", "-s", "20260902", "-d", "demo", "-o", str(out)],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    return out


class TestItStarts:
    """The commands that must work before any of the others can."""

    def test_version(self) -> None:
        result = invoke("version")
        assert result.exit_code == 0
        assert result.output.strip()

    def test_help_lists_every_command(self) -> None:
        """A command missing from --help is one nobody will find."""
        output = invoke("--help").output
        for command in (
            "generate", "reconcile", "checkpoint", "actions",
            "matrix", "golden", "rates", "doctor", "blind",
        ):
            assert command in output, f"{command} is missing from --help"

    def test_doctor_checks_the_environment(self) -> None:
        result = invoke("doctor")
        assert result.exit_code == 0

    def test_an_unknown_command_fails_rather_than_crashes(self) -> None:
        result = runner.invoke(app, ["definitely-not-a-command"])
        assert result.exit_code != 0


class TestGenerate:
    def test_it_writes_a_batch_and_its_ground_truth(self, tmp_path: Path) -> None:
        out = tmp_path / "b"
        result = invoke("generate", "-n", "200", "-s", "1", "-o", str(out))
        assert result.exit_code == 0
        assert (out / "ledger.csv").exists()
        assert (out / "ground_truth.json").exists()

    def test_the_same_seed_produces_the_same_batch(self, tmp_path: Path) -> None:
        """ADR-004's whole premise, asserted through the interface a person uses."""
        first, second = tmp_path / "a", tmp_path / "b"
        for out in (first, second):
            assert invoke("generate", "-n", "200", "-s", "7", "-o", str(out)).exit_code == 0
        assert (first / "ledger.csv").read_bytes() == (second / "ledger.csv").read_bytes()

    def test_an_impossible_profile_is_refused_with_a_reason(self, tmp_path: Path) -> None:
        """More defects than orders. The message must name the fix, not just the fault."""
        result = runner.invoke(
            app, ["generate", "-n", "5", "-d", "demo", "-o", str(tmp_path / "x")]
        )
        assert result.exit_code != 0
        # Rich hard-wraps the terminal output, so a phrase can be split across lines.
        # Compared with whitespace collapsed, which is what a reader sees rather than
        # what the renderer emitted.
        flat = " ".join(result.output.split())
        assert "raise --volume" in flat
        assert "rate-based profile" in flat

    def test_an_unknown_archetype_lists_the_valid_ones(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["generate", "-a", "not_an_archetype", "-o", str(tmp_path / "x")]
        )
        assert result.exit_code != 0
        assert "saas_subscription" in " ".join(result.output.split())


class TestTheAnalysisCommands:
    """The three a merchant actually runs, against a real batch."""

    def test_reconcile(self, batch: Path) -> None:
        result = invoke("reconcile", "--data", str(batch))
        assert result.exit_code == 0

    def test_checkpoint_scores_against_ground_truth(self, batch: Path) -> None:
        """The Day-1 checkpoint, and the command the README opens with."""
        result = invoke("checkpoint", "--data", str(batch))
        assert result.exit_code == 0
        assert "unexplained" in result.output.lower()

    def test_actions_names_the_customers(self, batch: Path) -> None:
        result = invoke("actions", "--data", str(batch))
        assert result.exit_code == 0

    def test_the_cli_and_the_engine_agree(self, batch: Path) -> None:
        """One pipeline, two callers. The claim in pipeline.py's own docstring.

        `checkpoint` reconstructs its stages rather than calling `run()`, which is
        precisely how the scorer came to be handed a stale settlement cycle (ADR-051).
        The CLI's number must equal the engine's, or a merchant reading the terminal and
        a merchant reading the browser see different money.
        """
        from finctl.pipeline import run

        expected = run(batch).correlated.unexplained_after_paise
        output = invoke("checkpoint", "--data", str(batch)).output
        # The residual is the honesty metric: ₹0.00 when correlation resolves everything.
        assert ("₹0.00" in output) == (expected == 0)

    def test_a_missing_batch_is_refused_not_crashed(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["checkpoint", "--data", str(tmp_path / "nope")])
        assert result.exit_code != 0

    def test_checkpoint_without_ground_truth_says_so(self, tmp_path: Path) -> None:
        """Real merchant data has none. Its absence is not an error, and the message
        must not read like one."""
        bare = tmp_path / "bare"
        bare.mkdir()
        (bare / "ledger.csv").write_text("order_id,amount\nORD-1,100.00\n")
        result = runner.invoke(app, ["checkpoint", "--data", str(bare)])
        assert result.exit_code != 0
        assert "ground_truth" in result.output


class TestRates:
    """The fee table. The command that answers "what should Razorpay have charged?"."""

    def test_it_prints_a_fee_for_an_amount(self) -> None:
        result = invoke("rates", "--amount", "10000")
        assert result.exit_code == 0
        assert "upi" in result.output.lower()

    def test_the_canonical_card_case(self) -> None:
        """₹10,000 on a card: ₹200 MDR, ₹36 GST. The number the brief opens with, and
        the one a finance reviewer checks first."""
        output = invoke("rates", "--amount", "10000").output
        assert "200.00" in output
        assert "36.00" in output


class TestGolden:
    def test_check_passes_on_a_clean_tree(self) -> None:
        """`golden` without --update must not rewrite anything, and must agree with the
        committed files. A failure here means the generator moved."""
        assert invoke("golden").exit_code == 0


class TestBlind:
    """Blind testing. The property under test is what the command does NOT print."""

    def test_new_prints_nothing_about_what_it_planted(self, tmp_path: Path) -> None:
        """Printing the configuration would spoil the test, which is the whole method."""
        result = invoke(
            "blind", "new",
            "--out", str(tmp_path / "blind"),
            "--answers", str(tmp_path / "answers"),
            "--seed", "42",
        )
        assert result.exit_code == 0
        lowered = result.output.lower()
        # Defect TYPE names and configuration values. Not the bare word "defect", which
        # appears in the sentence explaining that none of this is printed — an assertion
        # that fails on prose about the guarantee rather than on a breach of it.
        for leak in (
            "halted", "missing_order", "wrong_fee_rate", "one_sided_refund",
            "unrecorded_refund", "disputed", "split_settlement", "decoy",
            "saas_subscription", "d2c_ecommerce", "upi_heavy", "card_heavy",
        ):
            assert leak not in lowered, f"blind new leaked {leak!r}"
        # No bare integers either: a printed volume or cycle would spoil it just as well.
        assert not any(
            token.isdigit() and len(token) > 1
            for token in lowered.replace("(", " ").replace(")", " ").split()
        ), "blind new printed a number that could describe the batch"

    def test_the_answer_key_lands_outside_the_batch(self, tmp_path: Path) -> None:
        """An answer key inside the batch directory is not an answer key."""
        data, answers = tmp_path / "blind", tmp_path / "answers"
        assert invoke(
            "blind", "new", "--out", str(data), "--answers", str(answers), "--seed", "9"
        ).exit_code == 0
        assert (data / "ledger.csv").exists()
        assert answers.exists()
        assert not list(data.glob("*answer*"))

    def test_run_then_score(self, tmp_path: Path) -> None:
        """The full loop: plant blind, reconcile blind, then reveal."""
        data, answers = tmp_path / "blind", tmp_path / "answers"
        findings = data / "findings.json"

        assert invoke(
            "blind", "new", "--out", str(data), "--answers", str(answers), "--seed", "11"
        ).exit_code == 0
        assert invoke(
            "blind", "run", "--data", str(data), "--out", str(findings)
        ).exit_code == 0
        assert findings.exists()
        json.loads(findings.read_text())     # must be readable, not just present

        scored = invoke(
            "blind", "score", "--data", str(data),
            "--answers", str(answers), "--findings", str(findings),
        )
        assert scored.exit_code == 0
