# ============================================================
# KHARBOT PRO - FULLY INTERACTIVE TURN-BASED (30s TIMEOUT)
# ============================================================

import os
import time
import random
import sqlite3
import logging
import asyncio
import itertools
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
MIN_BET = 10
START_COINS = 2500

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
            user_id INTEGER PRIMARY KEY, name TEXT NOT NULL, coins INTEGER NOT NULL DEFAULT 2500,
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
        db.execute("""CREATE TABLE IF NOT EXISTS achievements (
            user_id INTEGER NOT NULL, achievement TEXT NOT NULL, unlocked_at INTEGER NOT NULL,
            PRIMARY KEY(user_id, achievement))""")
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
# SHOP & INVENTORY
# ============================================================

SHOP_ITEMS = {
    "golden_carrot": {"name": "🥕 هویج طلایی", "price": 300, "type": "consumable", "desc": "انرژی و گرسنگی کامل."},
    "vip_soap": {"name": "🫧 شامپو VIP", "price": 250, "type": "consumable", "desc": "شادی خر به ۱۰۰ می‌رسد."},
    "sunglasses": {"name": "🕶 عینک لاتی", "price": 3500, "type": "upgrade", "stat": "luck", "desc": "دائمی: شانس +1"},
    "megaphone": {"name": "📣 بلندگو", "price": 3500, "type": "upgrade", "stat": "sounds", "desc": "دائمی: صدای عر +1"},
}

def get_item_amount(user_id, item):
    with closing(db_connect()) as db:
        row = db.execute("SELECT amount FROM inventory WHERE user_id = ? AND item = ?", (user_id, item)).fetchone()
        return row["amount"] if row else 0

def update_inventory(user_id, item, amount_change):
    current = get_item_amount(user_id, item)
    new_amount = current + amount_change
    if new_amount < 0: return False
    with closing(db_connect()) as db:
        db.execute("INSERT INTO inventory (user_id, item, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item) DO UPDATE SET amount = ?", (user_id, item, new_amount, new_amount))
        db.commit()
    return True

# ============================================================
# GAMES, CRASH & LOGIC
# ============================================================

GAME_NAMES = {
    "سنگ_کاغذ_قیچی": "✌️✊✋ سنگ، کاغذ، قیچی (تعاملی)",
    "انفجار": "💥 بازی زنده انفجار (Crash)",
    "دوز": "❌⭕️ دوز (تعاملی و نوبتی)",
    "پوکر": "🎰 پوکر اورجینال",
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
    if p_id == -1: return "🤖 بات"
    u = get_user(p_id)
    return u["name"] if u else f"بازیکن {p_id}"

# ------------------------------------------------------------
# موتور بازی زنده انفجار
# ------------------------------------------------------------
async def run_crash_task(bot, chat_id, message_id, user_id, session):
    crash_point = session["crash_point"]
    step = 1
    while session.get("active") and session["current"] < crash_point:
        await asyncio.sleep(1.5)
        if not session.get("active"): break
        session["current"] += random.uniform(0.1, 0.4) * step
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

# ------------------------------------------------------------
# ۱. موتور تعاملی دوز با تایمر ۳۰ ثانیه‌ای
# ------------------------------------------------------------
def build_tictactoe_ui(room):
    board = room.game_state["board"]
    turn = room.game_state["turn"]
    strikes = room.game_state["strikes"]
    p1, p2 = room.players[0], room.players[1]
    
    msg = f"❌⭕️ **بازی دوز تعاملی**\n━━━━━━━━━━━━━━\n💰 شرط کل: {room.bet * 2} 🪙\n\n"
    msg += f"❌ {get_p_name(p1)} (اخطار: {strikes[p1]}/2)\n"
    msg += f"⭕️ {get_p_name(p2)} (اخطار: {strikes[p2]}/2)\n\n"
    msg += f"⏳ **نوبت:** {get_p_name(turn)} (۳۰ ثانیه فرصت دارید!)"
    
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
            prize = int((room.bet * 2) * 0.95)
            add_coins(other_player, prize)
            record_win(other_player)
            record_loss(current_player)
            msg = f"❌⭕️ **پایان بازی دوز**\n💀 {get_p_name(current_player)} به دلیل عدم فعالیت حذف شد!\n🏆 **{get_p_name(other_player)} برنده شد!**\n🪙 جایزه: {prize}"
            remove_room(room)
            try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=main_menu())
            except: pass
        else:
            room.game_state["turn"] = other_player
            room.game_state["turn_num"] += 1
            msg, kb = build_tictactoe_ui(room)
            msg += f"\n\n⚠️ {get_p_name(current_player)} یک نوبت را از دست داد!"
            try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=kb)
            except: pass
            asyncio.create_task(tictactoe_timer_task(bot, chat_id, room.game_state["turn_num"], other_player))

