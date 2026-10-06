import os
import asyncio
import csv
import io
import random
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

PRAISE = [
    "🎉 Отлично! Привычка отмечена.",
    "💪 Так держать! Ещё один шаг к цели.",
    "🔥 Супер! Ты справляешься.",
    "✨ Молодец! Продолжай в том же духе.",
    "👏 Класс! Привычка выполнена.",
    "🚀 Ты в деле! Так и надо.",
]

def now_msk():
    return datetime.utcnow() + timedelta(hours=3)

def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить привычку", callback_data="add_habit")
    kb.button(text="📋 Мои привычки", callback_data="my_habits")
    kb.button(text="📊 Статистика", callback_data="stats")
    kb.button(text="🏆 Топ привычек", callback_data="top")
    kb.button(text="📤 Экспорт", callback_data="export")
    kb.button(text="⏰ Мои напоминания", callback_data="my_reminders")
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
    name = message.from_user.first_name or "друг"
    await message.answer(
        f"👋 Привет, {name}!\n\n"
        "Я твой личный трекер привычек. Помогу не забывать о важном и следить за прогрессом.\n\n"
        "Что будем делать?",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "add_habit")
async def add_habit(callback: types.CallbackQuery):
    await edit_or_send(callback, "✍️ Напиши название привычки.\nНапример: «Зарядка» или «Читать 10 страниц»")
    await callback.answer()

@dp.message(F.text.regexp(r"^\d{2}:\d{2}$"))
async def save_time_for_habit(message: types.Message):
    user_id = message.from_user.id
    if user_id not in pending_reminder:
        sb.table("habits").insert({"user_id": user_id, "name": message.text}).execute()
        await message.answer("✅ Привычка сохранена!", reply_markup=main_menu())
        return
    habit_id = pending_reminder.pop(user_id)
    sb.table("habits").update({"remind_time": message.text}).eq("id", habit_id).eq("user_id", user_id).execute()
    await message.answer(
        f"⏰ Готово! Буду напоминать в {message.text} (по МСК).",
        reply_markup=main_menu()
    )

@dp.message(F.text & ~F.text.startswith("/"))
async def save_habit(message: types.Message):
    sb.table("habits").insert({"user_id": message.from_user.id, "name": message.text}).execute()
    await message.answer(
        f"✅ Привычка «{message.text}» добавлена!\n\n"
        "💡 Совет: поставь напоминание, чтобы не забывать.",
        reply_markup=main_menu()
    )

# === МОИ ПРИВЫЧКИ (с ❌/✅, процентом и датой) ===
@dp.callback_query(F.data == "my_habits")
async def my_habits(callback: types.CallbackQuery):
    res = sb.table("habits").select("id, name, remind_time").eq("user_id", callback.from_user.id).execute()
    habits = res.data
    if not habits:
        await edit_or_send(callback, "📭 У тебя пока нет привычек.\n\nДобавь первую — нажми «➕ Добавить привычку»", main_menu())
        await callback.answer()
        return

    today = now_msk().date()
    week_ago = today - timedelta(days=6)
    kb = InlineKeyboardBuilder()
    done_count = 0
    total = len(habits)

    for h in habits:
        done_today = sb.table("completions").select("id").eq("habit_id", h["id"]).eq("done_date", today.isoformat()).execute()
        is_done = bool(done_today.data)
        if is_done:
            done_count += 1
        mark = "✅" if is_done else "❌"
        remind = f" ⏰{h['remind_time']}" if h.get("remind_time") else ""
        kb.button(text=f"{mark} {h['name']}{remind}", callback_data=f"done_{h['id']}")
        kb.button(text="🗑", callback_data=f"del_{h['id']}")
    kb.button(text="🏠 Назад", callback_data="back_home")
    kb.adjust(2)

    lines = [f"📋 Мои привычки ({done_count} из {total} выполнено сегодня)\n"]
    for h in habits:
        all_dates = sb.table("completions").select("done_date").eq("habit_id", h["id"]).execute().data
        dates = [d["done_date"] for d in all_dates if d.get("done_date")]
        week_dates = [d for d in dates if d >= week_ago.isoformat()]
        week_count = len(week_dates)
        percent = round(week_count / 7 * 100)
        last = max(dates) if dates else "—"
        done_today = sb.table("completions").select("id").eq("habit_id", h["id"]).eq("done_date", today.isoformat()).execute()
        mark = "✅" if done_today.data else "❌"
        lines.append(f"{mark} {h['name']}")
        lines.append(f"   📅 За 7 дней: {week_count}/7 ({percent}%)")
        lines.append(f"   🕐 Последнее: {last}")
    lines.append("\nНажми на привычку, чтобы отметить.")
    text = "\n".join(lines)

    await edit_or_send(callback, text, kb.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("done_"))
