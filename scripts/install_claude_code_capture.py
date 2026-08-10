#!/usr/bin/env python3
"""Install hourly Claude Code + Codex capture as a macOS LaunchAgent."""

import argparse
import os
import plistlib
import platform
import subprocess
import sys
from pathlib import Path


LABEL = "com.milen.obsidian-brain.claude-code-capture"
INTERVAL_SECONDS = 3600


def paths(home=None):
    home = home or Path.home()
    project = home / "dev" / "projects" / "personal" / "obsidian-brain"
    return {
        "project": project,
        "capture": project / "scripts" / "capture_chats.py",
        "agent": home / "Library" / "LaunchAgents" / f"{LABEL}.plist",
        "log": home / "Library" / "Logs" / "obsidian-brain-claude-code-capture.log",
    }


def build_plist(python_path=None, home=None):
    resolved = paths(home)
    python_path = Path(python_path or sys.executable).resolve()
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python_path), str(resolved["capture"])],
        "WorkingDirectory": str(resolved["project"]),
        "RunAtLoad": True,
        "StartInterval": INTERVAL_SECONDS,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "StandardOutPath": str(resolved["log"]),
        "StandardErrorPath": str(resolved["log"]),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }


def _domain():
    return f"gui/{os.getuid()}"


def _launchctl(*args, check=True):
    return subprocess.run(
        ["/bin/launchctl", *args],
        check=check,
        text=True,
        capture_output=True,
    )


def install():
    if platform.system() != "Darwin":
        raise SystemExit("This installer supports macOS only.")
    resolved = paths()
    if not resolved["capture"].is_file():
        raise SystemExit(f"Capture runner not found: {resolved['capture']}")

    resolved["agent"].parent.mkdir(parents=True, exist_ok=True)
    resolved["log"].parent.mkdir(parents=True, exist_ok=True)
    with resolved["agent"].open("wb") as handle:
        plistlib.dump(build_plist(), handle, sort_keys=False)
    resolved["agent"].chmod(0o644)

    # Replace an older loaded copy, if present, then run the new definition now.
    _launchctl("bootout", _domain(), str(resolved["agent"]), check=False)
    try:
        _launchctl("bootstrap", _domain(), str(resolved["agent"]))
        _launchctl("kickstart", "-k", f"{_domain()}/{LABEL}")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise SystemExit(f"LaunchAgent installation failed: {detail}") from exc

    print(f"Installed {LABEL}")
    print("Claude Code + Codex capture runs at login and hourly; notes stay in 00-inbox until triage.")
    print(f"Log: {resolved['log']}")


def uninstall():
    resolved = paths()
    _launchctl("bootout", _domain(), str(resolved["agent"]), check=False)
    if resolved["agent"].exists():
        resolved["agent"].unlink()
    print(f"Uninstalled {LABEL}; existing Obsidian notes were not changed.")


def status():
    result = _launchctl("print", f"{_domain()}/{LABEL}", check=False)
    if result.returncode:
        print("Not installed or not loaded.")
        raise SystemExit(1)
    print(result.stdout.rstrip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--uninstall", action="store_true")
    action.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.uninstall:
        uninstall()
    elif args.status:
        status()
    else:
        install()


if __name__ == "__main__":
    main()