# ------------------------------------------------------------
# ۲. موتور تعاملی سنگ، کاغذ، قیچی با تایمر ۳۰ ثانیه‌ای
# ------------------------------------------------------------
def build_rps_ui(room):
    p1, p2 = room.players[0], room.players[1]
    choices = room.game_state["choices"]
    
    status_p1 = "✅ انتخاب کرد" if choices.get(p1) else "⏳ در حال فکر کردن..."
    status_p2 = "✅ انتخاب کرد" if choices.get(p2) else "⏳ در حال فکر کردن..."
    
    msg = f"✌️✊✋ **سنگ، کاغذ، قیچی تعاملی**\n━━━━━━━━━━━━━━\n"
    msg += f"💰 شرط: {room.bet * 2} 🪙\n\n"
    msg += f"▪️ {get_p_name(p1)}: {status_p1}\n"
    msg += f"▪️ {get_p_name(p2)}: {status_p2}\n\n"
    msg += f"⏳ هر دو بازیکن ۳۰ ثانیه فرصت دارند حرکت خود را انتخاب کنند:"
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("سنگ 🗿", callback_data="rps_سنگ"),
            InlineKeyboardButton("کاغذ 📄", callback_data="rps_کاغذ"),
            InlineKeyboardButton("قیچی ✂️", callback_data="rps_قیچی")
        ]
    ])
    return msg, kb

async def rps_timer_task(bot, chat_id, expected_round):
    await asyncio.sleep(30)
    room = get_room(chat_id)
    if not room or room.game_type != "سنگ_کاغذ_قیچی" or not room.started: return
    
    if room.game_state.get("round") == expected_round:
        choices = room.game_state["choices"]
        p1, p2 = room.players[0], room.players[1]
        
        # هرکس انتخاب نکرده بازنده محسوب میشه
        if not choices.get(p1) and choices.get(p2):
            winner = p2
        elif choices.get(p1) and not choices.get(p2):
            winner = p1
        else:
            winner = "DRAW"
            
        if winner == "DRAW":
            for p in room.players: add_coins(p, room.bet)
            msg = "🤝 **هر دو بازیکن تعلل کردند یا مساوی شدند! سکه‌ها برگشت.**"
        else:
            loser = p2 if winner == p1 else p1
            prize = int((room.bet * 2) * 0.95)
            add_coins(winner, prize)
            record_win(winner)
            record_loss(loser)
            msg = f"🏆 **{get_p_name(winner)} به دلیل عدم پاسخ‌دهی حریف برنده شد!**\n🪙 جایزه: {prize}"
            
        remove_room(room)
        try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=room.message_id, reply_markup=main_menu())
        except: pass

# ============================================================
# SOUND & SCORING SYSTEM
# ============================================================

