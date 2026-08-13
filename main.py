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
from google import genai

# =========================================================
# CONFIGURATION
# =========================================================

CONFIG = {
    "BOT_TOKEN": os.getenv("BOT_TOKEN"),
    "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY"),
    "ADMIN_ID": int(os.getenv("ADMIN_ID", "0")),
    "DB_PATH": os.getenv("DB_PATH", "/tmp/kharbot.db"),
    "ARR_SCORE": 10,
    "ARR_COOLDOWN": 30,
    "DAILY_SCORE": 100,
}

TOKEN = CONFIG["BOT_TOKEN"]
GEMINI_API_KEY = CONFIG["GEMINI_API_KEY"]
ADMIN_ID = CONFIG["ADMIN_ID"]
DB_PATH = CONFIG["DB_PATH"]
ARR_SCORE = CONFIG["ARR_SCORE"]
ARR_COOLDOWN = CONFIG["ARR_COOLDOWN"]
DAILY_SCORE = CONFIG["DAILY_SCORE"]

# =========================================================
# AI SETTINGS (Google Gemini 2.0)
# =========================================================

ai_client = None
if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_INSTRUCTION = "تو 'خر‌بات' هستی؛ یک هوش مصنوعی بسیار بامزه، طنز و شوخ‌طبع. لحن صمیمی و باکل‌کل داشته باش."

async def ask_ai(prompt: str) -> str:
    if not ai_client: 
        return "🫏 کلید GEMINI_API_KEY در تنظیمات بلمو ست نشده است!"
    try:
        response = ai_client.models.generate_content(
            model='gemini-2.0-flash',  # مدل کاملاً فعال و رایگان
            contents=f"{SYSTEM_INSTRUCTION}\n\nسوال کاربر: {prompt}"
        )
        return response.text
    except Exception as e:
        print(f"AI Error: {e}")
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
    rps_games INTEGER DEFAULT 0,
    rps_wins INTEGER DEFAULT 0,
    rps_losses INTEGER DEFAULT 0,
    rps_draws INTEGER DEFAULT 0,
    pending_game TEXT DEFAULT '',
    title TEXT DEFAULT ''
)
""")
db.commit()

for col, col_type in [("pending_game", "TEXT DEFAULT ''"), ("title", "TEXT DEFAULT ''")]:
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
    item_name TEXT
)
""")
db.commit()

# =========================================================
# USER SYSTEM
# =========================================================

def create_user(user):
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user.id,))
    if cursor.fetchone() is None:
        cursor.execute("INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)", (user.id, user.username or "", user.first_name or "Player"))
    else:
        cursor.execute("UPDATE users SET username = ?, first_name = ? WHERE user_id = ?", (user.username or "", user.first_name or "Player", user.id))
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

