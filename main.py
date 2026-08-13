import os
import sqlite3
import random
import time
import asyncio
from datetime import datetime, date

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
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_FILE = "kharbot.db"

ARR_SCORE = 10
ARR_COOLDOWN = 30
DAILY_BASE = 100

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
تو «خر‌بات» هستی 🫏😂

شخصیتی بامزه، رفیق، شوخ‌طبع و اهل کل‌کل داری.
فارسی صحبت کن.
گاهی از عبارت «تورکعلی 😂» استفاده کن.
جواب‌ها خیلی خشک و رسمی نباشند.
اگر کاربر شوخی کرد، با شوخی جواب بده.
اگر سؤال جدی پرسید، جواب مفید بده ولی همچنان شخصیت خر‌بات را حفظ کن.
"""

async def ask_ai(prompt: str) -> str:
    if not ai_client:
        return "🫏 تورکعلی! کلید GROQ_API_KEY تنظیم نشده 😂"

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
        return "🫏 تورکعلی، مغزم هنگ کرد 😂 دوباره بپرس."


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

db.row_factory = sqlite3.Row


def db_execute(query, params=(), commit=False):
    cur = db.cursor()
    cur.execute(query, params)

    if commit:
        db.commit()

    return cur


def init_db():

    db_execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT DEFAULT '',
        first_name TEXT DEFAULT '',

        coins INTEGER DEFAULT 0,

        xp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1,

        reputation INTEGER DEFAULT 50,

        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        draws INTEGER DEFAULT 0,

        games_played INTEGER DEFAULT 0,
        ai_messages INTEGER DEFAULT 0,
        arr_count INTEGER DEFAULT 0,

        daily_last INTEGER DEFAULT 0,
        streak INTEGER DEFAULT 0,

        title TEXT DEFAULT '',

        q_arr INTEGER DEFAULT 0,
        q_game INTEGER DEFAULT 0,
        q_ai INTEGER DEFAULT 0,

        banned INTEGER DEFAULT 0,
        muted INTEGER DEFAULT 0,

        created_at TEXT DEFAULT ''
    )
    """, commit=True)

    db_execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        item_id TEXT,
        item_name TEXT,
        quantity INTEGER DEFAULT 1
    )
    """, commit=True)

    db_execute("""
    CREATE TABLE IF NOT EXISTS achievements (
        id TEXT PRIMARY KEY,
        name TEXT,
        description TEXT,
        reward INTEGER DEFAULT 0
    )
    """, commit=True)

    db_execute("""
    CREATE TABLE IF NOT EXISTS user_achievements (
        user_id INTEGER,
        achievement_id TEXT,
        claimed_at TEXT,
        PRIMARY KEY(user_id, achievement_id)
    )
    """, commit=True)

    db_execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        reason TEXT,
        created_at TEXT
    )
    """, commit=True)

    db_execute("""
    CREATE TABLE IF NOT EXISTS clans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        owner_id INTEGER,
        coins INTEGER DEFAULT 0,
        created_at TEXT
    )
    """, commit=True)

    db_execute("""
    CREATE TABLE IF NOT EXISTS clan_members (
        clan_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY(clan_id, user_id)
    )
    """, commit=True)

    achievements = [
        (
            "first_game",
            "🎮 اولین بازی",
            "اولین بازی خود را انجام بده",
            100
        ),
        (
            "first_win",
            "🏆 اولین برد",
            "اولین برد خود را کسب کن",
            200
        ),
        (
            "ten_wins",
            "🔥 ده برد",
            "۱۰ بار برنده شو",
            500
        ),
        (
            "rich",
            "💰 پولدار",
            "به ۱۰ هزار سکه برس",
            1000
        ),
        (
            "arr_100",
            "🫏 استاد عر",
            "۱۰۰ بار عر بزن",
            500
        ),
        (
            "ai_100",
            "🤖 رفیق خر‌بات",
            "۱۰۰ بار با خر‌بات صحبت کن",
            500
        ),
        (
            "games_100",
            "🎮 گیمر",
            "۱۰۰ بازی انجام بده",
            1000
        ),
    ]

    for ach in achievements:
        db_execute("""
        INSERT OR IGNORE INTO achievements
        (id, name, description, reward)
        VALUES (?, ?, ?, ?)
        """, ach)

    db.commit()


init_db()


# =========================================================
# USER SYSTEM
# =========================================================

