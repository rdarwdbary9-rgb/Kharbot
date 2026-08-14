============================================================
KHARBOT PRO - ULTIMATE VERSION (CLEAN)
============================================================

import os
import time
import random
import sqlite3
import logging
import asyncio
import itertools
import json
from contextlib import closing
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

============================================================
CONFIG & LOGGING
============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DB_FILE = "/tmp/kharbot.db"
MIN_BET = 10
START_COINS = 2500
MAX_PLAYERS = 10

CURRENCY_NAME = "تي تاپ"
CURRENCY_EMOJI = ""

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("KHARBOT")

============================================================
DATABASE SETUP
============================================================

def db_connect():
    db = sqlite3.connect(DB_FILE, timeout=20)
    db.row_factory = sqlite3.Row
    return db

def init_db():
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

============================================================
USER MANAGEMENT
============================================================

def ensure_user(user_id, name="Player"):
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

============================================================
TITLE SYSTEM
============================================================

def get_title_by_level(level):
    titles = {
        1: "korekhar tazehkar",
        2: "khar karamoz",
        3: "khar maher",
        4: "khar horfei",
        5: "khar ostad",
        6: "takshakh afsanei",
        7: "ejdehaye zarin",
        8: "khar setarei",
        9: "khar kahkeshani",
        10: "khoda kharha"
    }
    return titles.get(level, "korekhar tazehkar")

============================================================
PROFILE
============================================================

def profile_text(user_id):
    u = get_user(user_id)
    if not u:
        return "Error: User not found."
    
    level = u["level"]
    title = get_title_by_level(level)
    donkey = get_donkey(user_id)
    babies = json.loads(u["baby_names"]) if u["baby_names"] else []
    
    equipped_parts = []
    if donkey:
        if donkey["equipped_hat"]: equipped_parts.append("Hat: " + donkey["equipped_hat"])
        if donkey["equipped_saddle"]: equipped_parts.append("Saddle: " + donkey["equipped_saddle"])
        if donkey["equipped_horseshoe"]: equipped_parts.append("Horseshoe: " + donkey["equipped_horseshoe"])
        if donkey["equipped_tie"]: equipped_parts.append("Tie: " + donkey["equipped_tie"])
        if donkey["equipped_clothes"]: equipped_parts.append("Clothes: " + donkey["equipped_clothes"])
        if donkey["equipped_accessory"]: equipped_parts.append("Accessory: " + donkey["equipped_accessory"])
    
    msg = (
        f"Profile of {u['name']}\n"
        f"========================\n"
        f"Title: {title}\n"
        f"Level: {level}\n"
        f"T-Top: {u['coins']:,}\n"
        f"Wins: {u['wins']} | Losses: {u['losses']}\n"
    )
    
    if equipped_parts:
        msg += f"\nActive Items:\n"
        for part in equipped_parts:
            msg += f"{part}\n"
    else:
        msg += f"\nActive Items: None"
    
    if babies:
        msg += f"\nBabies: {len(babies)}\n"
        for i, baby in enumerate(babies[:3], 1):
            msg += f"{i}. {baby}\n"
        if len(babies) > 3:
            msg += f"... and {len(babies)-3} more"
    else:
        msg += f"\nBabies: None"
    
    return msg

============================================================
DAILY REWARD
============================================================

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
        return await update.message.reply_text(
            f"{hours} hours and {minutes} minutes left for next daily reward!"
        )
    
    reward = random.randint(DAILY_MIN, DAILY_MAX)
    bonus = ""
    if random.random() < 0.10:
        extra = random.randint(50, 200)
        reward += extra
        bonus = f"\nSpecial Reward! +{extra} T-Top"
    
    add_coins(user.id, reward)
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET last_daily = ? WHERE user_id = ?", (now, user.id))
        db.commit()
    
    await update.message.reply_text(
        f"Daily Reward!\n"
        f"========================\n"
        f"{user.first_name}\n"
        f"Reward: {reward} T-Top"
        f"{bonus}\n"
        f"\nCome back tomorrow!"
    )

