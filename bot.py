import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv
import aiosqlite

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ====================== БАЗА ДАННЫХ ======================

async def init_db():
    async with aiosqlite.connect("database.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS countries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                price INTEGER NOT NULL,
                description TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                country TEXT,
                price INTEGER,
                city TEXT,
                delivery TEXT,
                comment TEXT,
                status TEXT DEFAULT 'new',
                created_at TEXT,
                admin_note TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                from_admin INTEGER,
                text TEXT,
                created_at TEXT
            )
        """)
        await db.commit()

# ====================== СОСТОЯНИЯ FSM ======================

class OrderStates(StatesGroup):
    waiting_full_name = State()
    waiting_city = State()
    waiting_delivery = State()
    waiting_comment = State()

class AdminStates(StatesGroup):
    add_country_name = State()
    add_country_price = State()
    add_country_desc = State()
    reply_to_user = State()
    change_status = State()

# ====================== КЛАВИАТУРЫ ======================

def main_kb(is_admin: bool = False):
    builder = ReplyKeyboardBuilder()
    builder.button(text="📱 Купить номер")
    builder.button(text="📦 Мои заказы")
    builder.button(text="💬 Написать продавцу")
    if is_admin:
        builder.button(text="⚙️ Админ-панель")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def admin_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Добавить страну")
    builder.button(text="📋 Список стран")
    builder.button(text="📦 Все заказы")
    builder.button(text="📊 Статистика")
    builder.button(text="◀️ В меню")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

# ====================== КОМАНДЫ ======================

@router.message(CommandStart())
async def cmd_start(message: Message):
    is_admin = message.from_user.id == ADMIN_ID
    await message.answer(
        f"Привет, {message.from_user.first_name}!\n\n"
        "Я бот по продаже физических SIM-карт и номеров.\n"
        "Выбирай страну → оформляй заказ → получай номер.",
        reply_markup=main_kb(is_admin)
    )

@router.message(F.text == "◀️ В меню")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    is_admin = message.from_user.id == ADMIN_ID
    await message.answer("Главное меню", reply_markup=main_kb(is_admin))

# ====================== КАТАЛОГ ======================

@router.message(F.text == "📱 Купить номер")
async def show_catalog(message: Message):
    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            "SELECT id, name, price, description FROM countries WHERE is_active = 1 ORDER BY name"
        )
        countries = await cursor.fetchall()

    if not countries:
        await message.answer("Сейчас нет доступных номеров. Загляни позже.")
        return

    builder = InlineKeyboardBuilder()
    for c_id, name, price, desc in countries:
        builder.button(
            text=f"{name} — {price} ₽",
            callback_data=f"country_{c_id}"
        )
    builder.adjust(1)

    await message.answer("Выбери страну / оператора:", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("country_"))
async def select_country(callback: CallbackQuery, state: FSMContext):
    country_id = int(callback.data.split("_")[1])

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            "SELECT name, price, description FROM countries WHERE id = ?", (country_id,)
        )
        row = await cursor.fetchone()

    if not row:
        await callback.answer("Страна больше не доступна", show_alert=True)
        return

    name, price, desc = row
    text = f"<b>{name}</b>\nЦена: <b>{price} ₽</b>\n\n{desc or 'Описание отсутствует'}"

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Оформить заказ", callback_data=f"order_{country_id}")
    builder.button(text="◀️ Назад", callback_data="back_catalog")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "back_catalog")
async def back_catalog(callback: CallbackQuery):
    await show_catalog(callback.message)
    await callback.answer()

# ====================== ОФОРМЛЕНИЕ ЗАКАЗА ======================

@router.callback_query(F.data.startswith("order_"))
async def start_order(callback: CallbackQuery, state: FSMContext):
    country_id = int(callback.data.split("_")[1])

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            "SELECT name, price FROM countries WHERE id = ?", (country_id,)
        )
        row = await cursor.fetchone()

    if not row:
        await callback.answer("Ошибка", show_alert=True)
        return

    name, price = row
    await state.update_data(country=name, price=price, country_id=country_id)

    await callback.message.answer(
        f"Оформляем заказ на: <b>{name}</b> ({price} ₽)\n\n"
        "Напиши своё <b>ФИО</b> (как в паспорте):",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )
    await state.set_state(OrderStates.waiting_full_name)
    await callback.answer()

@router.message(OrderStates.waiting_full_name)
async def process_full_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено", reply_markup=main_kb(message.from_user.id == ADMIN_ID))
        return

    await state.update_data(full_name=message.text)
    await message.answer("В каком городе ты находишься?")
    await state.set_state(OrderStates.waiting_city)

@router.message(OrderStates.waiting_city)
async def process_city(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено", reply_markup=main_kb(message.from_user.id == ADMIN_ID))
        return

    await state.update_data(city=message.text)
    await message.answer(
        "Как удобнее получить номер?\n"
        "(самовывоз / доставка СДЭК / почта / встреча и т.д.)"
    )
    await state.set_state(OrderStates.waiting_delivery)

@router.message(OrderStates.waiting_delivery)
async def process_delivery(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено", reply_markup=main_kb(message.from_user.id == ADMIN_ID))
        return

    await state.update_data(delivery=message.text)
    await message.answer("Комментарий к заказу (можно пропустить, написав «-»):")
    await state.set_state(OrderStates.waiting_comment)

@router.message(OrderStates.waiting_comment)
async def process_comment(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено", reply_markup=main_kb(message.from_user.id == ADMIN_ID))
        return

    data = await state.get_data()
    comment = message.text if message.text != "-" else ""

    # Сохраняем заказ
    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            """INSERT INTO orders 
               (user_id, username, full_name, country, price, city, delivery, comment, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message.from_user.id,
                message.from_user.username,
                data["full_name"],
                data["country"],
                data["price"],
                data["city"],
                data["delivery"],
                comment,
                datetime.now().strftime("%Y-%m-%d %H:%M")
            )
        )
        order_id = cursor.lastrowid
        await db.commit()

    # Уведомляем клиента
    await message.answer(
        f"✅ Заказ <b>#{order_id}</b> принят!\n\n"
        f"Страна: {data['country']}\n"
        f"Цена: {data['price']} ₽\n"
        f"ФИО: {data['full_name']}\n"
        f"Город: {data['city']}\n"
        f"Получение: {data['delivery']}\n\n"
        "Скоро с тобой свяжется администратор.",
        parse_mode="HTML",
        reply_markup=main_kb(message.from_user.id == ADMIN_ID)
    )

    # Уведомляем админа
    text_admin = (
        f"🆕 <b>Новый заказ #{order_id}</b>\n\n"
        f"От: @{message.from_user.username or 'нет'} (ID: {message.from_user.id})\n"
        f"Страна: {data['country']}\n"
        f"Цена: {data['price']} ₽\n"
        f"ФИО: {data['full_name']}\n"
        f"Город: {data['city']}\n"
        f"Получение: {data['delivery']}\n"
        f"Комментарий: {comment or '—'}"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Ответить", callback_data=f"reply_{message.from_user.id}")
    builder.button(text="📦 Статус", callback_data=f"status_{order_id}")

    await bot.send_message(ADMIN_ID, text_admin, parse_mode="HTML", reply_markup=builder.as_markup())
    await state.clear()

# ====================== МОИ ЗАКАЗЫ ======================

@router.message(F.text == "📦 Мои заказы")
async def my_orders(message: Message):
    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            "SELECT id, country, price, status, created_at FROM orders WHERE user_id = ? ORDER BY id DESC",
            (message.from_user.id,)
        )
        orders = await cursor.fetchall()

    if not orders:
        await message.answer("У тебя пока нет заказов.")
        return

    text = "<b>Твои заказы:</b>\n\n"
    for o_id, country, price, status, created in orders:
        text += f"#{o_id} | {country} | {price} ₽ | <b>{status}</b> | {created}\n"

    await message.answer(text, parse_mode="HTML")

