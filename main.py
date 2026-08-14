# ============================================================
# KHARBOT PRO - MASTER VERSION (INTERACTIVE GAMES)
# Crash is intentionally unchanged.
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
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET wins = wins + 1 WHERE user_id = ?", (user_id,))
        db.commit()
    add_xp(user_id, 25)

def record_loss(user_id):
    with closing(db_connect()) as db:
        db.execute("UPDATE users SET losses = losses + 1 WHERE user_id = ?", (user_id,))
        db.commit()
    add_xp(user_id, 5)

# ============================================================
# SHOP & INVENTORY
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
        db.execute("""INSERT INTO inventory (user_id, item, amount) VALUES (?, ?, ?)
                      ON CONFLICT(user_id, item) DO UPDATE SET amount = ?""",
                   (user_id, item, new_amount, new_amount))
        db.commit()
    return True

# ============================================================
# GAMES / ROOMS
# ============================================================

GAME_NAMES = {
    "سنگ_کاغذ_قیچی": "✌️✊✋ سنگ، کاغذ، قیچی",
    "لگد_خر": "🐴💥 لگد خر",
    "هویج_خوری": "🥕 مسابقه هویج‌خوری",
    "انفجار": "💥 بازی زنده انفجار (Crash)",
    "دوز": "❌⭕️ دوز (تیک‌تک‌تو)",
    "کارت_31": "🃏 بازی 31",
    "پوکر": "♠️ پوکر Texas Hold'em",
}

ACTIVE_GAMES = {}
PLAYER_GAMES = {}
USER_GAME_SELECTION = {}
CRASH_SESSIONS = {}
BOT_USERNAME = ""

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
    game_state: dict = field(default_factory=dict)
    message_id: int = 0

def get_room(chat_id):
    return ACTIVE_GAMES.get(str(chat_id))

def player_in_game(user_id):
    return user_id in PLAYER_GAMES

def remove_room(room):
    ACTIVE_GAMES.pop(str(room.chat_id), None)
    for p in room.players:
        if p != -1:
            PLAYER_GAMES.pop(p, None)

def get_p_name(p_id):
    if p_id == -1: return "🤖 بات قوی"
    u = get_user(p_id)
    return u["name"] if u else f"بازیکن {p_id}"

# ============================================================
# CRASH - UNCHANGED
# ============================================================

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
            try:
                await bot.edit_message_text(msg, chat_id=chat_id, message_id=message_id, reply_markup=main_menu())
            except: pass
            break
        else:
            current_prize = int(session["bet"] * session["current"])
            msg = f"💥 **بازی زنده انفجار**\n━━━━━━━━━━━━━━\n💰 شرط: {session['bet']} 🪙\n📈 ضریب فعلی: **{session['current']:.2f}x**\n⚠️ سریع برداشت کن!"
            btn = InlineKeyboardMarkup([[InlineKeyboardButton(f"🛑 برداشت ({current_prize:,} 🪙)", callback_data=f"crashout_{user_id}")]])
            try:
                await bot.edit_message_text(msg, chat_id=chat_id, message_id=message_id, reply_markup=btn)
            except: pass
        step += 1

# ============================================================
# INTERACTIVE GAME HELPERS
# ============================================================

def round_robin_next(alive_order, current):
    if not alive_order:
        return None
    try:
        idx = alive_order.index(current)
    except ValueError:
        idx = -1
    for step in range(1, len(alive_order) + 1):
        p = alive_order[(idx + step) % len(alive_order)]
        if p in alive_order:
            return p
    return alive_order[0]

def kick_keyboard(room):
    current = room.game_state.get("turn")
    alive = room.game_state.get("alive", [])
    targets = [p for p in alive if p != current]
    rows = [[InlineKeyboardButton(f"🎯 {get_p_name(p)}", callback_data=f"kick_target_{p}")] for p in targets]
    rows.append([InlineKeyboardButton("🔄 وضعیت", callback_data="kick_status")])
    return InlineKeyboardMarkup(rows)

def rps_keyboard(room):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗿 سنگ", callback_data="rps_rock"),
         InlineKeyboardButton("📄 کاغذ", callback_data="rps_paper"),
         InlineKeyboardButton("✂️ قیچی", callback_data="rps_scissors")]
    ])

def tic_keyboard(room):
    board = room.game_state["board"]
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            i = r * 3 + c
            val = board[i] or str(i + 1)
            row.append(InlineKeyboardButton(val, callback_data=f"tic_{i}"))
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def carrot_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🥕 هویج بخور!", callback_data="carrot_eat")]])

def poker_action_keyboard(room):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Check", callback_data="poker_check"),
         InlineKeyboardButton("💰 Call", callback_data="poker_call")],
        [InlineKeyboardButton("⬆️ Raise", callback_data="poker_raise"),
         InlineKeyboardButton("🚪 Fold", callback_data="poker_fold")]
    ])

# ---------------- 31 ----------------

R31_RANKS = list(range(8, 15))
R31_SUITS = ["♠️", "♥️", "♦️", "♣️"]

def r31_card_text(card):
    rank = card[0]
    label = "A" if rank == 14 else {11: "J", 12: "Q", 13: "K"}.get(rank, str(rank))
    return f"{label}{card[1]}"

def r31_deck():
    deck = [(rank, suit) for rank in R31_RANKS for suit in R31_SUITS]
    random.shuffle(deck)
    return deck

def r31_score(hand):
    # Three cards with the same rank = 30.5 regardless of suit.
    if len(hand) == 3 and len({c[0] for c in hand}) == 1:
        return 30.5
    totals = {}
    for rank, suit in hand:
        value = 11 if rank == 14 else rank
        totals[suit] = totals.get(suit, 0) + value
    return min(31, max(totals.values(), default=0))

def r31_public_table(room):
    return " | ".join(r31_card_text(c) for c in room.game_state["table"])

