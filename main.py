import os
import sqlite3
import time
import random
import asyncio
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
# CONFIGURATION (KEY - VALUE FROM BELMO DASHBOARD)
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
# AI SETTINGS (Google Gemini)
# =========================================================

ai_client = None
if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_INSTRUCTION = """
تو "خر‌بات" هستی؛ یک هوش مصنوعی بسیار بامزه، طنز، شوخ‌طبع و باحال که توی گروه‌های تلگرامی چت می‌کنی.
لحن تو باید صمیمی، طنز، همراه با کل‌کل و ایموجی‌های بامزه (مثل 🫏، 😂، 🔥) باشه.
پاسخ‌هات نباید خیلی طولانی و رسمی باشه. طوری جواب بده که بچه‌های گروه بخندن.
تو بازی‌هایی مثل "خرینه"، "انفجار"، "سنگ کاغذ قیچی" و "دوز" رو بلدی و می‌تونی درباره‌شون کل‌کل کنی.
"""

async def ask_ai(prompt: str) -> str:
    if not ai_client:
        return "🫏 کلید GEMINI_API_KEY در تنظیمات ثبت نشده!"
    
    try:
        response = ai_client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
            config={
                'system_instruction': SYSTEM_INSTRUCTION,
                'temperature': 0.85,
            }
        )
        return response.text
    except Exception as e:
        print(f"AI Error: {e}")
        return "🫏 ای بابا، مخم هنگ کرد! چند لحظه دیگه دوباره بپرس."

# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    DB_PATH,
    check_same_thread=False
)

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

# ارتقای ساختار جدول در صورت وجود دیتابیس قدیمی
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
        cursor.execute("""
        INSERT INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
        """, (user.id, user.username or "", user.first_name or "Player"))
    else:
        cursor.execute("""
        UPDATE users SET username = ?, first_name = ? WHERE user_id = ?
        """, (user.username or "", user.first_name or "Player", user.id))
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
# ARR SYSTEM
# =========================================================

ARR_WORDS = {"عر", "عرعر", "عر عر", "عرر", "عررر", "عرررر", "عررررر", "ار ار", "ارار"}
last_arr = {}
ARR_RESPONSES = [
    "🫏 خر شناسایی شد!", "🫏 عررررر!", "😂 صدای خر تأیید شد!",
    "🔥 عر زدی، پوینت گرفتی!", "🫏 خر‌بات راضی است!", "😂 گروه داره تبدیل به طویله میشه!"
]

def can_get_arr_score(user_id):
    now = time.time()
    last_time = last_arr.get(user_id, 0)
    if now - last_time < ARR_COOLDOWN:
        return False
    last_arr[user_id] = now
    return True

# =========================================================
# MAIN MENU & STORE MENU
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
    "role_doctor": {"name": "🩺 کارت خرپزشک (بازی بعدی)", "price": 1500, "type": "card", "val": "doctor"},
    "role_kharine": {"name": "🐺 کارت خرینه (بازی بعدی)", "price": 2500, "type": "card", "val": "kharine"},
}

def store_menu():
    keyboard = []
    for item_id, item in STORE_ITEMS.items():
        keyboard.append([
            InlineKeyboardButton(f"{item['name']} — {item['price']} 🫏", callback_data=f"buy_{item_id}")
        ])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

