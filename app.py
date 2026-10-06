import os
import asyncio
from datetime import datetime, timedelta
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from supabase import create_client

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
    kb.button(text="⏰ Настроить напоминание", callback_data="set_remind")
    kb.adjust(1)
    return kb.as_markup()

async def edit_or_send(callback, text, kb=None):
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)

@dp.message(Command("start"))
async def start(message: types.Message):
    sb.table("users").upsert({"user_id": message.from_user.id}).execute()
    await message.answer("Привет! Я помогу отслеживать привычки.", reply_markup=main_menu())

@dp.callback_query(F.data == "add_habit")
async def add_habit(callback: types.CallbackQuery):
    await edit_or_send(callback, "Напиши название привычки:")
    await callback.answer()

@dp.message(F.text & ~F.text.startswith("/") & ~F.text.regexp(r"^\d{2}:\d{2}$"))
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
        await edit_or_send(callback, "У тебя пока нет привычек.", main_menu())
        await callback.answer()
        return
    kb = InlineKeyboardBuilder()
    for h in habits:
        kb.button(text=f"✅ {h['name']}", callback_data=f"done_{h['id']}")
        kb.button(text="🗑", callback_data=f"del_{h['id']}")
    kb.button(text="🏠 Назад", callback_data="back_home")
    kb.adjust(2)
    await edit_or_send(callback, "Нажми, чтобы отметить. Или 🗑, чтобы удалить:", kb.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("done_"))
async def mark_done(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    sb.table("completions").insert({
        "habit_id": habit_id,
        "user_id": callback.from_user.id,
        "date": (datetime.utcnow() + timedelta(hours=3)).date().isoformat()
    }).execute()
    await callback.answer("🎉 Отмечено!")
    await my_habits(callback)

@dp.callback_query(F.data.startswith("del_"))
async def delete_habit(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    sb.table("completions").delete().eq("habit_id", habit_id).execute()
    sb.table("habits").delete().eq("id", habit_id).execute()
    await callback.answer("🗑 Удалено.")
    await my_habits(callback)

@dp.callback_query(F.data == "stats")
async def stats(callback: types.CallbackQuery):
    res = sb.table("habits").select("id, name").eq("user_id", callback.from_user.id).execute()
    habits = res.data
    if not habits:
        await edit_or_send(callback, "Нет привычек.", main_menu())
        await callback.answer()
        return
    text = "📊 Статистика:\n\n"
    for h in habits:
        cnt = sb.table("completions").select("id", count="exact").eq("habit_id", h["id"]).execute()
        text += f"• {h['name']}: {cnt.count} раз\n"
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Назад", callback_data="back_home")
    await edit_or_send(callback, text, kb.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "set_remind")
async def set_remind(callback: types.CallbackQuery):
    await edit_or_send(callback, "Напиши время напоминания в формате ЧЧ:ММ (по Минску):")
    await callback.answer()

@dp.message(F.text.regexp(r"^\d{2}:\d{2}$"))
async def save_remind(message: types.Message):
    sb.table("users").upsert({
        "user_id": message.from_user.id,
        "remind_time": message.text
    }).execute()
    await message.answer(f"⏰ Напоминание установлено на {message.text} (по Минску)", reply_markup=main_menu())

@dp.callback_query(F.data == "back_home")
async def back_home(callback: types.CallbackQuery):
    await edit_or_send(callback, "Главное меню:", main_menu())
    await callback.answer()

# === НАПОМИНАНИЯ (с поправкой на UTC+3) ===
async def reminder_loop():
    while True:
        now = (datetime.utcnow() + timedelta(hours=3)).strftime("%H:%M")
        try:
            users = sb.table("users").select("user_id, remind_time").eq("remind_time", now).execute()
            for u in users.data:
                habits = sb.table("habits").select("name").eq("user_id", u["user_id"]).execute()
                if habits.data:
                    text = "⏰ Напоминание! Не забудь:\n" + "\n".join(f"• {h['name']}" for h in habits.data)
                    try:
                        await bot.send_message(u["user_id"], text)
                    except Exception:
                        pass
        except Exception:
            pass
        await asyncio.sleep(60)

# === FLASK ===
app = Flask(__name__)

@app.route("/")
@app.route("/health")
def health():
    return "OK"

async def run_bot():
    asyncio.create_task(reminder_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    import threading
    from werkzeug.serving import make_server

    def run_flask():
        server = make_server("0.0.0.0", int(os.environ.get("PORT", 10000)), app)
        server.serve_forever()

    threading.Thread(target=run_flask, daemon=True).start()
    asyncio.run(run_bot())
