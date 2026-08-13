import os
import sqlite3
import time
import random
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =========================================================
# SETTINGS
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

ARR_SCORE = 10
ARR_COOLDOWN = 30
DAILY_SCORE = 100

# فعلاً برای جلوگیری از خطای permission
DB_PATH = os.getenv("DB_PATH", "/tmp/kharbot.db")

# =========================================================
# DATABASE
# =========================================================

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


# =========================================================
# USER SYSTEM
# =========================================================

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


# =========================================================
# ARR SYSTEM
# =========================================================

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

ARR_RESPONSES = [
    "🫏 خر شناسایی شد!",
    "🫏 عررررر!",
    "😂 صدای خر تأیید شد!",
    "🔥 عر زدی، پوینت گرفتی!",
    "🫏 خر‌بات راضی است!",
    "😂 گروه داره تبدیل به طویله میشه!"
]


def can_get_arr_score(user_id):

    now = time.time()

    last_time = last_arr.get(user_id, 0)

    if now - last_time < ARR_COOLDOWN:
        return False

    last_arr[user_id] = now

    return True


# =========================================================
# MAIN MENU
# =========================================================

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


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if user:
        create_user(user)

    await update.message.reply_text(
        """
🫏 خر‌بات

به قلمرو خرها خوش اومدی 😂

💰 پوینت جمع کن
🎮 بازی کن
🫏 خرینه بازی کن
🏆 رتبه بگیر
🎁 جایزه بگیر

از منوی زیر استفاده کن:
""",
        reply_markup=main_menu()
    )


# =========================================================
# PROFILE
# =========================================================

async def profile(update, context):

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

    await update.message.reply_text(
        f"""
👤 پروفایل

نام: {user.first_name}

💰 پوینت: {score}

🪨📄✂️ سنگ کاغذ قیچی
🎮 بازی: {data[0]}
🏆 برد: {data[1]}
💀 باخت: {data[2]}
🤝 مساوی: {data[3]}
"""
    )


# =========================================================
# BALANCE
# =========================================================

async def balance(update, context):

    user = update.effective_user

    if not user:
        return

    create_user(user)

    await update.message.reply_text(
        f"💰 موجودی شما:\n\n🫏 {get_score(user.id)} پوینت"
    )


# =========================================================
# DAILY
# =========================================================

async def daily(update, context):

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

        remaining = 86400 - (now - last_daily)

        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        await update.message.reply_text(
            f"""
🎁 جایزه امروز رو قبلاً گرفتی!

⏳ {hours} ساعت و {minutes} دقیقه دیگه دوباره بیا.
"""
        )

        return

    add_score(user.id, DAILY_SCORE)

    cursor.execute("""
    UPDATE users
    SET last_daily = ?
    WHERE user_id = ?
    """, (
        now,
        user.id
    ))

    db.commit()

    await update.message.reply_text(
        f"""
🎁 جایزه روزانه!

+{DAILY_SCORE} 🫏 پوینت

💰 موجودی:
{get_score(user.id)}
"""
    )


# =========================================================
# LEADERBOARD
# =========================================================

async def leaderboard(update, context):

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

    for i, row in enumerate(users):

        name = (
            "@" + row[1]
            if row[1]
            else row[0]
        )

        if i == 0:
            medal = "🥇"
        elif i == 1:
            medal = "🥈"
        elif i == 2:
            medal = "🥉"
        else:
            medal = f"{i + 1}."

        text += f"{medal} {name} — {row[2]} 🫏\n"

    await update.message.reply_text(text)


# =========================================================
# HELP
# =========================================================

async def help_command(update, context):

    await update.message.reply_text(
        """
📖 راهنمای خر‌بات

🫏 عر
گرفتن پوینت

💰 موجودی
دیدن پوینت

👤 پروفایل
دیدن مشخصات

🎁 جایزه
جایزه روزانه

🏆 جدول
جدول امتیازات

🎮 بازی
منوی بازی‌ها

🪨 سنگ کاغذ قیچی
بازی با خر‌بات

🫏 شروع خرینه
شروع بازی خرینه داخل گروه
"""
    )


# =========================================================
# RPS
# =========================================================

