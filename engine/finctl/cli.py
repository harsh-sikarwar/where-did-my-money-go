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


if __name__ == "__main__":
    app()


@app.command()
def probe(
    live: bool = typer.Option(
        False, "--live", help="Call Razorpay test mode and overwrite fixtures (Day-2 task)."
    ),
) -> None:
    """Inspect Razorpay's real response shapes (ADR-006: verification, not foundation).

    Without --live this reads the committed fixtures: no network, no credentials.
    """
    from finctl.probe import FIXTURE_DIR, analyse_fee_convention, field_inventory, load_fixture

    if live:
        console.print("[yellow]--live not yet implemented.[/yellow] Day-2 task per ADR-006.")
        console.print("The offline probe below is what validates the generator in Phase 1.")
        console.print()

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
    console.print("[dim]Not live-captured. Re-run with --live on Day 2 — see PROVENANCE.md.[/dim]")