def r31_private_text(room, user_id):
    st = room.game_state
    hand = st["hands"].get(user_id, [])
    score = r31_score(hand)
    return (f"🃏 **بازی 31**\n━━━━━━━━━━━━━━\n"
            f"🎴 کارت‌های تو: {' | '.join(r31_card_text(c) for c in hand)}\n"
            f"⭐ امتیاز فعلی: **{score:g}**\n\n"
            f"🃏 کارت‌های روی میز:\n{r31_public_table(room)}\n\n"
            f"🎯 نوبت: **{get_p_name(st['turn'])}**")

def r31_private_keyboard(room, user_id):
    st = room.game_state
    if st["turn"] != user_id:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⏳ منتظر نوبتت باش", callback_data="noop")]])
    rows = []
    for ti, card in enumerate(st["table"]):
        for hi, own in enumerate(st["hands"][user_id]):
            rows.append([InlineKeyboardButton(
                f"🔄 {r31_card_text(card)} ← جایگزین {r31_card_text(own)}",
                callback_data=f"31_swap_{ti}_{hi}")])
    rows.append([InlineKeyboardButton("⏭️ رد نوبت", callback_data="31_pass"),
                 InlineKeyboardButton("🛑 استپ", callback_data="31_stop")])
    return InlineKeyboardMarkup(rows)

async def send_31_private(bot, room, user_id, edit=False):
    try:
        text = r31_private_text(room, user_id)
        markup = r31_private_keyboard(room, user_id)
        mid = room.game_state.setdefault("private_messages", {}).get(user_id)
        if edit and mid:
            try:
                await bot.edit_message_text(text, chat_id=user_id, message_id=mid, reply_markup=markup, parse_mode="Markdown")
                return
            except: pass
        msg = await bot.send_message(user_id, text, reply_markup=markup, parse_mode="Markdown")
        room.game_state["private_messages"][user_id] = msg.message_id
    except Exception as e:
        logger.warning("31 private message failed for %s: %s", user_id, e)

async def update_31_all(bot, room):
    for p in room.players:
        if p != -1:
            await send_31_private(bot, room, p, edit=True)

def r31_result_text(room):
    scores = {p: r31_score(room.game_state["hands"][p]) for p in room.players if p != -1}
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    lines = ["🏁 **پایان بازی 31**\n━━━━━━━━━━━━━━"]
    for i, (p, score) in enumerate(ordered, 1):
        medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else "▪️"
        lines.append(f"{medal} {get_p_name(p)} — **{score:g}**")
    if ordered:
        lines.append(f"\n🏆 برنده: **{get_p_name(ordered[0][0])}**")
    return "\n".join(lines), ordered

async def finish_31(bot, room, winner=None):
    if room.game_state.get("finished"):
        return
    room.game_state["finished"] = True
    msg, ordered = r31_result_text(room)
    if ordered:
        top = ordered[0][1]
        winners = [p for p, s in ordered if s == top]
        if winner is not None and winner in winners:
            winners = [winner]
        if len(winners) == 1:
            add_coins(winners[0], int(room.bet * len(room.players) * 0.95))
            record_win(winners[0])
            for p in room.players:
                if p != winners[0] and p != -1: record_loss(p)
        else:
            # tie: split the pool equally
            pool = int(room.bet * len(room.players) * 0.95)
            share = pool // len(winners)
            for p in winners:
                add_coins(p, share)
                record_win(p)
            for p in room.players:
                if p not in winners and p != -1: record_loss(p)
    for p in room.players:
        if p != -1:
            try:
                await bot.send_message(p, msg, parse_mode="Markdown", reply_markup=main_menu())
            except: pass
    try:
        await bot.send_message(room.chat_id, msg, parse_mode="Markdown", reply_markup=main_menu())
    except: pass
    remove_room(room)

async def start_31_room(bot, room):
    deck = r31_deck()
    hands = {p: [deck.pop(), deck.pop(), deck.pop()] for p in room.players if p != -1}
    # PvE bot gets a hand too.
    if -1 in room.players:
        hands[-1] = [deck.pop(), deck.pop(), deck.pop()]
    table = [deck.pop(), deck.pop(), deck.pop()]
    order = room.players.copy()
    random.shuffle(order)
    room.game_state = {
        "hands": hands, "table": table, "deck": deck, "order": order,
        "turn_index": 0, "turn": order[0], "finished": False,
        "stopped_by": None, "stop_turn_index": None, "private_messages": {}
    }
    await update_31_all(bot, room)
    # 31 on the initial deal ends the game immediately.
    instant = next((p for p in room.players if r31_score(hands[p]) == 31), None)
    if instant is not None:
        await finish_31(bot, room, instant)
        return
    # Bot plays when its turn comes.
    if room.game_state["turn"] == -1:
        await asyncio.sleep(1)
        await bot_31_turn(bot, room)

async def advance_31(bot, room):
    st = room.game_state
    if st.get("finished"): return
    st["turn_index"] = (st["turn_index"] + 1) % len(st["order"])
    st["turn"] = st["order"][st["turn_index"]]
    # Stop ends when the turn returns to stopper.
    if st.get("stopped_by") is not None and st["turn"] == st["stopped_by"]:
        await finish_31(bot, room)
        return
    await update_31_all(bot, room)
    if st["turn"] == -1:
        await asyncio.sleep(1)
        await bot_31_turn(bot, room)

async def bot_31_turn(bot, room):
    st = room.game_state
    if st.get("finished") or st["turn"] != -1: return
    hand = st["hands"][-1]
    if r31_score(hand) == 31:
        await finish_31(bot, room, -1)
        return
    # Strong but fair: take the table card that maximizes score, or pass.
    best = None
    best_score = r31_score(hand)
    for ti, table_card in enumerate(st["table"]):
        for hi, own in enumerate(hand):
            candidate = hand.copy()
            candidate[hi] = table_card
            score = r31_score(candidate)
            if score > best_score:
                best_score, best = score, (ti, hi)
    if best:
        ti, hi = best
        st["table"][ti], st["hands"][-1][hi] = st["hands"][-1][hi], st["table"][ti]
        if r31_score(st["hands"][-1]) == 31:
            await finish_31(bot, room, -1)
            return
    await advance_31(bot, room)

# ---------------- Donkey Kick ----------------