RPS_CHOICES = {
    "stone": "🪨 سنگ",
    "paper": "📄 کاغذ",
    "scissors": "✂️ قیچی"
}


def rps_winner(player, bot):

    if player == bot:
        return "draw"

    if player == "stone" and bot == "scissors":
        return "win"

    if player == "paper" and bot == "stone":
        return "win"

    if player == "scissors" and bot == "paper":
        return "win"

    return "lose"


async def rps_menu(update, context):

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
        "🪨📄✂️ انتخابت رو بزن:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def play_rps(query, choice):

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

        add_score(user.id, 100)

        cursor.execute("""
        UPDATE users
        SET rps_wins = rps_wins + 1
        WHERE user_id = ?
        """, (user.id,))

        message = "🎉 بردی!\n\n+100 پوینت 🫏"

    elif result == "lose":

        cursor.execute("""
        UPDATE users
        SET rps_losses = rps_losses + 1
        WHERE user_id = ?
        """, (user.id,))

        message = "💀 باختی!\n\nخر‌بات برد 😂"

    else:

        cursor.execute("""
        UPDATE users
        SET rps_draws = rps_draws + 1
        WHERE user_id = ?
        """, (user.id,))

        message = "🤝 مساوی شد!"

    db.commit()

    await query.edit_message_text(
        f"""
🪨📄✂️ نتیجه

تو:
{RPS_CHOICES[choice]}

خر‌بات:
{RPS_CHOICES[bot_choice]}

{message}

💰 موجودی:
{get_score(user.id)}
"""
    )


# =========================================================
# =========================================================
# 🫏 KHARINE GAME
# =========================================================
# =========================================================

# ساختار بازی:
#
# chat_id -> {
#     players: {
#         user_id: {
#             name,
#             role,
#             alive
#         }
#     },
#     state,
#     day,
#     night_votes,
#     doctor_target,
#     seer_target,
#     votes
# }
#
# فقط یک بازی فعال در هر گروه.

kharine_games = {}


ROLE_NAMES = {
    "kharine": "🐺 خرینه",
    "seer": "🔮 فال‌خر",
    "doctor": "🩺 خرپزشک",
    "villager": "👨‍🌾 خر‌دار"
}


# =========================================================
# ROLE DISTRIBUTION
# =========================================================

def create_roles(player_count):

    if player_count == 4:

        roles = [
            "kharine",
            "seer",
            "doctor",
            "villager"
        ]

    elif player_count == 5:

        roles = [
            "kharine",
            "seer",
            "doctor",
            "villager",
            "villager"
        ]

    elif player_count == 6:

        roles = [
            "kharine",
            "kharine",
            "seer",
            "doctor",
            "villager",
            "villager"
        ]

    elif player_count == 7:

        roles = [
            "kharine",
            "kharine",
            "seer",
            "doctor",
            "villager",
            "villager",
            "villager"
        ]

    else:

        roles = [
            "kharine",
            "kharine",
            "seer",
            "doctor",
            "villager",
            "villager",
            "villager",
            "villager"
        ]

    random.shuffle(roles)

    return roles


# =========================================================
# KHARINE MENU
# =========================================================

def kharine_lobby_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🫏 ورود به بازی",
                callback_data="kharine_join"
            )
        ],
        [
            InlineKeyboardButton(
                "🚪 خروج",
                callback_data="kharine_leave"
            )
        ],
        [
            InlineKeyboardButton(
                "🚀 شروع بازی",
                callback_data="kharine_start"
            )
        ]
    ])


def kharine_lobby_text(game):

    players = game["players"]

    text = """
🫏 خرینه

🎭 یک بازی مافیایی مخصوص خر‌بات!

👥 بازیکنان:
"""

    for i, player in enumerate(players.values(), 1):

        text += f"{i}. {player['name']}\n"

    text += f"""
    
👥 تعداد: {len(players)}/8

حداقل بازیکن: 4 نفر

برای ورود روی دکمه بزنید.
"""

    return text


# =========================================================
# START KHARINE
# =========================================================

