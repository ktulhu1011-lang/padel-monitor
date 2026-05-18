#!/usr/bin/env python3
"""
Одноразовая проверка слотов — запускается GitHub Actions каждые 5 минут.
Состояние хранится в slots_state.json (коммитится в репо).
"""

import json
import os
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
STATE_FILE = "slots_state.json"

TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHAT_IDS = os.environ["TG_CHAT_IDS"].split(",")  # "190048502,384414841"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://russpass.ru/",
    "Origin": "https://russpass.ru",
    "Accept": "application/json",
}


def is_interesting(date_str: str, time_start: str) -> bool:
    return True  # ТЕСТ: пропускаем все слоты


def fetch_sessions() -> dict:
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
            start_time = s["time"]["start"]
            if not is_interesting(date, start_time):
                continue
            ext = json.loads(s["sessionExtendedId"])
            pid = str(ext["performanceId"])
            sessions[pid] = {
                "date": date,
                "start": start_time,
                "end": s["time"]["end"],
                "tickets": s.get("availableTicketsCount", 0),
            }
    return sessions


def send_telegram(text: str):
    for chat_id in TG_CHAT_IDS:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(sessions: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)


def format_slots(sessions: dict) -> str:
    days = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    lines = []
    for s in sorted(sessions.values(), key=lambda x: (x["date"], x["start"])):
        dt = datetime.strptime(s["date"], "%Y-%m-%d")
        day = days[dt.weekday()]
        lines.append(f"📅 {s['date']} ({day})  {s['start']}–{s['end']}  (билетов: {s['tickets']})")
    return "\n".join(lines)


def main():
    known = load_state()
    current = fetch_sessions()

    new = {k: v for k, v in current.items() if k not in known}

    if new:
        text = (
            f"🎾 <b>Новые слоты для падела!</b>\n\n"
            f"{format_slots(new)}\n\n"
            f"<a href='{EVENT_URL}'>Забронировать →</a>"
        )
        send_telegram(text)
        print(f"Отправлено уведомление: {len(new)} новых слотов")
    else:
        print(f"Без изменений. Интересных слотов: {len(current)}")

    save_state(current)


if __name__ == "__main__":
    main()
