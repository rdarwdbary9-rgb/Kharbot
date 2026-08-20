#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import random
import sqlite3
import logging
import json
import asyncio
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# ============================================================
# تنظیمات اولیه
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# 🧠 تنظیمات هوش مصنوعی «خر دانا» (Gemini یا هر سرویس دیگه)
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gemini-3.6-flash")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")

# مسیر دیتابیس در /tmp (سرور فقط اینجا اجازه نوشتن دارد)
DB_FILE = "/tmp/kharbot.db"

MIN_BET = 10
START_COINS = 2500
MAX_PLAYERS = 10

CURRENCY_NAME = "تی‌تاپ"

# 🤖 خر بات — حریف کامپیوتری
BOT_ID = -777
BOT_NAME = "🤖 خر بات"

# ⏰ اگر بازی تا این مدت شروع نشد، خودکار لغو می‌شود (۵ دقیقه)
ROOM_START_TIMEOUT = 300

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("KHARBOT")

# تبدیل اعداد فارسی/عربی به انگلیسی
FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

def esc_md(text):
    """فرار دادن کاراکترهای خاص Markdown در اسم کاربرها تا پیام کرش نکند"""
    if not text:
        return ""
    for ch in ("\\", "_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text

# ============================================================
# دیتابیس
# ============================================================

def db_connect():
    try:
        db = sqlite3.connect(DB_FILE, timeout=20)
        db.row_factory = sqlite3.Row
        return db
    except sqlite3.OperationalError as e:
        logger.error(f"❌ خطای دیتابیس: {e}")
        raise

def init_db():
    try:
        with closing(db_connect()) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                coins INTEGER NOT NULL DEFAULT 2500,
                level INTEGER NOT NULL DEFAULT 1,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL,
                last_mate INTEGER DEFAULT 0,
                babies INTEGER DEFAULT 0,
                baby_names TEXT DEFAULT '[]',
                last_sound INTEGER DEFAULT 0,
                last_daily INTEGER DEFAULT 0)""")
            
            db.execute("""CREATE TABLE IF NOT EXISTS donkeys (
                user_id INTEGER PRIMARY KEY,
                equipped_hat TEXT DEFAULT '',
                equipped_saddle TEXT DEFAULT '',
                equipped_horseshoe TEXT DEFAULT '',
                equipped_tie TEXT DEFAULT '',
                equipped_clothes TEXT DEFAULT '',
                equipped_accessory TEXT DEFAULT '',
                FOREIGN KEY(user_id) REFERENCES users(user_id))""")
            
            # 💬 چت‌ها (گروه‌ها و پی‌وی‌ها) برای پیام همگانی
            db.execute("""CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT DEFAULT '',
                title TEXT DEFAULT '',
                last_seen INTEGER DEFAULT 0)""")
            
            # ⚙️ تنظیمات (جوین اجباری و ...)
            db.execute("""CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT DEFAULT '')""")
            db.commit()
            # مهاجرت: ستون‌های جدید (اگر دیتابیس قدیمی باشد)
            existing = {r[1] for r in db.execute("PRAGMA table_info(users)").fetchall()}
            for col in ["last_work", "last_wheel", "last_rob", "last_fortune", "sound_count"]:
                if col not in existing:
                    db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
            db.commit()
        logger.info(f"✅ دیتابیس در {DB_FILE} راه‌اندازی شد")
    except sqlite3.OperationalError as e:
        logger.error(f"❌ خطا در راه‌اندازی دیتابیس: {e}")
        raise

# ============================================================
# مدیریت کاربران
# ============================================================

def track_chat(chat):
    """ثبت گروه/پی‌وی برای پیام همگانی"""
    if not chat:
        return
    try:
        with closing(db_connect()) as db:
            db.execute(
                "INSERT OR REPLACE INTO chats (chat_id, chat_type, title, last_seen) VALUES (?, ?, ?, ?)",
                (chat.id, chat.type or "", (getattr(chat, "title", "") or getattr(chat, "first_name", "") or "")[:100], int(time.time()))
            )
            db.commit()
    except Exception as e:
        logger.warning(f"⚠️ خطا در ثبت چت: {e}")

def get_setting(key, default=""):
    try:
        with closing(db_connect()) as db:
            row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default
    except Exception:
        return default

def set_setting(key, value):
    with closing(db_connect()) as db:
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        db.commit()

def ensure_user(user_id, name="کاربر"):
    now = int(time.time())
    with closing(db_connect()) as db:
        row = db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            db.execute("INSERT INTO users (user_id, name, coins, created_at) VALUES (?, ?, ?, ?)",
                      (user_id, name[:100], START_COINS, now))
            db.execute("INSERT INTO donkeys (user_id) VALUES (?)", (user_id,))
        else:
            db.execute("UPDATE users SET name = ? WHERE user_id = ?", (name[:100], user_id))
        db.commit()

def get_user(user_id):
    with closing(db_connect()) as db:
        return db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

def get_donkey(user_id):
    with closing(db_connect()) as db:
        return db.execute("SELECT * FROM donkeys WHERE user_id = ?", (user_id,)).fetchone()

def uname(user_id):
    if user_id == BOT_ID:
        return BOT_NAME
    u = get_user(user_id)
    return esc_md(u["name"]) if u else "ناشناس"

def add_coins(user_id, amount):
    if user_id == BOT_ID: return True  # خر بات پول لازم نداره
    if amount <= 0: return False
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
        db.commit()
    update_level(user_id)
    return True

def remove_coins(user_id, amount):
    if user_id == BOT_ID: return True
    if amount <= 0: return False
    with closing(db_connect()) as db:
        row = db.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row or row["coins"] < amount:
            return False
        db.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, user_id))
        db.commit()
    update_level(user_id)
    return True

def record_win(user_id):
    if user_id == BOT_ID: return
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET wins = wins + 1 WHERE user_id = ?", (user_id,))
        db.commit()
    update_level(user_id)

def record_loss(user_id):
    if user_id == BOT_ID: return
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET losses = losses + 1 WHERE user_id = ?", (user_id,))
        db.commit()
    update_level(user_id)

def update_level(user_id):
    with closing(db_connect()) as db:
        row = db.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row: return
        coins = row["coins"]
        if coins < 5000: level = 1
        elif coins < 15000: level = 2
        elif coins < 30000: level = 3
        elif coins < 60000: level = 4
        elif coins < 100000: level = 5
        elif coins < 200000: level = 6
        elif coins < 500000: level = 7
        elif coins < 1000000: level = 8
        elif coins < 5000000: level = 9
        else: level = 10
        db.execute("UPDATE users SET level = ? WHERE user_id = ?", (level, user_id))
        db.commit()

# ============================================================
# سیستم لقب‌ها
# ============================================================

def get_title_by_level(level):
    titles = {
        1: "🐣 کره‌خر تازه‌کار",
        2: "🐴 خر کارآموز",
        3: "🐴 خر ماهر",
        4: "🐴 خر حرفه‌ای",
        5: "🐴 خر استاد",
        6: "🦄 تک‌شاخ افسانه‌ای",
        7: "🐉 اژدهای زرین",
        8: "🌟 خر ستاره‌ای",
        9: "☀️ خر کهکشانی",
        10: "👑 خدا خرها"
    }
    return titles.get(level, "🐣 کره‌خر تازه‌کار")

# ============================================================
# پروفایل
# ============================================================

def profile_text(user_id):
    u = get_user(user_id)
    if not u:
        return "❌ کاربر پیدا نشد."
    
    level = u["level"]
    title = get_title_by_level(level)
    donkey = get_donkey(user_id)
    babies = load_babies(u)
    
    equipped_parts = []
    if donkey:
        if donkey["equipped_hat"]: equipped_parts.append("🎩 " + donkey["equipped_hat"])
        if donkey["equipped_saddle"]: equipped_parts.append("🐴 " + donkey["equipped_saddle"])
        if donkey["equipped_horseshoe"]: equipped_parts.append("👟 " + donkey["equipped_horseshoe"])
        if donkey["equipped_tie"]: equipped_parts.append("👔 " + donkey["equipped_tie"])
        if donkey["equipped_clothes"]: equipped_parts.append("👕 " + donkey["equipped_clothes"])
        if donkey["equipped_accessory"]: equipped_parts.append("🎀 " + donkey["equipped_accessory"])
    
    msg = (
        f"{title} 👤 **پروفایل {esc_md(u['name'])}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"⭐ سطح: {level}\n"
        f"🪙 {CURRENCY_NAME}: {u['coins']:,}\n"
        f"🏆 برد: {u['wins']} | 💀 باخت: {u['losses']}\n"
    )
    
    if equipped_parts:
        msg += f"\n🎀 **وسایل فعال:**\n"
        for part in equipped_parts:
            msg += f"{part}\n"
    else:
        msg += f"\n🎀 **وسایل فعال:** هیچ"
    
    if babies:
        income = babies_daily_income(babies)
        msg += f"\n👶 **کره‌خرها:** {len(babies)} عدد (سود روزانه: {income} {CURRENCY_NAME})\n"
        for i, baby in enumerate(babies[:3], 1):
            lv = BABY_LEVELS.get(baby.get("level", 1), BABY_LEVELS[1])
            msg += f"{i}. {lv['emoji']} {esc_md(baby['name'])} (س{baby.get('level',1)})\n"
        if len(babies) > 3:
            msg += f"... و {len(babies)-3} عدد دیگر"
    else:
        msg += f"\n👶 **کره‌خرها:** هیچ"
    
    return msg

# ============================================================
# جایزه روزانه
# ============================================================

DAILY_COOLDOWN = 86400
DAILY_MIN = 100
DAILY_MAX = 500

async def daily_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    u = get_user(user.id)
    if not u: return
    
    last_daily = u["last_daily"] or 0
    now = int(time.time())
    
    if now - last_daily < DAILY_COOLDOWN:
        remaining = DAILY_COOLDOWN - (now - last_daily)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        await update.message.reply_text(
            f"⏳ {hours} ساعت و {minutes} دقیقه مونده تا جایزه روزانه بعدی!"
        )
        return
    
    reward = random.randint(DAILY_MIN, DAILY_MAX)
    bonus = ""
    if random.random() < 0.10:
        extra = random.randint(50, 200)
        reward += extra
        bonus = f"\n🎉 **جایزه ویژه!** +{extra} {CURRENCY_NAME}"
    
    # 🐣 سود کره‌خرها — خودکار همراه جایزه روزانه
    babies = load_babies(u)
    baby_income = babies_daily_income(babies)
    baby_line_txt = ""
    if baby_income > 0:
        baby_line_txt = f"\n🐣 سود کره‌خرها ({len(babies)} عدد): **+{baby_income}** {CURRENCY_NAME}"
    
    total = reward + baby_income
    add_coins(user.id, total)
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET last_daily = ? WHERE user_id = ?", (now, user.id))
        db.commit()
    
    await update.message.reply_text(
        f"🎁 **جایزه روزانه!**\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 {esc_md(user.first_name)} عزیز\n"
        f"💰 جایزه: **{reward}** {CURRENCY_NAME}"
        f"{bonus}"
        f"{baby_line_txt}\n"
        f"💎 جمع کل: **{total}** {CURRENCY_NAME}\n"
        f"\n📅 فردا دوباره بیا! 🐴",
        parse_mode="Markdown"
    )

# ============================================================
# صدای خر
# ============================================================

# 💰 همه صداها امتیاز یکسان دارن: شانسی از ۵۰ تا ۵۰۰!
SOUND_MIN = 50
SOUND_MAX = 500
SOUND_RARE_CHANCE = 0.07  # شانس عر طلایی

SOUND_KEYWORDS = {
    "عر":         {"sound": "عَر عَر عَر 🔊",                       "desc": "صدای معمولی خر"},
    "عرعر":       {"sound": "عَرعَرعَرعَرعَر 📢",                    "desc": "رگبار عرعر"},
    "عرر":        {"sound": "عَررررررررررر 🌬️",                    "desc": "عر کشیده و سوزناک"},
    "ترک":        {"sound": "عَر-عَر-عَر... تِرِک! 💔",              "desc": "صدای شکسته و دلخراش"},
    "تورک":       {"sound": "عَرررر بۆیله عَرررر 🌀",               "desc": "عر با لهجه تورکی"},
    "عراپرا":     {"sound": "🎵 عَرا-پَرا عَرا-پَرا 🕺",             "desc": "عر ریتمیک رقصیدنی"},
    "عرملایم":    {"sound": "عـِـر... عـِـر... 🎻",                  "desc": "عر رمانتیک زیر نور ماه"},
    "عرجنگی":     {"sound": "عَ‌ررررر!!! ⚔️🔥",                     "desc": "نعره جنگی خر وحشی"},
    "عراپرایی":   {"sound": "🎭 عَ‌ره‌ره‌ره‌ریرا~ 🎶",                "desc": "عر اپرایی سوپرانو"},
    "عرغمگین":    {"sound": "عـِـر... 😢💧",                        "desc": "عر غمگین بارونی"},
    "عرشاد":      {"sound": "عَر عَر هورااا! 🎉🥳",                  "desc": "عر جشن و پایکوبی"},
    "عرخفن":      {"sound": "😎 عَر. فقط همین. 🕶️",                "desc": "عر باکلاس و لاکچری"},
    "عرتایید":    {"sound": "عَر! 👍✅",                            "desc": "مُهر تایید خر — یعنی آره، موافقم!"},
    "عرمخالفت":   {"sound": "عَر عَر! 👎❌",                        "desc": "وتوی خری — یعنی نه، عمراً!"},
    "عرلری":      {"sound": "عَر کاکو عَرررر! 🏔️💪",               "desc": "عر با لهجه غلیظ لری"},
    "عرکنکوری":   {"sound": "عَر... عَر... 📚😰",                   "desc": "عر پراسترس شب کنکور"}
}

# رتبه‌های عرعرکردن بر اساس تعداد کل صداها
SOUND_RANKS = [
    (0,   "🔇 خر ساکت"),
    (10,  "🔈 عرعرکار مبتدی"),
    (30,  "🔉 عرعرکار نیمه‌حرفه‌ای"),
    (75,  "🔊 عرعرکار حرفه‌ای"),
    (150, "📢 استاد عرعر"),
    (300, "🎺 سلطان عرعر"),
    (600, "👑 اسطوره عرعر خرستان")
]

def get_sound_rank(count):
    rank = SOUND_RANKS[0][1]
    for need, name in SOUND_RANKS:
        if count >= need:
            rank = name
    return rank

SOUND_COOLDOWN = 120

async def donkey_sound(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip().replace(" ", "").replace("\u200c", "")
    ensure_user(user.id, user.first_name)
    u = get_user(user.id)
    if not u: return
    
    last_sound = u["last_sound"] or 0
    now = int(time.time())
    
    if now - last_sound < SOUND_COOLDOWN:
        remaining = SOUND_COOLDOWN - (now - last_sound)
        minutes = remaining // 60
        seconds = remaining % 60
        await update.message.reply_text(
            f"⏳ حنجره‌ات خسته‌ست! {minutes} دقیقه و {seconds} ثانیه استراحت بده 🐴💤"
        )
        return
    
    # طولانی‌ترین کلید منطبق را پیدا کن (عرخفن قبل از عر)
    keyword = None
    for key in sorted(SOUND_KEYWORDS.keys(), key=len, reverse=True):
        if key == text:
            keyword = key
            break
    
    if not keyword:
        return
    
    sound_info = SOUND_KEYWORDS[keyword]
    reward = random.randint(SOUND_MIN, SOUND_MAX)
    bonus = ""
    
    if random.random() < SOUND_RARE_CHANCE:
        extra = random.randint(100, 300)
        reward += extra
        bonus = f"\n🌟 **عر طلایی!** پژواکش کل طویله رو لرزوند! +{extra} {CURRENCY_NAME}"
    
    if reward > 0:
        add_coins(user.id, reward)
    
    sound_count = (u["sound_count"] or 0) + 1
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET last_sound = ?, sound_count = ? WHERE user_id = ?",
                  (now, sound_count, user.id))
        db.commit()
    
    rank = get_sound_rank(sound_count)
    
    await update.message.reply_text(
        f"🔊 **صدای خر!**\n"
        f"━━━━━━━━━━━━━━\n"
        f"🎤 {sound_info['sound']}\n"
        f"📝 {sound_info['desc']}\n"
        f"\n👤 {esc_md(user.first_name)} عر کشید!\n"
        f"💰 پوینت: **+{reward}** {CURRENCY_NAME}"
        f"{bonus}\n"
        f"\n🏅 رتبه عرعر: {rank}\n"
        f"🔢 تعداد کل عرها: {sound_count}\n"
        f"💡 «صداها» رو بزن تا همه صداها رو ببینی!",
        parse_mode="Markdown"
    )

SOUNDS_LIST_TEXT = (
    f"🔊 **لیست صداهای خر — همه شانسی {SOUND_MIN} تا {SOUND_MAX} {CURRENCY_NAME}!**\n"
    "━━━━━━━━━━━━━━\n" +
    "\n".join(
        f"`{k}` — {v['desc']}"
        for k, v in SOUND_KEYWORDS.items()
    ) +
    f"\n\n🎲 هر عرعر یه قماره: بین **{SOUND_MIN}** تا **{SOUND_MAX}** {CURRENCY_NAME} شانسی!\n"
    "🌟 شانس **عر طلایی** هم هست (تا +300 اضافه!)\n"
    "🏅 با عرعر بیشتر، رتبه‌ات بالا می‌ره:\n" +
    "\n".join(f"{name} — {need} عر" for need, name in SOUND_RANKS) +
    "\n\n⏳ هر ۲ دقیقه یک بار می‌تونی صدا بدی."
)

# ============================================================
# کار کردن
# ============================================================

WORK_COOLDOWN = 3600  # هر ۱ ساعت

WORK_JOBS = [
    {"name": "🌾 گاری‌کشی توی مزرعه", "min": 50, "max": 150},
    {"name": "🧱 آجرکشی سر ساختمون", "min": 60, "max": 170},
    {"name": "🚕 مسافرکشی با گاری", "min": 40, "max": 200},
    {"name": "🎪 بازیگری توی سیرک", "min": 30, "max": 250},
    {"name": "📦 باربری بازار", "min": 70, "max": 160},
    {"name": "🎨 مدل نقاشی نقاش‌های خیابونی", "min": 20, "max": 220},
    {"name": "🏇 مسابقه دو با اسب‌ها", "min": 10, "max": 300},
    {"name": "🧹 نظافت طویله همسایه", "min": 80, "max": 140}
]

WORK_FAILS = [
    "وسط کار خوابت برد و صاحب‌کار بیرونت کرد! 😴",
    "جفتک انداختی به مشتری و اخراج شدی! 🦵",
    "گاری چپ شد و همه بارش ریخت! 🛒💥",
    "به جای کار، رفتی یونجه خوردی! 🌾😋"
]

async def work_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    u = get_user(user.id)
    if not u: return
    
    now = int(time.time())
    last_work = u["last_work"] or 0
    
    if now - last_work < WORK_COOLDOWN:
        remaining = WORK_COOLDOWN - (now - last_work)
        await update.message.reply_text(
            f"😮‍💨 هنوز خسته‌ای! {remaining // 60} دقیقه دیگه بیا سر کار 🐴"
        )
        return
    
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET last_work = ? WHERE user_id = ?", (now, user.id))
        db.commit()
    
    job = random.choice(WORK_JOBS)
    
    # ۱۵٪ احتمال شکست خنده‌دار
    if random.random() < 0.15:
        fail = random.choice(WORK_FAILS)
        await update.message.reply_text(
            f"💼 **کار: {job['name']}**\n━━━━━━━━━━━━━━\n"
            f"❌ {fail}\n💸 دستمزد: صفر! یک ساعت دیگه دوباره تلاش کن.",
            parse_mode="Markdown"
        )
        return
    
    wage = random.randint(job["min"], job["max"])
    add_coins(user.id, wage)
    await update.message.reply_text(
        f"💼 **کار: {job['name']}**\n━━━━━━━━━━━━━━\n"
        f"👤 {esc_md(user.first_name)} یه ساعت جون کند...\n"
        f"💰 دستمزد: **+{wage}** {CURRENCY_NAME}\n\n"
        f"⏰ یک ساعت دیگه دوباره می‌تونی کار کنی!",
        parse_mode="Markdown"
    )

# ============================================================
# گردونه شانس
# ============================================================

WHEEL_COOLDOWN = 10800  # هر ۳ ساعت
WHEEL_PRIZES = [
    (25, "💨 هیچی! گردونه خالی چرخید", 0),
    (25, "🪙 یه مشت سکه", 50),
    (20, "💰 کیسه سکه", 150),
    (15, "💎 جواهر کوچیک", 300),
    (10, "🏆 گنج طویله", 600),
    (4,  "👑 جکپات سلطنتی", 1500),
    (1,  "🌟 گنج افسانه‌ای خرستان", 5000)
]

async def wheel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    u = get_user(user.id)
    if not u: return
    
    now = int(time.time())
    last_wheel = u["last_wheel"] or 0
    
    if now - last_wheel < WHEEL_COOLDOWN:
        remaining = WHEEL_COOLDOWN - (now - last_wheel)
        await update.message.reply_text(
            f"🎡 گردونه داغ کرده! {remaining // 3600} ساعت و {(remaining % 3600) // 60} دقیقه دیگه بیا!"
        )
        return
    
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET last_wheel = ? WHERE user_id = ?", (now, user.id))
        db.commit()
    
    roll = random.uniform(0, 100)
    acc = 0
    prize_name, prize_coins = WHEEL_PRIZES[0][1], WHEEL_PRIZES[0][2]
    for chance, name, coins in WHEEL_PRIZES:
        acc += chance
        if roll <= acc:
            prize_name, prize_coins = name, coins
            break
    
    if prize_coins > 0:
        add_coins(user.id, prize_coins)
        result = f"🎊 {prize_name}\n💰 جایزه: **+{prize_coins}** {CURRENCY_NAME}"
    else:
        result = f"{prize_name} 😅\nشانست رو ۳ ساعت دیگه امتحان کن!"
    
    await update.message.reply_text(
        f"🎡 **گردونه شانس طویله**\n━━━━━━━━━━━━━━\n"
        f"🌀 گردونه چرخید و چرخید...\n\n"
        f"👤 {esc_md(user.first_name)}\n{result}",
        parse_mode="Markdown"
    )

# ============================================================
# دزدی
# ============================================================

ROB_COOLDOWN = 7200  # هر ۲ ساعت
ROB_SUCCESS_CHANCE = 0.40
ROB_FINE_PERCENT = 0.05

ROB_SUCCESS_TEXTS = [
    "نصفه‌شب یواشکی رفتی توی طویله‌اش و زدی به چاک! 🌙🏃",
    "با نقاب خرکی سر گردنه رو زدی! 🎭",
    "وقتی داشت یونجه می‌خورد جیبش رو زدی! 🌾🤏"
]
ROB_FAIL_TEXTS = [
    "صاحب طویله با بیل دنبالت کرد! 🪏💨",
    "پات به سطل گیر کرد و افتادی، همه بیدار شدن! 🪣💥",
    "سگ نگهبان گرفتت! جریمه شدی! 🐕⛓️"
]

async def rob_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    
    if not update.message.reply_to_message:
        await update.message.reply_text("🦹 روی پیام کسی که می‌خوای ازش بدزدی **ریپلی** بزن و بنویس `دزدی`", parse_mode="Markdown")
        return
    
    target = update.message.reply_to_message.from_user
    if target.id == user.id:
        await update.message.reply_text("❌ از خودت می‌خوای بدزدی؟! 😂")
        return
    if target.is_bot:
        await update.message.reply_text("❌ از ربات نمی‌شه دزدید! 🤖")
        return
    
    ensure_user(target.id, target.first_name)
    u = get_user(user.id)
    t = get_user(target.id)
    
    now = int(time.time())
    last_rob = u["last_rob"] or 0
    if now - last_rob < ROB_COOLDOWN:
        remaining = ROB_COOLDOWN - (now - last_rob)
        await update.message.reply_text(f"🚔 پلیس طویله دنبالته! {remaining // 60} دقیقه صبر کن!")
        return
    
    if t["coins"] < 100:
        await update.message.reply_text(f"😅 {esc_md(target.first_name)} انقدر فقیره که چیزی برای دزدیدن نداره!")
        return
    
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET last_rob = ? WHERE user_id = ?", (now, user.id))
        db.commit()
    
    if random.random() < ROB_SUCCESS_CHANCE:
        # موفق: ۳ تا ۱۰ درصد پول هدف
        loot = max(10, int(t["coins"] * random.uniform(0.03, 0.10)))
        loot = min(loot, 2000)  # سقف دزدی
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (loot, target.id))
            db.commit()
        add_coins(user.id, loot)
        story = random.choice(ROB_SUCCESS_TEXTS)
        await update.message.reply_text(
            f"🦹 **دزدی موفق!**\n━━━━━━━━━━━━━━\n"
            f"{story}\n\n"
            f"💰 {esc_md(user.first_name)} مبلغ **{loot}** {CURRENCY_NAME} از {esc_md(target.first_name)} دزدید! 🏃💨",
            parse_mode="Markdown"
        )
    else:
        fine = max(20, int(u["coins"] * ROB_FINE_PERCENT))
        fine = min(fine, 1000)
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (fine, user.id))
            db.commit()
        story = random.choice(ROB_FAIL_TEXTS)
        await update.message.reply_text(
            f"🚨 **دزدی ناموفق!**\n━━━━━━━━━━━━━━\n"
            f"{story}\n\n"
            f"💸 {esc_md(user.first_name)} جریمه شد: **-{fine}** {CURRENCY_NAME} 😭",
            parse_mode="Markdown"
        )

# ============================================================
# فال خرستان
# ============================================================

FORTUNE_COOLDOWN = 21600  # هر ۶ ساعت

FORTUNES = [
    ("🌟 امروز روز شانسته! یه عر بلند بکش!", 50),
    ("💰 ثروت بزرگی در راهه... شاید هم یونجه باشه!", 30),
    ("❤️ یک خر جذاب به زندگیت وارد می‌شه!", 20),
    ("🎲 امروز توی قمار دستت داغه! (شایدم نه 😏)", 25),
    ("🐴 خر درونت رو آزاد کن، موفقیت نزدیکه!", 35),
    ("🌈 بعد از هر عرعری، رنگین‌کمونی هست!", 15),
    ("⚠️ مواظب باش! یکی می‌خواد ازت بدزده!", 10),
    ("🦄 تو فقط یه خر نیستی، یه تک‌شاخ در حال پیشرفتی!", 40),
    ("📿 ستاره‌ها می‌گن: کمتر جفتک بنداز، بیشتر پس‌انداز کن!", 20),
    ("🔮 عدد شانس امروزت: عر!", 30)
]

async def fortune_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    u = get_user(user.id)
    if not u: return
    
    now = int(time.time())
    last_fortune = u["last_fortune"] or 0
    if now - last_fortune < FORTUNE_COOLDOWN:
        remaining = FORTUNE_COOLDOWN - (now - last_fortune)
        await update.message.reply_text(f"🔮 گوی جادویی خوابیده! {remaining // 3600} ساعت و {(remaining % 3600) // 60} دقیقه دیگه بیا.")
        return
    
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET last_fortune = ? WHERE user_id = ?", (now, user.id))
        db.commit()
    
    text_f, coins = random.choice(FORTUNES)
    add_coins(user.id, coins)
    
    await update.message.reply_text(
        f"🔮 **فال خرستان**\n━━━━━━━━━━━━━━\n"
        f"👤 {esc_md(user.first_name)} عزیز:\n\n"
        f"«{text_f}»\n\n"
        f"🎁 برکت فال: **+{coins}** {CURRENCY_NAME}",
        parse_mode="Markdown"
    )

# ============================================================
# انتقال سکه بین کاربران
# ============================================================

TRANSFER_MIN = 10
TRANSFER_MAX = 50000

async def transfer_command(update: Update, context: ContextTypes.DEFAULT_TYPE, amount):
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    
    if not update.message.reply_to_message:
        await update.message.reply_text("💸 روی پیام طرف **ریپلی** بزن و بنویس: `انتقال 100`", parse_mode="Markdown")
        return
    
    target = update.message.reply_to_message.from_user
    if target.id == user.id:
        await update.message.reply_text("❌ به خودت می‌خوای پول بدی؟! 😂")
        return
    if target.is_bot:
        await update.message.reply_text("❌ ربات پول نمی‌خواد! 🤖")
        return
    
    if amount < TRANSFER_MIN or amount > TRANSFER_MAX:
        await update.message.reply_text(f"❌ مبلغ باید بین {TRANSFER_MIN} تا {TRANSFER_MAX:,} باشه!")
        return
    
    ensure_user(target.id, target.first_name)
    
    if not remove_coins(user.id, amount):
        u = get_user(user.id)
        await update.message.reply_text(f"❌ موجودی کافی نداری! داری: {u['coins']:,} {CURRENCY_NAME}")
        return
    
    add_coins(target.id, amount)
    await update.message.reply_text(
        f"💸 **انتقال موفق!**\n━━━━━━━━━━━━━━\n"
        f"👤 {esc_md(user.first_name)} ⬅️ {esc_md(target.first_name)}\n"
        f"💰 مبلغ: **{amount:,}** {CURRENCY_NAME}\n\n"
        f"🤝 دمت گرم، رفاقت یعنی این!",
        parse_mode="Markdown"
    )

# ============================================================
# نمایش خر شخصی
# ============================================================

def donkey_art(user_id):
    """نمایش خر کاربر با وسایلش"""
    donkey = get_donkey(user_id)
    u = get_user(user_id)
    if not u:
        return "❌ کاربر پیدا نشد."
    
    hat = "🎩" if donkey and donkey["equipped_hat"] else "  "
    tie = "👔" if donkey and donkey["equipped_tie"] else ""
    acc = "🎀" if donkey and donkey["equipped_accessory"] else ""
    shoe = "👟" if donkey and donkey["equipped_horseshoe"] else ""
    
    art = (
        f"      {hat}\n"
        f"   🐴 {acc}\n"
        f"  ╱|  {tie}\n"
        f" ╱ |╲_🐾\n"
        f"   {shoe}  {shoe}\n"
    )
    
    items = []
    if donkey:
        pretty = {
            "equipped_hat": "🎩", "equipped_saddle": "🐴", "equipped_horseshoe": "👟",
            "equipped_tie": "👔", "equipped_clothes": "👕", "equipped_accessory": "🎀"
        }
        for col, emo in pretty.items():
            if donkey[col]:
                items.append(f"{emo} {donkey[col]}")
    
    title = get_title_by_level(u["level"])
    msg = (
        f"🐴 **خرِ {esc_md(u['name'])}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"```\n{art}```\n"
        f"🏅 لقب: {title}\n"
    )
    if items:
        msg += "🎒 تجهیزات:\n" + "\n".join(items)
    else:
        msg += "🎒 تجهیزات: لخت و پتی! برو فروشگاه 🏪"
    return msg

# ============================================================
# 🐣 سیستم کره‌خر: سود روزانه + ارتقا + اسم‌گذاری
# ============================================================

# سطح: (اسم سطح، ایموجی، سود روزانه، هزینه ارتقا به این سطح)
BABY_LEVELS = {
    1: {"name": "نوزاد",   "emoji": "🐣", "income": 200,  "cost": 0},
    2: {"name": "کوچولو",  "emoji": "🐤", "income": 400,  "cost": 1000},
    3: {"name": "نوجوون",  "emoji": "🐥", "income": 800,  "cost": 3000},
    4: {"name": "جوون",    "emoji": "🐴", "income": 1400, "cost": 8000},
    5: {"name": "طلایی",   "emoji": "🦄", "income": 2000, "cost": 20000},
}
BABY_MAX_LEVEL = 5
BABY_NAME_MAXLEN = 20

def load_babies(u):
    """خواندن کره‌خرها + مهاجرت خودکار از فرمت قدیمی (لیست رشته) به جدید (لیست دیکشنری)"""
    try:
        raw = json.loads(u["baby_names"]) if u["baby_names"] else []
    except (json.JSONDecodeError, TypeError):
        raw = []
    babies = []
    changed = False
    for b in raw:
        if isinstance(b, dict) and "name" in b:
            b.setdefault("level", 1)
            babies.append(b)
        else:
            # فرمت قدیمی: فقط اسم رشته‌ای
            name = str(b).replace("🐣", "").strip() or "کره‌خر"
            babies.append({"name": name[:BABY_NAME_MAXLEN], "level": 1})
            changed = True
    if changed:
        save_babies(u["user_id"], babies)
    return babies

def save_babies(user_id, babies):
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET baby_names = ?, babies = ? WHERE user_id = ?",
                  (json.dumps(babies, ensure_ascii=False), len(babies), user_id))
        db.commit()

def babies_daily_income(babies):
    return sum(BABY_LEVELS.get(b.get("level", 1), BABY_LEVELS[1])["income"] for b in babies)

def baby_line(i, b):
    lv = BABY_LEVELS.get(b.get("level", 1), BABY_LEVELS[1])
    return f"{i}. {lv['emoji']} **{esc_md(b['name'])}** — سطح {b.get('level',1)} ({lv['name']}) | سود روزانه: {lv['income']} {CURRENCY_NAME}"

# ------------------------------------------------------------
# 🐣 پنل کره‌خرها (دکمه شیشه‌ای)
# ------------------------------------------------------------

def baby_panel_text(user_id):
    u = get_user(user_id)
    if not u:
        return "❌ کاربر پیدا نشد."
    babies = load_babies(u)
    if not babies:
        return ("🐣 **پنل کره‌خرها**\n━━━━━━━━━━━━━━\n"
                "هنوز کره‌خری نداری! 😢\n\n"
                "❤️ روی پیام یه نفر ریپلی بزن و بنویس `جفت‌گیری` تا صاحب کره‌خر شی!\n"
                f"💰 هر کره‌خر روزی {BABY_LEVELS[1]['income']} تا {BABY_LEVELS[BABY_MAX_LEVEL]['income']} {CURRENCY_NAME} سود می‌ده!")
    lines = [f"🐣 **پنل کره‌خرهای {esc_md(u['name'])}** ({len(babies)}/{MAX_BABIES})", "━━━━━━━━━━━━━━"]
    for i, b in enumerate(babies, 1):
        lv = BABY_LEVELS.get(b.get("level", 1), BABY_LEVELS[1])
        bar = "🟩" * b.get("level", 1) + "⬜" * (BABY_MAX_LEVEL - b.get("level", 1))
        lines.append(f"{i}. {lv['emoji']} **{esc_md(b['name'])}**")
        lines.append(f"   {bar} سطح {b.get('level',1)} ({lv['name']})")
        if b.get("level", 1) < BABY_MAX_LEVEL:
            nxt = BABY_LEVELS[b.get("level", 1) + 1]
            lines.append(f"   💰 سود: {lv['income']}/روز | ⬆️ ارتقا: {nxt['cost']:,}")
        else:
            lines.append(f"   💰 سود: {lv['income']}/روز | 🏆 فول‌لِوِل!")
    total = babies_daily_income(babies)
    lines.append(f"\n💎 جمع سود روزانه: **{total}** {CURRENCY_NAME}")
    lines.append(f"💳 موجودیت: {u['coins']:,} {CURRENCY_NAME}")
    lines.append("\n👇 برای ارتقا یا تغییر اسم، دکمه کره‌خر رو بزن:")
    return "\n".join(lines)

def baby_panel_keyboard(user_id):
    u = get_user(user_id)
    babies = load_babies(u) if u else []
    rows = []
    row = []
    for i, b in enumerate(babies, 1):
        lv = BABY_LEVELS.get(b.get("level", 1), BABY_LEVELS[1])
        row.append(InlineKeyboardButton(f"{lv['emoji']} {b['name'][:12]}", callback_data=f"babe_view_{i}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🔄 بروزرسانی", callback_data="babe_home"),
                 InlineKeyboardButton("🏠 منو", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def baby_detail_text(user_id, idx):
    u = get_user(user_id)
    babies = load_babies(u) if u else []
    if idx < 1 or idx > len(babies):
        return None
    b = babies[idx - 1]
    lv_no = b.get("level", 1)
    lv = BABY_LEVELS.get(lv_no, BABY_LEVELS[1])
    bar = "🟩" * lv_no + "⬜" * (BABY_MAX_LEVEL - lv_no)
    lines = [f"{lv['emoji']} **{esc_md(b['name'])}** — کره‌خر شماره {idx}", "━━━━━━━━━━━━━━",
             f"{bar}",
             f"⭐ سطح: {lv_no} ({lv['name']})",
             f"💰 سود روزانه: **{lv['income']}** {CURRENCY_NAME}"]
    if lv_no < BABY_MAX_LEVEL:
        nxt = BABY_LEVELS[lv_no + 1]
        lines.append(f"\n⬆️ **ارتقا به سطح {lv_no+1} ({nxt['name']}):**")
        lines.append(f"💸 هزینه: {nxt['cost']:,} {CURRENCY_NAME}")
        lines.append(f"💰 سود جدید: {nxt['income']}/روز (+{nxt['income']-lv['income']})")
        lines.append(f"💳 موجودیت: {u['coins']:,} {CURRENCY_NAME}")
    else:
        lines.append("\n🏆 این کره‌خر فول‌لِوِله! 🦄")
    lines.append(f"\n📛 تغییر اسم: بنویس `اسم کره‌خر {idx} اسم‌جدید`")
    return "\n".join(lines)

def baby_detail_keyboard(user_id, idx):
    u = get_user(user_id)
    babies = load_babies(u) if u else []
    rows = []
    if 1 <= idx <= len(babies) and babies[idx-1].get("level", 1) < BABY_MAX_LEVEL:
        nxt = BABY_LEVELS[babies[idx-1].get("level", 1) + 1]
        rows.append([InlineKeyboardButton(f"⬆️ ارتقا ({nxt['cost']:,} 🪙)", callback_data=f"babe_up_{idx}")])
    rows.append([InlineKeyboardButton("🔙 پنل کره‌خرها", callback_data="babe_home")])
    return InlineKeyboardMarkup(rows)

def babies_list_text(user_id):
    u = get_user(user_id)
    if not u:
        return "❌ کاربر پیدا نشد."
    babies = load_babies(u)
    if not babies:
        return ("🐣 **کره‌خرهات**\n━━━━━━━━━━━━━━\n"
                "هنوز کره‌خری نداری! ❤️ با `جفت‌گیری` (ریپلی روی یه نفر) صاحب کره‌خر شو!\n"
                f"💰 هر کره‌خر روزی {BABY_LEVELS[1]['income']} تا {BABY_LEVELS[BABY_MAX_LEVEL]['income']} {CURRENCY_NAME} سود می‌ده!")
    lines = [f"🐣 **کره‌خرهای {esc_md(u['name'])}** ({len(babies)}/{MAX_BABIES})", "━━━━━━━━━━━━━━"]
    for i, b in enumerate(babies, 1):
        lines.append(baby_line(i, b))
    total = babies_daily_income(babies)
    lines.append(f"\n💰 جمع سود روزانه: **{total}** {CURRENCY_NAME} (خودکار با «روزانه»)")
    lines.append("\n📋 دستورات:")
    lines.append("`ارتقا کره‌خر 1` — ارتقای کره‌خر شماره ۱")
    lines.append("`اسم کره‌خر 1 فلفلی` — تغییر اسم")
    return "\n".join(lines)

async def baby_upgrade_command(update, context, idx):
    user = update.effective_user
    u = get_user(user.id)
    babies = load_babies(u)
    if not babies:
        await update.message.reply_text("❌ هنوز کره‌خری نداری! اول جفت‌گیری کن ❤️")
        return
    if idx < 1 or idx > len(babies):
        await update.message.reply_text(f"❌ کره‌خر شماره {idx} نداری! (۱ تا {len(babies)}) — لیست: `کره‌خرها`", parse_mode="Markdown")
        return
    b = babies[idx - 1]
    cur = b.get("level", 1)
    if cur >= BABY_MAX_LEVEL:
        await update.message.reply_text(f"🦄 **{esc_md(b['name'])}** الان فول‌لِوِله (طلایی)! بالاتر نداریم 😎", parse_mode="Markdown")
        return
    nxt = BABY_LEVELS[cur + 1]
    if not remove_coins(user.id, nxt["cost"]):
        await update.message.reply_text(
            f"❌ برای ارتقای **{esc_md(b['name'])}** به سطح {cur+1} ({nxt['name']}) {nxt['cost']:,} {CURRENCY_NAME} لازمه!\n"
            f"💳 موجودیت: {u['coins']:,}", parse_mode="Markdown")
        return
    b["level"] = cur + 1
    save_babies(user.id, babies)
    await update.message.reply_text(
        f"🎉 **ارتقا موفق!**\n━━━━━━━━━━━━━━\n"
        f"{nxt['emoji']} **{esc_md(b['name'])}** رسید به سطح **{cur+1} ({nxt['name']})**!\n"
        f"💰 سود روزانه جدیدش: **{nxt['income']}** {CURRENCY_NAME}\n"
        f"💸 هزینه: {nxt['cost']:,} {CURRENCY_NAME}", parse_mode="Markdown")

async def baby_rename_command(update, context, idx, new_name):
    user = update.effective_user
    u = get_user(user.id)
    babies = load_babies(u)
    if not babies:
        await update.message.reply_text("❌ هنوز کره‌خری نداری! اول جفت‌گیری کن ❤️")
        return
    if idx < 1 or idx > len(babies):
        await update.message.reply_text(f"❌ کره‌خر شماره {idx} نداری! (۱ تا {len(babies)})")
        return
    new_name = new_name.strip()[:BABY_NAME_MAXLEN]
    if not new_name:
        await update.message.reply_text("❌ اسم خالیه! مثال: `اسم کره‌خر 1 فلفلی`", parse_mode="Markdown")
        return
    old = babies[idx - 1]["name"]
    babies[idx - 1]["name"] = new_name
    save_babies(user.id, babies)
    await update.message.reply_text(
        f"📛 اسم کره‌خر شماره {idx} از «{esc_md(old)}» شد: **{esc_md(new_name)}** 🎉", parse_mode="Markdown")

# ============================================================
# جفت‌گیری
# ============================================================

MATE_COST = 500
MAX_BABIES = 5
MATE_COOLDOWN = 86400

# درخواست‌های جفت‌گیری در انتظار جواب: {(chat_id, msg_id): {"from": id, "to": id, "time": ts}}
MATE_PROPOSALS = {}
MATE_PROPOSAL_TTL = 300  # درخواست بعد از ۵ دقیقه منقضی می‌شود

def mate_check(user_id, user_name, target_id, target_name):
    """بررسی همه شرایط جفت‌گیری — خروجی: (پیام خطا یا None)"""
    u1 = get_user(user_id)
    u2 = get_user(target_id)
    
    if u1["level"] < 2:
        return f"❌ {esc_md(user_name)} عزیز، سطح تو {u1['level']} است.\nبرای جفت‌گیری باید به **سطح ۲** برسی! 🐣"
    if u2["level"] < 2:
        return f"❌ {esc_md(target_name)} عزیز، سطحش {u2['level']} است.\nبرای جفت‌گیری باید به **سطح ۲** برسه! 🐣"
    if u1["coins"] < MATE_COST:
        return f"❌ {esc_md(user_name)} {MATE_COST} {CURRENCY_NAME} نداری! 💸"
    if u2["coins"] < MATE_COST:
        return f"❌ {esc_md(target_name)} {MATE_COST} {CURRENCY_NAME} نداره! 💸"
    
    babies1 = load_babies(u1)
    babies2 = load_babies(u2)
    if len(babies1) >= MAX_BABIES:
        return f"❌ {esc_md(user_name)} دیگه جا برای کره‌خر جدید نداری! (حداکثر {MAX_BABIES})"
    if len(babies2) >= MAX_BABIES:
        return f"❌ {esc_md(target_name)} دیگه جا برای کره‌خر جدید نداره! (حداکثر {MAX_BABIES})"
    
    now = int(time.time())
    if now - u1["last_mate"] < MATE_COOLDOWN:
        remaining = (MATE_COOLDOWN - (now - u1["last_mate"])) // 3600
        return f"⏳ {esc_md(user_name)} عزیز، {remaining} ساعت دیگه می‌تونی جفت‌گیری کنی!"
    if now - u2["last_mate"] < MATE_COOLDOWN:
        remaining = (MATE_COOLDOWN - (now - u2["last_mate"])) // 3600
        return f"⏳ {esc_md(target_name)} عزیز، {remaining} ساعت دیگه می‌تونه جفت‌گیری کنه!"
    return None

def mate_do(user_id, target_id):
    """انجام جفت‌گیری بعد از قبول — خروجی: متن نتیجه"""
    u1 = get_user(user_id)
    u2 = get_user(target_id)
    now = int(time.time())
    
    remove_coins(user_id, MATE_COST)
    remove_coins(target_id, MATE_COST)
    
    baby_names = ["کوچولو", "نازنین", "خوشگل", "بازیگوش", "شیطون", "فسقلی", "پشمالو", "عرعرو"]
    baby_name = random.choice(baby_names)
    
    babies1 = load_babies(u1)
    babies2 = load_babies(u2)
    babies1.append({"name": baby_name, "level": 1})
    babies2.append({"name": baby_name, "level": 1})
    
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET baby_names = ?, babies = ?, last_mate = ? WHERE user_id = ?",
                  (json.dumps(babies1, ensure_ascii=False), len(babies1), now, user_id))
        db.execute("UPDATE users SET baby_names = ?, babies = ?, last_mate = ? WHERE user_id = ?",
                  (json.dumps(babies2, ensure_ascii=False), len(babies2), now, target_id))
        db.commit()
    
    return (
        f"🎉 **تبریک! جفت‌گیری موفق!**\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👫 {uname(user_id)} ❤️ {uname(target_id)}\n\n"
        f"🐣 **کره‌خر متولد شد:** {baby_name}\n"
        f"💰 سود روزانه‌ش: {BABY_LEVELS[1]['income']} {CURRENCY_NAME} (با «روزانه» خودکار می‌گیری)\n"
        f"👶 تعداد کره‌خرهای {uname(user_id)}: {len(babies1)}\n"
        f"👶 تعداد کره‌خرهای {uname(target_id)}: {len(babies2)}\n\n"
        f"💸 هزینه: {MATE_COST} {CURRENCY_NAME} از هر نفر\n"
        f"💡 با `کره‌خرها` مدیریتشون کن — اسم بذار و ارتقا بده!"
    )

async def mate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست جفت‌گیری — باید طرف مقابل قبول کنه ❤️"""
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ روی پیام شخص مورد نظر **ریپلی (Reply)** بزن و بنویس `جفت‌گیری`.",
            parse_mode="Markdown"
        )
        return
    
    target = update.message.reply_to_message.from_user
    target_id = target.id
    
    if user.id == target_id:
        await update.message.reply_text("❌ نمی‌تونی با خودت جفت‌گیری کنی! 😂")
        return
    if target.is_bot:
        await update.message.reply_text("❌ با ربات نمی‌شه جفت‌گیری کرد! 🤖😂")
        return
    
    ensure_user(target_id, target.first_name)
    
    # بررسی شرایط قبل از فرستادن درخواست
    err = mate_check(user.id, user.first_name, target_id, target.first_name)
    if err:
        await update.message.reply_text(err, parse_mode="Markdown")
        return
    
    # 💌 ارسال درخواست با دکمه قبول/رد — فقط طرف مقابل می‌تونه جواب بده
    sent = await update.message.reply_text(
        f"💌 **درخواست جفت‌گیری!**\n"
        f"━━━━━━━━━━━━━━\n"
        f"🐴 {esc_md(user.first_name)} می‌خواد با {esc_md(target.first_name)} جفت‌گیری کنه!\n\n"
        f"💸 هزینه: {MATE_COST} {CURRENCY_NAME} از هر نفر\n"
        f"🐣 نتیجه: یک کره‌خر برای هر دو!\n\n"
        f"❓ {esc_md(target.first_name)} عزیز، نظرت چیه؟\n"
        f"⏳ (۵ دقیقه فرصت داری جواب بدی)",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("💚 قبوله!", callback_data="mate_yes"),
            InlineKeyboardButton("💔 نه ممنون", callback_data="mate_no")
        ]]),
        parse_mode="Markdown"
    )
    
    # پاکسازی درخواست‌های منقضی‌شده
    now = time.time()
    for k in list(MATE_PROPOSALS.keys()):
        if now - MATE_PROPOSALS[k]["time"] > MATE_PROPOSAL_TTL:
            MATE_PROPOSALS.pop(k, None)
    
    MATE_PROPOSALS[(update.effective_chat.id, sent.message_id)] = {
        "from": user.id, "to": target_id, "time": now
    }

