#!/usr/bin/env python3
"""
Монитор слотов бронирования padel-кортов на russpass.ru
Уведомляет (macOS + Telegram) когда появляются новые окна.

Запуск:
    python3 bilet_monitor.py

Telegram (опционально):
    export TG_TOKEN="токен_от_@BotFather"
    export TG_CHAT_ID="ваш_chat_id"
"""

import json
import os
import subprocess
import time
import uuid
import warnings
from datetime import datetime, timedelta

import requests
import urllib3

urllib3.disable_warnings()
warnings.filterwarnings("ignore")

EVENT_ID = "69f3df933984161967fbdf2b"
EVENT_URL = f"https://russpass.ru/event/{EVENT_ID}"
API_URL = f"https://api.russpass.ru/events/portal/v1/events/{EVENT_ID}/schedule"

POLL_INTERVAL = 60  # секунды между проверками
STATE_FILE = f"/tmp/russpass_{EVENT_ID}.json"

# Фильтр: выходные (любое время) + будни после 19:00
def is_interesting(date_str: str, time_start: str) -> bool:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = dt.weekday()  # 0=пн, 5=сб, 6=вс
    hour = int(time_start.split(":")[0])
    is_weekend = weekday >= 5
    is_evening_weekday = weekday < 5 and hour >= 19
    return is_weekend or is_evening_weekday

TG_TOKEN = "8916283779:AAEsYO-WMl4_WZpgd-Kt4dTKyrtWUD_YZcM"
TG_CHAT_IDS = ["190048502", "384414841"]  # Kirill, Александр

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://russpass.ru/",
    "Origin": "https://russpass.ru",
    "Accept": "application/json",
}


# ── Уведомления ────────────────────────────────────────────────────────────────

def notify_macos(title: str, body: str):
    script = f'display notification "{body}" with title "{title}" sound name "Glass"'
    subprocess.run(["osascript", "-e", script], check=False)


def notify_telegram(text: str):
    for chat_id in TG_CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
        except Exception as e:
            print(f"  [Telegram] {e}")


def notify(title: str, body: str):
    print(f"\n{'='*50}")
    print(f"🔔 {title}")
    print(f"   {body}")
    print(f"{'='*50}\n")
    notify_macos(title, body)
    notify_telegram(f"<b>{title}</b>\n{body}\n\n{EVENT_URL}")


# ── API ────────────────────────────────────────────────────────────────────────

def fetch_sessions() -> dict[str, dict]:
    """
    Возвращает словарь: performanceId -> {date, start, end, tickets}
    """
    start = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    end = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%dT23:59:59")

    r = requests.get(
        API_URL,
        params={"startDate": start, "endDate": end},
        headers={**HEADERS, "rqid": str(uuid.uuid4())},
        verify=False,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()

    sessions = {}
    for day in data.get("dates", []):
        date = day.get("date", "")
        for s in day.get("sessions", []):
            if not s.get("isActive"):
                continue
            try:
                ext = json.loads(s["sessionExtendedId"])
                perf_id = str(ext["performanceId"])
            except Exception:
                perf_id = s["sessionExtendedId"]

            start_time = s["time"]["start"]
            if not is_interesting(date, start_time):
                continue
            sessions[perf_id] = {
                "date": date,
                "start": start_time,
                "end": s["time"]["end"],
                "tickets": s.get("availableTicketsCount", 0),
            }
    return sessions


# ── Состояние ──────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(sessions: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)


def format_sessions(sessions: dict) -> str:
    lines = []
    for s in sorted(sessions.values(), key=lambda x: (x["date"], x["start"])):
        lines.append(f"  📅 {s['date']}  {s['start']}–{s['end']}  (билетов: {s['tickets']})")
    return "\n".join(lines) if lines else "  (нет слотов)"


# ── Главный цикл ───────────────────────────────────────────────────────────────

def main():
    print("🎾 Монитор падел-кортов — russpass.ru")
    print(f"   Интервал: {POLL_INTERVAL}с")
    tg = "✓" if os.environ.get("TG_TOKEN") else "✗ (задай TG_TOKEN и TG_CHAT_ID)"
    print(f"   Telegram: {tg}\n")

    known = load_state()

    print("Первая проверка...")
    try:
        current = fetch_sessions()
    except Exception as e:
        print(f"Ошибка: {e}")
        current = {}

    if not known:
        print(f"Базовый снимок: {len(current)} слот(ов)")
        print(format_sessions(current))
        save_state(current)
        known = current
    else:
        new = {k: v for k, v in current.items() if k not in known}
        if new:
            lines = format_sessions(new)
            notify("🎾 Новые слоты для бронирования!", f"{len(new)} новых:\n{lines}\n\n{EVENT_URL}")
        known = current
        save_state(known)

    print(f"\nМониторинг запущен. Ctrl+C для остановки.\n")

    while True:
        time.sleep(POLL_INTERVAL)
        now = datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] Проверка...", end=" ", flush=True)

        try:
            current = fetch_sessions()
        except Exception as e:
            print(f"ошибка: {e}")
            continue

        new = {k: v for k, v in current.items() if k not in known}
        gone = {k: v for k, v in known.items() if k not in current}

        if new:
            lines = format_sessions(new)
            print(f"🆕 {len(new)} НОВЫХ!")
            notify(
                "🎾 Новые слоты для бронирования!",
                f"Появилось {len(new)} новых окна:\n{lines}\n\n{EVENT_URL}",
            )
        elif gone:
            print(f"слотов: {len(current)} (-{len(gone)} занято)")
        else:
            print(f"без изменений ({len(current)} слотов)")

        known = current
        save_state(known)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОстановлено.")
