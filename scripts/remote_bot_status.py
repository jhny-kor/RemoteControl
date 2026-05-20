from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
SCREEN_SHARING_PORT = 5900
SCREEN_SHARING_PLIST = Path("/System/Library/LaunchDaemons/com.apple.screensharing.plist")
HOMEBREW_PYTHON = Path("/opt/homebrew/bin/python3")


def run_result(args: list[str], cwd: Path | None = None, timeout_sec: int = 10) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd or APP_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=timeout_sec,
        )
    except FileNotFoundError:
        return 127, f"command not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"command timed out: {' '.join(args)}"
    return completed.returncode, (completed.stdout or "").strip()


def run(args: list[str], cwd: Path | None = None, timeout_sec: int = 10) -> str:
    _, output = run_result(args, cwd=cwd, timeout_sec=timeout_sec)
    return output


def remote_manager_python() -> str:
    if sys.version_info >= (3, 11):
        return sys.executable
    if HOMEBREW_PYTHON.exists():
        return str(HOMEBREW_PYTHON)
    return sys.executable


def probe_local_tcp_port(port: int) -> tuple[str, str]:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.7):
            return "open", "127.0.0.1 접속 성공"
    except ConnectionRefusedError:
        return "closed", "127.0.0.1 접속 거부"
    except TimeoutError:
        return "unknown", "127.0.0.1 접속 시간 초과"
    except OSError as exc:
        return "unknown", f"127.0.0.1 접속 확인 불가: {exc}"


def launchctl_service_state(target: str) -> str:
    code, output = run_result(["launchctl", "print", target], timeout_sec=3)
    if code == 0:
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if line.startswith("state = "):
                return f"loaded ({line.removeprefix('state = ')})"
        return "loaded"
    if "Could not find service" in output:
        return "not loaded"
    return f"unknown ({output.splitlines()[0] if output else 'no output'})"


def remote_management_pref_state() -> str:
    code, output = run_result(
        ["defaults", "read", "/Library/Preferences/com.apple.RemoteManagement"],
        timeout_sec=3,
    )
    if code == 0:
        return "exists"
    if "does not exist" in output:
        return "missing"
    return f"unknown ({output.splitlines()[0] if output else 'no output'})"


def screen_sharing_plist_disabled_state() -> str:
    if not SCREEN_SHARING_PLIST.exists():
        return "unknown (plist missing)"
    code, output = run_result(
        ["plutil", "-extract", "Disabled", "raw", "-o", "-", str(SCREEN_SHARING_PLIST)],
        timeout_sec=3,
    )
    if code == 0:
        return output.strip() or "unknown (empty plutil output)"
    return f"unknown ({output.splitlines()[0] if output else 'no output'})"


def build_screen_sharing_status() -> str:
    lsof_code, lsof_output = run_result(
        ["lsof", "-nP", f"-iTCP:{SCREEN_SHARING_PORT}", "-sTCP:LISTEN"],
        timeout_sec=3,
    )
    listener_lines = []
    if lsof_code == 0:
        listener_lines = [
            line
            for line in lsof_output.splitlines()
            if line.strip() and not line.startswith("COMMAND")
        ]
    port_state, probe_detail = probe_local_tcp_port(SCREEN_SHARING_PORT)
    screensharing_state = launchctl_service_state("system/com.apple.screensharing")
    remote_desktop_state = launchctl_service_state(
        f"gui/{os.getuid()}/com.apple.RemoteDesktop.agent"
    )
    plist_disabled_state = screen_sharing_plist_disabled_state()
    prefs_state = remote_management_pref_state()
    screensharing_not_loaded = screensharing_state == "not loaded"

    if listener_lines or port_state == "open":
        status = "리슨 중"
        reason = "화면공유/VNC 포트가 열려 있습니다."
    elif plist_disabled_state == "true" and screensharing_not_loaded:
        status = "리슨 안 함"
        reason = "macOS 화면 공유 launchd 항목이 비활성화되어 서비스가 로드되지 않았습니다."
    elif screensharing_not_loaded:
        status = "리슨 안 함"
        reason = "macOS 화면 공유 launchd 서비스가 로드되어 있지 않습니다."
    else:
        status = "리슨 안 함"
        reason = "포트 리스너가 확인되지 않았습니다. 서비스 상태나 권한 설정을 추가 확인해야 합니다."

    listener_detail = listener_lines[0] if listener_lines else "없음"
    return "\n".join(
        [
            "screen_sharing",
            f"port: {SCREEN_SHARING_PORT}",
            f"status: {status}",
            f"reason: {reason}",
            f"listener: {listener_detail}",
            f"tcp_probe: {port_state} ({probe_detail})",
            f"launchctl_screensharing: {screensharing_state}",
            f"launchctl_remote_desktop_agent: {remote_desktop_state}",
            f"screensharing_plist_disabled: {plist_disabled_state}",
            f"remote_management_pref: {prefs_state}",
            "enable_hint: 시스템 설정 > 일반 > 공유 > 화면 공유를 켜야 5900 포트가 열립니다.",
        ]
    )


def main() -> int:
    manager_status = run(
        [remote_manager_python(), str(APP_ROOT / "remote_manager.py"), "--status"]
    )
    dashboard_status = run(["zsh", "scripts/manage_process_control_launch_agent.sh", "status"])
    screen_sharing_status = build_screen_sharing_status()
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
                screen_sharing_status,
                "",
                f"dashboard_access_key_loaded: {access_key_loaded}",
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
