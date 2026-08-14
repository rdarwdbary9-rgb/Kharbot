import os
import sqlite3
import random
import time
import logging
from typing import Optional

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

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except:
    ADMIN_ID = 0

DB_PATH = "/tmp/kharbot.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger("KHARBOT")


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=20,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            coins INTEGER DEFAULT 500,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            games INTEGER DEFAULT 0,
            daily_at INTEGER DEFAULT 0,
            title TEXT DEFAULT '',
            created_at INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER NOT NULL,
            item_id TEXT NOT NULL,
            quantity INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, item_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS quests (
            user_id INTEGER PRIMARY KEY,
            games INTEGER DEFAULT 0,
            messages INTEGER DEFAULT 0,
            ai INTEGER DEFAULT 0,
            last_reset TEXT DEFAULT ''
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# USER FUNCTIONS
# =========================================================

def ensure_user(user):
    if not user:
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user.id,)
    )

    if not cur.fetchone():
        cur.execute("""
            INSERT INTO users
            (user_id, username, first_name, coins, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "Player",
            500,
            int(time.time())
        ))

    else:
        cur.execute("""
            UPDATE users
            SET username = ?, first_name = ?
            WHERE user_id = ?
        """, (
            user.username or "",
            user.first_name or "Player",
            user.id
        ))

    conn.commit()
    conn.close()


def get_coins(user_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT coins FROM users WHERE user_id = ?",
        (user_id,)
    )

    row = cur.fetchone()
    conn.close()

    return row["coins"] if row else 0


def add_coins(user_id, amount):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET coins = coins + ?
        WHERE user_id = ?
    """, (amount, user_id))

    conn.commit()
    conn.close()


def remove_coins(user_id, amount):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET coins = coins - ?
        WHERE user_id = ?
        AND coins >= ?
    """, (amount, user_id, amount))

    changed = cur.rowcount

    conn.commit()
    conn.close()

    return changed > 0


def add_game_result(user_id, win=False, loss=False):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET games = games + 1,
            wins = wins + ?,
            losses = losses + ?
        WHERE user_id = ?
    """, (
        1 if win else 0,
        1 if loss else 0,
        user_id
    ))

    conn.commit()
    conn.close()


# =========================================================
# ADMIN
# =========================================================

def is_admin(user_id):
    return ADMIN_ID != 0 and user_id == ADMIN_ID


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
            InlineKeyboardButton("🎒 انبار", callback_data="inventory"),
            InlineKeyboardButton("🏆 لیدربرد", callback_data="leaderboard")
        ],
        [
            InlineKeyboardButton("🎁 روزانه", callback_data="daily"),
            InlineKeyboardButton("🎯 ماموریت", callback_data="quests")
        ],
        [
            InlineKeyboardButton("📖 راهنما", callback_data="help")
        ]
    ]

    if is_admin(user_id):
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

    ensure_user(user)

    text = (
        "🫏 **خر‌بات وارد شد!**\n\n"
        "به قلمرو خرها خوش اومدی 😂\n\n"
        "💰 موجودی اولیه: **500 سکه**\n\n"
        "🎮 برای دیدن بازی‌ها روی «بازی‌ها» بزن."
    )

    await update.message.reply_text(
        text,
        reply_markup=main_menu(user.id),
        parse_mode="Markdown"
    )


# =========================================================
# PROFILE
# =========================================================

async def show_profile(update: Update, context=None):

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT coins, wins, losses, games, title
        FROM users
        WHERE user_id = ?
    """, (user.id,))

    row = cur.fetchone()
    conn.close()

    title = row["title"] if row["title"] else (
        "👑 مالک" if is_admin(user.id)
        else "🫏 خر معمولی"
    )

    text = (
        "👤 **پروفایل**\n"
        "━━━━━━━━━━━━━━\n"
        f"🏷 لقب: {title}\n"
        f"📝 نام: {user.first_name}\n"
        f"🆔 آیدی: `{user.id}`\n"
        f"💰 سکه: **{row['coins']}** 🪙\n\n"
        f"🎮 تعداد بازی: {row['games']}\n"
        f"🏆 برد: {row['wins']}\n"
        f"💀 باخت: {row['losses']}"
    )

    markup = main_menu(user.id)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=markup,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode="Markdown"
        )


# =========================================================
# BALANCE
# =========================================================

async def balance(update: Update, context=None):

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    coins = get_coins(user.id)

    text = (
        f"💰 **موجودی شما**\n\n"
        f"🪙 {coins} سکه"
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
# LEADERBOARD
# =========================================================

async def leaderboard(update: Update, context=None):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT first_name, username, coins, wins
        FROM users
        ORDER BY coins DESC
        LIMIT 10
    """)

    rows = cur.fetchall()
    conn.close()

    text = "🏆 **لیدربرد خر‌بات**\n━━━━━━━━━━━━━━\n\n"

    if not rows:
        text += "هنوز کسی اینجا نیست 😂"
    else:
        medals = ["🥇", "🥈", "🥉"]

        for i, row in enumerate(rows, 1):

            medal = medals[i - 1] if i <= 3 else f"{i}."

            name = row["first_name"] or row["username"] or "Player"

            text += (
                f"{medal} **{name}**\n"
                f"   🪙 {row['coins']} | 🏆 {row['wins']} برد\n\n"
            )

    markup = main_menu(
        update.effective_user.id
        if update.effective_user else 0
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=markup,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode="Markdown"
        )


# =========================================================
# GIVE COINS
# =========================================================

