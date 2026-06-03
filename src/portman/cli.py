"""Command-line interface for Portman."""

import asyncio
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer
from aiohttp import web
from rich.console import Console
from rich.table import Table

from portman.config import ConfigError, load
from portman.health import check_all
from portman.proxy import create_app
from portman.route_table import RouteTable
from portman.watcher import start_watcher

app = typer.Typer(help="Portman Local Reverse Proxy", add_completion=False)
hosts_app = typer.Typer(
    help="Experimental: manage hosts entries for custom local domains.",
    add_completion=False,
)
app.add_typer(hosts_app, name="hosts")

console = Console()


def version_callback(value: bool) -> None:
    """Print the version and exit."""
    if value:
        v = version("portman-proxy")
        typer.echo(f"Portman {v}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = None,
) -> None:
    """Portman CLI."""
    pass


@app.command()
def start(
    config_path: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            help="Path to the portman.yml config file.",
            exists=True,
            dir_okay=False,
        ),
    ] = Path("portman.yml"),
) -> None:
    """Start the Portman reverse proxy."""
    try:
        config = load(config_path)
    except ConfigError as e:
        console.print(f"[red]Error loading configuration: {e}[/red]")
        raise typer.Exit(code=1) from None

    route_table = RouteTable.from_config(config)
    observer = start_watcher(config_path, route_table)
    aio_app = create_app(route_table, config)

    console.print(f"[green]Starting Portman proxy on port {config.proxy_port}[/green]")
    try:
        web.run_app(
            aio_app,
            host="127.0.0.1",
            port=config.proxy_port,
            print=lambda *args, **kwargs: None,
        )
    finally:
        observer.stop()
        observer.join()


@app.command(name="list")
def list_routes(
    config_path: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            help="Path to the portman.yml config file.",
            exists=True,
            dir_okay=False,
        ),
    ] = Path("portman.yml"),
) -> None:
    """List configured routes and perform health checks."""
    try:
        config = load(config_path)
    except ConfigError as e:
        console.print(f"[red]Error loading configuration: {e}[/red]")
        raise typer.Exit(code=1) from None

    table = Table(title="Portman Routes")
    table.add_column("Domain", style="cyan", no_wrap=True)
    table.add_column("Port", style="magenta")
    table.add_column("Status", justify="center")

    ports = {entry.port for entry in config.routes}
    health_status = asyncio.run(check_all(ports))

    for route in sorted(config.routes, key=lambda r: r.domain):
        is_healthy = health_status.get(route.port, False)
        status_text = (
            "[green]Healthy[/green]" if is_healthy else "[red]Unreachable[/red]"
        )
        table.add_row(route.domain, str(route.port), status_text)

    console.print(table)


@hosts_app.command("install")
def hosts_install(
    config_path: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            help="Path to the portman.yml config file.",
            exists=True,
            dir_okay=False,
        ),
    ] = Path("portman.yml"),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview changes without modifying the file."),
    ] = False,
) -> None:
    """Optionally install routes into the system hosts file."""
    from portman.hosts import get_hosts_path, install_hosts

    try:
        config = load(config_path)
    except ConfigError as e:
        console.print(f"[red]Error loading configuration: {e}[/red]")
        raise typer.Exit(code=1) from None

    hosts_path = get_hosts_path()
    try:
        new_content = install_hosts(config, hosts_path, dry_run=dry_run)
        if dry_run:
            console.print(
                "[yellow]DRY RUN: The following changes would be written to "
                f"{hosts_path}:[/yellow]"
            )
            console.print(new_content)
        else:
            console.print(
                "[green]Successfully installed optional hosts entries into "
                f"{hosts_path}[/green]"
            )
    except PermissionError:
        console.print(
            f"[red]Permission denied modifying {hosts_path}. "
            "Try running as Administrator/root.[/red]"
        )
        raise typer.Exit(code=1) from None


@hosts_app.command("uninstall")
def hosts_uninstall(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview changes without modifying the file."),
    ] = False,
) -> None:
    """Remove optional portman routes from the system hosts file."""
    from portman.hosts import get_hosts_path, uninstall_hosts

    hosts_path = get_hosts_path()
    try:
        new_content = uninstall_hosts(hosts_path, dry_run=dry_run)
        if dry_run:
            console.print(
                "[yellow]DRY RUN: The following changes would be written to "
                f"{hosts_path}:[/yellow]"
            )
            console.print(new_content)
        else:
            console.print(
                "[green]Successfully removed optional hosts entries from "
                f"{hosts_path}[/green]"
            )
    except PermissionError:
        console.print(
            f"[red]Permission denied modifying {hosts_path}. "
            "Try running as Administrator/root.[/red]"
        )
        raise typer.Exit(code=1) from None


if __name__ == "__main__":
    app()