============================================================
DONKEY SOUND SYSTEM
============================================================

SOUND_KEYWORDS = {
    "ar": {"sound": "ar ar ar", "desc": "Normal donkey sound"},
    "arar": {"sound": "ar ar ar ar", "desc": "Repeated sound"},
    "arr": {"sound": "arrrrrrr", "desc": "Long sound"},
    "trak": {"sound": "ar-ar-ar-ar (Trak!)", "desc": "Broken sound"},
    "turk": {"sound": "arrrrrrrrr (Turk!)", "desc": "Twisted sound"}
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
        return await update.message.reply_text(
            f"Wait {minutes} minutes and {seconds} seconds to sound again!"
        )
    
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
        bonus = "\nSpecial Reward!"
    
    if reward > 0:
        add_coins(user.id, reward)
    
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET last_sound = ? WHERE user_id = ?", (now, user.id))
        db.commit()
    
    await update.message.reply_text(
        f"Donkey Sound!\n"
        f"========================\n"
        f"{sound_info['sound']}\n"
        f"{sound_info['desc']}\n"
        f"\n{user.first_name}\n"
        f"Reward: {reward} T-Top"
        f"{bonus}"
    )

============================================================
MATING SYSTEM
============================================================

MATE_COST = 500
MAX_BABIES = 5
MATE_COOLDOWN = 86400

async def mate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id, user.first_name)
    
    if not update.message.reply_to_message:
        return await update.message.reply_text(
            "Reply to the target person's message and type: mate"
        )
    
    target = update.message.reply_to_message.from_user
    target_id = target.id
    
    if user.id == target_id:
        return await update.message.reply_text("You cannot mate with yourself!")
    
    ensure_user(target_id, target.first_name)
    u1 = get_user(user.id)
    u2 = get_user(target_id)
    
    if u1["level"] < 2:
        return await update.message.reply_text(f"{user.first_name}, your level is {u1['level']}. You need level 2 to mate!")
    
    if u2["level"] < 2:
        return await update.message.reply_text(f"{target.first_name}, level is {u2['level']}. Need level 2 to mate!")
    
    if u1["coins"] < MATE_COST:
        return await update.message.reply_text(f"{user.first_name} doesn't have {MATE_COST} T-Top!")
    if u2["coins"] < MATE_COST:
        return await update.message.reply_text(f"{target.first_name} doesn't have {MATE_COST} T-Top!")
    
    babies1 = json.loads(u1["baby_names"]) if u1["baby_names"] else []
    babies2 = json.loads(u2["baby_names"]) if u2["baby_names"] else []
    
    if len(babies1) >= MAX_BABIES:
        return await update.message.reply_text(f"{user.first_name} has max babies! ({MAX_BABIES})")
    if len(babies2) >= MAX_BABIES:
        return await update.message.reply_text(f"{target.first_name} has max babies! ({MAX_BABIES})")
    
    now = int(time.time())
    if now - u1["last_mate"] < MATE_COOLDOWN:
        remaining = (MATE_COOLDOWN - (now - u1["last_mate"])) // 3600
        return await update.message.reply_text(f"{user.first_name}, wait {remaining} hours to mate again!")
    if now - u2["last_mate"] < MATE_COOLDOWN:
        remaining = (MATE_COOLDOWN - (now - u2["last_mate"])) // 3600
        return await update.message.reply_text(f"{target.first_name}, wait {remaining} hours to mate again!")
    
    remove_coins(user.id, MATE_COST)
    remove_coins(target_id, MATE_COST)
    
    baby_names = ["Baby Donkey 1", "Baby Donkey 2", "Baby Donkey 3", "Baby Donkey 4", "Baby Donkey 5"]
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
        f"Mating Successful!\n"
        f"========================\n"
        f"{user.first_name} + {target.first_name}\n\n"
        f"Baby Born: {baby_name}\n"
        f"{user.first_name} babies: {len(babies1)}\n"
        f"{target.first_name} babies: {len(babies2)}\n\n"
        f"Cost: {MATE_COST} T-Top each"
    )

