#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from remote_manager import APP_ROOT
from remote_manager import load_bot_token
from remote_manager import load_config
from remote_manager import send_broadcast_message
from remote_manager import send_imessage_broadcast

EVENT_LOG_PATH = APP_ROOT / "logs" / "batch_job_results.jsonl"
SUMMARY_PREFIXES = (
    "[OK]",
    "[FAIL]",
    "[SKIP]",
    "[압축 완료]",
    "압축 묶음 수:",
    "압축 파일 수:",
    "원본 총 크기:",
    "압축 총 크기:",
    "절감 크기:",
    "정리한 빈 폴더 수:",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Receive batchBot job results and forward them through remoteBot.")
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--display-name", default="")
    parser.add_argument("--status", required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--finished-at", required=True)
    parser.add_argument("--trigger", required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--log-path", required=True)
    parser.add_argument("--command", required=True)
    return parser.parse_args()


def append_event(record: dict[str, object]) -> None:
    EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def build_message(record: dict[str, object]) -> str:
    title = str(record.get("display_name") or record["job_name"])
    status = str(record["status"])
    exit_code = int(record["exit_code"])
    icon = "OK" if status == "success" else "FAIL"
    lines = [
        f"[batchBot] {icon} {title}",
        f"job: {record['job_name']}",
        f"trigger: {record['trigger']} / attempt: {record['attempt']}",
        f"exit: {exit_code}",
        f"started: {record['started_at']}",
        f"finished: {record['finished_at']}",
    ]
    log_path = str(record.get("log_path", "")).strip()
    if log_path:
        lines.append(f"log: {log_path}")
        summary_lines = extract_log_summary(Path(log_path))
        if summary_lines:
            lines.append("summary:")
            lines.extend(summary_lines)
    return "\n".join(lines)


def extract_log_summary(log_path: Path) -> list[str]:
    if not log_path.exists():
        return []

    try:
        raw_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    picked: list[str] = []
    for line in reversed(raw_lines):
        text = line.strip()
        if not text:
            continue
        if text.startswith(SUMMARY_PREFIXES):
            picked.append(text)
        if len(picked) >= 6:
            break
    return [f"  {line}" for line in reversed(picked)]


def main() -> int:
    args = parse_args()
    record = {
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "job_name": args.job_name,
        "display_name": args.display_name,
        "status": args.status,
        "exit_code": args.exit_code,
        "started_at": args.started_at,
        "finished_at": args.finished_at,
        "trigger": args.trigger,
        "attempt": args.attempt,
        "log_path": args.log_path,
        "command": args.command,
    }
    append_event(record)

    config = load_config(APP_ROOT / "config/projects.toml")
    bot_token = load_bot_token(config)
    message = build_message(record)
    if bot_token and config.telegram.allowed_chat_ids:
        send_broadcast_message(bot_token, config.telegram.allowed_chat_ids, message)
    if config.imessage.enabled and config.imessage.recipients:
        send_imessage_broadcast(config.imessage.recipients, message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