async def mate_callback(update, context, query, answer):
    """جواب درخواست جفت‌گیری — فقط کسی که ازش خواستگاری شده"""
    key = (query.message.chat_id, query.message.message_id)
    prop = MATE_PROPOSALS.get(key)
    
    if not prop:
        await query.answer("❌ این درخواست منقضی شده!", show_alert=True)
        try:
            await query.edit_message_text("⌛ این درخواست جفت‌گیری منقضی شده.")
        except Exception:
            pass
        return
    
    uid = query.from_user.id
    if uid != prop["to"]:
        if uid == prop["from"]:
            await query.answer("😅 صبر کن، طرف مقابل باید جواب بده!", show_alert=True)
        else:
            await query.answer("🔒 این درخواست مال تو نیست!", show_alert=True)
        return
    
    if time.time() - prop["time"] > MATE_PROPOSAL_TTL:
        MATE_PROPOSALS.pop(key, None)
        await query.answer("⌛ درخواست منقضی شده!", show_alert=True)
        await query.edit_message_text("⌛ این درخواست جفت‌گیری منقضی شده.")
        return
    
    MATE_PROPOSALS.pop(key, None)
    
    if answer == "no":
        await query.answer("💔 رد شد!")
        await query.edit_message_text(
            f"💔 **درخواست رد شد!**\n"
            f"{uname(prop['to'])} به {uname(prop['from'])} جواب منفی داد! 😢\n"
            f"🐴 غم آخرت باشه رفیق...",
            parse_mode="Markdown"
        )
        return
    
    # ✅ قبول — دوباره شرایط چک بشه (شاید توی این فاصله پولش رو خرج کرده!)
    u_from = get_user(prop["from"])
    u_to = get_user(prop["to"])
    err = mate_check(prop["from"], u_from["name"] if u_from else "کاربر",
                     prop["to"], u_to["name"] if u_to else "کاربر")
    if err:
        await query.answer("❌ شرایط تغییر کرده!", show_alert=True)
        await query.edit_message_text(f"❌ جفت‌گیری انجام نشد:\n{err}", parse_mode="Markdown")
        return
    
    await query.answer("💚 قبول شد! 🎉")
    result = mate_do(prop["from"], prop["to"])
    await query.edit_message_text(result, parse_mode="Markdown")

# ============================================================
# نام بازی‌ها
# ============================================================

GAME_NAMES = {
    "rps": "✊ سنگ-کاغذ-قیچی",
    "blackjack": "🃏 بلک‌جک ۲۱",
    "crash": "💥 انفجار",
    "poker": "🎰 پوکر",
    "ttt": "❌⭕ دوز",
    "dice": "🎲 تاس",
    "roulette": "🔫 رولت روسی",
    "coinflip": "🪙 شیر یا خط",
    "hilo": "🔼🔽 حدس بالا/پایین",
    "darts": "🎯 دارت",
    "bowling": "🎳 بولینگ",
    "penalty": "⚽ پنالتی",
    "guessnum": "🔢 حدس عدد",
    "mines": "💣 مین‌روب"
}

GAME_MAX_PLAYERS = {
    "rps": 2,
    "blackjack": 6,
    "crash": 10,
    "poker": 6,
    "ttt": 2,
    "dice": 10,
    "roulette": 10,
    "coinflip": 2,
    "hilo": 10,
    "darts": 10,
    "bowling": 10,
    "penalty": 2,
    "guessnum": 10,
    "mines": 10
}

# بازی‌هایی که دقیقاً ۲ نفره هستند
TWO_PLAYER_GAMES = {"rps", "ttt", "coinflip", "penalty"}

