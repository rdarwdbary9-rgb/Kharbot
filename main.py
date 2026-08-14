#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import random
import sqlite3
import logging
import json
from contextlib import closing
from dataclasses import dataclass, field

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# ============================================================
# تنظیمات اولیه
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# مسیر دیتابیس در /tmp
DB_FILE = "/tmp/kharbot.db"

MIN_BET = 10
START_COINS = 2500
MAX_PLAYERS = 10

CURRENCY_NAME = "تی‌تاپ"

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("KHARBOT")

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
        logger.info("✅ دیتابیس در /tmp/kharbot.db راه‌اندازی شد")
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
        f"{title} 👤 **پروفایل {u['name']}**\n"
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
    
    last_daily = u.get("last_daily", 0)
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
        f"👤 {user.first_name} عزیز\n"
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
    
    last_sound = u.get("last_sound", 0)
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
        f"\n👤 {user.first_name} عر کشید! 🐴\n"
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
        await update.message.reply_text(f"❌ {user.first_name} عزیز، سطح تو {u1['level']} است.\nبرای جفت‌گیری باید به **سطح ۲** برسی! 🐣")
        return
    
    if u2["level"] < 2:
        await update.message.reply_text(f"❌ {target.first_name} عزیز، سطحش {u2['level']} است.\nبرای جفت‌گیری باید به **سطح ۲** برسه! 🐣")
        return
    
    if u1["coins"] < MATE_COST:
        await update.message.reply_text(f"❌ {user.first_name} {MATE_COST} {CURRENCY_NAME} نداری! 💸")
        return
    if u2["coins"] < MATE_COST:
        await update.message.reply_text(f"❌ {target.first_name} {MATE_COST} {CURRENCY_NAME} نداره! 💸")
        return
    
    babies1 = json.loads(u1["baby_names"]) if u1["baby_names"] else []
    babies2 = json.loads(u2["baby_names"]) if u2["baby_names"] else []
    
    if len(babies1) >= MAX_BABIES:
        await update.message.reply_text(f"❌ {user.first_name} دیگه جا برای کره‌خر جدید نداری! (حداکثر {MAX_BABIES})")
        return
    if len(babies2) >= MAX_BABIES:
        await update.message.reply_text(f"❌ {target.first_name} دیگه جا برای کره‌خر جدید نداره! (حداکثر {MAX_BABIES})")
        return
    
    now = int(time.time())
    if now - u1["last_mate"] < MATE_COOLDOWN:
        remaining = (MATE_COOLDOWN - (now - u1["last_mate"])) // 3600
        await update.message.reply_text(f"⏳ {user.first_name} عزیز، {remaining} ساعت دیگه می‌تونی جفت‌گیری کنی!")
        return
    if now - u2["last_mate"] < MATE_COOLDOWN:
        remaining = (MATE_COOLDOWN - (now - u2["last_mate"])) // 3600
        await update.message.reply_text(f"⏳ {target.first_name} عزیز، {remaining} ساعت دیگه می‌تونه جفت‌گیری کنه!")
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
        f"👫 {user.first_name} ❤️ {target.first_name}\n\n"
        f"🐣 **کره‌خر متولد شد:** {baby_name}\n"
        f"👶 تعداد کره‌خرهای {user.first_name}: {len(babies1)}\n"
        f"👶 تعداد کره‌خرهای {target.first_name}: {len(babies2)}\n\n"
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
    "roulette": "🔫 رولت روسی"
}

GAME_MAX_PLAYERS = {
    "rps": 2,
    "blackjack": 6,
    "crash": 10,
    "poker": 6,
    "ttt": 2,
    "dice": 10,
    "roulette": 10
}

# ============================================================
# مدیریت اتاق‌ها
# ============================================================

ACTIVE_ROOMS = {}
PLAYER_IN_GAME = {}

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

def get_room(room_id: str):
    return ACTIVE_ROOMS.get(room_id)

