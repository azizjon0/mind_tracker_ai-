
import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
import pandas as pd
import matplotlib.pyplot as plt
import io
from datetime import datetime
import os

TOKEN = os.getenv("7511453165:AAEfc_58za6G0kDEMdYfn1rRVp4nwd_WHZk")

logging.basicConfig(level=logging.INFO)
conn = sqlite3.connect("thoughts.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS thoughts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    text TEXT,
    score INTEGER,
    category TEXT,
    timestamp TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS categories (
    user_id INTEGER,
    name TEXT
)
""")
conn.commit()

user_states = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Напиши свою мысль — я помогу её зафиксировать и проанализировать.")

async def handle_thought(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text
    user_states[user_id] = {"text": text}
    keyboard = [[InlineKeyboardButton(str(i), callback_data=f"score:{i}") for i in range(-3, 4)]]
    await update.message.reply_text("Как оцениваешь мысль по шкале от -3 до +3?", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    score = int(query.data.split(":")[1])
    user_states[user_id]["score"] = score

    cursor.execute("SELECT name FROM categories WHERE user_id = ?", (user_id,))
    existing_categories = [row[0] for row in cursor.fetchall()]
    keyboard = [[InlineKeyboardButton(name, callback_data=f"cat:{name}")] for name in existing_categories]
    keyboard.append([InlineKeyboardButton("➕ Новая категория", callback_data="cat:new")])
    await query.edit_message_text("Выбери категорию:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "cat:new":
        await query.edit_message_text("Напиши новую категорию:")
        user_states[user_id]["awaiting_new_category"] = True
        return

    category = query.data.split(":")[1]
    await save_thought(user_id, category, query)

async def handle_new_category_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in user_states and user_states[user_id].get("awaiting_new_category"):
        category = update.message.text.strip()
        cursor.execute("INSERT INTO categories (user_id, name) VALUES (?, ?)", (user_id, category))
        conn.commit()
        del user_states[user_id]["awaiting_new_category"]
        await save_thought(user_id, category, update)

async def save_thought(user_id, category, context_source):
    text = user_states[user_id]["text"]
    score = user_states[user_id]["score"]
    timestamp = datetime.now().isoformat()
    cursor.execute("INSERT INTO thoughts (user_id, text, score, category, timestamp) VALUES (?, ?, ?, ?, ?)",
                   (user_id, text, score, category, timestamp))
    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM thoughts WHERE user_id = ?", (user_id,))
    count = cursor.fetchone()[0]

    response = f"✅ Сохранено в категорию: {category}.
Всего мыслей: {count}"
    if isinstance(context_source, Update):
        await context_source.message.reply_text(response)
    else:
        await context_source.edit_message_text(response)

    if count % 20 == 0:
        await send_stats(user_id, context_source)

async def send_stats(user_id, context_source):
    cursor.execute("SELECT timestamp, score FROM thoughts WHERE user_id = ?", (user_id,))
    data = cursor.fetchall()
    if not data:
        return

    df = pd.DataFrame(data, columns=["timestamp", "score"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")

    plt.figure(figsize=(10, 5))
    plt.plot(df["timestamp"], df["score"], marker="o")
    plt.title("Эмоциональный график")
    plt.xlabel("Дата")
    plt.ylabel("Оценка")
    plt.grid(True)

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)

    if isinstance(context_source, Update):
        await context_source.message.reply_photo(buf)
    else:
        await context_source.message.reply_photo(buf)

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    cursor.execute("SELECT * FROM thoughts WHERE user_id = ?", (user_id,))
    data = cursor.fetchall()
    df = pd.DataFrame(data, columns=["id", "user_id", "text", "score", "category", "timestamp"])
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    await update.message.reply_document(InputFile(buf, filename="my_thoughts.csv"))

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("export", export_data))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_thought))
app.add_handler(CallbackQueryHandler(handle_score, pattern="^score:"))
app.add_handler(CallbackQueryHandler(handle_category, pattern="^cat:"))
app.add_handler(MessageHandler(filters.TEXT & filters.USER, handle_new_category_text))
app.run_polling()
