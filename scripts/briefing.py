#!/usr/bin/env python3
"""
每日晨報 Bot：Gmail 重要信 + 求職追蹤 + 台中天氣 + 激勵句。
推播到 Telegram。

Usage:
    python3 briefing.py
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import request, parse, error

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)


# --- Config -------------------------------------------------------------------
TAIPEI = timezone(timedelta(hours=8))

# 求職關鍵字（主旨或寄件人含以下字詞 = 重要）
JOB_KEYWORDS = [
    "面試", "錄取", "OFFER", "offer", "Offer",
    "感謝您的應徵", "履歷", "人力資源", "HR",
    "TÜV", "日月光", "台積電", "聯電", "友達", "聯發科",
    "工程師", "interview", "Interview", "hiring", "recruiting",
]

# 台中（烏日）座標：24.10, 120.62
TAICHUNG_LAT = 24.10
TAICHUNG_LON = 120.62

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def env(name: str, required: bool = True) -> str:
    val = os.environ.get(name, "")
    if required and not val:
        sys.exit(f"❌ 缺少環境變數：{name}")
    return val


# --- Gmail --------------------------------------------------------------------
def _decode_header(raw: str) -> str:
    """解碼 =?UTF-8?B?...?= 之類的 MIME encoded header。"""
    if not raw:
        return ""
    try:
        parts = email.header.decode_header(raw)
        out = []
        for text, charset in parts:
            if isinstance(text, bytes):
                out.append(text.decode(charset or "utf-8", errors="replace"))
            else:
                out.append(text)
        return "".join(out)
    except Exception:
        return raw


def fetch_gmail_summary() -> dict:
    """
    回傳 dict：
      total_unread:  未讀總數
      recent_24h:    最近 24h 未讀封數
      job_hits:      [(from, subject, date), ...] 命中求職關鍵字的信
      important:     [(from, subject, date), ...] 最近 24h 非促銷的未讀（前 5 封）
    """
    email_addr = env("GMAIL_EMAIL")
    pw = env("GMAIL_APP_PASSWORD").replace(" ", "")

    M = imaplib.IMAP4_SSL("imap.gmail.com")
    M.login(email_addr, pw)
    try:
        M.select("INBOX", readonly=True)

        # 未讀總數
        typ, data = M.search(None, "UNSEEN")
        total_unread = len(data[0].split()) if data and data[0] else 0

        # 最近 24 小時未讀
        since = (datetime.now(TAIPEI) - timedelta(days=1)).strftime("%d-%b-%Y")
        typ, data = M.search(None, f'(UNSEEN SINCE {since})')
        recent_ids = data[0].split() if data and data[0] else []

        # 取最新 30 封細節（避免太慢）
        recent_ids = recent_ids[-30:]
        job_hits = []
        important = []
        for msg_id in reversed(recent_ids):
            typ, msg_data = M.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            msg = email.message_from_string(raw)
            frm = _decode_header(msg.get("From", ""))
            subj = _decode_header(msg.get("Subject", "(無主旨)"))
            date_raw = msg.get("Date", "")
            try:
                date_parsed = email.utils.parsedate_to_datetime(date_raw)
                date_fmt = date_parsed.astimezone(TAIPEI).strftime("%m/%d %H:%M")
            except Exception:
                date_fmt = ""

            # 求職命中
            haystack = f"{frm} {subj}"
            if any(kw in haystack for kw in JOB_KEYWORDS):
                job_hits.append((frm, subj, date_fmt))
                continue

            # 過濾明顯促銷/電子報（寄件人名或主旨關鍵字）
            junk_markers = ["newsletter", "電子報", "促銷", "優惠", "No-reply", "noreply", "unsubscribe"]
            if any(kw.lower() in haystack.lower() for kw in junk_markers):
                continue

            if len(important) < 5:
                important.append((frm, subj, date_fmt))

        return {
            "total_unread": total_unread,
            "recent_24h": len(recent_ids),
            "job_hits": job_hits,
            "important": important,
        }
    finally:
        M.logout()


# --- Weather (Open-Meteo, 免費無需 API key) ------------------------------------
def fetch_weather() -> str:
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={TAICHUNG_LAT}&longitude={TAICHUNG_LON}"
        f"&current=temperature_2m,weather_code,precipitation"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        f"&timezone=Asia%2FTaipei&forecast_days=1"
    )
    try:
        with request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (error.URLError, TimeoutError) as e:
        return f"🌤️ 天氣：取得失敗（{e}）"

    cur = data.get("current", {})
    daily = data.get("daily", {})
    t_now = cur.get("temperature_2m")
    code = cur.get("weather_code", 0)
    t_max = (daily.get("temperature_2m_max") or [None])[0]
    t_min = (daily.get("temperature_2m_min") or [None])[0]
    rain = (daily.get("precipitation_probability_max") or [0])[0]

    # 簡化天氣代碼
    desc = {
        0: "☀️ 晴朗", 1: "🌤️ 大致晴", 2: "⛅ 多雲", 3: "☁️ 陰",
        45: "🌫️ 有霧", 48: "🌫️ 有霧",
        51: "🌦️ 小雨", 53: "🌦️ 毛毛雨", 55: "🌦️ 毛毛雨",
        61: "🌧️ 小雨", 63: "🌧️ 中雨", 65: "🌧️ 大雨",
        71: "🌨️ 小雪", 73: "🌨️ 雪", 75: "🌨️ 大雪",
        80: "🌦️ 陣雨", 81: "🌦️ 陣雨", 82: "⛈️ 強陣雨",
        95: "⛈️ 雷雨", 96: "⛈️ 雷雨", 99: "⛈️ 強雷雨",
    }.get(code, "🌤️ 未知")

    umbrella = "☂️ 記得帶傘！" if rain and rain >= 50 else ""
    return (
        f"{desc}　現在 {t_now}°C\n"
        f"今日 {t_min}°C ~ {t_max}°C　降雨機率 {rain}%\n"
        f"{umbrella}".strip()
    )


# --- Motivational quote (Gemini) ----------------------------------------------
def gemini_quote() -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return "今天也要加油！💪"  # fallback

    prompt = (
        "你是一個溫暖的朋友。用繁體中文寫一句 25 字以內的鼓勵話給一位正在求職的"
        "應屆畢業工程師（嵌入式 / IoT 方向，住台中）。"
        "風格：輕鬆、不雞湯、有幽默感。"
        "直接輸出那一句，不要任何其他文字、標點前綴、引號。"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 1.0, "maxOutputTokens": 128},
    }).encode("utf-8")
    url = f"{GEMINI_URL}?key={parse.quote(api_key)}"
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = payload["candidates"][0]["content"]["parts"][0]["text"].strip()
        # 去掉多餘引號
        text = text.strip('「」""\'\' ')
        return text or "今天也要加油！💪"
    except Exception:
        return "今天也要加油！💪"


# --- Telegram -----------------------------------------------------------------
def telegram_send(text: str) -> None:
    token = env("TELEGRAM_BOT_TOKEN")
    chat_id = env("TELEGRAM_CHAT_ID")
    url = TELEGRAM_API.format(token=token)

    # Telegram 單則上限 4096 字元
    if len(text) > 4000:
        text = text[:3990] + "…\n(已截斷)"

    body = parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = request.Request(url, data=body, method="POST")
    try:
        with request.urlopen(req, timeout=30) as resp:
            resp_body = resp.read().decode("utf-8")
            if resp.status >= 300:
                sys.exit(f"❌ Telegram 失敗 ({resp.status})：{resp_body}")
    except error.HTTPError as e:
        sys.exit(f"❌ Telegram HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}")


# --- Formatter ----------------------------------------------------------------
def truncate(s: str, n: int = 40) -> str:
    s = s.strip().replace("\n", " ")
    return s if len(s) <= n else s[:n - 1] + "…"


def build_message(gmail: dict, weather: str, quote: str) -> str:
    today = datetime.now(TAIPEI)
    weekday = ["一", "二", "三", "四", "五", "六", "日"][today.weekday()]
    lines = [
        f"☀️ 早安！{today.strftime('%m/%d')}（週{weekday}）晨報",
        "",
    ]

    # 求職（放最前，最重要）
    if gmail["job_hits"]:
        lines.append(f"💼 求職相關信件（{len(gmail['job_hits'])} 封）")
        for frm, subj, date in gmail["job_hits"][:5]:
            lines.append(f"  • [{date}] {truncate(subj, 35)}")
            lines.append(f"    📨 {truncate(frm, 30)}")
        lines.append("")
    else:
        lines.append("💼 求職相關：今日暫無新訊息")
        lines.append("")

    # 重要信件
    lines.append(f"📧 Gmail 未讀統計")
    lines.append(f"  • 最近 24h：{gmail['recent_24h']} 封")
    lines.append(f"  • 總未讀數：{gmail['total_unread']} 封")
    if gmail["important"]:
        lines.append(f"  近期值得看的：")
        for frm, subj, date in gmail["important"]:
            lines.append(f"  • [{date}] {truncate(subj, 32)}")
    lines.append("")

    # 天氣
    lines.append("🌏 台中今日天氣")
    lines.append(weather)
    lines.append("")

    # 激勵
    lines.append(f"💪 {quote}")

    return "\n".join(lines)


# --- Main ---------------------------------------------------------------------
def main() -> None:
    print("📧 抓 Gmail...")
    gmail = fetch_gmail_summary()
    print(f"  求職命中 {len(gmail['job_hits'])} 封，近 24h 未讀 {gmail['recent_24h']} 封")

    print("🌤️  抓天氣...")
    weather = fetch_weather()

    print("💪 產生激勵句...")
    quote = gemini_quote()

    msg = build_message(gmail, weather, quote)
    print("---")
    print(msg)
    print("---")

    print("📤 推 Telegram...")
    telegram_send(msg)

    # 寫入完成標記（watchdog 用來判斷今天是否已推）
    today = datetime.now(TAIPEI).strftime("%Y-%m-%d")
    (LOGS_DIR / f"{today}.pushed.txt").write_text(
        datetime.now(TAIPEI).isoformat(), encoding="utf-8"
    )
    print("✅ 完成")


if __name__ == "__main__":
    main()