# اسم فارسی بازی‌ها برای دستور متنی (مثلاً: انفجار 100)
GAME_ALIASES = {
    "انفجار": "crash",
    "تاس": "dice",
    "رولت": "roulette",
    "پوکر": "poker",
    "بلک‌جک": "blackjack",
    "بلک": "blackjack",
    "21": "blackjack",
    "۲۱": "blackjack",
    "دوز": "ttt",
    "سنگ": "rps",
    "قیچی": "rps",
    "شیرخط": "coinflip",
    "شیر": "coinflip",
    "حدس": "hilo",
    "بالاپایین": "hilo",
    "دارت": "darts",
    "بولینگ": "bowling",
    "پنالتی": "penalty",
    "حدس‌عدد": "guessnum",
    "حدسعدد": "guessnum",
    "مین": "mines",
    "بمب": "mines"
}

# ============================================================
# مدیریت اتاق‌ها
# ============================================================

ACTIVE_ROOMS = {}
PLAYER_IN_GAME = {}

# 🔒 مالکیت منوها: هر منویی که کاربر باز می‌کنه فقط خودش بتونه استفاده کنه
# (دکمه‌های بازی مثل «ورود به بازی» برای همه آزاده)
MENU_OWNERS = {}
MENU_OWNERS_MAX = 500

def register_menu(chat_id, message_id, user_id):
    """ثبت اینکه این منو رو کی باز کرده"""
    if len(MENU_OWNERS) >= MENU_OWNERS_MAX:
        # حذف قدیمی‌ترین‌ها
        for k in list(MENU_OWNERS.keys())[:100]:
            MENU_OWNERS.pop(k, None)
    MENU_OWNERS[(chat_id, message_id)] = user_id

def menu_owner_of(chat_id, message_id):
    return MENU_OWNERS.get((chat_id, message_id))

ROOM_TTL = 3600          # اتاق منتظر، بعد از یک ساعت پاک می‌شود
STARTED_TTL = 1800       # سقف مطلق عمر یک بازی شروع‌شده
STUCK_TIMEOUT = 180      # ⚡ بازی شروع‌شده بدون هیچ حرکتی بعد از ۳ دقیقه = گیر کرده → لغو و برگشت شرط
_ROOM_COUNTER = 0

def player_active_room(uid):
    """اتاق فعال بازیکن — اگر اتاق مرده باشد، قفل بازیکن هم آزاد می‌شود"""
    rid = PLAYER_IN_GAME.get(uid)
    if not rid:
        return None
    room = ACTIVE_ROOMS.get(rid)
    if not room or room.finished:
        PLAYER_IN_GAME.pop(uid, None)  # 🔓 رفع گیر: اتاق وجود ندارد
        return None
    return room

@dataclass
class GameRoom:
    room_id: str
    game_type: str
    chat_id: int
    creator_id: int
    bet: int
    max_players: int
    players: list = field(default_factory=list)
    started: bool = False
    finished: bool = False
    game_data: dict = field(default_factory=dict)
    message_id: int = 0
    created_at: float = field(default_factory=time.time)
    last_action: float = field(default_factory=time.time)

    def add_player(self, user_id: int) -> bool:
        if len(self.players) >= self.max_players:
            return False
        if user_id in self.players:
            return False
        self.players.append(user_id)
        return True

    def pot(self) -> int:
        return self.bet * len(self.players)

def _room_is_stale(room, now):
    """تشخیص اتاق مرده/گیرکرده"""
    if not room.started:
        return now - room.created_at > ROOM_TTL
    # بازی شروع‌شده: یا خیلی قدیمیه، یا هیچ حرکتی توش نشده (گیر کرده)
    if now - room.created_at > STARTED_TTL:
        return True
    # بازی‌های خودکار (انفجار، رولت با تسک) خودشون جلو می‌رن؛ گیرشون با last_action چک می‌شه
    if now - room.last_action > STUCK_TIMEOUT:
        return True
    return False

def refund_room(room):
    """💰 برگشت شرط همه بازیکنانی که طلبکارند"""
    if room.finished:
        return
    for p in room.players:
        # اگر در انفجار قبلاً برداشت کرده، دیگر پولی طلبکار نیست
        if room.game_type == "crash" and p in room.game_data.get("cashed", {}):
            continue
        add_coins(p, room.bet)

def purge_stale_rooms():
    """اتاق‌های رهاشده/گیرکرده را پاک می‌کند و شرط بازیکنان را برمی‌گرداند"""
    now = time.time()
    for rid in list(ACTIVE_ROOMS.keys()):
        room = ACTIVE_ROOMS.get(rid)
        if not room:
            continue
        if _room_is_stale(room, now):
            refund_room(room)
            room.finished = True
            for p in room.players:
                if PLAYER_IN_GAME.get(p) == rid:
                    PLAYER_IN_GAME.pop(p, None)
            ACTIVE_ROOMS.pop(rid, None)
            logger.info(f"🧹 اتاق گیرکرده/قدیمی {rid} ({room.game_type}) پاک شد و شرط‌ها برگشت")

def get_room(room_id: str):
    purge_stale_rooms()
    return ACTIVE_ROOMS.get(room_id)

def cleanup_room(room_id: str):
    room = ACTIVE_ROOMS.pop(room_id, None)
    if room:
        room.finished = True
        for p in room.players:
            if PLAYER_IN_GAME.get(p) == room_id:
                PLAYER_IN_GAME.pop(p, None)
        # پاکسازی صف‌های انتظار این چت
        try:
            if DICE_WAITING.get(room.chat_id) == room_id:
                DICE_WAITING.pop(room.chat_id, None)
        except NameError:
            pass
        try:
            if GUESS_WAITING.get(room.chat_id) == room_id:
                GUESS_WAITING.pop(room.chat_id, None)
        except NameError:
            pass

def create_room(chat_id: int, game_type: str, creator_id: int, bet: int) -> GameRoom:
    global _ROOM_COUNTER
    _ROOM_COUNTER += 1
    room_id = f"r{_ROOM_COUNTER}x{int(time.time())}"
    room = GameRoom(
        room_id=room_id,
        game_type=game_type,
        chat_id=chat_id,
        creator_id=creator_id,
        bet=bet,
        max_players=GAME_MAX_PLAYERS.get(game_type, 6),
        players=[creator_id]
    )
    ACTIVE_ROOMS[room_id] = room
    PLAYER_IN_GAME[creator_id] = room_id
    return room

async def show_room_status(room: GameRoom, context: ContextTypes.DEFAULT_TYPE, query=None):
    """نمایش وضعیت اتاق"""
    names = []
    for p in room.players:
        names.append(f"{len(names)+1}. {uname(p)}")
    
    min_p = 2
    text = (
        f"🎮 **{GAME_NAMES[room.game_type]}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 شرط: {room.bet} {CURRENCY_NAME}\n"
        f"🏆 جایزه فعلی: {room.pot()} {CURRENCY_NAME}\n"
        f"👥 بازیکنان ({len(room.players)}/{room.max_players}):\n"
        f"{chr(10).join(names)}\n"
    )
    
    if not room.started:
        if len(room.players) < min_p:
            text += "\n⏳ منتظر ورود بازیکنان... (حداقل ۲ نفر)"
        else:
            text += "\n✅ آماده شروع! سازنده می‌تونه شروع کنه."
    
    try:
        if query:
            await query.edit_message_text(text, reply_markup=room_control_keyboard(room), parse_mode="Markdown")
        else:
            await context.bot.edit_message_text(
                text,
                chat_id=room.chat_id,
                message_id=room.message_id,
                reply_markup=room_control_keyboard(room),
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.warning(f"⚠️ خطا در ویرایش پیام اتاق: {e}")

async def edit_room_msg(room: GameRoom, context, text, keyboard=None):
    """ویرایش امن پیام اصلی بازی"""
    try:
        await context.bot.edit_message_text(
            text,
            chat_id=room.chat_id,
            message_id=room.message_id,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.warning(f"⚠️ خطا در ویرایش پیام بازی: {e}")

def result_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎮 بازی جدید", callback_data="games_list"),
                                  InlineKeyboardButton("🏠 منو", callback_data="home")]])

# ============================================================
# دکمه‌ها
# ============================================================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 بازی‌ها", callback_data="games_list")],
        [InlineKeyboardButton("👤 پروفایل", callback_data="show_profile"), 
         InlineKeyboardButton("🏪 فروشگاه", callback_data="shop")],
        [InlineKeyboardButton("🐣 کره‌خرها", callback_data="babe_home"),
         InlineKeyboardButton("🏆 جدول", callback_data="leaderboard")],
        [InlineKeyboardButton("📖 راهنما", callback_data="help_main")]
    ])

def games_menu():
    buttons = []
    keys = list(GAME_NAMES.keys())
    # دو تا دو تا کنار هم
    for i in range(0, len(keys), 2):
        row = [InlineKeyboardButton(GAME_NAMES[k], callback_data=f"game_{k}") for k in keys[i:i+2]]
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="home")])
    return InlineKeyboardMarkup(buttons)

def shop_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎩 کلاه‌ها", callback_data="shop_hats")],
        [InlineKeyboardButton("🐴 زین‌ها", callback_data="shop_saddles")],
        [InlineKeyboardButton("👟 نعل‌ها", callback_data="shop_horseshoes")],
        [InlineKeyboardButton("👔 کروات‌ها", callback_data="shop_ties")],
        [InlineKeyboardButton("👕 لباس‌ها", callback_data="shop_clothes")],
        [InlineKeyboardButton("🎀 اکسسوری‌ها", callback_data="shop_accessories")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="home")]
    ])

def room_control_keyboard(room: GameRoom):
    buttons = []
    if not room.started:
        if len(room.players) < room.max_players:
            buttons.append([InlineKeyboardButton("👥 ورود به بازی", callback_data=f"room_join_{room.room_id}")])
        # 🤖 بازی با خر بات (وقتی هنوز جا هست و خر بات داخل نیست)
        if BOT_ID not in room.players and len(room.players) < room.max_players:
            buttons.append([InlineKeyboardButton("🤖 بازی با خر بات", callback_data=f"room_bot_{room.room_id}")])
        if len(room.players) >= 2:
            buttons.append([InlineKeyboardButton("▶️ شروع بازی", callback_data=f"room_start_{room.room_id}")])
        buttons.append([InlineKeyboardButton("❌ لغو", callback_data=f"room_cancel_{room.room_id}")])
    return InlineKeyboardMarkup(buttons)

async def room_timeout_watch(room: GameRoom, context):
    """⏰ اگر بازی تا ۲ دقیقه شروع نشد، خودکار لغو و شرط‌ها برگردانده شود"""
    try:
        await asyncio.sleep(ROOM_START_TIMEOUT)
        current = ACTIVE_ROOMS.get(room.room_id)
        if current is not room or room.started or room.finished:
            return
        for p in room.players:
            add_coins(p, room.bet)
        room.finished = True
        cleanup_room(room.room_id)
        await edit_room_msg(room, context,
            f"⏰ **بازی {GAME_NAMES[room.game_type]} به دلیل عدم شروع، خودکار لغو شد!**\n"
            f"💰 شرط همه بازیکنان برگشت داده شد.",
            result_keyboard())
    except Exception as e:
        logger.warning(f"⚠️ خطا در تایمر لغو اتاق: {e}")

# ============================================================
# اطلاعات فروشگاه
# ============================================================

SHOP_ITEMS = {
    "hats": {
        "name": "🎩 کلاه‌ها",
        "items": {
            "کلاه نی": {"price": 500, "emoji": "🧑‍🌾"},
            "کلاه کابوی": {"price": 2000, "emoji": "🤠"},
            "کلاه نظامی": {"price": 4000, "emoji": "🪖"},
            "کلاه شیک": {"price": 7000, "emoji": "🎩"},
            "تاج سلطنتی": {"price": 15000, "emoji": "👑"}
        }
    },
    "saddles": {
        "name": "🐴 زین‌ها",
        "items": {
            "زین چرمی ساده": {"price": 1000, "emoji": "🟫"},
            "زین نقره‌ای": {"price": 3500, "emoji": "🥈"},
            "زین طلایی": {"price": 8000, "emoji": "🥇"},
            "زین الماسی": {"price": 20000, "emoji": "💎"}
        }
    },
    "horseshoes": {
        "name": "👟 نعل‌ها",
        "items": {
            "نعل آهنی": {"price": 500, "emoji": "⚙️"},
            "نعل برنزی": {"price": 2000, "emoji": "🟠"},
            "نعل نقره‌ای": {"price": 5000, "emoji": "⚪"},
            "نعل طلایی": {"price": 12000, "emoji": "✨"}
        }
    },
    "ties": {
        "name": "👔 کروات‌ها",
        "items": {
            "کروات ساده": {"price": 500, "emoji": "⬛"},
            "کروات راه‌راه": {"price": 1500, "emoji": "🟦"},
            "کروات پولک‌دار": {"price": 3000, "emoji": "✨"},
            "کروات ابریشمی": {"price": 6000, "emoji": "🎀"},
            "کروات سلطنتی": {"price": 10000, "emoji": "👔"}
        }
    },
    "clothes": {
        "name": "👕 لباس‌ها",
        "items": {
            "لباس ساده": {"price": 500, "emoji": "👕"},
            "لباس شیک": {"price": 2000, "emoji": "🧥"},
            "لباس مجلسی": {"price": 4000, "emoji": "🤵"},
            "لباس نظامی": {"price": 7000, "emoji": "🎖️"},
            "لباس سلطنتی": {"price": 15000, "emoji": "👘"}
        }
    },
    "accessories": {
        "name": "🎀 اکسسوری‌ها",
        "items": {
            "زنگوله گردن": {"price": 500, "emoji": "🔔"},
            "پاپیون ساده": {"price": 1000, "emoji": "🎀"},
            "عینک آفتابی": {"price": 2500, "emoji": "😎"},
            "شال گردن": {"price": 4000, "emoji": "🧣"},
            "بال فرشته": {"price": 10000, "emoji": "🕊️"}
        }
    }
}

# ============================================================
# ابزار کارت
# ============================================================

CARD_SUITS = ["♠️", "♥️", "♦️", "♣️"]
CARD_RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_VALUE = {r: i + 2 for i, r in enumerate(CARD_RANKS)}

def new_deck():
    deck = [(r, s) for r in CARD_RANKS for s in CARD_SUITS]
    random.shuffle(deck)
    return deck

def card_str(c):
    return f"{c[0]}{c[1]}"

def hand_str(cards):
    return " ".join(card_str(c) for c in cards)

def bj_value(cards):
    """ارزش دست بلک‌جک با احتساب آس"""
    total = 0
    aces = 0
    for r, s in cards:
        if r == "A":
            aces += 1
            total += 11
        elif r in ("J", "Q", "K"):
            total += 10
        else:
            total += int(r)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total

# ارزیابی دست پوکر (۵ کارت)
POKER_HAND_NAMES = {
    8: "🌈 استریت فلاش",
    7: "🍀 کاره (چهارتایی)",
    6: "🏠 فول هاوس",
    5: "🎨 فلاش",
    4: "📶 استریت",
    3: "🎯 سه‌تایی",
    2: "✌️ دو پر",
    1: "👍 یک پر",
    0: "🃏 کارت بالا"
}

def poker_eval(cards):
    """خروجی: تاپل قابل مقایسه — بزرگتر یعنی دست بهتر"""
    ranks = sorted((RANK_VALUE[r] for r, s in cards), reverse=True)
    suits = [s for r, s in cards]
    cnt = Counter(ranks)
    groups = sorted(cnt.items(), key=lambda x: (x[1], x[0]), reverse=True)
    counts = [g[1] for g in groups]
    ordered = []
    for rank, c in groups:
        ordered.append(rank)
    
    flush = len(set(suits)) == 1
    uniq = sorted(set(ranks))
    straight = len(uniq) == 5 and uniq[-1] - uniq[0] == 4
    wheel = uniq == [2, 3, 4, 5, 14]  # A-2-3-4-5
    
    if (straight or wheel) and flush:
        high = 5 if wheel else uniq[-1]
        return (8, [high])
    if counts == [4, 1]:
        return (7, ordered)
    if counts == [3, 2]:
        return (6, ordered)
    if flush:
        return (5, ranks)
    if straight or wheel:
        high = 5 if wheel else uniq[-1]
        return (4, [high])
    if counts == [3, 1, 1]:
        return (3, ordered)
    if counts == [2, 2, 1]:
        return (2, ordered)
    if counts == [2, 1, 1, 1]:
        return (1, ordered)
    return (0, ranks)

# ============================================================
# موتور بازی‌ها
# ============================================================

def gcb(room_id, payload):
    """ساخت callback_data برای اکشن‌های داخل بازی"""
    return f"g|{room_id}|{payload}"

async def finish_game(room, context, text):
    """پایان بازی: نمایش نتیجه و پاکسازی اتاق"""
    room.finished = True
    await edit_room_msg(room, context, text, result_keyboard())
    cleanup_room(room.room_id)

async def start_game(room: GameRoom, context: ContextTypes.DEFAULT_TYPE, query):
    """اجرای بازی انتخاب‌شده بعد از دکمه شروع"""
    room.started = True
    room.last_action = time.time()
    gt = room.game_type
    if gt == "rps":
        await rps_begin(room, context)
    elif gt == "ttt":
        await ttt_begin(room, context)
    elif gt == "coinflip":
        await coinflip_run(room, context)
    elif gt in ("dice", "darts", "bowling", "penalty"):
        await emoji_game_begin(room, context)
    elif gt == "roulette":
        await roulette_begin(room, context)
    elif gt == "guessnum":
        await guessnum_begin(room, context)
    elif gt == "mines":
        await mines_begin(room, context)
    elif gt == "poker":
        await poker_run(room, context)
    elif gt == "blackjack":
        await bj_begin(room, context)
    elif gt == "crash":
        await crash_begin(room, context)
    elif gt == "hilo":
        await hilo_begin(room, context)

# ------------------------------------------------------------
# ✊ سنگ-کاغذ-قیچی (۲ نفره)
# ------------------------------------------------------------

RPS_EMOJI = {"rock": "✊ سنگ", "paper": "✋ کاغذ", "scissors": "✌️ قیچی"}

def rps_keyboard(room):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✊", callback_data=gcb(room.room_id, "rps_rock")),
        InlineKeyboardButton("✋", callback_data=gcb(room.room_id, "rps_paper")),
        InlineKeyboardButton("✌️", callback_data=gcb(room.room_id, "rps_scissors"))
    ]])

async def rps_begin(room, context):
    room.game_data = {"choices": {}}
    # 🤖 خر بات مخفیانه انتخابش رو می‌کنه
    if BOT_ID in room.players:
        room.game_data["choices"][BOT_ID] = random.choice(["rock", "paper", "scissors"])
    p1, p2 = room.players[0], room.players[1]
    await edit_room_msg(
        room, context,
        f"✊ **سنگ-کاغذ-قیچی**\n━━━━━━━━━━━━━━\n"
        f"⚔️ {uname(p1)} 🆚 {uname(p2)}\n"
        f"💰 جایزه: {room.pot()} {CURRENCY_NAME}\n\n"
        f"🤫 هر دو بازیکن مخفیانه انتخاب کنید:\n"
        f"⏳ انتخاب‌شده: 0/2",
        rps_keyboard(room)
    )

async def rps_action(room, context, query, choice):
    uid = query.from_user.id
    gd = room.game_data
    if uid in gd["choices"]:
        await query.answer("✅ قبلاً انتخاب کردی!", show_alert=True)
        return
    gd["choices"][uid] = choice
    await query.answer(f"انتخاب شد: {RPS_EMOJI[choice]} 🤫")
    
    if len(gd["choices"]) < 2:
        p1, p2 = room.players[0], room.players[1]
        await edit_room_msg(
            room, context,
            f"✊ **سنگ-کاغذ-قیچی**\n━━━━━━━━━━━━━━\n"
            f"⚔️ {uname(p1)} 🆚 {uname(p2)}\n"
            f"💰 جایزه: {room.pot()} {CURRENCY_NAME}\n\n"
            f"🤫 هر دو بازیکن مخفیانه انتخاب کنید:\n"
            f"⏳ انتخاب‌شده: 1/2",
            rps_keyboard(room)
        )
        return
    
    p1, p2 = room.players[0], room.players[1]
    c1, c2 = gd["choices"][p1], gd["choices"][p2]
    beats = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
    
    header = (f"✊ **سنگ-کاغذ-قیچی — نتیجه**\n━━━━━━━━━━━━━━\n"
              f"👤 {uname(p1)}: {RPS_EMOJI[c1]}\n"
              f"👤 {uname(p2)}: {RPS_EMOJI[c2]}\n\n")
    
    if c1 == c2:
        # مساوی → دور جدید
        gd["choices"] = {}
        if BOT_ID in room.players:
            gd["choices"][BOT_ID] = random.choice(["rock", "paper", "scissors"])
        await edit_room_msg(room, context, header + "🤝 مساوی! دوباره انتخاب کنید:", rps_keyboard(room))
        return
    
    winner = p1 if beats[c1] == c2 else p2
    loser = p2 if winner == p1 else p1
    add_coins(winner, room.pot())
    record_win(winner)
    record_loss(loser)
    await finish_game(room, context, header + f"🏆 برنده: **{uname(winner)}**\n💰 جایزه: {room.pot()} {CURRENCY_NAME}")

# ------------------------------------------------------------
# ❌⭕ دوز (۲ نفره)
# ------------------------------------------------------------

def ttt_keyboard(room):
    b = room.game_data["board"]
    rows = []
    for i in range(0, 9, 3):
        rows.append([
            InlineKeyboardButton(b[j] if b[j] else "⬜", callback_data=gcb(room.room_id, f"ttt_{j}"))
            for j in range(i, i + 3)
        ])
    return InlineKeyboardMarkup(rows)

def ttt_winner(b):
    lines = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    for a, c, d in lines:
        if b[a] and b[a] == b[c] == b[d]:
            return b[a]
    return None

def _ttt_minimax(board, my_mark, opp_mark, is_my_turn, depth=0):
    """محاسبه کامل همه حالت‌ها — خروجی: امتیاز بهترین نتیجه ممکن"""
    w = ttt_winner(board)
    if w == my_mark:
        return 10 - depth       # برد سریع‌تر بهتره
    if w == opp_mark:
        return depth - 10       # باخت دیرتر بهتره
    empty = [i for i in range(9) if not board[i]]
    if not empty:
        return 0                # مساوی
    
    if is_my_turn:
        best = -100
        for i in empty:
            board[i] = my_mark
            best = max(best, _ttt_minimax(board, my_mark, opp_mark, False, depth + 1))
            board[i] = ""
        return best
    else:
        worst = 100
        for i in empty:
            board[i] = opp_mark
            worst = min(worst, _ttt_minimax(board, my_mark, opp_mark, True, depth + 1))
            board[i] = ""
        return worst

def ttt_bot_move(board, my_mark, opp_mark):
    """🤖 هوش کامل خر بات: Minimax — همه حالت‌ها رو می‌بینه، تله دو گوشه هم روش کار نمی‌کنه!"""
    empty = [i for i in range(9) if not board[i]]
    if not empty:
        return None
    # حرکت اول: مرکز یا گوشه (برای سرعت، بدون محاسبه)
    if len(empty) >= 8:
        return 4 if 4 in empty else random.choice([0, 2, 6, 8])
    
    b = board[:]
    best_score = -100
    best_moves = []
    for i in empty:
        b[i] = my_mark
        score = _ttt_minimax(b, my_mark, opp_mark, False, 1)
        b[i] = ""
        if score > best_score:
            best_score = score
            best_moves = [i]
        elif score == best_score:
            best_moves.append(i)
    return random.choice(best_moves)

async def ttt_begin(room, context):
    room.game_data = {"board": [""] * 9, "turn": 0}
    p1, p2 = room.players[0], room.players[1]
    await edit_room_msg(
        room, context,
        f"❌⭕ **دوز**\n━━━━━━━━━━━━━━\n"
        f"❌ {uname(p1)} 🆚 ⭕ {uname(p2)}\n"
        f"💰 جایزه: {room.pot()} {CURRENCY_NAME}\n\n"
        f"🎯 نوبت: ❌ {uname(p1)}",
        ttt_keyboard(room)
    )

async def ttt_check_end(room, context):
    """بررسی برد/مساوی — خروجی True یعنی بازی تمام شد"""
    gd = room.game_data
    p1, p2 = room.players[0], room.players[1]
    w = ttt_winner(gd["board"])
    if w:
        winner = p1 if w == "❌" else p2
        loser = p2 if winner == p1 else p1
        add_coins(winner, room.pot())
        record_win(winner)
        record_loss(loser)
        board_txt = "\n".join("".join(gd["board"][j] if gd["board"][j] else "⬜" for j in range(i, i+3)) for i in range(0, 9, 3))
        await finish_game(room, context,
            f"❌⭕ **دوز — پایان**\n━━━━━━━━━━━━━━\n{board_txt}\n\n"
            f"🏆 برنده: **{uname(winner)}** ({w})\n💰 جایزه: {room.pot()} {CURRENCY_NAME}")
        return True
    if all(gd["board"]):
        for p in room.players:
            add_coins(p, room.bet)
        await finish_game(room, context,
            f"❌⭕ **دوز — پایان**\n━━━━━━━━━━━━━━\n"
            f"🤝 مساوی شد! شرط هر دو نفر برگشت داده شد.")
        return True
    return False

async def ttt_show_turn(room, context):
    gd = room.game_data
    p1, p2 = room.players[0], room.players[1]
    nxt = room.players[gd["turn"]]
    mark = "❌" if nxt == p1 else "⭕"
    await edit_room_msg(
        room, context,
        f"❌⭕ **دوز**\n━━━━━━━━━━━━━━\n"
        f"❌ {uname(p1)} 🆚 ⭕ {uname(p2)}\n"
        f"💰 جایزه: {room.pot()} {CURRENCY_NAME}\n\n"
        f"🎯 نوبت: {mark} {uname(nxt)}",
        ttt_keyboard(room)
    )

