"""
Personal AI assistant for Telegram: notes, tasks, planning, reminders,
workouts and voice messages, in English or Azerbaijani.
Optional Todoist sync and a Google Sheets workout log with a dashboard.

Talk to it naturally (by text or voice) or use slash commands.

Paste ONE of these lists into @BotFather -> /setcommands for a command menu.

Azerbaijani:
qeyd - Qeyd saxla
qeydler - Qeydləri göstər və ya axtar
tapsiriq - Tapşırıq əlavə et
tapsiriqlar - Açıq tapşırıqlar
hazir - Tapşırığı tamamla
xatirlat - Xatırlatma qur
plan - Bugünkü plan
gundem - Tapşırıqlar və xatırlatmalar
sifirla - Söhbət yaddaşını təmizlə
komek - Kömək
mesq - Bugünkü məşq
cedvel - Məşq cədvəli (Google Sheet)
setkey - Ayar və ya açar dəyiş

English:
note - Save a note
notes - List or search notes
task - Add a task
tasks - Show open tasks
done - Complete a task by ID
remind - Set a reminder
plan - AI plan for today
agenda - Tasks and reminders at a glance
reset - Clear conversation memory
help - Show help
workout - Today's workout
sheet - Workout Google Sheet
setkey - Change a setting or key
"""

import asyncio
import inspect
import json
import logging
import os
import re
import sqlite3
import time
from collections import defaultdict, deque
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

# ------------------------------------------------------------- texts
TEXTS = {
    "en": {
        "help": (
            "Just talk to me naturally, by text or voice message 🎤, for example:\n"
            "- Note: Elnur's birthday is on 12 December\n"
            "- Add task: send the invoice by Friday, high priority\n"
            "- Remind me to call mum tomorrow at 6pm\n"
            "- Plan my day\n"
            "- Create a 3-day gym program for me\n"
            "- Today: bench press 4x8 60kg, squats 3x10 80kg\n\n"
            "Or use commands:\n"
            "/note <text> - save a note\n"
            "/notes [search] - list or search notes\n"
            "/task <text> - add a task (dates understood)\n"
            "/tasks - open tasks\n"
            "/done <id> - complete a task\n"
            "/remind <when> <what> - set a reminder\n"
            "/plan - AI plan for today\n"
            "/agenda - tasks and reminders at a glance\n"
            "/workout - today's workout with log buttons\n"
            "/sheet - link to your workout Google Sheet\n"
            "/reset - clear conversation memory\n"
            "/setkey NAME value - change a setting or key (your message is deleted)"
        ),
        "start": "Hi! I'm your personal assistant.\nYour Telegram user ID: {uid}\n\n",
        "private": "This bot is private. Ask the owner to add your ID to ALLOWED_USER_IDS.",
        "note_usage": "Usage: /note <text>",
        "note_saved": "📝 Saved note #{id}",
        "no_notes": "No notes found.",
        "no_tasks": "No open tasks 🎉",
        "open_tasks": "📋 Open tasks:",
        "due": " (due {due}{overdue})",
        "overdue": " ⚠️ overdue",
        "done_usage": "Usage: /done <task id>",
        "done_ok": "✅ Done!",
        "done_fail": "No open task with that ID.",
        "reminders_header": "⏰ Upcoming reminders:",
        "none": "(none)",
        "reset": "🧹 Conversation memory cleared (notes and tasks are kept).",
        "ai_error": "Sorry, I couldn't reach the AI just now. Please try again in a moment.",
        "reminder": "⏰ Reminder: {text}",
        "brief_header": "☀️ Good morning!\n\n",
        "brief_prompt": "Give me my morning briefing: overdue items, what's due today, "
                        "reminders, and a suggested plan.",
        "task_prompt": "Add this task: {text}",
        "task_empty": "Help me add a task.",
        "remind_prompt": "Set a reminder: {text}",
        "remind_empty": "I want to set a reminder.",
        "plan_prompt": "Make a time-blocked plan for the rest of today from my open "
                       "tasks and reminders.",
        "voice_heard": "🎤 I heard: “{text}”",
        "voice_off": "Voice messages aren't set up yet: OPENAI_API_KEY is missing from the settings.",
        "voice_fail": "Sorry, I couldn't understand that voice message. Please try again or type it.",
        "voice_empty": "I couldn't hear anything in that voice message.",
        "lang_rule": "Reply in the language the user writes in.",
        "today_tasks": "📋 Today and overdue:",
        "tasks_first": "Send /tasks first, then use the number from that list.",
        "todoist_error": "Sorry, I couldn't reach Todoist just now. Please try again in a moment.",
        "todoist_ok": "✅ Todoist connected ({n} projects found).",
        "todoist_bad": "⚠️ Saved, but Todoist didn't accept this token. Check it and send /setkey again.",
        "setkey_usage": "Usage: /setkey NAME value\nYou can set: {keys}",
        "setkey_saved": "🔐 {key} saved{masked}. I deleted your message.",
        "setkey_invalid": "That value doesn't look right for {key}.",
        "setkey_locked": "For safety, /setkey only works when ALLOWED_USER_IDS is set.",
        "wk_title": "Workout",
        "wk_checkin": "🏋️ Today's workout: {title}\n{plan}\n\nHow did it go? Tell me what you did "
                      "(text or voice), or tap a button.",
        "wk_btn_done": "✅ Done as planned",
        "wk_btn_skip": "⏭ Skipped",
        "wk_saved": "✅ Workout saved{sheet}.",
        "wk_skipped": "⏭ Marked as skipped. Rest well, see you next session!",
        "wk_rest": "No workout planned for today: rest day 😌",
        "wk_noprogram": "You don't have a training program yet. Ask me, for example: "
                        "Create a 3-day gym program for me.",
        "wk_feeling": "Feeling",
        "wk_notes": "Notes",
        "unit_kg": "kg",
        "unit_min": "min",
        "unit_km": "km",
        "gsa_bad": "That file isn't a Google service account key.",
        "wk_sheet": " and added to your Google Sheet",
        "gsa_saved": "🔐 Google key saved and your message deleted.\n\nNext: create a blank Google "
                     "Sheet, click Share and add this address as Editor:\n{email}\n\n"
                     "Then send: /setkey GOOGLE_SHEET_ID followed by the sheet's link.",
        "sheet_ok": "✅ Google Sheet connected: {name}\nI set up the Dashboard, Log and Program "
                    "tabs:\n{url}",
        "sheet_bad": "⚠️ Saved, but I can't open that sheet yet. Check the link and that the sheet "
                     "is shared with the service account as Editor.",
        "sheet_nokey": "⚠️ Saved, but first send me the Google service account key file (.json).",
        "sheet_link": "📊 Your workout sheet:\n{url}",
        "sheet_off": "Google Sheet isn't connected yet. Send the key file, then /setkey "
                     "GOOGLE_SHEET_ID with the sheet's link.",
        "sheet_backfill": "📥 Copied your {n} earlier workouts into the Log.",
    },
    "az": {
        "help": (
            "Mənimlə adi dildə yazışın və ya səsli mesaj göndərin 🎤, məsələn:\n"
            "- Qeyd et: Elnurun ad günü 12 dekabrdadır\n"
            "- Tapşırıq: cümə gününə qədər hesab-fakturanı göndər, vacibdir\n"
            "- Sabah saat 18:00-da anama zəng etməyi xatırlat\n"
            "- Günümü planla\n"
            "- Mənim üçün həftədə 3 günlük zal proqramı hazırla\n"
            "- Bu gün: jim 4x8 60 kq, squat 3x10 80 kq\n\n"
            "Əmrlər:\n"
            "/qeyd <mətn> - qeyd saxla\n"
            "/qeydler [söz] - qeydləri göstər və ya axtar\n"
            "/tapsiriq <mətn> - tapşırıq əlavə et\n"
            "/tapsiriqlar - açıq tapşırıqlar\n"
            "/hazir <nömrə> - tapşırığı tamamla\n"
            "/xatirlat <nə vaxt> <nə> - xatırlatma qur\n"
            "/plan - bugünkü plan\n"
            "/gundem - tapşırıqlar və xatırlatmalar\n"
            "/mesq - bugünkü məşq və qeyd düymələri\n"
            "/cedvel - Google Sheet məşq cədvəlinin linki\n"
            "/sifirla - söhbət yaddaşını təmizlə\n"
            "/setkey AD dəyər - ayar və ya açar dəyiş (mesajınız silinir)"
        ),
        "start": "Salam! Mən sizin şəxsi köməkçinizəm.\nTelegram ID-niz: {uid}\n\n",
        "private": "Bu bot şəxsi istifadə üçündür. Sahibindən ID-nizi "
                   "ALLOWED_USER_IDS siyahısına əlavə etməsini xahiş edin.",
        "note_usage": "İstifadə: /qeyd <mətn>",
        "note_saved": "📝 Qeyd #{id} saxlanıldı",
        "no_notes": "Heç bir qeyd tapılmadı.",
        "no_tasks": "Açıq tapşırıq yoxdur 🎉",
        "open_tasks": "📋 Açıq tapşırıqlar:",
        "due": " (son tarix: {due}{overdue})",
        "overdue": " ⚠️ vaxtı keçib",
        "done_usage": "İstifadə: /hazir <tapşırıq nömrəsi>",
        "done_ok": "✅ Tamamlandı!",
        "done_fail": "Bu nömrə ilə açıq tapşırıq tapılmadı.",
        "reminders_header": "⏰ Gələcək xatırlatmalar:",
        "none": "(yoxdur)",
        "reset": "🧹 Söhbət yaddaşı təmizləndi (qeydlər və tapşırıqlar saxlanılır).",
        "ai_error": "Bağışlayın, hazırda süni intellektə qoşula bilmədim. "
                    "Bir azdan yenidən cəhd edin.",
        "reminder": "⏰ Xatırlatma: {text}",
        "brief_header": "☀️ Sabahınız xeyir!\n\n",
        "brief_prompt": "Səhər xülasəmi hazırla: vaxtı keçmiş işlər, bu gün bitməli "
                        "olanlar, xatırlatmalar və günün təklif olunan planı.",
        "task_prompt": "Bu tapşırığı əlavə et: {text}",
        "task_empty": "Tapşırıq əlavə etmək istəyirəm.",
        "remind_prompt": "Xatırlatma qur: {text}",
        "remind_empty": "Xatırlatma qurmaq istəyirəm.",
        "plan_prompt": "Açıq tapşırıqlarım və xatırlatmalarım əsasında bu günün qalan "
                       "hissəsi üçün saatlara bölünmüş plan qur.",
        "voice_heard": "🎤 Eşitdim: «{text}»",
        "voice_off": "Səsli mesajlar hələ qoşulmayıb: ayarlarda OPENAI_API_KEY yoxdur.",
        "voice_fail": "Bağışlayın, səsli mesajı tanıya bilmədim. Yenidən cəhd edin və ya yazın.",
        "voice_empty": "Səsli mesajda heç nə eşidə bilmədim.",
        "lang_rule": (
            "The user's main language is Azerbaijani. Reply in natural, correct "
            "Azerbaijani (Latin script), not Turkish, unless the user clearly writes in "
            "another language. Understand Azerbaijani time expressions such as 'sabah' "
            "(tomorrow), 'birigün' (day after tomorrow), 'gələn həftə' (next week), "
            "'cümə günü' (Friday) and 'saat 9-da' (at 9)."
        ),
        "today_tasks": "📋 Bu gün və vaxtı keçmiş:",
        "tasks_first": "Əvvəlcə /tapsiriqlar göndərin, sonra həmin siyahıdakı nömrədən istifadə edin.",
        "todoist_error": "Bağışlayın, hazırda Todoist-ə qoşula bilmədim. Bir azdan yenidən cəhd edin.",
        "todoist_ok": "✅ Todoist qoşuldu ({n} layihə tapıldı).",
        "todoist_bad": "⚠️ Saxlanıldı, amma Todoist bu tokeni qəbul etmədi. "
                       "Yoxlayın və /setkey ilə yenidən göndərin.",
        "setkey_usage": "İstifadə: /setkey AD dəyər\nDəyişə biləcəyiniz ayarlar: {keys}",
        "setkey_saved": "🔐 {key} saxlanıldı{masked}. Mesajınızı sildim.",
        "setkey_invalid": "Bu dəyər {key} üçün düzgün görünmür.",
        "setkey_locked": "Təhlükəsizlik üçün /setkey yalnız ALLOWED_USER_IDS təyin olunanda işləyir.",
        "wk_title": "Məşq",
        "wk_checkin": "🏋️ Bugünkü məşq: {title}\n{plan}\n\nNecə keçdi? Nə etdiyinizi yazın və ya "
                      "səsli mesaj göndərin, ya da düyməyə toxunun.",
        "wk_btn_done": "✅ Plana uyğun etdim",
        "wk_btn_skip": "⏭ Buraxdım",
        "wk_saved": "✅ Məşq saxlanıldı{sheet}.",
        "wk_skipped": "⏭ Buraxılmış kimi qeyd edildi. Yaxşı dincəlin, növbəti məşqdə görüşərik!",
        "wk_rest": "Bu gün məşq planlaşdırılmayıb: istirahət günü 😌",
        "wk_noprogram": "Hələ məşq proqramınız yoxdur. Məsələn, belə yazın: "
                        "Mənim üçün həftədə 3 günlük zal proqramı hazırla.",
        "wk_feeling": "Əhval",
        "wk_notes": "Qeydlər",
        "unit_kg": "kq",
        "unit_min": "dəq",
        "unit_km": "km",
        "gsa_bad": "Bu fayl Google service account açarı deyil.",
        "wk_sheet": " və Google Sheet-ə əlavə edildi",
        "gsa_saved": "🔐 Google açarı saxlanıldı və mesajınız silindi.\n\nNövbəti addım: boş Google "
                     "Sheet yaradın, Share (Paylaş) düyməsinə basın və bu ünvanı Editor kimi "
                     "əlavə edin:\n{email}\n\nSonra göndərin: /setkey GOOGLE_SHEET_ID və "
                     "cədvəlin linki.",
        "sheet_ok": "✅ Google Sheet qoşuldu: {name}\nPanel, Gündəlik və Proqram vərəqlərini "
                    "hazırladım:\n{url}",
        "sheet_bad": "⚠️ Saxlanıldı, amma bu cədvəli hələ aça bilmirəm. Linki və cədvəlin service "
                     "account ilə Editor kimi paylaşıldığını yoxlayın.",
        "sheet_nokey": "⚠️ Saxlanıldı, amma əvvəlcə Google service account açar faylını (.json) göndərin.",
        "sheet_link": "📊 Məşq cədvəliniz:\n{url}",
        "sheet_off": "Google Sheet hələ qoşulmayıb. Açar faylını göndərin, sonra /setkey "
                     "GOOGLE_SHEET_ID və cədvəlin linkini yazın.",
        "sheet_backfill": "📥 Əvvəlki {n} məşqinizi Gündəlik vərəqinə köçürdüm.",
    },
}

