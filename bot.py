"""
Personal AI assistant for Telegram: notes, tasks, planning, reminders
and voice messages, in English or Azerbaijani. Optional Todoist sync.

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
setkey - Change a setting or key
"""

import inspect
import json
import logging
import os
import sqlite3
import time
from collections import defaultdict, deque
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
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
            "- Plan my day\n\n"
            "Or use commands:\n"
            "/note <text> - save a note\n"
            "/notes [search] - list or search notes\n"
            "/task <text> - add a task (dates understood)\n"
            "/tasks - open tasks\n"
            "/done <id> - complete a task\n"
            "/remind <when> <what> - set a reminder\n"
            "/plan - AI plan for today\n"
            "/agenda - tasks and reminders at a glance\n"
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
    },
    "az": {
        "help": (
            "Mənimlə adi dildə yazışın və ya səsli mesaj göndərin 🎤, məsələn:\n"
            "- Qeyd et: Elnurun ad günü 12 dekabrdadır\n"
            "- Tapşırıq: cümə gününə qədər hesab-fakturanı göndər, vacibdir\n"
            "- Sabah saat 18:00-da anama zəng etməyi xatırlat\n"
            "- Günümü planla\n\n"
            "Əmrlər:\n"
            "/qeyd <mətn> - qeyd saxla\n"
            "/qeydler [söz] - qeydləri göstər və ya axtar\n"
            "/tapsiriq <mətn> - tapşırıq əlavə et\n"
            "/tapsiriqlar - açıq tapşırıqlar\n"
            "/hazir <nömrə> - tapşırığı tamamla\n"
            "/xatirlat <nə vaxt> <nə> - xatırlatma qur\n"
            "/plan - bugünkü plan\n"
            "/gundem - tapşırıqlar və xatırlatmalar\n"
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
    },
}

# ---------------------------------------------------------------- config
# Fixed at startup:
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DB_PATH = os.getenv("DB_PATH", "assistant.db")
ALLOWED = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip()}
ENV_PATH = Path(__file__).with_name(".env")
TODOIST_BASE = os.getenv("TODOIST_API_BASE", "https://api.todoist.com/api/v1").rstrip("/")


def load_config():
    """(Re)read changeable settings. Runs at startup and after /setkey."""
    global MODEL, TZ, BRIEF_TIME, LANG, T, VOICE_LANGUAGE, TRANSCRIBE_MODEL, client, stt
    MODEL = os.getenv("CLAUDE_MODEL", "").strip() or "claude-sonnet-5-5"
    TZ = ZoneInfo(os.getenv("TIMEZONE", "").strip() or "UTC")
    BRIEF_TIME = os.getenv("DAILY_BRIEF_TIME", "08:00").strip()  # blank = off
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


FUNCS = {f.__name__: f for f in [
    add_note, search_notes, delete_note, add_task, list_tasks, update_task,
    complete_task, delete_task, set_reminder, list_reminders, cancel_reminder,
    todoist_list_tasks, todoist_add_task, todoist_update_task, todoist_complete_task,
    todoist_delete_task, todoist_list_projects,
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
LOCAL_TASK_TOOLS = {"add_task", "list_tasks", "update_task", "complete_task", "delete_task"}


def active_tools():
    """With Todoist connected, tasks live there instead of the bot's own list."""
    if todoist_on():
        return [t for t in TOOLS if t["name"] not in LOCAL_TASK_TOOLS] + TODOIST_TOOLS
    return TOOLS


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


SETTABLE = {
    "TODOIST_API_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_MODEL",
    "BOT_LANGUAGE", "VOICE_LANGUAGE", "TRANSCRIBE_MODEL", "TIMEZONE", "DAILY_BRIEF_TIME",
}


def check_setting(key, value):
    """Raise if the value is clearly wrong; return the value to store."""
    if key == "TIMEZONE":
        ZoneInfo(value)
    elif key == "DAILY_BRIEF_TIME":
        if value.lower() == "off":
            return ""
        datetime.strptime(value, "%H:%M")
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
    schedule_brief(ctx.job_queue)
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


def schedule_brief(job_queue):
    for job in job_queue.get_jobs_by_name("daily_brief"):
        job.schedule_removal()
    if BRIEF_TIME and ALLOWED:
        h, m = map(int, BRIEF_TIME.split(":"))
        job_queue.run_daily(daily_brief, time=dtime(h, m, tzinfo=TZ), name="daily_brief")


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
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_msg))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    app.job_queue.run_repeating(check_reminders, interval=30, first=5)
    schedule_brief(app.job_queue)

    if not ALLOWED:
        log.warning("ALLOWED_USER_IDS is empty: anyone who finds this bot can use it.")
    if not stt:
        log.warning("OPENAI_API_KEY not set: voice messages are turned off.")
    log.info("Assistant running (language: %s, model: %s, Todoist: %s).",
             LANG, MODEL, "on" if todoist_on() else "off")
    app.run_polling()


if __name__ == "__main__":
    main()