async def ttt_action(room, context, query, cell):
    uid = query.from_user.id
    gd = room.game_data
    p1, p2 = room.players[0], room.players[1]
    current = room.players[gd["turn"]]
    
    if uid != current:
        await query.answer("⏳ نوبت تو نیست!", show_alert=True)
        return
    
    i = int(cell)
    if gd["board"][i]:
        await query.answer("❌ این خونه پره!", show_alert=True)
        return
    
    gd["board"][i] = "❌" if uid == p1 else "⭕"
    await query.answer()
    
    if await ttt_check_end(room, context):
        return
    
    gd["turn"] = 1 - gd["turn"]
    
    # 🤖 نوبت خر بات؟
    if room.players[gd["turn"]] == BOT_ID:
        my_mark = "❌" if BOT_ID == p1 else "⭕"
        opp_mark = "⭕" if my_mark == "❌" else "❌"
        await ttt_show_turn(room, context)
        await asyncio.sleep(1.2)  # مکث طبیعی
        if room.finished: return
        move = ttt_bot_move(gd["board"], my_mark, opp_mark)
        gd["board"][move] = my_mark
        if await ttt_check_end(room, context):
            return
        gd["turn"] = 1 - gd["turn"]
    
    await ttt_show_turn(room, context)

# ------------------------------------------------------------
# 🪙 شیر یا خط (۲ نفره)
# ------------------------------------------------------------

async def coinflip_run(room, context):
    p1, p2 = room.players[0], room.players[1]
    await edit_room_msg(room, context, f"🪙 سکه در حال چرخش... 🌀\n\n🦁 {uname(p1)} 🆚 {uname(p2)} 🌛")
    await asyncio.sleep(2)
    
    result = random.choice(["شیر", "خط"])
    winner = p1 if result == "شیر" else p2
    loser = p2 if winner == p1 else p1
    add_coins(winner, room.pot())
    record_win(winner)
    record_loss(loser)
    
    await finish_game(room, context,
        f"🪙 **شیر یا خط — نتیجه**\n━━━━━━━━━━━━━━\n"
        f"🦁 شیر: {uname(p1)}\n🌛 خط: {uname(p2)}\n\n"
        f"🪙 سکه افتاد: **{result}**!\n\n"
        f"🏆 برنده: **{uname(winner)}**\n💰 جایزه: {room.pot()} {CURRENCY_NAME}")

# ------------------------------------------------------------
# 🎲 تاس (۲ تا ۱۰ نفره)
# ------------------------------------------------------------

# نگاشت اتاق‌های تاس منتظر پرتاب: {chat_id: room_id}
DICE_WAITING = {}

# ------------------------------------------------------------
# 🎯🎳⚽ بازی‌های ایموجی (دارت، بولینگ، پنالتی) — مثل تاس
# ------------------------------------------------------------

EMOJI_OF_GAME = {"dice": "🎲", "darts": "🎯", "bowling": "🎳", "penalty": "⚽"}
GAME_OF_EMOJI = {v: k for k, v in EMOJI_OF_GAME.items()}
PENALTY_SHOTS = 3  # هر بازیکن ۳ ضربه

def emoji_status_text(room):
    gd = room.game_data
    emo = EMOJI_OF_GAME[room.game_type]
    lines = [f"{emo} **{GAME_NAMES[room.game_type]} — هر کی خودش می‌ندازه!**", "━━━━━━━━━━━━━━",
             f"💰 جایزه: {room.pot()} {CURRENCY_NAME}", ""]
    if room.game_type == "penalty":
        for p in room.players:
            shots = gd["shots"].get(p, [])
            goals = sum(1 for v in shots if v >= 3)
            done = "✅" if len(shots) >= PENALTY_SHOTS else "⏳"
            lines.append(f"{done} {uname(p)}: {len(shots)}/{PENALTY_SHOTS} ضربه — ⚽ {goals} گل")
        lines.append(f"\n👆 ایموجی ⚽ رو بفرست ({PENALTY_SHOTS} بار)!")
    else:
        for p in room.players:
            if p in gd["rolls"]:
                lines.append(f"✅ {uname(p)}: انداخت → **{gd['rolls'][p]}**")
            else:
                lines.append(f"⏳ {uname(p)}: منتظر پرتاب...")
        lines.append(f"\n👆 ایموجی {emo} رو از پنل ایموجی‌ها بفرست!")
    lines.append("⏰ ۲ دقیقه وقت دارید — نندازی، صفر حساب می‌شی!")
    return "\n".join(lines)

async def emoji_game_begin(room, context):
    """شروع بازی ایموجی: تاس/دارت/بولینگ (تک‌پرتاب) و پنالتی (۳ ضربه)"""
    if room.game_type == "penalty":
        room.game_data = {"shots": {}, "deadline": time.time() + 120}
        if BOT_ID in room.players:
            room.game_data["shots"][BOT_ID] = [random.randint(1, 5) for _ in range(PENALTY_SHOTS)]
    else:
        room.game_data = {"rolls": {}, "deadline": time.time() + 120}
        if BOT_ID in room.players:
            room.game_data["rolls"][BOT_ID] = random.randint(1, 6)
    DICE_WAITING[room.chat_id] = room.room_id
    await edit_room_msg(room, context, emoji_status_text(room))
    context.application.create_task(emoji_game_deadline_watch(room, context))

async def emoji_game_deadline_watch(room, context):
    try:
        await asyncio.sleep(120)
        if ACTIVE_ROOMS.get(room.room_id) is not room or room.finished:
            return
        await emoji_game_finish(room, context)
    except Exception as e:
        logger.warning(f"⚠️ خطا در تایمر بازی ایموجی: {e}")

async def emoji_game_finish(room, context):
    gd = room.game_data
    if DICE_WAITING.get(room.chat_id) == room.room_id:
        DICE_WAITING.pop(room.chat_id, None)
    emo = EMOJI_OF_GAME[room.game_type]
    
    if room.game_type == "penalty":
        scores = {}
        for p in room.players:
            shots = gd["shots"].get(p, [])
            scores[p] = sum(1 for v in shots if v >= 3)  # ⚽ مقدار ۳ به بالا = گل
        lines_detail = [f"{'🏆' if False else '▫️'}"]
    else:
        scores = {p: gd["rolls"].get(p, 0) for p in room.players}
    
    best = max(scores.values())
    if best == 0:
        for p in room.players:
            add_coins(p, room.bet)
        await finish_game(room, context,
            f"{emo} **{GAME_NAMES[room.game_type]} — لغو شد!**\n━━━━━━━━━━━━━━\n"
            "😴 هیچ‌کس بازی نکرد! شرط همه برگشت داده شد.")
        return
    
    winners = [p for p, v in scores.items() if v == best]
    lines = []
    for p, v in sorted(scores.items(), key=lambda x: -x[1]):
        mark = "🏆" if p in winners else "▫️"
        if room.game_type == "penalty":
            lines.append(f"{mark} {uname(p)}: ⚽ **{v}** گل از {PENALTY_SHOTS} ضربه")
        else:
            val = f"**{v}**" if v > 0 else "💤 ننداخت (صفر)"
            lines.append(f"{mark} {uname(p)}: {val}")
    
    share = room.pot() // len(winners)
    for w in winners:
        add_coins(w, share)
        record_win(w)
    for p in room.players:
        if p not in winners:
            record_loss(p)
    
    win_names = "، ".join(uname(w) for w in winners)
    result_note = "🤝 مساوی — تقسیم جایزه!\n" if len(winners) > 1 else ""
    await finish_game(room, context,
        f"{emo} **{GAME_NAMES[room.game_type]} — نتیجه**\n━━━━━━━━━━━━━━\n" + "\n".join(lines) +
        f"\n\n{result_note}🏆 برنده: **{win_names}**\n💰 جایزه هر نفر: {share} {CURRENCY_NAME}")