============================================================
GAME NAMES
============================================================

GAME_NAMES = {
    "rps": "Rock-Paper-Scissors",
    "blackjack": "Blackjack 21",
    "crash": "Crash",
    "poker": "Poker",
    "ttt": "Tic-Tac-Toe",
    "dice": "Dice",
    "roulette": "Russian Roulette"
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

GAME_HANDLERS = {}

async def game_placeholder(room, context):
    await context.bot.edit_message_text(
        "This game is under development!",
        chat_id=room.chat_id,
        message_id=room.message_id
    )

for game in GAME_NAMES.keys():
    GAME_HANDLERS[game] = game_placeholder

============================================================
ROOM MANAGEMENT
============================================================

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

============================================================
UI COMPONENTS
============================================================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Games", callback_data="games_list")],
        [InlineKeyboardButton("Profile", callback_data="show_profile"), 
         InlineKeyboardButton("Shop", callback_data="shop")],
        [InlineKeyboardButton("Leaderboard", callback_data="leaderboard")]
    ])

def games_menu():
    buttons = []
    for key, name in GAME_NAMES.items():
        buttons.append([InlineKeyboardButton(name, callback_data=f"game_{key}")])
    buttons.append([InlineKeyboardButton("Back", callback_data="home")])
    return InlineKeyboardMarkup(buttons)

def shop_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Hats", callback_data="shop_hats")],
        [InlineKeyboardButton("Saddles", callback_data="shop_saddles")],
        [InlineKeyboardButton("Horseshoes", callback_data="shop_horseshoes")],
        [InlineKeyboardButton("Ties", callback_data="shop_ties")],
        [InlineKeyboardButton("Clothes", callback_data="shop_clothes")],
        [InlineKeyboardButton("Accessories", callback_data="shop_accessories")],
        [InlineKeyboardButton("Back", callback_data="home")]
    ])

============================================================
SHOP DATA
============================================================

SHOP_ITEMS = {
    "hats": {
        "name": "Hats",
        "items": {
            "Straw Hat": {"price": 500},
            "Cowboy Hat": {"price": 2000},
            "Military Hat": {"price": 4000},
            "Fancy Hat": {"price": 7000},
            "Royal Crown": {"price": 15000}
        }
    },
    "saddles": {
        "name": "Saddles",
        "items": {
            "Simple Leather": {"price": 1000},
            "Silver Saddle": {"price": 3500},
            "Golden Saddle": {"price": 8000},
            "Diamond Saddle": {"price": 20000}
        }
    },
    "horseshoes": {
        "name": "Horseshoes",
        "items": {
            "Iron Horseshoe": {"price": 500},
            "Bronze Horseshoe": {"price": 2000},
            "Silver Horseshoe": {"price": 5000},
            "Golden Horseshoe": {"price": 12000}
        }
    },
    "ties": {
        "name": "Ties",
        "items": {
            "Simple Tie": {"price": 500},
            "Striped Tie": {"price": 1500},
            "Sparkly Tie": {"price": 3000},
            "Silk Tie": {"price": 6000},
            "Royal Tie": {"price": 10000}
        }
    },
    "clothes": {
        "name": "Clothes",
        "items": {
            "Simple Clothes": {"price": 500},
            "Fancy Clothes": {"price": 2000},
            "Formal Clothes": {"price": 4000},
            "Military Uniform": {"price": 7000},
            "Royal Clothes": {"price": 15000}
        }
    },
    "accessories": {
        "name": "Accessories",
        "items": {
            "Neck Bell": {"price": 500},
            "Simple Bow": {"price": 1000},
            "Sunglasses": {"price": 2500},
            "Scarf": {"price": 4000},
            "Angel Wings": {"price": 10000}
        }
    }
}

