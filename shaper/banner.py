"""
Banner and UI components for Signalis
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from core import __version__

# Global console instance
console = Console()


VERSION = __version__
TAGLINE = "Signal-driven matching engine for B2B outreach"


def show_banner():
    """Display ASCII art banner"""
    art = (
        "[bold cyan]"
        "███████╗██╗ ██████╗ ███╗   ██╗  █████╗ ██╗     ██╗███████╗\n"
        "██╔════╝██║██╔════╝ ████╗  ██║ ██╔══██╗██║     ██║██╔════╝\n"
        "███████╗██║██║  ███╗██╔██╗ ██║ ███████║██║     ██║███████╗\n"
        "╚════██║██║██║   ██║██║╚██╗██║ ██╔══██║██║     ██║╚════██║\n"
        "███████║██║╚██████╔╝██║ ╚████║ ██║  ██║███████╗██║███████║\n"
        "╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═╝  ╚═╝╚══════╝╚═╝╚══════╝"
        "[/bold cyan]"
    )
    panel = Panel(
        f"{art}\n\n[dim]{TAGLINE}[/dim]\n[dim]v{VERSION}[/dim]",
        border_style="cyan",
        padding=(1, 3),
    )
    console.print(panel)


def show_step(step, title: str, description: str = ""):
    """Show a step header"""
    console.print()
    header = f"[bold cyan]Step {step}: {title}[/bold cyan]"
    if description:
        console.print(f"{header}\n[dim]{description}[/dim]")
    else:
        console.print(header)


def show_success(message: str):
    """Show success message"""
    console.print(f"☉ [green]{message}[/green]")


def show_error(message: str):
    """Show error message"""
    console.print(f"☿ [red]{message}[/red]")


def show_warning(message: str):
    """Show warning message"""
    console.print(f"▲ [yellow]{message}[/yellow]")


def show_info(message: str):
    """Show info message"""
    console.print(f"◈ [blue]{message}[/blue]")


def show_preview_table(records: list, headers: list, limit: int = 5):
    """Display preview of data in a table"""
    table = Table(show_header=True, header_style="bold cyan")

    # Add columns
    for header in headers:
        table.add_column(header[:20], overflow="fold")  # Truncate long headers

    # Add rows (limit to preview count)
    for record in records[:limit]:
        row = [str(record.get(h, ""))[:30] for h in headers]  # Truncate long values
        table.add_row(*row)

    console.print(table)


def create_progress() -> Progress:
    """Create a Rich progress bar"""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    )