async def dice_roll_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🎲🎯🎳⚽ وقتی کسی ایموجی بازی می‌فرسته — عدد واقعی از تلگرام خونده می‌شه"""
    msg = update.message
    if not msg or not msg.dice or not update.effective_user:
        return
    game_of_emoji = GAME_OF_EMOJI.get(msg.dice.emoji)
    if not game_of_emoji:
        return
    # فوروارد قبول نیست! (تقلب)
    if getattr(msg, "forward_origin", None) or getattr(msg, "forward_date", None):
        return
    
    chat_id = update.effective_chat.id
    room_id = DICE_WAITING.get(chat_id)
    if not room_id:
        return
    room = ACTIVE_ROOMS.get(room_id)
    if not room or room.finished or room.game_type not in EMOJI_OF_GAME:
        DICE_WAITING.pop(chat_id, None)
        return
    # ایموجی باید با بازی همخونی داشته باشه (وسط بازی دارت، تاس نفرست!)
    if room.game_type != game_of_emoji:
        return
    
    uid = update.effective_user.id
    gd = room.game_data
    if uid not in room.players:
        return  # تماشاچی، مهم نیست
    
    room.last_action = time.time()
    
    if room.game_type == "penalty":
        shots = gd["shots"].setdefault(uid, [])
        if len(shots) >= PENALTY_SHOTS:
            try:
                await msg.reply_text(f"😅 هر {PENALTY_SHOTS} تا ضربه‌ات رو زدی!")
            except Exception:
                pass
            return
        shots.append(msg.dice.value)
        all_done = all(len(gd["shots"].get(p, [])) >= PENALTY_SHOTS for p in room.players)
        if all_done:
            await asyncio.sleep(3.5)
            if not room.finished:
                await emoji_game_finish(room, context)
        else:
            await edit_room_msg(room, context, emoji_status_text(room))
        return
    
    # تاس/دارت/بولینگ: تک پرتاب
    if uid in gd["rolls"]:
        try:
            await msg.reply_text("😅 قبلاً انداختی! همون اولی حسابه.")
        except Exception:
            pass
        return
    
    gd["rolls"][uid] = msg.dice.value
    
    if len(gd["rolls"]) == len(room.players):
        await asyncio.sleep(3.5)
        if not room.finished:
            await emoji_game_finish(room, context)
    else:
        await edit_room_msg(room, context, emoji_status_text(room))

# ------------------------------------------------------------
# 🔢 حدس عدد (۲ تا ۱۰ نفره) — عدد مخفی ۱ تا ۱۰۰
# ------------------------------------------------------------

GUESS_WAITING = {}  # {chat_id: room_id}

async def guessnum_begin(room, context):
    room.game_data = {"secret": random.randint(1, 100), "turn": 0, "history": [], "lo": 1, "hi": 100}
    GUESS_WAITING[room.chat_id] = room.room_id
    await edit_room_msg(room, context, guessnum_status(room))
    await guessnum_bot_turn(room, context)

def guessnum_status(room, extra=""):
    gd = room.game_data
    current = room.players[gd["turn"] % len(room.players)]
    hist = " | ".join(gd["history"][-6:]) if gd["history"] else "هنوز حدسی زده نشده"
    return (
        f"🔢 **حدس عدد (۱ تا ۱۰۰)**\n━━━━━━━━━━━━━━\n"
        f"💰 جایزه: {room.pot()} {CURRENCY_NAME}\n"
        f"🎯 بازه فعلی: **{gd['lo']} تا {gd['hi']}**\n"
        f"📜 حدس‌ها: {hist}\n"
        f"{extra}"
        f"\n👉 نوبت: **{uname(current)}** — عددت رو توی چت بنویس!"
    )

async def guessnum_bot_turn(room, context):
    """🤖 نوبت خر بات: حدس هوشمند وسط بازه"""
    gd = room.game_data
    while not room.finished and room.players[gd["turn"] % len(room.players)] == BOT_ID:
        await asyncio.sleep(1.5)
        if room.finished: return
        guess = (gd["lo"] + gd["hi"]) // 2
        done = await guessnum_process(room, context, BOT_ID, guess)
        if done: return

async def guessnum_process(room, context, uid, guess):
    """پردازش یک حدس — True یعنی بازی تمام شد"""
    gd = room.game_data
    secret = gd["secret"]
    room.last_action = time.time()
    
    if guess == secret:
        GUESS_WAITING.pop(room.chat_id, None)
        add_coins(uid, room.pot())
        record_win(uid)
        for p in room.players:
            if p != uid:
                record_loss(p)
        gd["history"].append(f"{guess}✅")
        await finish_game(room, context,
            f"🔢 **حدس عدد — پایان!**\n━━━━━━━━━━━━━━\n"
            f"🎉 عدد مخفی: **{secret}**\n"
            f"🏆 {uname(uid)} درست حدس زد و **{room.pot()}** {CURRENCY_NAME} برد!\n"
            f"📜 حدس‌ها: {' | '.join(gd['history'][-10:])}")
        return True
    
    if guess < secret:
        gd["lo"] = max(gd["lo"], guess + 1)
        gd["history"].append(f"{guess}⬆️")
        hint = f"⬆️ {uname(uid)} گفت {guess} — **بالاتره!**\n"
    else:
        gd["hi"] = min(gd["hi"], guess - 1)
        gd["history"].append(f"{guess}⬇️")
        hint = f"⬇️ {uname(uid)} گفت {guess} — **پایین‌تره!**\n"
    
    gd["turn"] += 1
    await edit_room_msg(room, context, guessnum_status(room, hint))
    await guessnum_bot_turn(room, context)
    return False

async def guessnum_text_received(update, context):
    """پردازش عدد نوشته‌شده توی چت برای بازی حدس عدد — خروجی True یعنی پیام مصرف شد"""
    chat_id = update.effective_chat.id
    room_id = GUESS_WAITING.get(chat_id)
    if not room_id:
        return False
    room = ACTIVE_ROOMS.get(room_id)
    if not room or room.finished or room.game_type != "guessnum":
        GUESS_WAITING.pop(chat_id, None)
        return False
    
    uid = update.effective_user.id
    if uid not in room.players:
        return False
    
    text = update.message.text.strip().translate(FA_DIGITS)
    if not text.isdigit():
        return False
    guess = int(text)
    if guess < 1 or guess > 100:
        return False
    
    gd = room.game_data
    current = room.players[gd["turn"] % len(room.players)]
    if uid != current:
        try:
            await update.message.reply_text(f"⏳ نوبت تو نیست! نوبت {uname(current)}ه.")
        except Exception:
            pass
        return True
    
    await guessnum_process(room, context, uid, guess)
    return True

# ------------------------------------------------------------
# 💣 مین‌روب (۲ تا ۱۰ نفره) — جعبه بمب‌دار رو باز نکن!
# ------------------------------------------------------------

MINES_BOXES = 9  # ۹ جعبه، هر راند یکیش بمبه

def mines_keyboard(room):
    gd = room.game_data
    rows = []
    for i in range(0, MINES_BOXES, 3):
        row = []
        for j in range(i, i + 3):
            if j in gd["opened"]:
                row.append(InlineKeyboardButton("✅", callback_data=gcb(room.room_id, f"mn_x{j}")))
            else:
                row.append(InlineKeyboardButton("📦", callback_data=gcb(room.room_id, f"mn_{j}")))
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def mines_status(room, extra=""):
    gd = room.game_data
    current = gd["alive"][gd["turn"] % len(gd["alive"])]
    alive_names = "، ".join(uname(p) for p in gd["alive"])
    return (
        f"💣 **مین‌روب — راند {gd['round']}**\n━━━━━━━━━━━━━━\n"
        f"💰 جایزه: {room.pot()} {CURRENCY_NAME}\n"
        f"❤️ زنده‌ها ({len(gd['alive'])}): {alive_names}\n"
        f"{extra}"
        f"\n📦 یکی از این جعبه‌ها **بمب** داره!\n"
        f"👉 نوبت: **{uname(current)}** — یه جعبه باز کن... 😰"
    )

def mines_new_round(room):
    gd = room.game_data
    gd["bomb"] = random.randint(0, MINES_BOXES - 1)
    gd["opened"] = set()

async def mines_begin(room, context):
    alive = room.players[:]
    random.shuffle(alive)
    room.game_data = {"alive": alive, "turn": 0, "round": 1}
    mines_new_round(room)
    await edit_room_msg(room, context, mines_status(room), mines_keyboard(room))
    await mines_bot_turn(room, context)

async def mines_bot_turn(room, context):
    gd = room.game_data
    while not room.finished and gd["alive"][gd["turn"] % len(gd["alive"])] == BOT_ID:
        await asyncio.sleep(1.5)
        if room.finished: return
        choices = [i for i in range(MINES_BOXES) if i not in gd["opened"]]
        if not choices: return
        done = await mines_open(room, context, BOT_ID, random.choice(choices))
        if done: return

async def mines_open(room, context, uid, box):
    """باز کردن جعبه — True یعنی بازی تمام شد"""
    gd = room.game_data
    room.last_action = time.time()
    
    if box == gd["bomb"]:
        # 💥 بمب! حذف بازیکن
        gd["alive"].remove(uid)
        if len(gd["alive"]) == 1:
            winner = gd["alive"][0]
            add_coins(winner, room.pot())
            record_win(winner)
            for p in room.players:
                if p != winner:
                    record_loss(p)
            await finish_game(room, context,
                f"💣 **مین‌روب — پایان!**\n━━━━━━━━━━━━━━\n"
                f"💥 **بوووم!** {uname(uid)} جعبه {box+1} رو باز کرد و منفجر شد! ☠️\n\n"
                f"🏆 آخرین بازمانده: **{uname(winner)}**\n"
                f"💰 جایزه: {room.pot()} {CURRENCY_NAME}")
            return True
        # راند جدید
        gd["round"] += 1
        gd["turn"] = gd["turn"] % len(gd["alive"])
        mines_new_round(room)
        extra = f"💥 **بوووم!** {uname(uid)} منفجر شد و حذف شد! ☠️\n🔄 بمب جدید کار گذاشته شد...\n"
        await edit_room_msg(room, context, mines_status(room, extra), mines_keyboard(room))
        await mines_bot_turn(room, context)
        return False
    
    # 📦 جعبه خالی
    gd["opened"].add(box)
    gd["turn"] += 1
    # اگه فقط جعبه بمب مونده → راند جدید (همه نجات پیدا کردن این راند)
    if len(gd["opened"]) >= MINES_BOXES - 1:
        gd["round"] += 1
        mines_new_round(room)
        extra = f"😮‍💨 {uname(uid)} جعبه {box+1} رو باز کرد — خالی بود!\n🍀 همه جعبه‌های امن باز شدن! راند جدید با بمب جدید...\n"
    else:
        extra = f"😮‍💨 {uname(uid)} جعبه {box+1} رو باز کرد — خالی بود!\n"
    await edit_room_msg(room, context, mines_status(room, extra), mines_keyboard(room))
    await mines_bot_turn(room, context)
    return False

async def mines_action(room, context, query, payload):
    gd = room.game_data
    uid = query.from_user.id
    
    if payload.startswith("x"):
        await query.answer("✅ این جعبه قبلاً باز شده!")
        return
    if uid not in gd["alive"]:
        await query.answer("☠️ تو حذف شدی! فقط تماشا کن!", show_alert=True)
        return
    current = gd["alive"][gd["turn"] % len(gd["alive"])]
    if uid != current:
        await query.answer("⏳ نوبت تو نیست!", show_alert=True)
        return
    
    box = int(payload)
    if box in gd["opened"]:
        await query.answer("✅ این جعبه قبلاً باز شده!")
        return
    
    await query.answer("😰 داری بازش می‌کنی...")
    await mines_open(room, context, uid, box)

# ------------------------------------------------------------
# 🔫 رولت روسی (۲ تا ۱۰ نفره)
# ------------------------------------------------------------

def roulette_keyboard(room):
    """دکمه انتخاب هدف: همه زنده‌ها به جز خود شلیک‌کننده"""
    gd = room.game_data
    shooter = gd["alive"][gd["turn"]]
    buttons = []
    row = []
    for p in gd["alive"]:
        if p == shooter:
            continue
        row.append(InlineKeyboardButton(f"🎯 {uname(p)}", callback_data=gcb(room.room_id, f"rr_{p}")))
        if len(row) == 2:
            buttons.append(row); row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def roulette_status(room, extra=""):
    gd = room.game_data
    shooter = gd["alive"][gd["turn"]]
    alive_names = "، ".join(uname(p) for p in gd["alive"])
    return (
        f"🔫 **رولت روسی — راند {gd['round']}**\n━━━━━━━━━━━━━━\n"
        f"❤️ زنده‌ها ({len(gd['alive'])}): {alive_names}\n"
        f"{extra}"
        f"\n🎯 نوبت شلیک: **{uname(shooter)}**\n"
        f"هفت‌تیر دستشه... به کی شلیک می‌کنه؟ 😰"
    )

async def roulette_begin(room, context):
    alive = room.players[:]
    random.shuffle(alive)
    room.game_data = {"alive": alive, "turn": 0, "round": 1}
    await edit_room_msg(room, context, roulette_status(room), roulette_keyboard(room))
    await roulette_bot_turn(room, context)

async def roulette_next_round(room, context, extra):
    """پایان راند: یک نفر حذف شد → راند جدید یا پایان بازی"""
    gd = room.game_data
    if len(gd["alive"]) == 1:
        winner = gd["alive"][0]
        add_coins(winner, room.pot())
        record_win(winner)
        for p in room.players:
            if p != winner:
                record_loss(p)
        await finish_game(room, context,
            f"🔫 **رولت روسی — پایان**\n━━━━━━━━━━━━━━\n"
            f"{extra}\n"
            f"🏆 آخرین بازمانده: **{uname(winner)}**\n"
            f"💰 جایزه: {room.pot()} {CURRENCY_NAME}")
        return True
    gd["round"] += 1
    gd["turn"] = gd["turn"] % len(gd["alive"])
    await edit_room_msg(room, context, roulette_status(room, extra + "\n"), roulette_keyboard(room))
    await roulette_bot_turn(room, context)
    return False

async def roulette_shoot(room, context, shooter, target):
    """شلیک: ۲ از ۶ احتمال گلوله. حذف = پایان راند"""
    gd = room.game_data
    room.last_action = time.time()
    await edit_room_msg(room, context,
        f"🔫 **رولت روسی — راند {gd['round']}**\n━━━━━━━━━━━━━━\n"
        f"😰 {uname(shooter)} هفت‌تیر رو گرفت سمت {uname(target)}...\n"
        f"🌀 چرخش استوانه...")
    await asyncio.sleep(2)
    if room.finished: return
    
    if random.randint(1, 6) <= 2:  # 💥 گلوله!
        gd["alive"].remove(target)
        extra = f"💥 **بنگ!** {uname(shooter)} زد و {uname(target)} حذف شد! ☠️\n"
        # راند تمام — نفر بعدی شروع‌کننده راند بعده
        await roulette_next_round(room, context, extra)
    else:
        # کلیک خالی → نوبت به نفر بعدی همین راند
        gd["turn"] = (gd["turn"] + 1) % len(gd["alive"])
        extra = f"😮‍💨 *کلیک...* پوکه خالی بود! {uname(target)} زنده موند!\n"
        await edit_room_msg(room, context, roulette_status(room, extra), roulette_keyboard(room))
        await roulette_bot_turn(room, context)

async def roulette_bot_turn(room, context):
    """🤖 اگه نوبت خر باته، خودش یه هدف تصادفی انتخاب می‌کنه"""
    gd = room.game_data
    while not room.finished and BOT_ID in gd["alive"] and gd["alive"][gd["turn"]] == BOT_ID:
        await asyncio.sleep(1.5)
        if room.finished: return
        targets = [p for p in gd["alive"] if p != BOT_ID]
        if not targets: return
        target = random.choice(targets)
        await roulette_shoot(room, context, BOT_ID, target)

async def roulette_action(room, context, query, target_str):
    gd = room.game_data
    uid = query.from_user.id
    shooter = gd["alive"][gd["turn"]]
    
    if uid not in gd["alive"]:
        await query.answer("☠️ تو حذف شدی! فقط تماشا کن!", show_alert=True)
        return
    if uid != shooter:
        await query.answer("⏳ نوبت تو نیست!", show_alert=True)
        return
    
    try:
        target = int(target_str)
    except ValueError:
        return
    if target not in gd["alive"] or target == uid:
        await query.answer("❌ هدف نامعتبره!", show_alert=True)
        return
    
    await query.answer("🔫 شلیک!")
    await roulette_shoot(room, context, uid, target)

# ------------------------------------------------------------
# 🎰 پوکر ۵ کارتی (۲ تا ۶ نفره)
# ------------------------------------------------------------

async def poker_run(room, context):
    await edit_room_msg(room, context, "🎰 در حال پخش کارت‌ها... 🃏")
    await asyncio.sleep(2)
    
    deck = new_deck()
    hands = {}
    for p in room.players:
        hands[p] = [deck.pop() for _ in range(5)]
    
    scores = {p: poker_eval(h) for p, h in hands.items()}
    best = max(scores.values())
    winners = [p for p in room.players if scores[p] == best]
    
    lines = []
    for p in sorted(room.players, key=lambda x: scores[x], reverse=True):
        mark = "🏆" if p in winners else "▫️"
        lines.append(f"{mark} {uname(p)}:\n   {hand_str(hands[p])}\n   {POKER_HAND_NAMES[scores[p][0]]}")
    
    share = room.pot() // len(winners)
    for w in winners:
        add_coins(w, share)
        record_win(w)
    for p in room.players:
        if p not in winners:
            record_loss(p)
    
    win_names = "، ".join(uname(w) for w in winners)
    await finish_game(room, context,
        f"🎰 **پوکر — نتیجه**\n━━━━━━━━━━━━━━\n" + "\n".join(lines) +
        f"\n\n🏆 برنده: **{win_names}**\n💰 جایزه هر نفر: {share} {CURRENCY_NAME}")

# ------------------------------------------------------------
# 🃏 بلک‌جک ۲۱ (۲ تا ۶ نفره — نوبتی)
# ------------------------------------------------------------

def bj_keyboard(room):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🎴 کارت بده", callback_data=gcb(room.room_id, "bj_hit")),
        InlineKeyboardButton("✋ کافیه", callback_data=gcb(room.room_id, "bj_stand"))
    ]])

def bj_status_text(room):
    gd = room.game_data
    lines = [f"🃏 **بلک‌جک ۲۱**", "━━━━━━━━━━━━━━",
             f"🎩 خونه: {card_str(gd['dealer'][0])} 🂠", ""]
    for i, p in enumerate(room.players):
        h = gd["hands"][p]
        v = bj_value(h)
        if i == gd["idx"] and not gd["done"].get(p):
            mark = "👉"
        elif gd["done"].get(p) == "bust":
            mark = "💥"
        elif gd["done"].get(p):
            mark = "✅"
        else:
            mark = "▫️"
        lines.append(f"{mark} {uname(p)}: {hand_str(h)} = **{v}**")
    current = room.players[gd["idx"]]
    lines.append(f"\n🎯 نوبت: **{uname(current)}**")
    return "\n".join(lines)

async def bj_begin(room, context):
    deck = new_deck()
    hands = {p: [deck.pop(), deck.pop()] for p in room.players}
    dealer = [deck.pop(), deck.pop()]
    room.game_data = {"deck": deck, "hands": hands, "dealer": dealer, "idx": 0, "done": {}}
    await bj_next_turn(room, context)

async def bj_bot_play(room, context):
    """🤖 خر بات مثل دیلر بازی می‌کنه: زیر ۱۷ کارت می‌گیره"""
    gd = room.game_data
    await asyncio.sleep(1.2)
    if room.finished: return
    while bj_value(gd["hands"][BOT_ID]) < 17:
        gd["hands"][BOT_ID].append(gd["deck"].pop())
    v = bj_value(gd["hands"][BOT_ID])
    gd["done"][BOT_ID] = "bust" if v > 21 else "stand"
    gd["idx"] += 1

async def bj_next_turn(room, context):
    gd = room.game_data
    while gd["idx"] < len(room.players):
        current = room.players[gd["idx"]]
        if gd["done"].get(current):
            gd["idx"] += 1
            continue
        if current == BOT_ID:
            await edit_room_msg(room, context, bj_status_text(room) + "\n🤖 خر بات داره فکر می‌کنه...", None)
            await bj_bot_play(room, context)
            if room.finished: return
            continue
        break
    
    if gd["idx"] >= len(room.players):
        await bj_dealer_and_finish(room, context)
        return
    await edit_room_msg(room, context, bj_status_text(room), bj_keyboard(room))

async def bj_dealer_and_finish(room, context):
    gd = room.game_data
    dealer = gd["dealer"]
    while bj_value(dealer) < 17:
        dealer.append(gd["deck"].pop())
    dv = bj_value(dealer)
    
    lines = [f"🃏 **بلک‌جک ۲۱ — نتیجه**", "━━━━━━━━━━━━━━",
             f"🎩 خونه: {hand_str(dealer)} = **{dv}**" + (" 💥" if dv > 21 else ""), ""]
    
    for p in room.players:
        h = gd["hands"][p]
        v = bj_value(h)
        if v > 21:
            res = "💀 باخت (سوخت)"
            record_loss(p)
        elif dv > 21 or v > dv:
            prize = room.bet * 2
            add_coins(p, prize)
            record_win(p)
            res = f"🏆 برد +{prize}"
        elif v == dv:
            add_coins(p, room.bet)
            res = "🤝 مساوی (برگشت شرط)"
        else:
            record_loss(p)
            res = "💀 باخت"
        lines.append(f"👤 {uname(p)}: {hand_str(h)} = {v} → {res}")
    
    await finish_game(room, context, "\n".join(lines))

async def bj_action(room, context, query, action):
    uid = query.from_user.id
    gd = room.game_data
    if gd["idx"] >= len(room.players):
        await query.answer()
        return
    current = room.players[gd["idx"]]
    if uid != current:
        await query.answer("⏳ نوبت تو نیست!", show_alert=True)
        return
    
    if action == "hit":
        gd["hands"][uid].append(gd["deck"].pop())
        v = bj_value(gd["hands"][uid])
        if v > 21:
            gd["done"][uid] = "bust"
            gd["idx"] += 1
            await query.answer(f"💥 سوختی! ({v})", show_alert=True)
            await bj_next_turn(room, context)
        elif v == 21:
            gd["done"][uid] = "stand"
            gd["idx"] += 1
            await query.answer("🎉 ۲۱! عالی!")
            await bj_next_turn(room, context)
        else:
            await query.answer(f"🎴 مجموع: {v}")
            await edit_room_msg(room, context, bj_status_text(room), bj_keyboard(room))
    else:  # stand
        gd["done"][uid] = "stand"
        gd["idx"] += 1
        await query.answer("✋ ایستادی")
        await bj_next_turn(room, context)

# ------------------------------------------------------------
# 💥 انفجار (۲ تا ۱۰ نفره)
# ------------------------------------------------------------

def crash_keyboard(room):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💸 برداشت!", callback_data=gcb(room.room_id, "crash_cash"))
    ]])

def crash_status_text(room):
    gd = room.game_data
    lines = [f"💥 **انفجار**", "━━━━━━━━━━━━━━",
             f"📈 ضریب: **x{gd['mult']:.2f}**", ""]
    for p in room.players:
        if p in gd["cashed"]:
            m = gd["cashed"][p]
            lines.append(f"✅ {uname(p)}: برداشت در x{m:.2f} (+{int(room.bet * m)})")
        else:
            lines.append(f"🚀 {uname(p)}: در پرواز...")
    lines.append("\n⚠️ قبل از انفجار برداشت کن!")
    return "\n".join(lines)

async def crash_begin(room, context):
    # نقطه انفجار: بین ۱ تا ~۱۲
    r = random.random()
    if r < 0.05:
        cp = 1.0  # انفجار فوری
    else:
        cp = min(12.0, round(0.9 / max(0.075, random.random()), 2))
        cp = max(1.1, cp)
    
    room.game_data = {"crash_point": cp, "mult": 1.0, "cashed": {}}
    # 🤖 خر بات یه هدف مخفی برای برداشت داره
    if BOT_ID in room.players:
        room.game_data["bot_target"] = round(random.uniform(1.3, 3.5), 2)
    await edit_room_msg(room, context,
        f"💥 **انفجار**\n━━━━━━━━━━━━━━\n🚀 موشک داره بلند می‌شه...\n📈 ضریب: **x1.00**\n\n⚠️ قبل از انفجار برداشت کن!",
        crash_keyboard(room))
    
    context.application.create_task(crash_loop(room, context))

async def crash_loop(room, context):
    gd = room.game_data
    try:
        while True:
            await asyncio.sleep(2)
            # اگر اتاق پاک شده، تمام
            if ACTIVE_ROOMS.get(room.room_id) is not room or room.finished:
                return
            
            gd["mult"] = round(gd["mult"] * random.uniform(1.12, 1.35), 2)
            room.last_action = time.time()  # ⚡ حلقه انفجار زنده‌ست
            
            # 🤖 برداشت خودکار خر بات وقتی به هدفش برسه
            if (BOT_ID in room.players and BOT_ID not in gd["cashed"]
                    and gd["mult"] >= gd.get("bot_target", 999) and gd["mult"] < gd["crash_point"]):
                gd["cashed"][BOT_ID] = gd["mult"]
            
            if gd["mult"] >= gd["crash_point"] or len(gd["cashed"]) == len(room.players):
                # 💥 انفجار یا همه برداشت کردند
                lines = [f"💥 **انفجار در x{gd['crash_point']:.2f}!**", "━━━━━━━━━━━━━━", ""]
                for p in room.players:
                    if p in gd["cashed"]:
                        m = gd["cashed"][p]
                        prize = int(room.bet * m)
                        lines.append(f"🏆 {uname(p)}: برداشت در x{m:.2f} → +{prize} {CURRENCY_NAME}")
                        record_win(p)
                    else:
                        lines.append(f"☠️ {uname(p)}: سوخت! -{room.bet} {CURRENCY_NAME}")
                        record_loss(p)
                await finish_game(room, context, "\n".join(lines))
                return
            
            await edit_room_msg(room, context, crash_status_text(room), crash_keyboard(room))
    except Exception as e:
        logger.error(f"❌ خطا در حلقه انفجار: {e}")
        # در صورت خطا، پول بازیکنانی که برداشت نکرده‌اند برگردد
        if ACTIVE_ROOMS.get(room.room_id) is room and not room.finished:
            for p in room.players:
                if p not in gd.get("cashed", {}):
                    add_coins(p, room.bet)
            cleanup_room(room.room_id)

async def crash_action(room, context, query):
    uid = query.from_user.id
    gd = room.game_data
    if uid not in room.players:
        await query.answer("❌ تو توی این بازی نیستی!", show_alert=True)
        return
    if uid in gd["cashed"]:
        await query.answer("✅ قبلاً برداشت کردی!", show_alert=True)
        return
    
    m = gd["mult"]
    gd["cashed"][uid] = m
    prize = int(room.bet * m)
    add_coins(uid, prize)
    await query.answer(f"💸 برداشت در x{m:.2f} → +{prize} {CURRENCY_NAME}", show_alert=True)

# ------------------------------------------------------------
# 🔼🔽 حدس بالا/پایین (۲ تا ۱۰ نفره)
# ------------------------------------------------------------

def hilo_keyboard(room):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔼 بالای ۷", callback_data=gcb(room.room_id, "hilo_hi")),
        InlineKeyboardButton("🎯 دقیقاً ۷", callback_data=gcb(room.room_id, "hilo_mid")),
        InlineKeyboardButton("🔽 پایین ۷", callback_data=gcb(room.room_id, "hilo_lo"))
    ]])

HILO_NAMES = {"hi": "🔼 بالای ۷", "mid": "🎯 دقیقاً ۷", "lo": "🔽 پایین ۷"}

async def hilo_begin(room, context):
    room.game_data = {"picks": {}}
    # 🤖 خر بات شانسی انتخاب می‌کنه (بیشتر بالا/پایین چون شانسش بهتره)
    if BOT_ID in room.players:
        room.game_data["picks"][BOT_ID] = random.choices(["hi", "lo", "mid"], weights=[42, 42, 16])[0]
    await edit_room_msg(room, context,
        f"🔼🔽 **حدس بالا/پایین**\n━━━━━━━━━━━━━━\n"
        f"🎲 دو تاس ریخته می‌شه. حدس بزن مجموع چی می‌شه:\n\n"
        f"🔼 بالای ۷ → جایزه x2\n"
        f"🎯 دقیقاً ۷ → جایزه x5\n"
        f"🔽 پایین ۷ → جایزه x2\n\n"
        f"⏳ انتخاب‌شده: 0/{len(room.players)}",
        hilo_keyboard(room))

async def hilo_action(room, context, query, pick):
    uid = query.from_user.id
    gd = room.game_data
    if uid not in room.players:
        await query.answer("❌ تو توی این بازی نیستی!", show_alert=True)
        return
    if uid in gd["picks"]:
        await query.answer("✅ قبلاً انتخاب کردی!", show_alert=True)
        return
    
    gd["picks"][uid] = pick
    await query.answer(f"انتخاب شد: {HILO_NAMES[pick]}")
    
    if len(gd["picks"]) < len(room.players):
        await edit_room_msg(room, context,
            f"🔼🔽 **حدس بالا/پایین**\n━━━━━━━━━━━━━━\n"
            f"🎲 دو تاس ریخته می‌شه. حدس بزن مجموع چی می‌شه:\n\n"
            f"🔼 بالای ۷ → جایزه x2\n"
            f"🎯 دقیقاً ۷ → جایزه x5\n"
            f"🔽 پایین ۷ → جایزه x2\n\n"
            f"⏳ انتخاب‌شده: {len(gd['picks'])}/{len(room.players)}",
            hilo_keyboard(room))
        return
    
    # همه انتخاب کردند → تاس!
    d1, d2 = random.randint(1, 6), random.randint(1, 6)
    total = d1 + d2
    if total > 7: outcome = "hi"
    elif total == 7: outcome = "mid"
    else: outcome = "lo"
    
    dice_emoji = ["", "⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]
    lines = [f"🔼🔽 **حدس بالا/پایین — نتیجه**", "━━━━━━━━━━━━━━",
             f"🎲 تاس‌ها: {dice_emoji[d1]}{dice_emoji[d2]} = **{total}** ({HILO_NAMES[outcome]})", ""]
    
    for p in room.players:
        pick = gd["picks"][p]
        if pick == outcome:
            mult = 5 if pick == "mid" else 2
            prize = room.bet * mult
            add_coins(p, prize)
            record_win(p)
            lines.append(f"🏆 {uname(p)}: {HILO_NAMES[pick]} → +{prize} {CURRENCY_NAME}")
        else:
            record_loss(p)
            lines.append(f"💀 {uname(p)}: {HILO_NAMES[pick]} → -{room.bet} {CURRENCY_NAME}")
    
    await finish_game(room, context, "\n".join(lines))

# ------------------------------------------------------------
# روتر اکشن‌های داخل بازی
# ------------------------------------------------------------

async def game_action_router(update, context, query, data):
    parts = data.split("|")
    if len(parts) < 3:
        return
    room_id, payload = parts[1], parts[2]
    room = get_room(room_id)
    if not room or not room.started or room.finished:
        await query.answer("❌ این بازی تمام شده!", show_alert=True)
        return
    
    uid = query.from_user.id
    if uid not in room.players:
        await query.answer("❌ تو توی این بازی نیستی!", show_alert=True)
        return
    
    room.last_action = time.time()  # ⚡ ضد گیر: ثبت آخرین حرکت
    
    try:
        if payload.startswith("rps_"):
            await rps_action(room, context, query, payload[4:])
        elif payload.startswith("ttt_"):
            await ttt_action(room, context, query, payload[4:])
        elif payload.startswith("bj_"):
            await bj_action(room, context, query, payload[3:])
        elif payload == "crash_cash":
            await crash_action(room, context, query)
        elif payload.startswith("hilo_"):
            await hilo_action(room, context, query, payload[5:])
        elif payload.startswith("rr_"):
            await roulette_action(room, context, query, payload[3:])
        elif payload.startswith("mn_"):
            await mines_action(room, context, query, payload[3:])
    except Exception as e:
        # 🛡️ خطای وسط بازی نباید بازی رو برای همیشه قفل کنه
        logger.error(f"❌ خطا وسط بازی {room.game_type} ({room.room_id}): {e}")
        if ACTIVE_ROOMS.get(room.room_id) is room and not room.finished:
            refund_room(room)
            room.finished = True
            cleanup_room(room.room_id)
            try:
                await edit_room_msg(room, context,
                    "⚠️ **بازی به دلیل خطا لغو شد!**\n💰 شرط همه بازیکنان برگشت داده شد.",
                    result_keyboard())
            except Exception:
                pass

# ============================================================
# بازی‌های قمار تکی (فوری — بدون اتاق)
# ============================================================

SLOT_SYMBOLS = ["🍒", "🍋", "🍇", "🔔", "💎", "7️⃣"]

async def slot_game(update, context, bet):
    user = update.effective_user
    if not remove_coins(user.id, bet):
        u = get_user(user.id)
        await update.message.reply_text(f"❌ پول کافی نداری! موجودی: {u['coins']:,} {CURRENCY_NAME}")
        return
    
    reels = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
    line = " | ".join(reels)
    
    if reels[0] == reels[1] == reels[2]:
        if reels[0] == "7️⃣": mult = 20
        elif reels[0] == "💎": mult = 10
        else: mult = 6
        prize = bet * mult
        add_coins(user.id, prize)
        record_win(user.id)
        result = f"🎰 **جکپات!** سه‌تایی {reels[0]}\n💰 بردی: **+{prize}** {CURRENCY_NAME} (x{mult})"
    elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        prize = bet * 2
        add_coins(user.id, prize)
        record_win(user.id)
        result = f"✨ دوتایی! 💰 بردی: **+{prize}** {CURRENCY_NAME} (x2)"
    else:
        record_loss(user.id)
        result = f"💀 باختی! **-{bet}** {CURRENCY_NAME}"
    
    await update.message.reply_text(
        f"🎰 **اسلات خرستان**\n━━━━━━━━━━━━━━\n"
        f"〘 {line} 〙\n\n"
        f"👤 {esc_md(user.first_name)}\n{result}",
        parse_mode="Markdown"
    )

async def double_game(update, context, bet):
    user = update.effective_user
    if not remove_coins(user.id, bet):
        u = get_user(user.id)
        await update.message.reply_text(f"❌ پول کافی نداری! موجودی: {u['coins']:,} {CURRENCY_NAME}")
        return
    
    if random.random() < 0.5:
        prize = bet * 2
        add_coins(user.id, prize)
        record_win(user.id)
        result = f"🎉 **دوبل شد!** بردی: **+{prize}** {CURRENCY_NAME}"
    else:
        record_loss(user.id)
        result = f"💀 سوخت! باختی: **-{bet}** {CURRENCY_NAME}"
    
    await update.message.reply_text(
        f"🎲 **دوبل یا هیچی**\n━━━━━━━━━━━━━━\n"
        f"👤 {esc_md(user.first_name)}\n💰 شرط: {bet} {CURRENCY_NAME}\n\n{result}",
        parse_mode="Markdown"
    )

def parse_bet_arg(parts):
    """استخراج مبلغ شرط از دستور متنی مثل «اسلات 100»"""
    if len(parts) < 2:
        return None
    val = parts[1].translate(FA_DIGITS)
    if not val.isdigit():
        return None
    bet = int(val)
    if bet < MIN_BET:
        return None
    return bet

async def start_room_from_text(update, context, game_type, bet):
    """ساخت اتاق بازی مستقیم با دستور فارسی مثل «انفجار 100»"""
    user = update.effective_user
    
    if player_active_room(user.id):
        await update.message.reply_text("⚠️ شما در یک بازی دیگر هستید! اول اون رو تموم کن.")
        return
    
    u = get_user(user.id)
    if u["coins"] < bet:
        await update.message.reply_text(f"❌ پول کافی نداری! موجودی: {u['coins']:,} {CURRENCY_NAME}")
        return
    
    remove_coins(user.id, bet)
    room = create_room(update.effective_chat.id, game_type, user.id, bet)
    
    two_p = "👥 بازی ۲ نفره" if game_type in TWO_PLAYER_GAMES else f"👥 ۲ تا {GAME_MAX_PLAYERS[game_type]} نفره"
    msg_text = (
        f"🎮 **{GAME_NAMES[game_type]}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 شرط: {bet} {CURRENCY_NAME}\n"
        f"{two_p}\n"
        f"👤 سازنده: {esc_md(user.first_name)}\n"
        f"\n🔄 منتظر ورود بازیکنان دیگر..."
    )
    
    sent_msg = await update.message.reply_text(
        msg_text,
        reply_markup=room_control_keyboard(room),
        parse_mode="Markdown"
    )
    room.message_id = sent_msg.message_id
    context.application.create_task(room_timeout_watch(room, context))

# ============================================================
# کادوهای مالک
# ============================================================

OWNER_GIFTS = {
    "گل": {"emoji": "🌹", "coins": 100},
    "شکلات": {"emoji": "🍫", "coins": 250},
    "کیک": {"emoji": "🎂", "coins": 500},
    "خرس": {"emoji": "🧸", "coins": 1000},
    "گردنبند": {"emoji": "📿", "coins": 2500},
    "الماس": {"emoji": "💎", "coins": 5000},
    "ماشین": {"emoji": "🚗", "coins": 10000},
    "خونه": {"emoji": "🏠", "coins": 25000}
}

# ============================================================
# 👑 پنل مخصوص اونر
# ============================================================

def owner_panel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 دیتابیس بازیکنان", callback_data="panel_players_0")],
        [InlineKeyboardButton("📊 آمار کلی ربات", callback_data="panel_stats")],
        [InlineKeyboardButton("💾 بکاپ دیتابیس", callback_data="panel_backup"),
         InlineKeyboardButton("📥 بازیابی", callback_data="panel_restore_help")],
        [InlineKeyboardButton("💰 مدیریت سکه", callback_data="panel_cmd_coins"),
         InlineKeyboardButton("🎁 کادو دادن", callback_data="panel_cmd_gifts")],
        [InlineKeyboardButton("🎊 دستورات همگانی", callback_data="panel_cmd_mass")],
        [InlineKeyboardButton("🚫 بن و آنبن", callback_data="panel_cmd_ban"),
         InlineKeyboardButton("📖 همه دستورات", callback_data="panel_cmd_all")]
    ])

def panel_back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="panel_main")]])

# 📚 بخش‌های آموزشی پنل اونر
PANEL_GUIDES = {
    "panel_cmd_coins": (
        "💰 **مدیریت سکه — آموزش کامل**\n"
        "━━━━━━━━━━━━━━\n"
        "**➕ سکه دادن به یک کاربر:**\n"
        "1️⃣ برو توی گروه، پیام اون کاربر رو پیدا کن\n"
        "2️⃣ روی پیامش **ریپلی (Reply)** بزن\n"
        "3️⃣ بنویس: `+سکه 1000`\n"
        "✅ همون لحظه ۱۰۰۰ تی‌تاپ بهش اضافه می‌شه\n\n"
        "**➖ کم کردن سکه از کاربر:**\n"
        "1️⃣ روی پیامش ریپلی بزن\n"
        "2️⃣ بنویس: `-سکه 500`\n"
        "✅ ۵۰۰ تی‌تاپ ازش کم می‌شه (منفی نمی‌شه، حداقل صفر)\n\n"
        "**💸 انتقال از جیب خودت:**\n"
        "ریپلی + `انتقال 100` — مثل بقیه کاربرا از موجودی خودت کم می‌شه\n\n"
        "💡 عدد فارسی هم قبوله: `+سکه ۱۰۰۰`"
    ),
    "panel_cmd_gifts": (
        "🎁 **کادو دادن — آموزش کامل**\n"
        "━━━━━━━━━━━━━━\n"
        "کادو یه پیام تبریک خوشگل توی گروه می‌فرسته و ارزشش به سکه اضافه می‌شه — از جیب تو کم نمی‌شه!\n\n"
        "**روش استفاده:**\n"
        "1️⃣ روی پیام کاربر **ریپلی** بزن\n"
        "2️⃣ بنویس: `کادو گل`\n"
        "✅ پیام تبریک + سکه به حسابش\n\n"
        "**🎁 لیست کادوها و ارزش‌شون:**\n"
        "🌹 `کادو گل` — 100\n"
        "🍫 `کادو شکلات` — 250\n"
        "🎂 `کادو کیک` — 500\n"
        "🧸 `کادو خرس` — 1,000\n"
        "📿 `کادو گردنبند` — 2,500\n"
        "💎 `کادو الماس` — 5,000\n"
        "🚗 `کادو ماشین` — 10,000\n"
        "🏠 `کادو خونه` — 25,000\n\n"
        "💡 اگه اسم کادو رو اشتباه بنویسی، ربات خودش لیست رو نشونت می‌ده."
    ),
    "panel_cmd_ban": (
        "🚫 **بن و آنبن — آموزش کامل**\n"
        "━━━━━━━━━━━━━━\n"
        "کاربر بن‌شده نمی‌تونه از هیچ قابلیت ربات استفاده کنه (بازی، عرعر، جایزه، هیچی!)\n\n"
        "**🚫 بن کردن:**\n"
        "1️⃣ روی پیام کاربر خاطی **ریپلی** بزن\n"
        "2️⃣ بنویس: `بن`\n"
        "✅ تمام! دیگه ربات جوابش رو نمی‌ده\n\n"
        "**✅ آنبن کردن:**\n"
        "1️⃣ روی پیامش ریپلی بزن\n"
        "2️⃣ بنویس: `انبن`\n"
        "✅ دوباره می‌تونه بازی کنه\n\n"
        "💡 لیست بن‌شده‌ها رو می‌تونی از «👥 دیتابیس بازیکنان» ببینی — کنار اسمشون 🚫بن نوشته شده."
    ),
    "panel_cmd_mass": (
        "🎊 **دستورات همگانی — آموزش کامل**\n"
        "━━━━━━━━━━━━━━\n"
        "**💰 سکه دادن به همه بازیکنان:**\n"
        "بنویس: `سکه‌همگانی 500`\n"
        "✅ به تک‌تک بازیکنان ثبت‌شده ۵۰۰ سکه اضافه می‌شه\n"
        "💡 مناسب جشن، مناسبت یا عذرخواهی بابت قطعی! 😄\n"
        "⚠️ حداکثر ۱٬۰۰۰٬۰۰۰ در هر بار\n\n"
        "**📢 پیام همگانی به همه چت‌ها:**\n"
        "بنویس: `اطلاعیه سلام! آپدیت جدید اومد 🎉`\n"
        "✅ پیامت با سربرگ «اطلاعیه طویله خرستان» به همه گروه‌ها و پی‌وی‌هایی که ربات توشون فعاله فرستاده می‌شه\n"
        "📊 آخرش گزارش می‌گیری: چند تا موفق، چند تا ناموفق\n"
        "🧹 چت‌هایی که ربات ازشون حذف شده خودکار از لیست پاک می‌شن\n\n"
        "⏱️ ارسال با فاصله انجام می‌شه که تلگرام ربات رو محدود نکنه."
    ),
    "panel_cmd_all": (
        "📖 **همه دستورات اونر — یکجا**\n"
        "━━━━━━━━━━━━━━\n"
        "**🎛️ پنل و دیتابیس:**\n"
        "`پنل` — باز کردن همین پنل\n"
        "`بکاپ` — دریافت فایل بکاپ دیتابیس\n"
        "ارسال فایل بکاپ با کپشن `بازیابی` — برگردوندن دیتا\n\n"
        "**🎊 همگانی:**\n"
        "`سکه‌همگانی 500` — سکه به همه بازیکنان\n"
        "`اطلاعیه متن پیام` — پیام به همه گروه‌ها و پی‌وی‌ها\n\n"
        "**👤 مدیریت کاربر (همه با ریپلی):**\n"
        "`+سکه 1000` — اضافه کردن سکه\n"
        "`-سکه 500` — کم کردن سکه\n"
        "`کادو گل` — کادو دادن (۸ نوع کادو)\n"
        "`بن` — مسدود کردن کاربر\n"
        "`انبن` — رفع مسدودی\n\n"
        "**⚠️ نکات مهم:**\n"
        "• همه این دستورات فقط برای تو کار می‌کنن (OWNER_ID)\n"
        "• کاربر عادی حتی نمی‌فهمه پنل وجود داره\n"
        "• دیتابیس توی /tmp هست → بعد از هر ری‌استارت سرور، فایل بکاپ رو با کپشن «بازیابی» بفرست\n"
        "• هر شب یه `بکاپ` بگیر و توی Saved Messages نگه دار 💾"
    )
}

PANEL_PAGE_SIZE = 10

def panel_players_text(page):
    with closing(db_connect()) as db:
        total = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        rows = db.execute(
            "SELECT u.*, d.equipped_hat, d.equipped_saddle, d.equipped_horseshoe, "
            "d.equipped_tie, d.equipped_clothes, d.equipped_accessory "
            "FROM users u LEFT JOIN donkeys d ON u.user_id = d.user_id "
            "ORDER BY u.coins DESC LIMIT ? OFFSET ?",
            (PANEL_PAGE_SIZE, page * PANEL_PAGE_SIZE)
        ).fetchall()
    
    if not rows:
        return "❌ بازیکنی در این صفحه نیست.", 0
    
    lines = [f"👑 **دیتابیس بازیکنان** (صفحه {page+1})",
             f"👥 کل بازیکنان: {total}", "━━━━━━━━━━━━━━"]
    for r in rows:
        items = []
        for col, emo in [("equipped_hat","🎩"),("equipped_saddle","🐴"),("equipped_horseshoe","👟"),
                          ("equipped_tie","👔"),("equipped_clothes","👕"),("equipped_accessory","🎀")]:
            try:
                if r[col]: items.append(f"{emo}{r[col]}")
            except (KeyError, IndexError):
                pass
        items_str = " | ".join(items) if items else "—"
        ban = " 🚫بن" if r["is_banned"] else ""
        lines.append(
            f"👤 {esc_md(r['name'])} (`{r['user_id']}`){ban}\n"
            f"   💰 {r['coins']:,} | ⭐ س{r['level']} | 🏆 {r['wins']}/{r['losses']} | 👶 {r['babies']}\n"
            f"   🎒 {items_str}"
        )
    return "\n".join(lines), total

def panel_players_keyboard(page, total):
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"panel_players_{page-1}"))
    if (page + 1) * PANEL_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"panel_players_{page+1}"))
    rows = []
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("🔙 پنل", callback_data="panel_main")])
    return InlineKeyboardMarkup(rows)

def export_db_json():
    """خروجی کامل دیتابیس به JSON برای بکاپ"""
    with closing(db_connect()) as db:
        users = [dict(r) for r in db.execute("SELECT * FROM users").fetchall()]
        donkeys = [dict(r) for r in db.execute("SELECT * FROM donkeys").fetchall()]
        chats = [dict(r) for r in db.execute("SELECT * FROM chats").fetchall()]
        settings = [dict(r) for r in db.execute("SELECT * FROM settings").fetchall()]
    return {
        "version": 1,
        "exported_at": int(time.time()),
        "users": users,
        "donkeys": donkeys,
        "chats": chats,
        "settings": settings
    }

def import_db_json(data):
    """وارد کردن بکاپ JSON به دیتابیس — کاربران موجود آپدیت می‌شوند"""
    if not isinstance(data, dict) or "users" not in data:
        raise ValueError("فرمت بکاپ نامعتبر است")
    
    users = data.get("users", [])
    donkeys = data.get("donkeys", [])
    
    user_cols = ["user_id","name","coins","level","wins","losses","is_banned","created_at",
                 "last_mate","babies","baby_names","last_sound","last_daily",
                 "last_work","last_wheel","last_rob","last_fortune","sound_count"]
    donkey_cols = ["user_id","equipped_hat","equipped_saddle","equipped_horseshoe",
                   "equipped_tie","equipped_clothes","equipped_accessory"]
    
    count = 0
    with closing(db_connect()) as db:
        for u in users:
            if "user_id" not in u: continue
            vals = [u.get(c, 0 if c != "name" and c != "baby_names" else ("کاربر" if c == "name" else "[]")) for c in user_cols]
            placeholders = ",".join("?" * len(user_cols))
            db.execute(f"INSERT OR REPLACE INTO users ({','.join(user_cols)}) VALUES ({placeholders})", vals)
            count += 1
        for d in donkeys:
            if "user_id" not in d: continue
            vals = [d.get(c, "" if c != "user_id" else 0) for c in donkey_cols]
            placeholders = ",".join("?" * len(donkey_cols))
            db.execute(f"INSERT OR REPLACE INTO donkeys ({','.join(donkey_cols)}) VALUES ({placeholders})", vals)
        # 💬 چت‌ها هم برگردن (برای پیام همگانی)
        for ch in data.get("chats", []):
            if "chat_id" not in ch: continue
            db.execute(
                "INSERT OR REPLACE INTO chats (chat_id, chat_type, title, last_seen) VALUES (?, ?, ?, ?)",
                (ch["chat_id"], ch.get("chat_type", ""), ch.get("title", ""), ch.get("last_seen", 0)))
        # ⚙️ تنظیمات (جوین اجباری و ...) هم برگردن
        for st in data.get("settings", []):
            if "key" not in st: continue
            db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                      (st["key"], st.get("value", "")))
        db.commit()
    return count

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📥 بازیابی بکاپ: اونر فایل JSON بکاپ رو با کپشن «بازیابی» بفرسته"""
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != OWNER_ID:
        return
    
    caption = (update.message.caption or "").strip()
    if caption not in ["بازیابی", "restore", "ریستور"]:
        return
    
    doc = update.message.document
    if not doc:
        return
    if doc.file_size and doc.file_size > 20 * 1024 * 1024:
        await update.message.reply_text("❌ فایل خیلی بزرگه! (حداکثر ۲۰ مگابایت)")
        return
    
    try:
        tg_file = await doc.get_file()
        raw = await tg_file.download_as_bytearray()
        data = json.loads(bytes(raw).decode("utf-8"))
        count = import_db_json(data)
        await update.message.reply_text(
            f"✅ **بازیابی موفق!**\n"
            f"👥 {count} بازیکن به دیتابیس برگردانده شد.\n"
            f"🎒 وسایل و مشخصات همه برگشت داده شد.",
            parse_mode="Markdown"
        )
        logger.info(f"✅ بکاپ بازیابی شد: {count} کاربر")
    except json.JSONDecodeError:
        await update.message.reply_text("❌ فایل JSON معتبر نیست!")
    except Exception as e:
        logger.error(f"❌ خطا در بازیابی: {e}")
        await update.message.reply_text(f"❌ خطا در بازیابی: {e}")