def main_menu():
    keyboard = [
        [InlineKeyboardButton("👤 پروفایل", callback_data="profile"), InlineKeyboardButton("💰 موجودی", callback_data="balance")],
        [InlineKeyboardButton("🎮 بازی‌ها", callback_data="games"), InlineKeyboardButton("🛍️ فروشگاه", callback_data="store")],
        [InlineKeyboardButton("🏆 جدول", callback_data="leaderboard"), InlineKeyboardButton("🎁 جایزه", callback_data="daily")],
        [InlineKeyboardButton("📖 راهنما", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

STORE_ITEMS = {
    "title_king": {"name": "👑 لقب: سلطان طویله", "price": 2000, "type": "title", "val": "👑 سلطان طویله"},
    "title_boss": {"name": "🔥 لقب: خرِ بزرگ", "price": 1000, "type": "title", "val": "🔥 خرِ بزرگ"},
}

def store_menu():
    keyboard = []
    for item_id, item in STORE_ITEMS.items():
        keyboard.append([InlineKeyboardButton(f"{item['name']} — {item['price']} 🫏", callback_data=f"buy_{item_id}")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

# =========================================================
# COMMANDS & GENERAL HANDLERS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        create_user(user)

    if context.args and context.args[0].startswith("join_"):
        try:
            chat_id = int(context.args[0].replace("join_", ""))
        except ValueError:
            await update.message.reply_text("❌ لینک ورود معتبر نیست!")
            return

        if chat_id not in kharine_games:
            await update.message.reply_text("❌ این بازی تمام شده یا وجود ندارد!")
            return

        game = kharine_games[chat_id]
        if game["state"] != "lobby":
            await update.message.reply_text("⚠️ بازی قبلاً شروع شده است!")
            return

        if user.id in game["players"]:
            await update.message.reply_text("🫏 شما قبلاً وارد این بازی شده‌اید!")
            return

        if len(game["players"]) >= 8:
            await update.message.reply_text("❌ ظرفیت بازی پر شده است (حداکثر ۸ نفر).")
            return

        game["players"][user.id] = {
            "name": user.first_name,
            "username": user.username or "",
            "role": None,
            "alive": True
        }

        await update.message.reply_text("✅ با موفقیت وارد بازی خرینه شدی! به گروه برگرد.")

        try:
            bot_username = (await context.bot.get_me()).username
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=game["message_id"],
                text=kharine_lobby_text(game),
                reply_markup=kharine_lobby_keyboard(chat_id, bot_username)
            )
        except Exception as e:
            print(f"Lobby Update Error: {e}")
        return

    await update.message.reply_text(
        "🫏 **خر‌بات**\n\nبه قلمرو خرها خوش اومدی 😂",
        reply_markup=main_menu()
    )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    create_user(user)

    cursor.execute("SELECT rps_games, rps_wins, rps_losses, rps_draws, title FROM users WHERE user_id = ?", (user.id,))
    row = cursor.fetchone()
    title = row[4] if (row and row[4]) else "🫏 خرِ معمولی"

    profile_text = (
        f"👤 **پروفایل کاربری**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏷️ **لقب:** {title}\n"
        f"📝 **نام:** {user.first_name}\n"
        f"🆔 **آیدی عددی:** `{user.id}`\n"
        f"💰 **موجودی:** **{get_score(user.id)}** 🫏 پوینت\n"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(profile_text)
    else:
        await update.message.reply_text(profile_text)

async def give_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message.reply_to_message:
        await update.message.reply_text("❌ روی پیام شخص مورد نظر ریپلی کن و بنویس `/give 50` یا `بده 50`")
        return

    target_user = update.message.reply_to_message.from_user
    if target_user.id == user.id:
        await update.message.reply_text("🤡 نمی‌تونی به خودت پوینت بدی!")
        return

    try:
        amount = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("❌ مبلغ معتبر نیست!")
        return

    if amount < 1:
        await update.message.reply_text("❌ مبلغ باید حداقل ۱ پوینت باشد!")
        return

    create_user(user)
    create_user(target_user)

    if get_score(user.id) < amount:
        await update.message.reply_text("❌ موجودی کافی نداری!")
        return

    remove_score(user.id, amount)
    add_score(target_user.id, amount)
    await update.message.reply_text(f"✅ **{amount}** پوینت با موفقیت به {target_user.first_name} هدیه داده شد!")

async def help_command(update, context):
    await update.message.reply_text("📖 **راهنما:**\nانفجار / سنگ / دوز / خرینه\nفروشگاه / جایزه / بده [مقدار]")

async def show_store(update, context):
    user = update.effective_user
    if not user: return
    create_user(user)
    text = f"🛍️ **فروشگاه**\n💰 موجودی شما: **{get_score(user.id)}** 🫏"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=store_menu())
    else:
        await update.message.reply_text(text, reply_markup=store_menu())

async def buy_item(query, item_id):
    user = query.from_user
    item = STORE_ITEMS.get(item_id)
    if not item: return

    score = get_score(user.id)
    if score < item["price"]:
        await query.answer("❌ موجودی کافی نیست!", show_alert=True)
        return

    remove_score(user.id, item["price"])
    cursor.execute("UPDATE users SET title = ? WHERE user_id = ?", (item["val"], user.id))
    db.commit()

    await query.answer("✅ خرید موفق!", show_alert=True)
    await query.edit_message_text(f"🎉 مبارکه! لقب شما به `{item['val']}` تغییر کرد.", reply_markup=store_menu())

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
# 🫏 KHARINE GAME (خرینه - ایمن‌شده)
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
# SYSTEM ARR & CALLBACKS
# =========================================================

ARR_WORDS = {"عر", "عرعر", "عر عر", "عرر", "عررر", "عرررر"}
last_arr = {}

def can_get_arr_score(user_id):
    now = time.time()
    if now - last_arr.get(user_id, 0) < ARR_COOLDOWN: return False
    last_arr[user_id] = now
    return True

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    create_user(user)

    if data == "main_menu":
        await query.edit_message_text("🫏 **خر‌بات**\n\nبه قلمرو خرها خوش اومدی!", reply_markup=main_menu())
        return

    if data == "games":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💥 انفجار", callback_data="btn_crash")],
            [InlineKeyboardButton("🪨 سنگ کاغذ قیچی", callback_data="btn_rps")],
            [InlineKeyboardButton("❌⭕ دوز", callback_data="btn_ttt")],
            [InlineKeyboardButton("🫏 خرینه", callback_data="btn_kharine")]
        ])
        await query.edit_message_text("🎮 **بازی‌ها:**", reply_markup=keyboard)
        return

    if data in ["btn_crash", "btn_rps", "btn_ttt", "btn_kharine"]:
        names = {"btn_crash": "انفجار", "btn_rps": "سنگ", "btn_ttt": "دوز", "btn_kharine": "خرینه"}
        await query.edit_message_text(f"🎯 برای شروع کافیست کلمه **{names[data]}** را بفرستید!")
        return

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

    if data in ["profile", "balance", "help", "store"]:
        if data == "profile": await profile(update, context)
        elif data == "help": await help_command(update, context)
        elif data == "store": await show_store(update, context)
        return

    if data.startswith("buy_"):
        await buy_item(query, data.replace("buy_", ""))
        return

# =========================================================
# MESSAGE HANDLER
# =========================================================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user = update.effective_user
    if not user: return

    create_user(user)
    text = update.message.text
    if not text: return
    clean_text = text.strip().lower()

    pending = get_pending_game(user.id)
    if pending:
        if clean_text.isdigit():
            set_pending_game(user.id, "")
            context.args = [clean_text]
            if pending == "crash": await start_crash(update, context); return
            elif pending == "rps": await start_rps_command(update, context); return
            elif pending == "ttt": await start_ttt_command(update, context); return
        else:
            set_pending_game(user.id, "")
            await update.message.reply_text("❌ مبلغ معتبر نبود. بازی لغو شد.")
            return

    parts = clean_text.split()
    if parts[0] == "بده" and len(parts) > 1 and parts[1].isdigit():
        if update.message.reply_to_message:
            context.args = [parts[1]]
            await give_score(update, context)
        else:
            await update.message.reply_text("❌ باید روی پیام شخص مورد نظر ریپلی کنی و بنویسی: `بده 50`")
        return

    if clean_text == "انفجار":
        set_pending_game(user.id, "crash")
        await update.message.reply_text("💥 **بازی انفجار**\n\nلطفاً مبلغ شرط را ارسال کن:")
        return

    if clean_text == "سنگ":
        set_pending_game(user.id, "rps")
        await update.message.reply_text("🪨📄✂️ **بازی سنگ کاغذ قیچی**\n\nلطفاً مبلغ شرط را ارسال کن:")
        return

    if clean_text == "دوز":
        set_pending_game(user.id, "ttt")
        await update.message.reply_text("❌⭕ **بازی دوز**\n\nلطفاً مبلغ شرط را ارسال کن:")
        return

    if clean_text in {"شروع خرینه", "خرینه", "بازی خرینه"}:
        await start_kharine(update, context)
        return

    if clean_text in ARR_WORDS:
        if not can_get_arr_score(user.id):
            await update.message.reply_text("⏳ یکم صبر کن بعد دوباره عر بزن 😂")
            return
        add_score(user.id, ARR_SCORE)
        await update.message.reply_text(f"🫏 عر زدی، پوینت گرفتی!\n+{ARR_SCORE} 🫏 پوینت")
        return

    if clean_text in {"فروشگاه", "خرید"}: await show_store(update, context); return
    if clean_text in {"پروفایل", "امتیاز"}: await profile(update, context); return

    if clean_text.startswith("خر ") or clean_text == "خر":
        prompt_text = "سلام خر!" if clean_text == "خر" else text[2:].strip()
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        ai_response = await ask_ai(prompt_text)
        await update.message.reply_text(ai_response)
        return

# =========================================================
# MAIN
# =========================================================

def main():
    if not TOKEN:
        print("ERROR: BOT_TOKEN is missing!")
        return

    print("KHARBOT STARTING...")
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("give", give_score))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("KHARBOT STARTED")
    app.run_polling()

if __name__ == "__main__":
    main()
 