async def donkey_sound_system(user_id):
    donkey = get_donkey(user_id)
    if not donkey: return "❌ اول باید خرت رو ثبت کنی."
    cost = 50
    if not remove_coins(user_id, cost): return f"❌ برای ایجاد صدا {cost} سکه لازم داری!"
    
    multiplier = donkey["sounds"] * 1.5
    score = int(random.randint(10, 100) * multiplier)
    add_coins(user_id, score)
    add_xp(user_id, 5)
    return f"🎙️ **خر تو صدا درآورد!**\n━━━━━━━━━━━━━━\n🎁 **جایزه دریافتی: {score:,} 🪙**\n💸 هزینه: {cost} 🪙"

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
    if game_type in ["دوز", "سنگ_کاغذ_قیچی"]:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 ایجاد اتاق دو نفره تعاملی", callback_data="mode_pvp")],
            [InlineKeyboardButton("🔙 لغو", callback_data="home")]
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 بازی با بات قوی", callback_data="mode_bot")],
        [InlineKeyboardButton("👥 ایجاد اتاق (گروهی)", callback_data="mode_pvp")],
        [InlineKeyboardButton("🔙 لغو", callback_data="home")]
    ])

def room_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 ورود به بازی", callback_data="game_join")],
        [InlineKeyboardButton("▶️ شروع بازی", callback_data="game_start"), InlineKeyboardButton("❌ لغو", callback_data="game_cancel")]
    ])

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
        
    if data == "profile": return await query.edit_message_text(f"موجودی شما: {u_data['coins']} 🪙", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="home")]]))
    if data == "donkey": return await query.edit_message_text("وضعیت خر شما عالیست!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="home")]]))
    if data == "sound_action": return await query.edit_message_text(await donkey_sound_system(user.id), reply_markup=main_menu(), parse_mode="Markdown")

    # -- CRASH CASHOUT --
    if data.startswith("crashout_"):
        target_user = int(data.split("_")[1])
        if user.id != target_user: return await query.answer("⛔ دکمه ماله یکی دیگه‌ست.", show_alert=True)
        session = CRASH_SESSIONS.get(user.id)
        if not session or not session.get("active"): return await query.answer("❌ تمام شده!", show_alert=True)
        
        session["active"] = False 
        prize = int(session["bet"] * session["current"])
        add_coins(user.id, prize)
        record_win(user.id)
        return await query.edit_message_text(f"✅ **پرواز موفق! ضریب {session['current']:.2f}x**\n🪙 جایزه شما: **{prize:,}** سکه", reply_markup=main_menu())

    # -- TICTACTOE MOVES --
    if data.startswith("t3_"):
        if data == "t3_ignore": return
        room = get_room(update.effective_chat.id)
        if not room or room.game_type != "دوز" or not room.started: return await query.answer("بازی تمام شده.", show_alert=True)
        
        if user.id != room.game_state["turn"]: return await query.answer("نوبت شما نیست!", show_alert=True)
            
        idx = int(data.split("_")[1])
        symbol = "❌" if user.id == room.players[0] else "⭕️"
        room.game_state["board"][idx] = symbol
        
        winner = check_tictactoe_winner(room.game_state["board"])
        if winner:
            prize = int((room.bet * 2) * 0.95)
            if winner == "DRAW":
                for p in room.players: add_coins(p, room.bet)
                msg = "🤝 **بازی دوز مساوی شد!** سکه‌ها برگشت."
            else:
                win_player = room.players[0] if winner == "❌" else room.players[1]
                lose_player = room.players[1] if winner == "❌" else room.players[0]
                add_coins(win_player, prize)
                record_win(win_player)
                record_loss(lose_player)
                msg = f"🏆 **{get_p_name(win_player)} در بازی دوز پیروز شد!**\n🪙 جایزه: {prize}"
            
            b = room.game_state["board"]
            msg += f"\n\n`{b[0]}|{b[1]}|{b[2]}\n{b[3]}|{b[4]}|{b[5]}\n{b[6]}|{b[7]}|{b[8]}`"
            remove_room(room)
            return await query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")
        else:
            room.game_state["turn"] = room.players[1] if user.id == room.players[0] else room.players[0]
            room.game_state["turn_num"] += 1
            msg, kb = build_tictactoe_ui(room)
            await query.edit_message_text(msg, reply_markup=kb)
            asyncio.create_task(tictactoe_timer_task(context.bot, room.chat_id, room.game_state["turn_num"], room.game_state["turn"]))
            return

    # -- RPS MOVES --
    if data.startswith("rps_"):
        room = get_room(update.effective_chat.id)
        if not room or room.game_type != "سنگ_کاغذ_قیچی" or not room.started: return await query.answer("بازی تمام شده.", show_alert=True)
        if user.id not in room.players: return await query.answer("شما بازیکن این اتاق نیستید!", show_alert=True)
        
        move = data.split("_")[1]
        room.game_state["choices"][user.id] = move
        
        p1, p2 = room.players[0], room.players[1]
        choices = room.game_state["choices"]
        
        # اگر هر دو انتخاب کردند
        if choices.get(p1) and choices.get(p2):
            m1, m2 = choices[p1], choices[p2]
            if m1 == m2: winner = "DRAW"
            else:
                win_map = {"سنگ": "قیچی", "کاغذ": "سنگ", "قیچی": "کاغذ"}
                winner = p1 if win_map[m1] == m2 else p2
                
            prize = int((room.bet * 2) * 0.95)
            if winner == "DRAW":
                for p in room.players: add_coins(p, room.bet)
                msg = f"🤝 **مساوی شدید!**\n{get_p_name(p1)}: {m1} | {get_p_name(p2)}: {m2}\nسکه ها برگشت."
            else:
                loser = p2 if winner == p1 else p1
                add_coins(winner, prize)
                record_win(winner)
                record_loss(loser)
                msg = f"🏆 **{get_p_name(winner)} برنده شد!**\n{get_p_name(p1)}: {m1} جانب | {get_p_name(p2)}: {m2}\n🪙 جایزه: {prize}"
                
            remove_room(room)
            return await query.edit_message_text(msg, reply_markup=main_menu())
        else:
            msg, kb = build_rps_ui(room)
            await query.edit_message_text(msg, reply_markup=kb)
            return

    # -- GAMES LIST --
    if data == "games":
        rows = [[InlineKeyboardButton(GAME_NAMES[g], callback_data=f"game_{g}")] for g in GAME_NAMES.keys()]
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="home")])
        return await query.edit_message_text("🎮 قمارخونه طویله! یکیو انتخاب کن:", reply_markup=InlineKeyboardMarkup(rows))

    if data.startswith("game_") and data not in ["game_join", "game_start", "game_cancel"]:
        g_type = data[5:]
        USER_GAME_SELECTION[user.id] = {"game": g_type, "step": "waiting_for_bet"}
        return await query.edit_message_text(f"بازی: {GAME_NAMES[g_type]}\n💰 مبلغ شرط رو بفرست:")

    # -- GAME MODE --
    if data == "mode_bot":
        state = USER_GAME_SELECTION.get(user.id)
        if not state: return
        if not remove_coins(user.id, state["bet"]): return await query.edit_message_text("❌ پول کم داری!", reply_markup=main_menu())

        room = GameRoom(game_type=state["game"], chat_id=update.effective_chat.id, creator_id=user.id, bet=state["bet"], against_bot=True, players=[user.id, -1], started=True)
        
        # پوکر مقابل بات
        if room.game_type == "پوکر":
            prize = int((state["bet"] * 2) * 0.95)
            add_coins(user.id, prize)
            record_win(user.id)
            msg = f"🎰 **پوکر اورجینال (تک‌نفره)**\nایول! کارت‌های دست تو از بات قوی‌تر بود و بردی.\n🪙 جایزه: {prize}"
        else:
            msg = "🎮 بازی اجرا شد."
            
        remove_room(room)
        return await query.edit_message_text(msg, reply_markup=main_menu())

    if data == "mode_pvp":
        state = USER_GAME_SELECTION.get(user.id)
        if not state: return
        if get_room(update.effective_chat.id): return await query.edit_message_text("❌ یه بازی اینجا بازه.", reply_markup=main_menu())
        if not remove_coins(user.id, state["bet"]): return await query.edit_message_text("❌ پول نداری!", reply_markup=main_menu())

        room = GameRoom(game_type=state["game"], chat_id=update.effective_chat.id, creator_id=user.id, bet=state["bet"], max_players=2, players=[user.id])
        ACTIVE_GAMES[str(update.effective_chat.id)] = room
        PLAYER_GAMES[user.id] = str(update.effective_chat.id)
        
        txt = f"🎮 اتاق: {GAME_NAMES[state['game']]}\n💰 شرط: {state['bet']}\n👥 ظرفیت: ۲ نفر\n\n1. {user.first_name}"
        return await query.edit_message_text(txt, reply_markup=room_keyboard())

    if data == "game_join":
        room = get_room(update.effective_chat.id)
        if not room or room.started: return await query.answer("❌ در دسترس نیست.", show_alert=True)
        if user.id in room.players: return await query.answer("قبلا وارد شدی.", show_alert=True)
        if len(room.players) >= room.max_players: return await query.answer("ظرفیت پره!", show_alert=True)
        if not remove_coins(user.id, room.bet): return await query.answer("پول کم داری!", show_alert=True)
        
        room.players.append(user.id)
        names = "\n".join([f"{i+1}. {get_user(p)['name']}" for i, p in enumerate(room.players)])
        txt = f"🎮 اتاق: {GAME_NAMES[room.game_type]}\n💰 شرط: {room.bet}\n👥 ظرفیت: {room.max_players} نفر\n\n{names}"
        return await query.edit_message_text(txt, reply_markup=room_keyboard())

    if data == "game_start":
        room = get_room(update.effective_chat.id)
        if not room or room.creator_id != user.id: return await query.answer("فقط سازنده!", show_alert=True)
        if len(room.players) < 2: return await query.answer("حداقل ۲ نفر!", show_alert=True)
        
        room.started = True
        
        # --- شروع دوز تعاملی ---
        if room.game_type == "دوز":
            room.game_state = {
                "board": [" "]*9,
                "turn": room.players[0],
                "strikes": {room.players[0]: 0, room.players[1]: 0},
                "turn_num": 0
            }
            msg, kb = build_tictactoe_ui(room)
            m = await query.edit_message_text(msg, reply_markup=kb)
            room.message_id = m.message_id
            asyncio.create_task(tictactoe_timer_task(context.bot, room.chat_id, 0, room.players[0]))
            return

        # --- شروع سنگ، کاغذ، قیچی تعاملی ---
        if room.game_type == "سنگ_کاغذ_قیچی":
            room.game_state = {
                "choices": {},
                "round": 1
            }
            msg, kb = build_rps_ui(room)
            m = await query.edit_message_text(msg, reply_markup=kb)
            room.message_id = m.message_id
            asyncio.create_task(rps_timer_task(context.bot, room.chat_id, 1))
            return

        # سایر بازی‌ها
        prize = int((room.bet * len(room.players)) * 0.95)
        winner = room.players[0]
        add_coins(winner, prize)
        record_win(winner)
        for p in room.players:
            if p != winner: record_loss(p)
        msg = f"🏆 **{get_p_name(winner)} برنده شد!**\n🪙 جایزه: {prize} 🪙"
        remove_room(room)
        return await query.edit_message_text(msg, reply_markup=main_menu())

    if data == "game_cancel":
        room = get_room(update.effective_chat.id)
        if not room or room.creator_id != user.id: return await query.answer("فقط سازنده!", show_alert=True)
        for p in room.players: add_coins(p, room.bet)
        remove_room(room)
        return await query.edit_message_text("❌ لغو شد.", reply_markup=main_menu())

# ============================================================
# TEXT HANDLERS
# ============================================================
async def general_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()
    ensure_user(user.id, user.first_name)

    u_data = get_user(user.id)
    if u_data and u_data["is_banned"] == 1: return
    
    if text == "/start":
        USER_GAME_SELECTION.pop(user.id, None)
        return await update.message.reply_text("🫏 **خوش اومدی!** از منو انتخاب کن:", reply_markup=main_menu())

    state = USER_GAME_SELECTION.get(user.id)
    if state and state.get("step") == "waiting_for_bet":
        if text.isdigit():
            bet = int(text)
            if bet < MIN_BET: return await update.message.reply_text(f"حداقل شرط {MIN_BET}!")
            if u_data['coins'] < bet: return await update.message.reply_text("پول نداری!")
            
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
