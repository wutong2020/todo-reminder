#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Actions 云端提醒检查脚本（无界面）"""
import json
import os
from datetime import datetime
from pathlib import Path

import requests

DATA_FILE = Path(__file__).with_name("todos.json")
TOKEN = os.environ.get("PUSHPLUS_TOKEN", "").strip()
LOOKBACK_MINUTES = int(os.environ.get("LOOKBACK_MINUTES", "1440"))


def send_pushplus(title, content):
    if not TOKEN:
        print("缺少 PUSHPLUS_TOKEN 环境变量")
        return False
    try:
        r = requests.post(
            "https://www.pushplus.plus/send",
            json={"token": TOKEN, "title": title[:100], "content": content[:20000]},
            timeout=15,
        )
        res = r.json()
        if res.get("code") == 200:
            return True
        print(f"PushPlus 返回错误: {res.get('msg')}")
        return False
    except Exception as e:
        print(f"推送异常: {e}")
        return False


def main():
    if not DATA_FILE.exists():
        print("todos.json 不存在")
        return

    todos = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    now = datetime.now()
    changed = False
    sent = 0

    for todo in todos:
        if todo.get("completed"):
            continue
        for r in todo.get("reminders", []):
            if r.get("reminded"):
                continue
            try:
                dt = datetime.fromisoformat(r["time"])
            except (KeyError, ValueError):
                continue
            if dt > now:
                continue
            # 过期超过 LOOKBACK_MINUTES 分钟的，直接标记为已处理，不补发
            if (now - dt).total_seconds() > LOOKBACK_MINUTES * 60:
                r["reminded"] = True
                changed = True
                continue

            lines = [
                todo.get("task", "待办事项"),
                f"事件时间：{todo.get('event_time', '').replace('T', ' ')}",
            ]
            mt = todo.get("meeting_type", "").strip()
            mi = todo.get("meeting_id", "").strip()
            if mt or mi:
                lines.append(f"会议信息：{mt} {mi}".strip())

            print(f"[发送] {todo.get('task')} @ {r['time']}")
            if send_pushplus("待办提醒", "\n".join(lines)):
                r["reminded"] = True
                changed = True
                sent += 1

    if changed:
        DATA_FILE.write_text(
            json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已发送 {sent} 条，reminded 标记已更新")
    else:
        print("没有需要发送的提醒")


if __name__ == "__main__":
    main()
