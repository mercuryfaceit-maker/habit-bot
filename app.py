import os
import asyncio
import sqlite3
from datetime import datetime
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN = os.environ.get("TELEGRAM_TOKEN")
bot = Bot(token=TOKEN)
dp = Dispatcher()

def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить привычку", callback_data="add_habit")
    kb.button(text="📋 Мои привычки", callback_data="my_habits")
    kb.button(text="📊 Статистика", callback_data="stats")
    kb.adjust(1)
    return kb.as_markup()

def init_db():
    conn = sqlite3.connect("habits.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS habits (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS completions (id INTEGER PRIMARY KEY AUTOINCREMENT, habit_id INTEGER, user_id INTEGER, date TEXT)")
    conn.commit()
    conn.close()

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Привет! Я помогу отслеживать привычки.", reply_markup=main_menu())

@dp.callback_query(F.data == "add_habit")
async def add_habit(callback: types.CallbackQuery):
    await callback.message.answer("Напиши название привычки:")
    await callback.answer()

@dp.message(F.text & ~F.text.startswith("/"))
async def save_habit(message: types.Message):
    conn = sqlite3.connect("habits.db")
    conn.execute("INSERT INTO habits (user_id, name) VALUES (?, ?)", (message.from_user.id, message.text))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Привычка «{message.text}» сохранена!", reply_markup=main_menu())

@dp.callback_query(F.data == "my_habits")
async def my_habits(callback: types.CallbackQuery):
    conn = sqlite3.connect("habits.db")
    habits = conn.execute("SELECT id, name FROM habits WHERE user_id = ?", (callback.from_user.id,)).fetchall()
    conn.close()
    if not habits:
        await callback.message.answer("Нет привычек.", reply_markup=main_menu())
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
    conn = sqlite3.connect("habits.db")
    conn.execute("INSERT INTO completions (habit_id, user_id, date) VALUES (?, ?, ?)",
                 (habit_id, callback.from_user.id, datetime.now().date().isoformat()))
    conn.commit()
    conn.close()
    await callback.message.answer("🎉 Отлично!", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "stats")
async def stats(callback: types.CallbackQuery):
    conn = sqlite3.connect("habits.db")
    habits = conn.execute("SELECT id, name FROM habits WHERE user_id = ?", (callback.from_user.id,)).fetchall()
    text = "📊 Статистика:\n\n"
    for habit_id, name in habits:
        count = conn.execute("SELECT COUNT(*) FROM completions WHERE habit_id = ?", (habit_id,)).fetchone()[0]
        text += f"• {name}: {count} раз\n"
    conn.close()
    await callback.message.answer(text, reply_markup=main_menu())
    await callback.answer()

# === FLASK ДЛЯ HEALTH CHECK ===
app = Flask(__name__)

@app.route("/")
@app.route("/health")
def health():
    return "OK"

# === ЗАПУСК БОТА В ОСНОВНОМ ПОТОКЕ ===
async def run_bot():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Запускаем бота и Flask в одном asyncio-цикле
    import threading
    from werkzeug.serving import make_server

    def run_flask():
        server = make_server("0.0.0.0", int(os.environ.get("PORT", 10000)), app)
        server.serve_forever()

    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(run_bot())
