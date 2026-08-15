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

# مسیر دیتابیس در /tmp (سرور فقط اینجا اجازه نوشتن دارد)
DB_FILE = "/tmp/kharbot.db"

MIN_BET = 10
START_COINS = 2500
MAX_PLAYERS = 10

CURRENCY_NAME = "تی‌تاپ"

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
            db.commit()
        logger.info(f"✅ دیتابیس در {DB_FILE} راه‌اندازی شد")
    except sqlite3.OperationalError as e:
        logger.error(f"❌ خطا در راه‌اندازی دیتابیس: {e}")
        raise

# ============================================================
# مدیریت کاربران
# ============================================================

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
    u = get_user(user_id)
    return esc_md(u["name"]) if u else "ناشناس"

def add_coins(user_id, amount):
    if amount <= 0: return False
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
        db.commit()
    update_level(user_id)
    return True

def remove_coins(user_id, amount):
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
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET wins = wins + 1 WHERE user_id = ?", (user_id,))
        db.commit()
    update_level(user_id)

def record_loss(user_id):
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
    babies = json.loads(u["baby_names"]) if u["baby_names"] else []
    
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
        msg += f"\n👶 **کره‌خرها:** {len(babies)} عدد\n"
        for i, baby in enumerate(babies[:3], 1):
            msg += f"{i}. {baby}\n"
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
    
    add_coins(user.id, reward)
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET last_daily = ? WHERE user_id = ?", (now, user.id))
        db.commit()
    
    await update.message.reply_text(
        f"🎁 **جایزه روزانه!**\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 {esc_md(user.first_name)} عزیز\n"
        f"💰 جایزه: **{reward}** {CURRENCY_NAME}"
        f"{bonus}\n"
        f"\n📅 فردا دوباره بیا! 🐴",
        parse_mode="Markdown"
    )

# ============================================================
# صدای خر
# ============================================================

SOUND_KEYWORDS = {
    "عر": {"sound": "عر عر عر", "desc": "صدای معمولی خر"},
    "عرعر": {"sound": "عر عر عر عر", "desc": "صدای پشت سر هم"},
    "عرر": {"sound": "عررررررر", "desc": "صدای کشیده"},
    "ترک": {"sound": "عر-عر-عر-عر (ترک!)", "desc": "صدای شکسته"},
    "تورک": {"sound": "عررررررررر (تورک!)", "desc": "صدای پیچیده"}
}

SOUND_COOLDOWN = 120
MIN_REWARD = 0
MAX_REWARD = 20

async def donkey_sound(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
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
            f"⏳ {minutes} دقیقه و {seconds} ثانیه صبر کن تا دوباره صدا بدی! 🐴"
        )
        return
    
    keyword = None
    for key in SOUND_KEYWORDS.keys():
        if key in text:
            keyword = key
            break
    
    if not keyword:
        return
    
    sound_info = SOUND_KEYWORDS[keyword]
    reward = random.randint(MIN_REWARD, MAX_REWARD)
    bonus = ""
    
    if random.random() < 0.05:
        reward = random.randint(20, 50)
        bonus = "\n🎉 **جایزه ویژه!**"
    
    if reward > 0:
        add_coins(user.id, reward)
    
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET last_sound = ? WHERE user_id = ?", (now, user.id))
        db.commit()
    
    await update.message.reply_text(
        f"🔊 **صدای خر!**\n"
        f"━━━━━━━━━━━━━━\n"
        f"🎤 {sound_info['sound']}\n"
        f"📝 {sound_info['desc']}\n"
        f"\n👤 {esc_md(user.first_name)} عر کشید! 🐴\n"
        f"💰 جایزه: **{reward}** {CURRENCY_NAME}"
        f"{bonus}",
        parse_mode="Markdown"
    )

# ============================================================
# جفت‌گیری
# ============================================================

MATE_COST = 500
MAX_BABIES = 5
MATE_COOLDOWN = 86400

