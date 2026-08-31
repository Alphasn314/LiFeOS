#!/usr/bin/env python3
"""LifeOS v1: send daily plan reminders through a Feishu app."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parent
PLANS_DIR = ROOT / "plans"
DATA_DIR = ROOT / "data"
FEISHU_DIR = Path.home() / ".pi" / "agent" / "feishu"
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LifeOSError(Exception):
    """A user-facing LifeOS error."""


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Load a small, dependency-free subset of .env syntax."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def get_timezone() -> ZoneInfo:
    name = os.getenv("LIFEOS_TIMEZONE", "Asia/Shanghai")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise LifeOSError(f"未知时区：{name}") from exc


def validate_date(value: str) -> str:
    if not DATE_RE.fullmatch(value):
        raise LifeOSError(f"日期格式必须是 YYYY-MM-DD：{value}")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise LifeOSError(f"无效日期：{value}") from exc
    return value


def parse_plan_text(text: str, source: str = "计划") -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if "|" not in line:
            raise LifeOSError(f"{source} 第 {line_number} 行缺少 | 分隔符")
        item_time, task = (part.strip() for part in line.split("|", 1))
        if not TIME_RE.fullmatch(item_time):
            raise LifeOSError(
                f"{source} 第 {line_number} 行时间无效：{item_time!r}，应为 HH:MM"
            )
        if not task:
            raise LifeOSError(f"{source} 第 {line_number} 行任务不能为空")
        key = (item_time, task)
        if key in seen:
            raise LifeOSError(f"{source} 第 {line_number} 行存在重复计划：{line}")
        seen.add(key)
        items.append({"time": item_time, "task": task})
    return items


def plan_path(plan_date: str) -> Path:
    return PLANS_DIR / f"{validate_date(plan_date)}.plan"


def data_path(plan_date: str) -> Path:
    return DATA_DIR / f"{validate_date(plan_date)}.json"


def read_plan(plan_date: str) -> list[dict[str, str]]:
    path = plan_path(plan_date)
    if not path.exists():
        return []
    return parse_plan_text(path.read_text(encoding="utf-8"), path.name)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def write_plan(plan_date: str, items: Any) -> Path:
    validate_date(plan_date)
    if not isinstance(items, list):
        raise LifeOSError("计划输入必须是 JSON 数组")

    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise LifeOSError(f"第 {index} 项必须是对象")
        unknown = set(item) - {"time", "task"}
        if unknown:
            raise LifeOSError(f"第 {index} 项包含未知字段：{', '.join(sorted(unknown))}")
        item_time = item.get("time")
        task = item.get("task")
        if not isinstance(item_time, str) or not isinstance(task, str):
            raise LifeOSError(f"第 {index} 项必须包含字符串 time 和 task")
        if "\n" in task or "\r" in task or "|" in task:
            raise LifeOSError(f"第 {index} 项任务不能包含换行或 |")
        lines.append(f"{item_time.strip()} | {task.strip()}")

    content = "\n".join(lines)
    if content:
        content += "\n"
    parse_plan_text(content, "输入计划")
    path = plan_path(plan_date)
    atomic_write(path, content)
    return path


def reminder_id(plan_date: str, item: dict[str, str]) -> str:
    value = f"{plan_date}\0{item['time']}\0{item['task']}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def read_daily_state(plan_date: str) -> dict[str, Any]:
    path = data_path(plan_date)
    if not path.exists():
        return {"date": plan_date, "sent": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise LifeOSError(f"无法读取状态文件 {path.name}：{exc}") from exc
    if not isinstance(state, dict) or not isinstance(state.get("sent"), dict):
        raise LifeOSError(f"状态文件格式错误：{path.name}")
    return state


def write_daily_state(plan_date: str, state: dict[str, Any]) -> None:
    atomic_write(
        data_path(plan_date),
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def read_json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise LifeOSError(f"{label}不存在：{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise LifeOSError(f"无法读取{label}：{exc}") from exc
    if not isinstance(value, dict):
        raise LifeOSError(f"{label}格式错误：顶层必须是对象")
    return value


def post_json(url: str, payload: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            response_body = response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise LifeOSError(f"飞书请求失败：{exc}") from exc

    try:
        result = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise LifeOSError(f"飞书返回了无法解析的响应：{response_body[:200]}") from exc
    if not isinstance(result, dict):
        raise LifeOSError("飞书返回格式错误")
    code = result.get("code", -1)
    if code != 0:
        message = result.get("msg", "未知错误")
        raise LifeOSError(f"飞书拒绝了消息：{code} {message}")
    return result


class FeishuClient:
    def __init__(self, app_id: str, app_secret: str, chat_id: str, domain: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.chat_id = chat_id
        self.base_url = (
            "https://open.larksuite.com" if domain == "lark" else "https://open.feishu.cn"
        )
        self._token = ""
        self._token_expires_at = 0.0

    @classmethod
    def from_bridge(cls) -> "FeishuClient":
        config_path = Path(
            os.getenv("FEISHU_CONFIG_PATH", str(FEISHU_DIR / "config.pi.json"))
        ).expanduser()
        bridge_path = Path(
            os.getenv("FEISHU_BRIDGE_PATH", str(FEISHU_DIR / "bridge.pi.json"))
        ).expanduser()
        config = read_json_object(config_path, "飞书 Bridge 配置")
        app_id = config.get("appId")
        app_secret = config.get("appSecret")
        if not isinstance(app_id, str) or not app_id or not isinstance(app_secret, str) or not app_secret:
            raise LifeOSError("飞书 Bridge 配置缺少 appId 或 appSecret")

        chat_id = os.getenv("FEISHU_CHAT_ID", "").strip()
        if not chat_id:
            bridge = read_json_object(bridge_path, "飞书 Bridge 路由")
            routes = bridge.get("routes", {})
            if not isinstance(routes, dict):
                raise LifeOSError("飞书 Bridge 路由格式错误")
            p2p_routes = {
                route.get("chatId")
                for route in routes.values()
                if isinstance(route, dict) and route.get("chatType") == "p2p"
            }
            p2p_routes.discard(None)
            if len(p2p_routes) != 1:
                raise LifeOSError(
                    "无法唯一确定飞书私聊目标；请先私聊机器人，或配置 FEISHU_CHAT_ID"
                )
            chat_id = p2p_routes.pop()

        domain = config.get("domain", "feishu")
        if domain not in {"feishu", "lark"}:
            raise LifeOSError(f"不支持的飞书域：{domain}")
        return cls(app_id, app_secret, chat_id, domain)

    def tenant_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        result = post_json(
            f"{self.base_url}/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": self.app_id, "app_secret": self.app_secret},
        )
        token = result.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise LifeOSError("飞书响应中缺少 tenant_access_token")
        expire = result.get("expire", 7200)
        self._token = token
        self._token_expires_at = time.monotonic() + max(int(expire) - 60, 1)
        return token

    def send_reminder(self, item_time: str, task: str) -> None:
        post_json(
            f"{self.base_url}/open-apis/im/v1/messages?receive_id_type=chat_id",
            {
                "receive_id": self.chat_id,
                "msg_type": "text",
                "content": json.dumps(
                    {"text": f"⏰ LifeOS 提醒\n\n{item_time}\n{task}"}, ensure_ascii=False
                ),
            },
            self.tenant_token(),
        )


def process_due(now: datetime, client: FeishuClient) -> int:
    plan_date = now.date().isoformat()
    items = read_plan(plan_date)
    if not items:
        return 0

    state = read_daily_state(plan_date)
    sent = state["sent"]
    sent_count = 0
    current_time = now.strftime("%H:%M")

    for item in items:
        item_id = reminder_id(plan_date, item)
        if item["time"] > current_time or item_id in sent:
            continue
        client.send_reminder(item["time"], item["task"])
        sent[item_id] = {
            "time": item["time"],
            "task": item["task"],
            "sent_at": now.isoformat(timespec="seconds"),
        }
        write_daily_state(plan_date, state)
        sent_count += 1
        print(f"已提醒 {item['time']} | {item['task']}", flush=True)
    return sent_count


def command_run(args: argparse.Namespace) -> int:
    client = FeishuClient.from_bridge()
    interval = args.interval
    timezone = get_timezone()
    print(
        f"LifeOS 已启动，时区 {timezone.key}，每 {interval} 秒检查一次计划。",
        flush=True,
    )
    while True:
        try:
            process_due(datetime.now(timezone), client)
        except LifeOSError as exc:
            print(f"[{datetime.now(timezone).isoformat(timespec='seconds')}] {exc}", file=sys.stderr)
        time.sleep(interval)


def command_plan_set(args: argparse.Namespace) -> int:
    try:
        items = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise LifeOSError(f"标准输入不是有效 JSON：{exc}") from exc
    path = write_plan(args.date, items)
    print(json.dumps({"ok": True, "path": str(path), "count": len(items)}, ensure_ascii=False))
    return 0


def command_plan_show(args: argparse.Namespace) -> int:
    plan_date = args.date or datetime.now(get_timezone()).date().isoformat()
    items = read_plan(plan_date)
    print(json.dumps({"date": plan_date, "items": items}, ensure_ascii=False, indent=2))
    return 0


def command_plan_validate(args: argparse.Namespace) -> int:
    plan_date = args.date or datetime.now(get_timezone()).date().isoformat()
    path = plan_path(plan_date)
    if not path.exists():
        raise LifeOSError(f"计划文件不存在：{path}")
    items = read_plan(plan_date)
    print(json.dumps({"ok": True, "date": plan_date, "count": len(items)}, ensure_ascii=False))
    return 0


def command_notify_test(args: argparse.Namespace) -> int:
    FeishuClient.from_bridge().send_reminder(
        datetime.now(get_timezone()).strftime("%H:%M"), args.message
    )
    print(json.dumps({"ok": True}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LifeOS v1 每日计划提醒器")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="持续检查计划并发送提醒")
    run_parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("LIFEOS_POLL_SECONDS", "15")),
        help="检查间隔秒数，默认 15",
    )
    run_parser.set_defaults(handler=command_run)

    set_parser = subparsers.add_parser("plan-set", help="从标准输入 JSON 写入整日计划")
    set_parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    set_parser.set_defaults(handler=command_plan_set)

    show_parser = subparsers.add_parser("plan-show", help="以 JSON 输出计划")
    show_parser.add_argument("--date", help="YYYY-MM-DD，默认今天")
    show_parser.set_defaults(handler=command_plan_show)

    validate_parser = subparsers.add_parser("plan-validate", help="校验计划文件")
    validate_parser.add_argument("--date", help="YYYY-MM-DD，默认今天")
    validate_parser.set_defaults(handler=command_plan_validate)

    notify_parser = subparsers.add_parser("notify-test", help="发送一条测试提醒")
    notify_parser.add_argument("--message", default="LifeOS 飞书连接测试成功")
    notify_parser.set_defaults(handler=command_notify_test)
    return parser


def main() -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        args = parser.parse_args(["run"])
    if args.command == "run" and args.interval < 1:
        parser.error("--interval 必须大于 0")
    try:
        return args.handler(args)
    except LifeOSError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nLifeOS 已停止。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