# ---------------------------------------------------------------- config
# Fixed at startup:
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DB_PATH = os.getenv("DB_PATH", "assistant.db")
ALLOWED = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip()}
ENV_PATH = Path(__file__).with_name(".env")
TODOIST_BASE = os.getenv("TODOIST_API_BASE", "https://api.todoist.com/api/v1").rstrip("/")
GSA_PATH = Path(__file__).with_name("google-service-account.json")


def load_config():
    """(Re)read changeable settings. Runs at startup and after /setkey."""
    global MODEL, TZ, BRIEF_TIME, LANG, T, VOICE_LANGUAGE, TRANSCRIBE_MODEL, client, stt
    global CHECKIN_TIME
    MODEL = os.getenv("CLAUDE_MODEL", "").strip() or "claude-sonnet-5-5"
    TZ = ZoneInfo(os.getenv("TIMEZONE", "").strip() or "UTC")
    BRIEF_TIME = os.getenv("DAILY_BRIEF_TIME", "08:00").strip()  # blank = off
    CHECKIN_TIME = os.getenv("WORKOUT_CHECKIN_TIME", "21:00").strip()  # blank = off
    lang = os.getenv("BOT_LANGUAGE", "en").strip().lower()
    LANG = lang if lang in TEXTS else "en"
    T = TEXTS[LANG]
    # Voice: speech-to-text via OpenAI. VOICE_LANGUAGE blank = auto-detect.
    VOICE_LANGUAGE = os.getenv("VOICE_LANGUAGE", "az" if LANG == "az" else "").strip()
    TRANSCRIBE_MODEL = os.getenv("TRANSCRIBE_MODEL", "").strip() or "gpt-4o-transcribe"
    client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    stt = AsyncOpenAI(api_key=openai_key) if openai_key else None


load_config()
history = defaultdict(lambda: deque(maxlen=12))  # short chat memory per user
last_list = {}  # per user: Todoist task IDs from the last numbered list
http = httpx.AsyncClient(timeout=20)
log = logging.getLogger("assistant")

# -------------------------------------------------------------- database
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript(
    """
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY, user_id INTEGER, content TEXT,
        tags TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, due TEXT,
        priority TEXT DEFAULT 'medium', status TEXT DEFAULT 'open',
        created_at TEXT);
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY, user_id INTEGER, text TEXT,
        remind_at TEXT, sent INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS programs (
        user_id INTEGER PRIMARY KEY, data TEXT, calendar_ids TEXT DEFAULT '[]',
        updated_at TEXT);
    CREATE TABLE IF NOT EXISTS workouts (
        id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, title TEXT,
        status TEXT DEFAULT 'done', exercises TEXT, duration_min REAL, feeling TEXT,
        notes TEXT, event_id TEXT, event_kind TEXT, created_at TEXT);
    """
)

FMT = "%Y-%m-%d %H:%M"


def now() -> str:
    return datetime.now(TZ).strftime(FMT)


def check_time(value: str) -> str:
    """Raise if value isn't 'YYYY-MM-DD HH:MM', so the AI gets a clear error."""
    datetime.strptime(value, FMT)
    return value


# ------------------------------------------------- tools the AI can call
def add_note(uid, content, tags=""):
    cur = db.execute(
        "INSERT INTO notes (user_id, content, tags, created_at) VALUES (?,?,?,?)",
        (uid, content, tags, now()),
    )
    db.commit()
    return {"saved_note_id": cur.lastrowid}


def search_notes(uid, query="", limit=10):
    like = f"%{query}%"
    rows = db.execute(
        "SELECT id, content, tags, created_at FROM notes WHERE user_id=? "
        "AND (content LIKE ? OR tags LIKE ?) ORDER BY id DESC LIMIT ?",
        (uid, like, like, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_note(uid, note_id):
    cur = db.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, uid))
    db.commit()
    return {"deleted": cur.rowcount == 1}


def add_task(uid, title, due=None, priority="medium"):
    cur = db.execute(
        "INSERT INTO tasks (user_id, title, due, priority, created_at) VALUES (?,?,?,?,?)",
        (uid, title, check_time(due) if due else None, priority, now()),
    )
    db.commit()
    return {"task_id": cur.lastrowid}


def list_tasks(uid, status="open"):
    rows = db.execute(
        "SELECT id, title, due, priority, status FROM tasks WHERE user_id=? "
        "AND (?='all' OR status=?) ORDER BY due IS NULL, due, id",
        (uid, status, status),
    ).fetchall()
    return [dict(r) for r in rows]


def update_task(uid, task_id, title=None, due=None, priority=None):
    fields = {"title": title, "due": check_time(due) if due else None, "priority": priority}
    fields = {k: v for k, v in fields.items() if v is not None}
    if not fields:
        return {"updated": False, "error": "nothing to change"}
    sets = ", ".join(f"{k}=?" for k in fields)
    cur = db.execute(
        f"UPDATE tasks SET {sets} WHERE id=? AND user_id=?",
        (*fields.values(), task_id, uid),
    )
    db.commit()
    return {"updated": cur.rowcount == 1}


def complete_task(uid, task_id):
    cur = db.execute(
        "UPDATE tasks SET status='done' WHERE id=? AND user_id=? AND status='open'",
        (task_id, uid),
    )
    db.commit()
    return {"completed": cur.rowcount == 1}


def delete_task(uid, task_id):
    cur = db.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, uid))
    db.commit()
    return {"deleted": cur.rowcount == 1}


def set_reminder(uid, text, remind_at):
    cur = db.execute(
        "INSERT INTO reminders (user_id, text, remind_at) VALUES (?,?,?)",
        (uid, text, check_time(remind_at)),
    )
    db.commit()
    return {"reminder_id": cur.lastrowid, "will_fire_at": remind_at}


def list_reminders(uid):
    rows = db.execute(
        "SELECT id, text, remind_at FROM reminders WHERE user_id=? AND sent=0 "
        "ORDER BY remind_at",
        (uid,),
    ).fetchall()
    return [dict(r) for r in rows]


def cancel_reminder(uid, reminder_id):
    cur = db.execute(
        "DELETE FROM reminders WHERE id=? AND user_id=? AND sent=0", (reminder_id, uid)
    )
    db.commit()
    return {"cancelled": cur.rowcount == 1}


# ------------------------------------------------------------- Todoist
PRIO = {"low": 1, "medium": 2, "high": 3, "urgent": 4}  # Todoist: 4 = most urgent (p1)
PRIO_NAME = {v: k for k, v in PRIO.items()}
_projects = {"at": 0.0, "items": []}


def todoist_on() -> bool:
    return bool(os.getenv("TODOIST_API_TOKEN", "").strip())


async def td(method, path, **kw):
    """Call the Todoist API and return its JSON (or None for empty replies)."""
    token = os.getenv("TODOIST_API_TOKEN", "").strip()
    r = await http.request(method, f"{TODOIST_BASE}{path}",
                           headers={"Authorization": f"Bearer {token}"}, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"Todoist error {r.status_code}: {r.text[:200]}")
    return r.json() if r.content else None


async def td_list(path, params=None, max_items=200):
    """Fetch a list from Todoist, following pages."""
    params = dict(params or {})
    items = []
    while True:
        data = await td("GET", path, params=params)
        if isinstance(data, list):  # older API style: plain list
            return data[:max_items]
        items += data.get("results", [])
        cursor = data.get("next_cursor")
        if not cursor or len(items) >= max_items:
            return items[:max_items]
        params["cursor"] = cursor


