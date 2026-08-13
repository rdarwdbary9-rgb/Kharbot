import os
import sqlite3
import time
import random
import asyncio
from pathlib import Path
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

START_SCORE = 100
DAILY_SCORE = 100
ARR_SCORE = 10
ARR_COOLDOWN = 30


# =========================================================
# DATABASE
# =========================================================

import sqlite3

DB_PATH = "/tmp/kharbot.db"

db = sqlite3.connect(
    DB_PATH,
    check_same_thread=False
)

# =========================================================
# DATABASE HELPERS
# =========================================================

def db_commit():
    db.commit()


def create_user(user):
    today = datetime.now().strftime("%Y-%m-%d")

    cursor.execute(
        "SELECT user_id, q_last_reset FROM users WHERE user_id = ?",
        (user.id,)
    )

    row = cursor.fetchone()

    if row is None:
        cursor.execute("""
            INSERT INTO users (
                user_id,
                username,
                first_name,
                score,
                q_last_reset
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "Player",
            START_SCORE,
            today
        ))

    else:
        cursor.execute("""
            UPDATE users
            SET username = ?,
                first_name = ?
            WHERE user_id = ?
        """, (
            user.username or "",
            user.first_name or "Player",
            user.id
        ))

        if row["q_last_reset"] != today:
            cursor.execute("""
                UPDATE users
                SET q_arr_count = 0,
                    q_game_count = 0,
                    q_ai_count = 0,
                    q_last_reset = ?
                WHERE user_id = ?
            """, (today, user.id))

    db_commit()


def get_score(user_id):
    cursor.execute(
        "SELECT score FROM users WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    return int(row["score"]) if row else 0


def add_score(user_id, amount):
    cursor.execute(
        "UPDATE users SET score = score + ? WHERE user_id = ?",
        (amount, user_id)
    )
    db_commit()


def remove_score(user_id, amount):
    cursor.execute(
        "UPDATE users SET score = MAX(0, score - ?) WHERE user_id = ?",
        (amount, user_id)
    )
    db_commit()


def update_quest(user_id, quest_type):
    column = {
        "arr": "q_arr_count",
        "game": "q_game_count",
        "ai": "q_ai_count"
    }.get(quest_type)

    if not column:
        return

    cursor.execute(
        f"UPDATE users SET {column} = {column} + 1 WHERE user_id = ?",
        (user_id,)
    )

    db_commit()


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
تو «خر‌بات» هستی و شخصیتت «تورکعلی» است.

یک ربات فارسی‌زبان بامزه، شیطون، صمیمی و اهل کل‌کل هستی.
جواب‌ها کوتاه و سرگرم‌کننده باشند.
گاهی از ایموجی 🫏😂 استفاده کن.
بی‌جهت جواب‌های خیلی طولانی نده.
اگر کاربر گفت «تورکعلی»، خودت را تورکعلی معرفی کن.
"""


async def ask_ai(prompt):

    if not ai_client:
        return "🫏 تورکعلی: کلید GROQ_API_KEY هنوز تنظیم نشده 😂"

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
            temperature=0.9,
            max_tokens=500
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        print("AI ERROR:", e)
        return "🫏 تورکعلی هنگ کرد 😂 دوباره بپرس."


# =========================================================
# STORE
# =========================================================

STORE_ITEMS = {
    "title_boss": {
        "name": "🔥 لقب خرِ بزرگ",
        "price": 1000,
        "type": "title",
        "value": "🔥 خرِ بزرگ"
    },

    "title_king": {
        "name": "👑 سلطان طویله",
        "price": 2000,
        "type": "title",
        "value": "👑 سلطان طویله"
    },

    "title_legend": {
        "name": "🌟 اسطوره یونجه",
        "price": 5000,
        "type": "title",
        "value": "🌟 اسطوره یونجه"
    },

    "luck": {
        "name": "🎲 کارت شانس",
        "price": 300,
        "type": "item"
    },

    "boost": {
        "name": "⚡ کارت دوبرابر",
        "price": 800,
        "type": "item"
    }
}


def store_keyboard():

    keyboard = []

    for item_id, item in STORE_ITEMS.items():

        keyboard.append([
            InlineKeyboardButton(
                f"{item['name']} | {item['price']} 🫏",
                callback_data=f"buy:{item_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 منوی اصلی",
            callback_data="main"
        )
    ])

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# MAIN MENU
# =========================================================

def main_menu(user_id):

    keyboard = [
        [
            InlineKeyboardButton("👤 پروفایل", callback_data="profile"),
            InlineKeyboardButton("💰 موجودی", callback_data="balance")
        ],
        [
            InlineKeyboardButton("🎮 بازی‌ها", callback_data="games"),
            InlineKeyboardButton("🛍 فروشگاه", callback_data="store")
        ],
        [
            InlineKeyboardButton("🎯 مأموریت‌ها", callback_data="quests"),
            InlineKeyboardButton("🎒 انبار", callback_data="inventory")
        ],
        [
            InlineKeyboardButton("🎁 روزانه", callback_data="daily"),
            InlineKeyboardButton("🏆 رتبه‌بندی", callback_data="ranking")
        ],
        [
            InlineKeyboardButton("🤖 تورکعلی", callback_data="ai"),
            InlineKeyboardButton("📖 راهنما", callback_data="help")
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

    text = """
🫏 **به خر‌بات خوش اومدی!**

😂 اینجا قلمرو تورکعلیه!

💰 سکه جمع کن
🎮 بازی کن
🎯 مأموریت انجام بده
🛍 خرید کن
🏆 رتبه بگیر
🤖 با تورکعلی حرف بزن
"""

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu(user.id)
    )


# =========================================================
# PROFILE
# =========================================================

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user:
        return

    create_user(user)

    cursor.execute(
        "SELECT title, score FROM users WHERE user_id = ?",
        (user.id,)
    )

    row = cursor.fetchone()

    title = row["title"] if row and row["title"] else (
        "👑 مالک" if user.id == ADMIN_ID else "🫏 خر معمولی"
    )

    text = f"""
👤 **پروفایل**

━━━━━━━━━━━━━━

🏷 لقب: {title}
📝 نام: {user.first_name}
🆔 آیدی: `{user.id}`
💰 موجودی: **{get_score(user.id)}** 🫏
"""

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=main_menu(user.id)
        )

    else:

        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=main_menu(user.id)
        )