async def start_kharine(update, context):

    chat = update.effective_chat
    user = update.effective_user

    if not chat or chat.type == "private":

        await update.message.reply_text(
            "🫏 خرینه باید داخل گروه شروع بشه!"
        )

        return

    if chat.id in kharine_games:

        await update.message.reply_text(
            "⚠️ یک بازی خرینه در این گروه در حال اجراست."
        )

        return

    create_user(user)

    kharine_games[chat.id] = {
        "players": {
            user.id: {
                "name": user.first_name,
                "username": user.username or "",
                "role": None,
                "alive": True
            }
        },
        "state": "lobby",
        "day": 0,
        "message_id": None,
        "night_kill": None,
        "doctor_target": None,
        "seer_target": None,
        "votes": {}
    }

    message = await update.message.reply_text(
        kharine_lobby_text(
            kharine_games[chat.id]
        ),
        reply_markup=kharine_lobby_keyboard()
    )

    kharine_games[chat.id]["message_id"] = message.message_id


# =========================================================
# JOIN KHARINE
# =========================================================

async def join_kharine(query):

    chat_id = query.message.chat_id
    user = query.from_user

    if chat_id not in kharine_games:

        await query.answer(
            "بازی وجود نداره!",
            show_alert=True
        )

        return

    game = kharine_games[chat_id]

    if game["state"] != "lobby":

        await query.answer(
            "بازی قبلاً شروع شده!",
            show_alert=True
        )

        return

    if user.id in game["players"]:

        await query.answer(
            "قبلاً وارد بازی شدی!",
            show_alert=True
        )

        return

    if len(game["players"]) >= 8:

        await query.answer(
            "بازی پر شده!",
            show_alert=True
        )

        return

    create_user(user)

    game["players"][user.id] = {
        "name": user.first_name,
        "username": user.username or "",
        "role": None,
        "alive": True
    }

    await query.answer(
        "🫏 وارد بازی شدی!"
    )

    await query.edit_message_text(
        kharine_lobby_text(game),
        reply_markup=kharine_lobby_keyboard()
    )


# =========================================================
# LEAVE KHARINE
# =========================================================

async def leave_kharine(query):

    chat_id = query.message.chat_id
    user = query.from_user

    if chat_id not in kharine_games:

        await query.answer(
            "بازی وجود نداره!",
            show_alert=True
        )

        return

    game = kharine_games[chat_id]

    if game["state"] != "lobby":

        await query.answer(
            "بازی شروع شده و نمی‌تونی خارج بشی!",
            show_alert=True
        )

        return

    if user.id not in game["players"]:

        await query.answer(
            "تو داخل بازی نیستی!",
            show_alert=True
        )

        return

    del game["players"][user.id]

    await query.answer(
        "🚪 از بازی خارج شدی."
    )

    if not game["players"]:

        del kharine_games[chat_id]

        await query.edit_message_text(
            "🫏 لابی خرینه خالی شد."
        )

        return

    await query.edit_message_text(
        kharine_lobby_text(game),
        reply_markup=kharine_lobby_keyboard()
    )


# =========================================================
# START ACTUAL GAME
# =========================================================

async def begin_kharine(query, context):

    chat_id = query.message.chat_id
    user = query.from_user

    if chat_id not in kharine_games:

        await query.answer(
            "بازی وجود نداره!",
            show_alert=True
        )

        return

    game = kharine_games[chat_id]

    if game["state"] != "lobby":

        await query.answer(
            "بازی قبلاً شروع شده!",
            show_alert=True
        )

        return

    count = len(game["players"])

    if count < 4:

        await query.answer(
            "حداقل ۴ بازیکن لازم است!",
            show_alert=True
        )

        return

    roles = create_roles(count)

    for user_id, role in zip(
        game["players"].keys(),
        roles
    ):

        game["players"][user_id]["role"] = role

    game["state"] = "night"
    game["day"] = 1

    await query.answer(
        "🚀 بازی شروع شد!"
    )

    # ارسال نقش خصوصی
    for user_id, player in game["players"].items():

        role = player["role"]

        role_text = ROLE_NAMES[role]

        description = ""

        if role == "kharine":

            description = """
تو عضو خرینه‌ها هستی.

🌙 شب‌ها باید یک بازیکن را برای حذف انتخاب کنید.

هدفت:
کشتن اهالی طویله بدون لو رفتن.
"""

        elif role == "seer":

            description = """
تو فال‌خر هستی.

🌙 هر شب می‌توانی نقش یک بازیکن را بررسی کنی.

فقط نتیجه بررسی برای خودت نمایش داده می‌شود.
"""

        elif role == "doctor":

            description = """
تو خرپزشک هستی.

🌙 هر شب می‌توانی یک نفر را نجات بدهی.
"""

        else:

            description = """
تو خر‌دار هستی.

قدرت ویژه‌ای نداری.

با صحبت و رأی‌گیری خرینه‌ها را پیدا کن.
"""

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=f"""
🎭 نقش تو در خرینه:

{role_text}

{description}

⚠️ این نقش محرمانه است.
به کسی نگو!
"""
            )

        except Exception:

            pass

    await query.edit_message_text(
        """
🫏 خرینه شروع شد!

🎭 نقش‌ها ارسال شدند.

🌙 شب اول آغاز شد...

بازیکنان نقش خود را در پیام خصوصی دریافت کرده‌اند.
"""
    )

    await start_night(
        chat_id,
        context
    )


