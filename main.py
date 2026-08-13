import os
import sqlite3
import time
import random

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# SETTINGS
# =========================

TOKEN = os.getenv("BOT_TOKEN")

ARR_SCORE = 10
ARR_COOLDOWN = 30
DAILY_SCORE = 100

# =========================
# DATABASE
# =========================

db = sqlite3.connect(
    "kharbot.db",
    check_same_thread=False
)

cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    score INTEGER DEFAULT 0,
    last_daily INTEGER DEFAULT 0
)
""")

db.commit()

# =========================
# USER
# =========================

def create_user(user):

    cursor.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user.id,)
    )

    if cursor.fetchone() is None:

        cursor.execute("""
        INSERT INTO users
        (user_id, username, first_name)
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


# =========================
# SCORE
# =========================

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


def get_score(user_id):

    cursor.execute("""
    SELECT score
    FROM users
    WHERE user_id = ?
    """, (user_id,))

    result = cursor.fetchone()

    if result:
        return result[0]

    return 0


# =========================
# ARR SYSTEM
# =========================

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
    "Donkey detected!",
    "ARRRRR!",
    "Nice donkey sound!",
    "The donkey approves!",
    "ARRR! +10",
    "The group is becoming a stable!"
]


# =========================
# LEADERBOARD
# =========================

async def leaderboard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    cursor.execute("""
    SELECT first_name, username, score
    FROM users
    ORDER BY score DESC
    LIMIT 10
    """)

    users = cursor.fetchall()

    if not users:

        await update.message.reply_text(
            "No scores yet!"
        )

        return

    text = "LEADERBOARD\n"
    text += "================\n\n"

    medals = [
        "1.",
        "2.",
        "3."
    ]

    for index, user in enumerate(users):

        first_name = user[0]
        username = user[1]
        score = user[2]

        if username:
            name = "@" + username
        else:
            name = first_name

        place = (
            medals[index]
            if index < 3
            else str(index + 1) + "."
        )

        text += (
            f"{place} {name} - "
            f"{score} points\n"
        )

    await update.message.reply_text(text)


# =========================
# PROFILE
# =========================

async def profile(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    create_user(user)

    score = get_score(user.id)

    await update.message.reply_text(
        f"""
PROFILE

Name: {user.first_name}

Donkey points: {score}

Say "عر عر" to earn points!
"""
    )


# =========================
# DAILY
# =========================

async def daily(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    create_user(user)

    now = int(time.time())

    cursor.execute("""
    SELECT last_daily
    FROM users
    WHERE user_id = ?
    """, (user.id,))

    result = cursor.fetchone()

    last_daily = result[0]

    if now - last_daily < 86400:

        remaining = 86400 - (
            now - last_daily
        )

        hours = remaining // 3600

        minutes = (
            remaining % 3600
        ) // 60

        await update.message.reply_text(
            f"Daily reward already claimed!\n"
            f"Come back in {hours}h {minutes}m."
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
DAILY REWARD!

+{DAILY_SCORE} points

Total: {score}
"""
    )


# =========================
# HELP
# =========================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        """
KHARBOT

Commands:

/top
Leaderboard

/profile
Your profile

/daily
Daily reward

/help
Help

You can also type:

عر
عرعر
عر عر
عررر
عرررر
"""
    )


# =========================
# MESSAGE HANDLER
# =========================

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
                "Wait a little before earning again!"
            )

            return

        add_score(
            user.id,
            ARR_SCORE
        )

        score = get_score(user.id)

        response = random.choice(
            ARR_RESPONSES
        )

        await update.message.reply_text(
            f"""
{response}

+{ARR_SCORE} points

Total: {score}
"""
        )

        return

    # PERSIAN COMMANDS

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
        "جایزه",
        "جایزه روزانه"
    }:

        await daily(
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


# =========================
# MAIN
# =========================

def main():

    if not TOKEN:

        print(
            "BOT_TOKEN is missing!"
        )

        return

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
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
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler
        )
    )

    print("KHARBOT STARTED")

    app.run_polling()


if __name__ == "__main__":
    main()