async def give_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    target = None
    amount = None

    # -----------------------------------------
    # Reply
    # /give 100
    # -----------------------------------------

    if update.message.reply_to_message:

        target = update.message.reply_to_message.from_user

        if context.args:
            try:
                amount = int(context.args[0])
            except:
                pass

    # -----------------------------------------
    # ID
    # /give 123456789 100
    # -----------------------------------------

    elif len(context.args) >= 2:

        try:
            target_id = int(context.args[0])
            amount = int(context.args[1])

            conn = get_db()
            cur = conn.cursor()

            cur.execute(
                "SELECT user_id FROM users WHERE user_id = ?",
                (target_id,)
            )

            exists = cur.fetchone()
            conn.close()

            if exists:
                class FakeUser:
                    id = target_id
                    first_name = str(target_id)

                target = FakeUser()

        except:
            pass

    if not target or not amount or amount <= 0:

        await update.message.reply_text(
            "❌ فرمت اشتباه!\n\n"
            "با ریپلای:\n"
            "`/give 100`\n\n"
            "با آیدی:\n"
            "`/give 123456789 100`",
            parse_mode="Markdown"
        )

        return

    # فقط مالک می‌تواند سکه رایگان ایجاد کند
    if is_admin(user.id):

        add_coins(target.id, amount)

        await update.message.reply_text(
            f"👑 **انتقال مالک**\n\n"
            f"👤 کاربر: `{target.id}`\n"
            f"💰 مقدار: **+{amount}** 🪙",
            parse_mode="Markdown"
        )

        return

    # کاربران عادی از موجودی خودشان منتقل می‌کنند
    if target.id == user.id:

        await update.message.reply_text(
            "🤡 به خودت که نمی‌تونی سکه بدی!"
        )

        return

    if get_coins(user.id) < amount:

        await update.message.reply_text(
            "❌ موجودی کافی نداری!"
        )

        return

    if not remove_coins(user.id, amount):

        await update.message.reply_text(
            "❌ انتقال انجام نشد."
        )

        return

    add_coins(target.id, amount)

    await update.message.reply_text(
        f"🎁 **انتقال انجام شد!**\n\n"
        f"👤 گیرنده: {target.first_name}\n"
        f"💰 مقدار: **{amount}** 🪙",
        parse_mode="Markdown"
    )


# =========================================================
# DAILY
# =========================================================

async def daily(update: Update, context=None):

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    now = int(time.time())

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT daily_at FROM users WHERE user_id = ?",
        (user.id,)
    )

    row = cur.fetchone()
    last = row["daily_at"] if row else 0

    if now - last < 86400:

        remaining = 86400 - (now - last)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        text = (
            "⏳ **جایزه روزانه قبلاً دریافت شده!**\n\n"
            f"🕐 {hours} ساعت و {minutes} دقیقه دیگر"
        )

    else:

        reward = random.randint(100, 250)

        cur.execute("""
            UPDATE users
            SET daily_at = ?,
                coins = coins + ?
            WHERE user_id = ?
        """, (now, reward, user.id))

        conn.commit()

        text = (
            "🎁 **جایزه روزانه!**\n\n"
            f"🪙 +{reward} سکه"
        )

    conn.close()

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
# GAMES MENU
# =========================================================