# =========================================================
# NIGHT
# =========================================================

async def start_night(chat_id, context):

    game = kharine_games.get(chat_id)

    if not game:
        return

    game["state"] = "night"
    game["night_kill"] = None
    game["doctor_target"] = None
    game["seer_target"] = None

    # خرینه‌ها
    for user_id, player in game["players"].items():

        if not player["alive"]:
            continue

        if player["role"] != "kharine":
            continue

        keyboard = []

        for target_id, target in game["players"].items():

            if not target["alive"]:
                continue

            if target_id == user_id:
                continue

            keyboard.append([
                InlineKeyboardButton(
                    target["name"],
                    callback_data=f"khkill_{chat_id}_{target_id}"
                )
            ])

        if keyboard:

            try:

                await context.bot.send_message(
                    chat_id=user_id,
                    text="🐺 خرینه‌ها: چه کسی را انتخاب می‌کنید؟",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            except Exception:
                pass

    # فال‌خر
    for user_id, player in game["players"].items():

        if not player["alive"]:
            continue

        if player["role"] != "seer":
            continue

        keyboard = []

        for target_id, target in game["players"].items():

            if not target["alive"]:
                continue

            if target_id == user_id:
                continue

            keyboard.append([
                InlineKeyboardButton(
                    target["name"],
                    callback_data=f"khseer_{chat_id}_{target_id}"
                )
            ])

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text="🔮 نقش یک نفر را بررسی کن:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        except Exception:
            pass

    # پزشک
    for user_id, player in game["players"].items():

        if not player["alive"]:
            continue

        if player["role"] != "doctor":
            continue

        keyboard = []

        for target_id, target in game["players"].items():

            if not target["alive"]:
                continue

            keyboard.append([
                InlineKeyboardButton(
                    target["name"],
                    callback_data=f"khdoctor_{chat_id}_{target_id}"
                )
            ])

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text="🩺 چه کسی را نجات می‌دهی؟",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        except Exception:
            pass

    # برای ساده و قابل کنترل بودن،
    # بعد از 30 ثانیه شب پردازش می‌شود.
    context.job_queue.run_once(
        finish_night_job,
        30,
        data=chat_id
    )


async def finish_night_job(context):

    chat_id = context.job.data

    await finish_night(
        chat_id,
        context
    )


# =========================================================
# NIGHT ACTIONS
# =========================================================

async def kh_kill(query, chat_id, target_id):

    try:
        chat_id = int(chat_id)
        target_id = int(target_id)
    except Exception:
        return

    if chat_id not in kharine_games:
        await query.answer("بازی تمام شده!", show_alert=True)
        return

    game = kharine_games[chat_id]

    if game["state"] != "night":
        await query.answer("الان شب نیست!", show_alert=True)
        return

    user_id = query.from_user.id

    if user_id not in game["players"]:
        return

    if game["players"][user_id]["role"] != "kharine":
        return

    if not game["players"][user_id]["alive"]:
        return

    game["night_kill"] = target_id

    await query.answer("🎯 انتخاب ثبت شد.")

    await query.edit_message_text(
        "🐺 انتخابت ثبت شد.\nمنتظر پایان شب باش."
    )


async def kh_seer(query, chat_id, target_id):

    try:
        chat_id = int(chat_id)
        target_id = int(target_id)
    except Exception:
        return

    if chat_id not in kharine_games:
        return

    game = kharine_games[chat_id]

    user_id = query.from_user.id

    if game["players"][user_id]["role"] != "seer":
        return

    role = game["players"][target_id]["role"]

    if role == "kharine":

        result = "🐺 این شخص خرینه است!"

    else:

        result = "🏘️ این شخص از خرینه‌ها نیست."

    await query.answer(
        result,
        show_alert=True
    )


async def kh_doctor(query, chat_id, target_id):

    try:
        chat_id = int(chat_id)
        target_id = int(target_id)
    except Exception:
        return

    if chat_id not in kharine_games:
        return

    game = kharine_games[chat_id]

    user_id = query.from_user.id

    if game["players"][user_id]["role"] != "doctor":
        return

    game["doctor_target"] = target_id

    await query.answer(
        "🩺 انتخاب ثبت شد."
    )

    await query.edit_message_text(
        "🩺 انتخاب نجات ثبت شد."
    )


# =========================================================
# FINISH NIGHT
# =========================================================

async def finish_night(chat_id, context):

    game = kharine_games.get(chat_id)

    if not game:
        return

    if game["state"] != "night":
        return

    kill = game["night_kill"]
    save = game["doctor_target"]

    killed_player = None

    if kill and kill != save:

        if kill in game["players"]:

            game["players"][kill]["alive"] = False

            killed_player = game["players"][kill]

    # صبح
    game["state"] = "day"

    if killed_player:

        name = killed_player["name"]

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"""
☀️ صبح شد!

💀 دیشب {name} حذف شد.

🎭 نقش او:
{ROLE_NAMES[killed_player["role"]]}

🗣️ حالا بازیکنان زنده بحث کنند.
"""
        )

    else:

        await context.bot.send_message(
            chat_id=chat_id,
            text="""
☀️ صبح شد!

😮 دیشب کسی حذف نشد!

احتمالاً خرپزشک جان یک نفر را نجات داد.

🗣️ وقت بحث است.
"""
        )

    if await check_kharine_win(
        chat_id,
        context
    ):
        return

    await start_voting(
        chat_id,
        context
    )