async def td_projects(force=False):
    if force or time.time() - _projects["at"] > 600:
        _projects["items"] = await td_list("/projects")
        _projects["at"] = time.time()
    return _projects["items"]


def fold(text: str) -> str:
    """Compare names ignoring case, including Azerbaijani İ/i and I/ı."""
    return text.strip().replace("İ", "i").replace("ı", "i").lower()


async def td_project_id(name):
    for attempt in (False, True):
        projects = await td_projects(force=attempt)
        wanted = fold(name)
        for p in projects:
            if fold(p["name"]) == wanted:
                return p["id"]
        for p in projects:
            if wanted in fold(p["name"]):
                return p["id"]
    names = ", ".join(p["name"] for p in projects)
    raise ValueError(f"No Todoist project called '{name}'. Projects: {names}")


def td_due(task):
    """Due date as 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS' in local time, or None."""
    due = task.get("due") or {}
    value = due.get("datetime") or due.get("date")
    if value and value.endswith("Z"):
        local = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ)
        value = local.strftime("%Y-%m-%dT%H:%M:%S")
    return value


def due_overdue(value) -> bool:
    if not value:
        return False
    if "T" in value:
        return value.replace("T", " ")[:16] < now()
    return value < now()[:10]


async def fetch_tasks(filter=""):
    if filter:
        try:
            tasks = await td_list("/tasks/filter", {"query": filter})
        except RuntimeError as e:
            if "404" not in str(e):
                raise
            tasks = await td_list("/tasks", {"filter": filter})  # older API style
    else:
        tasks = await td_list("/tasks")
    names = {p["id"]: p["name"] for p in await td_projects()}
    out = []
    for t in tasks:
        out.append({
            "id": t["id"],
            "content": t["content"],
            "due": td_due(t),
            "recurring": bool((t.get("due") or {}).get("is_recurring")),
            "priority": PRIO_NAME.get(t.get("priority", 1), "low"),
            "project": names.get(t.get("project_id"), ""),
            "description": (t.get("description") or "")[:200],
        })
    out.sort(key=lambda x: (x["due"] is None, x["due"] or ""))
    return out


async def todoist_list_tasks(uid, filter=""):
    return (await fetch_tasks(filter))[:50]


async def todoist_add_task(uid, content, due_string=None, priority=None,
                           project=None, description=None):
    body = {"content": content}
    if due_string:
        body.update(due_string=due_string, due_lang="en")
    if priority:
        body["priority"] = PRIO[priority]
    if description:
        body["description"] = description
    if project:
        body["project_id"] = await td_project_id(project)
    t = await td("POST", "/tasks", json=body)
    return {"created_task_id": t["id"], "due": td_due(t)}


async def todoist_update_task(uid, task_id, content=None, due_string=None,
                              priority=None, description=None):
    body = {}
    if content:
        body["content"] = content
    if due_string:
        body.update(due_string=due_string, due_lang="en")
    if priority:
        body["priority"] = PRIO[priority]
    if description is not None:
        body["description"] = description
    if not body:
        return {"updated": False, "error": "nothing to change"}
    await td("POST", f"/tasks/{task_id}", json=body)
    return {"updated": True}


async def todoist_complete_task(uid, task_id):
    await td("POST", f"/tasks/{task_id}/close")
    return {"completed": True}


async def todoist_delete_task(uid, task_id):
    await td("DELETE", f"/tasks/{task_id}")
    return {"deleted": True}


async def todoist_list_projects(uid):
    return [p["name"] for p in await td_projects(force=True)]


# ------------------------------------------------------ Google Sheets
SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
ROLES = ("dash", "log", "program", "data")
EPOCH = datetime(1899, 12, 30).date()  # Google Sheets day zero

SHEET_TEXTS = {
    "en": {
        "tab_dash": "Dashboard", "tab_log": "Log", "tab_program": "Program", "tab_data": "_data",
        "log_headers": ["Date", "Week", "Workout", "Exercise", "Sets", "Reps", "Weight (kg)",
                        "Volume (kg)", "Duration (min)", "Distance (km)", "Status", "Feeling",
                        "Notes", "Workout ID", "Count"],
        "program_headers": ["Day", "Workout", "Exercise", "Sets", "Reps", "Weight (kg)",
                            "Duration (min)", "Notes"],
        "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "title": "🏋️ Workout Dashboard",
        "kpis": ["Workouts done", "This week", "Total volume", "Completion", "Last workout"],
        "pick": "Exercise ▸", "pr": "🏆 Best:", "kg": "kg",
        "chart_weekly": "Workouts and volume per week",
        "axis_week": "Week", "axis_workouts": "Workouts", "axis_volume": "Volume (kg)",
        "chart_progress": "Selected exercise: max weight over time",
        "axis_date": "Date", "axis_weight": "Weight (kg)",
        "chart_top": "Top exercises by volume (kg)",
        "chart_split": "Workouts by type",
        "records": "🏆 Personal records", "rec_headers": ["Exercise", "Best (kg)", "Trend"],
        "data_headers": ["Week", "Workouts", "Volume (kg)", "", "Exercise", "Volume (kg)", "",
                         "Workout", "Count", "", "Exercises", "", "Date", "Max weight (kg)",
                         "Volume (kg)"],
    },
    "az": {
        "tab_dash": "Panel", "tab_log": "Gündəlik", "tab_program": "Proqram", "tab_data": "_data",
        "log_headers": ["Tarix", "Həftə", "Məşq", "Hərəkət", "Set", "Təkrar", "Çəki (kq)",
                        "Həcm (kq)", "Müddət (dəq)", "Məsafə (km)", "Status", "Əhval", "Qeyd",
                        "Məşq ID", "Say"],
        "program_headers": ["Gün", "Məşq", "Hərəkət", "Set", "Təkrar", "Çəki (kq)",
                            "Müddət (dəq)", "Qeyd"],
        "days": ["Bazar ertəsi", "Çərşənbə axşamı", "Çərşənbə", "Cümə axşamı", "Cümə", "Şənbə",
                 "Bazar"],
        "title": "🏋️ Məşq Paneli",
        "kpis": ["Edilən məşqlər", "Bu həftə", "Ümumi həcm", "İcra faizi", "Son məşq"],
        "pick": "Hərəkət ▸", "pr": "🏆 Rekord:", "kg": "kq",
        "chart_weekly": "Həftəlik məşq sayı və həcm",
        "axis_week": "Həftə", "axis_workouts": "Məşq sayı", "axis_volume": "Həcm (kq)",
        "chart_progress": "Seçilmiş hərəkət: maksimum çəki",
        "axis_date": "Tarix", "axis_weight": "Çəki (kq)",
        "chart_top": "Ən çox həcmli hərəkətlər (kq)",
        "chart_split": "Məşq növləri",
        "records": "🏆 Şəxsi rekordlar", "rec_headers": ["Hərəkət", "Rekord (kq)", "Trend"],
        "data_headers": ["Həftə", "Məşq sayı", "Həcm (kq)", "", "Hərəkət", "Həcm (kq)", "",
                         "Məşq", "Say", "", "Hərəkətlər", "", "Tarix", "Maks. çəki (kq)",
                         "Həcm (kq)"],
    },
}

# Dashboard formulas. {L} = Log tab, {D} = Dashboard tab (filled in at setup).
F_WEEKLY = r'''=IFERROR(SORT(QUERY({L}!A2:O,"select B, sum(O), sum(H) where K = '✅' and B is not null group by B order by B desc limit 12 label B '', sum(O) '', sum(H) ''",0),1,TRUE),"")'''
F_TOP = r'''=IFERROR(QUERY({L}!A2:O,"select D, sum(H) where K = '✅' and H > 0 group by D order by sum(H) desc limit 10 label D '', sum(H) ''",0),"")'''
F_SPLIT = r'''=IFERROR(QUERY({L}!A2:O,"select C, sum(O) where K = '✅' and O > 0 group by C order by sum(O) desc label C '', sum(O) ''",0),"")'''
F_EXERCISES = r'''=IFERROR(SORT(UNIQUE(FILTER({L}!D2:D,{L}!D2:D<>"",{L}!D2:D<>"—"))),"")'''
F_PROGRESS = r'''=IFERROR(QUERY({L}!A2:O,"select A, max(G), sum(H) where D = '"&SUBSTITUTE({D}!$B$7,"'","")&"' and G > 0 group by A order by A label A '', max(G) '', sum(H) ''",0),"")'''
K_DONE = r'''=SUMIFS({L}!O2:O,{L}!K2:K,"✅")'''
K_WEEK = r'''=SUMIFS({L}!O2:O,{L}!K2:K,"✅",{L}!A2:A,">="&(TODAY()-WEEKDAY(TODAY(),3)))'''
K_VOLUME = r'''=SUMIFS({L}!H2:H,{L}!K2:K,"✅")'''
K_RATE = r'''=IFERROR(SUMIFS({L}!O2:O,{L}!K2:K,"✅")/SUM({L}!O2:O),0)'''
K_LAST = r'''=IF(MAXIFS({L}!A2:A,{L}!K2:K,"✅")=0,"—",MAXIFS({L}!A2:A,{L}!K2:K,"✅"))'''
K_PR = r'''=IFERROR(MAXIFS({L}!G2:G,{L}!D2:D,B7),0)&" {KG}"'''
F_RECORDS = r'''=IFERROR(QUERY({L}!A2:O,"select D, max(G) where G > 0 group by D order by max(G) desc limit 15 label D '', max(G) ''",0),"")'''
F_TREND = r'''=IF(A{R}="","",IFERROR(SPARKLINE(FILTER({L}!$G$2:$G,{L}!$D$2:$D=A{R},{L}!$G$2:$G>0)),""))'''

_gcreds = {"c": None}
_meta = {"at": 0.0, "data": None}


def sheet_key() -> str:
    return os.getenv("GOOGLE_SHEET_ID", "").strip()


def sheets_on() -> bool:
    return GSA_PATH.exists() and bool(sheet_key())


def sheet_url() -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_key()}/edit"


