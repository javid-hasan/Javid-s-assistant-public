"""
Personal AI assistant for Telegram: notes, tasks, planning and reminders.

Talk to it naturally ("remind me to call mum tomorrow at 6pm",
"what's on my plate this week?") or use slash commands.

Paste this into @BotFather -> /setcommands to get a command menu:
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
"""

import json
import logging
import os
import sqlite3
from collections import defaultdict, deque
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
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

# ---------------------------------------------------------------- config
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
TZ = ZoneInfo(os.getenv("TIMEZONE", "UTC"))
DB_PATH = os.getenv("DB_PATH", "assistant.db")
ALLOWED = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip()}
BRIEF_TIME = os.getenv("DAILY_BRIEF_TIME", "08:00").strip()  # blank = off

client = AsyncAnthropic()  # reads ANTHROPIC_API_KEY from the environment
history = defaultdict(lambda: deque(maxlen=12))  # short chat memory per user
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


FUNCS = {f.__name__: f for f in [
    add_note, search_notes, delete_note, add_task, list_tasks, update_task,
    complete_task, delete_task, set_reminder, list_reminders, cancel_reminder,
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


def run_tool(uid, name, args):
    try:
        return FUNCS[name](uid, **args)
    except Exception as e:  # hand errors back to the AI so it can fix its call
        return {"error": str(e)}


# ------------------------------------------------------------ AI brain
def system_prompt() -> str:
    return (
        "You are a concise personal assistant living in the user's Telegram. You manage "
        "their notes, tasks, reminders and daily plans using the tools provided.\n"
        f"Current local time: {datetime.now(TZ).strftime('%A %Y-%m-%d %H:%M')} ({TZ.key}).\n"
        "Rules:\n"
        "- Convert relative times ('tomorrow 9am', 'next Friday') to 'YYYY-MM-DD HH:MM' "
        "before calling tools. If no time is given for a reminder, ask.\n"
        "- When the user shares something worth remembering, save it as a note.\n"
        "- When asked to plan, check open tasks and reminders, then propose a realistic "
        "time-blocked schedule, putting overdue and high-priority items first.\n"
        "- Mention task/note IDs so the user can refer to them later.\n"
        "- Reply in short plain text (no markdown headers or bold); use '-' for lists."
    )


async def ask_claude(uid: int, text: str) -> str:
    msgs = list(history[uid]) + [{"role": "user", "content": text}]
    for _ in range(8):  # cap tool-use rounds
        resp = await client.messages.create(
            model=MODEL, max_tokens=1024, system=system_prompt(),
            tools=TOOLS, messages=msgs,
        )
        if resp.stop_reason != "tool_use":
            break
        msgs.append({"role": "assistant", "content": resp.content})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": b.id,
             "content": json.dumps(run_tool(uid, b.name, b.input), default=str)}
            for b in resp.content if b.type == "tool_use"
        ]})
    reply = "".join(b.text for b in resp.content if b.type == "text").strip() or "Done."
    history[uid].append({"role": "user", "content": text})
    history[uid].append({"role": "assistant", "content": reply})
    return reply


# ------------------------------------------------------- telegram glue
HELP = (
    "Just talk to me naturally, for example:\n"
    "- Note: the cabin wifi password is on the fridge\n"
    "- Add task: send invoice to Acme by Friday, high priority\n"
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
    "/reset - clear conversation memory"
)


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
        answer = "Sorry, I couldn't reach the AI just now. Please try again in a moment."
    await send_long(update, answer)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = f"Hi! I'm your personal assistant.\nYour Telegram user ID: {uid}\n\n"
    if not allowed(update):
        msg += "This bot is private. Ask the owner to add your ID to ALLOWED_USER_IDS."
    else:
        msg += HELP
    await update.message.reply_text(msg)


async def chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        await reply_ai(update, update.message.text)


async def note_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    text = " ".join(ctx.args)
    if not text:
        return await update.message.reply_text("Usage: /note <text>")
    r = add_note(update.effective_user.id, text)
    await update.message.reply_text(f"📝 Saved note #{r['saved_note_id']}")


