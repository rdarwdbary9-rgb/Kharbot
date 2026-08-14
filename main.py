# ============================================================
# KHARBOT PRO - CHAT SOUND DETECTION (GROUP & PV) + ALL GAMES
# ============================================================

import os
import time
import random
import sqlite3
import logging
import asyncio
from contextlib import closing
from dataclasses import dataclass, field

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# ============================================================
# CONFIG & LOGGING
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DB_FILE = "/tmp/kharbot.db"
MIN_BET = 5
START_COINS = 150

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("KHARBOT")

# ============================================================
# DATABASE SETUP
# ============================================================

def db_connect():
    db = sqlite3.connect(DB_FILE, timeout=20)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    with closing(db_connect()) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, name TEXT NOT NULL, coins INTEGER NOT NULL DEFAULT 150,
            level INTEGER NOT NULL DEFAULT 1, xp INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0,
            last_daily INTEGER NOT NULL DEFAULT 0, is_banned INTEGER DEFAULT 0, created_at INTEGER NOT NULL)""")
        try: db.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
        except: pass
        
        db.execute("""CREATE TABLE IF NOT EXISTS donkeys (
            user_id INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT 'خر من',
            hunger INTEGER NOT NULL DEFAULT 100, thirst INTEGER NOT NULL DEFAULT 100,
            energy INTEGER NOT NULL DEFAULT 100, happiness INTEGER NOT NULL DEFAULT 100,
            strength INTEGER NOT NULL DEFAULT 1, speed INTEGER NOT NULL DEFAULT 1,
            luck INTEGER NOT NULL DEFAULT 1, sounds INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(user_id) REFERENCES users(user_id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER NOT NULL, item TEXT NOT NULL, amount INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id, item))""")
        db.commit()

# ============================================================
# USER & COIN MANAGEMENT
# ============================================================

def ensure_user(user_id, name="Player"):
    now = int(time.time())
    with closing(db_connect()) as db:
        row = db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            db.execute("INSERT INTO users (user_id, name, coins, created_at) VALUES (?, ?, ?, ?)", (user_id, name[:100], START_COINS, now))
            db.execute("INSERT INTO donkeys (user_id) VALUES (?)", (user_id,))
        else:
            db.execute("UPDATE users SET name = ? WHERE user_id = ?", (name[:100], user_id))
        db.commit()

def get_user(user_id):
    with closing(db_connect()) as db: return db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

def get_donkey(user_id):
    with closing(db_connect()) as db: return db.execute("SELECT * FROM donkeys WHERE user_id = ?", (user_id,)).fetchone()

def add_coins(user_id, amount):
    if amount <= 0: return False
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
        db.commit()
    return True

def remove_coins(user_id, amount):
    if amount <= 0: return False
    with closing(db_connect()) as db:
        row = db.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row or row["coins"] < amount: return False
        db.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, user_id))
        db.commit()
    return True

def add_xp(user_id, amount):
    if amount <= 0: return
    with closing(db_connect()) as db:
        row = db.execute("SELECT level, xp FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row: return
        level, xp = row["level"], row["xp"] + amount
        while xp >= 100 + ((level - 1) * 75):
            xp -= 100 + ((level - 1) * 75)
            level += 1
        db.execute("UPDATE users SET level = ?, xp = ? WHERE user_id = ?", (level, xp, user_id))
        db.commit()

def record_win(user_id):
    with closing(db_connect()) as db: db.execute("UPDATE users SET wins = wins + 1 WHERE user_id = ?", (user_id,)); db.commit()
    add_xp(user_id, 25)

def record_loss(user_id):
    with closing(db_connect()) as db: db.execute("UPDATE users SET losses = losses + 1 WHERE user_id = ?", (user_id,)); db.commit()
    add_xp(user_id, 5)

# ============================================================
# GAMES CONFIG & ROOMS
# ============================================================

GAME_NAMES = {
    "دوز": "❌⭕️ دوز (تیک‌تک‌تو تعاملی)",
    "سنگ_کاغذ_قیچی": "✌️✊✋ سنگ، کاغذ، قیچی (تعاملی)",
    "کارت_31": "🃏 بازی 31 (تعاملی با کارت کشیدن)",
    "لگد_خر": "🐴💥 لگد خر (بتل رویال تعاملی)",
    "انفجار": "💥 بازی زنده انفجار (Crash)",
}

ACTIVE_GAMES = {}
PLAYER_GAMES = {}
USER_GAME_SELECTION = {} 
CRASH_SESSIONS = {} 

@dataclass
class GameRoom:
    game_type: str
    chat_id: int
    creator_id: int
    bet: int
    max_players: int = 2 
    players: list = field(default_factory=list)
    started: bool = False
    against_bot: bool = False
    created_at: float = field(default_factory=time.time)
    game_state: dict = field(default_factory=dict)
    message_id: int = 0

def get_room(chat_id): return ACTIVE_GAMES.get(str(chat_id))
def player_in_game(user_id): return user_id in PLAYER_GAMES
def remove_room(room):
    ACTIVE_GAMES.pop(str(room.chat_id), None)
    for p in room.players:
        if p != -1: PLAYER_GAMES.pop(p, None)

def get_p_name(p_id):
    if p_id == -1: return "🤖 بات هوشمند"
    u = get_user(p_id)
    return u["name"] if u else f"بازیکن {p_id}"

# موتور زنده انفجار
async def run_crash_task(bot, chat_id, message_id, user_id, session):
    crash_point = session["crash_point"]
    step = 1
    while session.get("active") and session["current"] < crash_point:
        await asyncio.sleep(1.5)
        if not session.get("active"): break
        session["current"] += random.uniform(0.05, 0.25) * step
        if session["current"] > crash_point: session["current"] = crash_point
            
        if session["current"] >= crash_point:
            session["active"] = False
            record_loss(user_id)
            msg = f"💥 **بـــوم! انفجار!**\n━━━━━━━━━━━━━━\nمتأسفانه ضریب در **{crash_point:.2f}x** بسته شد و شرطت سوخت! 📉\n💸 باخت: {session['bet']} 🪙"
            try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=message_id, reply_markup=main_menu())
            except: pass
            break
        else:
            current_prize = int(session["bet"] * session["current"])
            msg = f"💥 **بازی زنده انفجار**\n━━━━━━━━━━━━━━\n💰 شرط: {session['bet']} 🪙\n📈 ضریب فعلی: **{session['current']:.2f}x**\n⚠️ سریع برداشت کن!"
            btn = InlineKeyboardMarkup([[InlineKeyboardButton(f"🛑 برداشت ({current_prize:,} 🪙)", callback_data=f"crashout_{user_id}")]])
            try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=message_id, reply_markup=btn)
            except: pass
        step += 1

# ============================================================
# INTERACTIVE GAMES BUILDERS & TIMERS (30s LIMIT)
# ============================================================

def build_tictactoe_ui(room):
    board = room.game_state["board"]
    turn = room.game_state["turn"]
    strikes = room.game_state["strikes"]
    p1, p2 = room.players[0], room.players[1]
    
    msg = f"❌⭕️ **بازی دوز تعاملی (۳۰ ثانیه نوبت)**\n━━━━━━━━━━━━━━\n💰 شرط کل: {room.bet * len(room.players)} 🪙\n\n"
    msg += f"❌ {get_p_name(p1)} (اخطار: {strikes[p1]}/2)\n"
    msg += f"⭕️ {get_p_name(p2)} (اخطار: {strikes[p2]}/2)\n\n"
    msg += f"⏳ **نوبت حرکت:** {get_p_name(turn)}"
    
    keyboard = []
    for i in range(0, 9, 3):
        row = []
        for j in range(3):
            idx = i + j
            text = board[idx] if board[idx] != " " else "⬜️"
            if board[idx] == " ": row.append(InlineKeyboardButton(text, callback_data=f"t3_{idx}"))
            else: row.append(InlineKeyboardButton(text, callback_data="t3_ignore"))
        keyboard.append(row)
    return msg, InlineKeyboardMarkup(keyboard)

def check_tictactoe_winner(board):
    win_cond = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    for a,b,c in win_cond:
        if board[a] != " " and board[a] == board[b] == board[c]: return board[a]
    if " " not in board: return "DRAW"
    return None

async def tictactoe_timer_task(bot, chat_id, expected_turn_num, current_player):
    await asyncio.sleep(30)
    room = get_room(chat_id)
    if not room or room.game_type != "دوز" or not room.started: return
    
    if room.game_state["turn_num"] == expected_turn_num:
        room.game_state["strikes"][current_player] += 1
        other_player = room.players[1] if room.players[0] == current_player else room.players[0]
        
        if room.game_state["strikes"][current_player] >= 2:
            prize = int((room.bet * len(room.players)) * 0.95)
            if other_player != -1:
                add_coins(other_player, prize)
                record_win(other_player)
            record_loss(current_player)
            msg = f"❌⭕️ **پایان بازی دوز**\n💀 {get_p_name(current_player)} به دلیل عدم فعالیت حذف شد!\n🏆 **{get_p_name(other_player)} برنده شد!**\n🪙 جایزه: {prize} سکه"
            remove_room(room)
            try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=main_menu())
            except: pass
        else:
            room.game_state["turn"] = other_player
            room.game_state["turn_num"] += 1
            msg, kb = build_tictactoe_ui(room)
            msg += f"\n\n⚠️ {get_p_name(current_player)} یک نوبت را به دلیل تاخیر از دست داد!"
            try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=kb)
            except: pass
            
            if other_player == -1:
                await handle_tictactoe_bot(bot, room, chat_id)
            else:
                asyncio.create_task(tictactoe_timer_task(bot, chat_id, room.game_state["turn_num"], other_player))

async def handle_tictactoe_bot(bot, room, chat_id):
    await asyncio.sleep(1.5)
    if not room.started: return
    empty_cells = [i for i, val in enumerate(room.game_state["board"]) if val == " "]
    if empty_cells:
        bot_idx = random.choice(empty_cells)
        room.game_state["board"][bot_idx] = "⭕️"
        winner = check_tictactoe_winner(room.game_state["board"])
        if winner:
            record_loss(room.players[0])
            msg = f"🤖 **بات هوشمند در دوز برد!** سکه‌هات پر!"
            remove_room(room)
            try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=main_menu())
            except: pass
            return
        room.game_state["turn"] = room.players[0]
        room.game_state["turn_num"] += 1
        msg, kb = build_tictactoe_ui(room)
        try: 
            m = await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=kb)
            room.message_id = m.message_id
        except: pass
        asyncio.create_task(tictactoe_timer_task(bot, chat_id, room.game_state["turn_num"], room.players[0]))

def build_rps_ui(room):
    p1, p2 = room.players[0], room.players[1]
    choices = room.game_state["choices"]
    status_p1 = "✅ انتخاب کرد" if choices.get(p1) else "⏳ در حال انتخاب..."
    status_p2 = "✅ انتخاب کرد" if choices.get(p2) else "⏳ در حال انتخاب..."
    
    msg = f"✌️✊✋ **سنگ، کاغذ، قیچی تعاملی (۳۰ ثانیه)**\n━━━━━━━━━━━━━━\n💰 شرط: {room.bet * 2} 🪙\n\n"
    msg += f"▪️ {get_p_name(p1)}: {status_p1}\n▪️ {get_p_name(p2)}: {status_p2}\n\n👇 روی دکمه‌ی دلخواه کلیک کن:"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("سنگ 🗿", callback_data="rps_سنگ"),
        InlineKeyboardButton("کاغذ 📄", callback_data="rps_کاغذ"),
        InlineKeyboardButton("قیچی ✂️", callback_data="rps_قیچی")
    ]])
    return msg, kb

async def rps_timer_task(bot, chat_id, expected_round):
    await asyncio.sleep(30)
    room = get_room(chat_id)
    if not room or room.game_type != "سنگ_کاغذ_قیچی" or not room.started: return
    
    if room.game_state.get("round") == expected_round:
        choices = room.game_state["choices"]
        p1, p2 = room.players[0], room.players[1]
        
        if not choices.get(p1) and choices.get(p2): winner = p2
        elif choices.get(p1) and not choices.get(p2): winner = p1
        else: winner = "DRAW"
            
        prize = int((room.bet * 2) * 0.95)
        if winner == "DRAW":
            for p in room.players:
                if p != -1: add_coins(p, room.bet)
            msg = "🤝 **تایم‌اوت / مساوی!** سکه‌ها برگشت."
        else:
            loser = p2 if winner == p1 else p1
            if winner != -1: add_coins(winner, prize); record_win(winner)
            if loser != -1: record_loss(loser)
            msg = f"🏆 **{get_p_name(winner)} به دلیل عدم پاسخ‌دهی حریف برنده شد!**\n🪙 جایزه: {prize} سکه"
            
        remove_room(room)
        try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=main_menu())
        except: pass

def build_card31_ui(room):
    turn = room.game_state["turn"]
    scores = room.game_state["scores"]
    lives = room.game_state["lives"]
    
    msg = f"🃏 **بازی ۳۱ تعاملی (نوبتی و ۳۰ ثانیه)**\n━━━━━━━━━━━━━━\n💰 شرط: {room.bet * len(room.players)} 🪙\n\n"
    for p in room.players:
        msg += f"▪️ {get_p_name(p)} ➔ امتیاز: {scores.get(p, 0)} | جون: {'❤️' * lives.get(p, 3)}\n"
    msg += f"\n⏳ **نوبت کشیدن کارت:** {get_p_name(turn)}"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🃏 کشیدن کارت", callback_data="c31_draw"), InlineKeyboardButton("🛑 ایست", callback_data="c31_pass")]
    ])
    return msg, kb

async def card31_timer_task(bot, chat_id, expected_turn_num, current_player):
    await asyncio.sleep(30)
    room = get_room(chat_id)
    if not room or room.game_type != "کارت_31" or not room.started: return
    
    if room.game_state["turn_num"] == expected_turn_num:
        room.game_state["lives"][current_player] -= 1
        other_player = room.players[1] if room.players[0] == current_player else room.players[0]
        
        if room.game_state["lives"][current_player] <= 0:
            prize = int((room.bet * len(room.players)) * 0.95)
            if other_player != -1: add_coins(other_player, prize); record_win(other_player)
            record_loss(current_player)
            msg = f"🃏 **پایان بازی ۳۱**\n💀 {get_p_name(current_player)} به دلیل تاخیر ۳۰ ثانیه‌ای باخت!\n🏆 **{get_p_name(other_player)} برنده شد!**"
            remove_room(room)
            try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=main_menu())
            except: pass
        else:
            room.game_state["turn"] = other_player
            room.game_state["turn_num"] += 1
            msg, kb = build_card31_ui(room)
            msg += f"\n\n⚠️ {get_p_name(current_player)} به دلیل تاخیر ۱ جون از دست داد!"
            try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=kb)
            except: pass
            
            if other_player == -1:
                await handle_card31_bot(bot, room, chat_id)
            else:
                asyncio.create_task(card31_timer_task(bot, chat_id, room.game_state["turn_num"], other_player))

async def handle_card31_bot(bot, room, chat_id):
    await asyncio.sleep(2)
    if not room.started: return
    bot_card = random.randint(3, 9)
    room.game_state["scores"][-1] += bot_card
    
    if room.game_state["scores"][-1] >= 26 or random.random() < 0.4:
        user_id = room.players[0]
        user_score = room.game_state["scores"][user_id]
        bot_score = room.game_state["scores"][-1]
        
        prize = int((room.bet * 2) * 0.95)
        if user_score > bot_score:
            winner, loser = user_id, -1
            msg = f"🃏 **بات ایست داد!** امتیاز بات: {bot_score} | امتیاز شما: {user_score}\n🏆 **شما برنده شدید!**\n🪙 جایزه: {prize} سکه"
        else:
            winner, loser = -1, user_id
            msg = f"🃏 **بات ایست داد!** امتیاز بات: {bot_score} | امتیاز شما: {user_score}\n🤖 **بات برنده شد!**"
            
        if winner != -1: add_coins(winner, prize); record_win(winner)
        if loser != -1: record_loss(loser)
        remove_room(room)
        try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=main_menu())
        except: pass
    else:
        room.game_state["turn"] = room.players[0]
        room.game_state["turn_num"] += 1
        msg, kb = build_card31_ui(room)
        try:
            m = await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=kb)
            room.message_id = m.message_id
        except: pass
        asyncio.create_task(card31_timer_task(bot, chat_id, room.game_state["turn_num"], room.players[0]))

def build_donkey_ui(room):
    turn = room.game_state["turn"]
    strikes = room.game_state["strikes"]
    
    msg = f"🐴💥 **لگد خر تعاملی (بقا - ۳۰ ثانیه)**\n━━━━━━━━━━━━━━\n💰 شرط کل: {room.bet * len(room.players)} 🪙\n\n"
    for p in room.players:
        msg += f"▪️ {get_p_name(p)} ➔ اخطار لگد: {strikes.get(p, 0)}/3\n"
    msg += f"\n⏳ **نوبت تست شانس:** {get_p_name(turn)}"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🐴 جفت پا جلو رفتن (تست شانس)", callback_data="dk_kick")]
    ])
    return msg, kb

async def donkey_timer_task(bot, chat_id, expected_turn_num, current_player):
    await asyncio.sleep(30)
    room = get_room(chat_id)
    if not room or room.game_type != "لگد_خر" or not room.started: return
    
    if room.game_state["turn_num"] == expected_turn_num:
        room.game_state["strikes"][current_player] += 1
        other_player = room.players[1] if room.players[0] == current_player else room.players[0]
        
        if room.game_state["strikes"][current_player] >= 2:
            prize = int((room.bet * len(room.players)) * 0.95)
            if other_player != -1: add_coins(other_player, prize); record_win(other_player)
            record_loss(current_player)
            msg = f"🐴💥 **پایان لگد خر**\n💀 {get_p_name(current_player)} به دلیل تاخیر حذف شد!\n🏆 **{get_p_name(other_player)} برنده شد!**"
            remove_room(room)
            try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=main_menu())
            except: pass
        else:
            room.game_state["turn"] = other_player
            room.game_state["turn_num"] += 1
            msg, kb = build_donkey_ui(room)
            msg += f"\n\n⚠️ {get_p_name(current_player)} به دلیل تاخیر نوبتش سوخت!"
            try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=kb)
            except: pass
            
            if other_player == -1:
                await handle_donkey_bot(bot, room, chat_id)
            else:
                asyncio.create_task(donkey_timer_task(bot, chat_id, room.game_state["turn_num"], other_player))

async def handle_donkey_bot(bot, room, chat_id):
    await asyncio.sleep(2)
    if not room.started: return
    hit = random.random() < 0.45
    user_id = room.players[0]
    if hit:
        prize = int((room.bet * 2) * 0.95)
        add_coins(user_id, prize); record_win(user_id)
        record_loss(-1)
        msg = f"🐴 **خر جفتک انداخت تو صورت بات!** 💥\n🤖 بات لگد خورد و باخت!\n🏆 **شما برنده شدید!**\n🪙 جایزه: {prize} سکه"
        remove_room(room)
        try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=main_menu())
        except: pass
    else:
        room.game_state["turn"] = user_id
        room.game_state["turn_num"] += 1
        msg, kb = build_donkey_ui(room)
        msg += f"\n\n🐴 خر به بات لگد نزد! نوبت شماست:"
        try:
            m = await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=kb)
            room.message_id = m.message_id
        except: pass
        asyncio.create_task(donkey_timer_task(bot, chat_id, room.game_state["turn_num"], user_id))

# ============================================================
# SOUND & SCORING SYSTEM (GROUP TEXT & MANUAL)
# ============================================================

DONKEY_SOUNDS_DB = [
    {"words": ["عر", "عرعر", "ar"], "text": "عررررررررر اصیل 🫏🔊", "min": 10, "max": 25},
    {"words": ["توورت", "توورت!", "toort"], "text": "تووووووورت! (صدای باد معده) 💨😷", "min": 20, "max": 45},
    {"words": ["ترک", "ترررک", "تارک", "tarak"], "text": "ترررررررک! (انفجار صوتی) 💥🤯", "min": 30, "max": 70},
]

async def check_chat_sound_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip().lower()
    ensure_user(user.id, user.first_name)
    
    u_data = get_user(user.id)
    if u_data and u_data["is_banned"] == 1: return False

    for sound in DONKEY_SOUNDS_DB:
        if any(w in text.split() or text == w for w in sound["words"]):
            donkey = get_donkey(user.id)
            multiplier = donkey["sounds"] * 1.2 if donkey else 1.0
            score = int(random.randint(sound["min"], sound["max"]) * multiplier)
            add_coins(user.id, score)
            add_xp(user.id, 2)
            
            await update.message.reply_text(
                f"🫏 **خرِ {user.first_name} تو گروه صدا داد!**\n"
                f"🔊 {sound['text']}\n"
                f"🎁 جایزه: **+{score} 🪙**"
            )
            return True
    return False

async def donkey_sound_system_menu(user_id):
    donkey = get_donkey(user_id)
    if not donkey: return "❌ اول باید خرت رو ثبت کنی."
    cost = 20
    if not remove_coins(user_id, cost): return f"❌ برای ایجاد صدا {cost} سکه لازم داری!"
    
    score = random.randint(10, 40)
    add_coins(user_id, score)
    add_xp(user_id, 3)
    return f"🎙️ **خر تو منو صدا درآورد!**\n━━━━━━━━━━━━━━\n🎁 **جایزه: {score} 🪙**\n💸 هزینه: {cost} 🪙"

# ============================================================
# UI KEYBOARDS & TEXTS
# ============================================================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🫏 خر من", callback_data="donkey"), InlineKeyboardButton("🎮 شروع بازی", callback_data="games")],
        [InlineKeyboardButton("🏪 فروشگاه", callback_data="shop"), InlineKeyboardButton("🎒 کیف", callback_data="inventory")],
        [InlineKeyboardButton("👤 پروفایل", callback_data="profile"), InlineKeyboardButton("🔊 ایجاد صدا", callback_data="sound_action")],
    ])

def game_mode_keyboard(game_type):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 بازی با بات هوشمند (PvE)", callback_data="mode_bot")],
        [InlineKeyboardButton("👥 ایجاد اتاق گروهی (PvP)", callback_data="mode_pvp")],
        [InlineKeyboardButton("🔙 لغو", callback_data="home")]
    ])

def room_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 ورود به بازی", callback_data="game_join")],
        [InlineKeyboardButton("▶️ شروع بازی", callback_data="game_start"), InlineKeyboardButton("❌ لغو", callback_data="game_cancel")]
    ])

def profile_text(user_id):
    u = get_user(user_id)
    if not u: return "❌ شناسنامه پیدا نشد."
    return (f"👤 **شناسنامه طویله‌ای {u['name']}**\n━━━━━━━━━━━━━━\n⭐ سطح: {u['level']}\n✨ تجربه (XP): {u['xp']}\n"
            f"🪙 جیب شما: **{u['coins']}** سکه\n🏆 برد: {u['wins']} | 💀 باخت: {u['losses']}")

def donkey_text(user_id):
    d = get_donkey(user_id)
    u = get_user(user_id)
    if not d: return "❌ خر یافت نشد."
    return (f"🫏 **خرِ {u['name']}**\n━━━━━━━━━━━━━━\n🍖 گرسنگی: {d['hunger']}/100\n💧 تشنگی: {d['thirst']}/100\n"
            f"⚡ انرژی: {d['energy']}/100\n❤️ شادی: {d['happiness']}/100\n\n💪 قدرت: {d['strength']} | 🏃 سرعت: {d['speed']}")

# ============================================================
# CALLBACK HANDLERS
# ============================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    ensure_user(user.id, user.first_name)
    
    u_data = get_user(user.id)
    if u_data and u_data["is_banned"] == 1:
        return await query.edit_message_text("🚫 **عرعــــر!** شما بن شده‌اید!")
        
    data = query.data

    if data == "home":
        USER_GAME_SELECTION.pop(user.id, None)
        return await query.edit_message_text("🏠 منوی اصلی طویله:", reply_markup=main_menu())
        
    if data == "profile": return await query.edit_message_text(profile_text(user.id), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="home")]]))
    if data == "donkey": return await query.edit_message_text(donkey_text(user.id), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="home")]]))
    if data == "sound_action": return await query.edit_message_text(await donkey_sound_system_menu(user.id), reply_markup=main_menu(), parse_mode="Markdown")

    if data.startswith("crashout_"):
        target_user = int(data.split("_")[1])
        if user.id != target_user: return await query.answer("⛔ دکمه ماله یکی دیگه‌ست.", show_alert=True)
        session = CRASH_SESSIONS.get(user.id)
        if not session or not session.get("active"): return await query.answer("❌ تمام شده!", show_alert=True)
        
        session["active"] = False 
        prize = int(session["bet"] * session["current"])
        add_coins(user.id, prize)
        record_win(user.id)
        return await query.edit_message_text(f"✅ **پرواز موفق! ضریب {session['current']:.2f}x**\n🪙 جایزه: **{prize}** سکه", reply_markup=main_menu())

    # دوز
    if data.startswith("t3_"):
        if data == "t3_ignore": return
        room = get_room(update.effective_chat.id)
        if not room or room.game_type != "دوز" or not room.started: return await query.answer("بازی در جریان نیست.", show_alert=True)
        if user.id != room.game_state["turn"]: return await query.answer("نوبت شما نیست!", show_alert=True)
            
        idx = int(data.split("_")[1])
        symbol = "❌" if user.id == room.players[0] else "⭕️"
        room.game_state["board"][idx] = symbol
        
        winner = check_tictactoe_winner(room.game_state["board"])
        if winner:
            prize = int((room.bet * len(room.players)) * 0.95)
            if winner == "DRAW":
                for p in room.players:
                    if p != -1: add_coins(p, room.bet)
                msg = "🤝 **بازی دوز مساوی شد! سکه‌ها برگشت.**"
            else:
                win_player = room.players[0] if winner == "❌" else room.players[1]
                lose_player = room.players[1] if winner == "❌" else room.players[0]
                if win_player != -1: add_coins(win_player, prize); record_win(win_player)
                if lose_player != -1: record_loss(lose_player)
                msg = f"🏆 **{get_p_name(win_player)} برنده شد!**\n🪙 جایزه: {prize} سکه"
            
            b = room.game_state["board"]
            msg += f"\n\n`{b[0]}|{b[1]}|{b[2]}\n{b[3]}|{b[4]}|{b[5]}\n{b[6]}|{b[7]}|{b[8]}`"
            remove_room(room)
            return await query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")
        else:
            next_turn = room.players[1] if user.id == room.players[0] else room.players[0]
            room.game_state["turn"] = next_turn
            room.game_state["turn_num"] += 1
            
            msg, kb = build_tictactoe_ui(room)
            await query.edit_message_text(msg, reply_markup=kb)
            
            if next_turn == -1:
                await handle_tictactoe_bot(context.bot, room, room.chat_id)
            else:
                asyncio.create_task(tictactoe_timer_task(context.bot, room.chat_id, room.game_state["turn_num"], next_turn))
            return

    # سنگ، کاغذ، قیچی
    if data.startswith("rps_"):
        room = get_room(update.effective_chat.id)
        if not room or room.game_type != "سنگ_کاغذ_قیچی" or not room.started: return await query.answer("بازی در جریان نیست.", show_alert=True)
        if user.id not in room.players: return await query.answer("شما بازیکن نیستید!", show_alert=True)
        
        room.game_state["choices"][user.id] = data.split("_")[1]
        p1, p2 = room.players[0], room.players[1]
        choices = room.game_state["choices"]
        
        if room.against_bot and -1 in room.players:
            choices[-1] = random.choice(["سنگ", "کاغذ", "قیچی"])
            
        if choices.get(p1) and choices.get(p2):
            m1, m2 = choices[p1], choices[p2]
            if m1 == m2: winner = "DRAW"
            else:
                win_map = {"سنگ": "قیچی", "کاغذ": "سنگ", "قیچی": "کاغذ"}
                winner = p1 if win_map[m1] == m2 else p2
                
            prize = int((room.bet * 2) * 0.95)
            if winner == "DRAW":
                for p in room.players:
                    if p != -1: add_coins(p, room.bet)
                msg = f"🤝 **مساوی!** سکه‌ها برگشت."
            else:
                loser = p2 if winner == p1 else p1
                if winner != -1: add_coins(winner, prize); record_win(winner)
                if loser != -1: record_loss(loser)
                msg = f"🏆 **{get_p_name(winner)} برنده شد!**\n🪙 جایزه: {prize} سکه"
                
            remove_room(room)
            return await query.edit_message_text(msg, reply_markup=main_menu())
        else:
            msg, kb = build_rps_ui(room)
            return await query.edit_message_text(msg, reply_markup=kb)

    # کارت ۳۱
    if data in ["c31_draw", "c31_pass"]:
        room = get_room(update.effective_chat.id)
        if not room or room.game_type != "کارت_31" or not room.started: return await query.answer("بازی در جریان نیست.", show_alert=True)
        if user.id != room.game_state["turn"]: return await query.answer("نوبت شما نیست!", show_alert=True)
        
        if data == "c31_draw":
            card_val = random.randint(2, 10)
            room.game_state["scores"][user.id] += card_val
            if room.game_state["scores"][user.id] > 31:
                room.game_state["lives"][user.id] -= 1
                room.game_state["scores"][user.id] = 0
                await query.answer("💥 سوختی! امتیازت بالای ۳۱ شد و یک جون کم شد!", show_alert=True)
                if room.game_state["lives"][user.id] <= 0:
                    msg = f"💀 **{get_p_name(user.id)} باخت و جون‌هاش تموم شد!**"
                    other = room.players[1] if room.players[0] == user.id else room.players[0]
                    prize = int((room.bet * 2) * 0.95)
                    if other != -1: add_coins(other, prize); record_win(other)
                    remove_room(room)
                    return await query.edit_message_text(msg, reply_markup=main_menu())
            else:
                await query.answer(f"🃏 کارت {card_val} کشیدی. کل: {room.game_state['scores'][user.id]}", show_alert=True)
                
        elif data == "c31_pass" or room.game_state["scores"][user.id] >= 28:
            other = room.players[1] if room.players[0] == user.id else room.players[0]
            s1 = room.game_state["scores"][room.players[0]]
            s2 = room.game_state["scores"][room.players[1]]
            
            prize = int((room.bet * 2) * 0.95)
            if s1 > s2: winner, loser = room.players[0], room.players[1]
            elif s2 > s1: winner, loser = room.players[1], room.players[0]
            else: winner = "DRAW"
            
            if winner == "DRAW":
                for p in room.players:
                    if p != -1: add_coins(p, room.bet)
                msg = f"🤝 **مساوی شدید!** امتیاز هر دو: {s1}"
            else:
                if winner != -1: add_coins(winner, prize); record_win(winner)
                if loser != -1: record_loss(loser)
                msg = f"🏆 **{get_p_name(winner)} در بازی ۳۱ پیروز شد!**\n{get_p_name(room.players[0])}: {s1} | {get_p_name(room.players[1])}: {s2}\n🪙 جایزه: {prize} سکه"
            remove_room(room)
            return await query.edit_message_text(msg, reply_markup=main_menu())

        next_turn = room.players[1] if user.id == room.players[0] else room.players[0]
        room.game_state["turn"] = next_turn
        room.game_state["turn_num"] += 1
        
        msg, kb = build_card31_ui(room)
        await query.edit_message_text(msg, reply_markup=kb)
        
        if next_turn == -1:
            await handle_card31_bot(context.bot, room, room.chat_id)
        else:
            asyncio.create_task(card31_timer_task(context.bot, room.chat_id, room.game_state["turn_num"], next_turn))
        return

    # لگد خر
    if data == "dk_kick":
        room = get_room(update.effective_chat.id)
        if not room or room.game_type != "لگد_خر" or not room.started: return await query.answer("بازی در جریان نیست.", show_alert=True)
        if user.id != room.game_state["turn"]: return await query.answer("نوبت شما نیست!", show_alert=True)
        
        hit = random.random() < 0.40
        if hit:
            prize = int((room.bet * len(room.players)) * 0.95)
            other = room.players[1] if room.players[0] == user.id else room.players[0]
            if other != -1: add_coins(other, prize); record_win(other)
            record_loss(user.id)
            msg = f"🐴💥 **تقققق! خر جفتک انداخت تو صورت {get_p_name(user.id)}!**\n\n🏆 **{get_p_name(other)} برنده شد!**\n🪙 جایزه: {prize} سکه"
            remove_room(room)
            return await query.edit_message_text(msg, reply_markup=main_menu())
        else:
            await query.answer("😅 جان سالم به در بردی! خر لگد نزد.", show_alert=True)
            next_turn = room.players[1] if user.id == room.players[0] else room.players[0]
            room.game_state["turn"] = next_turn
            room.game_state["turn_num"] += 1
            
            msg, kb = build_donkey_ui(room)
            await query.edit_message_text(msg, reply_markup=kb)
            
            if next_turn == -1:
                await handle_donkey_bot(context.bot, room, room.chat_id)
            else:
                asyncio.create_task(donkey_timer_task(context.bot, room.chat_id, room.game_state["turn_num"], next_turn))
            return

    if data == "games":
        rows = [[InlineKeyboardButton(GAME_NAMES[g], callback_data=f"game_{g}")] for g in GAME_NAMES.keys()]
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="home")])
        return await query.edit_message_text("🎮 قمارخونه طویله (بازی‌های تعاملی نوبتی):", reply_markup=InlineKeyboardMarkup(rows))

    if data.startswith("game_") and data not in ["game_join", "game_start", "game_cancel"]:
        g_type = data[5:]
        USER_GAME_SELECTION[user.id] = {"game": g_type, "step": "waiting_for_bet"}
        return await query.edit_message_text(f"بازی: {GAME_NAMES[g_type]}\n💰 مبلغ شرط را بفرست (حداقل {MIN_BET}):")

    if data == "mode_bot":
        state = USER_GAME_SELECTION.get(user.id)
        if not state: return
        if not remove_coins(user.id, state["bet"]): return await query.edit_message_text("❌ پول نداری!", reply_markup=main_menu())

        room = GameRoom(game_type=state["game"], chat_id=update.effective_chat.id, creator_id=user.id, bet=state["bet"], against_bot=True, players=[user.id, -1], started=True)
        ACTIVE_GAMES[str(update.effective_chat.id)] = room
        
        if state["game"] == "دوز":
            room.game_state = {"board": [" "]*9, "turn": user.id, "strikes": {user.id: 0, -1: 0}, "turn_num": 0}
            msg, kb = build_tictactoe_ui(room)
            m = await query.edit_message_text(msg, reply_markup=kb)
            room.message_id = m.message_id
            asyncio.create_task(tictactoe_timer_task(context.bot, room.chat_id, 0, user.id))
            return
        elif state["game"] == "سنگ_کاغذ_قیچی":
            room.game_state = {"choices": {}, "round": 1}
            msg, kb = build_rps_ui(room)
            m = await query.edit_message_text(msg, reply_markup=kb)
            room.message_id = m.message_id
            asyncio.create_task(rps_timer_task(context.bot, room.chat_id, 1))
            return
        elif state["game"] == "کارت_31":
            room.game_state = {"scores": {user.id: 0, -1: 0}, "lives": {user.id: 3, -1: 3}, "turn": user.id, "turn_num": 0}
            msg, kb = build_card31_ui(room)
            m = await query.edit_message_text(msg, reply_markup=kb)
            room.message_id = m.message_id
            asyncio.create_task(card31_timer_task(context.bot, room.chat_id, 0, user.id))
            return
        elif state["game"] == "لگد_خر":
            room.game_state = {"strikes": {user.id: 0, -1: 0}, "turn": user.id, "turn_num": 0}
            msg, kb = build_donkey_ui(room)
            m = await query.edit_message_text(msg, reply_markup=kb)
            room.message_id = m.message_id
            asyncio.create_task(donkey_timer_task(context.bot, room.chat_id, 0, user.id))
            return

    if data == "mode_pvp":
        state = USER_GAME_SELECTION.get(user.id)
        if not state: return
        if get_room(update.effective_chat.id): return await query.edit_message_text("❌ بازی دیگری جریان دارد.", reply_markup=main_menu())
        if not remove_coins(user.id, state["bet"]): return await query.edit_message_text("❌ پول نداری!", reply_markup=main_menu())

        room = GameRoom(game_type=state["game"], chat_id=update.effective_chat.id, creator_id=user.id, bet=state["bet"], max_players=2, players=[user.id])
        ACTIVE_GAMES[str(update.effective_chat.id)] = room
        PLAYER_GAMES[user.id] = str(update.effective_chat.id)
        txt = f"🎮 اتاق: {GAME_NAMES[state['game']]}\n💰 شرط: {state['bet']}\n\n1. {user.first_name}"
        return await query.edit_message_text(txt, reply_markup=room_keyboard())

    if data == "game_join":
        room = get_room(update.effective_chat.id)
        if not room or room.started: return await query.answer("❌ غیرقابل دسترس.", show_alert=True)
        if user.id in room.players: return await query.answer("قبلا وارد شدی.", show_alert=True)
        if not remove_coins(user.id, room.bet): return await query.answer("پول کم داری!", show_alert=True)
        
        room.players.append(user.id)
        names = "\n".join([f"{i+1}. {get_user(p)['name']}" for i, p in enumerate(room.players)])
        txt = f"🎮 اتاق: {GAME_NAMES[room.game_type]}\n💰 شرط: {room.bet}\n\n{names}"
        return await query.edit_message_text(txt, reply_markup=room_keyboard())

    if data == "game_start":
        room = get_room(update.effective_chat.id)
        if not room or room.creator_id != user.id: return await query.answer("فقط سازنده!", show_alert=True)
        if len(room.players) < 2: return await query.answer("حداقل ۲ نفر!", show_alert=True)
        
        room.started = True
        if room.game_type == "دوز":
            room.game_state = {"board": [" "]*9, "turn": room.players[0], "strikes": {p: 0 for p in room.players}, "turn_num": 0}
            msg, kb = build_tictactoe_ui(room)
            m = await query.edit_message_text(msg, reply_markup=kb)
            room.message_id = m.message_id
            asyncio.create_task(tictactoe_timer_task(context.bot, room.chat_id, 0, room.players[0]))
            return
        elif room.game_type == "سنگ_کاغذ_قیچی":
            room.game_state = {"choices": {}, "round": 1}
            msg, kb = build_rps_ui(room)
            m = await query.edit_message_text(msg, reply_markup=kb)
            room.message_id = m.message_id
            asyncio.create_task(rps_timer_task(context.bot, room.chat_id, 1))
            return
        elif room.game_type == "کارت_31":
            room.game_state = {"scores": {p: 0 for p in room.players}, "lives": {p: 3 for p in room.players}, "turn": room.players[0], "turn_num": 0}
            msg, kb = build_card31_ui(room)
            m = await query.edit_message_text(msg, reply_markup=kb)
            room.message_id = m.message_id
            asyncio.create_task(card31_timer_task(context.bot, room.chat_id, 0, room.players[0]))
            return
        elif room.game_type == "لگد_خر":
            room.game_state = {"strikes": {p: 0 for p in room.players}, "turn": room.players[0], "turn_num": 0}
            msg, kb = build_donkey_ui(room)
            m = await query.edit_message_text(msg, reply_markup=kb)
            room.message_id = m.message_id
            asyncio.create_task(donkey_timer_task(context.bot, room.chat_id, 0, room.players[0]))
            return

    if data == "game_cancel":
        room = get_room(update.effective_chat.id)
        if not room or room.creator_id != user.id: return await query.answer("فقط سازنده!", show_alert=True)
        for p in room.players: add_coins(p, room.bet)
        remove_room(room)
        return await query.edit_message_text("❌ لغو شد و سکه‌ها برگشت.", reply_markup=main_menu())

# ============================================================
# TEXT HANDLERS (GROUP CHAT SOUND DETECTION + ADMIN)
# ============================================================
async def general_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()
    ensure_user(user.id, user.first_name)

    u_data = get_user(user.id)
    if u_data and u_data["is_banned"] == 1: return

    # ۱. بررسی کلمات صدا در گروه یا پی‌وی (عر، توورت، ترک)
    triggered = await check_chat_sound_trigger(update, context)
    if triggered: return # اگر کلمه صدا بود، دیگه بقیه دستورات چک نشن

    # ۲. پنل ادمین با ریپلی
    if user.id == OWNER_ID and text.startswith(("/", "بن", "انبن", "سکه", "کسر", "+سکه", "-سکه")):
        if update.message.reply_to_message:
            target_id = update.message.reply_to_message.from_user.id
            parts = text.split()
            cmd = parts[0].lower()
            if cmd in ["/ban", "بن"]:
                with closing(db_connect()) as db: db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (target_id,)); db.commit()
                await update.message.reply_text("✅ کاربر بن شد.")
                return
            elif cmd in ["/addcoin", "سکه", "+سکه"] and len(parts) > 1:
                try:
                    amt = int(parts[1])
                    add_coins(target_id, amt)
                    await update.message.reply_text(f"💰 {amt} سکه واریز شد (ارباب سخاوتمند).")
                except: pass
                return

    if text == "/start":
        USER_GAME_SELECTION.pop(user.id, None)
        return await update.message.reply_text("🫏 **خوش اومدی!** تو گروه‌ها کلماتی مثل `عر`، `توورت` یا `ترک` رو بفرست تا خرت صدا در بیاره و جایزه بگیری!\n\n👇 از منو انتخاب کن:", reply_markup=main_menu())

    state = USER_GAME_SELECTION.get(user.id)
    if state and state.get("step") == "waiting_for_bet":
        if text.isdigit():
            bet = int(text)
            if bet < MIN_BET: return await update.message.reply_text(f"حداقل شرط {MIN_BET} سکه!")
            if u_data['coins'] < bet: return await update.message.reply_text("❌ پول نداری! جیبت خالیه.")
            
            if state["game"] == "انفجار":
                remove_coins(user.id, bet)
                r = random.random()
                c_point = max(1.00, 0.95 / r)
                if c_point > 20.0: c_point = 20.0
                
                CRASH_SESSIONS[user.id] = {"active": True, "bet": bet, "current": 1.00, "crash_point": c_point}
                msg = f"💥 **بازی زنده انفجار**\n💰 شرط: {bet} 🪙\n\n📈 ضریب: **1.00x**"
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 برداشت", callback_data=f"crashout_{user.id}")]])
                sent_msg = await update.message.reply_text(msg, reply_markup=btn)
                asyncio.create_task(run_crash_task(context.bot, update.effective_chat.id, sent_msg.message_id, user.id, CRASH_SESSIONS[user.id]))
                USER_GAME_SELECTION.pop(user.id, None)
                return

            USER_GAME_SELECTION[user.id]["bet"] = bet
            USER_GAME_SELECTION[user.id]["step"] = "ready_for_mode"
            return await update.message.reply_text(f"بازی: {GAME_NAMES[state['game']]}\nشرط: {bet} 🪙\n\nحالت رو انتخاب کن:", reply_markup=game_mode_keyboard(state["game"]))

# ============================================================
# MAIN
# ============================================================
def main():
    if not BOT_TOKEN: return
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, general_text_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
