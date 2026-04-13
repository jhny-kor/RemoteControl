from __future__ import annotations

import subprocess
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(
        args,
        cwd=str(cwd or APP_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return (completed.stdout or "").strip()


def main() -> int:
    manager_status = run([sys.executable, str(APP_ROOT / "remote_manager.py"), "--status"])
    dashboard_status = run(["zsh", "scripts/manage_process_control_launch_agent.sh", "status"])
    access_key_path = APP_ROOT / "logs" / "process_control_access_key.txt"
    access_key_loaded = "yes" if access_key_path.exists() and access_key_path.read_text(encoding="utf-8").strip() else "no"

    print(
        "\n".join(
            [
                "[remote_bot] status",
                "",
                "remote_manager",
                manager_status or "-",
                "",
                "process_control_dashboard",
                dashboard_status or "-",
                "",
                f"dashboard_access_key_loaded: {access_key_loaded}",
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