# ====================== ПЕРЕПИСКА С АДМИНОМ ======================

@router.message(F.text == "💬 Написать продавцу")
async def start_chat(message: Message, state: FSMContext):
    await message.answer(
        "Напиши сообщение продавцу. Он получит его и сможет ответить.",
        reply_markup=cancel_kb()
    )
    await state.set_state(AdminStates.reply_to_user)
    await state.update_data(target_user=None)  # клиент пишет админу

@router.message(AdminStates.reply_to_user)
async def process_message_to_admin(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено", reply_markup=main_kb(message.from_user.id == ADMIN_ID))
        return

    data = await state.get_data()
    target = data.get("target_user")

    if target:  # админ отвечает клиенту
        await bot.send_message(target, f"💬 <b>Ответ продавца:</b>\n\n{message.text}", parse_mode="HTML")
        await message.answer("Сообщение отправлено клиенту.", reply_markup=admin_kb())
    else:  # клиент пишет админу
        await bot.send_message(
            ADMIN_ID,
            f"💬 Сообщение от @{message.from_user.username or 'нет'} (ID: {message.from_user.id}):\n\n{message.text}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Ответить", callback_data=f"reply_{message.from_user.id}")]
            ])
        )
        await message.answer("Сообщение отправлено продавцу.", reply_markup=main_kb(False))

    await state.clear()

