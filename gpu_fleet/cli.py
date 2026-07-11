"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List

from rich.console import Console

from . import __version__
from .config import DEFAULT_CONFIG_PATH, Host, load_hosts, write_example
from .probe import HostStat, probe
from .ui import render


def poll_all(hosts: List[Host], timeout: float) -> List[HostStat]:
    """Probe every host concurrently so one slow box can't stall the view."""
    if not hosts:
        return []
    with ThreadPoolExecutor(max_workers=min(16, len(hosts))) as ex:
        return list(ex.map(lambda h: probe(h, timeout), hosts))


def _footer(interval: float) -> str:
    return (f"[grey50]refresh {interval:g}s · Ctrl-C to quit · "
            f"gpu-fleet {__version__}[/]")


def cmd_run(args) -> int:
    console = Console()
    try:
        hosts = load_hosts(args.config)
    except FileNotFoundError:
        console.print(f"[red]No config at[/] {args.config}")
        console.print("Run [bold]gpu-fleet init[/] to create one.")
        return 1
    if not hosts:
        console.print("[yellow]No hosts configured.[/] Edit "
                      f"{args.config}")
        return 1

    if args.once or not sys.stdout.isatty():
        stats = poll_all(hosts, args.timeout)
        console.print(render(stats))
        return 0

    from rich.console import Group
    from rich.live import Live

    def frame(stats):
        return Group(render(stats), _footer(args.interval))

    stats = poll_all(hosts, args.timeout)
    try:
        with Live(frame(stats), console=console, screen=False,
                  refresh_per_second=4) as live:
            while True:
                time.sleep(args.interval)
                stats = poll_all(hosts, args.timeout)
                live.update(frame(stats))
    except KeyboardInterrupt:
        pass
    return 0


def cmd_init(args) -> int:
    console = Console()
    import os
    if os.path.exists(args.config) and not args.force:
        console.print(f"[yellow]Config already exists:[/] {args.config}")
        console.print("Use [bold]--force[/] to overwrite.")
        return 1
    path = write_example(args.config)
    console.print(f"[green]Wrote example config:[/] {path}")
    console.print("Edit it to add your machines, then run [bold]gpu-fleet[/].")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gpu-fleet",
        description="Live multi-machine NVIDIA GPU dashboard over SSH.")
    p.add_argument("-c", "--config", default=DEFAULT_CONFIG_PATH,
                   help=f"config path (default: {DEFAULT_CONFIG_PATH})")
    p.add_argument("-n", "--interval", type=float, default=2.0,
                   help="refresh interval in seconds (default: 2)")
    p.add_argument("--timeout", type=float, default=8.0,
                   help="per-host SSH timeout in seconds (default: 8)")
    p.add_argument("--once", action="store_true",
                   help="print once and exit (no live view)")
    p.add_argument("--version", action="version",
                   version=f"gpu-fleet {__version__}")

    sub = p.add_subparsers(dest="command")
    ip = sub.add_parser("init", help="write an example config")
    ip.add_argument("-c", "--config", default=DEFAULT_CONFIG_PATH)
    ip.add_argument("--force", action="store_true")
    ip.set_defaults(func=cmd_init)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "func", None):
        return args.func(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