============================================================
MESSAGE HANDLER
============================================================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    ensure_user(user.id, user.first_name)
    
    u_data = get_user(user.id)
    if u_data and u_data["is_banned"] == 1:
        return await update.message.reply_text("You are banned!")
    
    # ===== ADMIN COMMANDS =====
    if user.id == OWNER_ID and update.message.reply_to_message:
        parts = text.split()
        if not parts:
            return
        cmd = parts[0].lower()
        target = update.message.reply_to_message.from_user
        
        if cmd in ["/ban", "ban"]:
            with closing(db_connect()) as db:
                db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (target.id,))
                db.commit()
            await update.message.reply_text(f"{target.first_name} banned!")
            return
        if cmd in ["/unban", "unban"]:
            with closing(db_connect()) as db:
                db.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (target.id,))
                db.commit()
            await update.message.reply_text(f"{target.first_name} unbanned!")
            return
        if cmd in ["/addcoin", "+coin"] and len(parts) > 1:
            try:
                amt = int(parts[1])
                add_coins(target.id, amt)
                await update.message.reply_text(f"{amt:,} T-Top added to {target.first_name}!")
            except:
                pass
            return
        if cmd in ["/remcoin", "-coin"] and len(parts) > 1:
            try:
                amt = int(parts[1])
                with closing(db_connect()) as db:
                    db.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (amt, target.id))
                    db.commit()
                await update.message.reply_text(f"{amt:,} T-Top removed from {target.first_name}!")
            except:
                pass
            return
    
    # ===== START =====
    if text.startswith("/start"):
        return await update.message.reply_text(
            "Welcome to Kharbot!\n\n"
            "Features:\n"
            "- 7 different games\n"
            "- Compete with friends\n"
            "- Daily rewards\n"
            "- Donkey sounds with rewards\n"
            "- Mate and have baby donkeys\n"
            "- Decorate your donkey\n\n"
            "Use the menu:",
            reply_markup=main_menu()
        )
    
    # ===== DAILY REWARD =====
    if text in ["daily", "day"]:
        await daily_reward(update, context)
        return
    
    # ===== MATE =====
    if text in ["mate", "جفت"]:
        await mate_command(update, context)
        return
    
    # ===== PROFILE =====
    if text in ["profile", "p"]:
        if update.message.reply_to_message:
            target = update.message.reply_to_message.from_user
            target_id = target.id
        else:
            target_id = user.id
        return await update.message.reply_text(
            profile_text(target_id),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="home")]])
        )
    
    # ===== COINS =====
    if text in ["coins", "c"]:
        u = get_user(user.id)
        return await update.message.reply_text(
            f"Your Balance: {u['coins']:,} T-Top",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="home")]])
        )
    
    # ===== LEADERBOARD =====
    if text in ["leaderboard", "top", "table"]:
        with closing(db_connect()) as db:
            rows = db.execute(
                "SELECT user_id, name, coins, level FROM users ORDER BY coins DESC LIMIT 10"
            ).fetchall()
        
        if not rows:
            return await update.message.reply_text("No users yet!")
        
        msg = "Leaderboard\n========================\n"
        for i, row in enumerate(rows, 1):
            medal = ["1st", "2nd", "3rd"][i-1] if i <= 3 else f"{i}."
            title = get_title_by_level(row["level"])
            msg += f"{medal} {title} {row['name']} - {row['coins']:,} T-Top (Level {row['level']})\n"
        
        user_row = db.execute(
            "SELECT COUNT(*) + 1 as rank FROM users WHERE coins > (SELECT coins FROM users WHERE user_id = ?)",
            (user.id,)
        ).fetchone()
        
        if user_row and user_row["rank"]:
            msg += f"\n========================\nYour Rank: #{user_row['rank']}"
        
        return await update.message.reply_text(msg)
    
    # ===== DONKEY SOUND =====
    if text in ["ar", "arar", "arr", "trak", "turk"]:
        await donkey_sound(update, context)
        return