@router.callback_query(F.data.startswith("reply_"))
async def admin_reply_start(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[1])
    await state.update_data(target_user=user_id)
    await callback.message.answer("Напиши ответ клиенту:", reply_markup=cancel_kb())
    await state.set_state(AdminStates.reply_to_user)
    await callback.answer()

# ====================== АДМИН-ПАНЕЛЬ ======================

@router.message(F.text == "⚙️ Админ-панель")
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Админ-панель", reply_markup=admin_kb())

@router.message(F.text == "➕ Добавить страну")
async def add_country_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Название страны / оператора:", reply_markup=cancel_kb())
    await state.set_state(AdminStates.add_country_name)

@router.message(AdminStates.add_country_name)
async def add_country_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено", reply_markup=admin_kb())
        return
    await state.update_data(name=message.text)
    await message.answer("Цена в рублях (только число):")
    await state.set_state(AdminStates.add_country_price)

@router.message(AdminStates.add_country_price)
async def add_country_price(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено", reply_markup=admin_kb())
        return
    try:
        price = int(message.text)
    except ValueError:
        await message.answer("Нужно число. Попробуй ещё раз:")
        return
    await state.update_data(price=price)
    await message.answer("Описание (можно «-»):")
    await state.set_state(AdminStates.add_country_desc)

@router.message(AdminStates.add_country_desc)
async def add_country_desc(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено", reply_markup=admin_kb())
        return

    data = await state.get_data()
    desc = message.text if message.text != "-" else ""

    async with aiosqlite.connect("database.db") as db:
        await db.execute(
            "INSERT INTO countries (name, price, description) VALUES (?, ?, ?)",
            (data["name"], data["price"], desc)
        )
        await db.commit()

    await message.answer(f"✅ Страна «{data['name']}» добавлена за {data['price']} ₽", reply_markup=admin_kb())
    await state.clear()

@router.message(F.text == "📋 Список стран")
async def list_countries(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute("SELECT id, name, price, is_active FROM countries ORDER BY name")
        countries = await cursor.fetchall()

    if not countries:
        await message.answer("Список пуст.")
        return

    text = "<b>Список стран:</b>\n\n"
    for c_id, name, price, active in countries:
        status = "✅" if active else "❌"
        text += f"{status} #{c_id} {name} — {price} ₽\n"

    await message.answer(text, parse_mode="HTML")

@router.message(F.text == "📦 Все заказы")
async def all_orders(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            "SELECT id, user_id, username, country, price, status, created_at FROM orders ORDER BY id DESC LIMIT 20"
        )
        orders = await cursor.fetchall()

    if not orders:
        await message.answer("Заказов пока нет.")
        return

    text = "<b>Последние заказы:</b>\n\n"
    for o_id, user_id, username, country, price, status, created in orders:
        text += (
            f"#{o_id} | @{username or user_id} | {country} | {price} ₽\n"
            f"Статус: <b>{status}</b> | {created}\n\n"
        )
    await message.answer(text, parse_mode="HTML")

@router.message(F.text == "📊 Статистика")
async def stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute("SELECT COUNT(*) FROM orders")
        total = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM orders WHERE status = 'new'")
        new = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT SUM(price) FROM orders WHERE status IN ('paid', 'done')")
        money = (await cursor.fetchone())[0] or 0

    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"Всего заказов: {total}\n"
        f"Новых: {new}\n"
        f"Заработано: {money} ₽",
        parse_mode="HTML"
    )

# Изменение статуса заказа
@router.callback_query(F.data.startswith("status_"))
async def change_status_start(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[1])
    await state.update_data(order_id=order_id)

    builder = InlineKeyboardBuilder()
    for st in ["new", "paid", "shipped", "done", "cancelled"]:
        builder.button(text=st, callback_data=f"setstatus_{st}")
    builder.adjust(2)

    await callback.message.answer(f"Выбери новый статус для заказа #{order_id}:", reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("setstatus_"))
async def set_status(callback: CallbackQuery, state: FSMContext):
    new_status = callback.data.split("_")[1]
    data = await state.get_data()
    order_id = data["order_id"]

    async with aiosqlite.connect("database.db") as db:
        await db.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
        cursor = await db.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,))
        user_id = (await cursor.fetchone())[0]
        await db.commit()

    await bot.send_message(user_id, f"📦 Статус твоего заказа #{order_id} изменён на: <b>{new_status}</b>", parse_mode="HTML")
    await callback.message.answer(f"Статус заказа #{order_id} → {new_status}")
    await state.clear()
    await callback.answer()

# ====================== ЗАПУСК ======================

async def main():
    await init_db()
    logging.basicConfig(level=logging.INFO)
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())