def kick_status_text(room):
    st = room.game_state
    alive = st.get("alive", [])
    return (f"🐴💥 **لگد خر**\n━━━━━━━━━━━━━━\n"
            f"👥 زنده‌ها: {', '.join(get_p_name(p) for p in alive)}\n"
            f"🔄 شماره راند: {st.get('round', 1)}\n"
            f"🎯 نوبت: **{get_p_name(st.get('turn'))}**")

async def finish_kick_round(bot, room, shooter, target, success):
    st = room.game_state
    if success and target in st["alive"]:
        st["alive"].remove(target)
    if len(st["alive"]) <= 1:
        winner = st["alive"][0]
        prize = int(room.bet * len(room.players) * 0.95)
        if winner != -1:
            add_coins(winner, prize)
            record_win(winner)
        for p in room.players:
            if p != winner and p != -1: record_loss(p)
        msg = f"🏆 **{get_p_name(winner)} برنده لگد خر شد!**\n🪙 جایزه: **{prize:,}**"
        try: await bot.edit_message_text(msg, chat_id=room.chat_id, message_id=room.message_id, reply_markup=main_menu(), parse_mode="Markdown")
        except: pass
        remove_room(room)
        return
    # A round ends immediately on a successful elimination.
    if success:
        st["round"] += 1
        # Next round starts at the player after the eliminated player in random order.
        order = st["order"]
        idx = order.index(target)
        next_turn = None
        for step in range(1, len(order) + 1):
            p = order[(idx + step) % len(order)]
            if p in st["alive"]:
                next_turn = p
                break
        st["turn"] = next_turn
    else:
        # Failed kick: continue to next player in the same round.
        st["turn"] = round_robin_next(st["alive"], shooter)
    text = kick_status_text(room)
    try:
        await bot.edit_message_text(text, chat_id=room.chat_id, message_id=room.message_id,
                                    reply_markup=kick_keyboard(room), parse_mode="Markdown")
    except: pass
    if st["turn"] == -1:
        await asyncio.sleep(1)
        await bot_kick_turn(bot, room)

async def bot_kick_turn(bot, room):
    st = room.game_state
    if st.get("turn") != -1 or len(st["alive"]) <= 1: return
    targets = [p for p in st["alive"] if p != -1]
    if not targets:
        return
    target = random.choice(targets)
    success = random.random() < 0.60
    await finish_kick_round(bot, room, -1, target, success)

async def start_kick_room(bot, room):
    order = room.players.copy()
    random.shuffle(order)
    room.game_state = {"order": order, "alive": order.copy(), "turn": order[0], "round": 1}
    text = kick_status_text(room)
    try:
        await bot.edit_message_text(text, chat_id=room.chat_id, message_id=room.message_id,
                                    reply_markup=kick_keyboard(room), parse_mode="Markdown")
    except: pass
    if room.game_state["turn"] == -1:
        await asyncio.sleep(1)
        await bot_kick_turn(bot, room)

# ---------------- RPS ----------------

async def rps_move(bot, room, user_id, move):
    st = room.game_state
    if st.get("finished") or user_id in st["moves"]:
        return
    st["moves"][user_id] = move

    # In PvE the bot chooses immediately after the human.
    if room.against_bot and -1 not in st["moves"]:
        st["moves"][-1] = random.choice(["rock", "paper", "scissors"])

    if len(st["moves"]) < len(room.players):
        return await bot.send_message(user_id, "✅ حرکتت ثبت شد. منتظر بقیه باش.")

    a, b = room.players[0], room.players[1]
    m = st["moves"]
    if m[a] == m[b]:
        result = "🤝 مساوی شد؛ شرط‌ها برگشت."
        add_coins(a, room.bet)
        if b != -1:
            add_coins(b, room.bet)
    else:
        wins = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
        winner = a if wins[m[a]] == m[b] else b
        if winner == -1:
            result = "🤖 بات برنده شد! سکه‌هات باخت."
            record_loss(a)
        else:
            prize = int(room.bet * 2 * 0.95)
            add_coins(winner, prize)
            record_win(winner)
            if a != -1 and b != -1:
                record_loss(b if winner == a else a)
            result = f"🏆 {get_p_name(winner)} برنده شد!\n🪙 جایزه: {prize:,}"
    labels = {"rock": "🗿 سنگ", "paper": "📄 کاغذ", "scissors": "✂️ قیچی"}
    result += f"\n\n{get_p_name(a)}: {labels[m[a]]}\n{get_p_name(b)}: {labels[m[b]]}"
    try:
        await bot.edit_message_text(result, chat_id=room.chat_id, message_id=room.message_id,
                                    reply_markup=main_menu(), parse_mode="Markdown")
    except:
        pass
    remove_room(room)

# ---------------- Tic Tac Toe ----------------

def tic_winner(board):
    combos = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
    for a,b,c in combos:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return None

async def tic_move(bot, room, user_id, pos):
    st = room.game_state
    if st.get("finished") or st["turn"] != user_id or st["board"][pos]:
        return
    mark = "❌" if user_id == room.players[0] else "⭕️"
    st["board"][pos] = mark
    winner = tic_winner(st["board"])
    if winner or all(st["board"]):
        st["finished"] = True
        if winner:
            winner_id = room.players[0] if winner == "❌" else room.players[1]
            prize = int(room.bet * 2 * 0.95)
            if winner_id != -1:
                add_coins(winner_id, prize)
                record_win(winner_id)
            loser = room.players[1] if winner_id == room.players[0] else room.players[0]
            if loser != -1:
                record_loss(loser)
            text = f"🏆 **{get_p_name(winner_id)} برد!**\n🪙 جایزه: {prize:,}"
        else:
            for p in room.players:
                if p != -1:
                    add_coins(p, room.bet)
            text = "🤝 **مساوی! شرط‌ها برگشت.**"
        try:
            await bot.edit_message_text(text, chat_id=room.chat_id, message_id=room.message_id,
                                        reply_markup=main_menu(), parse_mode="Markdown")
        except:
            pass
        remove_room(room)
        return

    st["turn"] = room.players[1] if user_id == room.players[0] else room.players[0]

    # Simple legal PvE response: bot picks a winning move if available, otherwise center/corner/random.
    if room.against_bot and st["turn"] == -1:
        await asyncio.sleep(0.5)
        empty = [i for i, v in enumerate(st["board"]) if not v]
        bot_pos = None
        for i in empty:
            test = st["board"].copy()
            test[i] = "⭕️"
            if tic_winner(test) == "⭕️":
                bot_pos = i
                break
        if bot_pos is None:
            human_mark = "❌"
            for i in empty:
                test = st["board"].copy()
                test[i] = human_mark
                if tic_winner(test) == human_mark:
                    bot_pos = i
                    break
        if bot_pos is None:
            for preferred in [4, 0, 2, 6, 8]:
                if preferred in empty:
                    bot_pos = preferred
                    break
        if bot_pos is None:
            bot_pos = random.choice(empty)
        await tic_move(bot, room, -1, bot_pos)
        return

    text = f"❌⭕️ **دوز**\n\nنوبت: **{get_p_name(st['turn'])}**"
    try:
        await bot.edit_message_text(text, chat_id=room.chat_id, message_id=room.message_id,
                                    reply_markup=tic_keyboard(room), parse_mode="Markdown")
    except:
        pass

