# ============================================================
# KHARBOT PRO - FINAL MASTER VERSION (WITH REPLY ADMIN CMD)
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

# استفاده از مسیر موقت برای رفع خطای سرورهای ابری
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
        
        try:
            db.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
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
# SHOP & INVENTORY SYSTEM
# ============================================================

SHOP_ITEMS = {
    "golden_carrot": {"name": "🥕 هویج طلایی", "price": 300, "type": "consumable", "desc": "انرژی و گرسنگی کامل."},
    "vip_soap": {"name": "🫧 شامپو VIP", "price": 250, "type": "consumable", "desc": "شادی خر به ۱۰۰ می‌رسد."},
    "sunglasses": {"name": "🕶 عینک لاتی", "price": 3500, "type": "upgrade", "stat": "luck", "desc": "دائمی: شانس +1"},
    "turbo_shoes": {"name": "👟 نعل توربو", "price": 3500, "type": "upgrade", "stat": "speed", "desc": "دائمی: سرعت +1"},
    "protein": {"name": "💪 مکمل پروتئین", "price": 3500, "type": "upgrade", "stat": "strength", "desc": "دائمی: قدرت +1"},
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
    "سنگ_کاغذ_قیچی": "✌️✊✋ سنگ، کاغذ، قیچی",
    "لگد_خر": "🐴💥 لگد خر (بتل رویال)",
    "هویج_خوری": "🥕 مسابقه هویج‌خوری",
    "انفجار": "💥 بازی زنده انفجار (Crash)",
    "دوز": "❌⭕️ دوز (تیک‌تک‌تو)",
    "کارت_31": "🃏 بازی 31 (۵ نفره)",
    "پوکر": "🎰 پوکر اورجینال (Texas Hold'em)",
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
    max_players: int = 5 
    players: list = field(default_factory=list)
    started: bool = False
    against_bot: bool = False
    created_at: float = field(default_factory=time.time)

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

async def run_crash_task(bot, chat_id, message_id, user_id, session):
    crash_point = session["crash_point"]
    step = 1
    
    while session.get("active") and session["current"] < crash_point:
        await asyncio.sleep(1.5)
        if not session.get("active"): break
            
        session["current"] += random.uniform(0.1, 0.4) * step
        if session["current"] > crash_point:
            session["current"] = crash_point
            
        if session["current"] >= crash_point:
            session["active"] = False
            record_loss(user_id)
            msg = f"💥 **بـــوم! انفجار!**\n━━━━━━━━━━━━━━\nمتأسفانه ضریب در **{crash_point:.2f}x** بسته شد و شرطت سوخت! 📉\n\n💸 مبلغ باخته: {session['bet']} 🪙"
            try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=message_id, reply_markup=main_menu())
            except Exception: pass
            break
        else:
            current_val = session["current"]
            current_prize = int(session["bet"] * current_val)
            msg = f"💥 **بازی زنده انفجار**\n━━━━━━━━━━━━━━\n💰 شرط: {session['bet']} 🪙\n\n📈 ضریب فعلی: **{current_val:.2f}x**\n\n⚠️ هر لحظه ممکنه منفجر بشه، سریع برداشت کن!"
            btn = InlineKeyboardMarkup([[InlineKeyboardButton(f"🛑 برداشت ({current_prize:,} 🪙)", callback_data=f"crashout_{user_id}")]])
            try: await bot.edit_message_text(msg, chat_id=chat_id, message_id=message_id, reply_markup=btn)
            except Exception: pass
        step += 1