# =========================================================
# COMMAND HANDLERS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        create_user(user)

    # Deep Linking برای ورود به لابی خرینه
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

        await update.message.reply_text(
            "✅ **با موفقیت وارد بازی خرینه شدی!**\n\n"
            "موقع شروع بازی، نقش شما همین‌جا ارسال می‌شود. برگرد به گروه! 🫏"
        )

        try:
            bot_username = (await context.bot.get_me()).username
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=game["message_id"],
                text=kharine_lobby_text(game),
                reply_markup=kharine_lobby_keyboard(chat_id, bot_username)
            )
        except Exception as e:
            print(f"Error updating lobby message: {e}")
        return

    await update.message.reply_text(
        "🫏 **خر‌بات**\n\nبه قلمرو خرها خوش اومدی 😂\n\n💰 پوینت جمع کن\n🎮 بازی کن\n🤖 با هوش مصنوعی چت کن\n🫏 خرینه بازی کن",
        reply_markup=main_menu()
    )


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    create_user(user)
    score = get_score(user.id)

    cursor.execute(
        "SELECT rps_games, rps_wins, rps_losses, rps_draws, title FROM users WHERE user_id = ?", 
        (user.id,)
    )
    row = cursor.fetchone()

    rps_games = row[0] if row else 0
    rps_wins = row[1] if row else 0
    rps_losses = row[2] if row else 0
    rps_draws = row[3] if row else 0
    title = row[4] if (row and row[4]) else "🫏 خرِ معمولی"

    profile_text = (
        f"👤 **پروفایل کاربری**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏷️ **لقب:** {title}\n"
        f"📝 **نام:** {user.first_name}\n"
        f"🆔 **آیدی عددی:** `{user.id}`\n"
        f"💰 **موجودی:** **{score}** 🫏 پوینت\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🎮 **آمار بازی سنگ‌کاغذ‌قیچی:**\n"
        f"🔹 کل بازی‌ها: {rps_games}\n"
        f"🏆 بردها: {rps_wins}\n"
        f"💀 باخت‌ها: {rps_losses}\n"
        f"🤝 مساوی‌ها: {rps_draws}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🛍️ برای خرید لقب جدید، کلمه **«فروشگاه»** رو بفرست!"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(profile_text)
    else:
        await update.message.reply_text(profile_text)


async def balance(update, context):
    user = update.effective_user
    if not user:
        return
    create_user(user)
    await update.message.reply_text(f"💰 موجودی شما:\n\n🫏 **{get_score(user.id)}** پوینت")


async def daily(update, context):
    user = update.effective_user
    if not user:
        return
    create_user(user)
    now = int(time.time())
    cursor.execute("SELECT last_daily FROM users WHERE user_id = ?", (user.id,))
    res = cursor.fetchone()
    last = res[0] if res else 0

    if now - last < 86400:
        rem = 86400 - (now - last)
        hours, minutes = rem // 3600, (rem % 3600) // 60
        await update.message.reply_text(f"🎁 جایزه امروز رو گرفتی!\n\n⏳ {hours} ساعت و {minutes} دقیقه دیگه بیا.")
        return

    add_score(user.id, DAILY_SCORE)
    cursor.execute("UPDATE users SET last_daily = ? WHERE user_id = ?", (now, user.id))
    db.commit()
    await update.message.reply_text(f"🎁 جایزه روزانه!\n\n+{DAILY_SCORE} 🫏 پوینت\n💰 موجودی: **{get_score(user.id)}**")


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute(
        "SELECT first_name, username, score, title FROM users ORDER BY score DESC LIMIT 10"
    )
    users = cursor.fetchall()

    if not users:
        await update.message.reply_text("هنوز کسی امتیازی نداره!")
        return

    text = "🏆 **جدول ۱۰ خرِ برتر قلمرو**\n\n"
    for i, row in enumerate(users):
        name = "@" + row[1] if row[1] else row[0]
        score = row[2]
        title = f" [{row[3]}]" if row[3] else ""

        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i + 1}."
        text += f"{medal} **{name}**{title} — **{score}** 🫏\n"

    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)


async def help_command(update, context):
    await update.message.reply_text(
        """
📖 **راهنمای جامع خر‌بات**

🎮 **شروع بازی‌ها (کلمه را بفرستید):**
💥 **انفجار** ➔ ارسال کلمه `انفجار`
🪨 **سنگ کاغذ قیچی** ➔ ارسال کلمه `سنگ`
❌ **دوز** ➔ ارسال کلمه `دوز`
🫏 **خرینه (مافیا)** ➔ ارسال کلمه `خرینه`

*(بعد از ارسال کلمه، ربات مبلغ شرط را از شما می‌پرسد)*

🤖 **چت با هوش مصنوعی:**
اول پیامت بگو **خر** (مثال: `خر چطوری؟`) یا روی پیام ربات **ریپلی** بزن!

🛍️ **فروشگاه و حساب:**
🛍️ **فروشگاه** ➔ خرید لقب و کارت ویژه
🫏 **عر** ➔ کسب پوینت سریع
🎁 **جایزه** | 💰 **موجودی** | 👤 **پروفایل** | 🏆 **جدول**
"""
    )