async def mark_done(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    today = now_msk().date().isoformat()
    existing = sb.table("completions").select("id").eq("habit_id", habit_id).eq("done_date", today).execute()
    if existing.data:
        await callback.answer("⚠️ Ты уже отмечал это сегодня!")
        return
    habit = sb.table("habits").select("name").eq("id", habit_id).execute()
    habit_name = habit.data[0]["name"] if habit.data else "Привычка"
    sb.table("completions").insert({
        "habit_id": habit_id,
        "user_id": callback.from_user.id,
        "date": today,
        "done_date": today
    }).execute()
    await callback.message.answer(
        f"{random.choice(PRAISE)}\n\n"
        f"«{habit_name}» — выполнено! Так держать 💪"
    )
    await callback.answer()
    await my_habits(callback)

@dp.callback_query(F.data.startswith("del_"))
async def delete_habit(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    sb.table("completions").delete().eq("habit_id", habit_id).execute()
    sb.table("habits").delete().eq("id", habit_id).execute()
    await callback.answer("🗑 Привычка удалена.")
    await my_habits(callback)

# === СТАТИСТИКА ===
@dp.callback_query(F.data == "stats")
async def stats(callback: types.CallbackQuery):
    res = sb.table("habits").select("id, name").eq("user_id", callback.from_user.id).execute()
    habits = res.data
    if not habits:
        await edit_or_send(callback, "📊 Пока нет данных. Добавь привычки и отмечай выполнение!", main_menu())
        await callback.answer()
        return
    today = now_msk().date()
    text = "📊 Твоя статистика:\n\n"
    for h in habits:
        cnt = sb.table("completions").select("id", count="exact").eq("habit_id", h["id"]).execute()
        all_dates = sb.table("completions").select("done_date").eq("habit_id", h["id"]).execute().data
        dates = [d["done_date"] for d in all_dates if d.get("done_date")]
        streak = 0
        if dates:
            days = sorted(dates, reverse=True)
            check = today
            for d in days:
                if d == check.isoformat():
                    streak += 1
                    check -= timedelta(days=1)
                else:
                    break
        month_ago = today - timedelta(days=29)
        month_count = len([d for d in dates if d >= month_ago.isoformat()])
        month_percent = round(month_count / 30 * 100)
        last = max(dates) if dates else "—"
        fire = "🔥" * min(streak, 5) if streak > 0 else ""
        text += (
            f"• {h['name']}\n"
            f"   Всего: {cnt.count} раз\n"
            f"   Серия: {streak} {fire}\n"
            f"   За 30 дней: {month_percent}%\n"
            f"   Последнее: {last}\n\n"
        )
    text += "💡 Продолжай в том же духе!"
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Назад", callback_data="back_home")
    await edit_or_send(callback, text, kb.as_markup())
    await callback.answer()

# === ТОП ПРИВЫЧЕК ===
@dp.callback_query(F.data == "top")
async def top(callback: types.CallbackQuery):
    res = sb.table("habits").select("id, name").eq("user_id", callback.from_user.id).execute()
    habits = res.data
    if not habits:
        await edit_or_send(callback, "🏆 Пока нет данных.", main_menu())
        await callback.answer()
        return
    stats = []
    for h in habits:
        cnt = sb.table("completions").select("id", count="exact").eq("habit_id", h["id"]).execute()
        stats.append((h["name"], cnt.count))
    stats.sort(key=lambda x: x[1], reverse=True)
    text = "🏆 Топ твоих привычек:\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, cnt) in enumerate(stats):
        medal = medals[i] if i < 3 else f"{i+1}."
        text += f"{medal} {name} — {cnt} раз\n"
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Назад", callback_data="back_home")
    await edit_or_send(callback, text, kb.as_markup())
    await callback.answer()

# === ЭКСПОРТ ===
@dp.callback_query(F.data == "export")
async def export(callback: types.CallbackQuery):
    res = sb.table("habits").select("id, name").eq("user_id", callback.from_user.id).execute()
    habits = res.data
    if not habits:
        await edit_or_send(callback, "📤 Пока нечего экспортировать.", main_menu())
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
    await callback.message.answer_document(file, caption="📤 Вот твой экспорт!")
    await callback.answer()

# === НАПОМИНАНИЯ ===
@dp.callback_query(F.data == "my_reminders")
async def my_reminders(callback: types.CallbackQuery):
    res = sb.table("habits").select("id, name, remind_time").eq("user_id", callback.from_user.id).execute()
    habits = res.data
    if not habits:
        await edit_or_send(callback, "⏰ Сначала добавь привычки!", main_menu())
        await callback.answer()
        return
    kb = InlineKeyboardBuilder()
    for h in habits:
        remind = h.get("remind_time") or "нет"
        kb.button(text=f"⏰ {h['name']} — {remind}", callback_data=f"setr_{h['id']}")
    kb.button(text="🏠 Назад", callback_data="back_home")
    kb.adjust(1)
    await edit_or_send(callback, "⏰ Выбери привычку, чтобы поставить напоминание:", kb.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("setr_"))
async def set_reminder_for_habit(callback: types.CallbackQuery):
    habit_id = int(callback.data.split("_")[1])
    pending_reminder[callback.from_user.id] = habit_id
    await callback.message.answer("✍️ Напиши время в формате ЧЧ:ММ\nНапример: 09:00")
    await callback.answer()

@dp.callback_query(F.data == "back_home")
async def back_home(callback: types.CallbackQuery):
    await edit_or_send(callback, "🏠 Главное меню:", main_menu())
    await callback.answer()

async def reminder_loop():
    while True:
        now = now_msk().strftime("%H:%M")
        try:
            habits = sb.table("habits").select("user_id, name, remind_time").eq("remind_time", now).execute()
            for h in habits.data:
                text = f"⏰ Напоминание: {h['name']}\n\nНе забудь отметить выполнение! ✅"
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
