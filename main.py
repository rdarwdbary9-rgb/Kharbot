import os
import sqlite3
import time
import random
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
# CONFIGURATION
# =========================================================

CONFIG = {
    "BOT_TOKEN": os.getenv("BOT_TOKEN"),
    "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY"),
    "ADMIN_ID": int(os.getenv("ADMIN_ID", "0")),
    "DB_PATH": os.getenv("DB_PATH", "/tmp/kharbot.db"),
    "ARR_SCORE": 10,
    "ARR_COOLDOWN": 30,
    "DAILY_SCORE": 100,
}

TOKEN = CONFIG["BOT_TOKEN"]
OPENROUTER_API_KEY = CONFIG["OPENROUTER_API_KEY"]
ADMIN_ID = CONFIG["ADMIN_ID"]
DB_PATH = CONFIG["DB_PATH"]
ARR_SCORE = CONFIG["ARR_SCORE"]
ARR_COOLDOWN = CONFIG["ARR_COOLDOWN"]
DAILY_SCORE = CONFIG["DAILY_SCORE"]

# =========================================================
# AI SETTINGS (OpenRouter - Llama 3 Free)
# =========================================================

ai_client = None
if OPENROUTER_API_KEY:
    ai_client = AsyncOpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1"
    )

SYSTEM_INSTRUCTION = "تو 'خر‌بات' هستی؛ یک هوش مصنوعی بسیار بامزه، طنز و شوخ‌طبع. لحن صمیمی و باکل‌کل داشته باش."

async def ask_ai(prompt: str) -> str:
    if not ai_client: 
        return "🫏 کلید OPENROUTER_API_KEY در تنظیمات بلمو ست نشده است!"
    try:
        response = await ai_client.chat.completions.create(
            model="meta-llama/llama-3.3-70b-instruct:free",
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"OpenRouter AI Error: {e}")
        return "🫏 ای بابا، مخم هنگ کرد! چند لحظه دیگه دوباره بپرس."

# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    score INTEGER DEFAULT 0,
    last_daily INTEGER DEFAULT 0,
    pending_game TEXT DEFAULT '',
    title TEXT DEFAULT '',
    q_arr_count INTEGER DEFAULT 0,
    q_game_count INTEGER DEFAULT 0,
    q_ai_count INTEGER DEFAULT 0,
    q_last_reset TEXT DEFAULT ''
)
""")
db.commit()

for col, col_type in [
    ("pending_game", "TEXT DEFAULT ''"),
    ("title", "TEXT DEFAULT ''"),
    ("q_arr_count", "INTEGER DEFAULT 0"),
    ("q_game_count", "INTEGER DEFAULT 0"),
    ("q_ai_count", "INTEGER DEFAULT 0"),
    ("q_last_reset", "TEXT DEFAULT ''")
]:
    try:
        cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        db.commit()
    except Exception:
        pass

cursor.execute("""
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    item_id TEXT,
    item_name TEXT,
    quantity INTEGER DEFAULT 1
)
""")
db.commit()

# =========================================================
# USER SYSTEM & QUESTS
# =========================================================

def create_user(user):
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT user_id, q_last_reset FROM users WHERE user_id = ?", (user.id,))
    row = cursor.fetchone()
    
    if row is None:
        cursor.execute(
            "INSERT INTO users (user_id, username, first_name, q_last_reset) VALUES (?, ?, ?, ?)",
            (user.id, user.username or "", user.first_name or "Player", today)
        )
    else:
        cursor.execute("UPDATE users SET username = ?, first_name = ? WHERE user_id = ?", (user.username or "", user.first_name or "Player", user.id))
        if row[1] != today:
            cursor.execute(
                "UPDATE users SET q_arr_count = 0, q_game_count = 0, q_ai_count = 0, q_last_reset = ? WHERE user_id = ?",
                (today, user.id)
            )
    db.commit()

def get_score(user_id):
    cursor.execute("SELECT score FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    return res[0] if res else 0

def add_score(user_id, amount):
    cursor.execute("UPDATE users SET score = score + ? WHERE user_id = ?", (amount, user_id))
    db.commit()

def remove_score(user_id, amount):
    cursor.execute("UPDATE users SET score = score - ? WHERE user_id = ?", (amount, user_id))
    db.commit()

def update_quest(user_id, q_type):
    if q_type == "arr":
        cursor.execute("UPDATE users SET q_arr_count = q_arr_count + 1 WHERE user_id = ?", (user_id,))
    elif q_type == "game":
        cursor.execute("UPDATE users SET q_game_count = q_game_count + 1 WHERE user_id = ?", (user_id,))
    elif q_type == "ai":
        cursor.execute("UPDATE users SET q_ai_count = q_ai_count + 1 WHERE user_id = ?", (user_id,))
    db.commit()

def set_pending_game(user_id, game_name):
    cursor.execute("UPDATE users SET pending_game = ? WHERE user_id = ?", (game_name, user_id))
    db.commit()

def get_pending_game(user_id):
    cursor.execute("SELECT pending_game FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    return res[0] if res else ""

# =========================================================
# MENUS & STORE
# =========================================================

def main_menu(user_id=0):
    keyboard = [
        [InlineKeyboardButton("👤 پروفایل", callback_data="profile"), InlineKeyboardButton("💰 موجودی", callback_data="balance")],
        [InlineKeyboardButton("🎮 بازی‌ها", callback_data="games"), InlineKeyboardButton("🛍️ فروشگاه", callback_data="store")],
        [InlineKeyboardButton("🎯 ماموریت‌ها", callback_data="quests"), InlineKeyboardButton("🎒 انبار من", callback_data="inventory")],
        [InlineKeyboardButton("🎁 جایزه روزانه", callback_data="daily"), InlineKeyboardButton("📖 راهنما", callback_data="help")]
    ]
    if user_id == ADMIN_ID and ADMIN_ID != 0:
        keyboard.append([InlineKeyboardButton("👑 پنل مدیریت مالک", callback_data="admin_panel")])
        
    return InlineKeyboardMarkup(keyboard)

STORE_ITEMS = {
    "title_king": {"name": "👑 لقب: سلطان طویله", "price": 2000, "type": "title", "val": "👑 سلطان طویله"},
    "title_boss": {"name": "🔥 لقب: خرِ بزرگ", "price": 1000, "type": "title", "val": "🔥 خرِ بزرگ"},
    "title_legend": {"name": "🌟 لقب: اسطوره یونجه", "price": 5000, "type": "title", "val": "🌟 اسطوره یونجه"},
    "item_luck": {"name": "🎲 کارت شانس", "price": 300, "type": "item", "val": "item_luck"},
    "item_boost": {"name": "⚡ طلسم دوبرابر کننده", "price": 800, "type": "item", "val": "item_boost"},
}

def store_menu():
    keyboard = []
    for item_id, item in STORE_ITEMS.items():
        keyboard.append([InlineKeyboardButton(f"{item['name']} — {item['price']} 🫏", callback_data=f"buy_{item_id}")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

# =========================================================
# COMMANDS & OWNER HANDLERS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user: create_user(user)
    await update.message.reply_text("🫏 **خر‌بات**\n\nبه قلمرو خرها خوش اومدی! 😂", reply_markup=main_menu(user.id if user else 0))

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    create_user(user)

    cursor.execute("SELECT title FROM users WHERE user_id = ?", (user.id,))
    row = cursor.fetchone()
    title = row[0] if (row and row[0]) else ("👑 مالک / اونر" if user.id == ADMIN_ID else "🫏 خرِ معمولی")

    text = (
        f"👤 **پروفایل کاربری**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏷️ **لقب:** {title}\n"
        f"📝 **نام:** {user.first_name}\n"
        f"🆔 **آیدی عددی:** `{user.id}`\n"
        f"💰 **موجودی:** **{get_score(user.id)}** 🫏 پوینت\n"
    )
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=main_menu(user.id))
    else: await update.message.reply_text(text, reply_markup=main_menu(user.id))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 **راهنمای جامع خر‌بات**\n"
        "━━━━━━━━━━━━━━━\n"
        "🤖 **هوش مصنوعی:**\n"
        "برای چت با هوش مصنوعی کافیست پیام خود را با کلمه **«خر»** شروع کنید.\n"
        "مثال: `خر چطوری؟` یا `خر یک داستان بگو`\n\n"
        "🎮 **بازی‌های گروهی و انفرادی:**\n"
        "• ارسال کلمه `انفجار` ➔ شروع بازی انفجار شرطی\n"
        "• ارسال کلمه `سنگ` ➔ سنگ کاغذ قیچی (با بات یا بقیه)\n"
        "• ارسال کلمه `دوز` ➔ بازی دوز (با بات یا بقیه)\n"
        "• ارسال کلمه `خرینه` ➔ شروع لابی بازی خرینه\n\n"
        "💰 **سیستم پوینت و امتیاز:**\n"
        "• ارسال کلمه `عر` ➔ دریافت پوینت رایگان (هر ۳۰ ثانیه)\n"
        "• ریپلی روی پیام کسی + `بده 50` ➔ انتقال ۵۰ پوینت به او\n"
        "• `/daily` یا دکمه جایزه ➔ دریافت ۱۰۰ پوینت روزانه\n\n"
        "🎯 **فروشگاه و انبار:**\n"
        "• `/store` ➔ خرید لقب و آیتم‌های شانس\n"
        "• `/inventory` ➔ مشاهده انبار و کیف پول\n"
        "• `/quests` ➔ مشاهده و انجام ماموریت‌های روزانه"
    )
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=main_menu(update.effective_user.id if update.effective_user else 0))
    else: await update.message.reply_text(text)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما دسترسی به این بخش را ندارید!")
        return

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    text = (
        f"👑 **پنل مدیریت اختصاصی مالکان**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 **تعداد کل کاربران:** {total_users}\n\n"
        f"🛠️ **دستورات مدیریتی:**\n"
        f"🔹 **افزایش سکه کاربر:**\n"
        f"`/addcoin [آیدی_عددی] [تعداد]`\n"
        f"مثال: `/addcoin 12345678 1000`\n\n"
        f"🔹 **کاهش سکه کاربر:**\n"
        f"`/removecoin [آیدی_عددی] [تعداد]`\n"
    )
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=main_menu(user.id))
    else: await update.message.reply_text(text)

async def admin_add_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID: return

    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        add_score(target_id, amount)
        await update.message.reply_text(f"✅ مقدار **{amount}** پوینت با موفقیت به آیدی `{target_id}` اضافه شد.")
    except Exception:
        await update.message.reply_text("❌ فرمت اشتباه است!\nمثال: `/addcoin 12345678 1000`")

async def admin_remove_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID: return

    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        remove_score(target_id, amount)
        await update.message.reply_text(f"✅ مقدار **{amount}** پوینت با موفقیت از آیدی `{target_id}` کم شد.")
    except Exception:
        await update.message.reply_text("❌ فرمت اشتباه است!\nمثال: `/removecoin 12345678 500`")
# =========================================================
# 💥 CRASH GAME (انفجار)
# =========================================================

active_crash_games = {}

def generate_crash_multiplier():
    rand = random.random()
    if rand < 0.25: return 1
    return min(int(2 + random.expovariate(0.3)), 30)

async def start_crash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    create_user(user)

    try: bet = int(context.args[0])
    except Exception: return

    if bet < 1 or get_score(user.id) < bet:
        await update.message.reply_text("❌ شرط باید حداقل ۱ پوینت باشد و موجودی کافی نداری!")
        return

    remove_score(user.id, bet)
    crash_point = generate_crash_multiplier()
    active_crash_games[user.id] = {"bet": bet, "crash_point": crash_point, "current_multiplier": 1}

    if crash_point == 1:
        del active_crash_games[user.id]
        await update.message.reply_text(f"💥 **بـومم! همون قدم اول (1x) منفجر شد!**\n💀 باختید: -{bet} پوینت")
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📈 افزایش ضریب (+1)", callback_data="crash_next"),
        InlineKeyboardButton("💰 برداشت پوینت", callback_data="crash_cashout")
    ]])

    await update.message.reply_text(f"🚀 **بازی انفجار شروع شد!**\n💵 شرط: **{bet}** | 📈 ضریب: **1x**", reply_markup=keyboard)

async def crash_next_step(query):
    user = query.from_user
    game = active_crash_games.get(user.id)
    if not game: return

    bet, crash_point = game["bet"], game["crash_point"]
    next_mult = game["current_multiplier"] + 1

    if next_mult >= crash_point:
        del active_crash_games[user.id]
        await query.answer("💥 بـومم! منفجر شد!", show_alert=True)
        await query.edit_message_text(f"💥 **بـومم! روی ضریب {crash_point}x منفجر شد!**\n💀 باختید: -{bet} پوینت")
        return

    game["current_multiplier"] = next_mult
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📈 افزایش ضریب (+1)", callback_data="crash_next"),
        InlineKeyboardButton("💰 برداشت پوینت", callback_data="crash_cashout")
    ]])
    await query.answer()
    await query.edit_message_text(f"🚀 **ضریب بالا رفت!**\n💵 شرط: **{bet}** | 📈 ضریب: **{next_mult}x**\n💰 سود: **{bet * next_mult}**", reply_markup=keyboard)

async def crash_cashout(query):
    user = query.from_user
    game = active_crash_games.get(user.id)
    if not game: return

    win_amount = game["bet"] * game["current_multiplier"]
    add_score(user.id, win_amount)
    del active_crash_games[user.id]

    await query.answer("🎉 برداشت موفق!", show_alert=True)
    await query.edit_message_text(f"✅ **برداشت موفق!**\n🎁 دریافت شد: **+{win_amount}** 🫏")

# =========================================================
# 🪨📄✂️ RPS GAME (سنگ کاغذ قیچی)
# =========================================================

active_group_rps = {}
RPS_CHOICES = {"stone": "🪨 سنگ", "paper": "📄 کاغذ", "scissors": "✂️ قیچی"}

def rps_winner(p1, p2):
    if p1 == p2: return "draw"
    if (p1 == "stone" and p2 == "scissors") or (p1 == "paper" and p2 == "stone") or (p1 == "scissors" and p2 == "paper"):
        return "p1"
    return "p2"

async def start_rps_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    create_user(user)

    try: bet = int(context.args[0])
    except Exception: return

    if bet < 1 or get_score(user.id) < bet:
        await update.message.reply_text("❌ شرط باید حداقل ۱ پوینت باشد و موجودی کافی نداری!")
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🤖 بازی با خر‌بات", callback_data=f"rps_bot_{bet}"),
        InlineKeyboardButton("👥 چالش در گروه", callback_data=f"rps_pvp_{bet}")
    ]])
    await update.message.reply_text(f"🪨📄✂️ **سنگ کاغذ قیچی شرطی**\n💵 شرط: **{bet}** پوینت", reply_markup=keyboard)

async def play_rps_bot_choice(query, bet, user_choice):
    user = query.from_user
    bot_choice = random.choice(list(RPS_CHOICES.keys()))
    res = rps_winner(user_choice, bot_choice)

    if res == "p1":
        add_score(user.id, bet)
        msg = f"🎉 **بردی!** (+{bet} پوینت)"
    elif res == "p2":
        remove_score(user.id, bet)
        msg = f"💀 **خر‌بات برد!** (-{bet} پوینت)"
    else:
        msg = "🤝 **مساوی شد!**"

    await query.edit_message_text(f"👤 تو: {RPS_CHOICES[user_choice]}\n🤖 خر‌بات: {RPS_CHOICES[bot_choice]}\n\n{msg}\n💰 موجودی: **{get_score(user.id)}**")

async def start_rps_pvp(query, bet):
    chat, user = query.message.chat, query.from_user
    if chat.type == "private":
        await query.answer("⚠️ چالش فقط در گروه!", show_alert=True)
        return

    game_id = f"{chat.id}_{int(time.time())}"
    active_group_rps[game_id] = {
        "p1_id": user.id, "p1_name": user.first_name, "p1_choice": None,
        "p2_id": None, "p2_name": None, "p2_choice": None, "bet": bet
    }
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⚔️ قبول چالش!", callback_data=f"rps_accept_{game_id}")]])
    await query.edit_message_text(f"⚔️ **چالش سنگ کاغذ قیچی!**\n👤 **{user.first_name}** | 💵 شرط: **{bet}**", reply_markup=keyboard)

async def accept_rps_pvp(query, game_id):
    user = query.from_user
    game = active_group_rps.get(game_id)
    if not game or user.id == game["p1_id"] or get_score(user.id) < game["bet"]: return

    game["p2_id"], game["p2_name"] = user.id, user.first_name
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🪨 سنگ", callback_data=f"rps_play_{game_id}_stone"),
        InlineKeyboardButton("📄 کاغذ", callback_data=f"rps_play_{game_id}_paper"),
        InlineKeyboardButton("✂️ قیچی", callback_data=f"rps_play_{game_id}_scissors")
    ]])
    await query.edit_message_text(f"🎮 **مسابقه شروع شد!**\n⚔️ **{game['p1_name']}** VS **{game['p2_name']}**\nانتخاب کنید:", reply_markup=keyboard)

async def play_rps_pvp_choice(query, game_id, choice):
    user = query.from_user
    game = active_group_rps.get(game_id)
    if not game or user.id not in [game["p1_id"], game["p2_id"]]: return

    if user.id == game["p1_id"]: game["p1_choice"] = choice
    else: game["p2_choice"] = choice

    if not game["p1_choice"] or not game["p2_choice"]:
        await query.answer("✅ انتخابت ثبت شد!")
        return

    res = rps_winner(game["p1_choice"], game["p2_choice"])
    bet = game["bet"]
    if res == "p1":
        add_score(game["p1_id"], bet); remove_score(game["p2_id"], bet)
        win_msg = f"🎉 **{game['p1_name']} برنده شد!**"
    elif res == "p2":
        add_score(game["p2_id"], bet); remove_score(game["p1_id"], bet)
        win_msg = f"🎉 **{game['p2_name']} برنده شد!**"
    else:
        win_msg = "🤝 **مساوی شد!**"

    del active_group_rps[game_id]
    await query.edit_message_text(f"🏆 **نتیجه:**\n👤 {game['p1_name']}: {RPS_CHOICES[game['p1_choice']]}\n👤 {game['p2_name']}: {RPS_CHOICES[game['p2_choice']]}\n\n{win_msg}")

# =========================================================
# ❌⭕ TIC-TAC-TOE (دوز)
# =========================================================

active_ttt_games = {}

def check_ttt_winner(board):
    lines = [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]]
    for a, b, c in lines:
        if board[a] and board[a] == board[b] == board[c]: return board[a]
    if "" not in board: return "draw"
    return None

def render_ttt_board(game_id, board):
    keyboard = []
    for i in range(0, 9, 3):
        row = []
        for j in range(i, i + 3):
            text = board[j] if board[j] != "" else "◽"
            row.append(InlineKeyboardButton(text, callback_data=f"ttt_move_{game_id}_{j}"))
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

async def start_ttt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    create_user(user)

    try: bet = int(context.args[0])
    except Exception: return

    if bet < 1 or get_score(user.id) < bet:
        await update.message.reply_text("❌ شرط باید حداقل ۱ پوینت باشد و موجودی کافی نداری!")
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🤖 بازی با خر‌بات", callback_data=f"ttt_bot_{bet}"),
        InlineKeyboardButton("👥 چالش در گروه", callback_data=f"ttt_pvp_{bet}")
    ]])
    await update.message.reply_text(f"❌⭕ **بازی دوز شرطی**\n💵 شرط: **{bet}** پوینت", reply_markup=keyboard)

async def start_ttt_bot(query, bet):
    user = query.from_user
    game_id = f"bot_{user.id}_{int(time.time())}"
    active_ttt_games[game_id] = {
        "mode": "bot", "user_id": user.id, "bet": bet, "board": [""] * 9,
        "user_symbol": "❌", "bot_symbol": "⭕"
    }
    await query.edit_message_text(f"🤖 **دوز با خر‌بات**\n💵 شرط: **{bet}**\nنوبت شماست:", reply_markup=render_ttt_board(game_id, active_ttt_games[game_id]["board"]))

async def handle_ttt_bot_move(query, game_id, pos):
    user = query.from_user
    game = active_ttt_games.get(game_id)
    if not game or game["board"][pos] != "": return

    game["board"][pos] = game["user_symbol"]
    winner = check_ttt_winner(game["board"])
    if winner:
        await finish_ttt_game(query, game_id, winner)
        return

    empty = [i for i, val in enumerate(game["board"]) if val == ""]
    if empty:
        game["board"][random.choice(empty)] = game["bot_symbol"]
        winner = check_ttt_winner(game["board"])
        if winner:
            await finish_ttt_game(query, game_id, winner)
            return

    await query.edit_message_text(f"🤖 **دوز با خر‌بات**\n💵 شرط: **{game['bet']}**\nنوبت شماست:", reply_markup=render_ttt_board(game_id, game["board"]))

async def start_ttt_pvp(query, bet):
    chat, user = query.message.chat, query.from_user
    if chat.type == "private": return

    game_id = f"pvp_{chat.id}_{int(time.time())}"
    active_ttt_games[game_id] = {
        "mode": "pvp", "p1_id": user.id, "p1_name": user.first_name, "p1_symbol": "❌",
        "p2_id": None, "p2_name": None, "p2_symbol": "⭕", "bet": bet, "board": [""] * 9,
        "turn_id": user.id, "state": "waiting"
    }
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⚔️ قبول چالش دوز!", callback_data=f"ttt_accept_{game_id}")]])
    await query.edit_message_text(f"⚔️ **چالش دوز!**\n👤 **{user.first_name}** (❌) | 💵 شرط: **{bet}**", reply_markup=keyboard)

async def accept_ttt_pvp(query, game_id):
    user = query.from_user
    game = active_ttt_games.get(game_id)
    if not game or user.id == game["p1_id"] or get_score(user.id) < game["bet"]: return

    game["p2_id"], game["p2_name"], game["state"] = user.id, user.first_name, "playing"
    await query.edit_message_text(f"❌⭕ **مسابقه شروع شد!**\n❌ **{game['p1_name']}** VS ⭕ **{game['p2_name']}**\n👉 نوبت: **{game['p1_name']}**", reply_markup=render_ttt_board(game_id, game["board"]))

async def handle_ttt_pvp_move(query, game_id, pos):
    user = query.from_user
    game = active_ttt_games.get(game_id)
    if not game or user.id != game["turn_id"] or game["board"][pos] != "": return

    symbol = game["p1_symbol"] if user.id == game["p1_id"] else game["p2_symbol"]
    game["board"][pos] = symbol
    winner = check_ttt_winner(game["board"])

    if winner:
        await finish_ttt_game(query, game_id, winner)
        return

    game["turn_id"] = game["p2_id"] if user.id == game["p1_id"] else game["p1_id"]
    next_name = game["p2_name"] if user.id == game["p1_id"] else game["p1_name"]
    await query.edit_message_text(f"❌⭕ **دوز در جریان...**\n👉 نوبت: **{next_name}**", reply_markup=render_ttt_board(game_id, game["board"]))

async def finish_ttt_game(query, game_id, winner):
    game = active_ttt_games.get(game_id)
    if not game: return
    bet = game["bet"]

    if game["mode"] == "bot":
        uid = game["user_id"]
        if winner == game["user_symbol"]: add_score(uid, bet); text = f"🎉 **بردی!** (+{bet})"
        elif winner == game["bot_symbol"]: remove_score(uid, bet); text = f"💀 **باختی!** (-{bet})"
        else: text = "🤝 **مساوی!**"
        del active_ttt_games[game_id]
        await query.edit_message_text(f"🏁 **پایان دوز**\n{text}\n💰 موجودی: **{get_score(uid)}**", reply_markup=render_ttt_board("fin", game["board"]))
    else:
        p1, p2 = game["p1_id"], game["p2_id"]
        if winner == "❌": add_score(p1, bet); remove_score(p2, bet); text = f"🎉 **{game['p1_name']} برنده شد!**"
        elif winner == "⭕": add_score(p2, bet); remove_score(p1, bet); text = f"🎉 **{game['p2_name']} برنده شد!**"
        else: text = "🤝 **مساوی!**"
        del active_ttt_games[game_id]
        await query.edit_message_text(f"🏁 **پایان دوز دو نفره**\n{text}", reply_markup=render_ttt_board("fin", game["board"]))

# =========================================================
# 🫏 KHARINE GAME (خرینه)
# =========================================================

kharine_games = {}

def kharine_lobby_keyboard(chat_id, bot_username):
    join_url = f"https://t.me/{bot_username}?start=join_{chat_id}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🫏 ورود به بازی (در پیوی)", url=join_url)],
        [InlineKeyboardButton("🚀 شروع بازی", callback_data=f"khstart:{chat_id}")]
    ])

def kharine_lobby_text(game):
    text = "🫏 **خرینه**\n\n👥 بازیکنان:\n"
    for i, p in enumerate(game["players"].values(), 1): text += f"{i}. {p['name']}\n"
    text += f"\n👥 تعداد: {len(game['players'])}/8"
    return text

async def cancel_kharine_lobby(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    game = kharine_games.get(chat_id)
    if game and game.get("state") == "lobby":
        del kharine_games[chat_id]
        await context.bot.send_message(chat_id=chat_id, text="⏰ **لابی خرینه لغو شد.**")

async def start_kharine(update, context):
    chat, user = update.effective_chat, update.effective_user
    if not chat or chat.type == "private" or chat.id in kharine_games: return

    create_user(user)
    bot_username = (await context.bot.get_me()).username
    
    timeout_job = None
    if context.job_queue:
        timeout_job = context.job_queue.run_once(cancel_kharine_lobby, 120, data=chat.id)

    kharine_games[chat.id] = {
        "players": {user.id: {"name": user.first_name, "username": user.username or "", "role": None, "alive": True}},
        "state": "lobby", "day": 0, "message_id": None, "timeout_job": timeout_job
    }
    msg = await update.message.reply_text(kharine_lobby_text(kharine_games[chat.id]), reply_markup=kharine_lobby_keyboard(chat.id, bot_username))
    kharine_games[chat.id]["message_id"] = msg.message_id

# =========================================================
# SYSTEM ARR, MESSAGES & CALLBACK HANDLERS
# =========================================================

ARR_WORDS = {"عر", "عرعر", "عر عر", "عرر", "عررر", "عرررر"}
last_arr = {}

def can_get_arr_score(user_id):
    now = time.time()
    if now - last_arr.get(user_id, 0) < ARR_COOLDOWN: return False
    last_arr[user_id] = now
    return True

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user = update.effective_user
    if not user: return

    create_user(user)
    text = update.message.text
    if not text: return
    clean_text = text.strip().lower()

    # دریافت مبلغ بازی‌های معلق
    pending = get_pending_game(user.id)
    if pending:
        if clean_text.isdigit():
            set_pending_game(user.id, "")
            context.args = [clean_text]
            if pending == "crash": await start_crash(update, context); update_quest(user.id, "game"); return
            elif pending == "rps": await start_rps_command(update, context); update_quest(user.id, "game"); return
            elif pending == "ttt": await start_ttt_command(update, context); update_quest(user.id, "game"); return
        else:
            set_pending_game(user.id, "")
            await update.message.reply_text("❌ مبلغ معتبر نبود. بازی لغو شد.")
            return

    # دستور بده / give
    parts = clean_text.split()
    if parts[0] == "بده" and len(parts) > 1 and parts[1].isdigit():
        if update.message.reply_to_message:
            context.args = [parts[1]]
            await give_score(update, context)
        return

    # بازی‌ها
    if clean_text == "انفجار":
        set_pending_game(user.id, "crash")
        await update.message.reply_text("💥 **بازی انفجار**\n\nلطفاً مبلغ شرط را ارسال کن:")
        return

    if clean_text == "سنگ":
        set_pending_game(user.id, "rps")
        await update.message.reply_text("🪨📄✂️ **سنگ کاغذ قیچی**\n\nلطفاً مبلغ شرط را ارسال کن:")
        return

    if clean_text == "دوز":
        set_pending_game(user.id, "ttt")
        await update.message.reply_text("❌⭕ **بازی دوز**\n\nلطفاً مبلغ شرط را ارسال کن:")
        return

    if clean_text in {"شروع خرینه", "خرینه", "بازی خرینه"}:
        await start_kharine(update, context)
        return

    # سیستم عر
    if clean_text in ARR_WORDS:
        if not can_get_arr_score(user.id):
            await update.message.reply_text("⏳ یکم صبر کن بعد دوباره عر بزن 😂")
            return
        add_score(user.id, ARR_SCORE)
        update_quest(user.id, "arr")
        await update.message.reply_text(f"🫏 عر زدی، پوینت گرفتی!\n+{ARR_SCORE} 🫏 پوینت")
        return

    # دستورات منو
    if clean_text in {"فروشگاه", "خرید"}: await show_store(update, context); return
    if clean_text in {"پروفایل", "امتیاز"}: await profile(update, context); return
    if clean_text in {"ماموریت", "ماموریت ها"}: await show_quests(update, context); return
    if clean_text in {"انبار", "کیف پول"}: await show_inventory(update, context); return
    if clean_text in {"راهنما", "کمک"}: await help_command(update, context); return

    # هوش مصنوعی
    if clean_text.startswith("خر ") or clean_text == "خر":
        prompt_text = "سلام خر!" if clean_text == "خر" else text[2:].strip()
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        ai_response = await ask_ai(prompt_text)
        update_quest(user.id, "ai")
        await update.message.reply_text(ai_response)
        return

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    create_user(user)

    if data == "main_menu": await query.edit_message_text("🫏 **خر‌بات**\n\nبه قلمرو خرها خوش اومدی!", reply_markup=main_menu(user.id)); return
    if data == "profile": await profile(update, context); return
    if data == "store": await show_store(update, context); return
    if data == "quests": await show_quests(update, context); return
    if data == "inventory": await show_inventory(update, context); return
    if data == "daily": await daily(update, context); return
    if data == "help": await help_command(update, context); return
    if data == "admin_panel": await admin_panel(update, context); return

    if data == "crash_next": await crash_next_step(query); return
    if data == "crash_cashout": await crash_cashout(query); return

    if data.startswith("rps_bot_"):
        bet = int(data.split("_")[2])
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🪨 سنگ", callback_data=f"rps_bplay_{bet}_stone"),
            InlineKeyboardButton("📄 کاغذ", callback_data=f"rps_bplay_{bet}_paper"),
            InlineKeyboardButton("✂️ قیچی", callback_data=f"rps_bplay_{bet}_scissors")
        ]])
        await query.edit_message_text("انتخابت رو بزن:", reply_markup=keyboard)
        return

    if data.startswith("rps_bplay_"):
        _, _, bet, choice = data.split("_")
        await play_rps_bot_choice(query, int(bet), choice)
        return

    if data.startswith("rps_pvp_"):
        bet = int(data.split("_")[2])
        await start_rps_pvp(query, bet)
        return

    if data.startswith("rps_accept_"):
        await accept_rps_pvp(query, data.replace("rps_accept_", ""))
        return

    if data.startswith("rps_play_"):
        parts = data.split("_")
        await play_rps_pvp_choice(query, f"{parts[2]}_{parts[3]}", parts[4])
        return

    if data.startswith("ttt_bot_"):
        await start_ttt_bot(query, int(data.split("_")[2]))
        return

    if data.startswith("ttt_pvp_"):
        await start_ttt_pvp(query, int(data.split("_")[2]))
        return

    if data.startswith("ttt_accept_"):
        await accept_ttt_pvp(query, data.replace("ttt_accept_", ""))
        return

    if data.startswith("ttt_move_"):
        parts = data.split("_")
        game_id = "_".join(parts[2:-1])
        pos = int(parts[-1])
        game = active_ttt_games.get(game_id)
        if game:
            if game["mode"] == "bot": await handle_ttt_bot_move(query, game_id, pos)
            else: await handle_ttt_pvp_move(query, game_id, pos)
        return

    if data.startswith("buy_"):
        await buy_item(query, data.replace("buy_", ""))
        return

# =========================================================
# MAIN FUNCTION
# =========================================================

def main():
    if not TOKEN:
        print("ERROR: BOT_TOKEN is missing!")
        return

    print("KHARBOT STARTING...")
    app = Application.builder().token(TOKEN).build()

    # عمومی
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("give", give_score))
    app.add_handler(CommandHandler("quests", show_quests))
    app.add_handler(CommandHandler("store", show_store))
    app.add_handler(CommandHandler("inventory", show_inventory))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("help", help_command))

    # مالک / Admin
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("addcoin", admin_add_coin))
    app.add_handler(CommandHandler("removecoin", admin_remove_coin))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("KHARBOT STARTED")
    app.run_polling()

if __name__ == "__main__":
    main()

