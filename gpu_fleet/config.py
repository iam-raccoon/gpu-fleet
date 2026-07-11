"""Host configuration (plain INI — stdlib only, comment-friendly)."""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from typing import List

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/gpu-fleet/hosts.ini")

EXAMPLE = """\
# gpu-fleet hosts. One [section] per machine.
#   ssh  = how to reach it: "user@host", a ~/.ssh/config alias, or "local"
#          for the machine running gpu-fleet itself.
#   type = auto (default) | nvidia | jetson   -- usually leave as auto.

[local]
ssh = local

# [aurora-server]
# ssh = user@aurora-server

# [jetson-xavier]
# ssh = user@jetson-xavier
# type = jetson
"""


@dataclass
class Host:
    name: str
    ssh: str
    type: str = "auto"


def load_hosts(path: str = None) -> List[Host]:
    path = path or DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    cp = configparser.ConfigParser()
    cp.read(path)
    hosts: List[Host] = []
    for name in cp.sections():
        sec = cp[name]
        hosts.append(Host(
            name=name,
            ssh=sec.get("ssh", name),
            type=sec.get("type", "auto"),
        ))
    return hosts


def write_example(path: str = None) -> str:
    path = path or DEFAULT_CONFIG_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(EXAMPLE)
    return path
