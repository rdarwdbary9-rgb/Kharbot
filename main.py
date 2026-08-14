import os
import sqlite3
import random
import time
import logging
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from openai import AsyncOpenAI


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

ARR_SCORE = 10
ARR_COOLDOWN = 30
DAILY_SCORE = 100


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("Kharbot")


# =========================================================
# DATABASE
# =========================================================
# IMPORTANT:
# Belmo /app is read-only.
# Therefore we use /tmp for now.

DB_PATH = "/tmp/kharbot.db"

db = sqlite3.connect(
    DB_PATH,
    check_same_thread=False
)

cursor = db.cursor()


def init_database():
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            score INTEGER DEFAULT 0,
            last_daily INTEGER DEFAULT 0,
            title TEXT DEFAULT '',
            q_arr_count INTEGER DEFAULT 0,
            q_game_count INTEGER DEFAULT 0,
            q_ai_count INTEGER DEFAULT 0,
            q_last_reset TEXT DEFAULT ''
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            item_id TEXT NOT NULL,
            item_name TEXT NOT NULL,
            quantity INTEGER DEFAULT 1,
            UNIQUE(user_id, item_id)
        )
    """)

    db.commit()


init_database()


# =========================================================
# AI
# =========================================================

ai_client = None

if GROQ_API_KEY:
    ai_client = AsyncOpenAI(
        api_key=GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1"
    )


SYSTEM_INSTRUCTION = """
تو «خر‌بات» هستی؛ یک ربات فارسی بامزه، شیطون، شوخ‌طبع و صمیمی.
با کاربرها دوستانه و باکل‌کل حرف بزن.
جواب‌ها طبیعی و کوتاه باشند.
اگر کاربر ازت سوال جدی پرسید، جواب مفید بده.
"""


async def ask_ai(prompt: str) -> str:

    if not ai_client:
        return "🫏 کلید GROQ_API_KEY تنظیم نشده!"

    try:
        response = await ai_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_INSTRUCTION
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.8,
            max_tokens=500,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.error("AI ERROR: %s", e)
        return "🫏 مغزم هنگ کرد 😂 دوباره امتحان کن."


# =========================================================
# USER FUNCTIONS
# =========================================================

def create_user(user):

    today = datetime.now().strftime("%Y-%m-%d")

    cursor.execute(
        "SELECT q_last_reset FROM users WHERE user_id = ?",
        (user.id,)
    )

    row = cursor.fetchone()

    if row is None:

        cursor.execute("""
            INSERT INTO users
            (
                user_id,
                username,
                first_name,
                q_last_reset
            )
            VALUES (?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "Player",
            today
        ))

    else:

        if row[0] != today:

            cursor.execute("""
                UPDATE users
                SET
                    q_arr_count = 0,
                    q_game_count = 0,
                    q_ai_count = 0,
                    q_last_reset = ?
                WHERE user_id = ?
            """, (
                today,
                user.id
            ))

    db.commit()


def get_score(user_id):

    cursor.execute(
        "SELECT score FROM users WHERE user_id = ?",
        (user_id,)
    )

    row = cursor.fetchone()

    return row[0] if row else 0


def add_score(user_id, amount):

    cursor.execute("""
        UPDATE users
        SET score = score + ?
        WHERE user_id = ?
    """, (
        amount,
        user_id
    ))

    db.commit()


def remove_score(user_id, amount):

    cursor.execute("""
        UPDATE users
        SET score = MAX(0, score - ?)
        WHERE user_id = ?
    """, (
        amount,
        user_id
    ))

    db.commit()


def update_quest(user_id, quest):

    column = {
        "arr": "q_arr_count",
        "game": "q_game_count",
        "ai": "q_ai_count"
    }.get(quest)

    if not column:
        return

    cursor.execute(
        f"UPDATE users SET {column} = {column} + 1 WHERE user_id = ?",
        (user_id,)
    )

    db.commit()