async def show_store(update, context):
    user = update.effective_user
    if not user: return
    create_user(user)

    text = (
        "🛍️ **فروشگاه خر‌بات**\n\n"
        f"💰 موجودی فعلی شما: **{get_score(user.id)}** 🫏 پوینت\n\n"
        "آیتم مورد نظرت رو انتخاب کن تا با پوینت‌هات بخری:"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=store_menu())
    else:
        await update.message.reply_text(text, reply_markup=store_menu())


async def buy_item(query, item_id):
    user = query.from_user
    item = STORE_ITEMS.get(item_id)

    if not item:
        await query.answer("❌ آیتم یافت نشد!", show_alert=True)
        return

    score = get_score(user.id)
    if score < item["price"]:
        await query.answer(f"❌ موجودی کافی نیست! این آیتم {item['price']} پوینت نیاز داره.", show_alert=True)
        return

    remove_score(user.id, item["price"])

    if item["type"] == "title":
        cursor.execute("UPDATE users SET title = ? WHERE user_id = ?", (item["val"], user.id))
        db.commit()
        msg = f"🎉 **مبارکه!** لقب شما به `{item['val']}` تغییر کرد."
    else:
        cursor.execute("INSERT INTO inventory (user_id, item_id, item_name) VALUES (?, ?, ?)", (user.id, item_id, item["name"]))
        db.commit()
        msg = f"🎉 **خرید موفق!** `{item['name']}` به کیف کارت‌های شما اضافه شد."

    await query.answer("✅ خرید با موفقیت انجام شد!", show_alert=True)
    await query.edit_message_text(
        f"{msg}\n\n💰 موجودی جدید: **{get_score(user.id)}** 🫏",
        reply_markup=store_menu()
    )

# =========================================================
# ADMIN COMMANDS
# =========================================================

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("⛔ شما دسترسی ادمین ندارید.")
        return

    if os.path.exists(DB_PATH):
        db.commit()
        with open(DB_PATH, "rb") as db_file:
            await context.bot.send_document(chat_id=user.id, document=db_file, filename="kharbot_backup.db")
    else:
        await update.message.reply_text("❌ فایل دیتابیس یافت نشد!")


async def add_score_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return

    target_id, amount = None, 0
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
        try: amount = int(context.args[0])
        except: return
    elif len(context.args) == 2:
        try: target_id, amount = int(context.args[0]), int(context.args[1])
        except: return

    if target_id and amount:
        add_score(target_id, amount)
        await update.message.reply_text(f"✅ {amount} پوینت به `{target_id}` اضافه شد.")


async def rem_score_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return

    target_id, amount = None, 0
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
        try: amount = int(context.args[0])
        except: return
    elif len(context.args) == 2:
        try: target_id, amount = int(context.args[0]), int(context.args[1])
        except: return

    if target_id and amount:
        remove_score(target_id, amount)
        await update.message.reply_text(f"🔻 {amount} پوینت از `{target_id}` کسر شد.")

# =========================================================
# 💥 CRASH GAME (انفجار)
# =========================================================

active_crash_games = {}

def generate_crash_multiplier():
    rand = random.random()
    if rand < 0.25:
        return 1
    return min(int(2 + random.expovariate(0.3)), 30)

async def start_crash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    create_user(user)

    try: bet = int(context.args[0])
    except: return

    if bet < 10 or bet > 5000 or get_score(user.id) < bet:
        await update.message.reply_text("❌ شرط نامعتبر یا موجودی کافی نیست!")
        return

    remove_score(user.id, bet)
    crash_point = generate_crash_multiplier()

    active_crash_games[user.id] = {
        "bet": bet, "crash_point": crash_point, "current_multiplier": 1, "cashed_out": False
    }

    if crash_point == 1:
        del active_crash_games[user.id]
        await update.message.reply_text(f"💥 **بـومم! همون قدم اول (1x) منفجر شد!**\n💀 باختید: -{bet} پوینت")
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📈 افزایش ضریب (+1)", callback_data="crash_next"),
        InlineKeyboardButton("💰 برداشت پوینت", callback_data="crash_cashout")
    ]])

    await update.message.reply_text(
        f"🚀 **بازی انفجار شروع شد!**\n\n💵 شرط: **{bet}** پوینت\n📈 ضریب فعلی: **1x**\n💰 سود: **{bet}**",
        reply_markup=keyboard
    )

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
    await query.edit_message_text(
        f"🚀 **ضریب بالا رفت!**\n\n💵 شرط: **{bet}** | 📈 ضریب: **{next_mult}x**\n💰 سود قابل برداشت: **{bet * next_mult}**",
        reply_markup=keyboard
    )

