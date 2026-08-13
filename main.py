import os
import sqlite3
import time
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ==================================================
# SETTINGS
# ==================================================

TOKEN = os.getenv("BOT_TOKEN")

ARR_SCORE = 10
ARR_COOLDOWN = 30
DAILY_SCORE = 100

DB_PATH = "/tmp/kharbot.db"

# ==================================================
# DATABASE
# ==================================================

db = sqlite3.connect(
    DB_PATH,
    check_same_thread=False
)

cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    score INTEGER DEFAULT 0,
    last_daily INTEGER DEFAULT 0,
    rps_games INTEGER DEFAULT 0,
    rps_wins INTEGER DEFAULT 0,
    rps_losses INTEGER DEFAULT 0,
    rps_draws INTEGER DEFAULT 0
)
""")

db.commit()

# ==================================================
# USER
# ==================================================

def create_user(user):

    cursor.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user.id,)
    )

    if cursor.fetchone() is None:

        cursor.execute("""
        INSERT INTO users
        (
            user_id,
            username,
            first_name
        )
        VALUES (?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "Player"
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

    db.commit()


# ==================================================
# SCORE
# ==================================================

def get_score(user_id):

    cursor.execute("""
    SELECT score
    FROM users
    WHERE user_id = ?
    """, (user_id,))

    result = cursor.fetchone()

    return result[0] if result else 0


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
    SET score = score - ?
    WHERE user_id = ?
    """, (
        amount,
        user_id
    ))

    db.commit()


# ==================================================
# ARR SYSTEM
# ==================================================

ARR_WORDS = {
    "عر",
    "عرعر",
    "عر عر",
    "عرر",
    "عررر",
    "عرررر",
    "عررررر",
    "عرررررر",
    "ار ار",
    "ارار"
}

last_arr = {}


def can_get_arr_score(user_id):

    now = time.time()

    last_time = last_arr.get(
        user_id,
        0
    )

    if now - last_time < ARR_COOLDOWN:
        return False

    last_arr[user_id] = now

    return True


ARR_RESPONSES = [
    "🫏 خر شناسایی شد!",
    "🫏 عررررر!",
    "😂 صدای خر تأیید شد!",
    "🫏 خر‌بات تأیید کرد!",
    "🔥 عررر! امتیاز گرفتی!",
    "😂 گروه داره تبدیل به طویله میشه!"
]


# ==================================================
# MAIN MENU
# ==================================================

def main_menu():

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
                "🏆 جدول",
                callback_data="leaderboard"
            )
        ],
        [
            InlineKeyboardButton(
                "🎁 جایزه",
                callback_data="daily"
            ),
            InlineKeyboardButton(
                "📖 راهنما",
                callback_data="help"
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


# ==================================================
# START
# ==================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if user:
        create_user(user)

    await update.message.reply_text(
        """
🫏 خر‌بات

به قلمرو خرها خوش اومدی! 😂

💰 پوینت جمع کن
🎮 بازی کن
🏆 رتبه بگیر
🎁 جایزه بگیر

برای شروع یکی از گزینه‌ها رو انتخاب کن:
""",
        reply_markup=main_menu()
    )


# ==================================================
# PROFILE
# ==================================================

async def profile(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    create_user(user)

    score = get_score(user.id)

    cursor.execute("""
    SELECT
        rps_games,
        rps_wins,
        rps_losses,
        rps_draws
    FROM users
    WHERE user_id = ?
    """, (user.id,))

    data = cursor.fetchone()

    games = data[0]
    wins = data[1]
    losses = data[2]
    draws = data[3]

    await update.message.reply_text(
        f"""
👤 پروفایل

نام: {user.first_name}

💰 پوینت: {score}

🎮 سنگ کاغذ قیچی
بازی: {games}
🏆 برد: {wins}
💀 باخت: {losses}
🤝 مساوی: {draws}
"""
    )


# ==================================================
# BALANCE
# ==================================================

async def balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    create_user(user)

    score = get_score(user.id)

    await update.message.reply_text(
        f"💰 موجودی شما:\n\n🫏 {score} پوینت"
    )


# ==================================================
# DAILY
# ==================================================

async def daily(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not user:
        return

    create_user(user)

    now = int(time.time())

    cursor.execute("""
    SELECT last_daily
    FROM users
    WHERE user_id = ?
    """, (user.id,))

    result = cursor.fetchone()

    last_daily = result[0] if result else 0

    if now - last_daily < 86400:

        remaining = 86400 - (
            now - last_daily
        )

        hours = remaining // 3600

        minutes = (
            remaining % 3600
        ) // 60

        await update.message.reply_text(
            f"""
🎁 جایزه امروز رو قبلاً گرفتی!

⏳ {hours} ساعت و {minutes} دقیقه دیگه دوباره بیا.
"""
        )

        return

    add_score(
        user.id,
        DAILY_SCORE
    )

    cursor.execute("""
    UPDATE users
    SET last_daily = ?
    WHERE user_id = ?
    """, (
        now,
        user.id
    ))

    db.commit()

    score = get_score(user.id)

    await update.message.reply_text(
        f"""
🎁 جایزه روزانه!

+{DAILY_SCORE} پوینت 🫏

💰 موجودی:
{score}
"""
    )


# ==================================================
# LEADERBOARD
# ==================================================

async def leaderboard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    cursor.execute("""
    SELECT
        first_name,
        username,
        score
    FROM users
    ORDER BY score DESC
    LIMIT 10
    """)

    users = cursor.fetchall()

    if not users:

        await update.message.reply_text(
            "هنوز کسی امتیازی نداره!"
        )

        return

    text = "🏆 جدول برترین خرها\n\n"

    for index, user in enumerate(users):

        first_name = user[0]
        username = user[1]
        score = user[2]

        name = (
            "@" + username
            if username
            else first_name
        )

        if index == 0:
            place = "🥇"
        elif index == 1:
            place = "🥈"
        elif index == 2:
            place = "🥉"
        else:
            place = f"{index + 1}."

        text += (
            f"{place} {name} — "
            f"{score} 🫏\n"
        )

    await update.message.reply_text(text)


# ==================================================
# HELP
# ==================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        """
📖 راهنمای خر‌بات

🫏 عر
برای گرفتن پوینت

💰 موجودی
دیدن پوینت

👤 پروفایل
دیدن مشخصات

🎁 جایزه
گرفتن جایزه روزانه

🏆 جدول
دیدن رتبه‌ها

🎮 بازی
دیدن بازی‌ها

🪨 سنگ کاغذ قیچی
شروع بازی با خر‌بات
"""
    )


# ==================================================
# RPS MENU
# ==================================================

async def rps_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    keyboard = [
        [
            InlineKeyboardButton(
                "🪨 سنگ",
                callback_data="rps_stone"
            ),
            InlineKeyboardButton(
                "📄 کاغذ",
                callback_data="rps_paper"
            ),
            InlineKeyboardButton(
                "✂️ قیچی",
                callback_data="rps_scissors"
            )
        ]
    ]

    await update.message.reply_text(
        """
🪨📄✂️ سنگ کاغذ قیچی

انتخاب خودت رو بزن!
"""
        ,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==================================================
# RPS GAME
# ==================================================

RPS_CHOICES = {
    "stone": "🪨 سنگ",
    "paper": "📄 کاغذ",
    "scissors": "✂️ قیچی"
}


def rps_winner(player, bot):

    if player == bot:
        return "draw"

    if (
        player == "stone"
        and bot == "scissors"
    ):
        return "win"

    if (
        player == "paper"
        and bot == "stone"
    ):
        return "win"

    if (
        player == "scissors"
        and bot == "paper"
    ):
        return "win"

    return "lose"


async def rps_callback(
    query,
    choice
):

    user = query.from_user

    create_user(user)

    bot_choice = random.choice(
        list(RPS_CHOICES.keys())
    )

    result = rps_winner(
        choice,
        bot_choice
    )

    cursor.execute("""
    UPDATE users
    SET rps_games = rps_games + 1
    WHERE user_id = ?
    """, (user.id,))

    if result == "win":

        add_score(
            user.id,
            100
        )

        cursor.execute("""
        UPDATE users
        SET rps_wins = rps_wins + 1
        WHERE user_id = ?
        """, (user.id,))

        message = """
🎉 بردی!

+100 🫏 پوینت
"""

    elif result == "lose":

        cursor.execute("""
        UPDATE users
        SET rps_losses = rps_losses + 1
        WHERE user_id = ?
        """, (user.id,))

        message = """
💀 باختی!

این بار خر‌بات برد 😂
"""

    else:

        cursor.execute("""
        UPDATE users
        SET rps_draws = rps_draws + 1
        WHERE user_id = ?
        """, (user.id,))

        message = """
🤝 مساوی شد!
"""

    db.commit()

    score = get_score(user.id)

    await query.edit_message_text(
        f"""
🪨📄✂️ نتیجه

انتخاب تو:
{RPS_CHOICES[choice]}

انتخاب خر‌بات:
{RPS_CHOICES[bot_choice]}

{message}

💰 موجودی:
{score} پوینت
"""
    )


# ==================================================
# CALLBACK BUTTONS
# ==================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    create_user(user)

    data = query.data

    if data == "profile":

        score = get_score(user.id)

        cursor.execute("""
        SELECT
            rps_games,
            rps_wins,
            rps_losses,
            rps_draws
        FROM users
        WHERE user_id = ?
        """, (user.id,))

        stats = cursor.fetchone()

        await query.edit_message_text(
            f"""
👤 پروفایل

نام: {user.first_name}

💰 پوینت: {score}

🎮 بازی‌ها: {stats[0]}
🏆 برد: {stats[1]}
💀 باخت: {stats[2]}
🤝 مساوی: {stats[3]}
""",
            reply_markup=main_menu()
        )

        return

    if data == "balance":

        score = get_score(user.id)

        await query.edit_message_text(
            f"""
💰 موجودی

🫏 {score} پوینت
""",
            reply_markup=main_menu()
        )

        return

    if data == "daily":

        now = int(time.time())

        cursor.execute("""
        SELECT last_daily
        FROM users
        WHERE user_id = ?
        """, (user.id,))

        last = cursor.fetchone()[0]

        if now - last < 86400:

            await query.edit_message_text(
                "🎁 جایزه امروز رو قبلاً گرفتی!",
                reply_markup=main_menu()
            )

            return

        add_score(
            user.id,
            DAILY_SCORE
        )

        cursor.execute("""
        UPDATE users
        SET last_daily = ?
        WHERE user_id = ?
        """, (
            now,
            user.id
        ))

        db.commit()

        await query.edit_message_text(
            f"""
🎁 جایزه دریافت شد!

+{DAILY_SCORE} پوینت 🫏

💰 موجودی:
{get_score(user.id)}
""",
            reply_markup=main_menu()
        )

        return

    if data == "leaderboard":

        cursor.execute("""
        SELECT
            first_name,
            username,
            score
        FROM users
        ORDER BY score DESC
        LIMIT 10
        """)

        users = cursor.fetchall()

        text = "🏆 جدول برترین‌ها\n\n"

        for i, row in enumerate(users):

            name = (
                "@" + row[1]
                if row[1]
                else row[0]
            )

            text += (
                f"{i + 1}. "
                f"{name} — "
                f"{row[2]} 🫏\n"
            )

        await query.edit_message_text(
            text,
            reply_markup=main_menu()
        )

        return

    if data == "games":

        keyboard = [
            [
                InlineKeyboardButton(
                    "🪨📄✂️ سنگ کاغذ قیچی",
                    callback_data="start_rps"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="back"
                )
            ]
        ]

        await query.edit_message_text(
            "🎮 بازی‌ها",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    if data == "start_rps":

        keyboard = [
            [
                InlineKeyboardButton(
                    "🪨 سنگ",
                    callback_data="rps_stone"
                ),
                InlineKeyboardButton(
                    "📄 کاغذ",
                    callback_data="rps_paper"
                ),
                InlineKeyboardButton(
                    "✂️ قیچی",
                    callback_data="rps_scissors"
                )
            ]
        ]

        await query.edit_message_text(
            "🪨📄✂️ انتخابت رو بزن:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    if data == "help":

        await query.edit_message_text(
            """
📖 راهنما

🫏 عر = +10 پوینت

🎁 جایزه = +100 پوینت روزانه

🪨📄✂️ سنگ کاغذ قیچی
بازی با خر‌بات

💰 موجودی
دیدن پوینت

🏆 جدول
دیدن رتبه‌ها
""",
            reply_markup=main_menu()
        )

        return

    if data == "back":

        await query.edit_message_text(
            "🫏 منوی اصلی",
            reply_markup=main_menu()
        )

        return

    if data.startswith("rps_"):

        choice = data.replace(
            "rps_",
            ""
        )

        await rps_callback(
            query,
            choice
        )


# ==================================================
# MESSAGE HANDLER
# ==================================================

async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    user = update.effective_user

    if not user:
        return

    create_user(user)

    text = update.message.text

    if not text:
        return

    text = text.strip().lower()

    # ARR

    if text in ARR_WORDS:

        if not can_get_arr_score(user.id):

            await update.message.reply_text(
                "⏳ یکم صبر کن بعد دوباره عر بزن 😂"
            )

            return

        add_score(
            user.id,
            ARR_SCORE
        )

        await update.message.reply_text(
            f"""
{random.choice(ARR_RESPONSES)}

+{ARR_SCORE} 🫏 پوینت

💰 موجودی:
{get_score(user.id)}
"""
        )

        return

    # PERSIAN COMMANDS

    if text in {
        "پروفایل",
        "امتیاز",
        "امتیاز من"
    }:

        await profile(
            update,
            context
        )

        return

    if text in {
        "موجودی",
        "پوینت",
        "پول"
    }:

        await balance(
            update,
            context
        )

        return

    if text in {
        "جایزه",
        "جایزه روزانه"
    }:

        await daily(
            update,
            context
        )

        return

    if text in {
        "جدول",
        "امتیازات",
        "رتبه",
        "رنک"
    }:

        await leaderboard(
            update,
            context
        )

        return

    if text in {
        "راهنما",
        "کمک",
        "دستورات"
    }:

        await help_command(
            update,
            context
        )

        return

    if text in {
        "بازی",
        "بازی ها",
        "بازی‌ها",
        "سنگ کاغذ قیچی"
    }:

        await rps_menu(
            update,
            context
        )


# ==================================================
# MAIN
# ==================================================

def main():

    if not TOKEN:

        print(
            "ERROR: BOT_TOKEN is missing!"
        )

        return

    print("KHARBOT STARTING...")

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "top",
            leaderboard
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
        CallbackQueryHandler(
            button_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler
        )
    )

    print("KHARBOT STARTED")

    app.run_polling()


if __name__ == "__main__":
    main()
