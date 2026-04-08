from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
import html
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import signal
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlencode, urlparse


APP_ROOT = Path("/Users/plo/Documents/remoteBot")
AUTO_COIN_ROOT = Path("/Users/plo/Documents/auto_coin_bot")
AUTO_COIN_BACKTEST_ROOT = AUTO_COIN_ROOT / "reports/backtest_batches"
AUTO_COIN_SWING_ROOT = Path("/Users/plo/Documents/auto_coin_bot_swing")
AUTO_STOCK_ROOT = Path("/Users/plo/Documents/auto_stock_bot")
AUTO_STOCK_SRC = AUTO_STOCK_ROOT / "src"
if str(AUTO_STOCK_SRC) not in sys.path:
    sys.path.insert(0, str(AUTO_STOCK_SRC))
BIND_HOST = "0.0.0.0"
LOCAL_URL_HOST = "127.0.0.1"
PORT = 8765
PID_PATH = APP_ROOT / "logs/process_control_server.pid"
SERVER_LOG_PATH = APP_ROOT / "logs/process_control_server.log"
OUT_PATH = APP_ROOT / "logs/process_control_server.out"
ACCESS_KEY_PATH = APP_ROOT / "logs/process_control_access_key.txt"
ACCESS_COOKIE_NAME = "remotebot_access"
TOOL_RUN_LOG_DIR = APP_ROOT / "logs" / "tool_runs"
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
MAX_LOG_LINES = 120
BACKTEST_SUMMARY_FILENAMES = {"batch_summary.md", "diff_summary.md"}
RECENT_BACKTEST_SUMMARY_LIMIT = 6


@dataclass(frozen=True)
class CommandSpec:
    cwd: Path
    argv: list[str]


@dataclass(frozen=True)
class ProgramStatus:
    name: str
    state: str
    detail: str
    target_key: str | None = None
    controllable: bool = False
    manual_runnable: bool = False


@dataclass(frozen=True)
class ToolAction:
    key: str
    label: str
    description: str
    command: CommandSpec


@dataclass(frozen=True)
class RegimeEntry:
    exchange: str
    symbol: str
    regime: str
    stage_text: str
    meaning: str
    reason: str
    volume_ratio: str
    avg_abs_change_pct: str
    gap_pct: str
    rsi: str
    adx: str
    recorded_at_local: str | None = None


@dataclass(frozen=True)
class ServiceStatus:
    key: str
    group: str
    title: str
    subtitle: str
    state: str
    detail: str
    programs: list[ProgramStatus]


@dataclass(frozen=True)
class ServiceSpec:
    key: str
    group: str
    title: str
    subtitle: str
    status_command: CommandSpec
    programs_command: CommandSpec | None
    start_command: CommandSpec
    stop_command: CommandSpec
    expected_running_sections: int


REGIME_STAGE_SEQUENCE: tuple[str, ...] = (
    "LOW_ENERGY",
    "CHOPPY_LOW_VOL",
    "CHOPPY_HIGH_VOL",
    "BREAKOUT_ATTEMPT",
    "TRENDING_EARLY",
    "TRENDING_MATURE",
    "EXHAUSTION_RISK",
    "OVERHEATED",
)


SERVICES = [
    ServiceSpec(
        key="remote_manager",
        group="manage",
        title="원격 매니저",
        subtitle="텔레그램 원격 제어 매니저",
        status_command=CommandSpec(
            cwd=APP_ROOT,
            argv=[sys.executable, str(APP_ROOT / "remote_manager.py"), "--status"],
        ),
        programs_command=None,
        start_command=CommandSpec(
            cwd=APP_ROOT,
            argv=[sys.executable, str(APP_ROOT / "remote_manager.py"), "--daemon"],
        ),
        stop_command=CommandSpec(
            cwd=APP_ROOT,
            argv=[sys.executable, str(APP_ROOT / "remote_manager.py"), "--stop"],
        ),
        expected_running_sections=1,
    ),
    ServiceSpec(
        key="auto_coin_bot",
        group="coin",
        title="Short",
        subtitle="auto_coin_bot 단기 코인 자동매매",
        status_command=CommandSpec(
            cwd=AUTO_COIN_ROOT,
            argv=[str(AUTO_COIN_ROOT / ".venv/bin/python"), "bot_manager.py", "status"],
        ),
        programs_command=None,
        start_command=CommandSpec(
            cwd=AUTO_COIN_ROOT,
            argv=[str(AUTO_COIN_ROOT / ".venv/bin/python"), "bot_manager.py", "start", "all"],
        ),
        stop_command=CommandSpec(
            cwd=AUTO_COIN_ROOT,
            argv=[str(AUTO_COIN_ROOT / ".venv/bin/python"), "bot_manager.py", "stop", "all"],
        ),
        expected_running_sections=6,
    ),
    ServiceSpec(
        key="auto_coin_bot_swing",
        group="coin",
        title="Long",
        subtitle="auto_coin_bot_swing 스윙 코인 자동매매",
        status_command=CommandSpec(
            cwd=AUTO_COIN_SWING_ROOT,
            argv=[str(AUTO_COIN_SWING_ROOT / ".venv/bin/python"), "bot_manager.py", "status"],
        ),
        programs_command=None,
        start_command=CommandSpec(
            cwd=AUTO_COIN_SWING_ROOT,
            argv=[str(AUTO_COIN_SWING_ROOT / ".venv/bin/python"), "bot_manager.py", "start", "all"],
        ),
        stop_command=CommandSpec(
            cwd=AUTO_COIN_SWING_ROOT,
            argv=[str(AUTO_COIN_SWING_ROOT / ".venv/bin/python"), "bot_manager.py", "stop", "all"],
        ),
        expected_running_sections=3,
    ),
    ServiceSpec(
        key="auto_stock_bot",
        group="stock",
        title="가치투자",
        subtitle="한국주식 자동매매/분석 수집기",
        status_command=CommandSpec(
            cwd=AUTO_STOCK_ROOT,
            argv=[str(AUTO_STOCK_ROOT / ".venv/bin/python"), "bot_manager.py", "status"],
        ),
        programs_command=None,
        start_command=CommandSpec(
            cwd=AUTO_STOCK_ROOT,
            argv=[str(AUTO_STOCK_ROOT / ".venv/bin/python"), "bot_manager.py", "start", "all"],
        ),
        stop_command=CommandSpec(
            cwd=AUTO_STOCK_ROOT,
            argv=[str(AUTO_STOCK_ROOT / ".venv/bin/python"), "bot_manager.py", "stop", "all"],
        ),
        expected_running_sections=1,
    ),
    ServiceSpec(
        key="batch_bot",
        group="manage",
        title="배치 메니저",
        subtitle="Codex 자동화와 로컬 jobs 실행 배치 매니저",
        status_command=CommandSpec(
            cwd=Path("/Users/plo/Documents/batchBot"),
            argv=["zsh", "scripts/manage_launch_agent.sh", "status"],
        ),
        programs_command=CommandSpec(
            cwd=APP_ROOT,
            argv=[sys.executable, str(APP_ROOT / "scripts/batch_bot_summary.py")],
        ),
        start_command=CommandSpec(
            cwd=Path("/Users/plo/Documents/batchBot"),
            argv=["zsh", "scripts/manage_launch_agent.sh", "reload"],
        ),
        stop_command=CommandSpec(
            cwd=Path("/Users/plo/Documents/batchBot"),
            argv=["zsh", "scripts/manage_launch_agent.sh", "stop"],
        ),
        expected_running_sections=1,
    ),
]


PROGRAM_TITLES: dict[str, dict[str, str]] = {
    "batch_bot": {
        "automation-2": "오늘의 공모주",
        "automation-3": "금주의 공모주",
        "daily-auto-coin-log-archive": "Coin Short Log Manager",
        "daily-auto-stock-log-archive": "Stock Log Archive",
        "daily-swing-log-archive": "Coin Long Log Manager",
    },
}


