#!/usr/bin/env python3
"""
Watchdog：檢查今日晨報有沒有推過。若該推但沒推 → 補跑 briefing.py，
並透過 Telegram 告警。

排程：每日 08:30 Taipei（00:30 UTC）應完成。30 分鐘 buffer 後啟動檢查。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib import request, error

TAIPEI = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"


def telegram_notify(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(f"[notify skipped] {text}")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=20):
            pass
    except (error.HTTPError, error.URLError, TimeoutError) as e:
        print(f"telegram error: {e}", file=sys.stderr)


def run_briefing() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["python3", "scripts/briefing.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        tail = (result.stdout + "\n" + result.stderr)[-600:]
        return result.returncode == 0, tail
    except subprocess.TimeoutExpired:
        return False, "⏱️ 超過 5 分鐘逾時"
    except Exception as e:
        return False, f"subprocess error: {e}"


def main() -> None:
    now = datetime.now(TAIPEI)
    today = now.strftime("%Y-%m-%d")
    hm = now.hour * 60 + now.minute

    # 晨報應在 08:30 完成 → 09:00 Taipei 後檢查
    expected = hm >= 9 * 60
    marker = LOGS_DIR / f"{today}.pushed.txt"

    if not expected:
        print(f"[{today} {now.strftime('%H:%M')}] 還沒到晨報檢查時間。")
        return

    if marker.exists():
        print(f"[{today} {now.strftime('%H:%M')}] 晨報已推，跳過。")
        return

    print(f"⚠️  {today} 晨報未完成，補跑中...")
    ok, tail = run_briefing()
    if ok:
        telegram_notify(f"🐕 watchdog 補推\n日期：{today}\n補推項目：晨報\n狀態：✅ 成功")
    else:
        telegram_notify(
            f"🚨 watchdog 補推失敗\n日期：{today}\n項目：晨報\n\n日誌末段：\n{tail}"
        )


if __name__ == "__main__":
    main()