# =========================================================
# BALANCE
# =========================================================

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user:
        return

    create_user(user)

    text = f"""
💰 **موجودی شما**

🫏 {get_score(user.id)} پوینت
"""

    await update.callback_query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu(user.id)
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

    row = cursor.fetchone()

    last = row["last_daily"]

    if now - last < 86400:

        remaining = 86400 - (now - last)

        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        text = (
            f"⏳ جایزه روزانه رو گرفتی!\n\n"
            f"🕐 {hours} ساعت و {minutes} دقیقه دیگه برگرد."
        )

    else:

        cursor.execute(
            "UPDATE users SET last_daily = ? WHERE user_id = ?",
            (now, user.id)
        )

        db_commit()

        add_score(user.id, DAILY_SCORE)

        text = (
            f"🎁 **جایزه روزانه!**\n\n"
            f"➕ {DAILY_SCORE} 🫏 پوینت"
        )

    await update.callback_query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu(user.id)
    )


# =========================================================
# ARR
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


# =========================================================
# GAMES MENU
# =========================================================

async def games_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [
            InlineKeyboardButton(
                "🎯 حدس عدد",
                callback_data="game:guess"
            )
        ],
        [
            InlineKeyboardButton(
                "🪨 سنگ کاغذ قیچی",
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
                "🧠 سوال اطلاعات عمومی",
                callback_data="game:quiz"
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
        "🎮 **بازی‌های خر‌بات**\n\nیکی رو انتخاب کن:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# DICE
# =========================================================

async def dice_game(query):

    user = query.from_user

    bot_number = random.randint(1, 6)

    reward = bot_number * 10

    add_score(user.id, reward)

    update_quest(user.id, "game")

    await query.edit_message_text(
        f"""
🎲 **تاس انداختی!**

🎯 عدد: **{bot_number}**

🎁 جایزه:
+{reward} 🫏 پوینت
""",
        reply_markup=main_menu(user.id)
    )


# =========================================================
# GUESS GAME
# =========================================================

guess_games = {}


async def start_guess(query):

    user = query.from_user

    number = random.randint(1, 10)

    guess_games[user.id] = number

    keyboard = []

    for i in range(1, 11):

        keyboard.append(
            InlineKeyboardButton(
                str(i),
                callback_data=f"guess:{i}"
            )
        )

    rows = [
        keyboard[i:i + 5]
        for i in range(0, 10, 5)
    ]

    rows.append([
        InlineKeyboardButton(
            "🔙 بازی‌ها",
            callback_data="games"
        )
    ])

    await query.edit_message_text(
        "🎯 **حدس عدد**\n\n"
        "تورکعلی یک عدد بین ۱ تا ۱۰ انتخاب کرده.\n"
        "حدست رو بزن:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows)
    )


async def guess_answer(query, number):

    user = query.from_user

    target = guess_games.get(user.id)

    if target is None:
        await query.answer("این بازی تموم شده!", show_alert=True)
        return

    del guess_games[user.id]

    if number == target:

        add_score(user.id, 100)
        reward = "+100"

        text = f"""
🎉 **درست حدس زدی!**

عدد: **{target}**

🏆 {reward} 🫏 پوینت
"""

    else:

        text = f"""
😂 باختی!

عدد تورکعلی **{target}** بود.

دوباره شانست رو امتحان کن.
"""

    update_quest(user.id, "game")

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu(user.id)
    )


# =========================================================
# RPS
# =========================================================

RPS = {
    "stone": "🪨 سنگ",
    "paper": "📄 کاغذ",
    "scissors": "✂️ قیچی"
}


def rps_winner(a, b):

    if a == b:
        return "draw"

    if (
        (a == "stone" and b == "scissors") or
        (a == "paper" and b == "stone") or
        (a == "scissors" and b == "paper")
    ):
        return "user"

    return "bot"


async def start_rps(query):

    keyboard = [[
        InlineKeyboardButton(
            "🪨 سنگ",
            callback_data="rps:stone"
        ),
        InlineKeyboardButton(
            "📄 کاغذ",
            callback_data="rps:paper"
        ),
        InlineKeyboardButton(
            "✂️ قیچی",
            callback_data="rps:scissors"
        )
    ]]

    await query.edit_message_text(
        "🪨📄✂️ **سنگ کاغذ قیچی**\n\nانتخاب کن:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def rps_play(query, choice):

    user = query.from_user

    bot_choice = random.choice(list(RPS.keys()))

    result = rps_winner(choice, bot_choice)

    if result == "user":

        add_score(user.id, 50)

        text = "🎉 بردی!\n\n➕50 🫏 پوینت"

    elif result == "bot":

        remove_score(user.id, 20)

        text = "💀 تورکعلی برد!\n\n➖20 🫏 پوینت"

    else:

        text = "🤝 مساوی شد!"

    update_quest(user.id, "game")

    await query.edit_message_text(
        f"""
🪨📄✂️ **نتیجه**

👤 تو: {RPS[choice]}
🤖 تورکعلی: {RPS[bot_choice]}

{text}

💰 موجودی: {get_score(user.id)}
""",
        parse_mode="Markdown",
        reply_markup=main_menu(user.id)
    )


# =========================================================
# QUIZ
# =========================================================

QUIZZES = [
    ("پایتخت ایران کدام است؟", ["تهران", "شیراز", "تبریز", "کرمان"], 0),
    ("بزرگ‌ترین سیاره منظومه شمسی کدام است؟", ["زمین", "مریخ", "مشتری", "زهره"], 2),
    ("آب در چند درجه سانتی‌گراد می‌جوشد؟", ["50", "75", "100", "150"], 2),
    ("کدام حیوان به سلطان جنگل معروف است؟", ["خر", "شیر", "گربه", "گرگ"], 1),
    ("چند قاره در جهان وجود دارد؟", ["5", "6", "7", "8"], 2)
]

quiz_games = {}


async def start_quiz(query):

    user = query.from_user

    question = random.choice(QUIZZES)

    quiz_games[user.id] = question

    text, options, correct = question

    keyboard = []

    for i, option in enumerate(options):

        keyboard.append([
            InlineKeyboardButton(
                option,
                callback_data=f"quiz:{i}"
            )
        ])

    await query.edit_message_text(
        f"🧠 **سؤال تورکعلی**\n\n{text}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def quiz_answer(query, answer):

    user = query.from_user

    question = quiz_games.get(user.id)

    if not question:
        return

    del quiz_games[user.id]

    text, options, correct = question

    if answer == correct:

        add_score(user.id, 70)

        result = "🎉 درست گفتی!\n➕70 پوینت"

    else:

        result = (
            f"😂 اشتباه!\n"
            f"جواب درست: **{options[correct]}**"
        )

    update_quest(user.id, "game")

    await query.edit_message_text(
        result,
        parse_mode="Markdown",
        reply_markup=main_menu(user.id)
    )


# =========================================================
# TIC TAC TOE
# =========================================================

ttt_games = {}


def ttt_winner(board):

    lines = [
        (0, 1, 2),
        (3, 4, 5),
        (6, 7, 8),
        (0, 3, 6),
        (1, 4, 7),
        (2, 5, 8),
        (0, 4, 8),
        (2, 4, 6)
    ]

    for a, b, c in lines:

        if board[a] and board[a] == board[b] == board[c]:
            return board[a]

    if "" not in board:
        return "draw"

    return None


def ttt_keyboard(game_id, board):

    rows = []

    for start in range(0, 9, 3):

        row = []

        for i in range(start, start + 3):

            symbol = board[i] if board[i] else "▫️"

            row.append(
                InlineKeyboardButton(
                    symbol,
                    callback_data=f"ttt:{game_id}:{i}"
                )
            )

        rows.append(row)

    return InlineKeyboardMarkup(rows)


async def start_ttt(query):

    user = query.from_user

    game_id = f"{user.id}_{int(time.time())}"

    board = [""] * 9

    ttt_games[game_id] = {
        "user_id": user.id,
        "board": board
    }

    await query.edit_message_text(
        "❌⭕ **دوز با تورکعلی**\n\nنوبت توئه:",
        parse_mode="Markdown",
        reply_markup=ttt_keyboard(game_id, board)
    )


async def ttt_move(query, game_id, position):

    game = ttt_games.get(game_id)

    if not game:
        return

    user = query.from_user

    if user.id != game["user_id"]:
        await query.answer("این بازی مال تو نیست!", show_alert=True)
        return

    board = game["board"]

    if board[position]:

        await query.answer(
            "این خونه پره 😂",
            show_alert=True
        )

        return

    board[position] = "❌"

    winner = ttt_winner(board)

    if winner:
        await finish_ttt(query, game_id, winner)
        return

    empty = [
        i for i, value in enumerate(board)
        if not value
    ]

    if empty:

        # حرکت ساده و قابل پیش‌بینی نیست
        bot_move = random.choice(empty)

        board[bot_move] = "⭕"

    winner = ttt_winner(board)

    if winner:
        await finish_ttt(query, game_id, winner)
        return

    await query.edit_message_text(
        "❌⭕ **دوز با تورکعلی**\n\nنوبت توئه:",
        parse_mode="Markdown",
        reply_markup=ttt_keyboard(game_id, board)
    )


async def finish_ttt(query, game_id, winner):

    game = ttt_games.pop(game_id, None)

    if not game:
        return

    user_id = game["user_id"]

    if winner == "❌":

        add_score(user_id, 100)

        text = "🎉 بردی!\n➕100 پوینت"

    elif winner == "⭕":

        remove_score(user_id, 30)

        text = "😂 تورکعلی برد!\n➖30 پوینت"

    else:

        text = "🤝 مساوی شد!"

    update_quest(user_id, "game")

    await query.edit_message_text(
        f"🏁 **پایان بازی**\n\n{text}",
        parse_mode="Markdown",
        reply_markup=main_menu(user_id)
    )


# =========================================================
# QUESTS
# =========================================================

async def quests(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    create_user(user)

    cursor.execute("""
        SELECT q_arr_count,
               q_game_count,
               q_ai_count
        FROM users
        WHERE user_id = ?
    """, (user.id,))

    row = cursor.fetchone()

    arr = row["q_arr_count"]
    game = row["q_game_count"]
    ai = row["q_ai_count"]

    text = f"""
🎯 **ماموریت‌های امروز**

🫏 ۳ بار عر:
{arr}/3

🎮 ۲ بازی:
{game}/2

🤖 ۳ پیام به تورکعلی:
{ai}/3

━━━━━━━━━━━━

🎁 پاداش‌ها:
• عر ×3 → +50
• بازی ×2 → +100
• AI ×3 → +50
"""

    await update.callback_query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu(user.id)
    )


# =========================================================
# INVENTORY
# =========================================================

async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    create_user(user)

    cursor.execute("""
        SELECT item_name, quantity
        FROM inventory
        WHERE user_id = ?
        AND quantity > 0
    """, (user.id,))

    rows = cursor.fetchall()

    if not rows:

        text = "🎒 **انبار خالیه!**"

    else:

        text = "🎒 **انبار تو**\n\n"

        for row in rows:

            text += (
                f"🔹 {row['item_name']} "
                f"× {row['quantity']}\n"
            )

    await update.callback_query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu(user.id)
    )


# =========================================================
# STORE
# =========================================================

async def store(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    create_user(user)

    text = f"""
🛍 **فروشگاه تورکعلی**

💰 موجودی:
**{get_score(user.id)}** 🫏 پوینت

یکی رو انتخاب کن:
"""

    await update.callback_query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=store_keyboard()
    )


async def buy_item(query, item_id):

    user = query.from_user

    item = STORE_ITEMS.get(item_id)

    if not item:
        return

    price = item["price"]

    if get_score(user.id) < price:

        await query.answer(
            "❌ پوینت کافی نداری!",
            show_alert=True
        )

        return

    remove_score(user.id, price)

    if item["type"] == "title":

        cursor.execute("""
            UPDATE users
            SET title = ?
            WHERE user_id = ?
        """, (
            item["value"],
            user.id
        ))

    else:

        cursor.execute("""
            INSERT INTO inventory (
                user_id,
                item_id,
                item_name,
                quantity
            )
            VALUES (?, ?, ?, 1)

            ON CONFLICT(user_id, item_id)
            DO UPDATE SET quantity = quantity + 1
        """, (
            user.id,
            item_id,
            item["name"]
        ))

    db_commit()

    await query.answer(
        "✅ خرید موفق!",
        show_alert=True
    )

    await query.edit_message_text(
        f"""
🎉 **خرید موفق!**

🛍 {item['name']}

💰 موجودی جدید:
**{get_score(user.id)}** 🫏
""",
        parse_mode="Markdown",
        reply_markup=store_keyboard()
    )


# =========================================================
# RANKING
# =========================================================

async def ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    cursor.execute("""
        SELECT first_name, username, score
        FROM users
        ORDER BY score DESC
        LIMIT 10
    """)

    rows = cursor.fetchall()

    text = "🏆 **۱۰ خر پولدار برتر**\n\n"

    for i, row in enumerate(rows, 1):

        name = row["first_name"] or row["username"] or "Unknown"

        text += (
            f"{i}. {name} — "
            f"**{row['score']}** 🫏\n"
        )

    await update.callback_query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu(user.id)
    )


# =========================================================
# HELP
# =========================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    text = """
📖 **راهنمای خر‌بات**

━━━━━━━━━━━━

🤖 **هوش مصنوعی**

پیامت رو با «خر» شروع کن:

`خر خوبی؟`

تورکعلی جواب میده 😂

━━━━━━━━━━━━

🎮 **بازی‌ها**

🎯 حدس عدد
🪨 سنگ کاغذ قیچی
❌⭕ دوز
🎲 تاس
🧠 اطلاعات عمومی

━━━━━━━━━━━━

💰 **اقتصاد**

🫏 عر → پوینت
🎁 جایزه روزانه
🛍 فروشگاه
🎒 انبار
🏆 رتبه‌بندی

━━━━━━━━━━━━

💸 **انتقال پوینت**

روی پیام شخص ریپلای کن:

`بده 100`

"""

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=main_menu(user.id)
        )

    else:

        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=main_menu(user.id)
        )


# =========================================================
# GIVE SCORE
# =========================================================

async def give_score(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not update.message.reply_to_message:

        await update.message.reply_text(
            "❌ روی پیام شخص ریپلای کن."
        )

        return

    try:

        amount = int(context.args[0])

    except:

        await update.message.reply_text(
            "مثال:\n`/give 100`",
            parse_mode="Markdown"
        )

        return

    if amount <= 0:

        return

    target = update.message.reply_to_message.from_user

    create_user(user)
    create_user(target)

    if user.id == target.id:

        await update.message.reply_text(
            "😂 نمی‌تونی به خودت پوینت بدی."
        )

        return

    if get_score(user.id) < amount:

        await update.message.reply_text(
            "❌ موجودی کافی نداری."
        )

        return

    remove_score(user.id, amount)
    add_score(target.id, amount)

    await update.message.reply_text(
        f"✅ {amount} پوینت به "
        f"{target.first_name} داده شد."
    )


# =========================================================
# ADMIN
# =========================================================

def is_admin(user_id):

    return (
        ADMIN_ID != 0
        and user_id == ADMIN_ID
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not is_admin(user.id):

        await update.message.reply_text(
            "⛔ دسترسی نداری."
        )

        return

    cursor.execute(
        "SELECT COUNT(*) AS total FROM users"
    )

    total = cursor.fetchone()["total"]

    text = f"""
👑 **پنل مالک**

━━━━━━━━━━━━

👥 کاربران:
**{total}**

🛠 دستورات:

`/addcoin ID AMOUNT`

`/removecoin ID AMOUNT`

`/setcoin ID AMOUNT`

`/broadcast متن`

`/users`
"""

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


async def addcoin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update.effective_user.id):
        return

    try:

        user_id = int(context.args[0])
        amount = int(context.args[1])

        cursor.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (user_id,)
        )

        if not cursor.fetchone():

            await update.message.reply_text(
                "❌ کاربر پیدا نشد."
            )

            return

        add_score(user_id, amount)

        await update.message.reply_text(
            f"✅ +{amount} پوینت"
        )

    except:

        await update.message.reply_text(
            "مثال:\n/addcoin 123456789 1000"
        )


async def removecoin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update.effective_user.id):
        return

    try:

        user_id = int(context.args[0])
        amount = int(context.args[1])

        remove_score(user_id, amount)

        await update.message.reply_text(
            f"✅ -{amount} پوینت"
        )

    except:

        await update.message.reply_text(
            "مثال:\n/removecoin 123456789 500"
        )


async def setcoin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update.effective_user.id):
        return

    try:

        user_id = int(context.args[0])
        amount = int(context.args[1])

        cursor.execute(
            "UPDATE users SET score = ? WHERE user_id = ?",
            (amount, user_id)
        )

        db_commit()

        await update.message.reply_text(
            f"✅ موجودی کاربر شد: {amount}"
        )

    except:

        await update.message.reply_text(
            "مثال:\n/setcoin 123456789 5000"
        )


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update.effective_user.id):
        return

    cursor.execute("""
        SELECT first_name, username, user_id, score
        FROM users
        ORDER BY score DESC
        LIMIT 20
    """)

    rows = cursor.fetchall()

    text = "👥 **کاربران**\n\n"

    for row in rows:

        text += (
            f"• {row['first_name']} | "
            f"`{row['user_id']}` | "
            f"{row['score']} 🫏\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update.effective_user.id):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/broadcast سلام بچه‌ها 😂"
        )

        return

    message = " ".join(context.args)

    cursor.execute(
        "SELECT user_id FROM users"
    )

    users = cursor.fetchall()

    sent = 0

    for row in users:

        try:

            await context.bot.send_message(
                chat_id=row["user_id"],
                text=message
            )

            sent += 1

            await asyncio.sleep(0.05)

        except Exception as e:

            print(
                "Broadcast error:",
                row["user_id"],
                e
            )

    await update.message.reply_text(
        f"📢 پیام برای {sent} نفر ارسال شد."
    )


# =========================================================
# MESSAGE HANDLER
# =========================================================

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

    # -------------------------
    # TOROKALI
    # -------------------------

    if clean == "تورکعلی":

        response = await ask_ai(
            "کاربر فقط اسم تورکعلی را صدا زده. جواب بامزه بده."
        )

        update_quest(user.id, "ai")

        await update.message.reply_text(response)

        return

    # -------------------------
    # AI
    # -------------------------

    if clean.startswith("خر ") or clean == "خر":

        prompt = (
            "سلام خر!"
            if clean == "خر"
            else text[3:].strip()
        )

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing"
        )

        response = await ask_ai(prompt)

        update_quest(user.id, "ai")

        await update.message.reply_text(response)

        return

    # -------------------------
    # ARR
    # -------------------------

    if clean in ARR_WORDS:

        if not can_arr(user.id):

            await update.message.reply_text(
                "⏳ یکم صبر کن بعد دوباره عر بزن 😂"
            )

            return

        add_score(user.id, ARR_SCORE)

        update_quest(user.id, "arr")

        await update.message.reply_text(
            f"🫏 عرررر!\n"
            f"➕{ARR_SCORE} پوینت"
        )

        return

    # -------------------------
    # GIVE
    # -------------------------

    parts = clean.split()

    if (
        parts
        and parts[0] == "بده"
        and len(parts) >= 2
        and parts[1].isdigit()
    ):

        context.args = [parts[1]]

        await give_score(
            update,
            context
        )

        return


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    create_user(user)

    data = query.data

    # -------------------------
    # MAIN
    # -------------------------

    if data == "main":

        await query.edit_message_text(
            "🫏 **خر‌بات**\n\nبه قلمرو تورکعلی خوش اومدی 😂",
            parse_mode="Markdown",
            reply_markup=main_menu(user.id)
        )

        return

    # -------------------------
    # PROFILE
    # -------------------------

    if data == "profile":

        await profile(
            update,
            context
        )

        return

    # -------------------------
    # BALANCE
    # -------------------------

    if data == "balance":

        await balance(
            update,
            context
        )

        return

    # -------------------------
    # GAMES
    # -------------------------

    if data == "games":

        await games_menu(
            update,
            context
        )

        return

    # -------------------------
    # STORE
    # -------------------------

    if data == "store":

        await store(
            update,
            context
        )

        return

    # -------------------------
    # INVENTORY
    # -------------------------

    if data == "inventory":

        await inventory(
            update,
            context
        )

        return

    # -------------------------
    # QUESTS
    # -------------------------

    if data == "quests":

        await quests(
            update,
            context
        )

        return

    # -------------------------
    # DAILY
    # -------------------------

    if data == "daily":

        await daily(
            update,
            context
        )

        return

    # -------------------------
    # RANKING
    # -------------------------

    if data == "ranking":

        await ranking(
            update,
            context
        )

        return

    # -------------------------
    # HELP
    # -------------------------

    if data == "help":

        await help_command(
            update,
            context
        )

        return

    # -------------------------
    # AI
    # -------------------------

    if data == "ai":

        await query.edit_message_text(
            "🤖 **تورکعلی آماده‌ست!**\n\n"
            "پیامت رو با «خر» شروع کن.\n\n"
            "مثال:\n"
            "`خر امروز چه خبر؟`",
            parse_mode="Markdown",
            reply_markup=main_menu(user.id)
        )

        return

    # -------------------------
    # ADMIN
    # -------------------------

    if data == "admin":

        if not is_admin(user.id):

            await query.answer(
                "⛔ دسترسی نداری!",
                show_alert=True
            )

            return

        await query.edit_message_text(
            "👑 پنل مالک:\n\n"
            "/addcoin ID AMOUNT\n"
            "/removecoin ID AMOUNT\n"
            "/setcoin ID AMOUNT\n"
            "/broadcast TEXT\n"
            "/users",
            reply_markup=main_menu(user.id)
        )

        return

    # -------------------------
    # GAME SELECT
    # -------------------------

    if data == "game:dice":

        await dice_game(query)

        return

    if data == "game:guess":

        await start_guess(query)

        return

    if data == "game:rps":

        await start_rps(query)

        return

    if data == "game:ttt":

        await start_ttt(query)

        return

    if data == "game:quiz":

        await start_quiz(query)

        return

    # -------------------------
    # GUESS
    # -------------------------

    if data.startswith("guess:"):

        number = int(data.split(":")[1])

        await guess_answer(
            query,
            number
        )

        return

    # -------------------------
    # RPS
    # -------------------------

    if data.startswith("rps:"):

        choice = data.split(":")[1]

        await rps_play(
            query,
            choice
        )

        return

    # -------------------------
    # QUIZ
    # -------------------------

    if data.startswith("quiz:"):

        answer = int(
            data.split(":")[1]
        )

        await quiz_answer(
            query,
            answer
        )

        return

    # -------------------------
    # TTT
    # -------------------------

    if data.startswith("ttt:"):

        parts = data.split(":")

        game_id = parts[1]
        position = int(parts[2])

        await ttt_move(
            query,
            game_id,
            position
        )

        return

    # -------------------------
    # STORE
    # -------------------------

    if data.startswith("buy:"):

        item_id = data.split(":")[1]

        await buy_item(
            query,
            item_id
        )

        return


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):

    print(
        "BOT ERROR:",
        repr(context.error)
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        print(
            "ERROR: BOT_TOKEN تنظیم نشده."
        )

        return

    print(
        "================================"
    )

    print(
        "🫏 KHARBOT STARTING..."
    )

    print(
        f"Database: {DB_PATH}"
    )

    print(
        "================================"
    )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # -------------------------
    # COMMANDS
    # -------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "profile",
            profile
        )
    )

    app.add_handler(
        CommandHandler(
            "daily",
            daily
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    app.add_handler(
        CommandHandler(
            "give",
            give_score
        )
    )

    app.add_handler(
        CommandHandler(
            "quests",
            quests
        )
    )

    app.add_handler(
        CommandHandler(
            "store",
            store
        )
    )

    app.add_handler(
        CommandHandler(
            "inventory",
            inventory
        )
    )

    # ADMIN

    app.add_handler(
        CommandHandler(
            "admin",
            admin_panel
        )
    )

    app.add_handler(
        CommandHandler(
            "addcoin",
            addcoin
        )
    )

    app.add_handler(
        CommandHandler(
            "removecoin",
            removecoin
        )
    )

    app.add_handler(
        CommandHandler(
            "setcoin",
            setcoin
        )
    )

    app.add_handler(
        CommandHandler(
            "users",
            users_command
        )
    )

    app.add_handler(
        CommandHandler(
            "broadcast",
            broadcast
        )
    )

    # -------------------------
    # CALLBACKS
    # -------------------------

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # -------------------------
    # TEXT
    # -------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler
        )
    )

    app.add_error_handler(
        error_handler
    )

    print(
        "🫏 KHARBOT STARTED"
    )

    # مهم:
    # فقط یک نمونه از ربات باید polling کند.
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