# =========================================================
# VOTING
# =========================================================

async def start_voting(chat_id, context):

    game = kharine_games.get(chat_id)

    if not game:
        return

    game["state"] = "voting"
    game["votes"] = {}

    keyboard = []

    for user_id, player in game["players"].items():

        if not player["alive"]:
            continue

        keyboard.append([
            InlineKeyboardButton(
                player["name"],
                callback_data=f"khvote_{chat_id}_{user_id}"
            )
        ])

    await context.bot.send_message(
        chat_id=chat_id,
        text="""
🗳️ زمان رأی‌گیری!

به کسی که فکر می‌کنی خرینه است رأی بده.

هر بازیکن زنده فقط یک رأی دارد.
""",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    context.job_queue.run_once(
        finish_voting_job,
        30,
        data=chat_id
    )


async def finish_voting_job(context):

    chat_id = context.job.data

    await finish_voting(
        chat_id,
        context
    )


async def kh_vote(query, chat_id, target_id):

    try:
        chat_id = int(chat_id)
        target_id = int(target_id)
    except Exception:
        return

    if chat_id not in kharine_games:
        return

    game = kharine_games[chat_id]

    if game["state"] != "voting":

        await query.answer(
            "الان زمان رأی‌گیری نیست!",
            show_alert=True
        )

        return

    voter = query.from_user.id

    if voter not in game["players"]:
        return

    if not game["players"][voter]["alive"]:

        await query.answer(
            "مرده‌ها رأی نمی‌دهند 😂",
            show_alert=True
        )

        return

    game["votes"][voter] = target_id

    await query.answer(
        "🗳️ رأی ثبت شد."
    )

    await query.edit_message_text(
        "🗳️ رأی تو ثبت شد."
    )


# =========================================================
# FINISH VOTING
# =========================================================

async def finish_voting(chat_id, context):

    game = kharine_games.get(chat_id)

    if not game:
        return

    if game["state"] != "voting":
        return

    votes = game["votes"]

    if not votes:

        await context.bot.send_message(
            chat_id=chat_id,
            text="🤷 هیچ رأیی ثبت نشد. روز بعد شروع می‌شود."
        )

        await start_night(
            chat_id,
            context
        )

        return

    counter = Counter(votes.values())

    max_votes = max(counter.values())

    candidates = [
        user_id
        for user_id, count in counter.items()
        if count == max_votes
    ]

    if len(candidates) > 1:

        await context.bot.send_message(
            chat_id=chat_id,
            text="""
🤝 رأی‌گیری مساوی شد!

کسی حذف نشد.

🌙 شب بعد شروع می‌شود.
"""
        )

        await start_night(
            chat_id,
            context
        )

        return

    eliminated_id = candidates[0]

    if eliminated_id not in game["players"]:
        return

    game["players"][eliminated_id]["alive"] = False

    eliminated = game["players"][eliminated_id]

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"""
🗳️ نتیجه رأی‌گیری:

💀 {eliminated["name"]} از بازی حذف شد.

🎭 نقش:
{ROLE_NAMES[eliminated["role"]]}
"""
    )

    if await check_kharine_win(
        chat_id,
        context
    ):
        return

    await start_night(
        chat_id,
        context
    )


