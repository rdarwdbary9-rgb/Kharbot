#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ╔══════════════════════════════════════════════════════════╗
# ║          🐴 ربات طویله خرستان — نسخه کامل 🐴 ║
# ╠══════════════════════════════════════════════════════════╣
# ║  📑 فهرست فصل‌ها — برای پریدن به هر فصل سرچ کن: «فصل N»   ║
# ║                                                          ║
# ║  فصل 1  ⚙️ تنظیمات و ثابت‌ها                              ║
# ║  فصل 2  🗄️ دیتابیس و مدیریت کاربران                      ║
# ║  فصل 3  👤 پروفایل و لقب‌ها                               ║
# ║  فصل 4  💰 درآمدها (روزانه/صدا/کار/گردونه/دزدی/فال)      ║
# ║  فصل 5  🏦 اقتصاد (بانک/وام/لیگ/تریاک/بیمه/مالیات)       ║
# ║  فصل 6  🐣 خر شخصی، کره‌خر و جفت‌گیری                     ║
# ║  فصل 7  🎮 بازی‌ها (اتاق‌ها، موتور، گزارشگر، فوری)        ║
# ║  فصل 8  👑 مالک (پنل/خر دانا/همگانی/کادو)                ║
# ║  فصل 9  📨 هندلرها (پیام/جوین اجباری/دکمه‌ها)            ║
# ║  فصل 10 🚀 خطا، نظافتچی، بکاپ و اجرا                     ║
# ╚══════════════════════════════════════════════════════════╝

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


# ╔══════════════════════════════════════════════════════════╗
# ║                 فصل 1 ⚙️ تنظیمات و ثابت‌ها
# ╚══════════════════════════════════════════════════════════╝
# ============================================================
# 1.1 ⚙️ تنظیمات اولیه و متغیرهای محیطی
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# 🧠 تنظیمات هوش مصنوعی «خر دانا» (Gemini یا هر سرویس دیگه)
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gemini-3.6-flash")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")

# مسیر دیتابیس در /tmp (سرور فقط اینجا اجازه نوشتن دارد)
DB_FILE = "/tmp/kharbot.db"

MIN_BET = 500
START_COINS = 5000
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


# ╔══════════════════════════════════════════════════════════╗
# ║                 فصل 2 🗄️ دیتابیس و مدیریت کاربران
# ╚══════════════════════════════════════════════════════════╝
# ============================================================
# 2.1 🗄️ اتصال و ساخت جداول دیتابیس
# ============================================================

def db_connect():
    try:
        db = sqlite3.connect(DB_FILE, timeout=20)
        db.row_factory = sqlite3.Row
        # ⚡ WAL: خواندن و نوشتن همزمان بدون قفل + نوشتن خیلی سریع‌تر
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.execute("PRAGMA cache_size=-8000")
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
            # 🆕 مهاجرت: ستون‌های جدید (طلسم/جادو/انبار وسایل)
            for _col, _def in [("equipped_talisman", "''"), ("equipped_magic", "''"), ("items", "'[]'")]:
                try:
                    db.execute(f"ALTER TABLE donkeys ADD COLUMN {_col} TEXT DEFAULT {_def}")
                except Exception:
                    pass
            
            # 🏇 رالی خرستان — آمار برد/باخت
            db.execute("""CREATE TABLE IF NOT EXISTS rally (
                user_id INTEGER PRIMARY KEY,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0)""")
            
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
            
            # 🏆 لیگ هفتگی — سکه‌های کسب‌شده این هفته
            db.execute("""CREATE TABLE IF NOT EXISTS league (
                user_id INTEGER PRIMARY KEY,
                earned INTEGER DEFAULT 0)""")
            db.commit()
            # مهاجرت: ستون‌های جدید (اگر دیتابیس قدیمی باشد)
            existing = {r[1] for r in db.execute("PRAGMA table_info(users)").fetchall()}
            for col in ["last_work", "last_wheel", "last_rob", "last_fortune", "sound_count",
                        "bank_balance", "bank_last", "insurance_until"]:
                if col not in existing:
                    db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
            db.commit()
        logger.info(f"✅ دیتابیس در {DB_FILE} راه‌اندازی شد")
    except sqlite3.OperationalError as e:
        logger.error(f"❌ خطا در راه‌اندازی دیتابیس: {e}")
        raise

# ============================================================
# 2.2 👥 مدیریت کاربران (سکه/سطح/ثبت)
# ============================================================

# ⚡ کش: هر چت فقط هر ۱۰ دقیقه یه بار توی DB آپدیت می‌شه (نه با هر پیام!)
_CHAT_TRACKED = {}

def track_chat(chat):
    """ثبت گروه/پی‌وی برای پیام همگانی"""
    if not chat:
        return
    now = time.time()
    if now - _CHAT_TRACKED.get(chat.id, 0) < 600:
        return  # همین ۱۰ دقیقه پیش ثبت شده
    _CHAT_TRACKED[chat.id] = now
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

# ⚡ کش: اسم هر کاربر فقط هر ۱۰ دقیقه یه بار آپدیت می‌شه (نه با هر پیام!)
_USER_ENSURED = {}

def ensure_user(user_id, name="کاربر"):
    now_t = time.time()
    cached = _USER_ENSURED.get(user_id)
    if cached and now_t - cached[0] < 600 and cached[1] == name:
        return  # همین چند دقیقه پیش با همین اسم ثبت شده
    now = int(now_t)
    with closing(db_connect()) as db:
        row = db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            db.execute("INSERT INTO users (user_id, name, coins, created_at) VALUES (?, ?, ?, ?)",
                      (user_id, name[:100], START_COINS, now))
            db.execute("INSERT INTO donkeys (user_id) VALUES (?)", (user_id,))
        else:
            db.execute("UPDATE users SET name = ? WHERE user_id = ?", (name[:100], user_id))
        db.commit()
    _USER_ENSURED[user_id] = (now_t, name)
    if len(_USER_ENSURED) > 5000:
        cutoff = now_t - 600
        for k in [k for k, v in _USER_ENSURED.items() if v[0] < cutoff][:2000]:
            _USER_ENSURED.pop(k, None)

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

def add_coins(user_id, amount, league=True):
    """league=False برای انتقال/کادو — که تقلب لیگ نشه"""
    if user_id == BOT_ID: return True  # خر بات پول لازم نداره
    if amount <= 0: return False
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
        if league:
            db.execute("""INSERT INTO league (user_id, earned) VALUES (?, ?)
                          ON CONFLICT(user_id) DO UPDATE SET earned = earned + ?""",
                      (user_id, amount, amount))
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

def record_loss(user_id, lost=0):
    """ثبت باخت + جبران خودکار بیمه (۲۰٪ باخت در همه بازی‌ها — بدون سقف)"""
    if user_id == BOT_ID: return 0
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET losses = losses + 1 WHERE user_id = ?", (user_id,))
        db.commit()
    update_level(user_id)
    try:
        return insurance_refund(user_id, lost)
    except NameError:
        return 0

def update_level(user_id):
    """⭐ سطح بر اساس ثروت کل (جیب + بانک) — متناسب با اقتصاد جدید"""
    with closing(db_connect()) as db:
        row = db.execute("SELECT coins, COALESCE(bank_balance,0) as bank FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row: return
        wealth = (row["coins"] or 0) + (row["bank"] or 0)
        if wealth < 15000: level = 1
        elif wealth < 35000: level = 2
        elif wealth < 75000: level = 3
        elif wealth < 150000: level = 4
        elif wealth < 300000: level = 5
        elif wealth < 600000: level = 6
        elif wealth < 1200000: level = 7
        elif wealth < 2500000: level = 8
        elif wealth < 6000000: level = 9
        else: level = 10
        db.execute("UPDATE users SET level = ? WHERE user_id = ?", (level, user_id))
        db.commit()


# ╔══════════════════════════════════════════════════════════╗
# ║                 فصل 3 👤 پروفایل و لقب‌ها
# ╚══════════════════════════════════════════════════════════╝
# ============================================================
# 3.1 🏅 سیستم لقب‌ها
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
# 3.2 👤 پروفایل
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
    
    # 📊 نوار پیشرفت سطح
    level_bar = "🟩" * level + "⬜" * (10 - level)
    wealth = (u["coins"] or 0) + (u["bank_balance"] or 0)
    total_games = (u["wins"] or 0) + (u["losses"] or 0)
    winrate = f"{u['wins']*100//total_games}٪" if total_games else "—"
    
    msg = (
        f"👤 **{esc_md(u['name'])}**\n"
        f"{title}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🆔 `{u['user_id']}`\n"
        f"⭐ سطح {level}  {level_bar}\n"
        f"━━━━━━━━━━━━━━\n"
        f"💵 جیب: **{u['coins']:,}**\n"
        f"🏦 بانک: **{(u['bank_balance'] or 0):,}**\n"
        f"💎 ثروت کل: **{wealth:,}** {CURRENCY_NAME}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🎮 بازی‌ها: {total_games}  •  🏆 {u['wins']} برد  •  💀 {u['losses']} باخت\n"
        f"📈 نرخ برد: {winrate}\n"
    )
    
    # وضعیت‌های ویژه
    badges = []
    try:
        if has_insurance(user_id):
            badges.append("🛡️ بیمه فعال")
        if get_loan(user_id) > 0:
            badges.append(f"💳 بدهی: {get_loan(user_id):,}")
        if get_opium_boost(user_id):
            badges.append("😵‍💫 نئشه!")
        if is_addict_hungover(user_id):
            badges.append("🥶 خمار")
        if get_setting(f"opium_addict_{user_id}", "0") == "1":
            badges.append("💀 خر خراب")
    except Exception:
        pass
    if badges:
        msg += f"━━━━━━━━━━━━━━\n📌 " + "  •  ".join(badges) + "\n"
    
    if equipped_parts:
        msg += f"━━━━━━━━━━━━━━\n🎽 **تیپ خر:**  " + " ".join(p.split(" ")[0] for p in equipped_parts) + "\n"
        msg += "      " + " • ".join(p.split(" ", 1)[1] for p in equipped_parts[:3])
        if len(equipped_parts) > 3:
            msg += f" و {len(equipped_parts)-3} قلم دیگه"
        msg += "\n"
    
    if babies:
        income = babies_daily_income(babies)
        baby_icons = " ".join(BABY_LEVELS.get(b.get("level",1), BABY_LEVELS[1])["emoji"] for b in babies)
        msg += (f"━━━━━━━━━━━━━━\n"
                f"👶 کره‌خرها: {baby_icons}  ({len(babies)}/{MAX_BABIES})\n"
                f"      سود روزانه: **{income:,}** {CURRENCY_NAME}\n")
    
    return msg


# ╔══════════════════════════════════════════════════════════╗
# ║                 فصل 4 💰 درآمدها
# ╚══════════════════════════════════════════════════════════╝
# ============================================================
# 4.1 🎁 جایزه روزانه
# ============================================================

DAILY_COOLDOWN = 86400
DAILY_MIN = 500
DAILY_MAX = 1500

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
    _b = get_equipped_buffs(user.id)
    if _b["daily"] > 0:  # 🐴 زین: +٪ جایزه روزانه
        extra_b = int(reward * _b["daily"] / 100)
        reward += extra_b
        bonus += f"\n🐴 باف زین: **+{_b['daily']}٪** ({extra_b:,}+)"
    if random.random() < 0.10:
        extra = random.randint(50, 200)
        reward += extra
        bonus += f"\n🎉 **جایزه ویژه!** +{extra} {CURRENCY_NAME}"
    
    # 🐣 سود کره‌خرها الان از پنل کره‌خرها برداشت می‌شه (دستور: کره‌خرها)
    babies = load_babies(u)
    baby_line_txt = ""
    if babies:
        baby_line_txt = f"\n🐣 یادت نره سود کره‌خرهات رو از پنل «کره‌خرها» برداری!"
    
    total = reward
    add_coins(user.id, total)
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET last_daily = ? WHERE user_id = ?", (now, user.id))
        db.commit()
    
    await update.message.reply_text(
        f"🎁 **جایزه روزانه رسید!**\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 {esc_md(user.first_name)} عزیز\n"
        f"💰 جایزه امروز: **{reward:,}** {CURRENCY_NAME}"
        f"{bonus}"
        f"{baby_line_txt}\n"
        f"\n📅 فردا هم یادت نره! 🐴✨",
        parse_mode="Markdown"
    )

# ============================================================
# 4.2 🔊 صدای خر (۱۶ صدا + رتبه عرعر)
# ============================================================

# 💰 همه صداها امتیاز یکسان دارن: شانسی از ۵۰ تا ۵۰۰!
SOUND_MIN = 150
SOUND_MAX = 1200
SOUND_RARE_CHANCE = 0.07  # شانس عر طلایی

SOUND_KEYWORDS = {
    "عر":         {"sound": "🔊 عَر عَر عَر",                       "desc": "صدای معمولی خر"},
    "عرعر":       {"sound": "📢 عَرعَرعَرعَرعَر",                    "desc": "رگبار عرعر"},
    "عرر":        {"sound": "🌬️ عَررررررررررر",                    "desc": "عر کشیده و سوزناک"},
    "ترک":        {"sound": "💔 عَر-عَر-عَر... تِرِک!",              "desc": "صدای شکسته و دلخراش"},
    "تورک":       {"sound": "🌀 عَرررر بۆیله عَرررر",               "desc": "عر با لهجه تورکی"},
    "عراپرا":     {"sound": "🎵🕺 عَرا-پَرا عَرا-پَرا",             "desc": "عر ریتمیک رقصیدنی"},
    "عرملایم":    {"sound": "🎻 عـِـر... عـِـر...",                  "desc": "عر رمانتیک زیر نور ماه"},
    "عرجنگی":     {"sound": "⚔️🔥 عَ‌ررررر!!!",                     "desc": "نعره جنگی خر وحشی"},
    "عراپرایی":   {"sound": "🎭🎶 عَ‌ره‌ره‌ره‌ریرا~",                "desc": "عر اپرایی سوپرانو"},
    "عرغمگین":    {"sound": "😢💧 عـِـر...",                        "desc": "عر غمگین بارونی"},
    "عرشاد":      {"sound": "🎉🥳 عَر عَر هورااا!",                  "desc": "عر جشن و پایکوبی"},
    "عرخفن":      {"sound": "😎🕶️ عَر. فقط همین.",                "desc": "عر باکلاس و لاکچری"},
    "عرتایید":    {"sound": "👍✅ عَر!",                            "desc": "مُهر تایید خر — یعنی آره، موافقم!"},
    "عرمخالفت":   {"sound": "👎❌ عَر عَر!",                        "desc": "وتوی خری — یعنی نه، عمراً!"},
    "عرلری":      {"sound": "🏔️💪 عَر کاکو عَرررر!",               "desc": "عر با لهجه غلیظ لری"},
    "عرکنکوری":   {"sound": "📚😰 عَر... عَر...",                   "desc": "عر پراسترس شب کنکور"}
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

SOUND_COOLDOWN = 300

async def donkey_sound(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip().replace(" ", "").replace("\u200c", "")
    ensure_user(user.id, user.first_name)
    u = get_user(user.id)
    if not u: return
    
    last_sound = u["last_sound"] or 0
    now = int(time.time())
    
    _b = get_equipped_buffs(user.id)
    _cd = int(SOUND_COOLDOWN * (100 - _b["cooldown"]) / 100)  # 👟 نعل
    if now - last_sound < _cd:
        return  # 🔇 کول‌داون: بی‌صدا نادیده بگیر
    
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
    if _b["sound"] > 0:  # 👕 لباس: +٪ درآمد عرعر
        _eb = int(reward * _b["sound"] / 100)
        reward += _eb
        bonus += f"\n👕 باف لباس: **+{_b['sound']}٪**"
    
    if random.random() < SOUND_RARE_CHANCE:
        extra = random.randint(100, 300)
        reward += extra
        bonus = f"\n🌟 **عر طلایی!** پژواکش کل طویله رو لرزوند! +{extra} {CURRENCY_NAME}"
    
    # 💨 نئشگی تریاک: پاداش عر × ضریب پک (۱.۵ تا ۳!)
    try:
        if get_opium_boost(user.id):
            _m = get_opium_mult(user.id)
            reward = int(reward * _m)
            bonus += f"\n😵‍💫 نئشگی: پاداش **×{_m:g}** شد!"
    except Exception:
        pass
    
    if reward > 0:
        add_coins(user.id, reward)
    
    sound_count = (u["sound_count"] or 0) + 1
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET last_sound = ?, sound_count = ? WHERE user_id = ?",
                  (now, sound_count, user.id))
        db.commit()
    
    rank = get_sound_rank(sound_count)
    
    await update.message.reply_text(
        f"🔊 **{sound_info['sound']}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"📝 {sound_info['desc']}\n"
        f"👤 {esc_md(user.first_name)} عر کشید!\n\n"
        f"💰 پاداش: **+{reward:,}** {CURRENCY_NAME}"
        f"{bonus}\n\n"
        f"🏅 {rank}  •  🔢 عر شماره {sound_count}",
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
    "\n\n⏳ هر ۵ دقیقه یک بار می‌تونی صدا بدی."
)

# ============================================================
# 4.3 💼 کار کردن
# ============================================================

WORK_COOLDOWN = 1800  # هر ۳۰ دقیقه

WORK_JOBS = [
    {"name": "🌾 گاری‌کشی توی مزرعه", "min": 150, "max": 450},
    {"name": "🧱 آجرکشی سر ساختمون", "min": 180, "max": 500},
    {"name": "🚕 مسافرکشی با گاری", "min": 120, "max": 600},
    {"name": "🎪 بازیگری توی سیرک", "min": 100, "max": 750},
    {"name": "📦 باربری بازار", "min": 200, "max": 480},
    {"name": "🎨 مدل نقاشی نقاش‌های خیابونی", "min": 80, "max": 650},
    {"name": "🏇 مسابقه دو با اسب‌ها", "min": 50, "max": 900},
    {"name": "🧹 نظافت طویله همسایه", "min": 250, "max": 420}
]

WORK_FAILS = [
    "😴 وسط کار خوابت برد و صاحب‌کار بیرونت کرد!",
    "🦵 جفتک انداختی به مشتری و اخراج شدی!",
    "🛒💥 گاری چپ شد و همه بارش ریخت!",
    "🌾😋 به جای کار، رفتی یونجه خوردی!"
]

async def work_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    u = get_user(user.id)
    if not u: return
    
    now = int(time.time())
    last_work = u["last_work"] or 0
    
    buffs = get_equipped_buffs(user.id)
    cd = int(WORK_COOLDOWN * (100 - buffs["cooldown"]) / 100)  # 👟 نعل: کول‌داون کمتر
    if now - last_work < cd:
        remaining = cd - (now - last_work)
        await update.message.reply_text(
            f"😮‍💨🐴 هنوز خسته‌ای! {remaining // 60} دقیقه دیگه بیا سر کار"
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
    boost_note = ""
    if buffs["work"] > 0:  # 🎩 کلاه: +٪ دستمزد
        bonus = int(wage * buffs["work"] / 100)
        wage += bonus
        boost_note += f"\n🎩 باف کلاه: **+{buffs['work']}٪** ({bonus:,}+)"
    try:
        if get_opium_boost(user.id):
            _m = get_opium_mult(user.id)
            wage = int(wage * _m)
            boost_note += f"\n😵‍💫 نئشگی: دستمزد **×{_m:g}** شد!"
        elif is_addict_hungover(user.id):
            wage //= 2
            boost_note += "\n🥶 خماری: دستمزدت **نصف** شد! برو ترک کن..."
    except Exception:
        pass
    add_coins(user.id, wage)
    await update.message.reply_text(
        f"💼 **{job['name']}**\n━━━━━━━━━━━━━━\n"
        f"👤😮‍💨 {esc_md(user.first_name)} حسابی جون کند...\n"
        f"💰 دستمزد: **+{wage:,}** {CURRENCY_NAME}{boost_note}\n\n"
        f"⏰ نیم ساعت دیگه دوباره بیا سر کار!",
        parse_mode="Markdown"
    )

# ============================================================
# 4.4 🎡 گردونه شانس
# ============================================================

WHEEL_COOLDOWN = 10800  # هر ۳ ساعت
WHEEL_PRIZES = [
    (15, "💨 هیچی! گردونه خالی چرخید", 0),
    (25, "🪙 یه مشت سکه", 150),
    (22, "💰 کیسه سکه", 400),
    (18, "💎 جواهر کوچیک", 800),
    (13, "🏆 گنج طویله", 1500),
    (5,  "👑 جکپات سلطنتی", 4000),
    (2,  "🌟 گنج افسانه‌ای خرستان", 10000)
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
    
    # 🍀 جادو: شانس بهتر — رول به سمت جوایز بالاتر هل داده می‌شه
    _luck = get_equipped_buffs(user.id)["luck"]
    roll = random.uniform(0, 100)
    if _luck > 0:
        roll = min(100.0, roll + _luck)  # جوایز بهتر آخر لیستن
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
# 4.5 🦹 دزدی از کاربران
# ============================================================

ROB_COOLDOWN = 7200  # هر ۲ ساعت
ROB_SUCCESS_CHANCE = 0.40
ROB_FINE_PERCENT = 0.05

ROB_SUCCESS_TEXTS = [
    "🌙🏃 نصفه‌شب یواشکی رفتی توی طویله‌اش و زدی به چاک!",
    "🎭 با نقاب خرکی سر گردنه رو زدی!",
    "🌾🤏 وقتی داشت یونجه می‌خورد جیبش رو زدی!"
]
ROB_FAIL_TEXTS = [
    "🪏💨 صاحب طویله با بیل دنبالت کرد!",
    "🪣💥 پات به سطل گیر کرد و افتادی، همه بیدار شدن!",
    "🐕⛓️ سگ نگهبان گرفتت! جریمه شدی!"
]

async def rob_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    
    if not update.message.reply_to_message:
        await update.message.reply_text("🦹 روی پیام کسی که می‌خوای ازش بدزدی **ریپلی** بزن و بنویس `دزدی`", parse_mode="Markdown")
        return
    
    target = update.message.reply_to_message.from_user
    if target.id == user.id:
        await update.message.reply_text("❌😂 از خودت می‌خوای بدزدی؟!")
        return
    if target.is_bot:
        await update.message.reply_text("❌🤖 از ربات نمی‌شه دزدید!")
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
    
    if t["coins"] < 500:
        await update.message.reply_text(f"😅 {esc_md(target.first_name)} انقدر فقیره که چیزی برای دزدیدن نداره!")
        return
    
    # 🛡️ هدف بیمه داره؟ دزدی ناکام!
    if has_insurance(target.id):
        await update.message.reply_text(
            f"🛡️ **دزدی ناکام!**\n"
            f"{esc_md(target.first_name)} بیمه خرستان داره — نگهبانای بیمه گرفتنت! 🚨\n"
            f"😏 این دفعه جریمه نشدی، ولی سراغ بیمه‌شده‌ها نرو!",
            parse_mode="Markdown")
        return
    
    # 🛡️ طلسم هدف؟ شانس دفع دزد!
    _tb = get_equipped_buffs(target.id)
    if _tb["shield"] > 0 and random.uniform(0, 100) < _tb["shield"]:
        await update.message.reply_text(
            f"🧿 **طلسم کار کرد!**\n"
            f"طلسم {esc_md(target.first_name)} درخشید و تو رو پس زد! ✨\n"
            f"😵 دست خالی برگشتی...",
            parse_mode="Markdown")
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET last_rob = ? WHERE user_id = ?", (now, user.id))
            db.commit()
        return
    
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET last_rob = ? WHERE user_id = ?", (now, user.id))
        db.commit()
    
    # 🎀 اکسسوری دزد: +٪ شانس موفقیت
    _rb = get_equipped_buffs(user.id)
    rob_chance = ROB_SUCCESS_CHANCE + _rb["rob"] / 100
    if random.random() < rob_chance:
        # موفق: ۳ تا ۱۰ درصد پول هدف
        loot = max(10, int(t["coins"] * random.uniform(0.03, 0.10)))
        loot = min(loot, 6000)  # سقف دزدی
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (loot, target.id))
            db.commit()
        add_coins(user.id, loot)
        story = random.choice(ROB_SUCCESS_TEXTS)
        await update.message.reply_text(
            f"🦹 **دزدی موفق!**\n━━━━━━━━━━━━━━\n"
            f"{story}\n\n"
            f"💰🏃💨 {esc_md(user.first_name)} مبلغ **{loot}** {CURRENCY_NAME} از {esc_md(target.first_name)} دزدید!",
            parse_mode="Markdown"
        )
    else:
        fine = max(20, int(u["coins"] * ROB_FINE_PERCENT))
        fine = min(fine, 3000)
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (fine, user.id))
            db.commit()
        story = random.choice(ROB_FAIL_TEXTS)
        await update.message.reply_text(
            f"🚨 **دزدی ناموفق!**\n━━━━━━━━━━━━━━\n"
            f"{story}\n\n"
            f"💸😭 {esc_md(user.first_name)} جریمه شد: **-{fine}** {CURRENCY_NAME}",
            parse_mode="Markdown"
        )

# ============================================================
# 4.6 🔮 فال خرستان
# ============================================================

FORTUNE_COOLDOWN = 21600  # هر ۶ ساعت

FORTUNES = [
    ("🌟 امروز روز شانسته! یه عر بلند بکش!", 200),
    ("💰 ثروت بزرگی در راهه... شاید هم یونجه باشه!", 120),
    ("❤️ یک خر جذاب به زندگیت وارد می‌شه!", 80),
    ("🎲 امروز توی قمار دستت داغه! (شایدم نه 😏)", 100),
    ("🐴 خر درونت رو آزاد کن، موفقیت نزدیکه!", 140),
    ("🌈 بعد از هر عرعری، رنگین‌کمونی هست!", 60),
    ("⚠️ مواظب باش! یکی می‌خواد ازت بدزده!", 160),
    ("🦄 تو فقط یه خر نیستی، یه تک‌شاخ در حال پیشرفتی!", 160),
    ("📿 ستاره‌ها می‌گن: کمتر جفتک بنداز، بیشتر پس‌انداز کن!", 80),
    ("🔮 عدد شانس امروزت: عر!", 120)
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
    _luck = get_equipped_buffs(user.id)["luck"]
    luck_note = ""
    if _luck > 0 and coins > 0:  # 🍀 جادو: برکت فال بیشتر
        _lb = int(coins * _luck / 100)
        coins += _lb
        luck_note = f"\n🍀 باف جادو: **+{_luck}٪** برکت!"
    add_coins(user.id, coins)
    
    await update.message.reply_text(
        f"🔮 **فال خرستان**\n━━━━━━━━━━━━━━\n"
        f"👤 {esc_md(user.first_name)} عزیز:\n\n"
        f"«{text_f}»\n\n"
        f"🎁 برکت فال: **+{coins}** {CURRENCY_NAME}{luck_note}",
        parse_mode="Markdown"
    )

# ============================================================
# 4.7 💸 انتقال سکه (ریپلی/آیدی/اسم + مالیات)
# ============================================================

TRANSFER_MIN = 50
TRANSFER_MAX = 100000
TRANSFER_TAX = 0.10   # 💸 ۱۰٪ مالیات انتقال

def find_user_by_ref(ref):
    """پیدا کردن کاربر با آیدی عددی یا یوزرنیم/اسم — خروجی: ردیف کاربر یا None"""
    ref = ref.strip()
    with closing(db_connect()) as db:
        # آیدی عددی
        num = ref.translate(FA_DIGITS)
        if num.isdigit():
            return db.execute("SELECT * FROM users WHERE user_id = ?", (int(num),)).fetchone()
        # یوزرنیم یا اسم (بدون @) — جستجو توی اسم‌های ثبت‌شده
        name = ref.lstrip("@")
        row = db.execute("SELECT * FROM users WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        if row:
            return row
        # جستجوی جزئی
        return db.execute("SELECT * FROM users WHERE name LIKE ? COLLATE NOCASE LIMIT 1", (f"%{name}%",)).fetchone()

async def transfer_command(update: Update, context: ContextTypes.DEFAULT_TYPE, amount, target_ref=None):
    """💸 انتقال تی‌تاپ — با ریپلی یا با آیدی عددی/اسم: «انتقال 100 123456» یا «انتقال 100 @علی»"""
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    
    target_id = None
    target_name = None
    
    if update.message.reply_to_message:
        # حالت ۱: ریپلی
        target = update.message.reply_to_message.from_user
        if target.is_bot:
            await update.message.reply_text("❌🤖 ربات پول نمی‌خواد!")
            return
        ensure_user(target.id, target.first_name)
        target_id, target_name = target.id, target.first_name
    elif target_ref:
        # حالت ۲: آیدی عددی یا اسم/یوزرنیم
        row = find_user_by_ref(target_ref)
        if not row:
            await update.message.reply_text(
                f"❌ کاربری با «{esc_md(target_ref)}» پیدا نشد!\n"
                f"💡 فقط کسایی که قبلاً با ربات کار کردن قابل پیدا شدنن.\n"
                f"🔢 آیدی عددی هر کس توی «👑 دیتابیس بازیکنان» یا با ریپلی + پروفایل معلومه.",
                parse_mode="Markdown")
            return
        target_id, target_name = row["user_id"], row["name"]
    else:
        await update.message.reply_text(
            "💸 **روش‌های انتقال:**\n"
            "1️⃣ ریپلی روی پیام طرف + `انتقال 100`\n"
            "2️⃣ با آیدی عددی: `انتقال 100 123456789`\n"
            "3️⃣ با اسم: `انتقال 100 @علی`",
            parse_mode="Markdown")
        return
    
    if target_id == user.id:
        await update.message.reply_text("❌😂 به خودت می‌خوای پول بدی؟!")
        return
    if target_id == BOT_ID:
        await update.message.reply_text("❌🤖 خر بات پول نمی‌خواد!")
        return
    
    if amount < TRANSFER_MIN or amount > TRANSFER_MAX:
        await update.message.reply_text(f"❌ مبلغ باید بین {TRANSFER_MIN} تا {TRANSFER_MAX:,} باشه!")
        return
    
    if not remove_coins(user.id, amount):
        u = get_user(user.id)
        await update.message.reply_text(f"❌ موجودی کافی نداری! داری: {u['coins']:,} {CURRENCY_NAME}")
        return
    
    # 👔 کروات: -٪ مالیات انتقال
    _tax_rate = max(0.0, TRANSFER_TAX - get_equipped_buffs(user.id)["tax"] / 100)
    tax = int(amount * _tax_rate)
    received = amount - tax
    add_coins(target_id, received, league=False)
    await update.message.reply_text(
        f"💸 **انتقال موفق!**\n━━━━━━━━━━━━━━\n"
        f"👤 {esc_md(user.first_name)} ⬅️ {esc_md(target_name)}\n"
        f"💰 مبلغ ارسالی: {amount:,} {CURRENCY_NAME}\n"
        f"🧾 مالیات انتقال ({int(_tax_rate*100)}٪): -{tax:,}\n"
        f"✅ رسید به دستش: **{received:,}** {CURRENCY_NAME}\n\n"
        f"🤝 دمت گرم، رفاقت یعنی این!",
        parse_mode="Markdown"
    )


# ╔══════════════════════════════════════════════════════════╗
# ║                 فصل 5 🏦 اقتصاد (بانک/وام/لیگ/تریاک/بیمه)
# ╚══════════════════════════════════════════════════════════╝
# ============================================================
# 5.1 🏦 بانک (سپرده/سود روزانه/واریز و برداشت)
# ============================================================

BANK_INTEREST = 0.20        # ۲۰٪ سود روزانه
BANK_INTEREST_CAP = 10**12  # بدون سقف عملی
BANK_MIN_DEPOSIT = 500
BANK_MAX_BALANCE = 10**15   # ♾️ بدون سقف — هر چقدر بخوای بریز!

def bank_pending_interest(user_id):
    """💹 سود آماده برداشت — فقط «یک روز» سود، مرکب نمی‌شه!
    خروجی: (سود قابل برداشت, آیا ۲۴ ساعت گذشته)"""
    u = get_user(user_id)
    if not u: return 0, False
    balance = u["bank_balance"] or 0
    last = u["bank_last"] or 0
    now = int(time.time())
    if balance <= 0:
        return 0, False
    if not last:
        # 🛟 تایمر گم شده (مثلاً بعد از ری‌استارت سرور بدون بازیابی) —
        # به نفع کاربر: سود همین الان آماده برداشته!
        last = now - 86400
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET bank_last = ? WHERE user_id = ?", (last, user_id))
            db.commit()
    if now - last < 86400:
        return 0, False
    # ⚠️ فقط سود یک روز — دیر بیای، سود روزهای قبل سوخته!
    return min(int(balance * BANK_INTEREST), BANK_INTEREST_CAP), True

def bank_apply_interest(user_id):
    """(سازگاری با کد قدیمی) — دیگه خودکار واریز نمی‌کنه، فقط صفر برمی‌گردونه"""
    return 0

async def bank_claim_interest(update, context):
    """💹 برداشت سود روزانه — دستور: «سود»"""
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    u = get_user(user.id)
    balance = u["bank_balance"] or 0
    if balance <= 0:
        await update.message.reply_text("🏦 حساب بانکیت خالیه! اول `واریز 1000` کن.", parse_mode="Markdown")
        return
    interest, ready = bank_pending_interest(user.id)
    now = int(time.time())
    last = u["bank_last"] or now
    if not ready:
        remaining = 86400 - (now - last)
        h, mnt = remaining // 3600, (remaining % 3600) // 60
        await update.message.reply_text(
            f"⏳ سودت هنوز نرسیده! {h} ساعت و {mnt} دقیقه دیگه بیا.\n"
            f"💹 سود فردا: ~{min(int(balance * BANK_INTEREST), BANK_INTEREST_CAP):,} {CURRENCY_NAME}")
        return
    add_coins(user.id, interest)
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET bank_last = ? WHERE user_id = ?", (now, user.id))
        db.commit()
    await update.message.reply_text(
        f"💹 **سود بانکی برداشت شد!**\n━━━━━━━━━━━━━━\n"
        f"💰 +{interest:,} {CURRENCY_NAME} به جیبت!\n"
        f"🏦 سپرده: {balance:,} (دست‌نخورده)\n\n"
        f"⚠️ یادت نره: سود روزانه‌ست — هر روز «سود» بزن وگرنه می‌سوزه!",
        parse_mode="Markdown")

def bank_text(user_id):
    u = get_user(user_id)
    balance = u["bank_balance"] or 0
    interest, ready = bank_pending_interest(user_id)
    loan = get_loan(user_id)
    msg = (
        f"🏦 **بانک خرستان**\n━━━━━━━━━━━━━━\n"
        f"👤 {esc_md(u['name'])}\n"
        f"💰 موجودی حساب: **{balance:,}** {CURRENCY_NAME}\n"
        f"💵 پول نقد (جیبت): {u['coins']:,} {CURRENCY_NAME}\n"
    )
    if ready and interest > 0:
        msg += f"\n💹 **سود آماده برداشته:** +{interest:,} — بزن `سود`! 🎉\n"
    if loan > 0:
        msg += f"\n💳 **بدهی وام:** {loan:,} {CURRENCY_NAME} — تسویه: `تسویه وام`\n"
    msg += (
        f"\n📈 سود روزانه: **{int(BANK_INTEREST*100)}٪**\n"
        f"⚠️ سود باید **هر روز** با دستور `سود` برداشت شه — برنداری می‌سوزه!\n"
        f"🛡️ پول توی بانک از **دزدی در امانه!**\n"
        f"♾️ بدون سقف — هر چقدر بخوای واریز کن!\n\n"
        f"📋 **دستورات:**\n"
        f"💰 `واریز 1000` یا `واریز همه` — پول بذار توی بانک\n"
        f"💵 `برداشت 1000` — پول بردار (یا `برداشت همه`)\n"
        f"💹 `سود` — برداشت سود روزانه\n"
        f"💳 `وام 5000` (با ریپلی روی ضامن) — وام تا {LOAN_MAX:,}\n"
        f"✅ `تسویه وام` — پرداخت بدهی\n"
    )
    return msg

async def bank_deposit(update, context, amount):
    user = update.effective_user
    bank_apply_interest(user.id)
    u = get_user(user.id)
    balance = u["bank_balance"] or 0
    if amount < BANK_MIN_DEPOSIT:
        await update.message.reply_text(f"❌ حداقل واریز {BANK_MIN_DEPOSIT} {CURRENCY_NAME}ه!")
        return
    if not remove_coins(user.id, amount):
        await update.message.reply_text(f"❌ انقدر پول نقد نداری! جیبت: {u['coins']:,} {CURRENCY_NAME}")
        return
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET bank_balance = COALESCE(bank_balance,0) + ? WHERE user_id = ?", (amount, user.id))
        db.commit()
    u = get_user(user.id)
    await update.message.reply_text(
        f"🏦 **واریز موفق!**\n💰 +{amount:,} {CURRENCY_NAME}\n"
        f"📊 موجودی حساب: {u['bank_balance']:,} | جیب: {u['coins']:,}\n"
        f"💹 از فردا روزی {int(BANK_INTEREST*100)}٪ سود می‌گیری!",
        parse_mode="Markdown")

async def bank_withdraw(update, context, amount_str):
    user = update.effective_user
    bank_apply_interest(user.id)
    u = get_user(user.id)
    balance = u["bank_balance"] or 0
    if balance <= 0:
        await update.message.reply_text("🏦 حسابت خالیه! اول `واریز 1000` کن.", parse_mode="Markdown")
        return
    if amount_str in ["همه", "کل", "all"]:
        amount = balance
    else:
        amount = int(amount_str)
        if amount <= 0 or amount > balance:
            await update.message.reply_text(f"❌ موجودی حسابت: {balance:,} {CURRENCY_NAME}")
            return
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET bank_balance = bank_balance - ? WHERE user_id = ?", (amount, user.id))
        db.commit()
    add_coins(user.id, amount, league=False)
    u = get_user(user.id)
    await update.message.reply_text(
        f"🏦 **برداشت موفق!**\n💵 +{amount:,} {CURRENCY_NAME} به جیبت\n"
        f"📊 حساب: {u['bank_balance']:,} | جیب: {u['coins']:,}",
        parse_mode="Markdown")

# ============================================================
# 5.2 💳 وام بانکی (ضامن + قسط خودکار)
# ============================================================

LOAN_MAX = 30000
LOAN_NEED_BELOW = 15000      # فقط وقتی پول نقد زیر این باشه وام می‌دن
LOAN_GUARANTOR_LEVEL = 2    # حداقل سطح ضامن
LOAN_MIN = 1000
LOAN_DAYS = 10              # 📅 بازپرداخت در ۱۰ قسط روزانه خودکار

# درخواست‌های وام منتظر تایید ضامن: {(chat_id, msg_id): {...}}
LOAN_REQUESTS = {}
LOAN_REQUEST_TTL = 300

def get_loan(user_id):
    return int(get_setting(f"loan_{user_id}", "0") or 0)

def set_loan(user_id, amount):
    set_setting(f"loan_{user_id}", str(max(0, amount)))

def get_loan_info(user_id):
    """اطلاعات وام: (بدهی, ضامن, قسط روزانه, آخرین قسط)"""
    debt = get_loan(user_id)
    guarantor = int(get_setting(f"loan_g_{user_id}", "0") or 0)
    installment = int(get_setting(f"loan_i_{user_id}", "0") or 0)
    last_pay = int(get_setting(f"loan_t_{user_id}", "0") or 0)
    return debt, guarantor, installment, last_pay

def set_loan_info(user_id, debt, guarantor, installment, last_pay):
    set_loan(user_id, debt)
    set_setting(f"loan_g_{user_id}", str(guarantor))
    set_setting(f"loan_i_{user_id}", str(installment))
    set_setting(f"loan_t_{user_id}", str(last_pay))

def clear_loan(user_id):
    set_loan(user_id, 0)
    set_setting(f"loan_g_{user_id}", "0")
    set_setting(f"loan_i_{user_id}", "0")
    set_setting(f"loan_t_{user_id}", "0")

def loan_collect_due(user_id):
    """💸 وصول قسط‌های عقب‌افتاده — روزی یک قسط. نداشت؟ از ضامن! 😂
    خروجی: لیست رویدادها برای گزارش"""
    debt, guarantor, installment, last_pay = get_loan_info(user_id)
    if debt <= 0 or installment <= 0:
        return []
    now = int(time.time())
    if not last_pay:
        set_setting(f"loan_t_{user_id}", str(now))
        return []
    days_due = int((now - last_pay) // 86400)
    if days_due <= 0:
        return []
    events = []
    for _ in range(min(days_due, 15)):
        if debt <= 0:
            break
        due = min(installment, debt)
        u = get_user(user_id)
        if u and (u["coins"] or 0) >= due:
            remove_coins(user_id, due)
            debt -= due
            events.append(("self", due))
        else:
            # 😂 از جیب خود بدهکار هرچی داره، بقیه از ضامن!
            from_self = min(u["coins"] or 0, due) if u else 0
            if from_self > 0:
                remove_coins(user_id, from_self)
            from_g = due - from_self
            if from_g > 0 and guarantor:
                with closing(db_connect()) as db:
                    db.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (from_g, guarantor))
                    db.commit()
            debt -= due
            events.append(("guarantor", due, from_self, from_g))
    if debt <= 0:
        clear_loan(user_id)
    else:
        set_loan(user_id, debt)
        set_setting(f"loan_t_{user_id}", str(last_pay + days_due * 86400))
    return events


async def loan_request(update, context, amount):
    """درخواست وام — با ریپلی روی ضامن"""
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    u = get_user(user.id)
    
    if get_loan(user.id) > 0:
        await update.message.reply_text(
            f"❌ هنوز {get_loan(user.id):,} {CURRENCY_NAME} بدهی داری!\nاول `تسویه وام` کن بعد وام جدید بگیر.",
            parse_mode="Markdown")
        return
    if u["coins"] >= LOAN_NEED_BELOW:
        await update.message.reply_text(
            f"❌ وام فقط به نیازمنداست! تو {u['coins']:,} {CURRENCY_NAME} داری.\n"
            f"(شرط: پول نقد زیر {LOAN_NEED_BELOW:,})")
        return
    if amount < LOAN_MIN or amount > LOAN_MAX:
        await update.message.reply_text(f"❌ مبلغ وام باید بین {LOAN_MIN} تا {LOAN_MAX:,} باشه!")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text(
            f"💳 **درخواست وام**\n"
            f"👉 روی پیام **ضامنت** ریپلی بزن و بنویس: `وام {amount}`\n"
            f"⚠️ ضامن باید حداقل **سطح {LOAN_GUARANTOR_LEVEL}** باشه و تایید کنه.\n"
            f"😈 اگه تسویه نکنی، بدهی از جیب ضامن کم می‌شه!",
            parse_mode="Markdown")
        return
    
    guarantor = update.message.reply_to_message.from_user
    if guarantor.id == user.id:
        await update.message.reply_text("❌ خودت ضامن خودت؟! 😂 یکی دیگه رو پیدا کن.")
        return
    if guarantor.is_bot:
        await update.message.reply_text("❌🤖 ربات ضامن نمی‌شه!")
        return
    ensure_user(guarantor.id, guarantor.first_name)
    g = get_user(guarantor.id)
    if g["level"] < LOAN_GUARANTOR_LEVEL:
        await update.message.reply_text(
            f"❌ ضامنت باید حداقل **سطح {LOAN_GUARANTOR_LEVEL}** باشه!\n"
            f"{esc_md(guarantor.first_name)} الان سطح {g['level']}ه. 🐣",
            parse_mode="Markdown")
        return
    
    sent = await update.message.reply_text(
        f"💳 **درخواست وام!**\n━━━━━━━━━━━━━━\n"
        f"👤 وام‌گیرنده: {esc_md(user.first_name)}\n"
        f"💰 مبلغ: **{amount:,}** {CURRENCY_NAME}\n"
        f"🤝 ضامن: {esc_md(guarantor.first_name)} (سطح {g['level']})\n\n"
        f"⚠️ {esc_md(guarantor.first_name)} عزیز: اگه تسویه نکنه، بدهی از **جیب تو** کم می‌شه!\n"
        f"❓ ضمانت می‌کنی؟ (۵ دقیقه فرصت)",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ ضمانت می‌کنم", callback_data="loan_yes"),
            InlineKeyboardButton("❌ نه بابا!", callback_data="loan_no")
        ]]),
        parse_mode="Markdown")
    
    now = time.time()
    for k in list(LOAN_REQUESTS.keys()):
        if now - LOAN_REQUESTS[k]["time"] > LOAN_REQUEST_TTL:
            LOAN_REQUESTS.pop(k, None)
    LOAN_REQUESTS[(update.effective_chat.id, sent.message_id)] = {
        "borrower": user.id, "guarantor": guarantor.id, "amount": amount, "time": now
    }

async def loan_callback(update, context, query, answer):
    """جواب ضامن — فقط خود ضامن"""
    key = (query.message.chat_id, query.message.message_id)
    req = LOAN_REQUESTS.get(key)
    if not req:
        await query.answer("❌ این درخواست منقضی شده!", show_alert=True)
        try:
            await query.edit_message_text("⌛ درخواست وام منقضی شد.")
        except Exception:
            pass
        return
    uid = query.from_user.id
    if uid != req["guarantor"]:
        if uid == req["borrower"]:
            await query.answer("😅 ضامن باید جواب بده، نه خودت!", show_alert=True)
        else:
            await query.answer("🔒 این درخواست مال تو نیست!", show_alert=True)
        return
    if time.time() - req["time"] > LOAN_REQUEST_TTL:
        LOAN_REQUESTS.pop(key, None)
        await query.answer("⌛ منقضی شد!", show_alert=True)
        await query.edit_message_text("⌛ درخواست وام منقضی شد.")
        return
    
    LOAN_REQUESTS.pop(key, None)
    
    if answer == "no":
        await query.answer("❌ رد شد!")
        await query.edit_message_text(
            f"❌ **ضمانت رد شد!**\n{uname(req['guarantor'])} حاضر نشد ضامن {uname(req['borrower'])} بشه! 😅\n"
            f"🐴 برو یه رفیق باوفاتر پیدا کن", parse_mode="Markdown")
        return
    
    # ✅ تایید — شرایط دوباره چک بشه
    b = get_user(req["borrower"])
    if get_loan(req["borrower"]) > 0 or (b and b["coins"] >= LOAN_NEED_BELOW):
        await query.answer("❌ شرایط وام‌گیرنده تغییر کرده!", show_alert=True)
        await query.edit_message_text("❌ وام رد شد: شرایط وام‌گیرنده دیگه برقرار نیست.")
        return
    
    installment = max(1, req["amount"] // LOAN_DAYS)
    set_loan_info(req["borrower"], req["amount"], req["guarantor"], installment, int(time.time()))
    add_coins(req["borrower"], req["amount"], league=False)
    await query.answer("✅ وام واریز شد!")
    await query.edit_message_text(
        f"💳 **وام پرداخت شد!**\n━━━━━━━━━━━━━━\n"
        f"💰 {req['amount']:,} {CURRENCY_NAME} به جیب {uname(req['borrower'])} واریز شد!\n"
        f"🤝 ضامن: {uname(req['guarantor'])}\n\n"
        f"📅 **بازپرداخت خودکار:** روزی {installment:,} {CURRENCY_NAME} در {LOAN_DAYS} روز\n"
        f"😈 پول نداشته باشه، قسط از جیب **ضامن** کم می‌شه!\n"
        f"📌 تسویه زودتر: `تسویه وام`",
        parse_mode="Markdown")

async def loan_repay(update, context):
    user = update.effective_user
    loan = get_loan(user.id)
    if loan <= 0:
        await update.message.reply_text("✅🐴 تو بدهی نداری! دمت گرم")
        return
    u = get_user(user.id)
    pay = min(loan, u["coins"])
    if pay <= 0:
        await update.message.reply_text(f"❌ پول نقد نداری! بدهیت: {loan:,} {CURRENCY_NAME}")
        return
    remove_coins(user.id, pay)
    if loan - pay <= 0:
        clear_loan(user.id)
    else:
        set_loan(user.id, loan - pay)
    left = get_loan(user.id)
    if left == 0:
        await update.message.reply_text(
            f"🎉 **وام تسویه شد!**\n💸 {pay:,} {CURRENCY_NAME} پرداختی.\nحالا دوباره می‌تونی وام بگیری. آفرین خر خوش‌حساب! 🐴✅",
            parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"💸 {pay:,} پرداخت شد.\n💳 باقی‌مانده بدهی: **{left:,}** {CURRENCY_NAME}",
            parse_mode="Markdown")

# ------------------------------------------------------------
# 🏦 پنل بانک (دکمه شیشه‌ای)
# ------------------------------------------------------------

def bank_panel_keyboard(user_id):
    u = get_user(user_id)
    balance = (u["bank_balance"] or 0) if u else 0
    interest, ready = bank_pending_interest(user_id)
    rows = []
    if ready and interest > 0:
        rows.append([InlineKeyboardButton(f"💹 برداشت سود (+{interest:,})", callback_data="bankp_claim")])
    rows.append([InlineKeyboardButton("💰 واریز", callback_data="bankp_dep"),
                 InlineKeyboardButton("💵 برداشت همه", callback_data="bankp_wd_all")])
    if get_loan(user_id) > 0:
        rows.append([InlineKeyboardButton("💳 تسویه وام", callback_data="bankp_repay")])
    rows.append([InlineKeyboardButton("🔄 بروزرسانی", callback_data="bankp_home"),
                 InlineKeyboardButton("🏠 منو", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def bank_panel_text(user_id):
    u = get_user(user_id)
    balance = u["bank_balance"] or 0
    interest, ready = bank_pending_interest(user_id)
    debt, guarantor, installment, _ = get_loan_info(user_id)
    now = int(time.time())
    last = u["bank_last"] or now
    wealth = (u["coins"] or 0) + balance
    msg = (
        f"🏦 **بانک خرستان**\n"
        f"_شعبه مرکزی طویله — سود روزانه {int(BANK_INTEREST*100)}٪_\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 {esc_md(u['name'])}\n\n"
        f"💰 سپرده: **{balance:,}**\n"
        f"💵 جیب: **{u['coins']:,}**\n"
        f"💎 ثروت کل: **{wealth:,}** {CURRENCY_NAME}\n"
    )
    if balance > 0:
        msg += "━━━━━━━━━━━━━━\n"
        if ready and interest > 0:
            msg += f"💹🎉 سود آماده: **+{interest:,}** — همین الان بردار!\n"
        else:
            remaining = 86400 - (now - last)
            msg += (f"⏳  سود بعدی: **+{min(int(balance*BANK_INTEREST), BANK_INTEREST_CAP):,}**\n"
                    f"      تا {remaining//3600} ساعت و {(remaining%3600)//60} دقیقه دیگه\n")
    if debt > 0:
        msg += ("━━━━━━━━━━━━━━\n"
                f"💳 بدهی وام: **{debt:,}** {CURRENCY_NAME}\n"
                f"📅😈 قسط روزانه: {installment:,} — نداری؟ از ضامن ({uname(guarantor)})!\n")
    msg += (
        "━━━━━━━━━━━━━━\n"
        "⚠️ سود روزانه‌ست — هر روز برداری وگرنه می‌سوزه!\n"
        "🛡️ پول توی بانک از دزدی در امانه\n\n"
        "💬 `واریز 1000` • `واریز همه` • `برداشت 500` • `سود`\n"
        "💳 `وام 5000` (ریپلی روی ضامن) • `تسویه وام`"
    )
    return msg

# ------------------------------------------------------------
# 🛡️ پنل بیمه (دکمه شیشه‌ای)
# ------------------------------------------------------------

def insurance_panel_keyboard(user_id):
    rows = []
    if not has_insurance(user_id):
        rows.append([InlineKeyboardButton(f"🛒 خرید بیمه ({INSURANCE_COST:,} 🪙 / {INSURANCE_DAYS} روز)", callback_data="insp_buy")])
    rows.append([InlineKeyboardButton("🔄 بروزرسانی", callback_data="insp_home"),
                 InlineKeyboardButton("🏠 منو", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def insurance_panel_text(user_id):
    u = get_user(user_id)
    until = u["insurance_until"] or 0
    now = int(time.time())
    msg = (f"🛡️ **بیمه خرستان**\n"
           f"_پشتیبان تو در روزهای بد قمار!_\n"
           f"━━━━━━━━━━━━━━\n"
           f"👤 {esc_md(u['name'])}\n\n")
    if until > now:
        d, h = (until-now)//86400, ((until-now)%86400)//3600
        msg += f"✅ **وضعیت: فعال**\n⏳  اعتبار: {d} روز و {h} ساعت دیگه\n"
    else:
        msg += "❌ **وضعیت: بدون پوشش**\nبا یه کلیک بیمه شو! 👇\n"
    msg += (
        "━━━━━━━━━━━━━━\n"
        "**پوشش بیمه:**\n"
        f"📉 {int(INSURANCE_REFUND*100)}٪ باخت همه بازی‌ها برمی‌گرده — **بدون سقف!**\n"
        f"🦹 دزدها حریفت نمی‌شن!\n"
        "━━━━━━━━━━━━━━\n"
        f"💳 قیمت: **{INSURANCE_COST:,}** {CURRENCY_NAME} / {INSURANCE_DAYS} روز\n"
        f"💬 دستور: `خرید بیمه`"
    )
    return msg


# ============================================================
# 5.3 🚔 سیستم بازداشت
# ============================================================

def get_jail_until(user_id):
    return int(get_setting(f"jail_{user_id}", "0") or 0)

def jail_user(user_id, seconds):
    set_setting(f"jail_{user_id}", str(int(time.time()) + seconds))

def is_jailed(user_id):
    """خروجی: ثانیه‌های باقی‌مانده بازداشت (۰ = آزاد)"""
    until = get_jail_until(user_id)
    now = int(time.time())
    return max(0, until - now)

# ============================================================
# 5.4 🏆 لیگ هفتگی (شنبه تا جمعه ایران)
# ============================================================

IRAN_UTC_OFFSET = 3.5 * 3600  # ایران UTC+3:30
LEAGUE_PRIZES = [200000, 100000, 50000]  # 🥇🥈🥉

def league_week_end_ts():
    """تایم‌استمپ جمعه ۲۳:۵۹:۵۹ همین هفته به وقت ایران"""
    now_ir = time.time() + IRAN_UTC_OFFSET
    tm = time.gmtime(now_ir)
    # weekday: دوشنبه=0 ... جمعه=4، شنبه=5، یکشنبه=6
    # روزهای مونده تا جمعه:
    days_to_friday = (4 - tm.tm_wday) % 7
    # امروز جمعه‌ست؟ همین امروز آخر هفته‌ست
    midnight_ir = now_ir - (tm.tm_hour * 3600 + tm.tm_min * 60 + tm.tm_sec)
    end_ir = midnight_ir + days_to_friday * 86400 + 86399  # جمعه ۲۳:۵۹:۵۹
    return int(end_ir - IRAN_UTC_OFFSET)  # برگردون به UTC

def league_get_end():
    """تاریخ پایان هفته جاری — نبود، بساز و ذخیره کن"""
    end = int(get_setting("league_end", "0") or 0)
    if not end:
        end = league_week_end_ts()
        set_setting("league_end", str(end))
    return end

def league_top(limit=10):
    with closing(db_connect()) as db:
        return db.execute(
            """SELECT l.user_id, l.earned, u.name, u.level FROM league l
               JOIN users u ON u.user_id = l.user_id
               WHERE l.earned > 0 ORDER BY l.earned DESC LIMIT ?""", (limit,)).fetchall()

def league_text(user_id=None):
    end = league_get_end()
    remaining = max(0, end - int(time.time()))
    d, h = remaining // 86400, (remaining % 86400) // 3600
    rows = league_top(10)
    lines = ["⚡ **جدول هفتگی خرستان**",
             "_فعال‌ترین خر هفته کیه؟_",
             "━━━━━━━━━━━━━━",
             f"⏳  پایان: {d} روز و {h} ساعت دیگه (جمعه‌شب)",
             f"🎁 🥇 {LEAGUE_PRIZES[0]:,}  •  🥈 {LEAGUE_PRIZES[1]:,}  •  🥉 {LEAGUE_PRIZES[2]:,}",
             "━━━━━━━━━━━━━━"]
    if not rows:
        lines.append("\n🦗 هنوز خبری نیست...\nبرو بازی کن، کار کن، عر بزن — صدرنشین شو! 🐴")
    else:
        for i, r in enumerate(rows, 1):
            medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f" {i}."
            lines.append(f"{medal}  {esc_md(r['name'])}  ⚡ **{r['earned']:,}**")
    if user_id:
        with closing(db_connect()) as db:
            me = db.execute("SELECT earned FROM league WHERE user_id = ?", (user_id,)).fetchone()
            if me and me["earned"] > 0:
                rank = db.execute("SELECT COUNT(*)+1 as r FROM league WHERE earned > ?", (me["earned"],)).fetchone()["r"]
                lines.append(f"━━━━━━━━━━━━━━\n👤 رتبه تو: **#{rank}**  ⚡ {me['earned']:,}")
    lines.append("\n💡 امتیاز فقط از کار و فعالیت (کار/روزانه/سود/عرعر...) — قمار حساب نیست!")
    return "\n".join(lines)

def leaderboard_choice_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏆 جدول کلی", callback_data="lb_total"),
        InlineKeyboardButton("⚡ جدول هفتگی", callback_data="lb_week")
    ]])

def total_leaderboard_text(user_id):
    """🏆 جدول کلی ثروتمندان (جیب + بانک)"""
    with closing(db_connect()) as db:
        rows = db.execute(
            "SELECT user_id, name, coins, level, coins + COALESCE(bank_balance,0) as wealth FROM users ORDER BY wealth DESC LIMIT 10"
        ).fetchall()
        user_row = db.execute(
            "SELECT COUNT(*) + 1 as rank FROM users WHERE coins + COALESCE(bank_balance,0) > (SELECT coins + COALESCE(bank_balance,0) FROM users WHERE user_id = ?)",
            (user_id,)).fetchone()
    if not rows:
        return "❌ هنوز کسی ثبت نشده!"
    msg = ("🏆 **جدول ثروتمندان طویله**\n"
           "_ثروت کل = جیب + بانک_\n"
           "━━━━━━━━━━━━━━\n")
    for i, row in enumerate(rows, 1):
        medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f" {i}."
        title = get_title_by_level(row["level"]).split(" ")[0]  # فقط ایموجی لقب
        msg += f"{medal}  {title} {esc_md(row['name'])}  💎 **{row['wealth']:,}**\n"
    if user_row and user_row["rank"]:
        msg += f"━━━━━━━━━━━━━━\n👤 رتبه تو: **#{user_row['rank']}**"
    return msg

async def league_settle(context):
    """🏁 پایان هفته: پرداخت جوایز + اعلام در همه گروه‌ها + ریست"""
    rows = league_top(3)
    end = league_get_end()
    
    # پرداخت جوایز
    winner_lines = []
    for i, r in enumerate(rows):
        prize = LEAGUE_PRIZES[i]
        add_coins(r["user_id"], prize, league=False)  # جایزه توی لیگ بعدی حساب نشه!
        medal = ["🥇", "🥈", "🥉"][i]
        winner_lines.append(f"{medal} **{esc_md(r['name'])}** — {r['earned']:,} امتیاز → جایزه: **{prize:,}** {CURRENCY_NAME}")
    
    # ریست لیگ + هفته جدید
    with closing(db_connect()) as db:
        db.execute("DELETE FROM league")
        db.commit()
    new_end = league_week_end_ts()
    if new_end <= int(time.time()):
        new_end += 7 * 86400
    set_setting("league_end", str(new_end))
    
    if not rows:
        logger.info("🏆 هفته لیگ بدون شرکت‌کننده تموم شد")
        return
    
    # 📢 اعلام در همه گروه‌ها
    msg = ("🏆🎉 **پایان هفته جدول هفتگی خرستان!** 🎉🏆\n━━━━━━━━━━━━━━\n"
           "👑 قهرمانان این هفته:\n\n" + "\n".join(winner_lines) +
           "\n\n⚡ هفته جدید از همین الان شروع شد!\nبجنگید برای قهرمانی! 🐴🔥")
    try:
        with closing(db_connect()) as db:
            chats = db.execute("SELECT chat_id FROM chats WHERE chat_type IN ('group','supergroup')").fetchall()
        for ch in chats:
            try:
                await context.bot.send_message(chat_id=ch["chat_id"], text=msg, parse_mode="Markdown")
            except Exception:
                pass
            await asyncio.sleep(0.5)
    except Exception as e:
        logger.error(f"❌ خطا در اعلام لیگ: {e}")
    logger.info(f"🏆 لیگ هفتگی بسته شد — {len(rows)} برنده")

# ============================================================
# 5.5 🦹 دزدی از بانک
# ============================================================

BANK_HEIST_CHANCE = 0.15       # شانس موفقیت
BANK_HEIST_MIN = 20000
BANK_HEIST_MAX = 50000
BANK_HEIST_FINE = 5000         # جریمه شکست
BANK_HEIST_JAIL = 3600         # ۱ ساعت بازداشت
BANK_HEIST_COOLDOWN = 21600    # هر ۶ ساعت

HEIST_SUCCESS_STORIES = [
    "🕳️💰 نصفه‌شب از تونل فاضلاب رفتی تو خزانه!",
    "🎭 با نقاب خر بانکو زدی و کسی نفهمید!",
    "🏃💨 نگهبانا خواب بودن... کیسه رو پر کردی و زدی به چاک!",
]
HEIST_FAIL_STORIES = [
    "🚨 آژیر خطر! نگهبانا ریختن سرت!",
    "🔴 پات به لیزر خورد و همه‌جا قرمز شد!",
    "😱 رئیس بانک خودش دم در بود! بدشانسی محض!",
]

async def bank_heist_command(update, context):
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    
    last = int(get_setting(f"heist_{user.id}", "0") or 0)
    now = int(time.time())
    if now - last < BANK_HEIST_COOLDOWN:
        remaining = BANK_HEIST_COOLDOWN - (now - last)
        await update.message.reply_text(
            f"🚔 بانک هنوز تو آماده‌باشه! {remaining//3600} ساعت و {(remaining%3600)//60} دقیقه دیگه بیا.")
        return
    
    set_setting(f"heist_{user.id}", str(now))
    
    if random.random() < BANK_HEIST_CHANCE:
        loot = random.randint(BANK_HEIST_MIN, BANK_HEIST_MAX)
        add_coins(user.id, loot)
        await update.message.reply_text(
            f"🏦💥 **سرقت از بانک موفق شد!!**\n━━━━━━━━━━━━━━\n"
            f"{random.choice(HEIST_SUCCESS_STORIES)}\n\n"
            f"💰🤑 {esc_md(user.first_name)} مبلغ **{loot:,}** {CURRENCY_NAME} بلند کرد!\n"
            f"🏃 فعلاً آفتابی نشو...",
            parse_mode="Markdown")
    else:
        # 🚨 گیر افتاد: جریمه (اول جیب، بعد بانک) + بازداشت
        u = get_user(user.id)
        fine = BANK_HEIST_FINE
        from_pocket = min(u["coins"] or 0, fine)
        from_bank = fine - from_pocket
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET coins = coins - ?, bank_balance = MAX(0, COALESCE(bank_balance,0) - ?) WHERE user_id = ?",
                      (from_pocket, from_bank, user.id))
            db.commit()
        jail_user(user.id, BANK_HEIST_JAIL)
        await update.message.reply_text(
            f"🚨 **گیر افتادی!!**\n━━━━━━━━━━━━━━\n"
            f"{random.choice(HEIST_FAIL_STORIES)}\n\n"
            f"💸 جریمه: **{fine:,}** {CURRENCY_NAME}\n"
            f"🚔 {esc_md(user.first_name)} به **۱ ساعت بازداشت** محکوم شد!\n"
            f"⛓️ تا آزادی هیچ کاری نمی‌تونی بکنی!",
            parse_mode="Markdown")

# ============================================================
# 5.6 💨 تریاک (نئشگی/اعتیاد/خماری)
# ============================================================

OPIUM_COST = 5000
OPIUM_COOLDOWN = 600          # ۱۰ دقیقه بین بست‌ها
OPIUM_ADDICT_LIMIT = 5        # ۵ بست (در کل!) = اعتیاد دائمی
OPIUM_BOOST_HOURS = 2         # نئشگی: ×۲ برای ۲ ساعت
OPIUM_WITHDRAWAL = 43200      # ⛓️ معتاد + ۱۲ ساعت بدون بست = خماری و قفل ربات
CAMP_COST = 25000             # 🏥 هزینه کمپ ترک اعتیاد
CAMP_DURATION = 86400         # ۲۴ ساعت قفل کامل دوره ترک

def get_opium_boost(user_id):
    """آیا الان نئشه‌ست؟ (برای ضریب درآمد کار و عرعر)"""
    return int(get_setting(f"opium_boost_{user_id}", "0") or 0) > int(time.time())

def get_opium_mult(user_id):
    """😵‍💫 ضریب نئشگی فعلی: ۱.۵ (پک سبک) / ۲ (بست) / ۳ (قلیون دو کله)"""
    try:
        return float(get_setting(f"opium_mult_{user_id}", "2") or 2)
    except ValueError:
        return 2.0

def is_opium_addict(user_id):
    """💀 معتاده؟ (۵ بست کشیده و هنوز ترک نکرده)"""
    return get_setting(f"opium_addict_{user_id}", "") == "1"

def is_addict_hungover(user_id):
    """🥶 خماری: معتاده و ۱۲+ ساعت از آخرین بست گذشته → ربات قفل (جز روزانه/کار/گدایی/تریاک)"""
    if not is_opium_addict(user_id):
        return False
    last = int(get_setting(f"opium_last_{user_id}", "0") or 0)
    return int(time.time()) - last >= OPIUM_WITHDRAWAL

def in_camp(user_id):
    """🏥 توی کمپ ترکه؟ خروجی: ثانیه‌های مونده (۰ = نه)"""
    until = int(get_setting(f"camp_until_{user_id}", "0") or 0)
    return max(0, until - int(time.time()))

# 🥶 دستوراتی که تو خماری هنوز کار می‌کنن (بتونه پول بست جور کنه!)
HANGOVER_ALLOWED = {"روزانه", "daily", "جایزه", "کار", "work", "گدایی", "کمک مالی", "beg",
                    "تریاک", "بساط", "opium", "کمپ", "کمپ ترک", "ترک اعتیاد", "camp"}

# 🚬 پک‌های تریاک — طمع بیشتر = خطر بیشتر!
# وزن نتیجه‌ها: high نئشگی | nap چرت | refund رگ ساقی | white خر سفید | buddy رفیق بساط
#               hallu توهم | sick حال بد | police پلیس | od اوردوز
OPIUM_PACKS = {
    "light": {"name": "🚬 یه پک سبک", "cost": 3000, "mult": 1.5, "hours": 1,
              "w": {"high": 48, "nap": 14, "refund": 10, "white": 8, "buddy": 6, "hallu": 3, "sick": 7, "police": 3, "od": 1}},
    "full":  {"name": "💨 بست کامل", "cost": 5000, "mult": 2.0, "hours": 2,
              "w": {"high": 40, "nap": 13, "refund": 10, "white": 5, "buddy": 5, "hallu": 7, "sick": 10, "police": 7, "od": 3}},
    "heavy": {"name": "☠️ قلیون دو کله!", "cost": 10000, "mult": 3.0, "hours": 3,
              "w": {"high": 39, "nap": 8, "refund": 5, "white": 4, "buddy": 4, "hallu": 8, "sick": 12, "police": 12, "od": 8}},
}

# 🎭 ساقی‌های شخصیت‌دار — هر بار یکی پشت طویله‌ست!
OPIUM_DEALERS = {
    "moshti": {"name": "مشتی قاطر", "emoji": "🐴", "price_mod": 1.2, "high_bonus": 5, "sick_bonus": 0,
               "quote": "«جنس من نابِ نابه داداش... ولی نابی خرج داره!» 😏"},
    "dalal":  {"name": "خر دلال", "emoji": "🕶️", "price_mod": 0.8, "high_bonus": 0, "sick_bonus": 8,
               "quote": "«ارزون می‌دم بهت... فقط زیاد سوال نپرس!» 🤫"},
    "amoo":   {"name": "عمو یونجه", "emoji": "👴", "price_mod": 1.0, "high_bonus": 0, "sick_bonus": 0,
               "quote": "«بیا جلو عمو... پول نداشتی هم یه کاریش می‌کنیم!» 🥹", "credit_chance": 0.15},
}

def opium_current_dealer(user_id):
    """🎭 ساقی فعلی کاربر — با باز شدن منو عوض می‌شه"""
    key = get_setting(f"dealer_{user_id}", "")
    if key not in OPIUM_DEALERS:
        key = random.choice(list(OPIUM_DEALERS.keys()))
        set_setting(f"dealer_{user_id}", key)
    return key, OPIUM_DEALERS[key]

def opium_pack_price(pack, dealer):
    return int(OPIUM_PACKS[pack]["cost"] * dealer["price_mod"] // 100 * 100)

def opium_addiction_meter(user_id):
    """☠️ اعتیادسنج: ▰▰▰▱▱ (۳ از ۵)"""
    if is_opium_addict(user_id):
        return "☠️ اعتیادسنج: ▰▰▰▰▰ **معتادی!** 💀"
    total = min(int(get_setting(f"opium_total_{user_id}", "0") or 0), OPIUM_ADDICT_LIMIT)
    return f"☠️ اعتیادسنج: {'▰' * total}{'▱' * (OPIUM_ADDICT_LIMIT - total)} ({total} از {OPIUM_ADDICT_LIMIT})"

def opium_menu_keyboard(user_id):
    _, dealer = opium_current_dealer(user_id)
    rows = []
    for key, p in OPIUM_PACKS.items():
        price = opium_pack_price(key, dealer)
        rows.append([InlineKeyboardButton(f"{p['name']} — {price:,}", callback_data=f"opium_p_{key}")])
    rows.append([InlineKeyboardButton("🏃 نه، پشیمون شدم", callback_data="opium_no")])
    return InlineKeyboardMarkup(rows)

def opium_menu_text(user_id):
    u = get_user(user_id)
    # 🎭 هر بار منو باز شه، ساقی جدید میاد!
    set_setting(f"dealer_{user_id}", random.choice(list(OPIUM_DEALERS.keys())))
    dkey, dealer = opium_current_dealer(user_id)
    addict_line = ""
    if is_opium_addict(user_id):
        addict_line = "\n💀 **تو معتادی!** هر ۱۲ ساعت نکشی، خمار می‌شی و ربات قفل می‌شه!\n🏥 راه نجات: بنویس `کمپ` (۲۵,۰۰۰ + ۲۴ ساعت قفل)"
    price_note = ""
    if dealer["price_mod"] > 1: price_note = " (گرون‌فروشه! 💸)"
    elif dealer["price_mod"] < 1: price_note = " (ارزون می‌ده... ولی مشکوکه! 🤨)"
    return (
        f"💨 **بساط تریاک — پشت طویله**\n━━━━━━━━━━━━━━\n"
        f"🎭 ساقی امشب: {dealer['emoji']} **{dealer['name']}**{price_note}\n"
        f"_{dealer['quote']}_\n\n"
        f"{opium_addiction_meter(user_id)}\n"
        f"💳 موجودیت: {u['coins']:,}\n\n"
        f"🚬 پک سبک: نئشگی ×۱.۵ (۱ ساعت) — کم‌خطر\n"
        f"💨 بست کامل: نئشگی ×۲ (۲ ساعت) — خطر متوسط\n"
        f"☠️ قلیون دو کله: نئشگی **×۳ (۳ ساعت!)** — پلیس و اوردوز بیخ گوشته! 🚔\n"
        f"{addict_line}\n\n"
        f"🔥 چی می‌کشی؟"
    )

# 🎬 صحنه‌های سینمایی کشیدن (پیام مرحله به مرحله ادیت می‌شه)
OPIUM_SCENES = [
    "🏚️ رفتی پشت طویله... {dealer} از تاریکی اومد بیرون... 👀",
    "🧻 {dealer} داره بست رو می‌پیچه...\n💬 {quote}",
    "🔥 منقل روشن شد... کبریت... پک اول...\n💨 دود رفت بالا...",
    "😶‍🌫️ پک دوم... چشمات داره سنگین می‌شه...\n🌀 صداها دور شدن...",
]

def opium_pick_outcome(pack_key, dealer):
    """🎲 انتخاب نتیجه بر اساس وزن‌های پک + تعدیل ساقی"""
    w = dict(OPIUM_PACKS[pack_key]["w"])
    w["high"] += dealer.get("high_bonus", 0)      # مشتی قاطر: جنس ناب‌تر
    w["sick"] += dealer.get("sick_bonus", 0)       # خر دلال: جنس مشکوک!
    keys = list(w.keys())
    return random.choices(keys, weights=[w[k] for k in keys])[0]

async def opium_smoke(user_id, first_name, pack_key="full", price_paid=None):
    """اجرای کشیدن — خروجی: متن نتیجه نهایی"""
    now = int(time.time())
    pack = OPIUM_PACKS.get(pack_key, OPIUM_PACKS["full"])
    if price_paid is None:
        price_paid = pack["cost"]
    dkey, dealer = opium_current_dealer(user_id)
    
    # 💀 شمارش کل بست‌ها — ۵ تا = اعتیاد دائمی
    total = int(get_setting(f"opium_total_{user_id}", "0") or 0) + 1
    set_setting(f"opium_total_{user_id}", str(total))
    set_setting(f"opium_last_{user_id}", str(now))
    
    addict_note = ""
    if total == OPIUM_ADDICT_LIMIT and not is_opium_addict(user_id):
        set_setting(f"opium_addict_{user_id}", "1")
        addict_note = (f"\n\n💀💀 **بست پنجم... تبریک! رسماً معتاد شدی!** 💀💀\n"
                       f"⛓️ از الان هر **۱۲ ساعت** باید یه بست بکشی وگرنه خمار می‌شی و ربات قفل می‌شه!\n"
                       f"🏥 تنها راه نجات: کمپ ترک اعتیاد — بنویس `کمپ` ({CAMP_COST:,} + ۲۴ ساعت قفل)")
    elif is_opium_addict(user_id):
        addict_note = "\n\n⛓️ ساعت خماری ریست شد — ۱۲ ساعت دیگه باز باید بکشی... چه زندگی‌ای! 😮‍💨"
    if not is_opium_addict(user_id):
        addict_note += f"\n{opium_addiction_meter(user_id)}"
    
    outcome = opium_pick_outcome(pack_key, dealer)
    
    if outcome == "high":
        # 😵‍💫 نئشگی — ضریب و مدت بسته به پک!
        set_setting(f"opium_boost_{user_id}", str(now + int(pack["hours"] * 3600)))
        set_setting(f"opium_mult_{user_id}", str(pack["mult"]))
        return (f"😵‍💫 **رفتی تو حس!!**\n━━━━━━━━━━━━━━\n"
                f"🌈 دنیا نرم شد... رنگا قشنگ شدن... عرت از ته دل میاد!\n\n"
                f"🚀 تا **{pack['hours']} ساعت** درآمد کار و عرعرت **×{pack['mult']:g}** شد!\n"
                f"برو کار کن و عر بزن تا نئشگی هست! 💰{addict_note}")
    if outcome == "nap":
        return (f"😴 **چرت زدی!**\n━━━━━━━━━━━━━━\n"
                f"💨 وسط بساط همونجا خوابت برد... بقیه بستت رو کشیدن!\n"
                f"💸 {price_paid:,} {CURRENCY_NAME} دود شد رفت هوا!{addict_note}")
    if outcome == "refund":
        refund = price_paid // 2
        add_coins(user_id, refund, league=False)
        return (f"🤑 **رگ خواب {dealer['name']} رو زدی!**\n━━━━━━━━━━━━━━\n"
                f"😂 از حرفات خوشش اومد و گفت: «نصفش مهمون من!»\n"
                f"💰 **+{refund:,}** {CURRENCY_NAME} پس گرفتی!{addict_note}")
    if outcome == "white":
        # 👻 خر سفید دیدی — فال مجانی از ترس!
        try:
            text_f, coins_f = random.choice(FORTUNES)
            if coins_f > 0:
                add_coins(user_id, coins_f, league=False)
            fal = f"\n🔮 از ترست فال گرفتی: «{text_f}»\n🎁 برکت: +{coins_f}"
        except Exception:
            fal = ""
        return (f"👻 **خر سفید دیدی!!**\n━━━━━━━━━━━━━━\n"
                f"😱 وسط دود، یه خر سفید نورانی ظاهر شد و بهت خیره شد...\n"
                f"🥶 سه متر پریدی هوا! نئشگی از کله‌ت پرید!{fal}{addict_note}")
    if outcome == "buddy":
        # 🤝 رفیق بساط — یه پلیر رندوم (فقط طنز!)
        buddy_name = None
        try:
            with closing(db_connect()) as db:
                row = db.execute("SELECT name FROM users WHERE user_id != ? ORDER BY RANDOM() LIMIT 1",
                                (user_id,)).fetchone()
            if row: buddy_name = row["name"]
        except Exception:
            pass
        buddy_line = f"👀 یهو دیدی **{esc_md(buddy_name)}** هم اونجاست! جفتتون زدین زیر خنده! 😂" if buddy_name else "👀 یه سایه آشنا هم اون گوشه بود... 🤔"
        return (f"🤝 **رفیق بساط پیدا کردی!**\n━━━━━━━━━━━━━━\n"
                f"{buddy_line}\n"
                f"🎶 تا صبح خاطره گفتین و عرعر خوندین...\n"
                f"💨 حداقل تنها نبودی!{addict_note}")
    if outcome == "hallu":
        # 🌈 توهم — فقط طنز
        vision = random.choice([
            "دیدی خر بات داره بهت پول می‌ده! دستتو دراز کردی... هیچی نبود! 🤲😂",
            "دیدی صدر جدول هفتگی شدی! از خوشحالی عرعر زدی... خواب بود! 📊💀",
            "دیدی یونجه‌ها طلا شدن! گاز زدی... خاک بود! 🌾😖",
            "دیدی اونر بهت ۱ میلیون کادو داد! بیدار شدی... جیبت همون قده! 🎁😭",
        ])
        return (f"🌈 **توهم زدی!!**\n━━━━━━━━━━━━━━\n"
                f"😵‍💫 {vision}\n"
                f"💊 جنس امشب یه چیزیش بود...{addict_note}")
    if outcome == "sick":
        fine = 8000
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (fine, user_id))
            db.commit()
        blame = " (از خر دلال خرید نکن گفته بودم! 🕶️)" if dkey == "dalal" else ""
        return (f"🤢 **حالت بد شد!**\n━━━━━━━━━━━━━━\n"
                f"🙈 جنس تقلبی بود! وسط طویله بالا آوردی و همه دیدن!{blame}\n"
                f"💸 خرج دوا درمون و آبروریزی: **-{fine:,}** {CURRENCY_NAME}{addict_note}")
    if outcome == "police":
        fine = 15000
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (fine, user_id))
            db.commit()
        jail_user(user_id, 1800)
        return (f"🚔 **پلیس ریخت سر بساط!!**\n━━━━━━━━━━━━━━\n"
                f"🚨 منقل جمع شد، دستبند خورد! {dealer['name']} از پنجره فرار کرد! 🏃💨\n"
                f"💸 جریمه: **-{fine:,}** {CURRENCY_NAME}\n"
                f"⛓️ **۳۰ دقیقه بازداشت** — هیچ کاری نمی‌تونی بکنی!{addict_note}")
    # 💀 اوردوز
    u = get_user(user_id)
    pct = 0.15 if pack_key == "heavy" else 0.10
    cost = int((u["coins"] or 0) * pct)
    if cost > 0:
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (cost, user_id))
            db.commit()
    return (f"💀 **اوردوز کردی!!**\n━━━━━━━━━━━━━━\n"
            f"🏥 زیاده‌روی کردی و کارت به بیمارستان طویله کشید!\n"
            f"💸 خرج درمان ({int(pct*100)}٪ جیبت): **-{cost:,}** {CURRENCY_NAME}\n"
            f"🙏 خدا رحم کرد زنده موندی...{addict_note}")

async def opium_smoke_cinematic(query, context, user_id, first_name, pack_key, price_paid):
    """🎬 کشیدن سینمایی: صحنه‌ها یکی‌یکی ادیت می‌شن، آخرش نتیجه!"""
    dkey, dealer = opium_current_dealer(user_id)
    dn = f"{dealer['emoji']} {dealer['name']}"
    pack = OPIUM_PACKS.get(pack_key, OPIUM_PACKS["full"])
    header = f"💨 **{pack['name']}** — پشت طویله\n━━━━━━━━━━━━━━\n"
    for scene in OPIUM_SCENES:
        try:
            await query.edit_message_text(
                header + scene.format(dealer=dn, quote=dealer["quote"]),
                parse_mode="Markdown")
        except Exception:
            pass
        await asyncio.sleep(1.8)
    result = await opium_smoke(user_id, first_name, pack_key, price_paid)
    try:
        await query.edit_message_text(result, parse_mode="Markdown")
    except Exception:
        pass

CAMP_MOODS = [
    "🥶 داری عرق سرد می‌ریزی و به دیوار نگاه می‌کنی...",
    "😖 دستات می‌لرزه... یاد بساط افتادی ولی طاقت بیار!",
    "🛏️ رو تخت کمپ دراز کشیدی و سقف رو می‌شمری...",
    "🍵 پرستار کمپ بهت آش داد... یه کم آروم شدی.",
    "💪 داری قوی‌تر می‌شی... چیزی نمونده!",
]

async def camp_command(update, context):
    """🏥 کمپ ترک اعتیاد — ۲۵,۰۰۰ + ۲۴ ساعت قفل کامل → پاکی"""
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    
    left = in_camp(user.id)
    if left > 0:
        await update.message.reply_text(
            f"🏥 **تو الان توی کمپی!**\n{random.choice(CAMP_MOODS)}\n"
            f"⏳ {left // 3600} ساعت و {(left % 3600) // 60} دقیقه مونده تا پاکی!",
            parse_mode="Markdown")
        return
    
    if not is_opium_addict(user.id):
        await update.message.reply_text(
            "😊 تو که معتاد نیستی خر سالم! برو خدا رو شکر کن.\n"
            "(کمپ فقط برای معتادهاست)")
        return
    
    u = get_user(user.id)
    if (u["coins"] or 0) < CAMP_COST:
        await update.message.reply_text(
            f"🏥 هزینه کمپ **{CAMP_COST:,}** {CURRENCY_NAME} است!\n"
            f"💳 داری: {u['coins']:,}\n"
            f"😮‍💨 برو با «کار» و «گدایی» جورش کن... یا به کشیدن ادامه بده!",
            parse_mode="Markdown")
        return
    
    remove_coins(user.id, CAMP_COST)
    set_setting(f"camp_until_{user.id}", str(int(time.time()) + CAMP_DURATION))
    await update.message.reply_text(
        f"🏥 **رفتی کمپ ترک اعتیاد!**\n━━━━━━━━━━━━━━\n"
        f"💸 هزینه: {CAMP_COST:,} {CURRENCY_NAME}\n"
        f"⛓️ **۲۴ ساعت کامل ربات برات قفله** — هیچی، حتی کار و روزانه!\n"
        f"🥶 دوره سختیه... ولی بعدش پاکِ پاکی!\n\n"
        f"💪 دووم بیار قهرمان! فردا همین موقع آزادی!",
        parse_mode="Markdown")

def camp_finish_check(user_id):
    """پایان دوره کمپ → پاکی کامل و ریست شمارنده"""
    until = int(get_setting(f"camp_until_{user_id}", "0") or 0)
    if until and int(time.time()) >= until:
        set_setting(f"camp_until_{user_id}", "0")
        set_setting(f"opium_addict_{user_id}", "")
        set_setting(f"opium_total_{user_id}", "0")
        set_setting(f"opium_boost_{user_id}", "0")
        return True
    return False

# ============================================================
# 5.6.4 🏇 رالی خرستان (مسابقه ۲ نفره داخل گروه — با اتاق مثل بقیه بازی‌ها)
# ============================================================


def rally_record(user_id, win):
    with closing(db_connect()) as db:
        db.execute("""INSERT INTO rally (user_id, wins, losses) VALUES (?, ?, ?)
                      ON CONFLICT(user_id) DO UPDATE SET wins = wins + ?, losses = losses + ?""",
                   (user_id, 1 if win else 0, 0 if win else 1, 1 if win else 0, 0 if win else 1))
        db.commit()

def rally_top(limit=10):
    with closing(db_connect()) as db:
        return db.execute(
            "SELECT r.user_id, r.wins, r.losses, u.name FROM rally r "
            "LEFT JOIN users u ON u.user_id = r.user_id "
            "ORDER BY r.wins DESC LIMIT ?", (limit,)).fetchall()

def rally_menu_text(user_id):
    power = donkey_power(user_id)
    with closing(db_connect()) as db:
        row = db.execute("SELECT wins, losses FROM rally WHERE user_id = ?", (user_id,)).fetchone()
    w, l = (row["wins"], row["losses"]) if row else (0, 0)
    streak = int(get_setting(f"rally_streak_{user_id}", "0") or 0)
    title = rally_streak_title(streak)
    streak_line = f"\n{title} — {streak} برد پشت هم! 🔥" if title else (f"\n🔥 استریک فعلی: {streak} برد" if streak > 0 else "")
    tracks = " | ".join(f"{t['emoji']} {t['name']}" for t in RALLY_TRACKS)
    return (
        "🏇 **رالی خرستان**\n"
        "_مسابقه خر با خر — قوی‌تر باش تا ببری!_\n"
        "━━━━━━━━━━━━━━\n"
        f"⚡ قدرت خر تو: **{power}**\n"
        f"📊 آمار رالی: 🏆 {w} برد | 💀 {l} باخت{streak_line}\n\n"
        f"🗺️ **پیست‌ها (شانسی):** {tracks}\n"
        "💡 هر پیست به یه دسته وسیله بونوس می‌ده — همه‌جوره تجهیز شو!\n\n"
        "📈 قدرت بیشتر = شانس برد بیشتر (تا ۸۸٪) — ولی شگفتی همیشه هست! 😏\n"
        "🎲 فرم روز، روحیه استریک و خستگی هم رو نتیجه اثر دارن!\n"
        "😮‍💨 ۳+ مسابقه تو یه ساعت = خر خسته می‌شه!\n\n"
        "🎮 **شروع مسابقه:** بنویس `رالی 1000` — اتاق ساخته می‌شه، حریف با دکمه وارد شه!\n\n"
        "👇 گزینه‌ها:"
    )

def rally_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏇 ساخت مسابقه", callback_data="game_rally")],
        [InlineKeyboardButton("🏆 قهرمانان رالی", callback_data="rally_top")],
        [InlineKeyboardButton("🏪 فروشگاه (تقویت خر)", callback_data="shop"),
         InlineKeyboardButton("🏠 منو", callback_data="home")]
    ])

# 🗺️ پیست‌های رالی — هر پیست به یه دسته وسیله بونوس تخصص می‌ده!
RALLY_TRACKS = [
    {"name": "دشت یونجه‌زار", "emoji": "🌾", "cat": "saddles", "cat_name": "🐴 زین",
     "flavor": "دشت باز و سرعتی — زین خوب اینجا حرف اول رو می‌زنه!"},
    {"name": "گردنه خرشکن", "emoji": "⛰️", "cat": "horseshoes", "cat_name": "👟 نعل",
     "flavor": "سربالایی سنگلاخ — بدون نعل درست، دخلت اومده!"},
    {"name": "جاده خاکی طویله", "emoji": "🛤️", "cat": "hats", "cat_name": "🎩 کلاه",
     "flavor": "گرد و خاک و آفتاب — کلاه‌دارا جلوترن!"},
    {"name": "پیست شبانه", "emoji": "🌙", "cat": "magics", "cat_name": "🍀 جادو",
     "flavor": "تاریکی مطلق — فقط جادو راه رو نشون می‌ده!"},
]

# 🎬 اتفاق‌های رندوم وسط مسابقه (برای گزارش زنده)
RALLY_EVENTS_LEAD = [
    "{A} جفتک زد و سرعت گرفت! 💨",
    "{A} از میان‌بر کنار جوب رفت! چه حرکتی! 🧠",
    "تماشاچیا برای {A} هویج پرت کردن — انرژی گرفت! 🥕",
    "{A} عرعرکنان داره می‌تازه! گوش فلک کر شد! 📢",
]
RALLY_EVENTS_BEHIND = [
    "{B} رو پوست موز لیز خورد! 🍌",
    "{B} وسط مسیر هوس یونجه کرد! 🌾😂",
    "{B} پاش تو چاله رفت! تلوتلو می‌خوره! 🕳️",
    "زنبور {B} رو نیش زد! داره دیوونه‌بازی درمیاره! 🐝",
]
RALLY_EVENTS_CLOSE = [
    "مچ‌به‌مچ دارن میان! هیچی معلوم نیست! 😱",
    "دُم به دُم! تماشاچیا نفسشون بند اومده! 🫁",
    "شونه به شونه — این دیگه جنگ اعصابه! ⚔️",
]

# 🔥 لقب استریک
def rally_streak_title(streak):
    if streak >= 7: return "👑 اسطوره پیست"
    if streak >= 5: return "⚡ خر صاعقه"
    if streak >= 3: return "🔥 خر آتشین"
    return ""

# 😮‍💨 خستگی: مسابقه‌های یه ساعت اخیر (در حافظه)
RALLY_RACE_LOG = {}   # {uid: [ts, ...]}
RALLY_FATIGUE_N = 3   # ۳+ مسابقه در ساعت = خستگی
RALLY_FATIGUE_PENALTY = 0.15

def rally_form():
    """🎲 فرم روز: ۰.۸۵ تا ۱.۱۵ — تیم قوی هم روز بد داره!"""
    return random.uniform(0.85, 1.15)

def rally_effective_power(user_id, track):
    """⚡ قدرت مؤثر = پایه × فرم + تخصص پیست + استریک − خستگی − حال بد
    خروجی: (قدرت مؤثر، دیکشنری جزئیات برای نمایش)"""
    base = donkey_power(user_id)
    detail = {"base": base, "form": 1.0, "track": 0, "streak": 0, "fatigue": False, "dizzy": False}
    
    eff = float(max(base, 1))  # حداقل ۱ که ضرب‌ها کار کنن
    # 🎲 فرم روز
    f = rally_form()
    detail["form"] = f
    eff *= f
    # 🗺️ تخصص پیست: وسیله پوشیده از دسته محبوب پیست → +۱۰٪ + پاور همون آیتم
    d = get_donkey(user_id)
    col = SHOP_COL_MAP.get(track["cat"])
    if d and col:
        try:
            worn = d[col]
        except (KeyError, IndexError):
            worn = None
        if worn and worn in SHOP_ITEMS[track["cat"]]["items"]:
            bonus = eff * 0.10 + SHOP_ITEMS[track["cat"]]["items"][worn]["power"]
            detail["track"] = int(bonus)
            eff += bonus
    # 🔥 استریک برد: +۳٪ هر برد (سقف ۹٪)
    streak = int(get_setting(f"rally_streak_{user_id}", "0") or 0)
    if streak > 0:
        sb = eff * min(streak * 0.03, 0.09)
        detail["streak"] = int(sb)
        eff += sb
    # 😮‍💨 خستگی: ۳+ رالی تو یه ساعت
    now = time.time()
    log = [t for t in RALLY_RACE_LOG.get(user_id, []) if now - t < 3600]
    RALLY_RACE_LOG[user_id] = log
    if len(log) >= RALLY_FATIGUE_N:
        detail["fatigue"] = True
        eff *= (1 - RALLY_FATIGUE_PENALTY)
    # 💨 نئشه/خمار: خر گیجه!
    try:
        if get_opium_boost(user_id) or is_addict_hungover(user_id):
            detail["dizzy"] = True
            eff *= 0.80
    except Exception:
        pass
    return eff, detail

def rally_win_chance(diff_ratio):
    """🎯 شانس برد قوی‌تر — پله‌ای بر اساس نسبت اختلاف قدرت مؤثر
    diff_ratio = (eff_strong - eff_weak) / eff_weak"""
    if diff_ratio < 0.10: return 0.55   # تقریباً برابر
    if diff_ratio < 0.30: return 0.63
    if diff_ratio < 0.60: return 0.72
    if diff_ratio < 1.00: return 0.80
    return 0.88                          # له‌کردن — ولی هیچ‌وقت ۱۰۰٪ نه!

RALLY_DRAW_CHANCE = 0.08

def rally_resolve_pro(p1, eff1, p2, eff2):
    """🏇 برنده با الگوریتم حرفه‌ای — خروجی: (برنده یا None، شانس قوی‌تر)"""
    strong, weak = (p1, p2) if eff1 >= eff2 else (p2, p1)
    es, ew = max(eff1, eff2), min(eff1, eff2)
    ratio = (es - ew) / max(ew, 1)
    wc = rally_win_chance(ratio)
    r = random.random()
    if r < RALLY_DRAW_CHANCE:
        return None, wc
    if r < RALLY_DRAW_CHANCE + wc * (1 - RALLY_DRAW_CHANCE):
        return strong, wc
    return weak, wc

def _rally_bar(pos, total=8):
    return "🏁" + "▰" * min(pos, total) + "▱" * max(0, total - pos)

async def rally_run(context, p1, p2, bet, chat_ids, global_match=False):
    """🎬 اجرای سینمایی مسابقه: گزارش زنده مرحله‌ای + نتیجه با الگوریتم حرفه‌ای"""
    track = random.choice(RALLY_TRACKS)
    eff1, det1 = rally_effective_power(p1, track)
    eff2, det2 = rally_effective_power(p2, track)
    winner, wc = rally_resolve_pro(p1, eff1, p2, eff2)
    
    # ثبت مسابقه تو لاگ خستگی
    now = time.time()
    RALLY_RACE_LOG.setdefault(p1, []).append(now)
    RALLY_RACE_LOG.setdefault(p2, []).append(now)
    
    pw1, pw2 = det1["base"], det2["base"]
    tag = "🏇 **رالی خرستان!**"
    
    def notes(det):
        out = []
        if det["track"]: out.append(f"🗺️ تخصص پیست +{det['track']}")
        if det["streak"]: out.append(f"🔥 روحیه +{det['streak']}")
        if det["fatigue"]: out.append("😮‍💨 خسته!")
        if det["dizzy"]: out.append("💫 گیج!")
        return (" | ".join(out)) if out else ""
    
    n1, n2 = notes(det1), notes(det2)
    header = (f"{tag}\n━━━━━━━━━━━━━━\n"
              f"{track['emoji']} پیست: **{track['name']}** (بونوس: {track['cat_name']})\n"
              f"_{track['flavor']}_\n"
              f"💰 شرط: {bet:,} {CURRENCY_NAME}\n"
              f"━━━━━━━━━━━━━━\n"
              f"🐴 {uname(p1)} ⚡{pw1}" + (f"  {n1}" if n1 else "") + "\n"
              f"🐴 {uname(p2)} ⚡{pw2}" + (f"  {n2}" if n2 else "") + "\n\n")
    
    # 📤 پیام اولیه به همه چت‌ها
    msgs = []
    for cid in set(chat_ids):
        try:
            sent = await context.bot.send_message(
                chat_id=cid, text=header + "🚦 آماده... حاضر...", parse_mode="Markdown")
            msgs.append((cid, sent.message_id))
        except Exception as e:
            logger.warning(f"⚠️ اعلام رالی به {cid} نشد: {e}")
    
    async def update_all(body, kb=None):
        for cid, mid in msgs:
            try:
                await context.bot.edit_message_text(
                    header + body, chat_id=cid, message_id=mid,
                    parse_mode="Markdown", reply_markup=kb)
            except Exception:
                pass
    
    # 🎬 سناریوی مرحله‌ای — جایگاه‌ها بر اساس برنده نهایی چیده می‌شن (با فراز و نشیب!)
    lead = winner if winner else random.choice([p1, p2])
    chase = p2 if lead == p1 else p1
    # مرحله ۱: استارت
    await asyncio.sleep(2)
    await update_all(
        f"🏁 **استارت زده شد!!** دوتا خر مثل فشنگ در رفتن! 💨\n\n"
        f"{_rally_bar(2)} {uname(lead)}\n{_rally_bar(2)} {uname(chase)}\n\n"
        f"🎙️ {random.choice(RALLY_EVENTS_CLOSE)}")
    # مرحله ۲: وسط مسیر — تعقیب‌کننده جلو می‌زنه (هیجان!)
    await asyncio.sleep(2.5)
    ev = random.choice(RALLY_EVENTS_LEAD).format(A=uname(chase))
    await update_all(
        f"🌀 **پیچ وسط مسیر!**\n\n"
        f"{_rally_bar(4)} {uname(chase)}\n{_rally_bar(3)} {uname(lead)}\n\n"
        f"🎙️ {ev}\n😱 سبقت!! {uname(chase)} جلو زد!")
    # مرحله ۳: نزدیک پایان — برنده واقعی برمی‌گرده جلو
    await asyncio.sleep(2.5)
    ev2 = random.choice(RALLY_EVENTS_BEHIND).format(B=uname(chase))
    await update_all(
        f"⚡ **صد متر آخر!!**\n\n"
        f"{_rally_bar(7)} {uname(lead)}\n{_rally_bar(6)} {uname(chase)}\n\n"
        f"🎙️ {ev2}\n🔥 {uname(lead)} دوباره اومد جلو! خط پایان نزدیکه!")
    await asyncio.sleep(2.5)
    
    # 🏆 نتیجه نهایی
    if winner is None:
        add_coins(p1, bet, league=False)
        add_coins(p2, bet, league=False)
        set_setting(f"rally_streak_{p1}", "0")
        set_setting(f"rally_streak_{p2}", "0")
        body = (f"🏁 **فوتوفینیش!!** 📸\n\n"
                f"{_rally_bar(8)} {uname(p1)}\n{_rally_bar(8)} {uname(p2)}\n\n"
                f"🤝 **دقیقاً با هم رسیدن! مساوی!**\n💰 شرط هر دو برگشت داده شد.")
    else:
        loser = p2 if winner == p1 else p1
        weff, leff = (eff1, eff2) if winner == p1 else (eff2, eff1)
        add_coins(winner, bet * 2, league=False)
        record_win(winner)
        record_loss(loser, bet)
        rally_record(winner, True)
        rally_record(loser, False)
        # 🔥 استریک
        streak = int(get_setting(f"rally_streak_{winner}", "0") or 0) + 1
        set_setting(f"rally_streak_{winner}", str(streak))
        set_setting(f"rally_streak_{loser}", "0")
        title = rally_streak_title(streak)
        title_line = f"\n{title.split()[0]} {uname(winner)} لقب **«{title}»** گرفت! ({streak} برد پشت هم)" if title else ""
        
        if weff < leff:
            story = f"😱😱 **شگفتی بزرگ پیست!!** {uname(winner)} با قدرت کمتر ترکوند!"
        elif det1["fatigue"] or det2["fatigue"]:
            story = f"🏆 {uname(winner)} برد — خستگی حریف کار دستش داد!"
        else:
            story = f"🏆 **{uname(winner)}** با اقتدار خط پایان رو رد کرد!"
        
        body = (f"🏁 **پایان مسابقه!**\n\n"
                f"{_rally_bar(8)} {uname(winner)} 🏆\n{_rally_bar(6)} {uname(loser)}\n\n"
                f"🎙️ {story}\n"
                f"💰 جایزه: **{bet*2:,}** {CURRENCY_NAME}{title_line}")
    
    # 🔄 دکمه انتقام
    kb = None
    if winner is not None and not global_match and len(msgs) == 1:
        loser = p2 if winner == p1 else p1
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 انتقام! (همون شرط)", callback_data=f"rally_rm_{loser}_{winner}_{bet}")]])
    await update_all(body, kb)

async def rally_room_begin(room, context):
    """🏇 شروع رالی از اتاق (مثل بقیه بازی‌ها — با دکمه ورود و شروع)"""
    p1, p2 = room.players[0], room.players[1]
    # 🚫 خر بات رالی نمی‌ده (نباید پیش بیاد چون دکمه‌ش حذفه — محض احتیاط)
    if BOT_ID in room.players:
        refund_room(room)
        room.finished = True
        cleanup_room(room.room_id)
        await edit_room_msg(room, context, "❌🤖 خر بات رالی نمی‌ده! شرط‌ها برگشت داده شد.", result_keyboard())
        return
    room.finished = True  # مدیریت پیام دست rally_run میفته
    cleanup_room(room.room_id)
    await edit_room_msg(room, context, "🏇 مسابقه شروع شد! 🏁💨")
    await rally_run(context, p1, p2, room.bet, [room.chat_id])

# ============================================================
# 5.6.5 🍾 عرق‌خوری دو نفره (فقط پلیرها)
# ============================================================

DRINK_COOLDOWN = 14400   # هر ۴ ساعت
DRINK_MIN, DRINK_MAX = 500, 2000
DRINK_PROPOSALS = {}     # {target_id: (asker_id, chat_id, ts)}

DRINK_GOOD_TEXTS = [
    "🥃 عرق سگی طویله کار خودشو کرد... دوتا خر مست دارن وسط طویله می‌رقصن! 💃",
    "🍾 به سلامتی رفاقت زدن و زمین و زمان رو فراموش کردن! 🎶",
    "🥂 اونقدر خندیدن که کره‌خرا هم جمع شدن تماشا! 😂",
    "🍻 قدح اول به سلامتی، قدح دوم به رفاقت... بقیه‌ش یادشون نیست! 🌀",
]
DRINK_POLICE_TEXTS = [
    "🚔 گشت طویله سر رسید! دوتا خر مست وسط عربده‌کشی گیر افتادن!",
    "🚨 صدای آوازخونی‌شون کل طویله رو برداشت... پلیس اومد جمعشون کرد!",
]
DRINK_FAKE_TEXTS = [
    "🤮 عرق تقلبی بود! جفتشون تا صبح بالا آوردن...",
    "🥴 ساقی جنس تقلبی داده بود! سردرد + خرج دوا درمون...",
]

async def drink_command(update, context):
    """🍾 ریپلای + «عرق» → دعوت رفیق به عرق‌خوری"""
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "🍾 روی پیام رفیقت **ریپلای** بزن و بنویس `عرق`\n"
            "🥃 دوتایی می‌زنین به سلامتی و جفتتون تی‌تاپ می‌گیرین!\n"
            "⚠️ ولی حواست باشه... گشت طویله و عرق تقلبی هم هست! 😏",
            parse_mode="Markdown")
        return
    
    target = update.message.reply_to_message.from_user
    if target.id == user.id:
        await update.message.reply_text("❌😂 تنهایی عرق می‌خوری؟! یه رفیق پیدا کن!")
        return
    if target.is_bot:
        await update.message.reply_text("❌🤖 خر بات پاکه، لب به عرق نمی‌زنه! با یه پلیر بزن.")
        return
    
    now = int(time.time())
    last = int(get_setting(f"drink_{user.id}", "0") or 0)
    if now - last < DRINK_COOLDOWN:
        rem = DRINK_COOLDOWN - (now - last)
        await update.message.reply_text(f"🥴 هنوز مستی از دفعه قبل! {rem // 3600} ساعت و {(rem % 3600) // 60} دقیقه دیگه بیا.")
        return
    last_t = int(get_setting(f"drink_{target.id}", "0") or 0)
    if now - last_t < DRINK_COOLDOWN:
        await update.message.reply_text(f"🥴 {esc_md(target.first_name)} هنوز مسته! بعداً بیاین.", parse_mode="Markdown")
        return
    
    ensure_user(target.id, target.first_name)
    DRINK_PROPOSALS[target.id] = (user.id, update.effective_chat.id, now)
    await update.message.reply_text(
        f"🍾 **دعوت به عرق‌خوری!**\n━━━━━━━━━━━━━━\n"
        f"🥃 {esc_md(user.first_name)} بساط پهن کرده و {esc_md(target.first_name)} رو دعوت کرده!\n"
        f"😏 پایه‌ای یا جا می‌زنی؟",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🍾 پایه‌ام!", callback_data=f"drink_yes_{target.id}"),
            InlineKeyboardButton("🙅 نمی‌خورم", callback_data=f"drink_no_{target.id}")]]),
        parse_mode="Markdown")

async def drink_callback(update, context, query, answer, target_id):
    """جواب دعوت عرق — فقط خود دعوت‌شده"""
    user = query.from_user
    if user.id != target_id:
        await query.answer("🔒 این دعوت مال تو نیست!", show_alert=True)
        return
    prop = DRINK_PROPOSALS.pop(target_id, None)
    if not prop:
        await query.answer("⏳ دعوت منقضی شده!", show_alert=True)
        return
    asker_id, chat_id, ts = prop
    if answer == "no":
        await query.edit_message_text(
            f"🙅 {esc_md(user.first_name)} جا زد! گفت: «من لب نمی‌زنم!»\n😏 خر عاقل...", parse_mode="Markdown")
        return
    
    now = int(time.time())
    set_setting(f"drink_{asker_id}", str(now))
    set_setting(f"drink_{target_id}", str(now))
    
    roll = random.random()
    a_name = uname(asker_id)
    t_name = esc_md(user.first_name)
    if roll < 0.80:
        # 🥂 خوش گذشت — جفتشون جایزه
        prize_a = random.randint(DRINK_MIN, DRINK_MAX)
        prize_t = random.randint(DRINK_MIN, DRINK_MAX)
        add_coins(asker_id, prize_a)
        add_coins(target_id, prize_t)
        await query.edit_message_text(
            f"🍾 **زدن به سلامتی رفاقت!**\n━━━━━━━━━━━━━━\n"
            f"{random.choice(DRINK_GOOD_TEXTS)}\n\n"
            f"💰 {a_name}: **+{prize_a:,}** | {t_name}: **+{prize_t:,}** {CURRENCY_NAME}\n"
            f"🎙️ مستی و راستی!",
            parse_mode="Markdown")
    elif roll < 0.90:
        # 🚔 گشت طویله — ۳۰ دقیقه بازداشت جفتی
        jail_user(asker_id, 1800)
        jail_user(target_id, 1800)
        await query.edit_message_text(
            f"🚔 **گشت طویله رسید!!**\n━━━━━━━━━━━━━━\n"
            f"{random.choice(DRINK_POLICE_TEXTS)}\n\n"
            f"⛓️ {a_name} و {t_name} جفتشون **۳۰ دقیقه بازداشت** شدن!\n"
            f"😅 مستی و عربده‌کشی جواب داد...",
            parse_mode="Markdown")
    else:
        # 🤮 عرق تقلبی — ضرر جفتی
        loss_a = random.randint(500, 1500)
        loss_t = random.randint(500, 1500)
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (loss_a, asker_id))
            db.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (loss_t, target_id))
            db.commit()
        await query.edit_message_text(
            f"🤮 **عرق تقلبی بود!!**\n━━━━━━━━━━━━━━\n"
            f"{random.choice(DRINK_FAKE_TEXTS)}\n\n"
            f"💸 خرج دوا درمون: {a_name}: **-{loss_a:,}** | {t_name}: **-{loss_t:,}**\n"
            f"😖 دیگه از هر ساقی‌ای جنس نگیرین!",
            parse_mode="Markdown")

# ============================================================
# 5.7 🆘 گدایی (تور نجات ورشکسته‌ها)
# ============================================================

BEG_THRESHOLD = 1000       # فقط وقتی ثروت کل زیر این باشه
BEG_COOLDOWN = 14400       # هر ۴ ساعت
BEG_MIN, BEG_MAX = 500, 1500

BEG_STORIES = [
    "🥺 کنار طویله نشستی و کاسه گرفتی... مردم دلشون سوخت!",
    "😢 یه عر سوزناک کشیدی، رهگذرا اشکشون دراومد!",
    "🥹 با چشمای خرگوشی (خری!) به مردم نگاه کردی...",
    "📋 تابلو گرفتی: «خر بی‌یونجه، کمک کنید»",
]

async def beg_command(update, context):
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    u = get_user(user.id)
    wealth = (u["coins"] or 0) + (u["bank_balance"] or 0)
    if wealth >= BEG_THRESHOLD:
        await update.message.reply_text(
            f"😒 با {wealth:,} {CURRENCY_NAME} اومدی گدایی؟! برو کار کن!\n"
            f"(گدایی فقط برای ثروت زیر {BEG_THRESHOLD:,})")
        return
    last = int(get_setting(f"beg_{user.id}", "0") or 0)
    now = int(time.time())
    if now - last < BEG_COOLDOWN:
        remaining = BEG_COOLDOWN - (now - last)
        await update.message.reply_text(
            f"⏳ تازه گدایی کردی! {remaining//3600} ساعت و {(remaining%3600)//60} دقیقه دیگه بیا.")
        return
    amount = random.randint(BEG_MIN, BEG_MAX)
    add_coins(user.id, amount)
    set_setting(f"beg_{user.id}", str(now))
    await update.message.reply_text(
        f"🆘 **گدایی موفق!**\n━━━━━━━━━━━━━━\n"
        f"{random.choice(BEG_STORIES)}\n\n"
        f"💰 مردم بهت {amount:,} {CURRENCY_NAME} دادن!\n"
        f"💪 حالا پاشو برو `کار` کن، گدایی که زندگی نشد!",
        parse_mode="Markdown")

# ============================================================
# 5.8 💸 مالیات ثروت
# ============================================================

WEALTH_TAX_THRESHOLD = 500000   # بالای این ثروت (جیب+بانک) مالیات می‌خوره
WEALTH_TAX_RATE = 0.02          # روزی ۲٪ از «مازاد»

def collect_wealth_tax(user_id):
    """💸 روزی یه بار موقع فعالیت — خروجی: مبلغ مالیات یا 0"""
    try:
        u = get_user(user_id)
        if not u: return 0
        wealth = (u["coins"] or 0) + (u["bank_balance"] or 0)
        if wealth <= WEALTH_TAX_THRESHOLD:
            return 0
        last = int(get_setting(f"tax_{user_id}", "0") or 0)
        now = int(time.time())
        if not last:
            set_setting(f"tax_{user_id}", str(now))
            return 0
        if now - last < 86400:
            return 0
        tax = int((wealth - WEALTH_TAX_THRESHOLD) * WEALTH_TAX_RATE)
        if tax <= 0:
            set_setting(f"tax_{user_id}", str(now))
            return 0
        # اول از جیب، بعد از بانک
        with closing(db_connect()) as db:
            coins = u["coins"] or 0
            from_pocket = min(coins, tax)
            from_bank = tax - from_pocket
            db.execute("UPDATE users SET coins = coins - ?, bank_balance = MAX(0, COALESCE(bank_balance,0) - ?) WHERE user_id = ?",
                      (from_pocket, from_bank, user_id))
            db.commit()
        set_setting(f"tax_{user_id}", str(now))
        update_level(user_id)
        return tax
    except Exception as e:
        logger.warning(f"⚠️ خطا در مالیات: {e}")
        return 0

# ============================================================
# 5.9 🛡️ بیمه (جبران باخت + سپر دزدی)
# ============================================================

INSURANCE_COST = 15000      # قیمت بیمه‌نامه
INSURANCE_DAYS = 3          # مدت اعتبار
INSURANCE_REFUND = 0.20     # ۲۰٪ باخت همه بازی‌ها برمی‌گرده — بدون سقف!
INSURANCE_REFUND_CAP = 10**12  # عملاً بدون سقف

def has_insurance(user_id):
    u = get_user(user_id)
    return u and (u["insurance_until"] or 0) > int(time.time())

def insurance_refund(user_id, lost_amount):
    """جبران بخشی از باخت برای بیمه‌شده‌ها — خروجی: مبلغ جبران"""
    if not has_insurance(user_id) or lost_amount <= 0:
        return 0
    refund = min(int(lost_amount * INSURANCE_REFUND), INSURANCE_REFUND_CAP)
    if refund > 0:
        add_coins(user_id, refund, league=False)
    return refund

def insurance_text(user_id):
    u = get_user(user_id)
    until = u["insurance_until"] or 0
    now = int(time.time())
    msg = (
        f"🛡️ **بیمه خرستان**\n━━━━━━━━━━━━━━\n"
    )
    if until > now:
        days_left = (until - now) // 86400
        hours_left = ((until - now) % 86400) // 3600
        msg += f"✅ **بیمه‌ای!** اعتبار: {days_left} روز و {hours_left} ساعت دیگه\n\n"
    else:
        msg += "❌ الان بیمه نیستی!\n\n"
    msg += (
        f"**مزایای بیمه:**\n"
        f"📉 {int(INSURANCE_REFUND*100)}٪ باخت‌های قمارت برمی‌گرده — بدون سقف!\n"
        f"🦹 دزدها نمی‌تونن ازت بدزدن!\n\n"
        f"💳 قیمت: **{INSURANCE_COST:,}** {CURRENCY_NAME} برای **{INSURANCE_DAYS} روز**\n"
        f"🛒 خرید: بنویس `خرید بیمه`"
    )
    return msg

async def insurance_buy(update, context):
    user = update.effective_user
    if has_insurance(user.id):
        u = get_user(user.id)
        days_left = ((u["insurance_until"] or 0) - int(time.time())) // 86400
        await update.message.reply_text(f"🛡️ همین الانم بیمه‌ای! ({days_left} روز مونده)")
        return
    if not remove_coins(user.id, INSURANCE_COST):
        u = get_user(user.id)
        await update.message.reply_text(f"❌ بیمه {INSURANCE_COST:,} {CURRENCY_NAME}ه! موجودیت: {u['coins']:,}")
        return
    until = int(time.time()) + INSURANCE_DAYS * 86400
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET insurance_until = ? WHERE user_id = ?", (until, user.id))
        db.commit()
    await update.message.reply_text(
        f"🛡️ **بیمه‌نامه صادر شد!**\n━━━━━━━━━━━━━━\n"
        f"✅ {INSURANCE_DAYS} روز تحت پوشش بیمه خرستانی!\n"
        f"📉 {int(INSURANCE_REFUND*100)}٪ باخت‌های قمارت برمی‌گرده — بدون سقف!\n"
        f"🦹 دزدها هم دیگه حریفت نمی‌شن!\n\n"
        f"💸 هزینه: {INSURANCE_COST:,} {CURRENCY_NAME}",
        parse_mode="Markdown")


# ╔══════════════════════════════════════════════════════════╗
# ║                 فصل 6 🐣 خر شخصی، کره‌خر و جفت‌گیری
# ╚══════════════════════════════════════════════════════════╝
# ============================================================
# 6.1 🐴 نمایش خر شخصی
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
            "equipped_tie": "👔", "equipped_clothes": "👕", "equipped_accessory": "🎀",
            "equipped_talisman": "🛡️", "equipped_magic": "🍀"
        }
        for col, emo in pretty.items():
            try:
                worn = donkey[col]
            except (KeyError, IndexError):
                worn = None
            if worn:
                items.append(f"{emo} {worn}")
    
    title = get_title_by_level(u["level"])
    buffs = get_equipped_buffs(user_id)
    msg = (
        f"🐴 **خرِ {esc_md(u['name'])}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"```\n{art}```\n"
        f"🏅 لقب: {title}\n"
        f"⚡ قدرت خر (رالی): **{buffs['power']}**\n"
    )
    # ⚡ باف‌های فعال
    active = []
    if buffs["work"]: active.append(f"💼 کار +{buffs['work']}٪")
    if buffs["daily"]: active.append(f"🎁 روزانه +{buffs['daily']}٪")
    if buffs["cooldown"]: active.append(f"⏱️ کول‌داون -{buffs['cooldown']}٪")
    if buffs["tax"]: active.append(f"🧾 مالیات -{buffs['tax']}٪")
    if buffs["sound"]: active.append(f"🔊 عرعر +{buffs['sound']}٪")
    if buffs["rob"]: active.append(f"🦹 دزدی +{buffs['rob']}٪")
    if buffs["shield"]: active.append(f"🛡️ سپر {buffs['shield']}٪")
    if buffs["luck"]: active.append(f"🍀 شانس +{buffs['luck']}٪")
    if active:
        msg += "✨ باف‌های فعال: " + " | ".join(active) + "\n"
    if items:
        msg += "🎒 تجهیزات:\n" + "\n".join(items)
    else:
        msg += "🎒🏪 تجهیزات: لخت و پتی! برو فروشگاه"
    return msg

# ============================================================
# 6.2 🐣 کره‌خرها (سود/ارتقا/اسم/پنل)
# ============================================================

# سطح: (اسم سطح، ایموجی، سود روزانه، هزینه ارتقا به این سطح)
BABY_LEVELS = {
    1: {"name": "نوزاد",   "emoji": "🐣", "income": 500,  "cost": 0},
    2: {"name": "کوچولو",  "emoji": "🐤", "income": 1000, "cost": 2000},
    3: {"name": "نوجوون",  "emoji": "🐥", "income": 2000, "cost": 6000},
    4: {"name": "جوون",    "emoji": "🐴", "income": 3500, "cost": 15000},
    5: {"name": "طلایی",   "emoji": "🦄", "income": 5000, "cost": 35000},
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

def babies_pending_income(user_id):
    """💰 سود کره‌خر آماده برداشت — روزی یک بار از پنل. خروجی: (مبلغ, آماده‌ست؟)"""
    u = get_user(user_id)
    if not u:
        return 0, False
    babies = load_babies(u)
    if not babies:
        return 0, False
    income = babies_daily_income(babies)
    last = int(get_setting(f"baby_claim_{user_id}", "0") or 0)
    now = int(time.time())
    if not last:
        # 🛟 تایمر گم شده (ری‌استارت بدون بازیابی) — به نفع کاربر: سود آماده‌ست!
        last = now - 86400
        set_setting(f"baby_claim_{user_id}", str(last))
    if now - last < 86400:
        return income, False
    return income, True

def babies_claim(user_id):
    """برداشت سود کره‌خرها — خروجی: مبلغ واریزشده یا 0"""
    income, ready = babies_pending_income(user_id)
    if not ready or income <= 0:
        return 0
    add_coins(user_id, income)
    set_setting(f"baby_claim_{user_id}", str(int(time.time())))
    return income

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
                "😢 هنوز کره‌خری نداری!\n\n"
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
    lines.append(f"\n💎 جمع سود روزانه: **{total:,}** {CURRENCY_NAME}")
    income, ready = babies_pending_income(user_id)
    if ready:
        lines.append(f"💰🎉 **سود آماده برداشته: +{income:,}** — دکمه رو بزن!")
    else:
        last = int(get_setting(f"baby_claim_{user_id}", "0") or 0)
        remaining = max(0, 86400 - (int(time.time()) - last))
        lines.append(f"⏳ سود بعدی تا {remaining//3600} ساعت و {(remaining%3600)//60} دقیقه دیگه")
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
    income, ready = babies_pending_income(user_id)
    if ready and income > 0:
        rows.insert(0, [InlineKeyboardButton(f"💰 برداشت سود (+{income:,})", callback_data="babe_claim")])
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
                "❤️ هنوز کره‌خری نداری! با `جفت‌گیری` (ریپلی روی یه نفر) صاحب کره‌خر شو!\n"
                f"💰 هر کره‌خر روزی {BABY_LEVELS[1]['income']} تا {BABY_LEVELS[BABY_MAX_LEVEL]['income']} {CURRENCY_NAME} سود می‌ده!")
    lines = [f"🐣 **کره‌خرهای {esc_md(u['name'])}** ({len(babies)}/{MAX_BABIES})", "━━━━━━━━━━━━━━"]
    for i, b in enumerate(babies, 1):
        lines.append(baby_line(i, b))
    total = babies_daily_income(babies)
    lines.append(f"\n💰 جمع سود روزانه: **{total}** {CURRENCY_NAME} (خودکار با «روزانه»)")
    lines.append("\n📋 دستورات:")
    lines.append("⬆️ `ارتقا کره‌خر 1` — ارتقای کره‌خر شماره ۱")
    lines.append("📛 `اسم کره‌خر 1 فلفلی` — تغییر اسم")
    return "\n".join(lines)

async def baby_upgrade_command(update, context, idx):
    user = update.effective_user
    u = get_user(user.id)
    babies = load_babies(u)
    if not babies:
        await update.message.reply_text("❌❤️ هنوز کره‌خری نداری! اول جفت‌گیری کن")
        return
    if idx < 1 or idx > len(babies):
        await update.message.reply_text(f"❌ کره‌خر شماره {idx} نداری! (۱ تا {len(babies)}) — لیست: `کره‌خرها`", parse_mode="Markdown")
        return
    b = babies[idx - 1]
    cur = b.get("level", 1)
    if cur >= BABY_MAX_LEVEL:
        await update.message.reply_text(f"🦄😎 **{esc_md(b['name'])}** الان فول‌لِوِله (طلایی)! بالاتر نداریم", parse_mode="Markdown")
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
        await update.message.reply_text("❌❤️ هنوز کره‌خری نداری! اول جفت‌گیری کن")
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
        f"📛🎉 اسم کره‌خر شماره {idx} از «{esc_md(old)}» شد: **{esc_md(new_name)}**", parse_mode="Markdown")

# ============================================================
# 6.3 ❤️ جفت‌گیری (رضایت + خرید مجوز)
# ============================================================

MATE_COST = 1500
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
        return f"❌💸 {esc_md(user_name)} {MATE_COST} {CURRENCY_NAME} نداری!"
    if u2["coins"] < MATE_COST:
        return f"❌💸 {esc_md(target_name)} {MATE_COST} {CURRENCY_NAME} نداره!"
    
    babies1 = load_babies(u1)
    babies2 = load_babies(u2)
    if len(babies1) >= MAX_BABIES:
        return f"❌ {esc_md(user_name)} دیگه جا برای کره‌خر جدید نداری! (حداکثر {MAX_BABIES})"
    if len(babies2) >= MAX_BABIES:
        return f"❌ {esc_md(target_name)} دیگه جا برای کره‌خر جدید نداره! (حداکثر {MAX_BABIES})"
    
    now = int(time.time())
    # ❤️ مجوز خریداری‌شده کول‌داون رو دور می‌زنه (یه‌بارمصرف)
    if now - u1["last_mate"] < MATE_COOLDOWN and not has_mate_pass(user_id):
        remaining = (MATE_COOLDOWN - (now - u1["last_mate"])) // 3600
        return (f"⏳ {esc_md(user_name)} عزیز، {remaining} ساعت دیگه می‌تونی جفت‌گیری کنی!\n\n"
                f"💰 یا با **{MATE_PASS_COST:,}** {CURRENCY_NAME} همین الان دوباره جفت‌گیری کن!\n"
                f"💬 بنویس: `خرید جفت‌گیری` (روزی فقط یه بار)")
    if now - u2["last_mate"] < MATE_COOLDOWN and not has_mate_pass(target_id):
        remaining = (MATE_COOLDOWN - (now - u2["last_mate"])) // 3600
        return f"⏳ {esc_md(target_name)} عزیز، {remaining} ساعت دیگه می‌تونه جفت‌گیری کنه!"
    return None

# ❤️ مجوز جفت‌گیری اضافه — ۳۰هزار، یه‌بارمصرف، روزی یه بار
MATE_PASS_COST = 30000

def has_mate_pass(user_id):
    return get_setting(f"mate_pass_{user_id}", "0") == "1"

def consume_mate_pass(user_id):
    if has_mate_pass(user_id):
        set_setting(f"mate_pass_{user_id}", "0")

async def buy_mate_reset(update, context):
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    u = get_user(user.id)
    now = int(time.time())
    
    if now - (u["last_mate"] or 0) >= MATE_COOLDOWN:
        await update.message.reply_text("✅❤️ کول‌داون نداری که! همین الان می‌تونی مجانی جفت‌گیری کنی")
        return
    if has_mate_pass(user.id):
        await update.message.reply_text("✅❤️ مجوزت رو قبلاً خریدی! برو جفت‌گیری کن")
        return
    # روزی یه بار
    today = time.strftime("%Y-%m-%d")
    if get_setting(f"mate_buy_day_{user.id}", "") == today:
        await update.message.reply_text("😏🐴 امروز یه بار خریدی! فردا دوباره بیا — بدن هم استراحت می‌خواد!")
        return
    if not remove_coins(user.id, MATE_PASS_COST):
        await update.message.reply_text(f"❌ {MATE_PASS_COST:,} {CURRENCY_NAME} لازمه! داری: {u['coins']:,}")
        return
    set_setting(f"mate_pass_{user.id}", "1")
    set_setting(f"mate_buy_day_{user.id}", today)
    await update.message.reply_text(
        f"❤️‍🔥 **مجوز جفت‌گیری خریدی!**\n━━━━━━━━━━━━━━\n"
        f"💸 {MATE_PASS_COST:,} {CURRENCY_NAME} پرداخت شد.\n"
        f"👉 حالا روی پیام طرف ریپلی بزن و بنویس `جفت‌گیری`!\n"
        f"⚠️ فقط برای **یک** جفت‌گیری اعتبار داره!",
        parse_mode="Markdown")

def mate_do(user_id, target_id):
    """انجام جفت‌گیری بعد از قبول — خروجی: متن نتیجه"""
    u1 = get_user(user_id)
    u2 = get_user(target_id)
    now = int(time.time())
    
    remove_coins(user_id, MATE_COST)
    remove_coins(target_id, MATE_COST)
    consume_mate_pass(user_id)  # ❤️ مجوز خریداری‌شده مصرف شد (یه‌بارمصرف)
    
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
        f"━━━━━━━━━━━━━━\n"
        f"👫 {uname(user_id)} ❤️ {uname(target_id)}\n\n"
        f"🐣 **کره‌خر متولد شد:** {baby_name}\n"
        f"💰 سود روزانه‌ش: {BABY_LEVELS[1]['income']} {CURRENCY_NAME} (با «روزانه» خودکار می‌گیری)\n"
        f"👶 تعداد کره‌خرهای {uname(user_id)}: {len(babies1)}\n"
        f"👶 تعداد کره‌خرهای {uname(target_id)}: {len(babies2)}\n\n"
        f"💸 هزینه: {MATE_COST} {CURRENCY_NAME} از هر نفر\n"
        f"💡 با `کره‌خرها` مدیریتشون کن — اسم بذار و ارتقا بده!"
    )

async def mate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """❤️ درخواست جفت‌گیری — باید طرف مقابل قبول کنه"""
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
        await update.message.reply_text("❌😂 نمی‌تونی با خودت جفت‌گیری کنی!")
        return
    if target.is_bot:
        await update.message.reply_text("❌🤖😂 با ربات نمی‌شه جفت‌گیری کرد!")
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
    
    await query.answer("💚🎉 قبول شد!")
    result = mate_do(prop["from"], prop["to"])
    await query.edit_message_text(result, parse_mode="Markdown")


# ╔══════════════════════════════════════════════════════════╗
# ║                 فصل 7 🎮 بازی‌ها
# ╚══════════════════════════════════════════════════════════╝
# ============================================================
# 7.1 🎮 نام و تنظیمات بازی‌ها
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
    "mines": "💣 مین‌روب",
    "basketball": "🏀 بسکتبال",
    "rally": "🏇 رالی"
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
    "mines": 5,
    "basketball": 10,
    "rally": 2
}

# بازی‌هایی که دقیقاً ۲ نفره هستند
TWO_PLAYER_GAMES = {"rps", "ttt", "coinflip", "penalty", "rally"}

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
    "بمب": "mines",
    "بسکتبال": "basketball",
    "بسکت": "basketball",
    "basketball": "basketball",
    "رالی": "rally",
    "مسابقه": "rally",
    "rally": "rally"
}

# ============================================================
# 7.2 🚪 مدیریت اتاق‌ها (ساخت/تایم‌اوت/پاکسازی)
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
        add_coins(p, room.bet, league=False)

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
    """ویرایش امن پیام اصلی بازی — مقاوم در برابر Flood Control تلگرام"""
    for attempt in range(2):
        try:
            await context.bot.edit_message_text(
                text,
                chat_id=room.chat_id,
                message_id=room.message_id,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            return
        except Exception as e:
            err = str(e)
            # 🚦 flood خوردیم؟ صبر کن و یه بار دیگه امتحان کن
            retry_after = getattr(e, "retry_after", None)
            if retry_after and attempt == 0:
                logger.warning(f"🚦 Flood control: {retry_after}s صبر می‌کنم...")
                await asyncio.sleep(min(float(retry_after) + 1, 30))
                continue
            if "not modified" not in err.lower():
                logger.warning(f"⚠️ خطا در ویرایش پیام بازی: {e}")
            return

async def send_commentary(room, context, text, keyboard=None):
    """🎙️ گزارشگر: پیام جدید به صورت ریپلای روی پیام اصلی بازی
    keyboard: دکمه‌های اکشن زیر همین گزارش (که بازیکن لازم نباشه بره بالا!)"""
    try:
        return await context.bot.send_message(
            chat_id=room.chat_id, text=text,
            reply_to_message_id=room.message_id, parse_mode="Markdown",
            reply_markup=keyboard)
    except Exception:
        try:
            return await context.bot.send_message(chat_id=room.chat_id, text=text,
                                                  parse_mode="Markdown", reply_markup=keyboard)
        except Exception as e:
            logger.warning(f"⚠️ خطا در ارسال گزارش: {e}")
    return None

def result_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎮 بازی جدید", callback_data="games_list"),
                                  InlineKeyboardButton("🏠 منو", callback_data="home")]])

# ============================================================
# 7.3 🔘 منوها و دکمه‌های اصلی
# ============================================================

def main_menu():
    """🏠 منوی اصلی — همه قابلیت‌ها توی بخش‌های دسته‌بندی‌شده"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 بازی‌ها", callback_data="sec_games"),
         InlineKeyboardButton("💰 درآمد", callback_data="sec_income")],
        [InlineKeyboardButton("🏦 بانک و مالی", callback_data="sec_money"),
         InlineKeyboardButton("🕵️ خلاف‌خونه", callback_data="sec_crime")],
        [InlineKeyboardButton("🐴 خر و خانواده", callback_data="sec_donkey"),
         InlineKeyboardButton("🏇 رالی", callback_data="sec_rally")],
        [InlineKeyboardButton("🏆 رقابت و جدول", callback_data="sec_rank"),
         InlineKeyboardButton("🧠 خر دانا", callback_data="sec_dana")],
        [InlineKeyboardButton("👤 پروفایل", callback_data="show_profile"),
         InlineKeyboardButton("📖 راهنما", callback_data="help_main")]
    ])

class _QuickShim:
    """آداپتور: اجازه می‌ده توابع درآمدی (که با پیام متنی کار می‌کنن) از دکمه هم صدا زده بشن"""
    class _Msg:
        def __init__(s, bot, chat_id):
            s._bot = bot; s._chat = chat_id
            s.reply_to_message = None; s.message_id = 0; s.caption = None; s.text = ""
        async def reply_text(s, text, reply_markup=None, parse_mode="Markdown"):
            try:
                return await s._bot.send_message(chat_id=s._chat, text=text,
                                                 reply_markup=reply_markup, parse_mode=parse_mode)
            except Exception:
                return await s._bot.send_message(chat_id=s._chat, text=text, reply_markup=reply_markup)
    def __init__(s, query, context):
        s.effective_user = query.from_user
        s.effective_chat = query.message.chat if hasattr(query.message, "chat") else None
        s.message = _QuickShim._Msg(context.bot, query.message.chat_id)

# ============================================================
# 7.3.1 🗂️ بخش‌های منوی اصلی (هر قابلیت توی بخش خودش)
# ============================================================

def sec_games_text():
    return (
        "🎮 **بخش بازی‌ها**\n"
        "_قمارخونه‌ی طویله — شرط ببند و ببر!_\n"
        "━━━━━━━━━━━━━━\n"
        "🏟️ **۱۵ بازی گروهی** — با رفیقات یا خر بات!\n"
        "🎰 **اسلات فوری** — تکی و سریع با انیمیشن واقعی!\n\n"
        "💬 **دستورات متنی:**\n"
        "💥 `انفجار 500` | `تاس 500` | `رولت 500` | `دارت 500`\n"
        "🎳 `بولینگ 500` | `پنالتی 500` | `بسکتبال 500` | `اسلات 500`\n"
        "🆘 گیر کردی؟ بنویس `لغو بازی`\n\n"
        "👇 از دکمه‌ها انتخاب کن:"
    )

def sec_games_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 لیست همه بازی‌ها", callback_data="games_list")],
        [InlineKeyboardButton("🎰 اسلات فوری", callback_data="instant_slot")],
        [InlineKeyboardButton("📖 راهنمای بازی‌ها", callback_data="help_games")],
        [InlineKeyboardButton("🔙 منو", callback_data="home")]
    ])

def sec_income_text(user_id):
    u = get_user(user_id)
    return (
        "💰 **بخش درآمد**\n"
        "_هر روز بیا، جیبت رو پر کن!_\n"
        "━━━━━━━━━━━━━━\n"
        f"💳 موجودی جیبت: **{(u['coins'] or 0):,}** {CURRENCY_NAME}\n\n"
        "🎁 روزانه ۵۰۰-۱۵۰۰ (هر ۲۴ ساعت)\n"
        "💼 کار تا ۹۰۰ (هر ۳۰ دقیقه)\n"
        "🎡 گردونه تا ۱۰٬۰۰۰ (هر ۳ ساعت)\n"
        "🔮 فال + برکت (هر ۶ ساعت)\n"
        "🔊 عرعر کن — هر صدا ۱۵۰ تا ۱۲۰۰! (هر ۵ دقیقه)\n"
        "🆘 گدایی — مخصوص ورشکسته‌ها (هر ۴ ساعت)\n\n"
        "💬 **دستور متنی:** `روزانه` | `کار` | `گردونه` | `فال` | `گدایی`\n\n"
        "👇 با یه کلیک انجام بده:"
    )

def sec_income_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 جایزه روزانه", callback_data="quick_daily"),
         InlineKeyboardButton("💼 کار", callback_data="quick_work")],
        [InlineKeyboardButton("🎡 گردونه", callback_data="quick_wheel"),
         InlineKeyboardButton("🔮 فال", callback_data="quick_fortune")],
        [InlineKeyboardButton("🆘 گدایی", callback_data="quick_beg"),
         InlineKeyboardButton("🔊 لیست صداها", callback_data="sec_sounds")],
        [InlineKeyboardButton("📖 راهنمای درآمد", callback_data="help_money")],
        [InlineKeyboardButton("🔙 منو", callback_data="home")]
    ])

def sec_money_text(user_id):
    u = get_user(user_id)
    loan = get_loan(user_id)
    loan_line = f"💳 بدهی وام: **{loan:,}**\n" if loan > 0 else ""
    return (
        "🏦 **بخش بانک و مالی**\n"
        "_پولت رو مدیریت کن مثل یه خر حسابدار!_\n"
        "━━━━━━━━━━━━━━\n"
        f"👛 جیب: **{(u['coins'] or 0):,}** | 🏦 بانک: **{(u['bank_balance'] or 0):,}**\n"
        f"{loan_line}\n"
        "💹 بانک: روزی **۲۰٪ سود** — هر روز خودت بردار!\n"
        "🛡️ بیمه: ۲۰٪ باخت‌هات برمی‌گرده (بی‌سقف!) + سپر دزدی\n"
        "💳 وام تا ۳۰هزار با ضامن سطح ۲+\n"
        "💸 انتقال سکه به رفیقات (۱۰٪ مالیات)\n\n"
        "💬 **دستور متنی:**\n"
        "🏦 `بانک` | `واریز 1000` | `واریز همه` | `برداشت همه` | `سود`\n"
        "💳 `وام 5000` (ریپلی روی ضامن) | `تسویه وام`\n"
        "🛡️ `بیمه` | `خرید بیمه` | ریپلی + `انتقال 100`\n\n"
        "👇 پنل‌ها:"
    )

def sec_money_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏦 پنل بانک", callback_data="bankp_home"),
         InlineKeyboardButton("🛡️ پنل بیمه", callback_data="insp_home")],
        [InlineKeyboardButton("💹 برداشت سود بانک", callback_data="bankp_claim")],
        [InlineKeyboardButton("📖 راهنمای مالی", callback_data="help_money")],
        [InlineKeyboardButton("🔙 منو", callback_data="home")]
    ])

def sec_crime_text(user_id):
    jail_left = is_jailed(user_id)
    jail_line = (f"⛓️ **الان بازداشتی!** {jail_left//60} دقیقه دیگه آزاد می‌شی\n\n"
                 if jail_left > 0 else "")
    return (
        "🕵️ **بخش خلاف‌خونه**\n"
        "_ریسک بالا، سود بالا... یا آب خنک!_ 🚔\n"
        "━━━━━━━━━━━━━━\n"
        f"{jail_line}"
        "🦹 **دزدی از رفیق** — ۴۰٪ شانس، جریمه داره! (هر ۲ ساعت)\n"
        "🏦 **دزدی از بانک** — جایزه تا ۵۰هزار، گیر بیفتی ۱ ساعت حبس! (هر ۶ ساعت)\n"
        "💨 **تریاک** — نئشه شی درآمدت ×۲... ولی ۵ بست بکشی معتاد می‌شی! (۵هزار)\n"
        "🍾 **عرق‌خوری** — با رفیقت بزن، جفتتون جایزه بگیرین! (هر ۴ ساعت)\n"
        "🏥 **کمپ ترک** — معتاد شدی؟ ۲۵هزار + ۲۴ ساعت قفل = پاکی!\n"
        "🛡️ طرف بیمه یا طلسم داشته باشه، دزدی سخته!\n\n"
        "💬 **دستور متنی:**\n"
        "🦹 ریپلی + `دزدی` | `دزدی بانک` | `تریاک` | ریپلی + `عرق` | `کمپ`\n\n"
        "👇 دل و جرأت داری؟"
    )

def sec_crime_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏦 دزدی از بانک", callback_data="quick_heist")],
        [InlineKeyboardButton("💨 بساط تریاک", callback_data="crime_opium")],
        [InlineKeyboardButton("🔙 منو", callback_data="home")]
    ])

def sec_donkey_text(user_id):
    u = get_user(user_id)
    babies = load_babies(u) if u else []
    return (
        "🐴 **بخش خر و خانواده**\n"
        "_خرت رو خوشگل کن، خانواده تشکیل بده!_\n"
        "━━━━━━━━━━━━━━\n"
        f"🐣 کره‌خرهات: **{len(babies)}** تا\n\n"
        "🐴 خر شخصیت رو ببین و تجهیزش کن\n"
        "🏪 فروشگاه ۶۴ قلمی: هر وسیله **باف واقعی** می‌ده + ⚡ قدرت خر!\n"
        "🏇 قدرت بیشتر = شانس برد بیشتر تو **رالی**!\n"
        "💰 وسیله‌ها و کادوها رو می‌تونی با ۵۰٪ قیمت بفروشی\n"
        "❤️ جفت‌گیری با ریپلی — کره‌خر دار شو! (سطح ۲+، ۱۵۰۰)\n"
        "🐣 کره‌خرها رو ارتقا بده — سود روزانه تا ۵۰۰۰!\n\n"
        "💬 **دستور متنی:**\n"
        "🐴 `خرم` | `فروشگاه` | ریپلی + `جفت‌گیری`\n"
        "🐣 `کره‌خرها` | `ارتقا کره‌خر 1` | `اسم کره‌خر 1 فلفلی`\n\n"
        "👇 برو تو کارش:"
    )

def sec_donkey_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🐴 خر من", callback_data="quick_donkey"),
         InlineKeyboardButton("🏪 فروشگاه", callback_data="shop")],
        [InlineKeyboardButton("🐣 پنل کره‌خرها", callback_data="babe_home")],
        [InlineKeyboardButton("📖 راهنمای خر شخصی", callback_data="help_donkey")],
        [InlineKeyboardButton("🔙 منو", callback_data="home")]
    ])

def sec_rank_text(user_id):
    u = get_user(user_id)
    wealth = ((u["coins"] or 0) + (u["bank_balance"] or 0)) if u else 0
    return (
        "🏆 **بخش رقابت و جدول**\n"
        "_کی خر اول طویله‌ست؟_ 👑\n"
        "━━━━━━━━━━━━━━\n"
        f"💎 ثروت کل تو: **{wealth:,}** {CURRENCY_NAME}\n\n"
        "🏆 جدول کلی — ۱۰ خر ثروتمند طویله\n"
        "⚡ جدول هفتگی — فعال‌ترین خر هفته! جایزه اول **۲۰۰هزار!** (فقط کار و فعالیت، نه قمار!)\n"
        "🏇 قهرمانان رالی — پرافتخارترین خرهای مسابقه\n"
        "👤 پروفایل با نوار سطح و نشان‌ها\n\n"
        "💬 **دستور متنی:**\n"
        "🏆 `جدول` | `جدول هفتگی` | `پروفایل` | `سکه`\n\n"
        "👇 ببین کجای جدولی:"
    )

def sec_rank_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏆 جدول کلی", callback_data="lb_total"),
         InlineKeyboardButton("⚡ جدول هفتگی", callback_data="lb_week")],
        [InlineKeyboardButton("🏇 قهرمانان رالی", callback_data="rally_top"),
         InlineKeyboardButton("👤 پروفایل من", callback_data="show_profile")],
        [InlineKeyboardButton("🔙 منو", callback_data="home")]
    ])

def games_menu():
    buttons = []
    keys = list(GAME_NAMES.keys())
    # دو تا دو تا کنار هم
    for i in range(0, len(keys), 2):
        row = [InlineKeyboardButton(GAME_NAMES[k], callback_data=f"game_{k}") for k in keys[i:i+2]]
        buttons.append(row)
    # 🎰 اسلات کنار بقیه بازی‌ها (تکی بدون اتاق)
    if len(buttons) and len(buttons[-1]) == 1:
        buttons[-1].append(InlineKeyboardButton("🎰 اسلات", callback_data="instant_slot"))
    else:
        buttons.append([InlineKeyboardButton("🎰 اسلات", callback_data="instant_slot")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="home")])
    return InlineKeyboardMarkup(buttons)

# 📖 آموزش اختصاصی هر بازی — خودمونی و کوتاه
GAME_TUTORIALS = {
    "crash": "💥 آموزش انفجار:\nضریب از ۱ شروع می‌شه و میره بالا. هر لحظه ممکنه منفجر شه!\n💸 قبل انفجار «برداشت» بزن = شرط × ضریب می‌گیری.\nدیر بزنی؟ همه‌چی سوخت! 💀",
    "dice": "🎲 آموزش تاس:\n۵ پرتاب نوبتی — هر کی نوبتش شد ایموجی 🎲 می‌فرسته.\nعدد تاس جمع می‌شه، مجموع بالاتر می‌بره!\nمساوی = راند طلایی 💛",
    "darts": "🎯 آموزش دارت:\n۵ پرتاب نوبتی با ایموجی 🎯 — وسط خال = ۶ امتیاز!\nمجموع بالاتر می‌بره. مساوی = راند طلایی 💛",
    "bowling": "🎳 آموزش بولینگ:\n۵ پرتاب نوبتی با ایموجی 🎳 — استرایک = ۶ امتیاز!\nمجموع بالاتر می‌بره. مساوی = راند طلایی 💛",
    "basketball": "🏀 آموزش بسکتبال:\n۵ پرتاب نوبتی با ایموجی 🏀 — توپ بره تو سبد = ۱ امتیاز!\nسبد بیشتر می‌بره. مساوی = راند طلایی 💛",
    "penalty": "⚽ آموزش پنالتی:\n۲ نفره — نوبتی ایموجی ⚽ بفرستین. ۵ ضربه هر نفر.\nگل بیشتر می‌بره! مساوی = ضربات طلایی 💛",
    "roulette": "🔫 آموزش رولت روسی:\nنوبتی با دکمه انتخاب می‌کنی به کی شلیک شه!\nشانس گلوله ۲ از ۶. خورد = حذف! ☠️\nآخرین بازمانده همه رو می‌بره 🏆",
    "blackjack": "🃏 آموزش بلک‌جک:\nهدف: مجموع کارتات نزدیک ۲۱ باشه ولی رد نشه!\n🎴 «کارت بده» یا ✋ «کافیه» — از ۲۱ رد شی سوختی!\n🔒 کارتات مخفیه — فقط خودت می‌بینی!",
    "poker": "🎰 آموزش پوکر:\nهر کی ۵ کارت می‌گیره — بهترین دست می‌بره!\nجفت < دوجفت < سه‌تایی < استریت < فلاش < فول‌هاوس < کاره!",
    "ttt": "❌⭕ آموزش دوز:\n۲ نفره — نوبتی خونه انتخاب کن.\nسه‌تا ردیف کنی (افقی/عمودی/مورب) بردی! 🏆",
    "rps": "✊ آموزش سنگ‌کاغذقیچی:\nبهترین از ۵ دست — ۳ برد = قهرمانی!\nانتخابات مخفیه 🤫 سنگ>قیچی، قیچی>کاغذ، کاغذ>سنگ!\n⏰ ۱ دقیقه وقت انتخاب داری وگرنه دست می‌سوزه!",
    "coinflip": "🪙 آموزش شیر یا خط:\nهر کی زودتر دکمه بزنه طرفش رو انتخاب می‌کنه!\n🎲 ربات تاس می‌ندازه: زوج = شیر 🦁 | فرد = خط 🌛",
    "hilo": "🔼🔽 آموزش بالا/پایین:\nربات دو تاس واقعی می‌ندازه — حدس بزن مجموع چنده:\n🔼 بالای ۷ = ×۲ | 🎯 دقیقاً ۷ = ×۵ | 🔽 زیر ۷ = ×۲",
    "guessnum": "🔢 آموزش حدس عدد:\nعدد مخفی بین ۱ تا ۱۰۰ — نوبتی تایپ کن!\nربات می‌گه بالاتر🔼 یا پایین‌تر🔽. درست گفتی؟ همه رو بردی! 🏆",
    "rally": "🏇 آموزش رالی:\n۲ نفره — قدرت خرت (وسیله‌های فروشگاه) شانس بردت رو تعیین می‌کنه!\nپیست شانسی + فرم روز + استریک — قوی‌تر تا ۸۸٪ می‌بره ولی شگفتی همیشه هست! 😏\n🚫 خر بات بازی نمی‌کنه — فقط پلیر!",
    "mines": "💣 آموزش مین‌روب:\n۲ نفره: ۹ جعبه | ۳-۵ نفره: ۱۶ جعبه — یکیش بمبه!\nنوبتی جعبه باز کن. بمب = حذف! ☠️ آخرین بازمانده می‌بره!",
}

def shop_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎩 کلاه‌ها", callback_data="shop_hats"),
         InlineKeyboardButton("🐴 زین‌ها", callback_data="shop_saddles")],
        [InlineKeyboardButton("👟 نعل‌ها", callback_data="shop_horseshoes"),
         InlineKeyboardButton("👔 کروات‌ها", callback_data="shop_ties")],
        [InlineKeyboardButton("👕 لباس‌ها", callback_data="shop_clothes"),
         InlineKeyboardButton("🎀 اکسسوری‌ها", callback_data="shop_accessories")],
        [InlineKeyboardButton("🛡️ طلسم‌ها", callback_data="shop_talismans"),
         InlineKeyboardButton("🍀 جادوها", callback_data="shop_magics")],
        [InlineKeyboardButton("💰 فروش وسایل (۵۰٪)", callback_data="sell_menu")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="home")]
    ])

def room_control_keyboard(room: GameRoom):
    buttons = []
    if not room.started:
        if len(room.players) < room.max_players:
            buttons.append([InlineKeyboardButton("👥 ورود به بازی", callback_data=f"room_join_{room.room_id}")])
        # 🤖 بازی با خر بات (وقتی هنوز جا هست و خر بات داخل نیست) — رالی فقط پلیر!
        if room.game_type != "rally" and BOT_ID not in room.players and len(room.players) < room.max_players:
            buttons.append([InlineKeyboardButton("🤖 بازی با خر بات", callback_data=f"room_bot_{room.room_id}")])
        if len(room.players) >= 2:
            buttons.append([InlineKeyboardButton("▶️ شروع بازی", callback_data=f"room_start_{room.room_id}")])
        buttons.append([InlineKeyboardButton("📖 آموزش", callback_data=f"tut_{room.game_type}"),
                        InlineKeyboardButton("❌ لغو", callback_data=f"room_cancel_{room.room_id}")])
    return InlineKeyboardMarkup(buttons)

async def room_timeout_watch(room: GameRoom, context):
    """⏰ اگر بازی تا ۲ دقیقه شروع نشد، خودکار لغو و شرط‌ها برگردانده شود"""
    try:
        await asyncio.sleep(ROOM_START_TIMEOUT)
        current = ACTIVE_ROOMS.get(room.room_id)
        if current is not room or room.started or room.finished:
            return
        for p in room.players:
            add_coins(p, room.bet, league=False)
        room.finished = True
        cleanup_room(room.room_id)
        await edit_room_msg(room, context,
            f"⏰ **بازی {GAME_NAMES[room.game_type]} به دلیل عدم شروع، خودکار لغو شد!**\n"
            f"💰 شرط همه بازیکنان برگشت داده شد.",
            result_keyboard())
    except Exception as e:
        logger.warning(f"⚠️ خطا در تایمر لغو اتاق: {e}")

# ============================================================
# 7.4 🏪 فروشگاه
# ============================================================

# 🏷️ رده‌های آیتم: قیمت → رنگ رده
def item_tier(price):
    if price >= 3000000: return "🔴"   # افسانه‌ای
    if price >= 800000: return "🟠"    # حماسی
    if price >= 100000: return "🟣"    # کمیاب
    if price >= 20000: return "🔵"     # خوب
    return "🟢"                         # معمولی

# 🏪 فروشگاه ۲.۵ — هر آیتم: قیمت + خرپاور (لول خر) + باف ٪
# باف هر دسته: hats=+کار | saddles=+روزانه | horseshoes=-کول‌داون کار/صدا
#              ties=-مالیات انتقال | clothes=+عرعر | accessories=+شانس دزدی
#              talismans=سپر دزدی | magics=+شانس گردونه/فال
SHOP_ITEMS = {
    "hats": {
        "name": "🎩 کلاه‌ها", "buff_name": "💼 کار", "buff_unit": "+٪ دستمزد",
        "items": {
            "کلاه نی": {"price": 2000, "emoji": "🧑‍🌾", "power": 1, "buff": 5},
            "کلاه پشمی": {"price": 8000, "emoji": "🧢", "power": 2, "buff": 8},
            "کلاه کابوی": {"price": 25000, "emoji": "🤠", "power": 3, "buff": 12},
            "کلاه نظامی": {"price": 60000, "emoji": "🪖", "power": 4, "buff": 16},
            "کلاه شیک": {"price": 150000, "emoji": "🎩", "power": 6, "buff": 20},
            "کلاه خلبانی": {"price": 400000, "emoji": "🧑‍✈️", "power": 8, "buff": 25},
            "تاج سلطنتی": {"price": 1200000, "emoji": "👑", "power": 12, "buff": 32},
            "تاج خدای خرها": {"price": 5000000, "emoji": "😇", "power": 20, "buff": 40}
        }
    },
    "saddles": {
        "name": "🐴 زین‌ها", "buff_name": "🎁 روزانه", "buff_unit": "+٪ جایزه",
        "items": {
            "زین پارچه‌ای": {"price": 2000, "emoji": "🟫", "power": 1, "buff": 5},
            "زین چرمی": {"price": 8000, "emoji": "🪑", "power": 2, "buff": 8},
            "زین نقره‌ای": {"price": 25000, "emoji": "🥈", "power": 3, "buff": 12},
            "زین طلایی": {"price": 60000, "emoji": "🥇", "power": 4, "buff": 16},
            "زین الماسی": {"price": 150000, "emoji": "💎", "power": 6, "buff": 20},
            "زین سلطنتی": {"price": 400000, "emoji": "🏇", "power": 8, "buff": 25},
            "زین اژدها": {"price": 1200000, "emoji": "🐉", "power": 12, "buff": 32},
            "زین کهکشانی": {"price": 5000000, "emoji": "🌌", "power": 20, "buff": 40}
        }
    },
    "horseshoes": {
        "name": "👟 نعل‌ها", "buff_name": "⏱️ سرعت", "buff_unit": "-٪ کول‌داون کار/صدا",
        "items": {
            "نعل زنگ‌زده": {"price": 2000, "emoji": "🩹", "power": 1, "buff": 3},
            "نعل آهنی": {"price": 8000, "emoji": "⚙️", "power": 2, "buff": 5},
            "نعل برنزی": {"price": 25000, "emoji": "🟠", "power": 3, "buff": 8},
            "نعل نقره‌ای": {"price": 60000, "emoji": "⚪", "power": 4, "buff": 11},
            "نعل طلایی": {"price": 150000, "emoji": "✨", "power": 6, "buff": 14},
            "نعل الماسی": {"price": 400000, "emoji": "💠", "power": 8, "buff": 17},
            "نعل آذرخش": {"price": 1200000, "emoji": "⚡", "power": 12, "buff": 20},
            "نعل نور": {"price": 5000000, "emoji": "🌟", "power": 20, "buff": 25}
        }
    },
    "ties": {
        "name": "👔 کروات‌ها", "buff_name": "🧾 مالیات", "buff_unit": "-٪ مالیات انتقال",
        "items": {
            "کروات کهنه": {"price": 2000, "emoji": "⬛", "power": 1, "buff": 1},
            "کروات ساده": {"price": 8000, "emoji": "🟦", "power": 2, "buff": 2},
            "کروات راه‌راه": {"price": 25000, "emoji": "🟪", "power": 3, "buff": 3},
            "کروات پولک‌دار": {"price": 60000, "emoji": "✨", "power": 4, "buff": 4},
            "کروات ابریشمی": {"price": 150000, "emoji": "🎀", "power": 6, "buff": 5},
            "کروات طلاکوب": {"price": 400000, "emoji": "🏵️", "power": 8, "buff": 6},
            "کروات سلطنتی": {"price": 1200000, "emoji": "👔", "power": 12, "buff": 8},
            "کروات وزیر خرها": {"price": 5000000, "emoji": "🎩", "power": 20, "buff": 10}
        }
    },
    "clothes": {
        "name": "👕 لباس‌ها", "buff_name": "🔊 عرعر", "buff_unit": "+٪ درآمد صدا",
        "items": {
            "لباس پاره": {"price": 2000, "emoji": "🩲", "power": 1, "buff": 5},
            "لباس ساده": {"price": 8000, "emoji": "👕", "power": 2, "buff": 8},
            "لباس شیک": {"price": 25000, "emoji": "🧥", "power": 3, "buff": 12},
            "لباس مجلسی": {"price": 60000, "emoji": "🤵", "power": 4, "buff": 16},
            "لباس نظامی": {"price": 150000, "emoji": "🎖️", "power": 6, "buff": 20},
            "لباس خواننده": {"price": 400000, "emoji": "🎤", "power": 8, "buff": 25},
            "لباس سلطنتی": {"price": 1200000, "emoji": "👘", "power": 12, "buff": 32},
            "لباس اپرای خرستان": {"price": 5000000, "emoji": "🎭", "power": 20, "buff": 40}
        }
    },
    "accessories": {
        "name": "🎀 اکسسوری‌ها", "buff_name": "🦹 دزدی", "buff_unit": "+٪ شانس دزدی",
        "items": {
            "زنگوله گردن": {"price": 2000, "emoji": "🔔", "power": 1, "buff": 1},
            "پاپیون ساده": {"price": 8000, "emoji": "🎀", "power": 2, "buff": 2},
            "شال گردن": {"price": 25000, "emoji": "🧣", "power": 3, "buff": 3},
            "عینک آفتابی": {"price": 60000, "emoji": "😎", "power": 4, "buff": 4},
            "دستکش چرمی": {"price": 150000, "emoji": "🧤", "power": 6, "buff": 5},
            "نقاب شب": {"price": 400000, "emoji": "🥷", "power": 8, "buff": 6},
            "بال فرشته": {"price": 1200000, "emoji": "🕊️", "power": 12, "buff": 8},
            "هاله خر مقدس": {"price": 5000000, "emoji": "🪽", "power": 20, "buff": 10}
        }
    },
    "talismans": {
        "name": "🛡️ طلسم‌ها", "buff_name": "🛡️ سپر", "buff_unit": "٪ دفع دزد",
        "items": {
            "طلسم چوبی": {"price": 2000, "emoji": "🪵", "power": 1, "buff": 5},
            "طلسم سنگی": {"price": 8000, "emoji": "🪨", "power": 2, "buff": 8},
            "طلسم چشم‌نظر": {"price": 25000, "emoji": "🧿", "power": 3, "buff": 12},
            "طلسم نعل و اسپند": {"price": 60000, "emoji": "🌿", "power": 4, "buff": 16},
            "طلسم عقاب": {"price": 150000, "emoji": "🦅", "power": 6, "buff": 20},
            "طلسم گرگ": {"price": 400000, "emoji": "🐺", "power": 8, "buff": 25},
            "طلسم اژدها": {"price": 1200000, "emoji": "🐲", "power": 12, "buff": 30},
            "طلسم خدایان": {"price": 5000000, "emoji": "⚜️", "power": 20, "buff": 35}
        }
    },
    "magics": {
        "name": "🍀 جادوها", "buff_name": "🎡 شانس", "buff_unit": "+٪ شانس گردونه/فال",
        "items": {
            "شبدر ۴برگ": {"price": 2000, "emoji": "🍀", "power": 1, "buff": 3},
            "سکه شانس": {"price": 8000, "emoji": "🪙", "power": 2, "buff": 5},
            "جام جادو": {"price": 25000, "emoji": "🏺", "power": 3, "buff": 8},
            "گوی بلورین": {"price": 60000, "emoji": "🔮", "power": 4, "buff": 11},
            "عصای جادو": {"price": 150000, "emoji": "🪄", "power": 6, "buff": 14},
            "کتاب طلسمات": {"price": 400000, "emoji": "📕", "power": 8, "buff": 17},
            "ققنوس کوچک": {"price": 1200000, "emoji": "🐦‍🔥", "power": 12, "buff": 20},
            "اسب شاخدار": {"price": 5000000, "emoji": "🦄", "power": 20, "buff": 25}
        }
    }
}

# نگاشت دسته → ستون DB
SHOP_COL_MAP = {
    "hats": "equipped_hat", "saddles": "equipped_saddle", "horseshoes": "equipped_horseshoe",
    "ties": "equipped_tie", "clothes": "equipped_clothes", "accessories": "equipped_accessory",
    "talismans": "equipped_talisman", "magics": "equipped_magic"
}

# 💸 قیمت آیتم‌های فروشگاه قدیمی (قبل از آپدیت ۲.۵) — برای برگشت کامل پول
OLD_SHOP_PRICES = {
    "کلاه نی": 1500, "کلاه کابوی": 6000, "کلاه نظامی": 12000, "کلاه شیک": 21000, "تاج سلطنتی": 45000,
    "زین چرمی ساده": 3000, "زین نقره‌ای": 10500, "زین طلایی": 24000, "زین الماسی": 60000,
    "نعل آهنی": 1500, "نعل برنزی": 6000, "نعل نقره‌ای": 15000, "نعل طلایی": 36000,
    "کروات ساده": 1500, "کروات راه‌راه": 4500, "کروات پولک‌دار": 9000, "کروات ابریشمی": 18000, "کروات سلطنتی": 30000,
    "لباس ساده": 1500, "لباس شیک": 6000, "لباس مجلسی": 12000, "لباس نظامی": 21000, "لباس سلطنتی": 45000,
    "زنگوله گردن": 1500, "پاپیون ساده": 3000, "عینک آفتابی": 7500, "شال گردن": 12000, "بال فرشته": 30000
}

def migrate_old_shop_refund():
    """💸 مهاجرت یه‌بارمصرف: وسیله‌های فروشگاه قدیمی → پول کامل برگرده + اسلات خالی شه
    (فقط وسیله‌هایی که تو انبار جدید ثبت نشدن — یعنی خرید قبل از آپدیت)"""
    if get_setting("shop2_refund_done", "") == "1":
        return 0, 0
    refunded_users, total = 0, 0
    old_cols = ["equipped_hat", "equipped_saddle", "equipped_horseshoe",
                "equipped_tie", "equipped_clothes", "equipped_accessory"]
    try:
        with closing(db_connect()) as db:
            rows = db.execute("SELECT * FROM donkeys").fetchall()
            for d in rows:
                uid = d["user_id"]
                try:
                    new_items = json.loads(d["items"] or "[]")
                except Exception:
                    new_items = []
                refund = 0
                clears = []
                for col in old_cols:
                    worn = d[col]
                    # آیتم قدیمیه (تو انبار جدید نیست) → قیمت قدیمش برگرده
                    if worn and worn in OLD_SHOP_PRICES and worn not in new_items:
                        refund += OLD_SHOP_PRICES[worn]
                        clears.append(col)
                if refund > 0:
                    for col in clears:
                        db.execute(f"UPDATE donkeys SET {col} = '' WHERE user_id = ?", (uid,))
                    # 💸 SQL مستقیم → تو جدول هفتگی حساب نمی‌شه!
                    db.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (refund, uid))
                    refunded_users += 1
                    total += refund
                    # 📬 یادداشت برای اطلاع‌رسانی — اولین دستور بعدی کاربر پیام می‌گیره
                    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                              (f"shop_refund_note_{uid}", str(refund)))
            db.commit()
    except Exception as e:
        logger.error(f"❌ خطا در برگشت پول فروشگاه قدیمی: {e}")
        return refunded_users, total
    set_setting("shop2_refund_done", "1")
    if refunded_users:
        logger.info(f"💸 برگشت پول فروشگاه قدیمی: {refunded_users} کاربر — جمعاً {total:,}")
    return refunded_users, total

def find_shop_item(item_name):
    """جستجوی آیتم تو کل فروشگاه — خروجی: (دسته، دیتا) یا (None, None)"""
    for cat, cd in SHOP_ITEMS.items():
        if item_name in cd["items"]:
            return cat, cd["items"][item_name]
    return None, None

def get_equipped_buffs(user_id):
    """⚡ جمع باف‌های وسایل پوشیده‌شده — خروجی: dict به تفکیک دسته + خرپاور کل"""
    d = get_donkey(user_id)
    out = {"work": 0, "daily": 0, "cooldown": 0, "tax": 0, "sound": 0, "rob": 0, "shield": 0, "luck": 0, "power": 0}
    if not d: return out
    buff_key = {"hats": "work", "saddles": "daily", "horseshoes": "cooldown", "ties": "tax",
                "clothes": "sound", "accessories": "rob", "talismans": "shield", "magics": "luck"}
    for cat, col in SHOP_COL_MAP.items():
        try:
            worn = d[col]
        except (KeyError, IndexError):
            worn = None
        if worn and worn in SHOP_ITEMS[cat]["items"]:
            it = SHOP_ITEMS[cat]["items"][worn]
            out[buff_key[cat]] += it["buff"]
            out["power"] += it["power"]
    return out

def donkey_power(user_id):
    """⚡ لول خر = جمع خرپاور وسیله‌های تنش"""
    return get_equipped_buffs(user_id)["power"]

def load_donkey_items(user_id):
    """🎒 انبار وسایل خریداری‌شده (لیست اسم آیتم‌ها)"""
    d = get_donkey(user_id)
    if not d: return []
    try:
        raw = d["items"] if d["items"] else "[]"
        return json.loads(raw)
    except Exception:
        return []

def save_donkey_items(user_id, items):
    with closing(db_connect()) as db:
        db.execute("UPDATE donkeys SET items = ? WHERE user_id = ?", (json.dumps(items, ensure_ascii=False), user_id))
        db.commit()

# ============================================================
# 7.5 🃏 ابزار کارت (بلک‌جک/پوکر)
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
# 7.6 ⚙️ موتور بازی‌ها (همه بازی‌های گروهی + گزارشگر)
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
        await coinflip_begin(room, context)
    elif gt in ("dice", "darts", "bowling", "penalty", "basketball"):
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
    elif gt == "rally":
        await rally_room_begin(room, context)

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

RPS_WINS_NEEDED = 3       # ✊ بهترین از ۵ — ۳ برد = قهرمانی
RPS_TIMEOUT_FIRST = 60    # ⏰ بار اول انتخاب نکنی: اون دست رو می‌بازی
RPS_TIMEOUT_REPEAT = 30   # ⏰ تکرار شه: حذف — حریف کل پول رو می‌بره

RPS_COMM_WIN = [
    "🎙️🔥 چه حرکتی! حریف رو غافلگیر کرد!",
    "🎙️🧠 دستشو خوند مثل کتاب باز!",
    "🎙️📣 ضربه کاری! تماشاگرا هورا کشیدن!",
    "🎙️🎭 استاد روانشناسی! می‌دونست چی می‌زنه!",
    "🎙️😱 بی‌رحمانه بود! حریف هنوز تو شوکه!",
]
RPS_COMM_DRAW = [
    "🎙️🤝 مساوی! ذهن‌هاشون یکی شد!",
    "🎙️🔄 هر دو یه چیز زدن! دوباره!",
    "🎙️🐴🐴 تله‌پاتی خری! همفکر شدن!",
]

def rps_status_text(room):
    gd = room.game_data
    p1, p2 = room.players[0], room.players[1]
    w1, w2 = gd["wins"].get(p1, 0), gd["wins"].get(p2, 0)
    lines = [
        f"✊ **سنگ‌کاغذقیچی**",
        "_بهترین از ۵ دست — ۳ برد = قهرمانی_",
        "━━━━━━━━━━━━━━",
        f"💰 جایزه: **{room.pot():,}** {CURRENCY_NAME}",
        "",
        f"🔵 {uname(p1)}: {'🏅' * w1}{'▫️' * (RPS_WINS_NEEDED - w1)}  ({w1})",
        f"🔴 {uname(p2)}: {'🏅' * w2}{'▫️' * (RPS_WINS_NEEDED - w2)}  ({w2})",
        "",
        f"🎲 دست {gd['round']} — 🤫 هر دو مخفیانه انتخاب کنید:",
        f"⏳ انتخاب‌شده: {len([u for u in gd['choices'] if u != BOT_ID or True])}/2" if gd["choices"] else "⏳ انتخاب‌شده: 0/2",
    ]
    return "\n".join(lines)

async def rps_deadline_watch(room, context):
    """⏱️ ناظر تایم‌اوت سنگ‌کاغذقیچی — پله‌ای: اول دست می‌سوزه، بعد حذف!"""
    try:
        while ACTIVE_ROOMS.get(room.room_id) is room and not room.finished:
            gd = room.game_data
            p1, p2 = room.players[0], room.players[1]
            waiting = [p for p in (p1, p2) if p not in gd["choices"] and p != BOT_ID]
            if not waiting:
                await asyncio.sleep(2)
                continue
            # کمترین مهلت بین منتظرها (اگه یکیشون سابقه‌دار باشه ۳۰ثانیه‌ست)
            slow = any(p in gd.setdefault("slowpokes", set()) for p in waiting)
            limit = RPS_TIMEOUT_REPEAT if slow else RPS_TIMEOUT_FIRST
            mark = room.last_action
            rnd = gd["round"]
            await asyncio.sleep(limit)
            if ACTIVE_ROOMS.get(room.room_id) is not room or room.finished:
                return
            if room.last_action != mark or gd["round"] != rnd:
                continue  # حرکتی شده — از اول بپا
            gd = room.game_data
            waiting = [p for p in (p1, p2) if p not in gd["choices"] and p != BOT_ID]
            if not waiting:
                continue
            for lazy in waiting:
                opp = p2 if lazy == p1 else p1
                if lazy in gd.setdefault("slowpokes", set()):
                    # ☠️ تکرار — حذف کامل، حریف کل پول رو می‌بره
                    add_coins(opp, room.pot(), league=False)
                    record_win(opp)
                    record_loss(lazy, room.bet)
                    await send_commentary(room, context,
                        f"☠️ {uname(lazy)} دوباره غیبش زد! 🎙️ داور از بازی **حذفش کرد!**")
                    await finish_game(room, context,
                        f"✊ **سنگ‌کاغذقیچی — پایان!**\n━━━━━━━━━━━━━━\n"
                        f"🎙️😴 {uname(lazy)} سر وقت انتخاب نکرد و حذف شد!\n\n"
                        f"🏆 برنده: **{uname(opp)}**\n💰 جایزه: {room.pot()} {CURRENCY_NAME}")
                    return
                # ⏰ بار اول — این دست رو می‌بازه
                gd["slowpokes"].add(lazy)
                gd["wins"][opp] = gd["wins"].get(opp, 0) + 1
                room.last_action = time.time()
                w = gd["wins"][opp]
                if w >= RPS_WINS_NEEDED:
                    add_coins(opp, room.pot(), league=False)
                    record_win(opp)
                    record_loss(lazy, room.bet)
                    await finish_game(room, context,
                        f"✊ **سنگ‌کاغذقیچی — پایان!**\n━━━━━━━━━━━━━━\n"
                        f"🎙️😴 {uname(lazy)} خواب موند و دست آخر رو باخت!\n\n"
                        f"🏆 برنده: **{uname(opp)}** با {w} برد\n💰 جایزه: {room.pot()} {CURRENCY_NAME}")
                    return
                gd["round"] += 1
                gd["choices"] = {}
                if BOT_ID in room.players:
                    gd["choices"][BOT_ID] = random.choice(["rock", "paper", "scissors"])
                await send_commentary(room, context,
                    f"⏰ وقت {uname(lazy)} تموم شد! 🎙️ داور اعلام کرد: **این دست به {uname(opp)} رسید!** ({gd['wins'].get(p1,0)}-{gd['wins'].get(p2,0)})\n"
                    f"⚠️ {uname(lazy)}! دفعه بعد فقط {RPS_TIMEOUT_REPEAT} ثانیه وقت داری وگرنه حذفی!\n"
                    f"👉 دست {gd['round']} — انتخاب کنید!")
                await edit_room_msg(room, context, rps_status_text(room), rps_keyboard(room))
                break  # این چرخه تموم — دوباره بپا
    except Exception as e:
        logger.warning(f"⚠️ خطا در ناظر سنگ‌کاغذقیچی: {e}")

async def rps_begin(room, context):
    room.game_data = {"choices": {}, "wins": {}, "round": 1, "slowpokes": set()}
    room.last_action = time.time()
    if BOT_ID in room.players:
        room.game_data["choices"][BOT_ID] = random.choice(["rock", "paper", "scissors"])
    p1, p2 = room.players[0], room.players[1]
    await edit_room_msg(room, context, rps_status_text(room), rps_keyboard(room))
    await send_commentary(room, context,
        f"🎙️ دوئل سنگ‌کاغذقیچی شروع شد! {uname(p1)} 🆚 {uname(p2)}\n"
        f"🏆🤫 هر کی ۳ دست ببره قهرمانه! انتخاب‌هاتون مخفیه...\n"
        f"⏰ هر دست ۱ دقیقه وقت داری — دیر بجنبی دست رو باختی!")
    context.application.create_task(rps_deadline_watch(room, context))

async def rps_action(room, context, query, choice):
    uid = query.from_user.id
    gd = room.game_data
    if uid in gd["choices"]:
        await query.answer("✅ قبلاً انتخاب کردی!", show_alert=True)
        return
    gd["choices"][uid] = choice
    await query.answer(f"🤫 انتخاب شد: {RPS_EMOJI[choice]}")
    
    p1, p2 = room.players[0], room.players[1]
    
    if len(gd["choices"]) < 2:
        await edit_room_msg(room, context, rps_status_text(room), rps_keyboard(room))
        return
    
    c1, c2 = gd["choices"][p1], gd["choices"][p2]
    beats = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
    reveal = f"👤 {uname(p1)}: {RPS_EMOJI[c1]}  🆚 👤 {uname(p2)}: {RPS_EMOJI[c2]}"
    
    if c1 == c2:
        # مساوی → همون دست دوباره
        gd["choices"] = {}
        if BOT_ID in room.players:
            gd["choices"][BOT_ID] = random.choice(["rock", "paper", "scissors"])
        await send_commentary(room, context,
            f"🎲 دست {gd['round']}:\n{reveal}\n{random.choice(RPS_COMM_DRAW)}\n\n🔁 همین دست دوباره بازی می‌شه!")
        await edit_room_msg(room, context, rps_status_text(room), rps_keyboard(room))
        return
    
    hand_winner = p1 if beats[c1] == c2 else p2
    gd["wins"][hand_winner] = gd["wins"].get(hand_winner, 0) + 1
    w = gd["wins"][hand_winner]
    
    # 🏆 برد زودهنگام: ۲ دست برد = تمام (نیازی به دست سوم نیست)
    if w >= RPS_WINS_NEEDED:
        loser = p2 if hand_winner == p1 else p1
        add_coins(hand_winner, room.pot(), league=False)
        record_win(hand_winner)
        record_loss(loser, room.bet)
        w1, w2 = gd["wins"].get(p1, 0), gd["wins"].get(p2, 0)
        await send_commentary(room, context,
            f"🎲 دست {gd['round']}:\n{reveal}\n{random.choice(RPS_COMM_WIN)}")
        await finish_game(room, context,
            f"✊ **سنگ-کاغذ-قیچی — پایان!**\n━━━━━━━━━━━━━━\n"
            f"📊 {uname(p1)} **{w1}** - **{w2}** {uname(p2)}\n\n"
            f"🎙️ تمووووم شد! **{uname(hand_winner)}** با {w} برد قهرمان شد!\n"
            f"💰 جایزه: {room.pot()} {CURRENCY_NAME}")
        return
    
    # دست بعدی
    gd["round"] += 1
    gd["choices"] = {}
    if BOT_ID in room.players:
        gd["choices"][BOT_ID] = random.choice(["rock", "paper", "scissors"])
    await send_commentary(room, context,
        f"🎲 دست {gd['round']-1}:\n{reveal}\n{random.choice(RPS_COMM_WIN)}\n\n"
        f"🏅 این دست رو **{uname(hand_winner)}** برد! ({gd['wins'].get(p1,0)}-{gd['wins'].get(p2,0)})\n"
        f"👉 دست {gd['round']} — دوباره انتخاب کنید!")
    await edit_room_msg(room, context, rps_status_text(room), rps_keyboard(room))

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
        add_coins(winner, room.pot(), league=False)
        record_win(winner)
        record_loss(loser, room.bet)
        board_txt = "\n".join("".join(gd["board"][j] if gd["board"][j] else "⬜" for j in range(i, i+3)) for i in range(0, 9, 3))
        await finish_game(room, context,
            f"❌⭕ **دوز — پایان**\n━━━━━━━━━━━━━━\n{board_txt}\n\n"
            f"🏆 برنده: **{uname(winner)}** ({w})\n💰 جایزه: {room.pot()} {CURRENCY_NAME}")
        return True
    if all(gd["board"]):
        for p in room.players:
            add_coins(p, room.bet, league=False)
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

def coinflip_keyboard(room):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🦁 شیر", callback_data=gcb(room.room_id, "cf_lion")),
        InlineKeyboardButton("🌛 خط", callback_data=gcb(room.room_id, "cf_moon"))
    ]])

async def coinflip_begin(room, context):
    """🪙 اول انتخاب طرف با دکمه — بعد ربات یه تاس واقعی می‌ندازه!"""
    room.game_data = {"sides": {}}
    p1, p2 = room.players[0], room.players[1]
    # 🤖 اگه خر بات بازیکنه، انتخاب دست آدمه — خر بات هر چی موند برمی‌داره
    await edit_room_msg(room, context,
        f"🪙 **شیر یا خط**\n━━━━━━━━━━━━━━\n"
        f"💰 جایزه: **{room.pot():,}** {CURRENCY_NAME}\n"
        f"👤 {uname(p1)} 🆚 {uname(p2)}\n\n"
        f"⚡ هر کی زودتر بزنه، طرفش رو **خودش انتخاب می‌کنه**!\n"
        f"نفر دوم خودکار اون‌یکی می‌شه.\n\n"
        f"🎲 بعدش ربات تاس می‌ندازه:\n"
        f"⚖️ زوج (۲،۴،۶) = **شیر** 🦁 | فرد (۱،۳،۵) = **خط** 🌛",
        coinflip_keyboard(room))

async def coinflip_action(room, context, query, side):
    """cf_lion / cf_moon — اولین کلیک طرف‌ها رو قفل می‌کنه"""
    uid = query.from_user.id
    gd = room.game_data
    if gd.get("locked"):
        await query.answer("⏳ انتخاب‌ها قفل شده — تاس داره میاد!", show_alert=True)
        return
    gd["locked"] = True
    p1, p2 = room.players[0], room.players[1]
    opp = p2 if uid == p1 else p1
    pick = "lion" if side == "lion" else "moon"
    other = "moon" if pick == "lion" else "lion"
    gd["sides"] = {uid: pick, opp: other}
    names = {"lion": "🦁 شیر", "moon": "🌛 خط"}
    await query.answer(f"✅ تو شدی: {names[pick]}")
    
    await send_commentary(room, context,
        f"🎙️ {uname(uid)} سریع‌تر بود و **{names[pick]}** رو برداشت!\n"
        f"{uname(opp)} شد **{names[other]}**!\n\n"
        f"🎲 ربات داره تاس می‌ندازه... زوج = شیر 🦁 | فرد = خط 🌛")
    await edit_room_msg(room, context,
        f"🪙 **شیر یا خط**\n━━━━━━━━━━━━━━\n"
        f"{names[gd['sides'][p1]]}: {uname(p1)}\n"
        f"{names[gd['sides'][p2]]}: {uname(p2)}\n\n"
        f"🎲 تاس در حال پرتاب...")
    
    # 🎲 تاس واقعی ربات!
    value = None
    try:
        sent = await context.bot.send_dice(
            chat_id=room.chat_id, emoji="🎲",
            reply_to_message_id=room.message_id)
        value = sent.dice.value
    except Exception as e:
        logger.warning(f"⚠️ تاس شیرخط نرفت: {e}")
        value = random.randint(1, 6)
    await asyncio.sleep(3.5)  # صبر تا انیمیشن تموم شه
    if room.finished or ACTIVE_ROOMS.get(room.room_id) is not room:
        return
    
    result = "lion" if value % 2 == 0 else "moon"
    winner = p1 if gd["sides"][p1] == result else p2
    loser = p2 if winner == p1 else p1
    add_coins(winner, room.pot(), league=False)
    record_win(winner)
    record_loss(loser, room.bet)
    
    await finish_game(room, context,
        f"🪙 **شیر یا خط — نتیجه**\n━━━━━━━━━━━━━━\n"
        f"{names[gd['sides'][p1]]}: {uname(p1)}\n"
        f"{names[gd['sides'][p2]]}: {uname(p2)}\n\n"
        f"🎲 تاس اومد: **{value}** ({'زوج' if value % 2 == 0 else 'فرد'}) → {names[result]}!\n\n"
        f"🏆 برنده: **{uname(winner)}**\n💰 جایزه: {room.pot()} {CURRENCY_NAME}")

# ------------------------------------------------------------
# 🎲 تاس (۲ تا ۱۰ نفره)
# ------------------------------------------------------------

# نگاشت اتاق‌های تاس منتظر پرتاب: {chat_id: room_id}
DICE_WAITING = {}

# ------------------------------------------------------------
# 🎯🎳⚽ بازی‌های ایموجی (دارت، بولینگ، پنالتی) — مثل تاس
# ------------------------------------------------------------

EMOJI_OF_GAME = {"dice": "🎲", "darts": "🎯", "bowling": "🎳", "penalty": "⚽", "basketball": "🏀"}
GAME_OF_EMOJI = {v: k for k, v in EMOJI_OF_GAME.items()}
PENALTY_SHOTS = 5  # ⚽ هر بازیکن ۵ ضربه — نوبتی! مساوی شد، ضربات طلایی

# 🎙️ گزارشگر پنالتی
PENALTY_COMMENTARY_GOAL = [
    "🔥 گگگگلللل!!! چه ضربه‌ای! دروازه‌بان فقط نگاه کرد!",
    "🎯 گل شد! توپ چسبید به گوشه دروازه — سانتی‌متری!",
    "🤯 گللللل! دروازه‌بان شیرجه زد ولی توپ رد شده بود!",
    "🖼️ چه گلی! این ضربه رو باید قاب گرفت زد به دیوار طویله!",
    "🐴⚽ گل! خونسرد مثل یه خر حرفه‌ای... بی‌رحمانه!",
    "😂 تور تکون خورد! دروازه‌بان هنوز دنبال توپ می‌گرده!",
    "✨ پنالتی‌زنِ مادرزاد! گل تماشایی!",
]
PENALTY_COMMENTARY_MISS = [
    "😵 ووووی! زد بیرون! توپ رفت هوا و برنگشت!",
    "🧤 مهار شد!! دروازه‌بان مثل پلنگ پرید!",
    "😩 تیرررک! صدای تیر همه‌جا پیچید!",
    "🙈 چیپ زد ولی دروازه‌بان جُم نخورد! آبروریزی!",
    "😰 خراب کرد! فشار پنالتی کمرش رو شکست!",
    "😂 توپ رفت بیرونِ بیرون... کره‌خرا هم بهش خندیدن!",
    "🫠 پاش لیز خورد! توپ سُر خورد رفت گوشه!",
]
PENALTY_COMMENTARY_TENSION = [
    "😰 حساس‌ترین لحظه بازی...",
    "🤐 سکوت عجیبی طویله رو گرفته...",
    "😮 تماشاگرا نفسشون رو حبس کردن...",
    "💓 قلب همه داره تند می‌زنه...",
]

def penalty_status_text(room, commentary=""):
    """⚽ تابلوی دوئل پنالتی"""
    gd = room.game_data
    p1, p2 = room.players[0], room.players[1]
    s1, s2 = gd["shots"].get(p1, []), gd["shots"].get(p2, [])
    g1 = sum(1 for v in s1 if v >= 3)
    g2 = sum(1 for v in s2 if v >= 3)
    
    def strip(shots, total):
        out = ""
        for v in shots:
            out += "⚽" if v >= 3 else "❌"
        out += "▫️" * max(0, total - len(shots))
        return out
    
    total_shots = max(PENALTY_SHOTS, len(s1), len(s2))
    shooter = room.players[gd["turn"]]
    shot_no = len(gd["shots"].get(shooter, [])) + 1
    
    # 🎙️ تحلیل زنده
    diff = abs(g1 - g2)
    if len(s1) + len(s2) == 0:
        analysis = "🏁 سوت شروع! کی خونسردتره؟"
    elif diff == 0:
        analysis = random.choice(["🥶 مساویه! هر ضربه می‌تونه سرنوشت‌ساز باشه!", "😱 سر به سر! نفس‌ها حبس شد!"])
    elif diff == 1:
        analysis = "😱 اختلاف فقط ۱ گل! نفس‌گیر شد!"
    else:
        leader = p1 if g1 > g2 else p2
        analysis = f"🔥 {uname(leader)} {diff} گل جلوئه!"
    
    phase = "💛 ضربات طلایی — مرگ ناگهانی!" if gd.get("sudden") else "🥅 سری پنالتی ۵ ضربه‌ای"
    mx = max(g1, g2, 1)
    lines = [
        f"        ⚔️⚽ **دوئل پنالتی** ⚽⚔️",
        f"_{phase}_",
        "━━━━━━━━━━━━━━",
        f"💰 {room.pot():,} {CURRENCY_NAME}",
        "",
        f"{'👉' if shooter==p1 else '　'} **{uname(p1)}** — **{g1}** گل",
        f"　 {strip(s1, total_shots)}",
        f"　 {_power_bar(g1, mx)}",
        "",
        f"{'👉' if shooter==p2 else '　'} **{uname(p2)}** — **{g2}** گل",
        f"　 {strip(s2, total_shots)}",
        f"　 {_power_bar(g2, mx)}",
        "━━━━━━━━━━━━━━",
        analysis,
    ]
    if commentary:
        lines.append(commentary)
    lines.append(f"🎯 نوبت: **{uname(shooter)}** — ضربه {shot_no}")
    lines.append("💡 کپی کن بفرست: ⚽")
    return "\n".join(lines)

def penalty_decided(room):
    """بررسی پایان بازی — خروجی: برنده یا None
    قانون ۵ ضربه‌ای: اگه اختلاف از ضربات باقی‌مونده بیشتر شد، زودتر تموم می‌شه.
    بعد از ۵ ضربه مساوی → ضربات طلایی: هر دو زدن، هر کی گل کرد و اون یکی نکرد برنده‌ست."""
    gd = room.game_data
    p1, p2 = room.players[0], room.players[1]
    s1, s2 = gd["shots"].get(p1, []), gd["shots"].get(p2, [])
    g1 = sum(1 for v in s1 if v >= 3)
    g2 = sum(1 for v in s2 if v >= 3)
    n1, n2 = len(s1), len(s2)
    
    if not gd.get("sudden"):
        # فاز عادی: برد زودهنگام ریاضی
        left1, left2 = PENALTY_SHOTS - n1, PENALTY_SHOTS - n2
        if g1 > g2 + left2: return p1
        if g2 > g1 + left1: return p2
        if n1 >= PENALTY_SHOTS and n2 >= PENALTY_SHOTS:
            if g1 > g2: return p1
            if g2 > g1: return p2
            gd["sudden"] = True  # مساوی → ضربات طلایی!
        return None
    
    # ضربات طلایی: هر دور (هر دو یه ضربه) مقایسه
    if n1 == n2 and n1 > PENALTY_SHOTS:
        if g1 > g2: return p1
        if g2 > g1: return p2
    return None

async def penalty_shot_received(room, context, msg, uid, value):
    """⚽ پردازش یک ضربه پنالتی — نوبتی!"""
    gd = room.game_data
    p1, p2 = room.players[0], room.players[1]
    shooter = room.players[gd["turn"]]
    
    if uid != shooter:
        try:
            await msg.reply_text(f"⏳ نوبت تو نیست! الان {uname(shooter)} باید بزنه.")
        except Exception:
            pass
        return
    
    shots = gd["shots"].setdefault(uid, [])
    shots.append(value)
    is_goal = value >= 3
    
    # 🎙️ گزارش این ضربه
    comm = "🎙️ " + random.choice(PENALTY_COMMENTARY_GOAL if is_goal else PENALTY_COMMENTARY_MISS)
    if gd.get("sudden"):
        comm = "🎙️ " + random.choice(PENALTY_COMMENTARY_TENSION) + "\n" + comm
    
    # نوبت بعدی
    gd["turn"] = 1 - gd["turn"]
    
    # کمی صبر تا انیمیشن توپ تلگرام تموم شه
    await asyncio.sleep(3.5)
    if room.finished:
        return
    
    winner = penalty_decided(room)
    if winner:
        loser = p2 if winner == p1 else p1
        s1, s2 = gd["shots"].get(p1, []), gd["shots"].get(p2, [])
        g1 = sum(1 for v in s1 if v >= 3)
        g2 = sum(1 for v in s2 if v >= 3)
        add_coins(winner, room.pot(), league=False)
        record_win(winner)
        record_loss(loser, room.bet)
        sudden_txt = " (در ضربات طلایی! 💛)" if gd.get("sudden") else ""
        await finish_game(room, context,
            f"⚽ **پنالتی — پایان بازی!**\n━━━━━━━━━━━━━━\n"
            f"{comm}\n\n"
            f"📊 نتیجه نهایی:\n"
            f"⚽ {uname(p1)}: **{g1}** گل\n"
            f"⚽ {uname(p2)}: **{g2}** گل\n\n"
            f"🎙️ تمووووم شد! **{uname(winner)}** قهرمان سری پنالتی شد{sudden_txt}!\n"
            f"💰 جایزه: {room.pot()} {CURRENCY_NAME}")
        return
    
    # ادامه بازی — اگه الان وارد ضربات طلایی شدیم اعلام کن
    if gd.get("sudden") and not gd.get("sudden_announced"):
        gd["sudden_announced"] = True
        comm += "\n\n🎙️ **باورم نمی‌شه! مساوی شد! می‌ریم ضربات طلایی — هر کی خطا کنه باخته!** 😱"
    
    # 🎙️ گزارش با پیام ریپلای + اعلام نوبت بعدی
    nxt = room.players[gd["turn"]]
    comm = f"⚽ {uname(uid)}: {'✅ گــل!' if is_goal else '❌ از دست رفت!'}\n{comm}\n\n👉 نوبت: **{uname(nxt)}**"
    await send_commentary(room, context, comm)
    await edit_room_msg(room, context, penalty_status_text(room))
    
    # 🤖 نوبت خر باته؟
    await penalty_bot_turn(room, context)

async def penalty_bot_turn(room, context):
    """🤖 خر بات ضربه‌ش رو می‌زنه — با ایموجی ⚽ واقعی!"""
    gd = room.game_data
    while not room.finished and room.players[gd["turn"]] == BOT_ID:
        await asyncio.sleep(2)
        if room.finished or ACTIVE_ROOMS.get(room.room_id) is not room:
            return
        value = await bot_send_real_dice(room, context)
        await asyncio.sleep(3.5)  # صبر تا انیمیشن توپ تموم شه
        if room.finished or ACTIVE_ROOMS.get(room.room_id) is not room:
            return
        p1, p2 = room.players[0], room.players[1]
        shots = gd["shots"].setdefault(BOT_ID, [])
        shots.append(value)
        is_goal = value >= 3
        comm = "🤖 خر بات پشت توپ ایستاد...\n🎙️ " + random.choice(
            PENALTY_COMMENTARY_GOAL if is_goal else PENALTY_COMMENTARY_MISS)
        gd["turn"] = 1 - gd["turn"]
        
        winner = penalty_decided(room)
        if winner:
            loser = p2 if winner == p1 else p1
            s1, s2 = gd["shots"].get(p1, []), gd["shots"].get(p2, [])
            g1 = sum(1 for v in s1 if v >= 3)
            g2 = sum(1 for v in s2 if v >= 3)
            add_coins(winner, room.pot(), league=False)
            record_win(winner)
            record_loss(loser, room.bet)
            sudden_txt = " (در ضربات طلایی! 💛)" if gd.get("sudden") else ""
            await finish_game(room, context,
                f"⚽ **پنالتی — پایان بازی!**\n━━━━━━━━━━━━━━\n"
                f"{comm}\n\n"
                f"📊 نتیجه نهایی:\n"
                f"⚽ {uname(p1)}: **{g1}** گل\n"
                f"⚽ {uname(p2)}: **{g2}** گل\n\n"
                f"🎙️ **{uname(winner)}** قهرمان شد{sudden_txt}!\n"
                f"💰 جایزه: {room.pot()} {CURRENCY_NAME}")
            return
        
        if gd.get("sudden") and not gd.get("sudden_announced"):
            gd["sudden_announced"] = True
            comm += "\n\n🎙️ **مساوی! ضربات طلایی شروع شد!** 😱"
        nxt = room.players[gd["turn"]]
        comm = f"{comm}\n\n👉 نوبت: **{uname(nxt)}**"
        await send_commentary(room, context, comm)
        await edit_room_msg(room, context, penalty_status_text(room))

THROW_ROUNDS = 5  # 🎲🎯🎳 هر بازیکن ۵ پرتاب — نوبتی، مجموع بالاتر می‌بره

# 🎙️ گزارشگر پرتاب‌ها
THROW_COMM_HIGH = {
    "dice":    ["🔥 شیییش!! تاس آتیش گرفت!", "💃 چه پرتابی! تاس رقصید و شیش نشست!",
                "✨ تاس طلایی! انگار جادوش کرده!", "🎉 غوغا کرد! طویله رو هوا رفت!"],
    "darts":   ["🎯 وسط خااال!! چشم‌بسته هم می‌زد انگار!", "🤯 بولزآی!! تماشاگرا از جا پریدن!",
                "✨ دقت لیزری! این دیگه انسان نیست!", "😱 چسبید به مرکز! حریف رنگش پرید!"],
    "bowling": ["💥 اسسسترایک!!! همه پین‌ها خوابیدن!", "🔥 چه غرشی! سالن منفجر شد!",
                "🎳 توپ مثل توپ جنگی رفت! هیچی نموند!", "✨ پین‌ها فرار کردن! استرایک تمیز!"],
    "basketball": ["🔥 سه امتیازی خفن!! توپ صاف رفت تو سبد!", "🤩 سوووئیش! حتی حلقه تکون نخورد!",
                   "💪 اسلم‌دانک خرکی!! حلقه ناله کرد!", "🎉 چه پرتابی! تماشاگرا وحشی شدن!"],
}
THROW_COMM_MID = {
    "dice":    ["🤏 پرتاب متوسط... می‌شد بهتر باشه!", "😏 بد نبود، ولی حریف نیشش باز شد!",
                "😐 نه خوب نه بد — تاسِ محافظه‌کار!"],
    "darts":   ["👌 نزدیک خال نشست... قابل قبوله!", "😌 به تخته چسبید، نه عالی نه فاجعه!",
                "🤏 دستش لرزید ولی آبروش نرفت!"],
    "bowling": ["🤔 چند تا پین افتاد... نصفه‌کاره!", "😐 ضربه معمولی... جای پیشرفت داره!",
                "🙃 نصف پین‌ها موندن سرجاشون!"],
    "basketball": ["😬 توپ رو حلقه چرخید و چرخید... نیفتاد!", "🤏 نزدیک بود! به تخته خورد و برگشت!",
                   "😐 پرتاب معمولی... حلقه قبولش نکرد!"],
}
THROW_COMM_LOW = {
    "dice":    ["😩 آخ آخ! تاس بهش پشت کرد!", "💀 یک؟! این دیگه بدشانسی محضه!",
                "😤 تاس قهر کرد باهاش!", "🙈 این پرتاب رو باید از تاریخ پاک کرد!"],
    "darts":   ["🙈 پرت شد بغل تخته! کجا رو نشونه گرفتی؟!", "😵 افتضاح! دارت رفت تو دیوار!",
                "🏃💨 نزدیک بود بزنه به تماشاگرا!", "💀 دستش لرزید... فاجعه بار اومد!"],
    "bowling": ["😭 رفت تو کانال!! توپ آب خورد!", "💨 عجب ضربه‌ای... به هیچی نخورد!",
                "🙄 توپ راهشو کج کرد و رفت!", "😂 پین‌ها حتی نترسیدن!"],
    "basketball": ["🙈 ایربال!! توپ حتی به حلقه نخورد!", "😵 کجا انداختی؟! توپ رفت تو تماشاگرا!",
                   "💀 پرتاب فاجعه! کره‌خرا هم خندیدن!", "😂 توپ به داور خورد! چه افتضاحی!"],
}

def throw_commentary(gt, value):
    if gt == "basketball":
        # 🏀 ۴-۵ = سبد | ۳ = لب حلقه | ۱-۲ = افتضاح
        if value >= 4: pool = THROW_COMM_HIGH[gt]
        elif value == 3: pool = THROW_COMM_MID[gt]
        else: pool = THROW_COMM_LOW[gt]
        return random.choice(pool)
    if value >= 5: pool = THROW_COMM_HIGH[gt]
    elif value >= 3: pool = THROW_COMM_MID[gt]
    else: pool = THROW_COMM_LOW[gt]
    return random.choice(pool)

def throw_point(gt, value):
    """🏀 بسکتبال: ۴-۵ = ۱ سبد، بقیه صفر — بقیه بازی‌ها: خود عدد"""
    if gt == "basketball":
        return 1 if value >= 4 else 0
    return value

def throw_total(gt, vals):
    return sum(throw_point(gt, v) for v in vals)

def throw_max_per(gt):
    """حداکثر امتیاز یک پرتاب (برای محاسبه برد زودهنگام)"""
    return 1 if gt == "basketball" else 6

def _throw_vals_str(gt, vals, pad=0):
    """رشته پرتاب‌های یه بازیکن"""
    if gt == "basketball":
        s = " ".join("🏀" if v >= 4 else "❌" for v in vals)
    else:
        s = "∙".join(str(v) for v in vals)
    if pad and len(vals) < pad:
        s = (s + " " if s else "") + "▫️" * (pad - len(vals))
    return s or "—"

def _power_bar(score, max_score):
    """▰ نوار قدرت نسبتی (۱۲ خونه)"""
    if max_score <= 0: return ""
    n = max(1, round(score / max_score * 12)) if score > 0 else 0
    return "▰" * n

def throw_live_analysis(gt, gd):
    """🎙️ تحلیل زنده تابلو — هر بار یه جمله باحال"""
    order = gd["order"]
    totals = {p: throw_total(gt, gd["scores"].get(p, [])) for p in order}
    ranked = sorted(order, key=lambda p: -totals[p])
    if len(ranked) < 2: return ""
    top, second = ranked[0], ranked[1]
    diff = totals[top] - totals[second]
    thrown = sum(len(gd["scores"].get(p, [])) for p in order)
    if thrown == 0:
        return "🏁 مسابقه تازه شروع شده — همه‌چیز ممکنه!"
    if diff == 0:
        return random.choice(["🥶 مساویه! هر پرتاب می‌تونه سرنوشت‌ساز باشه!",
                              "😱 سر به سر! طویله منفجر شد از هیجان!"])
    if diff == 1:
        return "😱 اختلاف فقط ۱! نفس‌گیر شد!"
    unit = "سبد" if gt == "basketball" else "امتیاز"
    if diff >= 8:
        return f"🔥 {uname(top)} داره له می‌کنه! {diff} {unit} جلوئه!"
    mx = throw_max_per(gt)
    left_second = (THROW_ROUNDS - len(gd["scores"].get(second, []))) * mx
    if left_second >= diff and diff >= 3:
        return f"🔥 {uname(second)} هنوز می‌تونه برگرده تو بازی!"
    return f"⚡ {uname(top)} {diff} {unit} جلوئه!"

def throw_status_text(room):
    """🎲🎯🎳🏀 تابلوی ترکیبی: ۲ نفره = دوئل ⚔️ | ۳+ = لیدربورد 🏁"""
    gd = room.game_data
    gt = room.game_type
    emo = EMOJI_OF_GAME[gt]
    shooter = gd["order"][gd["turn"] % len(gd["order"])]
    order = gd["order"]
    
    if gd.get("sudden"):
        # 💛 راند طلایی
        lines = [f"{emo} **{GAME_NAMES[gt]}**", "_💛 راند طلایی — مرگ ناگهانی!_", "━━━━━━━━━━━━━━",
                 f"💰 جایزه: **{room.pot():,}** {CURRENCY_NAME}", ""]
        for p in order:
            sd = gd["sd_scores"].get(p, [])
            mark = "👉" if p == shooter else "　"
            lines.append(f"{mark} {uname(p)}: امتیاز {throw_total(gt, gd['scores'].get(p, []))} | طلایی: {_throw_vals_str(gt, sd)}")
        lines += ["", f"🎯 نوبت: **{uname(shooter)}**", f"💡 کپی کن بفرست: {emo}"]
        return "\n".join(lines)
    
    totals = {p: throw_total(gt, gd["scores"].get(p, [])) for p in order}
    unit = "سبد" if gt == "basketball" else ""
    
    if len(order) == 2:
        # ⚔️ حالت دوئل
        p1, p2 = order[0], order[1]
        t1, t2 = totals[p1], totals[p2]
        mx = max(t1, t2, 1)
        lines = [
            f"        ⚔️ {emo} **دوئل {GAME_NAMES[gt].split(' ', 1)[-1]}** ⚔️",
            "━━━━━━━━━━━━━━",
            f"💰 {room.pot():,} {CURRENCY_NAME}",
            "",
            f"{'👉' if shooter == p1 else '　'} **{uname(p1)}** — **{t1}** {unit}",
            f"　 {_throw_vals_str(gt, gd['scores'].get(p1, []), pad=THROW_ROUNDS)}",
            f"　 {_power_bar(t1, mx)}",
            "",
            f"{'👉' if shooter == p2 else '　'} **{uname(p2)}** — **{t2}** {unit}",
            f"　 {_throw_vals_str(gt, gd['scores'].get(p2, []), pad=THROW_ROUNDS)}",
            f"　 {_power_bar(t2, mx)}",
            "━━━━━━━━━━━━━━",
            throw_live_analysis(gt, gd),
            f"🎯 نوبت: **{uname(shooter)}**",
            f"💡 کپی کن بفرست: {emo}",
        ]
        return "\n".join(lines)
    
    # 🏁 لیدربورد چندنفره + 🔺🔻 تغییر جایگاه
    prev_rank = gd.get("prev_rank", {})
    ranked = sorted(order, key=lambda p: -totals[p])
    cur_rank = {p: i for i, p in enumerate(ranked)}
    lines = [f"{emo} **{GAME_NAMES[gt]}** • 💰 {room.pot():,}",
             f"_🏁 {THROW_ROUNDS} پرتاب نوبتی_", "━━━━━━━━━━━━━━"]
    for i, p in enumerate(ranked):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
        if p in prev_rank:
            move = "🔺" if cur_rank[p] < prev_rank[p] else ("🔻" if cur_rank[p] > prev_rank[p] else "➖")
        else:
            move = "➖"
        arrow = "👉" if p == shooter else "　"
        lines.append(f"{arrow}{medal} {uname(p)} ─── **{totals[p]}** {move}")
        vals = _throw_vals_str(gt, gd["scores"].get(p, []))
        if vals != "—":
            lines.append(f"　　 {vals}")
    gd["prev_rank"] = cur_rank
    lines += ["━━━━━━━━━━━━━━",
              throw_live_analysis(gt, gd),
              f"🎯 حالا: **{uname(shooter)}**",
              f"💡 کپی کن بفرست: {emo}"]
    return "\n".join(lines)

def throw_decided(room):
    """بررسی پایان — خروجی: برنده یا None. برد زودهنگام: وقتی بقیه ریاضیاً نمی‌رسن."""
    gd = room.game_data
    gt = room.game_type
    players = gd["order"]
    totals = {p: throw_total(gt, gd["scores"].get(p, [])) for p in players}
    mx = throw_max_per(gt)
    
    if not gd.get("sudden"):
        # برد زودهنگام: امتیاز فعلی یه نفر > حداکثر ممکن همه بقیه
        for L in players:
            others_max = max(
                totals[p] + (THROW_ROUNDS - len(gd["scores"].get(p, []))) * mx
                for p in players if p != L
            )
            if totals[L] > others_max:
                return L
        # همه پرتاب‌ها تموم؟
        if all(len(gd["scores"].get(p, [])) >= THROW_ROUNDS for p in players):
            best = max(totals.values())
            leaders = [p for p in players if totals[p] == best]
            if len(leaders) == 1:
                return leaders[0]
            # مساوی → راند طلایی بین صدرنشین‌ها
            gd["sudden"] = True
            gd["order"] = leaders
            gd["turn"] = 0
            gd["sd_scores"] = {}
        return None
    
    # راند طلایی: وقتی همه یه پرتاب کردن مقایسه کن
    sd = gd["sd_scores"]
    counts = [len(sd.get(p, [])) for p in players]
    if min(counts) == max(counts) and min(counts) > 0:
        last = {p: throw_point(gt, sd[p][-1]) for p in players}
        best = max(last.values())
        leaders = [p for p in players if last[p] == best]
        if len(leaders) == 1:
            return leaders[0]
        # بازم مساوی → فقط صدرنشین‌ها ادامه می‌دن
        gd["order"] = leaders
        gd["turn"] = 0
    return None

async def throw_game_end(room, context, winner, note=""):
    gd = room.game_data
    gt = room.game_type
    emo = EMOJI_OF_GAME[gt]
    all_players = room.players
    unit = "سبد" if gt == "basketball" else "مجموع"
    lines = []
    for p in sorted(all_players, key=lambda x: -throw_total(gt, gd["scores"].get(x, []))):
        mark = "🏆" if p == winner else "▫️"
        lines.append(f"{mark} {uname(p)}: {unit} **{throw_total(gt, gd['scores'].get(p, []))}**")
    add_coins(winner, room.pot(), league=False)
    record_win(winner)
    for p in all_players:
        if p != winner:
            record_loss(p, room.bet)
    sudden_txt = " (در راند طلایی! 💛)" if gd.get("sudden") else ""
    await finish_game(room, context,
        f"{emo} **پایان مسابقه {GAME_NAMES[room.game_type]}**\n━━━━━━━━━━━━━━\n" +
        "\n".join(lines) +
        f"\n\n🎙️ سووووت پایان! **{uname(winner)}** قهرمان شد{sudden_txt}!{note}\n"
        f"💰🏆 جایزه: **{room.pot():,}** {CURRENCY_NAME}")

async def throw_received(room, context, uid, value, is_bot=False, is_timeout=False):
    """پردازش یک پرتاب نوبتی (تاس/دارت/بولینگ)"""
    gd = room.game_data
    gt = room.game_type
    room.last_action = time.time()
    
    # ثبت پرتاب
    if gd.get("sudden"):
        gd["sd_scores"].setdefault(uid, []).append(value)
    else:
        gd["scores"].setdefault(uid, []).append(value)
    gd["turn"] = (gd["turn"] + 1) % len(gd["order"])
    
    # کمی صبر تا انیمیشن ایموجی تلگرام تموم شه (تایم‌اوت انیمیشن نداره)
    if not is_timeout:
        await asyncio.sleep(3.5)
    if room.finished or ACTIVE_ROOMS.get(room.room_id) is not room:
        return
    
    was_sudden = gd.get("sudden", False)
    winner = throw_decided(room)
    
    # 🎙️ گزارش این پرتاب (ریپلای روی پیام اصلی)
    who = "🤖 خر بات" if is_bot else uname(uid)
    if is_timeout:
        comm = f"💤 {who} خواب موند — پرتاب سوخت: **۰**"
    elif gt == "basketball":
        basket = "🏀 سبد شد!" if value >= 4 else "❌ نرفت تو!"
        comm = f"🎯 {who} پرتاب کرد: {basket}\n🎙️ {throw_commentary(gt, value)}"
    else:
        comm = f"🎯 {who} انداخت: **{value}**\n🎙️ {throw_commentary(gt, value)}"
    
    if winner:
        await send_commentary(room, context, comm)
        await throw_game_end(room, context, winner)
        return
    
    if gd.get("sudden") and not was_sudden:
        comm += "\n\n🎙️ **مساوی شد! می‌ریم راند طلایی — هر پرتاب می‌تونه آخرین باشه!** 😱"
    
    nxt = gd["order"][gd["turn"] % len(gd["order"])]
    comm += f"\n\n👉 نوبت: **{uname(nxt)}**"
    await send_commentary(room, context, comm)
    await edit_room_msg(room, context, throw_status_text(room))
    await throw_bot_turn(room, context)

async def bot_send_real_dice(room, context):
    """🤖🎲 خر بات ایموجی انیمیشنی واقعی تلگرام می‌فرسته — نتیجه از خود انیمیشن!
    خروجی: مقدار واقعی dice یا None (اگه ارسال شکست خورد، عدد تصادفی جایگزین)"""
    emo = EMOJI_OF_GAME[room.game_type]
    try:
        sent = await context.bot.send_dice(
            chat_id=room.chat_id, emoji=emo,
            reply_to_message_id=room.message_id)
        return sent.dice.value
    except Exception as e:
        logger.warning(f"⚠️ خر بات نتونست ایموجی واقعی بفرسته: {e}")
        # جایگزین اضطراری: عدد تصادفی (بازی گیر نکنه)
        return random.randint(1, 5 if room.game_type in ("penalty", "basketball") else 6)

async def throw_bot_turn(room, context):
    """🤖 نوبت خر بات توی بازی‌های پرتابی — ایموجی واقعی می‌فرسته!"""
    gd = room.game_data
    while (not room.finished and ACTIVE_ROOMS.get(room.room_id) is room
           and gd["order"][gd["turn"] % len(gd["order"])] == BOT_ID):
        await asyncio.sleep(2)
        if room.finished or ACTIVE_ROOMS.get(room.room_id) is not room:
            return
        value = await bot_send_real_dice(room, context)
        if room.finished or ACTIVE_ROOMS.get(room.room_id) is not room:
            return
        await throw_received(room, context, BOT_ID, value, is_bot=True)
        return  # throw_received خودش زنجیره رو ادامه می‌ده

async def emoji_game_begin(room, context):
    """شروع بازی‌های ایموجی — همه نوبتی با گزارشگر!"""
    if room.game_type == "penalty":
        room.game_data = {"shots": {}, "turn": 0, "deadline": time.time() + 300}
        DICE_WAITING[room.chat_id] = room.room_id
        await edit_room_msg(room, context, penalty_status_text(room))
        await send_commentary(room, context,
            "🎙️🐴 سری پنالتی شروع شد! ۵ ضربه برای هر تیم — بریم ببینیم کی خونسردتره!\n"
            f"👉 اولین ضربه: **{uname(room.players[0])}**")
        context.application.create_task(emoji_game_deadline_watch(room, context))
        await penalty_bot_turn(room, context)
        return
    
    # 🎲🎯🎳🏀 نوبتی ۵ راندی
    room.game_data = {"scores": {}, "order": room.players[:], "turn": 0, "deadline": time.time() + 300}
    DICE_WAITING[room.chat_id] = room.room_id
    emo = EMOJI_OF_GAME[room.game_type]
    goal = "سبد بیشتر می‌بره" if room.game_type == "basketball" else "مجموع بالاتر می‌بره"
    await edit_room_msg(room, context, throw_status_text(room))
    await send_commentary(room, context,
        f"🎙️ مسابقه {GAME_NAMES[room.game_type]} شروع شد! {THROW_ROUNDS} پرتاب نوبتی — {goal}!\n"
        f"👉 اولین پرتاب: **{uname(room.players[0])}**")
    context.application.create_task(emoji_game_deadline_watch(room, context))
    await throw_bot_turn(room, context)

TURN_TIMEOUT_FIRST = 60    # ⏰ بار اول نیومد: ۱ دقیقه → امتیاز صفر
TURN_TIMEOUT_REPEAT = 30   # ⏰ دوباره نیومد: ۳۰ ثانیه → حذف از بازی!

async def emoji_game_deadline_watch(room, context):
    """⏱️ ناظر نوبت: دیر بیای اول صفر می‌گیری، تکرار شه حذف می‌شی!"""
    try:
        while ACTIVE_ROOMS.get(room.room_id) is room and not room.finished:
            gd = room.game_data
            # نوبت فعلی کیه؟ (پنالتی: players — پرتابی: order)
            if room.game_type == "penalty":
                cur = room.players[gd["turn"]]
            else:
                cur = gd["order"][gd["turn"] % len(gd["order"])]
            
            slow = cur in gd.setdefault("slowpokes", set())
            limit = TURN_TIMEOUT_REPEAT if slow else TURN_TIMEOUT_FIRST
            
            mark = room.last_action
            await asyncio.sleep(limit)
            if ACTIVE_ROOMS.get(room.room_id) is not room or room.finished:
                return
            if room.last_action != mark:
                continue  # حرکتی شده، از اول بپا
            
            gd = room.game_data
            # هنوز نوبت همون نفره؟
            if room.game_type == "penalty":
                still = room.players[gd["turn"]] == cur
            else:
                still = gd["order"][gd["turn"] % len(gd["order"])] == cur
            if not still or cur == BOT_ID:
                continue
            
            if not slow:
                # ⏰ بار اول: امتیاز صفر + اخطار
                gd["slowpokes"].add(cur)
                room.last_action = time.time()
                await send_commentary(room, context,
                    f"⏰ وقت {uname(cur)} تموم شد! 🎙️ داور اعلام کرد: **پرتاب سوخت — صفر!**\n"
                    f"⚠️ دفعه بعد فقط {TURN_TIMEOUT_REPEAT} ثانیه وقت داری وگرنه حذفی!")
                if room.game_type == "penalty":
                    await penalty_forfeit_shot(room, context, cur)
                else:
                    await throw_received(room, context, cur, 0, is_timeout=True)
            else:
                # ☠️ تکرار: حذف از بازی
                await send_commentary(room, context,
                    f"☠️ {uname(cur)} دوباره غیبش زد! 🎙️ داور از بازی **حذفش کرد!**")
                await eliminate_player(room, context, cur)
    except Exception as e:
        logger.warning(f"⚠️ خطا در ناظر نوبت: {e}")

async def eliminate_player(room, context, uid):
    """☠️ حذف بازیکن غایب — ۲ نفره: حریف می‌بره | چندنفره: بقیه ادامه می‌دن"""
    gd = room.game_data
    room.last_action = time.time()
    
    if room.game_type == "penalty" or len([p for p in gd.get("order", room.players) if p != uid]) < 2:
        # ۲ نفره (یا فقط یه نفر می‌مونه) → بازمانده برنده‌ست
        if room.game_type == "penalty":
            others = [p for p in room.players if p != uid]
        else:
            others = [p for p in gd["order"] if p != uid]
        winner = others[0]
        add_coins(winner, room.pot(), league=False)
        record_win(winner)
        record_loss(uid, room.bet)
        emo = EMOJI_OF_GAME[room.game_type]
        await finish_game(room, context,
            f"{emo} **{GAME_NAMES[room.game_type]} — پایان!**\n━━━━━━━━━━━━━━\n"
            f"🎙️ {uname(uid)} به خاطر غیبت حذف شد!\n\n"
            f"🏆 برنده: **{uname(winner)}**\n💰 جایزه: {room.pot()} {CURRENCY_NAME}")
        return
    
    # چندنفره: از چرخه خارج شه، بقیه ادامه بدن
    idx = gd["order"].index(uid)
    gd["order"].remove(uid)
    record_loss(uid, room.bet)
    if gd["turn"] >= len(gd["order"]):
        gd["turn"] = 0
    elif idx < gd["turn"]:
        gd["turn"] -= 1
    gd["turn"] %= len(gd["order"])
    PLAYER_IN_GAME.pop(uid, None)
    
    nxt = gd["order"][gd["turn"]]
    await send_commentary(room, context, f"👥 بازی با {len(gd['order'])} نفر ادامه پیدا می‌کنه!\n👉 نوبت: **{uname(nxt)}**")
    await edit_room_msg(room, context, throw_status_text(room))
    await throw_bot_turn(room, context)

async def penalty_forfeit_shot(room, context, uid):
    """⚽ ضربه سوخته پنالتی (تایم‌اوت بار اول) = خطا"""
    gd = room.game_data
    gd["shots"].setdefault(uid, []).append(0)  # 0 = خطا
    gd["turn"] = 1 - gd["turn"]
    
    winner = penalty_decided(room)
    if winner:
        p1, p2 = room.players[0], room.players[1]
        loser = p2 if winner == p1 else p1
        g1 = sum(1 for v in gd["shots"].get(p1, []) if v >= 3)
        g2 = sum(1 for v in gd["shots"].get(p2, []) if v >= 3)
        add_coins(winner, room.pot(), league=False)
        record_win(winner)
        record_loss(loser, room.bet)
        await finish_game(room, context,
            f"⚽ **پنالتی — پایان!**\n━━━━━━━━━━━━━━\n"
            f"📊 {uname(p1)}: {g1} گل | {uname(p2)}: {g2} گل\n"
            f"🏆 برنده: **{uname(winner)}**\n💰 جایزه: {room.pot()} {CURRENCY_NAME}")
        return
    if gd.get("sudden") and not gd.get("sudden_announced"):
        gd["sudden_announced"] = True
    nxt = room.players[gd["turn"]]
    await send_commentary(room, context, f"👉 نوبت: **{uname(nxt)}**")
    await edit_room_msg(room, context, penalty_status_text(room))
    await penalty_bot_turn(room, context)

async def emoji_game_finish(room, context):
    """⏰ فقط برای تایم‌اوت — هر کی سر نوبتش نیومد بازنده‌ست"""
    gd = room.game_data
    if DICE_WAITING.get(room.chat_id) == room.room_id:
        DICE_WAITING.pop(room.chat_id, None)
    emo = EMOJI_OF_GAME[room.game_type]
    
    if room.game_type == "penalty":
        p1, p2 = room.players[0], room.players[1]
        slacker = room.players[gd.get("turn", 0)]
        winner = p2 if slacker == p1 else p1
        g1 = sum(1 for v in gd["shots"].get(p1, []) if v >= 3)
        g2 = sum(1 for v in gd["shots"].get(p2, []) if v >= 3)
        add_coins(winner, room.pot(), league=False)
        record_win(winner)
        record_loss(slacker, room.bet)
        await finish_game(room, context,
            f"⚽ **پنالتی — پایان با تایم‌اوت!**\n━━━━━━━━━━━━━━\n"
            f"🎙️😴 {uname(slacker)} سر نوبتش نیومد پشت توپ! داور سوت پایان رو زد!\n\n"
            f"📊 {uname(p1)}: {g1} گل | {uname(p2)}: {g2} گل\n"
            f"🏆 برنده: **{uname(winner)}**\n💰 جایزه: {room.pot()} {CURRENCY_NAME}")
        return
    
    # بازی‌های پرتابی
    total_throws = sum(len(v) for v in gd.get("scores", {}).values())
    if total_throws == 0:
        for p in room.players:
            add_coins(p, room.bet, league=False)
        await finish_game(room, context,
            f"{emo} **{GAME_NAMES[room.game_type]} — لغو شد!**\n━━━━━━━━━━━━━━\n"
            "😴 هیچ‌کس بازی نکرد! شرط همه برگشت داده شد.")
        return
    
    slacker = gd["order"][gd["turn"] % len(gd["order"])]
    remaining = [p for p in room.players if p != slacker]
    totals = {p: throw_total(room.game_type, gd["scores"].get(p, [])) for p in remaining}
    best = max(totals.values()) if totals else 0
    winners = [p for p in remaining if totals[p] == best] or remaining[:1]
    
    share = room.pot() // len(winners)
    for w in winners:
        add_coins(w, share, league=False)
        record_win(w)
    for p in room.players:
        if p not in winners:
            record_loss(p, room.bet)
    
    win_names = "، ".join(uname(w) for w in winners)
    await finish_game(room, context,
        f"{emo} **{GAME_NAMES[room.game_type]} — پایان با تایم‌اوت!**\n━━━━━━━━━━━━━━\n"
        f"🎙️😴 {uname(slacker)} سر نوبتش نیومد! داور حذفش کرد!\n\n"
        f"🏆 برنده: **{win_names}**\n💰 جایزه هر نفر: {share} {CURRENCY_NAME}")

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
        # ⚽ نوبتی با گزارشگر
        await penalty_shot_received(room, context, msg, uid, msg.dice.value)
        return
    
    # 🎲🎯🎳 نوبتی: فقط کسی که نوبتشه
    shooter = gd["order"][gd["turn"] % len(gd["order"])]
    if uid != shooter:
        if uid in gd["order"]:
            try:
                await msg.reply_text(f"⏳ نوبت تو نیست! الان {uname(shooter)} باید بندازه.")
            except Exception:
                pass
        return
    await throw_received(room, context, uid, msg.dice.value)

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
        add_coins(uid, room.pot(), league=False)
        record_win(uid)
        for p in room.players:
            if p != uid:
                record_loss(p, room.bet)
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
# 💣 مین‌روب (۲ تا ۵ نفره) — ۲نفره ۹ جعبه | ۳-۵ نفره ۱۶ جعبه
# ------------------------------------------------------------

MINES_BOXES = 9        # ۲ نفره: ۹ جعبه (۳×۳)
MINES_BOXES_BIG = 16   # ۳ تا ۵ نفره: ۱۶ جعبه (۴×۴)

def mines_box_count(room):
    """💣 تعداد جعبه بر اساس تعداد بازیکنان: ۲ نفر = ۹ | ۳-۵ نفر = ۱۶"""
    return MINES_BOXES_BIG if len(room.players) >= 3 else MINES_BOXES

def mines_keyboard(room):
    gd = room.game_data
    total = gd.get("boxes", MINES_BOXES)
    per_row = 4 if total == MINES_BOXES_BIG else 3
    rows = []
    for i in range(0, total, per_row):
        row = []
        for j in range(i, min(i + per_row, total)):
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
        f"👉😰 نوبت: **{uname(current)}** — یه جعبه باز کن..."
    )

def mines_new_round(room):
    gd = room.game_data
    gd["bomb"] = random.randint(0, gd["boxes"] - 1)
    gd["opened"] = set()

async def mines_begin(room, context):
    alive = room.players[:]
    random.shuffle(alive)
    room.game_data = {"alive": alive, "turn": 0, "round": 1, "boxes": mines_box_count(room)}
    mines_new_round(room)
    await edit_room_msg(room, context, mines_status(room), mines_keyboard(room))
    await mines_bot_turn(room, context)

async def mines_bot_turn(room, context):
    gd = room.game_data
    while not room.finished and gd["alive"][gd["turn"] % len(gd["alive"])] == BOT_ID:
        await asyncio.sleep(1.5)
        if room.finished: return
        choices = [i for i in range(gd["boxes"]) if i not in gd["opened"]]
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
            add_coins(winner, room.pot(), league=False)
            record_win(winner)
            for p in room.players:
                if p != winner:
                    record_loss(p, room.bet)
            await finish_game(room, context,
                f"💣 **مین‌روب — پایان!**\n━━━━━━━━━━━━━━\n"
                f"💥☠️ **بوووم!** {uname(uid)} جعبه {box+1} رو باز کرد و منفجر شد!\n\n"
                f"🏆 آخرین بازمانده: **{uname(winner)}**\n"
                f"💰 جایزه: {room.pot()} {CURRENCY_NAME}")
            return True
        # راند جدید
        gd["round"] += 1
        gd["turn"] = gd["turn"] % len(gd["alive"])
        mines_new_round(room)
        extra = f"💥 **بوووم!** {uname(uid)} منفجر شد و حذف شد! ☠️\n🔄 بمب جدید کار گذاشته شد...\n"
        await edit_room_msg(room, context, mines_status(room, extra))
        # 🎙️ گزارش انفجار + جعبه‌های جدید زیر همین پیام!
        nxt = gd["alive"][gd["turn"] % len(gd["alive"])]
        kb = mines_keyboard(room) if nxt != BOT_ID else None
        await send_commentary(room, context,
            f"💥☠️ **بوووم!** {uname(uid)} پرید رو هوا!\n"
            f"❤️ {len(gd['alive'])} نفر موندن — بمب جدید کار گذاشته شد!\n\n"
            f"👉 نوبت: **{uname(nxt)}** — یه جعبه انتخاب کن! 😰", kb)
        await mines_bot_turn(room, context)
        return False
    
    # 📦 جعبه خالی
    gd["opened"].add(box)
    gd["turn"] += 1
    # اگه فقط جعبه بمب مونده → راند جدید (همه نجات پیدا کردن این راند)
    if len(gd["opened"]) >= gd["boxes"] - 1:
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
        f"😰 هفت‌تیر دستشه... به کی شلیک می‌کنه؟"
    )

# 🎙️ گزارشگر رولت روسی
RR_COMM_AIM = [
    "🎙️😱 هفت‌تیر بالا اومد! طویله ساکت شد... همه نفسشون رو حبس کردن!",
    "🎙️🥶 نگاهش رو قفل کرد... انگشتش رفت رو ماشه! این دیوونه شلیک می‌کنه!",
    "🎙️🫣 تماشاگرا چشماشون رو گرفتن! این لحظه رو نمی‌شه تماشا کرد!",
    "🎙️⚰️ قبرکن طویله هم بیل‌ش رو آماده کرد... اوضاع جدیه!",
]
RR_COMM_HIT = [
    "🎙️💥 بنگ!! پخش زمین شد! چه شلیک بی‌رحمانه‌ای!",
    "🎙️☠️ گلوله کار خودش رو کرد! یکی دیگه از دور خارج شد!",
    "🎙️😵 مستقیم خورد! حتی فرصت خداحافظی نداشت!",
    "🎙️🪦 تمومه! ببرینش... طویله یه خر کمتر شد!",
]
RR_COMM_MISS = [
    "🎙️😮‍💨 کلیک... خالی بود!! از مرگ برگشت! چه شانسی!",
    "🎙️🍀 پوکه خالی! رنگش پرید ولی زنده‌ست! نفس عمیق!",
    "🎙️🥵 خالی!! عرق سرد رو پیشونیش نشست... ولی جون سالم به در برد!",
    "🎙️😅 چیزی نشد! تماشاگرا دوباره نفس کشیدن... فعلاً!",
]

async def roulette_begin(room, context):
    alive = room.players[:]
    random.shuffle(alive)
    room.game_data = {"alive": alive, "turn": 0, "round": 1}
    await edit_room_msg(room, context, roulette_status(room))
    kb = roulette_keyboard(room) if alive[0] != BOT_ID else None
    await send_commentary(room, context,
        f"🎙️🔫 بازی مرگبار رولت روسی شروع شد! {len(alive)} خر جسور دور میز نشستن...\n"
        f"👉 اولین شلیک: **{uname(alive[0])}** — به کی شلیک می‌کنی؟", kb)
    await roulette_bot_turn(room, context)

async def roulette_next_round(room, context, extra):
    """پایان راند: یک نفر حذف شد → راند جدید یا پایان بازی"""
    gd = room.game_data
    if len(gd["alive"]) == 1:
        winner = gd["alive"][0]
        add_coins(winner, room.pot(), league=False)
        record_win(winner)
        for p in room.players:
            if p != winner:
                record_loss(p, room.bet)
        await send_commentary(room, context,
            f"🎙️🏆 تمووووم شد! **{uname(winner)}** تنها بازمانده این بازی مرگباره!\n"
            f"💰 کل جایزه {room.pot():,} {CURRENCY_NAME} رو با دستای لرزون برد! چه اعصابی داره این خر!")
        await finish_game(room, context,
            f"🔫 **رولت روسی — پایان**\n━━━━━━━━━━━━━━\n"
            f"{extra}\n"
            f"🏆 آخرین بازمانده: **{uname(winner)}**\n"
            f"💰 جایزه: {room.pot()} {CURRENCY_NAME}")
        return True
    gd["round"] += 1
    gd["turn"] = gd["turn"] % len(gd["alive"])
    await edit_room_msg(room, context, roulette_status(room, extra + "\n"))
    # 🎙️ دکمه‌های انتخاب هدف زیر آخرین گزارش — لازم نیست بره بالا!
    nxt = gd["alive"][gd["turn"]]
    if nxt != BOT_ID:
        await send_commentary(room, context,
            f"👉 نوبت: **{uname(nxt)}** — به کی شلیک می‌کنی؟ 🔫",
            roulette_keyboard(room))
    await roulette_bot_turn(room, context)
    return False

async def roulette_shoot(room, context, shooter, target):
    """شلیک: ۲ از ۶ احتمال گلوله. حذف = پایان راند — با گزارشگر زنده! 🎙️"""
    gd = room.game_data
    room.last_action = time.time()
    who = "🤖 خر بات" if shooter == BOT_ID else uname(shooter)
    # 🎙️ گزارش انتخاب هدف (ریپلای روی پیام اصلی)
    await send_commentary(room, context,
        f"🔫 {who} هفت‌تیر رو گرفت سمت **{uname(target)}**!\n"
        f"{random.choice(RR_COMM_AIM)}\n"
        f"🌀 استوانه می‌چرخه...")
    await edit_room_msg(room, context,
        f"🔫 **رولت روسی — راند {gd['round']}**\n━━━━━━━━━━━━━━\n"
        f"😰 {who} نشونه گرفت سمت {uname(target)}...\n"
        f"🌀 چرخش استوانه...")
    await asyncio.sleep(2)
    if room.finished: return
    
    if random.randint(1, 6) <= 2:  # 💥 گلوله!
        gd["alive"].remove(target)
        # 🎙️ گزارش اصابت
        await send_commentary(room, context,
            f"💥☠️ **بنگ!** {uname(target)} حذف شد!\n{random.choice(RR_COMM_HIT)}\n"
            f"❤️ {len(gd['alive'])} نفر زنده موندن...")
        extra = f"💥☠️ **بنگ!** {who} زد و {uname(target)} حذف شد!\n"
        # راند تمام — نفر بعدی شروع‌کننده راند بعده
        await roulette_next_round(room, context, extra)
    else:
        # کلیک خالی → نوبت به نفر بعدی همین راند
        gd["turn"] = (gd["turn"] + 1) % len(gd["alive"])
        nxt = gd["alive"][gd["turn"]]
        extra = f"😮‍💨 *کلیک...* پوکه خالی بود! {uname(target)} زنده موند!\n"
        await edit_room_msg(room, context, roulette_status(room, extra))
        # 🎙️ گزارش پوکه خالی + دکمه‌های شلیک زیر همین پیام!
        kb = roulette_keyboard(room) if nxt != BOT_ID else None
        await send_commentary(room, context,
            f"😮‍💨 *کلیک...* خالی بود! **{uname(target)}** زنده موند!\n{random.choice(RR_COMM_MISS)}\n\n"
            f"👉 هفت‌تیر رفت دست: **{uname(nxt)}** — به کی شلیک می‌کنی؟ 🔫", kb)
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
    await edit_room_msg(room, context, "🎰🃏 در حال پخش کارت‌ها...")
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
        add_coins(w, share, league=False)
        record_win(w)
    for p in room.players:
        if p not in winners:
            record_loss(p, room.bet)
    
    win_names = "، ".join(uname(w) for w in winners)
    await finish_game(room, context,
        f"🎰 **پوکر — نتیجه**\n━━━━━━━━━━━━━━\n" + "\n".join(lines) +
        f"\n\n🏆 برنده: **{win_names}**\n💰 جایزه هر نفر: {share} {CURRENCY_NAME}")

# ------------------------------------------------------------
# 🃏 بلک‌جک ۲۱ (۲ تا ۶ نفره — نوبتی)
# ------------------------------------------------------------

def bj_keyboard(room):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎴 کارت بده", callback_data=gcb(room.room_id, "bj_hit")),
         InlineKeyboardButton("✋ کافیه", callback_data=gcb(room.room_id, "bj_stand"))],
        [InlineKeyboardButton("👀 کارت‌های من", callback_data=gcb(room.room_id, "bj_peek")),
         InlineKeyboardButton("📖 آموزش", callback_data=gcb(room.room_id, "bj_help"))]
    ])

BJ_HELP_TEXT = (
    "📖 آموزش بلک‌جک ۲۱ — به زبون خری!\n"
    "━━━━━━━━━━━━━━\n"
    "🎯 هدف: مجموع کارتات به ۲۱ نزدیک باشه ولی رد نشه!\n\n"
    "🎴 «کارت بده» = یه کارت دیگه بگیر\n"
    "✋ «کافیه» = وایسا و ریسک نکن\n"
    "💥 از ۲۱ رد شی = سوختی!\n\n"
    "🃏 ارزش کارت‌ها:\n"
    "عددی‌ها = خودشون | J/Q/K = ۱۰\n"
    "آس = ۱۱ یا ۱ (خودکار بهترینش)\n\n"
    "🏆 آخرش هر کی به ۲۱ نزدیک‌تر بود می‌بره!\n"
    "👀 کارتات مخفیه — با «کارت‌های من» ببینشون!"
)

def bj_status_text(room):
    """🔒 کارت‌ها مخفی! فقط وضعیت و تعداد کارت‌ها معلومه"""
    gd = room.game_data
    lines = [f"🃏 **بلک‌جک ۲۱**",
             "_🔒 کارت‌ها مخفیه! با دکمه «👀 کارت‌های من» فقط خودت می‌بینی_",
             "━━━━━━━━━━━━━━",
             f"🎩 خونه: {card_str(gd['dealer'][0])} 🂠", ""]
    for i, p in enumerate(room.players):
        h = gd["hands"][p]
        if i == gd["idx"] and not gd["done"].get(p):
            mark = "👉"
        elif gd["done"].get(p) == "bust":
            mark = "💥"
        elif gd["done"].get(p):
            mark = "✅"
        else:
            mark = "▫️"
        # 🔒 فقط تعداد کارت‌ها — نه خودشون!
        status = " (سوخت!)" if gd["done"].get(p) == "bust" else ""
        lines.append(f"{mark} {uname(p)}: {'🂠 ' * len(h)}({len(h)} کارت){status}")
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
    # 🎙️ اعلام نوبت + دکمه‌ها زیر گزارش (وقتی نوبت عوض شده — نه با هر کارت کشیدن)
    current = room.players[gd["idx"]]
    if gd.get("last_announced") != current:
        gd["last_announced"] = current
        await send_commentary(room, context,
            f"👉 نوبت: **{uname(current)}** — کارت می‌خوای یا بسه? 🃏",
            bj_keyboard(room))

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
            record_loss(p, room.bet)
        elif dv > 21 or v > dv:
            prize = room.bet * 2
            add_coins(p, prize, league=False)
            record_win(p)
            res = f"🏆 برد +{prize}"
        elif v == dv:
            add_coins(p, room.bet, league=False)
            res = "🤝 مساوی (برگشت شرط)"
        else:
            record_loss(p, room.bet)
            res = "💀 باخت"
        lines.append(f"👤 {uname(p)}: {hand_str(h)} = {v} → {res}")
    
    await finish_game(room, context, "\n".join(lines))

async def bj_action(room, context, query, action):
    uid = query.from_user.id
    gd = room.game_data
    
    # 👀 دیدن کارت‌های خود — همیشه آزاد (پاپ‌آپ شخصی، فقط خودش می‌بینه)
    if action == "peek":
        h = gd["hands"].get(uid)
        if not h:
            await query.answer("❌ تو توی این بازی نیستی!", show_alert=True)
            return
        v = bj_value(h)
        state = " — 💥 سوختی!" if gd["done"].get(uid) == "bust" else (" — ✅ ایستادی" if gd["done"].get(uid) else "")
        await query.answer(f"🎴 کارت‌های تو: {hand_str(h)}\n🔢 مجموع: {v}{state}", show_alert=True)
        return
    
    # 📖 آموزش — همیشه آزاد (پاپ‌آپ شخصی)
    if action == "help":
        await query.answer(BJ_HELP_TEXT, show_alert=True)
        return
    
    if gd["idx"] >= len(room.players):
        await query.answer()
        return
    current = room.players[gd["idx"]]
    if uid != current:
        await query.answer("⏳ نوبت تو نیست!", show_alert=True)
        return
    
    if action == "hit":
        gd["hands"][uid].append(gd["deck"].pop())
        h = gd["hands"][uid]
        v = bj_value(h)
        if v > 21:
            gd["done"][uid] = "bust"
            gd["idx"] += 1
            # 🔒 کارت جدید فقط تو پاپ‌آپ شخصی
            await query.answer(f"🎴 کارت جدید: {card_str(h[-1])}\n💥 سوختی! مجموع: {v}", show_alert=True)
            await bj_next_turn(room, context)
        elif v == 21:
            gd["done"][uid] = "stand"
            gd["idx"] += 1
            await query.answer(f"🎴 کارت جدید: {card_str(h[-1])}\n🎉 ۲۱ شد! عالی!", show_alert=True)
            await bj_next_turn(room, context)
        else:
            await query.answer(f"🎴 کارت جدید: {card_str(h[-1])}\n🔢 مجموع: {v}", show_alert=True)
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
            await asyncio.sleep(3)  # ⏱️ ۳ ثانیه — که تلگرام flood نگیره
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
                        record_loss(p, room.bet)
                await finish_game(room, context, "\n".join(lines))
                return
            
            await edit_room_msg(room, context, crash_status_text(room), crash_keyboard(room))
    except Exception as e:
        logger.error(f"❌ خطا در حلقه انفجار: {e}")
        # در صورت خطا، پول بازیکنانی که برداشت نکرده‌اند برگردد
        if ACTIVE_ROOMS.get(room.room_id) is room and not room.finished:
            for p in room.players:
                if p not in gd.get("cashed", {}):
                    add_coins(p, room.bet, league=False)
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
    add_coins(uid, prize, league=False)
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
    await query.answer(f"✅ انتخاب شد: {HILO_NAMES[pick]}")
    
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
    
    # همه انتخاب کردند → 🎲 ربات دو تا تاس واقعی می‌ندازه!
    await edit_room_msg(room, context,
        f"🔼🔽 **حدس بالا/پایین**\n━━━━━━━━━━━━━━\n"
        f"✅ همه انتخاب کردن!\n🎲 ربات داره تاس‌ها رو می‌ندازه...")
    d1 = d2 = None
    try:
        s1 = await context.bot.send_dice(chat_id=room.chat_id, emoji="🎲",
                                         reply_to_message_id=room.message_id)
        d1 = s1.dice.value
        await asyncio.sleep(3.5)
        s2 = await context.bot.send_dice(chat_id=room.chat_id, emoji="🎲",
                                         reply_to_message_id=room.message_id)
        d2 = s2.dice.value
        await asyncio.sleep(3.5)
    except Exception as e:
        logger.warning(f"⚠️ تاس بالا/پایین نرفت: {e}")
        d1 = d1 or random.randint(1, 6)
        d2 = d2 or random.randint(1, 6)
    if room.finished or ACTIVE_ROOMS.get(room.room_id) is not room:
        return
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
            add_coins(p, prize, league=False)
            record_win(p)
            lines.append(f"🏆 {uname(p)}: {HILO_NAMES[pick]} → +{prize} {CURRENCY_NAME}")
        else:
            record_loss(p, room.bet)
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
        elif payload.startswith("cf_"):
            await coinflip_action(room, context, query, payload[3:])
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
# 7.7 🎰 بازی فوری (اسلات + صف ضد اسپم)
# ============================================================

SLOT_SYMBOLS = ["🍒", "🍋", "🍇", "🔔", "💎", "7️⃣"]

# ⏳ صف بازی‌های فوری: اسپم کنی، پیام‌هات دونه‌دونه هر ۲ ثانیه جواب داده می‌شن
INSTANT_GAME_GAP = 2          # فاصله بین هر بازی (ثانیه)
INSTANT_QUEUE_MAX = 5         # حداکثر ۵ تا پیام تو صف هر نفر — بیشترش دور ریخته می‌شه
_INSTANT_NEXT_FREE = {}       # {user_id: زمانی که نوبت بعدی آزاد می‌شه}
_INSTANT_QUEUED = {}          # {user_id: تعداد پیام‌های در صف}

def instant_game_delay(user_id):
    """⏱️ خروجی: چند ثانیه صبر کنه تا نوبتش بشه (۰ = همین الان)
    None یعنی صف پره و این پیام کلاً دور ریخته بشه."""
    now = time.time()
    next_free = _INSTANT_NEXT_FREE.get(user_id, 0)
    if now >= next_free:
        # آزاده — همین الان بازی کن، نوبت بعدی ۲ ثانیه دیگه
        _INSTANT_NEXT_FREE[user_id] = now + INSTANT_GAME_GAP
        # پاکسازی
        if len(_INSTANT_NEXT_FREE) > 3000:
            for k in [k for k, v in _INSTANT_NEXT_FREE.items() if v < now][:1000]:
                _INSTANT_NEXT_FREE.pop(k, None)
                _INSTANT_QUEUED.pop(k, None)
        return 0
    # مشغوله — بره تو صف (اگه جا باشه)
    queued = _INSTANT_QUEUED.get(user_id, 0)
    if queued >= INSTANT_QUEUE_MAX:
        return None  # صف پره، بی‌صدا دور بریز
    _INSTANT_QUEUED[user_id] = queued + 1  # 📬 همین‌جا جاش رزرو می‌شه
    delay = next_free - now
    _INSTANT_NEXT_FREE[user_id] = next_free + INSTANT_GAME_GAP
    return delay

async def _instant_run_later(user_id, delay, coro_fn):
    """اجرای بازی بعد از تاخیر صف"""
    try:
        await asyncio.sleep(delay)
        await coro_fn()
    except Exception as e:
        logger.warning(f"⚠️ خطا در صف بازی فوری: {e}")
    finally:
        _INSTANT_QUEUED[user_id] = max(0, _INSTANT_QUEUED.get(user_id, 0) - 1)

# 🎲 شانس برد بازی‌های فوری: ۳۵٪ برد / ۶۵٪ باخت
INSTANT_WIN_CHANCE = 0.35

# 🎰 نگاشت مقدار اسلات تلگرام (۱ تا ۶۴) به حلقه‌ها
# هر حلقه یکی از ۴ نماد: BAR، انگور 🍇، لیمو 🍋، هفت 7️⃣
_SLOT_TG_SYMBOLS = ["▪️BAR", "🍇", "🍋", "7️⃣"]

def slot_reels_from_value(value):
    """مقدار dice اسلات تلگرام → سه حلقه (خود انیمیشن همینو نشون می‌ده)"""
    v = value - 1
    return [_SLOT_TG_SYMBOLS[v & 3], _SLOT_TG_SYMBOLS[(v >> 2) & 3], _SLOT_TG_SYMBOLS[(v >> 4) & 3]]

async def slot_game(update, context, bet):
    user = update.effective_user
    delay = instant_game_delay(user.id)
    if delay is None:
        return  # صف پره — بی‌صدا دور بریز
    if delay > 0:
        # 📬 تو صف — بعد از نوبتش خودکار اجرا می‌شه
        context.application.create_task(
            _instant_run_later(user.id, delay, lambda: _slot_play(update, context, bet)))
        return
    await _slot_play(update, context, bet)

async def _slot_play(update, context, bet):
    """🎰 اسلات با ایموجی واقعی تلگرام — نتیجه از خود انیمیشن خونده می‌شه!"""
    user = update.effective_user
    if not remove_coins(user.id, bet):
        u = get_user(user.id)
        await update.message.reply_text(f"❌ پول کافی نداری! موجودی: {u['coins']:,} {CURRENCY_NAME}")
        return
    
    # 🎰 ایموجی واقعی — انیمیشن حلقه‌ها جلوی چشم همه می‌چرخه!
    value = None
    try:
        sent = await update.message.reply_dice(emoji="🎰")
        value = sent.dice.value
    except Exception as e:
        logger.warning(f"⚠️ اسلات واقعی نرفت: {e}")
        value = random.randint(1, 64)
    await asyncio.sleep(2.2)  # صبر تا انیمیشن حلقه‌ها بایسته
    
    reels = slot_reels_from_value(value)
    line = " | ".join(reels)
    
    if reels[0] == reels[1] == reels[2]:
        # سه‌تایی!
        if reels[0] == "7️⃣": mult = 20
        elif reels[0] == "🍇": mult = 10
        else: mult = 6
        prize = bet * mult
        add_coins(user.id, prize, league=False)
        record_win(user.id)
        result = f"🎰 **جکپات!** سه‌تایی {reels[0]}\n💰 بردی: **+{prize:,}** {CURRENCY_NAME} (x{mult})"
    elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        prize = bet * 2
        add_coins(user.id, prize, league=False)
        record_win(user.id)
        result = f"✨ دوتایی! 💰 بردی: **+{prize:,}** {CURRENCY_NAME} (x2)"
    else:
        ref = record_loss(user.id, bet)
        result = f"💀 باختی! **-{bet:,}** {CURRENCY_NAME}"
        if ref:
            result += f"\n🛡️ بیمه {ref} {CURRENCY_NAME} برگردوند!"
    
    await update.message.reply_text(
        f"🎰 **اسلات خرستان**\n━━━━━━━━━━━━━━\n"
        f"〘 {line} 〙\n\n"
        f"👤 {esc_md(user.first_name)}\n{result}",
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


# ╔══════════════════════════════════════════════════════════╗
# ║                 فصل 8 👑 بخش مالک (پنل/خر دانا/همگانی)
# ╚══════════════════════════════════════════════════════════╝
# ============================================================
# 8.1 🎁 کادوهای مالک
# ============================================================

OWNER_GIFTS = {
    "گل": {"emoji": "🌹", "coins": 300},
    "شکلات": {"emoji": "🍫", "coins": 750},
    "کیک": {"emoji": "🎂", "coins": 1500},
    "خرس": {"emoji": "🧸", "coins": 3000},
    "گردنبند": {"emoji": "📿", "coins": 7500},
    "الماس": {"emoji": "💎", "coins": 15000},
    "ماشین": {"emoji": "🚗", "coins": 30000},
    "خونه": {"emoji": "🏠", "coins": 75000}
}

def load_owner_gifts(user_id):
    """🎁 کادوهای کلکسیونی کاربر (لیست اسم — قابل فروش با ۵۰٪)"""
    try:
        return json.loads(get_setting(f"gifts_{user_id}", "[]") or "[]")
    except Exception:
        return []

def save_owner_gifts(user_id, gifts):
    set_setting(f"gifts_{user_id}", json.dumps(gifts, ensure_ascii=False))

# ============================================================
# 8.2 👑 پنل اونر (دیتابیس/آمار/بکاپ/آموزش)
# ============================================================

def owner_panel_keyboard():
    """👑 پنل اونر — بخش‌بندی‌شده: هر بخش قابلیت‌های خودش رو داره"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار و بازیکنان", callback_data="panel_sec_stats"),
         InlineKeyboardButton("💾 بکاپ و بازیابی", callback_data="panel_sec_backup")],
        [InlineKeyboardButton("💰 مدیریت اقتصاد", callback_data="panel_sec_economy"),
         InlineKeyboardButton("👥 مدیریت کاربران", callback_data="panel_sec_users")],
        [InlineKeyboardButton("📢 اطلاع‌رسانی همگانی", callback_data="panel_sec_broadcast"),
         InlineKeyboardButton("🔒 جوین اجباری", callback_data="panel_sec_join")],
        [InlineKeyboardButton("📖 همه دستورات اونر", callback_data="panel_cmd_all")]
    ])

def panel_back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="panel_main")]])

def panel_sec_kb(*rows, back="panel_main"):
    """کیبورد بخش پنل: ردیف‌های دلخواه + دکمه بازگشت"""
    kb = [list(r) for r in rows]
    kb.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data=back)])
    return InlineKeyboardMarkup(kb)

# 🗂️ بخش‌های پنل اونر — متن + کیبورد هر بخش
def panel_sections(data):
    """خروجی: (متن، کیبورد) بخش پنل اونر یا None"""
    if data == "panel_sec_stats":
        return (
            "📊 **بخش آمار و بازیکنان**\n"
            "_همه‌چیز رو زیر نظر داشته باش!_\n"
            "━━━━━━━━━━━━━━\n"
            "👥 **دیتابیس بازیکنان** — لیست کامل با سکه/سطح/بن (صفحه‌بندی)\n"
            "📊 **آمار کلی** — تعداد بازیکنان، سکه در گردش، بردها، کره‌خرها\n\n"
            "👇 انتخاب کن:",
            panel_sec_kb(
                [InlineKeyboardButton("👥 دیتابیس بازیکنان", callback_data="panel_players_0")],
                [InlineKeyboardButton("📊 آمار کلی ربات", callback_data="panel_stats")],
            ))
    if data == "panel_sec_backup":
        return (
            "💾 **بخش بکاپ و بازیابی**\n"
            "_دیتا از جونت مهم‌تره!_ 😄\n"
            "━━━━━━━━━━━━━━\n"
            "💾 **بکاپ** — فایل JSON کامل دیتابیس همین‌جا\n"
            "📥 **بازیابی** — آموزش برگردوندن دیتا بعد ری‌استارت\n"
            "🤖 بکاپ خودکار هر ۱ ساعت به پی‌وی‌ات میاد\n\n"
            "💬 **دستور متنی:** `بکاپ` | ارسال فایل با کپشن `بازیابی`\n\n"
            "👇 انتخاب کن:",
            panel_sec_kb(
                [InlineKeyboardButton("💾 بکاپ همین الان", callback_data="panel_backup"),
                 InlineKeyboardButton("📥 آموزش بازیابی", callback_data="panel_restore_help")],
            ))
    if data == "panel_sec_economy":
        return (
            "💰 **بخش مدیریت اقتصاد**\n"
            "_تو بانک مرکزی طویله‌ای!_ 🏦\n"
            "━━━━━━━━━━━━━━\n"
            "➕ سکه دادن/کم‌کردن — با ریپلی یا از راه دور با آیدی!\n"
            "🎁 کادو دادن (۸ نوع، از جیبت کم نمی‌شه)\n"
            "🎊 سکه همگانی به همه بازیکنان\n"
            "🔄 ریست جدول هفتگی\n\n"
            "💬 **دستور متنی:**\n"
            "➕➖ ریپلی + `+سکه 1000` | بدون ریپلی: `+سکه 1000 آیدی/@اسم`\n"
            "🎁 ریپلی + `کادو گل` | از راه دور: `کادو گل 123456`\n"
            "🎊 `سکه‌همگانی 500` | 🔄 `ریست هفتگی`\n\n"
            "👇 آموزش کامل هر کدوم:",
            panel_sec_kb(
                [InlineKeyboardButton("💰 آموزش مدیریت سکه", callback_data="panel_cmd_coins"),
                 InlineKeyboardButton("🎁 آموزش کادو دادن", callback_data="panel_cmd_gifts")],
                [InlineKeyboardButton("🎊 آموزش سکه همگانی", callback_data="panel_cmd_mass")],
            ))
    if data == "panel_sec_users":
        return (
            "👥 **بخش مدیریت کاربران**\n"
            "_شلاق و هویج دست توئه!_ 🥕\n"
            "━━━━━━━━━━━━━━\n"
            "🚫 **بن** — کاربر خاطی از همه‌چیز محروم می‌شه\n"
            "✅ **آنبن** — بخشش و آزادی\n"
            "👥 لیست بن‌شده‌ها توی دیتابیس بازیکنان با 🚫 مشخصه\n\n"
            "💬 **دستور متنی:** ریپلی + `بن` | ریپلی + `انبن`\n\n"
            "👇 آموزش کامل:",
            panel_sec_kb(
                [InlineKeyboardButton("🚫 آموزش بن و آنبن", callback_data="panel_cmd_ban")],
                [InlineKeyboardButton("👥 دیتابیس بازیکنان", callback_data="panel_players_0")],
            ))
    if data == "panel_sec_broadcast":
        return (
            "📢 **بخش اطلاع‌رسانی همگانی**\n"
            "_صدات به همه طویله برسه!_ 📣\n"
            "━━━━━━━━━━━━━━\n"
            "📢 **اطلاعیه** — پیام متنی به همه گروه‌ها و پی‌وی‌ها\n"
            "📨 **فوروارد/کپی همگانی** — پست/عکس/ویدیو به همه\n"
            "🎊 **سکه همگانی** — باران سکه توی طویله\n\n"
            "💬 **دستور متنی:**\n"
            "📢 `اطلاعیه متن پیام...`\n"
            "📨 ریپلی + `فوروارد همگانی` (با برچسب کانال)\n"
            "📋 ریپلی + `کپی همگانی` (بدون برچسب)\n"
            "🎊 `سکه‌همگانی 500`\n\n"
            "👇 آموزش کامل:",
            panel_sec_kb(
                [InlineKeyboardButton("🎊 آموزش دستورات همگانی", callback_data="panel_cmd_mass")],
            ))
    if data == "panel_sec_join":
        status = "🔒 روشن" if force_join_enabled() else "🔓 خاموش"
        ch = get_setting("fj_channel", "") or "—"
        gp = get_setting("fj_group", "") or "—"
        return (
            "🔒 **بخش جوین اجباری**\n"
            "_ممبر جمع کن واسه کانالت!_ 📈\n"
            "━━━━━━━━━━━━━━\n"
            f"⚙️ وضعیت: **{status}**\n"
            f"📢 کانال: {ch}\n"
            f"👥 گروه: {gp}\n\n"
            "⛔ بدون عضویت، هیچ دستوری برای کاربر کار نمی‌کنه!\n"
            "(فقط روی دستورات ربات چک می‌شه، چت عادی آزاده)\n\n"
            "💬 **دستور متنی:**\n"
            "📢 `تنظیم کانال @X` — ربات باید ادمین کانال باشه!\n"
            "👥 `تنظیم گروه @X` — گروه عمومی با یوزرنیم\n"
            "🔒 `جوین اجباری روشن` | `جوین اجباری خاموش`\n"
            "⚙️ `وضعیت جوین` — نمایش تنظیمات فعلی\n\n"
            "👇 کلید سریع:",
            panel_sec_kb(
                [InlineKeyboardButton("🔒 روشن کن", callback_data="panel_fj_on"),
                 InlineKeyboardButton("🔓 خاموش کن", callback_data="panel_fj_off")],
                [InlineKeyboardButton("🔄 بروزرسانی وضعیت", callback_data="panel_sec_join")],
            ))
    return None

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
        "🌹 `کادو گل` — 300\n"
        "🍫 `کادو شکلات` — 750\n"
        "🎂 `کادو کیک` — 1,500\n"
        "🧸 `کادو خرس` — 3,000\n"
        "📿 `کادو گردنبند` — 7,500\n"
        "💎 `کادو الماس` — 15,000\n"
        "🚗 `کادو ماشین` — 30,000\n"
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
        "💬 بنویس: `سکه‌همگانی 500`\n"
        "✅ به تک‌تک بازیکنان ثبت‌شده ۵۰۰ سکه اضافه می‌شه\n"
        "💡😄 مناسب جشن، مناسبت یا عذرخواهی بابت قطعی!\n"
        "⚠️ حداکثر ۱٬۰۰۰٬۰۰۰ در هر بار\n\n"
        "**📢 پیام همگانی به همه چت‌ها:**\n"
        "💬 بنویس: `اطلاعیه سلام! آپدیت جدید اومد 🎉`\n"
        "✅ پیامت با سربرگ «اطلاعیه طویله خرستان» به همه گروه‌ها و پی‌وی‌هایی که ربات توشون فعاله فرستاده می‌شه\n"
        "📊 آخرش گزارش می‌گیری: چند تا موفق، چند تا ناموفق\n"
        "🧹 چت‌هایی که ربات ازشون حذف شده خودکار از لیست پاک می‌شن\n\n"
        "⏱️ ارسال با فاصله انجام می‌شه که تلگرام ربات رو محدود نکنه."
    ),
    "panel_cmd_all": (
        "📖 **همه دستورات اونر — یکجا**\n"
        "━━━━━━━━━━━━━━\n"
        "**🎛️ پنل و دیتابیس:**\n"
        "🎛️ `پنل` — باز کردن همین پنل\n"
        "💾 `بکاپ` — دریافت فایل بکاپ دیتابیس\n"
        "📥 ارسال فایل بکاپ با کپشن `بازیابی` — برگردوندن دیتا\n\n"
        "**🎊 همگانی:**\n"
        "🎊 `سکه‌همگانی 500` — سکه به همه بازیکنان\n"
        "📢 `اطلاعیه متن پیام` — پیام به همه گروه‌ها و پی‌وی‌ها\n\n"
        "**👤 مدیریت کاربر (همه با ریپلی):**\n"
        "➕ `+سکه 1000` — اضافه کردن سکه\n"
        "➖ `-سکه 500` — کم کردن سکه\n"
        "🎁 `کادو گل` — کادو دادن (۸ نوع کادو)\n"
        "🚫 `بن` — مسدود کردن کاربر\n"
        "✅ `انبن` — رفع مسدودی\n\n"
        "**⚠️ نکات مهم:**\n"
        "• همه این دستورات فقط برای تو کار می‌کنن (OWNER_ID)\n"
        "• کاربر عادی حتی نمی‌فهمه پنل وجود داره\n"
        "• دیتابیس توی /tmp هست → بعد از هر ری‌استارت سرور، فایل بکاپ رو با کپشن «بازیابی» بفرست\n"
        "• هر شب یه `بکاپ` بگیر و توی Saved Messages نگه دار 💾"
    )
}

# 🔙 هر آموزش به کدوم بخش پنل برگرده
PANEL_GUIDE_BACK = {
    "panel_cmd_coins": "panel_sec_economy",
    "panel_cmd_gifts": "panel_sec_economy",
    "panel_cmd_mass": "panel_sec_broadcast",
    "panel_cmd_ban": "panel_sec_users",
    "panel_cmd_all": "panel_main",
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
        nav.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"panel_players_{page+1}"))
    rows = []
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="panel_sec_stats")])
    return InlineKeyboardMarkup(rows)

def export_db_json():
    """خروجی کامل دیتابیس به JSON برای بکاپ"""
    with closing(db_connect()) as db:
        users = [dict(r) for r in db.execute("SELECT * FROM users").fetchall()]
        donkeys = [dict(r) for r in db.execute("SELECT * FROM donkeys").fetchall()]
        chats = [dict(r) for r in db.execute("SELECT * FROM chats").fetchall()]
        settings = [dict(r) for r in db.execute("SELECT * FROM settings").fetchall()]
        league = [dict(r) for r in db.execute("SELECT * FROM league").fetchall()]
        rally = [dict(r) for r in db.execute("SELECT * FROM rally").fetchall()]
    return {
        "version": 2,
        "exported_at": int(time.time()),
        "users": users,
        "donkeys": donkeys,
        "chats": chats,
        "settings": settings,
        "league": league,
        "rally": rally
    }

def import_db_json(data):
    """وارد کردن بکاپ JSON به دیتابیس — کاربران موجود آپدیت می‌شوند"""
    if not isinstance(data, dict) or "users" not in data:
        raise ValueError("فرمت بکاپ نامعتبر است")
    
    users = data.get("users", [])
    donkeys = data.get("donkeys", [])
    
    user_cols = ["user_id","name","coins","level","wins","losses","is_banned","created_at",
                 "last_mate","babies","baby_names","last_sound","last_daily",
                 "last_work","last_wheel","last_rob","last_fortune","sound_count",
                 "bank_balance","bank_last","insurance_until"]
    donkey_cols = ["user_id","equipped_hat","equipped_saddle","equipped_horseshoe",
                   "equipped_tie","equipped_clothes","equipped_accessory",
                   "equipped_talisman","equipped_magic","items"]
    
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
            vals = [d.get(c, ("[]" if c == "items" else ("" if c != "user_id" else 0))) for c in donkey_cols]
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
        # 🏆 جدول هفتگی هم برگرده
        for lg in data.get("league", []):
            if "user_id" not in lg: continue
            db.execute("INSERT OR REPLACE INTO league (user_id, earned) VALUES (?, ?)",
                      (lg["user_id"], lg.get("earned", 0)))
        # 🏇 آمار رالی هم برگرده
        for rl in data.get("rally", []):
            if "user_id" not in rl: continue
            db.execute("INSERT OR REPLACE INTO rally (user_id, wins, losses) VALUES (?, ?, ?)",
                      (rl["user_id"], rl.get("wins", 0), rl.get("losses", 0)))
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
        # 💸 بکاپ قدیمی (نسخه ۱) وسیله‌های فروشگاه قدیمی داره → پولشون برگرده
        refund_note = ""
        if data.get("version", 1) < 2:
            set_setting("shop2_refund_done", "")  # اجازه اجرای دوباره مهاجرت
            r_users, r_total = migrate_old_shop_refund()
            if r_users:
                refund_note = f"\n💸 وسیله‌های فروشگاه قدیمی {r_users} نفر شناسایی شد — جمعاً {r_total:,} {CURRENCY_NAME} بهشون برگشت!"
        await update.message.reply_text(
            f"✅ **بازیابی موفق!**\n"
            f"👥 {count} بازیکن به دیتابیس برگردانده شد.\n"
            f"🎒 وسایل و مشخصات همه برگشت داده شد.{refund_note}",
            parse_mode="Markdown"
        )
        logger.info(f"✅ بکاپ بازیابی شد: {count} کاربر")
    except json.JSONDecodeError:
        await update.message.reply_text("❌ فایل JSON معتبر نیست!")
    except Exception as e:
        logger.error(f"❌ خطا در بازیابی: {e}")
        await update.message.reply_text(f"❌ خطا در بازیابی: {e}")

# ============================================================
# 8.3 🧠 خر دانا (هوش مصنوعی)
# ============================================================

import httpx

KHAR_DANA_COST = 250          # 💰 هزینه هر سوال (تی‌تاپ)
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
        await update.message.reply_text(f"❌🐴 سوالت خیلی درازه! (حداکثر {KHAR_DANA_MAX_Q} حرف) خلاصه‌ش کن")
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
            add_coins(user.id, KHAR_DANA_COST, league=False)
            await thinking.edit_text("😵 خر دانا الان مغزش هنگ کرد! پولت برگشت، چند دقیقه دیگه امتحان کن.")
    except Exception as e:
        logger.error(f"❌ خطای خر دانا: {e}")
        add_coins(user.id, KHAR_DANA_COST, league=False)
        try:
            if thinking:
                await thinking.edit_text("😵 خر دانا الان در دسترس نیست! پولت برگشت.")
        except Exception:
            pass
    finally:
        _KD_BUSY.discard(user.id)

# ============================================================
# 8.4 📤 ارسال همگانی (متن/فوروارد/کپی)
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
        await asyncio.sleep(0.5)  # رعایت محدودیت تلگرام — آروم‌تر که flood نگیره
    
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


# ╔══════════════════════════════════════════════════════════╗
# ║                 فصل 9 📨 هندلرها (پیام/جوین/دکمه‌ها)
# ╚══════════════════════════════════════════════════════════╝
# ============================================================
# 9.1 📨 هندلر پیام‌های متنی (همه دستورات)
# ============================================================

HELP_MAIN_TEXT = (
    "📖🫏 **راهنمای کامل طویله خرستان**\n"
    "━━━━━━━━━━━━━━\n"
    "🗣️ همه‌چیز با **دستور فارسی** کار می‌کنه — کافیه تایپ کنی!\n\n"
    "**⚡ دستورات پرکاربرد:**\n"
    "🏠 `منو` | 🎮 `بازی‌ها` | 🏪 `فروشگاه`\n"
    "👤 `پروفایل` | 💰 `سکه` | 🏆 `جدول`\n"
    "🎁 `روزانه` | 💼 `کار` | 🎡 `گردونه` | 🔮 `فال`\n"
    "🐴 `خرم` | 🔊 `صداها` | 📖 `راهنما`\n"
    "🎲 بازی: `انفجار 500` | `اسلات 500` | ...\n"
    "🧠 `خر جان سوالت...` — از خر دانا بپرس! (۲۵۰ تی‌تاپ)\n\n"
    "👇 برای توضیح کامل هر بخش، دکمه‌ش رو بزن:"
)

HELP_SECTIONS = {
    "help_games": (
        "🎮 **بازی‌های گروهی** — اسم بازی + شرط:\n"
        "━━━━━━━━━━━━━━\n"
        "💥 `انفجار 500` — ضریب بالا می‌ره، قبل انفجار برداشت کن! (تا ۱۰ نفر)\n"
        "🎲 `تاس 500` — ۵ پرتاب نوبتی با گزارشگر! مجموع بالاتر می‌بره (تا ۱۰ نفر)\n"
        "🔫 `رولت 500` — نوبتی انتخاب کن به کی شلیک بشه! آخرین بازمانده می‌بره (تا ۱۰ نفر)\n"
        "🔼🔽 `حدس 500` — حدس مجموع دو تاس، دقیقاً ۷ = x5 (تا ۱۰ نفر)\n"
        "🎰 `پوکر 500` — بهترین دست ۵ کارتی می‌بره (تا ۶ نفر)\n"
        "🃏 `بلک‌جک 500` — نزدیک‌ترین به ۲۱ بدون سوختن (تا ۶ نفر)\n"
        "❌⭕ `دوز 500` — سه‌تا ردیف کن! (۲ نفره)\n"
        "✊ `سنگ 500` — سنگ‌کاغذقیچی بهترین از ۵ دست! (۲ نفره)\n"
        "🪙 `شیرخط 500` — طرفت رو انتخاب کن، ربات تاس می‌ندازه! (۲ نفره)\n\n"
        "🆕 **بازی‌های جدید:**\n"
        "🎯 `دارت 500` — ۵ پرتاب نوبتی با گزارشگر! مجموع بالاتر می‌بره (تا ۱۰ نفر)\n"
        "🎳 `بولینگ 500` — ۵ پرتاب نوبتی با گزارشگر! استرایک = ۶ (تا ۱۰ نفر)\n"
        "🏀 `بسکتبال 500` — ۵ پرتاب نوبتی! سبد بیشتر می‌بره (تا ۱۰ نفر)\n"
        "⚽ `پنالتی 500` — سری ۵ ضربه‌ای نوبتی با گزارشگر! مساوی = ضربات طلایی (۲ نفره)\n"
        "🔢 `حدس‌عدد 500` — عدد مخفی ۱-۱۰۰، نوبتی حدس بزن! (تا ۱۰ نفر)\n"
        "💣 `مین 500` — جعبه بمب‌دار رو باز نکن! حذفی (تا ۵ نفر — ۳ نفر به بالا ۱۶ جعبه!)\n\n"
        "🎰 **بازی فوری تکی:**\n"
        "`اسلات 500` — انیمیشن واقعی! سه‌تایی 7️⃣ = x20 جکپات!\n\n"
        "💡 بازی‌های ۲ نفره با ورود نفر دوم خودکار شروع می‌شن.\n"
        "💡 می‌تونی فقط اسم بازی رو بنویسی (مثلاً `انفجار`) تا ربات مبلغ شرط رو ازت بپرسه.\n"
        "⏰ اگه بازی تا ۵ دقیقه شروع نشه، خودکار لغو می‌شه و شرط‌ها برمی‌گرده.\n"
        "🆘 بازی گیر کرد؟ بنویس `لغو بازی` — اگه ۳ دقیقه حرکتی نشده باشه لغو می‌شه و پول همه برمی‌گرده."
    ),
    "help_money": (
        "💰 **راه‌های پول درآوردن:**\n"
        "━━━━━━━━━━━━━━\n"
        "🎁 `روزانه` — جایزه ۵۰۰ تا ۱۵۰۰ (هر ۲۴ ساعت)\n"
        "💼 `کار` — دستمزد تا ۹۰۰! (هر ۳۰ دقیقه)\n"
        "🎡 `گردونه` — تا ۱۰٬۰۰۰ جایزه! (هر ۳ ساعت)\n"
        "🔮 `فال` — فال + برکت تا ۲۰۰ (هر ۶ ساعت)\n"
        "🔊 عرعر کن! — هر صدا ۱۵۰ تا ۱۲۰۰ شانسی (هر ۵ دقیقه)\n"
        "🦹 `دزدی` (با ریپلی) — ۴۰٪ شانس، ولی جریمه داره! (هر ۲ ساعت)\n"
        "🆘 `گدایی` — ورشکستی؟ مردم کمکت می‌کنن! (هر ۴ ساعت)\n"
        "🏦 `دزدی بانک` — شانس کم، جایزه تا ۵۰هزار! گیر بیفتی ۱ ساعت حبسی! (هر ۶ ساعت)\n"
        "💨 `تریاک` — نئشه شی درآمدت ×۲... ولی ۵ بست = اعتیاد! (۵هزار)\n"
        "🍾 ریپلی + `عرق` — با رفیقت بزن، جفتتون جایزه! (هر ۴ ساعت)\n"
        "🏥 `کمپ` — ترک اعتیاد: ۲۵هزار + ۲۴ ساعت قفل\n"
        "💸 `انتقال 100` (با ریپلی یا آیدی) — سکه بده به رفیقت (۱۰٪ مالیات، سقف ۱۰۰هزار)\n\n"
        "🏦 **بانک خرستان:**\n"
        "🏦 `بانک` — حسابت | `واریز 1000` / `واریز همه` | `برداشت همه`\n"
        "💹 `سود` — روزی **۲۰٪ سود**! ⚠️ هر روز باید خودت برداری وگرنه می‌سوزه!\n"
        "💳 `وام 5000` (ریپلی روی ضامن سطح ۲+) — وام تا ۳۰هزار برای فقرا | `تسویه وام`\n"
        "🛡️ پولت توی بانک از دزدی در امانه!\n\n"
        "🛡️ **بیمه خرستان:**\n"
        "🛡️ `بیمه` — وضعیت | `خرید بیمه` — ۱۵هزار برای ۳ روز\n"
        "📉 ۲۰٪ باخت **همه بازی‌ها** خودکار برمی‌گرده (بدون سقف!) + دزدها حریفت نمی‌شن!"
    ),
    "help_sounds": SOUNDS_LIST_TEXT,
    "help_donkey": (
        "🐴 **خر شخصی تو:**\n"
        "━━━━━━━━━━━━━━\n"
        "🐴 `خرم` — نمایش خرت با تجهیزاتش\n"
        "🏪 `فروشگاه` — ۶۴ قلم تو ۸ دسته! هر وسیله باف واقعی + ⚡ قدرت خر می‌ده\n"
        "💰 `فروش` — وسایل و کادوها رو با ۵۰٪ قیمت بفروش\n"
        "🏇 `رالی 1000` — با قدرت خرت مسابقه بده! (تو همین گروه)\n"
        "👤 `پروفایل` — مشخصات کامل (با ریپلی: پروفایل بقیه)\n"
        "❤️ `جفت‌گیری` یا `جفتگیری` (با ریپلی) — کره‌خر دار شو! (سطح ۲ لازمه، ۱۵۰۰ سکه)\n"
        "💌 طرف مقابل باید با دکمه «قبوله!» موافقت کنه وگرنه انجام نمی‌شه\n"
        "🐣 `کره‌خرها` — پنل کره‌خرها با دکمه: ارتقا، سود، تغییر اسم\n"
        "⬆️ `ارتقا کره‌خر 1` — ارتقا بده تا سود بیشتری بده (تا ۵۰۰۰ در روز!)\n"
        "📛 `اسم کره‌خر 1 فلفلی` — اسم دلخواه بذار\n"
        "💰 سود کره‌خرها رو هر روز از پنل `کره‌خرها` با دکمه بردار!\n"
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
        "🧠 `خر جان هرچی می‌خوای بپرس` — خر دانا با هوش مصنوعی جوابتو می‌ده! (۲۵۰ تی‌تاپ، ۱۰ سوال در روز)\n"
        "📖 `راهنما` — همین راهنما\n"
        "/start — پیام خوش‌آمد\n\n"
        "🔒 **نکته:** هر منویی که خودت باز کنی، فقط خودت می‌تونی دکمه‌هاش رو بزنی. "
        "🎮 فقط دکمه‌های وسط بازی (مثل «ورود به بازی») برای همه آزاده!"
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
    "🎛️ `اونر` یا `پنل` — پنل مدیریت: دیتابیس بازیکنان، آمار، بکاپ\n"
    "💾 `بکاپ` — دریافت فایل بکاپ کامل دیتابیس\n"
    "📥 ارسال فایل بکاپ با کپشن `بازیابی` — برگرداندن دیتابیس\n"
    "🎊 `سکه‌همگانی 500` — سکه به **همه** بازیکنان\n"
    "📢 `اطلاعیه متن...` — پیام به **همه** گروه‌ها و پی‌وی‌ها\n"
    "📨 ریپلی + `فوروارد همگانی` / `کپی همگانی` — ارسال پست/عکس/ویدیو به همه\n"
    "🔒 `تنظیم کانال @X` / `تنظیم گروه @X` — اهداف جوین اجباری\n"
    "`جوین اجباری روشن` / `خاموش` | `وضعیت جوین` 🔒\n\n"
    "**با ریپلی:**\n"
    "💰 `+سکه 1000` — سکه دادن\n"
    "🔥 `-سکه 1000` — کسر سکه\n"
    "🎁 `کادو گل` — کادو دادن\n"
    "🚫 `بن` / `انبن` — بن و آنبن\n\n"
    "🎁 **کادوها:** گل 🌹(300) | شکلات 🍫(750) | کیک 🎂(1500) | خرس 🧸(3000) | گردنبند 📿(7500) | الماس 💎(15000) | ماشین 🚗(30000) | خونه 🏠(75000)"
)

# ============================================================
# 9.2 🔒 جوین اجباری (کانال + گروه)
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

# ⚡ چک‌های روزانه (مالیات/قسط وام) هر کاربر فقط هر ۱۰ دقیقه
_DAILY_CHECKS_AT = {}

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
    "لغو بازی", "لغوبازی", "خروج از بازی", "cancelgame",
    "بانک", "bank", "حساب بانکی", "بیمه", "insurance", "خرید بیمه", "خریدبیمه", "بیمه بخر",
    "گدایی", "کمک مالی", "beg", "تریاک", "بساط", "opium", "لیگ", "جدول هفتگی", "لیگ هفتگی", "league",
    "دزدی بانک", "دزدی از بانک", "سرقت بانک", "سرقت از بانک", "خرید جفت‌گیری", "خرید جفتگیری", "خرید جفت گیری",
    "سود", "سود بانک", "برداشت سود", "تسویه وام", "تسویه‌وام", "تسویه",
    "کمپ", "کمپ ترک", "ترک اعتیاد", "camp", "عرق", "عرق‌خوری", "عرق خوری", "مشروب",
    "رالی", "rally", "مسابقه", "فروش", "فروش وسایل", "فروش وسیله", "sell"
}
FJ_FIRST_WORD_CMDS = {"اسلات", "slot", "انتقال", "transfer", "هدیه", "ارتقا", "اسم", "خرجان", "خردانا", "واریز", "برداشت", "deposit", "withdraw", "وام", "loan"}

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
    
    # ⛓️ بازداشت؟ هیچ دستوری کار نمی‌کنه (فقط به دستورات ربات جواب بده، نه چت عادی)
    jail_left = is_jailed(user.id)
    if jail_left > 0:
        if looks_like_bot_command(update, context, text):
            await update.message.reply_text(
                f"🚔⛓️ **تو بازداشتی!**\n"
                f"⏳ {jail_left // 60} دقیقه و {jail_left % 60} ثانیه دیگه آزاد می‌شی.\n"
                f"😏 تا اون موقع هیچ کاری نمی‌تونی بکنی!")
        return
    
    # 🏥 توی کمپ ترک؟ همه‌چیز قفل! (پایان دوره خودکار چک می‌شه)
    camp_left = in_camp(user.id)
    if camp_left > 0:
        if looks_like_bot_command(update, context, text):
            await update.message.reply_text(
                f"🏥 **تو کمپ ترکی!**\n{random.choice(CAMP_MOODS)}\n"
                f"⏳ {camp_left // 3600} ساعت و {(camp_left % 3600) // 60} دقیقه مونده تا پاکی کامل!",
                parse_mode="Markdown")
        return
    if camp_finish_check(user.id):
        await update.message.reply_text(
            "🎉🏥 **از کمپ اومدی بیرون — پاکِ پاک!**\n"
            "💪 اعتیادت ترک شد، شمارنده بست‌ها صفر شد!\n"
            "🐴 دیگه طرف بساط نرو خب؟!", parse_mode="Markdown")
    
    # 🥶 خماری اعتیاد؟ فقط روزانه/کار/گدایی/تریاک/کمپ کار می‌کنه
    if is_addict_hungover(user.id):
        first_word = text.split()[0] if text.split() else ""
        if text not in HANGOVER_ALLOWED and first_word not in HANGOVER_ALLOWED:
            if looks_like_bot_command(update, context, text):
                await update.message.reply_text(
                    "🥶💀 **خماری!! دستات می‌لرزه...**\n"
                    "⛓️ تا یه بست نکشی هیچ کاری نمی‌تونی بکنی!\n"
                    "💨 بنویس: `تریاک` (۵,۰۰۰)\n"
                    "🏥 یا برای همیشه ترک کن: `کمپ` (۲۵,۰۰۰ + ۲۴ ساعت قفل)\n"
                    "💰 پول نداری؟ «روزانه» و «کار» و «گدایی» هنوز کار می‌کنن!",
                    parse_mode="Markdown")
            return
    
    # 🔒 جوین اجباری — بدون عضویت هیچ دستوری کار نمی‌کنه
    if not await force_join_gate(update, context, user.id):
        return
    
    # 💸 اطلاع‌رسانی رفاند فروشگاه قدیمی — یه بار، با اولین دستور کاربر
    _refund_note = get_setting(f"shop_refund_note_{user.id}", "")
    if _refund_note and looks_like_bot_command(update, context, text):
        set_setting(f"shop_refund_note_{user.id}", "")
        try:
            await update.message.reply_text(
                f"📢 **خبر مهم — فروشگاه طویله نو شد!** 🏪✨\n"
                f"━━━━━━━━━━━━━━\n"
                f"🎒 وسیله‌های قدیمی خرت جمع شدن، ولی نگران نباش:\n"
                f"💸 **{int(_refund_note):,}** {CURRENCY_NAME} — پول وسایلت **کامل** برگشت تو جیبت!\n\n"
                f"🆕 فروشگاه جدید ۶۴ قلم داره و هر وسیله **قابلیت واقعی** می‌ده:\n"
                f"💼 درآمد بیشتر | 🛡️ سپر دزدی | ⚡ قدرت خر برای رالی!\n\n"
                f"👉 بنویس: `فروشگاه` و خرت رو دوباره تجهیز کن! 🐴",
                parse_mode="Markdown")
        except Exception:
            pass
    
    # ⚡ چک‌های روزانه (مالیات/قسط) فقط هر ۱۰ دقیقه یه بار — نه با هر پیام
    _now_chk = time.time()
    _do_daily_checks = _now_chk - _DAILY_CHECKS_AT.get(user.id, 0) >= 600
    if _do_daily_checks:
        _DAILY_CHECKS_AT[user.id] = _now_chk
    
    # 💸 مالیات ثروت (روزی یه بار برای خیلی‌پولدارها)
    try:
        tax = collect_wealth_tax(user.id) if _do_daily_checks else 0
        if tax > 0:
            await update.message.reply_text(
                f"💸 **مالیات طویله!**\n"
                f"👑 {esc_md(user.first_name)} عزیز، نگهداری این همه ثروت خرج داره!\n"
                f"🧾 {tax:,} {CURRENCY_NAME} هزینه نگهداری طویله کم شد.\n"
                f"💡 (فقط ثروت بالای {WEALTH_TAX_THRESHOLD:,} مالیات می‌خوره)",
                parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"⚠️ خطا در مالیات: {e}")
    
    # 💳 وصول خودکار قسط وام (روزی یک قسط — نداشت از ضامن! 😂)
    try:
        events = loan_collect_due(user.id) if _do_daily_checks else []
        for ev in events:
            if ev[0] == "guarantor" and ev[3] > 0:
                _, due, from_self, from_g = ev
                debt_left = get_loan(user.id)
                await update.message.reply_text(
                    f"💳😂 **قسط وام وصول شد!**\n"
                    f"👤 {esc_md(user.first_name)} پول قسط ({due:,}) رو نداشت!\n"
                    f"💸🤣 {from_g:,} {CURRENCY_NAME} از جیب **ضامن** بدبختش کم شد!\n"
                    f"📊 باقی بدهی: {debt_left:,}",
                    parse_mode="Markdown")
                break  # فقط یه پیام، اسپم نشه
    except Exception as e:
        logger.warning(f"⚠️ خطا در وصول قسط: {e}")
    
    # 🔢 عدد برای بازی حدس عدد فعال؟
    if await guessnum_text_received(update, context):
        return
    
    # ===== شروع =====
    if text.startswith("/start"):
        await reply_menu(update,
            "🫏✨ **به طویله خرستان خوش اومدی!**\n"
            "━━━━━━━━━━━━━━\n\n"
            "🎮 **۱۵ بازی گروهی** با گزارشگر زنده\n"
            "🎰 اسلات فوری با انیمیشن واقعی\n"
            "🏦 بانک با سود روزانه + وام و بیمه\n"
            "🐣 کره‌خر بزرگ کن، سود روزانه بگیر\n"
            "🔊 **۱۶ مدل عرعر** — هر عر تا ۱٬۲۰۰ تی‌تاپ!\n"
            "🏆 جدول هفتگی با جایزه ۲۰۰ هزارتایی\n"
            "🧠 خر دانا — هوش مصنوعی خودمون!\n\n"
            "━━━━━━━━━━━━━━\n"
            "📖 همه دستورات: بنویس **راهنما**",
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
            f"⚙️ وضعیت: {status}\n📢 کانال: {ch or '—'}\n👥 گروه: {gp or '—'}\n\n"
            f"📋 دستورات:\n`تنظیم کانال @X` | `تنظیم گروه @X`\n`جوین اجباری روشن` | `جوین اجباری خاموش`",
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
            f"🐴🎉 همه دارن عرعر خوشحالی می‌کنن!",
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
                "📨 پیامت به **همه گروه‌ها و پی‌وی‌هایی** که ربات توشونه فرستاده می‌شه.\n\n"
                "💡 برای ارسال پست کانال/عکس/ویدیو به همه:\n"
                "👉 روی پیامش **ریپلی** بزن و بنویس `فوروارد همگانی` یا `کپی همگانی`",
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
                "📨 `فوروارد همگانی` — با برچسب «Forwarded from» (تبلیغ کانالت!)\n"
                "📋 `کپی همگانی` — بدون برچسب، انگار خود ربات فرستاده",
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
    
    # ===== 🆘 گدایی (تور نجات ورشکسته‌ها) =====
    if text in ["گدایی", "کمک مالی", "beg"]:
        await beg_command(update, context)
        return
    
    # ===== دزدی =====
    # ===== 🏦🦹 دزدی از بانک =====
    if text in ["دزدی بانک", "دزدی از بانک", "سرقت بانک", "سرقت از بانک"]:
        await bank_heist_command(update, context)
        return
    
    # ===== 🏥 کمپ ترک اعتیاد =====
    if text in ["کمپ", "کمپ ترک", "ترک اعتیاد", "camp"]:
        await camp_command(update, context)
        return
    
    # ===== 🏇 منوی رالی (بدون عدد — با عدد میره تو GAME_ALIASES مثل بقیه بازی‌ها) =====
    if text in ["رالی", "rally", "مسابقه"]:
        await reply_menu(update, rally_menu_text(user.id), rally_menu_keyboard())
        return
    
    # ===== 🍾 عرق‌خوری (ریپلای روی رفیق) =====
    if text in ["عرق", "عرق‌خوری", "عرق خوری", "بزن بریم عرق", "مشروب"]:
        await drink_command(update, context)
        return
    
    # ===== 💨 تریاک (منوی تایید) =====
    if text in ["تریاک", "بساط", "opium"]:
        last_op = int(get_setting(f"opium_last_{user.id}", "0") or 0)
        if int(time.time()) - last_op < OPIUM_COOLDOWN:
            rem = OPIUM_COOLDOWN - (int(time.time()) - last_op)
            await update.message.reply_text(f"💨 ساقی گفت: صبر کن دود قبلی بره هوا! {rem//60} دقیقه دیگه بیا.")
            return
        await reply_menu(update, opium_menu_text(user.id), opium_menu_keyboard(user.id))
        return
    
    # ===== ⚡ لیگ هفتگی =====
    if text in ["لیگ", "جدول هفتگی", "لیگ هفتگی", "league"]:
        await update.message.reply_text(league_text(user.id), parse_mode="Markdown")
        return
    
    # ===== ❤️ خرید جفت‌گیری دوباره =====
    # ===== 💰 فروش وسایل و کادوها (منوی دکمه‌ای) =====
    if text in ["فروش", "فروش وسایل", "فروش وسیله", "sell"]:
        owned = load_donkey_items(user.id)
        gifts = load_owner_gifts(user.id)
        if not owned and not gifts:
            await update.message.reply_text("🎒 هیچ وسیله یا کادویی نداری که بفروشی!\n🏪 اول از «فروشگاه» خرید کن.")
            return
        buttons = []
        for it in owned[:30]:
            cat_, idata_ = find_shop_item(it)
            if not idata_: continue
            buttons.append([InlineKeyboardButton(
                f"{idata_['emoji']} {it} → 💰 {idata_['price']//2:,}",
                callback_data=f"sellask_{it}")])
        for g_ in set(gifts):
            if g_ in OWNER_GIFTS:
                gd_ = OWNER_GIFTS[g_]
                cnt_ = gifts.count(g_)
                buttons.append([InlineKeyboardButton(
                    f"{gd_['emoji']} کادو {g_}{f' ×{cnt_}' if cnt_ > 1 else ''} → 💰 {gd_['coins']//2:,}",
                    callback_data=f"sellgift_{g_}")])
        buttons.append([InlineKeyboardButton("🏠 منو", callback_data="home")])
        await reply_menu(update,
            "💰 **فروش وسایل و کادوها**\n_نصف قیمت خرید برمی‌گرده — فکرات رو بکن!_\n━━━━━━━━━━━━━━\n👇 چی می‌فروشی؟",
            InlineKeyboardMarkup(buttons))
        return
    
    if text in ["خرید جفت‌گیری", "خرید جفتگیری", "خرید جفت گیری"]:
        await buy_mate_reset(update, context)
        return
    
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
    
    # ===== 🏦 پنل بانک =====
    if text in ["بانک", "bank", "حساب بانکی", "پنل بانک"]:
        await reply_menu(update, bank_panel_text(user.id), bank_panel_keyboard(user.id))
        return
    
    parts_bank = text.split()
    if parts_bank and parts_bank[0] in ["واریز", "deposit"]:
        if len(parts_bank) < 2:
            await update.message.reply_text("🏦 روش استفاده: `واریز 1000` یا `واریز همه`", parse_mode="Markdown")
            return
        arg = parts_bank[1].translate(FA_DIGITS)
        if arg in ["همه", "کل", "all"]:
            # 💰 واریز کل جیب به بانک
            u = get_user(user.id)
            amount = u["coins"] or 0
            if amount < BANK_MIN_DEPOSIT:
                await update.message.reply_text(f"❌ جیبت ({amount:,}) کمتر از حداقل واریزه ({BANK_MIN_DEPOSIT})!")
                return
            await bank_deposit(update, context, amount)
            return
        if not arg.isdigit():
            await update.message.reply_text("🏦 روش استفاده: `واریز 1000` یا `واریز همه`", parse_mode="Markdown")
            return
        await bank_deposit(update, context, int(arg))
        return
    
    # 💹 برداشت سود روزانه
    if text in ["سود", "سود بانک", "برداشت سود"]:
        await bank_claim_interest(update, context)
        return
    
    # 💳 وام
    if parts_bank and parts_bank[0] in ["وام", "loan"]:
        if len(parts_bank) < 2 or not parts_bank[1].translate(FA_DIGITS).isdigit():
            await update.message.reply_text(
                f"💳 روش استفاده: روی پیام **ضامن** (سطح {LOAN_GUARANTOR_LEVEL}+) ریپلی بزن و بنویس `وام 5000`\n"
                f"📋 شرایط: پول نقدت زیر {LOAN_NEED_BELOW:,} باشه | سقف: {LOAN_MAX:,}",
                parse_mode="Markdown")
            return
        await loan_request(update, context, int(parts_bank[1].translate(FA_DIGITS)))
        return
    
    if text in ["تسویه وام", "تسویه‌وام", "تسویه"]:
        await loan_repay(update, context)
        return
    
    if parts_bank and parts_bank[0] in ["برداشت", "withdraw"]:
        if len(parts_bank) < 2:
            await update.message.reply_text("🏦 روش استفاده: `برداشت 1000` یا `برداشت همه`", parse_mode="Markdown")
            return
        arg = parts_bank[1].translate(FA_DIGITS)
        if not (arg.isdigit() or arg in ["همه", "کل", "all"]):
            await update.message.reply_text("🏦 روش استفاده: `برداشت 1000` یا `برداشت همه`", parse_mode="Markdown")
            return
        await bank_withdraw(update, context, arg)
        return
    
    # ===== 🛡️ پنل بیمه =====
    if text in ["بیمه", "insurance", "پنل بیمه"]:
        await reply_menu(update, insurance_panel_text(user.id), insurance_panel_keyboard(user.id))
        return
    
    if text in ["خرید بیمه", "خریدبیمه", "بیمه بخر"]:
        await insurance_buy(update, context)
        return
    
    # ===== نمایش خر =====
    if text in ["خرم", "خر من", "donkey"]:
        await update.message.reply_text(donkey_art(user.id), parse_mode="Markdown")
        return
    
    # ===== انتقال سکه =====
    parts_tr = text.split()
    if parts_tr and parts_tr[0] in ["انتقال", "transfer", "هدیه"]:
        if len(parts_tr) < 2:
            await update.message.reply_text(
                "💸 **روش‌های انتقال:**\n"
                "1️⃣ ریپلی + `انتقال 100`\n"
                "2️⃣ با آیدی عددی: `انتقال 100 123456789`\n"
                "3️⃣ با اسم: `انتقال 100 @علی`",
                parse_mode="Markdown")
            return
        val = parts_tr[1].translate(FA_DIGITS)
        if not val.isdigit():
            await update.message.reply_text("❌ مبلغ باید عدد باشه! مثال: `انتقال 100`", parse_mode="Markdown")
            return
        # هدف اختیاری: آیدی عددی یا اسم بعد از مبلغ
        target_ref = " ".join(parts_tr[2:]) if len(parts_tr) > 2 else None
        await transfer_command(update, context, int(val), target_ref)
        return
    
    # ===== منو =====
    if text in ["منو", "menu", "خانه"]:
        await reply_menu(update, "🏠 **منوی اصلی طویله خرستان**\n━━━━━━━━━━━━━━\nچی کار می‌خوای بکنی؟ 👇", main_menu())
        return
    
    # ===== لیست بازی‌ها =====
    if text in ["بازی", "بازی‌ها", "بازیها", "games"]:
        await reply_menu(update,
            "🎮 **انتخاب بازی:**\n\n"
            "💬 می‌تونی مستقیم تایپ کنی: `انفجار 500`\n"
            "👇 یا از دکمه‌ها انتخاب کنی:",
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
                add_coins(user.id, room.bet, league=False)
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
        await reply_menu(update,
            "🏆 **کدوم جدول رو می‌خوای ببینی؟**",
            leaderboard_choice_keyboard())
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
            await update.message.reply_text(f"🎰 روش بازی: `اسلات 500` (حداقل {MIN_BET})", parse_mode="Markdown")
            return
        await slot_game(update, context, bet)
        return
    
    # ===== ساخت بازی گروهی با دستور فارسی (مثلاً: انفجار 500 یا فقط: انفجار) =====
    if parts_fa and parts_fa[0] in GAME_ALIASES:
        game_type = GAME_ALIASES[parts_fa[0]]
        bet = parse_bet_arg(parts_fa)
        if bet is None:
            if len(parts_fa) >= 2:
                # عدد نوشته ولی نامعتبره
                await update.message.reply_text(
                    f"❌ مبلغ نامعتبره! حداقل شرط {MIN_BET} {CURRENCY_NAME} است.\nمثال: `{parts_fa[0]} 500`",
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
    # 👑 دستورات ادمین بدون ریپلی — با آیدی/یوزرنیم/اسم
    # «+سکه 5000 123456» | «-سکه 2000 @علی» | «کادو گل 123456»
    # ============================================================
    
    if user.id == OWNER_ID and not update.message.reply_to_message:
        parts_o = text.split()
        if parts_o and parts_o[0] in ["+سکه", "-سکه", "کادو"] and len(parts_o) >= 3:
            ref = " ".join(parts_o[2:])
            row_t = find_user_by_ref(ref)
            if row_t is None:
                await update.message.reply_text(
                    f"❌ کاربری با «{esc_md(ref)}» پیدا نکردم!\n"
                    f"💡 آیدی عددی، @یوزرنیم یا اسم ثبت‌شده رو بده.", parse_mode="Markdown")
                return
            t_id, t_name = row_t["user_id"], row_t["name"]
            if parts_o[0] == "کادو":
                gift_name = parts_o[1]
                if gift_name in OWNER_GIFTS:
                    gift = OWNER_GIFTS[gift_name]
                    add_coins(t_id, gift["coins"], league=False)
                    _g = load_owner_gifts(t_id); _g.append(gift_name); save_owner_gifts(t_id, _g)
                    await update.message.reply_text(
                        f"🎁 **کادو از راه دور!**\n{gift['emoji']} یک **{gift_name}** به {esc_md(t_name)} (آیدی `{t_id}`) هدیه شد!\n"
                        f"💰 ارزش: {gift['coins']:,} {CURRENCY_NAME}", parse_mode="Markdown")
                    return
            else:
                val = parts_o[1].translate(FA_DIGITS)
                if val.isdigit():
                    amt = int(val)
                    if parts_o[0] == "+سکه":
                        add_coins(t_id, amt, league=False)
                        u_t = get_user(t_id)
                        await update.message.reply_text(
                            f"✅ **{amt:,}** به {esc_md(t_name)} (آیدی `{t_id}`) اضافه شد!\n💳 موجودیش: {u_t['coins']:,}", parse_mode="Markdown")
                    else:
                        with closing(db_connect()) as db:
                            db.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (amt, t_id))
                            db.commit()
                        u_t = get_user(t_id)
                        await update.message.reply_text(
                            f"🔥 **{amt:,}** از {esc_md(t_name)} (آیدی `{t_id}`) کسر شد!\n💳 موجودیش: {u_t['coins']:,}", parse_mode="Markdown")
                    return
    
    # 🔄 ریست جدول هفتگی (اونر)
    if user.id == OWNER_ID and text in ["ریست هفتگی", "ریست جدول هفتگی", "ریست لیگ"]:
        await update.message.reply_text(
            "⚠️ **مطمئنی؟**\nامتیاز هفتگی **همه** صفر می‌شه و هفته از الان شروع می‌شه!\n(جایزه‌ای پرداخت نمی‌شه — ریست خشکه)",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ آره ریست کن", callback_data="panel_wreset_yes"),
                InlineKeyboardButton("❌ بیخیال", callback_data="panel_wreset_no")]]),
            parse_mode="Markdown")
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
            add_coins(target.id, gift["coins"], league=False)
            # 🎁 کادو به کلکسیونش هم اضافه می‌شه (قابل فروش با ۵۰٪)
            _g = load_owner_gifts(target.id); _g.append(gift_name); save_owner_gifts(target.id, _g)
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
                add_coins(target.id, amt, league=False)
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
                    "🐴 ۳ بار عدد معتبر وارد نکردی. هر وقت خواستی دوباره بازی بساز.",
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
# 9.3 🔘 هندلر دکمه‌های شیشه‌ای (callback)
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
    
    # ===== 💳 جواب ضامن وام =====
    if data in ["loan_yes", "loan_no"]:
        await loan_callback(update, context, query, "yes" if data == "loan_yes" else "no")
        return
    
    # ===== 💌 جواب درخواست جفت‌گیری (فقط طرف مقابل) =====
    if data in ["mate_yes", "mate_no"]:
        await mate_callback(update, context, query, "yes" if data == "mate_yes" else "no")
        return
    
    # ===== 🍾 جواب دعوت عرق‌خوری (فقط دعوت‌شده) =====
    if data.startswith("drink_yes_") or data.startswith("drink_no_"):
        ans = "yes" if data.startswith("drink_yes_") else "no"
        try:
            tid = int(data.rsplit("_", 1)[1])
        except ValueError:
            return
        await drink_callback(update, context, query, ans, tid)
        return
    
    # ===== 🔄 انتقام رالی (فقط بازنده می‌تونه بزنه) =====
    if data.startswith("rally_rm_"):
        try:
            _, _, loser_s, winner_s, bet_s = data.split("_")
            loser_id, winner_id, rbet = int(loser_s), int(winner_s), int(bet_s)
        except (ValueError, IndexError):
            return
        if user.id != loser_id:
            await query.answer("🔒 فقط بازنده می‌تونه انتقام بگیره! 😏", show_alert=True)
            return
        # پول هر دو چک و کم شه
        if not remove_coins(loser_id, rbet):
            await query.answer(f"❌ {rbet:,} نداری! برو پول جور کن بعد انتقام بگیر!", show_alert=True)
            return
        if not remove_coins(winner_id, rbet):
            add_coins(loser_id, rbet, league=False)
            await query.answer("❌ حریفت دیگه انقدر پول نداره!", show_alert=True)
            return
        await query.answer("🔥 انتقام شروع شد!")
        try:
            await query.edit_message_reply_markup(reply_markup=None)  # دکمه برداشته شه (دابل کلیک نشه)
        except Exception:
            pass
        await rally_run(context, loser_id, winner_id, rbet, [query.message.chat_id])
        return
    
    # ===== 📖 آموزش بازی (برای همه آزاد — پاپ‌آپ شخصی) =====
    if data.startswith("tut_"):
        gt = data[4:]
        tut = GAME_TUTORIALS.get(gt)
        if tut:
            await query.answer(tut, show_alert=True)
        else:
            await query.answer("📖 برای این بازی آموزشی نیست!")
        return
    
    # ===== 🧠 بخش خر دانا =====
    if data == "sec_dana":
        await query.answer()
        _day, used = _KD_USER_COUNT.get(user.id, ("", 0))
        if _day != _kd_today():
            used = 0
        await query.edit_message_text(
            "🧠 **خر دانا — دانای کل طویله!**\n"
            "_هر چی بپرسی جواب می‌ده... به سبک خرکی!_\n"
            "━━━━━━━━━━━━━━\n"
            f"💰 هر سوال: {KHAR_DANA_COST} {CURRENCY_NAME}\n"
            f"📊 سهم امروزت: {used} از {KHAR_DANA_USER_DAILY} سوال\n\n"
            "💬 **روش استفاده:**\n"
            "`خر جان امروز شانس دارم؟`\n"
            "`خر جان یه جوک بگو`\n\n"
            "👇 یا با یه کلیک بپرس:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎲 فال امروزم", callback_data="dana_ask_فال امروز من چیه؟"),
                 InlineKeyboardButton("😂 یه جوک بگو", callback_data="dana_ask_یه جوک خرکی بگو")],
                [InlineKeyboardButton("💡 نصیحت خرکی", callback_data="dana_ask_یه نصیحت خرکی بهم بکن")],
                [InlineKeyboardButton("🏠 منو", callback_data="home")]
            ]),
            parse_mode="Markdown")
        return
    
    if data.startswith("dana_ask_"):
        question = data[9:]
        await query.answer("🧠 دارم فکر می‌کنم...")
        shim = _QuickShim(query, context)
        await khar_dana_command(shim, context, question)
        return
    
    # ===== 🏇 بخش رالی =====
    if data == "sec_rally":
        await query.answer()
        await query.edit_message_text(rally_menu_text(user.id),
            reply_markup=rally_menu_keyboard(), parse_mode="Markdown")
        return
    
    if data == "rally_top":
        await query.answer()
        rows = rally_top()
        if not rows:
            msg_r = "🏇 **قهرمانان رالی**\n━━━━━━━━━━━━━━\n😴 هنوز هیچ رالی‌ای برگزار نشده!"
        else:
            msg_r = "🏇 **قهرمانان رالی خرستان**\n━━━━━━━━━━━━━━\n"
            for i, r in enumerate(rows, 1):
                medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
                msg_r += f"{medal} {esc_md(r['name'] or '؟')} — 🏆 {r['wins']} برد | 💀 {r['losses']} باخت\n"
        await query.edit_message_text(msg_r,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رالی", callback_data="sec_rally")]]),
            parse_mode="Markdown")
        return
    
    # ===== 🔒 قفل منو: هر منویی فقط برای کسی که بازش کرده =====
    # دکمه‌های اتاق بازی (ورود، خر بات، شروع، لغو) برای همه آزادن
    if not data.startswith("room_"):
        try:
            owner = menu_owner_of(query.message.chat_id, query.message.message_id)
        except Exception:
            owner = None
        if owner is not None and owner != user.id:
            await query.answer("🔒😉 این منو مال تو نیست! خودت یکی باز کن", show_alert=True)
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
        
        # 🗂️ بخش‌های پنل اونر
        sec = panel_sections(data)
        if sec:
            try:
                await query.edit_message_text(sec[0], reply_markup=sec[1], parse_mode="Markdown")
            except Exception:
                pass  # «بروزرسانی» با متن یکسان → Message is not modified
            return
        
        # 🔄 ریست جدول هفتگی
        if data == "panel_wreset_yes":
            with closing(db_connect()) as db:
                db.execute("DELETE FROM league")
                db.commit()
            set_setting("league_end", str(league_week_end_ts()))
            await query.edit_message_text(
                "✅ **جدول هفتگی ریست شد!**\nامتیاز همه صفر شد و هفته جدید از الان شروع شد.\n"
                "📢 اگه می‌خوای تو گروه‌ها اعلام کنی، بنویس: `اطلاعیه هفته جدید جدول هفتگی شروع شد!`",
                parse_mode="Markdown")
            return
        if data == "panel_wreset_no":
            await query.edit_message_text("❌ ریست لغو شد. جدول دست‌نخورده موند.")
            return
        
        # 🔒 کلیدهای سریع جوین اجباری
        if data == "panel_fj_on":
            if not force_join_targets():
                await query.answer("❌ اول کانال/گروه رو ثبت کن: «تنظیم کانال @X»", show_alert=True)
                return
            set_setting("force_join", "on")
            _MEMBER_CACHE.clear()
            sec = panel_sections("panel_sec_join")
            try:
                await query.edit_message_text(sec[0], reply_markup=sec[1], parse_mode="Markdown")
            except Exception:
                pass
            await query.answer("🔒 جوین اجباری روشن شد!")
            return
        if data == "panel_fj_off":
            set_setting("force_join", "off")
            sec = panel_sections("panel_sec_join")
            try:
                await query.edit_message_text(sec[0], reply_markup=sec[1], parse_mode="Markdown")
            except Exception:
                pass
            await query.answer("🔓 جوین اجباری خاموش شد!")
            return
        
        # 📚 بخش‌های آموزشی دستورات
        if data in PANEL_GUIDES:
            back = PANEL_GUIDE_BACK.get(data, "panel_main")
            await query.edit_message_text(
                PANEL_GUIDES[data],
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data=back)]]),
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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="panel_sec_stats")]]),
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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="panel_sec_backup")]]),
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
            "🏠 **منوی اصلی طویله خرستان**\n━━━━━━━━━━━━━━\nچی کار می‌خوای بکنی؟ 👇",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )
        return
    
    # ===== 🎰 راهنمای بازی‌های فوری =====
    if data == "instant_slot":
        await query.edit_message_text(
            "🎰 **اسلات خرستان**\n━━━━━━━━━━━━━━\n"
            "🎡 انیمیشن واقعی تلگرام می‌چرخه — نتیجه همونیه که می‌بینی!\n"
            "7️⃣7️⃣7️⃣ = جایزه **x20**! 💥\n"
            "🍇🍇🍇 = x10 | سه‌تایی دیگه = x6\n"
            "✌️ دوتایی = x2\n\n"
            f"💬 برای بازی بنویس: `اسلات 500`\n"
            f"(حداقل {MIN_BET})",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازی‌ها", callback_data="games_list")]]),
            parse_mode="Markdown")
        return
    
    
    # ===== لیست بازی‌ها =====
    if data == "games_list":
        await query.edit_message_text(
            "🎮 **انتخاب بازی:**\n\n"
            "👥 ۲ نفره: سنگ‌کاغذقیچی، دوز، شیر یا خط، پنالتی\n"
            "👥 تا ۶ نفر: بلک‌جک، پوکر\n"
            "👥 تا ۱۰ نفر: انفجار، تاس، دارت، بولینگ، بسکتبال، رولت، بالا/پایین، حدس عدد\n"
            "👥 تا ۵ نفر: مین‌روب",
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
            f"💬 مبلغ شرط رو وارد کن (عدد):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📖 آموزش این بازی", callback_data=f"tut_{game_type}")],
                [InlineKeyboardButton("🔙 لغو", callback_data="bet_cancel")]]),
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
        await query.answer("🤖🐴 خر بات وارد شد! عر عر!")
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
            add_coins(p, room.bet, league=False)
        room.finished = True
        cleanup_room(room_id)
        await query.edit_message_text("❌ اتاق لغو شد. شرط همه برگشت داده شد.", reply_markup=main_menu())
        return
    
    # ===== پروفایل =====
    # ===== 🏆 انتخاب جدول =====
    # ===== ⚡ منوی اکشن سریع =====
    if data in ["quick_daily", "quick_work", "quick_wheel", "quick_fortune", "quick_beg", "quick_heist"]:
        shim = _QuickShim(query, context)
        fn = {"quick_daily": daily_reward, "quick_work": work_command,
              "quick_wheel": wheel_command, "quick_fortune": fortune_command,
              "quick_beg": beg_command, "quick_heist": bank_heist_command}[data]
        await fn(shim, context)
        return
    
    # ===== 🗂️ بخش‌های منوی اصلی =====
    if data == "sec_games":
        await query.edit_message_text(sec_games_text(),
            reply_markup=sec_games_keyboard(), parse_mode="Markdown")
        return
    
    if data == "sec_income":
        await query.edit_message_text(sec_income_text(user.id),
            reply_markup=sec_income_keyboard(), parse_mode="Markdown")
        return
    
    if data == "sec_money":
        await query.edit_message_text(sec_money_text(user.id),
            reply_markup=sec_money_keyboard(), parse_mode="Markdown")
        return
    
    if data == "sec_crime":
        await query.edit_message_text(sec_crime_text(user.id),
            reply_markup=sec_crime_keyboard(), parse_mode="Markdown")
        return
    
    if data == "sec_donkey":
        await query.edit_message_text(sec_donkey_text(user.id),
            reply_markup=sec_donkey_keyboard(), parse_mode="Markdown")
        return
    
    if data == "sec_rank":
        await query.edit_message_text(sec_rank_text(user.id),
            reply_markup=sec_rank_keyboard(), parse_mode="Markdown")
        return
    
    if data == "sec_sounds":
        await query.edit_message_text(
            SOUNDS_LIST_TEXT,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بخش درآمد", callback_data="sec_income")]]),
            parse_mode="Markdown")
        return
    
    if data == "quick_donkey":
        await query.edit_message_text(
            donkey_art(user.id),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بخش خر", callback_data="sec_donkey")]]),
            parse_mode="Markdown")
        return
    
    if data == "crime_opium":
        if is_jailed(user.id):
            await query.answer("🚔 تو بازداشتی! چی می‌کشی؟!", show_alert=True)
            return
        last_op = int(get_setting(f"opium_last_{user.id}", "0") or 0)
        if int(time.time()) - last_op < OPIUM_COOLDOWN:
            rem = OPIUM_COOLDOWN - (int(time.time()) - last_op)
            await query.answer(f"💨 ساقی گفت: صبر کن دود قبلی بره هوا! {rem//60} دقیقه دیگه بیا.", show_alert=True)
            return
        await query.edit_message_text(opium_menu_text(user.id),
            reply_markup=opium_menu_keyboard(user.id), parse_mode="Markdown")
        return
    
    if data == "lb_total":
        await query.edit_message_text(
            total_leaderboard_text(user.id),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚡ جدول هفتگی", callback_data="lb_week"),
                                                InlineKeyboardButton("🏠 منو", callback_data="home")]]),
            parse_mode="Markdown")
        return
    
    if data == "lb_week":
        await query.edit_message_text(
            league_text(user.id),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏆 جدول کلی", callback_data="lb_total"),
                                                InlineKeyboardButton("🏠 منو", callback_data="home")]]),
            parse_mode="Markdown")
        return
    
    # ===== 💨 تریاک =====
    if data == "opium_no":
        await query.edit_message_text("🏃🐴✅ عاقلانه بود! پولت تو جیبت موند، سلامتیت سر جاش. آفرین خر عاقل!")
        return
    
    if data.startswith("opium_p_"):
        # 🚬 انتخاب پک: light / full / heavy
        pack_key = data[8:]
        if pack_key not in OPIUM_PACKS:
            return
        if is_jailed(user.id):
            await query.answer("🚔 تو بازداشتی! چی می‌کشی؟!", show_alert=True)
            return
        last_op = int(get_setting(f"opium_last_{user.id}", "0") or 0)
        if int(time.time()) - last_op < OPIUM_COOLDOWN:
            await query.answer(f"💨 صبر کن دود قبلی بره هوا! {(OPIUM_COOLDOWN-(int(time.time())-last_op))//60} دقیقه دیگه", show_alert=True)
            return
        dkey, dealer = opium_current_dealer(user.id)
        price = opium_pack_price(pack_key, dealer)
        # 👴 عمو یونجه: شانس نسیه!
        on_credit = False
        if not remove_coins(user.id, price):
            if dkey == "amoo" and random.random() < dealer.get("credit_chance", 0):
                on_credit = True
            else:
                u = get_user(user.id)
                await query.answer(f"❌ {price:,} لازمه! داری: {u['coins']:,}", show_alert=True)
                return
        await query.answer("💨 ...")
        if on_credit:
            try:
                await query.edit_message_text(
                    "👴 عمو یونجه: «پول نداری؟ عیب نداره... این دفعه **نسیه** ببر! ولی یادت باشه‌ها!» 🥹",
                    parse_mode="Markdown")
            except Exception:
                pass
            await asyncio.sleep(2)
        await opium_smoke_cinematic(query, context, user.id, user.first_name, pack_key, price)
        return
    
    # ===== 🏦 پنل بانک =====
    if data == "bankp_home":
        await query.edit_message_text(bank_panel_text(user.id),
            reply_markup=bank_panel_keyboard(user.id), parse_mode="Markdown")
        return
    
    if data == "bankp_claim":
        u = get_user(user.id)
        interest, ready = bank_pending_interest(user.id)
        if not ready or interest <= 0:
            await query.answer("⏳ سودت هنوز نرسیده!", show_alert=True)
            return
        add_coins(user.id, interest)
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET bank_last = ? WHERE user_id = ?", (int(time.time()), user.id))
            db.commit()
        await query.answer(f"💹 +{interest:,} {CURRENCY_NAME} سود گرفتی!", show_alert=True)
        await query.edit_message_text(bank_panel_text(user.id),
            reply_markup=bank_panel_keyboard(user.id), parse_mode="Markdown")
        return
    
    if data == "bankp_dep":
        await query.answer()
        await query.edit_message_text(
            bank_panel_text(user.id) + "\n\n💰 **برای واریز بنویس:** `واریز 1000`",
            reply_markup=bank_panel_keyboard(user.id), parse_mode="Markdown")
        return
    
    if data == "bankp_wd_all":
        u = get_user(user.id)
        balance = u["bank_balance"] or 0
        if balance <= 0:
            await query.answer("🏦 حسابت خالیه!", show_alert=True)
            return
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET bank_balance = 0 WHERE user_id = ?", (user.id,))
            db.commit()
        add_coins(user.id, balance, league=False)
        await query.answer(f"💵 {balance:,} {CURRENCY_NAME} اومد تو جیبت!", show_alert=True)
        await query.edit_message_text(bank_panel_text(user.id),
            reply_markup=bank_panel_keyboard(user.id), parse_mode="Markdown")
        return
    
    if data == "bankp_repay":
        loan = get_loan(user.id)
        if loan <= 0:
            await query.answer("✅ بدهی نداری!", show_alert=True)
            return
        u = get_user(user.id)
        pay = min(loan, u["coins"] or 0)
        if pay <= 0:
            await query.answer(f"❌ پول نقد نداری! بدهی: {loan:,}", show_alert=True)
            return
        remove_coins(user.id, pay)
        if loan - pay <= 0:
            clear_loan(user.id)
            await query.answer(f"🎉 وام کامل تسویه شد! (-{pay:,})", show_alert=True)
        else:
            set_loan(user.id, loan - pay)
            await query.answer(f"💸 {pay:,} پرداخت شد. باقی: {get_loan(user.id):,}", show_alert=True)
        await query.edit_message_text(bank_panel_text(user.id),
            reply_markup=bank_panel_keyboard(user.id), parse_mode="Markdown")
        return
    
    # ===== 🛡️ پنل بیمه =====
    if data == "insp_home":
        await query.edit_message_text(insurance_panel_text(user.id),
            reply_markup=insurance_panel_keyboard(user.id), parse_mode="Markdown")
        return
    
    if data == "insp_buy":
        if has_insurance(user.id):
            await query.answer("🛡️ همین الانم بیمه‌ای!", show_alert=True)
            return
        if not remove_coins(user.id, INSURANCE_COST):
            u = get_user(user.id)
            await query.answer(f"❌ {INSURANCE_COST:,} لازمه! داری: {u['coins']:,}", show_alert=True)
            return
        until = int(time.time()) + INSURANCE_DAYS * 86400
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET insurance_until = ? WHERE user_id = ?", (until, user.id))
            db.commit()
        await query.answer(f"🛡️🎉 بیمه شدی! {INSURANCE_DAYS} روز تحت پوششی", show_alert=True)
        await query.edit_message_text(insurance_panel_text(user.id),
            reply_markup=insurance_panel_keyboard(user.id), parse_mode="Markdown")
        return
    
    # ===== 🐣 برداشت سود کره‌خرها =====
    if data == "babe_claim":
        got = babies_claim(user.id)
        if got > 0:
            await query.answer(f"💰🎉 +{got:,} {CURRENCY_NAME} سود کره‌خرها!", show_alert=True)
        else:
            await query.answer("⏳ سودت هنوز نرسیده! روزی یه بار می‌تونی برداری.", show_alert=True)
        try:
            await query.edit_message_text(baby_panel_text(user.id),
                reply_markup=baby_panel_keyboard(user.id), parse_mode="Markdown")
        except Exception:
            pass
        return
    
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
            await query.answer("🏆🦄 فول‌لِوِله! بالاتر نداریم", show_alert=True)
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
                "SELECT user_id, name, coins, level, coins + COALESCE(bank_balance,0) as wealth FROM users ORDER BY wealth DESC LIMIT 10"
            ).fetchall()
            user_row = db.execute(
                "SELECT COUNT(*) + 1 as rank FROM users WHERE coins + COALESCE(bank_balance,0) > (SELECT coins + COALESCE(bank_balance,0) FROM users WHERE user_id = ?)",
                (user.id,)
            ).fetchone()
        
        if not rows:
            await query.edit_message_text("❌ هنوز کسی ثبت نشده!")
            return
        
        msg = "🏆 **جدول ثروتمندان طویله**\n━━━━━━━━━━━━━━\n"
        for i, row in enumerate(rows, 1):
            medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
            title = get_title_by_level(row["level"])
            msg += f"{medal} {title} {esc_md(row['name'])} — {row['wealth']:,}\n"
        
        if user_row and user_row["rank"]:
            msg += f"\n━━━━━━━━━━━━━━\n👤 رتبه شما: #{user_row['rank']}"
        
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
    
    # ===== 💰 فروش وسایل (لیست) =====
    if data == "sell_menu":
        owned = load_donkey_items(user.id)
        gifts = load_owner_gifts(user.id)
        if not owned and not gifts:
            await query.answer("🎒 هیچ وسیله یا کادویی نداری که بفروشی!", show_alert=True)
            return
        buttons = []
        for it in owned[:30]:
            cat, idata = find_shop_item(it)
            if not idata: continue
            sell_p = idata["price"] // 2
            buttons.append([InlineKeyboardButton(
                f"{idata['emoji']} {it} → 💰 {sell_p:,}",
                callback_data=f"sellask_{it}")])
        for g in set(gifts):
            if g in OWNER_GIFTS:
                gd_ = OWNER_GIFTS[g]
                cnt = gifts.count(g)
                buttons.append([InlineKeyboardButton(
                    f"{gd_['emoji']} کادو {g}{f' ×{cnt}' if cnt > 1 else ''} → 💰 {gd_['coins']//2:,}",
                    callback_data=f"sellgift_{g}")])
        buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="shop")])
        await query.edit_message_text(
            "💰 **فروش وسایل و کادوها**\n_نصف قیمت خرید برمی‌گرده — فکرات رو بکن!_\n━━━━━━━━━━━━━━\n👇 چی می‌فروشی؟",
            reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        return
    
    # ===== تایید فروش وسیله =====
    if data.startswith("sellask_"):
        item_name = data[8:]
        cat, idata = find_shop_item(item_name)
        if not idata or item_name not in load_donkey_items(user.id):
            await query.answer("❌ این وسیله رو نداری!", show_alert=True)
            return
        sell_p = idata["price"] // 2
        await query.edit_message_text(
            f"🤔 **مطمئنی؟**\n{idata['emoji']} **{item_name}** رو به **{sell_p:,}** {CURRENCY_NAME} می‌فروشی؟\n"
            f"(قیمت خریدش {idata['price']:,} بود)",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ آره بفروش", callback_data=f"sellok_{item_name}"),
                InlineKeyboardButton("❌ پشیمون شدم", callback_data="sell_menu")]]),
            parse_mode="Markdown")
        return
    
    if data.startswith("sellok_"):
        item_name = data[7:]
        cat, idata = find_shop_item(item_name)
        owned = load_donkey_items(user.id)
        if not idata or item_name not in owned:
            await query.answer("❌ این وسیله رو نداری!", show_alert=True)
            return
        owned.remove(item_name)
        save_donkey_items(user.id, owned)
        # اگه تنش بود، دربیار
        col = SHOP_COL_MAP.get(cat)
        if col:
            with closing(db_connect()) as db:
                row = db.execute(f"SELECT {col} AS worn FROM donkeys WHERE user_id = ?", (user.id,)).fetchone()
                if row and row["worn"] == item_name:
                    db.execute(f"UPDATE donkeys SET {col} = '' WHERE user_id = ?", (user.id,))
                db.commit()
        sell_p = idata["price"] // 2
        add_coins(user.id, sell_p, league=False)  # پول فروش امتیاز هفتگی نمی‌ده
        await query.answer(f"💰 فروخته شد! +{sell_p:,}", show_alert=True)
        await query.edit_message_text(
            f"✅ **فروش انجام شد!**\n{idata['emoji']} {item_name} → **+{sell_p:,}** {CURRENCY_NAME}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💰 فروش بیشتر", callback_data="sell_menu"),
                InlineKeyboardButton("🏠 منو", callback_data="home")]]),
            parse_mode="Markdown")
        return
    
    # ===== فروش کادو =====
    if data.startswith("sellgift_"):
        g = data[9:]
        gifts = load_owner_gifts(user.id)
        if g not in gifts or g not in OWNER_GIFTS:
            await query.answer("❌ این کادو رو نداری!", show_alert=True)
            return
        gifts.remove(g)
        save_owner_gifts(user.id, gifts)
        sell_p = OWNER_GIFTS[g]["coins"] // 2
        add_coins(user.id, sell_p, league=False)
        await query.answer(f"💰 کادو فروخته شد! +{sell_p:,}", show_alert=True)
        await query.edit_message_text(
            f"✅ **کادو فروخته شد!**\n{OWNER_GIFTS[g]['emoji']} {g} → **+{sell_p:,}** {CURRENCY_NAME}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💰 فروش بیشتر", callback_data="sell_menu"),
                InlineKeyboardButton("🏠 منو", callback_data="home")]]),
            parse_mode="Markdown")
        return
    
    # ===== دسته‌بندی فروشگاه =====
    if data.startswith("shop_"):
        category = data[5:]
        if category not in SHOP_ITEMS:
            return
        
        cat_data = SHOP_ITEMS[category]
        owned = load_donkey_items(user.id)
        buttons = []
        for item_name, item_data in cat_data["items"].items():
            tier = item_tier(item_data["price"])
            mark = "✅ " if item_name in owned else ""
            buttons.append([InlineKeyboardButton(
                f"{mark}{tier} {item_data['emoji']} {item_name} — {item_data['price']:,}",
                callback_data=f"buy_{category}_{item_name}"
            )])
        buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="shop")])
        
        await query.edit_message_text(
            f"🏪 **{cat_data['name']}**\n"
            f"_{cat_data['buff_name']}: {cat_data['buff_unit']} + ⚡ قدرت خر برای رالی!_\n"
            f"━━━━━━━━━━━━━━\n"
            f"🟢 معمولی | 🔵 خوب | 🟣 کمیاب | 🟠 حماسی | 🔴 افسانه‌ای\n"
            f"✅ = خریدی | خریدی؟ دوباره بزن تا بپوشه!",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown"
        )
        return
    
    # ===== خرید / پوشیدن =====
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
        
        owned = load_donkey_items(user.id)
        col = SHOP_COL_MAP.get(category)
        
        # 🎒 قبلاً خریده → فقط بپوشه (مجانی!)
        if item_name in owned:
            with closing(db_connect()) as db:
                db.execute(f"UPDATE donkeys SET {col} = ? WHERE user_id = ?", (item_name, user.id))
                db.commit()
            await query.answer(f"👕 {item_name} رو پوشید! (+{item_data['power']} قدرت)", show_alert=True)
            return
        
        if not remove_coins(user.id, price):
            await query.answer(f"❌ {price:,} {CURRENCY_NAME} ندارید!", show_alert=True)
            return
        
        owned.append(item_name)
        save_donkey_items(user.id, owned)
        with closing(db_connect()) as db:
            db.execute(f"UPDATE donkeys SET {col} = ? WHERE user_id = ?", (item_name, user.id))
            db.commit()
        
        await query.answer(f"✅ {item_name} خریداری و پوشیده شد!", show_alert=True)
        
        buffs = get_equipped_buffs(user.id)
        await query.edit_message_text(
            f"✅ **خرید موفق!**\n{item_data['emoji']} {item_name} روی خر شما قرار گرفت.\n"
            f"💰 هزینه: {price:,} {CURRENCY_NAME}\n"
            f"⚡ قدرت خر الان: **{buffs['power']}**\n"
            f"🎁 باف: {SHOP_ITEMS[category]['buff_name']} {SHOP_ITEMS[category]['buff_unit']} → **{item_data['buff']}**",
            reply_markup=shop_keyboard(),
            parse_mode="Markdown"
        )
        return


# ╔══════════════════════════════════════════════════════════╗
# ║                 فصل 10 🚀 خطا، نظافتچی، بکاپ و اجرا
# ╚══════════════════════════════════════════════════════════╝
# ============================================================
# 10.1 🚨 خطای سراسری + نظافتچی + بکاپ خودکار
# ============================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("❌ خطای هندل‌نشده:", exc_info=context.error)

async def auto_backup_job(context: ContextTypes.DEFAULT_TYPE):
    """💾 بکاپ خودکار هر ساعت — فایل به پی‌وی اونر ارسال می‌شه"""
    if not OWNER_ID:
        return
    try:
        data = export_db_json()
        if not data.get("users"):
            return  # دیتابیس خالیه، بکاپ بی‌فایده‌ست
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        import io
        f = io.BytesIO(payload)
        f.name = f"kharbot_auto_{time.strftime('%Y%m%d_%H%M')}.json"
        await context.bot.send_document(
            chat_id=OWNER_ID,
            document=f,
            caption=(f"💾 بکاپ خودکار ساعتی\n"
                     f"👥 {len(data['users'])} بازیکن | 💬 {len(data.get('chats', []))} چت\n"
                     f"🕐 {time.strftime('%Y-%m-%d %H:%M')}\n\n"
                     f"📥 بازیابی: همین فایل رو با کپشن «بازیابی» بفرست."),
            disable_notification=True  # 🔕 بی‌صدا که هر ساعت مزاحمت نشه
        )
        logger.info(f"💾 بکاپ خودکار ارسال شد ({len(data['users'])} کاربر)")
    except Exception as e:
        logger.error(f"❌ خطا در بکاپ خودکار: {e}")

async def janitor_job(context: ContextTypes.DEFAULT_TYPE):
    """🧹 نظافتچی دوره‌ای: هر دقیقه اتاق‌های گیرکرده رو پاک می‌کنه و به گروه خبر می‌ده"""
    now = time.time()
    # 🏆 پایان هفته لیگ؟
    try:
        if now > league_get_end():
            await league_settle(context)
    except Exception as e:
        logger.error(f"❌ خطا در بستن لیگ: {e}")
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
# 10.2 🚀 راه‌اندازی و اجرا
# ============================================================

def main():
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN تنظیم نشده!")
        return
    
    try:
        init_db()
        # 💸 برگشت پول وسیله‌های فروشگاه قدیمی (یه‌بارمصرف)
        migrate_old_shop_refund()
    except Exception as e:
        logger.error(f"❌ خطا در راه‌اندازی دیتابیس: {e}")
        return
    
    # 🚦 محدودکننده سرعت داخلی: قبل از اینکه تلگرام flood بگیره، خودمون ترمز می‌کنیم
    builder = Application.builder().token(BOT_TOKEN)
    try:
        from telegram.ext import AIORateLimiter
        builder = builder.rate_limiter(AIORateLimiter(
            overall_max_rate=25,       # حداکثر ۲۵ پیام در ثانیه (سقف تلگرام ۳۰)
            group_max_rate=18,         # حداکثر ~۱۸ پیام در دقیقه در هر گروه (سقف ۲۰)
            group_time_period=60,
            max_retries=3              # اگه flood خورد، خودش صبر و تکرار می‌کنه
        ))
        logger.info("🚦 Rate limiter فعال شد — ضد flood!")
    except ImportError:
        logger.warning("⚠️ AIORateLimiter نصب نیست! برای ضد flood نصب کن: "
                       "pip install 'python-telegram-bot[rate-limiter]'")
    app = builder.build()
    app.add_handler(MessageHandler(filters.TEXT, message_handler))
    app.add_handler(MessageHandler(filters.Dice.ALL, dice_roll_received))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_error_handler(error_handler)
    
    # 🧹 نظافتچی هر ۶۰ ثانیه (نیاز به python-telegram-bot[job-queue])
    if app.job_queue:
        app.job_queue.run_repeating(janitor_job, interval=60, first=60)
        # 💾 بکاپ خودکار هر ۱ ساعت (اولین بکاپ ۵ دقیقه بعد از استارت)
        app.job_queue.run_repeating(auto_backup_job, interval=3600, first=300)
        logger.info("🧹 نظافتچی دوره‌ای + 💾 بکاپ خودکار ساعتی فعال شد")
    else:
        logger.warning("⚠️ JobQueue نصب نیست — نظافت فقط موقع فعالیت کاربرا انجام می‌شه. "
                       "برای فعال‌سازی: pip install 'python-telegram-bot[job-queue]'")
    
    logger.info("✅ ربات خرستان راه‌اندازی شد!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
