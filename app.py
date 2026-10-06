import os
import asyncio
import sqlite3
import threading
from datetime import datetime
from flask import Flask

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# === НАСТРОЙКИ ===
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# === БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect("habits.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS habits
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS completions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, habit_id INTEGER, user_id INTEGER, date TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, remind_time TEXT DEFAULT '09:00')""")
    conn.commit()
    conn.close()

# === БОТ ===
bot = Bot(token=TOKEN)
dp = Dispatcher()

def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить привычку", callback_data="add_habit")
    kb.button(text="📋 Мои привычки", callback_data="my_habits")
    kb.button(text="📊 Статистика", callback_data="stats")
    kb.adjust(1)
    return kb.as_markup()

@dp.message(Command("start"))
async def start(message: types.Message):
    conn = sqlite3.connect("habits.db")
    conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
    conn.commit()
    conn.close()
    await message.answer("Привет! Я помогу отслеживать привычки.", reply_markup=main_menu())

@dp.callback_query(F.data == "add_habit")
async def add_habit(callback: types.CallbackQuery):
    await callback.message.answer("Напиши название привычки (например, «Зарядка»):")
    await callback.answer()

@dp.message(F.text & ~F.text.startswith("/"))
async def save_habit(message: types.Message):
    conn = sqlite3.connect("habits.db")
    conn.execute("INSERT INTO habits (user_id, name, created_at) VALUES (?, ?, ?)",
                 (message.from_user.id, message.text, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Привычка «{message.text}» сохранена!", reply_markup=main_menu())

@dp.callback_query(F.data == "my_habits")
async def my_habits(callback: types.CallbackQuery):
    conn = sqlite3.connect("habits.db")
    habits = conn.execute("SELECT id, name FROM habits WHERE user_id = ?", (callback.from_user.id,)).fetchall()
    conn.close()
    if not habits:
        await callback.message.answer("У тебя пока нет привычек.", reply_markup=main_menu())
        return
    kb = InlineKeyboardBuilder()
    for habit_id, name in habits:
        kb.button(text=f"✅ {name}", callback_data=f"done_{habit_id}")
    kb.adjust(1)
    await callback.message.answer("Нажми, чтобы отметить:", reply_markup=kb.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("done_"))
async def mark_done(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    today = datetime.now().date().isoformat()
    conn = sqlite3.connect("habits.db")
    conn.execute("INSERT INTO completions (habit_id, user_id, date) VALUES (?, ?, ?)",
                 (habit_id, callback.from_user.id, today))
    conn.commit()
    conn.close()
    await callback.message.answer("🎉 Отлично!", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "stats")
async def stats(callback: types.CallbackQuery):
    conn = sqlite3.connect("habits.db")
    habits = conn.execute("SELECT id, name FROM habits WHERE user_id = ?", (callback.from_user.id,)).fetchall()
    text = "📊 Твоя статистика:\n\n"
    for habit_id, name in habits:
        count = conn.execute("SELECT COUNT(*) FROM completions WHERE habit_id = ?", (habit_id,)).fetchone()[0]
        text += f"• {name}: {count} раз\n"
    conn.close()
    await callback.message.answer(text, reply_markup=main_menu())
    await callback.answer()

# === ЗАПУСК ===
app = Flask(__name__)

@app.route("/health")
def health():
    return "OK"

def run_bot():
    init_db()
    asyncio.run(dp.start_polling(bot))

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