# =========================================================
# CHECK WIN
# =========================================================

async def check_kharine_win(chat_id, context):

    game = kharine_games.get(chat_id)

    if not game:
        return True

    alive_players = [
        p
        for p in game["players"].values()
        if p["alive"]
    ]

    kharines = [
        p
        for p in alive_players
        if p["role"] == "kharine"
    ]

    villagers = [
        p
        for p in alive_players
        if p["role"] != "kharine"
    ]

    # خرینه‌ها با برابر شدن تعداد برنده می‌شوند
    if len(kharines) >= len(villagers):

        await end_kharine(
            chat_id,
            context,
            "kharine"
        )

        return True

    # اگر خرینه‌ای باقی نمانده
    if len(kharines) == 0:

        await end_kharine(
            chat_id,
            context,
            "villagers"
        )

        return True

    return False


# =========================================================
# END KHARINE
# =========================================================

async def end_kharine(
    chat_id,
    context,
    winner
):

    game = kharine_games.get(chat_id)

    if not game:
        return

    if winner == "kharine":

        winning_text = """
🐺 خرینه‌ها برنده شدند!

🫏 طویله سقوط کرد!
"""

        winning_role = "kharine"

    else:

        winning_text = """
🏘️ اهالی طویله برنده شدند!

🐺 تمام خرینه‌ها پیدا شدند!
"""

        winning_role = "villagers"

    rewards = []

    for user_id, player in game["players"].items():

        if winner == "kharine":

            if player["role"] == "kharine":

                reward = 500

            else:

                reward = 0

        else:

            if player["role"] != "kharine":

                reward = 300

            else:

                reward = 0

        if reward > 0:

            add_score(
                user_id,
                reward
            )

            rewards.append(
                f"🫏 {player['name']} +{reward}"
            )

    text = winning_text

    text += "\n🏆 جوایز:\n"

    if rewards:

        text += "\n".join(rewards)

    else:

        text += "امتیازی داده نشد."

    text += "\n\n🎭 نقش‌ها:\n"

    for player in game["players"].values():

        status = (
            "❤️ زنده"
            if player["alive"]
            else "💀 حذف شده"
        )

        text += (
            f"{player['name']} — "
            f"{ROLE_NAMES[player['role']]} — "
            f"{status}\n"
        )

    await context.bot.send_message(
        chat_id=chat_id,
        text=text
    )

    del kharine_games[chat_id]


# =========================================================
# BUTTON HANDLER
# =========================================================