============================================================
CALLBACK HANDLER
============================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    ensure_user(user.id, user.first_name)
    
    u_data = get_user(user.id)
    if u_data and u_data["is_banned"] == 1:
        return await query.edit_message_text("You are banned!")
    
    data = query.data
    
    # ===== HOME =====
    if data == "home":
        return await query.edit_message_text(
            "Main Menu",
            reply_markup=main_menu()
        )
    
    # ===== GAMES LIST =====
    if data == "games_list":
        return await query.edit_message_text(
            "Select Game:",
            reply_markup=games_menu()
        )
    
    # ===== GAME SELECTION =====
    if data.startswith("game_"):
        game_type = data[5:]
        if game_type not in GAME_NAMES:
            return
        
        if user.id in PLAYER_IN_GAME:
            return await query.answer("You are already in a game!", show_alert=True)
        
        context.user_data["temp_game"] = game_type
        context.user_data["awaiting_bet"] = True
        
        await query.edit_message_text(
            f"Game: {GAME_NAMES[game_type]}\n"
            f"========================\n"
            f"Min Bet: {MIN_BET} T-Top\n"
            f"Max Players: {GAME_MAX_PLAYERS[game_type]}\n\n"
            f"Enter bet amount (number):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="games_list")]])
        )
        context.user_data["awaiting_bet"] = True
        return
    
    # ===== PROFILE =====
    if data == "show_profile":
        return await query.edit_message_text(
            profile_text(user.id),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="home")]])
        )
    
    # ===== LEADERBOARD =====
    if data == "leaderboard":
        with closing(db_connect()) as db:
            rows = db.execute(
                "SELECT user_id, name, coins, level FROM users ORDER BY coins DESC LIMIT 10"
            ).fetchall()
        
        if not rows:
            return await query.edit_message_text("No users yet!")
        
        msg = "Leaderboard\n========================\n"
        for i, row in enumerate(rows, 1):
            medal = ["1st", "2nd", "3rd"][i-1] if i <= 3 else f"{i}."
            title = get_title_by_level(row["level"])
            msg += f"{medal} {title} {row['name']} - {row['coins']:,} T-Top (Level {row['level']})\n"
        
        user_row = db.execute(
            "SELECT COUNT(*) + 1 as rank FROM users WHERE coins > (SELECT coins FROM users WHERE user_id = ?)",
            (user.id,)
        ).fetchone()
        
        if user_row and user_row["rank"]:
            msg += f"\n========================\nYour Rank: #{user_row['rank']}"
        
        return await query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="home")]])
        )
    
    # ===== SHOP =====
    if data == "shop":
        return await query.edit_message_text(
            "Shop:",
            reply_markup=shop_keyboard()
        )
    
    # ===== SHOP CATEGORIES =====
    if data.startswith("shop_"):
        category = data[5:]
        if category not in SHOP_ITEMS:
            return
        
        cat_data = SHOP_ITEMS[category]
        buttons = []
        for item_name, item_data in cat_data["items"].items():
            buttons.append([InlineKeyboardButton(
                f"{item_name} - {item_data['price']:,} T-Top",
                callback_data=f"buy_{category}_{item_name}"
            )])
        buttons.append([InlineKeyboardButton("Back", callback_data="shop")])
        
        return await query.edit_message_text(
            f"{cat_data['name']}:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    
    # ===== BUY ITEM =====
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
            return await query.answer(f"You don't have {price:,} T-Top!", show_alert=True)
        
        donkey = get_donkey(user.id)
        if not donkey:
            return await query.answer("You don't have a donkey!", show_alert=True)
        
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
        
        await query.answer(f"{item_name} purchased and equipped!", show_alert=True)
        
        await query.edit_message_text(
            f"Purchase Successful!\n{item_name} equipped on your donkey.\nCost: {price:,} T-Top",
            reply_markup=shop_keyboard()
        )
        return

============================================================
MAIN
============================================================

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    init_db()
    logger.info("Database initialized")
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, message_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    logger.info("Kharbot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