def cleanup_room(room_id: str):
    room = ACTIVE_ROOMS.pop(room_id, None)
    if room:
        for p in room.players:
            PLAYER_IN_GAME.pop(p, None)

def create_room(chat_id: int, game_type: str, creator_id: int, bet: int) -> GameRoom:
    room_id = f"{chat_id}_{int(time.time())}"
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
        u = get_user(p)
        names.append(f"{len(names)+1}. {u['name'] if u else 'ناشناس'}")
    
    text = (
        f"🎮 **{GAME_NAMES[room.game_type]}**\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 شرط: {room.bet} {CURRENCY_NAME}\n"
        f"👥 بازیکنان ({len(room.players)}/{room.max_players}):\n"
        f"{chr(10).join(names)}\n"
    )
    
    if not room.started:
        text += "\n⏳ منتظر ورود بازیکنان..."
    
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
    for key, name in GAME_NAMES.items():
        buttons.append([InlineKeyboardButton(name, callback_data=f"game_{key}")])
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
# هندلر پیام‌ها
# ============================================================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    
    ensure_user(user.id, user.first_name)
    
    u_data = get_user(user.id)
    if u_data and u_data["is_banned"] == 1:
        await update.message.reply_text("🚫 شما بن شده‌اید!")
        return
    
    # ============================================================
    # دستورات فارسی - اولویت اول
    # ============================================================
    
    # ===== شروع =====
    if text.startswith("/start"):
        await update.message.reply_text(
            "🫏 **به طویله خرستان خوش آمدید!**\n\n"
            "با ربات ما می‌توانید:\n"
            "• 🎮 ۷ بازی مختلف انجام دهید\n"
            "• 🏆 با دوستان مسابقه دهید\n"
            "• 🎁 جایزه روزانه بگیرید\n"
            "• 🔊 صدای خر بدهید و جایزه بگیرید\n"
            "• ❤️ جفت‌گیری کنید و کره‌خر داشته باشید\n"
            "• 🎀 خر خود را با وسایل مختلف تزئین کنید\n\n"
            "از منو استفاده کنید:",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )
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
    
    # ===== سکه =====
    if text in ["سکه", "coins", "تی‌تاپ"]:
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
        
        if not rows:
            await update.message.reply_text("❌ هنوز کسی ثبت نشده!")
            return
        
        msg = "🏆 **جدول ثروتمندان طویله**\n━━━━━━━━━━━━━━━━\n"
        for i, row in enumerate(rows, 1):
            medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
            title = get_title_by_level(row["level"])
            msg += f"{medal} {title} {row['name']} — {row['coins']:,} {CURRENCY_NAME} (سطح {row['level']})\n"
        
        user_row = db.execute(
            "SELECT COUNT(*) + 1 as rank FROM users WHERE coins > (SELECT coins FROM users WHERE user_id = ?)",
            (user.id,)
        ).fetchone()
        
        if user_row and user_row["rank"]:
            msg += f"\n━━━━━━━━━━━━━━━━\n👤 رتبه شما: #{user_row['rank']}"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        return
    
    # ===== صدای خر =====
    if text in ["عر", "عرعر", "عرر", "ترک", "تورک"]:
        await donkey_sound(update, context)
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
            await update.message.reply_text(f"✅ {target.first_name} بن شد!")
            return
        if cmd in ["/unban", "انبن"]:
            with closing(db_connect()) as db:
                db.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (target.id,))
                db.commit()
            await update.message.reply_text(f"✅ {target.first_name} آنبن شد!")
            return
        if cmd in ["/addcoin", "سکه", "+سکه"] and len(parts) > 1:
            try:
                amt = int(parts[1])
                add_coins(target.id, amt)
                await update.message.reply_text(f"💰 {amt:,} {CURRENCY_NAME} به {target.first_name} اضافه شد!")
            except:
                pass
            return
        if cmd in ["/remcoin", "کسر", "-سکه"] and len(parts) > 1:
            try:
                amt = int(parts[1])
                with closing(db_connect()) as db:
                    db.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (amt, target.id))
                    db.commit()
                await update.message.reply_text(f"🔥 {amt:,} {CURRENCY_NAME} از {target.first_name} کسر شد!")
            except:
                pass
            return
    
    # ============================================================
    # دریافت شرط
    # ============================================================
    
    if context.user_data.get("awaiting_bet"):
        if text.isdigit():
            bet = int(text)
            if bet < MIN_BET:
                await update.message.reply_text(f"❌ حداقل شرط {MIN_BET} {CURRENCY_NAME} است!")
                return
            
            u = get_user(user.id)
            if u["coins"] < bet:
                await update.message.reply_text(f"❌ پول کافی ندارید! موجودی: {u['coins']:,} {CURRENCY_NAME}")
                return
            
            game_type = context.user_data.get("temp_game")
            if not game_type:
                await update.message.reply_text("❌ خطا! دوباره از منو بازی رو انتخاب کن.")
                return
            
            remove_coins(user.id, bet)
            room = create_room(update.effective_chat.id, game_type, user.id, bet)
            
            msg_text = (
                f"🎮 **{GAME_NAMES[game_type]}**\n"
                f"━━━━━━━━━━━━━━\n"
                f"💰 شرط: {bet} {CURRENCY_NAME}\n"
                f"👥 بازیکنان: 1/{GAME_MAX_PLAYERS[game_type]}\n"
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
    await query.answer()
    user = query.from_user
    ensure_user(user.id, user.first_name)
    
    u_data = get_user(user.id)
    if u_data and u_data["is_banned"] == 1:
        await query.edit_message_text("🚫 شما بن شده‌اید!")
        return
    
    data = query.data
    
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
            "🎮 **انتخاب بازی:**",
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
        
        await query.edit_message_text(
            f"🎮 **{GAME_NAMES[game_type]}**\n"
            f"━━━━━━━━━━━━━━\n"
            f"💰 حداقل شرط: {MIN_BET} {CURRENCY_NAME}\n"
            f"👥 حداکثر بازیکن: {GAME_MAX_PLAYERS[game_type]}\n\n"
            f"مبلغ شرط را وارد کنید (عدد):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لغو", callback_data="games_list")]]),
            parse_mode="Markdown"
        )
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
        
        if not remove_coins(user.id, room.bet):
            await query.answer(f"❌ شما {room.bet} {CURRENCY_NAME} ندارید!", show_alert=True)
            return
        
        room.add_player(user.id)
        PLAYER_IN_GAME[user.id] = room_id
        
        await show_room_status(room, context, query)
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
        
        room.started = True
        await query.edit_message_text("🎮 بازی شروع شد! (در حال توسعه...)")
        cleanup_room(room_id)
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
        
        for p in room.players:
            add_coins(p, room.bet)
            PLAYER_IN_GAME.pop(p, None)
        
        ACTIVE_ROOMS.pop(room_id, None)
        await query.edit_message_text("❌ اتاق لغو شد.", reply_markup=main_menu())
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
        
        if not rows:
            await query.edit_message_text("❌ هنوز کسی ثبت نشده!")
            return
        
        msg = "🏆 **جدول ثروتمندان طویله**\n━━━━━━━━━━━━━━━━\n"
        for i, row in enumerate(rows, 1):
            medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
            title = get_title_by_level(row["level"])
            msg += f"{medal} {title} {row['name']} — {row['coins']:,} {CURRENCY_NAME} (سطح {row['level']})\n"
        
        user_row = db.execute(
            "SELECT COUNT(*) + 1 as rank FROM users WHERE coins > (SELECT coins FROM users WHERE user_id = ?)",
            (user.id,)
        ).fetchone()
        
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
        
        if not remove_coins(user.id, price):
            await query.answer(f"❌ {price:,} {CURRENCY_NAME} ندارید!", show_alert=True)
            return
        
        donkey = get_donkey(user.id)
        if not donkey:
            await query.answer("❌ خر شما وجود ندارد!", show_alert=True)
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
    
    logger.info("✅ ربات خرستان راه‌اندازی شد!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