async def crash_cashout(query):
    user = query.from_user
    game = active_crash_games.get(user.id)
    if not game: return

    bet, curr_mult = game["bet"], game["current_multiplier"]
    win_amount = bet * curr_mult

    add_score(user.id, win_amount)
    del active_crash_games[user.id]

    await query.answer("🎉 برداشت موفق!", show_alert=True)
    await query.edit_message_text(f"✅ **برداشت موفق!**\n🎯 ضریب: **{curr_mult}x**\n🎁 دریافت شد: **+{win_amount}** 🫏")

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
    except: return

    if bet < 10 or bet > 5000 or get_score(user.id) < bet:
        await update.message.reply_text("❌ شرط نامعتبر یا موجودی کافی نیست!")
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🤖 بازی با خر‌بات", callback_data=f"rps_bot_{bet}"),
        InlineKeyboardButton("👥 چالش در گروه", callback_data=f"rps_pvp_{bet}")
    ]])

    await update.message.reply_text(
        f"🪨📄✂️ **سنگ کاغذ قیچی شرطی**\n\n💵 مبلغ شرط: **{bet}** پوینت\n\nانتخاب کن:",
        reply_markup=keyboard
    )

async def play_rps_bot_choice(query, bet, user_choice):
    user = query.from_user
    bot_choice = random.choice(list(RPS_CHOICES.keys()))
    res = rps_winner(user_choice, bot_choice)

    cursor.execute("UPDATE users SET rps_games = rps_games + 1 WHERE user_id = ?", (user.id,))

    if res == "p1":
        add_score(user.id, bet)
        cursor.execute("UPDATE users SET rps_wins = rps_wins + 1 WHERE user_id = ?", (user.id,))
        msg = f"🎉 **بردی!** (+{bet} پوینت)"
    elif res == "p2":
        remove_score(user.id, bet)
        cursor.execute("UPDATE users SET rps_losses = rps_losses + 1 WHERE user_id = ?", (user.id,))
        msg = f"💀 **خر‌بات برد!** (-{bet} پوینت)"
    else:
        cursor.execute("UPDATE users SET rps_draws = rps_draws + 1 WHERE user_id = ?", (user.id,))
        msg = "🤝 **مساوی شد!**"

    db.commit()

    await query.edit_message_text(
        f"👤 تو: {RPS_CHOICES[user_choice]}\n🤖 خر‌بات: {RPS_CHOICES[bot_choice]}\n\n{msg}\n💰 موجودی: **{get_score(user.id)}**"
    )

async def start_rps_pvp(query, bet):
    chat, user = query.message.chat, query.from_user
    if chat.type == "private":
        await query.answer("⚠️ چالش فقط در گروه!", show_alert=True)
        return

    game_id = f"{chat.id}_{int(time.time())}"
    active_group_rps[game_id] = {
        "p1_id": user.id, "p1_name": user.first_name, "p1_choice": None,
        "p2_id": None, "p2_name": None, "p2_choice": None, "bet": bet, "state": "waiting"
    }

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⚔️ قبول چالش!", callback_data=f"rps_accept_{game_id}")]])
    await query.edit_message_text(f"⚔️ **چالش سنگ کاغذ قیچی!**\n👤 ایجادکننده: **{user.first_name}**\n💵 شرط: **{bet}**", reply_markup=keyboard)