def _google_token() -> str:
    """Get an access token for the service account (runs in a thread)."""
    from google.auth.transport.requests import Request  # imported here so the bot
    from google.oauth2 import service_account           # still runs without these libs
    if _gcreds["c"] is None:
        _gcreds["c"] = service_account.Credentials.from_service_account_file(
            str(GSA_PATH), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    if not _gcreds["c"].valid:
        _gcreds["c"].refresh(Request())
    return _gcreds["c"].token


async def gsheet(method, path="", **kw):
    """Call the Google Sheets API for the connected spreadsheet."""
    token = await asyncio.to_thread(_google_token)
    r = await http.request(method, f"{SHEETS_BASE}/{sheet_key()}{path}",
                           headers={"Authorization": f"Bearer {token}"}, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"Google Sheets error {r.status_code}: {r.text[:200]}")
    return r.json() if r.content else None


def qt(tab) -> str:
    """Tab name quoted for formulas and ranges."""
    return "'" + tab.replace("'", "''") + "'"


def a1(tab, cells) -> str:
    """URL-safe range such as 'Gündəlik'!A2:O."""
    return quote(f"{qt(tab)}!{cells}", safe="")


async def sheet_meta(force=False):
    if force or _meta["data"] is None or time.time() - _meta["at"] > 300:
        _meta["data"] = await gsheet("GET", params={"fields": "properties.title,sheets.properties"})
        _meta["at"] = time.time()
    return _meta["data"]


async def tabs(force=False):
    """Our tab names and IDs, found in either language. Missing tabs have ID None."""
    meta = await sheet_meta(force)
    props = {s["properties"]["title"]: s["properties"] for s in meta.get("sheets", [])}
    names, ids = {}, {}
    for role in ROLES:
        options = [SHEET_TEXTS[LANG][f"tab_{role}"]] + [t[f"tab_{role}"] for t in SHEET_TEXTS.values()]
        found = next((o for o in options if o in props), None)
        names[role] = found or SHEET_TEXTS[LANG][f"tab_{role}"]
        ids[role] = props[found]["sheetId"] if found else None
    return names, ids, props


# --- formatting helpers for the Sheets API
def rgb(hex_color):
    h = hex_color.lstrip("#")
    return {"rgbColor": {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255,
                         "blue": int(h[4:6], 16) / 255}}


def grid(sid, r0, r1, c0, c1):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def style(rng, bg=None, color=None, bold=None, size=None, italic=None, align=None,
          number=None, wrap=None):
    f, tf = {}, {}
    if bg:
        f["backgroundColorStyle"] = rgb(bg)
    if color:
        tf["foregroundColorStyle"] = rgb(color)
    if bold is not None:
        tf["bold"] = bold
    if italic is not None:
        tf["italic"] = italic
    if size:
        tf["fontSize"] = size
    if tf:
        f["textFormat"] = tf
    if align:
        f["horizontalAlignment"] = align
        f["verticalAlignment"] = "MIDDLE"
    if number:
        f["numberFormat"] = {"type": number[0], "pattern": number[1]}
    if wrap:
        f["wrapStrategy"] = wrap
    return {"repeatCell": {"range": rng, "cell": {"userEnteredFormat": f},
                           "fields": "userEnteredFormat(" + ",".join(f) + ")"}}


def sizes(sid, dimension, spans):
    """spans: (first, last_exclusive, pixels)"""
    return [{"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": dimension, "startIndex": a, "endIndex": b},
        "properties": {"pixelSize": px}, "fields": "pixelSize"}} for a, b, px in spans]


def merge(rng):
    return {"mergeCells": {"range": rng, "mergeType": "MERGE_ALL"}}


def banding(rng, header, band):
    return {"addBanding": {"bandedRange": {"range": rng, "rowProperties": {
        "headerColorStyle": rgb(header), "firstBandColorStyle": rgb("#ffffff"),
        "secondBandColorStyle": rgb(band)}}}}


def source(sid, r0, r1, col):
    return {"sourceRange": {"sources": [grid(sid, r0, r1, col, col + 1)]}}


def chart(dash_id, row, col, spec, width=600, height=320):
    spec["hiddenDimensionStrategy"] = "SHOW_ALL"
    return {"addChart": {"chart": {"spec": spec, "position": {"overlayPosition": {
        "anchorCell": {"sheetId": dash_id, "rowIndex": row, "columnIndex": col},
        "widthPixels": width, "heightPixels": height}}}}}


# --- the four tabs
def build_log(sid, name):
    S = SHEET_TEXTS[LANG]
    reqs = [
        style(grid(sid, 0, 1, 0, 15), bg="#166534", color="#ffffff", bold=True, align="CENTER",
              wrap="WRAP"),
        banding(grid(sid, 0, 5000, 0, 13), "#166534", "#f0fdf4"),
        style(grid(sid, 1, 5000, 0, 2), number=("DATE", "dd.mm.yyyy")),
        style(grid(sid, 1, 5000, 10, 11), align="CENTER"),
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 13, "endIndex": 15},
            "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
        {"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [grid(sid, 1, 5000, 0, 13)],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue": '=$K2="⏭"'}]},
                "format": {"textFormat": {"italic": True,
                                          "foregroundColorStyle": rgb("#9ca3af")}}}}}},
    ] + sizes(sid, "COLUMNS", [(0, 2, 95), (2, 3, 150), (3, 4, 190), (4, 10, 85),
                               (10, 11, 65), (11, 12, 110), (12, 13, 230)])
    values = [{"range": f"{qt(name)}!A1", "values": [S["log_headers"]]}]
    return reqs, values


def build_program(sid, name):
    S = SHEET_TEXTS[LANG]
    reqs = [
        style(grid(sid, 0, 1, 0, 8), bg="#1e3a8a", color="#ffffff", bold=True, align="CENTER"),
        banding(grid(sid, 0, 300, 0, 8), "#1e3a8a", "#eff6ff"),
        style(grid(sid, 1, 300, 0, 2), bold=True),
        {"setDataValidation": {"range": grid(sid, 1, 300, 0, 1), "rule": {
            "condition": {"type": "ONE_OF_LIST",
                          "values": [{"userEnteredValue": d} for d in S["days"]]},
            "showCustomUi": True, "strict": False}}},
    ] + sizes(sid, "COLUMNS", [(0, 1, 150), (1, 2, 170), (2, 3, 210), (3, 7, 95), (7, 8, 230)])
    values = [{"range": f"{qt(name)}!A1", "values": [S["program_headers"]]}]
    return reqs, values


def build_data(sid, name, log_name, dash_name):
    S = SHEET_TEXTS[LANG]
    L, D = qt(log_name), qt(dash_name)

    def fill(formula):
        return formula.replace("{L}", L).replace("{D}", D)

    row2 = [""] * 15
    row2[0], row2[4], row2[7] = fill(F_WEEKLY), fill(F_TOP), fill(F_SPLIT)
    row2[10], row2[12] = fill(F_EXERCISES), fill(F_PROGRESS)
    reqs = [style(grid(sid, 1, 1000, 0, 1), number=("DATE", "dd.mm")),
            style(grid(sid, 1, 1000, 12, 13), number=("DATE", "dd.mm.yy"))]
    values = [{"range": f"{qt(name)}!A1", "values": [S["data_headers"], row2]}]
    return reqs, values


def build_dashboard(sid, name, log_name, data_id):
    S = SHEET_TEXTS[LANG]
    L, D = qt(log_name), qt(name)

    def fill(formula, row=None):
        out = formula.replace("{L}", L).replace("{D}", D).replace("{KG}", S["kg"])
        return out.replace("{R}", str(row)) if row else out

    accents = ["#16a34a", "#2563eb", "#9333ea", "#ea580c", "#0f766e"]
    formats = [("NUMBER", "0"), ("NUMBER", "0"), ("NUMBER", f'#,##0 "{S["kg"]}"'),
               ("PERCENT", "0%"), ("DATE", "dd.mm.yyyy")]
    reqs = [merge(grid(sid, 0, 1, 0, 10)),
            style(grid(sid, 0, 1, 0, 10), bg="#111827", color="#ffffff", bold=True, size=20,
                  align="CENTER"),
            style(grid(sid, 2, 3, 0, 10), bg="#f3f4f6", color="#6b7280", bold=True, size=10,
                  align="CENTER")]
    for i in range(5):
        c = i * 2
        reqs += [merge(grid(sid, 2, 3, c, c + 2)), merge(grid(sid, 3, 4, c, c + 2)),
                 style(grid(sid, 3, 4, c, c + 2), bg="#f3f4f6", color=accents[i], bold=True,
                       size=22, align="CENTER", number=formats[i])]
    reqs += [
        style(grid(sid, 6, 7, 0, 1), bold=True, align="RIGHT"),
        merge(grid(sid, 6, 7, 1, 3)),
        style(grid(sid, 6, 7, 1, 3), bg="#fef9c3", bold=True, align="CENTER"),
        style(grid(sid, 6, 7, 3, 4), bold=True, color="#6b7280", align="RIGHT"),
        style(grid(sid, 6, 7, 4, 5), bold=True, color="#16a34a", size=12, align="LEFT"),
        {"setDataValidation": {"range": grid(sid, 6, 7, 1, 2), "rule": {
            "condition": {"type": "ONE_OF_RANGE",
                          "values": [{"userEnteredValue": f"={qt('_data')}!$K$2:$K$300"}]},
            "showCustomUi": True, "strict": False}}},
        style(grid(sid, 42, 43, 0, 3), bold=True, size=14),
        style(grid(sid, 43, 44, 0, 3), bg="#e5e7eb", bold=True, align="CENTER"),
    ]
    reqs += sizes(sid, "COLUMNS", [(0, 1, 180), (1, 10, 110)])
    reqs += sizes(sid, "ROWS", [(0, 1, 54), (3, 4, 56)])
    reqs += [
        chart(sid, 8, 0, {"title": S["chart_weekly"], "basicChart": {
            "chartType": "COMBO", "legendPosition": "BOTTOM_LEGEND", "headerCount": 1,
            "axis": [{"position": "BOTTOM_AXIS", "title": S["axis_week"]},
                     {"position": "LEFT_AXIS", "title": S["axis_workouts"]},
                     {"position": "RIGHT_AXIS", "title": S["axis_volume"]}],
            "domains": [{"domain": source(data_id, 0, 13, 0)}],
            "series": [{"series": source(data_id, 0, 13, 1), "targetAxis": "LEFT_AXIS",
                        "type": "COLUMN", "colorStyle": rgb("#2563eb")},
                       {"series": source(data_id, 0, 13, 2), "targetAxis": "RIGHT_AXIS",
                        "type": "LINE", "colorStyle": rgb("#9333ea")}]}}),
        chart(sid, 8, 5, {"title": S["chart_progress"], "basicChart": {
            "chartType": "LINE", "legendPosition": "NO_LEGEND", "headerCount": 1,
            "lineSmoothing": True,
            "axis": [{"position": "BOTTOM_AXIS", "title": S["axis_date"]},
                     {"position": "LEFT_AXIS", "title": S["axis_weight"]}],
            "domains": [{"domain": source(data_id, 0, 1000, 12)}],
            "series": [{"series": source(data_id, 0, 1000, 13), "targetAxis": "LEFT_AXIS",
                        "colorStyle": rgb("#16a34a")}]}}),
        chart(sid, 25, 0, {"title": S["chart_top"], "basicChart": {
            "chartType": "BAR", "legendPosition": "NO_LEGEND", "headerCount": 1,
            "domains": [{"domain": source(data_id, 0, 11, 4)}],
            "series": [{"series": source(data_id, 0, 11, 5), "targetAxis": "BOTTOM_AXIS",
                        "colorStyle": rgb("#9333ea")}]}}),
        chart(sid, 25, 5, {"title": S["chart_split"], "pieChart": {
            "legendPosition": "RIGHT_LEGEND", "pieHole": 0.45,
            "domain": source(data_id, 1, 40, 7), "series": source(data_id, 1, 40, 8)}}),
    ]
    values = [
        {"range": f"{D}!A1", "values": [[S["title"]]]},
        {"range": f"{D}!A3", "values": [[S["kpis"][0], "", S["kpis"][1], "", S["kpis"][2], "",
                                         S["kpis"][3], "", S["kpis"][4], ""]]},
        {"range": f"{D}!A4", "values": [[fill(K_DONE), "", fill(K_WEEK), "", fill(K_VOLUME), "",
                                         fill(K_RATE), "", fill(K_LAST), ""]]},
        {"range": f"{D}!A7", "values": [[S["pick"], "", "", S["pr"], fill(K_PR)]]},
        {"range": f"{D}!A43", "values": [[S["records"]]]},
        {"range": f"{D}!A44", "values": [S["rec_headers"]]},
        {"range": f"{D}!A45", "values": [[fill(F_RECORDS)]]},
        {"range": f"{D}!C45:C59", "values": [[fill(F_TREND, r)] for r in range(45, 60)]},
    ]
    return reqs, values


