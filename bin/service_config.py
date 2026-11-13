"""Generate launchd paths on the installing machine; never commit the result."""
from __future__ import annotations

import argparse
import os
import plistlib
from pathlib import Path

LABEL = "com.local-meeting-assistant.web"


def service_config(root: Path) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(root / ".venv-app/bin/python"), str(root / "app.py"),
                             "--host", "127.0.0.1", "--port", "8766"],
        "WorkingDirectory": str(root),
        "EnvironmentVariables": {
            "PATH": os.pathsep.join(("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin")),
            "PYDANTIC_AI_NO_BANNER": "1",
            "MEETING_CONFIG_FILE": str(root / "config.local.json"),
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        # Audio must not inherit background CPU/I/O or coalesced timer throttling.
        "ProcessType": "Interactive",
        "LegacyTimers": True,
        "StandardOutPath": str(root / "var/app.log"),
        "StandardErrorPath": str(root / "var/app.log"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(plistlib.dumps(service_config(args.root.resolve())))