async def accept_rps_pvp(query, game_id):
    user = query.from_user
    game = active_group_rps.get(game_id)
    if not game or user.id == game["p1_id"] or get_score(user.id) < game["bet"]:
        return

    game["p2_id"], game["p2_name"], game["state"] = user.id, user.first_name, "choosing"
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🪨 سنگ", callback_data=f"rps_play_{game_id}_stone"),
        InlineKeyboardButton("📄 کاغذ", callback_data=f"rps_play_{game_id}_paper"),
        InlineKeyboardButton("✂️ قیچی", callback_data=f"rps_play_{game_id}_scissors")
    ]])
    await query.edit_message_text(f"🎮 **مسابقه شروع شد!**\n⚔️ **{game['p1_name']}** VS **{game['p2_name']}**\n👇 انتخاب کنید:", reply_markup=keyboard)

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
    except: return

    if bet < 10 or bet > 5000 or get_score(user.id) < bet:
        await update.message.reply_text("❌ شرط نامعتبر یا موجودی کافی نیست!")
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🤖 بازی با خر‌بات", callback_data=f"ttt_bot_{bet}"),
        InlineKeyboardButton("👥 چالش در گروه", callback_data=f"ttt_pvp_{bet}")
    ]])
    await update.message.reply_text(f"❌⭕ **بازی دوز شرطی**\n💵 شرط: **{bet}** پوینت\n\nانتخاب کن:", reply_markup=keyboard)

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
    await query.edit_message_text(f"⚔️ **چالش دوز!**\n👤 **{user.first_name}** (❌)\n💵 شرط: **{bet}**", reply_markup=keyboard)

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
ROLE_NAMES = {"kharine": "🐺 خرینه", "seer": "🔮 فال‌خر", "doctor": "🩺 خرپزشک", "villager": "👨‍🌾 خر‌دار"}

def create_roles(count):
    roles = ["kharine", "seer", "doctor", "villager"]
    if count >= 5: roles.append("villager")
    if count >= 6: roles.append("kharine")
    if count >= 7: roles.append("villager")
    if count >= 8: roles.append("villager")
    random.shuffle(roles)
    return roles

def kharine_lobby_keyboard(chat_id, bot_username):
    join_url = f"https://t.me/{bot_username}?start=join_{chat_id}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🫏 ورود به بازی (در پیوی)", url=join_url)],
        [InlineKeyboardButton("🚪 خروج", callback_data=f"khleave:{chat_id}")],
        [InlineKeyboardButton("🚀 شروع بازی", callback_data=f"khstart:{chat_id}")]
    ])

def kharine_lobby_text(game):
    text = "🫏 **خرینه**\n\n👥 بازیکنان:\n"
    for i, p in enumerate(game["players"].values(), 1): text += f"{i}. {p['name']}\n"
    text += f"\n👥 تعداد: {len(game['players'])}/8 (حداقل ۴ نفر)"
    return text