# ---------------- Carrot ----------------

async def carrot_eat(bot, room, user_id):
    st = room.game_state
    if st.get("finished") or st["turn"] != user_id: return
    st["scores"][user_id] += random.randint(1, 3)
    if st["scores"][user_id] >= st["target"]:
        await finish_carrot(bot, room)
        return
    st["turn"] = round_robin_next(room.players, user_id)
    text = f"🥕 **هویج‌خوری**\n\nامتیازها:\n" + "\n".join(f"▪️ {get_p_name(p)}: {st['scores'][p]}" for p in room.players) + f"\n\n🎯 نوبت: {get_p_name(st['turn'])}"
    try: await bot.edit_message_text(text, chat_id=room.chat_id, message_id=room.message_id, reply_markup=carrot_keyboard(), parse_mode="Markdown")
    except: pass
    if st["turn"] == -1:
        await asyncio.sleep(.6)
        await bot_carrot_turn(bot, room)

async def bot_carrot_turn(bot, room):
    st = room.game_state
    if st.get("finished") or st["turn"] != -1: return
    st["scores"][-1] += random.randint(2, 4)
    if st["scores"][-1] >= st["target"]:
        await finish_carrot(bot, room); return
    st["turn"] = round_robin_next(room.players, -1)
    await asyncio.sleep(.4)
    text = f"🥕 **هویج‌خوری**\n\nامتیازها:\n" + "\n".join(f"▪️ {get_p_name(p)}: {st['scores'][p]}" for p in room.players) + f"\n\n🎯 نوبت: {get_p_name(st['turn'])}"
    try: await bot.edit_message_text(text, chat_id=room.chat_id, message_id=room.message_id, reply_markup=carrot_keyboard(), parse_mode="Markdown")
    except: pass

async def finish_carrot(bot, room):
    st = room.game_state
    st["finished"] = True
    winner = max(st["scores"], key=st["scores"].get)
    prize = int(room.bet * len(room.players) * .95)
    if winner != -1:
        add_coins(winner, prize); record_win(winner)
    for p in room.players:
        if p != winner and p != -1: record_loss(p)
    text = "🏆 **هویج‌خوری تمام شد!**\n\n" + "\n".join(f"▪️ {get_p_name(p)}: {st['scores'][p]} 🥕" for p in room.players) + f"\n\n🥇 برنده: {get_p_name(winner)}\n🪙 جایزه: {prize:,}"
    try: await bot.edit_message_text(text, chat_id=room.chat_id, message_id=room.message_id, reply_markup=main_menu(), parse_mode="Markdown")
    except: pass
    remove_room(room)

# ---------------- Poker Texas Hold'em ----------------

POKER_SUITS = ["♠️","♥️","♦️","♣️"]
POKER_RANKS = list(range(2,15))

def poker_deck():
    d = [(r,s) for r in POKER_RANKS for s in POKER_SUITS]
    random.shuffle(d)
    return d

def poker_card(card):
    r,s = card
    return f"{'A' if r==14 else {11:'J',12:'Q',13:'K'}.get(r,str(r))}{s}"

def eval_poker5(cards):
    ranks = sorted([r for r,s in cards], reverse=True)
    counts = {r:ranks.count(r) for r in set(ranks)}
    flush = len({s for r,s in cards}) == 1
    uniq = sorted(set(ranks), reverse=True)
    straight_high = None
    if 14 in uniq: uniq.append(1)
    for i in range(len(uniq)-4):
        seq = uniq[i:i+5]
        if seq[0]-seq[4] == 4:
            straight_high = seq[0]; break
    if flush and straight_high: return (8, straight_high)
    fours = sorted([r for r,c in counts.items() if c==4], reverse=True)
    if fours: return (7, fours[0], max(r for r in ranks if r != fours[0]))
    trips = sorted([r for r,c in counts.items() if c==3], reverse=True)
    pairs = sorted([r for r,c in counts.items() if c==2], reverse=True)
    if trips and (pairs or len(trips)>1):
        pair = pairs[0] if pairs else trips[1]
        return (6, trips[0], pair)
    if flush: return (5, *ranks)
    if straight_high: return (4, straight_high)
    if trips: return (3, trips[0], *sorted([r for r in ranks if r!=trips[0]], reverse=True))
    if len(pairs)>=2:
        return (2, pairs[0], pairs[1], max(r for r in ranks if r not in pairs[:2]))
    if len(pairs)==1:
        p=pairs[0]; return (1,p,*sorted([r for r in ranks if r!=p], reverse=True))
    return (0,*ranks)

def best_poker7(cards):
    return max(eval_poker5(c) for c in itertools.combinations(cards,5))