async def games_menu(update: Update, context=None):

    keyboard = [
        [
            InlineKeyboardButton(
                "🪙 شیر یا خط",
                callback_data="game_coin"
            ),
            InlineKeyboardButton(
                "🎲 تاس",
                callback_data="game_dice"
            )
        ],
        [
            InlineKeyboardButton(
                "🪨 سنگ کاغذ قیچی",
                callback_data="game_rps"
            ),
            InlineKeyboardButton(
                "🔢 حدس عدد",
                callback_data="game_guess"
            )
        ],
        [
            InlineKeyboardButton(
                "❌⭕ دوز",
                callback_data="game_ttt"
            ),
            InlineKeyboardButton(
                "📈 بالا یا پایین",
                callback_data="game_highlow"
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 عدد شانس",
                callback_data="game_lucky"
            ),
            InlineKeyboardButton(
                "🎰 سه‌تایی",
                callback_data="game_slots"
            )
        ],
        [
            InlineKeyboardButton(
                "⚡ واکنش سریع",
                callback_data="game_reaction"
            ),
            InlineKeyboardButton(
                "🏆 رقابت",
                callback_data="game_duel"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="main"
            )
        ]
    ]

    text = (
        "🎮 **بازی‌های خر‌بات**\n"
        "━━━━━━━━━━━━━━\n\n"
        "🪙 شیر یا خط\n"
        "🎲 تاس\n"
        "🪨 سنگ کاغذ قیچی\n"
        "🔢 حدس عدد\n"
        "❌⭕ دوز\n"
        "📈 بالا یا پایین\n"
        "🎯 عدد شانس\n"
        "🎰 سه‌تایی\n"
        "⚡ واکنش سریع\n"
        "🏆 رقابت"
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    else:

        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


# =========================================================
# PENDING BET SYSTEM
# =========================================================

pending_bets = {}


def ask_bet(user_id, game):

    pending_bets[user_id] = {
        "game": game,
        "created": time.time()
    }


def get_pending_bet(user_id):

    data = pending_bets.get(user_id)

    if not data:
        return None

    if time.time() - data["created"] > 120:

        pending_bets.pop(user_id, None)
        return None

    return data


# =========================================================
# COIN FLIP
# =========================================================

async def coin_game(update: Update, context):

    user = update.effective_user
    ensure_user(user)

    if not context.args:

        ask_bet(user.id, "coin")

        await update.message.reply_text(
            "🪙 **شیر یا خط**\n\n"
            "مبلغ شرط را بفرست:",
            parse_mode="Markdown"
        )

        return

    try:
        bet = int(context.args[0])
    except:

        await update.message.reply_text(
            "❌ مبلغ نامعتبره."
        )
        return

    if bet <= 0 or get_coins(user.id) < bet:

        await update.message.reply_text(
            "❌ موجودی کافی نیست."
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🦁 شیر",
                callback_data=f"coin_{bet}_heads"
            ),
            InlineKeyboardButton(
                "🪙 خط",
                callback_data=f"coin_{bet}_tails"
            )
        ]
    ])

    await update.message.reply_text(
        f"🪙 **شیر یا خط**\n\n"
        f"شرط: **{bet}** 🪙\n"
        f"انتخاب کن:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


async def play_coin(query, bet, choice):

    user = query.from_user
    ensure_user(user)

    bet = int(bet)

    if get_coins(user.id) < bet:

        await query.answer(
            "❌ موجودی کافی نیست!",
            show_alert=True
        )
        return

    if not remove_coins(user.id, bet):

        await query.answer(
            "❌ شرط ثبت نشد.",
            show_alert=True
        )
        return

    result = random.choice(["heads", "tails"])

    names = {
        "heads": "🦁 شیر",
        "tails": "🪙 خط"
    }

    if choice == result:

        reward = bet * 2
        add_coins(user.id, reward)
        add_game_result(user.id, win=True)

        text = (
            "🎉 **بردی!**\n\n"
            f"نتیجه: {names[result]}\n"
            f"💰 دریافت: +{reward} 🪙"
        )

    else:

        add_game_result(user.id, loss=True)

        text = (
            "💀 **باختی!**\n\n"
            f"نتیجه: {names[result]}\n"
            f"💸 از دست رفت: {bet} 🪙"
        )

    await query.edit_message_text(
        text,
        parse_mode="Markdown"
    )


# =========================================================
# DICE
# =========================================================

async def dice_game(update: Update, context):

    user = update.effective_user
    ensure_user(user)

    if not context.args:

        ask_bet(user.id, "dice")

        await update.message.reply_text(
            "🎲 **بازی تاس**\n\n"
            "مبلغ شرط را بفرست:"
        )
        return

    try:
        bet = int(context.args[0])
    except:

        await update.message.reply_text(
            "❌ مبلغ نامعتبر."
        )
        return

    if bet <= 0 or get_coins(user.id) < bet:

        await update.message.reply_text(
            "❌ موجودی کافی نیست."
        )
        return

    if not remove_coins(user.id, bet):
        return

    player = random.randint(1, 6)
    bot = random.randint(1, 6)

    if player > bot:

        reward = bet * 2
        add_coins(user.id, reward)
        add_game_result(user.id, win=True)

        result = f"🎉 بردی! +{reward} 🪙"

    elif player == bot:

        add_coins(user.id, bet)

        result = "🤝 مساوی! شرطت برگشت."

    else:

        add_game_result(user.id, loss=True)

        result = f"💀 باختی! -{bet} 🪙"

    await update.message.reply_text(
        f"🎲 **نتیجه تاس**\n\n"
        f"👤 تو: {player}\n"
        f"🤖 خر‌بات: {bot}\n\n"
        f"{result}",
        parse_mode="Markdown"
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

    wins = {
        "stone": "scissors",
        "paper": "stone",
        "scissors": "paper"
    }

    return "player" if wins[a] == b else "bot"


async def rps_game(update: Update, context):

    user = update.effective_user
    ensure_user(user)

    if not context.args:

        ask_bet(user.id, "rps")

        await update.message.reply_text(
            "🪨📄✂️ **سنگ کاغذ قیچی**\n\n"
            "مبلغ شرط را بفرست:"
        )
        return

    try:
        bet = int(context.args[0])
    except:

        await update.message.reply_text(
            "❌ مبلغ نامعتبر."
        )
        return

    if bet <= 0 or get_coins(user.id) < bet:

        await update.message.reply_text(
            "❌ موجودی کافی نیست."
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🪨 سنگ",
                callback_data=f"rps_{bet}_stone"
            ),
            InlineKeyboardButton(
                "📄 کاغذ",
                callback_data=f"rps_{bet}_paper"
            ),
            InlineKeyboardButton(
                "✂️ قیچی",
                callback_data=f"rps_{bet}_scissors"
            )
        ]
    ])

    await update.message.reply_text(
        f"🪨📄✂️ **سنگ کاغذ قیچی**\n\n"
        f"شرط: {bet} 🪙",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    # =========================================================
# PART 2
# GAMES + STORE + QUESTS + ADMIN + CALLBACKS + MAIN
# =========================================================


# =========================================================
# COMMON GAME CHECK
# =========================================================

def valid_bet(user_id, bet):
    try:
        bet = int(bet)
    except:
        return False

    return bet > 0 and get_coins(user_id) >= bet


# =========================================================
# GUESS NUMBER
# =========================================================

guess_games = {}


async def guess_game(update: Update, context):

    user = update.effective_user
    ensure_user(user)

    if not context.args:
        ask_bet(user.id, "guess")

        await update.message.reply_text(
            "🔢 **حدس عدد**\n\n"
            "مبلغ شرط را بفرست:",
            parse_mode="Markdown"
        )
        return

    try:
        bet = int(context.args[0])
    except:
        await update.message.reply_text("❌ مبلغ نامعتبر.")
        return

    if not valid_bet(user.id, bet):
        await update.message.reply_text("❌ موجودی کافی نیست.")
        return

    if not remove_coins(user.id, bet):
        return

    number = random.randint(1, 5)

    guess_games[user.id] = {
        "number": number,
        "bet": bet,
        "created": time.time()
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1️⃣", callback_data="guess_1"),
            InlineKeyboardButton("2️⃣", callback_data="guess_2"),
            InlineKeyboardButton("3️⃣", callback_data="guess_3"),
            InlineKeyboardButton("4️⃣", callback_data="guess_4"),
            InlineKeyboardButton("5️⃣", callback_data="guess_5")
        ]
    ])

    await update.message.reply_text(
        f"🔢 **حدس عدد**\n\n"
        f"یک عدد بین ۱ تا ۵ انتخاب کن.\n"
        f"💰 شرط: {bet} 🪙",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


async def play_guess(query, choice):

    user = query.from_user
    game = guess_games.get(user.id)

    if not game:
        await query.answer(
            "❌ بازی منقضی شده.",
            show_alert=True
        )
        return

    if time.time() - game["created"] > 120:
        guess_games.pop(user.id, None)

        await query.answer(
            "⏰ بازی منقضی شد.",
            show_alert=True
        )
        return

    choice = int(choice)
    number = game["number"]
    bet = game["bet"]

    guess_games.pop(user.id, None)

    if choice == number:

        reward = bet * 4
        add_coins(user.id, reward)
        add_game_result(user.id, win=True)

        text = (
            "🎉 **درست حدس زدی!**\n\n"
            f"🔢 عدد: {number}\n"
            f"🪙 جایزه: +{reward}"
        )

    else:

        add_game_result(user.id, loss=True)

        text = (
            "💀 **اشتباه بود!**\n\n"
            f"🔢 عدد درست: {number}\n"
            f"💸 باخت: {bet} 🪙"
        )

    await query.edit_message_text(
        text,
        parse_mode="Markdown"
    )


# =========================================================
# HIGH / LOW
# =========================================================

async def highlow_game(update: Update, context):

    user = update.effective_user
    ensure_user(user)

    if not context.args:

        ask_bet(user.id, "highlow")

        await update.message.reply_text(
            "📈 **بالا یا پایین**\n\n"
            "مبلغ شرط را بفرست:"
        )
        return

    try:
        bet = int(context.args[0])
    except:
        await update.message.reply_text("❌ مبلغ نامعتبر.")
        return

    if not valid_bet(user.id, bet):
        await update.message.reply_text("❌ موجودی کافی نیست.")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⬆️ بالا",
                callback_data=f"hl_{bet}_high"
            ),
            InlineKeyboardButton(
                "⬇️ پایین",
                callback_data=f"hl_{bet}_low"
            )
        ]
    ])

    await update.message.reply_text(
        f"📈 **بالا یا پایین**\n\n"
        f"شرط: {bet} 🪙\n"
        f"انتخاب کن:",
        reply_markup=keyboard
    )


