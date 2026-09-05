"""Command-line entry point.

Deliberately the only user interface until the Day-1 checkpoint passes.
The FastAPI layer added later is a thin wrapper over these same calls.
"""

import contextlib
import platform
import sys

import typer
from rich.console import Console
from rich.table import Table

from finctl import __version__

# The explanation layer reads its key from the environment, and a key kept in the repo's
# .env never reached it: the CLI is usually the first place this project is run, and it
# was the one place that silently ran without a model. Guarded, because the engine
# installs with zero LLM dependencies by design (ADR-001) and must still start when
# dotenv is absent. `override=False`: an exported key outranks the file.
with contextlib.suppress(ImportError):
    from pathlib import Path as _Path

    from dotenv import load_dotenv

    load_dotenv(_Path(__file__).resolve().parents[2] / ".env", override=False)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Where did my money go? — settlement reconciliation with failure correlation.",
)
console = Console()


@app.callback()
def main(
    no_llm: bool = typer.Option(
        False,
        "--no-llm",
        help="Run with the language model switched off. Every command is deterministic.",
    ),
) -> None:
    """Global options.

    `--no-llm` is a real switch, not a reassurance. It sets `FINCTL_NO_LLM` for this
    process, and `LLMConfig.from_env` is the only place in the project that decides
    whether a model gets called — so throwing it here closes every path at once,
    including the one the API server takes when it is started through this CLI.

    Worth being precise about what it changes, because the honest answer is "less than
    you would expect": no command in this CLI has ever called a model. Matching, fee
    arithmetic, classification and correlation are all deterministic, and the engine
    installs with zero LLM dependencies (ADR-001). The model writes prose on the web
    UI's summary and chat, and nothing else. `--no-llm` makes that verifiable rather
    than merely claimed — run `finctl --no-llm doctor` and it says so.
    """
    if no_llm:
        import os

        from finctl.explain.client import NO_LLM_ENV

        os.environ[NO_LLM_ENV] = "1"


class _Refuse(contextlib.AbstractContextManager):
    """Turn the engine's own errors into something a merchant can act on.

    The engine's messages are written to be read: "unknown archetype 'x'. Known:
    ['d2c_ecommerce', 'saas_subscription']" and "defect profile 'demo' demands 34 defects
    but the batch has only 5 orders … Either raise --volume or use a rate-based profile".
    Both were reaching the terminal wrapped in eighteen lines of Rich traceback, with the
    useful sentence last — so the CLI was taking the single best thing about this engine's
    error handling and burying it under a stack dump.

    A traceback is the right output for a bug and the wrong one for a refusal. This
    prints the message, exits non-zero, and keeps the frames for genuinely unexpected
    exceptions, which still raise. ADR-054.
    """

    # Errors that mean "you asked for something impossible", not "the engine broke".
    # Deliberately narrow: anything not listed here keeps its traceback, because a
    # blanket `except Exception` would hide the next real bug behind a tidy one-liner.
    def __exit__(self, exc_type, exc, tb) -> bool:
        from finctl.config.loader import ConfigError
        from finctl.money import MoneyError
        from finctl.normalize.normalizer import NormalizationError

        if exc_type is None:
            return False
        if not issubclass(exc_type, ConfigError | MoneyError | NormalizationError | ValueError):
            return False
        # A ValueError from deep in the engine is a refusal; one from argument parsing
        # is Typer's own business and never reaches here.
        console.print(f"\n[red]{exc}[/red]\n")
        raise typer.Exit(1) from None


@app.command()
def version() -> None:
    """Print the engine version."""
    console.print(f"finctl {__version__}")


@app.command()
def doctor() -> None:
    """Check that the engine's environment is sane.

    Run this first when something behaves oddly. Cheaper than guessing.
    """
    table = Table(title="finctl doctor", show_header=True, header_style="bold")
    table.add_column("check")
    table.add_column("value")

    table.add_row("finctl", __version__)
    table.add_row("python", sys.version.split()[0])
    table.add_row("platform", platform.platform())

    for mod in ("pandas", "pydantic", "yaml", "typer", "rich"):
        try:
            m = __import__(mod)
            table.add_row(mod, getattr(m, "__version__", "?"))
        except ImportError:
            table.add_row(mod, "[red]MISSING[/red]")

    # The model's state, in the one command whose whole job is answering "what is this
    # process actually configured to do". A key present in .env and a key being used are
    # different facts, and the difference is exactly what --no-llm changes.
    from finctl.explain.client import NO_LLM_ENV, LLMConfig

    cfg = LLMConfig.from_env()
    if cfg.disabled:
        state = f"[yellow]off[/yellow]  [dim](--no-llm / {NO_LLM_ENV})[/dim]"
    elif cfg.enabled:
        state = f"[green]on[/green]  [dim]{cfg.model}[/dim]"
    else:
        state = "[yellow]off[/yellow]  [dim](no key configured)[/dim]"
    table.add_row("llm", state)
    table.add_row(
        "llm used by",
        "[dim]web summary + chat prose only; no CLI command calls a model[/dim]",
    )

    console.print(table)