async def poker_action(bot, room, user_id, action):
    st = room.game_state
    if st.get("finished") or st["turn"] != user_id:
        return

    active = [p for p in room.players if p not in st["folded"]]
    if action == "fold":
        st["folded"].add(user_id)
        active = [p for p in room.players if p not in st["folded"]]
        if len(active) == 1:
            winner = active[0]
            if winner != -1:
                prize = int(room.bet * len(room.players) * 0.95)
                add_coins(winner, prize)
                record_win(winner)
            for p in room.players:
                if p != winner and p != -1:
                    record_loss(p)
            text = f"🏆 {get_p_name(winner)} برنده شد!\n🪙 جایزه: {int(room.bet * len(room.players) * 0.95):,}"
            try:
                await bot.edit_message_text(text, chat_id=room.chat_id, message_id=room.message_id,
                                            reply_markup=main_menu(), parse_mode="Markdown")
            except:
                pass
            remove_room(room)
            return

    st["actions_this_round"] += 1
    active = [p for p in room.players if p not in st["folded"]]
    if not active:
        return
    st["turn"] = round_robin_next(active, user_id)

    if st["actions_this_round"] >= len(active):
        st["actions_this_round"] = 0
        if len(st["board"]) == 0:
            st["board"] = [st["deck"].pop() for _ in range(3)]  # Flop
        elif len(st["board"]) < 5:
            st["board"].append(st["deck"].pop())  # Turn, then River
        else:
            scores = {p: best_poker7(st["hands"][p] + st["board"]) for p in active}
            top = max(scores.values())
            winners = [p for p, score in scores.items() if score == top]
            pool = int(room.bet * len(room.players) * .95)
            share = pool // len(winners)
            for p in winners:
                if p != -1:
                    add_coins(p, share)
                    record_win(p)
            for p in room.players:
                if p not in winners and p != -1:
                    record_loss(p)
            text = "🏆 **پایان پوکر**\n\n" + "\n".join(
                f"{get_p_name(p)}: {scores[p]}" for p in scores
            ) + f"\n\n🥇 برنده: {', '.join(get_p_name(p) for p in winners)}"
            try:
                await bot.edit_message_text(text, chat_id=room.chat_id, message_id=room.message_id,
                                            reply_markup=main_menu(), parse_mode="Markdown")
            except:
                pass
            remove_room(room)
            return

    text = f"♠️ **Texas Hold'em**\n\n🃏 میز: {' '.join(poker_card(c) for c in st['board']) or '—'}\n🎯 نوبت: {get_p_name(st['turn'])}"
    try:
        await bot.edit_message_text(text, chat_id=room.chat_id, message_id=room.message_id,
                                    reply_markup=poker_action_keyboard(room), parse_mode="Markdown")
    except:
        pass

    if room.against_bot and st["turn"] == -1:
        await asyncio.sleep(0.7)
        # Basic legal bot strategy: fold weak starting hand occasionally, otherwise check/call.
        hand = st["hands"][-1]
        ranks = sorted([r for r, _ in hand], reverse=True)
        bot_action = "fold" if len(st["board"]) == 0 and ranks[0] < 10 and random.random() < 0.15 else "call"
        await poker_action(bot, room, -1, bot_action)

async def start_poker_room(bot, room):
    d = poker_deck()
    hands = {p: [d.pop(), d.pop()] for p in room.players}
    order = room.players.copy()
    random.shuffle(order)
    room.game_state = {
        "deck": d, "hands": hands, "board": [], "order": order,
        "turn": order[0], "folded": set(), "actions_this_round": 0, "finished": False
    }
    text = f"♠️ **Texas Hold'em**\n\n🎯 نوبت: {get_p_name(order[0])}\n🃏 میز: —"
    try:
        await bot.edit_message_text(text, chat_id=room.chat_id, message_id=room.message_id,
                                    reply_markup=poker_action_keyboard(room), parse_mode="Markdown")
    except:
        pass
    for p in room.players:
        if p != -1:
            try:
                await bot.send_message(p, f"🃏 کارت‌های خصوصی تو:\n{' | '.join(poker_card(c) for c in hands[p])}")
            except:
                pass
    if room.against_bot and room.game_state["turn"] == -1:
        await asyncio.sleep(.7)
        await poker_action(bot, room, -1, "call")

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
# UI
# ============================================================

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🫏 خر من", callback_data="donkey"), InlineKeyboardButton("🎮 شروع بازی", callback_data="games")],
        [InlineKeyboardButton("🏪 فروشگاه", callback_data="shop"), InlineKeyboardButton("🎒 کیف", callback_data="inventory")],
        [InlineKeyboardButton("👤 پروفایل", callback_data="profile"), InlineKeyboardButton("🔊 ایجاد صدا", callback_data="sound_action")],
    ])

def game_mode_keyboard(game_type):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 بازی با بات قوی (PvE)", callback_data="mode_bot")],
        [InlineKeyboardButton("👥 ایجاد اتاق گروهی (PvP)", callback_data="mode_pvp")],
        [InlineKeyboardButton("🔙 لغو", callback_data="home")]
    ])

