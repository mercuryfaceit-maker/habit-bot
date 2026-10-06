import os
import asyncio
from datetime import datetime
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from supabase import create_client

# === НАСТРОЙКИ ===
TOKEN = os.environ.get("TELEGRAM_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

bot = Bot(token=TOKEN)
dp = Dispatcher()
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить привычку", callback_data="add_habit")
    kb.button(text="📋 Мои привычки", callback_data="my_habits")
    kb.button(text="📊 Статистика", callback_data="stats")
    kb.adjust(1)
    return kb.as_markup()

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Привет! Я помогу отслеживать привычки.", reply_markup=main_menu())

@dp.callback_query(F.data == "add_habit")
async def add_habit(callback: types.CallbackQuery):
    await callback.message.answer("Напиши название привычки:")
    await callback.answer()

@dp.message(F.text & ~F.text.startswith("/"))
async def save_habit(message: types.Message):
    sb.table("habits").insert({
        "user_id": message.from_user.id,
        "name": message.text
    }).execute()
    await message.answer(f"✅ Привычка «{message.text}» сохранена!", reply_markup=main_menu())

@dp.callback_query(F.data == "my_habits")
async def my_habits(callback: types.CallbackQuery):
    res = sb.table("habits").select("id, name").eq("user_id", callback.from_user.id).execute()
    habits = res.data
    if not habits:
        await callback.message.answer("Нет привычек.", reply_markup=main_menu())
        return
    kb = InlineKeyboardBuilder()
    for h in habits:
        kb.button(text=f"✅ {h['name']}", callback_data=f"done_{h['id']}")
    kb.adjust(1)
    await callback.message.answer("Нажми, чтобы отметить:", reply_markup=kb.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("done_"))
async def mark_done(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    sb.table("completions").insert({
        "habit_id": habit_id,
        "user_id": callback.from_user.id,
        "date": datetime.now().date().isoformat()
    }).execute()
    await callback.message.answer("🎉 Отлично!", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "stats")
async def stats(callback: types.CallbackQuery):
    res = sb.table("habits").select("id, name").eq("user_id", callback.from_user.id).execute()
    habits = res.data
    text = "📊 Статистика:\n\n"
    for h in habits:
        cnt = sb.table("completions").select("id", count="exact").eq("habit_id", h["id"]).execute()
        text += f"• {h['name']}: {cnt.count} раз\n"
    await callback.message.answer(text, reply_markup=main_menu())
    await callback.answer()

# === FLASK ===
app = Flask(__name__)

@app.route("/")
@app.route("/health")
def health():
    return "OK"

async def run_bot():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import threading
    from werkzeug.serving import make_server

    def run_flask():
        server = make_server("0.0.0.0", int(os.environ.get("PORT", 10000)), app)
        server.serve_forever()

    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(run_bot())