async def mate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ روی پیام شخص مورد نظر **ریپلی (Reply)** بزن و سپس `جفت‌گیری` رو تایپ کن."
        )
        return
    
    target = update.message.reply_to_message.from_user
    target_id = target.id
    
    if user.id == target_id:
        await update.message.reply_text("❌ نمی‌تونی با خودت جفت‌گیری کنی! 😂")
        return
    
    ensure_user(target_id, target.first_name)
    u1 = get_user(user.id)
    u2 = get_user(target_id)
    
    if u1["level"] < 2:
        await update.message.reply_text(f"❌ {esc_md(user.first_name)} عزیز، سطح تو {u1['level']} است.\nبرای جفت‌گیری باید به **سطح ۲** برسی! 🐣", parse_mode="Markdown")
        return
    
    if u2["level"] < 2:
        await update.message.reply_text(f"❌ {esc_md(target.first_name)} عزیز، سطحش {u2['level']} است.\nبرای جفت‌گیری باید به **سطح ۲** برسه! 🐣", parse_mode="Markdown")
        return
    
    if u1["coins"] < MATE_COST:
        await update.message.reply_text(f"❌ {esc_md(user.first_name)} {MATE_COST} {CURRENCY_NAME} نداری! 💸")
        return
    if u2["coins"] < MATE_COST:
        await update.message.reply_text(f"❌ {esc_md(target.first_name)} {MATE_COST} {CURRENCY_NAME} نداره! 💸")
        return
    
    babies1 = json.loads(u1["baby_names"]) if u1["baby_names"] else []
    babies2 = json.loads(u2["baby_names"]) if u2["baby_names"] else []
    
    if len(babies1) >= MAX_BABIES:
        await update.message.reply_text(f"❌ {esc_md(user.first_name)} دیگه جا برای کره‌خر جدید نداری! (حداکثر {MAX_BABIES})")
        return
    if len(babies2) >= MAX_BABIES:
        await update.message.reply_text(f"❌ {esc_md(target.first_name)} دیگه جا برای کره‌خر جدید نداره! (حداکثر {MAX_BABIES})")
        return
    
    now = int(time.time())
    if now - u1["last_mate"] < MATE_COOLDOWN:
        remaining = (MATE_COOLDOWN - (now - u1["last_mate"])) // 3600
        await update.message.reply_text(f"⏳ {esc_md(user.first_name)} عزیز، {remaining} ساعت دیگه می‌تونی جفت‌گیری کنی!")
        return
    if now - u2["last_mate"] < MATE_COOLDOWN:
        remaining = (MATE_COOLDOWN - (now - u2["last_mate"])) // 3600
        await update.message.reply_text(f"⏳ {esc_md(target.first_name)} عزیز، {remaining} ساعت دیگه می‌تونه جفت‌گیری کنه!")
        return
    
    remove_coins(user.id, MATE_COST)
    remove_coins(target_id, MATE_COST)
    
    baby_names = ["🐣 کره‌خر کوچولو", "🐣 کره‌خر نازنین", "🐣 کره‌خر خوشگل", "🐣 کره‌خر بازیگوش", "🐣 کره‌خر شیطون"]
    baby_name = random.choice(baby_names)
    
    babies1.append(baby_name)
    babies2.append(baby_name)
    
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET baby_names = ?, babies = babies + 1, last_mate = ? WHERE user_id = ?",
                  (json.dumps(babies1), now, user.id))
        db.execute("UPDATE users SET baby_names = ?, babies = babies + 1, last_mate = ? WHERE user_id = ?",
                  (json.dumps(babies2), now, target_id))
        db.commit()
    
    await update.message.reply_text(
        f"🎉 **تبریک! جفت‌گیری موفق!**\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👫 {esc_md(user.first_name)} ❤️ {esc_md(target.first_name)}\n\n"
        f"🐣 **کره‌خر متولد شد:** {baby_name}\n"
        f"👶 تعداد کره‌خرهای {esc_md(user.first_name)}: {len(babies1)}\n"
        f"👶 تعداد کره‌خرهای {esc_md(target.first_name)}: {len(babies2)}\n\n"
        f"💸 هزینه: {MATE_COST} {CURRENCY_NAME} از هر نفر",
        parse_mode="Markdown"
    )

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
    "hilo": "🔼🔽 حدس بالا/پایین"
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
    "hilo": 10
}