def room_keyboard(room=None):
    rows = []
    if room and room.game_type == "کارت_31" and BOT_USERNAME:
        url = f"https://t.me/{BOT_USERNAME}?start=31_{room.chat_id}"
        rows.append([InlineKeyboardButton("🃏 ورود به بازی 31", url=url)])
    else:
        rows.append([InlineKeyboardButton("👥 ورود به بازی", callback_data="game_join")])
    rows.append([InlineKeyboardButton("▶️ شروع بازی", callback_data="game_start"),
                 InlineKeyboardButton("❌ لغو", callback_data="game_cancel")])
    return InlineKeyboardMarkup(rows)

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
# CALLBACK HANDLER
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

    if data == "noop":
        return

    if data == "home":
        USER_GAME_SELECTION.pop(user.id, None)
        return await query.edit_message_text("🏠 منوی اصلی طویله:", reply_markup=main_menu())

    if data == "profile":
        return await query.edit_message_text(profile_text(user.id), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="home")]]))
    if data == "donkey":
        return await query.edit_message_text(donkey_text(user.id), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="home")]]))
    if data == "sound_action":
        return await query.edit_message_text(await donkey_sound_system(user.id), reply_markup=main_menu(), parse_mode="Markdown")

    # Crash cashout -- unchanged
    if data.startswith("crashout_"):
        target_user = int(data.split("_")[1])
        if user.id != target_user:
            return await query.answer("⛔ دکمه ماله یکی دیگه‌ست.", show_alert=True)
        session = CRASH_SESSIONS.get(user.id)
        if not session or not session.get("active"):
            return await query.answer("❌ تمام شده!", show_alert=True)
        session["active"] = False
        prize = int(session["bet"] * session["current"])
        add_coins(user.id, prize)
        record_win(user.id)
        return await query.edit_message_text(f"✅ **پرواز موفق! ضریب {session['current']:.2f}x**\n🪙 جایزه شما: **{prize:,}** سکه", reply_markup=main_menu())

    if data == "games":
        rows = [[InlineKeyboardButton(GAME_NAMES[g], callback_data=f"game_{g}")] for g in GAME_NAMES.keys()]
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="home")])
        return await query.edit_message_text("🎮 قمارخونه طویله! یکیو انتخاب کن:", reply_markup=InlineKeyboardMarkup(rows))

    if data.startswith("game_") and data not in ["game_join", "game_start", "game_cancel"]:
        g_type = data[5:]
        USER_GAME_SELECTION[user.id] = {"game": g_type, "step": "waiting_for_bet"}
        return await query.edit_message_text(f"بازی: {GAME_NAMES[g_type]}\n💰 مبلغ شرط رو بفرست:")

    # Crash remains text-driven exactly as before; other games use interactive room engines.
    if data == "mode_bot":
        state = USER_GAME_SELECTION.get(user.id)
        if not state: return
        if not remove_coins(user.id, state["bet"]):
            return await query.edit_message_text("❌ پول کم داری!", reply_markup=main_menu())
        game = state["game"]
        room = GameRoom(game_type=game, chat_id=update.effective_chat.id, creator_id=user.id,
                        bet=state["bet"], against_bot=True, players=[user.id, -1], started=True)
        USER_GAME_SELECTION.pop(user.id, None)
        if game == "لگد_خر":
            ACTIVE_GAMES[str(room.chat_id)] = room
            PLAYER_GAMES[user.id] = str(room.chat_id)
            sent = await query.edit_message_text("🎮 در حال آماده‌سازی لگد خر...")
            room.message_id = sent.message_id
            await start_kick_room(context.bot, room)
            return
        if game == "سنگ_کاغذ_قیچی":
            ACTIVE_GAMES[str(room.chat_id)] = room; PLAYER_GAMES[user.id] = str(room.chat_id)
            room.game_state={"moves":{},"finished":False}
            sent = await query.edit_message_text("✊✋✌️ **انتخابت رو بزن:**", reply_markup=rps_keyboard(room), parse_mode="Markdown")
            room.message_id=sent.message_id
            return
        if game == "دوز":
            ACTIVE_GAMES[str(room.chat_id)] = room; PLAYER_GAMES[user.id] = str(room.chat_id)
            # PvE: bot gets a basic random legal response.
            room.game_state={"board":[None]*9,"turn":user.id,"finished":False}
            sent=await query.edit_message_text("❌⭕️ **دوز**\n\nنوبت تو:",reply_markup=tic_keyboard(room),parse_mode="Markdown")
            room.message_id=sent.message_id
            return
        if game == "هویج_خوری":
            ACTIVE_GAMES[str(room.chat_id)] = room; PLAYER_GAMES[user.id]=str(room.chat_id)
            room.game_state={"scores":{p:0 for p in room.players},"turn":user.id,"target":20,"finished":False}
            sent=await query.edit_message_text("🥕 **هویج‌خوری**\n\nهر نوبت چند هویج می‌خوری؟",reply_markup=carrot_keyboard(),parse_mode="Markdown")
            room.message_id=sent.message_id
            return
        if game == "کارت_31":
            ACTIVE_GAMES[str(room.chat_id)] = room; PLAYER_GAMES[user.id]=str(room.chat_id)
            sent=await query.edit_message_text("🃏 **بازی 31**\n\nکارت‌های خصوصی در PV فرستاده می‌شوند.")
            room.message_id=sent.message_id
            await start_31_room(context.bot, room)
            return
        if game == "پوکر":
            ACTIVE_GAMES[str(room.chat_id)] = room; PLAYER_GAMES[user.id]=str(room.chat_id)
            sent=await query.edit_message_text("♠️ **Texas Hold'em** در حال شروع...")
            room.message_id=sent.message_id
            await start_poker_room(context.bot, room)
            return

    if data == "mode_pvp":
        state = USER_GAME_SELECTION.get(user.id)
        if not state: return
        if get_room(update.effective_chat.id):
            return await query.edit_message_text("❌ یه بازی اینجا بازه.", reply_markup=main_menu())
        if not remove_coins(user.id, state["bet"]):
            return await query.edit_message_text("❌ پول نداری!", reply_markup=main_menu())
        max_p = 5 if state["game"] in ["کارت_31", "لگد_خر", "هویج_خوری", "پوکر"] else 2
        room = GameRoom(game_type=state["game"], chat_id=update.effective_chat.id, creator_id=user.id,
                        bet=state["bet"], max_players=max_p, players=[user.id])
        ACTIVE_GAMES[str(update.effective_chat.id)] = room
        PLAYER_GAMES[user.id] = str(update.effective_chat.id)
        txt = f"🎮 اتاق: {GAME_NAMES[state['game']]}\n💰 شرط: {state['bet']}\n👥 ظرفیت: {max_p} نفر\n\n1. {user.first_name}"
        sent = await query.edit_message_text(txt, reply_markup=room_keyboard(room))
        room.message_id = sent.message_id
        return

    # 31 deep-link users don't use this join callback. This remains for other games.
    if data == "game_join":
        room = get_room(update.effective_chat.id)
        if not room or room.started:
            return await query.answer("❌ در دسترس نیست.", show_alert=True)
        if room.game_type == "کارت_31":
            return await query.answer("🃏 برای 31 از لینک ورود به PV استفاده کن.", show_alert=True)
        if user.id in room.players:
            return await query.answer("قبلا وارد شدی.", show_alert=True)
        if len(room.players) >= room.max_players:
            return await query.answer("ظرفیت پره!", show_alert=True)
        if not remove_coins(user.id, room.bet):
            return await query.answer("پول کم داری!", show_alert=True)
        room.players.append(user.id)
        PLAYER_GAMES[user.id] = str(room.chat_id)
        names = "\n".join([f"{i+1}. {get_user(p)['name']}" for i, p in enumerate(room.players)])
        txt = f"🎮 اتاق: {GAME_NAMES[room.game_type]}\n💰 شرط: {room.bet}\n👥 ظرفیت: {room.max_players} نفر\n\n{names}"
        return await query.edit_message_text(txt, reply_markup=room_keyboard(room))

    # 31 deep-link join
    if data == "31_join":
        return await query.answer("از لینک PV وارد شو.", show_alert=True)

    if data == "game_start":
        room = get_room(update.effective_chat.id)
        if not room or room.creator_id != user.id:
            return await query.answer("فقط سازنده!", show_alert=True)
        if len(room.players) < 2:
            return await query.answer("حداقل ۲ نفر!", show_alert=True)
        room.started = True
        if room.game_type == "لگد_خر":
            await start_kick_room(context.bot, room); return
        if room.game_type == "سنگ_کاغذ_قیچی":
            room.game_state={"moves":{},"finished":False}
            await query.edit_message_text("✊✋✌️ هر دو بازیکن حرکتشان را انتخاب کنند.", reply_markup=rps_keyboard(room))
            room.message_id=query.message.message_id; return
        if room.game_type == "دوز":
            room.game_state={"board":[None]*9,"turn":room.players[0],"finished":False}
            await query.edit_message_text(f"❌⭕️ **دوز**\n\nنوبت: {get_p_name(room.players[0])}",reply_markup=tic_keyboard(room),parse_mode="Markdown")
            room.message_id=query.message.message_id; return
        if room.game_type == "هویج_خوری":
            room.game_state={"scores":{p:0 for p in room.players},"turn":room.players[0],"target":20,"finished":False}
            await query.edit_message_text(f"🥕 **هویج‌خوری**\n\nنوبت: {get_p_name(room.players[0])}",reply_markup=carrot_keyboard(),parse_mode="Markdown")
            room.message_id=query.message.message_id; return
        if room.game_type == "کارت_31":
            await query.edit_message_text("🃏 بازی 31 شروع شد. کارت‌های هر بازیکن به PV او ارسال می‌شود.")
            room.message_id=query.message.message_id
            await start_31_room(context.bot, room); return
        if room.game_type == "پوکر":
            await query.edit_message_text("♠️ پوکر شروع شد.")
            room.message_id=query.message.message_id
            await start_poker_room(context.bot, room); return

    if data == "game_cancel":
        room = get_room(update.effective_chat.id)
        if not room or room.creator_id != user.id:
            return await query.answer("فقط سازنده!", show_alert=True)
        for p in room.players:
            add_coins(p, room.bet)
        remove_room(room)
        return await query.edit_message_text("❌ لغو شد.", reply_markup=main_menu())

    # Kick
    if data.startswith("kick_target_"):
        room=get_room(update.effective_chat.id)
        if not room or room.game_type!="لگد_خر": return
        if room.game_state.get("turn") != user.id: return await query.answer("نوبت تو نیست.",show_alert=True)
        target=int(data.split("_")[-1])
        if target not in room.game_state["alive"] or target==user.id: return
        success=random.random()<0.60
        await finish_kick_round(context.bot,room,user.id,target,success)
        return
    if data=="kick_status":
        room=get_room(update.effective_chat.id)
        if room: return await query.answer(kick_status_text(room).replace("*","")[:180],show_alert=True)

    # RPS
    if data in ("rps_rock","rps_paper","rps_scissors"):
        room=get_room(update.effective_chat.id)
        if not room or room.game_type!="سنگ_کاغذ_قیچی": return
        move={"rps_rock":"rock","rps_paper":"paper","rps_scissors":"scissors"}[data]
        await rps_move(context.bot,room,user.id,move); return

    # Tic
    if data.startswith("tic_"):
        room=get_room(update.effective_chat.id)
        if not room or room.game_type!="دوز": return
        await tic_move(context.bot,room,user.id,int(data.split("_")[1])); return

    # Carrot
    if data=="carrot_eat":
        room=get_room(update.effective_chat.id)
        if not room or room.game_type!="هویج_خوری": return
        await carrot_eat(context.bot,room,user.id); return

    # 31
    if data.startswith("31_swap_"):
        room = PLAYER_GAMES.get(user.id) and get_room(PLAYER_GAMES[user.id])
        if not room or room.game_type!="کارت_31": return
        st=room.game_state
        if st.get("turn")!=user.id: return await query.answer("نوبت تو نیست.",show_alert=True)
        _,_,ti,hi=data.split("_")
        ti,hi=int(ti),int(hi)
        st["table"][ti], st["hands"][user.id][hi] = st["hands"][user.id][hi], st["table"][ti]
        if r31_score(st["hands"][user.id])==31:
            await finish_31(context.bot,room,user.id); return
        await advance_31(context.bot,room); return
    if data=="31_pass":
        room=PLAYER_GAMES.get(user.id) and get_room(PLAYER_GAMES[user.id])
        if not room or room.game_type!="کارت_31": return
        if room.game_state.get("turn")!=user.id: return await query.answer("نوبت تو نیست.",show_alert=True)
        await advance_31(context.bot,room); return
    if data=="31_stop":
        room=PLAYER_GAMES.get(user.id) and get_room(PLAYER_GAMES[user.id])
        if not room or room.game_type!="کارت_31": return
        st=room.game_state
        if st.get("turn")!=user.id: return await query.answer("نوبت تو نیست.",show_alert=True)
        st["stopped_by"]=user.id
        await advance_31(context.bot,room); return

    # Poker
    if data in ("poker_check","poker_call","poker_raise","poker_fold"):
        room=get_room(update.effective_chat.id)
        if not room or room.game_type!="پوکر": return
        action={"poker_check":"check","poker_call":"call","poker_raise":"raise","poker_fold":"fold"}[data]
        await poker_action(context.bot,room,user.id,action); return

