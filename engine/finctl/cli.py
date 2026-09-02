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