async def ensure_sheet():
    """Create any missing tabs (Dashboard, Log, Program, _data). Returns the file's title."""
    names, ids, props = await tabs(force=True)
    missing = [role for role in ROLES if ids[role] is None]
    title = (await sheet_meta())["properties"]["title"]
    if not missing:
        return title
    used = {p["sheetId"] for p in props.values()}
    for i, role in enumerate(ROLES):
        if ids[role] is None:
            new_id = 1001 + i * 10
            while new_id in used:
                new_id += 1
            used.add(new_id)
            ids[role] = new_id
    grid_size = {"dash": {"rowCount": 80, "columnCount": 12, "hideGridlines": True},
                 "log": {"rowCount": 5000, "columnCount": 15, "frozenRowCount": 1},
                 "program": {"rowCount": 300, "columnCount": 8, "frozenRowCount": 1},
                 "data": {"rowCount": 1000, "columnCount": 15}}
    tab_color = {"dash": "#f59e0b", "log": "#16a34a", "program": "#2563eb", "data": "#9ca3af"}
    reqs, values = [], []
    for index, role in enumerate(ROLES):
        if role in missing:
            p = {"sheetId": ids[role], "title": names[role], "index": index,
                 "gridProperties": grid_size[role], "tabColorStyle": rgb(tab_color[role])}
            if role == "data":
                p["hidden"] = True
            reqs.append({"addSheet": {"properties": p}})
    builders = {
        "log": lambda: build_log(ids["log"], names["log"]),
        "program": lambda: build_program(ids["program"], names["program"]),
        "data": lambda: build_data(ids["data"], names["data"], names["log"], names["dash"]),
        "dash": lambda: build_dashboard(ids["dash"], names["dash"], names["log"], ids["data"]),
    }
    for role in ROLES:
        if role in missing:
            r, v = builders[role]()
            reqs += r
            values += v
    # A brand-new file comes with one empty default tab ("Sheet1"): remove it.
    others = [p for t, p in props.items() if t not in names.values()]
    if len(props) == 1 and others:
        cells = await gsheet("GET", f"/values/{a1(others[0]['title'], 'A1:Z50')}")
        if not cells.get("values"):
            reqs.append({"deleteSheet": {"sheetId": others[0]["sheetId"]}})
    await gsheet("POST", ":batchUpdate", json={"requests": reqs})
    await gsheet("POST", "/values:batchUpdate",
                 json={"valueInputOption": "USER_ENTERED", "data": values})
    await sheet_meta(force=True)
    return title


# ----------------------------------------------------------- workouts
def today_date():
    return datetime.now(TZ).date()


def parse_day(value):
    return datetime.strptime(value, "%Y-%m-%d").date() if value else today_date()


def num(x) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def clean_num(x):
    return int(x) if isinstance(x, float) and x.is_integer() else x


def fmt_exercise(e) -> str:
    detail = ""
    sets, reps = e.get("sets"), e.get("reps")
    if sets and reps:
        detail = f"{num(sets)}×{reps}"
    elif reps:
        detail = str(reps)
    elif sets:
        detail = f"{num(sets)}×"
    if e.get("weight_kg"):
        detail += f" @ {num(e['weight_kg'])} {T['unit_kg']}"
    if e.get("duration_min"):
        detail += f" {num(e['duration_min'])} {T['unit_min']}"
    if e.get("distance_km"):
        detail += f" {num(e['distance_km'])} {T['unit_km']}"
    line = f"• {e.get('name', '?')}" + (f": {detail.strip()}" if detail.strip() else "")
    if e.get("notes"):
        line += f" ({e['notes']})"
    return line


def total_reps(e) -> int:
    reps = str(e.get("reps") or "").strip()
    nums = [int(n) for n in re.findall(r"\d+", reps)]
    if not nums:
        return 0
    if "," in reps:  # "10,8,6" = reps of each set
        return sum(nums)
    return nums[0] * int(e.get("sets") or 1)  # "8" or "8-10" (counts the lower number)


def reps_cell(value):
    text = str(value if value is not None else "").strip()
    if isinstance(value, float) and value.is_integer():
        text = str(int(value))
    return int(text) if text.isdigit() else (f"'{text}" if text else "")


def text_cell(value):
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@") else text


def cell_id(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value if value is not None else "").strip()


def cell_date(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return EPOCH + timedelta(days=int(value))
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(value).strip(), pattern).date()
        except ValueError:
            pass
    return None


def weekday_code(text):
    t = fold(str(text))
    for lang in SHEET_TEXTS.values():
        for i, name in enumerate(lang["days"]):
            if fold(name) == t:
                return WEEKDAYS[i]
    return t[:2].upper() if t[:2].upper() in WEEKDAYS else None  # "MO", "Mon", "Monday"


def log_rows(wid, day, title, status, exercises, duration_min, feeling, notes):
    """Rows for the Log tab: one per exercise."""
    serial = (day - EPOCH).days
    week = serial - day.weekday()  # Monday of that week
    mark = "✅" if status == "done" else "⏭"
    extra = f"⏱ {num(duration_min)} {T['unit_min']}" if duration_min else ""
    note = " · ".join(x for x in (notes or "", extra) if x)
    rows = []
    for i, e in enumerate(exercises or [{"name": "—"}]):
        weight = e.get("weight_kg") or ""
        reps = total_reps(e)
        volume = round(reps * float(weight), 1) if reps and weight else ""
        first = i == 0
        rows.append([serial, week, text_cell(title), text_cell(e.get("name") or "—"),
                     e.get("sets") or "", reps_cell(e.get("reps")), weight, volume,
                     e.get("duration_min") or "", e.get("distance_km") or "", mark,
                     text_cell(feeling) if first else "", text_cell(note) if first else "",
                     wid, 1 if first else 0])
    return rows


def program_rows(days):
    S = SHEET_TEXTS[LANG]
    rows = []
    for d in sorted(days, key=lambda d: WEEKDAYS.index(d["weekday"])):
        if rows:
            rows.append([""] * 8)  # blank line between days
        for i, e in enumerate(d.get("exercises") or [{}]):
            rows.append([S["days"][WEEKDAYS.index(d["weekday"])] if i == 0 else "",
                         text_cell(d.get("title", "")) if i == 0 else "",
                         text_cell(e.get("name", "")), e.get("sets") or "",
                         reps_cell(e.get("reps")), e.get("weight_kg") or "",
                         e.get("duration_min") or "", text_cell(e.get("notes", ""))])
    return rows


def parse_program(rows):
    """Read the Program tab back (the user may have edited it)."""
    days, current = [], None
    for raw in rows:
        r = (list(raw) + [""] * 8)[:8]
        day_text, title, name = str(r[0]).strip(), str(r[1]).strip(), str(r[2]).strip()
        if day_text:
            code = weekday_code(day_text)
            current = {"weekday": code, "title": title or T["wk_title"], "exercises": []} if code else None
            if current:
                days.append(current)
        elif title and current:
            current["title"] = title
        if current and name:
            ex = {"name": name}
            for key, idx in (("sets", 3), ("reps", 4), ("weight_kg", 5), ("duration_min", 6),
                             ("notes", 7)):
                if r[idx] not in ("", None):
                    ex[key] = cell_id(r[idx]) if key == "reps" else clean_num(r[idx])
            current["exercises"].append(ex)
    return days


async def sheet_write_program(days):
    names, _, _ = await tabs()
    await gsheet("POST", f"/values/{a1(names['program'], 'A2:H1000')}:clear", json={})
    rows = program_rows(days)
    if rows:
        await gsheet("PUT", f"/values/{a1(names['program'], 'A2')}",
                     params={"valueInputOption": "USER_ENTERED"}, json={"values": rows})


async def sheet_append(rows, pick=None):
    names, _, _ = await tabs()
    await gsheet("POST", f"/values/{a1(names['log'], 'A1:O1')}:append",
                 params={"valueInputOption": "USER_ENTERED", "insertDataOption": "OVERWRITE"},
                 json={"values": rows})
    if pick:  # pre-select an exercise on the dashboard the first time
        try:
            cell = a1(names["dash"], "B7")
            if not (await gsheet("GET", f"/values/{cell}")).get("values"):
                await gsheet("PUT", f"/values/{cell}", params={"valueInputOption": "RAW"},
                             json={"values": [[pick]]})
        except Exception:
            log.exception("Could not set the dashboard exercise")


async def sheet_logs():
    """All workouts from the Log tab, grouped (includes rows the user typed in)."""
    names, _, _ = await tabs()
    data = await gsheet("GET", f"/values/{a1(names['log'], 'A2:O5000')}", params={
        "valueRenderOption": "UNFORMATTED_VALUE", "dateTimeRenderOption": "SERIAL_NUMBER"})
    groups = {}
    for raw in data.get("values", []):
        r = (list(raw) + [""] * 15)[:15]
        day = cell_date(r[0])
        if not day:
            continue
        wid = cell_id(r[13])
        g = groups.setdefault(wid or f"{day}|{r[2]}", {
            "id": wid or None, "date": day.isoformat(), "title": str(r[2]),
            "status": "skipped" if r[10] == "⏭" else "done", "exercises": [],
            "feeling": "", "notes": ""})
        if r[11] and not g["feeling"]:
            g["feeling"] = str(r[11])
        if r[12] and not g["notes"]:
            g["notes"] = str(r[12])
        name = str(r[3]).strip()
        if name and name != "—":
            ex = {"name": name}
            for key, idx in (("sets", 4), ("reps", 5), ("weight_kg", 6), ("duration_min", 8),
                             ("distance_km", 9)):
                if r[idx] not in ("", None):
                    ex[key] = clean_num(r[idx])
            g["exercises"].append(ex)
    return sorted(groups.values(), key=lambda g: g["date"])


async def sheet_delete_rows(wid):
    names, ids, _ = await tabs()
    data = await gsheet("GET", f"/values/{a1(names['log'], 'N2:N5000')}",
                        params={"valueRenderOption": "UNFORMATTED_VALUE"})
    rows = [i for i, r in enumerate(data.get("values", []), start=1) if r and cell_id(r[0]) == str(wid)]
    reqs = [{"deleteDimension": {"range": {"sheetId": ids["log"], "dimension": "ROWS",
                                           "startIndex": i, "endIndex": i + 1}}}
            for i in sorted(rows, reverse=True)]
    if reqs:
        await gsheet("POST", ":batchUpdate", json={"requests": reqs})
    return len(rows)


