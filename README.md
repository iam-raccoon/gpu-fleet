# gpu-fleet

A live, **one-screen NVIDIA GPU dashboard for every machine you own** — desktops,
servers, and Jetsons — over SSH. No agent to install on the boxes, no browser,
just a terminal.

```
                                  gpu-fleet
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┓
┃ Host          ┃ GPU              ┃       Util ┃ Memory      ┃ Core ┃ VRAM ┃   Power ┃ Processes ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━┩
│ aurora-server │ RTX 3080         │ ██████ 78% │ █████ 7/10G │ 71°C │ 94°C │ 240/320W│ python 6.4G│
│ lab-main      │ RTX 3060         │ ░░░░░░  0% │ ░░░ 0.6/12G │ 44°C │   —  │  10/170W│ —          │
│ jetson-xavier │ Jetson Xavier NX │ ░░░░░░  0% │ ████  4.7/7G│ 36°C │   —  │      —  │ —          │
└───────────────┴──────────────────┴────────────┴─────────────┴──────┴──────┴─────────┴───────────┘
```

> **한국어 요약**: 데스크톱·서버·Jetson까지 내 모든 머신의 NVIDIA GPU 상태(사용률·메모리·코어/VRAM 온도·
> 전력·돌아가는 프로세스)를 SSH로 긁어와 **한 터미널 화면**에 실시간으로 보여주는 툴. 원격 머신에 아무것도
> 설치할 필요 없고(에이전트리스), Jetson은 `nvidia-smi`가 없어도 sysfs에서 알아서 읽음. `nvidia-smi`가
> N/A만 주는 **GDDR6X VRAM 온도**도 [gddr6](https://github.com/olealgoritme/gddr6) 툴이 깔린 호스트면
> 같이 보여줌. Tailscale로 묶어두면 어디서든 포트 열지 않고 확인 가능.

![platform](https://img.shields.io/badge/platform-Linux-informational)
![python](https://img.shields.io/badge/python-3.8%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

---

## Why

If you run more than one GPU box — a training server, a workstation, a Jetson on
the bench — checking each one means SSH-ing in and squinting at `nvidia-smi`
three times. `gpu-fleet` polls them all at once and lays the whole fleet out in a
single auto-refreshing table, colour-coded by load and temperature.

- **Agentless.** Nothing is installed on the remote machines. Each poll runs one
  small snippet over your existing SSH — if you can `ssh` in, it works.
- **Jetson-aware.** Tegra boards have no `nvidia-smi`; gpu-fleet reads GPU load,
  temperature and (unified) memory straight from sysfs and shows them alongside
  the desktop cards.
- **VRAM temperature.** On consumer cards `nvidia-smi` reports memory temperature
  as `N/A`, which hides the one number that matters on GDDR6X — it runs far
  hotter than the core and throttles around 105 °C. If a host has the
  [gddr6](https://github.com/olealgoritme/gddr6) tool, gpu-fleet shows real VRAM
  temperature in its own column, on its own colour scale.
- **Tailscale-friendly.** Use tailnet names as hosts and watch your fleet from
  anywhere without exposing a single port.
- **Tiny.** Pure Python, one dependency (`rich`). Config is a plain INI file.

## Install

```bash
pip install --user rich
git clone https://github.com/iam-raccoon/gpu-fleet.git
cd gpu-fleet
pip install --user .          # installs the `gpu-fleet` command
```

Or just run it in place without installing: `python3 -m gpu_fleet`.

**Requirements:** Linux, Python 3.8+, `rich`, an `ssh` client, and key-based SSH
access to each remote host (so polling doesn't prompt for a password).

## Usage

```bash
gpu-fleet init            # write an example ~/.config/gpu-fleet/hosts.ini
$EDITOR ~/.config/gpu-fleet/hosts.ini
gpu-fleet                 # live dashboard (Ctrl-C to quit)
```

Config is one section per machine:

```ini
[local]
ssh = local               # the machine running gpu-fleet itself

[aurora-server]
ssh = user@aurora-server  # user@host, or a ~/.ssh/config alias

[jetson-xavier]
ssh = user@jetson-xavier  # Jetson auto-detected — no nvidia-smi needed
```

### Options

| Flag | Meaning |
|------|---------|
| `-n, --interval N` | refresh every N seconds (default 2) |
| `--timeout N` | per-host SSH timeout (default 8) |
| `--once` | print a single snapshot and exit (great for scripts/cron) |
| `-c, --config PATH` | use a specific config file |

`gpu-fleet --once` prints plain output when stdout isn't a terminal, so it drops
neatly into a cron job, a status bar, or `watch`.

## How it works

For each host, gpu-fleet opens one SSH connection and runs a self-contained shell
snippet that auto-detects the GPU type:

- **Desktop / server** → parsed from `nvidia-smi --query-gpu=…` (util, memory,
  temperature, power) plus running compute processes.
- **Jetson (Tegra)** → GPU load from `/sys/devices/gpu.0/load`, temperature from
  the `GPU-therm` thermal zone, and memory from `/proc/meminfo` (unified).
- **VRAM temperature** → from the `gddr6` tool, if the host has it (see below).

Hosts are polled concurrently, so one unreachable or slow machine never stalls
the rest — it just shows up as `offline` with the reason.

### Enabling VRAM temperature (optional)

The `VRAM` column stays `—` unless a host can report it. `gddr6` reads the
memory controller over PCI, so it needs root and Secure Boot off. On each host
you want it for:

```bash
sudo apt install -y libpci-dev build-essential cmake git
git clone https://github.com/olealgoritme/gddr6.git ~/gddr6
cd ~/gddr6 && mkdir -p build && cd build && cmake .. && cmake --build . --config Release
```

Then allow it to run without a password prompt, so polling stays non-interactive
(`visudo -f /etc/sudoers.d/gddr6`):

```
your-user ALL=(root) NOPASSWD: /home/your-user/gddr6/build/bin/gddr6
```

gpu-fleet looks for `~/gddr6/build/bin/gddr6`, `/usr/local/bin/gddr6`,
`/usr/bin/gddr6`, or `gddr6` on `PATH`. It only ever invokes it with `sudo -n`
(never prompts) under a 1-second timeout, and hosts without it pay no cost.
Supported on GDDR6/GDDR6X cards — roughly RTX 3000/4000.

## Troubleshooting

- **`offline · ssh auth failed`** → set up key-based SSH to that host
  (`ssh-copy-id`), or give it a working `~/.ssh/config` alias and use that as `ssh =`.
- **`offline · connection timed out`** → the machine is down or unreachable
  (expected for powered-off boxes).
- **A Jetson shows `no GPU`** → its sysfs layout differs; open an issue with the
  output of `ls /sys/devices/gpu.0/ /sys/devices/platform/gpu.0/`.
- **`VRAM` shows `—` on a card that has GDDR6X** → check, on that host, that
  `gddr6` is built where gpu-fleet looks, that `sudo -n <path-to-gddr6>` runs
  without a password, and that Secure Boot is disabled.

## License

MIT — see [LICENSE](LICENSE).