async def play_highlow(query, bet, choice):

    user = query.from_user
    bet = int(bet)

    if not valid_bet(user.id, bet):
        await query.answer(
            "❌ موجودی کافی نیست.",
            show_alert=True
        )
        return

    if not remove_coins(user.id, bet):
        return

    a = random.randint(1, 13)
    b = random.randint(1, 13)

    if a == b:
        add_coins(user.id, bet)

        text = (
            "🤝 **مساوی!**\n\n"
            f"عدد اول: {a}\n"
            f"عدد دوم: {b}\n\n"
            "شرط برگشت داده شد."
        )

    else:

        result = "high" if b > a else "low"

        if choice == result:

            reward = bet * 2
            add_coins(user.id, reward)
            add_game_result(user.id, win=True)

            text = (
                "🎉 **بردی!**\n\n"
                f"{a} ➜ {b}\n"
                f"🪙 +{reward}"
            )

        else:

            add_game_result(user.id, loss=True)

            text = (
                "💀 **باختی!**\n\n"
                f"{a} ➜ {b}\n"
                f"💸 -{bet}"
            )

    await query.edit_message_text(
        text,
        parse_mode="Markdown"
    )


# =========================================================
# LUCKY NUMBER
# =========================================================

async def lucky_game(update: Update, context):

    user = update.effective_user
    ensure_user(user)

    if not context.args:

        ask_bet(user.id, "lucky")

        await update.message.reply_text(
            "🎯 **عدد شانس**\n\n"
            "مبلغ شرط را بفرست:"
        )
        return

    try:
        bet = int(context.args[0])
    except:
        await update.message.reply_text("❌ مبلغ نامعتبر.")
        return

    if not valid_bet(user.id, bet):
        await update.message.reply_text("❌ موجودی کافی نیست.")
        return

    if not remove_coins(user.id, bet):
        return

    number = random.randint(1, 10)

    if number == 7:

        reward = bet * 5
        add_coins(user.id, reward)
        add_game_result(user.id, win=True)

        text = (
            "🍀 **عدد شانس ۷ بود!**\n\n"
            f"🎯 عدد: {number}\n"
            f"🎉 جایزه: +{reward}"
        )

    else:

        add_game_result(user.id, loss=True)

        text = (
            "😵 **شانست نگرفت!**\n\n"
            f"🎯 عدد: {number}\n"
            f"💸 -{bet} 🪙"
        )

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


# =========================================================
# SLOTS
# =========================================================

async def slots_game(update: Update, context):

    user = update.effective_user
    ensure_user(user)

    if not context.args:

        ask_bet(user.id, "slots")

        await update.message.reply_text(
            "🎰 **سه‌تایی**\n\n"
            "مبلغ شرط را بفرست:"
        )
        return

    try:
        bet = int(context.args[0])
    except:
        await update.message.reply_text("❌ مبلغ نامعتبر.")
        return

    if not valid_bet(user.id, bet):
        await update.message.reply_text("❌ موجودی کافی نیست.")
        return

    if not remove_coins(user.id, bet):
        return

    symbols = ["🍒", "🍋", "🍇", "⭐", "7️⃣"]

    result = [
        random.choice(symbols),
        random.choice(symbols),
        random.choice(symbols)
    ]

    if result[0] == result[1] == result[2]:

        reward = bet * 5
        add_coins(user.id, reward)
        add_game_result(user.id, win=True)

        text = (
            "🎰 **جک‌پات!**\n\n"
            f"{' | '.join(result)}\n\n"
            f"🎉 +{reward} 🪙"
        )

    elif result[0] == result[1] or result[1] == result[2]:

        reward = bet * 2
        add_coins(user.id, reward)
        add_game_result(user.id, win=True)

        text = (
            "🎰 **دو تا یکی شد!**\n\n"
            f"{' | '.join(result)}\n\n"
            f"🎉 +{reward} 🪙"
        )

    else:

        add_game_result(user.id, loss=True)

        text = (
            "🎰 **باختی!**\n\n"
            f"{' | '.join(result)}\n\n"
            f"💸 -{bet} 🪙"
        )

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


# =========================================================
# REACTION GAME
# =========================================================

async def reaction_game(update: Update, context):

    user = update.effective_user
    ensure_user(user)

    reward = random.randint(20, 100)

    await update.message.reply_text(
        "⚡ **واکنش سریع!**\n\n"
        "اگر ربات گفت «بپر» سریع بنویس:\n"
        "`پر`",
        parse_mode="Markdown"
    )

    context.user_data["reaction"] = {
        "answer": "پر",
        "reward": reward,
        "created": time.time()
    }


# =========================================================
# TIC TAC TOE
# =========================================================

ttt_games = {}


def ttt_winner(board):

    lines = [
        (0,1,2),
        (3,4,5),
        (6,7,8),
        (0,3,6),
        (1,4,7),
        (2,5,8),
        (0,4,8),
        (2,4,6)
    ]

    for a, b, c in lines:

        if (
            board[a] and
            board[a] == board[b] == board[c]
        ):
            return board[a]

    if all(board):
        return "draw"

    return None


def ttt_keyboard(game_id, board):

    rows = []

    for start in range(0, 9, 3):

        row = []

        for i in range(start, start + 3):

            value = board[i] if board[i] else "⬜"

            row.append(
                InlineKeyboardButton(
                    value,
                    callback_data=f"ttt_{game_id}_{i}"
                )
            )

        rows.append(row)

    return InlineKeyboardMarkup(rows)


async def ttt_game(update: Update, context):

    user = update.effective_user
    ensure_user(user)

    if not context.args:

        ask_bet(user.id, "ttt")

        await update.message.reply_text(
            "❌⭕ **دوز**\n\n"
            "مبلغ شرط را بفرست:"
        )
        return

    try:
        bet = int(context.args[0])
    except:
        await update.message.reply_text("❌ مبلغ نامعتبر.")
        return

    if not valid_bet(user.id, bet):
        await update.message.reply_text("❌ موجودی کافی نیست.")
        return

    if not remove_coins(user.id, bet):
        return

    game_id = f"{user.id}_{int(time.time()*1000)}"

    ttt_games[game_id] = {
        "user": user.id,
        "bet": bet,
        "board": [""] * 9
    }

    await update.message.reply_text(
        "❌⭕ **دوز**\n\n"
        "تو ❌ هستی.\n"
        "حرکتت رو انتخاب کن:",
        reply_markup=ttt_keyboard(
            game_id,
            ttt_games[game_id]["board"]
        )
    )