async def sheet_backfill(uid):
    """After connecting: copy the saved program and earlier workouts into empty tabs."""
    names, _, _ = await tabs()
    program, _ = get_program_row(uid)
    if program and not (await gsheet("GET", f"/values/{a1(names['program'], 'A2:C3')}")).get("values"):
        await sheet_write_program(program["days"])
    if (await gsheet("GET", f"/values/{a1(names['log'], 'A2:A3')}")).get("values"):
        return 0
    rows, copied = [], 0
    for r in db.execute("SELECT * FROM workouts WHERE user_id=? ORDER BY date, id", (uid,)):
        rows += log_rows(r["id"], parse_day(r["date"]), r["title"], r["status"],
                         json.loads(r["exercises"] or "[]"), r["duration_min"], r["feeling"],
                         r["notes"])
        copied += 1
    if rows:
        await sheet_append(rows)
    return copied


def get_program_row(uid):
    row = db.execute("SELECT data, calendar_ids FROM programs WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return None, []
    return json.loads(row["data"]), json.loads(row["calendar_ids"] or "[]")


def program_day(program, day):
    if not program:
        return None
    code = WEEKDAYS[day.weekday()]
    return next((d for d in program.get("days", []) if d.get("weekday") == code), None)


async def current_program(uid):
    """The program from the sheet's Program tab if connected, else the bot's saved copy."""
    program, _ = get_program_row(uid)
    if sheets_on():
        try:
            names, _, _ = await tabs()
            data = await gsheet("GET", f"/values/{a1(names['program'], 'A2:H1000')}",
                                params={"valueRenderOption": "UNFORMATTED_VALUE"})
            days = parse_program(data.get("values", []))
            if days:
                program = {**(program or {"name": names["program"]}), "days": days}
        except Exception:
            log.exception("Reading the program from the sheet failed")
    return program


async def save_program(uid, name, days, goal=None, notes=None):
    for d in days:
        d["weekday"] = str(d.get("weekday", "")).upper()[:2]
        if d["weekday"] not in WEEKDAYS:
            raise ValueError(f"weekday must be one of {WEEKDAYS}")
    data = {"name": name, "goal": goal, "notes": notes, "days": days}
    db.execute(
        "INSERT INTO programs (user_id, data, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
        (uid, json.dumps(data, ensure_ascii=False), now()),
    )
    db.commit()
    result = {"saved": True, "training_days": [d["weekday"] for d in days], "sheet": "off"}
    if sheets_on():
        try:
            await sheet_write_program(days)
            result["sheet"] = "written to the Program tab"
        except Exception as e:
            log.exception("Writing the program to the sheet failed")
            result["sheet"] = f"error: {e}"
    return result


async def get_program(uid):
    program = await current_program(uid)
    if not program:
        return {"program": None}
    out = {"program": program, "today": program_day(program, today_date())}
    if sheets_on():
        out["sheet_url"] = sheet_url()
    return out


async def log_workout(uid, exercises, date=None, title=None, duration_min=None,
                      feeling=None, notes=None, status="done"):
    day = parse_day(date)
    if not title:
        planned = program_day(await current_program(uid), day)
        title = (planned or {}).get("title") or T["wk_title"]
    cur = db.execute(
        "INSERT INTO workouts (user_id, date, title, status, exercises, duration_min, feeling, "
        "notes, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (uid, day.isoformat(), title, status, json.dumps(exercises, ensure_ascii=False),
         duration_min, feeling, notes, now()),
    )
    db.commit()
    result = {"saved_workout_id": cur.lastrowid, "date": day.isoformat(), "sheet": "off"}
    if sheets_on():
        try:
            pick = next((e.get("name") for e in exercises if e.get("weight_kg")), None)
            await sheet_append(log_rows(cur.lastrowid, day, title, status, exercises,
                                        duration_min, feeling, notes), pick)
            result["sheet"] = "saved"
        except Exception as e:
            log.exception("Writing the workout to the sheet failed")
            result["sheet"] = f"error: {e}"
    return result


async def delete_workout(uid, workout_id):
    row = db.execute("SELECT id FROM workouts WHERE id=? AND user_id=?",
                     (workout_id, uid)).fetchone()
    removed = 0
    if sheets_on():
        try:
            removed = await sheet_delete_rows(workout_id)
        except Exception:
            log.exception("Deleting rows from the sheet failed")
    if row:
        db.execute("DELETE FROM workouts WHERE id=?", (workout_id,))
        db.commit()
    return {"deleted": bool(row or removed), "sheet_rows_removed": removed}


def local_logs(uid):
    rows = db.execute(
        "SELECT id, date, title, status, exercises, duration_min, feeling, notes FROM workouts "
        "WHERE user_id=? ORDER BY date, id", (uid,)).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["exercises"] = json.loads(r["exercises"] or "[]")
        out.append(item)
    return out


async def workout_history(uid, days=30, exercise=None):
    logs, source_name = None, "bot"
    if sheets_on():
        try:
            logs, source_name = await sheet_logs(), "google_sheet"
        except Exception:
            log.exception("Reading the sheet failed")
    if logs is None:
        logs = local_logs(uid)
    since = (today_date() - timedelta(days=int(days))).isoformat()
    logs = [x for x in logs if x["date"] >= since]
    out = {"source": source_name,
           "workouts_done": sum(1 for x in logs if x["status"] == "done"),
           "workouts_skipped": sum(1 for x in logs if x["status"] == "skipped")}
    if exercise:
        wanted = fold(exercise)
        entries = [{"date": x["date"], **e} for x in logs for e in x["exercises"]
                   if wanted in fold(e.get("name", ""))]
        weights = []
        for e in entries:
            try:
                weights.append(float(e["weight_kg"]))
            except (KeyError, TypeError, ValueError):
                pass
        out.update(exercise=exercise, entries=entries[-20:],
                   best_weight_kg=max(weights) if weights else None)
    else:
        out["workouts"] = logs[-30:]
    if sheets_on():
        out["sheet_url"] = sheet_url()
    return out


FUNCS = {f.__name__: f for f in [
    add_note, search_notes, delete_note, add_task, list_tasks, update_task,
    complete_task, delete_task, set_reminder, list_reminders, cancel_reminder,
    todoist_list_tasks, todoist_add_task, todoist_update_task, todoist_complete_task,
    todoist_delete_task, todoist_list_projects,
    save_program, get_program, log_workout, delete_workout, workout_history,
]}

TIME_DESC = "Local time as 'YYYY-MM-DD HH:MM'"
ID = {"type": "integer"}
TOOLS = [
    {"name": "add_note", "description": "Save a note or piece of information to remember.",
     "input_schema": {"type": "object", "properties": {
         "content": {"type": "string"},
         "tags": {"type": "string", "description": "Comma-separated tags, e.g. 'work,ideas'"}},
         "required": ["content"]}},
    {"name": "search_notes", "description": "Search saved notes. Empty query returns the latest notes.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "delete_note", "description": "Delete a note by ID.",
     "input_schema": {"type": "object", "properties": {"note_id": ID}, "required": ["note_id"]}},
    {"name": "add_task", "description": "Add a to-do item, optionally with a due date and priority.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"},
         "due": {"type": "string", "description": TIME_DESC},
         "priority": {"type": "string", "enum": ["low", "medium", "high"]}},
         "required": ["title"]}},
    {"name": "list_tasks", "description": "List tasks. status: open (default), done, or all.",
     "input_schema": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["open", "done", "all"]}}}},
    {"name": "update_task", "description": "Change a task's title, due date or priority.",
     "input_schema": {"type": "object", "properties": {
         "task_id": ID, "title": {"type": "string"},
         "due": {"type": "string", "description": TIME_DESC},
         "priority": {"type": "string", "enum": ["low", "medium", "high"]}},
         "required": ["task_id"]}},
    {"name": "complete_task", "description": "Mark a task as done.",
     "input_schema": {"type": "object", "properties": {"task_id": ID}, "required": ["task_id"]}},
    {"name": "delete_task", "description": "Delete a task entirely.",
     "input_schema": {"type": "object", "properties": {"task_id": ID}, "required": ["task_id"]}},
    {"name": "set_reminder", "description": "Schedule a message to be sent to the user at a given time.",
     "input_schema": {"type": "object", "properties": {
         "text": {"type": "string"},
         "remind_at": {"type": "string", "description": TIME_DESC}},
         "required": ["text", "remind_at"]}},
    {"name": "list_reminders", "description": "List pending reminders.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "cancel_reminder", "description": "Cancel a pending reminder by ID.",
     "input_schema": {"type": "object", "properties": {"reminder_id": ID},
                      "required": ["reminder_id"]}},
]


PRIO_ENUM = {"type": "string", "enum": ["low", "medium", "high", "urgent"]}
TASK_ID = {"type": "string", "description": "Todoist task id"}
DUE_DESC = ("When it's due, written in ENGLISH, e.g. 'tomorrow 9am', 'every monday 9am', "
            "'Nov 5 2026 14:00'. Use 'no date' to remove a due date.")
TODOIST_TOOLS = [
    {"name": "todoist_list_tasks",
     "description": "List open tasks in the user's Todoist. Optional filter uses Todoist "
                    "filter syntax, e.g. 'today | overdue', '7 days', '#Work', 'p1', 'no date'.",
     "input_schema": {"type": "object", "properties": {"filter": {"type": "string"}}}},
    {"name": "todoist_add_task", "description": "Create a task in the user's Todoist.",
     "input_schema": {"type": "object", "properties": {
         "content": {"type": "string", "description": "Task title, in the user's language"},
         "due_string": {"type": "string", "description": DUE_DESC},
         "priority": PRIO_ENUM,
         "project": {"type": "string", "description": "Project name; omit for Inbox"},
         "description": {"type": "string"}},
         "required": ["content"]}},
    {"name": "todoist_update_task", "description": "Change a Todoist task's title, due date, "
                                                   "priority or description.",
     "input_schema": {"type": "object", "properties": {
         "task_id": TASK_ID, "content": {"type": "string"},
         "due_string": {"type": "string", "description": DUE_DESC},
         "priority": PRIO_ENUM, "description": {"type": "string"}},
         "required": ["task_id"]}},
    {"name": "todoist_complete_task", "description": "Mark a Todoist task as done.",
     "input_schema": {"type": "object", "properties": {"task_id": TASK_ID},
                      "required": ["task_id"]}},
    {"name": "todoist_delete_task", "description": "Delete a Todoist task entirely.",
     "input_schema": {"type": "object", "properties": {"task_id": TASK_ID},
                      "required": ["task_id"]}},
    {"name": "todoist_list_projects", "description": "List the user's Todoist project names.",
     "input_schema": {"type": "object", "properties": {}}},
]
EXERCISE = {"type": "object", "properties": {
    "name": {"type": "string", "description": "Exercise name; keep names consistent over time"},
    "sets": {"type": "integer"},
    "reps": {"type": "string", "description": "Reps per set, e.g. '8' or '10,8,6' or '8-10'"},
    "weight_kg": {"type": "number"},
    "duration_min": {"type": "number", "description": "For cardio or timed work"},
    "distance_km": {"type": "number"},
    "notes": {"type": "string"}},
    "required": ["name"]}