# ============================================================
# TEXT HANDLER
# ============================================================

async def general_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()
    ensure_user(user.id, user.first_name)

    u_data = get_user(user.id)
    if u_data and u_data["is_banned"] == 1: return

    # Deep-link /start for 31
    if text.startswith("/start"):
        payload = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""
        if payload.startswith("31_"):
            try:
                chat_id=int(payload[3:])
            except:
                return await update.message.reply_text("❌ لینک بازی نامعتبر است.")
            room=get_room(chat_id)
            if not room or room.game_type!="کارت_31":
                return await update.message.reply_text("❌ این اتاق دیگر فعال نیست.")
            if room.started:
                return await update.message.reply_text("❌ بازی شروع شده و ورود جدید بسته است.")
            if user.id in room.players:
                return await update.message.reply_text("✅ تو از قبل وارد اتاق شدی. منتظر شروع بازی باش.")
            if len(room.players)>=room.max_players:
                return await update.message.reply_text("❌ ظرفیت اتاق پر شده.")
            if not remove_coins(user.id,room.bet):
                return await update.message.reply_text("❌ سکه کافی نداری.")
            room.players.append(user.id)
            PLAYER_GAMES[user.id]=str(chat_id)
            await update.message.reply_text(
                f"✅ وارد بازی 31 شدی!\n💰 شرط: {room.bet:,} 🪙\n👥 بازیکنان: {len(room.players)}/{room.max_players}\n\nوقتی سازنده بازی را شروع کند، کارت‌ها همین‌جا در PV برایت می‌آیند."
            )
            try:
                names="\n".join(f"{i+1}. {get_user(p)['name']}" for i,p in enumerate(room.players))
                await context.bot.edit_message_text(
                    f"🎮 اتاق: {GAME_NAMES['کارت_31']}\n💰 شرط: {room.bet}\n👥 ظرفیت: {room.max_players} نفر\n\n{names}",
                    chat_id=room.chat_id,message_id=room.message_id,reply_markup=room_keyboard(room)
                )
            except: pass
            return
        USER_GAME_SELECTION.pop(user.id,None)
        return await update.message.reply_text("🫏 **خوش اومدی به طویله خرستان!** از منو انتخاب کن:", reply_markup=main_menu())

    # Admin panel
    if user.id == OWNER_ID and text.startswith(("/", "بن", "انبن", "سکه", "کسر", "+سکه", "-سکه")):
        if not update.message.reply_to_message:
            parts=text.split(); cmd=parts[0].lower()
            if cmd in ["/ban","بن","/unban","انبن","/addcoin","سکه","+سکه","/remcoin","کسر","-سکه"]:
                await update.message.reply_text("⚠️ ارباب، باید روی پیام کسی که می‌خوای عملیات روش انجام بشه **ریپلی (Reply)** بزنی!")
                return
        else:
            target_user=update.message.reply_to_message.from_user
            target_id=target_user.id; parts=text.split(); cmd=parts[0].lower()
            if cmd in ["/ban","بن"]:
                with closing(db_connect()) as db:
                    db.execute("UPDATE users SET is_banned=1 WHERE user_id=?",(target_id,)); db.commit()
                await update.message.reply_text(f"✅ کاربر {target_user.first_name} بن شد! 🐴🦶"); return
            if cmd in ["/unban","انبن"]:
                with closing(db_connect()) as db:
                    db.execute("UPDATE users SET is_banned=0 WHERE user_id=?",(target_id,)); db.commit()
                await update.message.reply_text(f"✅ کاربر {target_user.first_name} آنبن شد! 🐎"); return
            if cmd in ["/addcoin","سکه","+سکه"] and len(parts)>1:
                try:
                    amt=int(parts[1]); add_coins(target_id,amt)
                    await update.message.reply_text(f"💰 مبلغ {amt:,} سکه به حساب {target_user.first_name} واریز شد! 👑")
                except ValueError: pass
                return
            if cmd in ["/remcoin","کسر","-سکه"] and len(parts)>1:
                try:
                    amt=int(parts[1])
                    with closing(db_connect()) as db:
                        db.execute("UPDATE users SET coins=MAX(0,coins-?) WHERE user_id=?",(amt,target_id)); db.commit()
                    await update.message.reply_text(f"🔥 مبلغ {amt:,} سکه از حساب {target_user.first_name} کسر شد! 😡")
                except ValueError: pass
                return

    state=USER_GAME_SELECTION.get(user.id)
    if state and state.get("step")=="waiting_for_bet":
        if text.isdigit():
            bet=int(text)
            if bet<MIN_BET: return await update.message.reply_text(f"حداقل شرط {MIN_BET}!")
            if u_data['coins']<bet: return await update.message.reply_text("پول نداری!")
            if state["game"]=="انفجار":
                remove_coins(user.id,bet)
                r=random.random(); c_point=max(1.00,0.95/r)
                if c_point>40.0: c_point=40.0
                CRASH_SESSIONS[user.id]={"active":True,"bet":bet,"current":1.00,"crash_point":c_point}
                msg=f"💥 **بازی زنده انفجار**\n💰 شرط: {bet} 🪙\n\n📈 ضریب: **1.00x**"
                btn=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 برداشت",callback_data=f"crashout_{user.id}")]])
                sent=await update.message.reply_text(msg,reply_markup=btn)
                asyncio.create_task(run_crash_task(context.bot,update.effective_chat.id,sent.message_id,user.id,CRASH_SESSIONS[user.id]))
                USER_GAME_SELECTION.pop(user.id,None); return
            USER_GAME_SELECTION[user.id]["bet"]=bet
            USER_GAME_SELECTION[user.id]["step"]="ready_for_mode"
            return await update.message.reply_text(f"بازی: {GAME_NAMES[state['game']]}\nشرط: {bet} 🪙\n\nحالت رو انتخاب کن:",reply_markup=game_mode_keyboard(state["game"]))

# ============================================================
# MAIN
# ============================================================

async def post_init(application):
    global BOT_USERNAME
    me=await application.bot.get_me()
    BOT_USERNAME=me.username or ""

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set")
        return
    init_db()
    app=Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, general_text_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__=="__main__":
    main()