async def ttt_move(query, game_id, position):

    game = ttt_games.get(game_id)

    if not game:
        await query.answer(
            "❌ بازی تمام شده.",
            show_alert=True
        )
        return

    user = query.from_user

    if user.id != game["user"]:
        await query.answer(
            "❌ این بازی مال تو نیست.",
            show_alert=True
        )
        return

    board = game["board"]
    position = int(position)

    if board[position]:
        await query.answer(
            "این خانه پره!",
            show_alert=True
        )
        return

    board[position] = "❌"

    winner = ttt_winner(board)

    if winner:
        await finish_ttt(query, game_id, winner)
        return

    empty = [
        i for i, x in enumerate(board)
        if not x
    ]

    if empty:
        board[random.choice(empty)] = "⭕"

    winner = ttt_winner(board)

    if winner:
        await finish_ttt(query, game_id, winner)
        return

    await query.edit_message_text(
        "❌⭕ **دوز**\n\n"
        "نوبت تو:",
        reply_markup=ttt_keyboard(
            game_id,
            board
        )
    )


async def finish_ttt(query, game_id, winner):

    game = ttt_games.pop(game_id, None)

    if not game:
        return

    bet = game["bet"]
    user_id = game["user"]

    if winner == "❌":

        reward = bet * 2
        add_coins(user_id, reward)
        add_game_result(user_id, win=True)

        text = f"🎉 **بردی!**\n+{reward} 🪙"

    elif winner == "⭕":

        add_game_result(user_id, loss=True)

        text = f"💀 **باختی!**\n-{bet} 🪙"

    else:

        add_coins(user_id, bet)

        text = "🤝 **مساوی شد!**\nشرط برگشت."

    await query.edit_message_text(
        f"❌⭕ **پایان دوز**\n\n{text}",
        parse_mode="Markdown"
    )


# =========================================================
# STORE
# =========================================================

STORE = {

    "lucky": {
        "name": "🍀 کارت شانس",
        "price": 300
    },

    "shield": {
        "name": "🛡 سپر",
        "price": 700
    },

    "double": {
        "name": "⚡ دوبرابرکننده",
        "price": 1000
    },

    "title_boss": {
        "name": "👑 لقب خر بزرگ",
        "price": 2500
    },

    "title_king": {
        "name": "🔥 سلطان طویله",
        "price": 5000
    }
}


async def store(update: Update, context=None):

    user = update.effective_user
    ensure_user(user)

    keyboard = []

    for item_id, item in STORE.items():

        keyboard.append([
            InlineKeyboardButton(
                f"{item['name']} | {item['price']} 🪙",
                callback_data=f"buy_{item_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 برگشت",
            callback_data="main"
        )
    ])

    text = (
        "🛍 **فروشگاه خر‌بات**\n\n"
        f"💰 موجودی: {get_coins(user.id)} 🪙\n\n"
        "آیتم موردنظر را انتخاب کن:"
    )

    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=markup,
            parse_mode="Markdown"
        )

    else:

        await update.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode="Markdown"
        )


async def buy_item(query, item_id):

    user = query.from_user
    item = STORE.get(item_id)

    if not item:
        await query.answer(
            "❌ آیتم پیدا نشد.",
            show_alert=True
        )
        return

    price = item["price"]

    if not remove_coins(user.id, price):

        await query.answer(
            "❌ موجودی کافی نیست.",
            show_alert=True
        )
        return

    # لقب‌ها
    if item_id.startswith("title_"):

        conn = get_db()
        cur = conn.cursor()

        title = item["name"]

        cur.execute(
            "UPDATE users SET title = ? WHERE user_id = ?",
            (title, user.id)
        )

        conn.commit()
        conn.close()

    else:

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO inventory
            (user_id, item_id, quantity)
            VALUES (?, ?, 1)

            ON CONFLICT(user_id, item_id)
            DO UPDATE SET quantity = quantity + 1
        """, (user.id, item_id))

        conn.commit()
        conn.close()

    await query.answer(
        "✅ خرید موفق!",
        show_alert=True
    )

    await store(query, None)


# =========================================================
# INVENTORY
# =========================================================

async def inventory(update: Update, context=None):

    user = update.effective_user
    ensure_user(user)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT item_id, quantity
        FROM inventory
        WHERE user_id = ?
        AND quantity > 0
    """, (user.id,))

    rows = cur.fetchall()
    conn.close()

    text = "🎒 **انبار من**\n━━━━━━━━━━━━\n\n"

    if not rows:

        text += "انبارت خالیه 😂"

    else:

        for row in rows:

            item = STORE.get(row["item_id"])

            if item:
                name = item["name"]
            else:
                name = row["item_id"]

            text += f"{name} × {row['quantity']}\n"

    markup = main_menu(user.id)

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=markup,
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

async def quests(update: Update, context=None):

    user = update.effective_user
    ensure_user(user)

    conn = get_db()
    cur = conn.cursor()

    today = time.strftime("%Y-%m-%d")

    cur.execute(
        "SELECT * FROM quests WHERE user_id = ?",
        (user.id,)
    )

    row = cur.fetchone()

    if not row:

        cur.execute("""
            INSERT INTO quests
            (user_id, games, messages, ai, last_reset)
            VALUES (?, 0, 0, 0, ?)
        """, (user.id, today))

        conn.commit()

        games = 0
        messages = 0
        ai = 0

    else:

        games = row["games"]
        messages = row["messages"]
        ai = row["ai"]

        if row["last_reset"] != today:

            cur.execute("""
                UPDATE quests
                SET games = 0,
                    messages = 0,
                    ai = 0,
                    last_reset = ?
                WHERE user_id = ?
            """, (today, user.id))

            conn.commit()

            games = 0
            messages = 0
            ai = 0

    conn.close()

    text = (
        "🎯 **ماموریت‌های روزانه**\n"
        "━━━━━━━━━━━━━━\n\n"
        f"🎮 ۳ بازی: {min(games,3)}/3\n"
        f"💬 ۱۰ پیام: {min(messages,10)}/10\n"
        f"🤖 ۳ چت AI: {min(ai,3)}/3\n"
    )

    if games >= 3:
        text += "\n✅ مأموریت بازی تکمیل شده!"

    markup = main_menu(user.id)

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=markup,
            parse_mode="Markdown"
        )

    else:

        await update.message.reply_text(
            text,
            parse_mode="Markdown"
        )


# =========================================================
# HELP
# =========================================================

