#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Actions 云端提醒检查脚本（无界面，支持加密）"""
import base64
import json
import os
from datetime import datetime
from pathlib import Path

import requests
from cryptography.fernet import Fernet

DATA_FILE = Path(__file__).with_name("todos.json")
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "").strip()
ENCRYPT_KEY = os.environ.get("ENCRYPT_KEY", "").strip()
LOOKBACK_MINUTES = int(os.environ.get("LOOKBACK_MINUTES", "1440"))

_fernet = None
if ENCRYPT_KEY:
    try:
        _fernet = Fernet(ENCRYPT_KEY.encode("ascii"))
    except Exception as e:
        print(f"ENCRYPT_KEY 无效：{e}")


def decode_content(content):
    content = (content or "").strip()
    if content.startswith("ENC:"):
        if not _fernet:
            raise RuntimeError("内容已加密，但环境缺少 ENCRYPT_KEY")
        token = content[4:].encode("ascii")
        text = _fernet.decrypt(token).decode("utf-8")
        return json.loads(text)
    if not content:
        return []
    return json.loads(content)


def encode_content(todos):
    text = json.dumps(todos, ensure_ascii=False, indent=2)
    if _fernet:
        token = _fernet.encrypt(text.encode("utf-8"))
        return "ENC:" + token.decode("ascii")
    return text


def send_pushplus(title, content):
    if not PUSHPLUS_TOKEN:
        print("缺少 PUSHPLUS_TOKEN 环境变量")
        return False
    try:
        r = requests.post(
            "https://www.pushplus.plus/send",
            json={"token": PUSHPLUS_TOKEN, "title": title[:100], "content": content[:20000]},
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

    raw = DATA_FILE.read_text(encoding="utf-8")
    try:
        todos = decode_content(raw)
    except Exception as e:
        print(f"内容解析失败: {e}")
        return

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
        DATA_FILE.write_text(encode_content(todos), encoding="utf-8")
        print(f"已发送 {sent} 条，reminded 标记已更新")
    else:
        print("没有需要发送的提醒")


if __name__ == "__main__":
    main()
