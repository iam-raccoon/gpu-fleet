"""Remote GPU probing.

Agentless: nothing is installed on the target machines. For each host we run a
single self-contained bash snippet over SSH (or locally, for ssh = "local").
The snippet auto-detects the GPU flavour:

  * NVIDIA desktop/server GPUs  -> parsed from `nvidia-smi`
  * NVIDIA Jetson (Tegra)       -> read from sysfs (`nvidia-smi` is absent there)

GDDR6/GDDR6X memory temperature is reported when the host has the `gddr6` tool
(https://github.com/olealgoritme/gddr6) and grants passwordless sudo for it;
`nvidia-smi` reports N/A for memory temperature on consumer cards. Hosts without
it simply report no VRAM temperature.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

# One round-trip per host. Emits a tiny tagged text protocol that _parse() reads.
REMOTE_SCRIPT = r"""
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "TYPE nvidia"
  nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit --format=csv,noheader,nounits 2>/dev/null
  echo "VRAM"
  gd=""
  for c in "$HOME/gddr6/build/bin/gddr6" /usr/local/bin/gddr6 /usr/bin/gddr6; do
    [ -x "$c" ] && { gd="$c"; break; }
  done
  [ -z "$gd" ] && gd=$(command -v gddr6 2>/dev/null)
  # gddr6 needs root and never exits on its own, hence sudo -n + timeout.
  if [ -n "$gd" ] && sudo -n true 2>/dev/null; then
    sudo -n timeout 1 "$gd" 2>/dev/null | tr '\r' '\n' \
      | grep -a 'VRAM Temps' | tail -1 | grep -oE '[0-9]+'
  fi
  echo "PROCS"
  nvidia-smi --query-compute-apps=pid,used_memory,process_name --format=csv,noheader,nounits 2>/dev/null
elif [ -e /sys/devices/gpu.0/load ] || [ -e /sys/devices/platform/gpu.0/load ]; then
  echo "TYPE jetson"
  load=$(cat /sys/devices/gpu.0/load 2>/dev/null || cat /sys/devices/platform/gpu.0/load 2>/dev/null || echo "")
  echo "LOAD $load"
  gtemp=""
  for z in /sys/class/thermal/thermal_zone*/; do
    t=$(cat "$z/type" 2>/dev/null)
    case "$t" in
      *GPU*) gtemp=$(cat "$z/temp" 2>/dev/null); break;;
    esac
  done
  echo "TEMP $gtemp"
  echo "MEM $(grep -E 'MemTotal|MemAvailable' /proc/meminfo 2>/dev/null | awk '{print $2}' | paste -sd' ')"
  echo "MODEL $(tr -d '\0' < /proc/device-tree/model 2>/dev/null)"
else
  echo "TYPE none"