async def notes_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    rows = search_notes(update.effective_user.id, " ".join(ctx.args), limit=15)
    if not rows:
        return await update.message.reply_text("No notes found.")
    await send_long(update, "\n\n".join(
        f"#{n['id']} ({n['created_at']})\n{n['content']}" for n in rows))


async def tasks_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    rows = list_tasks(update.effective_user.id)
    if not rows:
        return await update.message.reply_text("No open tasks 🎉")
    await send_long(update, "📋 Open tasks:\n" + "\n".join(format_task(t) for t in rows))


def format_task(t) -> str:
    line = f"#{t['id']} {t['title']}"
    if t["due"]:
        overdue = " ⚠️ overdue" if t["due"] < now() else ""
        line += f" (due {t['due']}{overdue})"
    if t["priority"] == "high":
        line += " 🔴"
    return line


async def done_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    if not ctx.args or not ctx.args[0].lstrip("#").isdigit():
        return await update.message.reply_text("Usage: /done <task id>")
    r = complete_task(update.effective_user.id, int(ctx.args[0].lstrip("#")))
    await update.message.reply_text("✅ Done!" if r["completed"] else "No open task with that ID.")


async def agenda_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    uid = update.effective_user.id
    tasks = list_tasks(uid)
    rems = list_reminders(uid)
    parts = ["📋 Open tasks:"]
    parts += [format_task(t) for t in tasks] or ["(none)"]
    parts += ["", "⏰ Upcoming reminders:"]
    parts += [f"#{r['id']} {r['remind_at']} - {r['text']}" for r in rems] or ["(none)"]
    await send_long(update, "\n".join(parts))


async def task_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        text = " ".join(ctx.args)
        await reply_ai(update, f"Add this task: {text}" if text else "Help me add a task.")


async def remind_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        text = " ".join(ctx.args)
        await reply_ai(update, f"Set a reminder: {text}" if text else "I want to set a reminder.")


async def plan_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if allowed(update):
        extra = " ".join(ctx.args)
        await reply_ai(update, "Make a time-blocked plan for the rest of today from my open "
                               f"tasks and reminders. {extra}".strip())


async def reset_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    history.pop(update.effective_user.id, None)
    await update.message.reply_text("🧹 Conversation memory cleared (notes and tasks are kept).")


# --------------------------------------------------- background jobs
async def check_reminders(ctx: ContextTypes.DEFAULT_TYPE):
    due = db.execute(
        "SELECT id, user_id, text FROM reminders WHERE sent=0 AND remind_at <= ?", (now(),)
    ).fetchall()
    for r in due:
        try:
            await ctx.bot.send_message(r["user_id"], f"⏰ Reminder: {r['text']}")
        except Exception:
            log.exception("Could not deliver reminder %s", r["id"])
        db.execute("UPDATE reminders SET sent=1 WHERE id=?", (r["id"],))
    db.commit()


async def daily_brief(ctx: ContextTypes.DEFAULT_TYPE):
    for uid in ALLOWED:
        try:
            text = await ask_claude(uid, "Give me my morning briefing: overdue items, what's "
                                         "due today, reminders, and a suggested plan.")
            await ctx.bot.send_message(uid, "☀️ Good morning!\n\n" + text)
        except Exception:
            log.exception("Daily brief failed for %s", uid)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # keeps the bot token out of logs

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("note", note_cmd))
    app.add_handler(CommandHandler("notes", notes_cmd))
    app.add_handler(CommandHandler("task", task_cmd))
    app.add_handler(CommandHandler("tasks", tasks_cmd))
    app.add_handler(CommandHandler("done", done_cmd))
    app.add_handler(CommandHandler("remind", remind_cmd))
    app.add_handler(CommandHandler("plan", plan_cmd))
    app.add_handler(CommandHandler("agenda", agenda_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    app.job_queue.run_repeating(check_reminders, interval=30, first=5)
    if BRIEF_TIME and ALLOWED:
        h, m = map(int, BRIEF_TIME.split(":"))
        app.job_queue.run_daily(daily_brief, time=dtime(h, m, tzinfo=TZ))

    if not ALLOWED:
        log.warning("ALLOWED_USER_IDS is empty: anyone who finds this bot can use it.")
    log.info("Assistant running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
