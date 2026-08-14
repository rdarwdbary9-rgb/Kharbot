import os
import random
import sqlite3
import time
import json
import uuid
import logging
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ============================================================
# 🫏 KHARBOT
# ONE FILE EDITION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)

# روی Belmo از /tmp استفاده می‌کنیم چون /app ممکن است read-only باشد.
DB_PATH = os.getenv("DB_PATH", "/tmp/kharbot.db")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN تنظیم نشده است.")

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger("KharBot")

# ============================================================
# DATABASE
# ============================================================

db = sqlite3.connect(
    DB_PATH,
    check_same_thread=False
)

db.row_factory = sqlite3.Row

db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA synchronous=NORMAL")

db_lock = None


def execute(sql, params=(), commit=False):
    cur = db.cursor()
    cur.execute(sql, params)

    if commit:
        db.commit()

    return cur


def init_database():

    execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT DEFAULT '',
        first_name TEXT DEFAULT '',

        coins INTEGER DEFAULT 100,
        gems INTEGER DEFAULT 0,

        xp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1,

        title TEXT DEFAULT '',

        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        games INTEGER DEFAULT 0,

        daily_at INTEGER DEFAULT 0,

        voice_last INTEGER DEFAULT 0,
        voice_count INTEGER DEFAULT 0,

        banned INTEGER DEFAULT 0,

        created_at INTEGER DEFAULT 0
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS donkeys (
        user_id INTEGER PRIMARY KEY,

        name TEXT DEFAULT 'خر من',

        age INTEGER DEFAULT 1,

        health INTEGER DEFAULT 100,
        hunger INTEGER DEFAULT 20,
        thirst INTEGER DEFAULT 20,
        energy INTEGER DEFAULT 100,
        cleanliness INTEGER DEFAULT 100,

        power INTEGER DEFAULT 1,
        defense INTEGER DEFAULT 1,
        luck INTEGER DEFAULT 1,

        skin TEXT DEFAULT 'classic',

        last_update INTEGER DEFAULT 0,

        FOREIGN KEY(user_id)
        REFERENCES users(user_id)
        ON DELETE CASCADE
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        user_id INTEGER,
        item_id TEXT,

        quantity INTEGER DEFAULT 0,

        PRIMARY KEY(user_id, item_id)
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS achievements (
        user_id INTEGER,
        achievement_id TEXT,

        PRIMARY KEY(user_id, achievement_id)
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS quests (
        user_id INTEGER,
        quest_id TEXT,

        progress INTEGER DEFAULT 0,
        claimed INTEGER DEFAULT 0,
        day TEXT DEFAULT '',

        PRIMARY KEY(user_id, quest_id)
    )
    """)

    execute("""
    CREATE TABLE IF NOT EXISTS group_games (
        game_id TEXT PRIMARY KEY,

        chat_id INTEGER,
        message_id INTEGER,

        game_type TEXT,

        creator_id INTEGER,

        bet INTEGER DEFAULT 0,

        state TEXT DEFAULT 'lobby',

        players TEXT DEFAULT '[]',

        data TEXT DEFAULT '{}',

        created_at INTEGER DEFAULT 0
    )
    """)

    db.commit()


init_database()

# ============================================================
# ECONOMY
# ============================================================

VOICE_REWARDS = {
    "عر": 10,
    "عرعر": 15,
    "عرر": 18,
    "عررر": 20,
    "عرررر": 25,
    "خر": 8,
    "خرر": 12,
    "خررر": 18,
    "تورک": 12,
    "ترک": 18,
}

VOICE_COOLDOWN = 30

DAILY_REWARD = 100


def get_coins(user_id):

    row = execute(
        "SELECT coins FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    return int(row["coins"]) if row else 0


def get_gems(user_id):

    row = execute(
        "SELECT gems FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    return int(row["gems"]) if row else 0


def add_coins(user_id, amount):

    execute(
        """
        UPDATE users
        SET coins = MAX(0, coins + ?)
        WHERE user_id=?
        """,
        (amount, user_id),
        commit=True
    )


def remove_coins(user_id, amount):

    row = execute(
        "SELECT coins FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not row or row["coins"] < amount:
        return False

    execute(
        """
        UPDATE users
        SET coins = coins - ?
        WHERE user_id=?
        """,
        (amount, user_id),
        commit=True
    )

    return True


def add_gems(user_id, amount):

    execute(
        """
        UPDATE users
        SET gems = MAX(0, gems + ?)
        WHERE user_id=?
        """,
        (amount, user_id),
        commit=True
    )


def remove_gems(user_id, amount):

    row = execute(
        "SELECT gems FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not row or row["gems"] < amount:
        return False

    execute(
        """
        UPDATE users
        SET gems = gems - ?
        WHERE user_id=?
        """,
        (amount, user_id),
        commit=True
    )

    return True


# ============================================================
# USER CREATION
# ============================================================

def create_user(user):

    now = int(time.time())

    row = execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (user.id,)
    ).fetchone()

    if not row:

        execute(
            """
            INSERT INTO users(
                user_id,
                username,
                first_name,
                coins,
                gems,
                created_at
            )
            VALUES (?, ?, ?, 100, 0, ?)
            """,
            (
                user.id,
                user.username or "",
                user.first_name or "Player",
                now
            )
        )

        execute(
            """
            INSERT INTO donkeys(
                user_id,
                name,
                last_update
            )
            VALUES (?, ?, ?)
            """,
            (
                user.id,
                f"خر {user.first_name or 'من'}",
                now
            )
        )

        db.commit()

    else:

        execute(
            """
            UPDATE users
            SET username=?,
                first_name=?
            WHERE user_id=?
            """,
            (
                user.username or "",
                user.first_name or "Player",
                user.id
            ),
            commit=True
        )


# ============================================================
# XP / LEVEL
# ============================================================

def level_cost(level):

    return 100 + ((level - 1) * 75)


def add_xp(user_id, amount):

    row = execute(
        "SELECT xp, level FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not row:
        return False

    xp = row["xp"] + amount
    level = row["level"]

    leveled_up = False

    while xp >= level * 100:

        xp -= level * 100
        level += 1
        leveled_up = True

    execute(
        """
        UPDATE users
        SET xp=?,
            level=?
        WHERE user_id=?
        """,
        (xp, level, user_id),
        commit=True
    )

    return leveled_up


# ============================================================
# DONKEY SYSTEM
# ============================================================

DONKEY_COSTS = {

    "food": 20,
    "food_plus": 60,

    "water": 10,

    "bath": 30,
    "bath_plus": 80,

    "rest": 15,

    "medicine": 50,
    "medicine_plus": 150,

    "energy": 40,

    "training": 75,
    "defense": 75,

    "luck": 100,
}


def get_donkey(user_id):

    row = execute(
        """
        SELECT *
        FROM donkeys
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()

    return row


def update_donkey_stats(user_id):

    donkey = get_donkey(user_id)

    if not donkey:
        return

    now = int(time.time())

    last = donkey["last_update"]

    if last <= 0:
        last = now

    elapsed = now - last

    # هر ۳۰ دقیقه کمی نیازهای خر تغییر می‌کند.
    steps = elapsed // 1800

    if steps <= 0:
        return

    hunger = min(100, donkey["hunger"] + steps * 3)
    thirst = min(100, donkey["thirst"] + steps * 4)
    cleanliness = max(0, donkey["cleanliness"] - steps * 2)
    energy = max(0, donkey["energy"] - steps * 2)

    health = donkey["health"]

    if hunger >= 90:
        health -= steps

    if thirst >= 90:
        health -= steps * 2

    if cleanliness <= 10:
        health -= steps

    health = max(0, min(100, health))

    execute(
        """
        UPDATE donkeys

        SET hunger=?,
            thirst=?,
            cleanliness=?,
            energy=?,
            health=?,
            last_update=?

        WHERE user_id=?
        """,
        (
            hunger,
            thirst,
            cleanliness,
            energy,
            health,
            now,
            user_id
        ),
        commit=True
    )


def donkey_action(user_id, action):

    update_donkey_stats(user_id)

    donkey = get_donkey(user_id)

    if not donkey:
        return False, "خر پیدا نشد."

    cost = DONKEY_COSTS.get(action)

    if cost is None:
        return False, "این عملیات وجود ندارد."

    if not remove_coins(user_id, cost):
        return False, (
            f"❌ سکه کافی نداری!\n"
            f"💰 هزینه: {cost:,} 🪙"
        )

    health = donkey["health"]
    hunger = donkey["hunger"]
    thirst = donkey["thirst"]
    energy = donkey["energy"]
    cleanliness = donkey["cleanliness"]
    power = donkey["power"]
    defense = donkey["defense"]
    luck = donkey["luck"]

    if action == "food":
        hunger = max(0, hunger - 30)
        energy = min(100, energy + 5)

    elif action == "food_plus":
        hunger = max(0, hunger - 60)
        health = min(100, health + 5)
        energy = min(100, energy + 15)

    elif action == "water":
        thirst = max(0, thirst - 40)
        energy = min(100, energy + 5)

    elif action == "bath":
        cleanliness = min(100, cleanliness + 45)

    elif action == "bath_plus":
        cleanliness = 100
        health = min(100, health + 5)

    elif action == "rest":
        energy = min(100, energy + 35)

    elif action == "medicine":
        health = min(100, health + 20)

    elif action == "medicine_plus":
        health = 100

    elif action == "energy":
        energy = min(100, energy + 50)

    elif action == "training":

        if energy < 20:
            add_coins(user_id, cost)
            return False, "⚡ انرژی خر برای تمرین کافی نیست."

        power += 1
        energy = max(0, energy - 20)

    elif action == "defense":

        if energy < 20:
            add_coins(user_id, cost)
            return False, "⚡ انرژی خر برای تمرین کافی نیست."

        defense += 1
        energy = max(0, energy - 20)

    elif action == "luck":
        luck += 1

    execute(
        """
        UPDATE donkeys

        SET health=?,
            hunger=?,
            thirst=?,
            energy=?,
            cleanliness=?,
            power=?,
            defense=?,
            luck=?

        WHERE user_id=?
        """,
        (
            health,
            hunger,
            thirst,
            energy,
            cleanliness,
            power,
            defense,
            luck,
            user_id
        ),
        commit=True
    )

    add_xp(user_id, 5)

    return True, f"✅ عملیات انجام شد!\n💸 هزینه: {cost:,} 🪙"


# ============================================================
# DONKEY LEVEL UP
# ============================================================

def upgrade_donkey(user_id):

    donkey = get_donkey(user_id)

    if not donkey:
        return False, "خر پیدا نشد."

    level = execute(
        "SELECT level FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()["level"]

    cost = level_cost(level)

    if not remove_coins(user_id, cost):

        return False, (
            "❌ سکه کافی نیست!\n\n"
            f"⬆️ Level فعلی: {level}\n"
            f"💰 هزینه ارتقا: {cost:,} 🪙"
        )

    execute(
        """
        UPDATE users
        SET level=level+1,
            xp=0
        WHERE user_id=?
        """,
        (user_id,),
        commit=True
    )

    execute(
        """
        UPDATE donkeys

        SET health=100,
            energy=100,
            power=power+1,
            defense=defense+1

        WHERE user_id=?
        """,
        (user_id,),
        commit=True
    )

    return True, (
        "🎉 **خر ارتقا پیدا کرد!**\n\n"
        f"💸 هزینه: {cost:,} 🪙\n"
        "❤️ سلامت: 100\n"
        "⚡ انرژی: 100\n"
        "💪 قدرت +1\n"
        "🛡️ دفاع +1"
    )


# ============================================================
# STORE
# ============================================================

STORE = {

    "food": {
        "name": "🍎 غذای معمولی",
        "price": 20,
        "type": "action"
    },

    "food_plus": {
        "name": "🥩 غذای ویژه",
        "price": 60,
        "type": "action"
    },

    "water": {
        "name": "💧 آب",
        "price": 10,
        "type": "action"
    },

    "bath": {
        "name": "🛁 حمام",
        "price": 30,
        "type": "action"
    },

    "bath_plus": {
        "name": "🧼 حمام ویژه",
        "price": 80,
        "type": "action"
    },

    "rest": {
        "name": "😴 استراحت",
        "price": 15,
        "type": "action"
    },

    "medicine": {
        "name": "💊 دارو",
        "price": 50,
        "type": "action"
    },

    "medicine_plus": {
        "name": "❤️ درمان کامل",
        "price": 150,
        "type": "action"
    },

    "energy": {
        "name": "⚡ انرژی",
        "price": 40,
        "type": "action"
    },

    "training": {
        "name": "🏋️ تمرین قدرت",
        "price": 75,
        "type": "action"
    },

    "defense": {
        "name": "🛡️ تمرین دفاع",
        "price": 75,
        "type": "action"
    },

    "luck": {
        "name": "🍀 افزایش شانس",
        "price": 100,
        "type": "action"
    },

    "skin_gold": {
        "name": "✨ پوست طلایی",
        "price": 1000,
        "type": "skin",
        "skin": "gold"
    },

    "skin_legend": {
        "name": "🌟 پوست افسانه‌ای",
        "price": 2500,
        "type": "skin",
        "skin": "legend"
    },
}


# ============================================================
# UI HELPERS
# ============================================================

def back_button():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 منوی اصلی",
                callback_data="main"
            )
        ]
    ])


def main_menu(user_id):

    rows = [

        [
            InlineKeyboardButton(
                "🫏 خر من",
                callback_data="donkey"
            ),
            InlineKeyboardButton(
                "👤 پروفایل",
                callback_data="profile"
            )
        ],

        [
            InlineKeyboardButton(
                "🎮 بازی‌ها",
                callback_data="games"
            ),
            InlineKeyboardButton(
                "🛒 فروشگاه",
                callback_data="shop"
            )
        ],

        [
            InlineKeyboardButton(
                "🏆 لیدربرد",
                callback_data="leaderboard"
            ),
            InlineKeyboardButton(
                "🎯 مأموریت‌ها",
                callback_data="quests"
            )
        ],

        [
            InlineKeyboardButton(
                "🎒 انبار",
                callback_data="inventory"
            ),
            InlineKeyboardButton(
                "🎁 روزانه",
                callback_data="daily"
            )
        ],

        [
            InlineKeyboardButton(
                "📖 راهنما",
                callback_data="help"
            )
        ]
    ]

    if user_id == ADMIN_ID and ADMIN_ID != 0:

        rows.append([
            InlineKeyboardButton(
                "👑 پنل مالک",
                callback_data="admin"
            )
        ])

    return InlineKeyboardMarkup(rows)


# ============================================================
# DONKEY MENU
# ============================================================

def donkey_menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🍎 غذا",
                callback_data="donkey_food"
            ),
            InlineKeyboardButton(
                "💧 آب",
                callback_data="donkey_water"
            )
        ],

        [
            InlineKeyboardButton(
                "🛁 حمام",
                callback_data="donkey_bath"
            ),
            InlineKeyboardButton(
                "😴 استراحت",
                callback_data="donkey_rest"
            )
        ],

        [
            InlineKeyboardButton(
                "💊 درمان",
                callback_data="donkey_medicine"
            ),
            InlineKeyboardButton(
                "⚡ انرژی",
                callback_data="donkey_energy"
            )
        ],

        [
            InlineKeyboardButton(
                "🏋️ قدرت",
                callback_data="donkey_training"
            ),
            InlineKeyboardButton(
                "🛡️ دفاع",
                callback_data="donkey_defense"
            )
        ],

        [
            InlineKeyboardButton(
                "🍀 شانس",
                callback_data="donkey_luck"
            ),
            InlineKeyboardButton(
                "⬆️ ارتقا",
                callback_data="donkey_upgrade"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 منوی اصلی",
                callback_data="main"
            )
        ]
    ])


def donkey_text(user_id):

    update_donkey_stats(user_id)

    user = execute(
        """
        SELECT level, xp, coins, gems
        FROM users
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()

    d = get_donkey(user_id)

    skin_names = {
        "classic": "🫏 کلاسیک",
        "gold": "✨ طلایی",
        "legend": "🌟 افسانه‌ای"
    }

    return (
        f"🫏 **خر من**\n"
        f"━━━━━━━━━━━━━━\n"
        f"🏷️ نام: **{d['name']}**\n"
        f"⭐ Level: **{user['level']}**\n"
        f"✨ XP: **{user['xp']}**\n\n"

        f"❤️ سلامت: **{d['health']}/100**\n"
        f"🍎 گرسنگی: **{d['hunger']}/100**\n"
        f"💧 تشنگی: **{d['thirst']}/100**\n"
        f"⚡ انرژی: **{d['energy']}/100**\n"
        f"🛁 تمیزی: **{d['cleanliness']}/100**\n\n"

        f"💪 قدرت: **{d['power']}**\n"
        f"🛡️ دفاع: **{d['defense']}**\n"
        f"🍀 شانس: **{d['luck']}**\n"
        f"🎨 ظاهر: **{skin_names.get(d['skin'], d['skin'])}**\n\n"

        f"💰 سکه: **{user['coins']:,}** 🪙\n"
        f"💎 جم: **{user['gems']:,}**"
    )


# ============================================================
# PROFILE
# ============================================================

async def show_profile(update, user_id):

    row = execute(
        """
        SELECT *
        FROM users
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()

    if not row:
        return

    text = (
        "👤 **پروفایل خر‌بات**\n"
        "━━━━━━━━━━━━━━\n"
        f"📝 نام: **{row['first_name']}**\n"
        f"🆔 ID: `{user_id}`\n"
        f"🏷️ لقب: **{row['title'] or 'خر معمولی'}**\n\n"

        f"💰 سکه: **{row['coins']:,}** 🪙\n"
        f"💎 جم: **{row['gems']:,}**\n"
        f"⭐ Level: **{row['level']}**\n"
        f"✨ XP: **{row['xp']}**\n\n"

        f"🎮 بازی‌ها: **{row['games']}**\n"
        f"🏆 برد: **{row['wins']}**\n"
        f"💀 باخت: **{row['losses']}**"
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=main_menu(user_id)
    )


# ============================================================
# DAILY
# ============================================================

async def daily_command(update, context):

    user = update.effective_user

    create_user(user)

    now = int(time.time())

    row = execute(
        "SELECT daily_at FROM users WHERE user_id=?",
        (user.id,)
    ).fetchone()

    last = row["daily_at"]

    if now - last < 86400:

        remaining = 86400 - (now - last)

        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        await update.message.reply_text(
            f"⏳ جایزه روزانه‌ات رو گرفتی!\n"
            f"⏰ **{hours} ساعت و {minutes} دقیقه** دیگه برگرد."
        )

        return

    execute(
        """
        UPDATE users
        SET daily_at=?
        WHERE user_id=?
        """,
        (now, user.id),
        commit=True
    )

    add_coins(user.id, DAILY_REWARD)
    add_xp(user.id, 10)

    await update.message.reply_text(
        f"🎁 **جایزه روزانه!**\n\n"
        f"+{DAILY_REWARD} 🪙 سکه\n"
        f"+10 ✨ XP"
    )


# ============================================================
# VOICE / EARN SYSTEM
# ============================================================

async def voice_command(update, text):

    user = update.effective_user

    create_user(user)

    text = text.strip().lower()

    reward = VOICE_REWARDS.get(text)

    if reward is None:
        return False

    row = execute(
        """
        SELECT voice_last
        FROM users
        WHERE user_id=?
        """,
        (user.id,)
    ).fetchone()

    now = int(time.time())

    if now - row["voice_last"] < VOICE_COOLDOWN:

        remaining = VOICE_COOLDOWN - (
            now - row["voice_last"]
        )

        await update.message.reply_text(
            f"⏳ هنوز زوده 😂\n"
            f"**{remaining} ثانیه** دیگه دوباره امتحان کن."
        )

        return True

    execute(
        """
        UPDATE users
        SET voice_last=?,
            voice_count=voice_count+1
        WHERE user_id=?
        """,
        (now, user.id),
        commit=True
    )

    add_coins(user.id, reward)
    add_xp(user.id, 2)

    donkey = get_donkey(user.id)

    await update.message.reply_text(
        f"🫏 **{text}**\n\n"
        f"💰 +{reward} 🪙\n"
        f"⭐ +2 XP\n\n"
        f"❤️ سلامت خر: {donkey['health']}/100"
    )

    return True
    # ============================================================
# 🛒 SHOP SYSTEM
# ============================================================

SHOP_ITEMS = {
    "food": {
        "name": "🍎 غذای معمولی",
        "price": 20,
        "description": "گرسنگی خر را کاهش می‌دهد."
    },

    "food_plus": {
        "name": "🥩 غذای ویژه",
        "price": 60,
        "description": "غذای قوی‌تر با اثر بیشتر."
    },

    "water": {
        "name": "💧 آب خنک",
        "price": 10,
        "description": "تشنگی خر را کاهش می‌دهد."
    },

    "bath": {
        "name": "🛁 حمام",
        "price": 30,
        "description": "تمیزی خر را افزایش می‌دهد."
    },

    "bath_plus": {
        "name": "🧼 حمام VIP",
        "price": 80,
        "description": "خر را کاملاً تمیز می‌کند."
    },

    "medicine": {
        "name": "💊 دارو",
        "price": 50,
        "description": "سلامت خر را افزایش می‌دهد."
    },

    "medicine_plus": {
        "name": "❤️ درمان کامل",
        "price": 150,
        "description": "سلامت خر را کامل می‌کند."
    },

    "rest": {
        "name": "😴 استراحت",
        "price": 15,
        "description": "انرژی خر را افزایش می‌دهد."
    },

    "energy": {
        "name": "⚡ انرژی",
        "price": 40,
        "description": "انرژی زیادی به خر می‌دهد."
    },

    "training": {
        "name": "🏋️ تمرین قدرت",
        "price": 75,
        "description": "قدرت خر را افزایش می‌دهد."
    },

    "defense": {
        "name": "🛡️ تمرین دفاع",
        "price": 75,
        "description": "دفاع خر را افزایش می‌دهد."
    },

    "luck": {
        "name": "🍀 آموزش شانس",
        "price": 100,
        "description": "شانس خر را افزایش می‌دهد."
    },

    "skin_gold": {
        "name": "✨ ظاهر طلایی",
        "price": 1000,
        "description": "ظاهر ویژه طلایی."
    },

    "skin_legend": {
        "name": "🌟 ظاهر افسانه‌ای",
        "price": 2500,
        "description": "کمیاب‌ترین ظاهر."
    }
}


def shop_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🍎 غذا",
                callback_data="buy_food"
            ),
            InlineKeyboardButton(
                "🥩 غذای ویژه",
                callback_data="buy_food_plus"
            )
        ],

        [
            InlineKeyboardButton(
                "💧 آب",
                callback_data="buy_water"
            ),
            InlineKeyboardButton(
                "🛁 حمام",
                callback_data="buy_bath"
            )
        ],

        [
            InlineKeyboardButton(
                "🧼 حمام VIP",
                callback_data="buy_bath_plus"
            ),
            InlineKeyboardButton(
                "💊 دارو",
                callback_data="buy_medicine"
            )
        ],

        [
            InlineKeyboardButton(
                "❤️ درمان کامل",
                callback_data="buy_medicine_plus"
            ),
            InlineKeyboardButton(
                "⚡ انرژی",
                callback_data="buy_energy"
            )
        ],

        [
            InlineKeyboardButton(
                "🏋️ قدرت",
                callback_data="buy_training"
            ),
            InlineKeyboardButton(
                "🛡️ دفاع",
                callback_data="buy_defense"
            )
        ],

        [
            InlineKeyboardButton(
                "🍀 شانس",
                callback_data="buy_luck"
            )
        ],

        [
            InlineKeyboardButton(
                "✨ ظاهر طلایی",
                callback_data="buy_skin_gold"
            ),
            InlineKeyboardButton(
                "🌟 افسانه‌ای",
                callback_data="buy_skin_legend"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 منو",
                callback_data="main"
            )
        ]
    ])


async def shop_page(update, context):

    user = update.effective_user

    coins = get_coins(user.id)
    gems = get_gems(user.id)

    text = (
        "🛒 **فروشگاه خر‌بات**\n"
        "━━━━━━━━━━━━━━\n\n"

        "💰 موجودی:\n"
        f"🪙 **{coins:,}**\n"
        f"💎 **{gems:,}**\n\n"

        "هر خرید مستقیماً روی خر یا موجودی "
        "تو اعمال می‌شود.\n\n"

        "💡 قیمت‌ها طوری تنظیم شده‌اند که "
        "سکه ارزش خودش را حفظ کند."
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=shop_keyboard()
    )


# ============================================================
# INVENTORY
# ============================================================

async def inventory_page(update, context):

    user = update.effective_user

    rows = execute(
        """
        SELECT item_id, quantity
        FROM inventory
        WHERE user_id=?
        AND quantity > 0
        ORDER BY item_id
        """,
        (user.id,)
    ).fetchall()

    text = "🎒 **انبار من**\n━━━━━━━━━━━━━━\n\n"

    if not rows:

        text += "📭 انبارت خالیه."

    else:

        for row in rows:

            item = SHOP_ITEMS.get(row["item_id"])

            if item:

                text += (
                    f"{item['name']} × "
                    f"**{row['quantity']}**\n"
                )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🛒 فروشگاه",
                callback_data="shop"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 منو",
                callback_data="main"
            )
        ]
    ])

    await update.callback_query.edit_message_text(
        text,
        reply_markup=keyboard
    )


def add_item(user_id, item_id, quantity=1):

    execute(
        """
        INSERT INTO inventory(
            user_id,
            item_id,
            quantity
        )
        VALUES (?, ?, ?)

        ON CONFLICT(user_id,item_id)

        DO UPDATE SET
        quantity=quantity+excluded.quantity
        """,
        (
            user_id,
            item_id,
            quantity
        ),
        commit=True
    )


def remove_item(user_id, item_id, quantity=1):

    row = execute(
        """
        SELECT quantity
        FROM inventory
        WHERE user_id=?
        AND item_id=?
        """,
        (
            user_id,
            item_id
        )
    ).fetchone()

    if not row or row["quantity"] < quantity:
        return False

    execute(
        """
        UPDATE inventory
        SET quantity=quantity-?
        WHERE user_id=?
        AND item_id=?
        """,
        (
            quantity,
            user_id,
            item_id
        ),
        commit=True
    )

    return True


# ============================================================
# SHOP PURCHASE
# ============================================================

async def purchase_item(update, context, item_id):

    user = update.effective_user

    item = SHOP_ITEMS.get(item_id)

    if not item:
        await update.callback_query.answer(
            "❌ این آیتم وجود ندارد.",
            show_alert=True
        )
        return

    price = item["price"]

    if not remove_coins(user.id, price):

        await update.callback_query.answer(
            f"❌ سکه کافی نداری!\n"
            f"قیمت: {price:,} 🪙",
            show_alert=True
        )

        return

    # آیتم‌های مصرفی مستقیماً اعمال می‌شوند.
    if item_id in DONKEY_COSTS:

        # قیمت قبلاً پرداخت شده؛
        # بنابراین اکشن را مستقیماً اعمال می‌کنیم.
        update_donkey_stats(user.id)

        d = get_donkey(user.id)

        health = d["health"]
        hunger = d["hunger"]
        thirst = d["thirst"]
        energy = d["energy"]
        cleanliness = d["cleanliness"]
        power = d["power"]
        defense = d["defense"]
        luck = d["luck"]

        if item_id == "food":
            hunger = max(0, hunger - 30)
            energy = min(100, energy + 5)

        elif item_id == "food_plus":
            hunger = max(0, hunger - 60)
            energy = min(100, energy + 15)
            health = min(100, health + 5)

        elif item_id == "water":
            thirst = max(0, thirst - 40)

        elif item_id == "bath":
            cleanliness = min(100, cleanliness + 45)

        elif item_id == "bath_plus":
            cleanliness = 100
            health = min(100, health + 5)

        elif item_id == "medicine":
            health = min(100, health + 20)

        elif item_id == "medicine_plus":
            health = 100

        elif item_id == "rest":
            energy = min(100, energy + 35)

        elif item_id == "energy":
            energy = min(100, energy + 50)

        elif item_id == "training":

            if energy < 20:

                add_coins(user.id, price)

                await update.callback_query.answer(
                    "⚡ انرژی خر کافی نیست.",
                    show_alert=True
                )

                return

            power += 1
            energy -= 20

        elif item_id == "defense":

            if energy < 20:

                add_coins(user.id, price)

                await update.callback_query.answer(
                    "⚡ انرژی خر کافی نیست.",
                    show_alert=True
                )

                return

            defense += 1
            energy -= 20

        elif item_id == "luck":
            luck += 1

        execute(
            """
            UPDATE donkeys

            SET health=?,
                hunger=?,
                thirst=?,
                energy=?,
                cleanliness=?,
                power=?,
                defense=?,
                luck=?

            WHERE user_id=?
            """,
            (
                health,
                hunger,
                thirst,
                energy,
                cleanliness,
                power,
                defense,
                luck,
                user.id
            ),
            commit=True
        )

        add_xp(user.id, 5)

    elif item_id == "skin_gold":

        execute(
            """
            UPDATE donkeys
            SET skin='gold'
            WHERE user_id=?
            """,
            (user.id,),
            commit=True
        )

    elif item_id == "skin_legend":

        execute(
            """
            UPDATE donkeys
            SET skin='legend'
            WHERE user_id=?
            """,
            (user.id,),
            commit=True
        )

    else:

        add_item(
            user.id,
            item_id,
            1
        )

    await update.callback_query.answer(
        f"✅ خرید شد!\n"
        f"💸 -{price:,} 🪙",
        show_alert=True
    )


# ============================================================
# DAILY QUESTS
# ============================================================

QUESTS = {
    "voice": {
        "name": "🫏 صدای خر",
        "target": 5,
        "reward": 100
    },

    "games": {
        "name": "🎮 گیمر",
        "target": 3,
        "reward": 150
    },

    "win": {
        "name": "🏆 برنده",
        "target": 1,
        "reward": 200
    },

    "feed": {
        "name": "🍎 مراقبت",
        "target": 2,
        "reward": 80
    }
}


def today():

    return datetime.utcnow().strftime("%Y-%m-%d")


def quest_progress(user_id, quest_id):

    day = today()

    row = execute(
        """
        SELECT progress, claimed
        FROM quests
        WHERE user_id=?
        AND quest_id=?
        AND day=?
        """,
        (
            user_id,
            quest_id,
            day
        )
    ).fetchone()

    if not row:

        execute(
            """
            INSERT OR REPLACE INTO quests(
                user_id,
                quest_id,
                progress,
                claimed,
                day
            )
            VALUES (?, ?, 0, 0, ?)
            """,
            (
                user_id,
                quest_id,
                day
            ),
            commit=True
        )

        return 0, 0

    return row["progress"], row["claimed"]


def increase_quest(user_id, quest_id, amount=1):

    if quest_id not in QUESTS:
        return

    progress, claimed = quest_progress(
        user_id,
        quest_id
    )

    target = QUESTS[quest_id]["target"]

    progress = min(
        target,
        progress + amount
    )

    execute(
        """
        UPDATE quests

        SET progress=?

        WHERE user_id=?
        AND quest_id=?
        AND day=?
        """,
        (
            progress,
            user_id,
            quest_id,
            today()
        ),
        commit=True
    )


async def quests_page(update, context):

    user = update.effective_user

    text = (
        "🎯 **مأموریت‌های امروز**\n"
        "━━━━━━━━━━━━━━\n\n"
    )

    buttons = []

    for quest_id, quest in QUESTS.items():

        progress, claimed = quest_progress(
            user.id,
            quest_id
        )

        status = "✅ دریافت شد" if claimed else (
            "🎁 آماده دریافت"
            if progress >= quest["target"]
            else "⏳ در حال انجام"
        )

        text += (
            f"{quest['name']}\n"
            f"📊 {progress}/{quest['target']}\n"
            f"💰 جایزه: {quest['reward']} 🪙\n"
            f"{status}\n\n"
        )

        if progress >= quest["target"] and not claimed:

            buttons.append([
                InlineKeyboardButton(
                    f"🎁 دریافت {quest['name']}",
                    callback_data=f"claimquest_{quest_id}"
                )
            ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 منو",
            callback_data="main"
        )
    ])

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def claim_quest(update, context, quest_id):

    user = update.effective_user

    if quest_id not in QUESTS:
        return

    progress, claimed = quest_progress(
        user.id,
        quest_id
    )

    target = QUESTS[quest_id]["target"]

    if claimed:

        await update.callback_query.answer(
            "این جایزه قبلاً گرفته شده.",
            show_alert=True
        )

        return

    if progress < target:

        await update.callback_query.answer(
            "هنوز کاملش نکردی.",
            show_alert=True
        )

        return

    reward = QUESTS[quest_id]["reward"]

    execute(
        """
        UPDATE quests
        SET claimed=1
        WHERE user_id=?
        AND quest_id=?
        AND day=?
        """,
        (
            user.id,
            quest_id,
            today()
        ),
        commit=True
    )

    add_coins(user.id, reward)
    add_xp(user.id, 15)

    await update.callback_query.answer(
        f"🎁 +{reward} 🪙",
        show_alert=True
    )


# ============================================================
# ACHIEVEMENTS
# ============================================================

ACHIEVEMENTS = {

    "first_game": (
        "🎮 اولین بازی",
        1
    ),

    "ten_games": (
        "🎮 ده بازی",
        10
    ),

    "first_win": (
        "🏆 اولین برد",
        1
    ),

    "ten_wins": (
        "🏆 ده برد",
        10
    ),

    "rich": (
        "💰 پولدار",
        5000
    ),

    "donkey_power": (
        "💪 خر قدرتمند",
        10
    )
}


def has_achievement(user_id, achievement_id):

    row = execute(
        """
        SELECT 1
        FROM achievements
        WHERE user_id=?
        AND achievement_id=?
        """,
        (
            user_id,
            achievement_id
        )
    ).fetchone()

    return row is not None


def unlock_achievement(user_id, achievement_id):

    if has_achievement(
        user_id,
        achievement_id
    ):
        return False

    execute(
        """
        INSERT INTO achievements(
            user_id,
            achievement_id
        )
        VALUES (?, ?)
        """,
        (
            user_id,
            achievement_id
        ),
        commit=True
    )

    add_coins(
        user_id,
        100
    )

    add_xp(
        user_id,
        25
    )

    return True


def check_achievements(user_id):

    row = execute(
        """
        SELECT games, wins, coins
        FROM users
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()

    d = get_donkey(user_id)

    if row["games"] >= 1:
        unlock_achievement(
            user_id,
            "first_game"
        )

    if row["games"] >= 10:
        unlock_achievement(
            user_id,
            "ten_games"
        )

    if row["wins"] >= 1:
        unlock_achievement(
            user_id,
            "first_win"
        )

    if row["wins"] >= 10:
        unlock_achievement(
            user_id,
            "ten_wins"
        )

    if row["coins"] >= 5000:
        unlock_achievement(
            user_id,
            "rich"
        )

    if d and d["power"] >= 10:
        unlock_achievement(
            user_id,
            "donkey_power"
        )


async def achievements_page(update, context):

    user = update.effective_user

    text = (
        "🏅 **Achievement ها**\n"
        "━━━━━━━━━━━━━━\n\n"
    )

    for aid, (name, target) in ACHIEVEMENTS.items():

        if has_achievement(
            user.id,
            aid
        ):

            text += (
                f"✅ {name}\n"
                f"🎁 جایزه دریافت شد\n\n"
            )

        else:

            text += (
                f"🔒 {name}\n"
                f"🎯 هدف: {target}\n\n"
            )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 منو",
                    callback_data="main"
                )
            ]
        ])
    )


# ============================================================
# LEADERBOARD
# ============================================================

async def leaderboard_page(update, context):

    rows = execute(
        """
        SELECT first_name, username, coins, level, wins
        FROM users
        ORDER BY coins DESC
        LIMIT 10
        """
    ).fetchall()

    text = (
        "🏆 **لیدربرد خر‌بات**\n"
        "━━━━━━━━━━━━━━\n\n"
    )

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    if not rows:

        text += "هنوز کسی بازی نکرده."

    else:

        for i, row in enumerate(rows):

            medal = medals[i] if i < 3 else f"#{i + 1}"

            name = row["first_name"] or (
                "@" + row["username"]
                if row["username"]
                else "بازیکن"
            )

            text += (
                f"{medal} **{name}**\n"
                f"   💰 {row['coins']:,} 🪙"
                f" | ⭐ Lv.{row['level']}"
                f" | 🏆 {row['wins']}\n\n"
            )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔄 بروزرسانی",
                    callback_data="leaderboard"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 منو",
                    callback_data="main"
                )
            ]
        ])
    )


# ============================================================
# COIN TRANSFER
# ============================================================

async def transfer_coins(
    update,
    context,
    target_id,
    amount
):

    sender = update.effective_user

    create_user(sender)

    if target_id == sender.id:

        await update.message.reply_text(
            "❌ نمی‌تونی به خودت سکه بدی."
        )

        return

    if amount <= 0:

        await update.message.reply_text(
            "❌ مقدار سکه باید بیشتر از صفر باشد."
        )

        return

    target = execute(
        """
        SELECT user_id, first_name
        FROM users
        WHERE user_id=?
        """,
        (target_id,)
    ).fetchone()

    if not target:

        await update.message.reply_text(
            "❌ این کاربر هنوز خر‌بات را فعال نکرده."
        )

        return

    # کارمزد کوچک برای جلوگیری از انتقال بی‌نهایت.
    fee = max(
        1,
        int(amount * 0.02)
    )

    total = amount + fee

    if not remove_coins(
        sender.id,
        total
    ):

        await update.message.reply_text(
            f"❌ سکه کافی نداری.\n"
            f"💸 مبلغ: {amount:,}\n"
            f"💰 کارمزد: {fee:,}\n"
            f"📦 نیاز: {total:,} 🪙"
        )

        return

    add_coins(
        target_id,
        amount
    )

    await update.message.reply_text(
        "💸 **انتقال موفق**\n\n"
        f"👤 گیرنده: {target['first_name']}\n"
        f"💰 مبلغ: {amount:,} 🪙\n"
        f"💸 کارمزد: {fee:,} 🪙"
    )


# ============================================================
# ADMIN SYSTEM
# ============================================================

def is_admin(user_id):

    return ADMIN_ID != 0 and user_id == ADMIN_ID


async def admin_panel(update, context):

    user = update.effective_user

    if not is_admin(user.id):

        await update.callback_query.answer(
            "⛔ دسترسی نداری.",
            show_alert=True
        )

        return

    row = execute(
        """
        SELECT
            COUNT(*) AS users,
            COALESCE(SUM(coins),0) AS coins,
            COALESCE(SUM(gems),0) AS gems,
            COALESCE(SUM(games),0) AS games
        FROM users
        """
    ).fetchone()

    text = (
        "👑 **پنل مالک خر‌بات**\n"
        "━━━━━━━━━━━━━━\n\n"
        f"👥 کاربران: **{row['users']:,}**\n"
        f"🪙 مجموع سکه‌ها: **{row['coins']:,}**\n"
        f"💎 مجموع جم‌ها: **{row['gems']:,}**\n"
        f"🎮 مجموع بازی‌ها: **{row['games']:,}**\n"
    )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📊 آمار",
                callback_data="admin_stats"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 منو",
                callback_data="main"
            )
        ]
    ])

    await update.callback_query.edit_message_text(
        text,
        reply_markup=keyboard
    )


async def admin_stats(update, context):

    user = update.effective_user

    if not is_admin(user.id):
        return

    row = execute(
        """
        SELECT
            COUNT(*) users,
            SUM(wins) wins,
            SUM(losses) losses,
            SUM(games) games
        FROM users
        """
    ).fetchone()

    text = (
        "📊 **آمار کامل ربات**\n"
        "━━━━━━━━━━━━━━\n\n"
        f"👥 کاربران: {row['users'] or 0:,}\n"
        f"🎮 بازی‌ها: {row['games'] or 0:,}\n"
        f"🏆 بردها: {row['wins'] or 0:,}\n"
        f"💀 باخت‌ها: {row['losses'] or 0:,}\n"
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 پنل مالک",
                    callback_data="admin"
                )
            ]
        ])
    )


# ============================================================
# ADMIN COMMANDS
# ============================================================

async def admin_addcoin(update, context):

    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "استفاده:\n"
            "/addcoin USER_ID AMOUNT"
        )

        return

    try:

        target_id = int(context.args[0])
        amount = int(context.args[1])

    except ValueError:

        await update.message.reply_text(
            "❌ مقدار نامعتبر."
        )

        return

    target = execute(
        "SELECT user_id FROM users WHERE user_id=?",
        (target_id,)
    ).fetchone()

    if not target:

        await update.message.reply_text(
            "❌ کاربر پیدا نشد."
        )

        return

    add_coins(
        target_id,
        amount
    )

    await update.message.reply_text(
        f"✅ {amount:,} 🪙 اضافه شد."
    )


async def admin_removecoin(update, context):

    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "استفاده:\n"
            "/removecoin USER_ID AMOUNT"
        )

        return

    try:

        target_id = int(context.args[0])
        amount = int(context.args[1])

    except ValueError:

        await update.message.reply_text(
            "❌ مقدار نامعتبر."
        )

        return

    remove_coins(
        target_id,
        amount
    )

    await update.message.reply_text(
        "✅ انجام شد."
    )


async def admin_addgem(update, context):

    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "/addgem USER_ID AMOUNT"
        )
        return

    try:

        target_id = int(context.args[0])
        amount = int(context.args[1])

    except ValueError:

        await update.message.reply_text(
            "❌ مقدار نامعتبر."
        )

        return

    add_gems(
        target_id,
        amount
    )

    await update.message.reply_text(
        f"💎 +{amount:,}"
    )


async def admin_broadcast(update, context):

    if not is_admin(update.effective_user.id):
        return

    if not context.args:

        await update.message.reply_text(
            "استفاده:\n"
            "/broadcast متن پیام"
        )

        return

    text = " ".join(context.args)

    rows = execute(
        "SELECT user_id FROM users WHERE banned=0"
    ).fetchall()

    sent = 0

    for row in rows:

        try:

            await context.bot.send_message(
                chat_id=row["user_id"],
                text=text
            )

            sent += 1

        except Exception:

            pass

    await update.message.reply_text(
        f"📢 ارسال شد به {sent} کاربر."
)
    # ============================================================
# 🎮 GAME ENGINE V3
# 🤖 BOT + 👥 GROUP + ❌ CANCEL + ⏱️ TIMEOUT
# ============================================================

import random
import time
import asyncio
from collections import defaultdict


# ============================================================
# GAME SETTINGS
# ============================================================

GAME_TIMEOUT = 90

MIN_PLAYERS = 2
MAX_PLAYERS = 6

BOT_DIFFICULTIES = {
    "easy": {
        "name": "🟢 آسان",
        "win_rate": 0.35
    },

    "normal": {
        "name": "🟡 معمولی",
        "win_rate": 0.50
    },

    "hard": {
        "name": "🔴 سخت",
        "win_rate": 0.65
    },

    "nightmare": {
        "name": "☠️ کابوس",
        "win_rate": 0.78
    }
}


# ============================================================
# ACTIVE GAMES
# ============================================================

ACTIVE_GAMES = {}

GROUP_LOBBIES = {}

USER_GAME = {}

GAME_LOCKS = defaultdict(asyncio.Lock)


# ============================================================
# GAME OBJECT
# ============================================================

class GameSession:

    def __init__(
        self,
        game_id,
        game_type,
        owner_id,
        chat_id,
        bet=0,
        difficulty="hard"
    ):

        self.game_id = game_id

        self.game_type = game_type

        self.owner_id = owner_id

        self.chat_id = chat_id

        self.bet = bet

        self.difficulty = difficulty

        self.players = []

        self.started = False

        self.finished = False

        self.cancelled = False

        self.paid = False

        self.created_at = time.time()

        self.last_action = time.time()

        self.current_turn = None

        self.round = 0

        self.data = {}

    def add_player(self, user_id):

        if self.started:
            return False

        if self.finished:
            return False

        if user_id in self.players:
            return False

        if len(self.players) >= MAX_PLAYERS:
            return False

        self.players.append(user_id)

        USER_GAME[user_id] = self.game_id

        return True

    def remove_player(self, user_id):

        if user_id not in self.players:
            return False

        self.players.remove(user_id)

        if USER_GAME.get(user_id) == self.game_id:

            del USER_GAME[user_id]

        return True

    def is_full(self):

        return len(self.players) >= MAX_PLAYERS

    def touch(self):

        self.last_action = time.time()

    def expired(self):

        return (
            time.time() - self.last_action
            >= GAME_TIMEOUT
        )


# ============================================================
# GAME ID
# ============================================================

def new_game_id():

    return (
        str(int(time.time() * 1000))
        + str(random.randint(100, 999))
    )


# ============================================================
# GAME REGISTRATION
# ============================================================

def register_game(game):

    ACTIVE_GAMES[
        game.game_id
    ] = game


def delete_game(game_id):

    game = ACTIVE_GAMES.pop(
        game_id,
        None
    )

    if not game:
        return

    for user_id in list(game.players):

        if USER_GAME.get(user_id) == game_id:

            del USER_GAME[user_id]


# ============================================================
# USER CURRENT GAME
# ============================================================

def get_user_game(user_id):

    game_id = USER_GAME.get(
        user_id
    )

    if not game_id:
        return None

    game = ACTIVE_GAMES.get(
        game_id
    )

    if not game:

        USER_GAME.pop(
            user_id,
            None
        )

        return None

    return game


# ============================================================
# BET VALIDATION
# ============================================================

def valid_bet(amount):

    if amount < 0:
        return False

    if amount > 1_000_000:
        return False

    return True


def lock_bet(user_id, amount):

    if amount <= 0:
        return True

    return remove_coins(
        user_id,
        amount
    )


def refund_bet(user_id, amount):

    if amount <= 0:
        return

    add_coins(
        user_id,
        amount
    )


# ============================================================
# GAME PAYOUT
# ============================================================

def payout_game(game, winners):

    if game.paid:
        return False

    if game.cancelled:
        return False

    game.paid = True

    if not winners:
        return False

    # مبلغ کل جایزه
    prize = game.bet * len(
        game.players
    )

    # اگر بازی بدون شرط بود
    if prize <= 0:
        return True

    # تقسیم جایزه بین برندگان
    share = max(
        1,
        prize // len(winners)
    )

    for user_id in winners:

        add_coins(
            user_id,
            share
        )

        increase_quest(
            user_id,
            "win"
        )

    return True


# ============================================================
# CANCEL GAME
# ============================================================

async def cancel_game(
    update,
    context,
    game_id=None
):

    user = update.effective_user

    if game_id:

        game = ACTIVE_GAMES.get(
            game_id
        )

    else:

        game = get_user_game(
            user.id
        )

    if not game:

        if update.callback_query:

            await update.callback_query.answer(
                "❌ بازی فعالی نداری.",
                show_alert=True
            )

        return

    # فقط بازیکن بازی
    if user.id not in game.players:

        if update.callback_query:

            await update.callback_query.answer(
                "❌ تو داخل این بازی نیستی.",
                show_alert=True
            )

        return

    # بازی هنوز شروع نشده
    if not game.started:

        # بازپرداخت
        if game.bet > 0:

            refund_bet(
                user.id,
                game.bet
            )

        game.remove_player(
            user.id
        )

        if not game.players:

            game.cancelled = True

            delete_game(
                game.game_id
            )

        if update.callback_query:

            await update.callback_query.answer(
                "❌ از بازی خارج شدی.",
                show_alert=True
            )

        return

    # اگر بازی شروع شده:
    # لغو شخصی = فرار = باخت
    if game.started and not game.finished:

        game.finished = True

        game.cancelled = True

        # بازیکن فراری جایزه نمی‌گیرد
        winners = [
            p for p in game.players
            if p != user.id
        ]

        if winners:

            payout_game(
                game,
                winners
            )

        if update.callback_query:

            await update.callback_query.answer(
                "🏳️ از بازی فرار کردی و بازی را باختی.",
                show_alert=True
            )

        delete_game(
            game.game_id
        )


# ============================================================
# GROUP LOBBY
# ============================================================

async def create_group_game(
    update,
    context,
    game_name,
    bet=0
):

    user = update.effective_user

    chat = update.effective_chat

    # فقط گروه
    if chat.type not in (
        "group",
        "supergroup"
    ):

        await update.message.reply_text(
            "❌ این بازی برای گروه طراحی شده."
        )

        return

    # کاربر بازی فعال دارد؟
    if get_user_game(user.id):

        await update.message.reply_text(
            "❌ اول بازی فعلی‌ات را تمام کن."
        )

        return

    if not valid_bet(
        bet
    ):

        await update.message.reply_text(
            "❌ مبلغ بازی نامعتبر است."
        )

        return

    if bet > 0:

        if not lock_bet(
            user.id,
            bet
        ):

            await update.message.reply_text(
                "❌ سکه کافی نداری."
            )

            return

    game_id = new_game_id()

    game = GameSession(
        game_id=game_id,
        game_type="group",
        owner_id=user.id,
        chat_id=chat.id,
        bet=bet
    )

    game.add_player(
        user.id
    )

    register_game(
        game
    )

    GROUP_LOBBIES[
        chat.id
    ] = game_id

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "➕ ورود",
                callback_data=f"join_{game_id}"
            ),

            InlineKeyboardButton(
                "🚀 شروع",
                callback_data=f"start_{game_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "❌ لغو",
                callback_data=f"cancel_{game_id}"
            )
        ]

    ])

    await update.message.reply_text(

        f"🎮 **{game_name}**\n"
        f"━━━━━━━━━━━━━━\n\n"

        f"👤 سازنده:\n"
        f"{user.first_name}\n\n"

        f"👥 بازیکنان:\n"
        f"1️⃣ {user.first_name}\n\n"

        f"👥 ظرفیت:\n"
        f"{MIN_PLAYERS} تا {MAX_PLAYERS} نفر\n\n"

        f"💰 ورودی:\n"
        f"{bet:,} 🪙\n\n"

        f"⏱️ مدت انتظار: {GAME_TIMEOUT} ثانیه\n\n"

        "برای ورود روی «➕ ورود» بزنید.",
        reply_markup=keyboard
    )


# ============================================================
# JOIN GROUP GAME
# ============================================================

async def join_group_game(
    update,
    context,
    game_id
):

    query = update.callback_query

    user = update.effective_user

    await query.answer()

    game = ACTIVE_GAMES.get(
        game_id
    )

    if not game:

        await query.answer(
            "❌ بازی تمام شده.",
            show_alert=True
        )

        return

    if game.started:

        await query.answer(
            "❌ بازی شروع شده.",
            show_alert=True
        )

        return

    if game.is_full():

        await query.answer(
            "❌ ظرفیت کامل است.",
            show_alert=True
        )

        return

    old_game = get_user_game(
        user.id
    )

    if old_game:

        await query.answer(
            "❌ تو قبلاً داخل یک بازی هستی.",
            show_alert=True
        )

        return

    if game.bet > 0:

        if not lock_bet(
            user.id,
            game.bet
        ):

            await query.answer(
                "❌ سکه کافی نداری.",
                show_alert=True
            )

            return

    game.add_player(
        user.id
    )

    game.touch()

    players_text = ""

    for i, player_id in enumerate(
        game.players,
        start=1
    ):

        try:

            member = await context.bot.get_chat_member(
                game.chat_id,
                player_id
            )

            name = member.user.first_name

        except Exception:

            name = f"بازیکن {i}"

        players_text += (
            f"{i}️⃣ {name}\n"
        )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "➕ ورود",
                callback_data=f"join_{game_id}"
            ),

            InlineKeyboardButton(
                "🚀 شروع",
                callback_data=f"start_{game_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "❌ خروج",
                callback_data=f"leave_{game_id}"
            )
        ]

    ])

    await query.edit_message_text(

        f"🎮 **لابی بازی**\n"
        f"━━━━━━━━━━━━━━\n\n"

        f"👥 بازیکنان:\n"
        f"{players_text}\n"

        f"📊 {len(game.players)}/{MAX_PLAYERS}\n"
        f"💰 ورود: {game.bet:,} 🪙\n\n"

        "وقتی آماده بودید، سازنده بازی "
        "می‌تواند آن را شروع کند.",

        reply_markup=keyboard
    )


# ============================================================
# LEAVE GROUP GAME
# ============================================================

async def leave_group_game(
    update,
    context,
    game_id
):

    query = update.callback_query

    user = update.effective_user

    game = ACTIVE_GAMES.get(
        game_id
    )

    if not game:

        await query.answer(
            "❌ بازی پیدا نشد.",
            show_alert=True
        )

        return

    if game.started:

        await query.answer(
            "❌ بازی شروع شده؛ برای خروج باید فرار کنی.",
            show_alert=True
        )

        return

    if user.id not in game.players:

        await query.answer(
            "❌ عضو این بازی نیستی.",
            show_alert=True
        )

        return

    refund_bet(
        user.id,
        game.bet
    )

    game.remove_player(
        user.id
    )

    game.touch()

    await query.answer(
        "✅ از بازی خارج شدی."
    )

    if not game.players:

        delete_game(
            game.game_id
        )

        return

    names = []

    for player_id in game.players:

        try:

            member = await context.bot.get_chat_member(
                game.chat_id,
                player_id
            )

            names.append(
                member.user.first_name
            )

        except Exception:

            names.append(
                "بازیکن"
            )

    text = (
        "🎮 **لابی بازی**\n\n"
        "👥 بازیکنان:\n"
        + "\n".join(
            f"• {name}"
            for name in names
        )
        + "\n\n"
        f"📊 {len(game.players)}/{MAX_PLAYERS}"
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "➕ ورود",
                    callback_data=f"join_{game_id}"
                ),

                InlineKeyboardButton(
                    "🚀 شروع",
                    callback_data=f"start_{game_id}"
                )
            ]
        ])
    )


# ============================================================
# START GROUP GAME
# ============================================================

async def start_group_game(
    update,
    context,
    game_id
):

    query = update.callback_query

    user = update.effective_user

    game = ACTIVE_GAMES.get(
        game_id
    )

    if not game:

        await query.answer(
            "❌ بازی پیدا نشد.",
            show_alert=True
        )

        return

    if game.owner_id != user.id:

        await query.answer(
            "⛔ فقط سازنده می‌تواند بازی را شروع کند.",
            show_alert=True
        )

        return

    if len(game.players) < MIN_PLAYERS:

        await query.answer(
            f"❌ حداقل {MIN_PLAYERS} بازیکن لازم است.",
            show_alert=True
        )

        return

    if game.started:

        await query.answer(
            "❌ بازی قبلاً شروع شده.",
            show_alert=True
        )

        return

    game.started = True

    game.round = 1

    game.touch()

    game.current_turn = game.players[0]

    await query.answer(
        "🚀 بازی شروع شد!"
    )

    await start_game_round(
        context,
        game
    )


# ============================================================
# START GAME ROUND
# ============================================================

async def start_game_round(
    context,
    game
):

    if game.finished:
        return

    game.touch()

    # بازی نمونه:
    # خرها وارد مبارزه می‌شوند.
    text = (
        "🎮 **بازی شروع شد!**\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🔄 راند: {game.round}\n\n"
    )

    for i, player_id in enumerate(
        game.players,
        start=1
    ):

        try:

            member = await context.bot.get_chat_member(
                game.chat_id,
                player_id
            )

            name = member.user.first_name

        except Exception:

            name = f"بازیکن {i}"

        text += (
            f"{i}️⃣ {name}\n"
        )

    text += (
        "\n🎯 نوبت بازیکن اول است.\n"
        "برای حرکت انتخاب کن:"
    )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "⚔️ حمله",
                callback_data=f"move_attack_{game.game_id}"
            ),

            InlineKeyboardButton(
                "🛡️ دفاع",
                callback_data=f"move_defend_{game.game_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "🎲 شانس",
                callback_data=f"move_luck_{game.game_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "🏳️ فرار",
                callback_data=f"cancel_{game.game_id}"
            )

        ]

    ])

    await context.bot.send_message(
        chat_id=game.chat_id,
        text=text,
        reply_markup=keyboard
    )


# ============================================================
# HARD BOT ENGINE
# ============================================================

def bot_should_win(
    difficulty,
    player_stats=None
):

    config = BOT_DIFFICULTIES.get(
        difficulty,
        BOT_DIFFICULTIES["hard"]
    )

    chance = config["win_rate"]

    # کمی وابستگی به قدرت خر
    if player_stats:

        power = player_stats.get(
            "power",
            1
        )

        luck = player_stats.get(
            "luck",
            1
        )

        # خر قوی‌تر، شانس برد بیشتری دارد
        chance -= min(
            0.15,
            power * 0.005
        )

        chance -= min(
            0.10,
            luck * 0.003
        )

    return random.random() < chance


def bot_choose_move(
    difficulty,
    available_moves
):

    if not available_moves:
        return None

    config = BOT_DIFFICULTIES.get(
        difficulty,
        BOT_DIFFICULTIES["hard"]
    )

    win_rate = config["win_rate"]

    # سختی بالا:
    # انتخاب حرکت بهتر
    if win_rate >= 0.65:

        return available_moves[
            random.randrange(
                len(available_moves)
            )
        ]

    return random.choice(
        available_moves
    )


# ============================================================
# BOT GAME
# ============================================================

async def create_bot_game(
    update,
    context,
    game_name,
    bet=0,
    difficulty="hard"
):

    user = update.effective_user

    if get_user_game(
        user.id
    ):

        await update.callback_query.answer(
            "❌ اول بازی فعلی را تمام کن.",
            show_alert=True
        )

        return

    if difficulty not in BOT_DIFFICULTIES:

        difficulty = "hard"

    if not valid_bet(
        bet
    ):

        await update.callback_query.answer(
            "❌ مبلغ بازی نامعتبر است.",
            show_alert=True
        )

        return

    if bet > 0:

        if not lock_bet(
            user.id,
            bet
        ):

            await update.callback_query.answer(
                "❌ سکه کافی نداری.",
                show_alert=True
            )

            return

    game_id = new_game_id()

    game = GameSession(
        game_id=game_id,
        game_type="bot",
        owner_id=user.id,
        chat_id=update.effective_chat.id,
        bet=bet,
        difficulty=difficulty
    )

    game.add_player(
        user.id
    )

    game.started = True

    game.round = 1

    game.current_turn = user.id

    register_game(
        game
    )

    await update.callback_query.answer(
        "🤖 خر‌بات وارد شد!"
    )

    await bot_start_game(
        update,
        context,
        game,
        game_name
    )


# ============================================================
# BOT START
# ============================================================

async def bot_start_game(
    update,
    context,
    game,
    game_name
):

    difficulty_name = BOT_DIFFICULTIES[
        game.difficulty
    ]["name"]

    text = (
        f"🤖 **{game_name}**\n"
        "━━━━━━━━━━━━━━\n\n"

        "🫏 حریف تو: **خر‌بات**\n"
        f"🧠 سطح: {difficulty_name}\n\n"

        f"💰 ورودی: {game.bet:,} 🪙\n\n"

        "🤖 خر‌بات بازی را شروع می‌کند!\n"
        "اما انتخاب حرکتش براساس وضعیت بازی "
        "انجام می‌شود."
    )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "⚔️ حمله",
                callback_data=f"bot_attack_{game.game_id}"
            ),

            InlineKeyboardButton(
                "🛡️ دفاع",
                callback_data=f"bot_defend_{game.game_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "🎲 حرکت شانسی",
                callback_data=f"bot_luck_{game.game_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "🏳️ فرار",
                callback_data=f"cancel_{game.game_id}"
            )
        ]

    ])

    await context.bot.send_message(
        chat_id=game.chat_id,
        text=text,
        reply_markup=keyboard
    )


# ============================================================
# BOT MOVE
# ============================================================

async def bot_move(
    update,
    context,
    game_id,
    player_move
):

    query = update.callback_query

    user = update.effective_user

    game = ACTIVE_GAMES.get(
        game_id
    )

    if not game:

        await query.answer(
            "❌ بازی تمام شده.",
            show_alert=True
        )

        return

    if game.finished:

        await query.answer(
            "❌ بازی تمام شده.",
            show_alert=True
        )

        return

    if game.owner_id != user.id:

        await query.answer(
            "❌ این بازی متعلق به تو نیست.",
            show_alert=True
        )

        return

    if game.game_type != "bot":

        return

    await query.answer()

    game.touch()

    # حرکات ممکن خر‌بات
    moves = [
        "attack",
        "defend",
        "luck"
    ]

    bot_move_result = bot_choose_move(
        game.difficulty,
        moves
    )

    player_stats = get_donkey(
        user.id
    )

    stats = {}

    if player_stats:

        stats = {
            "power": player_stats["power"],
            "luck": player_stats["luck"]
        }

    bot_wins = bot_should_win(
        game.difficulty,
        stats
    )

    if bot_wins:

        result = "bot"

    else:

        result = "player"

    # حالت مساوی
    if player_move == bot_move_result:

        result = "draw"

    if result == "bot":

        message = (
            "🤖 خر‌بات این راند را برد! 😈\n\n"
            f"👤 حرکت تو: {player_move}\n"
            f"🤖 حرکت خر‌بات: {bot_move_result}\n\n"
            "🔄 راند بعدی..."
        )

    elif result == "player":

        message = (
            "🔥 آفرین! این راند را بردی!\n\n"
            f"👤 حرکت تو: {player_move}\n"
            f"🤖 حرکت خر‌بات: {bot_move_result}\n\n"
            "🔄 راند بعدی..."
        )

    else:

        message = (
            "🤝 مساوی شد!\n\n"
            f"👤 حرکت تو: {player_move}\n"
            f"🤖 حرکت خر‌بات: {bot_move_result}\n\n"
            "🔄 راند بعدی..."
        )

    game.round += 1

    # بعد از 3 راند نتیجه نهایی
    if game.round > 3:

        game.finished = True

        if result == "player":

            add_coins(
                user.id,
                game.bet * 2
            )

            execute(
                """
                UPDATE users
                SET wins=wins+1,
                    games=games+1
                WHERE user_id=?
                """,
                (user.id,),
                commit=True
            )

            increase_quest(
                user.id,
                "games"
            )

            increase_quest(
                user.id,
                "win"
            )

            check_achievements(
                user.id
            )

            message = (
                "🏆 **بردی!**\n\n"
                f"💰 جایزه: "
                f"{game.bet * 2:,} 🪙"
            )

        elif result == "bot":

            execute(
                """
                UPDATE users
                SET losses=losses+1,
                    games=games+1
                WHERE user_id=?
                """,
                (user.id,),
                commit=True
            )

            increase_quest(
                user.id,
                "games"
            )

            check_achievements(
                user.id
            )

            message = (
                "💀 **خر‌بات برد!**\n\n"
                "دوباره تلاش کن 😈"
            )

        else:

            add_coins(
                user.id,
                game.bet
            )

            execute(
                """
                UPDATE users
                SET games=games+1
                WHERE user_id=?
                """,
                (user.id,),
                commit=True
            )

            message = (
                "🤝 **مساوی!**\n\n"
                f"💰 {game.bet:,} 🪙 برگشت داده شد."
            )

        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🔄 بازی دوباره",
                        callback_data="games"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "🏠 منو",
                        callback_data="main"
                    )
                ]

            ])
        )

        delete_game(
            game.game_id
        )

        return

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "⚔️ حمله",
                callback_data=f"bot_attack_{game.game_id}"
            ),

            InlineKeyboardButton(
                "🛡️ دفاع",
                callback_data=f"bot_defend_{game.game_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "🎲 شانس",
                callback_data=f"bot_luck_{game.game_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "🏳️ فرار",
                callback_data=f"cancel_{game.game_id}"
            )
        ]

    ])

    await query.edit_message_text(
        message,
        reply_markup=keyboard
    )


# ============================================================
# GAME TIMEOUT WATCHER
# ============================================================

async def game_timeout_watcher(
    application
):

    while True:

        await asyncio.sleep(10)

        now = time.time()

        expired_games = []

        for game_id, game in list(
            ACTIVE_GAMES.items()
        ):

            if (
                not game.finished
                and now - game.last_action >= GAME_TIMEOUT
            ):

                expired_games.append(
                    game
                )

        for game in expired_games:

            game.finished = True
            game.cancelled = True

            # بازپرداخت بازی‌هایی که شروع نشده‌اند
            if not game.started:

                for player_id in game.players:

                    refund_bet(
                        player_id,
                        game.bet
                    )

            else:

                # اگر بازی شروع شده،
                # آخرین بازیکن فعال برنده می‌شود.
                if game.current_turn:

                    winners = [
                        p for p in game.players
                        if p != game.current_turn
                    ]

                    if winners:

                        payout_game(
                            game,
                            winners
                        )

            try:

                await application.bot.send_message(
                    chat_id=game.chat_id,
                    text=(
                        "⏱️ **بازی به دلیل عدم فعالیت "
                        "لغو شد.**"
                    )
                )

            except Exception:

                pass

            delete_game(
                game.game_id
            )


# ============================================================
# GAME MENU
# ============================================================

async def games_menu(
    update,
    context
):

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🤖 بازی با خر‌بات",
                callback_data="bot_games"
            )
        ],

        [
            InlineKeyboardButton(
                "👥 بازی گروهی",
                callback_data="group_games"
            )
        ],

        [
            InlineKeyboardButton(
                "🏆 لیدربرد",
                callback_data="leaderboard"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 منو",
                callback_data="main"
            )
        ]

    ])

    text = (
        "🎮 **مرکز بازی خر‌بات**\n"
        "━━━━━━━━━━━━━━\n\n"

        "🤖 با خر‌بات بازی کن\n"
        "👥 با دوستانت داخل گروه بازی کن\n\n"

        "هر بازی سیستم شرط، زمان، "
        "لغو و جایزه خودش را دارد."
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=keyboard
        )

    else:

        await update.message.reply_text(
            text,
            reply_markup=keyboard
        )


# ============================================================
# BOT GAME DIFFICULTY MENU
# ============================================================

async def bot_games_menu(
    update,
    context
):

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🟢 آسان",
                callback_data="difficulty_easy"
            )
        ],

        [
            InlineKeyboardButton(
                "🟡 معمولی",
                callback_data="difficulty_normal"
            )
        ],

        [
            InlineKeyboardButton(
                "🔴 سخت",
                callback_data="difficulty_hard"
            )
        ],

        [
            InlineKeyboardButton(
                "☠️ کابوس",
                callback_data="difficulty_nightmare"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 برگشت",
                callback_data="games"
            )
        ]

    ])

    await update.callback_query.edit_message_text(
        "🤖 **انتخاب قدرت خر‌بات**\n\n"
        "هرچه سطح بالاتر باشد، "
        "خر‌بات تصمیم‌های بهتری می‌گیرد.\n\n"
        "☠️ کابوس برای بازیکن‌های حرفه‌ای است.",
        reply_markup=keyboard
    )


# ============================================================
# GROUP GAME MENU
# ============================================================

async def group_games_menu(
    update,
    context
):

    await update.callback_query.edit_message_text(

        "👥 **بازی گروهی**\n\n"

        "برای شروع یکی از بازی‌ها را "
        "در گروه ارسال کن.\n\n"

        "مثال:\n"
        "`سنگ کاغذ قیچی`\n"
        "`دوز`\n"
        "`جنگ خرها`\n"
        "`حدس عدد`\n\n"

        "سپس بازیکنان با دکمه ورود "
        "به لابی اضافه می‌شوند.",

        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 برگشت",
                    callback_data="games"
                )
            ]
        ])
    )


# ============================================================
# CALLBACK ROUTER FOR GAME SYSTEM
# ============================================================

async def game_callback_router(
    update,
    context
):

    query = update.callback_query

    data = query.data

    if data.startswith(
        "cancel_"
    ):

        game_id = data.split(
            "_",
            1
        )[1]

        await cancel_game(
            update,
            context,
            game_id
        )

        return

    if data.startswith(
        "join_"
    ):

        game_id = data.split(
            "_",
            1
        )[1]

        await join_group_game(
            update,
            context,
            game_id
        )

        return

    if data.startswith(
        "leave_"
    ):

        game_id = data.split(
            "_",
            1
        )[1]

        await leave_group_game(
            update,
            context,
            game_id
        )

        return

    if data.startswith(
        "start_"
    ):

        game_id = data.split(
            "_",
            1
        )[1]

        await start_group_game(
            update,
            context,
            game_id
        )

        return

    if data.startswith(
        "bot_attack_"
    ):

        game_id = data.split(
            "bot_attack_",
            1
        )[1]

        await bot_move(
            update,
            context,
            game_id,
            "attack"
        )

        return

    if data.startswith(
        "bot_defend_"
    ):

        game_id = data.split(
            "bot_defend_",
            1
        )[1]

        await bot_move(
            update,
            context,
            game_id,
            "defend"
        )

        return

    if data.startswith(
        "bot_luck_"
    ):

        game_id = data.split(
            "bot_luck_",
            1
        )[1]

        await bot_move(
            update,
            context,
            game_id,
            "luck"
        )

        return

    if data.startswith(
        "move_"
    ):

        move = data.split(
            "_",
            1
        )[1]

        game = get_user_game(
            update.effective_user.id
        )

        if not game:
            return

        game.touch()

        await query.answer(
            f"حرکت: {move}"
        )

        return

    if data == "games":

        await games_menu(
            update,
            context
        )

        return

    if data == "bot_games":

        await bot_games_menu(
            update,
            context
        )

        return

    if data == "group_games":

        await group_games_menu(
            update,
            context
        )

        return

    if data.startswith(
        "difficulty_"
    ):

        difficulty = data.split(
            "_",
            1
        )[1]

        # بازی نمونه با خر‌بات
        await create_bot_game(
            update,
            context,
            "جنگ خرها",
            bet=100,
            difficulty=difficulty
        )

        return 
# ============================================================
# 🎮 KHARBOT GAMES V4
# 10 MINI GAMES
# ============================================================

# ------------------------------------------------------------
# GAME DEFINITIONS
# ------------------------------------------------------------

GAME_LIST = {
    "rps": {
        "name": "🪨 سنگ کاغذ قیچی",
        "emoji": "🪨"
    },

    "guess": {
        "name": "🎯 حدس عدد",
        "emoji": "🎯"
    },

    "dice": {
        "name": "🎲 تاس",
        "emoji": "🎲"
    },

    "higher": {
        "name": "📈 بالاتر یا پایین‌تر",
        "emoji": "📈"
    },

    "coin": {
        "name": "🪙 شیر یا خط",
        "emoji": "🪙"
    },

    "duel": {
        "name": "⚔️ دوئل خرها",
        "emoji": "⚔️"
    },

    "race": {
        "name": "🏁 مسابقه خرها",
        "emoji": "🏁"
    },

    "memory": {
        "name": "🧠 حافظه",
        "emoji": "🧠"
    },

    "number": {
        "name": "🔢 عدد مخفی",
        "emoji": "🔢"
    },

    "reaction": {
        "name": "⚡ واکنش سریع",
        "emoji": "⚡"
    }
}


# ------------------------------------------------------------
# GAME SELECT MENU
# ------------------------------------------------------------

async def show_all_games(update, context):

    keyboard = []

    for game_id, game in GAME_LIST.items():

        keyboard.append([
            InlineKeyboardButton(
                game["name"],
                callback_data=f"selectgame_{game_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 برگشت",
            callback_data="games"
        )
    ])

    text = (
        "🎮 **مرکز بازی خر‌بات**\n"
        "━━━━━━━━━━━━━━\n\n"
        "یک بازی انتخاب کن:"
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    else:

        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# ------------------------------------------------------------
# GAME MODE MENU
# ------------------------------------------------------------

async def select_game_mode(
    update,
    context,
    game_id
):

    game = GAME_LIST.get(game_id)

    if not game:

        await update.callback_query.answer(
            "❌ بازی پیدا نشد.",
            show_alert=True
        )

        return

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🤖 بازی با خر‌بات",
                callback_data=f"single_{game_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "👥 بازی گروهی",
                callback_data=f"group_{game_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 برگشت",
                callback_data="allgames"
            )
        ]

    ])

    await update.callback_query.edit_message_text(

        f"{game['emoji']} **{game['name']}**\n"
        "━━━━━━━━━━━━━━\n\n"

        "نوع بازی را انتخاب کن:",

        reply_markup=keyboard
    )


# ============================================================
# GAME 1
# 🪨 ROCK PAPER SCISSORS
# ============================================================

RPS_MOVES = {
    "rock": "🪨 سنگ",
    "paper": "📄 کاغذ",
    "scissors": "✂️ قیچی"
}


def rps_result(player, bot):

    if player == bot:
        return "draw"

    wins = {
        ("rock", "scissors"),
        ("scissors", "paper"),
        ("paper", "rock")
    }

    if (player, bot) in wins:
        return "player"

    return "bot"


async def start_rps(
    update,
    context,
    game_id=None
):

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🪨 سنگ",
                callback_data="rps_rock"
            ),

            InlineKeyboardButton(
                "📄 کاغذ",
                callback_data="rps_paper"
            )
        ],

        [
            InlineKeyboardButton(
                "✂️ قیچی",
                callback_data="rps_scissors"
            )
        ],

        [
            InlineKeyboardButton(
                "🏳️ فرار",
                callback_data=f"cancel_{game_id}"
                if game_id else "main"
            )
        ]
    ])

    await update.callback_query.edit_message_text(

        "🪨 **سنگ کاغذ قیچی**\n\n"
        "حرکتت را انتخاب کن:",

        reply_markup=keyboard
    )


async def play_rps(
    update,
    context,
    player_move
):

    query = update.callback_query

    user_id = update.effective_user.id

    game = get_user_game(user_id)

    if not game:
        await query.answer(
            "❌ بازی فعال نیست.",
            show_alert=True
        )
        return

    bot = random.choice(
        list(RPS_MOVES.keys())
    )

    result = rps_result(
        player_move,
        bot
    )

    if result == "player":

        text = (
            "🏆 **بردی!**\n\n"
            f"👤 تو: {RPS_MOVES[player_move]}\n"
            f"🤖 خر‌بات: {RPS_MOVES[bot]}"
        )

    elif result == "bot":

        text = (
            "💀 **خر‌بات برد!**\n\n"
            f"👤 تو: {RPS_MOVES[player_move]}\n"
            f"🤖 خر‌بات: {RPS_MOVES[bot]}"
        )

    else:

        text = (
            "🤝 **مساوی!**\n\n"
            f"👤 تو: {RPS_MOVES[player_move]}\n"
            f"🤖 خر‌بات: {RPS_MOVES[bot]}"
        )

    await finish_single_game(
        update,
        game,
        result,
        text
    )


# ============================================================
# GAME 2
# 🎯 GUESS NUMBER
# ============================================================

async def start_guess_game(
    update,
    context,
    game_id
):

    number = random.randint(
        1,
        10
    )

    game = ACTIVE_GAMES.get(
        game_id
    )

    if not game:
        return

    game.data["number"] = number

    keyboard = []

    row = []

    for number in range(1, 11):

        row.append(
            InlineKeyboardButton(
                str(number),
                callback_data=f"guess_{number}"
            )
        )

        if len(row) == 5:

            keyboard.append(row)

            row = []

    if row:
        keyboard.append(row)

    keyboard.append([

        InlineKeyboardButton(
            "🏳️ فرار",
            callback_data=f"cancel_{game_id}"
        )

    ])

    await update.callback_query.edit_message_text(

        "🎯 **حدس عدد**\n\n"
        "خر‌بات یک عدد بین ۱ تا ۱۰ انتخاب کرده.\n"
        "عدد درست را پیدا کن:",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


async def play_guess(
    update,
    context,
    number
):

    query = update.callback_query

    user_id = update.effective_user.id

    game = get_user_game(
        user_id
    )

    if not game:
        return

    correct = game.data.get(
        "number"
    )

    if number == correct:

        result = "player"

        text = (
            "🎯🔥 **درست حدس زدی!**\n\n"
            f"عدد: `{number}`"
        )

    else:

        result = "bot"

        text = (
            "💀 **اشتباه بود!**\n\n"
            f"انتخاب تو: {number}\n"
            "عدد مخفی درست نبود."
        )

    await finish_single_game(
        update,
        game,
        result,
        text
    )


# ============================================================
# GAME 3
# 🎲 DICE
# ============================================================

async def start_dice_game(
    update,
    context,
    game_id
):

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🎲 پرتاب تاس",
                callback_data="roll_dice"
            )
        ],

        [
            InlineKeyboardButton(
                "🏳️ فرار",
                callback_data=f"cancel_{game_id}"
            )
        ]

    ])

    await update.callback_query.edit_message_text(

        "🎲 **دوئل تاس**\n\n"
        "هرکس عدد بالاتری بیاورد برنده است.\n\n"
        "آماده‌ای؟",

        reply_markup=keyboard
    )


async def play_dice(
    update,
    context
):

    query = update.callback_query

    user_id = update.effective_user.id

    game = get_user_game(user_id)

    if not game:
        return

    player = random.randint(
        1,
        6
    )

    bot = random.randint(
        1,
        6
    )

    if player > bot:
        result = "player"

    elif bot > player:
        result = "bot"

    else:
        result = "draw"

    text = (
        "🎲 **نتیجه تاس**\n\n"
        f"👤 تو: {player}\n"
        f"🤖 خر‌بات: {bot}\n\n"
    )

    if result == "player":
        text += "🏆 بردی!"

    elif result == "bot":
        text += "💀 خر‌بات برد!"

    else:
        text += "🤝 مساوی!"

    await finish_single_game(
        update,
        game,
        result,
        text
    )


# ============================================================
# GAME 4
# 📈 HIGHER / LOWER
# ============================================================

async def start_higher_game(
    update,
    context,
    game_id
):

    current = random.randint(
        1,
        9
    )

    game = ACTIVE_GAMES.get(
        game_id
    )

    if not game:
        return

    game.data["current"] = current

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "⬆️ بالاتر",
                callback_data="higher_up"
            ),

            InlineKeyboardButton(
                "⬇️ پایین‌تر",
                callback_data="higher_down"
            )
        ],

        [
            InlineKeyboardButton(
                "🏳️ فرار",
                callback_data=f"cancel_{game_id}"
            )
        ]

    ])

    await update.callback_query.edit_message_text(

        f"📈 **بالاتر یا پایین‌تر**\n\n"
        f"عدد فعلی: **{current}**\n\n"
        "عدد بعدی بالاتر است یا پایین‌تر؟",

        reply_markup=keyboard
    )


async def play_higher(
    update,
    context,
    choice
):

    query = update.callback_query

    game = get_user_game(
        update.effective_user.id
    )

    if not game:
        return

    current = game.data.get(
        "current",
        5
    )

    next_number = random.randint(
        1,
        10
    )

    if next_number == current:

        result = "draw"

    elif (
        choice == "up"
        and next_number > current
    ):

        result = "player"

    elif (
        choice == "down"
        and next_number < current
    ):

        result = "player"

    else:

        result = "bot"

    text = (
        "📈 **نتیجه**\n\n"
        f"عدد قبلی: {current}\n"
        f"عدد جدید: {next_number}\n\n"
    )

    if result == "player":
        text += "🏆 درست گفتی!"

    elif result == "bot":
        text += "💀 اشتباه بود!"

    else:
        text += "🤝 مساوی!"

    await finish_single_game(
        update,
        game,
        result,
        text
    )


# ============================================================
# GAME 5
# 🪙 COIN FLIP
# ============================================================

async def start_coin_game(
    update,
    context,
    game_id
):

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🦁 شیر",
                callback_data="coin_heads"
            ),

            InlineKeyboardButton(
                "🪙 خط",
                callback_data="coin_tails"
            )
        ],

        [
            InlineKeyboardButton(
                "🏳️ فرار",
                callback_data=f"cancel_{game_id}"
            )
        ]

    ])

    await update.callback_query.edit_message_text(

        "🪙 **شیر یا خط**\n\n"
        "انتخاب کن:",

        reply_markup=keyboard
    )


async def play_coin(
    update,
    context,
    choice
):

    game = get_user_game(
        update.effective_user.id
    )

    if not game:
        return

    result_coin = random.choice([
        "heads",
        "tails"
    ])

    result = (
        "player"
        if choice == result_coin
        else "bot"
    )

    text = (
        "🪙 **نتیجه**\n\n"
        f"نتیجه: "
        f"{'🦁 شیر' if result_coin == 'heads' else '🪙 خط'}\n\n"
    )

    text += (
        "🏆 بردی!"
        if result == "player"
        else
        "💀 باختی!"
    )

    await finish_single_game(
        update,
        game,
        result,
        text
    )


# ============================================================
# GAME 6
# ⚔️ DONKEY DUEL
# ============================================================

async def start_duel_game(
    update,
    context,
    game_id
):

    game = ACTIVE_GAMES.get(
        game_id
    )

    if not game:
        return

    game.data["player_hp"] = 100
    game.data["bot_hp"] = 100

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "⚔️ حمله",
                callback_data="duel_attack"
            )
        ],

        [
            InlineKeyboardButton(
                "🛡️ دفاع",
                callback_data="duel_defend"
            )
        ],

        [
            InlineKeyboardButton(
                "💥 ضربه ویژه",
                callback_data="duel_special"
            )
        ],

        [
            InlineKeyboardButton(
                "🏳️ فرار",
                callback_data=f"cancel_{game_id}"
            )
        ]

    ])

    await update.callback_query.edit_message_text(

        "⚔️ **دوئل خرها**\n"
        "━━━━━━━━━━━━━━\n\n"

        "👤 خر تو: ❤️ 100\n"
        "🤖 خر‌بات: ❤️ 100\n\n"

        "حرکتت را انتخاب کن:",

        reply_markup=keyboard
    )


async def play_duel(
    update,
    context,
    move
):

    game = get_user_game(
        update.effective_user.id
    )

    if not game:
        return

    player_hp = game.data.get(
        "player_hp",
        100
    )

    bot_hp = game.data.get(
        "bot_hp",
        100
    )

    if move == "attack":

        damage = random.randint(
            10,
            25
        )

        bot_hp -= damage

    elif move == "special":

        damage = random.randint(
            20,
            40
        )

        bot_hp -= damage

    else:

        damage = random.randint(
            3,
            10
        )

        bot_hp -= damage

    # Bot turn
    bot_damage = random.randint(
        8,
        25
    )

    if move == "defend":

        bot_damage //= 2

    player_hp -= bot_damage

    game.data["player_hp"] = max(
        0,
        player_hp
    )

    game.data["bot_hp"] = max(
        0,
        bot_hp
    )

    if bot_hp <= 0:

        result = "player"

    elif player_hp <= 0:

        result = "bot"

    else:

        result = "continue"

    if result == "continue":

        text = (
            "⚔️ **دوئل ادامه دارد**\n\n"
            f"👤 ❤️ {max(0, player_hp)}\n"
            f"🤖 ❤️ {max(0, bot_hp)}\n\n"
            f"💥 ضربه تو: {damage}\n"
            f"🤖 ضربه خر‌بات: {bot_damage}"
        )

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "⚔️ حمله",
                    callback_data="duel_attack"
                ),

                InlineKeyboardButton(
                    "🛡️ دفاع",
                    callback_data="duel_defend"
                )
            ],

            [
                InlineKeyboardButton(
                    "💥 ویژه",
                    callback_data="duel_special"
                )
            ],

            [
                InlineKeyboardButton(
                    "🏳️ فرار",
                    callback_data=f"cancel_{game.game_id}"
                )
            ]

        ])

        await update.callback_query.edit_message_text(
            text,
            reply_markup=keyboard
        )

        return

    text = (
        "🏆 **دوئل تمام شد**\n\n"
        f"👤 ❤️ {max(0, player_hp)}\n"
        f"🤖 ❤️ {max(0, bot_hp)}\n\n"
    )

    text += (
        "🔥 تو بردی!"
        if result == "player"
        else
        "💀 خر‌بات برد!"
    )

    await finish_single_game(
        update,
        game,
        result,
        text
    )


# ============================================================
# GAME 7
# 🏁 DONKEY RACE
# ============================================================

async def start_race_game(
    update,
    context,
    game_id
):

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🏁 شروع مسابقه",
                callback_data="race_start"
            )
        ],

        [
            InlineKeyboardButton(
                "🏳️ فرار",
                callback_data=f"cancel_{game_id}"
            )
        ]

    ])

    await update.callback_query.edit_message_text(

        "🏁 **مسابقه خرها**\n\n"
        "خر تو در مقابل خر‌بات.\n\n"
        "برای شروع آماده‌ای؟",

        reply_markup=keyboard
    )


async def play_race(
    update,
    context
):

    game = get_user_game(
        update.effective_user.id
    )

    if not game:
        return

    player = random.randint(
        1,
        100
    )

    bot = random.randint(
        1,
        100
    )

    if player > bot:
        result = "player"

    elif bot > player:
        result = "bot"

    else:
        result = "draw"

    text = (
        "🏁 **نتیجه مسابقه**\n\n"
        f"👤 خر تو: {player} متر\n"
        f"🤖 خر‌بات: {bot} متر\n\n"
    )

    if result == "player":
        text += "🏆 خر تو برنده شد!"

    elif result == "bot":
        text += "💀 خر‌بات جلو زد!"

    else:
        text += "🤝 مساوی!"

    await finish_single_game(
        update,
        game,
        result,
        text
    )


# ============================================================
# GAME 8
# 🧠 MEMORY
# ============================================================

async def start_memory_game(
    update,
    context,
    game_id
):

    game = ACTIVE_GAMES.get(
        game_id
    )

    if not game:
        return

    numbers = random.sample(
        range(1, 10),
        3
    )

    game.data["memory"] = numbers

    text = (
        "🧠 **بازی حافظه**\n\n"
        "این اعداد را به خاطر بسپار:\n\n"
        f"🔢 {' - '.join(map(str, numbers))}\n\n"
        "حالا آماده شو..."
    )

    await update.callback_query.edit_message_text(
        text
    )

    await asyncio.sleep(2)

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                str(i),
                callback_data=f"memory_{i}"
            )
            for i in range(1, 10)
        ]

    ])

    await context.bot.send_message(

        chat_id=game.chat_id,

        text=(
            "🧠 عدد اولی که یادت مانده "
            "را انتخاب کن:"
        ),

        reply_markup=keyboard
    )


async def play_memory(
    update,
    context,
    number
):

    game = get_user_game(
        update.effective_user.id
    )

    if not game:
        return

    memory = game.data.get(
        "memory",
        []
    )

    result = (
        "player"
        if number in memory
        else
        "bot"
    )

    text = (
        "🧠 **نتیجه حافظه**\n\n"
        f"انتخاب تو: {number}\n"
        f"اعداد: {', '.join(map(str, memory))}\n\n"
    )

    text += (
        "🏆 حافظه‌ات خوب بود!"
        if result == "player"
        else
        "💀 اشتباه کردی!"
    )

    await finish_single_game(
        update,
        game,
        result,
        text
    )


# ============================================================
# GAME 9
# 🔢 HIDDEN NUMBER
# ============================================================

async def start_hidden_number(
    update,
    context,
    game_id
):

    game = ACTIVE_GAMES.get(
        game_id
    )

    if not game:
        return

    secret = random.randint(
        1,
        20
    )

    game.data["secret"] = secret

    keyboard = []

    for start in range(
        1,
        21,
        5
    ):

        row = []

        for i in range(
            start,
            min(start + 5, 21)
        ):

            row.append(
                InlineKeyboardButton(
                    str(i),
                    callback_data=f"hidden_{i}"
                )
            )

        keyboard.append(row)

    keyboard.append([

        InlineKeyboardButton(
            "🏳️ فرار",
            callback_data=f"cancel_{game_id}"
        )

    ])

    await update.callback_query.edit_message_text(

        "🔢 **عدد مخفی**\n\n"
        "یک عدد بین ۱ تا ۲۰ انتخاب شده.\n"
        "پیداش کن!",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


async def play_hidden(
    update,
    context,
    number
):

    game = get_user_game(
        update.effective_user.id
    )

    if not game:
        return

    secret = game.data.get(
        "secret"
    )

    if number == secret:

        result = "player"

        text = (
            "🎯🔥 **پیداش کردی!**\n\n"
            f"عدد مخفی: {secret}"
        )

    else:

        result = "bot"

        hint = (
            "بزرگ‌تره 📈"
            if number < secret
            else
            "کوچک‌تره 📉"
        )

        text = (
            "❌ اشتباه!\n\n"
            f"عدد انتخابی: {number}\n"
            f"راهنما: {hint}"
        )

    await finish_single_game(
        update,
        game,
        result,
        text
    )


# ============================================================
# GAME 10
# ⚡ REACTION
# ============================================================

async def start_reaction_game(
    update,
    context,
    game_id
):

    delay = random.uniform(
        1.5,
        4.0
    )

    game = ACTIVE_GAMES.get(
        game_id
    )

    if not game:
        return

    game.data["reaction_ready"] = False

    await update.callback_query.edit_message_text(
        "⚡ **آماده باش...**\n\n"
        "وقتی علامت ظاهر شد سریع بزن!"
    )

    await asyncio.sleep(
        delay
    )

    game.data["reaction_ready"] = True
    game.touch()

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "⚡ الان!",
                callback_data="reaction_hit"
            )
        ]

    ])

    await context.bot.send_message(

        chat_id=game.chat_id,

        text="⚡⚡⚡ **بزن!**",

        reply_markup=keyboard
    )


async def play_reaction(
    update,
    context
):

    game = get_user_game(
        update.effective_user.id
    )

    if not game:
        return

    if not game.data.get(
        "reaction_ready"
    ):

        result = "bot"

        text = (
            "❌ زود زدی!\n\n"
            "باید منتظر علامت می‌موندی."
        )

    else:

        result = "player"

        text = (
            "⚡🔥 **سریع بودی!**\n\n"
            "🏆 برنده شدی!"
        )

    await finish_single_game(
        update,
        game,
        result,
        text
    )


# ============================================================
# FINISH SINGLE PLAYER GAME
# ============================================================

async def finish_single_game(
    update,
    game,
    result,
    text
):

    if game.finished:
        return

    game.finished = True

    user_id = update.effective_user.id

    if result == "player":

        # جایزه
        prize = game.bet * 2

        if prize > 0:

            add_coins(
                user_id,
                prize
            )

        execute(
            """
            UPDATE users
            SET wins = wins + 1,
                games = games + 1
            WHERE user_id = ?
            """,
            (user_id,),
            commit=True
        )

        increase_quest(
            user_id,
            "win"
        )

        check_achievements(
            user_id
        )

        text += (
            f"\n\n💰 جایزه: "
            f"{prize:,} 🪙"
        )

    elif result == "bot":

        execute(
            """
            UPDATE users
            SET losses = losses + 1,
                games = games + 1
            WHERE user_id = ?
            """,
            (user_id,),
            commit=True
        )

        increase_quest(
            user_id,
            "games"
        )

        check_achievements(
            user_id
        )

    else:

        # مساوی = برگشت شرط
        refund_bet(
            user_id,
            game.bet
        )

        execute(
            """
            UPDATE users
            SET games = games + 1
            WHERE user_id = ?
            """,
            (user_id,),
            commit=True
        )

        text += (
            f"\n\n💰 شرط {game.bet:,} 🪙 برگشت داده شد."
        )

    await update.callback_query.edit_message_text(

        text,

        reply_markup=InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "🔄 بازی دوباره",
                    callback_data="allgames"
                )
            ],

            [
                InlineKeyboardButton(
                    "🎮 بازی‌ها",
                    callback_data="allgames"
                ),

                InlineKeyboardButton(
                    "🏠 منو",
                    callback_data="main"
                )
            ]

        ])
    )

    delete_game(
        game.game_id
    )


# ============================================================
# START SELECTED GAME
# ============================================================

async def start_selected_game(
    update,
    context,
    game_id
):

    user = update.effective_user

    if get_user_game(user.id):

        await update.callback_query.answer(
            "❌ اول بازی فعلی‌ات را تمام کن.",
            show_alert=True
        )

        return

    # مبلغ پایه
    bet = 100

    if not lock_bet(
        user.id,
        bet
    ):

        await update.callback_query.answer(
            "❌ حداقل 100 سکه لازم داری.",
            show_alert=True
        )

        return

    session_id = new_game_id()

    game = GameSession(
        game_id=session_id,
        game_type="bot",
        owner_id=user.id,
        chat_id=update.effective_chat.id,
        bet=bet,
        difficulty="hard"
    )

    game.add_player(
        user.id
    )

    game.started = True

    register_game(
        game
    )

    # انتخاب بازی
    if game_id == "rps":
        await start_rps(
            update,
            context,
            session_id
        )

    elif game_id == "guess":
        await start_guess_game(
            update,
            context,
            session_id
        )

    elif game_id == "dice":
        await start_dice_game(
            update,
            context,
            session_id
        )

    elif game_id == "higher":
        await start_higher_game(
            update,
            context,
            session_id
        )

    elif game_id == "coin":
        await start_coin_game(
            update,
            context,
            session_id
        )

    elif game_id == "duel":
        await start_duel_game(
            update,
            context,
            session_id
        )

    elif game_id == "race":
        await start_race_game(
            update,
            context,
            session_id
        )

    elif game_id == "memory":
        await start_memory_game(
            update,
            context,
            session_id
        )

    elif game_id == "number":
        await start_hidden_number(
            update,
            context,
            session_id
        )

    elif game_id == "reaction":
        await start_reaction_game(
            update,
            context,
            session_id
        )

    else:

        refund_bet(
            user.id,
            bet
        )

        delete_game(
            session_id
        )

        await update.callback_query.answer(
            "❌ بازی ناشناخته است.",
            show_alert=True
        )


# ============================================================
# GROUP GAME CREATOR
# ============================================================

async def start_group_selected_game(
    update,
    context,
    game_id
):

    game = GAME_LIST.get(
        game_id
    )

    if not game:
        return

    await create_group_game(
        update,
        context,
        game["name"],
        bet=100
    )


# ============================================================
# GAME CALLBACK EXTENSION
# ============================================================

async def games_callback_v4(
    update,
    context
):

    query = update.callback_query

    data = query.data

    # همه بازی‌ها
    if data == "allgames":

        await show_all_games(
            update,
            context
        )

        return True

    # انتخاب بازی
    if data.startswith(
        "selectgame_"
    ):

        game_id = data.split(
            "_",
            1
        )[1]

        await select_game_mode(
            update,
            context,
            game_id
        )

        return True

    # بازی تک نفره
    if data.startswith(
        "single_"
    ):

        game_id = data.split(
            "_",
            1
        )[1]

        await start_selected_game(
            update,
            context,
            game_id
        )

        return True

    # بازی گروهی
    if data.startswith(
        "group_"
    ):

        game_id = data.split(
            "_",
            1
        )[1]

        await start_group_selected_game(
            update,
            context,
            game_id
        )

        return True

    # RPS
    if data.startswith("rps_"):

        move = data.split(
            "_",
            1
        )[1]

        await play_rps(
            update,
            context,
            move
        )

        return True

    # Guess
    if data.startswith("guess_"):

        number = int(
            data.split(
                "_",
                1
            )[1]
        )

        await play_guess(
            update,
            context,
            number
        )

        return True

    # Dice
    if data == "roll_dice":

        await play_dice(
            update,
            context
        )

        return True

    # Higher
    if data == "higher_up":

        await play_higher(
            update,
            context,
            "up"
        )

        return True

    if data == "higher_down":

        await play_higher(
            update,
            context,
            "down"
        )

        return True

    # Coin
    if data == "coin_heads":

        await play_coin(
            update,
            context,
            "heads"
        )

        return True

    if data == "coin_tails":

        await play_coin(
            update,
            context,
            "tails"
        )

        return True

    # Duel
    if data.startswith("duel_"):

        move = data.split(
            "_",
            1
        )[1]

        await play_duel(
            update,
            context,
            move
        )

        return True

    # Race
    if data == "race_start":

        await play_race(
            update,
            context
        )

        return True

    # Memory
    if data.startswith("memory_"):

        number = int(
            data.split(
                "_",
                1
            )[1]
        )

        await play_memory(
            update,
            context,
            number
        )

        return True

    # Hidden
    if data.startswith("hidden_"):

        number = int(
            data.split(
                "_",
                1
            )[1]
        )

        await play_hidden(
            update,
            context,
            number
        )

        return True

    # Reaction
    if data == "reaction_hit":

        await play_reaction(
            update,
            context
        )

        return True

    return False
    # ============================================================
# KHARBOT V5
# 👥 GROUP GAME ENGINE
# ============================================================

GROUP_MIN_PLAYERS = 2
GROUP_MAX_PLAYERS = 8

GROUP_JOIN_TIME = 45
GROUP_TURN_TIME = 30


# ============================================================
# GROUP GAME SESSION
# ============================================================

class GroupGame:

    def __init__(
        self,
        game_id,
        game_type,
        chat_id,
        creator_id,
        bet
    ):

        self.game_id = game_id
        self.game_type = game_type
        self.chat_id = chat_id
        self.creator_id = creator_id

        self.bet = bet

        self.players = {}

        self.started = False
        self.finished = False

        self.created_at = time.time()

        self.current_turn = 0

        self.data = {}

        self.message_id = None

    def add_player(
        self,
        user_id,
        name
    ):

        if self.started:
            return False

        if len(self.players) >= GROUP_MAX_PLAYERS:
            return False

        if user_id in self.players:
            return False

        self.players[user_id] = {

            "id": user_id,

            "name": name,

            "score": 0,

            "hp": 100,

            "alive": True,

            "joined_at": time.time()
        }

        return True

    def remove_player(
        self,
        user_id
    ):

        if user_id in self.players:

            del self.players[user_id]

            return True

        return False

    def player_count(self):

        return len(self.players)

    def get_players(self):

        return list(
            self.players.values()
        )

    def alive_players(self):

        return [
            p for p in self.players.values()
            if p["alive"]
        ]


# ============================================================
# GROUP GAMES STORAGE
# ============================================================

GROUP_GAMES = {}


# ============================================================
# CREATE GROUP GAME
# ============================================================

async def create_group_game(
    update,
    context,
    game_name,
    bet=100
):

    user = update.effective_user

    chat = update.effective_chat

    # فقط گروه
    if chat.type not in (
        "group",
        "supergroup"
    ):

        await update.callback_query.answer(

            "❌ این بازی فقط داخل گروه قابل اجراست.",

            show_alert=True
        )

        return

    # بررسی بازی فعال سازنده
    for game in GROUP_GAMES.values():

        if (
            user.id in game.players
            and not game.finished
        ):

            await update.callback_query.answer(

                "❌ تو همین الان داخل یک بازی هستی.",

                show_alert=True
            )

            return

    # ساخت شناسه
    game_id = (
        f"GRP_"
        f"{chat.id}_"
        f"{int(time.time())}_"
        f"{random.randint(1000,9999)}"
    )

    # ساخت بازی
    game = GroupGame(

        game_id=game_id,

        game_type=game_name,

        chat_id=chat.id,

        creator_id=user.id,

        bet=bet
    )

    # پرداخت ورودی
    if not remove_coins(
        user.id,
        bet
    ):

        await update.callback_query.answer(

            "❌ سکه کافی نداری.",

            show_alert=True
        )

        return

    # اضافه کردن سازنده
    game.add_player(

        user.id,

        user.first_name or "بازیکن"
    )

    GROUP_GAMES[game_id] = game

    # دکمه‌ها
    keyboard = group_lobby_keyboard(
        game_id
    )

    message = await update.callback_query.edit_message_text(

        group_lobby_text(
            game
        ),

        reply_markup=keyboard
    )

    game.message_id = message.message_id

    # شروع تایمر
    asyncio.create_task(

        group_lobby_timer(
            context,
            game_id
        )
    )


# ============================================================
# GROUP LOBBY TEXT
# ============================================================

def group_lobby_text(
    game
):

    players = game.get_players()

    lines = [

        "🎮 **بازی گروهی خر‌بات**",

        "━━━━━━━━━━━━━━━━",

        f"🎯 بازی: **{game.game_type}**",

        f"💰 ورودی: **{game.bet:,} 🪙**",

        "",

        f"👥 بازیکنان "
        f"({len(players)}/{GROUP_MAX_PLAYERS})",

    ]

    for index, player in enumerate(
        players,
        1
    ):

        crown = (
            " 👑"
            if player["id"]
            == game.creator_id
            else ""
        )

        lines.append(

            f"{index}. "
            f"{player['name']}"
            f"{crown}"
        )

    lines += [

        "",

        "━━━━━━━━━━━━━━━━",

        "⏳ منتظر بازیکنان...",

        "حداقل بازیکن: "
        f"{GROUP_MIN_PLAYERS}",

    ]

    return "\n".join(lines)


# ============================================================
# GROUP LOBBY KEYBOARD
# ============================================================

def group_lobby_keyboard(
    game_id
):

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton(

                "🎮 ورود به بازی",

                callback_data=
                f"join_group_{game_id}"
            )

        ],

        [

            InlineKeyboardButton(

                "▶️ شروع بازی",

                callback_data=
                f"start_group_{game_id}"
            )

        ],

        [

            InlineKeyboardButton(

                "❌ لغو بازی",

                callback_data=
                f"cancel_group_{game_id}"
            )

        ]

    ])


# ============================================================
# JOIN GROUP GAME
# ============================================================

async def join_group_game(
    update,
    context,
    game_id
):

    query = update.callback_query

    user = update.effective_user

    game = GROUP_GAMES.get(
        game_id
    )

    if not game:

        await query.answer(

            "❌ این بازی دیگر وجود ندارد.",

            show_alert=True
        )

        return

    if game.finished:

        await query.answer(

            "❌ بازی تمام شده.",

            show_alert=True
        )

        return

    if game.started:

        await query.answer(

            "❌ بازی شروع شده.",

            show_alert=True
        )

        return

    if user.id in game.players:

        await query.answer(

            "✅ قبلاً وارد بازی شدی.",

            show_alert=True
        )

        return

    if game.player_count() >= GROUP_MAX_PLAYERS:

        await query.answer(

            "❌ ظرفیت بازی تکمیل شده.",

            show_alert=True
        )

        return

    # بررسی سکه
    if not remove_coins(
        user.id,
        game.bet
    ):

        await query.answer(

            f"❌ برای ورود "
            f"{game.bet:,} 🪙 لازم داری.",

            show_alert=True
        )

        return

    # ورود
    game.add_player(

        user.id,

        user.first_name or "بازیکن"
    )

    await query.answer(
        "✅ وارد بازی شدی!"
    )

    # آپدیت لابی
    try:

        await query.edit_message_text(

            group_lobby_text(game),

            reply_markup=
            group_lobby_keyboard(game_id)
        )

    except Exception:
        pass

    # اگر ظرفیت پر شد
    if game.player_count() >= GROUP_MAX_PLAYERS:

        await start_group_game(
            update,
            context,
            game_id,
            automatic=True
        )


# ============================================================
# START GROUP GAME
# ============================================================

async def start_group_game(
    update,
    context,
    game_id,
    automatic=False
):

    game = GROUP_GAMES.get(
        game_id
    )

    if not game:
        return

    if game.started:
        return

    if game.finished:
        return

    # حداقل بازیکن
    if game.player_count() < GROUP_MIN_PLAYERS:

        if not automatic:

            await update.callback_query.answer(

                f"❌ حداقل "
                f"{GROUP_MIN_PLAYERS} بازیکن لازم است.",

                show_alert=True
            )

        return

    # فقط سازنده می‌تواند دستی شروع کند
    if (
        not automatic
        and update.effective_user.id
        != game.creator_id
    ):

        await update.callback_query.answer(

            "❌ فقط سازنده بازی می‌تواند شروع کند.",

            show_alert=True
        )

        return

    game.started = True

    game.current_turn = 0

    # تعیین بازی
    game_name = game.game_type

    # پیام شروع
    try:

        await context.bot.edit_message_text(

            chat_id=game.chat_id,

            message_id=game.message_id,

            text=(
                "🔥 **بازی شروع شد!**\n\n"
                f"🎮 {game_name}\n\n"
                f"👥 بازیکنان: "
                f"{game.player_count()}\n\n"
                "🤖 خر‌بات داور بازی است."
            )

        )

    except Exception:
        pass

    await asyncio.sleep(1)

    # اجرای موتور بازی
    await run_group_game(
        context,
        game
    )


# ============================================================
# GROUP GAME ENGINE
# ============================================================

async def run_group_game(
    context,
    game
):

    if game.finished:
        return

    if game.game_type == "🪨 سنگ کاغذ قیچی":

        await group_rps_game(
            context,
            game
        )

    elif game.game_type == "🎲 تاس":

        await group_dice_game(
            context,
            game
        )

    elif game.game_type == "🏁 مسابقه خرها":

        await group_race_game(
            context,
            game
        )

    elif game.game_type == "⚔️ دوئل خرها":

        await group_duel_game(
            context,
            game
        )

    else:

        await group_number_game(
            context,
            game
        )


# ============================================================
# GROUP RPS
# ============================================================

async def group_rps_game(
    context,
    game
):

    game.data["moves"] = {}

    keyboard = InlineKeyboardMarkup([

        [

            InlineKeyboardButton(
                "🪨",
                callback_data=
                f"grp_rps_rock_{game.game_id}"
            ),

            InlineKeyboardButton(
                "📄",
                callback_data=
                f"grp_rps_paper_{game.game_id}"
            ),

            InlineKeyboardButton(
                "✂️",
                callback_data=
                f"grp_rps_scissors_{game.game_id}"
            )

        ],

        [

            InlineKeyboardButton(
                "❌ خروج",
                callback_data=
                f"leave_group_{game.game_id}"
            )

        ]

    ])

    await context.bot.send_message(

        chat_id=game.chat_id,

        text=(

            "🪨 **سنگ کاغذ قیچی**\n\n"

            "همه بازیکنان حرکت خود را انتخاب کنند.\n\n"

            f"⏳ زمان: "
            f"{GROUP_TURN_TIME} ثانیه"

        ),

        reply_markup=keyboard
    )


# ============================================================
# GROUP RPS MOVE
# ============================================================

async def group_rps_move(
    update,
    context,
    game_id,
    move
):

    query = update.callback_query

    user = update.effective_user

    game = GROUP_GAMES.get(
        game_id
    )

    if not game or game.finished:

        return

    if user.id not in game.players:

        await query.answer(
            "❌ عضو بازی نیستی.",
            show_alert=True
        )

        return

    game.data["moves"][user.id] = move

    await query.answer(
        "✅ حرکت ثبت شد."
    )

    # همه انتخاب کردند
    if len(
        game.data["moves"]
    ) >= game.player_count():

        await finish_group_rps(
            context,
            game
        )


# ============================================================
# FINISH GROUP RPS
# ============================================================

async def finish_group_rps(
    context,
    game
):

    if game.finished:
        return

    game.finished = True

    moves = game.data.get(
        "moves",
        {}
    )

    scores = {}

    for user_id, move in moves.items():

        scores[user_id] = 0

    # مقایسه همه با همه
    for user_a, move_a in moves.items():

        for user_b, move_b in moves.items():

            if user_a == user_b:
                continue

            result = rps_result(
                move_a,
                move_b
            )

            if result == "player":

                scores[user_a] += 1

    # پیدا کردن برنده
    max_score = max(
        scores.values(),
        default=0
    )

    winners = [

        user_id

        for user_id, score
        in scores.items()

        if score == max_score
    ]

    # متن
    text = (
        "🏆 **نتیجه بازی**\n"
        "━━━━━━━━━━━━━━\n\n"
    )

    for user_id, score in scores.items():

        player = game.players.get(
            user_id
        )

        if not player:
            continue

        medal = (
            "🏆"
            if user_id in winners
            else "▫️"
        )

        text += (
            f"{medal} "
            f"{player['name']} — "
            f"{score} امتیاز\n"
        )

    # پرداخت
    await distribute_group_prize(
        context,
        game,
        winners
    )

    await context.bot.send_message(

        chat_id=game.chat_id,

        text=text
    )

    GROUP_GAMES.pop(
        game.game_id,
        None
    )


# ============================================================
# GROUP DICE
# ============================================================

async def group_dice_game(
    context,
    game
):

    results = {}

    for user_id in game.players:

        results[user_id] = random.randint(
            1,
            6
        )

    best = max(
        results.values()
    )

    winners = [

        user_id

        for user_id, value
        in results.items()

        if value == best
    ]

    text = (
        "🎲 **نتیجه تاس گروهی**\n"
        "━━━━━━━━━━━━━━\n\n"
    )

    for user_id, value in results.items():

        player = game.players[user_id]

        medal = (
            "🏆"
            if user_id in winners
            else "🎲"
        )

        text += (
            f"{medal} "
            f"{player['name']}: "
            f"{value}\n"
        )

    await distribute_group_prize(
        context,
        game,
        winners
    )

    game.finished = True

    await context.bot.send_message(

        chat_id=game.chat_id,

        text=text
    )

    GROUP_GAMES.pop(
        game.game_id,
        None
    )


# ============================================================
# GROUP RACE
# ============================================================

async def group_race_game(
    context,
    game
):

    results = {}

    for user_id in game.players:

        # کمی اختلاف تصادفی
        results[user_id] = random.randint(
            50,
            100
        )

    best = max(
        results.values()
    )

    winners = [

        user_id

        for user_id, value
        in results.items()

        if value == best
    ]

    text = (
        "🏁 **مسابقه خرها**\n"
        "━━━━━━━━━━━━━━\n\n"
    )

    sorted_results = sorted(

        results.items(),

        key=lambda x: x[1],

        reverse=True
    )

    for position, (
        user_id,
        distance
    ) in enumerate(
        sorted_results,
        1
    ):

        player = game.players[user_id]

        medal = (
            "🥇"
            if position == 1
            else
            "🥈"
            if position == 2
            else
            "🥉"
            if position == 3
            else
            "▫️"
        )

        text += (
            f"{medal} "
            f"{player['name']} — "
            f"{distance} متر\n"
        )

    await distribute_group_prize(
        context,
        game,
        winners
    )

    game.finished = True

    await context.bot.send_message(

        chat_id=game.chat_id,

        text=text
    )

    GROUP_GAMES.pop(
        game.game_id,
        None
    )


# ============================================================
# GROUP DUEL
# ============================================================

async def group_duel_game(
    context,
    game
):

    # هر بازیکن HP دارد
    for player in game.players.values():

        player["hp"] = 100

        player["alive"] = True

    await context.bot.send_message(

        chat_id=game.chat_id,

        text=(

            "⚔️ **دوئل گروهی شروع شد!**\n\n"

            "هر خر ۱۰۰ ❤️ دارد.\n"

            "در هر راند، خرها به صورت تصادفی "
            "به یکدیگر حمله می‌کنند.\n\n"

            "🔥 آخرین خر زنده برنده است."
        )
    )

    await asyncio.sleep(2)

    round_number = 0

    while True:

        round_number += 1

        alive = game.alive_players()

        if len(alive) <= 1:
            break

        for attacker in alive:

            targets = [

                p

                for p in alive

                if p["id"] != attacker["id"]
                and p["alive"]
            ]

            if not targets:
                continue

            target = random.choice(
                targets
            )

            damage = random.randint(
                8,
                25
            )

            target["hp"] -= damage

            if target["hp"] <= 0:

                target["hp"] = 0

                target["alive"] = False

        if round_number % 2 == 0:

            status = (
                "⚔️ **وضعیت دوئل**\n\n"
            )

            for player in game.players.values():

                status += (

                    f"{'💀' if not player['alive'] else '❤️'} "
                    f"{player['name']}: "
                    f"{player['hp']} HP\n"
                )

            await context.bot.send_message(

                chat_id=game.chat_id,

                text=status
            )

        await asyncio.sleep(1)

        if round_number >= 30:

            break

    alive = game.alive_players()

    if alive:

        winners = [
            alive[0]["id"]
        ]

    else:

        # اگر همه همزمان مردند
        winners = [
            max(
                game.players.values(),
                key=lambda p: p["hp"]
            )["id"]
        ]

    game.finished = True

    await distribute_group_prize(

        context,

        game,

        winners
    )

    winner = game.players[
        winners[0]
    ]

    await context.bot.send_message(

        chat_id=game.chat_id,

        text=(

            "🏆 **دوئل تمام شد!**\n\n"

            f"👑 برنده: "
            f"{winner['name']}\n\n"

            f"❤️ HP باقی‌مانده: "
            f"{winner['hp']}"
        )
    )

    GROUP_GAMES.pop(
        game.game_id,
        None
    )


# ============================================================
# GROUP NUMBER GAME
# ============================================================

async def group_number_game(
    context,
    game
):

    secret = random.randint(
        1,
        100
    )

    game.data["secret"] = secret

    await context.bot.send_message(

        chat_id=game.chat_id,

        text=(

            "🔢 **عدد مخفی گروهی**\n\n"

            "من یک عدد بین ۱ تا ۱۰۰ انتخاب کردم.\n\n"

            "هرکس زودتر حدس درست بزند "
            "برنده می‌شود.\n\n"

            "برای حدس بزن:\n"

            "`حدس 50`"
        )
    )


# ============================================================
# GROUP NUMBER MESSAGE HANDLER
# ============================================================

async def group_number_guess(
    update,
    context
):

    message = update.message

    if not message:
        return

    if not message.text:
        return

    text = message.text.strip()

    if not text.startswith(
        "حدس "
    ):
        return

    try:

        number = int(
            text.split(
                " ",
                1
            )[1]
        )

    except:

        return

    # بازی فعال در این گروه
    game = None

    for current in GROUP_GAMES.values():

        if (
            current.chat_id
            == message.chat_id
            and current.started
            and not current.finished
        ):

            game = current

            break

    if not game:
        return

    if game.game_type != "🔢 عدد مخفی":
        return

    if message.from_user.id not in game.players:
        return

    secret = game.data.get(
        "secret"
    )

    if number == secret:

        game.finished = True

        winners = [
            message.from_user.id
        ]

        await distribute_group_prize(
            context,
            game,
            winners
        )

        await message.reply_text(

            "🎯🔥 **درست حدس زدی!**\n\n"

            f"👑 برنده: "
            f"{message.from_user.first_name}\n\n"

            f"🔢 عدد: {secret}"
        )

        GROUP_GAMES.pop(
            game.game_id,
            None
        )

        return

    if number < secret:

        await message.reply_text(
            "📈 بالاتره!"
        )

    else:

        await message.reply_text(
            "📉 پایین‌تره!"
        )


# ============================================================
# GROUP PRIZE DISTRIBUTION
# ============================================================

async def distribute_group_prize(
    context,
    game,
    winners
):

    if not winners:
        return

    total_pot = (
        game.bet
        * game.player_count()
    )

    # 90٪ استخر بین برندگان
    prize_pool = int(
        total_pot * 0.90
    )

    each_prize = (
        prize_pool
        // len(winners)
    )

    # سهم باقی مانده از تقسیم حذف می‌شود
    for user_id in winners:

        add_coins(
            user_id,
            each_prize
        )

        execute(

            """
            UPDATE users
            SET wins = wins + 1,
                games = games + 1
            WHERE user_id = ?
            """,

            (user_id,),

            commit=True
        )

    # بازنده‌ها
    for user_id in game.players:

        if user_id not in winners:

            execute(

                """
                UPDATE users
                SET losses = losses + 1,
                    games = games + 1
                WHERE user_id = ?
                """,

                (user_id,),

                commit=True
            )


# ============================================================
# CANCEL GROUP GAME
# ============================================================

async def cancel_group_game(
    update,
    context,
    game_id
):

    query = update.callback_query

    user = update.effective_user

    game = GROUP_GAMES.get(
        game_id
    )

    if not game:

        await query.answer(

            "❌ بازی پیدا نشد.",

            show_alert=True
        )

        return

    if game.started:

        await query.answer(

            "❌ بازی شروع شده و قابل لغو نیست.",

            show_alert=True
        )

        return

    if user.id != game.creator_id:

        await query.answer(

            "❌ فقط سازنده می‌تواند بازی را لغو کند.",

            show_alert=True
        )

        return

    # بازگرداندن ورودی همه
    for player in game.players.values():

        add_coins(

            player["id"],

            game.bet
        )

    game.finished = True

    GROUP_GAMES.pop(
        game_id,
        None
    )

    await query.edit_message_text(

        "❌ **بازی لغو شد.**\n\n"

        "💰 ورودی تمام بازیکنان "
        "به حسابشان برگشت داده شد."
    )


# ============================================================
# LEAVE GROUP GAME
# ============================================================

async def leave_group_game(
    update,
    context,
    game_id
):

    query = update.callback_query

    user = update.effective_user

    game = GROUP_GAMES.get(
        game_id
    )

    if not game:
        return

    if game.started:

        await query.answer(

            "❌ بعد از شروع نمی‌توانی خارج شوی.",

            show_alert=True
        )

        return

    if user.id not in game.players:

        await query.answer(
            "❌ عضو بازی نیستی.",
            show_alert=True
        )

        return

    # برگشت پول
    add_coins(
        user.id,
        game.bet
    )

    game.remove_player(
        user.id
    )

    await query.answer(
        "✅ از بازی خارج شدی."
    )

    if game.player_count() == 0:

        GROUP_GAMES.pop(
            game_id,
            None
        )

        try:

            await query.edit_message_text(

                "❌ بازی لغو شد؛ "
                "همه خارج شدند."
            )

        except Exception:
            pass

        return

    try:

        await query.edit_message_text(

            group_lobby_text(game),

            reply_markup=
            group_lobby_keyboard(
                game_id
            )
        )

    except Exception:
        pass


# ============================================================
# LOBBY TIMER
# ============================================================

async def group_lobby_timer(
    context,
    game_id
):

    await asyncio.sleep(
        GROUP_JOIN_TIME
    )

    game = GROUP_GAMES.get(
        game_id
    )

    if not game:
        return

    if game.started:
        return

    if game.finished:
        return

    # اگر حداقل نفر دارد
    if game.player_count() >= GROUP_MIN_PLAYERS:

        game.started = True

        await run_group_game(
            context,
            game
        )

        return

    # برگشت پول
    for player in game.players.values():

        add_coins(
            player["id"],
            game.bet
        )

    game.finished = True

    GROUP_GAMES.pop(
        game_id,
        None
    )

    try:

        await context.bot.edit_message_text(

            chat_id=game.chat_id,

            message_id=game.message_id,

            text=(

                "⏰ **زمان لابی تمام شد.**\n\n"

                "❌ بازیکن کافی پیدا نشد.\n\n"

                "💰 پول همه بازگردانده شد."
            )
        )

    except Exception:
        pass


# ============================================================
# GROUP CALLBACK HANDLER
# ============================================================

async def group_callback_handler(
    update,
    context
):

    query = update.callback_query

    data = query.data

    # JOIN
    if data.startswith(
        "join_group_"
    ):

        game_id = data.replace(
            "join_group_",
            "",
            1
        )

        await join_group_game(
            update,
            context,
            game_id
        )

        return True

    # START
    if data.startswith(
        "start_group_"
    ):

        game_id = data.replace(
            "start_group_",
            "",
            1
        )

        await start_group_game(
            update,
            context,
            game_id
        )

        return True

    # CANCEL
    if data.startswith(
        "cancel_group_"
    ):

        game_id = data.replace(
            "cancel_group_",
            "",
            1
        )

        await cancel_group_game(
            update,
            context,
            game_id
        )

        return True

    # LEAVE
    if data.startswith(
        "leave_group_"
    ):

        game_id = data.replace(
            "leave_group_",
            "",
            1
        )

        await leave_group_game(
            update,
            context,
            game_id
        )

        return True

    # RPS
    if data.startswith(
        "grp_rps_"
    ):

        parts = data.split("_")

        if len(parts) >= 4:

            move = parts[2]

            game_id = "_".join(
                parts[3:]
            )

            await group_rps_move(
                update,
                context,
                game_id,
                move
            )

            return True

    return False
# ============================================================
# KHARBOT V6
# 🤖 BOT OPPONENT ENGINE
# ============================================================

BOT_MIN_DELAY = 1.2
BOT_MAX_DELAY = 3.5

BOT_DIFFICULTY = {
    "easy": 0.35,
    "normal": 0.60,
    "hard": 0.78,
    "expert": 0.90
}


# ============================================================
# BOT PLAYER
# ============================================================

class KharBotPlayer:

    def __init__(
        self,
        bot_id,
        name,
        difficulty="hard"
    ):

        self.id = bot_id

        self.name = name

        self.difficulty = difficulty

        self.score = 0

        self.hp = 100

        self.alive = True

        self.coins = 0

        self.is_bot = True

    def accuracy(self):

        return BOT_DIFFICULTY.get(
            self.difficulty,
            0.78
        )


# ============================================================
# BOT NAMES
# ============================================================

BOT_NAMES = [

    "خر گردن‌کلفت",
    "خر سیاه",
    "خر وحشی",
    "خر پیر",
    "خر استاد",
    "خر بدشانس",
    "خر رئیس",
    "خر سلطان",
    "خر جنگجو",
    "خر دیوانه"
]


# ============================================================
# CREATE BOT
# ============================================================

def create_khar_bot(
    difficulty="hard"
):

    bot_id = (
        -random.randint(
            100000,
            999999999
        )
    )

    return KharBotPlayer(

        bot_id=bot_id,

        name=random.choice(
            BOT_NAMES
        ),

        difficulty=difficulty
    )


# ============================================================
# BOT CHOICE
# ============================================================

def bot_random_choice(
    choices,
    difficulty="hard"
):

    accuracy = BOT_DIFFICULTY.get(
        difficulty,
        0.78
    )

    # تصمیم نسبتاً خوب
    if random.random() < accuracy:

        return choices[
            random.randrange(
                len(choices)
            )
        ]

    # تصمیم تصادفی
    return random.choice(
        choices
    )


# ============================================================
# BOT RPS
# ============================================================

def bot_rps_move(
    player_move,
    difficulty="hard"
):

    # حرکتی که بازیکن را شکست می‌دهد
    counter = {

        "rock": "paper",

        "paper": "scissors",

        "scissors": "rock"
    }

    # بات همیشه کامل نمی‌خواند
    accuracy = BOT_DIFFICULTY.get(
        difficulty,
        0.78
    )

    if random.random() < accuracy:

        return counter[
            player_move
        ]

    return random.choice(
        [
            "rock",
            "paper",
            "scissors"
        ]
    )


# ============================================================
# SOLO GAME
# ============================================================

SOLO_GAMES = {}


class SoloGame:

    def __init__(
        self,
        game_id,
        user_id,
        game_type,
        bet,
        difficulty="hard"
    ):

        self.game_id = game_id

        self.user_id = user_id

        self.game_type = game_type

        self.bet = bet

        self.difficulty = difficulty

        self.bot = create_khar_bot(
            difficulty
        )

        self.started = False

        self.finished = False

        self.data = {}


# ============================================================
# CREATE SOLO GAME
# ============================================================

async def create_solo_game(
    update,
    context,
    game_type,
    bet=100,
    difficulty="hard"
):

    user = update.effective_user

    # بازی قبلی
    for game in SOLO_GAMES.values():

        if (
            game.user_id
            == user.id
            and not game.finished
        ):

            await update.callback_query.answer(

                "❌ اول بازی فعلی را تمام کن.",

                show_alert=True
            )

            return

    # پول
    if not remove_coins(
        user.id,
        bet
    ):

        await update.callback_query.answer(

            "❌ سکه کافی نداری.",

            show_alert=True
        )

        return

    game_id = (

        f"SOLO_"
        f"{user.id}_"
        f"{int(time.time())}_"
        f"{random.randint(1000,9999)}"

    )

    game = SoloGame(

        game_id=game_id,

        user_id=user.id,

        game_type=game_type,

        bet=bet,

        difficulty=difficulty
    )

    game.started = True

    SOLO_GAMES[
        game_id
    ] = game

    await update.callback_query.answer()

    await update.callback_query.edit_message_text(

        "🤖 **حریف پیدا شد!**\n\n"

        f"🫏 {game.bot.name}\n"

        f"🎯 سختی: "
        f"{difficulty.upper()}\n\n"

        "🔥 بازی شروع شد..."
    )

    await asyncio.sleep(
        random.uniform(
            BOT_MIN_DELAY,
            BOT_MAX_DELAY
        )
    )

    await run_solo_game(
        context,
        game
    )


# ============================================================
# SOLO GAME ENGINE
# ============================================================

async def run_solo_game(
    context,
    game
):

    if game.finished:
        return

    if game.game_type == "🪨 سنگ کاغذ قیچی":

        await solo_rps(
            context,
            game
        )

    elif game.game_type == "🎲 تاس":

        await solo_dice(
            context,
            game
        )

    elif game.game_type == "🏁 مسابقه خرها":

        await solo_race(
            context,
            game
        )

    elif game.game_type == "⚔️ دوئل خرها":

        await solo_duel(
            context,
            game
        )

    else:

        await solo_luck(
            context,
            game
        )


# ============================================================
# SOLO RPS
# ============================================================

async def solo_rps(
    context,
    game
):

    keyboard = InlineKeyboardMarkup([

        [

            InlineKeyboardButton(
                "🪨",
                callback_data=
                f"solo_rps_rock_{game.game_id}"
            ),

            InlineKeyboardButton(
                "📄",
                callback_data=
                f"solo_rps_paper_{game.game_id}"
            ),

            InlineKeyboardButton(
                "✂️",
                callback_data=
                f"solo_rps_scissors_{game.game_id}"
            )

        ],

        [

            InlineKeyboardButton(
                "❌ لغو بازی",
                callback_data=
                f"solo_cancel_{game.game_id}"
            )

        ]

    ])

    await context.bot.send_message(

        chat_id=game.user_id,

        text=(

            "🪨 **سنگ کاغذ قیچی**\n\n"

            f"🤖 حریف: "
            f"{game.bot.name}\n\n"

            "حرکتت را انتخاب کن:"
        ),

        reply_markup=keyboard
    )


# ============================================================
# SOLO RPS MOVE
# ============================================================

async def solo_rps_move(
    update,
    context,
    game_id,
    move
):

    query = update.callback_query

    user = update.effective_user

    game = SOLO_GAMES.get(
        game_id
    )

    if not game:
        return

    if game.finished:
        return

    if user.id != game.user_id:

        await query.answer(
            "❌ این بازی متعلق به تو نیست.",
            show_alert=True
        )

        return

    # انتخاب بات
    bot_move = bot_rps_move(

        move,

        game.difficulty
    )

    result = rps_result(
        move,
        bot_move
    )

    game.finished = True

    # نتیجه
    if result == "player":

        reward = game.bet * 2

        add_coins(
            user.id,
            reward
        )

        result_text = (

            "🏆 **بردی!**\n\n"

            f"🫵 تو: {move}\n"

            f"🤖 {game.bot.name}: "
            f"{bot_move}\n\n"

            f"💰 جایزه: "
            f"+{reward:,} 🪙"
        )

    elif result == "bot":

        reward = 0

        result_text = (

            "💀 **باختی!**\n\n"

            f"🫵 تو: {move}\n"

            f"🤖 {game.bot.name}: "
            f"{bot_move}\n\n"

            "💸 ورودی از دست رفت."
        )

    else:

        reward = game.bet

        add_coins(
            user.id,
            reward
        )

        result_text = (

            "🤝 **مساوی!**\n\n"

            f"🫵 تو: {move}\n"

            f"🤖 {game.bot.name}: "
            f"{bot_move}\n\n"

            f"💰 "
            f"{reward:,} 🪙 برگشت داده شد."
        )

    await query.answer()

    await query.edit_message_text(
        result_text
    )

    SOLO_GAMES.pop(
        game_id,
        None
    )


# ============================================================
# SOLO DICE
# ============================================================

async def solo_dice(
    context,
    game
):

    player_roll = random.randint(
        1,
        6
    )

    bot_roll = random.randint(
        1,
        6
    )

    # کمی هوشمندی بات
    if (
        game.difficulty
        in (
            "hard",
            "expert"
        )
        and bot_roll < player_roll
    ):

        if random.random() < (
            BOT_DIFFICULTY[
                game.difficulty
            ]
        ):

            bot_roll = random.randint(
                player_roll,
                6
            )

    if bot_roll > player_roll:

        result = "bot"

    elif player_roll > bot_roll:

        result = "player"

    else:

        result = "draw"

    game.finished = True

    if result == "player":

        reward = game.bet * 2

        add_coins(
            game.user_id,
            reward
        )

        text = (

            "🎲🏆 **بردی!**\n\n"

            f"🫵 تو: {player_roll}\n"

            f"🤖 {game.bot.name}: "
            f"{bot_roll}\n\n"

            f"💰 +{reward:,} 🪙"
        )

    elif result == "bot":

        text = (

            "🎲💀 **باختی!**\n\n"

            f"🫵 تو: {player_roll}\n"

            f"🤖 {game.bot.name}: "
            f"{bot_roll}\n\n"

            "💸 سکه‌ها از دست رفت."
        )

    else:

        add_coins(
            game.user_id,
            game.bet
        )

        text = (

            "🎲🤝 **مساوی!**\n\n"

            f"🫵 تو: {player_roll}\n"

            f"🤖 {game.bot.name}: "
            f"{bot_roll}\n\n"

            f"💰 {game.bet:,} 🪙 برگشت."
        )

    await context.bot.send_message(

        chat_id=game.user_id,

        text=text
    )

    SOLO_GAMES.pop(
        game.game_id,
        None
    )


# ============================================================
# SOLO RACE
# ============================================================

async def solo_race(
    context,
    game
):

    player_power = random.randint(
        50,
        100
    )

    bot_power = random.randint(
        50,
        100
    )

    # بات حرفه‌ای‌تر
    if random.random() < (
        game.bot.accuracy()
    ):

        bot_power = max(
            bot_power,
            player_power +
            random.randint(
                -5,
                12
            )
        )

        bot_power = min(
            bot_power,
            100
        )

    if player_power > bot_power:

        winner = "player"

    elif bot_power > player_power:

        winner = "bot"

    else:

        winner = "draw"

    game.finished = True

    if winner == "player":

        reward = game.bet * 2

        add_coins(
            game.user_id,
            reward
        )

        text = (

            "🏁🏆 **خر تو برنده شد!**\n\n"

            f"🫵 قدرت تو: "
            f"{player_power}\n"

            f"🤖 {game.bot.name}: "
            f"{bot_power}\n\n"

            f"💰 جایزه: "
            f"+{reward:,} 🪙"
        )

    elif winner == "bot":

        text = (

            "🏁💀 **خر حریف برد!**\n\n"

            f"🫵 قدرت تو: "
            f"{player_power}\n"

            f"🤖 {game.bot.name}: "
            f"{bot_power}\n\n"

            "💸 باختی!"
        )

    else:

        add_coins(
            game.user_id,
            game.bet
        )

        text = (

            "🏁🤝 **مساوی شد!**\n\n"

            f"🫵 {player_power}\n"

            f"🤖 {bot_power}\n\n"

            f"💰 ورودی برگشت داده شد."
        )

    await context.bot.send_message(

        chat_id=game.user_id,

        text=text
    )

    SOLO_GAMES.pop(
        game.game_id,
        None
    )


# ============================================================
# SOLO DUEL
# ============================================================

async def solo_duel(
    context,
    game
):

    player_hp = 100

    bot_hp = 100

    round_number = 0

    while (
        player_hp > 0
        and bot_hp > 0
        and round_number < 20
    ):

        round_number += 1

        # بازیکن
        player_damage = random.randint(
            8,
            24
        )

        # بات
        bot_damage = random.randint(
            8,
            24
        )

        # بات سخت‌تر
        if random.random() < (
            game.bot.accuracy()
        ):

            bot_damage += random.randint(
                2,
                7
            )

        bot_damage = min(
            bot_damage,
            30
        )

        bot_hp -= player_damage

        if bot_hp <= 0:
            bot_hp = 0
            break

        player_hp -= bot_damage

        if player_hp <= 0:
            player_hp = 0
            break

        await asyncio.sleep(
            0.25
        )

    game.finished = True

    if player_hp > bot_hp:

        reward = game.bet * 2

        add_coins(
            game.user_id,
            reward
        )

        result = (

            "⚔️🏆 **دوئل را بردی!**\n\n"

            f"🫵 HP تو: {player_hp}\n"

            f"🤖 HP {game.bot.name}: "
            f"{bot_hp}\n\n"

            f"💰 +{reward:,} 🪙"
        )

    elif bot_hp > player_hp:

        result = (

            "⚔️💀 **دوئل را باختی!**\n\n"

            f"🫵 HP تو: {player_hp}\n"

            f"🤖 HP حریف: "
            f"{bot_hp}\n\n"

            "💸 ورودی از دست رفت."
        )

    else:

        add_coins(
            game.user_id,
            game.bet
        )

        result = (

            "⚔️🤝 **دوئل مساوی شد!**\n\n"

            "💰 ورودی برگشت داده شد."
        )

    await context.bot.send_message(

        chat_id=game.user_id,

        text=result
    )

    SOLO_GAMES.pop(
        game.game_id,
        None
    )


# ============================================================
# SOLO LUCK
# ============================================================

async def solo_luck(
    context,
    game
):

    player = random.randint(
        1,
        100
    )

    bot = random.randint(
        1,
        100
    )

    # سختی روی شانس بات تأثیر دارد
    if random.random() < (
        game.bot.accuracy()
    ):

        bot = max(
            bot,
            player
        )

    game.finished = True

    if player > bot:

        reward = game.bet * 2

        add_coins(
            game.user_id,
            reward
        )

        text = (

            "🍀🏆 **شانس با تو بود!**\n\n"

            f"🫵 {player}\n"

            f"🤖 {bot}\n\n"

            f"💰 +{reward:,} 🪙"
        )

    elif bot > player:

        text = (

            "🍀💀 **حریف خوش‌شانس‌تر بود!**\n\n"

            f"🫵 {player}\n"

            f"🤖 {bot}\n\n"

            "💸 باختی."
        )

    else:

        add_coins(
            game.user_id,
            game.bet
        )

        text = (

            "🍀🤝 **مساوی!**\n\n"

            "💰 پولت برگشت داده شد."
        )

    await context.bot.send_message(

        chat_id=game.user_id,

        text=text
    )

    SOLO_GAMES.pop(
        game.game_id,
        None
    )


# ============================================================
# CANCEL SOLO GAME
# ============================================================

async def cancel_solo_game(
    update,
    context,
    game_id
):

    query = update.callback_query

    user = update.effective_user

    game = SOLO_GAMES.get(
        game_id
    )

    if not game:

        await query.answer(

            "❌ بازی پیدا نشد.",

            show_alert=True
        )

        return

    if game.user_id != user.id:

        await query.answer(

            "❌ این بازی متعلق به تو نیست.",

            show_alert=True
        )

        return

    if game.finished:

        return

    game.finished = True

    # برگشت ورودی
    add_coins(
        user.id,
        game.bet
    )

    SOLO_GAMES.pop(
        game_id,
        None
    )

    await query.answer(
        "بازی لغو شد."
    )

    await query.edit_message_text(

        "❌ **بازی لغو شد.**\n\n"

        f"💰 {game.bet:,} 🪙 "
        "به حسابت برگشت."
    )


# ============================================================
# SOLO CALLBACK ROUTER
# ============================================================

async def solo_callback_handler(
    update,
    context
):

    query = update.callback_query

    data = query.data

    # RPS
    if data.startswith(
        "solo_rps_"
    ):

        parts = data.split("_")

        move = parts[2]

        game_id = "_".join(
            parts[3:]
        )

        await solo_rps_move(

            update,
            context,
            game_id,
            move
        )

        return True

    # CANCEL
    if data.startswith(
        "solo_cancel_"
    ):

        game_id = data.replace(
            "solo_cancel_",
            "",
            1
        )

        await cancel_solo_game(

            update,
            context,
            game_id
        )

        return True

    return False

# ============================================================
# KHARBOT V7
# 🫏 PERSONAL DONKEY SYSTEM
# ============================================================

MAX_DONKEY_LEVEL = 50

DONKEY_MAX_HUNGER = 100
DONKEY_MAX_THIRST = 100
DONKEY_MAX_ENERGY = 100
DONKEY_MAX_HEALTH = 100
DONKEY_MAX_CLEAN = 100

DONKEY_DECAY_SECONDS = 3600


# ============================================================
# DONKEY DEFAULT DATA
# ============================================================

DEFAULT_DONKEY = {
    "name": "خر من",

    "level": 1,

    "xp": 0,

    "hunger": 100,

    "thirst": 100,

    "energy": 100,

    "health": 100,

    "clean": 100,

    "strength": 10,

    "speed": 10,

    "luck": 10,

    "defense": 10,

    "last_update": int(time.time())
}


# ============================================================
# DONKEY TABLE
# ============================================================

execute("""
CREATE TABLE IF NOT EXISTS donkeys (

    user_id INTEGER PRIMARY KEY,

    name TEXT NOT NULL DEFAULT 'خر من',

    level INTEGER NOT NULL DEFAULT 1,

    xp INTEGER NOT NULL DEFAULT 0,

    hunger INTEGER NOT NULL DEFAULT 100,

    thirst INTEGER NOT NULL DEFAULT 100,

    energy INTEGER NOT NULL DEFAULT 100,

    health INTEGER NOT NULL DEFAULT 100,

    clean INTEGER NOT NULL DEFAULT 100,

    strength INTEGER NOT NULL DEFAULT 10,

    speed INTEGER NOT NULL DEFAULT 10,

    luck INTEGER NOT NULL DEFAULT 10,

    defense INTEGER NOT NULL DEFAULT 10,

    last_update INTEGER NOT NULL
)
""", commit=True)


# ============================================================
# GET DONKEY
# ============================================================

def get_donkey(user_id):

    row = fetchone(
        """
        SELECT *
        FROM donkeys
        WHERE user_id = ?
        """,
        (user_id,)
    )

    if row:

        columns = [
            "user_id",
            "name",
            "level",
            "xp",
            "hunger",
            "thirst",
            "energy",
            "health",
            "clean",
            "strength",
            "speed",
            "luck",
            "defense",
            "last_update"
        ]

        return dict(
            zip(columns, row)
        )

    create_donkey(user_id)

    return get_donkey(user_id)


# ============================================================
# CREATE DONKEY
# ============================================================

def create_donkey(user_id):

    now = int(time.time())

    execute(
        """
        INSERT OR IGNORE INTO donkeys (

            user_id,
            name,
            level,
            xp,
            hunger,
            thirst,
            energy,
            health,
            clean,
            strength,
            speed,
            luck,
            defense,
            last_update

        )

        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,

        (
            user_id,
            "خر من",
            1,
            0,
            100,
            100,
            100,
            100,
            100,
            10,
            10,
            10,
            10,
            now
        ),

        commit=True
    )


# ============================================================
# UPDATE DONKEY
# ============================================================

def update_donkey(
    user_id,
    **values
):

    if not values:
        return

    allowed = {

        "name",
        "level",
        "xp",
        "hunger",
        "thirst",
        "energy",
        "health",
        "clean",
        "strength",
        "speed",
        "luck",
        "defense",
        "last_update"
    }

    clean_values = {

        key: value

        for key, value
        in values.items()

        if key in allowed
    }

    if not clean_values:
        return

    fields = ", ".join(
        f"{key} = ?"
        for key in clean_values
    )

    params = list(
        clean_values.values()
    )

    params.append(user_id)

    execute(
        f"""
        UPDATE donkeys
        SET {fields}
        WHERE user_id = ?
        """,
        tuple(params),
        commit=True
    )


# ============================================================
# CLAMP DONKEY STATS
# ============================================================

def clamp_donkey_stats(
    donkey
):

    for stat, maximum in [

        ("hunger", 100),

        ("thirst", 100),

        ("energy", 100),

        ("health", 100),

        ("clean", 100)

    ]:

        donkey[stat] = max(
            0,
            min(
                maximum,
                int(donkey[stat])
            )
        )

    for stat in [

        "strength",
        "speed",
        "luck",
        "defense"

    ]:

        donkey[stat] = max(
            1,
            int(donkey[stat])
        )

    return donkey


# ============================================================
# DONKEY TIME DECAY
# ============================================================

def update_donkey_needs(
    user_id
):

    donkey = get_donkey(
        user_id
    )

    now = int(time.time())

    last = int(
        donkey.get(
            "last_update",
            now
        )
    )

    elapsed = max(
        0,
        now - last
    )

    if elapsed < DONKEY_DECAY_SECONDS:

        return donkey

    hours = elapsed // DONKEY_DECAY_SECONDS

    hunger_loss = min(
        40,
        hours * 5
    )

    thirst_loss = min(
        50,
        hours * 7
    )

    clean_loss = min(
        40,
        hours * 3
    )

    energy_loss = min(
        30,
        hours * 2
    )

    donkey["hunger"] -= hunger_loss

    donkey["thirst"] -= thirst_loss

    donkey["clean"] -= clean_loss

    donkey["energy"] -= energy_loss

    # وضعیت بد روی سلامتی اثر می‌گذارد
    bad_conditions = 0

    if donkey["hunger"] < 20:
        bad_conditions += 1

    if donkey["thirst"] < 20:
        bad_conditions += 1

    if donkey["clean"] < 20:
        bad_conditions += 1

    if bad_conditions:

        donkey["health"] -= (
            bad_conditions * hours
        )

    # انرژی کم
    if donkey["energy"] <= 0:

        donkey["health"] -= (
            max(1, hours)
        )

    donkey["last_update"] = now

    donkey = clamp_donkey_stats(
        donkey
    )

    update_donkey(
        user_id,

        hunger=donkey["hunger"],

        thirst=donkey["thirst"],

        clean=donkey["clean"],

        energy=donkey["energy"],

        health=donkey["health"],

        last_update=now
    )

    return donkey


# ============================================================
# DONKEY XP
# ============================================================

def donkey_xp_required(
    level
):

    return int(
        100 *
        (level ** 1.45)
    )


# ============================================================
# ADD DONKEY XP
# ============================================================

def add_donkey_xp(
    user_id,
    amount
):

    donkey = get_donkey(
        user_id
    )

    if donkey["level"] >= MAX_DONKEY_LEVEL:

        return False, 0

    donkey["xp"] += max(
        0,
        int(amount)
    )

    levels_gained = 0

    while (
        donkey["level"]
        < MAX_DONKEY_LEVEL
    ):

        required = donkey_xp_required(
            donkey["level"]
        )

        if donkey["xp"] < required:

            break

        donkey["xp"] -= required

        donkey["level"] += 1

        levels_gained += 1

        # افزایش پایه
        donkey["strength"] += 2

        donkey["speed"] += 2

        donkey["luck"] += 1

        donkey["defense"] += 2

        donkey["health"] = 100

        donkey["energy"] = 100

    update_donkey(

        user_id,

        level=donkey["level"],

        xp=donkey["xp"],

        strength=donkey["strength"],

        speed=donkey["speed"],

        luck=donkey["luck"],

        defense=donkey["defense"],

        health=donkey["health"],

        energy=donkey["energy"]
    )

    return True, levels_gained


# ============================================================
# DONKEY ACTION COSTS
# ============================================================

DONKEY_ACTIONS = {

    "feed": {
        "coins": 35,
        "hunger": 25,
        "energy": 3
    },

    "water": {
        "coins": 20,
        "thirst": 30
    },

    "bath": {
        "coins": 45,
        "clean": 40,
        "energy": 5
    },

    "sleep": {
        "coins": 30,
        "energy": 35,
        "hunger": 5,
        "thirst": 5
    }
}


# ============================================================
# FEED
# ============================================================

def feed_donkey(
    user_id
):

    donkey = update_donkey_needs(
        user_id
    )

    cost = DONKEY_ACTIONS[
        "feed"
    ]["coins"]

    if not remove_coins(
        user_id,
        cost
    ):

        return False, "❌ سکه کافی نداری."

    donkey["hunger"] += 25

    donkey["energy"] += 3

    donkey = clamp_donkey_stats(
        donkey
    )

    update_donkey(

        user_id,

        hunger=donkey["hunger"],

        energy=donkey["energy"],

        last_update=int(time.time())
    )

    return True, (

        "🥕 خر غذا خورد!\n\n"

        f"🍖 گرسنگی: "
        f"{donkey['hunger']}/100\n"

        f"⚡ انرژی: "
        f"{donkey['energy']}/100\n\n"

        f"💰 هزینه: {cost} 🪙"
    )


# ============================================================
# WATER
# ============================================================

def water_donkey(
    user_id
):

    donkey = update_donkey_needs(
        user_id
    )

    cost = DONKEY_ACTIONS[
        "water"
    ]["coins"]

    if not remove_coins(
        user_id,
        cost
    ):

        return False, "❌ سکه کافی نداری."

    donkey["thirst"] += 30

    donkey = clamp_donkey_stats(
        donkey
    )

    update_donkey(

        user_id,

        thirst=donkey["thirst"],

        last_update=int(time.time())
    )

    return True, (

        "💧 خر آب خورد!\n\n"

        f"💧 تشنگی: "
        f"{donkey['thirst']}/100\n\n"

        f"💰 هزینه: {cost} 🪙"
    )


# ============================================================
# BATH
# ============================================================

def bath_donkey(
    user_id
):

    donkey = update_donkey_needs(
        user_id
    )

    cost = DONKEY_ACTIONS[
        "bath"
    ]["coins"]

    if not remove_coins(
        user_id,
        cost
    ):

        return False, "❌ سکه کافی نداری."

    donkey["clean"] += 40

    donkey["energy"] -= 5

    donkey = clamp_donkey_stats(
        donkey
    )

    update_donkey(

        user_id,

        clean=donkey["clean"],

        energy=donkey["energy"],

        last_update=int(time.time())
    )

    return True, (

        "🛁 خر حمام کرد!\n\n"

        f"🧼 تمیزی: "
        f"{donkey['clean']}/100\n"

        f"⚡ انرژی: "
        f"{donkey['energy']}/100\n\n"

        f"💰 هزینه: {cost} 🪙"
    )


# ============================================================
# SLEEP
# ============================================================

def sleep_donkey(
    user_id
):

    donkey = update_donkey_needs(
        user_id
    )

    cost = DONKEY_ACTIONS[
        "sleep"
    ]["coins"]

    if not remove_coins(
        user_id,
        cost
    ):

        return False, "❌ سکه کافی نداری."

    donkey["energy"] += 35

    donkey["hunger"] -= 5

    donkey["thirst"] -= 5

    donkey = clamp_donkey_stats(
        donkey
    )

    update_donkey(

        user_id,

        energy=donkey["energy"],

        hunger=donkey["hunger"],

        thirst=donkey["thirst"],

        last_update=int(time.time())
    )

    return True, (

        "😴 خر خوابید!\n\n"

        f"⚡ انرژی: "
        f"{donkey['energy']}/100\n"

        f"🍖 گرسنگی: "
        f"{donkey['hunger']}/100\n"

        f"💧 تشنگی: "
        f"{donkey['thirst']}/100\n\n"

        f"💰 هزینه: {cost} 🪙"
    )


# ============================================================
# DONKEY PROFILE TEXT
# ============================================================

def donkey_profile_text(
    donkey
):

    level = donkey["level"]

    xp_required = donkey_xp_required(
        level
    )

    return (

        "🫏 **پروفایل خر من**\n"

        "━━━━━━━━━━━━━━━━\n\n"

        f"🏷 نام: **{donkey['name']}**\n"

        f"⭐ سطح: **{level}**\n"

        f"✨ XP: "
        f"**{donkey['xp']}/{xp_required}**\n\n"

        "❤️ وضعیت\n"

        f"❤️ سلامتی: "
        f"{donkey['health']}/100\n"

        f"🍖 گرسنگی: "
        f"{donkey['hunger']}/100\n"

        f"💧 تشنگی: "
        f"{donkey['thirst']}/100\n"

        f"⚡ انرژی: "
        f"{donkey['energy']}/100\n"

        f"🧼 تمیزی: "
        f"{donkey['clean']}/100\n\n"

        "⚔️ مهارت‌ها\n"

        f"💪 قدرت: "
        f"{donkey['strength']}\n"

        f"🏃 سرعت: "
        f"{donkey['speed']}\n"

        f"🍀 شانس: "
        f"{donkey['luck']}\n"

        f"🛡 دفاع: "
        f"{donkey['defense']}\n"
    )


# ============================================================
# DONKEY KEYBOARD
# ============================================================

def donkey_keyboard():

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton(
                "🥕 غذا",
                callback_data="donkey_feed"
            ),

            InlineKeyboardButton(
                "💧 آب",
                callback_data="donkey_water"
            )

        ],

        [

            InlineKeyboardButton(
                "🛁 حمام",
                callback_data="donkey_bath"
            ),

            InlineKeyboardButton(
                "😴 خواب",
                callback_data="donkey_sleep"
            )

        ],

        [

            InlineKeyboardButton(
                "⬆️ ارتقا",
                callback_data="donkey_upgrade"
            ),

            InlineKeyboardButton(
                "🏪 فروشگاه",
                callback_data="donkey_shop"
            )

        ]

    ])


# ============================================================
# DONKEY PROFILE COMMAND
# ============================================================

async def donkey_profile(
    update,
    context
):

    user = update.effective_user

    donkey = update_donkey_needs(
        user.id
    )

    await update.message.reply_text(

        donkey_profile_text(
            donkey
        ),

        reply_markup=
        donkey_keyboard()
    )


# ============================================================
# DONKEY CALLBACKS
# ============================================================

async def donkey_callback_handler(
    update,
    context
):

    query = update.callback_query

    data = query.data

    user_id = query.from_user.id

    if data == "donkey_feed":

        success, text = feed_donkey(
            user_id
        )

        await query.answer(
            "🥕 غذا داده شد!"
            if success
            else "❌ سکه کافی نیست."
        )

        donkey = update_donkey_needs(
            user_id
        )

        await query.edit_message_text(

            donkey_profile_text(
                donkey
            ),

            reply_markup=
            donkey_keyboard()
        )

        return True

    if data == "donkey_water":

        success, text = water_donkey(
            user_id
        )

        await query.answer(
            "💧 آب داده شد!"
            if success
            else "❌ سکه کافی نیست."
        )

        donkey = update_donkey_needs(
            user_id
        )

        await query.edit_message_text(

            donkey_profile_text(
                donkey
            ),

            reply_markup=
            donkey_keyboard()
        )

        return True

    if data == "donkey_bath":

        success, text = bath_donkey(
            user_id
        )

        await query.answer(
            "🛁 خر حمام کرد!"
            if success
            else "❌ سکه کافی نیست."
        )

        donkey = update_donkey_needs(
            user_id
        )

        await query.edit_message_text(

            donkey_profile_text(
                donkey
            ),

            reply_markup=
            donkey_keyboard()
        )

        return True

    if data == "donkey_sleep":

        success, text = sleep_donkey(
            user_id
        )

        await query.answer(
            "😴 خر خوابید!"
            if success
            else "❌ سکه کافی نیست."
        )

        donkey = update_donkey_needs(
            user_id
        )

        await query.edit_message_text(

            donkey_profile_text(
                donkey
            ),

            reply_markup=
            donkey_keyboard()
        )

        return True

    return False

# ============================================================
# KHARBOT V7
# 🫏 PERSONAL DONKEY SYSTEM
# ============================================================

MAX_DONKEY_LEVEL = 50

DONKEY_MAX_HUNGER = 100
DONKEY_MAX_THIRST = 100
DONKEY_MAX_ENERGY = 100
DONKEY_MAX_HEALTH = 100
DONKEY_MAX_CLEAN = 100

DONKEY_DECAY_SECONDS = 3600


# ============================================================
# DONKEY DEFAULT DATA
# ============================================================

DEFAULT_DONKEY = {
    "name": "خر من",

    "level": 1,

    "xp": 0,

    "hunger": 100,

    "thirst": 100,

    "energy": 100,

    "health": 100,

    "clean": 100,

    "strength": 10,

    "speed": 10,

    "luck": 10,

    "defense": 10,

    "last_update": int(time.time())
}


# ============================================================
# DONKEY TABLE
# ============================================================

execute("""
CREATE TABLE IF NOT EXISTS donkeys (

    user_id INTEGER PRIMARY KEY,

    name TEXT NOT NULL DEFAULT 'خر من',

    level INTEGER NOT NULL DEFAULT 1,

    xp INTEGER NOT NULL DEFAULT 0,

    hunger INTEGER NOT NULL DEFAULT 100,

    thirst INTEGER NOT NULL DEFAULT 100,

    energy INTEGER NOT NULL DEFAULT 100,

    health INTEGER NOT NULL DEFAULT 100,

    clean INTEGER NOT NULL DEFAULT 100,

    strength INTEGER NOT NULL DEFAULT 10,

    speed INTEGER NOT NULL DEFAULT 10,

    luck INTEGER NOT NULL DEFAULT 10,

    defense INTEGER NOT NULL DEFAULT 10,

    last_update INTEGER NOT NULL
)
""", commit=True)


# ============================================================
# GET DONKEY
# ============================================================

def get_donkey(user_id):

    row = fetchone(
        """
        SELECT *
        FROM donkeys
        WHERE user_id = ?
        """,
        (user_id,)
    )

    if row:

        columns = [
            "user_id",
            "name",
            "level",
            "xp",
            "hunger",
            "thirst",
            "energy",
            "health",
            "clean",
            "strength",
            "speed",
            "luck",
            "defense",
            "last_update"
        ]

        return dict(
            zip(columns, row)
        )

    create_donkey(user_id)

    return get_donkey(user_id)


# ============================================================
# CREATE DONKEY
# ============================================================

def create_donkey(user_id):

    now = int(time.time())

    execute(
        """
        INSERT OR IGNORE INTO donkeys (

            user_id,
            name,
            level,
            xp,
            hunger,
            thirst,
            energy,
            health,
            clean,
            strength,
            speed,
            luck,
            defense,
            last_update

        )

        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,

        (
            user_id,
            "خر من",
            1,
            0,
            100,
            100,
            100,
            100,
            100,
            10,
            10,
            10,
            10,
            now
        ),

        commit=True
    )


# ============================================================
# UPDATE DONKEY
# ============================================================

def update_donkey(
    user_id,
    **values
):

    if not values:
        return

    allowed = {

        "name",
        "level",
        "xp",
        "hunger",
        "thirst",
        "energy",
        "health",
        "clean",
        "strength",
        "speed",
        "luck",
        "defense",
        "last_update"
    }

    clean_values = {

        key: value

        for key, value
        in values.items()

        if key in allowed
    }

    if not clean_values:
        return

    fields = ", ".join(
        f"{key} = ?"
        for key in clean_values
    )

    params = list(
        clean_values.values()
    )

    params.append(user_id)

    execute(
        f"""
        UPDATE donkeys
        SET {fields}
        WHERE user_id = ?
        """,
        tuple(params),
        commit=True
    )


# ============================================================
# CLAMP DONKEY STATS
# ============================================================

def clamp_donkey_stats(
    donkey
):

    for stat, maximum in [

        ("hunger", 100),

        ("thirst", 100),

        ("energy", 100),

        ("health", 100),

        ("clean", 100)

    ]:

        donkey[stat] = max(
            0,
            min(
                maximum,
                int(donkey[stat])
            )
        )

    for stat in [

        "strength",
        "speed",
        "luck",
        "defense"

    ]:

        donkey[stat] = max(
            1,
            int(donkey[stat])
        )

    return donkey


# ============================================================
# DONKEY TIME DECAY
# ============================================================

def update_donkey_needs(
    user_id
):

    donkey = get_donkey(
        user_id
    )

    now = int(time.time())

    last = int(
        donkey.get(
            "last_update",
            now
        )
    )

    elapsed = max(
        0,
        now - last
    )

    if elapsed < DONKEY_DECAY_SECONDS:

        return donkey

    hours = elapsed // DONKEY_DECAY_SECONDS

    hunger_loss = min(
        40,
        hours * 5
    )

    thirst_loss = min(
        50,
        hours * 7
    )

    clean_loss = min(
        40,
        hours * 3
    )

    energy_loss = min(
        30,
        hours * 2
    )

    donkey["hunger"] -= hunger_loss

    donkey["thirst"] -= thirst_loss

    donkey["clean"] -= clean_loss

    donkey["energy"] -= energy_loss

    # وضعیت بد روی سلامتی اثر می‌گذارد
    bad_conditions = 0

    if donkey["hunger"] < 20:
        bad_conditions += 1

    if donkey["thirst"] < 20:
        bad_conditions += 1

    if donkey["clean"] < 20:
        bad_conditions += 1

    if bad_conditions:

        donkey["health"] -= (
            bad_conditions * hours
        )

    # انرژی کم
    if donkey["energy"] <= 0:

        donkey["health"] -= (
            max(1, hours)
        )

    donkey["last_update"] = now

    donkey = clamp_donkey_stats(
        donkey
    )

    update_donkey(
        user_id,

        hunger=donkey["hunger"],

        thirst=donkey["thirst"],

        clean=donkey["clean"],

        energy=donkey["energy"],

        health=donkey["health"],

        last_update=now
    )

    return donkey


# ============================================================
# DONKEY XP
# ============================================================

def donkey_xp_required(
    level
):

    return int(
        100 *
        (level ** 1.45)
    )


# ============================================================
# ADD DONKEY XP
# ============================================================

def add_donkey_xp(
    user_id,
    amount
):

    donkey = get_donkey(
        user_id
    )

    if donkey["level"] >= MAX_DONKEY_LEVEL:

        return False, 0

    donkey["xp"] += max(
        0,
        int(amount)
    )

    levels_gained = 0

    while (
        donkey["level"]
        < MAX_DONKEY_LEVEL
    ):

        required = donkey_xp_required(
            donkey["level"]
        )

        if donkey["xp"] < required:

            break

        donkey["xp"] -= required

        donkey["level"] += 1

        levels_gained += 1

        # افزایش پایه
        donkey["strength"] += 2

        donkey["speed"] += 2

        donkey["luck"] += 1

        donkey["defense"] += 2

        donkey["health"] = 100

        donkey["energy"] = 100

    update_donkey(

        user_id,

        level=donkey["level"],

        xp=donkey["xp"],

        strength=donkey["strength"],

        speed=donkey["speed"],

        luck=donkey["luck"],

        defense=donkey["defense"],

        health=donkey["health"],

        energy=donkey["energy"]
    )

    return True, levels_gained


# ============================================================
# DONKEY ACTION COSTS
# ============================================================

DONKEY_ACTIONS = {

    "feed": {
        "coins": 35,
        "hunger": 25,
        "energy": 3
    },

    "water": {
        "coins": 20,
        "thirst": 30
    },

    "bath": {
        "coins": 45,
        "clean": 40,
        "energy": 5
    },

    "sleep": {
        "coins": 30,
        "energy": 35,
        "hunger": 5,
        "thirst": 5
    }
}


# ============================================================
# FEED
# ============================================================

def feed_donkey(
    user_id
):

    donkey = update_donkey_needs(
        user_id
    )

    cost = DONKEY_ACTIONS[
        "feed"
    ]["coins"]

    if not remove_coins(
        user_id,
        cost
    ):

        return False, "❌ سکه کافی نداری."

    donkey["hunger"] += 25

    donkey["energy"] += 3

    donkey = clamp_donkey_stats(
        donkey
    )

    update_donkey(

        user_id,

        hunger=donkey["hunger"],

        energy=donkey["energy"],

        last_update=int(time.time())
    )

    return True, (

        "🥕 خر غذا خورد!\n\n"

        f"🍖 گرسنگی: "
        f"{donkey['hunger']}/100\n"

        f"⚡ انرژی: "
        f"{donkey['energy']}/100\n\n"

        f"💰 هزینه: {cost} 🪙"
    )


# ============================================================
# WATER
# ============================================================

def water_donkey(
    user_id
):

    donkey = update_donkey_needs(
        user_id
    )

    cost = DONKEY_ACTIONS[
        "water"
    ]["coins"]

    if not remove_coins(
        user_id,
        cost
    ):

        return False, "❌ سکه کافی نداری."

    donkey["thirst"] += 30

    donkey = clamp_donkey_stats(
        donkey
    )

    update_donkey(

        user_id,

        thirst=donkey["thirst"],

        last_update=int(time.time())
    )

    return True, (

        "💧 خر آب خورد!\n\n"

        f"💧 تشنگی: "
        f"{donkey['thirst']}/100\n\n"

        f"💰 هزینه: {cost} 🪙"
    )


# ============================================================
# BATH
# ============================================================

def bath_donkey(
    user_id
):

    donkey = update_donkey_needs(
        user_id
    )

    cost = DONKEY_ACTIONS[
        "bath"
    ]["coins"]

    if not remove_coins(
        user_id,
        cost
    ):

        return False, "❌ سکه کافی نداری."

    donkey["clean"] += 40

    donkey["energy"] -= 5

    donkey = clamp_donkey_stats(
        donkey
    )

    update_donkey(

        user_id,

        clean=donkey["clean"],

        energy=donkey["energy"],

        last_update=int(time.time())
    )

    return True, (

        "🛁 خر حمام کرد!\n\n"

        f"🧼 تمیزی: "
        f"{donkey['clean']}/100\n"

        f"⚡ انرژی: "
        f"{donkey['energy']}/100\n\n"

        f"💰 هزینه: {cost} 🪙"
    )


# ============================================================
# SLEEP
# ============================================================

def sleep_donkey(
    user_id
):

    donkey = update_donkey_needs(
        user_id
    )

    cost = DONKEY_ACTIONS[
        "sleep"
    ]["coins"]

    if not remove_coins(
        user_id,
        cost
    ):

        return False, "❌ سکه کافی نداری."

    donkey["energy"] += 35

    donkey["hunger"] -= 5

    donkey["thirst"] -= 5

    donkey = clamp_donkey_stats(
        donkey
    )

    update_donkey(

        user_id,

        energy=donkey["energy"],

        hunger=donkey["hunger"],

        thirst=donkey["thirst"],

        last_update=int(time.time())
    )

    return True, (

        "😴 خر خوابید!\n\n"

        f"⚡ انرژی: "
        f"{donkey['energy']}/100\n"

        f"🍖 گرسنگی: "
        f"{donkey['hunger']}/100\n"

        f"💧 تشنگی: "
        f"{donkey['thirst']}/100\n\n"

        f"💰 هزینه: {cost} 🪙"
    )


# ============================================================
# DONKEY PROFILE TEXT
# ============================================================

def donkey_profile_text(
    donkey
):

    level = donkey["level"]

    xp_required = donkey_xp_required(
        level
    )

    return (

        "🫏 **پروفایل خر من**\n"

        "━━━━━━━━━━━━━━━━\n\n"

        f"🏷 نام: **{donkey['name']}**\n"

        f"⭐ سطح: **{level}**\n"

        f"✨ XP: "
        f"**{donkey['xp']}/{xp_required}**\n\n"

        "❤️ وضعیت\n"

        f"❤️ سلامتی: "
        f"{donkey['health']}/100\n"

        f"🍖 گرسنگی: "
        f"{donkey['hunger']}/100\n"

        f"💧 تشنگی: "
        f"{donkey['thirst']}/100\n"

        f"⚡ انرژی: "
        f"{donkey['energy']}/100\n"

        f"🧼 تمیزی: "
        f"{donkey['clean']}/100\n\n"

        "⚔️ مهارت‌ها\n"

        f"💪 قدرت: "
        f"{donkey['strength']}\n"

        f"🏃 سرعت: "
        f"{donkey['speed']}\n"

        f"🍀 شانس: "
        f"{donkey['luck']}\n"

        f"🛡 دفاع: "
        f"{donkey['defense']}\n"
    )


# ============================================================
# DONKEY KEYBOARD
# ============================================================

def donkey_keyboard():

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton(
                "🥕 غذا",
                callback_data="donkey_feed"
            ),

            InlineKeyboardButton(
                "💧 آب",
                callback_data="donkey_water"
            )

        ],

        [

            InlineKeyboardButton(
                "🛁 حمام",
                callback_data="donkey_bath"
            ),

            InlineKeyboardButton(
                "😴 خواب",
                callback_data="donkey_sleep"
            )

        ],

        [

            InlineKeyboardButton(
                "⬆️ ارتقا",
                callback_data="donkey_upgrade"
            ),

            InlineKeyboardButton(
                "🏪 فروشگاه",
                callback_data="donkey_shop"
            )

        ]

    ])


# ============================================================
# DONKEY PROFILE COMMAND
# ============================================================

async def donkey_profile(
    update,
    context
):

    user = update.effective_user

    donkey = update_donkey_needs(
        user.id
    )

    await update.message.reply_text(

        donkey_profile_text(
            donkey
        ),

        reply_markup=
        donkey_keyboard()
    )


# ============================================================
# DONKEY CALLBACKS
# ============================================================

async def donkey_callback_handler(
    update,
    context
):

    query = update.callback_query

    data = query.data

    user_id = query.from_user.id

    if data == "donkey_feed":

        success, text = feed_donkey(
            user_id
        )

        await query.answer(
            "🥕 غذا داده شد!"
            if success
            else "❌ سکه کافی نیست."
        )

        donkey = update_donkey_needs(
            user_id
        )

        await query.edit_message_text(

            donkey_profile_text(
                donkey
            ),

            reply_markup=
            donkey_keyboard()
        )

        return True

    if data == "donkey_water":

        success, text = water_donkey(
            user_id
        )

        await query.answer(
            "💧 آب داده شد!"
            if success
            else "❌ سکه کافی نیست."
        )

        donkey = update_donkey_needs(
            user_id
        )

        await query.edit_message_text(

            donkey_profile_text(
                donkey
            ),

            reply_markup=
            donkey_keyboard()
        )

        return True

    if data == "donkey_bath":

        success, text = bath_donkey(
            user_id
        )

        await query.answer(
            "🛁 خر حمام کرد!"
            if success
            else "❌ سکه کافی نیست."
        )

        donkey = update_donkey_needs(
            user_id
        )

        await query.edit_message_text(

            donkey_profile_text(
                donkey
            ),

            reply_markup=
            donkey_keyboard()
        )

        return True

    if data == "donkey_sleep":

        success, text = sleep_donkey(
            user_id
        )

        await query.answer(
            "😴 خر خوابید!"
            if success
            else "❌ سکه کافی نیست."
        )

        donkey = update_donkey_needs(
            user_id
        )

        await query.edit_message_text(

            donkey_profile_text(
                donkey
            ),

            reply_markup=
            donkey_keyboard()
        )

        return True

    return False

# ============================================================
# KHARBOT V9
# 👥 MULTIPLAYER GROUP GAME ENGINE
# ============================================================

GROUP_GAMES = {}

GROUP_GAME_MIN_PLAYERS = 2
GROUP_GAME_MAX_PLAYERS = 8

GROUP_GAME_TIMEOUT = 180


# ============================================================
# GROUP GAME CLASS
# ============================================================

class GroupGame:

    def __init__(
        self,
        game_id,
        chat_id,
        creator_id,
        game_type,
        bet
    ):

        self.game_id = game_id

        self.chat_id = chat_id

        self.creator_id = creator_id

        self.game_type = game_type

        self.bet = bet

        self.players = {}

        self.started = False

        self.finished = False

        self.created_at = time.time()

        self.message_id = None

        self.turn = 0

    def add_player(
        self,
        user_id,
        name
    ):

        if self.started:
            return False

        if len(self.players) >= GROUP_GAME_MAX_PLAYERS:
            return False

        if user_id in self.players:
            return False

        self.players[user_id] = {

            "id": user_id,

            "name": name,

            "score": 0,

            "alive": True,

            "move": None,

            "coins_won": 0
        }

        return True

    def remove_player(
        self,
        user_id
    ):

        if user_id in self.players:

            del self.players[user_id]

            return True

        return False


# ============================================================
# CREATE GROUP GAME
# ============================================================

async def create_group_game(
    update,
    context,
    game_type,
    bet
):

    chat = update.effective_chat

    user = update.effective_user

    if chat.type == "private":

        await update.message.reply_text(

            "❌ بازی گروهی فقط داخل گروه قابل اجراست."
        )

        return

    # بررسی بازی فعال کاربر
    for game in GROUP_GAMES.values():

        if (
            user.id in game.players
            and not game.finished
        ):

            await update.message.reply_text(

                "❌ تو همین الان داخل یک بازی هستی."
            )

            return

    if bet <= 0:

        await update.message.reply_text(
            "❌ مبلغ شرط نامعتبر است."
        )

        return

    if not remove_coins(
        user.id,
        bet
    ):

        await update.message.reply_text(

            "❌ سکه کافی نداری."
        )

        return

    game_id = (

        f"GRP_"
        f"{chat.id}_"
        f"{int(time.time())}_"
        f"{random.randint(1000,9999)}"

    )

    game = GroupGame(

        game_id=game_id,

        chat_id=chat.id,

        creator_id=user.id,

        game_type=game_type,

        bet=bet
    )

    game.add_player(

        user.id,

        user.first_name
        or "بازیکن"
    )

    GROUP_GAMES[
        game_id
    ] = game

    keyboard = group_lobby_keyboard(
        game
    )

    msg = await context.bot.send_message(

        chat_id=chat.id,

        text=group_lobby_text(
            game
        ),

        reply_markup=keyboard
    )

    game.message_id = msg.message_id


# ============================================================
# LOBBY TEXT
# ============================================================

def group_lobby_text(
    game
):

    text = (

        "🎮 **اتاق بازی گروهی**\n"

        "━━━━━━━━━━━━━━━━\n\n"

        f"🎯 بازی: "
        f"**{game.game_type}**\n"

        f"💰 ورودی: "
        f"**{game.bet:,} 🪙**\n\n"

        f"👥 بازیکنان: "
        f"**{len(game.players)}/"
        f"{GROUP_GAME_MAX_PLAYERS}**\n\n"
    )

    number = 1

    for player in game.players.values():

        text += (

            f"{number}. "
            f"🫏 {player['name']}\n"
        )

        number += 1

    text += (

        "\n👇 برای ورود به بازی روی "
        "«ورود» بزن."
    )

    return text


# ============================================================
# LOBBY KEYBOARD
# ============================================================

def group_lobby_keyboard(
    game
):

    keyboard = [

        [

            InlineKeyboardButton(

                "🎮 ورود",

                callback_data=
                f"group_join_{game.game_id}"

            ),

            InlineKeyboardButton(

                "🚪 خروج",

                callback_data=
                f"group_leave_{game.game_id}"

            )

        ]

    ]

    if (
        len(game.players)
        >= GROUP_GAME_MIN_PLAYERS
    ):

        keyboard.append([

            InlineKeyboardButton(

                "▶️ شروع بازی",

                callback_data=
                f"group_start_{game.game_id}"

            )

        ])

    keyboard.append([

        InlineKeyboardButton(

            "❌ لغو اتاق",

            callback_data=
            f"group_cancel_{game.game_id}"

        )

    ])

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# JOIN GROUP GAME
# ============================================================

async def group_join(
    update,
    context,
    game_id
):

    query = update.callback_query

    user = query.from_user

    game = GROUP_GAMES.get(
        game_id
    )

    if not game:

        await query.answer(

            "❌ این اتاق دیگر وجود ندارد.",

            show_alert=True
        )

        return

    if game.started:

        await query.answer(

            "❌ بازی شروع شده.",

            show_alert=True
        )

        return

    if len(game.players) >= GROUP_GAME_MAX_PLAYERS:

        await query.answer(

            "❌ اتاق پر است.",

            show_alert=True
        )

        return

    if user.id in game.players:

        await query.answer(

            "تو قبلاً وارد شدی.",
            show_alert=True
        )

        return

    # بررسی بازی دیگر
    for other in GROUP_GAMES.values():

        if (
            user.id in other.players
            and not other.finished
        ):

            await query.answer(

                "❌ تو در یک بازی دیگر هستی.",

                show_alert=True
            )

            return

    if not remove_coins(
        user.id,
        game.bet
    ):

        await query.answer(

            "❌ سکه کافی نداری.",

            show_alert=True
        )

        return

    game.add_player(

        user.id,

        user.first_name
        or "بازیکن"
    )

    await query.answer(
        "🎮 وارد بازی شدی!"
    )

    await query.edit_message_text(

        group_lobby_text(
            game
        ),

        reply_markup=
        group_lobby_keyboard(
            game
        )
    )


# ============================================================
# LEAVE GROUP GAME
# ============================================================

async def group_leave(
    update,
    context,
    game_id
):

    query = update.callback_query

    user = query.from_user

    game = GROUP_GAMES.get(
        game_id
    )

    if not game:

        await query.answer(
            "❌ اتاق پیدا نشد.",
            show_alert=True
        )

        return

    if game.started:

        await query.answer(

            "❌ بازی شروع شده و نمی‌توانی خارج شوی.",

            show_alert=True
        )

        return

    if user.id not in game.players:

        await query.answer(

            "تو داخل این بازی نیستی.",
            show_alert=True
        )

        return

    game.remove_player(
        user.id
    )

    # برگشت شرط
    add_coins(
        user.id,
        game.bet
    )

    await query.answer(
        "🚪 از بازی خارج شدی."
    )

    if not game.players:

        GROUP_GAMES.pop(
            game_id,
            None
        )

        await query.edit_message_text(

            "❌ اتاق خالی شد و حذف شد."
        )

        return

    await query.edit_message_text(

        group_lobby_text(
            game
        ),

        reply_markup=
        group_lobby_keyboard(
            game
        )
    )


# ============================================================
# CANCEL GROUP GAME
# ============================================================

async def group_cancel(
    update,
    context,
    game_id
):

    query = update.callback_query

    user = query.from_user

    game = GROUP_GAMES.get(
        game_id
    )

    if not game:

        await query.answer(
            "❌ اتاق پیدا نشد.",
            show_alert=True
        )

        return

    if game.started:

        await query.answer(

            "❌ بازی شروع شده.",
            show_alert=True
        )

        return

    if user.id != game.creator_id:

        await query.answer(

            "❌ فقط سازنده اتاق می‌تواند آن را لغو کند.",

            show_alert=True
        )

        return

    # برگشت پول همه
    for player in game.players.values():

        add_coins(

            player["id"],

            game.bet
        )

    game.finished = True

    GROUP_GAMES.pop(
        game_id,
        None
    )

    await query.answer(
        "اتاق لغو شد."
    )

    await query.edit_message_text(

        "❌ **بازی لغو شد.**\n\n"

        "💰 ورودی همه بازیکنان برگشت داده شد."
    )


# ============================================================
# START GROUP GAME
# ============================================================

async def group_start(
    update,
    context,
    game_id
):

    query = update.callback_query

    user = query.from_user

    game = GROUP_GAMES.get(
        game_id
    )

    if not game:

        await query.answer(

            "❌ اتاق پیدا نشد.",
            show_alert=True
        )

        return

    if user.id != game.creator_id:

        await query.answer(

            "❌ فقط سازنده می‌تواند بازی را شروع کند.",

            show_alert=True
        )

        return

    if len(game.players) < GROUP_GAME_MIN_PLAYERS:

        await query.answer(

            f"❌ حداقل "
            f"{GROUP_GAME_MIN_PLAYERS} بازیکن لازم است.",

            show_alert=True
        )

        return

    if game.started:

        await query.answer(
            "بازی قبلاً شروع شده."
        )

        return

    game.started = True

    await query.answer(
        "🔥 بازی شروع شد!"
    )

    await query.edit_message_text(

        "🔥 **بازی شروع شد!**\n\n"

        f"🎯 {game.game_type}\n"

        f"👥 بازیکنان: "
        f"{len(game.players)}\n\n"

        "🤖 سیستم در حال آماده‌سازی بازی..."
    )

    await asyncio.sleep(1)

    await run_group_game(
        context,
        game
    )


# ============================================================
# GROUP GAME ENGINE
# ============================================================

async def run_group_game(
    context,
    game
):

    if game.finished:
        return

    if game.game_type == "🎲 تاس":

        await group_dice_game(
            context,
            game
        )

        return

    if game.game_type == "🏁 مسابقه خرها":

        await group_race_game(
            context,
            game
        )

        return

    if game.game_type == "⚔️ دوئل خرها":

        await group_duel_game(
            context,
            game
        )

        return

    if game.game_type == "🍀 شانس":

        await group_luck_game(
            context,
            game
        )

        return

    await group_luck_game(
        context,
        game
    )


# ============================================================
# GROUP DICE
# ============================================================

async def group_dice_game(
    context,
    game
):

    results = []

    for player in game.players.values():

        roll = random.randint(
            1,
            6
        )

        player["score"] = roll

        results.append(
            (
                player["name"],
                roll
            )
        )

    results.sort(
        key=lambda x: x[1],
        reverse=True
    )

    winner = results[0]

    # جایزه
    prize = (
        game.bet *
        len(game.players)
    )

    add_coins(
        game.players[
            next(
                uid
                for uid, p
                in game.players.items()
                if p["name"] == winner[0]
            )
        ]["id"],
        prize
    )

    text = (
        "🎲 **نتیجه تاس گروهی**\n"
        "━━━━━━━━━━━━━━━━\n\n"
    )

    rank = 1

    for name, score in results:

        text += (

            f"{rank}. "
            f"🫏 {name} — "
            f"🎲 {score}\n"
        )

        rank += 1

    text += (

        "\n🏆 برنده: "
        f"**{winner[0]}**\n"

        f"💰 جایزه: "
        f"{prize:,} 🪙"
    )

    game.finished = True

    await context.bot.send_message(

        chat_id=game.chat_id,

        text=text
    )

    GROUP_GAMES.pop(
        game.game_id,
        None
    )


# ============================================================
# GROUP RACE
# ============================================================

async def group_race_game(
    context,
    game
):

    results = []

    for player in game.players.values():

        donkey = update_donkey_needs(
            player["id"]
        )

        # وضعیت خر روی مسابقه اثر دارد
        base = (

            donkey["speed"] * 2

            + donkey["energy"] * 0.25

            + donkey["health"] * 0.15

        )

        random_part = random.randint(
            0,
            35
        )

        score = int(
            base +
            random_part
        )

        player["score"] = score

        results.append(
            (
                player["id"],
                player["name"],
                score
            )
        )

    results.sort(
        key=lambda x: x[2],
        reverse=True
    )

    total_prize = (
        game.bet *
        len(game.players)
    )

    # تقسیم جایزه
    prize_table = {

        1: 0.70,

        2: 0.20,

        3: 0.10
    }

    text = (
        "🏁 **مسابقه خرها**\n"
        "━━━━━━━━━━━━━━━━\n\n"
    )

    for index, (
        user_id,
        name,
        score
    ) in enumerate(
        results,
        start=1
    ):

        prize = int(

            total_prize *
            prize_table.get(
                index,
                0
            )
        )

        if prize > 0:

            add_coins(
                user_id,
                prize
            )

        text += (

            f"{index}. "
            f"🫏 {name}\n"

            f"   🏃 امتیاز: "
            f"{score}\n"

            f"   💰 +{prize:,} 🪙\n\n"
        )

    game.finished = True

    await context.bot.send_message(

        chat_id=game.chat_id,

        text=text
    )

    GROUP_GAMES.pop(
        game.game_id,
        None
    )


# ============================================================
# GROUP LUCK
# ============================================================

async def group_luck_game(
    context,
    game
):

    results = []

    for player in game.players.values():

        donkey = update_donkey_needs(
            player["id"]
        )

        luck_bonus = (
            donkey["luck"] // 2
        )

        score = (
            random.randint(
                1,
                100
            )
            +
            luck_bonus
        )

        player["score"] = score

        results.append(
            (
                player["id"],
                player["name"],
                score
            )
        )

    results.sort(
        key=lambda x: x[2],
        reverse=True
    )

    total_prize = (
        game.bet *
        len(game.players)
    )

    winner_id = results[0][0]

    add_coins(
        winner_id,
        total_prize
    )

    text = (
        "🍀 **بازی شانس گروهی**\n"
        "━━━━━━━━━━━━━━━━\n\n"
    )

    for index, (
        user_id,
        name,
        score
    ) in enumerate(
        results,
        start=1
    ):

        text += (

            f"{index}. "
            f"🫏 {name} — "
            f"{score}\n"
        )

    text += (

        "\n🏆 برنده: "
        f"**{results[0][1]}**\n"

        f"💰 جایزه: "
        f"{total_prize:,} 🪙"
    )

    game.finished = True

    await context.bot.send_message(

        chat_id=game.chat_id,

        text=text
    )

    GROUP_GAMES.pop(
        game.game_id,
        None
    )


# ============================================================
# GROUP DUEL
# ============================================================

async def group_duel_game(
    context,
    game
):

    players = list(
        game.players.values()
    )

    # HP
    for player in players:

        donkey = update_donkey_needs(
            player["id"]
        )

        player["hp"] = (
            100 +
            donkey["defense"] * 2
        )

        player["damage"] = (
            10 +
            donkey["strength"] * 2
        )

    # نبرد
    rounds = 0

    while (
        len(
            [
                p for p in players
                if p["hp"] > 0
            ]
        ) > 1

        and rounds < 50
    ):

        rounds += 1

        alive = [
            p for p in players
            if p["hp"] > 0
        ]

        for attacker in alive:

            targets = [
                p for p in alive
                if p["id"]
                != attacker["id"]
                and p["hp"] > 0
            ]

            if not targets:
                break

            target = random.choice(
                targets
            )

            damage = random.randint(
                max(
                    5,
                    attacker["damage"] - 8
                ),
                attacker["damage"] + 8
            )

            target["hp"] -= damage

    alive = [
        p for p in players
        if p["hp"] > 0
    ]

    if alive:

        winner = alive[0]

    else:

        winner = max(
            players,
            key=lambda p: p["hp"]
        )

    prize = (
        game.bet *
        len(players)
    )

    add_coins(
        winner["id"],
        prize
    )

    text = (

        "⚔️ **دوئل گروهی خرها**\n"
        "━━━━━━━━━━━━━━━━\n\n"
    )

    for player in sorted(
        players,
        key=lambda p: p["hp"],
        reverse=True
    ):

        text += (

            f"🫏 {player['name']}\n"

            f"❤️ HP: "
            f"{max(0, player['hp'])}\n\n"
        )

    text += (

        f"🏆 برنده: "
        f"**{winner['name']}**\n"

        f"💰 جایزه: "
        f"{prize:,} 🪙"
    )

    game.finished = True

    await context.bot.send_message(

        chat_id=game.chat_id,

        text=text
    )

    GROUP_GAMES.pop(
        game.game_id,
        None
    )


# ============================================================
# GROUP CALLBACK HANDLER
# ============================================================

async def group_callback_handler(
    update,
    context
):

    query = update.callback_query

    data = query.data

    if data.startswith(
        "group_join_"
    ):

        game_id = data.replace(
            "group_join_",
            "",
            1
        )

        await group_join(
            update,
            context,
            game_id
        )

        return True

    if data.startswith(
        "group_leave_"
    ):

        game_id = data.replace(
            "group_leave_",
            "",
            1
        )

        await group_leave(
            update,
            context,
            game_id
        )

        return True

    if data.startswith(
        "group_start_"
    ):

        game_id = data.replace(
            "group_start_",
            "",
            1
        )

        await group_start(
            update,
            context,
            game_id
        )

        return True

    if data.startswith(
        "group_cancel_"
    ):

        game_id = data.replace(
            "group_cancel_",
            "",
            1
        )

        await group_cancel(
            update,
            context,
            game_id
        )

        return True

    return False


# ============================================================
# CLEANUP ABANDONED GROUP GAMES
# ============================================================

async def cleanup_group_games(
    context
):

    now = time.time()

    expired = []

    for game_id, game in list(
        GROUP_GAMES.items()
    ):

        if game.finished:

            expired.append(
                game_id
            )

            continue

        if (
            now -
            game.created_at
            >
            GROUP_GAME_TIMEOUT
        ):

            for player in game.players.values():

                add_coins(
                    player["id"],
                    game.bet
                )

            expired.append(
                game_id
            )

            try:

                await context.bot.send_message(

                    chat_id=game.chat_id,

                    text=(
                        "⏰ **اتاق بازی منقضی شد.**\n\n"
                        "💰 ورودی همه بازیکنان برگشت داده شد."
                    )
                )

            except Exception:

                pass

    for game_id in expired:

        GROUP_GAMES.pop(
            game_id,
            None
    )
        # ============================================================
# KHARBOT V10
# 🫏 XP + BRAY + DAILY QUEST + STREAK + LEADERBOARD
# ============================================================

# ============================================================
# TABLES
# ============================================================

execute("""
CREATE TABLE IF NOT EXISTS donkey_progress (
    user_id INTEGER PRIMARY KEY,
    xp INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 1,
    total_brays INTEGER NOT NULL DEFAULT 0,
    total_games INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    best_score INTEGER NOT NULL DEFAULT 0
)
""", commit=True)


execute("""
CREATE TABLE IF NOT EXISTS daily_rewards (
    user_id INTEGER PRIMARY KEY,
    last_claim TEXT,
    streak INTEGER NOT NULL DEFAULT 0
)
""", commit=True)


execute("""
CREATE TABLE IF NOT EXISTS daily_quests (
    user_id INTEGER NOT NULL,
    quest_date TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    target INTEGER NOT NULL,
    reward_coins INTEGER NOT NULL,
    reward_xp INTEGER NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(user_id, quest_date, quest_id)
)
""", commit=True)


# ============================================================
# XP SYSTEM
# ============================================================

def xp_for_level(level):

    return int(
        100 *
        (level ** 1.45)
    )


def get_progress(user_id):

    row = fetchone(
        """
        SELECT
            xp,
            level,
            total_brays,
            total_games,
            wins,
            losses,
            best_score
        FROM donkey_progress
        WHERE user_id = ?
        """,
        (user_id,)
    )

    if not row:

        execute(
            """
            INSERT OR IGNORE INTO donkey_progress
            (user_id)
            VALUES (?)
            """,
            (user_id,),
            commit=True
        )

        return {
            "xp": 0,
            "level": 1,
            "total_brays": 0,
            "total_games": 0,
            "wins": 0,
            "losses": 0,
            "best_score": 0
        }

    return {
        "xp": row[0],
        "level": row[1],
        "total_brays": row[2],
        "total_games": row[3],
        "wins": row[4],
        "losses": row[5],
        "best_score": row[6]
    }


# ============================================================
# ADD XP
# ============================================================

def add_xp(user_id, amount):

    if amount <= 0:
        return 0, False

    progress = get_progress(user_id)

    old_level = progress["level"]

    new_xp = progress["xp"] + amount
    new_level = old_level

    while (
        new_xp >=
        xp_for_level(new_level + 1)
    ):
        new_level += 1

    execute(
        """
        UPDATE donkey_progress

        SET xp = ?,
            level = ?

        WHERE user_id = ?
        """,
        (
            new_xp,
            new_level,
            user_id
        ),
        commit=True
    )

    return (
        new_level,
        new_level > old_level
    )


# ============================================================
# RECORD GAME
# ============================================================

def record_game_result(
    user_id,
    won,
    score=0
):

    progress = get_progress(
        user_id
    )

    games = (
        progress["total_games"]
        + 1
    )

    wins = progress["wins"]

    losses = progress["losses"]

    if won:
        wins += 1
    else:
        losses += 1

    best_score = max(
        progress["best_score"],
        score
    )

    execute(
        """
        UPDATE donkey_progress

        SET total_games = ?,
            wins = ?,
            losses = ?,
            best_score = ?

        WHERE user_id = ?
        """,
        (
            games,
            wins,
            losses,
            best_score,
            user_id
        ),
        commit=True
    )

    xp = 50 if won else 20

    add_xp(
        user_id,
        xp
    )


# ============================================================
# BRAY SOUNDS
# ============================================================

BRAY_SOUNDS = [

    {
        "id": "classic",
        "name": "🫏 عررر معمولی",
        "text": "عرررررررررر! 🫏",
        "reward": 8
    },

    {
        "id": "long",
        "name": "📢 عرررر طولانی",
        "text": "عــــررررررررررررررر! 🫏",
        "reward": 12
    },

    {
        "id": "angry",
        "name": "😡 عررر عصبانی",
        "text": "عَررررررررر! 😡🫏",
        "reward": 15
    },

    {
        "id": "baby",
        "name": "🥹 عررر بچگانه",
        "text": "عرر... عرر... 🥹🫏",
        "reward": 10
    },

    {
        "id": "king",
        "name": "👑 عررر پادشاهی",
        "text": "عــــرررررر! 👑🫏",
        "reward": 20
    },

    {
        "id": "crazy",
        "name": "🤪 عررر دیوانه",
        "text": "عَر عَر عَرررررررر! 🤪",
        "reward": 25
    }
]


def get_bray(
    bray_id
):

    for bray in BRAY_SOUNDS:

        if bray["id"] == bray_id:
            return bray

    return BRAY_SOUNDS[0]


# ============================================================
# BRAY COOLDOWN
# ============================================================

BRAY_COOLDOWN = {}


def can_bray(user_id):

    now = time.time()

    last = BRAY_COOLDOWN.get(
        user_id,
        0
    )

    if now - last < 8:

        return False

    BRAY_COOLDOWN[user_id] = now

    return True


# ============================================================
# BRAY ACTION
# ============================================================

async def do_bray(
    update,
    context,
    bray_id="classic"
):

    user = update.effective_user

    user_id = user.id

    if not can_bray(user_id):

        await update.message.reply_text(

            "⏳ خر تو هنوز داره نفس می‌گیره 😂\n"
            "چند ثانیه دیگه دوباره عر بکش."
        )

        return

    bray = get_bray(
        bray_id
    )

    # پاداش
    base_reward = bray["reward"]

    bonus = random.randint(
        0,
        5
    )

    coins = (
        base_reward +
        bonus
    )

    add_coins(
        user_id,
        coins
    )

    add_xp(
        user_id,
        5
    )

    execute(
        """
        UPDATE donkey_progress

        SET total_brays =
            total_brays + 1

        WHERE user_id = ?
        """,
        (user_id,),
        commit=True
    )

    # مأموریت عرعر
    update_quest_progress(
        user_id,
        "bray",
        1
    )

    await update.message.reply_text(

        f"{bray['text']}\n\n"

        f"🎁 +{coins} 🪙\n"
        f"⭐ +5 XP"
    )


# ============================================================
# DAILY REWARD
# ============================================================

DAILY_REWARDS = {

    1: 500,
    2: 650,
    3: 800,
    4: 1000,
    5: 1300,
    6: 1700,
    7: 2500
}


def today_string():

    return time.strftime(
        "%Y-%m-%d"
    )


def yesterday_string():

    return time.strftime(
        "%Y-%m-%d",
        time.localtime(
            time.time() - 86400
        )
    )


def claim_daily(
    user_id
):

    today = today_string()

    row = fetchone(
        """
        SELECT
            last_claim,
            streak
        FROM daily_rewards
        WHERE user_id = ?
        """,
        (user_id,)
    )

    if not row:

        streak = 1

    else:

        last_claim = row[0]
        old_streak = row[1]

        if last_claim == today:

            return False, (
                "⏰ پاداش امروزت رو گرفتی."
            )

        if last_claim == yesterday_string():

            streak = old_streak + 1

        else:

            streak = 1

    if streak > 7:
        streak = 1

    reward = DAILY_REWARDS[
        streak
    ]

    add_coins(
        user_id,
        reward
    )

    add_xp(
        user_id,
        30
    )

    execute(
        """
        INSERT INTO daily_rewards
        (
            user_id,
            last_claim,
            streak
        )

        VALUES (?, ?, ?)

        ON CONFLICT(user_id)

        DO UPDATE SET
            last_claim = excluded.last_claim,
            streak = excluded.streak
        """,
        (
            user_id,
            today,
            streak
        ),
        commit=True
    )

    return True, (
        "🎁 **پاداش روزانه دریافت شد!**\n\n"

        f"🔥 Streak: {streak}/7\n"

        f"🪙 +{reward:,} سکه\n"

        "⭐ +30 XP"
    )


# ============================================================
# DAILY QUESTS
# ============================================================

QUESTS = {

    "bray": {
        "name": "🫏 عرعر کن",
        "target": 5,
        "coins": 250,
        "xp": 40
    },

    "games": {
        "name": "🎮 بازی کن",
        "target": 3,
        "coins": 400,
        "xp": 70
    },

    "win": {
        "name": "🏆 برنده شو",
        "target": 1,
        "coins": 700,
        "xp": 100
    },

    "feed": {
        "name": "🥕 خر را غذا بده",
        "target": 2,
        "coins": 250,
        "xp": 40
    },

    "clean": {
        "name": "🧼 خر را تمیز کن",
        "target": 1,
        "coins": 300,
        "xp": 50
    }
}


def ensure_daily_quests(
    user_id
):

    today = today_string()

    for quest_id, quest in QUESTS.items():

        exists = fetchone(
            """
            SELECT 1

            FROM daily_quests

            WHERE user_id = ?

            AND quest_date = ?

            AND quest_id = ?
            """,
            (
                user_id,
                today,
                quest_id
            )
        )

        if exists:
            continue

        execute(
            """
            INSERT INTO daily_quests

            (
                user_id,
                quest_date,
                quest_id,
                progress,
                target,
                reward_coins,
                reward_xp
            )

            VALUES (?, ?, ?, 0, ?, ?, ?)
            """,
            (
                user_id,
                today,
                quest_id,
                quest["target"],
                quest["coins"],
                quest["xp"]
            ),
            commit=True
        )


def update_quest_progress(
    user_id,
    quest_id,
    amount=1
):

    if quest_id not in QUESTS:
        return

    ensure_daily_quests(
        user_id
    )

    today = today_string()

    row = fetchone(
        """
        SELECT
            progress,
            target,
            completed

        FROM daily_quests

        WHERE user_id = ?

        AND quest_date = ?

        AND quest_id = ?
        """,
        (
            user_id,
            today,
            quest_id
        )
    )

    if not row:
        return

    progress = row[0]
    target = row[1]
    completed = row[2]

    if completed:
        return

    progress = min(
        progress + amount,
        target
    )

    execute(
        """
        UPDATE daily_quests

        SET progress = ?

        WHERE user_id = ?

        AND quest_date = ?

        AND quest_id = ?
        """,
        (
            progress,
            user_id,
            today,
            quest_id
        ),
        commit=True
    )


# ============================================================
# CLAIM QUEST
# ============================================================

def claim_quest(
    user_id,
    quest_id
):

    ensure_daily_quests(
        user_id
    )

    today = today_string()

    row = fetchone(
        """
        SELECT
            progress,
            target,
            reward_coins,
            reward_xp,
            completed

        FROM daily_quests

        WHERE user_id = ?

        AND quest_date = ?

        AND quest_id = ?
        """,
        (
            user_id,
            today,
            quest_id
        )
    )

    if not row:

        return False, (
            "❌ مأموریت پیدا نشد."
        )

    progress = row[0]
    target = row[1]
    coins = row[2]
    xp = row[3]
    completed = row[4]

    if completed:

        return False, (
            "❌ جایزه قبلاً دریافت شده."
        )

    if progress < target:

        return False, (
            f"⏳ هنوز کامل نشده.\n\n"
            f"📊 {progress}/{target}"
        )

    execute(
        """
        UPDATE daily_quests

        SET completed = 1

        WHERE user_id = ?

        AND quest_date = ?

        AND quest_id = ?
        """,
        (
            user_id,
            today,
            quest_id
        ),
        commit=True
    )

    add_coins(
        user_id,
        coins
    )

    add_xp(
        user_id,
        xp
    )

    return True, (
        "🎉 **مأموریت کامل شد!**\n\n"

        f"🪙 +{coins:,}\n"

        f"⭐ +{xp} XP"
    )


# ============================================================
# QUEST TEXT
# ============================================================

def quests_text(
    user_id
):

    ensure_daily_quests(
        user_id
    )

    today = today_string()

    rows = fetchall(
        """
        SELECT
            quest_id,
            progress,
            target,
            reward_coins,
            reward_xp,
            completed

        FROM daily_quests

        WHERE user_id = ?

        AND quest_date = ?
        """,
        (
            user_id,
            today
        )
    )

    text = (
        "📜 **مأموریت‌های امروز**\n"
        "━━━━━━━━━━━━━━━━\n\n"
    )

    for row in rows:

        quest_id = row[0]

        progress = row[1]

        target = row[2]

        coins = row[3]

        xp = row[4]

        completed = row[5]

        quest = QUESTS.get(
            quest_id
        )

        if not quest:
            continue

        status = (
            "✅"
            if completed
            else "🔄"
        )

        text += (

            f"{status} {quest['name']}\n"

            f"📊 {progress}/{target}\n"

            f"🎁 {coins:,} 🪙 + "
            f"{xp} XP\n\n"
        )

    return text


# ============================================================
# QUEST KEYBOARD
# ============================================================

def quests_keyboard(
    user_id
):

    ensure_daily_quests(
        user_id
    )

    today = today_string()

    rows = fetchall(
        """
        SELECT
            quest_id,
            progress,
            target,
            completed

        FROM daily_quests

        WHERE user_id = ?

        AND quest_date = ?
        """,
        (
            user_id,
            today
        )
    )

    keyboard = []

    for row in rows:

        quest_id = row[0]

        progress = row[1]

        target = row[2]

        completed = row[3]

        if (
            progress >= target
            and not completed
        ):

            keyboard.append([

                InlineKeyboardButton(

                    f"🎁 دریافت "
                    f"{QUESTS[quest_id]['name']}",

                    callback_data=
                    f"claimquest_{quest_id}"
                )

            ])

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# LEADERBOARD
# ============================================================

def leaderboard_text():

    rows = fetchall(
        """
        SELECT
            user_id,
            level,
            xp,
            wins,
            total_games,
            total_brays

        FROM donkey_progress

        ORDER BY
            level DESC,
            xp DESC,
            wins DESC

        LIMIT 10
        """
    )

    if not rows:

        return (
            "🏆 هنوز کسی وارد جدول نشده."
        )

    text = (
        "🏆 **لیدربرد خرستان**\n"
        "━━━━━━━━━━━━━━━━\n\n"
    )

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    for index, row in enumerate(
        rows,
        start=1
    ):

        user_id = row[0]

        level = row[1]

        xp = row[2]

        wins = row[3]

        games = row[4]

        brays = row[5]

        medal = (
            medals[index - 1]
            if index <= 3
            else f"{index}."
        )

        text += (

            f"{medal} "
            f"`{user_id}`\n"

            f"   ⭐ Level {level} | "
            f"XP {xp:,}\n"

            f"   🏆 {wins} برد | "
            f"🎮 {games} بازی | "
            f"🫏 {brays} عر\n\n"
        )

    return text


# ============================================================
# PROFILE
# ============================================================

def progress_text(
    user_id
):

    p = get_progress(
        user_id
    )

    next_xp = xp_for_level(
        p["level"] + 1
    )

    return (

        "⭐ **پیشرفت خر**\n"
        "━━━━━━━━━━━━━━━━\n\n"

        f"🏅 Level: "
        f"**{p['level']}**\n"

        f"⭐ XP: "
        f"**{p['xp']:,}** / "
        f"{next_xp:,}\n\n"

        f"🫏 عرعر: "
        f"{p['total_brays']:,}\n"

        f"🎮 بازی‌ها: "
        f"{p['total_games']:,}\n"

        f"🏆 برد: "
        f"{p['wins']:,}\n"

        f"💀 باخت: "
        f"{p['losses']:,}\n"

        f"🔥 بهترین امتیاز: "
        f"{p['best_score']:,}"
    )


# ============================================================
# BRAY KEYBOARD
# ============================================================

def bray_keyboard():

    rows = []

    for bray in BRAY_SOUNDS:

        rows.append([

            InlineKeyboardButton(

                f"{bray['name']} "
                f"(+{bray['reward']}🪙)",

                callback_data=
                f"bray_{bray['id']}"
            )

        ])

    return InlineKeyboardMarkup(
        rows
    )


# ============================================================
# MAIN PROGRESS KEYBOARD
# ============================================================

def progress_keyboard():

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton(
                "🫏 عرعر",
                callback_data="bray_menu"
            ),

            InlineKeyboardButton(
                "📜 مأموریت",
                callback_data="quests"
            )

        ],

        [

            InlineKeyboardButton(
                "🎁 پاداش روزانه",
                callback_data="daily"
            ),

            InlineKeyboardButton(
                "🏆 لیدربرد",
                callback_data="leaderboard"
            )

        ]

    ])


# ============================================================
# PROGRESS CALLBACK
# ============================================================

async def progress_callback_handler(
    update,
    context
):

    query = update.callback_query

    data = query.data

    user_id = query.from_user.id

    # --------------------------------------------------------
    # BRAY MENU
    # --------------------------------------------------------

    if data == "bray_menu":

        await query.answer()

        await query.edit_message_text(

            "🫏 **صدای خر خودت را انتخاب کن!**\n\n"
            "هر عرعر مقدار متفاوتی سکه می‌دهد.",

            reply_markup=
            bray_keyboard()
        )

        return True

    # --------------------------------------------------------
    # BRAY
    # --------------------------------------------------------

    if data.startswith(
        "bray_"
    ):

        bray_id = data.replace(
            "bray_",
            "",
            1
        )

        if not can_bray(
            user_id
        ):

            await query.answer(

                "⏳ خر هنوز آماده عرعر بعدی نیست 😂",

                show_alert=True
            )

            return True

        bray = get_bray(
            bray_id
        )

        bonus = random.randint(
            0,
            5
        )

        reward = (
            bray["reward"]
            + bonus
        )

        add_coins(
            user_id,
            reward
        )

        add_xp(
            user_id,
            5
        )

        execute(
            """
            UPDATE donkey_progress

            SET total_brays =
                total_brays + 1

            WHERE user_id = ?
            """,
            (user_id,),
            commit=True
        )

        update_quest_progress(
            user_id,
            "bray",
            1
        )

        await query.answer(
            f"{bray['text']} +{reward}🪙",
            show_alert=True
        )

        return True

    # --------------------------------------------------------
    # QUESTS
    # --------------------------------------------------------

    if data == "quests":

        await query.answer()

        await query.edit_message_text(

            quests_text(
                user_id
            ),

            reply_markup=
            quests_keyboard(
                user_id
            )
        )

        return True

    # --------------------------------------------------------
    # CLAIM QUEST
    # --------------------------------------------------------

    if data.startswith(
        "claimquest_"
    ):

        quest_id = data.replace(
            "claimquest_",
            "",
            1
        )

        success, text = claim_quest(

            user_id,
            quest_id
        )

        await query.answer(
            text[:180],
            show_alert=True
        )

        await query.edit_message_text(

            quests_text(
                user_id
            ),

            reply_markup=
            quests_keyboard(
                user_id
            )
        )

        return True

    # --------------------------------------------------------
    # DAILY
    # --------------------------------------------------------

    if data == "daily":

        success, text = claim_daily(
            user_id
        )

        await query.answer(
            text[:180],
            show_alert=True
        )

        return True

    # --------------------------------------------------------
    # LEADERBOARD
    # --------------------------------------------------------

    if data == "leaderboard":

        await query.answer()

        await query.edit_message_text(

            leaderboard_text(),

            reply_markup=
            InlineKeyboardMarkup([

                [

                    InlineKeyboardButton(

                        "🔙 برگشت",

                        callback_data=
                        "progress"

                    )

                ]

            ])
        )

        return True

    # --------------------------------------------------------
    # PROGRESS
    # --------------------------------------------------------

    if data == "progress":

        await query.answer()

        await query.edit_message_text(

            progress_text(
                user_id
            ),

            reply_markup=
            progress_keyboard()
        )

        return True

    return False

# ============================================================
# KHARBOT V11
# 🫏 DONKEY LIFE / NEEDS / PROFILE SYSTEM
# ============================================================

# ------------------------------------------------------------
# DONKEY TABLE
# ------------------------------------------------------------

execute("""
CREATE TABLE IF NOT EXISTS donkeys (
    user_id INTEGER PRIMARY KEY,

    name TEXT NOT NULL DEFAULT 'خر من',

    hunger INTEGER NOT NULL DEFAULT 80,
    thirst INTEGER NOT NULL DEFAULT 80,
    energy INTEGER NOT NULL DEFAULT 80,
    clean INTEGER NOT NULL DEFAULT 80,
    health INTEGER NOT NULL DEFAULT 100,

    strength INTEGER NOT NULL DEFAULT 5,
    speed INTEGER NOT NULL DEFAULT 5,
    defense INTEGER NOT NULL DEFAULT 5,
    luck INTEGER NOT NULL DEFAULT 5,

    level INTEGER NOT NULL DEFAULT 1,
    affection INTEGER NOT NULL DEFAULT 0,

    total_care INTEGER NOT NULL DEFAULT 0,

    created_at INTEGER NOT NULL
)
""", commit=True)


# ============================================================
# CONSTANTS
# ============================================================

DONKEY_MAX_STAT = 100
DONKEY_MAX_HEALTH = 100

NEED_DECAY_INTERVAL = 3600

CARE_XP = 5


# ============================================================
# CREATE DONKEY
# ============================================================

def ensure_donkey(user_id):

    row = fetchone(
        """
        SELECT user_id
        FROM donkeys
        WHERE user_id = ?
        """,
        (user_id,)
    )

    if row:
        return

    execute(
        """
        INSERT INTO donkeys (
            user_id,
            name,
            hunger,
            thirst,
            energy,
            clean,
            health,
            strength,
            speed,
            defense,
            luck,
            level,
            affection,
            total_care,
            created_at
        )

        VALUES (
            ?,
            'خر من',
            80,
            80,
            80,
            80,
            100,
            5,
            5,
            5,
            5,
            1,
            0,
            0,
            ?
        )
        """,
        (
            user_id,
            int(time.time())
        ),
        commit=True
    )


# ============================================================
# GET DONKEY
# ============================================================

def get_donkey(user_id):

    ensure_donkey(user_id)

    row = fetchone(
        """
        SELECT
            user_id,
            name,
            hunger,
            thirst,
            energy,
            clean,
            health,
            strength,
            speed,
            defense,
            luck,
            level,
            affection,
            total_care,
            created_at

        FROM donkeys

        WHERE user_id = ?
        """,
        (user_id,)
    )

    return {
        "user_id": row[0],
        "name": row[1],
        "hunger": row[2],
        "thirst": row[3],
        "energy": row[4],
        "clean": row[5],
        "health": row[6],
        "strength": row[7],
        "speed": row[8],
        "defense": row[9],
        "luck": row[10],
        "level": row[11],
        "affection": row[12],
        "total_care": row[13],
        "created_at": row[14]
    }


# ============================================================
# CLAMP
# ============================================================

def clamp_value(
    value,
    minimum,
    maximum
):

    return max(
        minimum,
        min(
            maximum,
            int(value)
        )
    )


def clamp_donkey_stats(
    donkey
):

    for key in (
        "hunger",
        "thirst",
        "energy",
        "clean",
        "affection"
    ):

        donkey[key] = clamp_value(
            donkey[key],
            0,
            100
        )

    donkey["health"] = clamp_value(
        donkey["health"],
        0,
        100
    )

    return donkey


# ============================================================
# UPDATE DONKEY
# ============================================================

def update_donkey(
    user_id,
    **values
):

    if not values:
        return

    allowed = {
        "name",
        "hunger",
        "thirst",
        "energy",
        "clean",
        "health",
        "strength",
        "speed",
        "defense",
        "luck",
        "level",
        "affection",
        "total_care"
    }

    fields = []
    params = []

    for key, value in values.items():

        if key not in allowed:
            continue

        fields.append(
            f"{key} = ?"
        )

        params.append(value)

    if not fields:
        return

    params.append(
        user_id
    )

    execute(
        f"""
        UPDATE donkeys

        SET {", ".join(fields)}

        WHERE user_id = ?
        """,
        tuple(params),
        commit=True
    )


# ============================================================
# NEED DECAY
# ============================================================

def update_donkey_needs(
    user_id
):

    donkey = get_donkey(
        user_id
    )

    now = int(
        time.time()
    )

    elapsed = max(
        0,
        now - donkey["created_at"]
    )

    # هر ساعت کمی افت
    periods = elapsed // NEED_DECAY_INTERVAL

    if periods <= 0:
        return donkey

    hunger_loss = min(
        periods * 3,
        40
    )

    thirst_loss = min(
        periods * 4,
        50
    )

    energy_loss = min(
        periods * 2,
        30
    )

    clean_loss = min(
        periods * 2,
        30
    )

    donkey["hunger"] -= hunger_loss

    donkey["thirst"] -= thirst_loss

    donkey["energy"] -= energy_loss

    donkey["clean"] -= clean_loss

    # اگر نیازها خیلی پایین باشند سلامتی هم آسیب می‌بیند
    bad_needs = 0

    if donkey["hunger"] < 20:
        bad_needs += 1

    if donkey["thirst"] < 20:
        bad_needs += 1

    if donkey["energy"] < 15:
        bad_needs += 1

    if donkey["clean"] < 15:
        bad_needs += 1

    if bad_needs:

        donkey["health"] -= (
            bad_needs *
            periods
        )

    donkey = clamp_donkey_stats(
        donkey
    )

    # زمان آخرین محاسبه
    donkey["created_at"] = now

    update_donkey(
        user_id,

        hunger=donkey["hunger"],

        thirst=donkey["thirst"],

        energy=donkey["energy"],

        clean=donkey["clean"],

        health=donkey["health"],

        created_at=now
    )

    return donkey


# ============================================================
# FIX: created_at UPDATE SUPPORT
# ============================================================

# اگر ستون created_at در نسخه قبلی وجود داشته باشد
# همین تابع بالا از آن استفاده می‌کند.


# ============================================================
# FEED DONKEY
# ============================================================

def feed_donkey(
    user_id,
    amount=20
):

    donkey = update_donkey_needs(
        user_id
    )

    if donkey["health"] <= 0:

        return False, (
            "💀 خر خیلی ضعیف شده.\n"
            "اول باید حالش را بهتر کنی."
        )

    old = donkey["hunger"]

    donkey["hunger"] = clamp_value(
        old + amount,
        0,
        100
    )

    donkey["affection"] = clamp_value(
        donkey["affection"] + 1,
        0,
        100
    )

    donkey["total_care"] += 1

    update_donkey(

        user_id,

        hunger=donkey["hunger"],

        affection=donkey["affection"],

        total_care=donkey["total_care"]
    )

    add_xp(
        user_id,
        CARE_XP
    )

    update_quest_progress(
        user_id,
        "feed",
        1
    )

    return True, (
        "🥕 خر غذا خورد!\n\n"

        f"🍖 گرسنگی: "
        f"{old} → "
        f"{donkey['hunger']}\n"

        f"❤️ محبت: "
        f"{donkey['affection']}\n\n"

        f"⭐ +{CARE_XP} XP"
    )


# ============================================================
# GIVE WATER
# ============================================================

def water_donkey(
    user_id,
    amount=25
):

    donkey = update_donkey_needs(
        user_id
    )

    old = donkey["thirst"]

    donkey["thirst"] = clamp_value(
        old + amount,
        0,
        100
    )

    donkey["affection"] = clamp_value(
        donkey["affection"] + 1,
        0,
        100
    )

    update_donkey(

        user_id,

        thirst=donkey["thirst"],

        affection=donkey["affection"]
    )

    add_xp(
        user_id,
        CARE_XP
    )

    return True, (
        "💧 خر آب خورد!\n\n"

        f"💧 تشنگی: "
        f"{old} → "
        f"{donkey['thirst']}\n"

        f"⭐ +{CARE_XP} XP"
    )


# ============================================================
# BATHE DONKEY
# ============================================================

def bathe_donkey(
    user_id,
    amount=35
):

    donkey = update_donkey_needs(
        user_id
    )

    old = donkey["clean"]

    donkey["clean"] = clamp_value(
        old + amount,
        0,
        100
    )

    donkey["affection"] = clamp_value(
        donkey["affection"] + 2,
        0,
        100
    )

    donkey["total_care"] += 1

    update_donkey(

        user_id,

        clean=donkey["clean"],

        affection=donkey["affection"],

        total_care=donkey["total_care"]
    )

    add_xp(
        user_id,
        CARE_XP
    )

    update_quest_progress(
        user_id,
        "clean",
        1
    )

    return True, (
        "🛁 خر حمام کرد!\n\n"

        f"✨ تمیزی: "
        f"{old} → "
        f"{donkey['clean']}\n"

        f"❤️ محبت: "
        f"{donkey['affection']}\n"

        f"⭐ +{CARE_XP} XP"
    )


# ============================================================
# REST
# ============================================================

def rest_donkey(
    user_id
):

    donkey = update_donkey_needs(
        user_id
    )

    old = donkey["energy"]

    donkey["energy"] = clamp_value(
        old + 30,
        0,
        100
    )

    update_donkey(
        user_id,
        energy=donkey["energy"]
    )

    return True, (
        "😴 خر کمی استراحت کرد.\n\n"

        f"⚡ انرژی: "
        f"{old} → "
        f"{donkey['energy']}"
    )


# ============================================================
# HEALTH RECOVERY
# ============================================================

def recover_donkey(
    user_id
):

    donkey = update_donkey_needs(
        user_id
    )

    if donkey["health"] >= 100:

        return False, (
            "❤️ سلامتی خر کامله."
        )

    if (
        donkey["hunger"] < 50
        or donkey["thirst"] < 50
    ):

        return False, (
            "❌ اول خر را غذا بده "
            "و آب بده."
        )

    old = donkey["health"]

    donkey["health"] = clamp_value(
        old + 10,
        0,
        100
    )

    update_donkey(
        user_id,
        health=donkey["health"]
    )

    return True, (
        "❤️ حال خر بهتر شد!\n\n"

        f"❤️ سلامتی: "
        f"{old} → "
        f"{donkey['health']}"
    )


# ============================================================
# DONKEY STATUS
# ============================================================

def stat_bar(
    value,
    length=10
):

    filled = int(
        value / 100 * length
    )

    empty = (
        length -
        filled
    )

    return (
        "🟩" * filled
        +
        "⬜" * empty
    )


def donkey_status_text(
    user_id
):

    donkey = update_donkey_needs(
        user_id
    )

    health_state = "❤️"

    if donkey["health"] < 30:
        health_state = "🚨"

    hunger_state = "🟢"

    if donkey["hunger"] < 30:
        hunger_state = "🔴"

    elif donkey["hunger"] < 60:
        hunger_state = "🟡"

    thirst_state = "🟢"

    if donkey["thirst"] < 30:
        thirst_state = "🔴"

    elif donkey["thirst"] < 60:
        thirst_state = "🟡"

    return (

        f"🫏 **{donkey['name']}**\n"
        "━━━━━━━━━━━━━━━━\n\n"

        f"❤️ سلامتی\n"
        f"{health_state} "
        f"{stat_bar(donkey['health'])} "
        f"{donkey['health']}/100\n\n"

        f"🍖 گرسنگی\n"
        f"{hunger_state} "
        f"{stat_bar(donkey['hunger'])} "
        f"{donkey['hunger']}/100\n\n"

        f"💧 تشنگی\n"
        f"{thirst_state} "
        f"{stat_bar(donkey['thirst'])} "
        f"{donkey['thirst']}/100\n\n"

        f"⚡ انرژی\n"
        f"{stat_bar(donkey['energy'])} "
        f"{donkey['energy']}/100\n\n"

        f"🧼 تمیزی\n"
        f"{stat_bar(donkey['clean'])} "
        f"{donkey['clean']}/100\n\n"

        "━━━━━━━━━━━━━━━━\n"

        f"💪 قدرت: {donkey['strength']}\n"
        f"🏃 سرعت: {donkey['speed']}\n"
        f"🛡 دفاع: {donkey['defense']}\n"
        f"🍀 شانس: {donkey['luck']}\n\n"

        f"❤️ محبت: "
        f"{donkey['affection']}/100\n"

        f"⭐ Level: "
        f"{donkey['level']}"
    )


# ============================================================
# DONKEY KEYBOARD
# ============================================================

def donkey_keyboard():

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton(
                "🥕 غذا",
                callback_data="donkey_feed"
            ),

            InlineKeyboardButton(
                "💧 آب",
                callback_data="donkey_water"
            )

        ],

        [

            InlineKeyboardButton(
                "🛁 حمام",
                callback_data="donkey_bath"
            ),

            InlineKeyboardButton(
                "😴 استراحت",
                callback_data="donkey_rest"
            )

        ],

        [

            InlineKeyboardButton(
                "❤️ درمان",
                callback_data="donkey_heal"
            ),

            InlineKeyboardButton(
                "✏️ تغییر اسم",
                callback_data="donkey_rename"
            )

        ],

        [

            InlineKeyboardButton(
                "⬆️ ارتقا",
                callback_data="donkey_upgrade"
            ),

            InlineKeyboardButton(
                "🎒 آیتم‌ها",
                callback_data="inventory"
            )

        ]

    ])


# ============================================================
# RENAME STATE
# ============================================================

RENAME_WAITING = set()


async def start_donkey_rename(
    update,
    context
):

    query = update.callback_query

    user_id = query.from_user.id

    RENAME_WAITING.add(
        user_id
    )

    await query.answer()

    await query.message.reply_text(

        "✏️ **اسم جدید خر را بفرست.**\n\n"

        "حداکثر ۲۰ کاراکتر.\n"
        "اسم خالی یا خیلی طولانی قبول نمی‌شود."
    )


# ============================================================
# HANDLE DONKEY RENAME
# ============================================================

async def handle_donkey_rename(
    update,
    context
):

    user_id = update.effective_user.id

    if user_id not in RENAME_WAITING:
        return False

    if not update.message:
        return False

    name = (
        update.message.text
        or ""
    ).strip()

    if not name:

        await update.message.reply_text(
            "❌ اسم نمی‌تواند خالی باشد."
        )

        return True

    if len(name) > 20:

        await update.message.reply_text(
            "❌ اسم حداکثر ۲۰ کاراکتر."
        )

        return True

    # جلوگیری از کاراکترهای کنترل
    if "\n" in name or "\r" in name:

        await update.message.reply_text(
            "❌ اسم نامعتبر است."
        )

        return True

    update_donkey(
        user_id,
        name=name
    )

    RENAME_WAITING.discard(
        user_id
    )

    await update.message.reply_text(

        f"✅ اسم خر شد:\n\n"
        f"🫏 **{name}**",

        reply_markup=
        donkey_keyboard()
    )

    return True


# ============================================================
# DONKEY CALLBACK
# ============================================================

async def donkey_callback_handler(
    update,
    context
):

    query = update.callback_query

    data = query.data

    user_id = query.from_user.id

    # --------------------------------------------------------
    # PROFILE
    # --------------------------------------------------------

    if data == "donkey_profile":

        await query.answer()

        await query.edit_message_text(

            donkey_status_text(
                user_id
            ),

            reply_markup=
            donkey_keyboard()
        )

        return True

    # --------------------------------------------------------
    # FEED
    # --------------------------------------------------------

    if data == "donkey_feed":

        success, text = feed_donkey(
            user_id,
            20
        )

        await query.answer(
            text[:180],
            show_alert=True
        )

        await query.edit_message_text(

            donkey_status_text(
                user_id
            ),

            reply_markup=
            donkey_keyboard()
        )

        return True

    # --------------------------------------------------------
    # WATER
    # --------------------------------------------------------

    if data == "donkey_water":

        success, text = water_donkey(
            user_id,
            25
        )

        await query.answer(
            text[:180],
            show_alert=True
        )

        await query.edit_message_text(

            donkey_status_text(
                user_id
            ),

            reply_markup=
            donkey_keyboard()
        )

        return True

    # --------------------------------------------------------
    # BATH
    # --------------------------------------------------------

    if data == "donkey_bath":

        success, text = bathe_donkey(
            user_id,
            35
        )

        await query.answer(
            text[:180],
            show_alert=True
        )

        await query.edit_message_text(

            donkey_status_text(
                user_id
            ),

            reply_markup=
            donkey_keyboard()
        )

        return True

    # --------------------------------------------------------
    # REST
    # --------------------------------------------------------

    if data == "donkey_rest":

        success, text = rest_donkey(
            user_id
        )

        await query.answer(
            text[:180],
            show_alert=True
        )

        await query.edit_message_text(

            donkey_status_text(
                user_id
            ),

            reply_markup=
            donkey_keyboard()
        )

        return True

    # --------------------------------------------------------
    # HEAL
    # --------------------------------------------------------

    if data == "donkey_heal":

        success, text = recover_donkey(
            user_id
        )

        await query.answer(
            text[:180],
            show_alert=True
        )

        await query.edit_message_text(

            donkey_status_text(
                user_id
            ),

            reply_markup=
            donkey_keyboard()
        )

        return True

    # --------------------------------------------------------
    # RENAME
    # --------------------------------------------------------

    if data == "donkey_rename":

        await start_donkey_rename(
            update,
            context
        )

        return True

    return False

    # ============================================================
# KHARBOT V12
# 🛒 SHOP + INVENTORY + DONKEY UPGRADES
# ============================================================


# ============================================================
# INVENTORY TABLE
# ============================================================

execute("""
CREATE TABLE IF NOT EXISTS inventory (
    user_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(user_id, item_id)
)
""", commit=True)


# ============================================================
# SHOP ITEMS
# ============================================================

SHOP_ITEMS = {

    # --------------------------------------------------------
    # FOOD
    # --------------------------------------------------------

    "carrot": {
        "name": "🥕 هویج",
        "description": "گرسنگی خر را افزایش می‌دهد.",
        "price": 100,
        "type": "food",
        "value": 25
    },

    "golden_carrot": {
        "name": "🥕✨ هویج طلایی",
        "description": "غذای بسیار مقوی.",
        "price": 450,
        "type": "food",
        "value": 60
    },

    # --------------------------------------------------------
    # WATER
    # --------------------------------------------------------

    "water": {
        "name": "💧 آب",
        "description": "تشنگی خر را کاهش می‌دهد.",
        "price": 80,
        "type": "water",
        "value": 30
    },

    "energy_drink": {
        "name": "⚡ نوشیدنی انرژی‌زا",
        "description": "انرژی خر را افزایش می‌دهد.",
        "price": 350,
        "type": "energy",
        "value": 40
    },

    # --------------------------------------------------------
    # CLEAN
    # --------------------------------------------------------

    "soap": {
        "name": "🧼 صابون",
        "description": "برای حمام خر.",
        "price": 120,
        "type": "clean",
        "value": 40
    },

    # --------------------------------------------------------
    # HEALTH
    # --------------------------------------------------------

    "medicine": {
        "name": "💊 دارو",
        "description": "سلامتی خر را افزایش می‌دهد.",
        "price": 500,
        "type": "health",
        "value": 25
    },

    "mega_medicine": {
        "name": "💊✨ داروی ویژه",
        "description": "درمان قوی.",
        "price": 1200,
        "type": "health",
        "value": 60
    },

    # --------------------------------------------------------
    # SPECIAL
    # --------------------------------------------------------

    "lucky_horseshoe": {
        "name": "🍀 نعل شانس",
        "description": "برای افزایش شانس خر.",
        "price": 2500,
        "type": "luck",
        "value": 1
    },

    "training_book": {
        "name": "📕 کتاب آموزش",
        "description": "برای ارتقای مهارت خر.",
        "price": 3000,
        "type": "training",
        "value": 1
    },

    "energy_food": {
        "name": "🍎 غذای انرژی‌زا",
        "description": "هم گرسنگی و هم انرژی را افزایش می‌دهد.",
        "price": 700,
        "type": "energy_food",
        "value": 30
    }
}


# ============================================================
# UPGRADE PRICES
# ============================================================

UPGRADE_BASE_PRICES = {

    "strength": 1500,
    "speed": 1800,
    "defense": 1600,
    "luck": 2500
}


# ============================================================
# INVENTORY HELPERS
# ============================================================

def get_item_amount(
    user_id,
    item_id
):

    row = fetchone(
        """
        SELECT amount

        FROM inventory

        WHERE user_id = ?

        AND item_id = ?
        """,
        (
            user_id,
            item_id
        )
    )

    if not row:
        return 0

    return row[0]


def add_item(
    user_id,
    item_id,
    amount=1
):

    if amount <= 0:
        return False

    if item_id not in SHOP_ITEMS:
        return False

    execute(
        """
        INSERT INTO inventory
        (
            user_id,
            item_id,
            amount
        )

        VALUES (?, ?, ?)

        ON CONFLICT(user_id, item_id)

        DO UPDATE SET
            amount =
            amount + excluded.amount
        """,
        (
            user_id,
            item_id,
            amount
        ),
        commit=True
    )

    return True


def remove_item(
    user_id,
    item_id,
    amount=1
):

    current = get_item_amount(
        user_id,
        item_id
    )

    if current < amount:
        return False

    new_amount = current - amount

    if new_amount <= 0:

        execute(
            """
            DELETE FROM inventory

            WHERE user_id = ?

            AND item_id = ?
            """,
            (
                user_id,
                item_id
            ),
            commit=True
        )

    else:

        execute(
            """
            UPDATE inventory

            SET amount = ?

            WHERE user_id = ?

            AND item_id = ?
            """,
            (
                new_amount,
                user_id,
                item_id
            ),
            commit=True
        )

    return True


# ============================================================
# COIN CHECK
# ============================================================

def try_spend_coins(
    user_id,
    amount
):

    if amount <= 0:
        return True

    # این تابع باید با سیستم کیف پول قبلی هماهنگ باشد.
    # اگر add_coins / get_coins شما در پارت‌های قبلی وجود دارد،
    # همین قسمت را استفاده کن.

    balance = get_coins(
        user_id
    )

    if balance < amount:
        return False

    add_coins(
        user_id,
        -amount
    )

    return True


# ============================================================
# BUY ITEM
# ============================================================

def buy_item(
    user_id,
    item_id,
    quantity=1
):

    if item_id not in SHOP_ITEMS:

        return False, (
            "❌ این آیتم وجود ندارد."
        )

    if quantity < 1:

        return False, (
            "❌ تعداد نامعتبر است."
        )

    if quantity > 99:

        return False, (
            "❌ حداکثر خرید ۹۹ عدد است."
        )

    item = SHOP_ITEMS[item_id]

    total_price = (
        item["price"] *
        quantity
    )

    if not try_spend_coins(
        user_id,
        total_price
    ):

        return False, (

            "❌ سکه کافی نداری.\n\n"

            f"💰 قیمت: "
            f"{total_price:,} 🪙\n"

            f"💳 موجودی: "
            f"{get_coins(user_id):,} 🪙"
        )

    add_item(
        user_id,
        item_id,
        quantity
    )

    return True, (

        "✅ خرید انجام شد!\n\n"

        f"{item['name']}\n"

        f"📦 تعداد: "
        f"{quantity}\n"

        f"💰 هزینه: "
        f"{total_price:,} 🪙"
    )


# ============================================================
# USE ITEM
# ============================================================

def use_item(
    user_id,
    item_id
):

    if item_id not in SHOP_ITEMS:

        return False, (
            "❌ آیتم وجود ندارد."
        )

    if get_item_amount(
        user_id,
        item_id
    ) <= 0:

        return False, (
            "❌ این آیتم را نداری."
        )

    item = SHOP_ITEMS[item_id]

    donkey = update_donkey_needs(
        user_id
    )

    item_type = item["type"]

    value = item["value"]

    # --------------------------------------------------------
    # FOOD
    # --------------------------------------------------------

    if item_type == "food":

        old = donkey["hunger"]

        new = clamp_value(
            old + value,
            0,
            100
        )

        update_donkey(
            user_id,
            hunger=new
        )

        message = (
            f"🥕 {item['name']} مصرف شد.\n\n"
            f"🍖 گرسنگی: "
            f"{old} → {new}"
        )

    # --------------------------------------------------------
    # WATER
    # --------------------------------------------------------

    elif item_type == "water":

        old = donkey["thirst"]

        new = clamp_value(
            old + value,
            0,
            100
        )

        update_donkey(
            user_id,
            thirst=new
        )

        message = (
            f"💧 {item['name']} مصرف شد.\n\n"
            f"💧 تشنگی: "
            f"{old} → {new}"
        )

    # --------------------------------------------------------
    # ENERGY
    # --------------------------------------------------------

    elif item_type == "energy":

        old = donkey["energy"]

        new = clamp_value(
            old + value,
            0,
            100
        )

        update_donkey(
            user_id,
            energy=new
        )

        message = (
            f"⚡ {item['name']} مصرف شد.\n\n"
            f"⚡ انرژی: "
            f"{old} → {new}"
        )

    # --------------------------------------------------------
    # CLEAN
    # --------------------------------------------------------

    elif item_type == "clean":

        old = donkey["clean"]

        new = clamp_value(
            old + value,
            0,
            100
        )

        update_donkey(
            user_id,
            clean=new
        )

        message = (
            f"🧼 {item['name']} استفاده شد.\n\n"
            f"✨ تمیزی: "
            f"{old} → {new}"
        )

    # --------------------------------------------------------
    # HEALTH
    # --------------------------------------------------------

    elif item_type == "health":

        old = donkey["health"]

        new = clamp_value(
            old + value,
            0,
            100
        )

        update_donkey(
            user_id,
            health=new
        )

        message = (
            f"💊 {item['name']} استفاده شد.\n\n"
            f"❤️ سلامتی: "
            f"{old} → {new}"
        )

    # --------------------------------------------------------
    # ENERGY FOOD
    # --------------------------------------------------------

    elif item_type == "energy_food":

        old_hunger = donkey["hunger"]

        old_energy = donkey["energy"]

        new_hunger = clamp_value(
            old_hunger + value,
            0,
            100
        )

        new_energy = clamp_value(
            old_energy + value,
            0,
            100
        )

        update_donkey(
            user_id,

            hunger=new_hunger,

            energy=new_energy
        )

        message = (
            f"🍎 {item['name']} مصرف شد.\n\n"

            f"🍖 گرسنگی: "
            f"{old_hunger} → "
            f"{new_hunger}\n"

            f"⚡ انرژی: "
            f"{old_energy} → "
            f"{new_energy}"
        )

    # --------------------------------------------------------
    # LUCK
    # --------------------------------------------------------

    elif item_type == "luck":

        old = donkey["luck"]

        if old >= 50:

            return False, (
                "🍀 شانس خر به حداکثر رسیده."
            )

        update_donkey(
            user_id,
            luck=old + value
        )

        message = (
            f"🍀 {item['name']} استفاده شد.\n\n"

            f"🍀 شانس: "
            f"{old} → "
            f"{old + value}"
        )

    # --------------------------------------------------------
    # TRAINING
    # --------------------------------------------------------

    elif item_type == "training":

        return False, (
            "📕 کتاب آموزش را باید "
            "از بخش ارتقای خر استفاده کنی."
        )

    else:

        return False, (
            "❌ این آیتم قابل استفاده نیست."
        )

    remove_item(
        user_id,
        item_id,
        1
    )

    add_xp(
        user_id,
        3
    )

    return True, message


# ============================================================
# UPGRADE PRICE
# ============================================================

def get_upgrade_price(
    stat,
    current_level
):

    base = UPGRADE_BASE_PRICES.get(
        stat
    )

    if base is None:
        return None

    # قیمت با هر سطح بیشتر می‌شود
    multiplier = (
        1 +
        (current_level * 0.35)
    )

    return int(
        base * multiplier
    )


# ============================================================
# UPGRADE DONKEY
# ============================================================

def upgrade_donkey_stat(
    user_id,
    stat
):

    if stat not in (
        "strength",
        "speed",
        "defense",
        "luck"
    ):

        return False, (
            "❌ مهارت نامعتبر."
        )

    donkey = get_donkey(
        user_id
    )

    current = donkey[stat]

    if current >= 50:

        return False, (
            "🔒 این مهارت به حداکثر "
            "سطح فعلی رسیده."
        )

    price = get_upgrade_price(
        stat,
        current
    )

    if not try_spend_coins(
        user_id,
        price
    ):

        return False, (

            "❌ سکه کافی نیست.\n\n"

            f"💰 نیاز: "
            f"{price:,} 🪙\n"

            f"💳 موجودی: "
            f"{get_coins(user_id):,} 🪙"
        )

    update_donkey(
        user_id,
        **{
            stat: current + 1
        }
    )

    add_xp(
        user_id,
        20
    )

    return True, (

        "⬆️ **ارتقا انجام شد!**\n\n"

        f"📊 {stat}\n"

        f"🔻 قبلی: {current}\n"

        f"🔺 جدید: {current + 1}\n\n"

        f"💰 هزینه: "
        f"{price:,} 🪙\n"

        "⭐ +20 XP"
    )


# ============================================================
# INVENTORY TEXT
# ============================================================

def inventory_text(
    user_id
):

    rows = fetchall(
        """
        SELECT
            item_id,
            amount

        FROM inventory

        WHERE user_id = ?

        AND amount > 0

        ORDER BY item_id
        """,
        (user_id,)
    )

    text = (
        "🎒 **کوله‌پشتی خر**\n"
        "━━━━━━━━━━━━━━━━\n\n"
    )

    if not rows:

        text += (
            "📭 کوله‌پشتی خالی است.\n\n"
            "🛒 از فروشگاه آیتم بخر."
        )

        return text

    for item_id, amount in rows:

        item = SHOP_ITEMS.get(
            item_id
        )

        if not item:
            continue

        text += (

            f"{item['name']}\n"

            f"📦 تعداد: "
            f"**{amount}**\n"

            f"ℹ️ {item['description']}\n\n"
        )

    return text


# ============================================================
# SHOP TEXT
# ============================================================

def shop_text():

    text = (
        "🛒 **فروشگاه خرستان**\n"
        "━━━━━━━━━━━━━━━━\n\n"
    )

    for item_id, item in SHOP_ITEMS.items():

        text += (

            f"{item['name']}\n"

            f"💰 {item['price']:,} 🪙\n"

            f"ℹ️ {item['description']}\n\n"
        )

    return text


# ============================================================
# SHOP KEYBOARD
# ============================================================

def shop_keyboard():

    keyboard = []

    for item_id, item in SHOP_ITEMS.items():

        keyboard.append([

            InlineKeyboardButton(

                f"{item['name']} "
                f"• {item['price']:,}🪙",

                callback_data=
                f"shop_buy_{item_id}"
            )

        ])

    keyboard.append([

        InlineKeyboardButton(
            "🎒 کوله‌پشتی",
            callback_data="inventory"
        )

    ])

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# INVENTORY KEYBOARD
# ============================================================

def inventory_keyboard(
    user_id
):

    rows = fetchall(
        """
        SELECT item_id

        FROM inventory

        WHERE user_id = ?

        AND amount > 0
        """,
        (user_id,)
    )

    keyboard = []

    for row in rows:

        item_id = row[0]

        item = SHOP_ITEMS.get(
            item_id
        )

        if not item:
            continue

        keyboard.append([

            InlineKeyboardButton(

                f"استفاده از {item['name']}",

                callback_data=
                f"useitem_{item_id}"
            )

        ])

    keyboard.append([

        InlineKeyboardButton(
            "🛒 فروشگاه",
            callback_data="shop"
        )

    ])

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# UPGRADE KEYBOARD
# ============================================================

def upgrade_keyboard(
    user_id
):

    donkey = get_donkey(
        user_id
    )

    keyboard = []

    names = {
        "strength": "💪 قدرت",
        "speed": "🏃 سرعت",
        "defense": "🛡 دفاع",
        "luck": "🍀 شانس"
    }

    for stat in (
        "strength",
        "speed",
        "defense",
        "luck"
    ):

        current = donkey[stat]

        price = get_upgrade_price(
            stat,
            current
        )

        keyboard.append([

            InlineKeyboardButton(

                f"{names[stat]} "
                f"{current} → {current + 1} "
                f"({price:,}🪙)",

                callback_data=
                f"upgrade_{stat}"
            )

        ])

    keyboard.append([

        InlineKeyboardButton(
            "🔙 خر من",
            callback_data="donkey_profile"
        )

    ])

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# SHOP CALLBACK
# ============================================================

async def shop_callback_handler(
    update,
    context
):

    query = update.callback_query

    data = query.data

    user_id = query.from_user.id

    # --------------------------------------------------------
    # SHOP
    # --------------------------------------------------------

    if data == "shop":

        await query.answer()

        await query.edit_message_text(

            shop_text(),

            reply_markup=
            shop_keyboard()
        )

        return True

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    if data.startswith(
        "shop_buy_"
    ):

        item_id = data.replace(
            "shop_buy_",
            "",
            1
        )

        success, text = buy_item(
            user_id,
            item_id,
            1
        )

        await query.answer(
            text[:180],
            show_alert=True
        )

        return True

    # --------------------------------------------------------
    # INVENTORY
    # --------------------------------------------------------

    if data == "inventory":

        await query.answer()

        await query.edit_message_text(

            inventory_text(
                user_id
            ),

            reply_markup=
            inventory_keyboard(
                user_id
            )
        )

        return True

    # --------------------------------------------------------
    # USE ITEM
    # --------------------------------------------------------

    if data.startswith(
        "useitem_"
    ):

        item_id = data.replace(
            "useitem_",
            "",
            1
        )

        success, text = use_item(
            user_id,
            item_id
        )

        await query.answer(
            text[:180],
            show_alert=True
        )

        await query.edit_message_text(

            inventory_text(
                user_id
            ),

            reply_markup=
            inventory_keyboard(
                user_id
            )
        )

        return True

    # --------------------------------------------------------
    # UPGRADE MENU
    # --------------------------------------------------------

    if data == "donkey_upgrade":

        await query.answer()

        await query.edit_message_text(

            "⬆️ **ارتقای خر**\n\n"

            "هرچه مهارت بالاتر برود، "
            "هزینه ارتقا هم بیشتر می‌شود.\n\n"

            "💪 قدرت → عملکرد بهتر در مبارزه\n"
            "🏃 سرعت → شانس حرکت بهتر\n"
            "🛡 دفاع → مقاومت بیشتر\n"
            "🍀 شانس → احتمال رویدادهای خوب",

            reply_markup=
            upgrade_keyboard(
                user_id
            )
        )

        return True

    # --------------------------------------------------------
    # UPGRADE
    # --------------------------------------------------------

    if data.startswith(
        "upgrade_"
    ):

        stat = data.replace(
            "upgrade_",
            "",
            1
        )

        success, text = upgrade_donkey_stat(
            user_id,
            stat
        )

        await query.answer(
            text[:180],
            show_alert=True
        )

        await query.edit_message_text(

            "⬆️ **ارتقای خر**\n\n"

            "مهارت موردنظر را انتخاب کن:",

            reply_markup=
            upgrade_keyboard(
                user_id
            )
        )

        return True

    return False

# ============================================================
# KHARBOT V13
# 🎮 MULTIPLAYER GAME ENGINE
# 👥 GROUP + 🤖 BOT
# ❌ CANCEL + ⏱ TURN SYSTEM
# ============================================================

import asyncio
import random
import time
from collections import defaultdict


# ============================================================
# GAME SETTINGS
# ============================================================

GAME_TIMEOUT = 120
TURN_TIMEOUT = 30
MAX_PLAYERS = 6

games = {}
player_games = {}
game_locks = defaultdict(asyncio.Lock)


# ============================================================
# GAME ID
# ============================================================

def make_game_id():

    return (
        f"{int(time.time() * 1000)}"
        f"_{random.randint(1000, 9999)}"
    )


# ============================================================
# GAME OBJECT
# ============================================================

class Game:

    def __init__(
        self,
        game_id,
        chat_id,
        game_type,
        creator_id,
        creator_name
    ):

        self.id = game_id

        self.chat_id = chat_id

        self.type = game_type

        self.creator_id = creator_id

        self.creator_name = creator_name

        self.players = []

        self.names = {}

        self.scores = {}

        self.turn_index = 0

        self.started = False

        self.cancelled = False

        self.finished = False

        self.created_at = time.time()

        self.last_action = time.time()

        self.turn_message_id = None

        self.data = {}

    # --------------------------------------------------------
    # ADD PLAYER
    # --------------------------------------------------------

    def add_player(
        self,
        user_id,
        name
    ):

        if self.started:
            return False

        if user_id in self.players:
            return False

        if len(self.players) >= MAX_PLAYERS:
            return False

        self.players.append(
            user_id
        )

        self.names[user_id] = name

        self.scores[user_id] = 0

        player_games[user_id] = self.id

        return True

    # --------------------------------------------------------
    # REMOVE PLAYER
    # --------------------------------------------------------

    def remove_player(
        self,
        user_id
    ):

        if user_id in self.players:

            self.players.remove(
                user_id
            )

            self.names.pop(
                user_id,
                None
            )

            self.scores.pop(
                user_id,
                None
            )

            player_games.pop(
                user_id,
                None
            )

            return True

        return False

    # --------------------------------------------------------
    # CURRENT PLAYER
    # --------------------------------------------------------

    def current_player(self):

        if not self.players:
            return None

        if self.turn_index >= len(
            self.players
        ):
            self.turn_index = 0

        return self.players[
            self.turn_index
        ]

    # --------------------------------------------------------
    # NEXT TURN
    # --------------------------------------------------------

    def next_turn(self):

        if not self.players:
            return None

        self.turn_index = (
            self.turn_index + 1
        ) % len(self.players)

        self.last_action = time.time()

        return self.current_player()


# ============================================================
# GAME MANAGER
# ============================================================

class GameManager:

    def create(
        self,
        chat_id,
        game_type,
        user_id,
        name
    ):

        if user_id in player_games:

            return None

        game_id = make_game_id()

        game = Game(
            game_id,
            chat_id,
            game_type,
            user_id,
            name
        )

        game.add_player(
            user_id,
            name
        )

        games[game_id] = game

        return game

    # --------------------------------------------------------

    def get(
        self,
        game_id
    ):

        return games.get(
            game_id
        )

    # --------------------------------------------------------

    def get_player_game(
        self,
        user_id
    ):

        game_id = player_games.get(
            user_id
        )

        if not game_id:
            return None

        return games.get(
            game_id
        )

    # --------------------------------------------------------

    def delete(
        self,
        game_id
    ):

        game = games.pop(
            game_id,
            None
        )

        if not game:
            return

        for user_id in game.players:

            player_games.pop(
                user_id,
                None
            )

    # --------------------------------------------------------

    def cancel(
        self,
        game_id
    ):

        game = self.get(
            game_id
        )

        if not game:
            return False

        game.cancelled = True

        self.delete(
            game_id
        )

        return True


game_manager = GameManager()


# ============================================================
# GAME TYPE DEFINITIONS
# ============================================================

GAME_TYPES = {

    "dice": {
        "name": "🎲 تاس",
        "min_players": 1,
        "max_players": 6
    },

    "coinflip": {
        "name": "🪙 شیر یا خط",
        "min_players": 1,
        "max_players": 2
    },

    "duel": {
        "name": "⚔️ دوئل خرها",
        "min_players": 1,
        "max_players": 2
    },

    "race": {
        "name": "🏁 مسابقه خرها",
        "min_players": 1,
        "max_players": 6
    }
}


# ============================================================
# BOT PLAYER
# ============================================================

BOT_ID = -999999999


def bot_name():

    return "🤖 خرِ بات"


def add_bot(
    game
):

    if BOT_ID in game.players:
        return False

    if len(game.players) >= MAX_PLAYERS:
        return False

    game.players.append(
        BOT_ID
    )

    game.names[
        BOT_ID
    ] = bot_name()

    game.scores[
        BOT_ID
    ] = 0

    return True


# ============================================================
# HARD BOT AI
# ============================================================

def bot_roll():

    # بات کاملاً تصادفی نیست.
    # در بعضی شرایط تصمیم بهتری می‌گیرد.

    roll = random.randint(
        1,
        100
    )

    if roll <= 15:
        return random.randint(
            70,
            100
        )

    if roll <= 70:
        return random.randint(
            40,
            85
        )

    return random.randint(
        1,
        65
    )


def bot_duel_power():

    base = random.randint(
        45,
        85
    )

    # بات گاهی عملکرد قوی دارد
    if random.random() < 0.25:
        base += random.randint(
            10,
            20
        )

    return min(
        100,
        base
    )


# ============================================================
# GAME LOBBY TEXT
# ============================================================

def lobby_text(
    game
):

    text = (

        f"🎮 **{GAME_TYPES[game.type]['name']}**\n"
        "━━━━━━━━━━━━━━━━\n\n"

        f"👤 سازنده:\n"
        f"└ {game.creator_name}\n\n"

        f"👥 بازیکنان "
        f"({len(game.players)}/"
        f"{GAME_TYPES[game.type]['max_players']}):\n"
    )

    for index, user_id in enumerate(
        game.players,
        1
    ):

        name = game.names.get(
            user_id,
            "بازیکن"
        )

        if user_id == BOT_ID:
            name = "🤖 خرِ بات"

        text += (
            f"{index}. {name}\n"
        )

    text += (

        "\n━━━━━━━━━━━━━━━━\n"

        "🎯 برای ورود روی «ورود» بزن.\n"
        "▶️ سازنده می‌تواند بازی را شروع کند.\n"
        "❌ هر بازیکن می‌تواند از بازی خارج شود."
    )

    return text


# ============================================================
# LOBBY KEYBOARD
# ============================================================

def lobby_keyboard(
    game
):

    buttons = [

        [
            InlineKeyboardButton(
                "🎮 ورود به بازی",
                callback_data=
                f"game_join_{game.id}"
            )
        ],

        [
            InlineKeyboardButton(
                "▶️ شروع",
                callback_data=
                f"game_start_{game.id}"
            ),

            InlineKeyboardButton(
                "❌ لغو",
                callback_data=
                f"game_cancel_{game.id}"
            )
        ]

    ]

    return InlineKeyboardMarkup(
        buttons
    )


# ============================================================
# START GAME
# ============================================================

async def start_game(
    game
):

    if game.started:
        return False

    game.started = True

    game.last_action = time.time()

    # بازی یک نفره → بات اضافه می‌شود
    if len(game.players) == 1:

        add_bot(
            game
        )

    return True


# ============================================================
# FINISH GAME
# ============================================================

def finish_game(
    game,
    winner_id=None
):

    game.finished = True

    result = []

    if winner_id is not None:

        winner_name = game.names.get(
            winner_id,
            "بازیکن"
        )

        result.append(
            f"🏆 برنده: "
            f"**{winner_name}**"
        )

    else:

        ordered = sorted(
            game.scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        result.append(
            "🏆 **نتیجه بازی**"
        )

        for index, (
            user_id,
            score
        ) in enumerate(
            ordered,
            1
        ):

            name = game.names.get(
                user_id,
                "بازیکن"
            )

            result.append(
                f"{index}. "
                f"{name} — "
                f"{score} امتیاز"
            )

    return "\n".join(
        result
    )


# ============================================================
# GAME REWARD
# ============================================================

def reward_game_result(
    game,
    winner_id=None
):

    if not game.players:
        return

    for user_id in game.players:

        if user_id == BOT_ID:
            continue

        score = game.scores.get(
            user_id,
            0
        )

        # پاداش پایه بر اساس عملکرد
        coins = max(
            10,
            min(
                500,
                20 + score * 5
            )
        )

        if winner_id == user_id:
            coins += 100

        add_coins(
            user_id,
            coins
        )

        add_xp(
            user_id,
            max(
                5,
                score * 2
            )
        )

        # ثبت آمار
        if winner_id == user_id:
            record_game_win(
                user_id
            )
        else:
            record_game_loss(
                user_id
            )


# ============================================================
# DICE GAME
# ============================================================

def play_dice_round(
    game
):

    if game.finished:
        return None

    results = {}

    for user_id in game.players:

        if user_id == BOT_ID:

            value = bot_roll()

        else:

            value = random.randint(
                1,
                100
            )

        results[
            user_id
        ] = value

        game.scores[
            user_id
        ] += value

    return results


def dice_result_text(
    game,
    results
):

    text = (
        "🎲 **نتیجه تاس**\n"
        "━━━━━━━━━━━━━━━━\n\n"
    )

    ordered = sorted(
        results.items(),
        key=lambda x: x[1],
        reverse=True
    )

    for index, (
        user_id,
        value
    ) in enumerate(
        ordered,
        1
    ):

        name = game.names.get(
            user_id,
            "بازیکن"
        )

        text += (
            f"{index}. "
            f"{name} → "
            f"🎲 {value}\n"
        )

    return text


# ============================================================
# COIN FLIP
# ============================================================

def coin_flip():

    return random.choice([
        "🦁 شیر",
        "🪙 خط"
    ])


# ============================================================
# DUEL
# ============================================================

def duel_power(
    user_id
):

    if user_id == BOT_ID:
        return bot_duel_power()

    return random.randint(
        30,
        90
    )


def play_duel(
    game
):

    if len(game.players) != 2:
        return None

    p1 = game.players[0]

    p2 = game.players[1]

    power1 = duel_power(
        p1
    )

    power2 = duel_power(
        p2
    )

    game.scores[p1] = power1

    game.scores[p2] = power2

    if power1 > power2:

        winner = p1

    elif power2 > power1:

        winner = p2

    else:

        winner = None

    return (
        power1,
        power2,
        winner
    )


# ============================================================
# RACE
# ============================================================

def race_round(
    game
):

    results = {}

    for user_id in game.players:

        if user_id == BOT_ID:

            value = random.randint(
                35,
                95
            )

        else:

            value = random.randint(
                20,
                90
            )

        results[
            user_id
        ] = value

    return results


# ============================================================
# GAME CLEANUP TASK
# ============================================================

async def cleanup_games():

    while True:

        now = time.time()

        expired = []

        for game_id, game in list(
            games.items()
        ):

            if game.finished:

                expired.append(
                    game_id
                )

                continue

            if (
                now -
                game.last_action
                > GAME_TIMEOUT
            ):

                expired.append(
                    game_id
                )

        for game_id in expired:

            game_manager.delete(
                game_id
            )

        await asyncio.sleep(
            15
        )


# ============================================================
# CREATE GAME
# ============================================================

async def create_game_message(
    update,
    context,
    game_type
):

    user = update.effective_user

    chat = update.effective_chat

    if game_type not in GAME_TYPES:

        await update.message.reply_text(
            "❌ نوع بازی وجود ندارد."
        )

        return

    if user.id in player_games:

        await update.message.reply_text(
            "❌ تو همین الان داخل یک بازی هستی."
        )

        return

    game = game_manager.create(

        chat.id,

        game_type,

        user.id,

        user.full_name
    )

    if not game:

        await update.message.reply_text(
            "❌ ساخت بازی انجام نشد."
        )

        return

    await update.message.reply_text(

        lobby_text(game),

        reply_markup=
        lobby_keyboard(game)
    )


# ============================================================
# GAME CALLBACK
# ============================================================

async def game_callback_handler(
    update,
    context
):

    query = update.callback_query

    data = query.data

    user_id = query.from_user.id

    # --------------------------------------------------------
    # JOIN
    # --------------------------------------------------------

    if data.startswith(
        "game_join_"
    ):

        game_id = data.replace(
            "game_join_",
            "",
            1
        )

        game = game_manager.get(
            game_id
        )

        if not game:

            await query.answer(
                "❌ بازی پیدا نشد.",
                show_alert=True
            )

            return True

        if game.started:

            await query.answer(
                "❌ بازی شروع شده.",
                show_alert=True
            )

            return True

        if user_id in player_games:

            await query.answer(
                "❌ قبلاً داخل بازی هستی.",
                show_alert=True
            )

            return True

        if len(game.players) >= MAX_PLAYERS:

            await query.answer(
                "❌ ظرفیت بازی پر شده.",
                show_alert=True
            )

            return True

        game.add_player(
            user_id,
            query.from_user.full_name
        )

        game.last_action = time.time()

        await query.answer(
            "✅ وارد بازی شدی!"
        )

        await query.edit_message_text(

            lobby_text(game),

            reply_markup=
            lobby_keyboard(game)
        )

        return True

    # --------------------------------------------------------
    # CANCEL
    # --------------------------------------------------------

    if data.startswith(
        "game_cancel_"
    ):

        game_id = data.replace(
            "game_cancel_",
            "",
            1
        )

        game = game_manager.get(
            game_id
        )

        if not game:

            await query.answer(
                "❌ بازی وجود ندارد.",
                show_alert=True
            )

            return True

        # سازنده یا بازیکن خودش
        if user_id not in game.players:

            await query.answer(
                "❌ تو عضو این بازی نیستی.",
                show_alert=True
            )

            return True

        game_manager.cancel(
            game_id
        )

        await query.answer(
            "❌ بازی لغو شد."
        )

        await query.edit_message_text(
            "❌ **این بازی لغو شد.**"
        )

        return True

    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    if data.startswith(
        "game_start_"
    ):

        game_id = data.replace(
            "game_start_",
            "",
            1
        )

        game = game_manager.get(
            game_id
        )

        if not game:

            await query.answer(
                "❌ بازی پیدا نشد.",
                show_alert=True
            )

            return True

        if user_id != game.creator_id:

            await query.answer(
                "❌ فقط سازنده بازی می‌تواند شروع کند.",
                show_alert=True
            )

            return True

        if game.started:

            await query.answer(
                "بازی قبلاً شروع شده."
            )

            return True

        await start_game(
            game
        )

        await query.answer(
            "▶️ بازی شروع شد!"
        )

        await run_game(
            query,
            game
        )

        return True

    return False


# ============================================================
# RUN GAME
# ============================================================

async def run_game(
    query,
    game
):

    if game.type == "dice":

        results = play_dice_round(
            game
        )

        text = dice_result_text(
            game,
            results
        )

        await query.edit_message_text(
            text
        )

        winner = max(
            results,
            key=results.get
        )

        reward_game_result(
            game,
            winner
        )

        game_manager.delete(
            game.id
        )

        return

    # --------------------------------------------------------

    if game.type == "duel":

        result = play_duel(
            game
        )

        if not result:
            return

        p1_power, p2_power, winner = result

        p1 = game.names.get(
            game.players[0],
            "بازیکن"
        )

        p2 = game.names.get(
            game.players[1],
            "بازیکن"
        )

        text = (
            "⚔️ **دوئل خرها**\n"
            "━━━━━━━━━━━━━━━━\n\n"

            f"🫏 {p1}\n"
            f"💥 قدرت: {p1_power}\n\n"

            f"🫏 {p2}\n"
            f"💥 قدرت: {p2_power}\n\n"
        )

        if winner is None:

            text += "🤝 مساوی!"

        else:

            winner_name = game.names.get(
                winner,
                "بازیکن"
            )

            text += (
                f"🏆 برنده:\n"
                f"**{winner_name}**"
            )

        await query.edit_message_text(
            text
        )

        reward_game_result(
            game,
            winner
        )

        game_manager.delete(
            game.id
        )

        return

    # --------------------------------------------------------

    if game.type == "race":

        results = race_round(
            game
        )

        for user_id, value in results.items():

            game.scores[
                user_id
            ] += value

        ordered = sorted(
            results.items(),
            key=lambda x: x[1],
            reverse=True
        )

        text = (
            "🏁 **مسابقه خرها**\n"
            "━━━━━━━━━━━━━━━━\n\n"
        )

        for index, (
            user_id,
            value
        ) in enumerate(
            ordered,
            1
        ):

            name = game.names.get(
                user_id,
                "بازیکن"
            )

            text += (
                f"{index}. "
                f"{name} "
                f"🏃 {value}\n"
            )

        winner = ordered[0][0]

        text += (
            "\n🏆 برنده: "
            f"**{game.names[winner]}**"
        )

        await query.edit_message_text(
            text
        )

        reward_game_result(
            game,
            winner
        )

        game_manager.delete(
            game.id
        )

        return

# ============================================================
# KHARBOT V14
# 🎮 EXTRA GAMES PACK
# ============================================================

EXTRA_GAMES = {

    "highlow": {
        "name": "📈 بالا یا پایین",
        "max_players": 2
    },

    "rps": {
        "name": "✊ سنگ کاغذ قیچی",
        "max_players": 2
    },

    "guess": {
        "name": "🎯 حدس عدد",
        "max_players": 4
    },

    "reaction": {
        "name": "⚡ سرعت عمل",
        "max_players": 6
    },

    "blackjack": {
        "name": "🃏 ۲۱",
        "max_players": 4
    },

    "horse_race": {
        "name": "🏇 مسابقه بزرگ خرها",
        "max_players": 6
    },

    "memory": {
        "name": "🧠 حافظه",
        "max_players": 4
    },

    "odd_even": {
        "name": "🔢 زوج یا فرد",
        "max_players": 2
    },

    "higher": {
        "name": "🎴 کارت بالاتر",
        "max_players": 2
    },

    "lucky": {
        "name": "🍀 شانس خر",
        "max_players": 6
    }
}


# ============================================================
# EXTRA GAME STATE
# ============================================================

extra_game_state = {}


# ============================================================
# RANDOM NUMBER
# ============================================================

def secure_randint(
    minimum,
    maximum
):

    return random.randint(
        minimum,
        maximum
    )


# ============================================================
# 🤜 RPS
# ============================================================

RPS_CHOICES = {
    "rock": "✊ سنگ",
    "paper": "📄 کاغذ",
    "scissors": "✂️ قیچی"
}


def rps_winner(
    a,
    b
):

    if a == b:
        return None

    wins = {
        "rock": "scissors",
        "scissors": "paper",
        "paper": "rock"
    }

    if wins[a] == b:
        return 0

    return 1


def bot_rps():

    return random.choice(
        list(RPS_CHOICES.keys())
    )


# ============================================================
# 📈 HIGH / LOW
# ============================================================

def highlow_round():

    first = random.randint(
        1,
        13
    )

    second = random.randint(
        1,
        13
    )

    if second > first:
        result = "high"

    elif second < first:
        result = "low"

    else:
        result = "draw"

    return (
        first,
        second,
        result
    )


# ============================================================
# 🎯 GUESS NUMBER
# ============================================================

def create_guess_game(
    game
):

    game.data[
        "number"
    ] = random.randint(
        1,
        50
    )

    game.data[
        "attempts"
    ] = defaultdict(int)

    game.data[
        "finished"
    ] = False


def check_guess(
    game,
    user_id,
    number
):

    if "number" not in game.data:
        create_guess_game(game)

    target = game.data[
        "number"
    ]

    game.data[
        "attempts"
    ][user_id] += 1

    if number == target:

        game.data[
            "finished"
        ] = True

        return "correct"

    if number < target:
        return "higher"

    return "lower"


# ============================================================
# ⚡ REACTION
# ============================================================

def reaction_score():

    # عدد کمتر = واکنش بهتر
    return random.randint(
        200,
        1500
    )


# ============================================================
# 🃏 BLACKJACK
# ============================================================

def blackjack_card():

    return random.randint(
        1,
        11
    )


def blackjack_hand():

    return [
        blackjack_card(),
        blackjack_card()
    ]


def blackjack_score(
    cards
):

    total = sum(cards)

    # مدیریت ساده آس
    while total > 21 and 11 in cards:

        cards[
            cards.index(11)
        ] = 1

        total = sum(cards)

    return total


# ============================================================
# 🏇 HORSE RACE
# ============================================================

def horse_race(
    game
):

    results = {}

    for user_id in game.players:

        donkey = None

        if user_id != BOT_ID:

            try:
                donkey = get_donkey(
                    user_id
                )
            except Exception:
                donkey = None

        if donkey:

            base = (
                donkey["speed"] * 2
                +
                donkey["energy"] // 5
                +
                donkey["luck"]
            )

            value = (
                base
                +
                random.randint(
                    10,
                    80
                )
            )

        else:

            value = random.randint(
                30,
                100
            )

        results[
            user_id
        ] = value

    return results


# ============================================================
# 🧠 MEMORY
# ============================================================

def memory_sequence(
    length=4
):

    return [
        random.randint(
            1,
            9
        )
        for _ in range(length)
    ]


# ============================================================
# 🔢 ODD / EVEN
# ============================================================

def odd_even():

    number = random.randint(
        1,
        100
    )

    return (
        number,
        "even"
        if number % 2 == 0
        else "odd"
    )


# ============================================================
# 🎴 HIGHER CARD
# ============================================================

def higher_card():

    return (
        random.randint(1, 13),
        random.randint(1, 13)
    )


# ============================================================
# 🍀 LUCKY DONKEY
# ============================================================

def lucky_donkey(
    user_id
):

    donkey = None

    if user_id != BOT_ID:

        try:
            donkey = get_donkey(
                user_id
            )
        except Exception:
            pass

    if donkey:

        luck = donkey["luck"]

        bonus = random.randint(
            0,
            luck
        )

        value = (
            random.randint(
                1,
                100
            )
            +
            bonus
        )

    else:

        value = random.randint(
            1,
            100
        )

    return min(
        100,
        value
    )


# ============================================================
# 🏆 EXTRA GAME REWARD
# ============================================================

def reward_extra_game(
    game,
    winner
):

    if not game.players:
        return

    for user_id in game.players:

        if user_id == BOT_ID:
            continue

        if user_id == winner:

            coins = 150
            xp = 25

            try:
                record_game_win(
                    user_id
                )
            except Exception:
                pass

        else:

            coins = 30
            xp = 8

            try:
                record_game_loss(
                    user_id
                )
            except Exception:
                pass

        add_coins(
            user_id,
            coins
        )

        add_xp(
            user_id,
            xp
        )


# ============================================================
# START EXTRA GAME
# ============================================================

async def run_extra_game(
    query,
    game
):

    # ========================================================
    # ✊ RPS
    # ========================================================

    if game.type == "rps":

        if len(game.players) == 1:
            add_bot(game)

        p1 = game.players[0]
        p2 = game.players[1]

        c1 = random.choice(
            list(RPS_CHOICES.keys())
        )

        c2 = bot_rps()

        result = rps_winner(
            c1,
            c2
        )

        n1 = game.names[p1]
        n2 = game.names[p2]

        text = (
            "✊ **سنگ کاغذ قیچی**\n"
            "━━━━━━━━━━━━\n\n"

            f"{n1}: "
            f"{RPS_CHOICES[c1]}\n"

            f"{n2}: "
            f"{RPS_CHOICES[c2]}\n\n"
        )

        if result is None:

            text += "🤝 مساوی!"

            winner = None

        elif result == 0:

            text += (
                f"🏆 {n1} برنده شد!"
            )

            winner = p1

        else:

            text += (
                f"🏆 {n2} برنده شد!"
            )

            winner = p2

        await query.edit_message_text(
            text
        )

        if winner is not None:
            reward_extra_game(
                game,
                winner
            )

        game_manager.delete(
            game.id
        )

        return


    # ========================================================
    # 📈 HIGHLOW
    # ========================================================

    if game.type == "highlow":

        if len(game.players) == 1:
            add_bot(game)

        p1 = game.players[0]
        p2 = game.players[1]

        a = random.randint(
            1,
            13
        )

        b = random.randint(
            1,
            13
        )

        text = (
            "📈 **بالا یا پایین**\n"
            "━━━━━━━━━━━━\n\n"

            f"🎴 کارت اول: **{a}**\n"
            f"🎴 کارت دوم: **{b}**\n\n"
        )

        if a == b:

            text += "🤝 مساوی!"

            winner = None

        elif a > b:

            text += (
                f"🏆 {game.names[p1]} برنده شد!"
            )

            winner = p1

        else:

            text += (
                f"🏆 {game.names[p2]} برنده شد!"
            )

            winner = p2

        await query.edit_message_text(
            text
        )

        if winner is not None:
            reward_extra_game(
                game,
                winner
            )

        game_manager.delete(
            game.id
        )

        return


    # ========================================================
    # 🔢 ODD EVEN
    # ========================================================

    if game.type == "odd_even":

        if len(game.players) == 1:
            add_bot(game)

        p1 = game.players[0]
        p2 = game.players[1]

        number = random.randint(
            1,
            100
        )

        result = (
            "even"
            if number % 2 == 0
            else "odd"
        )

        # انتخاب تصادفی بازیکن اول
        choice = random.choice([
            "even",
            "odd"
        ])

        winner = (
            p1
            if choice == result
            else p2
        )

        text = (
            "🔢 **زوج یا فرد**\n"
            "━━━━━━━━━━━━\n\n"

            f"🎯 عدد: **{number}**\n"

            f"📌 نتیجه: "
            f"{'زوج' if result == 'even' else 'فرد'}\n\n"

            f"🎲 انتخاب {game.names[p1]}: "
            f"{'زوج' if choice == 'even' else 'فرد'}\n\n"

            f"🏆 برنده: "
            f"**{game.names[winner]}**"
        )

        await query.edit_message_text(
            text
        )

        reward_extra_game(
            game,
            winner
        )

        game_manager.delete(
            game.id
        )

        return


    # ========================================================
    # 🎴 HIGHER CARD
    # ========================================================

    if game.type == "higher":

        if len(game.players) == 1:
            add_bot(game)

        p1 = game.players[0]
        p2 = game.players[1]

        c1, c2 = higher_card()

        text = (
            "🎴 **کارت بالاتر**\n"
            "━━━━━━━━━━━━\n\n"

            f"🫏 {game.names[p1]}: "
            f"**{c1}**\n"

            f"🤖 {game.names[p2]}: "
            f"**{c2}**\n\n"
        )

        if c1 == c2:

            winner = None

            text += "🤝 مساوی!"

        elif c1 > c2:

            winner = p1

            text += (
                f"🏆 برنده: "
                f"**{game.names[p1]}**"
            )

        else:

            winner = p2

            text += (
                f"🏆 برنده: "
                f"**{game.names[p2]}**"
            )

        await query.edit_message_text(
            text
        )

        if winner is not None:
            reward_extra_game(
                game,
                winner
            )

        game_manager.delete(
            game.id
        )

        return


    # ========================================================
    # 🏇 HORSE RACE
    # ========================================================

    if game.type == "horse_race":

        if len(game.players) == 1:
            add_bot(game)

        results = horse_race(
            game
        )

        ordered = sorted(
            results.items(),
            key=lambda x: x[1],
            reverse=True
        )

        text = (
            "🏇 **مسابقه بزرگ خرها**\n"
            "━━━━━━━━━━━━\n\n"
        )

        for index, (
            user_id,
            score
        ) in enumerate(
            ordered,
            1
        ):

            name = game.names[
                user_id
            ]

            text += (
                f"{index}. "
                f"{name} — "
                f"🏃 {score}\n"
            )

        winner = ordered[0][0]

        text += (
            f"\n🏆 برنده: "
            f"**{game.names[winner]}**"
        )

        await query.edit_message_text(
            text
        )

        reward_extra_game(
            game,
            winner
        )

        game_manager.delete(
            game.id
        )

        return


    # ========================================================
    # 🍀 LUCKY
    # ========================================================

    if game.type == "lucky":

        if len(game.players) == 1:
            add_bot(game)

        results = {}

        for user_id in game.players:

            results[user_id] = (
                lucky_donkey(
                    user_id
                )
            )

        ordered = sorted(
            results.items(),
            key=lambda x: x[1],
            reverse=True
        )

        text = (
            "🍀 **شانس خر**\n"
            "━━━━━━━━━━━━\n\n"
        )

        for index, (
            user_id,
            score
        ) in enumerate(
            ordered,
            1
        ):

            text += (
                f"{index}. "
                f"{game.names[user_id]} "
                f"🍀 {score}\n"
            )

        winner = ordered[0][0]

        text += (
            f"\n🏆 برنده: "
            f"**{game.names[winner]}**"
        )

        await query.edit_message_text(
            text
        )

        reward_extra_game(
            game,
            winner
        )

        game_manager.delete(
            game.id
        )

        return


# ============================================================
# EXTRA GAME CALLBACK
# ============================================================

async def extra_game_callback(
    update,
    context
):

    query = update.callback_query

    data = query.data

    # --------------------------------------------------------
    # START EXTRA GAME
    # --------------------------------------------------------

    if data.startswith(
        "extra_start_"
    ):

        game_id = data.replace(
            "extra_start_",
            "",
            1
        )

        game = game_manager.get(
            game_id
        )

        if not game:

            await query.answer(
                "❌ بازی پیدا نشد.",
                show_alert=True
            )

            return True

        await query.answer(
            "🎮 بازی شروع شد!"
        )

        await run_extra_game(
            query,
            game
        )

        return True

    return False


# ============================================================
# EXTRA GAME CREATOR
# ============================================================

async def create_extra_game(
    update,
    context,
    game_type
):

    user = update.effective_user

    chat = update.effective_chat

    if game_type not in EXTRA_GAMES:

        await update.message.reply_text(
            "❌ بازی وجود ندارد."
        )

        return

    if user.id in player_games:

        await update.message.reply_text(
            "❌ تو در یک بازی دیگر هستی."
        )

        return

    game = game_manager.create(

        chat.id,

        game_type,

        user.id,

        user.full_name
    )

    if not game:
        return

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🎮 ورود",
                callback_data=
                f"game_join_{game.id}"
            )
        ],

        [
            InlineKeyboardButton(
                "▶️ شروع",
                callback_data=
                f"extra_start_{game.id}"
            ),

            InlineKeyboardButton(
                "❌ لغو",
                callback_data=
                f"game_cancel_{game.id}"
            )
        ]

    ])

    await update.message.reply_text(

        (
            f"🎮 **{EXTRA_GAMES[game_type]['name']}**\n\n"

            f"👥 بازیکنان: "
            f"{len(game.players)}/"
            f"{EXTRA_GAMES[game_type]['max_players']}\n\n"

            "👥 دوستانت می‌توانند با دکمه ورود "
            "به بازی اضافه شوند.\n\n"

            "🤖 اگر تنها شروع کنی، "
            "بات وارد بازی می‌شود."
        ),

        reply_markup=keyboard
    )


# ============================================================
# EXTRA GAME COMMANDS / ONE WORD
# ============================================================

EXTRA_GAME_WORDS = {

    "سنگ": "rps",
    "قیچی": "rps",
    "کاغذ": "rps",

    "بالاپایین": "highlow",
    "بالا": "highlow",
    "پایین": "highlow",

    "حدس": "guess",

    "سرعت": "reaction",

    "۲۱": "blackjack",
    "21": "blackjack",

    "مسابقه خر": "horse_race",
    "مسابقه‌بزرگ": "horse_race",

    "حافظه": "memory",

    "زوج": "odd_even",
    "فرد": "odd_even",

    "کارت": "higher",

    "شانس": "lucky"
}


async def handle_extra_game_word(
    update,
    context
):

    if not update.message:
        return False

    text = (
        update.message.text
        or ""
    ).strip().lower()

    game_type = EXTRA_GAME_WORDS.get(
        text
    )

    if not game_type:
        return False

    await create_extra_game(
        update,
        context,
        game_type
    )

    return True

# ============================================================
# KHARBOT V15
# 💰 ECONOMY + BET + JACKPOT + STATS + LEADERBOARD
# ============================================================

from datetime import datetime, timedelta
from collections import Counter


# ============================================================
# ECONOMY SETTINGS
# ============================================================

MIN_BET = 10
MAX_BET = 100000

WIN_MULTIPLIER = 1.80
JACKPOT_PERCENT = 5

DAILY_REWARD = 500
DAILY_XP = 50

WEEKLY_REWARD = 5000


# ============================================================
# SAFE INTEGER
# ============================================================

def safe_int(value, default=0):

    try:
        return int(value)

    except Exception:
        return default


# ============================================================
# PLAYER ECONOMY
# ============================================================

def get_player_balance(user_id):

    try:

        return get_coins(user_id)

    except Exception:

        return 0


def can_afford(
    user_id,
    amount
):

    return (
        get_player_balance(user_id)
        >= amount
    )


def charge_player(
    user_id,
    amount
):

    if amount <= 0:
        return False

    if not can_afford(
        user_id,
        amount
    ):
        return False

    try:

        remove_coins(
            user_id,
            amount
        )

        return True

    except Exception:

        return False


def pay_player(
    user_id,
    amount
):

    if amount <= 0:
        return False

    try:

        add_coins(
            user_id,
            amount
        )

        return True

    except Exception:

        return False


# ============================================================
# GAME BET
# ============================================================

class BetGame:

    def __init__(
        self,
        game_id,
        game_type,
        creator_id,
        bet
    ):

        self.id = game_id

        self.game_type = game_type

        self.creator_id = creator_id

        self.bet = bet

        self.players = []

        self.paid_players = set()

        self.finished = False

        self.created_at = time.time()

        self.jackpot = 0


    def add_player(
        self,
        user_id
    ):

        if user_id in self.players:

            return False

        if self.finished:

            return False

        if not charge_player(
            user_id,
            self.bet
        ):

            return False

        self.players.append(
            user_id
        )

        self.paid_players.add(
            user_id
        )

        self.jackpot += (
            self.bet
            *
            JACKPOT_PERCENT
            // 100
        )

        return True


    def refund_all(self):

        for user_id in self.paid_players:

            pay_player(
                user_id,
                self.bet
            )

        self.paid_players.clear()


    def payout(
        self,
        winner_id
    ):

        if winner_id not in self.paid_players:

            return 0

        pool = (
            self.bet
            *
            len(self.players)
        )

        jackpot = self.jackpot

        winner_amount = (
            pool
            +
            jackpot
        )

        pay_player(
            winner_id,
            winner_amount
        )

        self.finished = True

        return winner_amount


# ============================================================
# BET VALIDATION
# ============================================================

def validate_bet(
    user_id,
    bet
):

    bet = safe_int(
        bet
    )

    if bet < MIN_BET:

        return (
            False,
            f"❌ حداقل شرط "
            f"{MIN_BET:,} سکه است."
        )

    if bet > MAX_BET:

        return (
            False,
            f"❌ حداکثر شرط "
            f"{MAX_BET:,} سکه است."
        )

    if not can_afford(
        user_id,
        bet
    ):

        return (
            False,
            "❌ سکه کافی نداری."
        )

    return (
        True,
        ""
    )


# ============================================================
# BET GAMES STORAGE
# ============================================================

bet_games = {}


# ============================================================
# CREATE BET GAME
# ============================================================

async def create_bet_game(
    update,
    context,
    game_type,
    bet
):

    user = update.effective_user

    chat = update.effective_chat

    valid, error = validate_bet(
        user.id,
        bet
    )

    if not valid:

        await update.message.reply_text(
            error
        )

        return

    if user.id in player_games:

        await update.message.reply_text(
            "❌ اول از بازی فعلی خارج شو."
        )

        return

    game_id = make_game_id()

    game = BetGame(
        game_id,
        game_type,
        user.id,
        bet
    )

    if not game.add_player(
        user.id
    ):

        await update.message.reply_text(
            "❌ پرداخت ورودی انجام نشد."
        )

        return

    bet_games[
        game_id
    ] = game

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "💰 ورود به بازی",
                callback_data=
                f"bet_join_{game_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "▶️ شروع",
                callback_data=
                f"bet_start_{game_id}"
            ),

            InlineKeyboardButton(
                "❌ لغو",
                callback_data=
                f"bet_cancel_{game_id}"
            )
        ]

    ])

    await update.message.reply_text(

        (
            f"💰 **بازی شرطی**\n"
            f"━━━━━━━━━━━━\n\n"

            f"🎮 بازی: "
            f"{game_type}\n"

            f"💵 ورودی: "
            f"{bet:,} 🪙\n"

            f"🏦 جک‌پات فعلی: "
            f"{game.jackpot:,} 🪙\n\n"

            f"👤 سازنده: "
            f"{user.full_name}\n\n"

            "👥 بقیه بازیکنان می‌توانند "
            "با دکمه ورود شرکت کنند."
        ),

        reply_markup=keyboard
    )


# ============================================================
# BET CALLBACK
# ============================================================

async def bet_callback(
    update,
    context
):

    query = update.callback_query

    data = query.data

    user_id = query.from_user.id


    # ========================================================
    # JOIN
    # ========================================================

    if data.startswith(
        "bet_join_"
    ):

        game_id = data.replace(
            "bet_join_",
            "",
            1
        )

        game = bet_games.get(
            game_id
        )

        if not game:

            await query.answer(
                "❌ بازی پیدا نشد.",
                show_alert=True
            )

            return True

        if game.finished:

            await query.answer(
                "❌ بازی تمام شده.",
                show_alert=True
            )

            return True

        if user_id in game.players:

            await query.answer(
                "❌ قبلاً وارد شدی.",
                show_alert=True
            )

            return True

        if not game.add_player(
            user_id
        ):

            await query.answer(
                "❌ سکه کافی نداری.",
                show_alert=True
            )

            return True

        await query.answer(
            "✅ وارد بازی شدی!"
        )

        await query.edit_message_text(

            (
                "💰 **بازی شرطی**\n\n"

                f"👥 بازیکنان: "
                f"{len(game.players)}\n"

                f"💵 ورودی: "
                f"{game.bet:,} 🪙\n"

                f"🏦 جک‌پات: "
                f"{game.jackpot:,} 🪙\n\n"

                "▶️ سازنده می‌تواند بازی را شروع کند."
            ),

            reply_markup=query.message.reply_markup
        )

        return True


    # ========================================================
    # CANCEL
    # ========================================================

    if data.startswith(
        "bet_cancel_"
    ):

        game_id = data.replace(
            "bet_cancel_",
            "",
            1
        )

        game = bet_games.get(
            game_id
        )

        if not game:

            await query.answer(
                "❌ بازی پیدا نشد.",
                show_alert=True
            )

            return True

        if user_id != game.creator_id:

            await query.answer(
                "❌ فقط سازنده می‌تواند لغو کند.",
                show_alert=True
            )

            return True

        game.refund_all()

        game.finished = True

        bet_games.pop(
            game_id,
            None
        )

        await query.answer(
            "❌ بازی لغو شد و سکه‌ها برگشت."
        )

        await query.edit_message_text(
            "❌ **بازی لغو شد.**\n\n"
            "💰 ورودی همه بازیکنان برگشت داده شد."
        )

        return True


    # ========================================================
    # START
    # ========================================================

    if data.startswith(
        "bet_start_"
    ):

        game_id = data.replace(
            "bet_start_",
            "",
            1
        )

        game = bet_games.get(
            game_id
        )

        if not game:

            await query.answer(
                "❌ بازی پیدا نشد.",
                show_alert=True
            )

            return True

        if user_id != game.creator_id:

            await query.answer(
                "❌ فقط سازنده می‌تواند شروع کند.",
                show_alert=True
            )

            return True

        if len(game.players) < 2:

            await query.answer(
                "❌ حداقل دو بازیکن لازم است.",
                show_alert=True
            )

            return True

        await query.answer(
            "🎮 بازی شروع شد!"
        )

        # فعلاً انتخاب برنده تصادفی
        # موتور بازی‌های واقعی در پارت‌های بعدی
        winner = random.choice(
            game.players
        )

        amount = game.payout(
            winner
        )

        winner_name = (
            query.from_user.full_name
            if winner == user_id
            else "بازیکن برنده"
        )

        await query.edit_message_text(

            (
                "🏆 **بازی تمام شد!**\n"
                "━━━━━━━━━━━━\n\n"

                f"🥇 برنده: "
                f"**{winner_name}**\n\n"

                f"💰 جایزه: "
                f"**{amount:,} 🪙**"
            )
        )

        bet_games.pop(
            game_id,
            None
        )

        return True

    return False


# ============================================================
# PLAYER STATISTICS
# ============================================================

def get_stats(
    user_id
):

    try:

        return get_player_stats(
            user_id
        )

    except Exception:

        return {
            "wins": 0,
            "losses": 0,
            "games": 0,
            "xp": 0
        }


def stats_text(
    user_id,
    name
):

    stats = get_stats(
        user_id
    )

    wins = safe_int(
        stats.get(
            "wins",
            0
        )
    )

    losses = safe_int(
        stats.get(
            "losses",
            0
        )
    )

    games = safe_int(
        stats.get(
            "games",
            wins + losses
        )
    )

    xp = safe_int(
        stats.get(
            "xp",
            0
        )
    )

    balance = get_player_balance(
        user_id
    )

    if games:

        winrate = (
            wins * 100
        ) / games

    else:

        winrate = 0

    return (

        "👤 **پروفایل بازیکن**\n"
        "━━━━━━━━━━━━\n\n"

        f"🫏 نام: **{name}**\n"

        f"🪙 سکه: "
        f"**{balance:,}**\n"

        f"⭐ XP: "
        f"**{xp:,}**\n\n"

        f"🎮 بازی‌ها: "
        f"**{games:,}**\n"

        f"🏆 برد: "
        f"**{wins:,}**\n"

        f"💀 باخت: "
        f"**{losses:,}**\n"

        f"📊 نرخ برد: "
        f"**{winrate:.1f}%**"
    )


# ============================================================
# LEADERBOARD
# ============================================================

def leaderboard_data(
    limit=10
):

    try:

        return get_leaderboard(
            limit
        )

    except Exception:

        return []


def leaderboard_text(
    limit=10
):

    rows = leaderboard_data(
        limit
    )

    if not rows:

        return (
            "🏆 **لیدربرد**\n\n"
            "هنوز اطلاعاتی ثبت نشده."
        )

    text = (
        "🏆 **KHARBOT LEADERBOARD**\n"
        "━━━━━━━━━━━━━━━━\n\n"
    )

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    for index, row in enumerate(
        rows,
        1
    ):

        if isinstance(
            row,
            dict
        ):

            name = row.get(
                "name",
                "بازیکن"
            )

            coins = safe_int(
                row.get(
                    "coins",
                    0
                )
            )

        else:

            name = str(
                row[0]
            )

            coins = safe_int(
                row[1]
            )

        medal = (
            medals[index - 1]
            if index <= 3
            else f"{index}."
        )

        text += (
            f"{medal} "
            f"**{name}** — "
            f"{coins:,} 🪙\n"
        )

    return text


# ============================================================
# DAILY REWARD
# ============================================================

daily_claims = {}


def claim_daily(
    user_id
):

    now = time.time()

    last = daily_claims.get(
        user_id,
        0
    )

    cooldown = (
        24 * 60 * 60
    )

    if now - last < cooldown:

        remaining = int(
            cooldown
            -
            (now - last)
        )

        hours = remaining // 3600

        minutes = (
            remaining % 3600
        ) // 60

        return (
            False,
            (
                f"⏳ پاداش روزانه قبلاً "
                f"گرفته شده.\n\n"
                f"⏱ {hours} ساعت و "
                f"{minutes} دقیقه دیگر."
            )
        )

    daily_claims[
        user_id
    ] = now

    add_coins(
        user_id,
        DAILY_REWARD
    )

    add_xp(
        user_id,
        DAILY_XP
    )

    return (
        True,
        (
            "🎁 **پاداش روزانه**\n\n"
            f"🪙 +{DAILY_REWARD:,} سکه\n"
            f"⭐ +{DAILY_XP} XP"
        )
    )


# ============================================================
# TEXT COMMANDS
# ============================================================

async def economy_text_handler(
    update,
    context
):

    if not update.message:

        return False

    text = (
        update.message.text
        or ""
    ).strip().lower()

    user = update.effective_user


    # --------------------------------------------------------
    # PROFILE
    # --------------------------------------------------------

    if text in (
        "پروفایل",
        "پروفايل",
        "profile",
        "me"
    ):

        await update.message.reply_text(

            stats_text(
                user.id,
                user.full_name
            )
        )

        return True


    # --------------------------------------------------------
    # LEADERBOARD
    # --------------------------------------------------------

    if text in (
        "لیدربرد",
        "لیدر",
        "برترین",
        "leaderboard",
        "top"
    ):

        await update.message.reply_text(

            leaderboard_text()
        )

        return True


    # --------------------------------------------------------
    # DAILY
    # --------------------------------------------------------

    if text in (
        "روزانه",
        "پاداش",
        "daily"
    ):

        success, message = claim_daily(
            user.id
        )

        await update.message.reply_text(
            message
        )

        return True


    # --------------------------------------------------------
    # BALANCE
    # --------------------------------------------------------

    if text in (
        "موجودی",
        "سکه",
        "balance"
    ):

        balance = get_player_balance(
            user.id
        )

        await update.message.reply_text(

            (
                "🪙 **موجودی شما**\n\n"
                f"💰 {balance:,} سکه"
            )
        )

        return True


    return False


# ============================================================
# ECONOMY CALLBACK CONNECTOR
# ============================================================

async def economy_callback_handler(
    update,
    context
):

    handled = await bet_callback(
        update,
        context
    )

    if handled:
        return True

    return False

# ============================================================
# KHARBOT FINAL CORE
# 🗄️ DATABASE + 🫏 DONKEY + 🛒 SHOP + 📊 STATS
# ============================================================

import sqlite3
import threading
import time
import random
from pathlib import Path


# ============================================================
# DATABASE
# ============================================================

DB_PATH = "/tmp/kharbot.db"

db_lock = threading.RLock()


def db_connect():

    return sqlite3.connect(
        DB_PATH,
        check_same_thread=False
    )


def db_execute(
    query,
    params=(),
    fetchone=False,
    fetchall=False,
    commit=True
):

    with db_lock:

        connection = db_connect()

        try:

            cursor = connection.cursor()

            cursor.execute(
                query,
                params
            )

            result = None

            if fetchone:

                result = cursor.fetchone()

            elif fetchall:

                result = cursor.fetchall()

            if commit:

                connection.commit()

            return result

        finally:

            connection.close()


# ============================================================
# CREATE TABLES
# ============================================================

def init_database():

    db_execute("""
        CREATE TABLE IF NOT EXISTS users (

            user_id INTEGER PRIMARY KEY,

            name TEXT DEFAULT '',

            coins INTEGER DEFAULT 1000,

            xp INTEGER DEFAULT 0,

            level INTEGER DEFAULT 1,

            wins INTEGER DEFAULT 0,

            losses INTEGER DEFAULT 0,

            games INTEGER DEFAULT 0,

            created_at INTEGER,

            last_seen INTEGER

        )
    """)


    db_execute("""
        CREATE TABLE IF NOT EXISTS donkeys (

            user_id INTEGER PRIMARY KEY,

            name TEXT DEFAULT 'خر من',

            level INTEGER DEFAULT 1,

            health INTEGER DEFAULT 100,

            hunger INTEGER DEFAULT 100,

            thirst INTEGER DEFAULT 100,

            energy INTEGER DEFAULT 100,

            hygiene INTEGER DEFAULT 100,

            happiness INTEGER DEFAULT 100,

            strength INTEGER DEFAULT 10,

            speed INTEGER DEFAULT 10,

            luck INTEGER DEFAULT 10,

            intelligence INTEGER DEFAULT 10,

            sounds INTEGER DEFAULT 1,

            breeding_count INTEGER DEFAULT 0,

            last_update INTEGER,

            FOREIGN KEY(user_id)
                REFERENCES users(user_id)

        )
    """)


    db_execute("""
        CREATE TABLE IF NOT EXISTS inventory (

            user_id INTEGER,

            item TEXT,

            amount INTEGER DEFAULT 0,

            PRIMARY KEY(user_id, item)

        )
    """)


    db_execute("""
        CREATE TABLE IF NOT EXISTS transactions (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER,

            type TEXT,

            amount INTEGER,

            description TEXT,

            created_at INTEGER

        )
    """)


    db_execute("""
        CREATE TABLE IF NOT EXISTS game_stats (

            user_id INTEGER PRIMARY KEY,

            wins INTEGER DEFAULT 0,

            losses INTEGER DEFAULT 0,

            games INTEGER DEFAULT 0,

            coins_won INTEGER DEFAULT 0,

            coins_lost INTEGER DEFAULT 0

        )
    """)


init_database()


# ============================================================
# USER
# ============================================================

def ensure_user(
    user_id,
    name=""
):

    now = int(
        time.time()
    )

    db_execute(
        """
        INSERT OR IGNORE INTO users
        (
            user_id,
            name,
            coins,
            created_at,
            last_seen
        )
        VALUES (?, ?, 1000, ?, ?)
        """,
        (
            user_id,
            name,
            now,
            now
        )
    )

    db_execute(
        """
        UPDATE users
        SET
            name=?,
            last_seen=?
        WHERE user_id=?
        """,
        (
            name,
            now,
            user_id
        )
    )


    db_execute(
        """
        INSERT OR IGNORE INTO donkeys
        (
            user_id,
            name,
            last_update
        )
        VALUES (?, ?, ?)
        """,
        (
            user_id,
            f"خر {name}",
            now
        )
    )


    db_execute(
        """
        INSERT OR IGNORE INTO game_stats
        (user_id)
        VALUES (?)
        """,
        (
            user_id,
        )
    )


# ============================================================
# COINS
# ============================================================

def get_coins(
    user_id
):

    ensure_user(
        user_id
    )

    row = db_execute(
        """
        SELECT coins
        FROM users
        WHERE user_id=?
        """,
        (
            user_id,
        ),
        fetchone=True
    )

    return int(
        row[0]
        if row
        else 0
    )


def add_coins(
    user_id,
    amount
):

    if amount <= 0:
        return False

    ensure_user(
        user_id
    )

    db_execute(
        """
        UPDATE users
        SET coins = coins + ?
        WHERE user_id=?
        """,
        (
            amount,
            user_id
        )
    )

    db_execute(
        """
        INSERT INTO transactions
        (
            user_id,
            type,
            amount,
            description,
            created_at
        )
        VALUES (?, 'ADD', ?, ?, ?)
        """,
        (
            user_id,
            amount,
            "coin reward",
            int(time.time())
        )
    )

    return True


def remove_coins(
    user_id,
    amount
):

    if amount <= 0:
        return False

    ensure_user(
        user_id
    )

    with db_lock:

        connection = db_connect()

        try:

            cursor = connection.cursor()

            cursor.execute(
                """
                UPDATE users

                SET coins = coins - ?

                WHERE user_id=?

                AND coins >= ?
                """,
                (
                    amount,
                    user_id,
                    amount
                )
            )

            if cursor.rowcount != 1:

                connection.rollback()

                return False

            cursor.execute(
                """
                INSERT INTO transactions
                (
                    user_id,
                    type,
                    amount,
                    description,
                    created_at
                )
                VALUES (?, 'REMOVE', ?, ?, ?)
                """,
                (
                    user_id,
                    amount,
                    "coin spend",
                    int(time.time())
                )
            )

            connection.commit()

            return True

        finally:

            connection.close()


# ============================================================
# XP / LEVEL
# ============================================================

def xp_required(
    level
):

    return (
        100
        +
        (level - 1) * 75
    )


def add_xp(
    user_id,
    amount
):

    if amount <= 0:
        return

    ensure_user(
        user_id
    )

    db_execute(
        """
        UPDATE users
        SET xp = xp + ?
        WHERE user_id=?
        """,
        (
            amount,
            user_id
        )
    )

    check_level_up(
        user_id
    )


def check_level_up(
    user_id
):

    row = db_execute(
        """
        SELECT xp, level
        FROM users
        WHERE user_id=?
        """,
        (
            user_id,
        ),
        fetchone=True
    )

    if not row:
        return

    xp = int(row[0])

    level = int(row[1])

    changed = False

    while xp >= xp_required(level):

        xp -= xp_required(
            level
        )

        level += 1

        changed = True

    if changed:

        db_execute(
            """
            UPDATE users

            SET
                xp=?,
                level=?

            WHERE user_id=?
            """,
            (
                xp,
                level,
                user_id
            )
        )


# ============================================================
# GAME STATS
# ============================================================

def record_game_win(
    user_id
):

    ensure_user(
        user_id
    )

    db_execute(
        """
        UPDATE users

        SET
            wins=wins+1,
            games=games+1

        WHERE user_id=?
        """,
        (
            user_id,
        )
    )

    db_execute(
        """
        UPDATE game_stats

        SET
            wins=wins+1,
            games=games+1

        WHERE user_id=?
        """,
        (
            user_id,
        )
    )


def record_game_loss(
    user_id
):

    ensure_user(
        user_id
    )

    db_execute(
        """
        UPDATE users

        SET
            losses=losses+1,
            games=games+1

        WHERE user_id=?
        """,
        (
            user_id,
        )
    )

    db_execute(
        """
        UPDATE game_stats

        SET
            losses=losses+1,
            games=games+1

        WHERE user_id=?
        """,
        (
            user_id,
        )
    )


def get_player_stats(
    user_id
):

    ensure_user(
        user_id
    )

    row = db_execute(
        """
        SELECT
            wins,
            losses,
            games,
            xp,
            level

        FROM users

        WHERE user_id=?
        """,
        (
            user_id,
        ),
        fetchone=True
    )

    if not row:

        return {}

    return {

        "wins": row[0],

        "losses": row[1],

        "games": row[2],

        "xp": row[3],

        "level": row[4]

    }


# ============================================================
# LEADERBOARD
# ============================================================

def get_leaderboard(
    limit=10
):

    return db_execute(
        """
        SELECT
            name,
            coins

        FROM users

        ORDER BY coins DESC

        LIMIT ?
        """,
        (
            limit,
        ),
        fetchall=True
    )


# ============================================================
# DONKEY
# ============================================================

DONKEY_COLUMNS = (

    "name",
    "level",
    "health",
    "hunger",
    "thirst",
    "energy",
    "hygiene",
    "happiness",
    "strength",
    "speed",
    "luck",
    "intelligence",
    "sounds",
    "breeding_count"

)


def get_donkey(
    user_id
):

    ensure_user(
        user_id
    )

    row = db_execute(
        """
        SELECT
            name,
            level,
            health,
            hunger,
            thirst,
            energy,
            hygiene,
            happiness,
            strength,
            speed,
            luck,
            intelligence,
            sounds,
            breeding_count

        FROM donkeys

        WHERE user_id=?
        """,
        (
            user_id,
        ),
        fetchone=True
    )

    if not row:
        return None

    return dict(
        zip(
            DONKEY_COLUMNS,
            row
        )
    )


# ============================================================
# DONKEY UPDATE
# ============================================================

def update_donkey(
    user_id,
    field,
    value
):

    if field not in DONKEY_COLUMNS:

        return False

    if field == "name":

        db_execute(
            f"""
            UPDATE donkeys
            SET {field}=?
            WHERE user_id=?
            """,
            (
                str(value)[:30],
                user_id
            )
        )

    else:

        value = max(
            0,
            min(
                100,
                int(value)
            )
        )

        db_execute(
            f"""
            UPDATE donkeys
            SET {field}=?
            WHERE user_id=?
            """,
            (
                value,
                user_id
            )
        )

    return True


# ============================================================
# DONKEY NEEDS
# ============================================================

def update_donkey_needs():

    now = int(
        time.time()
    )

    rows = db_execute(
        """
        SELECT
            user_id,
            last_update

        FROM donkeys
        """,
        fetchall=True
    )

    for user_id, last_update in rows:

        elapsed = (
            now
            -
            int(last_update or now)
        )

        # هر 30 دقیقه
        # نیازها کمی کاهش پیدا می‌کنند

        steps = elapsed // 1800

        if steps <= 0:
            continue

        db_execute(
            """
            UPDATE donkeys

            SET
                hunger=
                    MAX(0, hunger-?),

                thirst=
                    MAX(0, thirst-?),

                energy=
                    MAX(0, energy-?),

                hygiene=
                    MAX(0, hygiene-?),

                happiness=
                    MAX(0, happiness-?)

            WHERE user_id=?
            """,
            (
                steps * 3,
                steps * 4,
                steps * 2,
                steps * 2,
                steps,
                user_id
            )
        )

        db_execute(
            """
            UPDATE donkeys
            SET last_update=?
            WHERE user_id=?
            """,
            (
                now,
                user_id
            )
        )


# ============================================================
# DONKEY ACTIONS
# ============================================================

DONKEY_ACTIONS = {

    "food": {

        "field": "hunger",

        "value": 25,

        "cost": 30

    },

    "water": {

        "field": "thirst",

        "value": 30,

        "cost": 20

    },

    "shower": {

        "field": "hygiene",

        "value": 35,

        "cost": 40

    },

    "rest": {

        "field": "energy",

        "value": 30,

        "cost": 25

    },

    "play": {

        "field": "happiness",

        "value": 25,

        "cost": 35

    }

}


def donkey_action(
    user_id,
    action
):

    if action not in DONKEY_ACTIONS:

        return (
            False,
            "❌ عملیات نامعتبر."
        )

    data = DONKEY_ACTIONS[
        action
    ]

    cost = data["cost"]

    if not remove_coins(
        user_id,
        cost
    ):

        return (
            False,
            "❌ سکه کافی نداری."
        )

    donkey = get_donkey(
        user_id
    )

    current = donkey[
        data["field"]
    ]

    new_value = min(
        100,
        current + data["value"]
    )

    update_donkey(
        user_id,
        data["field"],
        new_value
    )

    # بازی و فعالیت کمی شادی اضافه می‌کند

    if action == "play":

        update_donkey(
            user_id,
            "happiness",
            new_value
        )

    return (
        True,
        f"✅ انجام شد.\n"
        f"🪙 هزینه: {cost:,}"
    )


# ============================================================
# DONKEY UPGRADE
# ============================================================

UPGRADE_PRICES = {

    "strength": 150,

    "speed": 150,

    "luck": 200,

    "intelligence": 200

}


def upgrade_donkey(
    user_id,
    stat
):

    if stat not in UPGRADE_PRICES:

        return (
            False,
            "❌ ویژگی نامعتبر."
        )

    donkey = get_donkey(
        user_id
    )

    if not donkey:

        return (
            False,
            "❌ خر پیدا نشد."
        )

    current = donkey[
        stat
    ]

    if current >= 100:

        return (
            False,
            "⭐ این ویژگی به حداکثر رسیده."
        )

    level = donkey[
        "level"
    ]

    cost = (
        UPGRADE_PRICES[stat]
        *
        level
    )

    if not remove_coins(
        user_id,
        cost
    ):

        return (
            False,
            f"❌ {cost:,} سکه لازم داری."
        )

    update_donkey(
        user_id,
        stat,
        current + 5
    )

    return (
        True,
        (
            f"⬆️ **ارتقا انجام شد**\n\n"
            f"📊 {stat}\n"
            f"➕ +5\n"
            f"🪙 هزینه: {cost:,}"
        )
    )


# ============================================================
# DONKEY SOUND
# ============================================================

DONKEY_SOUNDS = {

    1: "عــرررر 🫏",

    2: "عــــررررررررر 😤",

    3: "ایـــــــ عــــرررر 😂",

    4: "هـــــــعــــررررررر 🤣",

    5: "عــــــرررررررررررر 💀"

}


def donkey_sound(
    user_id
):

    donkey = get_donkey(
        user_id
    )

    if not donkey:
        return "عــر 🫏"

    level = donkey[
        "sounds"
    ]

    level = max(
        1,
        min(
            5,
            level
        )
    )

    return DONKEY_SOUNDS[
        level
    ]


# ============================================================
# BUY DONKEY SOUND
# ============================================================

SOUND_PRICES = {

    2: 500,

    3: 1500,

    4: 4000,

    5: 10000

}


def upgrade_sound(
    user_id
):

    donkey = get_donkey(
        user_id
    )

    current = donkey[
        "sounds"
    ]

    if current >= 5:

        return (
            False,
            "🔊 صدای خر به آخرین سطح رسیده."
        )

    new_level = current + 1

    cost = SOUND_PRICES[
        new_level
    ]

    if not remove_coins(
        user_id,
        cost
    ):

        return (
            False,
            f"❌ {cost:,} سکه لازم داری."
        )

    db_execute(
        """
        UPDATE donkeys

        SET sounds=?

        WHERE user_id=?
        """,
        (
            new_level,
            user_id
        )
    )

    return (
        True,
        (
            "🔊 **صدای جدید خریداری شد!**\n\n"
            f"📢 سطح صدا: {new_level}\n"
            f"🪙 هزینه: {cost:,}"
        )
    )


# ============================================================
# INVENTORY
# ============================================================

def add_item(
    user_id,
    item,
    amount=1
):

    db_execute(
        """
        INSERT INTO inventory
        (
            user_id,
            item,
            amount
        )

        VALUES (?, ?, ?)

        ON CONFLICT(user_id, item)

        DO UPDATE SET
            amount=amount+excluded.amount
        """,
        (
            user_id,
            item,
            amount
        )
    )


def get_inventory(
    user_id
):

    return db_execute(
        """
        SELECT
            item,
            amount

        FROM inventory

        WHERE user_id=?

        AND amount > 0
        """,
        (
            user_id,
        ),
        fetchall=True
    )


# ============================================================
# SHOP
# ============================================================

SHOP_ITEMS = {

    "food": {

        "name": "🥕 غذای خر",

        "price": 50

    },

    "water": {

        "name": "💧 آب",

        "price": 30

    },

    "medicine": {

        "name": "💊 دارو",

        "price": 200

    },

    "soap": {

        "name": "🧼 صابون",

        "price": 80

    },

    "energy": {

        "name": "⚡ انرژی‌زا",

        "price": 120

    }

}


def buy_item(
    user_id,
    item
):

    if item not in SHOP_ITEMS:

        return (
            False,
            "❌ آیتم وجود ندارد."
        )

    price = SHOP_ITEMS[
        item
    ]["price"]

    if not remove_coins(
        user_id,
        price
    ):

        return (
            False,
            "❌ سکه کافی نداری."
        )

    add_item(
        user_id,
        item
    )

    return (
        True,
        (
            f"🛒 خرید موفق!\n\n"
            f"{SHOP_ITEMS[item]['name']}\n"
            f"🪙 {price:,}"
        )
    )


# ============================================================
# DONKEY PROFILE
# ============================================================

def donkey_profile_text(
    user_id
):

    donkey = get_donkey(
        user_id
    )

    if not donkey:

        return "❌ خر پیدا نشد."

    return (

        "🫏 **پروفایل خر شما**\n"
        "━━━━━━━━━━━━━━━━\n\n"

        f"🏷 نام: "
        f"**{donkey['name']}**\n"

        f"⭐ سطح: "
        f"**{donkey['level']}**\n\n"

        f"❤️ سلامتی: "
        f"{donkey['health']}/100\n"

        f"🍖 گرسنگی: "
        f"{donkey['hunger']}/100\n"

        f"💧 تشنگی: "
        f"{donkey['thirst']}/100\n"

        f"⚡ انرژی: "
        f"{donkey['energy']}/100\n"

        f"🧼 نظافت: "
        f"{donkey['hygiene']}/100\n"

        f"❤️ شادی: "
        f"{donkey['happiness']}/100\n\n"

        f"💪 قدرت: "
        f"{donkey['strength']}\n"

        f"🏃 سرعت: "
        f"{donkey['speed']}\n"

        f"🍀 شانس: "
        f"{donkey['luck']}\n"

        f"🧠 هوش: "
        f"{donkey['intelligence']}\n\n"

        f"🔊 صدای عرعر: "
        f"سطح {donkey['sounds']}\n"

        f"💕 جفت‌گیری: "
        f"{donkey['breeding_count']} بار"
    )


# ============================================================
# COMMAND / TEXT HANDLER
# ============================================================

async def donkey_text_handler(
    update,
    context
):

    if not update.message:

        return False

    text = (
        update.message.text
        or ""
    ).strip().lower()

    user = update.effective_user

    ensure_user(
        user.id,
        user.full_name
    )


    # --------------------------------------------------------
    # DONKEY
    # --------------------------------------------------------

    if text in (
        "خر",
        "donkey",
        "خر من",
        "پروفایل خر"
    ):

        await update.message.reply_text(

            donkey_profile_text(
                user.id
            )
        )

        return True


    # --------------------------------------------------------
    # SOUND
    # --------------------------------------------------------

    if text in (
        "عر",
        "عرعر",
        "عر عر",
        "صدا"
    ):

        sound = donkey_sound(
            user.id
        )

        await update.message.reply_text(
            sound
        )

        return True


    # --------------------------------------------------------
    # FOOD
    # --------------------------------------------------------

    if text in (
        "غذا",
        "غذا بده",
        "گرسنه"
    ):

        ok, message = donkey_action(
            user.id,
            "food"
        )

        await update.message.reply_text(
            message
        )

        return True


    # --------------------------------------------------------
    # WATER
    # --------------------------------------------------------

    if text in (
        "آب",
        "آب بده",
        "تشنه"
    ):

        ok, message = donkey_action(
            user.id,
            "water"
        )

        await update.message.reply_text(
            message
        )

        return True


    # --------------------------------------------------------
    # SHOWER
    # --------------------------------------------------------

    if text in (
        "حموم",
        "حمام",
        "بشور"
    ):

        ok, message = donkey_action(
            user.id,
            "shower"
        )

        await update.message.reply_text(
            message
        )

        return True


    # --------------------------------------------------------
    # REST
    # --------------------------------------------------------

    if text in (
        "بخواب",
        "استراحت",
        "خواب"
    ):

        ok, message = donkey_action(
            user.id,
            "rest"
        )

        await update.message.reply_text(
            message
        )

        return True


    # --------------------------------------------------------
    # PLAY
    # --------------------------------------------------------

    if text in (
        "بازی با خر",
        "بازی خر"
    ):

        ok, message = donkey_action(
            user.id,
            "play"
        )

        await update.message.reply_text(
            message
        )

        return True


    return False


# ============================================================
# BACKGROUND NEEDS
# ============================================================

def donkey_background_loop():

    while True:

        try:

            update_donkey_needs()

        except Exception as error:

            print(
                "DONKEY LOOP ERROR:",
                repr(error)
            )

        time.sleep(
            600
        )


# ============================================================
# START BACKGROUND THREAD
# ============================================================

donkey_thread = threading.Thread(
    target=donkey_background_loop,
    daemon=True
)

donkey_thread.start()


# ============================================================
# END FINAL CORE
# ============================================================

# ============================================================
# 🫏 KHARBOT - FINAL GAME ENGINE
# ============================================================

import asyncio
import random
import time
from dataclasses import dataclass, field


# ============================================================
# GAME CONFIG
# ============================================================

GAME_TIMEOUT = 180

MIN_PLAYERS = 2
MAX_PLAYERS = 8

ACTIVE_GAMES = {}


# ============================================================
# GAME OBJECT
# ============================================================

@dataclass
class GameRoom:

    game_id: str

    game_type: str

    chat_id: int

    creator_id: int

    bet: int = 0

    players: list = field(default_factory=list)

    names: dict = field(default_factory=dict)

    started: bool = False

    cancelled: bool = False

    created_at: float = field(
        default_factory=time.time
    )

    turn: int = 0

    data: dict = field(
        default_factory=dict
    )


# ============================================================
# GAME ID
# ============================================================

def new_game_id():

    return (
        f"{int(time.time()*1000)}"
        f"{random.randint(100,999)}"
    )


# ============================================================
# CREATE ROOM
# ============================================================

def create_room(
    game_type,
    chat_id,
    creator_id,
    name,
    bet=0
):

    game_id = new_game_id()

    room = GameRoom(

        game_id=game_id,

        game_type=game_type,

        chat_id=chat_id,

        creator_id=creator_id,

        bet=bet

    )

    room.players.append(
        creator_id
    )

    room.names[
        creator_id
    ] = name

    ACTIVE_GAMES[
        game_id
    ] = room

    return room


# ============================================================
# JOIN
# ============================================================

def join_room(
    room,
    user_id,
    name
):

    if room.started:

        return False, "❌ بازی شروع شده."

    if room.cancelled:

        return False, "❌ بازی لغو شده."

    if user_id in room.players:

        return False, "❌ قبلاً وارد بازی شدی."

    if len(room.players) >= MAX_PLAYERS:

        return False, "❌ ظرفیت بازی پر است."

    # شرط مجازی
    if room.bet > 0:

        if not remove_coins(
            user_id,
            room.bet
        ):

            return (
                False,
                "❌ سکه کافی نداری."
            )

    room.players.append(
        user_id
    )

    room.names[
        user_id
    ] = name

    return True, "✅ وارد بازی شدی."


# ============================================================
# CANCEL ROOM
# ============================================================

def cancel_room(
    room
):

    if room.cancelled:

        return

    room.cancelled = True

    # بازگرداندن شرط
    if room.bet > 0:

        for user_id in room.players:

            add_coins(
                user_id,
                room.bet
            )

    ACTIVE_GAMES.pop(
        room.game_id,
        None
    )


# ============================================================
# FINISH ROOM
# ============================================================

def finish_room(
    room
):

    room.started = False

    ACTIVE_GAMES.pop(
        room.game_id,
        None
    )


# ============================================================
# GAME LIST
# ============================================================

GAMES = {

    "تاس": "🎲 تاس",

    "حدس": "🔢 حدس عدد",

    "سکه": "🪙 شیر یا خط",

    "جنگ": "⚔️ جنگ",

    "ریس": "🏇 مسابقه",

    "بمب": "💣 بمب",

    "دزد": "🥷 دزد و پلیس",

    "گنج": "💎 گنج",

    "چالش": "🧠 چالش",

    "عرعر": "🫏 عرعر"

}


# ============================================================
# GAME MENU
# ============================================================

def game_menu():

    keyboard = []

    for key, title in GAMES.items():

        keyboard.append([

            InlineKeyboardButton(
                title,
                callback_data=f"game_{key}"
            )

        ])

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# GAME MESSAGE
# ============================================================

def room_text(
    room
):

    players = "\n".join(

        f"👤 {i+1}. "
        f"{room.names[user_id]}"

        for i, user_id
        in enumerate(room.players)

    )

    return (

        f"🎮 **{GAMES.get(room.game_type, room.game_type)}**\n"
        f"━━━━━━━━━━━━━━\n\n"

        f"👥 بازیکنان: "
        f"{len(room.players)}/{MAX_PLAYERS}\n"

        f"💰 ورودی: "
        f"{room.bet:,} 🪙\n\n"

        f"{players}\n\n"

        "👇 برای ورود دکمه را بزنید."
    )


# ============================================================
# START BUTTONS
# ============================================================

def room_keyboard(
    room
):

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "➕ ورود",
                callback_data=
                f"join_{room.game_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "▶️ شروع",
                callback_data=
                f"start_{room.game_id}"
            ),

            InlineKeyboardButton(
                "❌ لغو",
                callback_data=
                f"cancel_{room.game_id}"
            )
        ]

    ])


# ============================================================
# GAME 1 - DICE
# ============================================================

async def play_dice(
    room,
    update
):

    results = []

    for user_id in room.players:

        value = random.randint(
            1,
            6
        )

        results.append(
            (
                user_id,
                value
            )
        )

    results.sort(
        key=lambda x: x[1],
        reverse=True
    )

    winner = results[0][0]

    text = "🎲 **نتیجه تاس**\n\n"

    for user_id, value in results:

        text += (
            f"👤 {room.names[user_id]}: "
            f"🎲 {value}\n"
        )

    text += (
        f"\n🏆 برنده: "
        f"**{room.names[winner]}**"
    )

    await update.message.reply_text(
        text
    )

    return winner


# ============================================================
# GAME 2 - COIN
# ============================================================

async def play_coin(
    room,
    update
):

    winner = random.choice(
        room.players
    )

    result = random.choice(
        [
            "شیر 🦁",
            "خط 🪙"
        ]
    )

    await update.message.reply_text(

        f"🪙 **شیر یا خط**\n\n"
        f"نتیجه: **{result}**\n\n"
        f"🏆 برنده: "
        f"**{room.names[winner]}**"
    )

    return winner


# ============================================================
# GAME 3 - NUMBER
# ============================================================

async def play_number(
    room,
    update
):

    target = random.randint(
        1,
        100
    )

    distances = []

    for user_id in room.players:

        guess = random.randint(
            1,
            100
        )

        distance = abs(
            target - guess
        )

        distances.append(
            (
                user_id,
                guess,
                distance
            )
        )

    distances.sort(
        key=lambda x: x[2]
    )

    winner = distances[0][0]

    text = (
        "🔢 **حدس عدد**\n\n"
        f"عدد مخفی: **{target}**\n\n"
    )

    for user_id, guess, distance in distances:

        text += (
            f"👤 {room.names[user_id]}: "
            f"{guess}\n"
        )

    text += (
        f"\n🏆 برنده: "
        f"**{room.names[winner]}**"
    )

    await update.message.reply_text(
        text
    )

    return winner


# ============================================================
# GAME 4 - WAR
# ============================================================

async def play_war(
    room,
    update
):

    scores = []

    for user_id in room.players:

        power = random.randint(
            1,
            100
        )

        donkey = get_donkey(
            user_id
        )

        if donkey:

            power += (
                donkey["strength"] // 5
            )

        scores.append(
            (
                user_id,
                power
            )
        )

    scores.sort(
        key=lambda x: x[1],
        reverse=True
    )

    winner = scores[0][0]

    text = "⚔️ **جنگ خرها**\n\n"

    for user_id, power in scores:

        text += (
            f"🫏 {room.names[user_id]}: "
            f"{power} قدرت\n"
        )

    text += (
        f"\n🏆 برنده: "
        f"**{room.names[winner]}**"
    )

    await update.message.reply_text(
        text
    )

    return winner


# ============================================================
# GAME 5 - RACE
# ============================================================

async def play_race(
    room,
    update
):

    scores = []

    for user_id in room.players:

        donkey = get_donkey(
            user_id
        )

        speed = random.randint(
            1,
            100
        )

        if donkey:

            speed += (
                donkey["speed"] // 2
            )

        scores.append(
            (
                user_id,
                speed
            )
        )

    scores.sort(
        key=lambda x: x[1],
        reverse=True
    )

    winner = scores[0][0]

    text = "🏇 **مسابقه خرها**\n\n"

    for user_id, speed in scores:

        text += (
            f"🫏 {room.names[user_id]}: "
            f"{speed}\n"
        )

    text += (
        f"\n🥇 برنده: "
        f"**{room.names[winner]}**"
    )

    await update.message.reply_text(
        text
    )

    return winner


# ============================================================
# GAME 6 - BOMB
# ============================================================

async def play_bomb(
    room,
    update
):

    safe = list(
        room.players
    )

    eliminated = []

    while len(safe) > 1:

        loser = random.choice(
            safe
        )

        safe.remove(
            loser
        )

        eliminated.append(
            loser
        )

    winner = safe[0]

    text = "💣 **بمب منفجر شد!**\n\n"

    for user_id in eliminated:

        text += (
            f"💥 {room.names[user_id]} حذف شد.\n"
        )

    text += (
        f"\n🏆 آخرین نفر: "
        f"**{room.names[winner]}**"
    )

    await update.message.reply_text(
        text
    )

    return winner


# ============================================================
# GAME 7 - THIEF
# ============================================================

async def play_thief(
    room,
    update
):

    thief = random.choice(
        room.players
    )

    police = random.choice(
        [
            x for x in room.players
            if x != thief
        ]
    )

    caught = random.random() < 0.55

    if caught:

        winner = police

        result = (
            f"🚓 پلیس **{room.names[police]}** "
            f"دزد را گرفت!"
        )

    else:

        winner = thief

        result = (
            f"🥷 دزد **{room.names[thief]}** "
            f"فرار کرد!"
        )

    await update.message.reply_text(

        "🥷 **دزد و پلیس**\n\n"
        + result
        +
        f"\n\n🏆 برنده: "
        f"**{room.names[winner]}**"
    )

    return winner


# ============================================================
# GAME 8 - TREASURE
# ============================================================

async def play_treasure(
    room,
    update
):

    winner = random.choice(
        room.players
    )

    reward = random.randint(
        100,
        500
    )

    add_coins(
        winner,
        reward
    )

    await update.message.reply_text(

        "💎 **گنج پیدا شد!**\n\n"

        f"👤 پیدا کننده:\n"
        f"**{room.names[winner]}**\n\n"

        f"💰 جایزه: "
        f"**{reward:,} 🪙**"
    )

    return winner


# ============================================================
# GAME 9 - CHALLENGE
# ============================================================

CHALLENGES = [

    "عدد 7 را حدس بزن!",

    "چه کسی شانس بیشتری دارد؟",

    "خر کی سریع‌تر است؟",

    "چه کسی امروز برنده می‌شود؟",

    "عرعر کن یا بباز!."

]


async def play_challenge(
    room,
    update
):

    challenge = random.choice(
        CHALLENGES
    )

    winner = random.choice(
        room.players
    )

    await update.message.reply_text(

        "🧠 **چالش**\n\n"

        f"❓ {challenge}\n\n"

        f"🏆 برنده:\n"
        f"**{room.names[winner]}**"
    )

    return winner


# ============================================================
# GAME 10 - DONKEY SOUND
# ============================================================

async def play_sound(
    room,
    update
):

    scores = []

    for user_id in room.players:

        donkey = get_donkey(
            user_id
        )

        sound_level = (

            donkey["sounds"]
            if donkey
            else 1

        )

        score = (

            random.randint(
                1,
                100
            )
            +
            sound_level * 10
        )

        scores.append(
            (
                user_id,
                score
            )
        )

    scores.sort(
        key=lambda x: x[1],
        reverse=True
    )

    winner = scores[0][0]

    text = (
        "🫏 **مسابقه عرعر**\n\n"
    )

    for user_id, score in scores:

        text += (
            f"{room.names[user_id]}: "
            f"عــــرررر 🫏 "
            f"{score}\n"
        )

    text += (
        f"\n🏆 سلطان عرعر:\n"
        f"**{room.names[winner]}**"
    )

    await update.message.reply_text(
        text
    )

    return winner


# ============================================================
# GAME DISPATCHER
# ============================================================

async def run_game(
    room,
    update
):

    room.started = True

    game_functions = {

        "تاس": play_dice,

        "سکه": play_coin,

        "حدس": play_number,

        "جنگ": play_war,

        "ریس": play_race,

        "بمب": play_bomb,

        "دزد": play_thief,

        "گنج": play_treasure,

        "چالش": play_challenge,

        "عرعر": play_sound

    }

    function = game_functions.get(
        room.game_type
    )

    if not function:

        return None

    winner = await function(
        room,
        update
    )

    # ثبت نتیجه
    for user_id in room.players:

        if user_id == winner:

            record_game_win(
                user_id
            )

            add_xp(
                user_id,
                25
            )

        else:

            record_game_loss(
                user_id
            )

            add_xp(
                user_id,
                10
            )

    # جایزه شرطی
    if room.bet > 0:

        prize = (
            room.bet
            *
            len(room.players)
        )

        add_coins(
            winner,
            prize
        )

    finish_room(
        room
    )

    return winner


# ============================================================
# BOT VS PLAYER
# ============================================================

async def bot_game(
    update,
    game_type,
    user_id,
    name
):

    room = create_room(

        game_type=game_type,

        chat_id=update.effective_chat.id,

        creator_id=user_id,

        name=name,

        bet=0

    )

    bot_id = -random.randint(
        100000,
        999999
    )

    room.players.append(
        bot_id
    )

    room.names[
        bot_id
    ] = "🤖 خرِ بات"

    await update.message.reply_text(
        "🤖 خر بات وارد بازی شد!\n\n"
        "🎮 بازی شروع می‌شود..."
    )

    await asyncio.sleep(
        1
    )

    return await run_game(
        room,
        update
    )


# ============================================================
# GROUP GAME COMMAND
# ============================================================

async def group_game_handler(
    update,
    context
):

    if not update.message:

        return False

    text = (
        update.message.text
        or ""
    ).strip()

    if not text:

        return False

    parts = text.split()

    command = parts[0].lower()

    aliases = {

        "تاس": "تاس",

        "dice": "تاس",

        "سکه": "سکه",

        "coin": "سکه",

        "حدس": "حدس",

        "جنگ": "جنگ",

        "ریس": "ریس",

        "مسابقه": "ریس",

        "بمب": "بمب",

        "دزد": "دزد",

        "گنج": "گنج",

        "چالش": "چالش",

        "عرعر": "عرعر"

    }

    game_type = aliases.get(
        command
    )

    if not game_type:

        return False

    user = update.effective_user

    ensure_user(
        user.id,
        user.full_name
    )

    # اگر بازی فعال است
    for room in ACTIVE_GAMES.values():

        if (
            room.chat_id
            ==
            update.effective_chat.id
        ):

            await update.message.reply_text(
                "❌ در این گروه یک بازی در حال اجراست."
            )

            return True

    # بازی مقابل بات
    if len(parts) > 1:

        mode = parts[1].lower()

        if mode in (
            "بات",
            "bot",
            "ai"
        ):

            await bot_game(

                update,

                game_type,

                user.id,

                user.full_name

            )

            return True

    room = create_room(

        game_type,

        update.effective_chat.id,

        user.id,

        user.full_name

    )

    await update.message.reply_text(

        room_text(room),

        reply_markup=room_keyboard(room)

    )

    return True


# ============================================================
# CALLBACK HANDLER
# ============================================================

async def final_game_callback(
    update,
    context
):

    query = update.callback_query

    data = query.data

    user = query.from_user


    # --------------------------------------------------------
    # GAME SELECT
    # --------------------------------------------------------

    if data.startswith(
        "game_"
    ):

        game_type = data.replace(
            "game_",
            "",
            1
        )

        if game_type not in GAMES:

            await query.answer(
                "❌ بازی نامعتبر.",
                show_alert=True
            )

            return True

        room = create_room(

            game_type,

            query.message.chat.id,

            user.id,

            user.full_name

        )

        await query.answer(
            "🎮 بازی ساخته شد!"
        )

        await query.edit_message_text(

            room_text(room),

            reply_markup=room_keyboard(room)

        )

        return True


    # --------------------------------------------------------
    # JOIN
    # --------------------------------------------------------

    if data.startswith(
        "join_"
    ):

        game_id = data.replace(
            "join_",
            "",
            1
        )

        room = ACTIVE_GAMES.get(
            game_id
        )

        if not room:

            await query.answer(
                "❌ بازی پیدا نشد.",
                show_alert=True
            )

            return True

        ok, message = join_room(

            room,

            user.id,

            user.full_name

        )

        await query.answer(
            message,
            show_alert=not ok
        )

        if ok:

            await query.edit_message_text(

                room_text(room),

                reply_markup=room_keyboard(room)

            )

        return True


    # --------------------------------------------------------
    # CANCEL
    # --------------------------------------------------------

    if data.startswith(
        "cancel_"
    ):

        game_id = data.replace(
            "cancel_",
            "",
            1
        )

        room = ACTIVE_GAMES.get(
            game_id
        )

        if not room:

            await query.answer(
                "❌ بازی وجود ندارد.",
                show_alert=True
            )

            return True

        if user.id != room.creator_id:

            await query.answer(
                "❌ فقط سازنده می‌تواند لغو کند.",
                show_alert=True
            )

            return True

        cancel_room(
            room
        )

        await query.answer(
            "❌ بازی لغو شد."
        )

        await query.edit_message_text(

            "❌ **بازی لغو شد.**\n\n"
            "💰 ورودی بازیکنان برگشت داده شد."
        )

        return True


    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    if data.startswith(
        "start_"
    ):

        game_id = data.replace(
            "start_",
            "",
            1
        )

        room = ACTIVE_GAMES.get(
            game_id
        )

        if not room:

            await query.answer(
                "❌ بازی پیدا نشد.",
                show_alert=True
            )

            return True

        if user.id != room.creator_id:

            await query.answer(
                "❌ فقط سازنده می‌تواند بازی را شروع کند.",
                show_alert=True
            )

            return True

        if len(room.players) < MIN_PLAYERS:

            await query.answer(
                "❌ حداقل دو بازیکن لازم است.",
                show_alert=True
            )

            return True

        await query.answer(
            "🎮 بازی شروع شد!"
        )

        await query.edit_message_text(
            "🎮 **بازی شروع شد!**\n\n"
            "🫏 آماده باشید..."
        )

        await asyncio.sleep(
            1
        )

        await run_game(
            room,
            update
        )

        return True

    return False


# ============================================================
# MAIN MENU
# ============================================================

def main_menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🫏 خر من",
                callback_data="menu_donkey"
            ),

            InlineKeyboardButton(
                "🎮 بازی‌ها",
                callback_data="menu_games"
            )
        ],

        [
            InlineKeyboardButton(
                "🛒 فروشگاه",
                callback_data="menu_shop"
            ),

            InlineKeyboardButton(
                "🏆 لیدربرد",
                callback_data="menu_top"
            )
        ],

        [
            InlineKeyboardButton(
                "👤 پروفایل",
                callback_data="menu_profile"
            ),

            InlineKeyboardButton(
                "🎁 روزانه",
                callback_data="menu_daily"
            )
        ]

    ])


# ============================================================
# START COMMAND / WORD
# ============================================================

async def start_handler(
    update,
    context
):

    user = update.effective_user

    ensure_user(
        user.id,
        user.full_name
    )

    await update.message.reply_text(

        "🫏 **به KHARBOT خوش اومدی!**\n"
        "━━━━━━━━━━━━━━\n\n"

        "یک خر اختصاصی داری.\n"
        "بزرگش کن، غذا بده، حمومش کن، "
        "ارتقاش بده و با بقیه بازی کن! 😈\n\n"

        "🎮 برای بازی فقط اسم بازی رو بفرست.\n"
        "مثلاً:\n"
        "🎲 تاس\n"
        "⚔️ جنگ\n"
        "🫏 عرعر\n\n"

        "🤖 برای بازی با بات:\n"
        "`تاس بات`",

        reply_markup=main_menu()

    )


# ============================================================
# SIMPLE TEXT ROUTER
# ============================================================

async def final_text_router(
    update,
    context
):

    if not update.message:

        return

    # اول بازی‌ها
    handled = await group_game_handler(
        update,
        context
    )

    if handled:

        return

    # بعد خر
    handled = await donkey_text_handler(
        update,
        context
    )

    if handled:

        return

    # بعد اقتصاد
    handled = await economy_text_handler(
        update,
        context
    )

    if handled:

        return


# ============================================================
# MENU CALLBACK
# ============================================================

async def menu_callback(
    update,
    context
):

    query = update.callback_query

    data = query.data

    user = query.from_user

    if data == "menu_games":

        await query.answer()

        await query.edit_message_text(

            "🎮 **لیست بازی‌ها**\n\n"
            "یکی را انتخاب کن:",

            reply_markup=game_menu()

        )

        return True


    if data == "menu_donkey":

        await query.answer()

        await query.edit_message_text(

            donkey_profile_text(
                user.id
            ),

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🍖 غذا",
                        callback_data="donkey_food"
                    ),

                    InlineKeyboardButton(
                        "💧 آب",
                        callback_data="donkey_water"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "🧼 حموم",
                        callback_data="donkey_shower"
                    ),

                    InlineKeyboardButton(
                        "⚡ استراحت",
                        callback_data="donkey_rest"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "🫏 عرعر",
                        callback_data="donkey_sound"
                    )
                ]

            ])

        )

        return True


    if data == "menu_top":

        await query.answer()

        await query.edit_message_text(

            leaderboard_text()

        )

        return True


    if data == "menu_profile":

        await query.answer()

        await query.edit_message_text(

            stats_text(
                user.id,
                user.full_name
            )

        )

        return True


    if data == "menu_daily":

        await query.answer()

        success, message = claim_daily(
            user.id
        )

        await query.edit_message_text(
            message
        )

        return True


    # ========================================================
    # DONKEY ACTION BUTTONS
    # ========================================================

    actions = {

        "donkey_food": "food",

        "donkey_water": "water",

        "donkey_shower": "shower",

        "donkey_rest": "rest",

        "donkey_play": "play"

    }

    if data in actions:

        action = actions[data]

        ok, message = donkey_action(

            user.id,

            action

        )

        await query.answer(
            message,
            show_alert=True
        )

        await query.edit_message_text(

            donkey_profile_text(
                user.id
            )

        )

        return True


    if data == "donkey_sound":

        await query.answer(

            donkey_sound(
                user.id
            ),

            show_alert=True

        )

        return True


    return False


# ============================================================
# CALLBACK MASTER
# ============================================================

async def master_callback(
    update,
    context
):

    data = update.callback_query.data

    if data.startswith(
        "menu_"
    ):

        if await menu_callback(
            update,
            context
        ):

            return

    if data.startswith(
        "donkey_"
    ):

        if await menu_callback(
            update,
            context
        ):

            return

    if (
        data.startswith("game_")
        or
        data.startswith("join_")
        or
        data.startswith("start_")
        or
        data.startswith("cancel_")
    ):

        if await final_game_callback(
            update,
            context
        ):

            return

    if data.startswith(
        "bet_"
    ):

        if await economy_callback_handler(
            update,
            context
        ):

            return


# ============================================================
# REGISTER HANDLERS
# ============================================================

def register_kharbot_handlers(
    application
):

    application.add_handler(

        CommandHandler(
            "start",
            start_handler
        )

    )

    application.add_handler(

        CallbackQueryHandler(
            master_callback
        )

    )

    application.add_handler(

        MessageHandler(
            filters.TEXT
            &
            ~filters.COMMAND,
            final_text_router
        )

    )


# ============================================================
# CLEAN OLD GAMES
# ============================================================

async def game_cleanup_loop():

    while True:

        try:

            now = time.time()

            expired = []

            for game_id, room in list(
                ACTIVE_GAMES.items()
            ):

                if (
                    now
                    -
                    room.created_at
                    >
                    GAME_TIMEOUT
                ):

                    expired.append(
                        room
                    )

            for room in expired:

                cancel_room(
                    room
                )

        except Exception as error:

            print(
                "GAME CLEANUP ERROR:",
                repr(error)
            )

        await asyncio.sleep(
            30
        )


# ============================================================
# END
# ============================================================
