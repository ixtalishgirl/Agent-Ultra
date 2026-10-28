"""Copy spawner.

REAL: creates N copy dirs (workspace + browser profile each) under a
base dir and registers them with the head.

HONEST LIMIT: a copy's "own machine" here is a local directory, not a
container. Docker is not installed on this host, so the container
path (OpenBot's supervisor model: one container per Bot) is UNTESTED
and is recorded as such on every copy. Spawning 1000 copy dirs is
cheap; running 1000 containers at once is a different claim entirely
(see ARCHITECTURE.md scaling math) and is NOT made here.
"""

import shutil
from pathlib import Path

from .copy_agent import CopyAgent

DEFAULT_CONCURRENT = 10  # safe default for one host; 1000 needs a fleet


class Spawner:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.docker = shutil.which("docker")

    def machine_record(self):
        if self.docker:
            return {
                "type": "container",
                "status": "UNTESTED",
                "note": "Docker binary found, but no container launch has been run.",
            }
        return {
            "type": "local-directory",
            "status": "UNTESTED-container",
            "note": "No Docker on this host: machine is a local dir, not a container.",
        }

    def spawn(self, count, prefix="copy"):
        copies = []
        machine = self.machine_record()
        for i in range(1, count + 1):
            copy_id = f"{prefix}-{i:04d}"
            copies.append(CopyAgent(copy_id, self.base_dir / copy_id, machine))
        return copies
