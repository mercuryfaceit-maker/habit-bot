import os
import asyncio
import csv
import io
from datetime import datetime, timedelta
from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import BufferedInputFile
from supabase import create_client

TOKEN = os.environ.get("TELEGRAM_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

bot = Bot(token=TOKEN)
dp = Dispatcher()
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

pending_reminder = {}

def now_msk():
    return datetime.utcnow() + timedelta(hours=3)

def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="Добавить привычку", callback_data="add_habit")
    kb.button(text="Мои привычки", callback_data="my_habits")
    kb.button(text="Статистика", callback_data="stats")
    kb.button(text="Экспорт", callback_data="export")
    kb.button(text="Мои напоминания", callback_data="my_reminders")
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

@dp.message(F.text.regexp(r"^\d{2}:\d{2}$"))
async def save_time_for_habit(message: types.Message):
    user_id = message.from_user.id
    if user_id not in pending_reminder:
        sb.table("habits").insert({"user_id": user_id, "name": message.text}).execute()
        await message.answer("Привычка сохранена!", reply_markup=main_menu())
        return
    habit_id = pending_reminder.pop(user_id)
    sb.table("habits").update({"remind_time": message.text}).eq("id", habit_id).eq("user_id", user_id).execute()
    await message.answer(f"Напоминание установлено на {message.text} (по МСК)", reply_markup=main_menu())

@dp.message(F.text & ~F.text.startswith("/"))
async def save_habit(message: types.Message):
    sb.table("habits").insert({"user_id": message.from_user.id, "name": message.text}).execute()
    await message.answer("Привычка сохранена!", reply_markup=main_menu())

@dp.callback_query(F.data == "my_habits")
async def my_habits(callback: types.CallbackQuery):
    res = sb.table("habits").select("id, name, remind_time").eq("user_id", callback.from_user.id).execute()
    habits = res.data
    if not habits:
        await edit_or_send(callback, "У тебя пока нет привычек.", main_menu())
        await callback.answer()
        return
    kb = InlineKeyboardBuilder()
    for h in habits:
        remind = f" [{h['remind_time']}]" if h.get("remind_time") else ""
        kb.button(text=f"{h['name']}{remind}", callback_data=f"done_{h['id']}")
        kb.button(text="Удалить", callback_data=f"del_{h['id']}")
    kb.button(text="Назад", callback_data="back_home")
    kb.adjust(2)
    await edit_or_send(callback, "Нажми, чтобы отметить. Или Удалить.", kb.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("done_"))
async def mark_done(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    today = now_msk().date().isoformat()
    existing = sb.table("completions").select("id").eq("habit_id", habit_id).eq("done_date", today).execute()
    if existing.data:
        await callback.answer("Уже отмечено сегодня!")
        return
    sb.table("completions").insert({
        "habit_id": habit_id,
        "user_id": callback.from_user.id,
        "date": today,
        "done_date": today
    }).execute()
    await callback.answer("Отмечено!")
    await my_habits(callback)

@dp.callback_query(F.data.startswith("del_"))
async def delete_habit(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    sb.table("completions").delete().eq("habit_id", habit_id).execute()
    sb.table("habits").delete().eq("id", habit_id).execute()
    await callback.answer("Удалено.")
    await my_habits(callback)

@dp.callback_query(F.data == "stats")
async def stats(callback: types.CallbackQuery):
    res = sb.table("habits").select("id, name").eq("user_id", callback.from_user.id).execute()
    habits = res.data
    if not habits:
        await edit_or_send(callback, "Нет привычек.", main_menu())
        await callback.answer()
        return
    text = "Статистика:\n\n"
    for h in habits:
        cnt = sb.table("completions").select("id", count="exact").eq("habit_id", h["id"]).execute()
        dates = sb.table("completions").select("done_date").eq("habit_id", h["id"]).execute().data
        streak = 0
        if dates:
            days = sorted([d["done_date"] for d in dates if d.get("done_date")], reverse=True)
            check = now_msk().date()
            for d in days:
                if d == check.isoformat():
                    streak += 1
                    check -= timedelta(days=1)
                else:
                    break
        text += f"- {h['name']}: {cnt.count} раз, серия {streak}\n"
    kb = InlineKeyboardBuilder()
    kb.button(text="Назад", callback_data="back_home")
    await edit_or_send(callback, text, kb.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "export")
async def export(callback: types.CallbackQuery):
    res = sb.table("habits").select("id, name").eq("user_id", callback.from_user.id).execute()
    habits = res.data
    if not habits:
        await edit_or_send(callback, "Нет данных для экспорта.", main_menu())
        await callback.answer()
        return
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Привычка", "Дата"])
    for h in habits:
        dates = sb.table("completions").select("done_date").eq("habit_id", h["id"]).execute().data
        for d in dates:
            writer.writerow([h["name"], d.get("done_date", "")])
    file = BufferedInputFile(output.getvalue().encode("utf-8"), filename="habits.csv")
    await callback.message.answer_document(file)
    await callback.answer()

@dp.callback_query(F.data == "my_reminders")
async def my_reminders(callback: types.CallbackQuery):
    res = sb.table("habits").select("id, name, remind_time").eq("user_id", callback.from_user.id).execute()
    habits = res.data
    if not habits:
        await edit_or_send(callback, "Сначала добавь привычки.", main_menu())
        await callback.answer()
        return
    kb = InlineKeyboardBuilder()
    for h in habits:
        remind = h.get("remind_time") or "нет"
        kb.button(text=f"{h['name']} - {remind}", callback_data=f"setr_{h['id']}")
    kb.button(text="Назад", callback_data="back_home")
    kb.adjust(1)
    await edit_or_send(callback, "Выбери привычку:", kb.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("setr_"))
async def set_reminder_for_habit(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    pending_reminder[callback.from_user.id] = habit_id
    await callback.message.answer("Введи время в формате ЧЧ:ММ (например, 09:00):")
    await callback.answer()

@dp.callback_query(F.data == "back_home")
async def back_home(callback: types.CallbackQuery):
    await edit_or_send(callback, "Главное меню:", main_menu())
    await callback.answer()

async def reminder_loop():
    while True:
        now = now_msk().strftime("%H:%M")
        try:
            habits = sb.table("habits").select("user_id, name, remind_time").eq("remind_time", now).execute()
            for h in habits.data:
                text = f"Напоминание: {h['name']}"
                try:
                    await bot.send_message(h["user_id"], text)
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(60)

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