# =========================================================
# MAIN MENU
# =========================================================

def main_menu(user_id):

    keyboard = [
        [
            InlineKeyboardButton(
                "👤 پروفایل",
                callback_data="profile"
            ),
            InlineKeyboardButton(
                "💰 موجودی",
                callback_data="balance"
            )
        ],
        [
            InlineKeyboardButton(
                "🎮 بازی‌ها",
                callback_data="games"
            ),
            InlineKeyboardButton(
                "🛍️ فروشگاه",
                callback_data="store"
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 ماموریت‌ها",
                callback_data="quests"
            ),
            InlineKeyboardButton(
                "🎒 انبار",
                callback_data="inventory"
            )
        ],
        [
            InlineKeyboardButton(
                "🎁 جایزه روزانه",
                callback_data="daily"
            ),
            InlineKeyboardButton(
                "📖 راهنما",
                callback_data="help"
            )
        ]
    ]

    if user_id == ADMIN_ID and ADMIN_ID != 0:

        keyboard.append([
            InlineKeyboardButton(
                "👑 پنل مالک",
                callback_data="admin"
            )
        ])

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user:
        return

    create_user(user)

    await update.message.reply_text(
        "🫏 **خر‌بات**\n\n"
        "به قلمرو خرها خوش اومدی 😂\n\n"
        "برای شروع یکی از گزینه‌های زیر رو انتخاب کن:",
        reply_markup=main_menu(user.id),
        parse_mode="Markdown"
    )


# =========================================================
# PROFILE
# =========================================================

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user:
        return

    create_user(user)

    cursor.execute(
        "SELECT title FROM users WHERE user_id = ?",
        (user.id,)
    )

    row = cursor.fetchone()

    title = row[0] if row and row[0] else "🫏 خر معمولی"

    if user.id == ADMIN_ID:
        title = "👑 مالک خر‌بات"

    text = (
        "👤 **پروفایل**\n"
        "━━━━━━━━━━━━\n"
        f"📝 نام: {user.first_name}\n"
        f"🆔 آیدی: `{user.id}`\n"
        f"🏷️ لقب: {title}\n"
        f"💰 موجودی: **{get_score(user.id)}** 🫏"
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_menu(user.id),
            parse_mode="Markdown"
        )

    else:

        await update.message.reply_text(
            text,
            reply_markup=main_menu(user.id),
            parse_mode="Markdown"
        )


# =========================================================
# DAILY
# =========================================================

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user:
        return

    create_user(user)

    now = int(time.time())

    cursor.execute(
        "SELECT last_daily FROM users WHERE user_id = ?",
        (user.id,)
    )

    last = cursor.fetchone()[0]

    if now - last < 86400:

        remaining = 86400 - (now - last)
        hours = remaining // 3600

        text = (
            f"⏳ جایزه روزانه رو قبلاً گرفتی!\n"
            f"حدود **{hours} ساعت** دیگه برگرد."
        )

    else:

        cursor.execute(
            "UPDATE users SET last_daily = ? WHERE user_id = ?",
            (now, user.id)
        )

        db.commit()

        add_score(user.id, DAILY_SCORE)

        text = (
            "🎁 **جایزه روزانه دریافت شد!**\n\n"
            f"+{DAILY_SCORE} 🫏 پوینت"
        )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_menu(user.id),
            parse_mode="Markdown"
        )

    else:

        await update.message.reply_text(
            text,
            parse_mode="Markdown"
        )


# =========================================================
# QUESTS
# =========================================================