def ensure_user(user):

    if not user:
        return

    row = db_execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user.id,)
    ).fetchone()

    if not row:
        db_execute("""
        INSERT INTO users
        (user_id, username, first_name, created_at)
        VALUES (?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "Player",
            datetime.now().isoformat()
        ), commit=True)

    else:
        db_execute("""
        UPDATE users
        SET username = ?, first_name = ?
        WHERE user_id = ?
        """, (
            user.username or "",
            user.first_name or "Player",
            user.id
        ), commit=True)


def get_user(user_id):

    return db_execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()


def coins(user_id):

    row = get_user(user_id)
    return row["coins"] if row else 0


def add_coins(user_id, amount, reason="system"):

    if amount == 0:
        return

    db_execute("""
    UPDATE users
    SET coins = MAX(0, coins + ?)
    WHERE user_id = ?
    """, (amount, user_id), commit=True)

    db_execute("""
    INSERT INTO transactions
    (user_id, amount, reason, created_at)
    VALUES (?, ?, ?, ?)
    """, (
        user_id,
        amount,
        reason,
        datetime.now().isoformat()
    ), commit=True)


def remove_coins(user_id, amount, reason="game"):

    if amount <= 0:
        return False

    if coins(user_id) < amount:
        return False

    add_coins(
        user_id,
        -amount,
        reason
    )

    return True


# =========================================================
# XP / LEVEL
# =========================================================

def xp_required(level):
    return level * 250


def add_xp(user_id, amount):

    row = get_user(user_id)

    if not row:
        return

    xp = row["xp"] + amount
    level = row["level"]

    leveled = False

    while xp >= xp_required(level):
        xp -= xp_required(level)
        level += 1
        leveled = True

    db_execute("""
    UPDATE users
    SET xp = ?, level = ?
    WHERE user_id = ?
    """, (
        xp,
        level,
        user_id
    ), commit=True)

    return leveled


# =========================================================
# STATS
# =========================================================

def game_result(
    user_id,
    result,
    reward=0
):

    if result == "win":
        db_execute("""
        UPDATE users
        SET wins = wins + 1,
            games_played = games_played + 1,
            reputation = MIN(100, reputation + 1)
        WHERE user_id = ?
        """, (user_id,), commit=True)

        add_xp(user_id, 40)

        if reward:
            add_coins(
                user_id,
                reward,
                "game_win"
            )

    elif result == "loss":

        db_execute("""
        UPDATE users
        SET losses = losses + 1,
            games_played = games_played + 1,
            reputation = MAX(0, reputation - 1)
        WHERE user_id = ?
        """, (user_id,), commit=True)

        add_xp(user_id, 10)

    else:

        db_execute("""
        UPDATE users
        SET draws = draws + 1,
            games_played = games_played + 1
        WHERE user_id = ?
        """, (user_id,), commit=True)

        add_xp(user_id, 20)


# =========================================================
# ACHIEVEMENTS
# =========================================================

async def check_achievements(bot, user_id):

    row = get_user(user_id)

    if not row:
        return

    checks = {
        "first_game": row["games_played"] >= 1,
        "first_win": row["wins"] >= 1,
        "ten_wins": row["wins"] >= 10,
        "rich": row["coins"] >= 10000,
        "arr_100": row["arr_count"] >= 100,
        "ai_100": row["ai_messages"] >= 100,
        "games_100": row["games_played"] >= 100,
    }

    for ach_id, condition in checks.items():

        if not condition:
            continue

        exists = db_execute("""
        SELECT 1
        FROM user_achievements
        WHERE user_id = ? AND achievement_id = ?
        """, (
            user_id,
            ach_id
        )).fetchone()

        if exists:
            continue

        ach = db_execute("""
        SELECT *
        FROM achievements
        WHERE id = ?
        """, (ach_id,)).fetchone()

        if not ach:
            continue

        db_execute("""
        INSERT INTO user_achievements
        (user_id, achievement_id, claimed_at)
        VALUES (?, ?, ?)
        """, (
            user_id,
            ach_id,
            datetime.now().isoformat()
        ), commit=True)

        add_coins(
            user_id,
            ach["reward"],
            f"achievement:{ach_id}"
        )

        try:
            await bot.send_message(
                user_id,
                f"""
🏆 **دستاورد جدید!**

{ach["name"]}

📜 {ach["description"]}

🎁 جایزه:
+{ach["reward"]} 🫏
"""
            )
        except Exception:
            pass


# =========================================================
# MENUS
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
                "🛒 فروشگاه",
                callback_data="store"
            )
        ],
        [
            InlineKeyboardButton(
                "🏆 رتبه‌بندی",
                callback_data="leaderboard"
            ),
            InlineKeyboardButton(
                "🏅 دستاوردها",
                callback_data="achievements"
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
                "🔥 استریک",
                callback_data="streak"
            ),
            InlineKeyboardButton(
                "🏰 طویله‌ها",
                callback_data="clans"
            )
        ],
        [
            InlineKeyboardButton(
                "🤖 خر‌بات AI",
                callback_data="ai_help"
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


def games_menu():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💥 انفجار",
                callback_data="game_crash"
            ),
            InlineKeyboardButton(
                "🪙 شیر یا خط",
                callback_data="game_coin"
            )
        ],
        [
            InlineKeyboardButton(
                "🎲 تاس",
                callback_data="game_dice"
            ),
            InlineKeyboardButton(
                "🎰 اسلات",
                callback_data="game_slots"
            )
        ],
        [
            InlineKeyboardButton(
                "💣 Mines",
                callback_data="game_mines"
            ),
            InlineKeyboardButton(
                "🃏 Blackjack",
                callback_data="game_blackjack"
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 حدس عدد",
                callback_data="game_guess"
            ),
            InlineKeyboardButton(
                "🧠 Quiz",
                callback_data="game_quiz"
            )
        ],
        [
            InlineKeyboardButton(
                "🪨 سنگ‌کاغذقیچی",
                callback_data="game_rps"
            ),
            InlineKeyboardButton(
                "❌ دوز",
                callback_data="game_ttt"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 منوی اصلی",
                callback_data="main"
            )
        ]
    ])


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    await update.message.reply_text(
        """
🫏 **خر‌بات وارد شد!**

به قلمرو خرها خوش اومدی 😂

🔥 بازی کن
💰 سکه جمع کن
🏆 Level بگیر
👑 لقب باز کن
🤖 با خر‌بات حرف بزن

و یادت نره...

**تورکعلی 😂🫏**
""",
        reply_markup=main_menu(user.id)
    )


# =========================================================
# PROFILE
# =========================================================

async def show_profile(update, context):

    user = update.effective_user

    ensure_user(user)

    row = get_user(user.id)

    title = row["title"]

    if not title:
        title = (
            "👑 مالک"
            if user.id == ADMIN_ID
            else "🫏 خر معمولی"
        )

    text = f"""
👤 **پروفایل**

━━━━━━━━━━━━

🏷️ لقب:
{title}

📝 نام:
{row["first_name"]}

🆔 ID:
`{user.id}`

💰 موجودی:
**{row["coins"]}** 🫏

⭐ Level:
**{row["level"]}**

✨ XP:
**{row["xp"]}/{xp_required(row["level"])}**

🏆 برد:
{row["wins"]}

💀 باخت:
{row["losses"]}

🤝 مساوی:
{row["draws"]}

🎮 بازی:
{row["games_played"]}

🔥 Streak:
{row["streak"]}

⭐ Reputation:
{row["reputation"]}/100
"""

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_menu(user.id)
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=main_menu(user.id)
        )


# =========================================================
# DAILY / STREAK
# =========================================================

async def daily(update, context):

    user = update.effective_user

    ensure_user(user)

    row = get_user(user.id)

    now = int(time.time())

    if row["daily_last"]:

        diff = now - row["daily_last"]

        if diff < 86400:

            remaining = 86400 - diff
            hours = remaining // 3600

            text = f"""
⏳ **جایزه روزانه**

قبلاً گرفتی!

⏰ {hours} ساعت دیگه برگرد.
🔥 Streak فعلی: {row["streak"]}
"""

            await update.message.reply_text(text)
            return

        if diff <= 172800:
            streak = row["streak"] + 1
        else:
            streak = 1

    else:
        streak = 1

    reward = DAILY_BASE + (streak * 25)

    db_execute("""
    UPDATE users
    SET daily_last = ?,
        streak = ?
    WHERE user_id = ?
    """, (
        now,
        streak,
        user.id
    ), commit=True)

    add_coins(
        user.id,
        reward,
        "daily"
    )

    add_xp(user.id, 25)

    await check_achievements(
        context.bot,
        user.id
    )

    await update.message.reply_text(
        f"""
🎁 **جایزه روزانه**

💰 +{reward} 🫏

🔥 Streak:
**{streak} روز**

تورکعلی میگه فردا هم بیا 😂
"""
    )


# =========================================================
# LEADERBOARD
# =========================================================

async def leaderboard(update, context):

    rows = db_execute("""
    SELECT first_name, coins, level, wins
    FROM users
    WHERE banned = 0
    ORDER BY coins DESC
    LIMIT 10
    """).fetchall()

    text = "🏆 **برترین خرها**\n\n"

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    for i, row in enumerate(rows):

        medal = medals[i] if i < 3 else f"{i+1}."

        text += (
            f"{medal} {row['first_name']} "
            f"— 💰 {row['coins']} "
            f"| ⭐ Lv.{row['level']}\n"
        )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_menu(update.effective_user.id)
        )
    else:
        await update.message.reply_text(text)


# =========================================================
# STORE
# =========================================================

STORE = {
    "title_boss": {
        "name": "🔥 لقب خر بزرگ",
        "price": 1000,
        "type": "title",
        "value": "🔥 خر بزرگ"
    },

    "title_king": {
        "name": "👑 سلطان طویله",
        "price": 2500,
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
        "name": "🍀 کارت شانس",
        "price": 500,
        "type": "item"
    },

    "double_xp": {
        "name": "⚡ دوبرابر XP",
        "price": 800,
        "type": "item"
    },

    "free_bet": {
        "name": "🎟️ Free Bet",
        "price": 1000,
        "type": "item"
    }
}


def store_keyboard():

    rows = []

    for item_id, item in STORE.items():

        rows.append([
            InlineKeyboardButton(
                f"{item['name']} — {item['price']} 🫏",
                callback_data=f"buy:{item_id}"
            )
        ])

    rows.append([
        InlineKeyboardButton(
            "🔙 برگشت",
            callback_data="main"
        )
    ])

    return InlineKeyboardMarkup(rows)


async def show_store(update, context):

    user = update.effective_user

    ensure_user(user)

    text = f"""
🛒 **فروشگاه خر‌بات**

💰 موجودی:
**{coins(user.id)}** 🫏

آیتم مورد نظرت رو انتخاب کن:
"""

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=store_keyboard()
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=store_keyboard()
        )


async def buy_item(query, item_id):

    user = query.from_user

    item = STORE.get(item_id)

    if not item:
        return

    if not remove_coins(
        user.id,
        item["price"],
        f"shop:{item_id}"
    ):

        await query.answer(
            "❌ موجودی کافی نیست!",
            show_alert=True
        )

        return

    if item["type"] == "title":

        db_execute("""
        UPDATE users
        SET title = ?
        WHERE user_id = ?
        """, (
            item["value"],
            user.id
        ), commit=True)

    else:

        row = db_execute("""
        SELECT quantity
        FROM inventory
        WHERE user_id = ?
        AND item_id = ?
        """, (
            user.id,
            item_id
        )).fetchone()

        if row:

            db_execute("""
            UPDATE inventory
            SET quantity = quantity + 1
            WHERE user_id = ?
            AND item_id = ?
            """, (
                user.id,
                item_id
            ), commit=True)

        else:

            db_execute("""
            INSERT INTO inventory
            (user_id, item_id, item_name, quantity)
            VALUES (?, ?, ?, 1)
            """, (
                user.id,
                item_id,
                item["name"]
            ), commit=True)

    await query.answer(
        "✅ خرید انجام شد!",
        show_alert=True
    )

    await query.edit_message_text(
        f"""
🎉 **خرید موفق!**

{item["name"]}

💰 موجودی:
**{coins(user.id)}** 🫏
""",
        reply_markup=store_keyboard()
    )


# =========================================================
# INVENTORY
# =========================================================

async def inventory(update, context):

    user = update.effective_user

    ensure_user(user)

    rows = db_execute("""
    SELECT item_name, quantity
    FROM inventory
    WHERE user_id = ?
    AND quantity > 0
    """, (user.id,)).fetchall()

    if not rows:

        text = "🎒 **انبار خالیه!**"

    else:

        text = "🎒 **انبار من**\n\n"

        for row in rows:

            text += (
                f"🔹 {row['item_name']} "
                f"× {row['quantity']}\n"
            )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_menu(user.id)
        )

    else:

        await update.message.reply_text(
            text,
            reply_markup=main_menu(user.id)
        )


# =========================================================
# ACHIEVEMENTS
# =========================================================

async def achievements(update, context):

    user = update.effective_user

    rows = db_execute("""
    SELECT
        a.*,
        CASE
            WHEN ua.user_id IS NULL THEN 0
            ELSE 1
        END AS unlocked
    FROM achievements a
    LEFT JOIN user_achievements ua
    ON a.id = ua.achievement_id
    AND ua.user_id = ?
    """, (user.id,)).fetchall()

    text = "🏅 **دستاوردها**\n\n"

    for row in rows:

        icon = "✅" if row["unlocked"] else "🔒"

        text += (
            f"{icon} {row['name']}\n"
            f"   {row['description']}\n"
            f"   🎁 {row['reward']} 🫏\n\n"
        )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_menu(user.id)
        )

    else:

        await update.message.reply_text(text)


# =========================================================
# QUESTS
# =========================================================

async def quests(update, context):

    user = update.effective_user

    row = get_user(user.id)

    text = f"""
🎯 **ماموریت‌های امروز**

🫏 عر زدن:
{row["q_arr"]}/3

🎮 بازی:
{row["q_game"]}/2

🤖 AI:
{row["q_ai"]}/3

🎁 هر ماموریت کامل:
+100 🫏
"""

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_menu(user.id)
        )

    else:

        await update.message.reply_text(
            text,
            reply_markup=main_menu(user.id)
        )


def quest_progress(user_id, qtype):

    column = {
        "arr": "q_arr",
        "game": "q_game",
        "ai": "q_ai"
    }.get(qtype)

    if not column:
        return

    row = get_user(user_id)

    old = row[column]

    if old >= 3:
        return

    db_execute(
        f"""
        UPDATE users
        SET {column} = {column} + 1
        WHERE user_id = ?
        """,
        (user_id,),
        commit=True
    )

    if old + 1 == 3:

        add_coins(
            user_id,
            100,
            f"quest:{qtype}"
        )


# =========================================================
# SIMPLE BET HELPER
# =========================================================

def valid_bet(user_id, bet):

    return (
        isinstance(bet, int)
        and bet > 0
        and coins(user_id) >= bet
    )


# =========================================================
# COIN FLIP
# =========================================================

async def coin_game(query, bet, choice):

    user = query.from_user

    if not valid_bet(user.id, bet):

        await query.answer(
            "❌ شرط معتبر نیست.",
            show_alert=True
        )

        return

    remove_coins(
        user.id,
        bet,
        "coin_bet"
    )

    result = random.choice([
        "heads",
        "tails"
    ])

    names = {
        "heads": "🦁 شیر",
        "tails": "🪙 خط"
    }

    if choice == result:

        win = bet * 2

        add_coins(
            user.id,
            win,
            "coin_win"
        )

        game_result(
            user.id,
            "win"
        )

        text = f"""
🪙 **شیر یا خط**

تو: {names[choice]}
خر‌بات: {names[result]}

🎉 **بردی!**
+{win} 🫏
"""

    else:

        game_result(
            user.id,
            "loss"
        )

        text = f"""
🪙 **شیر یا خط**

تو: {names[choice]}
خر‌بات: {names[result]}

💀 **باختی!**
-{bet} 🫏
"""

    quest_progress(
        user.id,
        "game"
    )

    await query.edit_message_text(text)


# =========================================================
# DICE
# =========================================================

async def dice_game(query, bet):

    user = query.from_user

    if not valid_bet(user.id, bet):

        await query.answer(
            "❌ شرط معتبر نیست.",
            show_alert=True
        )

        return

    remove_coins(
        user.id,
        bet,
        "dice_bet"
    )

    player = random.randint(1, 6)
    bot = random.randint(1, 6)

    if player > bot:

        win = bet * 2

        add_coins(
            user.id,
            win,
            "dice_win"
        )

        game_result(
            user.id,
            "win"
        )

        result = f"🎉 **بردی!** +{win}"

    elif player < bot:

        game_result(
            user.id,
            "loss"
        )

        result = f"💀 **باختی!** -{bet}"

    else:

        add_coins(
            user.id,
            bet,
            "dice_draw"
        )

        game_result(
            user.id,
            "draw"
        )

        result = "🤝 مساوی!"

    await query.edit_message_text(
        f"""
🎲 **تاس**

👤 تو: **{player}**
🤖 خر‌بات: **{bot}**

{result}
"""
    )


# =========================================================
# SLOTS
# =========================================================

SLOT_SYMBOLS = [
    "🍒",
    "🍋",
    "🔔",
    "⭐",
    "💎",
    "7️⃣"
]


async def slots_game(query, bet):

    user = query.from_user

    if not valid_bet(user.id, bet):

        await query.answer(
            "❌ شرط معتبر نیست.",
            show_alert=True
        )

        return

    remove_coins(
        user.id,
        bet,
        "slots_bet"
    )

    result = [
        random.choice(SLOT_SYMBOLS)
        for _ in range(3)
    ]

    if result[0] == result[1] == result[2]:

        if result[0] == "7️⃣":
            multiplier = 10
        elif result[0] == "💎":
            multiplier = 7
        else:
            multiplier = 5

        win = bet * multiplier

        add_coins(
            user.id,
            win,
            "slots_win"
        )

        game_result(
            user.id,
            "win"
        )

        msg = f"🎉 **جک‌پات! +{win}** 🫏"

    elif (
        result[0] == result[1]
        or result[1] == result[2]
        or result[0] == result[2]
    ):

        win = bet * 2

        add_coins(
            user.id,
            win,
            "slots_pair"
        )

        game_result(
            user.id,
            "win"
        )

        msg = f"🔥 **دو تا یکی شد! +{win}**"

    else:

        game_result(
            user.id,
            "loss"
        )

        msg = f"💀 باختی! -{bet}"

    await query.edit_message_text(
        f"""
🎰 **اسلات خر‌بات**

| {' | '.join(result)} |

{msg}
"""
    )


# =========================================================
# GUESS NUMBER
# =========================================================

guess_games = {}


async def start_guess(query, bet):

    user = query.from_user

    if not valid_bet(user.id, bet):

        await query.answer(
            "❌ شرط معتبر نیست.",
            show_alert=True
        )

        return

    remove_coins(
        user.id,
        bet,
        "guess_bet"
    )

    number = random.randint(1, 10)

    guess_games[user.id] = {
        "number": number,
        "bet": bet
    }

    keyboard = []

    for start in range(1, 11, 5):

        keyboard.append([
            InlineKeyboardButton(
                str(i),
                callback_data=f"guess:{i}"
            )
            for i in range(
                start,
                min(start + 5, 11)
            )
        ])

    await query.edit_message_text(
        """
🎯 **حدس عدد**

خر‌بات یک عدد بین ۱ تا ۱۰ انتخاب کرده.

حدست رو بزن:
""",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_guess(query, number):

    user = query.from_user

    game = guess_games.get(user.id)

    if not game:
        return

    target = game["number"]
    bet = game["bet"]

    del guess_games[user.id]

    if number == target:

        win = bet * 5

        add_coins(
            user.id,
            win,
            "guess_win"
        )

        game_result(
            user.id,
            "win"
        )

        text = f"""
🎯 عدد خر‌بات: **{target}**

🎉 **درست حدس زدی!**
+{win} 🫏
"""

    else:

        game_result(
            user.id,
            "loss"
        )

        text = f"""
🎯 عدد خر‌بات: **{target}**

💀 اشتباه بود!
-{bet} 🫏
"""

    await query.edit_message_text(text)


# =========================================================
# CRASH
# =========================================================

crash_games = {}


def crash_multiplier():

    value = random.uniform(1.2, 8)

    return round(value, 1)


async def start_crash(query, bet):

    user = query.from_user

    if not valid_bet(user.id, bet):

        await query.answer(
            "❌ شرط معتبر نیست.",
            show_alert=True
        )

        return

    remove_coins(
        user.id,
        bet,
        "crash_bet"
    )

    point = crash_multiplier()

    crash_games[user.id] = {
        "bet": bet,
        "point": point,
        "current": 1.0
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📈 +0.5x",
                callback_data="crash_next"
            )
        ],
        [
            InlineKeyboardButton(
                "💰 Cash Out",
                callback_data="crash_cash"
            )
        ]
    ])

    await query.edit_message_text(
        f"""
💥 **انفجار**

💵 شرط: {bet}

📈 ضریب:
**1.0x**

قبل از انفجار برداشت کن!
""",
        reply_markup=keyboard
    )


async def crash_next(query):

    user = query.from_user

    game = crash_games.get(user.id)

    if not game:
        return

    game["current"] += 0.5

    if game["current"] >= game["point"]:

        del crash_games[user.id]

        game_result(
            user.id,
            "loss"
        )

        await query.edit_message_text(
            f"""
💥 **بـوووم!**

ضریب انفجار:
**{game["point"]}x**

💀 باختی!
"""
        )

        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📈 +0.5x",
                callback_data="crash_next"
            )
        ],
        [
            InlineKeyboardButton(
                "💰 Cash Out",
                callback_data="crash_cash"
            )
        ]
    ])

    await query.edit_message_text(
        f"""
💥 **انفجار**

📈 ضریب:
**{game["current"]:.1f}x**

💰 برداشت فعلی:
**{int(game["bet"] * game["current"])}**
""",
        reply_markup=keyboard
    )


async def crash_cash(query):

    user = query.from_user

    game = crash_games.get(user.id)

    if not game:
        return

    win = int(
        game["bet"] *
        game["current"]
    )

    del crash_games[user.id]

    add_coins(
        user.id,
        win,
        "crash_win"
    )

    game_result(
        user.id,
        "win"
    )

    await query.edit_message_text(
        f"""
💰 **Cash Out موفق**

📈 ضریب:
{game["current"]:.1f}x

🎁 دریافت:
**+{win}** 🫏
"""
    )


# =========================================================
# RPS
# =========================================================

RPS = {
    "stone": "🪨",
    "paper": "📄",
    "scissors": "✂️"
}


def rps_winner(a, b):

    if a == b:
        return "draw"

    if (
        (a == "stone" and b == "scissors")
        or
        (a == "paper" and b == "stone")
        or
        (a == "scissors" and b == "paper")
    ):
        return "win"

    return "loss"


async def rps_game(query, bet, choice):

    user = query.from_user

    if not valid_bet(user.id, bet):
        await query.answer(
            "❌ شرط معتبر نیست.",
            show_alert=True
        )
        return

    remove_coins(
        user.id,
        bet,
        "rps_bet"
    )

    bot_choice = random.choice(
        list(RPS.keys())
    )

    result = rps_winner(
        choice,
        bot_choice
    )

    if result == "win":

        win = bet * 2

        add_coins(
            user.id,
            win,
            "rps_win"
        )

        game_result(
            user.id,
            "win"
        )

        msg = f"🎉 بردی! +{win}"

    elif result == "loss":

        game_result(
            user.id,
            "loss"
        )

        msg = f"💀 باختی! -{bet}"

    else:

        add_coins(
            user.id,
            bet,
            "rps_draw"
        )

        game_result(
            user.id,
            "draw"
        )

        msg = "🤝 مساوی!"

    await query.edit_message_text(
        f"""
🪨📄✂️ **سنگ کاغذ قیچی**

👤 تو: {RPS[choice]}
🤖 خر‌بات: {RPS[bot_choice]}

{msg}
"""
    )


# =========================================================
# BLACKJACK
# =========================================================

blackjack_games = {}


def card_value(cards):

    total = 0
    aces = 0

    for card in cards:

        if card in ["J", "Q", "K"]:
            total += 10

        elif card == "A":
            total += 11
            aces += 1

        else:
            total += int(card)

    while total > 21 and aces:
        total -= 10
        aces -= 1

    return total


CARDS = [
    "2", "3", "4", "5", "6", "7",
    "8", "9", "10", "J", "Q", "K", "A"
]


async def blackjack_start(query, bet):

    user = query.from_user

    if not valid_bet(user.id, bet):

        await query.answer(
            "❌ شرط معتبر نیست.",
            show_alert=True
        )

        return

    remove_coins(
        user.id,
        bet,
        "blackjack_bet"
    )

    player = [
        random.choice(CARDS),
        random.choice(CARDS)
    ]

    dealer = [
        random.choice(CARDS),
        random.choice(CARDS)
    ]

    blackjack_games[user.id] = {
        "bet": bet,
        "player": player,
        "dealer": dealer
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🃏 کارت بکش",
                callback_data="bj_hit"
            ),
            InlineKeyboardButton(
                "✋ بایست",
                callback_data="bj_stand"
            )
        ]
    ])

    await query.edit_message_text(
        f"""
🃏 **Blackjack**

👤 کارت‌های تو:
{' '.join(player)}

امتیاز:
**{card_value(player)}**

🤖 کارت خر‌بات:
{dealer[0]} ❓
""",
        reply_markup=keyboard
    )


async def blackjack_hit(query):

    user = query.from_user

    game = blackjack_games.get(user.id)

    if not game:
        return

    game["player"].append(
        random.choice(CARDS)
    )

    value = card_value(
        game["player"]
    )

    if value > 21:

        del blackjack_games[user.id]

        game_result(
            user.id,
            "loss"
        )

        await query.edit_message_text(
            f"""
🃏 **Blackjack**

کارت‌ها:
{' '.join(game["player"])}

💀 امتیاز: **{value}**

Bust شدی!
"""
        )

        return

    await query.edit_message_text(
        f"""
🃏 **Blackjack**

کارت‌ها:
{' '.join(game["player"])}

امتیاز:
**{value}**
""",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🃏 کارت بکش",
                    callback_data="bj_hit"
                ),
                InlineKeyboardButton(
                    "✋ بایست",
                    callback_data="bj_stand"
                )
            ]
        ])
    )


async def blackjack_stand(query):

    user = query.from_user

    game = blackjack_games.get(user.id)

    if not game:
        return

    player_value = card_value(
        game["player"]
    )

    dealer = game["dealer"]

    while card_value(dealer) < 17:
        dealer.append(
            random.choice(CARDS)
        )

    dealer_value = card_value(dealer)

    del blackjack_games[user.id]

    if (
        dealer_value > 21
        or player_value > dealer_value
    ):

        win = game["bet"] * 2

        add_coins(
            user.id,
            win,
            "blackjack_win"
        )

        game_result(
            user.id,
            "win"
        )

        result = f"🎉 بردی! +{win}"

    elif player_value == dealer_value:

        add_coins(
            user.id,
            game["bet"],
            "blackjack_draw"
        )

        game_result(
            user.id,
            "draw"
        )

        result = "🤝 مساوی!"

    else:

        game_result(
            user.id,
            "loss"
        )

        result = f"💀 باختی! -{game['bet']}"

    await query.edit_message_text(
        f"""
🃏 **Blackjack**

👤 تو:
{' '.join(game["player"])}
= {player_value}

🤖 خر‌بات:
{' '.join(dealer)}
= {dealer_value}

{result}
"""
    )


# =========================================================
# MINES
# =========================================================

mines_games = {}


async def mines_start(query, bet):

    user = query.from_user

    if not valid_bet(user.id, bet):
        await query.answer(
            "❌ شرط معتبر نیست.",
            show_alert=True
        )
        return

    remove_coins(
        user.id,
        bet,
        "mines_bet"
    )

    bombs = random.sample(
        range(9),
        2
    )

    mines_games[user.id] = {
        "bet": bet,
        "bombs": bombs,
        "opened": [],
        "multiplier": 1.0
    }

    await render_mines(query, user.id)


async def render_mines(query, user_id):

    game = mines_games.get(user_id)

    if not game:
        return

    buttons = []

    for i in range(9):

        if i in game["opened"]:
            label = "💎"
        else:
            label = "⬜"

        buttons.append(
            InlineKeyboardButton(
                label,
                callback_data=f"mine:{i}"
            )
        )

    keyboard = [
        buttons[0:3],
        buttons[3:6],
        buttons[6:9],
        [
            InlineKeyboardButton(
                f"💰 برداشت {int(game['bet'] * game['multiplier'])}",
                callback_data="mine_cash"
            )
        ]
    ]

    await query.edit_message_text(
        f"""
💣 **Mines**

💵 شرط:
{game["bet"]}

📈 ضریب:
{game["multiplier"]:.1f}x

یک خانه انتخاب کن.
""",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def mines_pick(query, position):

    user = query.from_user

    game = mines_games.get(user.id)

    if not game:
        return

    if position in game["opened"]:
        return

    if position in game["bombs"]:

        del mines_games[user.id]

        game_result(
            user.id,
            "loss"
        )

        await query.edit_message_text(
            """
💣 **بـــوم!**

مین رو پیدا کردی 😂

💀 باختی.
"""
        )

        return

    game["opened"].append(position)

    game["multiplier"] += 0.4

    if len(game["opened"]) == 7:

        win = int(
            game["bet"] *
            game["multiplier"]
        )

        add_coins(
            user.id,
            win,
            "mines_win"
        )

        del mines_games[user.id]

        game_result(
            user.id,
            "win"
        )

        await query.edit_message_text(
            f"""
💣 **Mines تمام شد!**

🎉 جایزه:
**+{win}** 🫏
"""
        )

        return

    await render_mines(
        query,
        user.id
    )


async def mines_cash(query):

    user = query.from_user

    game = mines_games.get(user.id)

    if not game:
        return

    win = int(
        game["bet"] *
        game["multiplier"]
    )

    del mines_games[user.id]

    add_coins(
        user.id,
        win,
        "mines_cashout"
    )

    game_result(
        user.id,
        "win"
    )

    await query.edit_message_text(
        f"""
💰 **Mines Cash Out**

📈 ضریب:
{game["multiplier"]:.1f}x

🎁 دریافت:
**+{win}**
"""
    )


# =========================================================
# QUIZ
# =========================================================

QUIZ = [
    (
        "پایتخت ایران کدام است؟",
        ["تهران", "شیراز", "تبریز", "کرمان"],
        0
    ),
    (
        "5 × 5 چند است؟",
        ["15", "20", "25", "30"],
        2
    ),
    (
        "بزرگترین سیاره منظومه شمسی؟",
        ["زمین", "مریخ", "زحل", "مشتری"],
        3
    ),
    (
        "کدام حیوان خر است؟ 😂",
        ["خر", "گربه", "ماهی", "مرغ"],
        0
    )
]

quiz_games = {}


async def start_quiz(query):

    user = query.from_user

    question = random.choice(QUIZ)

    quiz_games[user.id] = question

    keyboard = []

    for i, option in enumerate(question[1]):

        keyboard.append([
            InlineKeyboardButton(
                option,
                callback_data=f"quiz:{i}"
            )
        ])

    await query.edit_message_text(
        f"""
🧠 **Quiz خر‌بات**

{question[0]}
""",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def answer_quiz(query, answer):

    user = query.from_user

    question = quiz_games.get(user.id)

    if not question:
        return

    del quiz_games[user.id]

    correct = question[2]

    if answer == correct:

        add_coins(
            user.id,
            100,
            "quiz_win"
        )

        add_xp(
            user.id,
            50
        )

        game_result(
            user.id,
            "win"
        )

        text = """
🎉 **درست جواب دادی!**

+100 🫏
"""

    else:

        game_result(
            user.id,
            "loss"
        )

        text = f"""
💀 غلط بود!

جواب درست:
**{question[1][correct]}**
"""

    await query.edit_message_text(text)


# =========================================================
# TIC TAC TOE
# =========================================================

ttt_games = {}


def ttt_keyboard(game_id, board):

    rows = []

    for r in range(3):

        row = []

        for c in range(3):

            i = r * 3 + c

            row.append(
                InlineKeyboardButton(
                    board[i] or "⬜",
                    callback_data=f"ttt:{game_id}:{i}"
                )
            )

        rows.append(row)

    return InlineKeyboardMarkup(rows)


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

    for a,b,c in lines:

        if (
            board[a]
            and board[a] == board[b]
            and board[b] == board[c]
        ):
            return board[a]

    if all(board):
        return "draw"

    return None


async def start_ttt(query, bet):

    user = query.from_user

    if not valid_bet(user.id, bet):
        await query.answer(
            "❌ شرط معتبر نیست.",
            show_alert=True
        )
        return

    remove_coins(
        user.id,
        bet,
        "ttt_bet"
    )

    game_id = str(
        random.randint(
            100000,
            999999
        )
    )

    ttt_games[game_id] = {
        "user": user.id,
        "bet": bet,
        "board": [""] * 9
    }

    await query.edit_message_text(
        """
❌⭕ **دوز**

تو ❌ هستی.

نوبت تو:
""",
        reply_markup=ttt_keyboard(
            game_id,
            [""] * 9
        )
    )


async def ttt_move(query, game_id, position):

    user = query.from_user

    game = ttt_games.get(game_id)

    if not game or game["user"] != user.id:
        return

    board = game["board"]

    if board[position]:
        return

    board[position] = "❌"

    winner = ttt_winner(board)

    if winner:
        await finish_ttt(
            query,
            game_id,
            winner
        )
        return

    empty = [
        i for i,v in enumerate(board)
        if not v
    ]

    if empty:

        board[random.choice(empty)] = "⭕"

    winner = ttt_winner(board)

    if winner:

        await finish_ttt(
            query,
            game_id,
            winner
        )

        return

    await query.edit_message_text(
        "❌⭕ **دوز**\n\nنوبت تو:",
        reply_markup=ttt_keyboard(
            game_id,
            board
        )
    )


async def finish_ttt(query, game_id, winner):

    game = ttt_games.get(game_id)

    if not game:
        return

    user_id = game["user"]
    bet = game["bet"]

    del ttt_games[game_id]

    if winner == "❌":

        win = bet * 2

        add_coins(
            user_id,
            win,
            "ttt_win"
        )

        game_result(
            user_id,
            "win"
        )

        text = f"🎉 بردی! +{win}"

    elif winner == "⭕":

        game_result(
            user_id,
            "loss"
        )

        text = f"💀 باختی! -{bet}"

    else:

        add_coins(
            user_id,
            bet,
            "ttt_draw"
        )

        game_result(
            user_id,
            "draw"
        )

        text = "🤝 مساوی!"

    await query.edit_message_text(
        f"❌⭕ **پایان دوز**\n\n{text}"
    )


# =========================================================
# DUEL
# =========================================================

duels = {}


def duel_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⚔️ حمله",
                callback_data="duel_attack"
            ),
            InlineKeyboardButton(
                "🛡 دفاع",
                callback_data="duel_defend"
            )
        ],
        [
            InlineKeyboardButton(
                "💚 Heal",
                callback_data="duel_heal"
            )
        ]
    ])


async def duel_start(query, bet):

    user = query.from_user

    if not valid_bet(user.id, bet):
        await query.answer(
            "❌ شرط معتبر نیست.",
            show_alert=True
        )
        return

    remove_coins(
        user.id,
        bet,
        "duel_bet"
    )

    duels[user.id] = {
        "bet": bet,
        "hp": 100,
        "enemy": 100,
        "turn": True
    }

    await query.edit_message_text(
        """
⚔️ **دوئل خر‌بات**

❤️ HP تو: 100
💀 HP خر‌بات: 100

حرکتت رو انتخاب کن:
""",
        reply_markup=duel_keyboard()
    )


async def duel_move(query, action):

    user = query.from_user

    game = duels.get(user.id)

    if not game:
        return

    if action == "attack":

        damage = random.randint(
            10,
            30
        )

        if random.random() < 0.15:
            damage *= 2

        game["enemy"] -= damage

        text = f"⚔️ ضربه زدی: **{damage}**"

    elif action == "defend":

        damage = random.randint(
            3,
            10
        )

        game["enemy"] -= damage

        text = f"🛡 دفاع کردی و {damage} آسیب زدی."

    else:

        heal = random.randint(
            10,
            25
        )

        game["hp"] = min(
            100,
            game["hp"] + heal
        )

        text = f"💚 +{heal} HP"

    if game["enemy"] <= 0:

        win = game["bet"] * 2

        add_coins(
            user.id,
            win,
            "duel_win"
        )

        game_result(
            user.id,
            "win"
        )

        del duels[user.id]

        await query.edit_message_text(
            f"""
🏆 **تو برنده شدی!**

🎁 +{win} 🫏
"""
        )

        return

    enemy_damage = random.randint(
        8,
        22
    )

    game["hp"] -= enemy_damage

    if game["hp"] <= 0:

        game_result(
            user.id,
            "loss"
        )

        del duels[user.id]

        await query.edit_message_text(
            f"""
💀 **خر‌بات برنده شد!**

-{game["bet"]} 🫏
"""
        )

        return

    await query.edit_message_text(
        f"""
⚔️ **دوئل**

{text}

❤️ HP تو:
**{game["hp"]}**

💀 HP خر‌بات:
**{game["enemy"]}**

🤖 حمله خر‌بات:
-{enemy_damage}

حرکت بعدی:
""",
        reply_markup=duel_keyboard()
    )


# =========================================================
# ADMIN
# =========================================================

def is_admin(user):

    return (
        user
        and ADMIN_ID != 0
        and user.id == ADMIN_ID
    )


async def admin_panel(update, context):

    user = update.effective_user

    if not is_admin(user):
        return

    total = db_execute(
        "SELECT COUNT(*) AS c FROM users"
    ).fetchone()["c"]

    banned = db_execute(
        "SELECT COUNT(*) AS c FROM users WHERE banned=1"
    ).fetchone()["c"]

    total_coins = db_execute(
        "SELECT COALESCE(SUM(coins),0) AS c FROM users"
    ).fetchone()["c"]

    text = f"""
👑 **پنل مالک خر‌بات**

━━━━━━━━━━━━

👥 کاربران:
**{total}**

🚫 بن‌شده:
**{banned}**

💰 کل سکه‌های سیستم:
**{total_coins}**

━━━━━━━━━━━━

🛠️ دستورات:

/addcoin ID AMOUNT

/removecoin ID AMOUNT

/setlevel ID LEVEL

/settitle ID TITLE

/giveitem ID ITEM

/ban ID

/unban ID

/mute ID

/unmute ID

/user ID

/broadcast TEXT

/giveall AMOUNT
"""

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_menu(user.id)
        )

    else:

        await update.message.reply_text(text)


async def admin_addcoin(update, context):

    if not is_admin(update.effective_user):
        return

    try:

        uid = int(context.args[0])
        amount = int(context.args[1])

        if not get_user(uid):

            await update.message.reply_text(
                "❌ کاربر پیدا نشد."
            )

            return

        add_coins(
            uid,
            amount,
            "admin_add"
        )

        await update.message.reply_text(
            f"✅ +{amount} 🫏 به `{uid}` اضافه شد."
        )

    except:

        await update.message.reply_text(
            "فرمت:\n/addcoin ID AMOUNT"
        )


async def admin_removecoin(update, context):

    if not is_admin(update.effective_user):
        return

    try:

        uid = int(context.args[0])
        amount = int(context.args[1])

        if remove_coins(
            uid,
            amount,
            "admin_remove"
        ):

            await update.message.reply_text(
                f"✅ {amount} 🫏 کم شد."
            )

        else:

            await update.message.reply_text(
                "❌ موجودی کافی نیست یا کاربر وجود ندارد."
            )

    except:

        await update.message.reply_text(
            "فرمت:\n/removecoin ID AMOUNT"
        )


async def admin_setlevel(update, context):

    if not is_admin(update.effective_user):
        return

    try:

        uid = int(context.args[0])
        level = max(
            1,
            int(context.args[1])
        )

        db_execute("""
        UPDATE users
        SET level = ?, xp = 0
        WHERE user_id = ?
        """, (
            level,
            uid
        ), commit=True)

        await update.message.reply_text(
            "✅ Level تغییر کرد."
        )

    except:

        await update.message.reply_text(
            "/setlevel ID LEVEL"
        )


async def admin_settitle(update, context):

    if not is_admin(update.effective_user):
        return

    try:

        uid = int(context.args[0])

        title = " ".join(
            context.args[1:]
        )

        db_execute("""
        UPDATE users
        SET title = ?
        WHERE user_id = ?
        """, (
            title,
            uid
        ), commit=True)

        await update.message.reply_text(
            "✅ لقب تغییر کرد."
        )

    except:

        await update.message.reply_text(
            "/settitle ID TITLE"
        )


async def admin_ban(update, context):

    if not is_admin(update.effective_user):
        return

    try:

        uid = int(context.args[0])

        db_execute("""
        UPDATE users
        SET banned = 1
        WHERE user_id = ?
        """, (
            uid,
        ), commit=True)

        await update.message.reply_text(
            "🚫 کاربر بن شد."
        )

    except:
        pass


async def admin_unban(update, context):

    if not is_admin(update.effective_user):
        return

    try:

        uid = int(context.args[0])

        db_execute("""
        UPDATE users
        SET banned = 0
        WHERE user_id = ?
        """, (
            uid,
        ), commit=True)

        await update.message.reply_text(
            "✅ آن‌بن شد."
        )

    except:
        pass


async def admin_mute(update, context):

    if not is_admin(update.effective_user):
        return

    try:

        uid = int(context.args[0])

        db_execute("""
        UPDATE users
        SET muted = 1
        WHERE user_id = ?
        """, (
            uid,
        ), commit=True)

        await update.message.reply_text(
            "🔇 کاربر میوت شد."
        )

    except:
        pass


async def admin_unmute(update, context):

    if not is_admin(update.effective_user):
        return

    try:

        uid = int(context.args[0])

        db_execute("""
        UPDATE users
        SET muted = 0
        WHERE user_id = ?
        """, (
            uid,
        ), commit=True)

        await update.message.reply_text(
            "🔊 آن‌میوت شد."
        )

    except:
        pass


async def admin_giveall(update, context):

    if not is_admin(update.effective_user):
        return

    try:

        amount = int(context.args[0])

        rows = db_execute(
            "SELECT user_id FROM users WHERE banned=0"
        ).fetchall()

        for row in rows:

            add_coins(
                row["user_id"],
                amount,
                "admin_giveall"
            )

        await update.message.reply_text(
            f"🎁 به {len(rows)} کاربر +{amount} داده شد."
        )

    except:

        await update.message.reply_text(
            "/giveall AMOUNT"
        )


async def admin_user(update, context):

    if not is_admin(update.effective_user):
        return

    try:

        uid = int(context.args[0])

        row = get_user(uid)

        if not row:

            await update.message.reply_text(
                "❌ پیدا نشد."
            )

            return

        await update.message.reply_text(
            f"""
👤 **User Info**

ID: `{uid}`

نام: {row["first_name"]}

💰 Coins: {row["coins"]}

⭐ Level: {row["level"]}

XP: {row["xp"]}

🏆 Wins: {row["wins"]}

💀 Losses: {row["losses"]}

🎮 Games: {row["games_played"]}

🔥 Streak: {row["streak"]}

⭐ Reputation: {row["reputation"]}

🚫 Banned: {row["banned"]}

🔇 Muted: {row["muted"]}
"""
        )

    except:

        await update.message.reply_text(
            "/user ID"
        )


async def admin_broadcast(update, context):

    if not is_admin(update.effective_user):
        return

    text = " ".join(context.args)

    if not text:

        await update.message.reply_text(
            "/broadcast متن پیام"
        )

        return

    rows = db_execute(
        "SELECT user_id FROM users WHERE banned=0"
    ).fetchall()

    sent = 0

    for row in rows:

        try:

            await context.bot.send_message(
                row["user_id"],
                text
            )

            sent += 1

            await asyncio.sleep(
                0.05
            )

        except Exception:
            pass

    await update.message.reply_text(
        f"📢 ارسال شد به {sent} کاربر."
    )


# =========================================================
# HELP
# =========================================================

async def help_command(update, context):

    text = """
📖 **راهنمای خر‌بات**

━━━━━━━━━━━━

🤖 **AI**
پیامت رو با «خر» شروع کن.

مثال:
`خر خوبی؟`

🎮 **بازی‌ها**
از منوی بازی‌ها استفاده کن.

💰 **اقتصاد**

/daily
/store
/inventory
/quests

🏆 **رتبه‌بندی**

/top

💸 **انتقال سکه**

روی پیام طرف Reply کن:

`بده 500`

━━━━━━━━━━━━

🤖 خر‌بات:
**تورکعلی 😂🫏**
"""

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            reply_markup=main_menu(
                update.effective_user.id
            )
        )

    else:

        await update.message.reply_text(
            text,
            reply_markup=main_menu(
                update.effective_user.id
            )
        )


# =========================================================
# GAME MENU CALLBACK
# =========================================================

async def game_menu_handler(query):

    await query.edit_message_text(
        """
🎮 **بازی‌های خر‌بات**

برای بازی، اول مبلغ شرط رو انتخاب کن.
""",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "10 🫏",
                    callback_data="bet:10"
                ),
                InlineKeyboardButton(
                    "50 🫏",
                    callback_data="bet:50"
                ),
                InlineKeyboardButton(
                    "100 🫏",
                    callback_data="bet:100"
                )
            ],
            [
                InlineKeyboardButton(
                    "500 🫏",
                    callback_data="bet:500"
                ),
                InlineKeyboardButton(
                    "1000 🫏",
                    callback_data="bet:1000"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 برگشت",
                    callback_data="main"
                )
            ]
        ])
    )


# =========================================================
# BET SELECT
# =========================================================

async def bet_select(query, bet):

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🪙 شیر",
                callback_data=f"coin:{bet}:heads"
            ),
            InlineKeyboardButton(
                "🪙 خط",
                callback_data=f"coin:{bet}:tails"
            )
        ],
        [
            InlineKeyboardButton(
                "🎲 تاس",
                callback_data=f"dice:{bet}"
            ),
            InlineKeyboardButton(
                "🎰 اسلات",
                callback_data=f"slots:{bet}"
            )
        ],
        [
            InlineKeyboardButton(
                "💣 Mines",
                callback_data=f"mines:{bet}"
            ),
            InlineKeyboardButton(
                "🃏 Blackjack",
                callback_data=f"bj:{bet}"
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 حدس عدد",
                callback_data=f"guess:{bet}"
            )
        ],
        [
            InlineKeyboardButton(
                "💥 انفجار",
                callback_data=f"crash:{bet}"
            )
        ],
        [
            InlineKeyboardButton(
                "🪨 سنگ",
                callback_data=f"rpsmenu:{bet}"
            ),
            InlineKeyboardButton(
                "❌ دوز",
                callback_data=f"ttt:{bet}"
            )
        ],
        [
            InlineKeyboardButton(
                "⚔️ دوئل",
                callback_data=f"duel:{bet}"
            )
        ]
    ])

    await query.edit_message_text(
        f"""
💰 **شرط: {bet} 🫏**

بازی مورد نظرت رو انتخاب کن:
""",
        reply_markup=keyboard
    )


# =========================================================
# RPS MENU
# =========================================================

async def rps_menu(query, bet):

    await query.edit_message_text(
        "🪨📄✂️ انتخاب کن:",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🪨",
                    callback_data=f"rps:{bet}:stone"
                ),
                InlineKeyboardButton(
                    "📄",
                    callback_data=f"rps:{bet}:paper"
                ),
                InlineKeyboardButton(
                    "✂️",
                    callback_data=f"rps:{bet}:scissors"
                )
            ]
        ])
    )


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def callback_handler(update, context):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    ensure_user(user)

    data = query.data

    # MAIN

    if data == "main":

        await query.edit_message_text(
            "🫏 **خر‌بات**\n\nبه قلمرو خرها خوش اومدی 😂",
            reply_markup=main_menu(user.id)
        )

        return

    if data == "profile":

        await show_profile(
            update,
            context
        )

        return

    if data == "balance":

        await query.edit_message_text(
            f"""
💰 **موجودی**

**{coins(user.id)}** 🫏
""",
            reply_markup=main_menu(user.id)
        )

        return

    if data == "games":

        await query.edit_message_text(
            "🎮 **بازی‌ها**",
            reply_markup=games_menu()
        )

        return

    if data == "store":

        await show_store(
            update,
            context
        )

        return

    if data == "inventory":

        await inventory(
            update,
            context
        )

        return

    if data == "leaderboard":

        await leaderboard(
            update,
            context
        )

        return

    if data == "achievements":

        await achievements(
            update,
            context
        )

        return

    if data == "quests":

        await quests(
            update,
            context
        )

        return

    if data == "streak":

        row = get_user(user.id)

        await query.edit_message_text(
            f"""
🔥 **Streak**

🔥 {row["streak"]} روز متوالی

هر روز بیا تا Streak حفظ بشه.
""",
            reply_markup=main_menu(user.id)
        )

        return

    if data == "help":

        await help_command(
            update,
            context
        )

        return

    if data == "ai_help":

        await query.edit_message_text(
            """
🤖 **خر‌بات AI**

هر پیامی رو که با «خر» شروع کنی،
خر‌بات جواب میده.

مثال:

`خر یه جوک بگو`

`خر تورکعلی کیه؟`

😂🫏
""",
            reply_markup=main_menu(user.id)
        )

        return

    if data == "admin":

        await admin_panel(
            update,
            context
        )

        return

    # BET

    if data.startswith("bet:"):

        bet = int(
            data.split(":")[1]
        )

        await bet_select(
            query,
            bet
        )

        return

    # COIN

    if data.startswith("coin:"):

        _, bet, choice = data.split(":")

        await coin_game(
            query,
            int(bet),
            choice
        )

        return

    # DICE

    if data.startswith("dice:"):

        bet = int(
            data.split(":")[1]
        )

        await dice_game(
            query,
            bet
        )

        return

    # SLOTS

    if data.startswith("slots:"):

        bet = int(
            data.split(":")[1]
        )

        await slots_game(
            query,
            bet
        )

        return

    # MINES

    if data.startswith("mines:"):

        bet = int(
            data.split(":")[1]
        )

        await mines_start(
            query,
            bet
        )

        return

    if data.startswith("mine:"):

        pos = int(
            data.split(":")[1]
        )

        await mines_pick(
            query,
            pos
        )

        return

    if data == "mine_cash":

        await mines_cash(
            query
        )

        return

    # BLACKJACK

    if data.startswith("bj:"):

        bet = int(
            data.split(":")[1]
        )

        await blackjack_start(
            query,
            bet
        )

        return

    if data == "bj_hit":

        await blackjack_hit(
            query
        )

        return

    if data == "bj_stand":

        await blackjack_stand(
            query
        )

        return

    # GUESS

    if data.startswith("guess:"):

        bet = int(
            data.split(":")[1]
        )

        await start_guess(
            query,
            bet
        )

        return

    if data.startswith("guess:"):

        return

    # CRASH

    if data.startswith("crash:"):

        bet = int(
            data.split(":")[1]
        )

        await start_crash(
            query,
            bet
        )

        return

    if data == "crash_next":

        await crash_next(
            query
        )

        return

    if data == "crash_cash":

        await crash_cash(
            query
        )

        return

    # RPS

    if data.startswith("rpsmenu:"):

        bet = int(
            data.split(":")[1]
        )

        await rps_menu(
            query,
            bet
        )

        return

    if data.startswith("rps:"):

        _, bet, choice = data.split(":")

        await rps_game(
            query,
            int(bet),
            choice
        )

        return

    # TTT

    if data.startswith("ttt:"):

        parts = data.split(":")

        if len(parts) == 2:

            bet = int(parts[1])

            await start_ttt(
                query,
                bet
            )

        else:

            game_id = parts[1]
            pos = int(parts[2])

            await ttt_move(
                query,
                game_id,
                pos
            )

        return

    # DUEL

    if data.startswith("duel:"):

        bet = int(
            data.split(":")[1]
        )

        await duel_start(
            query,
            bet
        )

        return

    if data.startswith("duel_"):

        action = data.replace(
            "duel_",
            ""
        )

        await duel_move(
            query,
            action
        )

        return

    # QUIZ

    if data == "quiz_start":

        await start_quiz(
            query
        )

        return

    if data.startswith("quiz:"):

        answer = int(
            data.split(":")[1]
        )

        await answer_quiz(
            query,
            answer
        )

        return

    # STORE

    if data.startswith("buy:"):

        await buy_item(
            query,
            data.split(":")[1]
        )

        return


# =========================================================
# MESSAGE HANDLER
# =========================================================

last_arr = {}


async def message_handler(update, context):

    if not update.message:
        return

    user = update.effective_user

    if not user:
        return

    ensure_user(user)

    row = get_user(user.id)

    if row["banned"]:
        return

    if row["muted"]:
        return

    text = update.message.text

    if not text:
        return

    clean = text.strip().lower()

    # TRANSFER

    parts = clean.split()

    if (
        len(parts) >= 2
        and parts[0] == "بده"
        and parts[1].isdigit()
        and update.message.reply_to_message
    ):

        amount = int(parts[1])

        target = (
            update.message
            .reply_to_message
            .from_user
        )

        if target.id == user.id:

            await update.message.reply_text(
                "🤡 به خودت نمیشه."
            )

            return

        if remove_coins(
            user.id,
            amount,
            "transfer"
        ):

            ensure_user(target)

            add_coins(
                target.id,
                amount,
                "transfer"
            )

            await update.message.reply_text(
                f"""
💸 انتقال موفق!

👤 {target.first_name}

+{amount} 🫏
"""
            )

        else:

            await update.message.reply_text(
                "❌ موجودی کافی نیست."
            )

        return

    # ARR

    if clean in {
        "عر",
        "عرعر",
        "عرر",
        "عررر",
        "عرررر"
    }:

        now = time.time()

        if now - last_arr.get(
            user.id,
            0
        ) < ARR_COOLDOWN:

            await update.message.reply_text(
                "⏳ یکم صبر کن 😂"
            )

            return

        last_arr[user.id] = now

        add_coins(
            user.id,
            ARR_SCORE,
            "arr"
        )

        add_xp(
            user.id,
            5
        )

        db_execute("""
        UPDATE users
        SET arr_count = arr_count + 1
        WHERE user_id = ?
        """, (
            user.id,
        ), commit=True)

        quest_progress(
            user.id,
            "arr"
        )

        await update.message.reply_text(
            f"""
🫏 عررررر!

+{ARR_SCORE} 🫏

تورکعلی 😂
"""
        )

        await check_achievements(
            context.bot,
            user.id
        )

        return

    # GAME WORDS

    if clean in {
        "بازی",
        "بازی ها",
        "بازی‌ها"
    }:

        await update.message.reply_text(
            "🎮 بازی‌ها:",
            reply_markup=games_menu()
        )

        return

    # STORE

    if clean in {
        "فروشگاه",
        "خرید"
    }:

        await show_store(
            update,
            context
        )

        return

    # PROFILE

    if clean in {
        "پروفایل",
        "امتیاز"
    }:

        await show_profile(
            update,
            context
        )

        return

    # TOP

    if clean in {
        "تاپ",
        "top",
        "رتبه"
    }:

        await leaderboard(
            update,
            context
        )

        return

    # DAILY

    if clean in {
        "daily",
        "روزانه",
        "جایزه"
    }:

        await daily(
            update,
            context
        )

        return

    # QUESTS

    if clean in {
        "ماموریت",
        "ماموریت ها",
        "ماموریت‌ها"
    }:

        await quests(
            update,
            context
        )

        return

    # INVENTORY

    if clean in {
        "انبار",
        "کیف"
    }:

        await inventory(
            update,
            context
        )

        return

    # HELP

    if clean in {
        "راهنما",
        "کمک"
    }:

        await help_command(
            update,
            context
        )

        return

    # AI

    if (
        clean == "خر"
        or clean.startswith("خر ")
    ):

        if clean == "خر":

            prompt = "سلام خر!"

        else:

            prompt = text[3:].strip()

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing"
        )

        answer = await ask_ai(
            prompt
        )

        db_execute("""
        UPDATE users
        SET ai_messages = ai_messages + 1
        WHERE user_id = ?
        """, (
            user.id,
        ), commit=True)

        quest_progress(
            user.id,
            "ai"
        )

        add_xp(
            user.id,
            10
        )

        await update.message.reply_text(
            answer
        )

        await check_achievements(
            context.bot,
            user.id
        )


# =========================================================
# COMMANDS
# =========================================================

async def top_command(update, context):
    await leaderboard(update, context)


async def store_command(update, context):
    await show_store(update, context)


async def inventory_command(update, context):
    await inventory(update, context)


async def quests_command(update, context):
    await quests(update, context)


async def profile_command(update, context):
    await show_profile(update, context)


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        print(
            "ERROR: BOT_TOKEN is missing!"
        )

        return

    print(
        "🫏 KHARBOT V2 STARTING..."
    )

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # BASIC

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "profile",
            profile_command
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
            "top",
            top_command
        )
    )

    app.add_handler(
        CommandHandler(
            "store",
            store_command
        )
    )

    app.add_handler(
        CommandHandler(
            "inventory",
            inventory_command
        )
    )

    app.add_handler(
        CommandHandler(
            "quests",
            quests_command
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command
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
            admin_addcoin
        )
    )

    app.add_handler(
        CommandHandler(
            "removecoin",
            admin_removecoin
        )
    )

    app.add_handler(
        CommandHandler(
            "setlevel",
            admin_setlevel
        )
    )

    app.add_handler(
        CommandHandler(
            "settitle",
            admin_settitle
        )
    )

    app.add_handler(
        CommandHandler(
            "ban",
            admin_ban
        )
    )

    app.add_handler(
        CommandHandler(
            "unban",
            admin_unban
        )
    )

    app.add_handler(
        CommandHandler(
            "mute",
            admin_mute
        )
    )

    app.add_handler(
        CommandHandler(
            "unmute",
            admin_unmute
        )
    )

    app.add_handler(
        CommandHandler(
            "giveall",
            admin_giveall
        )
    )

    app.add_handler(
        CommandHandler(
            "user",
            admin_user
        )
    )

    app.add_handler(
        CommandHandler(
            "broadcast",
            admin_broadcast
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
            message_handler
        )
    )

    print(
        "🫏 KHARBOT V2 STARTED!"
    )

    app.run_polling()


if __name__ == "__main__":
    main()
