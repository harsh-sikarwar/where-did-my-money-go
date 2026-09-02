"""Command-line entry point.

Deliberately the only user interface until the Day-1 checkpoint passes.
The FastAPI layer added later is a thin wrapper over these same calls.
"""

import platform
import sys

import typer
from rich.console import Console
from rich.table import Table

from finctl import __version__

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Where did my money go? — settlement reconciliation with failure correlation.",
)
console = Console()


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

    total_rows = sum(i["rows"] for i in manifest["sources"].values())
    console.print(
        f"\n[dim]{elapsed:.3f}s · {total_rows / elapsed:,.0f} rows/sec"
        f" · matching is identifier-based only, never fuzzy[/dim]"
    )


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
    classified = Classifier(cfg).classify(matches)
    correlated = Correlator(batch).correlate(classified)
    report = score(GroundTruth.read(gt_path), correlated, matches, cfg)

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
    table.add_column("recall", justify="right")
    for name, s in sorted(report.by_type.items()):
        colour = "green" if not s.missed else "red"
        table.add_row(
            name, str(len(s.caught)),
            f"[{colour}]{len(s.missed)}[/{colour}]" if s.missed else "0",
            f"[dim]{len(s.below_tolerance)}[/dim]" if s.below_tolerance else "0",
            f"[{colour}]{s.recall * 100:.0f}%[/{colour}]",
        )
    console.print(table)

    console.print(
        f"\n  overall recall [bold]{report.recall * 100:.1f}%[/bold]"
        f"  ({report.total_caught} caught, {report.total_missed} missed, "
        f"{report.total_below_tolerance} below tolerance)"
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