def run_game(room):
    extra_data = {}
    winner = None

    if room.game_type == "سنگ_کاغذ_قیچی":
        moves = ["سنگ 🗿", "کاغذ 📄", "قیچی ✂️"]
        results = {p: random.choice(moves) for p in room.players}
        p1, p2 = room.players[0], room.players[1]
        m1, m2 = results[p1], results[p2]
        
        if m1 == m2: winner = "DRAW"
        else:
            win_map = {"سنگ 🗿": "قیچی ✂️", "کاغذ 📄": "سنگ 🗿", "قیچی ✂️": "کاغذ 📄"}
            winner = p1 if win_map[m1] == m2 else p2
        extra_data = {"results": results}

    elif room.game_type == "لگد_خر":
        alive = room.players.copy()
        log = []
        round_num = 1
        while len(alive) > 1:
            loser = random.choice(alive)
            if loser == -1 and len(alive) > 2 and random.random() < 0.3:
                loser = random.choice([x for x in alive if x != -1])
            alive.remove(loser)
            log.append(f"راند {round_num}: خر جفتک انداخت تو صورت {get_p_name(loser)} 💥")
            round_num += 1
        winner = alive[0]
        extra_data = {"log": log}

    elif room.game_type == "هویج_خوری":
        results = {p: random.randint(10, 80) for p in room.players}
        winner = max(results, key=results.get)
        extra_data = {"results": results}

    elif room.game_type == "دوز":
        p1, p2 = room.players[0], room.players[1]
        rand = random.random()
        if rand < 0.2:
            winner = "DRAW"
            board = "❌ | ⭕️ | ❌\n⭕️ | ❌ | ⭕️\n⭕️ | ❌ | ⭕️"
        elif rand < 0.6:
            winner = p1
            board = "❌ | ❌ | ❌\n⭕️ |    | ⭕️\n   | ⭕️ |   "
        else:
            winner = p2
            board = "⭕️ | ⭕️ | ⭕️\n❌ |    | ❌\n   | ❌ |   "
        extra_data = {"board": board}

    elif room.game_type == "کارت_31":
        lives = {p: 3 for p in room.players}
        alive = room.players.copy()
        log = []
        round_num = 1
        
        while len(alive) > 1:
            round_scores = {}
            for p in alive:
                if p == -1: round_scores[p] = random.randint(22, 31) 
                else: round_scores[p] = random.randint(15, 31)
            
            min_score = min(round_scores.values())
            losers = [p for p, s in round_scores.items() if s == min_score]
            round_loser = random.choice(losers) 
            
            lives[round_loser] -= 1
            log.append(f"♦️ راند {round_num}: کمترین امتیاز رو {get_p_name(round_loser)} آورد ({min_score}). یک جون پرید! (باقی‌مانده: {lives[round_loser]} ❤️)")
            
            if lives[round_loser] == 0:
                log.append(f"💀 {get_p_name(round_loser)} تمام جون‌هاش تموم شد و حذف شد!")
                alive.remove(round_loser)
            round_num += 1

        winner = alive[0]
        extra_data = {"log": log}

    elif room.game_type == "پوکر":
        suits = ['♠️', '♥️', '♦️', '♣️']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        deck = [(r_idx, r, s) for r_idx, r in enumerate(ranks, start=2) for s in suits]
        random.shuffle(deck)
        
        def eval_poker_hand(cards):
            c_ranks = [c[0] for c in cards]
            c_suits = [c[2] for c in cards]
            is_flush = len(set(c_suits)) == 1
            r_sorted = sorted(set(c_ranks), reverse=True)
            is_straight = len(r_sorted) == 5 and r_sorted[0] - r_sorted[4] == 4
            if r_sorted == [14, 5, 4, 3, 2]: 
                is_straight = True
                c_ranks = [5, 4, 3, 2, 1] if 14 in c_ranks else c_ranks
            score_base = sorted(c_ranks, key=lambda r: (c_ranks.count(r), r), reverse=True)
            counts = {r: c_ranks.count(r) for r in set(c_ranks)}
            freq = sorted(counts.values(), reverse=True)
            
            if is_flush and is_straight: return (8, score_base), "استریت فلاش"
            if freq == [4, 1]: return (7, score_base), "کاره (4 of a Kind)"
            if freq == [3, 2]: return (6, score_base), "فول هاوس"
            if is_flush: return (5, score_base), "رنگ (Flush)"
            if is_straight: return (4, score_base), "ردیف (Straight)"
            if freq == [3, 1, 1]: return (3, score_base), "سه تایی (3 of a Kind)"
            if freq == [2, 2, 1]: return (2, score_base), "دو جفت (Two Pair)"
            if freq == [2, 1, 1, 1]: return (1, score_base), "یک جفت (Pair)"
            return (0, score_base), "کارت بالا (High Card)"

        board = [deck.pop() for _ in range(5)]
        board_str = " ".join([f"{c[1]}{c[2]}" for c in board])

        results = {}
        for p in room.players:
            hole = [deck.pop() for _ in range(2)]
            best_score = (-1, [])
            best_name = ""
            for combo in itertools.combinations(hole + board, 5):
                score, name = eval_poker_hand(list(combo))
                if score > best_score:
                    best_score, best_name = score, name
            hole_str = " ".join([f"{c[1]}{c[2]}" for c in hole])
            results[p] = {"score": best_score, "name": best_name, "hand": hole_str}
            
        winner = max(results, key=lambda x: results[x]["score"])
        extra_data = {"results": results, "board": board_str}

    return winner, extra_data

# ============================================================
# SOUND & SCORING SYSTEM
# ============================================================