fi
""".strip()


@dataclass
class GpuStat:
    index: int
    name: str
    util: float                      # percent 0..100
    mem_used: float                  # MiB
    mem_total: float                 # MiB
    temp: Optional[float]            # core/die deg C
    power: Optional[float] = None    # W
    power_limit: Optional[float] = None
    vram_temp: Optional[float] = None  # GDDR6/6X deg C, None if unavailable


@dataclass
class Proc:
    pid: str
    mem: float                       # MiB
    name: str


@dataclass
class HostStat:
    name: str
    ok: bool
    kind: str = "unknown"            # nvidia | jetson | none | unknown
    gpus: List[GpuStat] = field(default_factory=list)
    procs: List[Proc] = field(default_factory=list)
    model: str = ""
    error: str = ""


def _run(ssh: str, timeout: float):
    if ssh == "local":
        cmd = ["bash", "-s"]
    else:
        cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=accept-new",
            ssh, "bash -s",
        ]
    p = subprocess.run(cmd, input=REMOTE_SCRIPT, capture_output=True,
                       text=True, timeout=timeout)
    return p.stdout, p.stderr, p.returncode


def probe(host, timeout: float = 8.0) -> HostStat:
    """Probe one host. Never raises — failures come back as ok=False."""
    try:
        out, err, rc = _run(host.ssh, timeout)
    except subprocess.TimeoutExpired:
        return HostStat(host.name, ok=False, error="timeout")
    except FileNotFoundError:
        return HostStat(host.name, ok=False, error="ssh not found")
    except Exception as e:  # pragma: no cover - defensive
        return HostStat(host.name, ok=False, error=str(e)[:60])

    if not out.strip():
        return HostStat(host.name, ok=False, error=_short_error(err, rc))
    return _parse(host.name, out)


def _short_error(err: str, rc: int) -> str:
    """Boil an ssh failure down to a few readable words for the table."""
    low = err.lower()
    if "connection timed out" in low or "operation timed out" in low:
        return "connection timed out"
    if "connection refused" in low:
        return "connection refused"
    if "permission denied" in low:
        return "ssh auth failed"
    if "could not resolve" in low or "name or service not known" in low:
        return "host not found"
    if "no route to host" in low:
        return "no route to host"
    last = err.strip().splitlines()[-1] if err.strip() else f"ssh rc={rc}"
    return last[:40]


def _f(val: str) -> Optional[float]:
    val = val.strip()
    if not val or val.upper().startswith("[N/A") or val.upper() == "N/A":
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _parse(name: str, out: str) -> HostStat:
    lines = out.splitlines()
    kind = "unknown"
    for ln in lines:
        if ln.startswith("TYPE "):
            kind = ln.split(None, 1)[1].strip()
            break

    if kind == "nvidia":
        return _parse_nvidia(name, lines)
    if kind == "jetson":
        return _parse_jetson(name, lines)
    if kind == "none":
        return HostStat(name, ok=True, kind="none")
    return HostStat(name, ok=False, error="unrecognized output")


def _parse_nvidia(name: str, lines: List[str]) -> HostStat:
    gpus: List[GpuStat] = []
    procs: List[Proc] = []
    vram_temps: List[float] = []
    section = "gpu"
    for ln in lines:
        s = ln.strip()
        if s == "TYPE nvidia":
            continue
        if s == "VRAM":
            section = "vram"
            continue
        if s == "PROCS":
            section = "procs"
            continue
        if not s:
            continue
        if section == "vram":
            v = _f(s)
            if v is not None:
                vram_temps.append(v)
            continue
        parts = [p.strip() for p in s.split(",")]
        if section == "gpu" and len(parts) >= 6:
            gpus.append(GpuStat(
                index=int(_f(parts[0]) or 0),
                name=parts[1],
                util=_f(parts[2]) or 0.0,
                mem_used=_f(parts[3]) or 0.0,
                mem_total=_f(parts[4]) or 0.0,
                temp=_f(parts[5]),
                power=_f(parts[6]) if len(parts) > 6 else None,
                power_limit=_f(parts[7]) if len(parts) > 7 else None,
            ))
        elif section == "procs" and len(parts) >= 3:
            procs.append(Proc(pid=parts[0], mem=_f(parts[1]) or 0.0,
                              name=parts[2]))

    # gddr6 lists devices in PCI order, same as nvidia-smi's default index
    # order, so pair them positionally. Mismatched counts: leave VRAM unset
    # rather than risk showing one GPU's temperature against another.
    if len(vram_temps) == len(gpus):
        for g, v in zip(gpus, vram_temps):
            g.vram_temp = v

    return HostStat(name, ok=True, kind="nvidia", gpus=gpus, procs=procs)


def _parse_jetson(name: str, lines: List[str]) -> HostStat:
    load = temp = None
    mem_total = mem_avail = None
    model = "Jetson"
    for ln in lines:
        s = ln.strip()
        if s.startswith("LOAD "):
            load = _f(s[5:])
        elif s.startswith("TEMP "):
            temp = _f(s[5:])
        elif s.startswith("MEM "):
            nums = [_f(x) for x in s[4:].split()]
            nums = [n for n in nums if n is not None]
            if len(nums) >= 2:
                mem_total, mem_avail = nums[0], nums[1]
        elif s.startswith("MODEL "):
            m = s[6:].strip()
            if m:
                model = m

    # Jetson sysfs load is 0..1000 (tenths of a percent).
    util = (load / 10.0) if load is not None else 0.0
    # sysfs temp is milli-degrees C.
    tempc = (temp / 1000.0) if temp is not None else None
    # /proc/meminfo is in kB; unified memory is shared with the GPU.
    mt = (mem_total or 0.0) / 1024.0
    ma = (mem_avail or 0.0) / 1024.0
    gpu = GpuStat(index=0, name=model, util=util,
                  mem_used=max(0.0, mt - ma), mem_total=mt, temp=tempc)
    return HostStat(name, ok=True, kind="jetson", gpus=[gpu], model=model)
