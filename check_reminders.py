#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Actions 云端提醒检查脚本（无界面，支持加密，按当前周期提醒）"""
import base64
import json
import os
from datetime import datetime, timedelta
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


# ---------- 新增：周期计算逻辑（与本地代码保持一致） ----------
def get_effective_event_datetime(todo):
    """返回待办事项"当前周期"对应的实际事件时间。"""
    try:
        base = datetime.fromisoformat(todo["event_time"])
    except (KeyError, ValueError):
        return datetime.now()

    repeat_type = todo.get("repeat_type", "none")
    if repeat_type not in ("weekly", "monthly"):
        return base

    now = datetime.now()

    if repeat_type == "weekly":
        try:
            target_wd = int(str(todo.get("repeat_config", "0")).strip() or 0)
        except (TypeError, ValueError):
            target_wd = 0
        target_wd = max(0, min(6, target_wd))
        monday = now - timedelta(days=now.weekday())
        cand = (monday + timedelta(days=target_wd)).replace(
            hour=base.hour, minute=base.minute, second=0, microsecond=0
        )
        if cand < now:
            cand += timedelta(days=7)
        return cand

    if repeat_type == "monthly":
        try:
            target_day = int(str(todo.get("repeat_config", "1")).strip() or 1)
        except (TypeError, ValueError):
            target_day = 1
        target_day = max(1, min(31, target_day))

        def month_candidate(y, m):
            if m == 12:
                last = 31
            else:
                last = (datetime(y, m + 1, 1) - timedelta(days=1)).day
            return datetime(y, m, min(target_day, last), base.hour, base.minute)

        cand = month_candidate(now.year, now.month)
        if cand < now:
            year, month = now.year, now.month + 1
            if month > 12:
                month = 1
                year += 1
            cand = month_candidate(year, month)
        return cand

    return base


def get_current_cycle_reminders(todo, effective_event_dt):
    """只返回属于"当前周期"的提醒 [(dt, r), ...]。"""
    reminders = todo.get("reminders", [])
    repeat_type = todo.get("repeat_type", "none")
    out = []
    for r in reminders:
        try:
            dt = datetime.fromisoformat(r["time"])
        except (KeyError, ValueError):
            continue
        if repeat_type == "weekly":
            delta = (effective_event_dt.date() - dt.date()).days
            if 0 <= delta < 7:
                out.append((dt, r))
        elif repeat_type == "monthly":
            if (dt.year, dt.month) == (effective_event_dt.year, effective_event_dt.month):
                out.append((dt, r))
        else:
            out.append((dt, r))
    out.sort(key=lambda x: x[0])
    return out


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
            
        # 动态计算当前周期的事件时间，并过滤出当前周期的提醒
        eff = get_effective_event_datetime(todo)
        cycle_reminders = get_current_cycle_reminders(todo, eff)
        
        for dt, r in cycle_reminders:
            if r.get("reminded"):
                continue
            if dt > now:
                continue
            
            # 兜底：如果这条提醒比现在早了太久（比如几天前），标记为已提醒但不发送
            if (now - dt).total_seconds() > LOOKBACK_MINUTES * 60:
                r["reminded"] = True
                changed = True
                continue

            # 发送消息内容，事件时间使用动态计算的 eff
            lines = [
                todo.get("task", "待办事项"),
                f"事件时间：{eff.strftime('%Y-%m-%d %H:%M')}",
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