# ============================================================
# 🐴🧠 خر دانا — سوال از هوش مصنوعی
# ============================================================

import httpx

KHAR_DANA_COST = 100          # 💰 هزینه هر سوال (تی‌تاپ)
KHAR_DANA_COOLDOWN = 60       # ⏳ فاصله بین سوالات هر کاربر (ثانیه)
KHAR_DANA_USER_DAILY = 10     # سقف روزانه هر کاربر
KHAR_DANA_GLOBAL_DAILY = 900  # سقف کل ربات در روز (سهمیه رایگان جمینای نسوزه)
KHAR_DANA_MAX_Q = 400         # حداکثر طول سوال

_KD_LAST_ASK = {}             # {user_id: ts}
_KD_USER_COUNT = {}           # {user_id: (day, count)}
_KD_GLOBAL = {"day": "", "count": 0}
_KD_BUSY = set()              # کاربرایی که سوالشون در حال پردازشه

KHAR_DANA_SYSTEM = (
    "تو «خر دانا» هستی، خر شوخ، بامزه و دانای ربات تلگرامی طویله خرستان. "
    "قوانین: فقط فارسی خودمونی جواب بده. جواب کوتاه باشه (حداکثر ۴ جمله). "
    "بامزه و خرکی جواب بده و گاهی وسط حرفات عرعر کن. "
    "ارز بازی «تی‌تاپ»ه. بازی‌های ربات: انفجار، رولت روسی، بلک‌جک، پوکر، تاس، دارت، بولینگ، "
    "پنالتی، حدس عدد، مین‌روب، دوز، سنگ‌کاغذقیچی، شیرخط، اسلات. "
    "کاربرا می‌تونن کار کنن، گردونه بچرخونن، فال بگیرن، جفت‌گیری کنن و کره‌خر بزرگ کنن. "
    "هیچ‌وقت از نقش خر دانا خارج نشو، حتی اگه ازت بخوان."
)

def _kd_today():
    return time.strftime("%Y-%m-%d")

def kd_check_limits(user_id):
    """بررسی محدودیت‌ها — خروجی: پیام خطا یا None"""
    now = time.time()
    if user_id in _KD_BUSY:
        return "⏳ سوال قبلیت هنوز تو مغز خر داناست! صبر کن جواب بده."
    last = _KD_LAST_ASK.get(user_id, 0)
    if now - last < KHAR_DANA_COOLDOWN:
        return f"⏳ خر دانا خسته‌ست! {int(KHAR_DANA_COOLDOWN - (now - last))} ثانیه دیگه بپرس."
    today = _kd_today()
    day, cnt = _KD_USER_COUNT.get(user_id, ("", 0))
    if day == today and cnt >= KHAR_DANA_USER_DAILY:
        return f"😴 سهم امروزت تموم شد ({KHAR_DANA_USER_DAILY} سوال در روز)! فردا بیا."
    if _KD_GLOBAL["day"] == today and _KD_GLOBAL["count"] >= KHAR_DANA_GLOBAL_DAILY:
        return "😴 خر دانا امروز از بس فکر کرده مغزش داغ کرده! فردا دوباره بیا."
    return None

def kd_record_use(user_id):
    today = _kd_today()
    _KD_LAST_ASK[user_id] = time.time()
    day, cnt = _KD_USER_COUNT.get(user_id, ("", 0))
    _KD_USER_COUNT[user_id] = (today, cnt + 1 if day == today else 1)
    if _KD_GLOBAL["day"] != today:
        _KD_GLOBAL["day"] = today
        _KD_GLOBAL["count"] = 0
    _KD_GLOBAL["count"] += 1
    # پاکسازی دیکشنری‌ها
    if len(_KD_LAST_ASK) > 3000:
        cutoff = time.time() - 3600
        for k in [k for k, v in _KD_LAST_ASK.items() if v < cutoff][:1000]:
            _KD_LAST_ASK.pop(k, None)
            _KD_USER_COUNT.pop(k, None)

async def kd_ask_ai(question):
    """ارسال سوال به Gemini — خروجی: متن جواب یا None"""
    url = f"{AI_BASE_URL}/models/{AI_MODEL}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": KHAR_DANA_SYSTEM}]},
        "contents": [{"parts": [{"text": question}]}],
        "generationConfig": {"maxOutputTokens": 2000}
    }
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(url, json=payload, headers={
            "Content-Type": "application/json",
            "X-goog-api-key": AI_API_KEY
        })
    data = resp.json()
    if "candidates" in data and data["candidates"]:
        parts = data["candidates"][0].get("content", {}).get("parts", [])
        text = " ".join(p.get("text", "") for p in parts).strip()
        return text or None
    err = data.get("error", {}).get("message", "?")
    logger.warning(f"⚠️ خر دانا: خطای API: {err[:150]}")
    return None

async def khar_dana_command(update, context, question):
    user = update.effective_user
    
    if not AI_API_KEY:
        if user.id == OWNER_ID:
            await update.message.reply_text("❌ متغیر AI_API_KEY روی سرور تنظیم نشده!")
        return
    
    question = question.strip()
    if not question:
        await update.message.reply_text(
            f"🐴🧠 **خر دانا** — هر چی می‌خوای بپرس!\n"
            f"مثال: `خر جان امروز شانس دارم؟`\n\n"
            f"💰 هزینه هر سوال: {KHAR_DANA_COST} {CURRENCY_NAME}\n"
            f"📊 سقف: {KHAR_DANA_USER_DAILY} سوال در روز",
            parse_mode="Markdown")
        return
    if len(question) > KHAR_DANA_MAX_Q:
        await update.message.reply_text(f"❌ سوالت خیلی درازه! (حداکثر {KHAR_DANA_MAX_Q} حرف) خلاصه‌ش کن 🐴")
        return
    
    err = kd_check_limits(user.id)
    if err:
        await update.message.reply_text(err)
        return
    
    # 💰 هزینه
    if not remove_coins(user.id, KHAR_DANA_COST):
        u = get_user(user.id)
        await update.message.reply_text(
            f"❌ سوال از خر دانا {KHAR_DANA_COST} {CURRENCY_NAME} خرج داره!\n💳 موجودیت: {u['coins']:,}")
        return
    
    kd_record_use(user.id)
    _KD_BUSY.add(user.id)
    thinking = None
    try:
        thinking = await update.message.reply_text("🐴💭 خر دانا داره فکر می‌کنه... (عر... عر...)")
        answer = await kd_ask_ai(question)
        if answer:
            out = (f"🐴🧠 **خر دانا می‌گه:**\n━━━━━━━━━━━━━━\n{esc_md(answer)}\n\n"
                   f"💸 {KHAR_DANA_COST} {CURRENCY_NAME} | 👤 {esc_md(user.first_name)}")
            try:
                await thinking.edit_text(out, parse_mode="Markdown")
            except Exception:
                await thinking.edit_text(f"🐴🧠 خر دانا می‌گه:\n{answer}")
        else:
            # خطا → پول برگرده
            add_coins(user.id, KHAR_DANA_COST)
            await thinking.edit_text("😵 خر دانا الان مغزش هنگ کرد! پولت برگشت، چند دقیقه دیگه امتحان کن.")
    except Exception as e:
        logger.error(f"❌ خطای خر دانا: {e}")
        add_coins(user.id, KHAR_DANA_COST)
        try:
            if thinking:
                await thinking.edit_text("😵 خر دانا الان در دسترس نیست! پولت برگشت.")
        except Exception:
            pass
    finally:
        _KD_BUSY.discard(user.id)

# ============================================================
# 📤 موتور ارسال همگانی (متن/فوروارد/کپی)
# ============================================================

async def do_broadcast(update, context, send_fn):
    """ارسال به همه چت‌ها با گزارش و پاکسازی چت‌های مرده — send_fn(chat_id) پیام رو می‌فرسته"""
    with closing(db_connect()) as db:
        chats = db.execute("SELECT chat_id, chat_type FROM chats").fetchall()
    
    if not chats:
        await update.message.reply_text("❌ هنوز هیچ چتی ثبت نشده!")
        return
    
    status_msg = await update.message.reply_text(f"📤 در حال ارسال به {len(chats)} چت...")
    
    ok, fail = 0, 0
    dead_chats = []
    for ch in chats:
        try:
            await send_fn(ch["chat_id"])
            ok += 1
        except Exception as e:
            fail += 1
            err = str(e).lower()
            # چت‌هایی که ربات ازشون حذف شده رو پاک کن
            if "blocked" in err or "kicked" in err or "not found" in err or "deactivated" in err:
                dead_chats.append(ch["chat_id"])
        await asyncio.sleep(0.1)  # رعایت محدودیت تلگرام (۳۰ پیام/ثانیه)
    
    if dead_chats:
        with closing(db_connect()) as db:
            db.executemany("DELETE FROM chats WHERE chat_id = ?", [(c,) for c in dead_chats])
            db.commit()
    
    try:
        await status_msg.edit_text(
            f"📢 **ارسال همگانی تمام شد!**\n"
            f"━━━━━━━━━━━━━━\n"
            f"✅ موفق: {ok} چت\n"
            f"❌ ناموفق: {fail} چت"
            + (f"\n🧹 {len(dead_chats)} چت مرده از لیست پاک شد" if dead_chats else "")
        )
    except Exception:
        pass

# ============================================================
# هندلر پیام‌ها
# ============================================================

HELP_MAIN_TEXT = (
    "📖 **راهنمای کامل طویله خرستان** 🫏\n"
    "━━━━━━━━━━━━━━\n"
    "🗣️ همه‌چیز با **دستور فارسی** کار می‌کنه — کافیه تایپ کنی!\n\n"
    "**⚡ دستورات پرکاربرد:**\n"
    "🏠 `منو` | 🎮 `بازی‌ها` | 🏪 `فروشگاه`\n"
    "👤 `پروفایل` | 💰 `سکه` | 🏆 `جدول`\n"
    "🎁 `روزانه` | 💼 `کار` | 🎡 `گردونه` | 🔮 `فال`\n"
    "🐴 `خرم` | 🔊 `صداها` | 📖 `راهنما`\n"
    "🎲 بازی: `انفجار 100` | `اسلات 100` | ...\n"
    "🧠 `خر جان سوالت...` — از خر دانا بپرس! (۱۰۰ تی‌تاپ)\n\n"
    "👇 برای توضیح کامل هر بخش، دکمه‌ش رو بزن:"
)

HELP_SECTIONS = {
    "help_games": (
        "🎮 **بازی‌های گروهی** — اسم بازی + شرط:\n"
        "━━━━━━━━━━━━━━\n"
        "💥 `انفجار 100` — ضریب بالا می‌ره، قبل انفجار برداشت کن! (تا ۱۰ نفر)\n"
        "🎲 `تاس 100` — هر کی **خودش ایموجی 🎲 می‌فرسته**، بالاترین عدد می‌بره! (تا ۱۰ نفر)\n"
        "🔫 `رولت 100` — نوبتی انتخاب کن به کی شلیک بشه! آخرین بازمانده می‌بره (تا ۱۰ نفر)\n"
        "🔼🔽 `حدس 100` — حدس مجموع دو تاس، دقیقاً ۷ = x5 (تا ۱۰ نفر)\n"
        "🎰 `پوکر 100` — بهترین دست ۵ کارتی می‌بره (تا ۶ نفر)\n"
        "🃏 `بلک‌جک 100` — نزدیک‌ترین به ۲۱ بدون سوختن (تا ۶ نفر)\n"
        "❌⭕ `دوز 100` — سه‌تا ردیف کن! (۲ نفره)\n"
        "✊ `سنگ 100` — سنگ‌کاغذقیچی (۲ نفره)\n"
        "🪙 `شیرخط 100` — شانس خالص! (۲ نفره)\n\n"
        "🆕 **بازی‌های جدید:**\n"
        "🎯 `دارت 100` — با ایموجی واقعی 🎯، بالاترین می‌بره (تا ۱۰ نفر)\n"
        "🎳 `بولینگ 100` — با ایموجی واقعی 🎳، استرایک = ۶ (تا ۱۰ نفر)\n"
        "⚽ `پنالتی 100` — ۳ ضربه با ایموجی ⚽، گل بیشتر = برد (۲ نفره)\n"
        "🔢 `حدس‌عدد 100` — عدد مخفی ۱-۱۰۰، نوبتی حدس بزن! (تا ۱۰ نفر)\n"
        "💣 `مین 100` — جعبه بمب‌دار رو باز نکن! حذفی (تا ۱۰ نفر)\n\n"
        "🎰 **بازی فوری تکی:**\n"
        "`اسلات 100` — سه‌تایی 7️⃣ = x20 جکپات!\n"
        "`دوبل 100` — شانس ۵۰-۵۰، دوبل یا هیچی!\n\n"
        "💡 بازی‌های ۲ نفره با ورود نفر دوم خودکار شروع می‌شن.\n"
        "💡 می‌تونی فقط اسم بازی رو بنویسی (مثلاً `انفجار`) تا ربات مبلغ شرط رو ازت بپرسه.\n"
        "⏰ اگه بازی تا ۵ دقیقه شروع نشه، خودکار لغو می‌شه و شرط‌ها برمی‌گرده.\n"
        "🆘 بازی گیر کرد؟ بنویس `لغو بازی` — اگه ۳ دقیقه حرکتی نشده باشه لغو می‌شه و پول همه برمی‌گرده."
    ),
    "help_money": (
        "💰 **راه‌های پول درآوردن:**\n"
        "━━━━━━━━━━━━━━\n"
        "🎁 `روزانه` — جایزه روزانه (هر ۲۴ ساعت)\n"
        "💼 `کار` — برو سر کار، دستمزد بگیر (هر ۱ ساعت)\n"
        "🎡 `گردونه` — گردونه شانس، تا ۵۰۰۰ جایزه! (هر ۳ ساعت)\n"
        "🔮 `فال` — فالت رو بگیر + برکت (هر ۶ ساعت)\n"
        "🔊 عرعر کن! — هر صدا پوینت داره (هر ۲ دقیقه)\n"
        "🦹 `دزدی` (با ریپلی) — ۴۰٪ شانس، ولی جریمه داره! (هر ۲ ساعت)\n"
        "💸 `انتقال 100` (با ریپلی) — سکه بده به رفیقت\n\n"
        "⚠️ مواظب باش: توی دزدی اگه گیر بیفتی جریمه می‌شی!"
    ),
    "help_sounds": SOUNDS_LIST_TEXT,
    "help_donkey": (
        "🐴 **خر شخصی تو:**\n"
        "━━━━━━━━━━━━━━\n"
        "🐴 `خرم` — نمایش خرت با تجهیزاتش\n"
        "🏪 `فروشگاه` — خرید کلاه، زین، نعل، کروات، لباس، اکسسوری\n"
        "👤 `پروفایل` — مشخصات کامل (با ریپلی: پروفایل بقیه)\n"
        "❤️ `جفت‌گیری` یا `جفتگیری` (با ریپلی) — کره‌خر دار شو! (سطح ۲ لازمه، ۵۰۰ سکه)\n"
        "💌 طرف مقابل باید با دکمه «قبوله!» موافقت کنه وگرنه انجام نمی‌شه\n"
        "🐣 `کره‌خرها` — پنل کره‌خرها با دکمه: ارتقا، سود، تغییر اسم\n"
        "⬆️ `ارتقا کره‌خر 1` — ارتقا بده تا سود بیشتری بده (تا ۲۰۰۰ در روز!)\n"
        "📛 `اسم کره‌خر 1 فلفلی` — اسم دلخواه بذار\n"
        "💰 سود کره‌خرها خودکار همراه «روزانه» پرداخت می‌شه\n"
        "⭐ با پول بیشتر، سطح و لقبت بالاتر می‌ره:\n"
        "🐣 کره‌خر تازه‌کار → ... → 👑 خدا خرها"
    ),
    "help_other": (
        "📋 **بقیه دستورات:**\n"
        "━━━━━━━━━━━━━━\n"
        "🏠 `منو` — منوی اصلی با دکمه‌ها\n"
        "🎮 `بازی‌ها` — لیست بازی‌ها با دکمه‌ها\n"
        "🏪 `فروشگاه` — خرید وسایل برای خرت\n"
        "💰 `سکه` — نمایش موجودیت\n"
        "🏆 `جدول` — ۱۰ نفر ثروتمند طویله + رتبه خودت\n"
        "🔊 `صداها` — لیست همه صداهای خر و پوینت‌هاشون\n"
        "🧠 `خر جان هرچی می‌خوای بپرس` — خر دانا با هوش مصنوعی جوابتو می‌ده! (۱۰۰ تی‌تاپ، ۱۰ سوال در روز)\n"
        "📖 `راهنما` — همین راهنما\n"
        "/start — پیام خوش‌آمد\n\n"
        "🔒 **نکته:** هر منویی که خودت باز کنی، فقط خودت می‌تونی دکمه‌هاش رو بزنی. "
        "فقط دکمه‌های وسط بازی (مثل «ورود به بازی») برای همه آزاده!"
    )
}

def help_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 بازی‌ها", callback_data="help_games"),
         InlineKeyboardButton("💰 پول درآوردن", callback_data="help_money")],
        [InlineKeyboardButton("🔊 صداهای خر", callback_data="help_sounds"),
         InlineKeyboardButton("🐴 خر شخصی", callback_data="help_donkey")],
        [InlineKeyboardButton("📋 بقیه دستورات", callback_data="help_other")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="home")]
    ])

OWNER_HELP_TEXT = (
    "👑 **دستورات مالک:**\n"
    "━━━━━━━━━━━━━━\n"
    "`اونر` یا `پنل` — پنل مدیریت: دیتابیس بازیکنان، آمار، بکاپ 🎛️\n"
    "`بکاپ` — دریافت فایل بکاپ کامل دیتابیس 💾\n"
    "ارسال فایل بکاپ با کپشن `بازیابی` — برگرداندن دیتابیس 📥\n"
    "`سکه‌همگانی 500` — سکه به **همه** بازیکنان 🎊\n"
    "`اطلاعیه متن...` — پیام به **همه** گروه‌ها و پی‌وی‌ها 📢\n"
    "ریپلی + `فوروارد همگانی` / `کپی همگانی` — ارسال پست/عکس/ویدیو به همه 📨\n"
    "`تنظیم کانال @X` / `تنظیم گروه @X` — اهداف جوین اجباری 🔒\n"
    "`جوین اجباری روشن` / `خاموش` | `وضعیت جوین` 🔒\n\n"
    "**با ریپلی:**\n"
    "`+سکه 1000` — سکه دادن 💰\n"
    "`-سکه 1000` — کسر سکه 🔥\n"
    "`کادو گل` — کادو دادن 🎁\n"
    "`بن` / `انبن` — بن و آنبن 🚫\n\n"
    "🎁 **کادوها:** گل 🌹(100) | شکلات 🍫(250) | کیک 🎂(500) | خرس 🧸(1000) | گردنبند 📿(2500) | الماس 💎(5000) | ماشین 🚗(10000) | خونه 🏠(25000)"
)

# ============================================================
# 🔒 جوین اجباری کانال + گروه
# ============================================================

# کش عضویت تاییدشده تا هر پیام یه API کال نزنه: {user_id: expire_ts}
_MEMBER_CACHE = {}
MEMBER_CACHE_TTL = 300  # ۵ دقیقه

def force_join_enabled():
    return get_setting("force_join", "off") == "on"

def force_join_targets():
    """لیست (نوع، آیدی/یوزرنیم) اهداف جوین اجباری"""
    targets = []
    ch = get_setting("fj_channel", "")
    gp = get_setting("fj_group", "")
    if ch: targets.append(("کانال", ch))
    if gp: targets.append(("گروه", gp))
    return targets

def _fj_link(ident):
    ident = ident.strip()
    if ident.startswith("@"):
        return f"https://t.me/{ident[1:]}"
    if ident.startswith("https://"):
        return ident
    return None

def force_join_keyboard():
    rows = []
    for label, ident in force_join_targets():
        link = _fj_link(ident)
        if link:
            emoji = "📢" if label == "کانال" else "👥"
            rows.append([InlineKeyboardButton(f"{emoji} عضویت در {label}", url=link)])
    rows.append([InlineKeyboardButton("✅ عضو شدم — چک کن", callback_data="fj_check")])
    return InlineKeyboardMarkup(rows)

FORCE_JOIN_TEXT = (
    "🔒 **برای استفاده از ربات اول عضو شو!**\n"
    "━━━━━━━━━━━━━━\n"
    "🐴 طویله خرستان فقط برای اعضای خانواده‌ست!\n"
    "1️⃣ روی دکمه‌های زیر بزن و عضو شو\n"
    "2️⃣ بعدش «✅ عضو شدم» رو بزن"
)