async def show_quests(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user:
        return

    create_user(user)

    cursor.execute("""
        SELECT
            q_arr_count,
            q_game_count,
            q_ai_count
        FROM users
        WHERE user_id = ?
    """, (user.id,))

    arr_count, game_count, ai_count = cursor.fetchone()

    text = (
        "🎯 **ماموریت‌های امروز**\n"
        "━━━━━━━━━━━━\n\n"
        f"🫏 ۳ بار «عر» بگو: "
        f"**{min(arr_count, 3)}/3**\n\n"
        f"🎮 دو بازی انجام بده: "
        f"**{min(game_count, 2)}/2**\n\n"
        f"🤖 سه بار AI استفاده کن: "
        f"**{min(ai_count, 3)}/3**"
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_menu(user.id),
            parse_mode="Markdown"
        )

    else:

        await update.message.reply_text(
            text,
            parse_mode="Markdown"
        )


# =========================================================
# INVENTORY
# =========================================================

async def show_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user:
        return

    create_user(user)

    cursor.execute("""
        SELECT item_name, quantity
        FROM inventory
        WHERE user_id = ?
    """, (user.id,))

    items = cursor.fetchall()

    if not items:

        text = (
            "🎒 **انبار خالیه!**\n\n"
            "از فروشگاه آیتم بخر."
        )

    else:

        text = "🎒 **انبار شما**\n\n"

        for name, quantity in items:

            text += f"🔹 {name} × {quantity}\n"

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_menu(user.id),
            parse_mode="Markdown"
        )

    else:

        await update.message.reply_text(
            text,
            parse_mode="Markdown"
        )


# =========================================================
# STORE
# =========================================================

STORE_ITEMS = {

    "luck":
        {
            "name": "🎲 کارت شانس",
            "price": 300
        },

    "boost":
        {
            "name": "⚡ بوستر دوبرابر",
            "price": 800
        },

    "title_boss":
        {
            "name": "🔥 لقب خر بزرگ",
            "price": 1000
        },

    "title_king":
        {
            "name": "👑 سلطان طویله",
            "price": 2000
        },

    "title_legend":
        {
            "name": "🌟 اسطوره یونجه",
            "price": 5000
        }
}