@app.command()
def probe(
    live: bool = typer.Option(
        False, "--live", help="Call Razorpay test mode and overwrite fixtures (Day-2 task)."
    ),
) -> None:
    """Inspect Razorpay's real response shapes (ADR-006: verification, not foundation).

    Without --live this reads the committed fixtures: no network, no credentials.
    """
    from finctl.probe import (
        FIXTURE_DIR,
        analyse_fee_convention,
        capture_live,
        diff_shapes,
        field_inventory,
        load_fixture,
        write_capture,
    )

    if live:
        _run_live_capture(capture_live, write_capture, diff_shapes, load_fixture)

    for name in ("settlement_recon", "payment_failed", "subscription_halted"):
        fixture = load_fixture(name)
        prov = fixture.get("_provenance", {})
        status = prov.get("status", "unknown")
        colour = "green" if prov.get("live_capture") else "yellow"

        console.print(f"[bold]{name}[/bold]  [{colour}]{status}[/{colour}]  ({fixture.get('count', 0)} items)")

        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("field")
        table.add_column("type")
        table.add_column("null?")
        table.add_column("example", overflow="ellipsis", max_width=34)

        for field, info in sorted(field_inventory(fixture).items()):
            example = info["examples"][0] if info["examples"] else ""
            table.add_row(
                field,
                "|".join(info["types"]) or "—",
                "[red]yes[/red]" if info["nullable"] else "no",
                str(example),
            )
        console.print(table)
        console.print()

    console.print("[bold]Fee/tax convention (ADR-007)[/bold]")
    analysis = analyse_fee_convention(load_fixture("settlement_recon"))
    console.print(f"  verdict: [bold]{analysis['verdict']}[/bold]")
    for key in ("gst_inclusive_rows", "mdr_only_rows", "ambiguous_rows", "inconsistent_rows"):
        if analysis[key]:
            console.print(f"  {key}: {', '.join(analysis[key])}")

    console.print()
    console.print(f"[dim]Fixtures: {FIXTURE_DIR}[/dim]")
    if not live:
        console.print(
            "[dim]Reading committed fixtures only. Re-run with --live to capture from "
            "Razorpay test mode — see PROVENANCE.md.[/dim]"
        )


def _run_live_capture(capture_live, write_capture, diff_shapes, load_fixture) -> None:
    """Capture from Razorpay test mode, write fixtures, and report every divergence.

    Kept out of `probe` so the offline path stays readable and importable without any
    of this ever being reached.
    """
    console.print("[bold]Live capture[/bold] — Razorpay test mode (ADR-006: verification)")
    console.print()

    # Snapshot the documented shapes BEFORE anything is overwritten; they are the
    # baseline the live capture is diffed against.
    documented = {}
    for name in ("settlement_recon", "payment_failed", "subscription_halted"):
        try:
            documented[name] = load_fixture(name)
        except FileNotFoundError:
            documented[name] = None

    results = capture_live()

    for name, result in results.items():
        if "error" in result:
            console.print(
                f"[red]FAILED[/red] {name}: {result['endpoint']} "
                f"{result['params']} → {result['error']}"
            )
            console.print(f"  [dim]{result['body']}[/dim]")
            continue

        payload = result["payload"]
        items = payload.get("items", [])
        # An empty collection carries no item shape. Overwriting a documented fixture
        # with one would delete the contract and replace it with nothing.
        preserve = not items and documented.get(name) is not None
        path = write_capture(name, result, preserve_documented=True)

        verb = "wrote" if not preserve else "wrote (documented fixture PRESERVED)"
        console.print(f"[green]OK[/green] {name}: {len(items)} items — {verb} {path.name}")

        if preserve:
            console.print(
                "  [yellow]empty collection[/yellow] — the account holds no data of this "
                "kind, so no shape diff is possible."
            )
        elif documented.get(name):
            diff = diff_shapes(documented[name], payload)
            if any(diff.values()):
                console.print("  [yellow]DIVERGENCE from documented shape:[/yellow]")
                for field in diff["only_documented"]:
                    console.print(f"    - {field}: in docs, ABSENT live")
                for field in diff["only_live"]:
                    console.print(f"    + {field}: live only, NOT in docs")
                for change in diff["changed"]:
                    console.print(
                        f"    ~ {change['field']}: docs {change['documented']} "
                        f"vs live {change['live']}"
                    )
            else:
                console.print("  [dim]no divergence from documented shape[/dim]")

    console.print()


if __name__ == "__main__":
    app()