DAY_DESC = "Local date 'YYYY-MM-DD'; omit for today"
WORKOUT_TOOLS = [
    {"name": "save_program",
     "description": "Save (or replace) the user's weekly training program. Also writes it "
                    "to the Program tab of the Google Sheet if connected.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"}, "goal": {"type": "string"}, "notes": {"type": "string"},
         "days": {"type": "array", "items": {"type": "object", "properties": {
             "weekday": {"type": "string", "enum": ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]},
             "title": {"type": "string", "description": "e.g. 'Push day', 'Ayaq günü'"},
             "exercises": {"type": "array", "items": EXERCISE}},
             "required": ["weekday", "title", "exercises"]}}},
         "required": ["name", "days"]}},
    {"name": "get_program",
     "description": "Get the training program (read from the Google Sheet's Program tab if "
                    "connected, so it includes the user's own edits) and today's workout.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "log_workout",
     "description": "Save a workout the user did (or skipped) with exercises, sets, reps and "
                    "weights. Also adds it to the Log tab of the Google Sheet if connected.",
     "input_schema": {"type": "object", "properties": {
         "exercises": {"type": "array", "items": EXERCISE},
         "date": {"type": "string", "description": DAY_DESC},
         "title": {"type": "string", "description": "Omit to use the planned workout's title"},
         "duration_min": {"type": "number"},
         "feeling": {"type": "string", "description": "How the user felt, in their words"},
         "notes": {"type": "string"},
         "status": {"type": "string", "enum": ["done", "skipped"]}},
         "required": ["exercises"]}},
    {"name": "delete_workout", "description": "Delete a logged workout by its ID.",
     "input_schema": {"type": "object", "properties": {"workout_id": {"type": "integer"}},
                      "required": ["workout_id"]}},
    {"name": "workout_history",
     "description": "Get logged workouts and progress (from the Google Sheet if connected, "
                    "including rows the user typed in). Give an exercise name to see its "
                    "progress over time (entries and best weight).",
     "input_schema": {"type": "object", "properties": {
         "days": {"type": "integer", "description": "How far back, default 30"},
         "exercise": {"type": "string"}}}},
]
LOCAL_TASK_TOOLS = {"add_task", "list_tasks", "update_task", "complete_task", "delete_task"}


def active_tools():
    """With Todoist connected, tasks live there instead of the bot's own list."""
    if todoist_on():
        return [t for t in TOOLS if t["name"] not in LOCAL_TASK_TOOLS] + TODOIST_TOOLS + WORKOUT_TOOLS
    return TOOLS + WORKOUT_TOOLS


async def run_tool(uid, name, args):
    try:
        result = FUNCS[name](uid, **args)
        if inspect.isawaitable(result):
            result = await result
        return result
    except Exception as e:  # hand errors back to the AI so it can fix its call
        return {"error": str(e)}


# ------------------------------------------------------------ AI brain
def system_prompt() -> str:
    return (
        "You are a concise personal assistant living in the user's Telegram. You manage "
        "their notes, tasks, reminders and daily plans using the tools provided.\n"
        f"Current local time: {datetime.now(TZ).strftime('%A %Y-%m-%d %H:%M')} ({TZ.key}).\n"
        f"Language: {T['lang_rule']}\n"
        "Rules:\n"
        "- Convert relative times ('tomorrow 9am', 'next Friday') to 'YYYY-MM-DD HH:MM' "
        "before calling tools. If no time is given for a reminder, ask.\n"
        "- When the user shares something worth remembering, save it as a note.\n"
        "- Messages starting with [voice] are automatic transcripts of voice messages and "
        "may contain recognition mistakes; interpret them sensibly. If a voice message is "
        "just information with no clear request, save it as a note.\n"
        "- When asked to plan, check open tasks and reminders, then propose a realistic "
        "time-blocked schedule, putting overdue and high-priority items first.\n"
        "- Mention task/note IDs so the user can refer to them later.\n"
        "- Reply in short plain text (no markdown headers or bold); use '-' for lists."
        + (
            "\nTodoist: the user's tasks live in their Todoist account. Use the todoist_* "
            "tools for anything about tasks or to-dos. Write due_string in English "
            "(Todoist doesn't understand Azerbaijani dates). Repeating tasks are supported, "
            "e.g. 'every monday 9am'. When the user wants an alert at a time, also use "
            "set_reminder so it arrives in Telegram. For plans and briefings, check "
            "todoist_list_tasks with the filter 'today | overdue'."
            if todoist_on() else ""
        )
        + "\nFitness: you can design training programs and save them with save_program, "
        "tailored to the user's goal, level, equipment, available days and session length "
        "(ask briefly about these if unknown, then show the plan before saving). Keep exercise "
        "names consistent with the program and history. When the user reports what they did, "
        "call log_workout with sets, reps and weight_kg (duration_min/distance_km for cardio). "
        "Use workout_history for progress questions. In plans and briefings, mention today's "
        "planned workout (get_program). If the user mentions pain or injury, suggest a lighter "
        "alternative and seeing a professional. "
        + (f"Google Sheet is connected ({sheet_url()}): save_program also fills the Program tab, "
           "which the user may edit directly (get_program reads it), and every log_workout adds "
           "rows to the Log tab that feed the Dashboard charts. Share the link when the user "
           "asks about their progress dashboard." if sheets_on()
           else "Google Sheet is not connected yet.")
    )


async def ask_claude(uid: int, text: str) -> str:
    msgs = list(history[uid]) + [{"role": "user", "content": text}]
    for _ in range(8):  # cap tool-use rounds
        resp = await client.messages.create(
            model=MODEL, max_tokens=1024, system=system_prompt(),
            tools=active_tools(), messages=msgs,
        )
        if resp.stop_reason != "tool_use":
            break
        msgs.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                out = await run_tool(uid, b.name, b.input)
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(out, default=str, ensure_ascii=False)})
        msgs.append({"role": "user", "content": results})
    reply = "".join(b.text for b in resp.content if b.type == "text").strip() or "✅"
    history[uid].append({"role": "user", "content": text})
    history[uid].append({"role": "assistant", "content": reply})
    return reply


async def transcribe(media) -> str:
    """Download a Telegram voice/audio message and turn it into text."""
    tg_file = await media.get_file()
    data = await tg_file.download_as_bytearray()
    name = getattr(media, "file_name", None) or "voice.ogg"
    kwargs = {"model": TRANSCRIBE_MODEL, "file": (name, bytes(data))}
    if VOICE_LANGUAGE:
        kwargs["language"] = VOICE_LANGUAGE
    result = await stt.audio.transcriptions.create(**kwargs)
    return (getattr(result, "text", "") or "").strip()


# ------------------------------------------------------- telegram glue
def allowed(update: Update) -> bool:
    return not ALLOWED or update.effective_user.id in ALLOWED


async def send_long(update: Update, text: str):
    for i in range(0, len(text), 4000):  # Telegram caps messages at 4096 chars
        await update.message.reply_text(text[i:i + 4000])


async def reply_ai(update: Update, prompt: str):
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        answer = await ask_claude(update.effective_user.id, prompt)
    except Exception:
        log.exception("AI call failed")
        answer = T["ai_error"]
    await send_long(update, answer)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = T["start"].format(uid=update.effective_user.id)
    msg += T["help"] if allowed(update) else T["private"]
    await update.message.reply_text(msg)


async def chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        await reply_ai(update, update.message.text)


async def voice_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    if not stt:
        return await update.message.reply_text(T["voice_off"])
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        text = await transcribe(update.message.voice or update.message.audio)
    except Exception:
        log.exception("Transcription failed")
        return await update.message.reply_text(T["voice_fail"])
    if not text:
        return await update.message.reply_text(T["voice_empty"])
    await update.message.reply_text(T["voice_heard"].format(text=text))
    await reply_ai(update, f"[voice] {text}")


async def note_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    text = " ".join(ctx.args)
    if not text:
        return await update.message.reply_text(T["note_usage"])
    r = add_note(update.effective_user.id, text)
    await update.message.reply_text(T["note_saved"].format(id=r["saved_note_id"]))


async def notes_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    rows = search_notes(update.effective_user.id, " ".join(ctx.args), limit=15)
    if not rows:
        return await update.message.reply_text(T["no_notes"])
    await send_long(update, "\n\n".join(
        f"#{n['id']} ({n['created_at']})\n{n['content']}" for n in rows))


def format_task(t) -> str:
    line = f"#{t['id']} {t['title']}"
    if t["due"]:
        overdue = T["overdue"] if t["due"] < now() else ""
        line += T["due"].format(due=t["due"], overdue=overdue)
    if t["priority"] == "high":
        line += " 🔴"
    return line


def format_td(i, t) -> str:
    line = f"{i}. {t['content']}"
    if t["due"]:
        overdue = T["overdue"] if due_overdue(t["due"]) else ""
        line += T["due"].format(due=t["due"].replace("T", " ")[:16], overdue=overdue)
    if t["recurring"]:
        line += " 🔁"
    if t["priority"] in ("urgent", "high"):
        line += " 🔴" if t["priority"] == "urgent" else " 🟠"
    if t["project"] and fold(t["project"]) != "inbox":
        line += f" · {t['project']}"
    return line


async def todoist_listing(update: Update, header: str, filter: str = ""):
    """Show a numbered Todoist list and remember the numbers for /done."""
    try:
        items = (await fetch_tasks(filter))[:40]
    except Exception:
        log.exception("Todoist list failed")
        await update.message.reply_text(T["todoist_error"])
        return None
    last_list[update.effective_user.id] = [t["id"] for t in items]
    lines = [format_td(i + 1, t) for i, t in enumerate(items)]
    return [header] + (lines or [T["none"]])


async def tasks_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    if todoist_on():
        lines = await todoist_listing(update, T["open_tasks"], " ".join(ctx.args))
        if lines is None:
            return
        if lines[1:] == [T["none"]]:
            return await update.message.reply_text(T["no_tasks"])
        return await send_long(update, "\n".join(lines))
    rows = list_tasks(update.effective_user.id)
    if not rows:
        return await update.message.reply_text(T["no_tasks"])
    await send_long(update, T["open_tasks"] + "\n" + "\n".join(format_task(t) for t in rows))


async def done_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    arg = ctx.args[0].lstrip("#") if ctx.args else ""
    if not arg:
        return await update.message.reply_text(T["done_usage"])
    if todoist_on():
        ids = last_list.get(update.effective_user.id, [])
        if arg.isdigit() and 1 <= int(arg) <= len(ids):
            task_id = ids[int(arg) - 1]
        elif arg.isdigit() and len(arg) <= 3:
            return await update.message.reply_text(T["tasks_first"])
        else:
            task_id = arg  # a raw Todoist task id
        try:
            await todoist_complete_task(update.effective_user.id, task_id)
        except Exception:
            log.exception("Todoist complete failed")
            return await update.message.reply_text(T["done_fail"])
        return await update.message.reply_text(T["done_ok"])
    if not arg.isdigit():
        return await update.message.reply_text(T["done_usage"])
    r = complete_task(update.effective_user.id, int(arg))
    await update.message.reply_text(T["done_ok"] if r["completed"] else T["done_fail"])