# بازی‌هایی که دقیقاً ۲ نفره هستند
TWO_PLAYER_GAMES = {"rps", "ttt", "coinflip"}

# ============================================================
# مدیریت اتاق‌ها
# ============================================================

ACTIVE_ROOMS = {}
PLAYER_IN_GAME = {}
ROOM_TTL = 3600          # اتاق منتظر، بعد از یک ساعت پاک می‌شود
STARTED_TTL = 1800       # بازی گیرکرده، بعد از نیم ساعت پاک و شرط برگردانده می‌شود
_ROOM_COUNTER = 0

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

    def add_player(self, user_id: int) -> bool:
        if len(self.players) >= self.max_players:
            return False
        if user_id in self.players:
            return False
        self.players.append(user_id)
        return True

    def pot(self) -> int:
        return self.bet * len(self.players)

def purge_stale_rooms():
    """اتاق‌های رهاشده را پاک می‌کند و شرط بازیکنان را برمی‌گرداند"""
    now = time.time()
    for rid in list(ACTIVE_ROOMS.keys()):
        room = ACTIVE_ROOMS.get(rid)
        if not room:
            continue
        ttl = STARTED_TTL if room.started else ROOM_TTL
        if now - room.created_at > ttl:
            if not room.finished:
                for p in room.players:
                    # اگر در انفجار قبلاً برداشت کرده، دیگر پولی طلبکار نیست
                    if room.game_type == "crash" and p in room.game_data.get("cashed", {}):
                        continue
                    add_coins(p, room.bet)
            for p in room.players:
                if PLAYER_IN_GAME.get(p) == rid:
                    PLAYER_IN_GAME.pop(p, None)
            ACTIVE_ROOMS.pop(rid, None)
            logger.info(f"🧹 اتاق قدیمی {rid} پاک شد")

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
        [InlineKeyboardButton("🏆 جدول", callback_data="leaderboard")]
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
        if len(room.players) >= 2:
            buttons.append([InlineKeyboardButton("▶️ شروع بازی", callback_data=f"room_start_{room.room_id}")])
        buttons.append([InlineKeyboardButton("❌ لغو", callback_data=f"room_cancel_{room.room_id}")])
    return InlineKeyboardMarkup(buttons)

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
    gt = room.game_type
    if gt == "rps":
        await rps_begin(room, context)
    elif gt == "ttt":
        await ttt_begin(room, context)
    elif gt == "coinflip":
        await coinflip_run(room, context)
    elif gt == "dice":
        await dice_run(room, context)
    elif gt == "roulette":
        await roulette_run(room, context)
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
        return
    
    if all(gd["board"]):
        for p in room.players:
            add_coins(p, room.bet)
        await finish_game(room, context,
            f"❌⭕ **دوز — پایان**\n━━━━━━━━━━━━━━\n"
            f"🤝 مساوی شد! شرط هر دو نفر برگشت داده شد.")
        return
    
    gd["turn"] = 1 - gd["turn"]
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

