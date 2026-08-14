# ============================================================
# KHARBOT PRO
# PART 1/2
# ============================================================

import os
import time
import random
import sqlite3
import logging
import asyncio
from contextlib import closing
from dataclasses import dataclass, field

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# آیدی عددی ادمین اصلی را در Environment قرار بده
OWNER_ID = int(
    os.getenv("OWNER_ID", "0")
)

DB_FILE = "kharbot.db"

MIN_BET = 50
MAX_BET = 10000

START_COINS = 2500

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(
    "KHARBOT"
)


# ============================================================
# DATABASE
# ============================================================

def db_connect():

    db = sqlite3.connect(
        DB_FILE,
        timeout=20
    )

    db.row_factory = sqlite3.Row

    return db


def init_db():

    with closing(db_connect()) as db:

        db.execute("""
            CREATE TABLE IF NOT EXISTS users (

                user_id INTEGER PRIMARY KEY,

                name TEXT NOT NULL,

                coins INTEGER NOT NULL DEFAULT 2500,

                level INTEGER NOT NULL DEFAULT 1,

                xp INTEGER NOT NULL DEFAULT 0,

                wins INTEGER NOT NULL DEFAULT 0,

                losses INTEGER NOT NULL DEFAULT 0,

                last_daily INTEGER NOT NULL DEFAULT 0,

                created_at INTEGER NOT NULL

            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS donkeys (

                user_id INTEGER PRIMARY KEY,

                name TEXT NOT NULL DEFAULT 'خر من',

                hunger INTEGER NOT NULL DEFAULT 100,

                thirst INTEGER NOT NULL DEFAULT 100,

                energy INTEGER NOT NULL DEFAULT 100,

                happiness INTEGER NOT NULL DEFAULT 100,

                strength INTEGER NOT NULL DEFAULT 1,

                speed INTEGER NOT NULL DEFAULT 1,

                luck INTEGER NOT NULL DEFAULT 1,

                sounds INTEGER NOT NULL DEFAULT 1,

                FOREIGN KEY(user_id)
                REFERENCES users(user_id)

            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS inventory (

                user_id INTEGER NOT NULL,

                item TEXT NOT NULL,

                amount INTEGER NOT NULL DEFAULT 0,

                PRIMARY KEY(user_id, item)

            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                amount INTEGER NOT NULL,

                reason TEXT,

                created_at INTEGER NOT NULL

            )
        """)

        db.commit()


# ============================================================
# USER SYSTEM
# ============================================================

def ensure_user(
    user_id,
    name="Player"
):

    now = int(time.time())

    with closing(db_connect()) as db:

        row = db.execute(
            """
            SELECT user_id
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if not row:

            db.execute(
                """
                INSERT INTO users
                (
                    user_id,
                    name,
                    coins,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    user_id,
                    name[:100],
                    START_COINS,
                    now
                )
            )

            db.execute(
                """
                INSERT INTO donkeys
                (
                    user_id
                )
                VALUES (?)
                """,
                (user_id,)
            )

            db.commit()

        else:

            db.execute(
                """
                UPDATE users
                SET name = ?
                WHERE user_id = ?
                """,
                (
                    name[:100],
                    user_id
                )
            )

            db.commit()