async def agenda_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    uid = update.effective_user.id
    if todoist_on():
        parts = await todoist_listing(update, T["today_tasks"], "today | overdue")
        if parts is None:
            return
    else:
        parts = [T["open_tasks"]]
        parts += [format_task(t) for t in list_tasks(uid)] or [T["none"]]
    rems = list_reminders(uid)
    parts += ["", T["reminders_header"]]
    parts += [f"#{r['id']} {r['remind_at']} - {r['text']}" for r in rems] or [T["none"]]
    await send_long(update, "\n".join(parts))


async def task_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        text = " ".join(ctx.args)
        await reply_ai(update, T["task_prompt"].format(text=text) if text else T["task_empty"])


async def remind_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        text = " ".join(ctx.args)
        await reply_ai(update, T["remind_prompt"].format(text=text) if text else T["remind_empty"])


async def plan_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        extra = " ".join(ctx.args)
        await reply_ai(update, f"{T['plan_prompt']} {extra}".strip())


async def reset_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    history.pop(update.effective_user.id, None)
    await update.message.reply_text(T["reset"])


# --------------------------------------------------- background jobs
async def check_reminders(ctx: ContextTypes.DEFAULT_TYPE):
    due = db.execute(
        "SELECT id, user_id, text FROM reminders WHERE sent=0 AND remind_at <= ?", (now(),)
    ).fetchall()
    for r in due:
        try:
            await ctx.bot.send_message(r["user_id"], T["reminder"].format(text=r["text"]))
        except Exception:
            log.exception("Could not deliver reminder %s", r["id"])
        db.execute("UPDATE reminders SET sent=1 WHERE id=?", (r["id"],))
    db.commit()


async def daily_brief(ctx: ContextTypes.DEFAULT_TYPE):
    for uid in ALLOWED:
        try:
            text = await ask_claude(uid, T["brief_prompt"])
            await ctx.bot.send_message(uid, T["brief_header"] + text)
        except Exception:
            log.exception("Daily brief failed for %s", uid)


async def send_workout_prompt(bot, uid, only_if_pending=False):
    """Send today's planned workout with Done/Skipped buttons."""
    program = await current_program(uid)
    if not program:
        if not only_if_pending:
            await bot.send_message(uid, T["wk_noprogram"])
        return
    day = today_date()
    planned = program_day(program, day)
    if not planned:
        if not only_if_pending:
            await bot.send_message(uid, T["wk_rest"])
        return
    if only_if_pending and db.execute(
            "SELECT 1 FROM workouts WHERE user_id=? AND date=?", (uid, day.isoformat())).fetchone():
        return
    plan = "\n".join(fmt_exercise(e) for e in planned.get("exercises", []))
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton(T["wk_btn_done"], callback_data=f"wk:done:{day.isoformat()}"),
        InlineKeyboardButton(T["wk_btn_skip"], callback_data=f"wk:skip:{day.isoformat()}"),
    ]])
    await bot.send_message(uid, T["wk_checkin"].format(title=planned.get("title", ""), plan=plan),
                           reply_markup=buttons)


async def workout_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        await send_workout_prompt(ctx.bot, update.effective_user.id)


async def workout_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not allowed(update):
        return
    _, action, day = query.data.split(":")
    uid = update.effective_user.id
    planned = program_day(await current_program(uid), parse_day(day)) or {}
    if action == "done":
        res = await log_workout(uid, planned.get("exercises", []), date=day,
                                title=planned.get("title"))
        done = T["wk_saved"].format(sheet=T["wk_sheet"] if res["sheet"] == "saved" else "")
    else:
        await log_workout(uid, [], date=day, title=planned.get("title"), status="skipped")
        done = T["wk_skipped"]
    await query.edit_message_text(f"{query.message.text}\n\n{done}")


async def sheet_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Link to the workout sheet (and repair any missing tabs)."""
    if not allowed(update):
        return
    if not sheets_on():
        return await update.message.reply_text(T["sheet_off"])
    try:
        await ensure_sheet()
    except Exception:
        log.exception("Sheet check failed")
        return await update.message.reply_text(T["sheet_bad"])
    await update.message.reply_text(T["sheet_link"].format(url=sheet_url()))


async def json_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Owner sends the Google service account key file (.json)."""
    if not allowed(update) or not ALLOWED:
        return
    try:
        tg_file = await update.message.document.get_file()
        raw = bytes(await tg_file.download_as_bytearray())
        info = json.loads(raw)
        ok = info.get("type") == "service_account" and "private_key" in info
    except Exception:
        ok = False
    if not ok:
        return await update.message.reply_text(T["gsa_bad"])
    try:
        await update.message.delete()
    except Exception:
        log.warning("Could not delete the key file message")
    GSA_PATH.write_bytes(raw)
    os.chmod(GSA_PATH, 0o600)
    _gcreds["c"] = None
    await ctx.bot.send_message(update.effective_chat.id,
                               T["gsa_saved"].format(email=info.get("client_email", "?")))


SETTABLE = {
    "TODOIST_API_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_MODEL",
    "BOT_LANGUAGE", "VOICE_LANGUAGE", "TRANSCRIBE_MODEL", "TIMEZONE", "DAILY_BRIEF_TIME",
    "GOOGLE_SHEET_ID", "WORKOUT_CHECKIN_TIME",
}


def check_setting(key, value):
    """Raise if the value is clearly wrong; return the value to store."""
    if key == "TIMEZONE":
        ZoneInfo(value)
    elif key in ("DAILY_BRIEF_TIME", "WORKOUT_CHECKIN_TIME"):
        if value.lower() == "off":
            return ""
        datetime.strptime(value, "%H:%M")
    elif key == "GOOGLE_SHEET_ID":  # accept the whole link too
        found = re.search(r"/d/([A-Za-z0-9_-]+)", value)
        value = found.group(1) if found else value
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,}", value):
            raise ValueError("not a sheet ID")
    elif key == "BOT_LANGUAGE":
        value = value.lower()
        if value not in TEXTS:
            raise ValueError("unknown language")
    return value


def save_setting(key, value):
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    lines = [ln for ln in lines if not ln.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n")
    os.chmod(ENV_PATH, 0o600)
    os.environ[key] = value


async def setkey_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Owner-only: /setkey NAME value. Deletes the message so the key doesn't stay in chat."""
    if not allowed(update):
        return
    try:
        await update.message.delete()
    except Exception:
        log.warning("Could not delete the /setkey message")
    chat_id = update.effective_chat.id
    if not ALLOWED:
        return await ctx.bot.send_message(chat_id, T["setkey_locked"])
    key = ctx.args[0].upper() if ctx.args else ""
    if len(ctx.args) != 2 or key not in SETTABLE:
        return await ctx.bot.send_message(
            chat_id, T["setkey_usage"].format(keys=", ".join(sorted(SETTABLE))))
    try:
        value = check_setting(key, ctx.args[1].strip())
    except Exception:
        return await ctx.bot.send_message(chat_id, T["setkey_invalid"].format(key=key))

    save_setting(key, value)
    load_config()
    schedule_jobs(ctx.job_queue)
    secret = key.endswith(("_KEY", "_TOKEN"))
    masked = f" (…{value[-4:]})" if secret and len(value) > 8 else (f": {value}" if not secret else "")
    await ctx.bot.send_message(chat_id, T["setkey_saved"].format(key=key, masked=masked))

    if key == "TODOIST_API_TOKEN":
        try:
            n = len(await td_projects(force=True))
            await ctx.bot.send_message(chat_id, T["todoist_ok"].format(n=n))
        except Exception:
            log.exception("Todoist token check failed")
            await ctx.bot.send_message(chat_id, T["todoist_bad"])

    if key == "GOOGLE_SHEET_ID":
        if not GSA_PATH.exists():
            return await ctx.bot.send_message(chat_id, T["sheet_nokey"])
        try:
            title = await ensure_sheet()
            await ctx.bot.send_message(chat_id, T["sheet_ok"].format(name=title, url=sheet_url()))
            copied = await sheet_backfill(update.effective_user.id)
            if copied:
                await ctx.bot.send_message(chat_id, T["sheet_backfill"].format(n=copied))
        except Exception:
            log.exception("Sheet setup failed")
            await ctx.bot.send_message(chat_id, T["sheet_bad"])


async def workout_checkin(ctx: ContextTypes.DEFAULT_TYPE):
    for uid in ALLOWED:
        try:
            await send_workout_prompt(ctx.bot, uid, only_if_pending=True)
        except Exception:
            log.exception("Workout check-in failed for %s", uid)


def schedule_jobs(job_queue):
    """(Re)schedule the daily briefing and the evening workout check-in."""
    for name in ("daily_brief", "workout_checkin"):
        for job in job_queue.get_jobs_by_name(name):
            job.schedule_removal()
    if not ALLOWED:
        return
    for name, when, callback in (("daily_brief", BRIEF_TIME, daily_brief),
                                 ("workout_checkin", CHECKIN_TIME, workout_checkin)):
        if when:
            h, m = map(int, when.split(":"))
            job_queue.run_daily(callback, time=dtime(h, m, tzinfo=TZ), name=name)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # keeps the bot token out of logs

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    # English and Azerbaijani names both work (Telegram commands allow only a-z, 0-9, _)
    app.add_handler(CommandHandler(["start", "help", "komek"], start))
    app.add_handler(CommandHandler(["note", "qeyd"], note_cmd))
    app.add_handler(CommandHandler(["notes", "qeydler"], notes_cmd))
    app.add_handler(CommandHandler(["task", "tapsiriq"], task_cmd))
    app.add_handler(CommandHandler(["tasks", "tapsiriqlar"], tasks_cmd))
    app.add_handler(CommandHandler(["done", "hazir"], done_cmd))
    app.add_handler(CommandHandler(["remind", "xatirlat"], remind_cmd))
    app.add_handler(CommandHandler("plan", plan_cmd))
    app.add_handler(CommandHandler(["agenda", "gundem"], agenda_cmd))
    app.add_handler(CommandHandler(["reset", "sifirla"], reset_cmd))
    app.add_handler(CommandHandler("setkey", setkey_cmd))
    app.add_handler(CommandHandler(["workout", "mesq"], workout_cmd))
    app.add_handler(CommandHandler(["sheet", "cedvel"], sheet_cmd))
    app.add_handler(CallbackQueryHandler(workout_button, pattern=r"^wk:"))
    app.add_handler(MessageHandler(filters.Document.FileExtension("json"), json_file))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_msg))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    app.job_queue.run_repeating(check_reminders, interval=30, first=5)
    schedule_jobs(app.job_queue)

    if not ALLOWED:
        log.warning("ALLOWED_USER_IDS is empty: anyone who finds this bot can use it.")
    if not stt:
        log.warning("OPENAI_API_KEY not set: voice messages are turned off.")
    log.info("Assistant running (language: %s, model: %s, Todoist: %s, Sheet: %s).",
             LANG, MODEL, "on" if todoist_on() else "off", "on" if sheets_on() else "off")
    app.run_polling()


if __name__ == "__main__":
    main()