async def is_member_of_required(user_id, context):
    """چک عضویت در همه اهداف — خطای دسترسی ربات = نادیده گرفتن اون هدف (تا ربات از کار نیفته)"""
    now = time.time()
    if _MEMBER_CACHE.get(user_id, 0) > now:
        return True
    
    for label, ident in force_join_targets():
        chat_ref = ident if ident.startswith("@") else ident
        try:
            member = await context.bot.get_chat_member(chat_ref, user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception as e:
            # ربات ادمین نیست یا کانال اشتباهه → این هدف رو نادیده بگیر و به لاگ هشدار بده
            logger.warning(f"⚠️ جوین اجباری: نتونستم عضویت {label} ({ident}) رو چک کنم: {e}")
            continue
    
    _MEMBER_CACHE[user_id] = now + MEMBER_CACHE_TTL
    # جلوگیری از رشد بی‌نهایت کش
    if len(_MEMBER_CACHE) > 2000:
        for k in [k for k, v in _MEMBER_CACHE.items() if v < now][:500]:
            _MEMBER_CACHE.pop(k, None)
    return True

# ⏱️ ضد اسپم پیام جوین: هر کاربر حداکثر هر ۹۰ ثانیه یه بار پیام جوین می‌بینه
FJ_PROMPT_COOLDOWN = 90
_FJ_LAST_PROMPT = {}

# لیست دستورات متنی کامل ربات (برای تشخیص «آیا این پیام کار ربات است؟»)
FJ_KNOWN_CMDS = {
    "راهنما", "help", "/help", "کمک", "منو", "menu", "خانه",
    "بازی", "بازی‌ها", "بازیها", "games", "فروشگاه", "شاپ", "shop",
    "روزانه", "daily", "جایزه روزانه", "جفت‌گیری", "جفت گیری", "جفتگیری",
    "پروفایل", "profile", "پروف", "سکه", "coins", "تی‌تاپ",
    "جدول", "ج", "leaderboard", "top", "صداها", "صدا", "sounds",
    "کار", "work", "کارکردن", "گردونه", "چرخ", "wheel",
    "فال", "fortune", "طالع", "دزدی", "سرقت", "rob",
    "خرم", "خر من", "donkey", "کره‌خرها", "کره خرها", "کره‌خر", "کره خر",
    "babies", "پنل کره‌خر", "پنل کره خر",
    "لغو بازی", "لغوبازی", "خروج از بازی", "cancelgame"
}
FJ_FIRST_WORD_CMDS = {"اسلات", "slot", "دوبل", "double", "انتقال", "transfer", "هدیه", "ارتقا", "اسم", "خرجان", "خردانا"}

def looks_like_bot_command(update, context, text):
    """تشخیص اینکه پیام، دستور ربات است یا چت عادی گروه"""
    if not text:
        return False
    if text.startswith("/"):
        return True
    if text in FJ_KNOWN_CMDS:
        return True
    squeezed = text.replace(" ", "").replace("\u200c", "")
    if squeezed in SOUND_KEYWORDS:
        return True
    parts = text.split()
    if parts and (parts[0] in FJ_FIRST_WORD_CMDS or parts[0] in GAME_ALIASES):
        return True
    # «خر جان ...» / «خر دانا ...» (دو کلمه‌ای) — ولی «خر خودتی» چت عادیه!
    if len(parts) >= 2 and parts[0] == "خر" and parts[1] in ["جان", "دانا"]:
        return True
    # عدد فقط وقتی ربات منتظرشه (شرط بازی یا حدس عدد)
    norm = text.translate(FA_DIGITS)
    if norm.isdigit():
        if context.user_data.get("awaiting_bet"):
            return True
        try:
            if GUESS_WAITING.get(update.effective_chat.id):
                return True
        except Exception:
            pass
    return False

async def force_join_gate(update, context, user_id):
    """True یعنی ادامه بده؛ False یعنی کاربر بلاک شد"""
    if not force_join_enabled() or user_id == OWNER_ID or not force_join_targets():
        return True
    
    # 🔑 توی گروه فقط وقتی «دستور ربات» زده چک کن — به چت عادی مردم کاری نداریم!
    text = (update.message.text or "").strip() if update.message and update.message.text else ""
    chat = update.effective_chat
    if chat and chat.type in ("group", "supergroup"):
        if not looks_like_bot_command(update, context, text):
            return True  # پیام عادی گروهه — بذار رد شه، ربات هم جوابی نمی‌ده
    
    if await is_member_of_required(user_id, context):
        return True
    
    # ⏱️ ضد اسپم: پیام جوین رو مدام تکرار نکن
    now = time.time()
    if now - _FJ_LAST_PROMPT.get(user_id, 0) >= FJ_PROMPT_COOLDOWN:
        _FJ_LAST_PROMPT[user_id] = now
        if len(_FJ_LAST_PROMPT) > 2000:
            for k in [k for k, v in _FJ_LAST_PROMPT.items() if now - v > FJ_PROMPT_COOLDOWN][:500]:
                _FJ_LAST_PROMPT.pop(k, None)
        try:
            await update.message.reply_text(FORCE_JOIN_TEXT, reply_markup=force_join_keyboard(), parse_mode="Markdown")
        except Exception:
            pass
    return False

async def reply_menu(update, text, kb, parse_mode="Markdown"):
    """ارسال منو و ثبت مالکیتش — فقط بازکننده می‌تونه دکمه‌هاش رو بزنه"""
    sent = await update.message.reply_text(text, reply_markup=kb, parse_mode=parse_mode)
    try:
        register_menu(update.effective_chat.id, sent.message_id, update.effective_user.id)
    except Exception:
        pass
    return sent

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # محافظت در برابر پیام‌های ویرایش‌شده / پست کانال
    if not update.message or not update.message.text or not update.effective_user:
        return
    user = update.effective_user
    text = update.message.text.strip()
    
    ensure_user(user.id, user.first_name)
    track_chat(update.effective_chat)
    
    u_data = get_user(user.id)
    if u_data and u_data["is_banned"] == 1:
        await update.message.reply_text("🚫 شما بن شده‌اید!")
        return
    
    # 🔒 جوین اجباری — بدون عضویت هیچ دستوری کار نمی‌کنه
    if not await force_join_gate(update, context, user.id):
        return
    
    # 🔢 عدد برای بازی حدس عدد فعال؟
    if await guessnum_text_received(update, context):
        return
    
    # ===== شروع =====
    if text.startswith("/start"):
        await reply_menu(update,
            "🫏✨ **به طویله خرستان خوش آمدید!** ✨🫏\n"
            "━━━━━━━━━━━━━━\n"
            "🎮 ۹ بازی گروهی + اسلات و دوبل\n"
            "🔊 ۱۲ صدای خر با پوینت و رتبه‌بندی\n"
            "💼 کار کن، 🎡 گردونه بچرخون، 🔮 فال بگیر\n"
            "🦹 از رفیقات بدزد (به ریسک خودت! 😏)\n"
            "🎁 جایزه روزانه + 💸 انتقال سکه به رفیقا\n"
            "❤️ جفت‌گیری کن و کره‌خر دار شو\n"
            "🎀 خرت رو خوشتیپ کن و به همه پز بده\n"
            "━━━━━━━━━━━━━━\n"
            "📖 برای دیدن همه دستورات: **راهنما**",
            main_menu()
        )
        return
    
    # ===== 👑 پنل اونر (با کلمه «اونر» یا «پنل») =====
    if text in ["اونر", "پنل", "panel", "/panel", "owner"]:
        if user.id != OWNER_ID:
            return  # کاربر عادی اصلاً متوجه وجود پنل نمی‌شه
        await reply_menu(update,
            "👑 **پنل مدیریت طویله**\n━━━━━━━━━━━━━━\nفقط برای اونر! انتخاب کن:",
            owner_panel_keyboard()
        )
        return
    
    # ===== 🔒 تنظیمات جوین اجباری (فقط اونر) =====
    parts_fj = text.split()
    if parts_fj and parts_fj[0] in ["تنظیم"] and user.id == OWNER_ID and len(parts_fj) >= 2:
        if parts_fj[1] == "کانال":
            if len(parts_fj) < 3 or not parts_fj[2].startswith("@"):
                await update.message.reply_text("📢 روش استفاده: `تنظیم کانال @MyChannel`\n(ربات باید توی کانال **ادمین** باشه!)", parse_mode="Markdown")
                return
            set_setting("fj_channel", parts_fj[2])
            _MEMBER_CACHE.clear()
            await update.message.reply_text(f"✅ کانال جوین اجباری ثبت شد: {parts_fj[2]}\n⚠️ یادت نره ربات رو توی کانال **ادمین** کنی!", parse_mode="Markdown")
            return
        if parts_fj[1] == "گروه":
            if len(parts_fj) < 3 or not parts_fj[2].startswith("@"):
                await update.message.reply_text("👥 روش استفاده: `تنظیم گروه @MyGroup`\n(گروه باید **یوزرنیم عمومی** داشته باشه و ربات عضوش باشه!)", parse_mode="Markdown")
                return
            set_setting("fj_group", parts_fj[2])
            _MEMBER_CACHE.clear()
            await update.message.reply_text(f"✅ گروه جوین اجباری ثبت شد: {parts_fj[2]}", parse_mode="Markdown")
            return
    
    if text in ["جوین اجباری روشن", "جوین‌اجباری روشن"] and user.id == OWNER_ID:
        if not force_join_targets():
            await update.message.reply_text("❌ اول کانال یا گروه رو ثبت کن:\n`تنظیم کانال @MyChannel`\n`تنظیم گروه @MyGroup`", parse_mode="Markdown")
            return
        set_setting("force_join", "on")
        _MEMBER_CACHE.clear()
        await update.message.reply_text("🔒 جوین اجباری **روشن** شد! از الان فقط اعضا می‌تونن از ربات استفاده کنن.", parse_mode="Markdown")
        return
    if text in ["جوین اجباری خاموش", "جوین‌اجباری خاموش"] and user.id == OWNER_ID:
        set_setting("force_join", "off")
        await update.message.reply_text("🔓 جوین اجباری **خاموش** شد.", parse_mode="Markdown")
        return
    if text in ["وضعیت جوین", "وضعیت‌جوین"] and user.id == OWNER_ID:
        status = "🔒 روشن" if force_join_enabled() else "🔓 خاموش"
        ch = get_setting("fj_channel", "—")
        gp = get_setting("fj_group", "—")
        await update.message.reply_text(
            f"⚙️ **وضعیت جوین اجباری**\n━━━━━━━━━━━━━━\n"
            f"وضعیت: {status}\n📢 کانال: {ch or '—'}\n👥 گروه: {gp or '—'}\n\n"
            f"دستورات:\n`تنظیم کانال @X` | `تنظیم گروه @X`\n`جوین اجباری روشن` | `جوین اجباری خاموش`",
            parse_mode="Markdown")
        return
    
    # ===== 💰 سکه همگانی (فقط اونر): «سکه‌همگانی 500» =====
    parts_ow = text.split()
    if parts_ow and parts_ow[0] in ["سکه‌همگانی", "سکه همگانی", "پول‌همگانی", "massgive"] and user.id == OWNER_ID:
        if len(parts_ow) < 2 or not parts_ow[1].translate(FA_DIGITS).isdigit():
            await update.message.reply_text(
                "💰 روش استفاده: `سکه‌همگانی 500`\nبه **همه بازیکنان** این مقدار سکه داده می‌شه.",
                parse_mode="Markdown")
            return
        amt = int(parts_ow[1].translate(FA_DIGITS))
        if amt <= 0 or amt > 1000000:
            await update.message.reply_text("❌ مبلغ باید بین ۱ تا ۱٬۰۰۰٬۰۰۰ باشه!")
            return
        with closing(db_connect()) as db:
            cnt = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
            db.execute("UPDATE users SET coins = coins + ?", (amt,))
            db.commit()
        await update.message.reply_text(
            f"🎊 **باران {CURRENCY_NAME} در طویله!**\n"
            f"━━━━━━━━━━━━━━\n"
            f"💰 مبلغ: **{amt:,}** {CURRENCY_NAME}\n"
            f"👥 به **{cnt}** بازیکن داده شد!\n\n"
            f"🐴 همه دارن عرعر خوشحالی می‌کنن! 🎉",
            parse_mode="Markdown")
        return
    # جلوی سوءاستفاده: کاربر عادی این دستور رو بزنه، هیچی نگو
    if parts_ow and parts_ow[0] in ["سکه‌همگانی", "سکه همگانی", "پول‌همگانی", "massgive"]:
        return
    
    # ===== 📢 پیام همگانی (فقط اونر): «اطلاعیه متن پیام...» =====
    if parts_ow and parts_ow[0] in ["اطلاعیه", "همگانی", "broadcast"] and user.id == OWNER_ID:
        bc_text = text[len(parts_ow[0]):].strip()
        if not bc_text:
            await update.message.reply_text(
                "📢 روش استفاده:\n`اطلاعیه سلام به همه!`\n\n"
                "پیامت به **همه گروه‌ها و پی‌وی‌هایی** که ربات توشونه فرستاده می‌شه.\n\n"
                "💡 برای ارسال پست کانال/عکس/ویدیو به همه:\n"
                "روی پیامش **ریپلی** بزن و بنویس `فوروارد همگانی` یا `کپی همگانی`",
                parse_mode="Markdown")
            return
        
        async def send_text(chat_id):
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"📢 **اطلاعیه طویله خرستان**\n━━━━━━━━━━━━━━\n{bc_text}",
                parse_mode="Markdown")
        
        await do_broadcast(update, context, send_text)
        return
    if parts_ow and parts_ow[0] in ["اطلاعیه", "همگانی", "broadcast"]:
        return
    
    # ===== 📨 فوروارد/کپی همگانی (فقط اونر — با ریپلی روی پیام) =====
    if text in ["فوروارد همگانی", "فوروارد‌همگانی", "کپی همگانی", "کپی‌همگانی"] and user.id == OWNER_ID:
        src = update.message.reply_to_message
        if not src:
            await update.message.reply_text(
                "📨 **روش استفاده:**\n"
                "1️⃣ پست کانال (یا هر پیامی: عکس، ویدیو، متن...) رو برای من فوروارد کن یا پیداش کن\n"
                "2️⃣ روش **ریپلی** بزن و بنویس:\n"
                "`فوروارد همگانی` — با برچسب «Forwarded from» (تبلیغ کانالت!)\n"
                "`کپی همگانی` — بدون برچسب، انگار خود ربات فرستاده",
                parse_mode="Markdown")
            return
        
        is_forward = text.startswith("فوروارد")
        
        async def send_msg(chat_id):
            if is_forward:
                await context.bot.forward_message(
                    chat_id=chat_id,
                    from_chat_id=src.chat_id,
                    message_id=src.message_id)
            else:
                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=src.chat_id,
                    message_id=src.message_id)
        
        await do_broadcast(update, context, send_msg)
        return
    if text in ["فوروارد همگانی", "فوروارد‌همگانی", "کپی همگانی", "کپی‌همگانی"]:
        return
    
    # ===== 💾 بکاپ متنی سریع =====
    if text in ["بکاپ", "backup", "/backup"]:
        if user.id != OWNER_ID:
            return
        try:
            data = export_db_json()
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            import io
            f = io.BytesIO(payload)
            f.name = f"kharbot_backup_{int(time.time())}.json"
            await update.message.reply_document(
                document=f,
                caption=(f"💾 بکاپ کامل دیتابیس\n👥 {len(data['users'])} بازیکن\n\n"
                         f"📥 برای بازیابی بعد از ری‌استارت: همین فایل رو با کپشن «بازیابی» بفرست.")
            )
        except Exception as e:
            logger.error(f"❌ خطا در بکاپ: {e}")
            await update.message.reply_text(f"❌ خطا در بکاپ: {e}")
        return
    
    # ===== راهنما =====
    if text in ["راهنما", "help", "/help", "کمک"]:
        msg = HELP_MAIN_TEXT
        if user.id == OWNER_ID:
            msg += "\n\n" + OWNER_HELP_TEXT
        await reply_menu(update, msg, help_keyboard())
        return
    
    # ===== لیست صداها =====
    if text in ["صداها", "صدا", "sounds"]:
        await update.message.reply_text(SOUNDS_LIST_TEXT, parse_mode="Markdown")
        return
    
    # ===== کار =====
    if text in ["کار", "work", "کارکردن"]:
        await work_command(update, context)
        return
    
    # ===== گردونه =====
    if text in ["گردونه", "چرخ", "wheel"]:
        await wheel_command(update, context)
        return
    
    # ===== فال =====
    if text in ["فال", "fortune", "طالع"]:
        await fortune_command(update, context)
        return
    
    # ===== دزدی =====
    if text in ["دزدی", "سرقت", "rob"]:
        await rob_command(update, context)
        return
    
    # ===== 🐣 پنل کره‌خرها =====
    if text in ["کره‌خرها", "کره خرها", "کره‌خر", "کره خر", "babies", "پنل کره‌خر", "پنل کره خر"]:
        await reply_menu(update, baby_panel_text(user.id), baby_panel_keyboard(user.id))
        return
    
    parts_baby = text.split()
    if len(parts_baby) >= 2 and parts_baby[0] == "ارتقا" and parts_baby[1] in ["کره‌خر", "کره", "کره‌خرها"]:
        idx_str = parts_baby[2].translate(FA_DIGITS) if len(parts_baby) > 2 else ""
        if not idx_str.isdigit():
            await update.message.reply_text("⬆️ روش استفاده: `ارتقا کره‌خر 1`", parse_mode="Markdown")
            return
        await baby_upgrade_command(update, context, int(idx_str))
        return
    
    if len(parts_baby) >= 3 and parts_baby[0] == "اسم" and parts_baby[1] in ["کره‌خر", "کره"]:
        idx_str = parts_baby[2].translate(FA_DIGITS)
        if not idx_str.isdigit() or len(parts_baby) < 4:
            await update.message.reply_text("📛 روش استفاده: `اسم کره‌خر 1 فلفلی`", parse_mode="Markdown")
            return
        new_name = " ".join(parts_baby[3:])
        await baby_rename_command(update, context, int(idx_str), new_name)
        return
    
    # ===== 🐴🧠 خر دانا =====
    parts_kd = text.split(None, 2)
    if parts_kd and parts_kd[0] in ["خرجان", "خردانا"]:
        await khar_dana_command(update, context, text[len(parts_kd[0]):])
        return
    if len(parts_kd) >= 2 and parts_kd[0] == "خر" and parts_kd[1] in ["جان", "دانا"]:
        q = text.split(None, 2)
        await khar_dana_command(update, context, q[2] if len(q) > 2 else "")
        return
    
    # ===== نمایش خر =====
    if text in ["خرم", "خر من", "donkey"]:
        await update.message.reply_text(donkey_art(user.id), parse_mode="Markdown")
        return
    
    # ===== انتقال سکه =====
    parts_tr = text.split()
    if parts_tr and parts_tr[0] in ["انتقال", "transfer", "هدیه"]:
        if len(parts_tr) < 2:
            await update.message.reply_text("💸 روش استفاده: روی پیام طرف ریپلی بزن و بنویس `انتقال 100`", parse_mode="Markdown")
            return
        val = parts_tr[1].translate(FA_DIGITS)
        if not val.isdigit():
            await update.message.reply_text("❌ مبلغ باید عدد باشه! مثال: `انتقال 100`", parse_mode="Markdown")
            return
        await transfer_command(update, context, int(val))
        return
    
    # ===== منو =====
    if text in ["منو", "menu", "خانه"]:
        await reply_menu(update, "🏠 **منوی اصلی طویله**", main_menu())
        return
    
    # ===== لیست بازی‌ها =====
    if text in ["بازی", "بازی‌ها", "بازیها", "games"]:
        await reply_menu(update,
            "🎮 **انتخاب بازی:**\n\n"
            "می‌تونی مستقیم تایپ کنی: `انفجار 100`\n"
            "یا از دکمه‌ها انتخاب کنی:",
            games_menu()
        )
        return
    
    # ===== فروشگاه =====
    if text in ["فروشگاه", "شاپ", "shop"]:
        await reply_menu(update,
            "🏪 **فروشگاه طویله**\nانتخاب کنید:",
            shop_keyboard()
        )
        return
    
    # ===== 🆘 لغو بازی گیرکرده =====
    if text in ["لغو بازی", "لغوبازی", "خروج از بازی", "cancelgame"]:
        room = player_active_room(user.id)
        if not room:
            await update.message.reply_text("✅ تو الان توی هیچ بازی‌ای نیستی!")
            return
        # اتاق شروع‌نشده: اگه سازنده‌ای کل اتاق لغو می‌شه، وگرنه فقط خودت خارج می‌شی
        if not room.started:
            if room.creator_id == user.id:
                refund_room(room)
                cleanup_room(room.room_id)
                await update.message.reply_text("❌ اتاقت لغو شد و شرط همه برگشت داده شد.")
            else:
                room.players.remove(user.id)
                add_coins(user.id, room.bet)
                PLAYER_IN_GAME.pop(user.id, None)
                await update.message.reply_text("🚪 از اتاق خارج شدی و شرطت برگشت.")
            return
        # بازی شروع‌شده: فقط اگه گیر کرده باشه (۳ دقیقه بی‌حرکت) قابل لغوئه
        if time.time() - room.last_action > STUCK_TIMEOUT:
            refund_room(room)
            room.finished = True
            cleanup_room(room.room_id)
            await update.message.reply_text(
                "🧹 **بازی گیرکرده لغو شد!**\n💰 شرط همه بازیکنان برگشت داده شد.",
                parse_mode="Markdown")
        else:
            remaining = int(STUCK_TIMEOUT - (time.time() - room.last_action))
            await update.message.reply_text(
                f"⏳ بازی هنوز فعاله! اگه {remaining} ثانیه دیگه هیچ حرکتی نشه، می‌تونی با «لغو بازی» آزادش کنی.")
        return
    
    # ===== جایزه روزانه =====
    if text in ["روزانه", "daily", "جایزه روزانه"]:
        await daily_reward(update, context)
        return
    
    # ===== جفت‌گیری =====
    if text in ["جفت‌گیری", "جفت گیری", "جفتگیری"]:
        await mate_command(update, context)
        return
    
    # ===== پروفایل =====
    if text in ["پروفایل", "profile", "پروف"]:
        if update.message.reply_to_message:
            target = update.message.reply_to_message.from_user
            target_id = target.id
        else:
            target_id = user.id
        await update.message.reply_text(
            profile_text(target_id),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="home")]]),
            parse_mode="Markdown"
        )
        return
    
    # ===== سکه (بدون ریپلی — موجودی خود شخص) =====
    if text in ["سکه", "coins", "تی‌تاپ"] and not update.message.reply_to_message:
        u = get_user(user.id)
        await update.message.reply_text(
            f"💰 **موجودی شما:** {u['coins']:,} {CURRENCY_NAME}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="home")]]),
            parse_mode="Markdown"
        )
        return
    
    # ===== جدول =====
    if text in ["جدول", "ج", "leaderboard", "top"]:
        with closing(db_connect()) as db:
            rows = db.execute(
                "SELECT user_id, name, coins, level FROM users ORDER BY coins DESC LIMIT 10"
            ).fetchall()
            user_row = db.execute(
                "SELECT COUNT(*) + 1 as rank FROM users WHERE coins > (SELECT coins FROM users WHERE user_id = ?)",
                (user.id,)
            ).fetchone()
        
        if not rows:
            await update.message.reply_text("❌ هنوز کسی ثبت نشده!")
            return
        
        msg = "🏆 **جدول ثروتمندان طویله**\n━━━━━━━━━━━━━━━━\n"
        for i, row in enumerate(rows, 1):
            medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
            title = get_title_by_level(row["level"])
            msg += f"{medal} {title} {esc_md(row['name'])} — {row['coins']:,}\n"
        
        if user_row and user_row["rank"]:
            msg += f"\n━━━━━━━━━━━━━━━━\n👤 رتبه شما: #{user_row['rank']}"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
    
    # ===== صدای خر =====
    if text.replace(" ", "").replace("\u200c", "") in SOUND_KEYWORDS:
        await donkey_sound(update, context)
        return
    
    # ===== بازی‌های فوری =====
    parts_fa = text.split()
    if parts_fa and parts_fa[0] in ["اسلات", "slot"]:
        bet = parse_bet_arg(parts_fa)
        if bet is None:
            await update.message.reply_text(f"🎰 روش بازی: `اسلات 100` (حداقل {MIN_BET})", parse_mode="Markdown")
            return
        await slot_game(update, context, bet)
        return
    
    if parts_fa and parts_fa[0] in ["دوبل", "double"]:
        bet = parse_bet_arg(parts_fa)
        if bet is None:
            await update.message.reply_text(f"🎲 روش بازی: `دوبل 100` (حداقل {MIN_BET})", parse_mode="Markdown")
            return
        await double_game(update, context, bet)
        return
    
    # ===== ساخت بازی گروهی با دستور فارسی (مثلاً: انفجار 100 یا فقط: انفجار) =====
    if parts_fa and parts_fa[0] in GAME_ALIASES:
        game_type = GAME_ALIASES[parts_fa[0]]
        bet = parse_bet_arg(parts_fa)
        if bet is None:
            if len(parts_fa) >= 2:
                # عدد نوشته ولی نامعتبره
                await update.message.reply_text(
                    f"❌ مبلغ نامعتبره! حداقل شرط {MIN_BET} {CURRENCY_NAME} است.\nمثال: `{parts_fa[0]} 100`",
                    parse_mode="Markdown")
                return
            # فقط اسم بازی رو نوشته → مبلغ شرط رو بپرس
            if player_active_room(user.id):
                await update.message.reply_text("⚠️ شما در یک بازی دیگر هستید! اول اون رو تموم کن.")
                return
            context.user_data["temp_game"] = game_type
            context.user_data["awaiting_bet"] = True
            context.user_data["bet_tries"] = 0
            pl = "دقیقاً ۲ بازیکن" if game_type in TWO_PLAYER_GAMES else f"۲ تا {GAME_MAX_PLAYERS[game_type]} بازیکن"
            await update.message.reply_text(
                f"🎮 **{GAME_NAMES[game_type]}**\n"
                f"━━━━━━━━━━━━━━\n"
                f"💰 حداقل شرط: {MIN_BET} {CURRENCY_NAME}\n"
                f"👥 {pl}\n"
                f"💳 موجودی تو: {get_user(user.id)['coins']:,} {CURRENCY_NAME}\n\n"
                f"💬 مبلغ شرط رو بنویس (فقط عدد):",
                parse_mode="Markdown")
            return
        await start_room_from_text(update, context, game_type, bet)
        return
    
    # ============================================================
    # دستورات ادمین (با ریپلی)
    # ============================================================
    
    if user.id == OWNER_ID and update.message.reply_to_message:
        parts = text.split()
        if not parts:
            return
        cmd = parts[0].lower()
        target = update.message.reply_to_message.from_user
        
        if cmd in ["/ban", "بن"]:
            with closing(db_connect()) as db:
                db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (target.id,))
                db.commit()
            await update.message.reply_text(f"✅ {esc_md(target.first_name)} بن شد!")
            return
        if cmd in ["/unban", "انبن"]:
            with closing(db_connect()) as db:
                db.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (target.id,))
                db.commit()
            await update.message.reply_text(f"✅ {esc_md(target.first_name)} آنبن شد!")
            return
        if cmd == "کادو" and len(parts) > 1:
            gift_name = parts[1]
            if gift_name not in OWNER_GIFTS:
                gifts_list = " | ".join(f"{g}{OWNER_GIFTS[g]['emoji']}" for g in OWNER_GIFTS)
                await update.message.reply_text(f"🎁 کادوهای موجود:\n{gifts_list}\n\nمثال: `کادو گل` (با ریپلی)", parse_mode="Markdown")
                return
            gift = OWNER_GIFTS[gift_name]
            ensure_user(target.id, target.first_name)
            add_coins(target.id, gift["coins"])
            await update.message.reply_text(
                f"🎁 **کادو از طرف مالک طویله!**\n"
                f"━━━━━━━━━━━━━━\n"
                f"{gift['emoji']} یک **{gift_name}** به {esc_md(target.first_name)} هدیه داده شد!\n"
                f"💰 ارزش: **{gift['coins']:,}** {CURRENCY_NAME}\n\n"
                f"🥳 مبارکش باشه!",
                parse_mode="Markdown"
            )
            return
        if cmd in ["/addcoin", "سکه", "+سکه"] and len(parts) > 1:
            try:
                amt = int(parts[1].translate(FA_DIGITS))
                ensure_user(target.id, target.first_name)
                add_coins(target.id, amt)
                await update.message.reply_text(f"💰 {amt:,} {CURRENCY_NAME} به {esc_md(target.first_name)} اضافه شد!")
            except (ValueError, IndexError):
                pass
            return
        if cmd in ["/remcoin", "کسر", "-سکه"] and len(parts) > 1:
            try:
                amt = int(parts[1].translate(FA_DIGITS))
                with closing(db_connect()) as db:
                    db.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (amt, target.id))
                    db.commit()
                await update.message.reply_text(f"🔥 {amt:,} {CURRENCY_NAME} از {esc_md(target.first_name)} کسر شد!")
            except (ValueError, IndexError):
                pass
            return
    
    # ============================================================
    # دریافت شرط
    # ============================================================
    
    if context.user_data.get("awaiting_bet"):
        
        async def bet_fail(err_msg):
            """❌ ورودی نامعتبر: فقط ۲ بار اخطار، بار سوم درخواست بازی بسته می‌شود"""
            tries = context.user_data.get("bet_tries", 0) + 1
            context.user_data["bet_tries"] = tries
            if tries >= 3:
                context.user_data["awaiting_bet"] = False
                context.user_data["temp_game"] = None
                context.user_data["bet_tries"] = 0
                await update.message.reply_text(
                    "🚪 **درخواست بازی بسته شد!**\n"
                    "۳ بار عدد معتبر وارد نکردی. هر وقت خواستی دوباره بازی بساز. 🐴",
                    parse_mode="Markdown")
            else:
                await update.message.reply_text(f"{err_msg}\n⚠️ فرصت باقی‌مانده: {2 - tries + 1} از ۲")
        
        normalized = text.translate(FA_DIGITS)
        if normalized.isdigit():
            bet = int(normalized)
            if bet < MIN_BET:
                await bet_fail(f"❌ حداقل شرط {MIN_BET} {CURRENCY_NAME} است!")
                return
            
            u = get_user(user.id)
            if u["coins"] < bet:
                await bet_fail(f"❌ پول کافی ندارید! موجودی: {u['coins']:,} {CURRENCY_NAME}")
                return
            
            game_type = context.user_data.get("temp_game")
            if not game_type:
                context.user_data["awaiting_bet"] = False
                context.user_data["bet_tries"] = 0
                await update.message.reply_text("❌ خطا! دوباره از منو بازی رو انتخاب کن.")
                return
            
            if player_active_room(user.id):
                context.user_data["awaiting_bet"] = False
                context.user_data["bet_tries"] = 0
                await update.message.reply_text("⚠️ شما در یک بازی دیگر هستید!")
                return
            
            remove_coins(user.id, bet)
            room = create_room(update.effective_chat.id, game_type, user.id, bet)
            
            two_p = "👥 بازی ۲ نفره" if game_type in TWO_PLAYER_GAMES else f"👥 ۲ تا {GAME_MAX_PLAYERS[game_type]} نفره"
            msg_text = (
                f"🎮 **{GAME_NAMES[game_type]}**\n"
                f"━━━━━━━━━━━━━━\n"
                f"💰 شرط: {bet} {CURRENCY_NAME}\n"
                f"{two_p}\n"
                f"👤 سازنده: {esc_md(user.first_name)}\n"
                f"\n🔄 منتظر ورود بازیکنان دیگر..."
            )
            
            sent_msg = await update.message.reply_text(
                msg_text,
                reply_markup=room_control_keyboard(room),
                parse_mode="Markdown"
            )
            room.message_id = sent_msg.message_id
            context.application.create_task(room_timeout_watch(room, context))
            
            context.user_data["awaiting_bet"] = False
            context.user_data["temp_game"] = None
            context.user_data["bet_tries"] = 0
            
        else:
            await bet_fail("❌ لطفاً یک عدد معتبر وارد کنید!")
        return