DONKEY_SOUNDS_DB = [
    {"text": "عررررررررر اصیل 🫏🔊", "type": "ar", "min": 10, "max": 30, "chance": 60},
    {"text": "تووووووورت! (صدای باد معده) 💨😷", "type": "toort", "min": 50, "max": 100, "chance": 25},
    {"text": "ترررررررک! (انفجار صوتی) 💥🤯", "type": "tarak", "min": 150, "max": 300, "chance": 15},
]

async def donkey_sound_system(user_id):
    donkey = get_donkey(user_id)
    if not donkey: return "❌ اول باید خرت رو ثبت کنی."
    cost = 50
    if not remove_coins(user_id, cost): return f"❌ برای ایجاد صدا {cost} سکه لازم داری!"
    
    rand_val = random.randint(1, 100)
    cumulative = 0
    selected = DONKEY_SOUNDS_DB[0]
    for s in DONKEY_SOUNDS_DB:
        cumulative += s["chance"]
        if rand_val <= cumulative:
            selected = s; break

    multiplier = donkey["sounds"] * 1.5
    score = int(random.randint(selected["min"], selected["max"]) * multiplier)
    add_coins(user_id, score)
    add_xp(user_id, 5)

    return (f"🎙️ **خر تو صدا درآورد!**\n━━━━━━━━━━━━━━\n🔊 **{selected['text']}**\n\n"
            f"🎯 امتیاز پایه: {score // multiplier}\n📈 ضریب مهارت خر: x{multiplier}\n\n"
            f"🎁 **جایزه دریافتی: {score:,} 🪙**\n💸 هزینه: {cost} 🪙")

# ============================================================
# UI KEYBOARDS & TEXTS
# ============================================================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🫏 خر من", callback_data="donkey"), InlineKeyboardButton("🎮 شروع بازی", callback_data="games")],
        [InlineKeyboardButton("🏪 فروشگاه", callback_data="shop"), InlineKeyboardButton("🎒 کیف", callback_data="inventory")],
        [InlineKeyboardButton("👤 پروفایل", callback_data="profile"), InlineKeyboardButton("🏆 لیدربرد", callback_data="leaderboard")],
        [InlineKeyboardButton("🎁 پاداش روزانه", callback_data="daily"), InlineKeyboardButton("🔊 ایجاد صدا", callback_data="sound_action")],
    ])

def game_mode_keyboard():
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

def profile_text(user_id):
    u = get_user(user_id)
    if not u: return "❌ شناسنامه پیدا نشد."
    return (f"👤 **شناسنامه طویله‌ای {u['name']}**\n━━━━━━━━━━━━━━\n⭐ سطح: {u['level']}\n✨ تجربه (XP): {u['xp']}\n"
            f"🪙 جیب شما: **{u['coins']:,}**\n🏆 برد: {u['wins']} | 💀 باخت: {u['losses']}")

def donkey_text(user_id):
    d = get_donkey(user_id)
    u = get_user(user_id)
    if not d: return "❌ خر یافت نشد."
    return (f"🫏 **خرِ {u['name']}**\n━━━━━━━━━━━━━━\n🍖 گرسنگی: {d['hunger']}/100\n💧 تشنگی: {d['thirst']}/100\n"
            f"⚡ انرژی: {d['energy']}/100\n❤️ شادی: {d['happiness']}/100\n\n💪 قدرت: {d['strength']} | 🏃 سرعت: {d['speed']}\n"
            f"🍀 شانس: {d['luck']} | 🔊 مهارت عرعر: {d['sounds']}")