async def dice_run(room, context):
    await edit_room_msg(room, context, "🎲 همه تاس می‌ریزند... 🌀")
    await asyncio.sleep(2)
    
    rolls = {}
    for p in room.players:
        rolls[p] = (random.randint(1, 6), random.randint(1, 6))
    
    best = max(sum(r) for r in rolls.values())
    winners = [p for p, r in rolls.items() if sum(r) == best]
    
    dice_emoji = ["", "⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]
    lines = []
    for p, (d1, d2) in sorted(rolls.items(), key=lambda x: -sum(x[1])):
        mark = "🏆" if p in winners else "▫️"
        lines.append(f"{mark} {uname(p)}: {dice_emoji[d1]}{dice_emoji[d2]} = **{d1+d2}**")
    
    share = room.pot() // len(winners)
    for w in winners:
        add_coins(w, share)
        record_win(w)
    for p in room.players:
        if p not in winners:
            record_loss(p)
    
    win_names = "، ".join(uname(w) for w in winners)
    await finish_game(room, context,
        f"🎲 **تاس — نتیجه**\n━━━━━━━━━━━━━━\n" + "\n".join(lines) +
        f"\n\n🏆 برنده: **{win_names}**\n💰 جایزه هر نفر: {share} {CURRENCY_NAME}")

# ------------------------------------------------------------
# 🔫 رولت روسی (۲ تا ۱۰ نفره)
# ------------------------------------------------------------

async def roulette_run(room, context):
    alive = room.players[:]
    random.shuffle(alive)
    round_no = 0
    
    while len(alive) > 1:
        round_no += 1
        victim = random.choice(alive)
        await edit_room_msg(
            room, context,
            f"🔫 **رولت روسی — دور {round_no}**\n━━━━━━━━━━━━━━\n"
            f"👥 زنده‌ها: {len(alive)}\n"
            f"😰 {uname(victim)} هفت‌تیر رو گرفت روی شقیقه‌اش...\n\n🌀 چرخش استوانه..."
        )
        await asyncio.sleep(2)
        
        if random.randint(1, 6) <= 2:  # شانس شلیک
            alive.remove(victim)
            await edit_room_msg(
                room, context,
                f"🔫 **رولت روسی — دور {round_no}**\n━━━━━━━━━━━━━━\n"
                f"💥 **بنگ!** {uname(victim)} حذف شد! ☠️\n"
                f"👥 باقی‌مانده: {len(alive)} نفر"
            )
        else:
            await edit_room_msg(
                room, context,
                f"🔫 **رولت روسی — دور {round_no}**\n━━━━━━━━━━━━━━\n"
                f"😮‍💨 *کلیک...* {uname(victim)} زنده موند!\n"
                f"👥 زنده‌ها: {len(alive)} نفر"
            )
        await asyncio.sleep(1.5)
    
    winner = alive[0]
    add_coins(winner, room.pot())
    record_win(winner)
    for p in room.players:
        if p != winner:
            record_loss(p)
    
    await finish_game(room, context,
        f"🔫 **رولت روسی — پایان**\n━━━━━━━━━━━━━━\n"
        f"🏆 آخرین بازمانده: **{uname(winner)}**\n"
        f"💰 جایزه: {room.pot()} {CURRENCY_NAME}")

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
    await edit_room_msg(room, context, bj_status_text(room), bj_keyboard(room))

async def bj_next_turn(room, context):
    gd = room.game_data
    # پیدا کردن بازیکن بعدی که هنوز تمام نکرده
    while gd["idx"] < len(room.players) and gd["done"].get(room.players[gd["idx"]]):
        gd["idx"] += 1
    
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

# ============================================================
# هندلر پیام‌ها
# ============================================================

HELP_TEXT = (
    "🫏 **راهنمای طویله خرستان**\n"
    "━━━━━━━━━━━━━━\n"
    "🎮 **بازی‌های گروهی** (از منو → بازی‌ها):\n"
    "✊ سنگ‌کاغذقیچی، ❌⭕ دوز، 🪙 شیر یا خط (۲ نفره)\n"
    "🃏 بلک‌جک، 🎰 پوکر (تا ۶ نفر)\n"
    "💥 انفجار، 🎲 تاس، 🔫 رولت روسی، 🔼 بالا/پایین (تا ۱۰ نفر)\n\n"
    "🎰 **بازی‌های فوری** (تایپ کن):\n"
    "`اسلات 100` — اسلات ماشین\n"
    "`دوبل 100` — دوبل یا هیچی\n\n"
    "💬 **دستورات متنی:**\n"
    "روزانه — جایزه روزانه 🎁\n"
    "پروفایل — مشخصات تو 👤\n"
    "سکه — موجودی 💰\n"
    "جدول — ثروتمندان 🏆\n"
    "عر — صدای خر بده و جایزه بگیر 🔊\n"
    "جفت‌گیری (با ریپلی) — کره‌خر دار شو ❤️"
)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # محافظت در برابر پیام‌های ویرایش‌شده / پست کانال
    if not update.message or not update.message.text or not update.effective_user:
        return
    user = update.effective_user
    text = update.message.text.strip()
    
    ensure_user(user.id, user.first_name)
    
    u_data = get_user(user.id)
    if u_data and u_data["is_banned"] == 1:
        await update.message.reply_text("🚫 شما بن شده‌اید!")
        return
    
    # ===== شروع =====
    if text.startswith("/start"):
        await update.message.reply_text(
            "🫏 **به طویله خرستان خوش آمدید!**\n\n"
            "با ربات ما می‌توانید:\n"
            "• 🎮 ۹ بازی گروهی انجام دهید\n"
            "• 🎰 اسلات و دوبل بازی کنید\n"
            "• 🏆 با دوستان مسابقه دهید\n"
            "• 🎁 جایزه روزانه بگیرید\n"
            "• 🔊 صدای خر بدهید و جایزه بگیرید\n"
            "• ❤️ جفت‌گیری کنید و کره‌خر داشته باشید\n"
            "• 🎀 خر خود را تزئین کنید\n\n"
            "برای راهنما بنویس: **راهنما**",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )
        return
    
    # ===== راهنما =====
    if text in ["راهنما", "help", "/help", "کمک"]:
        await update.message.reply_text(HELP_TEXT, reply_markup=main_menu(), parse_mode="Markdown")
        return
    
    # ===== جایزه روزانه =====
    if text in ["روزانه", "daily", "جایزه روزانه"]:
        await daily_reward(update, context)
        return
    
    # ===== جفت‌گیری =====
    if text == "جفت‌گیری":
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
            msg += f"{medal} {title} {esc_md(row['name'])} — {row['coins']:,} {CURRENCY_NAME} (سطح {row['level']})\n"
        
        if user_row and user_row["rank"]:
            msg += f"\n━━━━━━━━━━━━━━━━\n👤 رتبه شما: #{user_row['rank']}"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
    
    # ===== صدای خر =====
    if text in ["عر", "عرعر", "عرر", "ترک", "تورک"]:
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
        if cmd in ["/addcoin", "سکه", "+سکه"] and len(parts) > 1:
            try:
                amt = int(parts[1].translate(FA_DIGITS))
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
        normalized = text.translate(FA_DIGITS)
        if normalized.isdigit():
            bet = int(normalized)
            if bet < MIN_BET:
                await update.message.reply_text(f"❌ حداقل شرط {MIN_BET} {CURRENCY_NAME} است!")
                return
            
            u = get_user(user.id)
            if u["coins"] < bet:
                await update.message.reply_text(f"❌ پول کافی ندارید! موجودی: {u['coins']:,} {CURRENCY_NAME}")
                return
            
            game_type = context.user_data.get("temp_game")
            if not game_type:
                context.user_data["awaiting_bet"] = False
                await update.message.reply_text("❌ خطا! دوباره از منو بازی رو انتخاب کن.")
                return
            
            if user.id in PLAYER_IN_GAME:
                context.user_data["awaiting_bet"] = False
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
            
            context.user_data["awaiting_bet"] = False
            context.user_data["temp_game"] = None
            
        else:
            await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید!")
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
    
    await query.answer()
    
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
        
        if user.id in PLAYER_IN_GAME:
            await query.answer("⚠️ شما در یک بازی دیگر هستید!", show_alert=True)
            return
        
        context.user_data["temp_game"] = game_type
        context.user_data["awaiting_bet"] = True
        
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
        if user.id in PLAYER_IN_GAME:
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
            msg += f"{medal} {title} {esc_md(row['name'])} — {row['coins']:,} {CURRENCY_NAME} (سطح {row['level']})\n"
        
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
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_error_handler(error_handler)
    
    logger.info("✅ ربات خرستان راه‌اندازی شد!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