def load_literal_dict(path: Path, variable_name: str) -> dict[str, str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        return {}

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == variable_name:
                try:
                    value = ast.literal_eval(node.value)
                except Exception:
                    return {}
                if isinstance(value, dict):
                    return {
                        str(key): str(item)
                        for key, item in value.items()
                    }
    return {}


def build_swing_titles() -> dict[str, str]:
    programs = load_literal_dict(AUTO_COIN_SWING_ROOT / "bot_manager.py", "PROGRAMS")
    if not programs:
        return {
            "okx": "OKX 스윙 봇",
            "upbit": "업비트 스윙 봇",
            "collector": "분석 수집기",
        }

    titles: dict[str, str] = {}
    for key in programs:
        if key == "okx":
            titles[key] = "OKX 스윙 봇"
        elif key == "upbit":
            titles[key] = "업비트 스윙 봇"
        elif key == "collector":
            titles[key] = "분석 수집기"
        else:
            titles[key] = key.replace("_", " ").title()
    return titles


def load_auto_coin_titles() -> dict[str, str]:
    registry_path = AUTO_COIN_ROOT / "core" / "runtime" / "program_registry.py"
    try:
        spec = importlib.util.spec_from_file_location("auto_coin_program_registry", registry_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("spec load failed")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        titles = getattr(module, "PROGRAM_TITLES", {})
        if isinstance(titles, dict):
            return {str(key): str(value) for key, value in titles.items()}
    except Exception:
        pass

    return {
        "okx": "OKX 봇",
        "upbit": "업비트 봇",
        "okx_btc": "OKX BTC EMA 봇",
        "upbit_btc": "업비트 BTC EMA 봇",
        "collector": "분석 수집기",
        "upbit_stream": "업비트 웹소켓 수집기",
        "telegram": "텔레그램 명령 리스너",
    }


PROGRAM_TITLES.update(
    {
        "auto_coin_bot": load_auto_coin_titles(),
        "auto_coin_bot_swing": build_swing_titles(),
        "auto_stock_bot": load_literal_dict(AUTO_STOCK_ROOT / "bot_manager.py", "SECTION_TITLES"),
    }
)


SERVICE_TOOLS: dict[str, list[ToolAction]] = {
    "auto_coin_bot": [
        ToolAction(
            key="weekly_backtest_report",
            label="주간 백테스트 실행",
            description="관리 심볼 기준 최근 7일 배치 백테스트와 비교 요약을 생성합니다.",
            command=CommandSpec(
                cwd=AUTO_COIN_ROOT,
                argv=[str(AUTO_COIN_ROOT / ".venv/bin/python"), "backtest_report_runner.py", "weekly"],
            ),
        ),
    ],
    "auto_stock_bot": [
        ToolAction(
            key="daily_data_pipeline",
            label="데일리 데이터 파이프라인",
            description="수집, 리포트, 스크리너, 로그 정리를 한 번에 수행합니다.",
            command=CommandSpec(
                cwd=AUTO_STOCK_ROOT,
                argv=[str(AUTO_STOCK_ROOT / ".venv/bin/python"), "scripts/daily_data_pipeline.py"],
            ),
        ),
        ToolAction(
            key="news_check",
            label="뉴스 점검",
            description="관심 종목 기준 최근 뉴스를 수동으로 조회합니다.",
            command=CommandSpec(
                cwd=AUTO_STOCK_ROOT,
                argv=[str(AUTO_STOCK_ROOT / ".venv/bin/python"), "scripts/news_check.py"],
            ),
        ),
        ToolAction(
            key="disclosure_check",
            label="공시 점검",
            description="관심 종목의 최근 OpenDART 공시를 한 번 조회합니다.",
            command=CommandSpec(
                cwd=AUTO_STOCK_ROOT,
                argv=[str(AUTO_STOCK_ROOT / ".venv/bin/python"), "scripts/disclosure_check.py"],
            ),
        ),
        ToolAction(
            key="stock_analysis_report",
            label="분석 리포트 생성",
            description="최신 분석 로그 기준 리포트를 만들고 reports 폴더에 저장합니다.",
            command=CommandSpec(
                cwd=AUTO_STOCK_ROOT,
                argv=[str(AUTO_STOCK_ROOT / ".venv/bin/python"), "scripts/stock_analysis_report.py", "--write"],
            ),
        ),
        ToolAction(
            key="value_recovery_screener",
            label="가치 회복 스크리너",
            description="최신 데이터 기준 스크리닝 리포트를 만들고 저장합니다.",
            command=CommandSpec(
                cwd=AUTO_STOCK_ROOT,
                argv=[str(AUTO_STOCK_ROOT / ".venv/bin/python"), "scripts/value_recovery_screener.py", "--write"],
            ),
        ),
        ToolAction(
            key="ipo_schedule_check",
            label="공모주 일정 점검",
            description="공모주 일정 데이터를 조회해 현재 일정을 확인합니다.",
            command=CommandSpec(
                cwd=AUTO_STOCK_ROOT,
                argv=[str(AUTO_STOCK_ROOT / ".venv/bin/python"), "scripts/ipo_schedule_check.py"],
            ),
        ),
    ],
}


class AppState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.message = ""

    def set_message(self, message: str) -> None:
        with self.lock:
            self.message = message

    def pop_message(self) -> str:
        with self.lock:
            value = self.message
            self.message = ""
            return value


STATE = AppState()


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_access_key() -> str:
    ACCESS_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ACCESS_KEY_PATH.exists():
        key = ACCESS_KEY_PATH.read_text(encoding="utf-8").strip()
        if key:
            return key

    key = secrets.token_urlsafe(24)
    ACCESS_KEY_PATH.write_text(key, encoding="utf-8")
    return key


ACCESS_KEY = ensure_access_key()


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def is_loopback_client(host: str) -> bool:
    return host in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def parse_cookie_header(raw_cookie: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for chunk in raw_cookie.split(";"):
        item = chunk.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        cookies[key.strip()] = value.strip()
    return cookies


def check_request_authorization(handler: BaseHTTPRequestHandler) -> tuple[bool, bool]:
    client_host = handler.client_address[0]
    if is_loopback_client(client_host):
        return True, False

    parsed = urlparse(handler.path)
    query = parse_qs(parsed.query)
    if query.get("key", [""])[0] == ACCESS_KEY:
        return True, True

    cookies = parse_cookie_header(handler.headers.get("Cookie", ""))
    if cookies.get(ACCESS_COOKIE_NAME) == ACCESS_KEY:
        return True, False

    return False, False


def append_server_log(message: str) -> None:
    SERVER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SERVER_LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(f"[{now_text()}] {message}\n")


def read_env_file_values(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


@contextmanager
def temporary_env_override(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = value
        yield
    finally:
        for key, old_value in previous.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def send_autostock_tool_telegram(text: str) -> None:
    try:
        from autostocktrading.notifications import load_telegram_notifier
    except Exception as exc:
        append_server_log(f"가치투자 텔레그램 모듈 로드 실패: {exc}")
        return

    try:
        with temporary_env_override(read_env_file_values(AUTO_STOCK_ROOT / ".env")):
            notifier = load_telegram_notifier()
            if not notifier.enabled:
                append_server_log("가치투자 텔레그램 알림 비활성화")
                return
            sent, error = notifier.send_message_chunks(text)
            if not sent:
                append_server_log(f"가치투자 텔레그램 전송 실패: {error or '-'}")
    except Exception as exc:
        append_server_log(f"가치투자 텔레그램 전송 예외: {exc}")


def send_autostock_tool_documents(tool_label: str, paths: list[Path]) -> None:
    try:
        from autostocktrading.notifications import load_telegram_notifier
    except Exception as exc:
        append_server_log(f"가치투자 문서 전송 모듈 로드 실패: {exc}")
        return

    try:
        with temporary_env_override(read_env_file_values(AUTO_STOCK_ROOT / ".env")):
            notifier = load_telegram_notifier()
            if not notifier.enabled:
                append_server_log("가치투자 텔레그램 문서 전송 비활성화")
                return

            for index, path in enumerate(paths, start=1):
                caption = f"[가치투자 도구 결과] {tool_label} ({index}/{len(paths)})"
                sent, error = notifier.send_document(str(path), caption=caption)
                if not sent:
                    append_server_log(f"가치투자 문서 전송 실패: {path} | {error or '-'}")
    except Exception as exc:
        append_server_log(f"가치투자 문서 전송 예외: {exc}")


def snapshot_report_files() -> dict[Path, int]:
    report_root = AUTO_STOCK_ROOT / "reports"
    snapshots: dict[Path, int] = {}
    if not report_root.exists():
        return snapshots

    for path in report_root.rglob("*.md"):
        try:
            snapshots[path] = path.stat().st_mtime_ns
        except OSError:
            continue
    return snapshots


def collect_changed_report_files(before: dict[Path, int]) -> list[Path]:
    after = snapshot_report_files()
    changed = [
        path
        for path, mtime in after.items()
        if before.get(path, 0) < mtime
    ]
    return sorted(changed)


def list_backtest_summaries(limit: int | None = None) -> list[Path]:
    """배치 백테스트 요약 Markdown 파일 목록을 최신순으로 돌려준다."""
    if not AUTO_COIN_BACKTEST_ROOT.exists():
        return []

    candidates: list[tuple[int, Path]] = []
    for path in AUTO_COIN_BACKTEST_ROOT.rglob("*.md"):
        if path.name not in BACKTEST_SUMMARY_FILENAMES:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        candidates.append((stat.st_mtime_ns, path))

    if not candidates:
        return []
    candidates.sort(key=lambda item: item[0], reverse=True)
    ordered = [path for _, path in candidates]
    if limit is not None:
        return ordered[:limit]
    return ordered


def find_latest_backtest_summary() -> Path | None:
    """가장 최근 배치 백테스트 요약 Markdown 파일을 찾는다."""
    summaries = list_backtest_summaries(limit=1)
    return summaries[0] if summaries else None


def find_latest_batch_summary_md() -> Path | None:
    """주간/스냅샷 배치의 batch_summary.md 중 가장 최근 파일을 찾는다."""
    if not AUTO_COIN_BACKTEST_ROOT.exists():
        return None
    candidates: list[tuple[int, Path]] = []
    for path in AUTO_COIN_BACKTEST_ROOT.rglob("batch_summary.md"):
        try:
            stat = path.stat()
        except OSError:
            continue
        candidates.append((stat.st_mtime_ns, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def list_pending_backtest_batches(limit: int | None = None) -> list[tuple[Path, str, int]]:
    """요약 Markdown 이 아직 없는 최근 배치 디렉터리를 반환한다."""
    if not AUTO_COIN_BACKTEST_ROOT.exists():
        return []

    now = datetime.now().timestamp()
    rows: list[tuple[int, Path, str, int]] = []
    for child in AUTO_COIN_BACKTEST_ROOT.iterdir():
        if not child.is_dir():
            continue
        has_summary = any(
            path.is_file() and path.name in BACKTEST_SUMMARY_FILENAMES
            for path in child.rglob("*.md")
        )
        if has_summary:
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        results_dir = child / "results"
        result_count = sum(1 for path in results_dir.iterdir() if path.is_dir()) if results_dir.exists() else 0
        age_seconds = max(0, int(now - stat.st_mtime))
        state = "진행 중" if age_seconds < 1800 else "확인 필요"
        rows.append((stat.st_mtime_ns, child, state, result_count))

    rows.sort(key=lambda item: item[0], reverse=True)
    ordered = [(path, state, result_count) for _, path, state, result_count in rows]
    if limit is not None:
        return ordered[:limit]
    return ordered


def resolve_backtest_batch_dir(relative_path: str) -> Path | None:
    """쿼리 문자열에서 받은 상대 경로를 안전하게 실제 배치 디렉터리로 해석한다."""
    candidate = relative_path.strip()
    if not candidate:
        return None
    try:
        resolved = (AUTO_COIN_ROOT / candidate).resolve()
    except OSError:
        return None
    try:
        resolved.relative_to(AUTO_COIN_BACKTEST_ROOT)
    except ValueError:
        return None
    if not resolved.is_dir():
        return None
    return resolved


def delete_pending_backtest_batch(relative_path: str) -> str:
    """요약 파일이 없는 확인 필요 배치를 삭제한다."""
    batch_dir = resolve_backtest_batch_dir(relative_path)
    if batch_dir is None:
        return "삭제 대상 배치를 찾지 못했습니다."

    has_summary = any(
        path.is_file() and path.name in BACKTEST_SUMMARY_FILENAMES
        for path in batch_dir.rglob("*.md")
    )
    if has_summary:
        return "요약 파일이 이미 생성된 배치는 삭제할 수 없습니다."

    try:
        shutil.rmtree(batch_dir)
    except OSError as exc:
        append_server_log(f"백테스트 배치 삭제 실패: path={batch_dir} error={exc}")
        return f"배치 삭제에 실패했습니다: {exc}"

    append_server_log(f"백테스트 배치 삭제 완료: path={batch_dir}")
    return f"{batch_dir.name} 배치를 삭제했습니다."


def resolve_backtest_summary(relative_path: str) -> Path | None:
    """쿼리 문자열에서 받은 상대 경로를 안전하게 실제 파일로 해석한다."""
    candidate = relative_path.strip()
    if not candidate:
        return None
    try:
        resolved = (AUTO_COIN_ROOT / candidate).resolve()
    except OSError:
        return None
    try:
        resolved.relative_to(AUTO_COIN_BACKTEST_ROOT)
    except ValueError:
        return None
    if resolved.name not in BACKTEST_SUMMARY_FILENAMES or not resolved.is_file():
        return None
    return resolved


def build_backtest_summary_href(summary_path: Path, *, download: bool = False) -> str:
    """요약 파일 보기/다운로드 링크를 만든다."""
    relative_path = summary_path.relative_to(AUTO_COIN_ROOT).as_posix()
    base = "/backtest-summary/download" if download else "/backtest-summary"
    return f"{base}?path={quote(relative_path, safe='/')}"


def render_backtest_summary_page(
    summary_path: Path, *, show_completed_banner: bool = False
) -> bytes:
    """백테스트 요약 Markdown 전문 페이지를 렌더링한다."""
    text = summary_path.read_text(encoding="utf-8")
    relative_path = summary_path.relative_to(AUTO_COIN_ROOT)
    completed_block = ""
    if show_completed_banner:
        completed_block = """
    <div class="done-banner" role="status">
      웹에서 실행한 주간 백테스트가 완료되었습니다. 아래 요약이 방금 생성된 결과입니다.
    </div>
"""
    page = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#1f7a49">
  <title>백테스트 요약</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="shortcut icon" href="/favicon.svg" type="image/svg+xml">
  <style>
    :root {{
      --bg: #efe7dc;
      --card: #fbf8f3;
      --text: #1f1a17;
      --muted: #625b53;
      --line: #ddd2c2;
      --green: #1f7a49;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif;
      background: radial-gradient(circle at top left, #f5eee5 0%, var(--bg) 45%, #eadfcf 100%);
      color: var(--text);
    }}
    .wrap {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 28px 20px 40px;
    }}
    .card {{
      background: var(--card);
      border-radius: 20px;
      padding: 22px;
      box-shadow: 0 10px 30px rgba(48, 35, 18, 0.08);
    }}
    .done-banner {{
      margin: 0 0 16px;
      padding: 12px 16px;
      border-radius: 14px;
      background: #e8f5ec;
      border: 1px solid #b8dcc4;
      color: #134d2a;
      font-size: 14px;
      font-weight: 600;
      line-height: 1.5;
    }}
    h1 {{
      margin: 0;
      font-size: 30px;
      letter-spacing: -0.03em;
    }}
    .meta {{
      margin: 8px 0 18px;
      color: var(--muted);
      font-size: 14px;
    }}
    .actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 18px;
    }}
    a {{
      border-radius: 12px;
      padding: 10px 14px;
      font-size: 14px;
      font-weight: 700;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .primary {{
      background: var(--green);
      color: white;
    }}
    .ghost {{
      background: #e6dccf;
      color: #2f2a25;
    }}
    pre {{
      margin: 0;
      padding: 18px;
      border-radius: 16px;
      background: #f6f0e7;
      border: 1px solid var(--line);
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.6;
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
{completed_block}
      <h1>백테스트 요약</h1>
      <p class="meta">{html.escape(str(relative_path))}</p>
      <div class="actions">
        <a class="ghost" href="/">메인으로</a>
        <a class="ghost" href="/backtest-summaries">목록 보기</a>
        <a class="primary" href="{html.escape(build_backtest_summary_href(summary_path, download=True))}">다운로드</a>
      </div>
      <pre>{html.escape(text)}</pre>
    </div>
  </div>
</body>
</html>
"""
    return page.encode("utf-8")


def render_backtest_summary_list_page(summary_paths: list[Path]) -> bytes:
    """백테스트 요약 목록 페이지를 렌더링한다."""
    pending_batches = list_pending_backtest_batches(limit=10)
    pending_html = ""
    if pending_batches:
        pending_items = []
        for path, state, result_count in pending_batches:
            relative_path = path.relative_to(AUTO_COIN_ROOT).as_posix()
            delete_form = ""
            if state == "확인 필요":
                delete_form = f"""
                <form method="post" action="/delete-backtest-batch">
                  <input type="hidden" name="batch_path" value="{html.escape(relative_path)}">
                  <button type="submit" class="danger">삭제</button>
                </form>
                """
            pending_items.append(
                f"""
                <li class="summary-row pending-row">
                  <div class="summary-copy">
                    <strong>{html.escape(path.name)}</strong>
                    <span>{html.escape(relative_path)}</span>
                  </div>
                  <div class="summary-actions pending-actions">
                    <span class="pending-badge">{html.escape(state)}</span>
                    <span class="pending-note">생성된 결과 디렉터리 {result_count}개</span>
                    {delete_form}
                  </div>
                </li>
                """
            )
        pending_html = (
            '<section class="pending-section">'
            '<h2>진행 중 또는 요약 미생성 배치</h2>'
            '<p class="meta">batch_summary.md 또는 diff_summary.md 가 아직 생성되지 않은 최근 실행입니다.</p>'
            f'<ul class="summary-list">{"".join(pending_items)}</ul>'
            '</section>'
        )

    if summary_paths:
        items = []
        for path in summary_paths:
            relative_path = path.relative_to(AUTO_COIN_ROOT).as_posix()
            items.append(
                f"""
                <li class="summary-row">
                  <div class="summary-copy">
                    <strong>{html.escape(path.parent.name)}</strong>
                    <span>{html.escape(relative_path)}</span>
                  </div>
                  <div class="summary-actions">
                    <a class="ghost" href="{html.escape(build_backtest_summary_href(path))}" target="_blank" rel="noopener">전체 보기</a>
                    <a class="primary" href="{html.escape(build_backtest_summary_href(path, download=True))}">다운로드</a>
                  </div>
                </li>
                """
            )
        list_html = f'<ul class="summary-list">{"".join(items)}</ul>'
    else:
        list_html = '<p class="empty-text">표시할 백테스트 요약이 없습니다.</p>'

    page = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#1f7a49">
  <title>백테스트 요약 목록</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="shortcut icon" href="/favicon.svg" type="image/svg+xml">
  <style>
    :root {{
      --bg: #efe7dc;
      --card: #fbf8f3;
      --text: #1f1a17;
      --muted: #625b53;
      --line: #ddd2c2;
      --green: #1f7a49;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif;
      background: radial-gradient(circle at top left, #f5eee5 0%, var(--bg) 45%, #eadfcf 100%);
      color: var(--text);
    }}
    .wrap {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 28px 20px 40px;
    }}
    .card {{
      background: var(--card);
      border-radius: 20px;
      padding: 22px;
      box-shadow: 0 10px 30px rgba(48, 35, 18, 0.08);
    }}
    h1 {{
      margin: 0;
      font-size: 30px;
      letter-spacing: -0.03em;
    }}
    .meta {{
      margin: 8px 0 18px;
      color: var(--muted);
      font-size: 14px;
    }}
    .summary-list {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 10px;
    }}
    .pending-section {{
      margin-bottom: 22px;
      display: grid;
      gap: 10px;
    }}
    h2 {{
      margin: 0;
      font-size: 20px;
      letter-spacing: -0.02em;
    }}
    .summary-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #f7f0e6;
      padding: 12px 14px;
    }}
    .summary-copy {{
      display: grid;
      gap: 4px;
      min-width: 0;
    }}
    .summary-copy strong {{
      font-size: 14px;
    }}
    .summary-copy span {{
      color: var(--muted);
      font-size: 13px;
      word-break: break-word;
    }}
    .summary-actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .pending-row {{
      background: #f3eadf;
    }}
    .pending-actions {{
      align-items: flex-end;
      flex-direction: column;
    }}
    .pending-badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 78px;
      padding: 7px 10px;
      border-radius: 999px;
      background: #efe4b7;
      color: #7a5d00;
      font-size: 12px;
      font-weight: 800;
    }}
    .pending-note {{
      color: var(--muted);
      font-size: 12px;
    }}
    a {{
      border-radius: 12px;
      padding: 10px 14px;
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .primary {{
      background: var(--green);
      color: white;
    }}
    .ghost {{
      background: #e6dccf;
      color: #2f2a25;
    }}
    .danger {{
      border: 0;
      border-radius: 12px;
      padding: 10px 14px;
      font-size: 13px;
      font-weight: 700;
      background: #a33b3b;
      color: white;
      cursor: pointer;
    }}
    .top-actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 18px;
    }}
    .empty-text {{
      margin: 0;
      color: var(--muted);
      line-height: 1.6;
    }}
    @media (max-width: 720px) {{
      .summary-row {{
        grid-template-columns: minmax(0, 1fr);
      }}
      .summary-actions {{
        justify-content: flex-start;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>백테스트 요약 목록</h1>
      <p class="meta">최근 생성된 batch_summary.md, diff_summary.md 파일을 최신순으로 표시합니다.</p>
      <div class="top-actions">
        <a class="ghost" href="/">메인으로</a>
      </div>
      {pending_html}
      {list_html}
    </div>
  </div>
</body>
</html>
"""
    return page.encode("utf-8")


def tail_server_log(limit: int = 30) -> str:
    if not SERVER_LOG_PATH.exists():
        return ""
    lines = SERVER_LOG_PATH.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-limit:])


def run_command(command: CommandSpec, timeout_sec: int = 90) -> tuple[bool, str]:
    completed = subprocess.run(
        command.argv,
        cwd=command.cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    output = strip_ansi((completed.stdout or "").strip())
    return completed.returncode == 0, output


def parse_service_state(service: ServiceSpec, output: str) -> str:
    clean = strip_ansi(output)

    if service.key == "remote_manager":
        if "remote_manager 상태: running" in clean:
            return "running"
        if "remote_manager 상태: stopped" in clean:
            return "stopped"
        return "error"

    if service.key == "batch_bot":
        if "state = running" in clean:
            return "running"
        if "state = spawn scheduled" in clean or "state = waiting" in clean:
            return "idle"
        if "LaunchAgent is not currently loaded" in clean:
            return "stopped"
        if "state =" in clean:
            return "partial"
        return "error"

    if service.key == "auto_coin_bot_swing":
        programs = parse_swing_bot_programs(clean)
        if not programs:
            return "error"
        running_count = sum(item.state == "running" for item in programs)
        stopped_count = sum(item.state == "stopped" for item in programs)

        if running_count == len(programs):
            return "running"
        if stopped_count == len(programs):
            return "stopped"
        if running_count > 0:
            return "partial"
        return "error"

    if service.key in {"auto_coin_bot", "auto_stock_bot"}:
        programs = parse_bot_manager_programs(service.key, clean)
        if not programs:
            return "error"
        running_count = sum(item.state == "running" for item in programs)
        stopped_count = sum(item.state == "stopped" for item in programs)

        if running_count == len(programs):
            return "running"
        if stopped_count == len(programs):
            return "stopped"
        if running_count > 0:
            return "partial"
        return "error"

    status_lines = [
        line.strip()
        for line in clean.splitlines()
        if "상태:" in line
    ]
    running_count = sum("실행 중" in line for line in status_lines)
    stopped_count = sum("중지됨" in line for line in status_lines)

    if running_count == service.expected_running_sections:
        return "running"
    if stopped_count == service.expected_running_sections:
        return "stopped"
    if running_count > 0:
        return "partial"
    return "error"


def summarize_remote_manager(output: str) -> str:
    clean = strip_ansi(output)
    if "remote_manager 상태: running" in clean:
        return "텔레그램 원격 제어가 실행 중입니다."
    if "remote_manager 상태: stopped" in clean:
        return "텔레그램 원격 제어가 중지되어 있습니다."
    return "원격 제어 상태 확인이 필요합니다."


def summarize_batch_manager(output: str) -> str:
    clean = strip_ansi(output)
    state = "-"

    for line in clean.splitlines():
        stripped = line.strip()
        if state == "-" and stripped.startswith("state ="):
            state = stripped.split("=", 1)[1].strip()

    if state == "-" and "LaunchAgent is not currently loaded" in clean:
        return "LaunchAgent 미적재 상태"
    if state == "running":
        return "배치 매니저가 실행 중입니다."
    if state in {"spawn scheduled", "waiting"}:
        return "배치 매니저가 다음 실행을 대기 중입니다."
    if state != "-":
        return f"배치 매니저 상태: {state}"
    return "배치 매니저 상태 확인이 필요합니다."


def extract_batch_latest_run_text(output: str) -> str | None:
    latest_text: str | None = None
    latest_stamp = ""

    for raw_line in strip_ansi(output).splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("오늘 실행:"):
            continue
        if "(" not in stripped or ")" not in stripped:
            continue

        inner = stripped.split("(", 1)[1].rsplit(")", 1)[0].strip()
        timestamp = inner.split(",", 1)[0].strip()
        if not timestamp or timestamp == "없음":
            continue

        sortable = timestamp.replace(" ", "T")
        if sortable >= latest_stamp:
            latest_stamp = sortable
            latest_text = timestamp

    return latest_text


def extract_batch_schedule_summary(output: str) -> str | None:
    schedules: list[str] = []

    for raw_line in strip_ansi(output).splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("스케줄:"):
            continue
        schedule = stripped.split(":", 1)[1].strip()
        if schedule and schedule != "-" and schedule not in schedules:
            schedules.append(schedule)

    if not schedules:
        return None
    return " / ".join(schedules)


def summarize_bot_manager(service_key: str, output: str) -> str:
    clean = strip_ansi(output)
    programs = parse_bot_manager_programs(service_key, clean)
    if not programs:
        return "프로그램 상태를 읽지 못했습니다."

    running = sum(item.state == "running" for item in programs)
    stopped = sum(item.state == "stopped" for item in programs)
    total = len(programs)
    return f"프로그램 {total}개 중 실행 {running}개, 중지 {stopped}개"


def summarize_swing_bot_manager(output: str) -> str:
    programs = parse_swing_bot_programs(output)
    if not programs:
        return "프로그램 상태를 읽지 못했습니다."

    running = sum(item.state == "running" for item in programs)
    stopped = sum(item.state == "stopped" for item in programs)
    total = len(programs)
    return f"프로그램 {total}개 중 실행 {running}개, 중지 {stopped}개"


def parse_bot_manager_programs(service_key: str, output: str) -> list[ProgramStatus]:
    programs: list[ProgramStatus] = []
    current_name = ""
    current_lines: list[str] = []
    reverse_titles = reverse_program_title_map(service_key)

    def flush() -> None:
        nonlocal current_name, current_lines
        if not current_name:
            return

        joined = " ".join(line.strip() for line in current_lines)
        if "상태:" not in joined:
            current_name = ""
            current_lines = []
            return

        state = "error"
        if "실행 중" in joined:
            state = "running"
        elif "중지됨" in joined:
            state = "stopped"

        detail_lines: list[str] = []
        for raw_line in current_lines:
            stripped = raw_line.strip()
            if stripped.startswith("상태:"):
                detail_lines.append(stripped)
            elif stripped.startswith("-"):
                detail_lines.append(stripped[1:].strip())

        programs.append(
            ProgramStatus(
                name=current_name,
                state=state,
                detail="\n".join(detail_lines),
                target_key=reverse_titles.get(current_name),
                controllable=reverse_titles.get(current_name) is not None,
            )
        )
        current_name = ""
        current_lines = []

    for raw_line in strip_ansi(output).splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("안내:"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            flush()
            current_name = stripped[1:-1].strip()
            current_lines = []
            continue
        if current_name:
            current_lines.append(stripped)

    flush()
    return programs


def parse_batch_programs(output: str) -> list[ProgramStatus]:
    programs: list[ProgramStatus] = []
    current_name = ""
    detail_lines: list[str] = []

    def flush() -> None:
        nonlocal current_name, detail_lines
        if not current_name:
            return

        detail_text = "\n".join(detail_lines)
        if "오늘 실행: 성공" in detail_text:
            state = "success"
        elif "오늘 실행: 실패" in detail_text or "최근 결과 전송: failed" in detail_text:
            state = "failed"
        elif "최근 결과 전송: success" in detail_text:
            state = "success"
        else:
            state = "idle"

        programs.append(
            ProgramStatus(
                name=current_name,
                state=state,
                detail=detail_text,
                target_key=current_name,
                manual_runnable=True,
            )
        )
        current_name = ""
        detail_lines = []

    for raw_line in strip_ansi(output).splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped == "batch_bot 등록 자동화":
            continue
        if stripped.startswith("- "):
            flush()
            current_name = stripped[2:].strip()
            detail_lines = []
            continue
        if current_name:
            detail_lines.append(stripped)

    flush()
    return programs


def parse_swing_bot_programs(output: str) -> list[ProgramStatus]:
    title_map = program_title_map("auto_coin_bot_swing")
    programs: list[ProgramStatus] = []

    for raw_line in strip_ansi(output).splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("- "):
            continue

        body = stripped[2:]
        if ":" not in body:
            continue

        key, detail = body.split(":", 1)
        key = key.strip()
        detail = detail.strip()

        state = "error"
        if detail.startswith("실행 중"):
            state = "running"
        elif detail.startswith("중지됨"):
            state = "stopped"

        programs.append(
            ProgramStatus(
                name=title_map.get(key, key),
                state=state,
                detail=detail,
                target_key=key if key in title_map else None,
                controllable=key in title_map,
            )
        )

    return programs


def build_programs(service: ServiceSpec, status_output: str, programs_output: str | None) -> list[ProgramStatus]:
    if service.key == "remote_manager":
        return [
            ProgramStatus(
                name="원격 제어 폴링",
                state=parse_service_state(service, status_output),
                detail=summarize_remote_manager(status_output),
            )
        ]
    if service.key in {"auto_coin_bot", "auto_stock_bot"}:
        return parse_bot_manager_programs(service.key, status_output)
    if service.key == "auto_coin_bot_swing":
        return parse_swing_bot_programs(status_output)
    if service.key == "batch_bot":
        return parse_batch_programs(programs_output or "")
    return []


def build_service_detail(
    service: ServiceSpec,
    status_output: str,
    programs_output: str | None = None,
) -> str:
    if service.key == "remote_manager":
        return summarize_remote_manager(status_output)
    if service.key in {"auto_coin_bot", "auto_stock_bot"}:
        return summarize_bot_manager(service.key, status_output)
    if service.key == "auto_coin_bot_swing":
        return summarize_swing_bot_manager(status_output)
    if service.key == "batch_bot":
        base = summarize_batch_manager(status_output)
        schedule_summary = extract_batch_schedule_summary(programs_output or "")
        if schedule_summary:
            return f"{base}\n등록 스케줄: {schedule_summary}"
        return f"{base}\n등록 스케줄: 확인 필요"

    detail_lines = strip_ansi(status_output).splitlines()
    return "\n".join(detail_lines[:2]) if detail_lines else service.subtitle


def get_all_statuses() -> list[ServiceStatus]:
    results: list[ServiceStatus] = []
    for service in SERVICES:
        _, status_output = run_command(service.status_command)
        programs_output = None
        if service.programs_command is not None:
            _, programs_output = run_command(service.programs_command)
        detail = build_service_detail(service, status_output, programs_output)
        results.append(
            ServiceStatus(
                key=service.key,
                group=service.group,
                title=service.title,
                subtitle=service.subtitle,
                state=parse_service_state(service, status_output),
                detail=detail,
                programs=build_programs(service, status_output, programs_output),
            )
        )
    return results


def find_service(service_key: str) -> ServiceSpec | None:
    for service in SERVICES:
        if service.key == service_key:
            return service
    return None


def program_title_map(service_key: str) -> dict[str, str]:
    return PROGRAM_TITLES.get(service_key, {})


def reverse_program_title_map(service_key: str) -> dict[str, str]:
    return {title: key for key, title in program_title_map(service_key).items()}


def build_program_command(service_key: str, program_key: str, turn_on: bool) -> CommandSpec | None:
    action = "start" if turn_on else "stop"

    if service_key == "auto_coin_bot":
        return CommandSpec(
            cwd=AUTO_COIN_ROOT,
            argv=[str(AUTO_COIN_ROOT / ".venv/bin/python"), "bot_manager.py", action, program_key],
        )
    if service_key == "auto_coin_bot_swing":
        return CommandSpec(
            cwd=AUTO_COIN_SWING_ROOT,
            argv=[str(AUTO_COIN_SWING_ROOT / ".venv/bin/python"), "bot_manager.py", action, program_key],
        )
    if service_key == "auto_stock_bot":
        return CommandSpec(
            cwd=AUTO_STOCK_ROOT,
            argv=[str(AUTO_STOCK_ROOT / ".venv/bin/python"), "bot_manager.py", action, program_key],
        )
    return None


def find_tool_action(service_key: str, tool_key: str) -> ToolAction | None:
    for tool in SERVICE_TOOLS.get(service_key, []):
        if tool.key == tool_key:
            return tool
    return None


def load_short_regime_entries() -> list[RegimeEntry]:
    command = CommandSpec(
        cwd=AUTO_COIN_ROOT,
        argv=[
            str(AUTO_COIN_ROOT / ".venv/bin/python"),
            "-m",
            "reporting.current_regime_snapshot",
            "--print-only",
        ],
    )
    success, output = run_command(command)
    if not success:
        append_server_log(f"단타 레짐 스냅샷 실행 실패: {output[:300]}")
        return []
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        append_server_log(f"단타 레짐 스냅샷 파싱 실패: {exc}")
        return []
    rows = payload.get("rows", []) if isinstance(payload, dict) else []

    def sort_key(item: RegimeEntry) -> tuple[int, int, str]:
        exchange_order = 0 if item.exchange == "UPBIT" else 1
        symbol_order = 0 if item.symbol.startswith("BTC/") else 1
        return (exchange_order, symbol_order, item.symbol)

    entries: list[RegimeEntry] = []
    for row in rows:
        exchange = str(row.get("exchange", "")).strip().upper()
        symbol = str(row.get("symbol", "")).strip()
        regime = str(row.get("regime", "")).strip()
        if not exchange or not symbol or not regime:
            continue
        volume_value = row.get("volume_ratio")
        change_value = row.get("avg_abs_change_pct")
        gap_value = row.get("gap_pct")
        rsi_value = row.get("rsi")
        adx_value = row.get("adx")
        volume_ratio = "-" if volume_value is None else f"{float(volume_value):.2f}배"
        avg_abs_change_pct = "-" if change_value is None else f"{float(change_value):.3f}%"
        gap_pct = "-" if gap_value is None else f"{float(gap_value):.3f}%"
        rsi_text = "-" if rsi_value is None else f"{float(rsi_value):.1f}"
        adx_text = "-" if adx_value is None else f"{float(adx_value):.1f}"
        stage_index = row.get("stage_index")
        total_stages = row.get("total_stages")
        stage_text = (
            f"{stage_index}/{total_stages}"
            if stage_index not in (None, "")
            else f"?/{total_stages or '-'}"
        )
        entries.append(
            RegimeEntry(
                exchange=exchange,
                symbol=symbol,
                regime=regime,
                stage_text=stage_text,
                meaning=str(row.get("meaning", "")).strip() or "-",
                reason=str(row.get("reason", "")).strip() or "-",
                volume_ratio=volume_ratio,
                avg_abs_change_pct=avg_abs_change_pct,
                gap_pct=gap_pct,
                rsi=rsi_text,
                adx=adx_text,
                recorded_at_local=str(row.get("recorded_at_local", "")).strip() or None,
            )
        )

    entries.sort(key=sort_key)
    return entries


def regime_badge_class(regime: str) -> str:
    mapping = {
        "LOW_ENERGY": "regime-low-energy",
        "CHOPPY_LOW_VOL": "regime-choppy-low",
        "CHOPPY_HIGH_VOL": "regime-choppy-high",
        "BREAKOUT_ATTEMPT": "regime-breakout",
        "TRENDING_EARLY": "regime-trending-early",
        "TRENDING_MATURE": "regime-trending-mature",
        "EXHAUSTION_RISK": "regime-exhaustion",
        "OVERHEATED": "regime-overheated",
    }
    return mapping.get(regime, "regime-unknown")


def display_regime_name(regime: str) -> str:
    return regime.replace("_", " ")


def render_regime_stage_overview(
    entries: list[RegimeEntry],
    *,
    show_coins: bool = True,
    layout: str = "flow",
    size: str = "normal",
) -> str:
    grouped: dict[str, list[RegimeEntry]] = {regime: [] for regime in REGIME_STAGE_SEQUENCE}
    for entry in entries:
        grouped.setdefault(entry.regime, []).append(entry)

    blocks: list[str] = []
    for regime in REGIME_STAGE_SEQUENCE:
        stage_entries = grouped.get(regime, [])
        if stage_entries:
            exchange_groups: dict[str, list[str]] = {}
            for entry in stage_entries:
                exchange_groups.setdefault(entry.exchange, []).append(entry.symbol)
            group_lines = []
            for exchange in sorted(exchange_groups):
                group_lines.append(
                    f"{html.escape(exchange)}: {html.escape(', '.join(exchange_groups[exchange]))}"
                )
            coins_html = "<br>".join(group_lines)
        else:
            coins_html = "없음"
        blocks.append(
            f"""
            <div class="regime-stage {regime_badge_class(regime)}">
              <div class="regime-stage-head">
                <span class="regime-stage-name">{html.escape(display_regime_name(regime))}</span>
              </div>
              {f'<div class="regime-stage-coins">{coins_html}</div>' if show_coins else ''}
            </div>
            """
        )

    flow_items: list[str] = []
    for idx, block in enumerate(blocks):
        flow_items.append(block)
        if idx < len(blocks) - 1:
            flow_items.append('<div class="regime-arrow">→</div>')
    board_classes = "regime-board regime-board-flow"
    if size == "compact":
        board_classes += " regime-board-compact"
    return f'<div class="{board_classes}"><div class="regime-flow regime-flow-horizontal">{"".join(flow_items)}</div></div>'


def render_short_regime_page(entries: list[RegimeEntry]) -> bytes:
    """심볼별 현재 레짐 상세 페이지를 렌더링한다."""
    if not entries:
        body_rows = """
        <tr>
          <td colspan="9">표시할 현재 레짐 데이터가 없습니다.</td>
        </tr>
        """
    else:
        rows: list[str] = []
        for entry in entries:
            rows.append(
                f"""
                <tr>
                  <td class="col-exchange">{html.escape(entry.exchange)}</td>
                  <td class="col-symbol">{html.escape(entry.symbol)}</td>
                  <td class="col-stage">{html.escape(entry.stage_text)}</td>
                  <td class="col-regime"><span class="regime-badge {regime_badge_class(entry.regime)}">{html.escape(display_regime_name(entry.regime))}</span></td>
                  <td class="col-meaning">{html.escape(entry.meaning)}</td>
                  <td class="col-reason">{html.escape(entry.reason)}</td>
                  <td class="col-volume">{html.escape(entry.volume_ratio)}</td>
                  <td class="col-change">{html.escape(entry.avg_abs_change_pct)}</td>
                  <td class="col-gap">{html.escape(entry.gap_pct)}</td>
                  <td class="col-rsi">{html.escape(entry.rsi)}</td>
                  <td class="col-adx">{html.escape(entry.adx)}</td>
                </tr>
                """
            )
        body_rows = "".join(rows)

    page = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#1f7a49">
  <title>현재 레짐 상세</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="shortcut icon" href="/favicon.svg" type="image/svg+xml">
  <style>
    :root {{
      --bg: #efe7dc;
      --card: #fbf8f3;
      --text: #1f1a17;
      --muted: #625b53;
      --line: #ddd2c2;
      --green: #1f7a49;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif;
      background: radial-gradient(circle at top left, #f5eee5 0%, var(--bg) 45%, #eadfcf 100%);
      color: var(--text);
    }}
    .wrap {{
      max-width: 1320px;
      margin: 0 auto;
      padding: 28px 20px 40px;
    }}
    .card {{
      background: var(--card);
      border-radius: 20px;
      padding: 22px;
      box-shadow: 0 10px 30px rgba(48, 35, 18, 0.08);
    }}
    h1 {{
      margin: 0;
      font-size: 30px;
      letter-spacing: -0.03em;
    }}
    .meta {{
      margin: 8px 0 18px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
    }}
    .actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 18px;
    }}
    a {{
      border-radius: 12px;
      padding: 10px 14px;
      font-size: 14px;
      font-weight: 700;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .ghost {{
      background: #e6dccf;
      color: #2f2a25;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
      background: #f7f0e6;
      border: 1px solid var(--line);
      border-radius: 16px;
      overflow: hidden;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 12px 10px;
      vertical-align: top;
      text-align: left;
      line-height: 1.55;
    }}
    th {{
      background: #efe4d5;
      font-size: 13px;
    }}
    .regime-badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .regime-low-energy {{ background: #dfe7f1; color: #35506e; }}
    .regime-choppy-low {{ background: #efe4b7; color: #7a5d00; }}
    .regime-choppy-high {{ background: #f6dbb9; color: #8b5700; }}
    .regime-breakout {{ background: #d6f1db; color: #1f7a49; }}
    .regime-trending-early {{ background: #d8f0ea; color: #156c60; }}
    .regime-trending-mature {{ background: #cfe3fb; color: #1e4f8f; }}
    .regime-exhaustion {{ background: #f5dfc1; color: #8d5600; }}
    .regime-overheated {{ background: #f1d9d9; color: #9f2f2f; }}
    .regime-unknown {{ background: #e6dccf; color: #2f2a25; }}
    .col-reason {{
      max-width: 240px;
      width: 240px;
      font-size: 13px;
      line-height: 1.45;
    }}
    .col-volume {{
      min-width: 78px;
      white-space: nowrap;
    }}
    .col-meaning {{
      min-width: 170px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>현재 레짐 상세</h1>
      <p class="meta">각 심볼이 총 8단계 레짐 중 현재 어디에 있는지, 그리고 그 레짐이 실제로 어떤 시장 상황을 의미하는지 함께 보여줍니다.</p>
      <div class="actions">
        <a class="ghost" href="/">메인으로</a>
      </div>
      <table>
        <thead>
          <tr>
            <th>거래소</th>
            <th>심볼</th>
            <th>단계</th>
            <th>현재 레짐</th>
            <th>레짐 의미</th>
            <th>현재 해석</th>
            <th>거래량</th>
            <th>변화율</th>
            <th>이격도</th>
            <th>RSI</th>
            <th>ADX</th>
          </tr>
        </thead>
        <tbody>
          {body_rows}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""
    return page.encode("utf-8")


def apply_desired_state(turn_on: bool) -> str:
    ordered = SERVICES if turn_on else list(reversed(SERVICES))
    action = "시작" if turn_on else "중지"
    for service in ordered:
        command = service.start_command if turn_on else service.stop_command
        success, output = run_command(command)
        append_server_log(f"{service.title} {action} {'성공' if success else '실패'}")
        if output:
            for line in output.splitlines()[:20]:
                append_server_log(f"{service.title} | {line}")
    return f"희망 상태를 {'켜짐' if turn_on else '꺼짐'} 으로 적용했습니다."


def apply_service_state(service_key: str, turn_on: bool) -> str:
    service = find_service(service_key)
    if service is None:
        return "알 수 없는 서비스입니다."

    action = "시작" if turn_on else "중지"
    command = service.start_command if turn_on else service.stop_command
    success, output = run_command(command)
    append_server_log(f"{service.title} 개별 {action} {'성공' if success else '실패'}")
    if output:
        for line in output.splitlines()[:20]:
            append_server_log(f"{service.title} | {line}")

    suffix = "" if success else " 확인이 필요합니다."
    return f"{service.title} 를 {'켜짐' if turn_on else '꺼짐'} 으로 적용했습니다.{suffix}"


def apply_program_state(service_key: str, program_key: str, turn_on: bool) -> str:
    service = find_service(service_key)
    if service is None:
        return "알 수 없는 서비스입니다."

    title = program_title_map(service_key).get(program_key, program_key)
    command = build_program_command(service_key, program_key, turn_on)
    if command is None:
        return f"{service.title} 의 해당 프로그램은 개별 제어를 지원하지 않습니다."

    action = "시작" if turn_on else "중지"
    success, output = run_command(command)
    append_server_log(
        f"{service.title} 프로그램 개별 {action} | target={program_key} | {'성공' if success else '실패'}"
    )
    if output:
        for line in output.splitlines()[:20]:
            append_server_log(f"{service.title}:{program_key} | {line}")

    suffix = "" if success else " 확인이 필요합니다."
    return f"{service.title} / {title} 를 {'켜짐' if turn_on else '꺼짐'} 으로 적용했습니다.{suffix}"


def run_batch_program(program_key: str) -> str:
    service = find_service("batch_bot")
    title = program_title_map("batch_bot").get(program_key, program_key)
    command = CommandSpec(
        cwd=Path("/Users/plo/Documents/batchBot"),
        argv=[
            "python3",
            "batch_manager.py",
            "--source",
            "codex",
            "run-job",
            program_key,
        ],
    )
    success, output = run_command(command, timeout_sec=600)
    append_server_log(
        f"배치 메니저 수동 실행 | target={program_key} | {'성공' if success else '실패'}"
    )
    if output:
        for line in output.splitlines()[:30]:
            append_server_log(f"batch:{program_key} | {line}")

    suffix = "" if success else " 확인이 필요합니다."
    return f"{service.title} / {title} 수동 실행을 요청했습니다.{suffix}"


def run_tool_action(service_key: str, tool_key: str) -> tuple[str, str | None]:
    """도구를 실행하고 (플래시 메시지, 성공 시 이동할 상대 URL)을 반환한다."""
    service = find_service(service_key)
    tool = find_tool_action(service_key, tool_key)
    if service is None or tool is None:
        return "알 수 없는 도구입니다.", None

    if service_key == "auto_coin_bot" and tool_key == "weekly_backtest_report":
        TOOL_RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = TOOL_RUN_LOG_DIR / f"{tool_key}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        with log_path.open("a", encoding="utf-8") as log_stream:
            process = subprocess.Popen(
                tool.command.argv,
                cwd=tool.command.cwd,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                text=True,
            )
        append_server_log(
            f"{service.title} 도구 실행 | tool={tool_key} | 백그라운드 시작 | pid={process.pid} | log={log_path}"
        )
        message = (
            f"{service.title} / {tool.label} 실행을 시작했습니다.\n"
            "백테스트 요약 목록에서 진행 중 배치와 완료 결과를 확인할 수 있습니다."
        )
        return message, "/backtest-summaries"

    is_auto_stock_tool = service_key == "auto_stock_bot"
    if is_auto_stock_tool:
        send_autostock_tool_telegram(
            f"[가치투자 도구 실행]\n- 도구: {tool.label}\n- 시각: {now_text()}\n- 상태: 시작"
        )
    report_snapshot_before = snapshot_report_files() if is_auto_stock_tool else {}
    success, output = run_command(tool.command, timeout_sec=600)
    append_server_log(
        f"{service.title} 도구 실행 | tool={tool_key} | {'성공' if success else '실패'}"
    )
    if output:
        for line in output.splitlines()[:30]:
            append_server_log(f"{service.title}:tool:{tool_key} | {line}")

    result_status = "성공" if success else "실패"
    if is_auto_stock_tool:
        result_lines = [
            "[가치투자 도구 실행 결과]",
            f"- 도구: {tool.label}",
            f"- 시각: {now_text()}",
            f"- 상태: {result_status}",
        ]
        preview = "\n".join(line.strip() for line in output.splitlines()[:5]).strip()
        if preview:
            result_lines.append(f"- 요약:\n{preview}")
        send_autostock_tool_telegram("\n".join(result_lines))

        if success and tool_key in {
            "daily_data_pipeline",
            "stock_analysis_report",
            "value_recovery_screener",
        }:
            changed_reports = collect_changed_report_files(report_snapshot_before)
            if changed_reports:
                send_autostock_tool_documents(tool.label, changed_reports)

    suffix = "" if success else " 확인이 필요합니다."
    message = f"{service.title} / {tool.label} 실행을 요청했습니다.{suffix}"

    redirect_to: str | None = None
    if service_key == "auto_coin_bot" and tool_key == "weekly_backtest_report":
        latest = find_latest_batch_summary_md()
        if success and latest is not None:
            rel = latest.relative_to(AUTO_COIN_ROOT).as_posix()
            redirect_to = (
                "/backtest-summary?"
                + urlencode({"path": rel, "completed": "1"})
            )
            message = (
                f"{service.title} / {tool.label} 가 완료되었습니다. "
                "아래에서 방금 생성된 요약을 확인할 수 있습니다."
            )
        else:
            redirect_to = "/backtest-summaries"
            preview = "\n".join(line.strip() for line in output.splitlines()[-5:]).strip()
            if preview:
                message = (
                    f"{service.title} / {tool.label} 실행이 실패했습니다.\n"
                    f"요약:\n{preview}"
                )
            else:
                message = f"{service.title} / {tool.label} 실행이 실패했습니다."

    return message, redirect_to


def read_pid() -> int | None:
    if not PID_PATH.exists():
        return None
    try:
        return int(PID_PATH.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def ensure_server_running() -> int:
    pid = read_pid()
    if pid and is_pid_alive(pid):
        return pid

    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("a", encoding="utf-8") as out_stream:
        process = subprocess.Popen(
            [sys.executable, str(APP_ROOT / "scripts/process_control_server.py"), "--serve"],
            cwd=APP_ROOT,
            stdout=out_stream,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
        )
    PID_PATH.write_text(str(process.pid), encoding="utf-8")
    return process.pid


def stop_server() -> str:
    pid = read_pid()
    if not pid or not is_pid_alive(pid):
        if PID_PATH.exists():
            PID_PATH.unlink()
        return "제어 서버가 이미 중지되어 있습니다."

    os.kill(pid, signal.SIGTERM)
    return f"제어 서버 종료 신호를 보냈습니다. pid={pid}"


def overall_state_label(statuses: list[ServiceStatus]) -> tuple[str, bool | None]:
    states = [item.state for item in statuses]
    if all(state == "running" for state in states):
        return "현재 전체 상태: 모두 켜짐", True
    if all(state == "stopped" for state in states):
        return "현재 전체 상태: 모두 꺼짐", False
    return "현재 전체 상태: 일부만 실행 중", None


def state_badge(state: str) -> tuple[str, str]:
    mapping = {
        "running": ("실행 중", "running"),
        "stopped": ("중지됨", "stopped"),
        "partial": ("일부 실행", "partial"),
        "error": ("확인 필요", "error"),
        "success": ("성공", "success"),
        "idle": ("대기", "idle"),
        "failed": ("실패", "failed"),
    }
    return mapping.get(state, ("확인 필요", "error"))


def render_page(message: str = "") -> bytes:
    statuses = get_all_statuses()
    summary_text, desired = overall_state_label(statuses)
    checked = "checked" if desired is not False else ""

    def iter_program_sections(item: ServiceStatus) -> list[tuple[str | None, list[ProgramStatus]]]:
        if item.key == "auto_coin_bot":
            order = [
                ("업비트", ["upbit_btc", "upbit", "upbit_stream"]),
                ("OKX", ["okx_btc", "okx"]),
                ("관리", ["collector", "telegram"]),
            ]
            by_key = {
                program.target_key: program
                for program in item.programs
                if program.target_key is not None
            }
            sections: list[tuple[str | None, list[ProgramStatus]]] = []
            consumed_keys: set[str] = set()
            for title, keys in order:
                section_programs = [by_key[key] for key in keys if key in by_key]
                if section_programs:
                    sections.append((title, section_programs))
                    consumed_keys.update(
                        key for key in keys if key in by_key
                    )

            extras = [
                program
                for program in item.programs
                if program.target_key is None or program.target_key not in consumed_keys
            ]
            if extras:
                sections.append((None, extras))
            return sections

        if item.key == "auto_stock_bot":
            order = [
                "collector",
                "kr_long",
                "kr_long_trade",
                "kr_short",
                "kr_short_trade",
                "order_watch",
                "telegram",
                "reporter",
                "disclosure",
            ]
            by_key = {
                program.target_key: program
                for program in item.programs
                if program.target_key is not None
            }
            ordered_programs = [by_key[key] for key in order if key in by_key]
            extras = [program for program in item.programs if program.target_key is None]
            return [(None, [*ordered_programs, *extras])]

        return [(None, item.programs)]

    def display_program_name(item: ServiceStatus, program: ProgramStatus) -> str:
        if item.key == "auto_coin_bot":
            labels = {
                "upbit_btc": "비트코인",
                "okx_btc": "비트코인",
                "upbit": "알트",
                "upbit_stream": "웹소켓 수집기",
                "okx": "알트",
                "collector": "분석 수집기",
                "telegram": "텔레그램 명령 리스너",
            }
            if program.target_key in labels:
                return labels[program.target_key]
        if item.key == "batch_bot":
            labels = {
                "automation-2": "오늘의 공모주",
                "automation-3": "금주의 공모주",
                "daily-auto-coin-log-archive": "Coin Short Log Manager",
                "daily-auto-stock-log-archive": "Stock Log Archive",
                "daily-swing-log-archive": "Coin Long Log Manager",
            }
            if program.target_key in labels:
                return labels[program.target_key]
        return program.name

    def render_program_item(item: ServiceStatus, program: ProgramStatus) -> str:
        badge_text, badge_class = state_badge(program.state)
        program_checked = "checked" if program.state != "stopped" else ""
        program_state_text = "켜짐" if program.state != "stopped" else "꺼짐"
        show_program_detail = item.key == "batch_bot"
        program_controls = ""
        manual_action = ""
        if program.controllable and program.target_key:
            label_id = f"program-state-label-{item.key}-{program.target_key}"
            program_controls = f"""
              <form class="program-actions" method="post" action="/apply-program">
                <input type="hidden" name="service_key" value="{html.escape(item.key)}">
                <input type="hidden" name="program_key" value="{html.escape(program.target_key)}">
                <div class="mini-switch-wrap program-switch-wrap">
                  <span>프로그램</span>
                  <label class="switch micro-switch">
                    <input
                      type="checkbox"
                      class="program-toggle"
                      name="desired_state"
                      value="on"
                      data-state-label="{label_id}"
                      {program_checked}
                    >
                    <span class="slider"></span>
                  </label>
                  <span class="micro-state-text" id="{label_id}">{program_state_text}</span>
                </div>
                <button type="submit" class="micro-button">적용</button>
              </form>
            """
        if item.key == "batch_bot" and program.manual_runnable and program.target_key:
            manual_action = f"""
              <form class="program-manual-form" method="post" action="/run-batch-job">
                <input type="hidden" name="program_key" value="{html.escape(program.target_key)}">
                <button type="submit" class="manual-button">수동 실행</button>
              </form>
            """

        return f"""
            <li class="program-row">
              <div class="program-header">
                <strong>{html.escape(display_program_name(item, program))}</strong>
                <span class="badge small {badge_class}">{html.escape(badge_text)}</span>
              </div>
              {f'<div class="program-detail">{html.escape(program.detail)}</div>' if show_program_detail and program.detail else ''}
              {manual_action}
              {program_controls}
            </li>
            """

    def render_status_card(item: ServiceStatus) -> str:
        badge_text, badge_class = state_badge(item.state)
        item_checked = "checked" if item.state != "stopped" else ""
        item_state_text = "켜짐" if item.state != "stopped" else "꺼짐"
        body_id = f"card-body-{item.key}"
        section_blocks: list[str] = []
        for index, (section_title, section_programs) in enumerate(iter_program_sections(item)):
            programs_html = ''.join(render_program_item(item, program) for program in section_programs)
            if section_title:
                storage_key = f"program-group:{item.key}:{index}"
                group_body_id = f"program-group-body-{item.key}-{index}"
                section_blocks.append(
                    f"""
                    <section class="program-group collapsible-group" data-storage-key="{storage_key}">
                      <div class="program-group-header">
                        <h4>{html.escape(section_title)}</h4>
                        <button
                          type="button"
                          class="ghost tool-button section-collapse-button"
                          data-target="{group_body_id}"
                          data-storage-key="{storage_key}"
                        >
                          접기
                        </button>
                      </div>
                      <div class="program-group-body" id="{group_body_id}">
                        <ul class="program-list">
                          {programs_html or '<li class="program-empty">세부 프로그램 정보가 없습니다.</li>'}
                        </ul>
                      </div>
                    </section>
                    """
                )
            else:
                section_blocks.append(
                    f"""
                    <section class="program-group plain-group">
                      <ul class="program-list">
                        {programs_html or '<li class="program-empty">세부 프로그램 정보가 없습니다.</li>'}
                      </ul>
                    </section>
                    """
                )

        card_classes = "card wide" if len(item.programs) >= 4 else "card"
        if item.key == "auto_coin_bot":
            card_classes += " short-card"
        if item.group == "manage":
            card_classes += " manage-card"
        tool_blocks = []
        for tool in SERVICE_TOOLS.get(item.key, []):
            tool_blocks.append(
                f"""
                <li class="tool-row">
                  <div class="tool-copy">
                    <span class="tool-label">{html.escape(tool.label)}</span>
                    <span class="tool-description">{html.escape(tool.description)}</span>
                  </div>
                  <form method="post" action="/run-tool">
                    <input type="hidden" name="service_key" value="{html.escape(item.key)}">
                    <input type="hidden" name="tool_key" value="{html.escape(tool.key)}">
                    <button type="submit" class="manual-button">실행</button>
                    </form>
                </li>
                """
            )
        tool_section = ""
        if tool_blocks:
            tool_body_id = f"tool-box-body-{item.key}"
            tool_storage_key = f"tool-box:{item.key}"
            tool_title = "추가 프로그램" if item.key == "auto_stock_bot" else "도구"
            if item.key == "auto_coin_bot":
                recent_summary_paths = list_backtest_summaries(limit=RECENT_BACKTEST_SUMMARY_LIMIT)
                if recent_summary_paths:
                    summary_rows = []
                    for summary_path in recent_summary_paths:
                        summary_rows.append(
                            f"""
                            <li class="tool-subrow">
                              <div class="tool-copy">
                                <span class="tool-label marquee-field" data-marquee>
                                  <span class="marquee-track">
                                    <span class="marquee-text">{html.escape(summary_path.parent.name)}</span>
                                  </span>
                                </span>
                                <span class="tool-description marquee-field" data-marquee>
                                  <span class="marquee-track">
                                    <span class="marquee-text">{html.escape(summary_path.relative_to(AUTO_COIN_ROOT).as_posix())}</span>
                                  </span>
                                </span>
                              </div>
                              <div class="tool-link-row">
                                <a class="ghost tool-link-button" href="{html.escape(build_backtest_summary_href(summary_path))}" target="_blank" rel="noopener">보기</a>
                                <a class="ghost tool-link-button" href="{html.escape(build_backtest_summary_href(summary_path, download=True))}">다운로드</a>
                              </div>
                            </li>
                            """
                        )
                    tool_blocks.append(
                        f"""
                        <li class="tool-row tool-row-stack">
                          <div class="tool-copy">
                            <span class="tool-label">최근 백테스트 요약 여러 개</span>
                            <span class="tool-description">최신 요약 {len(recent_summary_paths)}개를 바로 열거나 다운로드할 수 있습니다.</span>
                          </div>
                          <div class="tool-link-row">
                            <a class="ghost tool-link-button" href="/backtest-summaries" target="_blank" rel="noopener">전체 목록</a>
                          </div>
                          <ul class="tool-sublist">
                            {"".join(summary_rows)}
                          </ul>
                        </li>
                        """
                    )
            tool_section = (
                f'<section class="tool-box collapsible-tool-box" data-storage-key="{tool_storage_key}">'
                f'<div class="tool-box-header">'
                f'<h4>{tool_title}</h4>'
                f'<button type="button" class="ghost tool-button tool-collapse-button" '
                f'data-target="{tool_body_id}" data-storage-key="{tool_storage_key}">접기</button>'
                f'</div>'
                f'<div class="tool-box-body" id="{tool_body_id}">'
                f'<ul class="tool-list">{"".join(tool_blocks)}</ul>'
                f'</div>'
                f'</section>'
            )
        regime_section = ""
        if item.key == "auto_coin_bot":
            regime_entries = load_short_regime_entries()
            if regime_entries:
                regime_body_id = f"regime-box-body-{item.key}"
                regime_storage_key = f"regime-box:{item.key}"
                regime_section = (
                    f'<section class="regime-box collapsible-regime-box" data-storage-key="{regime_storage_key}">'
                    '<div class="regime-box-header">'
                    '<h4>현재 레짐</h4>'
                    '<div class="summary-actions">'
                    f'<a class="ghost tool-link-button" href="/regime-snapshot" target="_blank" rel="noopener">전체 보기</a>'
                    f'<button type="button" class="ghost tool-button regime-collapse-button" '
                    f'data-target="{regime_body_id}" data-storage-key="{regime_storage_key}">접기</button>'
                    '</div>'
                    '</div>'
                    f'<div class="regime-box-body" id="{regime_body_id}">'
                    f'{render_regime_stage_overview(regime_entries, show_coins=True, layout="flow", size="compact")}'
                    '</div>'
                    '</section>'
                )
        return f"""
            <section class="{card_classes}" data-service-key="{html.escape(item.key)}" draggable="true">
              <div class="row">
                <div>
                  <h3>{html.escape(item.title)}</h3>
                  <p class="subtitle">{html.escape(item.subtitle)}</p>
                </div>
                <div class="card-header-actions">
                  <span class="badge {badge_class}">{html.escape(badge_text)}</span>
                  <button
                    type="button"
                    class="ghost tool-button collapse-button"
                    data-target="{body_id}"
                    data-card-key="{html.escape(item.key)}"
                  >
                    숨기기
                  </button>
                  <span class="drag-handle" title="카드를 드래그해서 위치를 바꿉니다.">이동</span>
                </div>
              </div>
              <div class="card-body" id="{body_id}">
                <form class="service-actions" method="post" action="/apply-service">
                  <input type="hidden" name="service_key" value="{html.escape(item.key)}">
                  <div class="mini-switch-wrap">
                    <span>일괄 제어</span>
                    <label class="switch mini-switch">
                      <input
                        type="checkbox"
                        class="service-toggle"
                        name="desired_state"
                        value="on"
                        data-state-label="state-label-{html.escape(item.key)}"
                        {item_checked}
                      >
                      <span class="slider"></span>
                    </label>
                    <span class="mini-state-text" id="state-label-{html.escape(item.key)}">{item_state_text}</span>
                  </div>
                  <button type="submit" class="mini-button">일괄 적용</button>
                </form>
                <div class="service-detail">{html.escape(item.detail)}</div>
                {regime_section}
                <div class="program-sections">
                  {''.join(section_blocks) or '<div class="program-empty">세부 프로그램 정보가 없습니다.</div>'}
                </div>
                {tool_section}
              </div>
            </section>
            """

    group_titles = {
        "coin": "코인",
        "stock": "주식",
        "manage": "관리",
    }
    group_order = ["coin", "stock", "manage"]
    sections: list[str] = []
    for group in group_order:
        group_items = [item for item in statuses if item.group == group]
        if not group_items:
            continue
        sections.append(
            f"""
            <section class="group-block">
              <div class="group-header">
                <h2>{html.escape(group_titles[group])}</h2>
                <p class="group-help">카드는 드래그로 순서를 바꾸고, 숨기기 버튼으로 접을 수 있습니다.</p>
              </div>
              <div class="grid" data-group-key="{html.escape(group)}">
                {''.join(render_status_card(item) for item in group_items)}
              </div>
            </section>
            """
        )

    flash = f'<div class="flash">{html.escape(message)}</div>' if message else ""
    page = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#1f7a49">
  <title>Process Control Center</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="shortcut icon" href="/favicon.svg" type="image/svg+xml">
  <style>
    :root {{
      --bg: #efe7dc;
      --card: #fbf8f3;
      --text: #1f1a17;
      --muted: #625b53;
      --line: #ddd2c2;
      --green: #26a65b;
      --green-soft: #dff2e7;
      --gray: #7c7771;
      --gray-soft: #e8e0d7;
      --amber: #946200;
      --amber-soft: #f4e5bb;
      --red: #9f2f2f;
      --red-soft: #f1d9d9;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif;
      background: radial-gradient(circle at top left, #f5eee5 0%, var(--bg) 45%, #eadfcf 100%);
      color: var(--text);
    }}
    .wrap {{
      max-width: 1320px;
      margin: 0 auto;
      padding: 28px 20px 40px;
    }}
    h1 {{
      margin: 0;
      font-size: 34px;
      letter-spacing: -0.03em;
    }}
    .lead {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 15px;
    }}
    .flash {{
      margin-top: 18px;
      padding: 12px 14px;
      border-radius: 14px;
      background: #fff7d1;
      color: #6e5a00;
      font-weight: 600;
    }}
    .panel {{
      margin-top: 20px;
      background: var(--card);
      border-radius: 20px;
      padding: 22px;
      box-shadow: 0 10px 30px rgba(48, 35, 18, 0.08);
    }}
    .top-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
    }}
    .top-actions {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-left: auto;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .switch-wrap {{
      display: inline-flex;
      align-items: center;
      gap: 12px;
      font-weight: 700;
    }}
    .switch {{
      position: relative;
      display: inline-block;
      width: 74px;
      height: 40px;
    }}
    .switch input {{
      opacity: 0;
      width: 0;
      height: 0;
    }}
    .slider {{
      position: absolute;
      inset: 0;
      background: #b6b1ab;
      transition: 0.25s;
      border-radius: 999px;
      cursor: pointer;
    }}
    .slider:before {{
      position: absolute;
      content: "";
      height: 30px;
      width: 30px;
      left: 5px;
      top: 5px;
      background: white;
      transition: 0.25s;
      border-radius: 50%;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    }}
    input:checked + .slider {{
      background: var(--green);
    }}
    input:checked + .slider:before {{
      transform: translateX(34px);
    }}
    .state-text {{
      font-size: 18px;
      color: var(--green);
      min-width: 48px;
    }}
    .summary {{
      margin-top: 14px;
      color: var(--muted);
      font-size: 15px;
    }}
    .actions {{
      margin-top: 18px;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    button, .ghost {{
      border: 0;
      border-radius: 12px;
      padding: 12px 16px;
      font-size: 14px;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    button {{
      background: #1f7a49;
      color: white;
    }}
    .ghost {{
      background: #e6dccf;
      color: #2f2a25;
    }}
    .service-actions {{
      margin-top: 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .mini-switch-wrap {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      font-size: 13px;
      font-weight: 700;
      color: var(--muted);
    }}
    .mini-switch {{
      width: 62px;
      height: 34px;
    }}
    .mini-switch .slider:before {{
      width: 24px;
      height: 24px;
      left: 5px;
      top: 5px;
    }}
    .mini-switch input:checked + .slider:before {{
      transform: translateX(28px);
    }}
    .mini-state-text {{
      min-width: 38px;
      font-size: 14px;
      color: #1f7a49;
    }}
    .mini-button {{
      padding: 10px 14px;
      font-size: 13px;
    }}
    .card-body {{
      display: grid;
      gap: 14px;
    }}
    .card-body.is-collapsed {{
      display: none;
    }}
    .program-actions {{
      margin-top: 10px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      gap: 8px;
      padding-top: 10px;
      border-top: 1px solid var(--line);
      min-width: 0;
    }}
    .program-switch-wrap {{
      font-size: 12px;
      min-width: 0;
      flex-wrap: wrap;
      row-gap: 6px;
    }}
    .micro-switch {{
      width: 50px;
      height: 28px;
    }}
    .micro-switch .slider:before {{
      width: 18px;
      height: 18px;
      left: 4px;
      top: 4px;
    }}
    .micro-switch input:checked + .slider:before {{
      transform: translateX(24px);
    }}
    .micro-state-text {{
      min-width: 32px;
      font-size: 12px;
      color: #1f7a49;
    }}
    .micro-button {{
      border: 0;
      border-radius: 9px;
      padding: 8px 10px;
      background: #d8ccb9;
      color: #2f2a25;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
      justify-self: end;
    }}
    .program-manual-form {{
      margin-top: 10px;
      display: flex;
      justify-content: flex-end;
    }}
    .manual-button {{
      border: 0;
      border-radius: 10px;
      padding: 8px 12px;
      background: #1f7a49;
      color: white;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 14px;
      align-items: start;
    }}
    .grid[data-group-key="coin"] {{
      grid-template-columns: minmax(0, 1fr);
    }}
    .grid[data-group-key="coin"] .card.wide {{
      grid-column: auto;
    }}
    .group-block {{
      margin-top: 22px;
    }}
    .group-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }}
    .group-help {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
    }}
    h2 {{
      margin: 0;
      font-size: 22px;
      letter-spacing: -0.02em;
    }}
    .card {{
      background: var(--card);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 10px 30px rgba(48, 35, 18, 0.08);
      min-width: 0;
      display: grid;
      gap: 14px;
    }}
    .card.wide {{
      grid-column: span 2;
    }}
    .card.is-collapsed {{
      gap: 0;
    }}
    .card.is-collapsed.wide {{
      grid-column: span 1;
    }}
    .card.dragging {{
      opacity: 0.45;
      border: 2px dashed #b89e78;
    }}
    .card-header-actions {{
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .tool-button {{
      padding: 8px 12px;
      font-size: 12px;
      background: #efe4d5;
    }}
    .drag-handle {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 44px;
      padding: 8px 10px;
      border-radius: 10px;
      background: #eadcca;
      color: #4f483f;
      font-size: 12px;
      font-weight: 700;
      cursor: grab;
      user-select: none;
    }}
    .row {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
    }}
    h3 {{
      margin: 0;
      font-size: 18px;
    }}
    .subtitle {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .badge {{
      white-space: nowrap;
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 12px;
      font-weight: 800;
    }}
    .badge.small {{
      padding: 6px 10px;
      font-size: 11px;
    }}
    .badge.running {{ background: var(--green-soft); color: var(--green); }}
    .badge.stopped {{ background: var(--gray-soft); color: var(--gray); }}
    .badge.partial {{ background: var(--amber-soft); color: var(--amber); }}
    .badge.error {{ background: var(--red-soft); color: var(--red); }}
    .badge.success {{ background: var(--green-soft); color: var(--green); }}
    .badge.idle {{ background: var(--gray-soft); color: var(--gray); }}
    .badge.failed {{ background: var(--red-soft); color: var(--red); }}
    .service-detail {{
      white-space: pre-wrap;
      background: #f3ede4;
      border-radius: 12px;
      padding: 12px;
      color: #3f3a34;
      font-size: 14px;
      line-height: 1.5;
    }}
    .program-sections {{
      display: grid;
      gap: 12px;
    }}
    .program-group {{
      display: grid;
      gap: 10px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #f7f0e6;
      padding: 10px;
    }}
    .program-group-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .program-group h4 {{
      margin: 0;
      font-size: 14px;
      font-weight: 800;
      color: #473f38;
    }}
    .program-group-body {{
      display: block;
    }}
    .program-group-body.is-collapsed {{
      display: none;
    }}
    .program-group.plain-group {{
      border: 0;
      background: transparent;
      padding: 0;
    }}
    .program-list {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 10px;
      grid-template-columns: minmax(0, 1fr);
    }}
    .program-row,
    .program-empty {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #f8f2e9;
      padding: 12px;
    }}
    .program-header {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;
    }}
    .program-header strong {{
      font-size: 14px;
      line-height: 1.4;
    }}
    .program-detail {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
      white-space: pre-wrap;
      line-height: 1.5;
      word-break: break-word;
    }}
    .program-empty {{
      color: var(--muted);
      font-size: 13px;
    }}
    .regime-box {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #f7f0e6;
      padding: 12px;
      display: grid;
      gap: 10px;
    }}
    .regime-box-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .regime-box h4 {{
      margin: 0;
      font-size: 14px;
      font-weight: 800;
      color: #473f38;
    }}
    .regime-box-body.is-collapsed {{
      display: none;
    }}
    .regime-board {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #fbf6ef;
      padding: 8px;
      overflow: hidden;
    }}
    .regime-board.regime-board-flow {{
      overflow-x: auto;
    }}
    .regime-board.regime-board-compact {{
      padding: 6px;
    }}
    .regime-flow {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      align-items: stretch;
      width: 100%;
    }}
    .regime-flow.regime-flow-horizontal {{
      display: flex;
      gap: 6px;
      align-items: stretch;
      flex-wrap: nowrap;
      min-width: 980px;
      width: max-content;
    }}
    .regime-stage {{
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px 8px;
      display: grid;
      gap: 4px;
      background: #fbf6ef;
    }}
    .regime-stage-head {{
      display: grid;
      gap: 2px;
    }}
    .regime-stage-name {{
      font-size: 10px;
      font-weight: 800;
      line-height: 1.15;
      word-break: break-word;
      letter-spacing: -0.02em;
    }}
    .regime-stage-coins {{
      font-size: 9px;
      line-height: 1.15;
      color: var(--muted);
      word-break: break-word;
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      overflow: hidden;
    }}
    .regime-arrow {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 12px;
      flex: 0 0 12px;
      font-size: 11px;
      font-weight: 800;
      color: #8d806d;
    }}
    .regime-board-compact .regime-flow.regime-flow-horizontal {{
      gap: 6px;
      min-width: 980px;
    }}
    .regime-board-compact .regime-stage {{
      border-radius: 8px;
      padding: 10px 8px;
      gap: 6px;
    }}
    .regime-board-compact .regime-stage-name {{
      font-size: 10px;
      line-height: 1.2;
    }}
    .regime-board-compact .regime-stage-coins {{
      font-size: 9px;
      line-height: 1.3;
    }}
    .regime-board-compact .regime-arrow {{
      min-width: 12px;
      flex: 0 0 12px;
      font-size: 11px;
    }}
    .regime-board-compact .regime-arrow {{
      min-width: 10px;
      flex: 0 0 10px;
      font-size: 9px;
    }}
    .regime-low-energy {{ background: #dfe7f1; color: #35506e; }}
    .regime-choppy-low {{ background: #efe4b7; color: #7a5d00; }}
    .regime-choppy-high {{ background: #f6dbb9; color: #8b5700; }}
    .regime-breakout {{ background: #d6f1db; color: #1f7a49; }}
    .regime-trending-early {{ background: #d8f0ea; color: #156c60; }}
    .regime-trending-mature {{ background: #cfe3fb; color: #1e4f8f; }}
    .regime-exhaustion {{ background: #f5dfc1; color: #8d5600; }}
    .regime-overheated {{ background: #f1d9d9; color: #9f2f2f; }}
    .regime-unknown {{ background: #e6dccf; color: #2f2a25; }}
    .manage-card .program-sections {{
      grid-template-columns: minmax(0, 1fr);
    }}
    .manage-card .program-list {{
      grid-template-columns: minmax(0, 1fr);
    }}
    .tool-box {{
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #f7f0e6;
      padding: 12px;
      display: grid;
      gap: 10px;
    }}
    .tool-box-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .tool-box h4 {{
      margin: 0;
      font-size: 14px;
      font-weight: 800;
      color: #473f38;
    }}
    .tool-box-body.is-collapsed {{
      display: none;
    }}
    .tool-list {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 8px;
    }}
    .tool-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #fbf6ef;
      padding: 10px 12px;
    }}
    .tool-row-stack {{
      grid-template-columns: minmax(0, 1fr);
      align-items: stretch;
    }}
    .tool-label {{
      font-size: 13px;
      font-weight: 700;
      color: #3f3a34;
      display: block;
      min-width: 0;
    }}
    .tool-copy {{
      display: grid;
      gap: 4px;
      min-width: 0;
    }}
    .tool-description {{
      font-size: 12px;
      line-height: 1.5;
      color: var(--muted);
      display: block;
      min-width: 0;
    }}
    .marquee-field {{
      position: relative;
      overflow: hidden;
      white-space: nowrap;
      max-width: 100%;
      mask-image: linear-gradient(to right, transparent 0, black 12px, black calc(100% - 12px), transparent 100%);
      -webkit-mask-image: linear-gradient(to right, transparent 0, black 12px, black calc(100% - 12px), transparent 100%);
    }}
    .marquee-track {{
      display: inline-flex;
      align-items: center;
      min-width: max-content;
      transform: translateX(0);
    }}
    .marquee-text {{
      display: inline-block;
      min-width: max-content;
      padding-right: 0;
    }}
    .marquee-field.is-overflow .marquee-track {{
      animation: marquee-slide var(--marquee-duration, 12s) linear infinite alternate;
      will-change: transform;
    }}
    @keyframes marquee-slide {{
      from {{
        transform: translateX(0);
      }}
      to {{
        transform: translateX(calc(-1 * var(--marquee-distance, 0px)));
      }}
    }}
    .tool-link-row {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .tool-sublist {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 8px;
    }}
    .tool-subrow {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #f3eadf;
      padding: 10px 12px;
    }}
    .tool-link-button {{
      padding: 8px 12px;
      font-size: 12px;
      font-weight: 700;
    }}
    @media (max-width: 720px) {{
      .wrap {{
        padding: 22px 14px 32px;
      }}
      h1 {{
        font-size: 28px;
      }}
      .panel,
      .card {{
        padding: 16px;
      }}
      .top-actions {{
        width: 100%;
        justify-content: flex-start;
        margin-left: 0;
      }}
      .card.is-collapsed {{
        padding-bottom: 16px;
      }}
      .card-header-actions {{
        justify-content: flex-start;
      }}
      .program-header {{
        flex-direction: column;
      }}
      .service-actions {{
        align-items: stretch;
      }}
      .program-actions {{
        grid-template-columns: minmax(0, 1fr);
      }}
      .tool-row {{
        grid-template-columns: minmax(0, 1fr);
      }}
      .tool-subrow {{
        grid-template-columns: minmax(0, 1fr);
      }}
      .card.wide {{
        grid-column: auto;
      }}
    }}
    @media (min-width: 1100px) {{
      .grid {{
        grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      }}
      .card.wide .program-list {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .card.wide .program-sections {{
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      }}
      .card.wide.short-card .program-sections {{
        grid-template-columns: minmax(0, 1fr);
      }}
      .card.wide.short-card .program-list {{
        grid-template-columns: minmax(0, 1fr);
      }}
      .card.wide.manage-card .program-sections {{
        grid-template-columns: minmax(0, 1fr);
      }}
      .card.wide.manage-card .program-list {{
        grid-template-columns: minmax(0, 1fr);
      }}
    }}
    @media (min-width: 1400px) {{
      .card.wide .program-list {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }}
      .card.wide.short-card .program-list {{
        grid-template-columns: minmax(0, 1fr);
      }}
      .card.wide.manage-card .program-list {{
        grid-template-columns: minmax(0, 1fr);
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Process Control Center</h1>
    <p class="lead">브라우저에서 켜짐/꺼짐 토글을 바꾸고 적용하면 전체 프로세스를 일괄 제어합니다.</p>
    {flash}
    <section class="panel">
      <form method="post" action="/apply">
        <div class="top-row">
          <div class="switch-wrap">
            <span>희망 상태</span>
            <label class="switch">
              <input type="checkbox" id="desiredToggle" name="desired_state" value="on" {checked}>
              <span class="slider"></span>
            </label>
            <span class="state-text" id="desiredStateText">{'켜짐' if checked else '꺼짐'}</span>
          </div>
          <div class="top-actions">
            <button type="submit">적용</button>
            <a class="ghost" href="/">새로고침</a>
          </div>
        </div>
        <div class="summary">{html.escape(summary_text)}</div>
      </form>
    </section>
    {''.join(sections)}
  </div>
  <script>
    const CARD_ORDER_KEY = 'process-control-card-order-v1';
    const CARD_COLLAPSE_KEY = 'process-control-card-collapse-v1';
    const DETAILS_COLLAPSE_KEY = 'process-control-details-collapse-v1';

    const readJsonStorage = (key, fallback) => {{
      try {{
        const raw = window.localStorage.getItem(key);
        return raw ? JSON.parse(raw) : fallback;
      }} catch (error) {{
        return fallback;
      }}
    }};

    const writeJsonStorage = (key, value) => {{
      try {{
        window.localStorage.setItem(key, JSON.stringify(value));
      }} catch (error) {{
        // ignore storage failures
      }}
    }};

    const toggle = document.getElementById('desiredToggle');
    const text = document.getElementById('desiredStateText');
    const refreshLabel = () => {{
      const on = toggle.checked;
      text.textContent = on ? '켜짐' : '꺼짐';
      text.style.color = on ? '#1f7a49' : '#6b6761';
    }};
    toggle.addEventListener('change', refreshLabel);
    refreshLabel();

    document.querySelectorAll('.service-toggle').forEach((serviceToggle) => {{
      const labelId = serviceToggle.dataset.stateLabel;
      const label = document.getElementById(labelId);
      const refreshServiceLabel = () => {{
        const on = serviceToggle.checked;
        label.textContent = on ? '켜짐' : '꺼짐';
        label.style.color = on ? '#1f7a49' : '#6b6761';
      }};
      serviceToggle.addEventListener('change', refreshServiceLabel);
      refreshServiceLabel();
    }});

    document.querySelectorAll('.program-toggle').forEach((programToggle) => {{
      const labelId = programToggle.dataset.stateLabel;
      const label = document.getElementById(labelId);
      const refreshProgramLabel = () => {{
        const on = programToggle.checked;
        label.textContent = on ? '켜짐' : '꺼짐';
        label.style.color = on ? '#1f7a49' : '#6b6761';
      }};
      programToggle.addEventListener('change', refreshProgramLabel);
      refreshProgramLabel();
    }});

    const setupMarquee = () => {{
      document.querySelectorAll('[data-marquee]').forEach((field) => {{
        const track = field.querySelector('.marquee-track');
        const textNode = field.querySelector('.marquee-text');
        if (!track || !textNode) {{
          return;
        }}

        field.classList.remove('is-overflow');
        field.style.removeProperty('--marquee-distance');
        field.style.removeProperty('--marquee-duration');
        track.style.transform = 'translateX(0)';

        const overflow = Math.ceil(textNode.scrollWidth - field.clientWidth);
        if (overflow <= 6) {{
          return;
        }}

        field.classList.add('is-overflow');
        field.style.setProperty('--marquee-distance', `${{overflow}}px`);
        const duration = Math.max(10, Math.min(24, overflow / 18));
        field.style.setProperty('--marquee-duration', `${{duration}}s`);
      }});
    }};

    window.addEventListener('load', setupMarquee);
    window.addEventListener('resize', setupMarquee);
    setupMarquee();

    const collapsedCards = readJsonStorage(CARD_COLLAPSE_KEY, {{}});
    document.querySelectorAll('.collapse-button').forEach((button) => {{
      const targetId = button.dataset.target;
      const cardKey = button.dataset.cardKey;
      const body = document.getElementById(targetId);
      const card = button.closest('.card');
      if (!body) {{
        return;
      }}

      const applyState = () => {{
        const collapsed = Boolean(collapsedCards[cardKey]);
        body.classList.toggle('is-collapsed', collapsed);
        if (card) {{
          card.classList.toggle('is-collapsed', collapsed);
        }}
        button.textContent = collapsed ? '펼치기' : '숨기기';
      }};

      applyState();
      button.addEventListener('click', () => {{
        collapsedCards[cardKey] = !collapsedCards[cardKey];
        writeJsonStorage(CARD_COLLAPSE_KEY, collapsedCards);
        applyState();
      }});
    }});

    const detailsState = readJsonStorage(DETAILS_COLLAPSE_KEY, {{}});
    document.querySelectorAll('.section-collapse-button').forEach((button) => {{
      const targetId = button.dataset.target;
      const storageKey = button.dataset.storageKey;
      const body = document.getElementById(targetId);
      if (!storageKey || !body) {{
        return;
      }}

      const applySectionState = () => {{
        const collapsed = Boolean(detailsState[storageKey]);
        body.classList.toggle('is-collapsed', collapsed);
        button.textContent = collapsed ? '펼치기' : '접기';
      }};

      applySectionState();
      button.addEventListener('click', () => {{
        detailsState[storageKey] = !detailsState[storageKey];
        writeJsonStorage(DETAILS_COLLAPSE_KEY, detailsState);
        applySectionState();
      }});
    }});

    document.querySelectorAll('.tool-collapse-button').forEach((button) => {{
      const targetId = button.dataset.target;
      const storageKey = button.dataset.storageKey;
      const body = document.getElementById(targetId);
      if (!storageKey || !body) {{
        return;
      }}

      const applyToolState = () => {{
        const collapsed = Boolean(detailsState[storageKey]);
        body.classList.toggle('is-collapsed', collapsed);
        button.textContent = collapsed ? '펼치기' : '접기';
      }};

      applyToolState();
      button.addEventListener('click', () => {{
        detailsState[storageKey] = !detailsState[storageKey];
        writeJsonStorage(DETAILS_COLLAPSE_KEY, detailsState);
        applyToolState();
      }});
    }});

    document.querySelectorAll('.regime-collapse-button').forEach((button) => {{
      const targetId = button.dataset.target;
      const storageKey = button.dataset.storageKey;
      const body = document.getElementById(targetId);
      if (!storageKey || !body) {{
        return;
      }}

      const applyRegimeState = () => {{
        const collapsed = Boolean(detailsState[storageKey]);
        body.classList.toggle('is-collapsed', collapsed);
        button.textContent = collapsed ? '펼치기' : '접기';
      }};

      applyRegimeState();
      button.addEventListener('click', () => {{
        detailsState[storageKey] = !detailsState[storageKey];
        writeJsonStorage(DETAILS_COLLAPSE_KEY, detailsState);
        applyRegimeState();
      }});
    }});

    const cardOrder = readJsonStorage(CARD_ORDER_KEY, {{}});
    document.querySelectorAll('.grid[data-group-key]').forEach((grid) => {{
      const groupKey = grid.dataset.groupKey;
      const savedOrder = cardOrder[groupKey];
      if (Array.isArray(savedOrder) && savedOrder.length) {{
        savedOrder.forEach((serviceKey) => {{
          const card = grid.querySelector(`[data-service-key="${{serviceKey}}"]`);
          if (card) {{
            grid.appendChild(card);
          }}
        }});
      }}
    }});

    const saveCardOrder = (grid) => {{
      const groupKey = grid.dataset.groupKey;
      if (!groupKey) {{
        return;
      }}
      cardOrder[groupKey] = Array.from(grid.querySelectorAll('.card[data-service-key]'))
        .map((card) => card.dataset.serviceKey);
      writeJsonStorage(CARD_ORDER_KEY, cardOrder);
    }};

    let draggingCard = null;
    document.querySelectorAll('.card[data-service-key]').forEach((card) => {{
      card.addEventListener('dragstart', () => {{
        draggingCard = card;
        card.classList.add('dragging');
      }});

      card.addEventListener('dragend', () => {{
        if (draggingCard) {{
          draggingCard.classList.remove('dragging');
          const parentGrid = draggingCard.closest('.grid[data-group-key]');
          if (parentGrid) {{
            saveCardOrder(parentGrid);
          }}
        }}
        draggingCard = null;
      }});

      card.addEventListener('dragover', (event) => {{
        if (!draggingCard) {{
          return;
        }}
        event.preventDefault();
      }});

      card.addEventListener('drop', (event) => {{
        if (!draggingCard) {{
          return;
        }}

        const target = event.currentTarget;
        const currentGrid = draggingCard.closest('.grid[data-group-key]');
        const targetGrid = target.closest('.grid[data-group-key]');
        if (!currentGrid || !targetGrid || currentGrid !== targetGrid || target === draggingCard) {{
          return;
        }}

        event.preventDefault();
        const rect = target.getBoundingClientRect();
        const placeBefore = event.clientY < rect.top + rect.height / 2;
        targetGrid.insertBefore(draggingCard, placeBefore ? target : target.nextSibling);
        saveCardOrder(targetGrid);
      }});
    }});

    document.querySelectorAll('.grid[data-group-key]').forEach((grid) => {{
      grid.addEventListener('dragover', (event) => {{
        if (draggingCard && draggingCard.closest('.grid[data-group-key]') === grid) {{
          event.preventDefault();
        }}
      }});

      grid.addEventListener('drop', (event) => {{
        if (!draggingCard || draggingCard.closest('.grid[data-group-key]') !== grid) {{
          return;
        }}
        if (event.target === grid) {{
          event.preventDefault();
          grid.appendChild(draggingCard);
          saveCardOrder(grid);
        }}
      }});
    }});
  </script>
</body>
</html>
"""
    return page.encode("utf-8")


def render_access_required_page() -> bytes:
    page = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#1f7a49">
  <title>Access Required</title>
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="shortcut icon" href="/favicon.svg" type="image/svg+xml">
  <style>
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif;
      background: linear-gradient(180deg, #f5eee5 0%, #eadfcf 100%);
      color: #2a241f;
      display: grid;
      min-height: 100vh;
      place-items: center;
      padding: 24px;
      box-sizing: border-box;
    }
    .card {
      width: min(420px, 100%);
      background: rgba(255, 251, 246, 0.94);
      border-radius: 22px;
      padding: 24px;
      box-shadow: 0 18px 40px rgba(60, 45, 25, 0.14);
    }
    h1 {
      margin: 0 0 10px;
      font-size: 22px;
    }
    p {
      margin: 0;
      line-height: 1.6;
      color: #655c53;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>접근 키가 필요합니다</h1>
    <p>아이폰이나 다른 기기에서는 접근 키가 포함된 URL로 접속해야 합니다.</p>
  </div>
</body>
</html>
"""
    return page.encode("utf-8")


def render_favicon_svg() -> bytes:
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="g" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0%" stop-color="#1f7a49"/>
      <stop offset="100%" stop-color="#26a65b"/>
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="16" fill="#f4ecdf"/>
  <rect x="9" y="9" width="46" height="46" rx="12" fill="url(#g)"/>
  <path d="M18 40 L28 31 L35 36 L46 22" fill="none" stroke="#f7f4ef" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="18" cy="40" r="3" fill="#f7f4ef"/>
  <circle cx="28" cy="31" r="3" fill="#f7f4ef"/>
  <circle cx="35" cy="36" r="3" fill="#f7f4ef"/>
  <circle cx="46" cy="22" r="3" fill="#f7f4ef"/>
</svg>"""
    return svg.encode("utf-8")


class ControlHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/favicon.svg", "/favicon.ico"}:
            body = render_favicon_svg()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path in {"/backtest-summary", "/backtest-summary/download", "/backtest-summaries", "/regime-snapshot"}:
            authorized, grant_cookie = check_request_authorization(self)
            if not authorized:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            query = parse_qs(parsed.query)
            if parsed.path == "/regime-snapshot":
                body = render_short_regime_page(load_short_regime_entries())
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            elif parsed.path == "/backtest-summaries":
                body = render_backtest_summary_list_page(list_backtest_summaries())
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            else:
                requested_path = query.get("path", [""])[0]
                completed_raw = (query.get("completed", [""])[0] or "").strip().lower()
                show_completed_banner = completed_raw in {"1", "true", "yes", "y", "on"}
                summary_path = (
                    resolve_backtest_summary(requested_path)
                    if requested_path
                    else find_latest_backtest_summary()
                )
                if summary_path is None:
                    self.send_error(HTTPStatus.NOT_FOUND, "요청한 백테스트 요약이 없습니다.")
                    return
                if parsed.path == "/backtest-summary/download":
                    body = summary_path.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/markdown; charset=utf-8")
                    self.send_header(
                        "Content-Disposition",
                        f'attachment; filename="{summary_path.parent.name}__{summary_path.name}"',
                    )
                else:
                    body = render_backtest_summary_page(
                        summary_path,
                        show_completed_banner=show_completed_banner,
                    )
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
            if grant_cookie:
                self.send_header(
                    "Set-Cookie",
                    f"{ACCESS_COOKIE_NAME}={ACCESS_KEY}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax",
                )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        authorized, grant_cookie = check_request_authorization(self)
        if not authorized:
            body = render_access_required_page()
            self.send_response(HTTPStatus.FORBIDDEN)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        message = STATE.pop_message()
        query = parse_qs(parsed.query)
        if not message and "message" in query:
            message = query["message"][0]

        body = render_page(message=message)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if grant_cookie:
            self.send_header(
                "Set-Cookie",
                f"{ACCESS_COOKIE_NAME}={ACCESS_KEY}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax",
            )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        authorized, _ = check_request_authorization(self)
        if not authorized:
            self.send_error(HTTPStatus.FORBIDDEN)
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length).decode("utf-8")
        form = parse_qs(raw)

        redirect_after_tool: str | None = None
        if parsed.path == "/apply":
            turn_on = form.get("desired_state", ["off"])[-1] == "on"
            append_server_log(f"웹 전체 제어 요청 수신: {'켜짐' if turn_on else '꺼짐'}")
            message = apply_desired_state(turn_on)
        elif parsed.path == "/apply-service":
            service_key = form.get("service_key", [""])[0]
            turn_on = form.get("desired_state", ["off"])[-1] == "on"
            append_server_log(
                f"웹 개별 제어 요청 수신: service={service_key} desired={'켜짐' if turn_on else '꺼짐'}"
            )
            message = apply_service_state(service_key, turn_on)
        elif parsed.path == "/apply-program":
            service_key = form.get("service_key", [""])[0]
            program_key = form.get("program_key", [""])[0]
            turn_on = form.get("desired_state", ["off"])[-1] == "on"
            append_server_log(
                "웹 프로그램 제어 요청 수신: "
                f"service={service_key} program={program_key} desired={'켜짐' if turn_on else '꺼짐'}"
            )
            message = apply_program_state(service_key, program_key, turn_on)
        elif parsed.path == "/run-batch-job":
            program_key = form.get("program_key", [""])[0]
            append_server_log(f"웹 배치 수동 실행 요청 수신: program={program_key}")
            message = run_batch_program(program_key)
        elif parsed.path == "/run-tool":
            service_key = form.get("service_key", [""])[0]
            tool_key = form.get("tool_key", [""])[0]
            append_server_log(f"웹 도구 실행 요청 수신: service={service_key} tool={tool_key}")
            message, redirect_after_tool = run_tool_action(service_key, tool_key)
        elif parsed.path == "/delete-backtest-batch":
            batch_path = form.get("batch_path", [""])[0]
            append_server_log(f"웹 백테스트 배치 삭제 요청 수신: path={batch_path}")
            message = delete_pending_backtest_batch(batch_path)
            redirect_after_tool = "/backtest-summaries"
        else:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        STATE.set_message(message)

        self.send_response(HTTPStatus.SEE_OTHER)
        if parsed.path == "/run-tool" and redirect_after_tool:
            location = redirect_after_tool
        else:
            location = "/"
        self.send_header("Location", location)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        append_server_log("HTTP " + (format % args))


def serve() -> int:
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    append_server_log(f"제어 서버 시작: bind={BIND_HOST}:{PORT}")
    server = ThreadingHTTPServer((BIND_HOST, PORT), ControlHandler)
    try:
        server.serve_forever()
    finally:
        if PID_PATH.exists():
            PID_PATH.unlink()
    return 0


def self_test() -> int:
    snapshot = []
    for service in SERVICES:
        _, status_output = run_command(service.status_command)
        programs_output = None
        if service.programs_command is not None:
            _, programs_output = run_command(service.programs_command)
        snapshot.append(
            {
                "title": service.title,
                "state": parse_service_state(service, status_output),
                "detail": build_service_detail(service, status_output, programs_output),
                "programs": [
                    {
                        "name": program.name,
                        "state": program.state,
                        "detail": program.detail,
                    }
                    for program in build_programs(service, status_output, programs_output)
                ],
            }
        )
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RemoteBot 로컬 제어 서버")
    parser.add_argument("--serve", action="store_true", help="제어 서버 실행")
    parser.add_argument("--ensure-running", action="store_true", help="서버가 없으면 시작")
    parser.add_argument("--open-browser", action="store_true", help="브라우저 열기")
    parser.add_argument("--stop-server", action="store_true", help="제어 서버 종료")
    parser.add_argument("--self-test", action="store_true", help="상태 점검 출력")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.self_test:
        return self_test()

    if args.stop_server:
        print(stop_server())
        return 0

    if args.ensure_running:
        pid = ensure_server_running()
        append_server_log(f"제어 서버 확보 완료: pid={pid}")
        if not args.open_browser and not args.serve:
            print(f"제어 서버 실행 중: pid={pid}")
            return 0

    if args.open_browser:
        subprocess.run(["open", f"http://{LOCAL_URL_HOST}:{PORT}"], check=False)
        return 0

    if args.serve:
        return serve()

    print("사용법: --ensure-running --open-browser 또는 --serve")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