@app.command()
def rates(
    amount: str = typer.Option("10000", "--amount", "-a", help="Transaction amount in RUPEES."),
) -> None:
    """Show the contracted fee for one amount across every payment method.

    Answers 'what about a UPI-heavy merchant?' in one command, with the arithmetic.
    """
    from finctl.config.loader import load_config
    from finctl.fees import expected_fee
    from finctl.money import format_rupees, parse_money

    cfg = load_config()
    amount_paise = parse_money(amount)

    console.print(
        f"[bold]{cfg.rate_card.name}[/bold] — fee on {format_rupees(amount_paise)}"
    )
    console.print(
        f"[dim]GST {cfg.rate_card.gst_rate_bps / 100:.0f}% on the MDR "
        f"(never on the amount) · rounding {cfg.rate_card.rounding_mode}[/dim]\n"
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("method")
    table.add_column("MDR", justify="right")
    table.add_column("MDR ₹", justify="right")
    table.add_column("GST on MDR ₹", justify="right")
    table.add_column("total fee ₹", justify="right")
    table.add_column("net to bank ₹", justify="right")

    for method in sorted(cfg.rate_card.methods):
        fee = expected_fee(amount_paise, method, cfg.rate_card)
        zero = fee.total_fee_paise == 0
        style = "green" if zero else ""
        table.add_row(
            f"[{style}]{method}[/{style}]" if style else method,
            f"{fee.mdr_bps / 100:.2f}%",
            format_rupees(fee.mdr_paise, symbol=False),
            format_rupees(fee.gst_paise, symbol=False),
            format_rupees(fee.total_fee_paise, symbol=False),
            format_rupees(fee.net_paise, symbol=False),
        )
    console.print(table)
    console.print("\n[dim]UPI is zero-MDR by mandate — that is a rate-card row, not a special case.[/dim]")


@app.command()
def generate(
    volume: int = typer.Option(200, "--volume", "-n", help="Number of orders."),
    archetype: str = typer.Option("saas_subscription", "--archetype", "-a"),
    mix: str = typer.Option(None, "--mix", "-m", help="Override the archetype's payment mix."),
    cycle: int = typer.Option(None, "--cycle", "-c", help="Settlement cycle, the N in T+N."),
    defects: str = typer.Option("demo", "--defects", "-d", help="Defect profile."),
    seed: int = typer.Option(20260902, "--seed", "-s"),
    out: str = typer.Option("data/batch", "--out", "-o", help="Output directory."),
) -> None:
    """Generate a seeded batch of Razorpay-shaped data plus its ground truth."""
    import time as _time
    from pathlib import Path

    from finctl.config.loader import load_config
    from finctl.generate.generator import Generator
    from finctl.generate.writer import write_batch
    from finctl.money import format_rupees

    cfg = load_config()
    started = _time.perf_counter()
    # An unknown archetype and an over-subscribed defect profile are both REFUSALS with
    # messages that name the fix. Without this they arrived as tracebacks.
    with _Refuse():
        batch = Generator(
            cfg,
            seed=seed,
            archetype=archetype,
            payment_mix=mix,
            volume=volume,
            settlement_cycle_days=cycle,
            defect_profile=defects,
        ).generate()
    elapsed = _time.perf_counter() - started

    write_batch(batch, Path(out))
    gt = batch.ground_truth
    assert gt is not None

    console.print(
        f"[bold]{volume}[/bold] orders · {archetype} · mix {gt.payment_mix} · "
        f"T+{gt.settlement_cycle_days} · defects [bold]{defects}[/bold] · seed {seed}"
    )
    console.print(
        f"[dim]{elapsed:.3f}s · {volume / elapsed:,.0f} orders/sec[/dim]\n"
    )

    counts = Table(show_header=True, header_style="bold", box=None)
    counts.add_column("file")
    counts.add_column("rows", justify="right")
    for name, key in (
        ("ledger.csv", "ledger"), ("bank.csv", "bank"), ("settlement_recon.json", "recon"),
        ("payments.json", "payments"), ("subscriptions.json", "subscriptions"),
    ):
        counts.add_row(name, f"{len(getattr(batch, key)):,}")
    console.print(counts)

    console.print(f"\n[bold]Planted defects[/bold] — {len(gt.real_defects)} total")
    table = Table(show_header=True, header_style="bold")
    table.add_column("defect")
    table.add_column("rows", justify="right")
    table.add_column("impact", justify="right")
    for defect_type, impact in sorted(gt.impact_by_type().items(), key=lambda kv: -kv[1]):
        table.add_row(defect_type, str(len(gt.by_type(defect_type))), format_rupees(impact))
    console.print(table)

    console.print(f"\n[dim]written to {out}/[/dim]")
    console.print(f"[dim]gross {format_rupees(gt.total_gross_paise)} · "
                  f"expected fees {format_rupees(gt.total_expected_fee_paise)}[/dim]")


@app.command()
def golden(
    update: bool = typer.Option(False, "--update", help="Rewrite the golden files."),
) -> None:
    """Check or regenerate the golden files.

    Only pass --update after reading the diff and confirming every changed line moved
    for a reason you can name. Regenerating to turn a test green discards the finding.
    """
    import json

    from tests.test_golden import CASES, GOLDEN_DIR, generate_case

    if not update:
        console.print("[dim]Run `uv run pytest tests/test_golden.py` to check.[/dim]")
        console.print("[dim]Pass --update to rewrite — after reading the diff.[/dim]")
        return

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for name in sorted(CASES):
        path = GOLDEN_DIR / f"{name}.json"
        existed = path.exists()
        path.write_text(json.dumps(generate_case(name), indent=2, sort_keys=True))
        console.print(f"  {'updated' if existed else 'created'} {path.name}")
    console.print(f"\n[bold]{len(CASES)}[/bold] golden files written.")


@app.command()
def reconcile(
    data: str = typer.Option("data/demo", "--data", "-D", help="Batch directory."),
) -> None:
    """Run the two-pass matcher over a staged batch and report match rates."""
    import time as _time
    from pathlib import Path

    from finctl.match.matcher import match
    from finctl.money import format_rupees
    from finctl.stage.staging import stage_from_dir

    started = _time.perf_counter()
    batch = stage_from_dir(Path(data))
    result = match(batch)
    elapsed = _time.perf_counter() - started

    manifest = batch.manifest()
    console.print(f"[bold]batch {manifest['batch_id']}[/bold]  [dim]{data}[/dim]")
    ingest = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    ingest.add_column("source")
    ingest.add_column("rows", justify="right")
    ingest.add_column("sha256")
    for name, info in manifest["sources"].items():
        ingest.add_row(name, f"{info['rows']:,}", info["sha256"][:12])
    console.print(ingest)

    s = result.summary()
    console.print()
    for key in ("pass1", "pass2"):
        p = s[key]
        rate = p["match_rate"] * 100
        colour = "green" if rate >= 95 else "yellow" if rate >= 60 else "red"
        console.print(
            f"[bold]{p['leg']}[/bold]  [dim]{p['question']}[/dim]\n"
            f"  matched [bold {colour}]{p['matched']:,}/{p['total']:,}[/bold {colour}]"
            f"  ([{colour}]{rate:.1f}%[/{colour}])"
            f"  unmatched {p['unmatched']:,}"
        )

    money = s["money"]
    console.print()
    console.print(
        f"Expected [bold]{format_rupees(money['expected_paise'])}[/bold] · "
        f"Received [bold]{format_rupees(money['received_paise'])}[/bold] · "
        f"Gap [bold yellow]{format_rupees(money['gap_paise'])}[/bold yellow]"
    )

    anomalies = {k: v for k, v in s["anomalies"].items() if v}
    if anomalies:
        console.print("\n[bold]Anomalies[/bold]")
        for key, value in anomalies.items():
            console.print(f"  {key}: {value if not isinstance(value, dict) else len(value)}")

    # ---- classify -------------------------------------------------------
    from finctl.classify.classifier import Classification, Classifier
    from finctl.config.loader import load_config
    from finctl.correlate.correlator import Correlator

    cfg = load_config()
    classified = Classifier(cfg).classify(result)

    console.print("\n[bold]Classification[/bold]  [dim]deterministic, proof on every row[/dim]")
    ctable = Table(show_header=True, header_style="bold")
    ctable.add_column("classification")
    ctable.add_column("rows", justify="right")
    ctable.add_column("amount", justify="right")
    for name, info in classified.summary().items():
        style = "dim" if name == "RECONCILED" else ""
        label = f"[{style}]{name}[/{style}]" if style else name
        ctable.add_row(label, f"{info['count']:,}", format_rupees(info["paise"]))
    console.print(ctable)

    # ---- correlate — the differentiator ----------------------------------
    correlated = Correlator(batch).correlate(classified)
    c = correlated.summary()

    console.print("\n[bold]Correlation[/bold]  [dim]unexplained rows -> payment status / subscriptions[/dim]")
    before = c["unexplained_before_paise"]
    after = c["unexplained_after_paise"]
    console.print(
        f"  unexplained BEFORE  [bold yellow]{format_rupees(before)}[/bold yellow]\n"
        f"  unexplained AFTER   [bold green]{format_rupees(after)}[/bold green]\n"
        f"  resolved            [bold]{format_rupees(c['resolved_paise'])}[/bold]"
        f"  ({c['gain_ratio'] * 100:.1f}% of the residual, {c['resolved_count']} rows)"
    )

    if c["resolved_by_class"]:
        console.print()
        for name, info in c["resolved_by_class"].items():
            console.print(f"    {name}: {info['count']} rows · {format_rupees(info['paise'])}")

    if correlated.still_unexplained:
        console.print(
            f"\n  [dim]{len(correlated.still_unexplained)} rows remain unexplained — "
            f"the honest residual[/dim]"
        )

    # ---- the four lines ---------------------------------------------------
    console.print("\n[bold]────────────  the verdict  ────────────[/bold]\n")
    console.print(
        f"Expected [bold]{format_rupees(money['expected_paise'])}[/bold] · "
        f"Received [bold]{format_rupees(money['received_paise'])}[/bold] · "
        f"Gap [bold]{format_rupees(money['gap_paise'])}[/bold]\n"
    )

    lines = [
        (Classification.TIMING, "not missing, just late", False),
        (Classification.FEE, "Razorpay's cut + tax on it", False),
        (Classification.REFUND, "refunds recorded on one side only", False),
        (Classification.HALTED_SUBSCRIPTION, "subscriptions died silently — recoverable", True),
        (Classification.PAYMENT_FAILED, "payments that failed", True),
    ]
    for classification, blurb, actionable in lines:
        rows = correlated.by_class(classification)
        if not rows:
            continue
        total = sum(f.amount_paise for f in rows)
        marker = "[yellow]⚠[/yellow]" if actionable else "→"
        console.print(
            f"  {marker} [bold]{format_rupees(total):>14}[/bold]  "
            f"{len(rows)} {blurb}"
        )

    console.print(
        f"    [dim]{format_rupees(after):>14}  we can't explain[/dim]"
    )

    actionable_rows = [
        f for f in correlated.findings
        if f.classification in (Classification.HALTED_SUBSCRIPTION,)
    ]
    if actionable_rows:
        customers = {
            f.proof.get("correlation", {}).get("customer_id") for f in actionable_rows
        }
        console.print(
            f"\n  [bold]→ One thing needs you this week:[/bold] "
            f"those {len(customers - {None}) or len(actionable_rows)} customers."
        )

    # Write the audit log beside the batch. From the working practices: "you'll debug
    # with it at 11pm" — which means it must land on disk without being asked for.
    from finctl.pipeline import run as run_pipeline

    audit_path = run_pipeline(Path(data), cfg).audit.write(Path(data) / "audit.jsonl")

    total_rows = sum(i["rows"] for i in manifest["sources"].values())
    console.print(
        f"\n[dim]{elapsed:.3f}s · {total_rows / elapsed:,.0f} rows/sec"
        f" · matching is identifier-based only, never fuzzy[/dim]"
    )
    console.print(f"[dim]audit trail → {audit_path}[/dim]")


@app.command()
def actions(
    data: str = typer.Option("data/demo", "--data", "-D", help="Batch directory."),
    csv_out: str = typer.Option(
        "", "--csv", help="Write the list to this path instead of printing it."
    ),
) -> None:
    """Who to chase, for how much, and why.

    The verdict says "those 6 customers"; this names them. ADR-001 says anything the UI
    can do the CLI must do first — and a CSV a merchant can open is the point of the
    feature, not a nicety, so it belongs here rather than only behind HTTP. See ADR-048.
    """
    from pathlib import Path

    from finctl.actions import to_csv
    from finctl.money import format_rupees
    from finctl.pipeline import run

    result = run(Path(data))
    groups = result.actions

    if csv_out:
        target = Path(csv_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(to_csv(groups))
        rows = sum(len(g.items) for g in groups)
        console.print(f"[green]wrote {rows} rows[/green] [dim]{target}[/dim]")
        return

    console.print(f"[bold]{result.verdict.headline()}[/bold]\n")

    if not groups:
        console.print("[dim]Nothing needs you.[/dim]")
        return

    for group in groups:
        console.print(
            f"[bold]{group.classification}[/bold] "
            f"[dim]{len(group.items)} · {format_rupees(group.total_paise)}[/dim]"
        )
        console.print(f"  [italic]{group.next_step}[/italic]")

        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("order")
        table.add_column("amount", justify="right")
        table.add_column("customer")
        table.add_column("why")
        for item in group.items:
            table.add_row(
                item.order_id or "—",
                item.amount_display,
                item.email or item.customer_id or "—",
                item.reason or "—",
            )
        console.print(table)
        console.print()


@app.command()
def checkpoint(
    data: str = typer.Option("data/demo", "--data", "-D", help="Batch directory."),
) -> None:
    """Score the engine against ground truth. The Day-1 checkpoint.

    Prints unexplained-before vs unexplained-after, plus the honest caught/missed list.
    """
    from pathlib import Path

    from finctl.classify.classifier import Classifier
    from finctl.config.loader import load_config
    from finctl.correlate.correlator import Correlator
    from finctl.fingerprint import fingerprint
    from finctl.generate.ground_truth import GroundTruth
    from finctl.match.matcher import match
    from finctl.money import format_rupees
    from finctl.score import score
    from finctl.stage.staging import stage_from_dir

    d = Path(data)
    gt_path = d / "ground_truth.json"
    if not gt_path.exists():
        console.print(f"[red]no ground_truth.json in {data}[/red] — generate a batch first.")
        raise typer.Exit(1)

    cfg = load_config()
    batch = stage_from_dir(d)
    matches = match(batch)
    # Keep the classifier: it holds the settlement cycle it actually judged against, and
    # the scorer needs the same number or it grades against a baseline nothing used.
    # See ADR-051.
    classifier = Classifier(cfg)
    classified = classifier.classify(matches)
    correlated = Correlator(batch).correlate(classified)
    report = score(
        GroundTruth.read(gt_path), correlated, matches, cfg,
        cycle_days=classifier.cycle_days,
    )

    before = report.unexplained_before_paise
    after = report.unexplained_after_paise

    console.print("[bold]════════  CORRELATION: the checkpoint  ════════[/bold]\n")
    console.print(
        f"  unexplained BEFORE   [bold yellow]{format_rupees(before):>16}[/bold yellow]\n"
        f"  unexplained AFTER    [bold green]{format_rupees(after):>16}[/bold green]\n"
        f"  resolved by joining  [bold]{format_rupees(before - after):>16}[/bold]"
    )
    moved = before != after
    console.print(
        f"\n  {'[bold green]✓ the number moved[/bold green]' if moved else '[bold red]✗ NO MOVEMENT[/bold red]'}"
        f"  [dim]({correlated.gain_ratio * 100:.1f}% of the residual resolved)[/dim]"
    )

    console.print("\n[bold]Seeded defects — caught / missed[/bold]  [dim]the honest list[/dim]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("defect")
    table.add_column("caught", justify="right")
    table.add_column("missed", justify="right")
    table.add_column("below tol.", justify="right")
    # Strict leads. The lenient figure drops `below_tolerance` from its denominator,
    # which cannot fall below 100% on any run whose only misses are sub-threshold — it
    # read 100% on a run that found 612 of 849 planted defects.
    table.add_column("recall", justify="right")
    table.add_column("of scoreable", justify="right")
    for name, s in sorted(report.by_type.items()):
        colour = "green" if not s.missed else "red"
        table.add_row(
            name, str(len(s.caught)),
            f"[{colour}]{len(s.missed)}[/{colour}]" if s.missed else "0",
            f"[dim]{len(s.below_tolerance)}[/dim]" if s.below_tolerance else "0",
            f"[{colour}]{s.recall_strict * 100:.0f}%[/{colour}]",
            f"[dim]{s.recall * 100:.0f}%[/dim]",
        )
    console.print(table)

    console.print(
        f"\n  overall recall [bold]{report.recall_strict * 100:.1f}%[/bold]"
        f"  ({report.total_caught} caught of {report.total_planted} planted, "
        f"{report.total_missed} missed, "
        f"{report.total_below_tolerance} below tolerance)"
    )
    if report.total_below_tolerance:
        console.print(
            f"  [dim]{report.recall * 100:.1f}% of the defects config asks us to "
            f"report — the rest settled within the {report.tolerance_grace_days}-day "
            "grace window and are not defects by policy[/dim]"
        )
    if report.false_positives:
        console.print(
            f"  [red]{len(report.false_positives)} false positives[/red] — "
            "orders flagged that were never planted as defects"
        )
    else:
        console.print("  [green]0 false positives[/green]")

    if report.total_below_tolerance:
        console.print(
            "\n[dim]'below tolerance' = planted, not flagged, because config says it is not\n"
            "a defect (e.g. a 1-day timing lag inside grace_days). Not a miss.[/dim]"
        )

    # The claims of this run, reduced to sixteen characters a reader can compare.
    # Printed rather than hidden behind a flag: a determinism claim nobody is shown is
    # a determinism claim nobody checks.
    claims = {
        "unexplained_before_paise": before,
        "unexplained_after_paise": after,
        "total_planted": report.total_planted,
        "total_caught": report.total_caught,
        "total_missed": report.total_missed,
        "total_below_tolerance": report.total_below_tolerance,
        "false_positives": len(report.false_positives),
        "by_type": {
            name: {
                "caught": len(st.caught),
                "missed": len(st.missed),
                "below_tolerance": len(st.below_tolerance),
            }
            for name, st in sorted(report.by_type.items())
        },
    }
    console.print(
        f"\n  metrics fingerprint  [bold]{fingerprint(claims)}[/bold]"
        "  [dim]same batch, same engine → same sixteen characters[/dim]"
    )


@app.command()
def matrix(
    out: str = typer.Option("data/matrix", "--out", "-o", help="Where to write batches."),
    results: str = typer.Option("../docs/matrix-results.json", "--results"),
    quick: bool = typer.Option(False, "--quick", help="Skip the 50k tier."),
) -> None:
    """Run the test-day matrix and emit the metrics table.

    Every number in the submission's metrics section comes from here, so it is
    reproducible by re-running one command rather than reconstructed from notes.
    """
    from pathlib import Path

    from finctl.fingerprint import fingerprint
    from finctl.matrix import default_matrix, run_matrix, write_results
    from finctl.money import format_rupees

    cells = default_matrix()
    if quick:
        cells = [c for c in cells if c["volume"] < 50_000]

    console.print(f"[bold]{len(cells)} runs[/bold]  [dim]volume × archetype × mix × cycle[/dim]\n")

    def report(r) -> None:
        if r.error:
            console.print(f"  [yellow]skipped[/yellow] {r.archetype[:4]}/{r.payment_mix}/{r.volume}: {r.error[:60]}")
            return
        flag = "" if r.balances else " [red]DOES NOT BALANCE[/red]"
        miss = f" [red]{r.defects_missed} missed[/red]" if r.defects_missed else ""
        fp = f" [red]{r.false_positives} fp[/red]" if r.false_positives else ""
        console.print(
            f"  {r.archetype[:4]}/{r.payment_mix:<10}/{r.volume:>6}/T+{r.cycle_days} "
            f"[dim]{r.defect_profile:<6}[/dim] "
            f"match {r.match_rate_pass1 * 100:>5.1f}%  "
            f"recall {r.recall_strict * 100:>5.1f}%  "
            f"{r.rows_per_second:>7,}/s{miss}{fp}{flag}"
        )

    rows = run_matrix(Path(out), cells, on_result=report)
    path = write_results(rows, Path(results))

    ok = [r for r in rows if not r.error]
    console.print("\n[bold]Throughput[/bold]  [dim]engine only, excludes generation[/dim]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("volume", justify="right")
    table.add_column("rows", justify="right")
    table.add_column("seconds", justify="right")
    table.add_column("rows/sec", justify="right")
    for r in sorted({r.volume for r in ok}):
        cell = max((x for x in ok if x.volume == r), key=lambda x: x.rows)
        table.add_row(f"{r:,}", f"{cell.rows:,}", f"{cell.seconds:.3f}", f"{cell.rows_per_second:,}")
    console.print(table)

    console.print("\n[bold]Correlation gain by archetype[/bold]  [dim]the headline claim[/dim]")
    for archetype in sorted({r.archetype for r in ok}):
        cells_a = [r for r in ok if r.archetype == archetype and r.defect_profile == "demo"]
        if not cells_a:
            continue
        before = sum(r.unexplained_before_paise for r in cells_a)
        after = sum(r.unexplained_after_paise for r in cells_a)
        gain = (before - after) / before if before else 0.0
        console.print(
            f"  {archetype:<20} {format_rupees(before):>14} → {format_rupees(after):>12}"
            f"  ({gain * 100:.1f}% resolved)"
        )

    missed = sum(r.defects_missed for r in ok)
    fps = sum(r.false_positives for r in ok)
    unbalanced = [r for r in ok if not r.balances]

    console.print(f"\n[bold]Across {len(ok)} runs[/bold]")
    console.print(f"  defects missed:  {'[green]0[/green]' if not missed else f'[red]{missed}[/red]'}")
    console.print(f"  false positives: {'[green]0[/green]' if not fps else f'[red]{fps}[/red]'}")
    console.print(
        "  balance identity: "
        + ("[green]holds in every run[/green]" if not unbalanced
           else f"[red]FAILS in {len(unbalanced)} runs[/red]")
    )
    # Over the claims of every run, timing excluded — see `finctl.fingerprint`. This is
    # the number the metrics table is reproducible against.
    console.print(
        f"\n  metrics fingerprint  [bold]{fingerprint([r.as_row() for r in rows])}[/bold]"
        "  [dim]excludes wall-clock timing, which is the host's, not the engine's[/dim]"
    )
    console.print(f"\n[dim]results → {path}[/dim]")


blind_app = typer.Typer(
    no_args_is_help=True,
    help="Blind testing: run the engine against a batch whose answers it cannot see.",
)
app.add_typer(blind_app, name="blind")


@blind_app.command("new")
def blind_new(
    out: str = typer.Option("data/blind", "--out", "-o", help="Where the batch goes."),
    answers: str = typer.Option(
        "~/finctl-answers", "--answers", "-a",
        help="Where the answer key goes. Keep this away from the project.",
    ),
    seed: int = typer.Option(None, "--seed", "-s", help="Omit for a random one."),
) -> None:
    """Create a blind batch. Prints NOTHING about what was planted.

    The answer key is written outside the project by default, so it cannot be read by
    accident while debugging.
    """
    import random as _random
    from pathlib import Path

    from finctl.blind import create, random_spec
    from finctl.config.loader import load_config

    rng = _random.Random(seed)
    spec = random_spec(rng)

    batch_dir = Path(out)
    answer_dir = Path(answers).expanduser()

    receipt = create(load_config(), batch_dir, answer_dir, spec)

    console.print("[bold]Blind batch created.[/bold]\n")
    console.print(f"  data    [bold]{batch_dir}[/bold]  [dim]({len(receipt['files'])} files)[/dim]")
    console.print(f"  answers [bold]{answer_dir}[/bold]  [red]do not open this yet[/red]\n")
    console.print(
        "[dim]Nothing about the configuration or the planted defects is printed here,\n"
        "deliberately — printing it would spoil the test.[/dim]\n"
    )
    console.print("Next:  [bold]uv run finctl blind run[/bold]")


@blind_app.command("run")
def blind_run(
    data: str = typer.Option("data/blind", "--data", "-D"),
    out: str = typer.Option("data/blind/findings.json", "--out", "-o"),
) -> None:
    """Reconcile a blind batch and write findings. Requires no ground truth.

    This is also exactly the path real merchant data takes, since real data has no
    ground truth either.
    """
    import json
    from pathlib import Path

    from finctl.classify.classifier import Classification
    from finctl.config.loader import load_config
    from finctl.money import format_rupees
    from finctl.pipeline import run as run_pipeline

    batch_dir = Path(data)
    if (batch_dir / "ground_truth.json").exists():
        console.print(
            "[red]ground_truth.json is present in the batch directory.[/red] "
            "This is not a blind run — remove it or use `finctl blind new`."
        )
        raise typer.Exit(1)

    result = run_pipeline(batch_dir, load_config())
    v = result.verdict

    console.print(f"[bold]Blind run[/bold]  [dim]{batch_dir}[/dim]\n")
    console.print(
        f"Expected [bold]{format_rupees(v.expected_paise)}[/bold] · "
        f"Received [bold]{format_rupees(v.received_paise)}[/bold] · "
        f"Gap [bold]{format_rupees(v.gap_paise)}[/bold]\n"
    )
    table = Table(show_header=True, header_style="bold")
    table.add_column("classification")
    table.add_column("rows", justify="right")
    table.add_column("amount", justify="right")
    for line in v.lines:
        table.add_row(str(line.classification), str(line.count),
                      format_rupees(line.amount_paise))
    console.print(table)

    balances = sum(line.amount_paise for line in v.lines) + v.unexplained_paise == v.gap_paise
    console.print(
        f"\n  residual {format_rupees(v.unexplained_paise)}  ·  "
        + ("[green]balances[/green]" if balances else "[red]DOES NOT BALANCE[/red]")
    )
    console.print(
        f"  match rate {result.matches.pass1_match_rate * 100:.1f}% order→PSP, "
        f"{result.matches.pass2_match_rate * 100:.1f}% PSP→bank"
    )
    console.print(f"  {result.rows_processed:,} rows in {result.elapsed_seconds * 1000:.0f}ms")

    # The findings file is the engine's ANSWER: one claim per order, which is what the
    # answer key is scored against. Written as data rather than read off the screen so
    # scoring cannot be fudged after the fact.
    findings = {
        "batch": str(batch_dir),
        "expected_paise": v.expected_paise,
        "received_paise": v.received_paise,
        "gap_paise": v.gap_paise,
        "residual_paise": v.unexplained_paise,
        "balances": balances,
        "claims": [
            {
                "order_id": f.order_id,
                "classification": str(f.classification),
                "amount_paise": f.amount_paise,
            }
            for f in result.correlated.findings
            if f.classification is not Classification.RECONCILED
        ],
        "reconciled_count": sum(
            1 for f in result.correlated.findings
            if f.classification is Classification.RECONCILED
        ),
    }
    Path(out).write_text(json.dumps(findings, indent=2))
    console.print(f"\n[dim]findings → {out}[/dim]")
    console.print("\nNext:  [bold]uv run finctl blind score[/bold]  (after revealing the answers)")


@blind_app.command("score")
def blind_score(
    data: str = typer.Option("data/blind", "--data", "-D"),
    answers: str = typer.Option("~/finctl-answers", "--answers", "-a"),
    findings: str = typer.Option("data/blind/findings.json", "--findings", "-f"),
) -> None:
    """Reveal the answers and score the blind run."""
    import json
    from pathlib import Path

    from finctl.blind import verify_receipt
    from finctl.classify.classifier import Classifier
    from finctl.config.loader import load_config
    from finctl.correlate.correlator import Correlator
    from finctl.generate.ground_truth import GroundTruth
    from finctl.match.matcher import match as run_match
    from finctl.money import format_rupees
    from finctl.score import score as score_run
    from finctl.stage.staging import stage_from_dir

    batch_dir = Path(data)
    answer_dir = Path(answers).expanduser()
    gt_path = answer_dir / "ground_truth.json"

    if not gt_path.exists():
        console.print(f"[red]no answer key at {gt_path}[/red]")
        raise typer.Exit(1)
    if not Path(findings).exists():
        console.print(f"[red]no findings at {findings}[/red] — run `finctl blind run` first.")
        raise typer.Exit(1)

    spec = json.loads((answer_dir / "spec.json").read_text())

    # Verify the data was not altered between generation and scoring. Without this,
    # "we ran it blind" is a claim rather than a fact.
    problems = verify_receipt(batch_dir, spec.get("receipt", {}))
    console.print("[bold]Integrity[/bold]")
    if problems:
        for p in problems:
            console.print(f"  [red]{p}[/red]")
        console.print("  [red]the batch changed after generation — this result is not blind[/red]\n")
    else:
        console.print("  [green]batch files unchanged since generation[/green]\n")

    console.print("[bold]What was actually generated[/bold]")
    for key in ("archetype", "payment_mix", "volume", "cycle_days", "defect_profile", "seed"):
        console.print(f"  {key:16} {spec[key]}")

    cfg = load_config()
    batch = stage_from_dir(batch_dir)
    matches = run_match(batch)
    correlated = Correlator(batch).correlate(Classifier(cfg).classify(matches))
    report = score_run(GroundTruth.read(gt_path), correlated, matches, cfg)

    console.print("\n[bold]Score[/bold]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("defect")
    table.add_column("caught", justify="right")
    table.add_column("missed", justify="right")
    table.add_column("below tol.", justify="right")
    table.add_column("recall", justify="right")
    table.add_column("of scoreable", justify="right")
    for name, s in sorted(report.by_type.items()):
        colour = "green" if not s.missed else "red"
        table.add_row(
            name, str(len(s.caught)),
            f"[{colour}]{len(s.missed)}[/{colour}]",
            f"[dim]{len(s.below_tolerance)}[/dim]",
            f"[{colour}]{s.recall_strict * 100:.0f}%[/{colour}]",
            f"[dim]{s.recall * 100:.0f}%[/dim]",
        )
    console.print(table)

    console.print(
        f"\n  recall [bold]{report.recall_strict * 100:.1f}%[/bold] "
        f"({report.total_caught} caught of {report.total_planted} planted, "
        f"{report.total_missed} missed, "
        f"{report.total_below_tolerance} below tolerance)"
    )
    # A hand-edited batch will produce findings that are NOT in the answer key, because
    # the human planted them and the generator did not know. Those are the engine
    # working, not failing — so they must not be reported as false positives, which
    # would penalise it for catching exactly what the edit was testing.
    edited = bool(problems)
    if report.false_positives and edited:
        console.print(
            f"  [yellow]{len(report.false_positives)} finding(s) not in the answer key"
            "[/yellow] — expected, since the batch was hand-edited:"
        )
        for order_id in report.false_positives[:10]:
            finding = next(
                (f for f in correlated.findings if f.order_id == order_id), None
            )
            if finding:
                console.print(
                    f"    [dim]{order_id}  {finding.classification}  "
                    f"{format_rupees(finding.amount_paise)}[/dim]"
                )
                proof = finding.proof.get("arithmetic")
                if proof:
                    console.print(f"      [dim]{proof}[/dim]")
    else:
        console.print(
            "  false positives: "
            + ("[green]0[/green]" if not report.false_positives
               else f"[red]{len(report.false_positives)}[/red]")
        )
    console.print(
        f"  unexplained {format_rupees(report.unexplained_before_paise)} → "
        f"{format_rupees(report.unexplained_after_paise)}"
    )

    # PASSED requires zero MISSED defects. False positives only count against the run
    # when the batch is untouched — on a hand-edited batch, findings outside the answer
    # key are the point of the exercise rather than a failure.
    failed = report.total_missed > 0 or (report.false_positives and not edited)
    verdict = "[bold red]FAILED[/bold red]" if failed else "[bold green]PASSED[/bold green]"
    suffix = (
        "on a hand-edited batch the engine had never seen"
        if edited else "on a batch the engine had never seen"
    )
    console.print(f"\n  {verdict}  [dim]{suffix}[/dim]")
    if edited and report.false_positives:
        console.print(
            "  [dim]The findings above are not in the answer key because a human "
            "planted them.\n  Check them against the edits you actually made.[/dim]"
        )
