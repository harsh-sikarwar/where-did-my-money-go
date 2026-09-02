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
