# ============================================================
# KHARBOT PRO - FINAL VERSION
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

DB_FILE = "kharbot.db"
MIN_BET = 50
MAX_BET = 10000
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
            last_daily INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)""")
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
        db.execute("""CREATE TABLE IF NOT EXISTS achievement_progress (
            user_id INTEGER PRIMARY KEY, games_count INTEGER DEFAULT 0)""")
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
# SHOP & INVENTORY SYSTEM (ADVANCED)
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
# GAMES AND LOGIC (FLAWLESS & STRONG BOT)
# ============================================================

GAME_NAMES = {
    "تاس": "🎲 تاس", "سکه": "🪙 شیر یا خط", "حدس": "🔢 حدس عدد",
    "جنگ": "⚔️ جنگ خرها", "ریس": "🏇 مسابقه خرها", "بمب": "💣 بمب",
    "گنج": "💎 گنج", "دزد": "🥷 دزد", "چالش": "🧠 چالش", "مسابقه صدا": "🔊 مسابقه عرعر"
}

ACTIVE_GAMES = {}
PLAYER_GAMES = {}
USER_GAME_SELECTION = {} # ذخیره مسیر انتخاب کاربر: game -> bet -> mode

@dataclass
class GameRoom:
    game_type: str
    chat_id: int
    creator_id: int
    bet: int
    max_players: int = 4
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

def run_game(room):
    # ربات بسیار قوی است!
    results = {}
    winner = None
    extra_data = None
    
    if room.game_type == "تاس":
        for p in room.players:
            if p == -1: results[p] = random.choice([5, 6, 6]) # ربات اکثرا ۶ میاورد
            else: results[p] = random.randint(1, 6)
        winner = max(results, key=results.get)
        extra_data = results
        
    elif room.game_type == "حدس":
        target = random.randint(1, 10)
        for p in room.players:
            if p == -1: results[p] = target if random.random() < 0.7 else random.randint(1, 10) # 70% شانس برد مطلق
            else: results[p] = target if random.random() < 0.15 else random.randint(1, 10)
        winner = min(results, key=lambda x: abs(results[x] - target))
        extra_data = (target, results)
        
    else:
        # برای سایر بازی‌ها سیستم امتیازی کلی
        for p in room.players:
            if p == -1: results[p] = random.uniform(85, 100) # امتیاز ربات بین 85 تا 100
            else:
                d = get_donkey(p)
                base = sum([d['luck'], d['speed'], d['strength'], d['sounds']]) if d else 4
                results[p] = random.uniform(10, 60) + (base * 2)
        winner = max(results, key=results.get)

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

def game_bet_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("50 🪙", callback_data="betval_50"), InlineKeyboardButton("100 🪙", callback_data="betval_100")],
        [InlineKeyboardButton("250 🪙", callback_data="betval_250"), InlineKeyboardButton("500 🪙", callback_data="betval_500")],
        [InlineKeyboardButton("1000 🪙", callback_data="betval_1000"), InlineKeyboardButton("5000 🪙", callback_data="betval_5000")],
        [InlineKeyboardButton("🔙 لیست بازی‌ها", callback_data="games")]
    ])

def game_mode_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 بازی با بات قوی", callback_data="mode_bot")],
        [InlineKeyboardButton("👥 ایجاد اتاق (گروهی)", callback_data="mode_pvp")],
        [InlineKeyboardButton("🔙 لغو", callback_data="games")]
    ])

def room_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 ورود به بازی", callback_data="game_join")],
        [InlineKeyboardButton("▶️ شروع بازی", callback_data="game_start"), InlineKeyboardButton("❌ لغو", callback_data="game_cancel")]
    ])

def profile_text(user_id):
    u = get_user(user_id)
    if not u: return "❌ پروفایل یافت نشد."
    return (f"👤 **پروفایل {u['name']}**\n━━━━━━━━━━━━━━\n⭐ سطح: {u['level']}\n✨ XP: {u['xp']}\n"
            f"🪙 موجودی: **{u['coins']:,}**\n🏆 برد: {u['wins']} | 💀 باخت: {u['losses']}")

def donkey_text(user_id):
    d = get_donkey(user_id)
    u = get_user(user_id)
    if not d: return "❌ خر یافت نشد."
    return (f"🫏 **خرِ {u['name']}**\n━━━━━━━━━━━━━━\n🍖 گرسنگی: {d['hunger']}/100\n💧 تشنگی: {d['thirst']}/100\n"
            f"⚡ انرژی: {d['energy']}/100\n❤️ شادی: {d['happiness']}/100\n\n💪 قدرت: {d['strength']} | 🏃 سرعت: {d['speed']}\n"
            f"🍀 شانس: {d['luck']} | 🔊 عرعر: {d['sounds']}")

# ============================================================
# CALLBACK HANDLERS
# ============================================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    ensure_user(user.id, user.first_name)
    data = query.data

    # -- NAV --
    if data == "home":
        await query.edit_message_text("🏠 منوی اصلی:", reply_markup=main_menu())
        return

    # -- PROFILE & DONKEY --
    if data == "profile":
        await query.edit_message_text(profile_text(user.id), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منو", callback_data="home")]]))
        return
    if data == "donkey":
        await query.edit_message_text(donkey_text(user.id), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منو", callback_data="home")]]))
        return

    # -- SOUND --
    if data == "sound_action":
        msg = await donkey_sound_system(user.id)
        await query.edit_message_text(msg, reply_markup=main_menu(), parse_mode="Markdown")
        return

    # -- DAILY --
    if data == "daily":
        now = int(time.time())
        u = get_user(user.id)
        if now - u["last_daily"] < 86400:
            await query.answer("⏳ جایزه روزانه هنوز آماده نیست!", show_alert=True)
            return
        reward = random.randint(500, 1000)
        with closing(db_connect()) as db:
            db.execute("UPDATE users SET coins = coins + ?, last_daily = ? WHERE user_id = ?", (reward, now, user.id)); db.commit()
        await query.edit_message_text(f"🎁 جایزه روزانه شما:\n🪙 +{reward:,} سکه", reply_markup=main_menu())
        return

    # -- SHOP & INVENTORY --
    if data == "shop":
        text = "🏪 **فروشگاه خرستان**\n━━━━━━━━━━━━━━\n"
        buttons = []
        for k, v in SHOP_ITEMS.items():
            text += f"▪️ {v['name']} ({v['price']}🪙): {v['desc']}\n"
            buttons.append([InlineKeyboardButton(f"خرید {v['name']}", callback_data=f"buy_{k}")])
        buttons.append([InlineKeyboardButton("🔙 منو", callback_data="home")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("buy_"):
        item_id = data[4:]
        item = SHOP_ITEMS[item_id]
        if not remove_coins(user.id, item["price"]):
            await query.answer("❌ سکه کافی نداری!", show_alert=True)
            return
            
        if item["type"] == "consumable":
            update_inventory(user.id, item_id, 1)
            await query.answer(f"✅ {item['name']} به کیف شما اضافه شد.", show_alert=True)
        else:
            # Upgrade directly
            stat = item["stat"]
            with closing(db_connect()) as db:
                db.execute(f"UPDATE donkeys SET {stat} = {stat} + 1 WHERE user_id = ?", (user.id,)); db.commit()
            await query.answer(f"✅ ارتقا با موفقیت انجام شد! {stat} +1", show_alert=True)
        return

    if data == "inventory":
        text = "🎒 **کوله پشتی**\n━━━━━━━━━━━━━━\n"
        buttons = []
        for k, v in SHOP_ITEMS.items():
            if v["type"] == "consumable":
                amt = get_item_amount(user.id, k)
                if amt > 0:
                    text += f"▪️ {v['name']}: {amt} عدد\n"
                    buttons.append([InlineKeyboardButton(f"استفاده {v['name']}", callback_data=f"use_{k}")])
        if not buttons: text += "کیف شما خالی است."
        buttons.append([InlineKeyboardButton("🔙 منو", callback_data="home")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("use_"):
        item_id = data[4:]
        if update_inventory(user.id, item_id, -1):
            if item_id == "golden_carrot":
                with closing(db_connect()) as db: db.execute("UPDATE donkeys SET hunger=100, energy=100 WHERE user_id=?", (user.id,)); db.commit()
            elif item_id == "vip_soap":
                with closing(db_connect()) as db: db.execute("UPDATE donkeys SET happiness=100 WHERE user_id=?", (user.id,)); db.commit()
            await query.answer("✅ استفاده شد!", show_alert=True)
        else:
            await query.answer("❌ این آیتم را ندارید.", show_alert=True)
        return

    # -- GAME FLOW: 1. SELECT GAME --
    if data == "games":
        rows = []
        g_list = list(GAME_NAMES.keys())
        for i in range(0, len(g_list), 2):
            rows.append([InlineKeyboardButton(GAME_NAMES[g], callback_data=f"game_{g}") for g in g_list[i:i+2]])
        rows.append([InlineKeyboardButton("🔙 منو", callback_data="home")])
        await query.edit_message_text("🎮 بازی مورد نظر را انتخاب کن:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("game_") and data not in ["game_join", "game_start", "game_cancel"]:
        g_type = data[5:]
        USER_GAME_SELECTION[user.id] = {"game": g_type}
        await query.edit_message_text(f"بازی انتخاب شده: {GAME_NAMES[g_type]}\n\n💰 مبلغ شرط را انتخاب کن:", reply_markup=game_bet_keyboard())
        return

    # -- GAME FLOW: 2. SELECT BET --
    if data.startswith("betval_"):
        bet = int(data[7:])
        if user.id not in USER_GAME_SELECTION: return
        USER_GAME_SELECTION[user.id]["bet"] = bet
        g_name = GAME_NAMES[USER_GAME_SELECTION[user.id]["game"]]
        await query.edit_message_text(f"بازی: {g_name}\nشرط: {bet} 🪙\n\n🎮 نوع رقابت را انتخاب کن:", reply_markup=game_mode_keyboard())
        return

    # -- GAME FLOW: 3. SELECT MODE (PVE / PVP) --
    if data == "mode_bot":
        state = USER_GAME_SELECTION.get(user.id)
        if not state: return
        
        if not remove_coins(user.id, state["bet"]):
            await query.edit_message_text("❌ سکه کافی نداری!", reply_markup=main_menu())
            return

        room = GameRoom(game_type=state["game"], chat_id=update.effective_chat.id, creator_id=user.id, bet=state["bet"], against_bot=True, players=[user.id, -1], started=True)
        
        winner, extra = run_game(room)
        
        if winner == -1:
            msg = f"🤖 **هوش مصنوعی برنده شد!**\nسکه هاتو باختی.\n\n"
            record_loss(user.id)
        else:
            prize = int((state["bet"] * 2) * 0.95) # 5% fee
            msg = f"🏆 **تو برنده شدی!**\n🪙 جایزه: {prize} 🪙\n\n"
            add_coins(user.id, prize)
            record_win(user.id)
            
        if extra and isinstance(extra, dict):
            msg += f"🎲 امتیاز شما: {extra.get(user.id)} | امتیاز بات: {extra.get(-1)}"
        elif extra and isinstance(extra, tuple):
            msg += f"🎯 هدف: {extra[0]} | حدس شما: {extra[1].get(user.id)} | حدس بات: {extra[1].get(-1)}"

        await query.edit_message_text(msg, reply_markup=main_menu())
        return

    if data == "mode_pvp":
        state = USER_GAME_SELECTION.get(user.id)
        if not state: return
        if get_room(update.effective_chat.id):
            await query.edit_message_text("❌ یک بازی از قبل در این گروه فعال است.", reply_markup=main_menu())
            return
        if not remove_coins(user.id, state["bet"]):
            await query.edit_message_text("❌ سکه کافی نداری!", reply_markup=main_menu())
            return

        room = GameRoom(game_type=state["game"], chat_id=update.effective_chat.id, creator_id=user.id, bet=state["bet"], max_players=4, players=[user.id])
        ACTIVE_GAMES[str(update.effective_chat.id)] = room
        PLAYER_GAMES[user.id] = str(update.effective_chat.id)
        
        txt = f"🎮 اتاق بازی: {GAME_NAMES[state['game']]}\n💰 شرط: {state['bet']}\n\n1. {user.first_name}"
        await query.edit_message_text(txt, reply_markup=room_keyboard())
        return

    # -- PVP ROOM CONTROLS --
    if data == "game_join":
        room = get_room(update.effective_chat.id)
        if not room or room.started: return await query.answer("❌ بازی در دسترس نیست.", show_alert=True)
        if user.id in room.players: return await query.answer("شما قبلا وارد شدید.", show_alert=True)
        if not remove_coins(user.id, room.bet): return await query.answer("سکه کافی نداری!", show_alert=True)
        
        room.players.append(user.id)
        PLAYER_GAMES[user.id] = str(update.effective_chat.id)
        
        names = "\n".join([f"{i+1}. {get_user(p)['name']}" for i, p in enumerate(room.players)])
        txt = f"🎮 اتاق بازی: {GAME_NAMES[room.game_type]}\n💰 شرط: {room.bet}\n\n{names}"
        await query.edit_message_text(txt, reply_markup=room_keyboard())
        return

    if data == "game_start":
        room = get_room(update.effective_chat.id)
        if not room or room.creator_id != user.id: return await query.answer("فقط سازنده میتواند استارت کند.", show_alert=True)
        if len(room.players) < 2: return await query.answer("حداقل ۲ نفر لازم است.", show_alert=True)
        
        room.started = True
        winner, extra = run_game(room)
        prize = int((room.bet * len(room.players)) * 0.95)
        
        add_coins(winner, prize)
        record_win(winner)
        for p in room.players:
            if p != winner: record_loss(p)
            
        msg = f"🏆 **{get_user(winner)['name']} برنده شد!**\n🪙 جایزه: {prize}\n"
        remove_room(room)
        await query.edit_message_text(msg, reply_markup=main_menu())
        return

    if data == "game_cancel":
        room = get_room(update.effective_chat.id)
        if not room or room.creator_id != user.id: return await query.answer("فقط سازنده میتواند لغو کند.", show_alert=True)
        
        for p in room.players:
            add_coins(p, room.bet)
        remove_room(room)
        await query.edit_message_text("❌ بازی لغو شد و سکه ها برگشت.", reply_markup=main_menu())
        return

# ============================================================
# COMMANDS & TEXT HANDLERS
# ============================================================

async def general_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()
    ensure_user(user.id, user.first_name)

    # Dictionary for mapping commands and words
    cmd_map = {
        "/donkey": "donkey", "خر": "donkey", "خر من": "donkey",
        "/profile": "profile", "پروفایل": "profile",
        "/shop": "shop", "فروشگاه": "shop", "خرید": "shop",
        "/inventory": "inventory", "کیف": "inventory", "کوله": "inventory",
        "/games": "games", "بازی": "games", "گیم": "games",
        "/daily": "daily", "جایزه": "daily", "روزانه": "daily",
        "/sound": "sound", "صدا": "sound", "عر": "sound", "عرعر": "sound", "ترک": "sound",
    }

    action = cmd_map.get(text.lower())
    
    if text == "/start" or text == "شروع":
        await update.message.reply_text("🫏 **به خرستان خوش آمدید!**", reply_markup=main_menu(), parse_mode="Markdown")
        return

    if action == "donkey":
        await update.message.reply_text(donkey_text(user.id), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منو", callback_data="home")]]))
    elif action == "profile":
        await update.message.reply_text(profile_text(user.id), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 منو", callback_data="home")]]))
    elif action == "shop":
        # Simulate click on shop
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
        
    # Check if a specific game name was directly typed
    elif text in GAME_NAMES:
        USER_GAME_SELECTION[user.id] = {"game": text}
        await update.message.reply_text(f"بازی انتخاب شده: {GAME_NAMES[text]}\n\n💰 مبلغ شرط را انتخاب کن:", reply_markup=game_bet_keyboard())
        
    elif not text.startswith("/"):
        pass # Ignore unknown regular texts to prevent spam

# ============================================================
# MAIN LAUNCHER
# ============================================================

def main():
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN is missing!")
        return
        
    init_db()
    
    app = Application.builder().token(BOT_TOKEN).build()

    # Handle all texts and commands via one unified robust handler
    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, general_text_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("KHARBOT PRO Started successfully!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