# ============================================================
# هندلر دکمه‌ها
# ============================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    ensure_user(user.id, user.first_name)
    
    u_data = get_user(user.id)
    if u_data and u_data["is_banned"] == 1:
        await query.answer("🚫 شما بن شده‌اید!", show_alert=True)
        return
    
    data = query.data
    
    # ===== اکشن‌های داخل بازی (جواب query داخل خود اکشن داده می‌شود) =====
    if data.startswith("g|"):
        await game_action_router(update, context, query, data)
        return
    
    # ===== ✅ چک عضویت جوین اجباری =====
    if data == "fj_check":
        _MEMBER_CACHE.pop(user.id, None)  # چک تازه
        if not force_join_enabled() or await is_member_of_required(user.id, context):
            await query.answer("🎉 خوش اومدی به طویله!", show_alert=True)
            try:
                await query.edit_message_text(
                    "✅ **عضویتت تایید شد! خوش اومدی به طویله خرستان!** 🐴🎉\nحالا از همه امکانات می‌تونی استفاده کنی.",
                    reply_markup=main_menu(), parse_mode="Markdown")
            except Exception:
                pass
        else:
            await query.answer("❌ هنوز عضو نشدی! اول جوین شو بعد این دکمه رو بزن.", show_alert=True)
        return
    
    # ===== 💌 جواب درخواست جفت‌گیری (فقط طرف مقابل) =====
    if data in ["mate_yes", "mate_no"]:
        await mate_callback(update, context, query, "yes" if data == "mate_yes" else "no")
        return
    
    # ===== 🔒 قفل منو: هر منویی فقط برای کسی که بازش کرده =====
    # دکمه‌های اتاق بازی (ورود، خر بات، شروع، لغو) برای همه آزادن
    if not data.startswith("room_"):
        try:
            owner = menu_owner_of(query.message.chat_id, query.message.message_id)
        except Exception:
            owner = None
        if owner is not None and owner != user.id:
            await query.answer("🔒 این منو مال تو نیست! خودت یکی باز کن 😉", show_alert=True)
            return
    
    # ===== 👑 پنل اونر (فقط اونر) =====
    if data.startswith("panel_"):
        if user.id != OWNER_ID:
            await query.answer("⛔ دسترسی نداری!", show_alert=True)
            return
        await query.answer()
        
        if data == "panel_main":
            await query.edit_message_text(
                "👑 **پنل مدیریت طویله**\n━━━━━━━━━━━━━━\nفقط برای اونر! انتخاب کن:",
                reply_markup=owner_panel_keyboard(),
                parse_mode="Markdown"
            )
            return
        
        # 📚 بخش‌های آموزشی دستورات
        if data in PANEL_GUIDES:
            await query.edit_message_text(
                PANEL_GUIDES[data],
                reply_markup=panel_back_kb(),
                parse_mode="Markdown"
            )
            return
        
        if data.startswith("panel_players_"):
            page = int(data[14:])
            text_p, total = panel_players_text(page)
            await query.edit_message_text(
                text_p,
                reply_markup=panel_players_keyboard(page, total),
                parse_mode="Markdown"
            )
            return
        
        if data == "panel_stats":
            with closing(db_connect()) as db:
                s = db.execute(
                    "SELECT COUNT(*) as users, COALESCE(SUM(coins),0) as coins, "
                    "COALESCE(SUM(wins),0) as wins, COALESCE(SUM(losses),0) as losses, "
                    "COALESCE(SUM(babies),0) as babies, COALESCE(SUM(sound_count),0) as sounds, "
                    "COALESCE(SUM(is_banned),0) as banned FROM users"
                ).fetchone()
                rich = db.execute("SELECT name, coins FROM users ORDER BY coins DESC LIMIT 1").fetchone()
            msg = (
                f"📊 **آمار کلی ربات**\n━━━━━━━━━━━━━━\n"
                f"👥 کل بازیکنان: {s['users']}\n"
                f"💰 کل {CURRENCY_NAME} در گردش: {s['coins']:,}\n"
                f"🎮 کل بردها: {s['wins']:,} | باخت‌ها: {s['losses']:,}\n"
                f"👶 کل کره‌خرها: {s['babies']}\n"
                f"🔊 کل عرعرها: {s['sounds']:,}\n"
                f"🚫 بن‌شده‌ها: {s['banned']}\n"
                f"🎪 اتاق‌های فعال: {len(ACTIVE_ROOMS)}\n"
            )
            if rich:
                msg += f"🥇 ثروتمندترین: {esc_md(rich['name'])} ({rich['coins']:,})"
            await query.edit_message_text(
                msg,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 پنل", callback_data="panel_main")]]),
                parse_mode="Markdown"
            )
            return
        
        if data == "panel_backup":
            try:
                bdata = export_db_json()
                payload = json.dumps(bdata, ensure_ascii=False).encode("utf-8")
                import io
                f = io.BytesIO(payload)
                f.name = f"kharbot_backup_{int(time.time())}.json"
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=f,
                    caption=(f"💾 بکاپ کامل دیتابیس\n👥 {len(bdata['users'])} بازیکن\n\n"
                             f"📥 برای بازیابی بعد از ری‌استارت: همین فایل رو با کپشن «بازیابی» بفرست.")
                )
                await query.answer("✅ بکاپ ارسال شد!")
            except Exception as e:
                logger.error(f"❌ خطا در بکاپ: {e}")
                await query.answer(f"❌ خطا: {e}", show_alert=True)
            return
        
        if data == "panel_restore_help":
            await query.edit_message_text(
                "📥 **راهنمای بازیابی دیتابیس**\n━━━━━━━━━━━━━━\n"
                "چون دیتابیس توی `/tmp` هست، بعد از هر ری‌استارت سرور پاک می‌شه.\n\n"
                "**روش کار:**\n"
                "1️⃣ هر چند وقت یه بار بنویس `بکاپ` یا از پنل دکمه «💾 بکاپ» رو بزن\n"
                "2️⃣ ربات یه فایل JSON بهت می‌ده — نگهش دار\n"
                "3️⃣ بعد از ری‌استارت، همون فایل رو برای ربات بفرست با **کپشن**: `بازیابی`\n"
                "4️⃣ تمام! سکه‌ها، وسایل، سطح و همه‌چیزِ همه برمی‌گرده ✅\n\n"
                "⚠️ فقط اونر می‌تونه بازیابی کنه.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 پنل", callback_data="panel_main")]]),
                parse_mode="Markdown"
            )
            return
        return
    
    await query.answer()
    
    # ===== راهنما =====
    if data == "help_main":
        msg = HELP_MAIN_TEXT
        if user.id == OWNER_ID:
            msg += "\n\n" + OWNER_HELP_TEXT
        await query.edit_message_text(msg, reply_markup=help_keyboard(), parse_mode="Markdown")
        return
    
    if data in HELP_SECTIONS:
        await query.edit_message_text(
            HELP_SECTIONS[data],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به راهنما", callback_data="help_main")]]),
            parse_mode="Markdown"
        )
        return
    
    # ===== خانه =====
    if data == "home":
        await query.edit_message_text(
            "🏠 **منوی اصلی طویله**",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )
        return
    
    # ===== لیست بازی‌ها =====
    if data == "games_list":
        await query.edit_message_text(
            "🎮 **انتخاب بازی:**\n\n"
            "👥 ۲ نفره: سنگ‌کاغذقیچی، دوز، شیر یا خط\n"
            "👥 تا ۶ نفر: بلک‌جک، پوکر\n"
            "👥 تا ۱۰ نفر: انفجار، تاس، رولت، بالا/پایین",
            reply_markup=games_menu(),
            parse_mode="Markdown"
        )
        return
    
    # ===== انتخاب بازی =====
    if data.startswith("game_"):
        game_type = data[5:]
        if game_type not in GAME_NAMES:
            return
        
        if player_active_room(user.id):
            await query.answer("⚠️ شما در یک بازی دیگر هستید!", show_alert=True)
            return
        
        context.user_data["temp_game"] = game_type
        context.user_data["awaiting_bet"] = True
        context.user_data["bet_tries"] = 0
        
        pl = "دقیقاً ۲ بازیکن" if game_type in TWO_PLAYER_GAMES else f"۲ تا {GAME_MAX_PLAYERS[game_type]} بازیکن"
        await query.edit_message_text(
            f"🎮 **{GAME_NAMES[game_type]}**\n"
            f"━━━━━━━━━━━━━━\n"
            f"💰 حداقل شرط: {MIN_BET} {CURRENCY_NAME}\n"
            f"👥 {pl}\n\n"
            f"مبلغ شرط را وارد کنید (عدد):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لغو", callback_data="bet_cancel")]]),
            parse_mode="Markdown"
        )
        return
    
    # ===== لغو انتخاب شرط =====
    if data == "bet_cancel":
        context.user_data["awaiting_bet"] = False
        context.user_data["temp_game"] = None
        await query.edit_message_text("🎮 **انتخاب بازی:**", reply_markup=games_menu(), parse_mode="Markdown")
        return
    
    # ===== ورود به اتاق =====
    if data.startswith("room_join_"):
        room_id = data[10:]
        room = get_room(room_id)
        if not room:
            await query.answer("❌ اتاق وجود ندارد!", show_alert=True)
            return
        if room.started:
            await query.answer("❌ بازی شروع شده!", show_alert=True)
            return
        if user.id in room.players:
            await query.answer("✅ شما قبلاً در اتاق هستید!", show_alert=True)
            return
        if len(room.players) >= room.max_players:
            await query.answer("❌ ظرفیت پر است!", show_alert=True)
            return
        if player_active_room(user.id):
            await query.answer("⚠️ شما در یک بازی دیگر هستید!", show_alert=True)
            return
        
        if not remove_coins(user.id, room.bet):
            await query.answer(f"❌ شما {room.bet} {CURRENCY_NAME} ندارید!", show_alert=True)
            return
        
        room.add_player(user.id)
        PLAYER_IN_GAME[user.id] = room_id
        
        await show_room_status(room, context, query)
        
        # بازی‌های دقیقاً ۲ نفره: با پر شدن ظرفیت، خودکار شروع شود
        if room.game_type in TWO_PLAYER_GAMES and len(room.players) == 2:
            await start_game(room, context, query)
        return
    
    # ===== اضافه کردن خر بات =====
    if data.startswith("room_bot_"):
        room_id = data[9:]
        room = get_room(room_id)
        if not room:
            await query.answer("❌ اتاق وجود ندارد!", show_alert=True)
            return
        if room.started:
            await query.answer("❌ بازی شروع شده!", show_alert=True)
            return
        if room.creator_id != user.id:
            await query.answer("❌ فقط سازنده اتاق می‌تونه خر بات رو دعوت کنه!", show_alert=True)
            return
        if BOT_ID in room.players:
            await query.answer("🤖 خر بات از قبل توی بازیه!", show_alert=True)
            return
        if len(room.players) >= room.max_players:
            await query.answer("❌ ظرفیت پر است!", show_alert=True)
            return
        
        room.add_player(BOT_ID)
        await query.answer("🤖 خر بات وارد شد! عر عر! 🐴")
        await show_room_status(room, context, query)
        
        # بازی‌های ۲ نفره: با ورود خر بات خودکار شروع شود
        if room.game_type in TWO_PLAYER_GAMES and len(room.players) == 2:
            await start_game(room, context, query)
        return
    
    # ===== شروع بازی =====
    if data.startswith("room_start_"):
        room_id = data[11:]
        room = get_room(room_id)
        if not room:
            await query.answer("❌ اتاق وجود ندارد!", show_alert=True)
            return
        if room.creator_id != user.id:
            await query.answer("❌ فقط سازنده اتاق می‌تواند شروع کند!", show_alert=True)
            return
        if len(room.players) < 2:
            await query.answer("❌ حداقل ۲ بازیکن نیاز است!", show_alert=True)
            return
        if room.started:
            return
        
        await start_game(room, context, query)
        return
    
    # ===== لغو اتاق =====
    if data.startswith("room_cancel_"):
        room_id = data[12:]
        room = get_room(room_id)
        if not room:
            await query.answer("❌ اتاق وجود ندارد!", show_alert=True)
            return
        if room.creator_id != user.id:
            await query.answer("❌ فقط سازنده اتاق می‌تواند لغو کند!", show_alert=True)
            return
        if room.started:
            await query.answer("❌ بازی شروع شده و قابل لغو نیست!", show_alert=True)
            return
        
        for p in room.players:
            add_coins(p, room.bet)
        room.finished = True
        cleanup_room(room_id)
        await query.edit_message_text("❌ اتاق لغو شد. شرط همه برگشت داده شد.", reply_markup=main_menu())
        return
    
    # ===== پروفایل =====
    # ===== 🐣 پنل کره‌خرها =====
    if data == "babe_home":
        await query.edit_message_text(
            baby_panel_text(user.id),
            reply_markup=baby_panel_keyboard(user.id),
            parse_mode="Markdown"
        )
        return
    
    if data.startswith("babe_view_"):
        idx = int(data[10:])
        detail = baby_detail_text(user.id, idx)
        if not detail:
            await query.answer("❌ این کره‌خر پیدا نشد!", show_alert=True)
            return
        await query.edit_message_text(
            detail,
            reply_markup=baby_detail_keyboard(user.id, idx),
            parse_mode="Markdown"
        )
        return
    
    if data.startswith("babe_up_"):
        idx = int(data[8:])
        u = get_user(user.id)
        babies = load_babies(u)
        if idx < 1 or idx > len(babies):
            await query.answer("❌ این کره‌خر پیدا نشد!", show_alert=True)
            return
        b = babies[idx - 1]
        cur = b.get("level", 1)
        if cur >= BABY_MAX_LEVEL:
            await query.answer("🏆 فول‌لِوِله! بالاتر نداریم 🦄", show_alert=True)
            return
        nxt = BABY_LEVELS[cur + 1]
        if not remove_coins(user.id, nxt["cost"]):
            await query.answer(f"❌ {nxt['cost']:,} {CURRENCY_NAME} لازمه! موجودیت: {u['coins']:,}", show_alert=True)
            return
        b["level"] = cur + 1
        save_babies(user.id, babies)
        await query.answer(f"🎉 {b['name']} شد سطح {cur+1} ({nxt['name']})!", show_alert=True)
        await query.edit_message_text(
            baby_detail_text(user.id, idx),
            reply_markup=baby_detail_keyboard(user.id, idx),
            parse_mode="Markdown"
        )
        return
    
    if data == "show_profile":
        await query.edit_message_text(
            profile_text(user.id),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="home")]]),
            parse_mode="Markdown"
        )
        return
    
    # ===== جدول =====
    if data == "leaderboard":
        with closing(db_connect()) as db:
            rows = db.execute(
                "SELECT user_id, name, coins, level FROM users ORDER BY coins DESC LIMIT 10"
            ).fetchall()
            user_row = db.execute(
                "SELECT COUNT(*) + 1 as rank FROM users WHERE coins > (SELECT coins FROM users WHERE user_id = ?)",
                (user.id,)
            ).fetchone()
        
        if not rows:
            await query.edit_message_text("❌ هنوز کسی ثبت نشده!")
            return
        
        msg = "🏆 **جدول ثروتمندان طویله**\n━━━━━━━━━━━━━━━━\n"
        for i, row in enumerate(rows, 1):
            medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
            title = get_title_by_level(row["level"])
            msg += f"{medal} {title} {esc_md(row['name'])} — {row['coins']:,}\n"
        
        if user_row and user_row["rank"]:
            msg += f"\n━━━━━━━━━━━━━━━━\n👤 رتبه شما: #{user_row['rank']}"
        
        await query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="home")]]),
            parse_mode="Markdown"
        )
        return
    
    # ===== فروشگاه =====
    if data == "shop":
        await query.edit_message_text(
            "🏪 **فروشگاه طویله**\nانتخاب کنید:",
            reply_markup=shop_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    # ===== دسته‌بندی فروشگاه =====
    if data.startswith("shop_"):
        category = data[5:]
        if category not in SHOP_ITEMS:
            return
        
        cat_data = SHOP_ITEMS[category]
        buttons = []
        for item_name, item_data in cat_data["items"].items():
            buttons.append([InlineKeyboardButton(
                f"{item_data['emoji']} {item_name} - {item_data['price']:,} {CURRENCY_NAME}",
                callback_data=f"buy_{category}_{item_name}"
            )])
        buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="shop")])
        
        await query.edit_message_text(
            f"🏪 **{cat_data['name']}**\nانتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown"
        )
        return
    
    # ===== خرید =====
    if data.startswith("buy_"):
        parts = data.split("_")
        if len(parts) < 3:
            return
        category = parts[1]
        item_name = "_".join(parts[2:])
        
        if category not in SHOP_ITEMS:
            return
        if item_name not in SHOP_ITEMS[category]["items"]:
            return
        
        item_data = SHOP_ITEMS[category]["items"][item_name]
        price = item_data["price"]
        
        donkey = get_donkey(user.id)
        if not donkey:
            await query.answer("❌ خر شما وجود ندارد!", show_alert=True)
            return
        
        if not remove_coins(user.id, price):
            await query.answer(f"❌ {price:,} {CURRENCY_NAME} ندارید!", show_alert=True)
            return
        
        col_map = {
            "hats": "equipped_hat",
            "saddles": "equipped_saddle",
            "horseshoes": "equipped_horseshoe",
            "ties": "equipped_tie",
            "clothes": "equipped_clothes",
            "accessories": "equipped_accessory"
        }
        
        col = col_map.get(category)
        if col:
            with closing(db_connect()) as db:
                db.execute(f"UPDATE donkeys SET {col} = ? WHERE user_id = ?", (item_name, user.id))
                db.commit()
        
        await query.answer(f"✅ {item_name} خریداری و فعال شد!", show_alert=True)
        
        await query.edit_message_text(
            f"✅ **خرید موفق!**\n{item_data['emoji']} {item_name} روی خر شما قرار گرفت.\n💰 هزینه: {price:,} {CURRENCY_NAME}",
            reply_markup=shop_keyboard(),
            parse_mode="Markdown"
        )
        return

# ============================================================
# هندلر خطای سراسری
# ============================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("❌ خطای هندل‌نشده:", exc_info=context.error)

async def janitor_job(context: ContextTypes.DEFAULT_TYPE):
    """🧹 نظافتچی دوره‌ای: هر دقیقه اتاق‌های گیرکرده رو پاک می‌کنه و به گروه خبر می‌ده"""
    now = time.time()
    for rid in list(ACTIVE_ROOMS.keys()):
        room = ACTIVE_ROOMS.get(rid)
        if not room or room.finished:
            continue
        if room.started and now - room.last_action > STUCK_TIMEOUT:
            refund_room(room)
            room.finished = True
            cleanup_room(rid)
            logger.info(f"🧹 نظافتچی: بازی گیرکرده {rid} ({room.game_type}) لغو شد")
            try:
                await context.bot.edit_message_text(
                    f"🧹 **بازی {GAME_NAMES.get(room.game_type, '')} به دلیل بی‌حرکتی لغو شد!**\n"
                    f"💰 شرط همه بازیکنان برگشت داده شد.",
                    chat_id=room.chat_id,
                    message_id=room.message_id,
                    parse_mode="Markdown"
                )
            except Exception:
                pass
    # قفل‌های بی‌صاحب (بازیکنی که اتاقش وجود نداره)
    for uid in list(PLAYER_IN_GAME.keys()):
        rid = PLAYER_IN_GAME.get(uid)
        room = ACTIVE_ROOMS.get(rid)
        if not room or room.finished:
            PLAYER_IN_GAME.pop(uid, None)
            logger.info(f"🔓 نظافتچی: قفل بی‌صاحب بازیکن {uid} آزاد شد")

# ============================================================
# اصلی
# ============================================================

def main():
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN تنظیم نشده!")
        return
    
    try:
        init_db()
    except Exception as e:
        logger.error(f"❌ خطا در راه‌اندازی دیتابیس: {e}")
        return
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, message_handler))
    app.add_handler(MessageHandler(filters.Dice.ALL, dice_roll_received))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_error_handler(error_handler)
    
    # 🧹 نظافتچی هر ۶۰ ثانیه (نیاز به python-telegram-bot[job-queue])
    if app.job_queue:
        app.job_queue.run_repeating(janitor_job, interval=60, first=60)
        logger.info("🧹 نظافتچی دوره‌ای فعال شد")
    else:
        logger.warning("⚠️ JobQueue نصب نیست — نظافت فقط موقع فعالیت کاربرا انجام می‌شه. "
                       "برای فعال‌سازی: pip install 'python-telegram-bot[job-queue]'")
    
    logger.info("✅ ربات خرستان راه‌اندازی شد!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
