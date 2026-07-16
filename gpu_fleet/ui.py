"""Rich rendering of fleet state."""

from __future__ import annotations

from typing import List

from rich.table import Table
from rich.text import Text

from .probe import HostStat


def _heat(pct: float) -> str:
    if pct >= 85:
        return "bold red"
    if pct >= 50:
        return "yellow"
    return "green"


def _temp_color(t: float) -> str:
    if t >= 80:
        return "bold red"
    if t >= 65:
        return "yellow"
    return "green"


def _vram_color(t: float) -> str:
    # GDDR6X throttles around 105 C, so it runs far hotter than the core and
    # needs its own scale — core-temp thresholds would flag healthy memory.
    if t >= 100:
        return "bold red"
    if t >= 90:
        return "red"
    if t >= 80:
        return "yellow"
    return "green"


def _bar(frac: float, width: int = 10, color: str = "green") -> Text:
    frac = max(0.0, min(1.0, frac))
    filled = int(round(frac * width))
    txt = Text()
    txt.append("█" * filled, style=color)
    txt.append("░" * (width - filled), style="grey37")
    return txt


def _short_procs(host: HostStat, limit: int = 3) -> Text:
    if not host.procs:
        return Text("—", style="grey50")
    txt = Text()
    for i, p in enumerate(host.procs[:limit]):
        if i:
            txt.append("  ")
        name = p.name.rsplit("/", 1)[-1]
        if len(name) > 16:
            name = name[:15] + "…"
        txt.append(name, style="cyan")
        txt.append(f" {p.mem/1024:.1f}G", style="grey62")
    extra = len(host.procs) - limit
    if extra > 0:
        txt.append(f"  +{extra}", style="grey50")
    return txt


def render(stats: List[HostStat], title: str = "gpu-fleet") -> Table:
    table = Table(title=title, title_style="bold", expand=False,
                  header_style="bold grey74", border_style="grey30",
                  pad_edge=False)
    table.add_column("Host", style="bold")
    table.add_column("GPU", no_wrap=True, overflow="ellipsis", max_width=22)
    table.add_column("Util", justify="right")
    table.add_column("Memory")
    table.add_column("Core", justify="right")
    table.add_column("VRAM", justify="right")
    table.add_column("Power", justify="right")
    table.add_column("Processes")

    for h in stats:
        if not h.ok:
            table.add_row(h.name, Text("offline", style="bold red"),
                          "", "", "", "", "", Text(h.error, style="red"))
            continue
        if h.kind == "none" or not h.gpus:
            table.add_row(h.name, Text("no GPU", style="grey50"),
                          "", "", "", "", "", "")
            continue

        for i, g in enumerate(h.gpus):
            hostcell = h.name if i == 0 else ""
            util_c = _heat(g.util)
            util_cell = Text.assemble(
                _bar(g.util / 100.0, 8, util_c), " ",
                Text(f"{g.util:3.0f}%", style=util_c))

            memfrac = (g.mem_used / g.mem_total) if g.mem_total else 0.0
            mem_cell = Text.assemble(
                _bar(memfrac, 8, _heat(memfrac * 100)), " ",
                Text(f"{g.mem_used/1024:.1f}/{g.mem_total/1024:.0f}G",
                     style="grey74"))

            if g.temp is None:
                temp_cell = Text("—", style="grey50")
            else:
                temp_cell = Text(f"{g.temp:.0f}°C", style=_temp_color(g.temp))

            if g.vram_temp is None:
                vram_cell = Text("—", style="grey50")
            else:
                vram_cell = Text(f"{g.vram_temp:.0f}°C",
                                 style=_vram_color(g.vram_temp))

            if g.power is None:
                pow_cell = Text("—", style="grey50")
            elif g.power_limit:
                pow_cell = Text(f"{g.power:.0f}/{g.power_limit:.0f}W",
                                style="grey74")
            else:
                pow_cell = Text(f"{g.power:.0f}W", style="grey74")

            gpu_name = (g.name.replace("NVIDIA ", "").replace("GeForce ", "")
                        .replace(" Developer Kit", "").strip())

            procs = _short_procs(h) if i == 0 else Text("")
            table.add_row(hostcell, gpu_name, util_cell, mem_cell,
                          temp_cell, vram_cell, pow_cell, procs)
    return table