async def help_menu(update: Update, context=None):

    text = (
        "📖 **راهنمای خر‌بات**\n"
        "━━━━━━━━━━━━━━\n\n"

        "🎮 **بازی‌ها**\n"
        "• `شیرخط`\n"
        "• `تاس`\n"
        "• `سنگ`\n"
        "• `حدس`\n"
        "• `دوز`\n"
        "• `بالاپایین`\n"
        "• `شانس`\n"
        "• `سه‌تایی`\n"
        "• `واکنش`\n\n"

        "💰 **اقتصاد**\n"
        "• `موجودی`\n"
        "• `فروشگاه`\n"
        "• `انبار`\n"
        "• `لیدربرد`\n"
        "• `روزانه`\n\n"

        "🎁 **انتقال سکه**\n"
        "با Reply:\n"
        "`/give 100`\n\n"

        "با آیدی:\n"
        "`/give 123456789 100`\n"
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_menu(
                update.effective_user.id
            ),
            parse_mode="Markdown"
        )

    else:

        await update.message.reply_text(
            text,
            parse_mode="Markdown"
        )


# =========================================================
# ADMIN PANEL
# =========================================================

async def admin_panel(update: Update, context=None):

    user = update.effective_user

    if not user or not is_admin(user.id):

        if update.callback_query:
            await update.callback_query.answer(
                "❌ دسترسی نداری!",
                show_alert=True
            )
        else:
            await update.message.reply_text(
                "❌ دسترسی نداری!"
            )

        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) AS count FROM users"
    )

    total = cur.fetchone()["count"]

    conn.close()

    text = (
        "👑 **پنل مالک خر‌بات**\n"
        "━━━━━━━━━━━━━━\n\n"
        f"👥 کاربران: **{total}**\n\n"

        "💰 `/addcoin ID AMOUNT`\n"
        "➖ `/removecoin ID AMOUNT`\n"
        "📢 `/broadcast TEXT`\n"
        "🔍 `/userinfo ID`\n"
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
# ADMIN ADD COIN
# =========================================================

async def addcoin_command(update: Update, context):

    user = update.effective_user

    if not is_admin(user.id):
        return

    if len(context.args) != 2:

        await update.message.reply_text(
            "مثال:\n"
            "`/addcoin 123456789 500`",
            parse_mode="Markdown"
        )
        return

    try:

        target = int(context.args[0])
        amount = int(context.args[1])

    except:

        await update.message.reply_text(
            "❌ مقدار نامعتبر."
        )
        return

    if amount <= 0:
        return

    add_coins(target, amount)

    await update.message.reply_text(
        f"👑 انجام شد.\n"
        f"🪙 +{amount} برای `{target}`",
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN REMOVE COIN
# =========================================================

async def removecoin_command(update: Update, context):

    user = update.effective_user

    if not is_admin(user.id):
        return

    if len(context.args) != 2:

        await update.message.reply_text(
            "مثال:\n"
            "`/removecoin 123456789 500`",
            parse_mode="Markdown"
        )
        return

    try:

        target = int(context.args[0])
        amount = int(context.args[1])

    except:

        await update.message.reply_text(
            "❌ مقدار نامعتبر."
        )
        return

    if amount <= 0:
        return

    remove_coins(target, amount)

    await update.message.reply_text(
        f"👑 انجام شد.\n"
        f"➖ {amount} از `{target}`",
        parse_mode="Markdown"
    )


# =========================================================
# USER INFO ADMIN
# =========================================================

async def userinfo_command(update: Update, context):

    user = update.effective_user

    if not is_admin(user.id):
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "مثال:\n/userinfo 123456789"
        )
        return

    try:
        target = int(context.args[0])
    except:
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM users
        WHERE user_id = ?
    """, (target,))

    row = cur.fetchone()
    conn.close()

    if not row:

        await update.message.reply_text(
            "❌ کاربر پیدا نشد."
        )
        return

    await update.message.reply_text(
        f"👤 **اطلاعات کاربر**\n\n"
        f"ID: `{row['user_id']}`\n"
        f"نام: {row['first_name']}\n"
        f"Username: @{row['username']}\n"
        f"سکه: {row['coins']}\n"
        f"بازی: {row['games']}\n"
        f"برد: {row['wins']}\n"
        f"باخت: {row['losses']}",
        parse_mode="Markdown"
    )


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def callback_handler(update: Update, context):

    query = update.callback_query
    user = query.from_user

    if not user:
        return

    ensure_user(user)

    try:
        await query.answer()
    except:
        pass

    data = query.data or ""

    # MAIN
    if data == "main":

        await query.edit_message_text(
            "🫏 **خر‌بات**\n\n"
            "به قلمرو خرها خوش اومدی 😂",
            reply_markup=main_menu(user.id),
            parse_mode="Markdown"
        )
        return

    # PROFILE
    if data == "profile":
        await show_profile(update, context)
        return

    # BALANCE
    if data == "balance":
        await balance(update, context)
        return

    # GAMES
    if data == "games":
        await games_menu(update, context)
        return

    # STORE
    if data == "store":
        await store(update, context)
        return

    # INVENTORY
    if data == "inventory":
        await inventory(update, context)
        return

    # LEADERBOARD
    if data == "leaderboard":
        await leaderboard(update, context)
        return

    # DAILY
    if data == "daily":
        await daily(update, context)
        return

    # QUESTS
    if data == "quests":
        await quests(update, context)
        return

    # HELP
    if data == "help":
        await help_menu(update, context)
        return

    # ADMIN
    if data == "admin":
        await admin_panel(update, context)
        return

    # -----------------------------------------
    # GAME BUTTONS
    # -----------------------------------------

    if data == "game_coin":

        ask_bet(user.id, "coin")

        await query.edit_message_text(
            "🪙 **شیر یا خط**\n\n"
            "مبلغ شرط را ارسال کن.",
            parse_mode="Markdown"
        )
        return

    if data == "game_dice":

        ask_bet(user.id, "dice")

        await query.edit_message_text(
            "🎲 **تاس**\n\n"
            "مبلغ شرط را ارسال کن."
        )
        return

    if data == "game_rps":

        ask_bet(user.id, "rps")

        await query.edit_message_text(
            "🪨📄✂️ **سنگ کاغذ قیچی**\n\n"
            "مبلغ شرط را ارسال کن."
        )
        return

    if data == "game_guess":

        ask_bet(user.id, "guess")

        await query.edit_message_text(
            "🔢 **حدس عدد**\n\n"
            "مبلغ شرط را ارسال کن."
        )
        return

    if data == "game_ttt":

        ask_bet(user.id, "ttt")

        await query.edit_message_text(
            "❌⭕ **دوز**\n\n"
            "مبلغ شرط را ارسال کن."
        )
        return

    if data == "game_highlow":

        ask_bet(user.id, "highlow")

        await query.edit_message_text(
            "📈 **بالا یا پایین**\n\n"
            "مبلغ شرط را ارسال کن."
        )
        return

    if data == "game_lucky":

        ask_bet(user.id, "lucky")

        await query.edit_message_text(
            "🎯 **عدد شانس**\n\n"
            "مبلغ شرط را ارسال کن."
        )
        return

    if data == "game_slots":

        ask_bet(user.id, "slots")

        await query.edit_message_text(
            "🎰 **سه‌تایی**\n\n"
            "مبلغ شرط را ارسال کن."
        )
        return

    if data == "game_reaction":

        await query.edit_message_text(
            "⚡ برای بازی واکنش سریع\n"
            "بنویس:\n\n"
            "`واکنش`",
            parse_mode="Markdown"
        )
        return

    # -----------------------------------------
    # COIN
    # -----------------------------------------

    if data.startswith("coin_"):

        parts = data.split("_")

        if len(parts) == 3:

            await play_coin(
                query,
                int(parts[1]),
                parts[2]
            )

        return

    # -----------------------------------------
    # RPS
    # -----------------------------------------

    if data.startswith("rps_"):

        parts = data.split("_")

        if len(parts) == 3:

            bet = int(parts[1])
            choice = parts[2]

            if not valid_bet(user.id, bet):

                await query.answer(
                    "❌ موجودی کافی نیست.",
                    show_alert=True
                )
                return

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🪨",
                        callback_data=f"rpsplay_{bet}_stone"
                    ),
                    InlineKeyboardButton(
                        "📄",
                        callback_data=f"rpsplay_{bet}_paper"
                    ),
                    InlineKeyboardButton(
                        "✂️",
                        callback_data=f"rpsplay_{bet}_scissors"
                    )
                ]
            ])

            await query.edit_message_text(
                "انتخابت رو بزن:",
                reply_markup=keyboard
            )

        return

    if data.startswith("rpsplay_"):

        parts = data.split("_")

        bet = int(parts[1])
        choice = parts[2]

        if not valid_bet(user.id, bet):
            await query.answer(
                "❌ موجودی کافی نیست.",
                show_alert=True
            )
            return

        if not remove_coins(user.id, bet):
            return

        bot_choice = random.choice(
            list(RPS.keys())
        )

        result = rps_winner(
            choice,
            bot_choice
        )

        if result == "player":

            reward = bet * 2

            add_coins(
                user.id,
                reward
            )

            add_game_result(
                user.id,
                win=True
            )

            text = (
                "🎉 **بردی!**\n\n"
                f"👤 {RPS[choice]}\n"
                f"🤖 {RPS[bot_choice]}\n\n"
                f"+{reward} 🪙"
            )

        elif result == "bot":

            add_game_result(
                user.id,
                loss=True
            )

            text = (
                "💀 **باختی!**\n\n"
                f"👤 {RPS[choice]}\n"
                f"🤖 {RPS[bot_choice]}\n\n"
                f"-{bet} 🪙"
            )

        else:

            add_coins(
                user.id,
                bet
            )

            text = (
                "🤝 **مساوی!**\n\n"
                f"👤 {RPS[choice]}\n"
                f"🤖 {RPS[bot_choice]}\n\n"
                "شرط برگشت."
            )

        await query.edit_message_text(
            text,
            parse_mode="Markdown"
        )

        return

    # -----------------------------------------
    # GUESS
    # -----------------------------------------

    if data.startswith("guess_"):

        await play_guess(
            query,
            data.split("_")[1]
        )

        return

    # -----------------------------------------
    # HIGH LOW
    # -----------------------------------------

    if data.startswith("hl_"):

        parts = data.split("_")

        await play_highlow(
            query,
            int(parts[1]),
            parts[2]
        )

        return

    # -----------------------------------------
    # TTT
    # -----------------------------------------

    if data.startswith("ttt_"):

        parts = data.split("_")

        if len(parts) >= 3:

            game_id = parts[1]
            position = parts[2]

            await ttt_move(
                query,
                game_id,
                position
            )

        return

    # -----------------------------------------
    # STORE
    # -----------------------------------------

    if data.startswith("buy_"):

        await buy_item(
            query,
            data[4:]
        )

        return


# =========================================================
# ONE-WORD GAME SYSTEM
# =========================================================

async def handle_text(update: Update, context):

    if not update.message:
        return

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    text = (
        update.message.text or ""
    ).strip().lower()

    if not text:
        return

    # -----------------------------------------
    # REACTION ANSWER
    # -----------------------------------------

    reaction = context.user_data.get("reaction")

    if reaction:

        if time.time() - reaction["created"] > 30:

            context.user_data.pop(
                "reaction",
                None
            )

            await update.message.reply_text(
                "⏰ دیر جواب دادی!"
            )

            return

        if text == reaction["answer"]:

            reward = reaction["reward"]

            add_coins(
                user.id,
                reward
            )

            context.user_data.pop(
                "reaction",
                None
            )

            await update.message.reply_text(
                f"⚡ **سریع بودی!**\n"
                f"+{reward} 🪙",
                parse_mode="Markdown"
            )

            return

    # -----------------------------------------
    # PENDING BET
    # -----------------------------------------

    pending = get_pending_bet(user.id)

    if pending and text.isdigit():

        bet = int(text)

        pending_bets.pop(
            user.id,
            None
        )

        game = pending["game"]

        if game == "coin":

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🦁 شیر",
                        callback_data=f"coin_{bet}_heads"
                    ),
                    InlineKeyboardButton(
                        "🪙 خط",
                        callback_data=f"coin_{bet}_tails"
                    )
                ]
            ])

            if not valid_bet(user.id, bet):

                await update.message.reply_text(
                    "❌ موجودی کافی نیست."
                )
                return

            await update.message.reply_text(
                f"🪙 شرط: {bet}\nانتخاب کن:",
                reply_markup=keyboard
            )

            return

        context.args = [str(bet)]

        if game == "dice":
            await dice_game(
                update,
                context
            )
            return

        if game == "rps":
            await rps_game(
                update,
                context
            )
            return

        if game == "guess":
            await guess_game(
                update,
                context
            )
            return

        if game == "ttt":
            await ttt_game(
                update,
                context
            )
            return

        if game == "highlow":
            await highlow_game(
                update,
                context
            )
            return

        if game == "lucky":
            await lucky_game(
                update,
                context
            )
            return

        if game == "slots":
            await slots_game(
                update,
                context
            )
            return

    # -----------------------------------------
    # ONE WORD GAMES
    # -----------------------------------------

    if text in {"شیرخط", "شیر خط"}:

        ask_bet(
            user.id,
            "coin"
        )

        await update.message.reply_text(
            "🪙 مبلغ شرط را بفرست:"
        )

        return

    if text in {"تاس", "بازی تاس"}:

        ask_bet(
            user.id,
            "dice"
        )

        await update.message.reply_text(
            "🎲 مبلغ شرط را بفرست:"
        )

        return

    if text in {"سنگ", "قیچی", "کاغذ"}:

        ask_bet(
            user.id,
            "rps"
        )

        await update.message.reply_text(
            "🪨📄✂️ مبلغ شرط را بفرست:"
        )

        return

    if text in {"حدس", "حدس عدد"}:

        ask_bet(
            user.id,
            "guess"
        )

        await update.message.reply_text(
            "🔢 مبلغ شرط را بفرست:"
        )

        return

    if text in {"دوز"}:

        ask_bet(
            user.id,
            "ttt"
        )

        await update.message.reply_text(
            "❌⭕ مبلغ شرط را بفرست:"
        )

        return

    if text in {"بالاپایین", "بالا پایین"}:

        ask_bet(
            user.id,
            "highlow"
        )

        await update.message.reply_text(
            "📈 مبلغ شرط را بفرست:"
        )

        return

    if text in {"شانس", "عدد شانس"}:

        ask_bet(
            user.id,
            "lucky"
        )

        await update.message.reply_text(
            "🎯 مبلغ شرط را بفرست:"
        )

        return

    if text in {"سه‌تایی", "سه تایی", "اسلات"}:

        ask_bet(
            user.id,
            "slots"
        )

        await update.message.reply_text(
            "🎰 مبلغ شرط را بفرست:"
        )

        return

    if text in {"واکنش", "ری‌اکشن", "ری اکشن"}:

        await reaction_game(
            update,
            context
        )

        return

    # -----------------------------------------
    # MENU WORDS
    # -----------------------------------------

    if text in {"موجودی", "سکه", "کیف"}:

        await balance(
            update,
            context
        )

        return

    if text in {"پروفایل", "پروفايل"}:

        await show_profile(
            update,
            context
        )

        return

    if text in {"فروشگاه", "خرید"}:

        await store(
            update,
            context
        )

        return

    if text in {"انبار", "آیتم‌ها", "آیتم ها"}:

        await inventory(
            update,
            context
        )

        return

    if text in {"لیدربرد", "برترین", "برترین‌ها", "برترین ها"}:

        await leaderboard(
            update,
            context
        )

        return

    if text in {"روزانه", "جایزه"}:

        await daily(
            update,
            context
        )

        return

    if text in {"ماموریت", "ماموریت‌ها", "ماموریت ها"}:

        await quests(
            update,
            context
        )

        return

    if text in {"بازی", "بازی‌ها", "بازی ها"}:

        await games_menu(
            update,
            context
        )

        return

    if text in {"راهنما", "کمک"}:

        await help_menu(
            update,
            context
        )

        return

    # -----------------------------------------
    # AI
    # -----------------------------------------

    if text.startswith("خر "):

        prompt = text[4:].strip()

        if prompt:

            await update.message.reply_text(
                "🫏 دارم فکر می‌کنم..."
            )

            if GROQ_API_KEY:

                try:

                    from openai import AsyncOpenAI

                    client = AsyncOpenAI(
                        api_key=GROQ_API_KEY,
                        base_url="https://api.groq.com/openai/v1"
                    )

                    response = await client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[
                            {
                                "role": "system",
                                "content":
                                "تو خر‌بات هستی؛ فارسی، بامزه، صمیمی و شوخ‌طبع جواب بده."
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        temperature=0.9,
                        max_tokens=500
                    )

                    answer = (
                        response
                        .choices[0]
                        .message
                        .content
                    )

                    await update.message.reply_text(
                        answer
                    )

                except Exception as e:

                    logger.error(
                        f"AI ERROR: {e}"
                    )

                    await update.message.reply_text(
                        "🫏 مغزم هنگ کرد 😂"
                    )

            else:

                await update.message.reply_text(
                    "🫏 برای AI باید GROQ_API_KEY تنظیم بشه."
                )

            return


# =========================================================
# COMMAND HANDLERS
# =========================================================

async def coin_command(update, context):
    await coin_game(update, context)


async def dice_command(update, context):
    await dice_game(update, context)


async def rps_command(update, context):
    await rps_game(update, context)


async def guess_command(update, context):
    await guess_game(update, context)


async def ttt_command(update, context):
    await ttt_game(update, context)


async def highlow_command(update, context):
    await highlow_game(update, context)


async def lucky_command(update, context):
    await lucky_game(update, context)


async def slots_command(update, context):
    await slots_game(update, context)


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):

    logger.error(
        "BOT ERROR: %r",
        context.error
    )

    try:

        if update and update.effective_message:

            await update.effective_message.reply_text(
                "🫏 یه خطای کوچیک رخ داد؛ دوباره امتحان کن."
            )

    except:
        pass


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        print("❌ BOT_TOKEN تنظیم نشده!")
        return

    init_db()

    print("=" * 40)
    print("🫏 KHARBOT STARTING")
    print(f"Database: {DB_PATH}")
    print("=" * 40)

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # -----------------------------------------
    # COMMANDS
    # -----------------------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "profile",
            show_profile
        )
    )

    app.add_handler(
        CommandHandler(
            "balance",
            balance
        )
    )

    app.add_handler(
        CommandHandler(
            "games",
            games_menu
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

    app.add_handler(
        CommandHandler(
            "leaderboard",
            leaderboard
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
            "quests",
            quests
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_menu
        )
    )

    app.add_handler(
        CommandHandler(
            "give",
            give_coins
        )
    )

    # GAME COMMANDS

    app.add_handler(
        CommandHandler(
            "coin",
            coin_command
        )
    )

    app.add_handler(
        CommandHandler(
            "dice",
            dice_command
        )
    )

    app.add_handler(
        CommandHandler(
            "rps",
            rps_command
        )
    )

    app.add_handler(
        CommandHandler(
            "guess",
            guess_command
        )
    )

    app.add_handler(
        CommandHandler(
            "ttt",
            ttt_command
        )
    )

    app.add_handler(
        CommandHandler(
            "highlow",
            highlow_command
        )
    )

    app.add_handler(
        CommandHandler(
            "lucky",
            lucky_command
        )
    )

    app.add_handler(
        CommandHandler(
            "slots",
            slots_command
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
            addcoin_command
        )
    )

    app.add_handler(
        CommandHandler(
            "removecoin",
            removecoin_command
        )
    )

    app.add_handler(
        CommandHandler(
            "userinfo",
            userinfo_command
        )
    )

    # CALLBACK

    app.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    # TEXT

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    app.add_error_handler(
        error_handler
    )

    print("🫏 KHARBOT STARTED")

    app.run_polling(
        drop_pending_updates=True
    )


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":
    main()
