# lynn-daily-briefing

[![Daily Briefing](https://github.com/lynn25004/lynn-daily-briefing/actions/workflows/briefing.yml/badge.svg)](https://github.com/lynn25004/lynn-daily-briefing/actions/workflows/briefing.yml)

> 每天 08:30 自動推一則晨報到 Telegram：Gmail 求職相關信 + 重要未讀 + 台中天氣 + Gemini 激勵句。

## 架構

```
GitHub Actions cron ──▶ briefing.py (Python stdlib)
                          │
             ┌────────────┼────────────┬─────────────┐
             ▼            ▼            ▼             ▼
          Gmail IMAP   Open-Meteo   Gemini API   Telegram Bot
        （抓求職信）  （台中天氣）  （激勵句）    （推播）
```

## 排程

| Workflow | 時間（Asia/Taipei） | UTC cron | 頻率 |
|---|---|---|---|
| `briefing.yml` | 08:30 | `30 0 * * *` | 每天 |

## 需要的 Secrets

到 repo 的 `Settings → Secrets and variables → Actions` 設定：

| Secret | 說明 | 取得方式 |
|---|---|---|
| `GMAIL_EMAIL` | 你的 Gmail 帳號 | — |
| `GMAIL_APP_PASSWORD` | Gmail App Password（16 位）| <https://myaccount.google.com/apppasswords>（需開 2FA）|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | @BotFather |
| `TELEGRAM_CHAT_ID` | 推播目標 chat_id | 跟 bot 聊天後 `getUpdates` API 取得 |
| `GEMINI_API_KEY` | Gemini API key | <https://aistudio.google.com/apikey> |

## 本機測試

```bash
export GMAIL_EMAIL="you@gmail.com"
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
export TELEGRAM_BOT_TOKEN="123:ABC..."
export TELEGRAM_CHAT_ID="12345678"
export GEMINI_API_KEY="AIzaSy..."

python3 scripts/briefing.py
```

## 調整

- **求職關鍵字**：改 `briefing.py` 裡的 `JOB_KEYWORDS`
- **推播時間**：改 `.github/workflows/briefing.yml` 的 cron
- **內容項目**：編輯 `build_message()` 函式

## 技術重點

- 純 Python stdlib（imaplib / urllib / json / email）— 零第三方依賴
- Gmail IMAP + App Password — 比 OAuth 簡單，可隨時撤銷
- Open-Meteo API — 免費無需 API key
- Gemini 2.5-flash — 動態生成個人化激勵句
- GitHub Actions — 免費無伺服器排程

## 授權

MIT License