async def show_store(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user:
        return

    create_user(user)

    keyboard = []

    for item_id, item in STORE_ITEMS.items():

        keyboard.append([
            InlineKeyboardButton(
                f"{item['name']} — {item['price']} 🫏",
                callback_data=f"buy:{item_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 منوی اصلی",
            callback_data="main"
        )
    ])

    text = (
        "🛍️ **فروشگاه خر‌بات**\n\n"
        f"💰 موجودی: **{get_score(user.id)}** 🫏"
    )

    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def buy_item(query, item_id):

    user = query.from_user

    item = STORE_ITEMS.get(item_id)

    if not item:
        return

    if get_score(user.id) < item["price"]:

        await query.answer(
            "❌ موجودی کافی نیست!",
            show_alert=True
        )

        return

    remove_score(
        user.id,
        item["price"]
    )

    if item_id.startswith("title_"):

        cursor.execute("""
            UPDATE users
            SET title = ?
            WHERE user_id = ?
        """, (
            item["name"],
            user.id
        ))

    else:

        cursor.execute("""
            INSERT INTO inventory
            (user_id, item_id, item_name, quantity)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id, item_id)
            DO UPDATE SET quantity = quantity + 1
        """, (
            user.id,
            item_id,
            item["name"]
        ))

    db.commit()

    await query.answer(
        "✅ خرید موفق بود!",
        show_alert=True
    )

    await query.edit_message_text(
        f"🎉 خرید انجام شد!\n\n"
        f"💰 موجودی جدید: **{get_score(user.id)}** 🫏",
        reply_markup=main_menu(user.id),
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN
# =========================================================

def is_admin(user_id):

    return ADMIN_ID != 0 and user_id == ADMIN_ID


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user or not is_admin(user.id):

        if update.callback_query:
            await update.callback_query.answer(
                "❌ دسترسی نداری!",
                show_alert=True
            )

        return

    cursor.execute(
        "SELECT COUNT(*) FROM users"
    )

    total_users = cursor.fetchone()[0]

    text = (
        "👑 **پنل مالک خر‌بات**\n"
        "━━━━━━━━━━━━\n\n"
        f"👥 کاربران: **{total_users}**\n\n"
        "🛠️ دستورات مالک:\n\n"
        "`/addcoin ID AMOUNT`\n"
        "`/removecoin ID AMOUNT`\n"
        "`/broadcast TEXT`"
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_menu(user.id),
            parse_mode="Markdown"
        )

    else:

        await update.message.reply_text(
            text,
            parse_mode="Markdown"
        )


async def add_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user or not is_admin(user.id):
        return

    try:

        target = int(context.args[0])
        amount = int(context.args[1])

        if amount <= 0:
            raise ValueError

        add_score(target, amount)

        await update.message.reply_text(
            f"✅ **{amount}** پوینت اضافه شد.",
            parse_mode="Markdown"
        )

    except Exception:

        await update.message.reply_text(
            "❌ فرمت:\n"
            "`/addcoin 123456789 500`",
            parse_mode="Markdown"
        )


async def remove_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user or not is_admin(user.id):
        return

    try:

        target = int(context.args[0])
        amount = int(context.args[1])

        if amount <= 0:
            raise ValueError

        remove_score(target, amount)

        await update.message.reply_text(
            f"✅ **{amount}** پوینت کم شد.",
            parse_mode="Markdown"
        )

    except Exception:

        await update.message.reply_text(
            "❌ فرمت:\n"
            "`/removecoin 123456789 500`",
            parse_mode="Markdown"
        )


# =========================================================
# GIVE COIN
# =========================================================

async def give_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user or not update.message.reply_to_message:
        return

    if not context.args:
        return

    try:

        amount = int(context.args[0])

        if amount <= 0:
            return

    except ValueError:

        return

    target = update.message.reply_to_message.from_user

    if target.id == user.id:

        await update.message.reply_text(
            "🤡 نمی‌تونی به خودت پوینت بدی!"
        )

        return

    create_user(target)

    if get_score(user.id) < amount:

        await update.message.reply_text(
            "❌ موجودی کافی نداری!"
        )

        return

    remove_score(user.id, amount)
    add_score(target.id, amount)

    await update.message.reply_text(
        f"🎁 **{amount}** پوینت به {target.first_name} داده شد.",
        parse_mode="Markdown"
    )


# =========================================================
# GAMES
# =========================================================

async def games_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    keyboard = [

        [
            InlineKeyboardButton(
                "💥 انفجار",
                callback_data="game:crash"
            )
        ],

        [
            InlineKeyboardButton(
                "🪨📄✂️ سنگ کاغذ قیچی",
                callback_data="game:rps"
            )
        ],

        [
            InlineKeyboardButton(
                "❌⭕ دوز",
                callback_data="game:ttt"
            )
        ],

        [
            InlineKeyboardButton(
                "🎲 تاس",
                callback_data="game:dice"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="main"
            )
        ]
    ]

    await update.callback_query.edit_message_text(
        "🎮 **بازی‌های خر‌بات**\n\n"
        "یک بازی رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# =========================================================
# DICE GAME
# =========================================================

async def dice_game(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user:
        return

    create_user(user)

    bet = 10

    if get_score(user.id) < bet:

        await update.message.reply_text(
            "❌ حداقل ۱۰ پوینت لازم داری!"
        )

        return

    remove_score(user.id, bet)

    user_roll = random.randint(1, 6)
    bot_roll = random.randint(1, 6)

    if user_roll > bot_roll:

        add_score(user.id, bet * 2)

        result = f"🎉 بردی! +{bet} پوینت"

    elif user_roll < bot_roll:

        result = f"💀 باختی! -{bet} پوینت"

    else:

        add_score(user.id, bet)

        result = "🤝 مساوی! شرطت برگشت."

    update_quest(user.id, "game")

    await update.message.reply_text(
        f"🎲 **تاس**\n\n"
        f"👤 تو: `{user_roll}`\n"
        f"🤖 خر‌بات: `{bot_roll}`\n\n"
        f"{result}\n"
        f"💰 موجودی: **{get_score(user.id)}**",
        parse_mode="Markdown"
    )


# =========================================================
# MESSAGE HANDLER
# =========================================================

ARR_WORDS = {
    "عر",
    "عرعر",
    "عر عر",
    "عرر",
    "عررر"
}

last_arr = {}


def can_arr(user_id):

    now = time.time()

    last = last_arr.get(user_id, 0)

    if now - last < ARR_COOLDOWN:
        return False

    last_arr[user_id] = now

    return True


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    user = update.effective_user

    if not user:
        return

    create_user(user)

    text = update.message.text

    if not text:
        return

    clean = text.strip().lower()

    # -----------------------------
    # ARR
    # -----------------------------

    if clean in ARR_WORDS:

        if not can_arr(user.id):

            await update.message.reply_text(
                "⏳ یکم صبر کن بعد دوباره عر بزن 😂"
            )

            return

        add_score(
            user.id,
            ARR_SCORE
        )

        update_quest(
            user.id,
            "arr"
        )

        await update.message.reply_text(
            f"🫏 عررررر!\n"
            f"+{ARR_SCORE} 🫏 پوینت"
        )

        return

    # -----------------------------
    # TOROKALI
    # -----------------------------

    if clean == "تورکعلی":

        await update.message.reply_text(
            "🫏 تورکعلی!"
        )

        return

    # -----------------------------
    # GIVE
    # -----------------------------

    parts = clean.split()

    if (
        len(parts) >= 2
        and parts[0] == "بده"
        and parts[1].isdigit()
        and update.message.reply_to_message
    ):

        context.args = [parts[1]]

        await give_coin(
            update,
            context
        )

        return

    # -----------------------------
    # SHOP
    # -----------------------------

    if clean in {
        "فروشگاه",
        "خرید"
    }:

        await update.message.reply_text(
            "🛍️ برای فروشگاه از `/store` استفاده کن.",
            parse_mode="Markdown"
        )

        return

    # -----------------------------
    # PROFILE
    # -----------------------------

    if clean in {
        "پروفایل",
        "امتیاز",
        "موجودی"
    }:

        await show_profile(
            update,
            context
        )

        return

    # -----------------------------
    # QUEST
    # -----------------------------

    if clean in {
        "ماموریت",
        "ماموریت ها"
    }:

        await show_quests(
            update,
            context
        )

        return

    # -----------------------------
    # AI
    # -----------------------------

    if clean == "خر" or clean.startswith("خر "):

        prompt = (
            "سلام خر!"
            if clean == "خر"
            else text[3:].strip()
        )

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing"
        )

        answer = await ask_ai(prompt)

        update_quest(
            user.id,
            "ai"
        )

        await update.message.reply_text(
            answer
        )

        return


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    create_user(user)

    data = query.data

    # -----------------------------
    # MAIN
    # -----------------------------

    if data == "main":

        await query.edit_message_text(
            "🫏 **خر‌بات**\n\n"
            "به قلمرو خرها خوش اومدی 😂",
            reply_markup=main_menu(user.id),
            parse_mode="Markdown"
        )

        return

    # -----------------------------
    # PROFILE
    # -----------------------------

    if data == "profile":

        await show_profile(
            update,
            context
        )

        return

    # -----------------------------
    # BALANCE
    # -----------------------------

    if data == "balance":

        await query.edit_message_text(
            f"💰 موجودی شما:\n\n"
            f"**{get_score(user.id)}** 🫏 پوینت",
            reply_markup=main_menu(user.id),
            parse_mode="Markdown"
        )

        return

    # -----------------------------
    # GAMES
    # -----------------------------

    if data == "games":

        await games_menu(
            update,
            context
        )

        return

    # -----------------------------
    # STORE
    # -----------------------------

    if data == "store":

        await show_store(
            update,
            context
        )

        return

    # -----------------------------
    # QUESTS
    # -----------------------------

    if data == "quests":

        await show_quests(
            update,
            context
        )

        return

    # -----------------------------
    # INVENTORY
    # -----------------------------

    if data == "inventory":

        await show_inventory(
            update,
            context
        )

        return

    # -----------------------------
    # DAILY
    # -----------------------------

    if data == "daily":

        await daily(
            update,
            context
        )

        return

    # -----------------------------
    # HELP
    # -----------------------------

    if data == "help":

        await query.edit_message_text(
            "📖 **راهنما**\n\n"
            "🫏 `عر` → دریافت پوینت\n"
            "🤖 `خر سوالت` → چت با AI\n"
            "💰 `/daily` → جایزه روزانه\n"
            "🎒 `/inventory` → انبار\n"
            "🛍️ `/store` → فروشگاه\n"
            "👑 `/admin` → پنل مالک",
            reply_markup=main_menu(user.id),
            parse_mode="Markdown"
        )

        return

    # -----------------------------
    # ADMIN
    # -----------------------------

    if data == "admin":

        await admin_panel(
            update,
            context
        )

        return

    # -----------------------------
    # BUY
    # -----------------------------

    if data.startswith("buy:"):

        item_id = data.split(":", 1)[1]

        await buy_item(
            query,
            item_id
        )

        return

    # -----------------------------
    # DICE
    # -----------------------------

    if data == "game:dice":

        await query.edit_message_text(
            "🎲 برای بازی تاس در چت بنویس:\n\n"
            "`/dice`",
            reply_markup=main_menu(user.id),
            parse_mode="Markdown"
        )

        return

    # -----------------------------
    # OTHER GAMES
    # -----------------------------

    if data in {
        "game:crash",
        "game:rps",
        "game:ttt"
    }:

        await query.edit_message_text(
            "🚧 این بازی در حال آماده‌سازی نسخه جدید خر‌باته.",
            reply_markup=main_menu(user.id)
        )

        return


# =========================================================
# COMMANDS
# =========================================================

async def help_command(update, context):

    await update.message.reply_text(
        "📖 **راهنمای خر‌بات**\n\n"
        "🫏 `عر` → پوینت\n"
        "🤖 `خر سوال` → هوش مصنوعی\n"
        "💰 `/daily` → جایزه روزانه\n"
        "👤 `/profile` → پروفایل\n"
        "🛍️ `/store` → فروشگاه\n"
        "🎒 `/inventory` → انبار\n"
        "🎯 `/quests` → ماموریت‌ها\n"
        "🎲 `/dice` → بازی تاس\n"
        "🎁 ریپلای + `بده 50` → انتقال پوینت",
        parse_mode="Markdown"
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):

    logger.error(
        "BOT ERROR: %r",
        context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        print("❌ BOT_TOKEN is missing!")

        return

    print("================================")
    print("🫏 KHARBOT STARTING...")
    print(f"Database: {DB_PATH}")
    print("================================")

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    application.add_handler(
        CommandHandler(
            "profile",
            show_profile
        )
    )

    application.add_handler(
        CommandHandler(
            "daily",
            daily
        )
    )

    application.add_handler(
        CommandHandler(
            "quests",
            show_quests
        )
    )

    application.add_handler(
        CommandHandler(
            "inventory",
            show_inventory
        )
    )

    application.add_handler(
        CommandHandler(
            "store",
            show_store
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_panel
        )
    )

    application.add_handler(
        CommandHandler(
            "addcoin",
            add_coin
        )
    )

    application.add_handler(
        CommandHandler(
            "removecoin",
            remove_coin
        )
    )

    application.add_handler(
        CommandHandler(
            "dice",
            dice_game
        )
    )

    # Callbacks

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    # Messages

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler
        )
    )

    application.add_error_handler(
        error_handler
    )

    print("🫏 KHARBOT STARTED")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