async def cancel_kharine_lobby(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    game = kharine_games.get(chat_id)
    if game and game.get("state") == "lobby":
        del kharine_games[chat_id]
        await context.bot.send_message(chat_id=chat_id, text="⏰ **لابی خرینه به دلیل عدم شروع بعد از ۲ دقیقه لغو شد.**")

async def start_kharine(update, context):
    chat, user = update.effective_chat, update.effective_user
    if not chat or chat.type == "private" or chat.id in kharine_games: return

    create_user(user)
    bot_username = (await context.bot.get_me()).username
    timeout_job = context.job_queue.run_once(cancel_kharine_lobby, 120, data=chat.id)

    kharine_games[chat.id] = {
        "players": {user.id: {"name": user.first_name, "username": user.username or "", "role": None, "alive": True}},
        "state": "lobby", "day": 0, "message_id": None, "night_kill": None, "doctor_target": None, "seer_target": None, "votes": {}, "timeout_job": timeout_job
    }
    msg = await update.message.reply_text(kharine_lobby_text(kharine_games[chat.id]), reply_markup=kharine_lobby_keyboard(chat.id, bot_username))
    kharine_games[chat.id]["message_id"] = msg.message_id

async def begin_kharine(query, context):
    chat_id = query.message.chat_id
    game = kharine_games.get(chat_id)
    if not game or game["state"] != "lobby" or len(game["players"]) < 4:
        await query.answer("حداقل ۴ بازیکن لازم است!", show_alert=True)
        return

    if "timeout_job" in game and game["timeout_job"]:
        game["timeout_job"].schedule_removal()

    roles = create_roles(len(game["players"]))
    for uid, role in zip(game["players"].keys(), roles):
        game["players"][uid]["role"] = role

    game["state"], game["day"] = "night", 1
    await query.answer("🚀 شروع شد!")

    descriptions = {
        "kharine": "🐺 **نقش شما: خرینه (مافیا)**\n🌙 شب‌ها یک نفر را حذف کن!",
        "seer": "🔮 **نقش شما: فال‌خر (کارآگاه)**\n🌙 هر شب استعلام بگیر!",
        "doctor": "🩺 **نقش شما: خرپزشک (دکتر)**\n🌙 هر شب یک نفر را نجات بده!",
        "villager": "👨‍🌾 **نقش شما: خر‌دار (شهروند)**\n🗣️ با بحث و رأی‌گیری خرینه‌ها را پیدا کن!"
    }

    for uid, p in game["players"].items():
        try: await context.bot.send_message(chat_id=uid, text=descriptions[p["role"]])
        except: pass

    await query.edit_message_text("🫏 **خرینه شروع شد!**\n🎭 نقش‌ها فرستاده شدند.\n🌙 شب اول آغاز شد...")
    await start_night(chat_id, context)

async def start_night(chat_id, context):
    game = kharine_games.get(chat_id)
    if not game: return
    game["state"], game["night_kill"], game["doctor_target"], game["seer_target"] = "night", None, None, None

    for uid, p in game["players"].items():
        if not p["alive"]: continue
        keyboard = []
        for tid, t in game["players"].items():
            if t["alive"] and tid != uid:
                prefix = "khkill" if p["role"] == "kharine" else "khseer" if p["role"] == "seer" else "khdoctor"
                keyboard.append([InlineKeyboardButton(t["name"], callback_data=f"{prefix}:{chat_id}:{tid}")])
        if keyboard and p["role"] in ["kharine", "seer", "doctor"]:
            try: await context.bot.send_message(chat_id=uid, text="🌙 نوبت حرکت شب:", reply_markup=InlineKeyboardMarkup(keyboard))
            except: pass

    context.job_queue.run_once(finish_night_job, 30, data=chat_id)

async def finish_night_job(context):
    await finish_night(context.job.data, context)

async def kh_kill(query, chat_id, target_id):
    game = kharine_games.get(int(chat_id))
    if game: game["night_kill"] = int(target_id)
    await query.answer("🎯 ثبت شد.")

async def kh_seer(query, chat_id, target_id):
    game = kharine_games.get(int(chat_id))
    if game:
        r = game["players"][int(target_id)]["role"]
        await query.answer("🐺 خرینه است!" if r == "kharine" else "🏘️ خرینه نیست.", show_alert=True)

async def kh_doctor(query, chat_id, target_id):
    game = kharine_games.get(int(chat_id))
    if game: game["doctor_target"] = int(target_id)
    await query.answer("🩺 ثبت شد.")

async def finish_night(chat_id, context):
    game = kharine_games.get(chat_id)
    if not game: return
    kill, save = game["night_kill"], game["doctor_target"]
    killed = None

    if kill and kill != save and kill in game["players"]:
        game["players"][kill]["alive"] = False
        killed = game["players"][kill]

    game["state"] = "day"
    text = f"☀️ صبح شد!\n💀 {killed['name']} حذف شد. (نقش: {ROLE_NAMES[killed['role']]})" if killed else "☀️ صبح شد!\n😮 دیشب کسی حذف نشد!"
    await context.bot.send_message(chat_id=chat_id, text=text)

    if await check_kharine_win(chat_id, context): return
    await start_voting(chat_id, context)

async def start_voting(chat_id, context):
    game = kharine_games.get(chat_id)
    if not game: return
    game["state"], game["votes"] = "voting", {}

    keyboard = [[InlineKeyboardButton(p["name"], callback_data=f"khvote:{chat_id}:{uid}")] for uid, p in game["players"].items() if p["alive"]]
    await context.bot.send_message(chat_id=chat_id, text="🗳️ **زمان رأی‌گیری!**", reply_markup=InlineKeyboardMarkup(keyboard))
    context.job_queue.run_once(finish_voting_job, 30, data=chat_id)

async def finish_voting_job(context):
    await finish_voting(context.job.data, context)

async def kh_vote(query, chat_id, target_id):
    game = kharine_games.get(int(chat_id))
    if game and game["players"][query.from_user.id]["alive"]:
        game["votes"][query.from_user.id] = int(target_id)
        await query.answer("🗳️ ثبت شد.")

async def finish_voting(chat_id, context):
    game = kharine_games.get(chat_id)
    if not game or not game["votes"]: return

    counter = Counter(game["votes"].values())
    max_v = max(counter.values())
    cands = [u for u, c in counter.items() if c == max_v]

    if len(cands) > 1:
        await context.bot.send_message(chat_id=chat_id, text="🤝 رأی‌گیری مساوی شد! کسی حذف نشد.")
    else:
        elim = cands[0]
        game["players"][elim]["alive"] = False
        await context.bot.send_message(chat_id=chat_id, text=f"🗳️ {game['players'][elim]['name']} حذف شد. (نقش: {ROLE_NAMES[game['players'][elim]['role']]})")

    if await check_kharine_win(chat_id, context): return
    await start_night(chat_id, context)

async def check_kharine_win(chat_id, context):
    game = kharine_games.get(chat_id)
    if not game: return True
    alive = [p for p in game["players"].values() if p["alive"]]
    khs = [p for p in alive if p["role"] == "kharine"]
    vils = [p for p in alive if p["role"] != "kharine"]

    if len(khs) >= len(vils):
        await context.bot.send_message(chat_id=chat_id, text="🐺 **خرینه‌ها برنده شدند!**")
        del kharine_games[chat_id]; return True
    if len(khs) == 0:
        await context.bot.send_message(chat_id=chat_id, text="🏘️ **اهالی طویله برنده شدند!**")
        del kharine_games[chat_id]; return True
    return False

# =========================================================
# BUTTON & MESSAGE HANDLERS
# =========================================================

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    data, user = query.data, query.from_user
    create_user(user)

    if data == "main_menu":
        await query.edit_message_text(
            "🫏 **خر‌بات**\n\nبه قلمرو خرها خوش اومدی 😂\n\n💰 پوینت جمع کن\n🎮 بازی کن\n🤖 با هوش مصنوعی چت کن\n🫏 خرینه بازی کن",
            reply_markup=main_menu()
        )
        return

    if data == "profile": await profile(update, context); return
    if data == "balance": await balance(update, context); return
    if data == "daily": await daily(update, context); return
    if data == "leaderboard": await leaderboard(update, context); return
    if data == "help": await help_command(update, context); return
    if data == "store": await show_store(update, context); return

    if data.startswith("buy_"):
        item_id = data.replace("buy_", "")
        await buy_item(query, item_id)
        return

    if data == "games":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💥 انفجار", callback_data="btn_crash")],
            [InlineKeyboardButton("🪨 سنگ کاغذ قیچی", callback_data="btn_rps")],
            [InlineKeyboardButton("❌⭕ دوز", callback_data="btn_ttt")],
            [InlineKeyboardButton("🫏 خرینه", callback_data="btn_kharine")]
        ])
        await query.edit_message_text("🎮 **بازی‌های خر‌بات:**\nبرای شروع بازی، اسمش رو توی گروه بفرست!", reply_markup=keyboard)
        return

    if data in ["btn_crash", "btn_rps", "btn_ttt", "btn_kharine"]:
        names = {"btn_crash": "انفجار", "btn_rps": "سنگ", "btn_ttt": "دوز", "btn_kharine": "خرینه"}
        await query.edit_message_text(f"🎯 برای شروع این بازی کافیست کلمه **{names[data]}** را ارسال کنید!")
        return

    if data.startswith("crash_"):
        if data == "crash_next": await crash_next_step(query)
        elif data == "crash_cashout": await crash_cashout(query)
        return

    if data.startswith("rps_"):
        if data.startswith("rps_bot_"):
            bet = int(data.replace("rps_bot_", ""))
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🪨 سنگ", callback_data=f"rps_bplay_{bet}_stone"),
                InlineKeyboardButton("📄 کاغذ", callback_data=f"rps_bplay_{bet}_paper"),
                InlineKeyboardButton("✂️ قیچی", callback_data=f"rps_bplay_{bet}_scissors")
            ]])
            await query.edit_message_text("انتخابت رو بزن:", reply_markup=keyboard)
        elif data.startswith("rps_bplay_"):
            _, _, bet, choice = data.split("_")
            await play_rps_bot_choice(query, int(bet), choice)
        elif data.startswith("rps_pvp_"):
            await start_rps_pvp(query, int(data.replace("rps_pvp_", "")))
        elif data.startswith("rps_accept_"):
            await accept_rps_pvp(query, data.replace("rps_accept_", ""))
        elif data.startswith("rps_play_"):
            _, _, game_id, choice = data.split("_", 3)
            await play_rps_pvp_choice(query, game_id, choice)
        return

    if data.startswith("ttt_"):
        if data.startswith("ttt_bot_"): await start_ttt_bot(query, int(data.replace("ttt_bot_", "")))
        elif data.startswith("ttt_pvp_"): await start_ttt_pvp(query, int(data.replace("ttt_pvp_", "")))
        elif data.startswith("ttt_accept_"): await accept_ttt_pvp(query, data.replace("ttt_accept_", ""))
        elif data.startswith("ttt_move_"):
            _, _, game_id, pos = data.split("_", 3)
            g = active_ttt_games.get(game_id)
            if g:
                if g["mode"] == "bot": await handle_ttt_bot_move(query, game_id, int(pos))
                else: await handle_ttt_pvp_move(query, game_id, int(pos))
        return

    if ":" in data:
        action, chat_id, target_id = data.split(":")
        if action == "khstart": await begin_kharine(query, context)
        elif action == "khkill": await kh_kill(query, chat_id, target_id)
        elif action == "khseer": await kh_seer(query, chat_id, target_id)
        elif action == "khdoctor": await kh_doctor(query, chat_id, target_id)
        elif action == "khvote": await kh_vote(query, chat_id, target_id)
        return


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user = update.effective_user
    if not user: return

    create_user(user)
    text = update.message.text
    if not text: return
    clean_text = text.strip().lower()

    # ۱. دریافت مبلغ بازی معلق
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

    # ۲. کلمات کلیدی بازی‌ها
    if clean_text == "انفجار":
        set_pending_game(user.id, "crash")
        await update.message.reply_text("💥 **بازی انفجار**\n\nلطفاً مبلغ شرط را به عدد ارسال کن (مثلاً: `100`):")
        return

    if clean_text == "سنگ":
        set_pending_game(user.id, "rps")
        await update.message.reply_text("🪨📄✂️ **بازی سنگ کاغذ قیچی**\n\nلطفاً مبلغ شرط را به عدد ارسال کن (مثلاً: `50`):")
        return

    if clean_text == "دوز":
        set_pending_game(user.id, "ttt")
        await update.message.reply_text("❌⭕ **بازی دوز**\n\nلطفاً مبلغ شرط را به عدد ارسال کن (مثلاً: `100`):")
        return

    if clean_text in {"شروع خرینه", "خرینه", "بازی خرینه"}:
        await start_kharine(update, context)
        return

    # ۳. سیستم عر
    if clean_text in ARR_WORDS:
        if not can_get_arr_score(user.id):
            await update.message.reply_text("⏳ یکم صبر کن بعد دوباره عر بزن 😂")
            return
        add_score(user.id, ARR_SCORE)
        await update.message.reply_text(f"{random.choice(ARR_RESPONSES)}\n\n+{ARR_SCORE} 🫏 پوینت\n💰 موجودی: **{get_score(user.id)}**")
        return

    # ۴. دستورات عمومی
    if clean_text in {"فروشگاه", "مغازه", "خرید"}: await show_store(update, context); return
    if clean_text in {"پروفایل", "امتیاز", "امتیاز من"}: await profile(update, context); return
    if clean_text in {"موجودی", "پوینت", "پول"}: await balance(update, context); return
    if clean_text in {"جایزه", "جایزه روزانه"}: await daily(update, context); return
    if clean_text in {"جدول", "امتیازات", "رتبه", "رنک"}: await leaderboard(update, context); return
    if clean_text in {"راهنما", "کمک"}: await help_command(update, context); return

    # ۵. هوش مصنوعی
    is_reply_to_bot = (
        update.message.reply_to_message and 
        update.message.reply_to_message.from_user and
        update.message.reply_to_message.from_user.id == context.bot.id
    )
    starts_with_khar = clean_text.startswith("خر ") or clean_text == "خر"

    if is_reply_to_bot or starts_with_khar:
        prompt_text = "سلام خر!" if clean_text == "خر" else text[2:].strip() if starts_with_khar else text
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

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("top", leaderboard))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("help", help_command))

    # Admin Commands
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("addscore", add_score_admin))
    app.add_handler(CommandHandler("remscore", rem_score_admin))

    # Handlers
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("KHARBOT STARTED")
    app.run_polling()

if __name__ == "__main__":
    main()