def get_user(
    user_id
):

    with closing(db_connect()) as db:

        return db.execute(
            """
            SELECT *
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()


def get_donkey(
    user_id
):

    with closing(db_connect()) as db:

        return db.execute(
            """
            SELECT *
            FROM donkeys
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()


# ============================================================
# COINS
# ============================================================

def add_coins(
    user_id,
    amount,
    reason="system"
):

    if amount <= 0:
        return False

    with closing(db_connect()) as db:

        db.execute(
            """
            UPDATE users
            SET coins = coins + ?
            WHERE user_id = ?
            """,
            (
                amount,
                user_id
            )
        )

        db.execute(
            """
            INSERT INTO transactions
            (
                user_id,
                amount,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                amount,
                reason,
                int(time.time())
            )
        )

        db.commit()

    return True


def remove_coins(
    user_id,
    amount,
    reason="spend"
):

    if amount <= 0:
        return False

    with closing(db_connect()) as db:

        row = db.execute(
            """
            SELECT coins
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if not row:
            return False

        if row["coins"] < amount:
            return False

        db.execute(
            """
            UPDATE users
            SET coins = coins - ?
            WHERE user_id = ?
            """,
            (
                amount,
                user_id
            )
        )

        db.execute(
            """
            INSERT INTO transactions
            (
                user_id,
                amount,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                -amount,
                reason,
                int(time.time())
            )
        )

        db.commit()

    return True


# ============================================================
# XP / LEVEL
# ============================================================

def xp_required(
    level
):

    return 100 + (
        (level - 1) * 75
    )


def add_xp(
    user_id,
    amount
):

    if amount <= 0:
        return

    with closing(db_connect()) as db:

        row = db.execute(
            """
            SELECT level, xp
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if not row:
            return

        level = row["level"]
        xp = row["xp"] + amount

        while xp >= xp_required(level):

            xp -= xp_required(level)
            level += 1

        db.execute(
            """
            UPDATE users
            SET level = ?, xp = ?
            WHERE user_id = ?
            """,
            (
                level,
                xp,
                user_id
            )
        )

        db.commit()


def record_win(
    user_id
):

    with closing(db_connect()) as db:

        db.execute(
            """
            UPDATE users
            SET wins = wins + 1
            WHERE user_id = ?
            """,
            (user_id,)
        )

        db.commit()

    add_xp(
        user_id,
        25
    )


def record_loss(
    user_id
):

    with closing(db_connect()) as db:

        db.execute(
            """
            UPDATE users
            SET losses = losses + 1
            WHERE user_id = ?
            """,
            (user_id,)
        )

        db.commit()

    add_xp(
        user_id,
        5
    )


# ============================================================
# DAILY
# ============================================================

def claim_daily(
    user_id
):

    now = int(time.time())

    with closing(db_connect()) as db:

        row = db.execute(
            """
            SELECT last_daily
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if not row:
            return False, "❌ کاربر پیدا نشد."

        if now - row["last_daily"] < 86400:

            remaining = (
                86400
                -
                (now - row["last_daily"])
            )

            hours = remaining // 3600
            minutes = (
                remaining % 3600
            ) // 60

            return False, (
                f"⏳ جایزه روزانه آماده نیست.\n"
                f"{hours} ساعت و {minutes} دقیقه دیگر."
            )

        reward = random.randint(
            400,
            800
        )

        db.execute(
            """
            UPDATE users
            SET
                coins = coins + ?,
                last_daily = ?
            WHERE user_id = ?
            """,
            (
                reward,
                now,
                user_id
            )
        )

        db.execute(
            """
            INSERT INTO transactions
            (
                user_id,
                amount,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                reward,
                "daily",
                now
            )
        )

        db.commit()

    add_xp(
        user_id,
        10
    )

    return True, (
        f"🎁 جایزه روزانه:\n"
        f"🪙 +{reward:,} سکه"
    )


# ============================================================
# DONKEY SYSTEM
# ============================================================

DONKEY_ACTION_COSTS = {

    "food": 100,

    "water": 70,

    "shower": 120,

    "rest": 80,

    "play": 100,

}


def donkey_action(
    user_id,
    action
):

    if action not in DONKEY_ACTION_COSTS:

        return False, (
            "❌ عملیات نامعتبر."
        )

    cost = DONKEY_ACTION_COSTS[
        action
    ]

    if not remove_coins(
        user_id,
        cost,
        reason=f"donkey_{action}"
    ):

        return False, (
            "❌ سکه کافی نداری."
        )

    changes = {

        "food": {
            "hunger": 30,
            "happiness": 5,
        },

        "water": {
            "thirst": 35,
            "happiness": 3,
        },

        "shower": {
            "happiness": 15,
        },

        "rest": {
            "energy": 35,
            "happiness": 5,
        },

        "play": {
            "happiness": 25,
            "energy": -10,
        },

    }

    change = changes[action]

    with closing(db_connect()) as db:

        donkey = db.execute(
            """
            SELECT *
            FROM donkeys
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if not donkey:

            return False, (
                "❌ خر پیدا نشد."
            )

        hunger = donkey["hunger"]
        thirst = donkey["thirst"]
        energy = donkey["energy"]
        happiness = donkey["happiness"]

        hunger += change.get(
            "hunger",
            0
        )

        thirst += change.get(
            "thirst",
            0
        )

        energy += change.get(
            "energy",
            0
        )

        happiness += change.get(
            "happiness",
            0
        )

        hunger = max(
            0,
            min(100, hunger)
        )

        thirst = max(
            0,
            min(100, thirst)
        )

        energy = max(
            0,
            min(100, energy)
        )

        happiness = max(
            0,
            min(100, happiness)
        )

        db.execute(
            """
            UPDATE donkeys
            SET
                hunger = ?,
                thirst = ?,
                energy = ?,
                happiness = ?
            WHERE user_id = ?
            """,
            (
                hunger,
                thirst,
                energy,
                happiness,
                user_id
            )
        )

        db.commit()

    add_xp(
        user_id,
        3
    )

    messages = {

        "food":
            "🍖 خر سیر شد.",

        "water":
            "💧 خر آب خورد.",

        "shower":
            "🧼 خر حمام کرد.",

        "rest":
            "😴 خر استراحت کرد.",

        "play":
            "🎾 با خر بازی کردی.",

    }

    return True, messages[action]


# ============================================================
# DONKEY UPGRADE
# ============================================================

UPGRADE_BASE_COST = {

    "strength": 300,

    "speed": 300,

    "luck": 400,

    "sounds": 250,

}


def upgrade_donkey(
    user_id,
    stat
):

    if stat not in UPGRADE_BASE_COST:

        return False, (
            "❌ ارتقای نامعتبر."
        )

    donkey = get_donkey(
        user_id
    )

    if not donkey:

        return False, (
            "❌ خر پیدا نشد."
        )

    current = donkey[stat]

    if current >= 20:

        return False, (
            "🏆 این ویژگی به حداکثر رسیده."
        )

    cost = (
        UPGRADE_BASE_COST[stat]
        *
        current
    )

    if not remove_coins(
        user_id,
        cost,
        reason=f"upgrade_{stat}"
    ):

        return False, (
            f"❌ سکه کافی نیست.\n"
            f"هزینه: {cost:,} 🪙"
        )

    with closing(db_connect()) as db:

        db.execute(
            f"""
            UPDATE donkeys
            SET {stat} = {stat} + 1
            WHERE user_id = ?
            """,
            (user_id,)
        )

        db.commit()

    add_xp(
        user_id,
        10
    )

    return True, (
        f"⬆️ {stat} ارتقا پیدا کرد.\n"
        f"💰 هزینه: {cost:,} 🪙"
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

    user = get_user(
        user_id
    )

    if not donkey or not user:

        return (
            "❌ اطلاعات خر پیدا نشد."
        )

    return (

        "🫏 **خر من**\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🏷️ نام: **{donkey['name']}**\n\n"

        f"🍖 گرسنگی: "
        f"{donkey['hunger']}/100\n"

        f"💧 تشنگی: "
        f"{donkey['thirst']}/100\n"

        f"⚡ انرژی: "
        f"{donkey['energy']}/100\n"

        f"❤️ شادی: "
        f"{donkey['happiness']}/100\n\n"

        f"💪 قدرت: "
        f"{donkey['strength']}\n"

        f"🏃 سرعت: "
        f"{donkey['speed']}\n"

        f"🍀 شانس: "
        f"{donkey['luck']}\n"

        f"🔊 عرعر: "
        f"{donkey['sounds']}\n\n"

        f"🪙 موجودی: "
        f"**{user['coins']:,}**"

    )


# ============================================================
# MENUS
# ============================================================

def main_menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🫏 خر من",
                callback_data="donkey"
            ),

            InlineKeyboardButton(
                "🎮 بازی‌ها",
                callback_data="games"
            ),
        ],

        [
            InlineKeyboardButton(
                "🛒 فروشگاه",
                callback_data="shop"
            ),

            InlineKeyboardButton(
                "🎒 کیف",
                callback_data="inventory"
            ),
        ],

        [
            InlineKeyboardButton(
                "👤 پروفایل",
                callback_data="profile"
            ),

            InlineKeyboardButton(
                "🏆 لیدربرد",
                callback_data="leaderboard"
            ),
        ],

        [
            InlineKeyboardButton(
                "🎁 جایزه روزانه",
                callback_data="daily"
            ),

            InlineKeyboardButton(
                "📖 راهنما",
                callback_data="help"
            ),
        ],

    ])


def donkey_menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🍖 غذا",
                callback_data="d_food"
            ),

            InlineKeyboardButton(
                "💧 آب",
                callback_data="d_water"
            ),
        ],

        [
            InlineKeyboardButton(
                "🧼 حمام",
                callback_data="d_shower"
            ),

            InlineKeyboardButton(
                "😴 استراحت",
                callback_data="d_rest"
            ),
        ],

        [
            InlineKeyboardButton(
                "🎾 بازی",
                callback_data="d_play"
            ),

            InlineKeyboardButton(
                "🔊 عرعر",
                callback_data="d_sound"
            ),
        ],

        [
            InlineKeyboardButton(
                "⬆️ ارتقا",
                callback_data="upgrades"
            ),
        ],

        [
            InlineKeyboardButton(
                "🔙 منوی اصلی",
                callback_data="home"
            ),
        ],

    ])


# ============================================================
# GAMES
# ============================================================

GAME_NAMES = {

    "تاس":
        "🎲 تاس",

    "سکه":
        "🪙 شیر یا خط",

    "حدس":
        "🔢 حدس عدد",

    "جنگ":
        "⚔️ جنگ خرها",

    "ریس":
        "🏇 مسابقه خرها",

    "بمب":
        "💣 بمب",

    "گنج":
        "💎 گنج",

    "دزد":
        "🥷 دزد",

    "چالش":
        "🧠 چالش",

    "عرعر":
        "🔊 مسابقه عرعر",

}


@dataclass
class GameRoom:

    game_type: str

    chat_id: int

    creator_id: int

    bet: int

    max_players: int = 4

    players: list = field(
        default_factory=list
    )

    started: bool = False

    against_bot: bool = False

    bot_difficulty: str = "hard"

    created_at: float = field(
        default_factory=time.time
    )


ACTIVE_GAMES = {}

PLAYER_GAMES = {}


# ============================================================
# GAME ROOM
# ============================================================

def get_room(
    chat_id
):

    return ACTIVE_GAMES.get(
        str(chat_id)
    )


def player_in_game(
    user_id
):

    return user_id in PLAYER_GAMES


def remove_room(
    room
):

    ACTIVE_GAMES.pop(
        str(room.chat_id),
        None
    )

    for player in room.players:

        if player != -1:

            PLAYER_GAMES.pop(
                player,
                None
            )


def create_room(
    game_type,
    chat_id,
    creator_id,
    bet,
    max_players=4,
    against_bot=False
):

    if game_type not in GAME_NAMES:

        return None, (
            "❌ بازی پیدا نشد."
        )

    if bet < MIN_BET or bet > MAX_BET:

        return None, (
            f"❌ شرط باید بین "
            f"{MIN_BET:,} و "
            f"{MAX_BET:,} باشد."
        )

    if get_room(chat_id):

        return None, (
            "❌ یک بازی در این چت در حال اجراست."
        )

    if player_in_game(
        creator_id
    ):

        return None, (
            "❌ تو داخل یک بازی دیگر هستی."
        )

    if not remove_coins(
        creator_id,
        bet,
        reason=f"bet_{game_type}"
    ):

        return None, (
            "❌ سکه کافی نداری."
        )

    room = GameRoom(

        game_type=game_type,

        chat_id=chat_id,

        creator_id=creator_id,

        bet=bet,

        max_players=max_players,

        players=[
            creator_id
        ],

        against_bot=against_bot

    )

    if against_bot:

        room.players.append(
            -1
        )

    ACTIVE_GAMES[
        str(chat_id)
    ] = room

    PLAYER_GAMES[
        creator_id
    ] = str(chat_id)

    return room, None


def join_room(
    room,
    user_id
):

    if room.started:

        return False, (
            "❌ بازی شروع شده."
        )

    if player_in_game(
        user_id
    ):

        return False, (
            "❌ تو قبلاً در یک بازی هستی."
        )

    if len(room.players) >= room.max_players:

        return False, (
            "❌ ظرفیت تکمیل شده."
        )

    if not remove_coins(
        user_id,
        room.bet,
        reason=f"bet_{room.game_type}"
    ):

        return False, (
            "❌ سکه کافی نداری."
        )

    room.players.append(
        user_id
    )

    PLAYER_GAMES[
        user_id
    ] = str(room.chat_id)

    return True, (
        "✅ وارد بازی شدی."
    )


def cancel_room(
    room,
    user_id
):

    if room.started:

        return False, (
            "❌ بازی شروع شده."
        )

    if room.creator_id != user_id:

        return False, (
            "⛔ فقط سازنده می‌تواند لغو کند."
        )

    for player in room.players:

        if player != -1:

            add_coins(
                player,
                room.bet,
                reason="game_refund"
            )

    remove_room(
        room
    )

    return True, (
        "❌ بازی لغو شد و "
        "شرط‌ها برگشت داده شدند."
    )


def room_keyboard(
    room
):

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "👥 ورود",
                callback_data="game_join"
            )
        ],

        [
            InlineKeyboardButton(
                "▶️ شروع",
                callback_data="game_start"
            ),

            InlineKeyboardButton(
                "❌ لغو",
                callback_data="game_cancel"
            )
        ],

    ])


def room_text(
    room
):

    names = []

    for index, player in enumerate(
        room.players,
        1
    ):

        if player == -1:

            name = "🤖 بات"

        else:

            user = get_user(
                player
            )

            name = (
                user["name"]
                if user
                else
                str(player)
            )

        names.append(
            f"{index}. {name}"
        )

    return (

        f"{GAME_NAMES[room.game_type]}\n"
        "━━━━━━━━━━━━━━\n\n"

        f"💰 شرط: **{room.bet:,} 🪙**\n"
        f"👥 بازیکنان: "
        f"**{len(room.players)}/{room.max_players}**\n\n"

        +
        "\n".join(names)

    )


# ============================================================
# BOT
# ============================================================

BOT_SKILL = {

    "easy": 0.45,

    "normal": 0.62,

    "hard": 0.78,

    "expert": 0.88,

}


def donkey_power(
    user_id
):

    donkey = get_donkey(
        user_id
    )

    if not donkey:

        return 1.0

    condition = (

        donkey["hunger"]

        +

        donkey["thirst"]

        +

        donkey["energy"]

        +

        donkey["happiness"]

    ) / 400

    base = (

        donkey["strength"] * 1.4

        +

        donkey["speed"] * 1.3

        +

        donkey["luck"] * 0.8

        +

        donkey["sounds"] * 0.2

    )

    return max(

        0.25,

        (
            1
            +
            base / 15
        )
        *
        (
            0.65
            +
            condition * 0.35
        )

    )


def bot_power(
    difficulty="hard"
):

    skill = BOT_SKILL.get(
        difficulty,
        0.78
    )

    return (

        1.0
        +
        skill * 1.35
        +
        random.uniform(
            -0.12,
            0.12
        )

    )


def weighted_winner(
    players,
    weights
):

    total = sum(weights)

    if total <= 0:

        return random.choice(
            players
        )

    target = random.uniform(
        0,
        total
    )

    current = 0

    for player, weight in zip(
        players,
        weights
    ):

        current += weight

        if current >= target:

            return player

    return players[-1]


# ============================================================
# GAME ENGINE
# ============================================================

def play_dice(
    room
):

    results = {}

    for player in room.players:

        value = random.randint(
            1,
            6
        )

        if player != -1:

            if (
                donkey_power(player)
                > 1.2
                and
                random.random() < 0.18
            ):

                value = min(
                    6,
                    value + 1
                )

        else:

            if (
                random.random()
                <
                BOT_SKILL[
                    room.bot_difficulty
                ]
            ):

                value = max(
                    value,
                    random.randint(
                        4,
                        6
                    )
                )

        results[player] = value

    winner = max(
        results,
        key=results.get
    )

    return winner, results


def play_coin(
    room
):

    results = {}

    for player in room.players:

        if player == -1:

            skill = BOT_SKILL[
                room.bot_difficulty
            ]

        else:

            donkey = get_donkey(
                player
            )

            skill = (
                donkey["luck"] / 30
                if donkey
                else 0
            )

        results[player] = (
            random.random()
            +
            skill
        )

    winner = max(
        results,
        key=results.get
    )

    return winner, results


def play_guess(
    room
):

    target = random.randint(
        1,
        10
    )

    results = {}

    for player in room.players:

        if player == -1:

            skill = BOT_SKILL[
                room.bot_difficulty
            ]

            if random.random() < skill:

                guess = target

            else:

                guess = random.randint(
                    1,
                    10
                )

        else:

            donkey = get_donkey(
                player
            )

            luck = (
                donkey["luck"]
                if donkey
                else 1
            )

            if random.random() < min(
                0.5,
                0.2 + luck * 0.02
            ):

                guess = target

            else:

                guess = random.randint(
                    1,
                    10
                )

        results[player] = guess

    winner = min(
        results,
        key=lambda p:
        abs(
            results[p] - target
        )
    )

    return winner, (
        target,
        results
    )


def play_battle(
    room
):

    powers = {}

    for player in room.players:

        if player == -1:

            powers[player] = bot_power(
                room.bot_difficulty
            )

        else:

            powers[player] = (
                donkey_power(player)
                *
                random.uniform(
                    0.75,
                    1.25
                )
            )

    winner = weighted_winner(
        list(powers.keys()),
        list(powers.values())
    )

    return winner, powers


def play_race(
    room
):

    scores = {}

    for player in room.players:

        if player == -1:

            base = (
                70
                +
                BOT_SKILL[
                    room.bot_difficulty
                ] * 30
            )

        else:

            donkey = get_donkey(
                player
            )

            base = (

                donkey["speed"] * 5

                +

                donkey["luck"] * 2

                +

                donkey["energy"] * 0.4

            )

        scores[player] = (
            base
            +
            random.uniform(
                0,
                40
            )
        )

    winner = max(
        scores,
        key=scores.get
    )

    return winner, scores


def play_bomb(
    room
):

    alive = {}

    for player in room.players:

        if player == -1:

            chance = BOT_SKILL[
                room.bot_difficulty
            ]

        else:

            donkey = get_donkey(
                player
            )

            chance = min(
                0.9,
                0.5
                +
                (
                    donkey["luck"] * 0.025
                    if donkey
                    else 0
                )
            )

        alive[player] = (
            random.random()
            <
            chance
        )

    survivors = [
        p
        for p, value in alive.items()
        if value
    ]

    if not survivors:

        winner = random.choice(
            list(alive.keys())
        )

    else:

        winner = random.choice(
            survivors
        )

    return winner, alive


def play_treasure(
    room
):

    scores = {}

    for player in room.players:

        if player == -1:

            skill = BOT_SKILL[
                room.bot_difficulty
            ]

        else:

            donkey = get_donkey(
                player
            )

            skill = (
                donkey["luck"] / 20
                if donkey
                else 0
            )

        scores[player] = (
            random.random()
            +
            skill
        )

    winner = max(
        scores,
        key=scores.get
    )

    return winner, scores


def play_thief(
    room
):

    scores = {}

    for player in room.players:

        if player == -1:

            skill = BOT_SKILL[
                room.bot_difficulty
            ]

        else:

            donkey = get_donkey(
                player
            )

            skill = (
                donkey["speed"] / 20
                +
                donkey["luck"] / 25
                if donkey
                else 0
            )

        scores[player] = (
            random.random()
            +
            skill
        )

    winner = max(
        scores,
        key=scores.get
    )

    return winner, scores


def play_challenge(
    room
):

    scores = {}

    for player in room.players:

        if player == -1:

            skill = BOT_SKILL[
                room.bot_difficulty
            ]

        else:

            skill = min(
                1.0,
                donkey_power(player)
                / 4
            )

        scores[player] = (
            random.random()
            +
            skill
        )

    winner = max(
        scores,
        key=scores.get
    )

    return winner, scores


def play_sound(
    room
):

    scores = {}

    for player in room.players:

        if player == -1:

            base = (
                5
                +
                BOT_SKILL[
                    room.bot_difficulty
                ] * 5
            )

        else:

            donkey = get_donkey(
                player
            )

            base = (
                donkey["sounds"]
                if donkey
                else 1
            )

        scores[player] = (
            base
            +
            random.uniform(
                0,
                8
            )
        )

    winner = max(
        scores,
        key=scores.get
    )

    return winner, scores


def run_game(
    room
):

    functions = {

        "تاس":
            play_dice,

        "سکه":
            play_coin,

        "حدس":
            play_guess,

        "جنگ":
            play_battle,

        "ریس":
            play_race,

        "بمب":
            play_bomb,

        "گنج":
            play_treasure,

        "دزد":
            play_thief,

        "چالش":
            play_challenge,

        "عرعر":
            play_sound,

    }

    function = functions.get(
        room.game_type
    )

    if not function:

        return None, None

    return function(room)


# ============================================================
# END OF PART 1
# ============================================================
# ============================================================
# KHARBOT PRO
# PART 2/2
# ============================================================


# ============================================================
# ACHIEVEMENT SYSTEM
# ============================================================

ACHIEVEMENTS = {

    "first_game": {
        "name": "🎮 اولین بازی",
        "description": "اولین بازی خودت را انجام بده.",
        "reward": 250,
    },

    "first_win": {
        "name": "🏆 اولین برد",
        "description": "اولین پیروزی خودت را ثبت کن.",
        "reward": 500,
    },

    "ten_wins": {
        "name": "🔥 بازیکن حرفه‌ای",
        "description": "۱۰ برد به دست بیاور.",
        "reward": 1000,
    },

    "fifty_wins": {
        "name": "👑 استاد بازی",
        "description": "۵۰ برد به دست بیاور.",
        "reward": 5000,
    },

    "rich": {
        "name": "💰 پولدار",
        "description": "موجودی خود را به ۱۰٬۰۰۰ سکه برسان.",
        "reward": 1000,
    },

    "very_rich": {
        "name": "💎 سرمایه‌دار",
        "description": "موجودی خود را به ۵۰٬۰۰۰ سکه برسان.",
        "reward": 5000,
    },

    "donkey_upgrade": {
        "name": "🫏 خرِ تقویت‌شده",
        "description": "یکی از ویژگی‌های خر را به سطح ۵ برسان.",
        "reward": 750,
    },

    "donkey_master": {
        "name": "🐴 سلطان خرها",
        "description": "یکی از ویژگی‌های خر را به سطح ۱۰ برسان.",
        "reward": 3000,
    },

    "daily_7": {
        "name": "🎁 منظم",
        "description": "۷ جایزه روزانه دریافت کن.",
        "reward": 1500,
    },

    "big_bet": {
        "name": "🎰 ریسک‌پذیر",
        "description": "یک بازی با حداقل ۵۰۰۰ سکه انجام بده.",
        "reward": 2000,
    },

    "sound_master": {
        "name": "🔊 استاد عرعر",
        "description": "قدرت عرعر خر را به سطح ۵ برسان.",
        "reward": 1000,
    },

    "level_10": {
        "name": "⭐ سطح ۱۰",
        "description": "به سطح ۱۰ برس.",
        "reward": 5000,
    },

}


def init_achievement_db():

    with closing(db_connect()) as db:

        db.execute("""
            CREATE TABLE IF NOT EXISTS achievements (

                user_id INTEGER NOT NULL,

                achievement TEXT NOT NULL,

                unlocked_at INTEGER NOT NULL,

                PRIMARY KEY(
                    user_id,
                    achievement
                )

            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS achievement_progress (

                user_id INTEGER PRIMARY KEY,

                daily_count INTEGER DEFAULT 0,

                games_count INTEGER DEFAULT 0

            )
        """)

        db.commit()


def achievement_unlocked(
    user_id,
    achievement
):

    with closing(db_connect()) as db:

        row = db.execute(
            """
            SELECT achievement
            FROM achievements
            WHERE user_id = ?
            AND achievement = ?
            """,
            (
                user_id,
                achievement
            )
        ).fetchone()

        return row is not None


def unlock_achievement(
    user_id,
    achievement
):

    if achievement not in ACHIEVEMENTS:
        return False

    if achievement_unlocked(
        user_id,
        achievement
    ):
        return False

    reward = ACHIEVEMENTS[
        achievement
    ]["reward"]

    with closing(db_connect()) as db:

        db.execute(
            """
            INSERT INTO achievements
            (
                user_id,
                achievement,
                unlocked_at
            )
            VALUES (?, ?, ?)
            """,
            (
                user_id,
                achievement,
                int(time.time())
            )
        )

        db.commit()

    add_coins(
        user_id,
        reward,
        reason=f"achievement_{achievement}"
    )

    return True


def get_achievement_status(
    user_id
):

    user = get_user(
        user_id
    )

    donkey = get_donkey(
        user_id
    )

    if not user or not donkey:
        return []

    status = []

    for key, achievement in ACHIEVEMENTS.items():

        unlocked = achievement_unlocked(
            user_id,
            key
        )

        progress = 0
        target = 1

        if key == "first_game":

            with closing(db_connect()) as db:

                row = db.execute(
                    """
                    SELECT games_count
                    FROM achievement_progress
                    WHERE user_id = ?
                    """,
                    (user_id,)
                ).fetchone()

                progress = (
                    row["games_count"]
                    if row
                    else 0
                )

            target = 1

        elif key == "first_win":

            progress = user["wins"]
            target = 1

        elif key == "ten_wins":

            progress = user["wins"]
            target = 10

        elif key == "fifty_wins":

            progress = user["wins"]
            target = 50

        elif key == "rich":

            progress = user["coins"]
            target = 10000

        elif key == "very_rich":

            progress = user["coins"]
            target = 50000

        elif key == "donkey_upgrade":

            progress = max(
                donkey["strength"],
                donkey["speed"],
                donkey["luck"],
                donkey["sounds"]
            )

            target = 5

        elif key == "donkey_master":

            progress = max(
                donkey["strength"],
                donkey["speed"],
                donkey["luck"],
                donkey["sounds"]
            )

            target = 10

        elif key == "sound_master":

            progress = donkey["sounds"]
            target = 5

        elif key == "level_10":

            progress = user["level"]
            target = 10

        status.append(
            (
                key,
                achievement,
                unlocked,
                progress,
                target
            )
        )

    return status


def check_achievements(
    user_id
):

    user = get_user(
        user_id
    )

    donkey = get_donkey(
        user_id
    )

    if not user or not donkey:
        return []

    unlocked_now = []

    # ----------------------------------------
    # FIRST GAME
    # ----------------------------------------

    with closing(db_connect()) as db:

        row = db.execute(
            """
            SELECT games_count
            FROM achievement_progress
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

    games_count = (
        row["games_count"]
        if row
        else 0
    )

    if games_count >= 1:

        if unlock_achievement(
            user_id,
            "first_game"
        ):
            unlocked_now.append(
                "first_game"
            )

    # ----------------------------------------
    # WINS
    # ----------------------------------------

    if user["wins"] >= 1:

        if unlock_achievement(
            user_id,
            "first_win"
        ):
            unlocked_now.append(
                "first_win"
            )

    if user["wins"] >= 10:

        if unlock_achievement(
            user_id,
            "ten_wins"
        ):
            unlocked_now.append(
                "ten_wins"
            )

    if user["wins"] >= 50:

        if unlock_achievement(
            user_id,
            "fifty_wins"
        ):
            unlocked_now.append(
                "fifty_wins"
            )

    # ----------------------------------------
    # COINS
    # ----------------------------------------

    if user["coins"] >= 10000:

        if unlock_achievement(
            user_id,
            "rich"
        ):
            unlocked_now.append(
                "rich"
            )

    if user["coins"] >= 50000:

        if unlock_achievement(
            user_id,
            "very_rich"
        ):
            unlocked_now.append(
                "very_rich"
            )

    # ----------------------------------------
    # DONKEY
    # ----------------------------------------

    max_stat = max(
        donkey["strength"],
        donkey["speed"],
        donkey["luck"],
        donkey["sounds"]
    )

    if max_stat >= 5:

        if unlock_achievement(
            user_id,
            "donkey_upgrade"
        ):
            unlocked_now.append(
                "donkey_upgrade"
            )

    if max_stat >= 10:

        if unlock_achievement(
            user_id,
            "donkey_master"
        ):
            unlocked_now.append(
                "donkey_master"
            )

    if donkey["sounds"] >= 5:

        if unlock_achievement(
            user_id,
            "sound_master"
        ):
            unlocked_now.append(
                "sound_master"
            )

    # ----------------------------------------
    # LEVEL
    # ----------------------------------------

    if user["level"] >= 10:

        if unlock_achievement(
            user_id,
            "level_10"
        ):
            unlocked_now.append(
                "level_10"
            )

    return unlocked_now


def increment_games(
    user_id
):

    with closing(db_connect()) as db:

        db.execute(
            """
            INSERT INTO achievement_progress
            (
                user_id,
                games_count
            )
            VALUES (?, 1)

            ON CONFLICT(user_id)
            DO UPDATE SET
                games_count =
                games_count + 1
            """,
            (user_id,)
        )

        db.commit()


# ============================================================
# INVENTORY
# ============================================================

SHOP_ITEMS = {

    "carrot": {
        "name": "🥕 هویج",
        "price": 80,
        "description": "افزایش گرسنگی خر.",
    },

    "water": {
        "name": "💧 بطری آب",
        "price": 60,
        "description": "افزایش تشنگی خر.",
    },

    "soap": {
        "name": "🧼 صابون ویژه",
        "price": 150,
        "description": "افزایش شادی خر.",
    },

    "energy": {
        "name": "⚡ انرژی‌زا",
        "price": 200,
        "description": "افزایش انرژی خر.",
    },

    "lucky": {
        "name": "🍀 شبدر شانس",
        "price": 500,
        "description": "آیتم شانسی.",
    },

    "sound_ticket": {
        "name": "🔊 بلیت عرعر",
        "price": 250,
        "description": "افزایش قدرت عرعر.",
    },

}


def get_item_amount(
    user_id,
    item
):

    with closing(db_connect()) as db:

        row = db.execute(
            """
            SELECT amount
            FROM inventory
            WHERE user_id = ?
            AND item = ?
            """,
            (
                user_id,
                item
            )
        ).fetchone()

        return (
            row["amount"]
            if row
            else 0
        )


def add_item(
    user_id,
    item,
    amount=1
):

    if item not in SHOP_ITEMS:
        return False

    with closing(db_connect()) as db:

        db.execute(
            """
            INSERT INTO inventory
            (
                user_id,
                item,
                amount
            )
            VALUES (?, ?, ?)

            ON CONFLICT(
                user_id,
                item
            )

            DO UPDATE SET
                amount =
                amount + excluded.amount
            """,
            (
                user_id,
                item,
                amount
            )
        )

        db.commit()

    return True


def remove_item(
    user_id,
    item,
    amount=1
):

    current = get_item_amount(
        user_id,
        item
    )

    if current < amount:
        return False

    with closing(db_connect()) as db:

        db.execute(
            """
            UPDATE inventory
            SET amount = amount - ?
            WHERE user_id = ?
            AND item = ?
            """,
            (
                amount,
                user_id,
                item
            )
        )

        db.commit()

    return True


# ============================================================
# SHOP
# ============================================================

def buy_item(
    user_id,
    item
):

    if item not in SHOP_ITEMS:

        return False, (
            "❌ آیتم وجود ندارد."
        )

    data = SHOP_ITEMS[item]

    if not remove_coins(
        user_id,
        data["price"],
        reason=f"buy_{item}"
    ):

        return False, (
            f"❌ سکه کافی نداری.\n"
            f"قیمت: {data['price']:,} 🪙"
        )

    add_item(
        user_id,
        item
    )

    return True, (
        f"✅ {data['name']} خریداری شد."
    )


def shop_keyboard():

    buttons = []

    for item, data in SHOP_ITEMS.items():

        buttons.append([
            InlineKeyboardButton(
                f"{data['name']} | "
                f"{data['price']:,} 🪙",
                callback_data=f"buy_{item}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(
        buttons
    )


def shop_text():

    text = (
        "🛒 **فروشگاه خرستان**\n"
        "━━━━━━━━━━━━━━\n\n"
    )

    for data in SHOP_ITEMS.values():

        text += (
            f"{data['name']}\n"
            f"💰 قیمت: "
            f"{data['price']:,} 🪙\n"
            f"ℹ️ {data['description']}\n\n"
        )

    return text


# ============================================================
# USE ITEM
# ============================================================

def use_item(
    user_id,
    item
):

    if not remove_item(
        user_id,
        item
    ):

        return False, (
            "❌ این آیتم را نداری."
        )

    with closing(db_connect()) as db:

        donkey = db.execute(
            """
            SELECT *
            FROM donkeys
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if not donkey:

            return False, (
                "❌ خر پیدا نشد."
            )

        hunger = donkey["hunger"]
        thirst = donkey["thirst"]
        energy = donkey["energy"]
        happiness = donkey["happiness"]
        luck = donkey["luck"]
        sounds = donkey["sounds"]

        if item == "carrot":

            hunger = min(
                100,
                hunger + 35
            )

            message = (
                "🥕 خر هویج خورد."
            )

        elif item == "water":

            thirst = min(
                100,
                thirst + 40
            )

            message = (
                "💧 خر آب خورد."
            )

        elif item == "soap":

            happiness = min(
                100,
                happiness + 30
            )

            message = (
                "🧼 صابون ویژه استفاده شد."
            )

        elif item == "energy":

            energy = min(
                100,
                energy + 40
            )

            message = (
                "⚡ انرژی خر افزایش یافت."
            )

        elif item == "lucky":

            luck = min(
                20,
                luck + 1
            )

            message = (
                "🍀 شانس خر +1 شد."
            )

        elif item == "sound_ticket":

            sounds = min(
                20,
                sounds + 1
            )

            message = (
                "🔊 قدرت عرعر +1 شد."
            )

        else:

            return False, (
                "❌ آیتم نامعتبر."
            )

        db.execute(
            """
            UPDATE donkeys
            SET
                hunger = ?,
                thirst = ?,
                energy = ?,
                happiness = ?,
                luck = ?,
                sounds = ?
            WHERE user_id = ?
            """,
            (
                hunger,
                thirst,
                energy,
                happiness,
                luck,
                sounds,
                user_id
            )
        )

        db.commit()

    add_xp(
        user_id,
        5
    )

    return True, message


# ============================================================
# LEADERBOARD
# ============================================================

def leaderboard_text():

    with closing(db_connect()) as db:

        rows = db.execute(
            """
            SELECT
                name,
                coins,
                wins,
                level
            FROM users
            ORDER BY coins DESC
            LIMIT 10
            """
        ).fetchall()

    if not rows:

        return (
            "🏆 هنوز کسی ثبت نشده."
        )

    text = (
        "🏆 **لیدربرد خرستان**\n"
        "━━━━━━━━━━━━━━\n\n"
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

        medal = (
            medals[index - 1]
            if index <= 3
            else f"{index}."
        )

        text += (
            f"{medal} "
            f"**{row['name']}**\n"
            f"   🪙 {row['coins']:,} | "
            f"🏆 {row['wins']} برد | "
            f"⭐ Lv.{row['level']}\n\n"
        )

    return text


# ============================================================
# PROFILE
# ============================================================

def profile_text(
    user_id
):

    user = get_user(
        user_id
    )

    if not user:

        return (
            "❌ پروفایل پیدا نشد."
        )

    total = (
        user["wins"]
        +
        user["losses"]
    )

    if total:

        winrate = (
            user["wins"]
            /
            total
            *
            100
        )

    else:

        winrate = 0

    return (

        "👤 **پروفایل بازیکن**\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🏷️ نام: "
        f"**{user['name']}**\n\n"

        f"⭐ سطح: "
        f"**{user['level']}**\n"

        f"✨ XP: "
        f"{user['xp']}/"
        f"{xp_required(user['level'])}\n\n"

        f"🪙 سکه: "
        f"**{user['coins']:,}**\n\n"

        f"🏆 برد: "
        f"{user['wins']}\n"

        f"💀 باخت: "
        f"{user['losses']}\n"

        f"📊 نرخ برد: "
        f"{winrate:.1f}%"

    )


# ============================================================
# ACHIEVEMENT TEXT
# ============================================================

def achievements_text(
    user_id
):

    statuses = get_achievement_status(
        user_id
    )

    text = (
        "🏅 **دستاوردها**\n"
        "━━━━━━━━━━━━━━\n\n"
    )

    unlocked_count = 0

    for (
        key,
        achievement,
        unlocked,
        progress,
        target
    ) in statuses:

        if unlocked:

            icon = "✅"
            unlocked_count += 1

            text += (
                f"{icon} "
                f"**{achievement['name']}**\n"
                f"   {achievement['description']}\n"
                f"   🎁 جایزه دریافت شد\n\n"
            )

        else:

            progress_show = min(
                progress,
                target
            )

            text += (
                f"🔒 "
                f"**{achievement['name']}**\n"
                f"   {achievement['description']}\n"
                f"   📈 "
                f"{progress_show}/{target}\n"
                f"   🎁 "
                f"{achievement['reward']:,} 🪙\n\n"
            )

    text += (
        f"🏅 باز شده: "
        f"{unlocked_count}/"
        f"{len(ACHIEVEMENTS)}"
    )

    return text


# ============================================================
# GAME MENU
# ============================================================

def games_keyboard():

    rows = []

    game_list = list(
        GAME_NAMES.keys()
    )

    for i in range(
        0,
        len(game_list),
        2
    ):

        row = []

        for game in game_list[i:i + 2]:

            row.append(
                InlineKeyboardButton(
                    GAME_NAMES[game],
                    callback_data=f"game_{game}"
                )
            )

        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="home"
        )
    ])

    return InlineKeyboardMarkup(
        rows
    )


def games_text():

    return (

        "🎮 **مرکز بازی‌ها**\n"
        "━━━━━━━━━━━━━━\n\n"

        "۱۰ بازی مختلف در دسترسه:\n\n"

        "🎲 تاس\n"
        "🪙 شیر یا خط\n"
        "🔢 حدس عدد\n"
        "⚔️ جنگ خرها\n"
        "🏇 مسابقه خرها\n"
        "💣 بمب\n"
        "💎 گنج\n"
        "🥷 دزد\n"
        "🧠 چالش\n"
        "🔊 مسابقه عرعر\n\n"

        f"💰 حداقل شرط: "
        f"{MIN_BET:,} 🪙\n"

        f"💰 حداکثر شرط: "
        f"{MAX_BET:,} 🪙"

    )


# ============================================================
# GAME SELECTION STATE
# ============================================================

USER_GAME_SELECTION = {}


def game_bet_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "50 🪙",
                callback_data="bet_50"
            ),

            InlineKeyboardButton(
                "100 🪙",
                callback_data="bet_100"
            ),
        ],

        [
            InlineKeyboardButton(
                "250 🪙",
                callback_data="bet_250"
            ),

            InlineKeyboardButton(
                "500 🪙",
                callback_data="bet_500"
            ),
        ],

        [
            InlineKeyboardButton(
                "1000 🪙",
                callback_data="bet_1000"
            ),

            InlineKeyboardButton(
                "5000 🪙",
                callback_data="bet_5000"
            ),
        ],

        [
            InlineKeyboardButton(
                "🤖 بازی با بات",
                callback_data="bet_bot"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="games"
            )
        ],

    ])


# ============================================================
# GAME RESULT / PAYOUT
# ============================================================

def calculate_payout(
    room
):

    # مجموع شرط‌ها
    pot = (
        room.bet
        *
        len(room.players)
    )

    # کمیسیون ثابت سیستم
    # باعث می‌شود اقتصاد بازی قابل کنترل باشد.
    fee = int(
        pot * 0.05
    )

    prize = pot - fee

    return max(
        prize,
        0
    )


async def finish_game(
    update,
    room,
    winner,
    result_data=None
):

    prize = calculate_payout(
        room
    )

    if winner == -1:

        # بات برنده شده.
        # برای حفظ اقتصاد، پول وارد سیستم نمی‌شود.
        winner_text = (
            "🤖 **بات برنده شد!**"
        )

        for player in room.players:

            if player != -1:

                record_loss(
                    player
                )

    else:

        add_coins(
            winner,
            prize,
            reason="game_prize"
        )

        record_win(
            winner
        )

        winner_user = get_user(
            winner
        )

        winner_name = (
            winner_user["name"]
            if winner_user
            else
            str(winner)
        )

        winner_text = (
            f"🏆 **{winner_name} برنده شد!**\n"
            f"🪙 جایزه: **{prize:,}**"
        )

        for player in room.players:

            if player not in (
                winner,
                -1
            ):

                record_loss(
                    player
                )

    # ثبت بازی
    for player in room.players:

        if player != -1:

            increment_games(
                player
            )

    # اچیومنت‌ها
    achievement_messages = []

    for player in room.players:

        if player == -1:
            continue

        unlocked = check_achievements(
            player
        )

        for achievement in unlocked:

            achievement_data = (
                ACHIEVEMENTS[
                    achievement
                ]
            )

            achievement_messages.append(
                f"🏅 {achievement_data['name']}\n"
                f"🎁 +{achievement_data['reward']:,} 🪙"
            )

    # نتیجه اضافی
    extra = ""

    if room.game_type == "تاس":

        if isinstance(
            result_data,
            dict
        ):

            extra = "\n\n🎲 نتایج:\n"

            for player, value in result_data.items():

                if player == -1:
                    name = "🤖 بات"
                else:
                    u = get_user(player)
                    name = (
                        u["name"]
                        if u
                        else
                        str(player)
                    )

                extra += (
                    f"• {name}: {value}\n"
                )

    elif room.game_type == "حدس":

        if isinstance(
            result_data,
            tuple
        ):

            target, guesses = result_data

            extra = (
                f"\n\n🎯 عدد مخفی: **{target}**\n"
            )

            for player, guess in guesses.items():

                if player == -1:
                    name = "🤖 بات"
                else:
                    u = get_user(player)
                    name = (
                        u["name"]
                        if u
                        else
                        str(player)
                    )

                extra += (
                    f"• {name}: {guess}\n"
                )

    message = (
        "🎮 **نتیجه بازی**\n"
        "━━━━━━━━━━━━━━\n\n"
        f"{winner_text}"
        f"{extra}"
    )

    if achievement_messages:

        message += (
            "\n\n🏅 **دستاورد جدید!**\n"
            +
            "\n".join(
                achievement_messages
            )
        )

    remove_room(
        room
    )

    return message


# ============================================================
# DONKEY SOUND
# ============================================================

DONKEY_SOUNDS = [

    "عررررررررر 🫏🔊",

    "عرررررر! 😎🫏",

    "هیییییییییی عررر! 😂",

    "عررررررررررررر! 🔥",

    "هَهاااااااااااا! 🫏",

]


async def donkey_sound(
    update,
    user_id
):

    donkey = get_donkey(
        user_id
    )

    if not donkey:

        return (
            "❌ خر پیدا نشد."
        )

    cost = 25

    if not remove_coins(
        user_id,
        cost,
        reason="donkey_sound"
    ):

        return (
            f"❌ برای عرعر کردن "
            f"{cost} سکه لازم داری."
        )

    sound = random.choice(
        DONKEY_SOUNDS
    )

    multiplier = donkey[
        "sounds"
    ]

    score = random.randint(
        5,
        10
    ) * multiplier

    add_coins(
        user_id,
        score,
        reason="donkey_sound_reward"
    )

    add_xp(
        user_id,
        2
    )

    return (
        f"🔊 {sound}\n\n"
        f"🎯 امتیاز عرعر: "
        f"**{score}**\n"
        f"🪙 جایزه: "
        f"**+{score}** سکه\n"
        f"💸 هزینه: "
        f"{cost} سکه"
    )


# ============================================================
# HELP
# ============================================================

def help_text():

    return (

        "📖 **راهنمای خرستان**\n"
        "━━━━━━━━━━━━━━\n\n"

        "🫏 **خر من**\n"
        "خر اختصاصی خودت را مدیریت کن.\n"
        "برای غذا، آب، حمام، بازی و ارتقا سکه خرج کن.\n\n"

        "🎮 **بازی‌ها**\n"
        "۱۰ بازی مختلف داری.\n"
        "می‌توانی با بات یا بازیکنان گروه بازی کنی.\n\n"

        "🛒 **فروشگاه**\n"
        "آیتم بخر و برای خر خودت استفاده کن.\n\n"

        "🏅 **دستاوردها**\n"
        "با انجام فعالیت‌ها اچیومنت باز کن و جایزه بگیر.\n\n"

        "🏆 **لیدربرد**\n"
        "ثروتمندترین بازیکنان را ببین.\n\n"

        "🎁 **جایزه روزانه**\n"
        "هر ۲۴ ساعت یک جایزه دریافت کن.\n\n"

        "💡 نکته:\n"
        "شرط‌بندی باعث برد یا باخت سکه می‌شود؛ "
        "قبل از بازی موجودی خودت را بررسی کن."

    )


# ============================================================
# OWNER PANEL
# ============================================================

def owner_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📊 آمار",
                callback_data="owner_stats"
            )
        ],

        [
            InlineKeyboardButton(
                "💰 اقتصاد",
                callback_data="owner_economy"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="home"
            )
        ],

    ])


def owner_stats_text():

    with closing(db_connect()) as db:

        users = db.execute(
            """
            SELECT COUNT(*) AS c
            FROM users
            """
        ).fetchone()["c"]

        coins = db.execute(
            """
            SELECT COALESCE(
                SUM(coins),
                0
            ) AS c
            FROM users
            """
        ).fetchone()["c"]

        wins = db.execute(
            """
            SELECT COALESCE(
                SUM(wins),
                0
            ) AS c
            FROM users
            """
        ).fetchone()["c"]

        losses = db.execute(
            """
            SELECT COALESCE(
                SUM(losses),
                0
            ) AS c
            FROM users
            """
        ).fetchone()["c"]

    return (

        "👑 **پنل Owner**\n"
        "━━━━━━━━━━━━━━\n\n"

        f"👥 کاربران: "
        f"{users:,}\n"

        f"🪙 مجموع سکه کاربران: "
        f"{coins:,}\n"

        f"🏆 مجموع بردها: "
        f"{wins:,}\n"

        f"💀 مجموع باخت‌ها: "
        f"{losses:,}\n"

        f"🎮 بازی فعال: "
        f"{len(ACTIVE_GAMES):,}"

    )


# ============================================================
# COMMAND HANDLERS
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    ensure_user(
        user.id,
        user.first_name or "Player"
    )

    text = (

        "🫏 **به خرستان خوش اومدی!**\n"
        "━━━━━━━━━━━━━━\n\n"

        "اینجا هر بازیکن یک خر اختصاصی داره.\n"
        "خر خودت رو ارتقا بده، بازی کن، "
        "سکه جمع کن و لیدربرد رو فتح کن! 🔥\n\n"

        f"🪙 سرمایه اولیه: "
        f"{START_COINS:,} سکه"

    )

    await update.message.reply_text(
        text,
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


async def profile_command(
    update,
    context
):

    user = update.effective_user

    ensure_user(
        user.id,
        user.first_name or "Player"
    )

    await update.message.reply_text(
        profile_text(user.id),
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🫏 خر من",
                    callback_data="donkey"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏅 اچیومنت‌ها",
                    callback_data="achievements"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 منو",
                    callback_data="home"
                )
            ]
        ]),
        parse_mode="Markdown"
    )


async def donkey_command(
    update,
    context
):

    user = update.effective_user

    ensure_user(
        user.id,
        user.first_name or "Player"
    )

    await update.message.reply_text(
        donkey_profile_text(
            user.id
        ),
        reply_markup=donkey_menu(),
        parse_mode="Markdown"
    )


async def games_command(
    update,
    context
):

    user = update.effective_user

    ensure_user(
        user.id,
        user.first_name or "Player"
    )

    await update.message.reply_text(
        games_text(),
        reply_markup=games_keyboard(),
        parse_mode="Markdown"
    )


async def daily_command(
    update,
    context
):

    user = update.effective_user

    ensure_user(
        user.id,
        user.first_name or "Player"
    )

    success, message = claim_daily(
        user.id
    )

    await update.message.reply_text(
        message,
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


async def shop_command(
    update,
    context
):

    user = update.effective_user

    ensure_user(
        user.id,
        user.first_name or "Player"
    )

    await update.message.reply_text(
        shop_text(),
        reply_markup=shop_keyboard(),
        parse_mode="Markdown"
    )


async def leaderboard_command(
    update,
    context
):

    user = update.effective_user

    ensure_user(
        user.id,
        user.first_name or "Player"
    )

    await update.message.reply_text(
        leaderboard_text(),
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 منو",
                    callback_data="home"
                )
            ]
        ]),
        parse_mode="Markdown"
    )


async def help_command(
    update,
    context
):

    await update.message.reply_text(
        help_text(),
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# ============================================================
# CALLBACK HANDLER
# ============================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    ensure_user(
        user.id,
        user.first_name or "Player"
    )

    data = query.data

    # ----------------------------------------
    # HOME
    # ----------------------------------------

    if data == "home":

        await query.edit_message_text(
            "🫏 **خرستان**\n\n"
            "به منوی اصلی برگشتی.",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # PROFILE
    # ----------------------------------------

    if data == "profile":

        await query.edit_message_text(
            profile_text(user.id),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🫏 خر من",
                        callback_data="donkey"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏅 اچیومنت‌ها",
                        callback_data="achievements"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 منو",
                        callback_data="home"
                    )
                ]
            ]),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # ACHIEVEMENTS
    # ----------------------------------------

    if data == "achievements":

        await query.edit_message_text(
            achievements_text(
                user.id
            ),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔄 بررسی دوباره",
                        callback_data="achievements"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 پروفایل",
                        callback_data="profile"
                    )
                ]
            ]),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # DONKEY
    # ----------------------------------------

    if data == "donkey":

        await query.edit_message_text(
            donkey_profile_text(
                user.id
            ),
            reply_markup=donkey_menu(),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # DONKEY ACTIONS
    # ----------------------------------------

    actions = {

        "d_food":
            "food",

        "d_water":
            "water",

        "d_shower":
            "shower",

        "d_rest":
            "rest",

        "d_play":
            "play",

    }

    if data in actions:

        success, message = donkey_action(
            user.id,
            actions[data]
        )

        await query.edit_message_text(
            (
                "🫏 **خر من**\n\n"
                f"{message}\n\n"
                +
                donkey_profile_text(
                    user.id
                )
            ),
            reply_markup=donkey_menu(),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # DONKEY SOUND
    # ----------------------------------------

    if data == "d_sound":

        message = await donkey_sound(
            query,
            user.id
        )

        await query.edit_message_text(
            message,
            reply_markup=donkey_menu(),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # UPGRADES
    # ----------------------------------------

    if data == "upgrades":

        donkey = get_donkey(
            user.id
        )

        text = (

            "⬆️ **ارتقای خر**\n"
            "━━━━━━━━━━━━━━\n\n"

            f"💪 قدرت: "
            f"{donkey['strength']}\n"

            f"🏃 سرعت: "
            f"{donkey['speed']}\n"

            f"🍀 شانس: "
            f"{donkey['luck']}\n"

            f"🔊 عرعر: "
            f"{donkey['sounds']}\n\n"

            "هر ارتقا هزینه بیشتری دارد."

        )

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "💪 +قدرت",
                    callback_data="up_strength"
                ),

                InlineKeyboardButton(
                    "🏃 +سرعت",
                    callback_data="up_speed"
                )
            ],

            [
                InlineKeyboardButton(
                    "🍀 +شانس",
                    callback_data="up_luck"
                ),

                InlineKeyboardButton(
                    "🔊 +عرعر",
                    callback_data="up_sounds"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔙 خر من",
                    callback_data="donkey"
                )
            ]

        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # UPGRADE ACTION
    # ----------------------------------------

    if data.startswith("up_"):

        stat = data[3:]

        success, message = upgrade_donkey(
            user.id,
            stat
        )

        await query.edit_message_text(
            f"{message}\n\n"
            +
            donkey_profile_text(
                user.id
            ),
            reply_markup=donkey_menu(),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # GAMES
    # ----------------------------------------

    if data == "games":

        await query.edit_message_text(
            games_text(),
            reply_markup=games_keyboard(),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # GAME SELECT
    # ----------------------------------------

    if data.startswith("game_"):

        game_type = data[5:]

        if game_type not in GAME_NAMES:

            await query.edit_message_text(
                "❌ بازی نامعتبر."
            )

            return

        USER_GAME_SELECTION[
            user.id
        ] = game_type

        await query.edit_message_text(
            f"{GAME_NAMES[game_type]}\n\n"
            "💰 مبلغ شرط را انتخاب کن:",
            reply_markup=game_bet_keyboard(),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # BOT GAME
    # ----------------------------------------

    if data == "bet_bot":

        game_type = USER_GAME_SELECTION.get(
            user.id
        )

        if not game_type:

            await query.edit_message_text(
                "❌ ابتدا یک بازی انتخاب کن.",
                reply_markup=games_keyboard()
            )

            return

        USER_GAME_SELECTION[
            user.id
        ] = (
            game_type,
            "bot"
        )

        await query.edit_message_text(
            f"{GAME_NAMES[game_type]}\n\n"
            "💰 مبلغ شرط را انتخاب کن:",
            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "50 🪙",
                        callback_data="botbet_50"
                    ),

                    InlineKeyboardButton(
                        "100 🪙",
                        callback_data="botbet_100"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "250 🪙",
                        callback_data="botbet_250"
                    ),

                    InlineKeyboardButton(
                        "500 🪙",
                        callback_data="botbet_500"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "1000 🪙",
                        callback_data="botbet_1000"
                    ),

                    InlineKeyboardButton(
                        "5000 🪙",
                        callback_data="botbet_5000"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="games"
                    )
                ]

            ]),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # NORMAL BET
    # ----------------------------------------

    if data.startswith("bet_"):

        try:

            bet = int(
                data[4:]
            )

        except ValueError:

            return

        game_type = USER_GAME_SELECTION.get(
            user.id
        )

        if not game_type or isinstance(
            game_type,
            tuple
        ):

            await query.edit_message_text(
                "❌ ابتدا بازی را انتخاب کن.",
                reply_markup=games_keyboard()
            )

            return

        room, error = create_room(
            game_type,
            query.message.chat_id,
            user.id,
            bet,
            max_players=4,
            against_bot=False
        )

        if error:

            await query.edit_message_text(
                error,
                reply_markup=games_keyboard()
            )

            return

        await query.edit_message_text(
            room_text(room),
            reply_markup=room_keyboard(room),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # BOT BET
    # ----------------------------------------

    if data.startswith("botbet_"):

        try:

            bet = int(
                data[7:]
            )

        except ValueError:

            return

        selection = USER_GAME_SELECTION.get(
            user.id
        )

        if not isinstance(
            selection,
            tuple
        ):

            await query.edit_message_text(
                "❌ ابتدا بازی را انتخاب کن.",
                reply_markup=games_keyboard()
            )

            return

        game_type = selection[0]

        room, error = create_room(
            game_type,
            query.message.chat_id,
            user.id,
            bet,
            max_players=2,
            against_bot=True
        )

        if error:

            await query.edit_message_text(
                error,
                reply_markup=games_keyboard()
            )

            return

        room.started = True

        winner, result = run_game(
            room
        )

        message = await finish_game(
            update,
            room,
            winner,
            result
        )

        await query.edit_message_text(
            message,
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # JOIN
    # ----------------------------------------

    if data == "game_join":

        room = get_room(
            query.message.chat_id
        )

        if not room:

            await query.answer(
                "❌ بازی وجود ندارد.",
                show_alert=True
            )

            return

        success, message = join_room(
            room,
            user.id
        )

        await query.answer(
            message,
            show_alert=True
        )

        if success:

            await query.edit_message_text(
                room_text(room),
                reply_markup=room_keyboard(room),
                parse_mode="Markdown"
            )

        return

    # ----------------------------------------
    # START
    # ----------------------------------------

    if data == "game_start":

        room = get_room(
            query.message.chat_id
        )

        if not room:

            await query.answer(
                "❌ بازی وجود ندارد.",
                show_alert=True
            )

            return

        if room.creator_id != user.id:

            await query.answer(
                "⛔ فقط سازنده بازی می‌تواند شروع کند.",
                show_alert=True
            )

            return

        if room.started:

            return

        if len(room.players) < 2:

            await query.answer(
                "👥 حداقل دو بازیکن لازم است.",
                show_alert=True
            )

            return

        room.started = True

        winner, result = run_game(
            room
        )

        message = await finish_game(
            update,
            room,
            winner,
            result
        )

        await query.edit_message_text(
            message,
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # CANCEL
    # ----------------------------------------

    if data == "game_cancel":

        room = get_room(
            query.message.chat_id
        )

        if not room:

            await query.answer(
                "❌ بازی وجود ندارد.",
                show_alert=True
            )

            return

        success, message = cancel_room(
            room,
            user.id
        )

        await query.answer(
            message,
            show_alert=True
        )

        if success:

            await query.edit_message_text(
                message,
                reply_markup=main_menu(),
                parse_mode="Markdown"
            )

        return

    # ----------------------------------------
    # SHOP
    # ----------------------------------------

    if data == "shop":

        await query.edit_message_text(
            shop_text(),
            reply_markup=shop_keyboard(),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # BUY
    # ----------------------------------------

    if data.startswith("buy_"):

        item = data[4:]

        success, message = buy_item(
            user.id,
            item
        )

        await query.answer(
            message,
            show_alert=True
        )

        await query.edit_message_text(
            shop_text(),
            reply_markup=shop_keyboard(),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # INVENTORY
    # ----------------------------------------

    if data == "inventory":

        text = (
            "🎒 **کیف من**\n"
            "━━━━━━━━━━━━━━\n\n"
        )

        buttons = []

        for item, item_data in SHOP_ITEMS.items():

            amount = get_item_amount(
                user.id,
                item
            )

            text += (
                f"{item_data['name']}: "
                f"**{amount}**\n"
            )

            if amount > 0:

                buttons.append([
                    InlineKeyboardButton(
                        f"استفاده {item_data['name']}",
                        callback_data=f"use_{item}"
                    )
                ])

        buttons.append([
            InlineKeyboardButton(
                "🛒 فروشگاه",
                callback_data="shop"
            )
        ])

        buttons.append([
            InlineKeyboardButton(
                "🔙 منو",
                callback_data="home"
            )
        ])

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                buttons
            ),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # USE ITEM
    # ----------------------------------------

    if data.startswith("use_"):

        item = data[4:]

        success, message = use_item(
            user.id,
            item
        )

        await query.answer(
            message,
            show_alert=True
        )

        # دوباره کیف
        text = (
            "🎒 **کیف من**\n"
            "━━━━━━━━━━━━━━\n\n"
        )

        buttons = []

        for item_id, item_data in SHOP_ITEMS.items():

            amount = get_item_amount(
                user.id,
                item_id
            )

            text += (
                f"{item_data['name']}: "
                f"**{amount}**\n"
            )

            if amount > 0:

                buttons.append([
                    InlineKeyboardButton(
                        f"استفاده {item_data['name']}",
                        callback_data=f"use_{item_id}"
                    )
                ])

        buttons.append([
            InlineKeyboardButton(
                "🛒 فروشگاه",
                callback_data="shop"
            )
        ])

        buttons.append([
            InlineKeyboardButton(
                "🔙 منو",
                callback_data="home"
            )
        ])

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                buttons
            ),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # LEADERBOARD
    # ----------------------------------------

    if data == "leaderboard":

        await query.edit_message_text(
            leaderboard_text(),
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
                        callback_data="home"
                    )
                ]
            ]),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # DAILY
    # ----------------------------------------

    if data == "daily":

        success, message = claim_daily(
            user.id
        )

        await query.answer(
            message,
            show_alert=True
        )

        await query.edit_message_text(
            message,
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # HELP
    # ----------------------------------------

    if data == "help":

        await query.edit_message_text(
            help_text(),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 منو",
                        callback_data="home"
                    )
                ]
            ]),
            parse_mode="Markdown"
        )

        return

    # ----------------------------------------
    # OWNER
    # ----------------------------------------

    if data == "owner":

        if user.id != OWNER_ID:

            await query.answer(
                "⛔ دسترسی ندارید.",
                show_alert=True
            )

            return

        await query.edit_message_text(
            owner_stats_text(),
            reply_markup=owner_keyboard(),
            parse_mode="Markdown"
        )

        return

    if data == "owner_stats":

        if user.id != OWNER_ID:
            return

        await query.edit_message_text(
            owner_stats_text(),
            reply_markup=owner_keyboard(),
            parse_mode="Markdown"
        )

        return


# ============================================================
# OWNER COMMAND
# ============================================================

async def owner_command(
    update,
    context
):

    user = update.effective_user

    if user.id != OWNER_ID:

        await update.message.reply_text(
            "⛔ این بخش فقط برای Owner است."
        )

        return

    await update.message.reply_text(
        owner_stats_text(),
        reply_markup=owner_keyboard(),
        parse_mode="Markdown"
    )


# ============================================================
# CANCEL COMMAND
# ============================================================

async def cancel_command(
    update,
    context
):

    user = update.effective_user

    chat_id = update.effective_chat.id

    room = get_room(
        chat_id
    )

    if not room:

        await update.message.reply_text(
            "❌ بازی فعالی وجود ندارد."
        )

        return

    success, message = cancel_room(
        room,
        user.id
    )

    await update.message.reply_text(
        message,
        reply_markup=main_menu()
    )


# ============================================================
# BALANCE COMMAND
# ============================================================

async def balance_command(
    update,
    context
):

    user = update.effective_user

    ensure_user(
        user.id,
        user.first_name or "Player"
    )

    data = get_user(
        user.id
    )

    await update.message.reply_text(
        f"🪙 موجودی تو:\n\n"
        f"**{data['coins']:,} سکه**",
        parse_mode="Markdown"
    )


# ============================================================
# TEXT HANDLER
# ============================================================

async def text_handler(
    update,
    context
):

    user = update.effective_user

    ensure_user(
        user.id,
        user.first_name or "Player"
    )

    text = (
        update.message.text
        or
        ""
    ).strip()

    commands = {

        "خر من":
            donkey_profile_text(
                user.id
            ),

        "پروفایل":
            profile_text(
                user.id
            ),

        "بازی":
            games_text(),

        "فروشگاه":
            shop_text(),

        "لیدربرد":
            leaderboard_text(),

        "راهنما":
            help_text(),

    }

    if text in commands:

        if text == "خر من":

            await update.message.reply_text(
                commands[text],
                reply_markup=donkey_menu(),
                parse_mode="Markdown"
            )

        elif text == "بازی":

            await update.message.reply_text(
                commands[text],
                reply_markup=games_keyboard(),
                parse_mode="Markdown"
            )

        elif text == "فروشگاه":

            await update.message.reply_text(
                commands[text],
                reply_markup=shop_keyboard(),
                parse_mode="Markdown"
            )

        else:

            await update.message.reply_text(
                commands[text],
                reply_markup=main_menu(),
                parse_mode="Markdown"
            )

        return

    # اگر چیزی متوجه نشد
    await update.message.reply_text(
        "🤔 این دستور را متوجه نشدم.\n\n"
        "از /start استفاده کن.",
        reply_markup=main_menu()
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context
):

    logger.exception(
        "Telegram error:",
        exc_info=context.error
    )


# ============================================================
# GAME CLEANUP
# ============================================================

async def cleanup_games(
    application
):

    while True:

        try:

            now = time.time()

            expired = []

            for key, room in list(
                ACTIVE_GAMES.items()
            ):

                if (
                    now
                    -
                    room.created_at
                    >
                    600
                ):

                    expired.append(
                        room
                    )

            for room in expired:

                for player in room.players:

                    if player != -1:

                        add_coins(
                            player,
                            room.bet,
                            reason="expired_game_refund"
                        )

                remove_room(
                    room
                )

            await asyncio.sleep(
                60
            )

        except Exception:

            logger.exception(
                "Cleanup error"
            )

            await asyncio.sleep(
                60
            )


# ============================================================
# PERIODIC DONKEY DECAY
# ============================================================

async def donkey_decay():

    while True:

        try:

            with closing(
                db_connect()
            ) as db:

                db.execute(
                    """
                    UPDATE donkeys
                    SET
                        hunger =
                        MAX(0, hunger - 2),

                        thirst =
                        MAX(0, thirst - 3),

                        energy =
                        MAX(0, energy - 1),

                        happiness =
                        MAX(0, happiness - 1)
                    """
                )

                db.commit()

        except Exception:

            logger.exception(
                "Donkey decay error"
            )

        await asyncio.sleep(
            3600
        )


# ============================================================
# POST INIT
# ============================================================

async def post_init(
    application
):

    asyncio.create_task(
        cleanup_games(
            application
        )
    )

    asyncio.create_task(
        donkey_decay()
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN is not configured."
        )

    init_db()

    init_achievement_db()

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # -------------------------------
    # COMMANDS
    # -------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "profile",
            profile_command
        )
    )

    application.add_handler(
        CommandHandler(
            "donkey",
            donkey_command
        )
    )

    application.add_handler(
        CommandHandler(
            "games",
            games_command
        )
    )

    application.add_handler(
        CommandHandler(
            "daily",
            daily_command
        )
    )

    application.add_handler(
        CommandHandler(
            "shop",
            shop_command
        )
    )

    application.add_handler(
        CommandHandler(
            "leaderboard",
            leaderboard_command
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
            "balance",
            balance_command
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_command
        )
    )

    application.add_handler(
        CommandHandler(
            "owner",
            owner_command
        )
    )

    # -------------------------------
    # CALLBACKS
    # -------------------------------

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    # -------------------------------
    # TEXT
    # -------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT
            &
            ~filters.COMMAND,
            text_handler
        )
    )

    # -------------------------------
    # ERRORS
    # -------------------------------

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "KHARBOT PRO started."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()