# ============================================================
# CALLBACK HANDLERS
# ============================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    ensure_user(user.id, user.first_name)
    
    # --- چک کردن بن بودن ---
    u_data = get_user(user.id)
    if u_data and u_data.get("is_banned", 0) == 1:
        await query.edit_message_text("🚫 **عرعــــر!** شما به دلیل جفتک‌اندازی زیاد از طویله اخراج (بن) شده‌اید!")
        return
        
    data = query.data

    if data == "home":
        USER_GAME_SELECTION.pop(user.id, None)
        await query.edit_message_text("🏠 منوی اصلی طویله:", reply_markup=main_menu())
        return

    if data == "profile":
        await query.edit_message_text(profile_text(user.id), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="home")]]))
        return
    if data == "donkey":
        await query.edit_message_text(donkey_text(user.id), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="home")]]))
        return
    if data == "sound_action":
        msg = await donkey_sound_system(user.id)
        await query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")
        return
    if data == "daily":
        now = int(time.time())
        u = get_user(user.id)
        if now - u["last_daily"] < 86400:
            await query.answer("⏳ خسیس بازی درنیار، هنوز ۲۴ ساعت نشده! بعدا بیا.", show_alert=True)
            return
        reward = random.randint(500, 1000)
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET coins = coins + ?, last_daily = ? WHERE user_id = ?", (reward, now, user.id)); db.commit()
        await query.edit_message_text(f"🎁 یارانه دولتی طویله به شما تعلق گرفت:\n🪙 +{reward:,} سکه", reply_markup=main_menu())
        return

    if data == "shop":
        text = "🏪 **بازار سیاه خرستان**\n━━━━━━━━━━━━━━\n"
        buttons = []
        for k, v in SHOP_ITEMS.items():
            text += f"▪️ {v['name']} ({v['price']}🪙): {v['desc']}\n"
            buttons.append([InlineKeyboardButton(f"خرید {v['name']}", callback_data=f"buy_{k}")])
        buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="home")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("buy_"):
        item_id = data[4:]
        item = SHOP_ITEMS[item_id]
        if not remove_coins(user.id, item["price"]):
            return await query.answer("❌ داداش پولت نمی‌رسه!", show_alert=True)
        if item["type"] == "consumable":
            update_inventory(user.id, item_id, 1)
            await query.answer(f"✅ {item['name']} رفت تو جیبت.", show_alert=True)
        else:
            stat = item["stat"]
            with closing(db_connect()) as db:
                db.execute(f"UPDATE donkeys SET {stat} = {stat} + 1 WHERE user_id = ?", (user.id,)); db.commit()
            await query.answer(f"✅ خرت خفن‌تر شد! {stat} +1", show_alert=True)
        return

    if data == "inventory":
        text = "🎒 **جیب و کوله‌پشتی شما**\n━━━━━━━━━━━━━━\n"
        buttons = []
        for k, v in SHOP_ITEMS.items():
            if v["type"] == "consumable":
                amt = get_item_amount(user.id, k)
                if amt > 0:
                    text += f"▪️ {v['name']}: {amt} عدد\n"
                    buttons.append([InlineKeyboardButton(f"استفاده {v['name']}", callback_data=f"use_{k}")])
        if not buttons: text += "جیبت فعلاً خالیه، باد توش می‌پیچه!"
        buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="home")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("use_"):
        item_id = data[4:]
        if update_inventory(user.id, item_id, -1):
            if item_id == "golden_carrot":
                with closing(db_connect()) as db: db.execute("UPDATE donkeys SET hunger=100, energy=100 WHERE user_id=?", (user.id,)); db.commit()
            elif item_id == "vip_soap":
                with closing(db_connect()) as db: db.execute("UPDATE donkeys SET happiness=100 WHERE user_id=?", (user.id,)); db.commit()
            await query.answer("✅ استفاده شد! خرت صفا کرد.", show_alert=True)
        else:
            await query.answer("❌ تو جیبت از اینا نداری.", show_alert=True)
        return

    # -- CRASH CASHOUT --
    if data.startswith("crashout_"):
        target_user = int(data.split("_")[1])
        if user.id != target_user: return await query.answer("⛔ فضولی موقوف! دکمه ماله یکی دیگه‌ست.", show_alert=True)
        session = CRASH_SESSIONS.get(user.id)
        if not session or not session.get("active"): return await query.answer("❌ دیر زدی! منفجر شده یا تموم شده!", show_alert=True)
        
        session["active"] = False 
        prize = int(session["bet"] * session["current"])
        add_coins(user.id, prize)
        record_win(user.id)
        msg = f"✅ **پرواز موفق!**\n━━━━━━━━━━━━━━\nتو تونستی قبل از انفجار، در ضریب **{session['current']:.2f}x** پولت رو بکشی بیرون.\n\n🪙 جایزه شما: **{prize:,}** سکه"
        await query.edit_message_text(msg, reply_markup=main_menu())
        return

    # -- GAMES LIST --
    if data == "games":
        rows = []
        g_list = list(GAME_NAMES.keys())
        for i in range(0, len(g_list), 2):
            rows.append([InlineKeyboardButton(GAME_NAMES[g], callback_data=f"game_{g}") for g in g_list[i:i+2]])
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="home")])
        await query.edit_message_text("🎮 قمارخونه طویله! یکیو انتخاب کن:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("game_") and data not in ["game_join", "game_start", "game_cancel"]:
        g_type = data[5:]
        USER_GAME_SELECTION[user.id] = {"game": g_type, "step": "waiting_for_bet"}
        await query.edit_message_text(f"بازی انتخابی: {GAME_NAMES[g_type]}\n\n💰 **مبلغ شرطت رو با کیبورد عدد تایپ کن بفرست:**\n(حداقل {MIN_BET} سکه! اگه منصرف شدی بزن لغو)")
        return

    # -- GAME MODE (PVE / PVP) --
    if data == "mode_bot":
        state = USER_GAME_SELECTION.get(user.id)
        if not state: return
        if not remove_coins(user.id, state["bet"]): return await query.edit_message_text("❌ پولت نمی‌رسه داداش!", reply_markup=main_menu())

        room = GameRoom(game_type=state["game"], chat_id=update.effective_chat.id, creator_id=user.id, bet=state["bet"], against_bot=True, players=[user.id, -1], started=True)
        winner, extra = run_game(room)
        
        if winner == "DRAW":
            for p in room.players:
                if p != -1: add_coins(p, room.bet)
            msg = "🤝 **مساوی شدید!**\nسکه هاتون برگشت داده شد.\n\n"
            if "results" in extra: msg += "\n".join([f"{get_p_name(k)}: {v}" for k, v in extra['results'].items()])
            elif "board" in extra: msg += f"نتیجه بازی:\n`{extra['board']}`\n"
            remove_room(room)
            await query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")
            return

        prize = int((room.bet * len(room.players)) * 0.95)

        if room.game_type in ["لگد_خر", "کارت_31"]:
            log_text = "\n".join(extra["log"])
            if room.game_type == "کارت_31": msg = f"🃏 **گزارش دست‌های بازی ۳۱:**\n\n{log_text}\n\n"
            else: msg = f"🐴 **گزارش لحظه به لحظه رولت خر:**\n\n{log_text}\n\n"
            if winner == -1: msg += "🤖 **بات تنها بازمانده بود و برد!**\nسکه هاتو باختی."
            else: msg += f"🏆 **{get_p_name(winner)} آخرین بازمانده بود و برد!**\n🪙 جایزه: {prize} 🪙"
        else:
            if winner == -1: msg = f"🤖 **بات زد تو گوشِت و برد!**\nسکه هاتو باختی.\n\n"
            else: msg = f"🏆 **ایول {get_p_name(winner)}! تو بردی!**\n🪙 جایزه: {prize} 🪙\n\n"
            
            if "results" in extra:
                if room.game_type == "پوکر":
                    msg += f"\n🃏 **کارت‌های روی میز:**\n`{extra['board']}`\n\n👥 **دست بازیکنان:**\n"
                    for p_id, d in extra["results"].items(): msg += f"▪️ {get_p_name(p_id)}: [ {d['hand']} ] ⬅️ **{d['name']}**\n"
                else:
                    for p_id, score in extra["results"].items():
                        if room.game_type == "هویج_خوری": msg += f"▪️ {get_p_name(p_id)}: {score} هویج 🥕\n"
                        elif room.game_type == "سنگ_کاغذ_قیچی": msg += f"▪️ {get_p_name(p_id)}: {score}\n"
            if room.game_type == "دوز": msg += f"زمین بازی:\n`{extra['board']}`\n"

        if winner != -1:
            add_coins(winner, prize)
            record_win(winner)
        for p in room.players:
            if p != winner and p != -1: record_loss(p)
                
        remove_room(room)
        await query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")
        return

    if data == "mode_pvp":
        state = USER_GAME_SELECTION.get(user.id)
        if not state: return
        if get_room(update.effective_chat.id): return await query.edit_message_text("❌ یه بازی اینجا بازه، اول اونو تموم کنید.", reply_markup=main_menu())
        if not remove_coins(user.id, state["bet"]): return await query.edit_message_text("❌ پولت نمی‌رسه!", reply_markup=main_menu())

        max_p = 5 if state["game"] in ["کارت_31", "لگد_خر", "هویج_خوری", "پوکر"] else 2
        room = GameRoom(game_type=state["game"], chat_id=update.effective_chat.id, creator_id=user.id, bet=state["bet"], max_players=max_p, players=[user.id])
        ACTIVE_GAMES[str(update.effective_chat.id)] = room
        PLAYER_GAMES[user.id] = str(update.effective_chat.id)
        
        txt = f"🎮 اتاق بازی: {GAME_NAMES[state['game']]}\n💰 شرط: {state['bet']}\n👥 ظرفیت: {max_p} نفر\n\n1. {user.first_name}"
        await query.edit_message_text(txt, reply_markup=room_keyboard())
        return

    if data == "game_join":
        room = get_room(update.effective_chat.id)
        if not room or room.started: return await query.answer("❌ بازی در دسترس نیست یا شروع شده.", show_alert=True)
        if user.id in room.players: return await query.answer("شما قبلا وارد شدی داداش.", show_alert=True)
        if len(room.players) >= room.max_players: return await query.answer("ظرفیت پره!", show_alert=True)
        if not remove_coins(user.id, room.bet): return await query.answer("پول کم داری!", show_alert=True)
        
        room.players.append(user.id)
        PLAYER_GAMES[user.id] = str(update.effective_chat.id)
        names = "\n".join([f"{i+1}. {get_user(p)['name']}" for i, p in enumerate(room.players)])
        txt = f"🎮 اتاق بازی: {GAME_NAMES[room.game_type]}\n💰 شرط: {room.bet}\n👥 ظرفیت: {room.max_players} نفر\n\n{names}"
        await query.edit_message_text(txt, reply_markup=room_keyboard())
        return

    if data == "game_start":
        room = get_room(update.effective_chat.id)
        if not room or room.creator_id != user.id: return await query.answer("فقط اونی که بازی رو ساخته می‌تونه استارت کنه.", show_alert=True)
        if len(room.players) < 2: return await query.answer("حداقل ۲ نفر باید باشید که بشه بازی کرد!", show_alert=True)
        
        room.started = True
        winner, extra = run_game(room)
        
        if winner == "DRAW":
            for p in room.players:
                if p != -1: add_coins(p, room.bet)
            msg = "🤝 **مساوی شدید!**\nسکه هاتون برگشت داده شد.\n\n"
            if "results" in extra: msg += "\n".join([f"{get_p_name(k)}: {v}" for k, v in extra['results'].items()])
            elif "board" in extra: msg += f"نتیجه بازی:\n`{extra['board']}`\n"
            remove_room(room)
            await query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")
            return

        prize = int((room.bet * len(room.players)) * 0.95)

        if room.game_type in ["لگد_خر", "کارت_31"]:
            log_text = "\n".join(extra["log"])
            if room.game_type == "کارت_31": msg = f"🃏 **گزارش دست‌های بازی ۳۱:**\n\n{log_text}\n\n"
            else: msg = f"🐴 **گزارش لحظه به لحظه رولت خر:**\n\n{log_text}\n\n"
            if winner == -1: msg += "🤖 **بات تنها بازمانده بود و برد!**\nسکه هاتو باختی."
            else: msg += f"🏆 **{get_p_name(winner)} آخرین بازمانده بود و برد!**\n🪙 جایزه: {prize} 🪙"
        else:
            if winner == -1: msg = f"🤖 **بات برنده شد!**\nسکه هاتو باختی.\n\n"
            else: msg = f"🏆 **ایول {get_p_name(winner)}! برنده شدی!**\n🪙 جایزه: {prize} 🪙\n\n"
            
            if "results" in extra:
                if room.game_type == "پوکر":
                    msg += f"\n🃏 **کارت‌های روی میز:**\n`{extra['board']}`\n\n👥 **دست بازیکنان:**\n"
                    for p_id, d in extra["results"].items(): msg += f"▪️ {get_p_name(p_id)}: [ {d['hand']} ] ⬅️ **{d['name']}**\n"
                else:
                    for p_id, score in extra["results"].items():
                        if room.game_type == "هویج_خوری": msg += f"▪️ {get_p_name(p_id)}: {score} هویج 🥕\n"
                        elif room.game_type == "سنگ_کاغذ_قیچی": msg += f"▪️ {get_p_name(p_id)}: {score}\n"
            if room.game_type == "دوز": msg += f"زمین بازی:\n`{extra['board']}`\n"

        if winner != -1:
            add_coins(winner, prize)
            record_win(winner)
        for p in room.players:
            if p != winner and p != -1: record_loss(p)
                
        remove_room(room)
        await query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")
        return

    if data == "game_cancel":
        room = get_room(update.effective_chat.id)
        if not room or room.creator_id != user.id: return await query.answer("فقط سازنده می‌تونه لغو کنه.", show_alert=True)
        for p in room.players: add_coins(p, room.bet)
        remove_room(room)
        await query.edit_message_text("❌ بازی کنسل شد و سکه‌ها برگشت تو جیبتون.", reply_markup=main_menu())
        return

# ============================================================
# COMMANDS & TEXT HANDLERS (WITH ADMIN REPLY COMMANDS)
# ============================================================

async def general_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()
    ensure_user(user.id, user.first_name)

    u_data = get_user(user.id)
    if u_data and u_data.get("is_banned", 0) == 1:
        await update.message.reply_text("🚫 **عرعــــر!** شما به دلیل رفتار نامناسب از طویله اخراج (بن) شده‌اید! دیگه هویج بی‌هویج 🥕")
        return

    # ==========================================
    # پنل مخفی اونر (ریپلی روی پیام‌ها)
    # ==========================================
    if user.id == OWNER_ID and text.startswith(("/", "بن", "انبن", "سکه", "کسر", "+سکه", "-سکه")):
        if not update.message.reply_to_message:
            # اگه کامند ادمینی زد ولی رو پیامی ریپلی نکرد
            # ممکنه دستور ربات (مثل /start) باشه، پس فقط اگر کامند اختصاصی ادمین بود هشدار بده
            parts = text.split()
            cmd = parts[0].lower()
            if cmd in ["/ban", "بن", "/unban", "انبن", "/addcoin", "سکه", "+سکه", "/remcoin", "کسر", "-سکه"]:
                await update.message.reply_text("⚠️ ارباب، باید روی پیام کسی که می‌خوای عملیات روش انجام بشه **ریپلی (Reply)** بزنی!")
                return
        else:
            target_user = update.message.reply_to_message.from_user
            target_id = target_user.id
            parts = text.split()
            cmd = parts[0].lower()

            if cmd in ["/ban", "بن"]:
                with closing(db_connect()) as db:
                    db.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (target_id,))
                    db.commit()
                await update.message.reply_text(f"✅ کَپَلِ {target_user.first_name} رو داغ کردیم! از طویله شوت شد بیرون (بن شد) 🐴🦶")
                return
                
            elif cmd in ["/unban", "انبن"]:
                with closing(db_connect()) as db:
                    db.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (target_id,))
                    db.commit()
                await update.message.reply_text(f"✅ کاربر {target_user.first_name} دوباره به طویله راه داده شد! (آنبن) 🐎")
                return
                
            elif cmd in ["/addcoin", "سکه", "+سکه"] and len(parts) > 1:
                try:
                    amt = int(parts[1])
                    add_coins(target_id, amt)
                    await update.message.reply_text(f"💰 مبلغ {amt:,} سکه با گونی به حساب {target_user.first_name} واریز شد! شما چقدر بخشنده‌ای ارباب! 👑")
                except ValueError: pass
                return

            elif cmd in ["/remcoin", "کسر", "-سکه"] and len(parts) > 1:
                try:
                    amt = int(parts[1])
                    with closing(db_connect()) as db:
                        db.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (amt, target_id))
                        db.commit()
                    await update.message.reply_text(f"🔥 مبلغ {amt:,} سکه از حساب {target_user.first_name} کسر شد! ارباب عصبانیه! 😡")
                except ValueError: pass
                return

    # ==========================================
    # پردازش شرط‌بندی بازی‌ها
    # ==========================================
    state = USER_GAME_SELECTION.get(user.id)
    if state and state.get("step") == "waiting_for_bet":
        if text.isdigit():
            bet_amount = int(text)
            if bet_amount < MIN_BET:
                await update.message.reply_text(f"❌ خسیس بازی درنیار! حداقل شرط {MIN_BET} سکه‌ست. یه عدد درشت‌تر تایپ کن:")
                return
            
            if u_data['coins'] < bet_amount:
                await update.message.reply_text("❌ داداش جیبت تار عنکبوت بسته! پولت نمی‌رسه. یه عدد کمتر بگو یا بزن لغو:")
                return
            
            if state["game"] == "انفجار":
                remove_coins(user.id, bet_amount)
                r = random.random()
                c_point = max(1.00, 0.95 / r)
                if c_point > 40.0: c_point = 40.0 
                
                CRASH_SESSIONS[user.id] = {"active": True, "bet": bet_amount, "current": 1.00, "crash_point": c_point}
                
                msg = f"💥 **بازی زنده انفجار**\n━━━━━━━━━━━━━━\n💰 شرط شما: {bet_amount} 🪙\n\n📈 ضریب فعلی: **1.00x**\n\n🚀 سوار موشک شدی... یا علی!"
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 زودتر بپّر بیرون (آماده‌سازی...)", callback_data=f"crashout_{user.id}")]])
                
                sent_msg = await update.message.reply_text(msg, reply_markup=btn)
                asyncio.create_task(run_crash_task(context.bot, update.effective_chat.id, sent_msg.message_id, user.id, CRASH_SESSIONS[user.id]))
                USER_GAME_SELECTION.pop(user.id, None)
                return
            
            USER_GAME_SELECTION[user.id]["bet"] = bet_amount
            USER_GAME_SELECTION[user.id]["step"] = "ready_for_mode"
            
            g_name = GAME_NAMES[state["game"]]
            await update.message.reply_text(f"بازی: {g_name}\nشرط: {bet_amount} 🪙\n\n🎮 خب حالا بگو می‌خوای تنهایی به باد بری (بات) یا گروهی؟", reply_markup=game_mode_keyboard())
            return

    # ==========================================
    # نقشه‌برداری دستورات (فارسی و انگلیسی)
    # ==========================================
    cmd_map = {
        "/donkey": "donkey", "خر": "donkey", "خر من": "donkey",
        "/profile": "profile", "پروفایل": "profile", "شناسنامه": "profile",
        "/shop": "shop", "فروشگاه": "shop", "خرید": "shop", "بازار": "shop",
        "/inventory": "inventory", "کیف": "inventory", "کوله": "inventory", "جیب": "inventory",
        "/games": "games", "بازی": "games", "گیم": "games", "قمارخونه": "games",
        "/daily": "daily", "جایزه": "daily", "روزانه": "daily", "یارانه": "daily",
        "/sound": "sound", "صدا": "sound", "عر": "sound", "عرعر": "sound", "ترک": "sound",
        "/cancel": "cancel", "لغو": "cancel", "کنسل": "cancel", "بیخیال": "cancel", "فرار": "cancel",
    }

    action = cmd_map.get(text.lower())
    
    if text == "/start" or text == "شروع":
        USER_GAME_SELECTION.pop(user.id, None)
        welcome_msg = (
            "🫏 **عرعـــــــر! خوش اومدی به طویله‌ی VIP خرستان!** 🎪\n"
            "━━━━━━━━━━━━━━\n\n"
            "اینجا جاییه که خرها پادشاهی می‌کنن و آدما براشون هویج می‌خرن. 🥕\n"
            "اگه آماده‌ای که جیب بقیه رو تو بازی‌ها خالی کنی یا خودت پیاده بری خونه، بسم‌الله!\n\n"
            "👇 از منوی پایین یکیو انتخاب کن:"
        )
        await update.message.reply_text(welcome_msg, reply_markup=main_menu(), parse_mode="Markdown")
        return

    # دستور لغو 
    if action == "cancel":
        USER_GAME_SELECTION.pop(user.id, None)
        room = get_room(update.effective_chat.id)
        if room and room.creator_id == user.id:
            for p in room.players: add_coins(p, room.bet)
            remove_room(room)
            await update.message.reply_text("🗑️ بازیت رو با موفقیت انداختم تو سطل آشغال طویله! پول‌ها برگشت. (عملیات لغو شد) 🧹", reply_markup=main_menu())
        else:
            await update.message.reply_text("🤷‍♂️ خرت که تو گِل گیر نکرده بود داداش! عملیات یا بازی خاصی برای لغو وجود نداشت.", reply_markup=main_menu())
        return

    if action == "donkey":
        await update.message.reply_text(donkey_text(user.id), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به طویله", callback_data="home")]]))
    elif action == "profile":
        await update.message.reply_text(profile_text(user.id), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به طویله", callback_data="home")]]))
    elif action == "shop":
        query = type('obj', (object,), {'data': 'shop', 'from_user': user, 'answer': lambda *a,**kw: asyncio.sleep(0), 'edit_message_text': update.message.reply_text})()
        await callback_handler(type('obj', (object,), {'callback_query': query, 'effective_chat': update.effective_chat})(), context)
    elif action == "inventory":
        query = type('obj', (object,), {'data': 'inventory', 'from_user': user, 'answer': lambda *a,**kw: asyncio.sleep(0), 'edit_message_text': update.message.reply_text})()
        await callback_handler(type('obj', (object,), {'callback_query': query, 'effective_chat': update.effective_chat})(), context)
    elif action == "games":
        query = type('obj', (object,), {'data': 'games', 'from_user': user, 'answer': lambda *a,**kw: asyncio.sleep(0), 'edit_message_text': update.message.reply_text})()
        await callback_handler(type('obj', (object,), {'callback_query': query, 'effective_chat': update.effective_chat})(), context)
    elif action == "daily":
        query = type('obj', (object,), {'data': 'daily', 'from_user': user, 'answer': lambda *a,**kw: asyncio.sleep(0), 'edit_message_text': update.message.reply_text})()
        await callback_handler(type('obj', (object,), {'callback_query': query, 'effective_chat': update.effective_chat})(), context)
    elif action == "sound":
        msg = await donkey_sound_system(user.id)
        await update.message.reply_text(msg, reply_markup=main_menu(), parse_mode="Markdown")
        
    for game_code, game_name in GAME_NAMES.items():
        if text in game_name or text == game_code.replace("_", " "):
            USER_GAME_SELECTION[user.id] = {"game": game_code, "step": "waiting_for_bet"}
            await update.message.reply_text(f"🎲 دمت گرم، {game_name} رو انتخاب کردی!\n\n💰 **چقدر مایه می‌ذاری؟ (مبلغ رو به عدد بفرست):**\n(اگه پشیمون شدی کلمه «لغو» رو بفرست)")
            return

# ============================================================
# MAIN LAUNCHER
# ============================================================

def main():
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN is missing!")
        return
        
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, general_text_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("KHARBOT PRO Started successfully!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
