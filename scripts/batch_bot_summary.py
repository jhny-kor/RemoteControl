from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Any

import tomllib


REMOTE_ROOT = Path("/Users/plo/Documents/remoteBot")
BATCHBOT_DB = Path("/Users/plo/Documents/batchBot/data/batch_manager.sqlite3")
EVENT_LOG_PATH = REMOTE_ROOT / "logs" / "batch_job_results.jsonl"
CONFIG_PATH = REMOTE_ROOT / "config/projects.toml"


def load_batch_config() -> dict[str, Any]:
    raw = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return raw["projects"]["batch_bot"]


def load_batch_programs() -> dict[str, str]:
    managed = load_batch_config()["managed_programs"]
    return {str(name): str(description) for name, description in managed.items()}


def load_schedule_texts() -> dict[str, str]:
    schedules = load_batch_config().get("program_schedules", {})
    return {str(name): str(text) for name, text in schedules.items()}


def fetch_today_runs() -> dict[str, dict[str, Any]]:
    if not BATCHBOT_DB.exists():
        return {}

    today = datetime.now().date()
    start = f"{today.isoformat()}T00:00:00"
    end = f"{(today + timedelta(days=1)).isoformat()}T00:00:00"

    sql = """
        SELECT job_name, status, started_at, finished_at, exit_code
        FROM job_runs
        WHERE started_at >= ? AND started_at < ?
        ORDER BY started_at DESC
    """

    conn = sqlite3.connect(BATCHBOT_DB)
    try:
        rows = conn.execute(sql, (start, end)).fetchall()
    finally:
        conn.close()

    results: dict[str, dict[str, Any]] = {}
    for job_name, status, started_at, finished_at, exit_code in rows:
        if job_name not in results:
            results[job_name] = {
                "status": status,
                "started_at": started_at,
                "finished_at": finished_at,
                "exit_code": exit_code,
            }
    return results


def fetch_latest_remote_results() -> dict[str, dict[str, Any]]:
    if not EVENT_LOG_PATH.exists():
        return {}

    results: dict[str, dict[str, Any]] = {}
    for line in EVENT_LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        job_name = str(record.get("job_name", "")).strip()
        recorded_at = str(record.get("recorded_at", "")).strip()
        if not job_name or not recorded_at:
            continue
        current = results.get(job_name)
        if current is None or str(current.get("recorded_at", "")) <= recorded_at:
            results[job_name] = record
    return results


def format_run_text(run: dict[str, Any] | None) -> str:
    if not run:
        return "오늘 실행: 없음"

    started_at = str(run["started_at"]).replace("T", " ")
    status = str(run["status"])
    if status == "success":
        return f"오늘 실행: 성공 ({started_at})"
    exit_code = run["exit_code"]
    suffix = f", exit_code={exit_code}" if exit_code is not None else ""
    return f"오늘 실행: 실패 ({started_at}{suffix})"


def format_remote_result_text(result: dict[str, Any] | None) -> str:
    if not result:
        return "최근 결과 전송: 없음"

    finished_at = str(result.get("finished_at", "-")).replace("T", " ")
    status = str(result.get("status", "-"))
    exit_code = result.get("exit_code")
    exit_suffix = f", exit_code={exit_code}" if exit_code is not None else ""
    return f"최근 결과 전송: {status} ({finished_at}{exit_suffix})"


def build_summary(show_all: bool = False) -> str:
    programs = load_batch_programs()
    schedules = load_schedule_texts()
    today_runs = fetch_today_runs()
    latest_remote_results = fetch_latest_remote_results()

    lines = ["batch_bot 등록 자동화"]
    for name, description in sorted(programs.items()):
        if not show_all and name not in today_runs and name.startswith("automation-"):
            # 오늘 실행 내역이 없어도 설명이 필요한 자동화는 그대로 보여준다.
            pass
        lines.append(f"- {name}")
        lines.append(f"  설명: {description}")
        lines.append(f"  스케줄: {schedules.get(name, '-')}")
        lines.append(f"  {format_run_text(today_runs.get(name))}")
        lines.append(f"  {format_remote_result_text(latest_remote_results.get(name))}")

    if show_all and today_runs:
        extra = sorted(set(today_runs) - set(programs))
        if extra:
            lines.append("")
            lines.append("기타 오늘 실행 이력")
            for name in extra:
                lines.append(f"- {name}")
                lines.append(f"  스케줄: {schedules.get(name, '-')}")
                lines.append(f"  {format_run_text(today_runs.get(name))}")
                lines.append(f"  {format_remote_result_text(latest_remote_results.get(name))}")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="batch_bot 등록 목록과 오늘 실행 여부 요약")
    parser.add_argument("--all", action="store_true", help="등록 목록 외 오늘 실행된 기타 job 도 함께 표시")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(build_summary(show_all=args.all))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