async def button_handler(update, context):

    query = update.callback_query

    await query.answer()

    data = query.data

    user = query.from_user

    create_user(user)

    # -----------------------------
    # MAIN MENU
    # -----------------------------

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

        await query.edit_message_text(
            f"""
💰 موجودی

🫏 {get_score(user.id)} پوینت
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
🎁 جایزه گرفتی!

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
                    "🫏 خرینه",
                    callback_data="kharine_info"
                )
            ]
        ]

        await query.edit_message_text(
            """
🎮 بازی‌های خر‌بات

🪨📄✂️ سنگ کاغذ قیچی
🫏 خرینه — بازی گروهی
""",
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

🫏 عر
+10 پوینت

🎁 جایزه
+100 پوینت روزانه

🪨📄✂️ سنگ کاغذ قیچی
بازی با خر‌بات

🫏 شروع خرینه
شروع بازی گروهی
""",
            reply_markup=main_menu()
        )

        return

    # -----------------------------
    # RPS
    # -----------------------------

    if data.startswith("rps_"):

        choice = data.replace(
            "rps_",
            ""
        )

        await play_rps(
            query,
            choice
        )

        return

    # -----------------------------
    # KHARINE
    # -----------------------------

    if data == "kharine_join":

        await join_kharine(query)

        return

    if data == "kharine_leave":

        await leave_kharine(query)

        return

    if data == "kharine_start":

        await begin_kharine(
            query,
            context
        )

        return

    if data.startswith("khkill_"):

        _, chat_id, target_id = data.split("_")

        await kh_kill(
            query,
            chat_id,
            target_id
        )

        return

    if data.startswith("khseer_"):

        _, chat_id, target_id = data.split("_")

        await kh_seer(
            query,
            chat_id,
            target_id
        )

        return

    if data.startswith("khdoctor_"):

        _, chat_id, target_id = data.split("_")

        await kh_doctor(
            query,
            chat_id,
            target_id
        )

        return

    if data.startswith("khvote_"):

        _, chat_id, target_id = data.split("_")

        await kh_vote(
            query,
            chat_id,
            target_id
        )

        return

    if data == "kharine_info":

        await query.edit_message_text(
            """
🫏 خرینه

👥 ۴ تا ۸ بازیکن

🐺 خرینه‌ها
🔮 فال‌خر
🩺 خرپزشک
👨‍🌾 خر‌دار

🌙 شب
☀️ روز
🗳️ رأی‌گیری

🏆 برد خرینه‌ها: +500 پوینت
🏘️ برد اهالی: +300 پوینت

برای شروع، داخل گروه بنویس:

شروع خرینه
"""
        )

        return


# =========================================================
# MESSAGE HANDLER
# =========================================================

async def message_handler(update, context):

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

    # -----------------------------
    # ARR
    # -----------------------------

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

    # -----------------------------
    # PERSIAN COMMANDS
    # -----------------------------

    if text in {
        "پروفایل",
        "امتیاز",
        "امتیاز من"
    }:

        await profile(update, context)
        return

    if text in {
        "موجودی",
        "پوینت",
        "پول"
    }:

        await balance(update, context)
        return

    if text in {
        "جایزه",
        "جایزه روزانه"
    }:

        await daily(update, context)
        return

    if text in {
        "جدول",
        "امتیازات",
        "رتبه",
        "رنک"
    }:

        await leaderboard(update, context)
        return

    if text in {
        "راهنما",
        "کمک",
        "دستورات"
    }:

        await help_command(update, context)
        return

    if text in {
        "بازی",
        "بازی ها",
        "بازی‌ها"
    }:

        keyboard = [
            [
                InlineKeyboardButton(
                    "🪨📄✂️ سنگ کاغذ قیچی",
                    callback_data="start_rps"
                )
            ],
            [
                InlineKeyboardButton(
                    "🫏 خرینه",
                    callback_data="kharine_info"
                )
            ]
        ]

        await update.message.reply_text(
            "🎮 بازی‌های خر‌بات:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return

    # -----------------------------
    # START KHARINE
    # -----------------------------

    if text in {
        "شروع خرینه",
        "خرینه",
        "بازی خرینه"
    }:

        await start_kharine(
            update,
            context
        )

        return


# =========================================================
# MAIN
# =========================================================

def main():

    if not TOKEN:

        print("ERROR: BOT_TOKEN is missing!")

        return

    print("KHARBOT STARTING...")

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # Commands
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

    # Buttons
    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # Persian text
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
