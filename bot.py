import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
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
                country TEXT,
                price INTEGER,
                status TEXT DEFAULT 'new',
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.commit()

async def get_banner():
    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = 'banner'")
        row = await cursor.fetchone()
        return row[0] if row else None

async def set_banner(file_id: str):
    async with aiosqlite.connect("database.db") as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('banner', ?)",
            (file_id,)
        )
        await db.commit()

# ====================== СОСТОЯНИЯ ======================

class AdminStates(StatesGroup):
    add_country_name = State()
    add_country_price = State()
    add_country_desc = State()
    reply_to_user = State()
    waiting_banner = State()

# ====================== КЛАВИАТУРЫ ======================

def main_menu_kb(is_admin: bool = False):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📱 Купить номер", callback_data="buy"))
    builder.row(InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders"))
    builder.row(InlineKeyboardButton(text="💬 Написать продавцу", callback_data="support"))
    builder.row(InlineKeyboardButton(text="ℹ️ Информация", callback_data="info"))
    if is_admin:
        builder.row(InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin"))
    return builder.as_markup()

def admin_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить страну", callback_data="add_country"))
    builder.row(InlineKeyboardButton(text="📋 Список стран", callback_data="list_countries"))
    builder.row(InlineKeyboardButton(text="📦 Все заказы", callback_data="all_orders"))
    builder.row(InlineKeyboardButton(text="🖼️ Загрузить баннер", callback_data="upload_banner"))
    builder.row(InlineKeyboardButton(text="📊 Статистика", callback_data="stats"))
    builder.row(InlineKeyboardButton(text="◀️ Главное меню", callback_data="main_menu"))
    return builder.as_markup()

def back_to_main_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu"))
    return builder.as_markup()

# ====================== СТАРТ ======================

@router.message(CommandStart())
async def cmd_start(message: Message):
    is_admin = message.from_user.id == ADMIN_ID
    banner = await get_banner()

    text = (
        f"👋 <b>Добро пожаловать!</b>\n\n"
        f"Привет, <b>{message.from_user.first_name}</b>!\n\n"
        "Я бот по продаже физических SIM-карт и номеров.\n"
        "Выбирай страну → оформляй заказ → получай номер."
    )

    if banner:
        await message.answer_photo(
            photo=banner,
            caption=text,
            parse_mode="HTML",
            reply_markup=main_menu_kb(is_admin)
        )
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb(is_admin))

@router.callback_query(F.data == "main_menu")
async def main_menu(callback: CallbackQuery):
    is_admin = callback.from_user.id == ADMIN_ID
    text = (
        f"👋 <b>Главное меню</b>\n\n"
        f"Привет, <b>{callback.from_user.first_name}</b>!\n"
        "Выбери нужный раздел:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_kb(is_admin))
    await callback.answer()

# ====================== ИНФОРМАЦИЯ ======================

@router.callback_query(F.data == "info")
async def info(callback: CallbackQuery):
    text = (
        "<b>ℹ️ Информация о магазине</b>\n\n"
        "• Продаём физические SIM-карты\n"
        "• Работаем по предоплате\n"
        "• Доставка / встреча — по договорённости\n\n"
        "По всем вопросам пишите через кнопку «Написать продавцу»"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_to_main_kb())
    await callback.answer()

# ====================== КАТАЛОГ ======================

@router.callback_query(F.data == "buy")
async def show_catalog(callback: CallbackQuery):
    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            "SELECT id, name, price FROM countries WHERE is_active = 1 ORDER BY name"
        )
        countries = await cursor.fetchall()

    if not countries:
        await callback.message.edit_text(
            "Сейчас нет доступных номеров.\nЗагляни позже.",
            reply_markup=back_to_main_kb()
        )
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    for c_id, name, price in countries:
        builder.row(InlineKeyboardButton(
            text=f"{name} — {price} ₽",
            callback_data=f"country_{c_id}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu"))

    await callback.message.edit_text(
        "<b>📱 Выбери страну / оператора:</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("country_"))
async def select_country(callback: CallbackQuery):
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
    text = f"<b>{name}</b>\n\nЦена: <b>{price} ₽</b>\n\n{desc or 'Описание отсутствует'}"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Оформить заказ", callback_data=f"order_{country_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="buy"))

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

# ====================== ОФОРМЛЕНИЕ ЗАКАЗА ======================

@router.callback_query(F.data.startswith("order_"))
async def make_order(callback: CallbackQuery):
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

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            """INSERT INTO orders (user_id, username, country, price, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                callback.from_user.id,
                callback.from_user.username,
                name,
                price,
                datetime.now().strftime("%Y-%m-%d %H:%M")
            )
        )
        order_id = cursor.lastrowid
        await db.commit()

    text = (
        f"✅ <b>Заказ #{order_id} принят!</b>\n\n"
        f"Страна: {name}\n"
        f"Цена: {price} ₽\n\n"
        "Скоро с тобой свяжется администратор."
    )

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_to_main_kb())

    # Уведомление админу
    text_admin = (
        f"🆕 <b>Новый заказ #{order_id}</b>\n\n"
        f"От: @{callback.from_user.username or 'нет'} (ID: {callback.from_user.id})\n"
        f"Страна: {name}\n"
        f"Цена: {price} ₽"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_{callback.from_user.id}"))
    builder.row(InlineKeyboardButton(text="📦 Статус", callback_data=f"status_{order_id}"))

    await bot.send_message(ADMIN_ID, text_admin, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

# ====================== МОИ ЗАКАЗЫ ======================

@router.callback_query(F.data == "my_orders")
async def my_orders(callback: CallbackQuery):
    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            "SELECT id, country, price, status, created_at FROM orders WHERE user_id = ? ORDER BY id DESC",
            (callback.from_user.id,)
        )
        orders = await cursor.fetchall()

    if not orders:
        await callback.message.edit_text(
            "У тебя пока нет заказов.",
            reply_markup=back_to_main_kb()
        )
        await callback.answer()
        return

    text = "<b>📦 Твои заказы:</b>\n\n"
    for o_id, country, price, status, created in orders:
        text += f"#{o_id} | {country} | {price} ₽ | <b>{status}</b> | {created}\n"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_to_main_kb())
    await callback.answer()

# ====================== ПОДДЕРЖКА ======================

@router.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "💬 <b>Написать продавцу</b>\n\n"
        "Просто напиши сообщение в чат — я передам его администратору.",
        parse_mode="HTML",
        reply_markup=back_to_main_kb()
    )
    await state.set_state(AdminStates.reply_to_user)
    await state.update_data(target_user=None)
    await callback.answer()

@router.message(AdminStates.reply_to_user)
async def process_message(message: Message, state: FSMContext):
    data = await state.get_data()
    target = data.get("target_user")

    if target:  # админ отвечает клиенту
        await bot.send_message(target, f"💬 <b>Ответ продавца:</b>\n\n{message.text}", parse_mode="HTML")
        await message.answer("Сообщение отправлено клиенту.")
    else:  # клиент пишет админу
        await bot.send_message(
            ADMIN_ID,
            f"💬 Сообщение от @{message.from_user.username or 'нет'} (ID: {message.from_user.id}):\n\n{message.text}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Ответить", callback_data=f"reply_{message.from_user.id}")]
            ])
        )
        await message.answer("Сообщение отправлено продавцу.", reply_markup=back_to_main_kb())

    await state.clear()

@router.callback_query(F.data.startswith("reply_"))
async def admin_reply_start(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[1])
    await state.update_data(target_user=user_id)
    await callback.message.answer("Напиши ответ клиенту:")
    await state.set_state(AdminStates.reply_to_user)
    await callback.answer()

# ====================== АДМИН-ПАНЕЛЬ ======================

@router.callback_query(F.data == "admin")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "⚙️ <b>Админ-панель</b>",
        parse_mode="HTML",
        reply_markup=admin_menu_kb()
    )
    await callback.answer()

@router.callback_query(F.data == "upload_banner")
async def upload_banner_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text(
        "🖼️ Отправь фото, которое будет показываться при /start",
        reply_markup=back_to_main_kb()
    )
    await state.set_state(AdminStates.waiting_banner)
    await callback.answer()

@router.message(AdminStates.waiting_banner, F.photo)
async def save_banner(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await set_banner(file_id)
    await message.answer("✅ Баннер успешно установлен!", reply_markup=main_menu_kb(True))
    await state.clear()

@router.callback_query(F.data == "add_country")
async def add_country_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("Название страны / оператора:")
    await state.set_state(AdminStates.add_country_name)
    await callback.answer()

@router.message(AdminStates.add_country_name)
async def add_country_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Цена в рублях (только число):")
    await state.set_state(AdminStates.add_country_price)

@router.message(AdminStates.add_country_price)
async def add_country_price(message: Message, state: FSMContext):
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
    data = await state.get_data()
    desc = message.text if message.text != "-" else ""

    async with aiosqlite.connect("database.db") as db:
        await db.execute(
            "INSERT INTO countries (name, price, description) VALUES (?, ?, ?)",
            (data["name"], data["price"], desc)
        )
        await db.commit()

    await message.answer(
        f"✅ Страна «{data['name']}» добавлена за {data['price']} ₽",
        reply_markup=admin_menu_kb()
    )
    await state.clear()

@router.callback_query(F.data == "list_countries")
async def list_countries(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute("SELECT id, name, price, is_active FROM countries ORDER BY name")
        countries = await cursor.fetchall()

    if not countries:
        await callback.message.edit_text("Список пуст.", reply_markup=admin_menu_kb())
        await callback.answer()
        return

    text = "<b>📋 Список стран:</b>\n\n"
    for c_id, name, price, active in countries:
        status = "✅" if active else "❌"
        text += f"{status} #{c_id} {name} — {price} ₽\n"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_menu_kb())
    await callback.answer()

@router.callback_query(F.data == "all_orders")
async def all_orders(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            "SELECT id, user_id, username, country, price, status, created_at FROM orders ORDER BY id DESC LIMIT 15"
        )
        orders = await cursor.fetchall()

    if not orders:
        await callback.message.edit_text("Заказов пока нет.", reply_markup=admin_menu_kb())
        await callback.answer()
        return

    text = "<b>📦 Последние заказы:</b>\n\n"
    for o_id, user_id, username, country, price, status, created in orders:
        text += (
            f"#{o_id} | @{username or user_id} | {country} | {price} ₽\n"
            f"Статус: <b>{status}</b> | {created}\n\n"
        )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_menu_kb())
    await callback.answer()

@router.callback_query(F.data == "stats")
async def stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute("SELECT COUNT(*) FROM orders")
        total = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM orders WHERE status = 'new'")
        new = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT SUM(price) FROM orders WHERE status IN ('paid', 'done')")
        money = (await cursor.fetchone())[0] or 0

    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"Всего заказов: {total}\n"
        f"Новых: {new}\n"
        f"Заработано: {money} ₽"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_menu_kb())
    await callback.answer()

# Статусы заказа
@router.callback_query(F.data.startswith("status_"))
async def change_status_start(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])

    builder = InlineKeyboardBuilder()
    for st in ["new", "paid", "shipped", "done", "cancelled"]:
        builder.row(InlineKeyboardButton(text=st, callback_data=f"setstatus_{order_id}_{st}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="all_orders"))

    await callback.message.edit_text(
        f"Выбери новый статус для заказа #{order_id}:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("setstatus_"))
async def set_status(callback: CallbackQuery):
    parts = callback.data.split("_")
    order_id = int(parts[1])
    new_status = parts[2]

    async with aiosqlite.connect("database.db") as db:
        await db.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
        cursor = await db.execute("SELECT user_id FROM orders WHERE id = ?", (order_id,))
        user_id = (await cursor.fetchone())[0]
        await db.commit()

    await bot.send_message(
        user_id,
        f"📦 Статус твоего заказа #{order_id} изменён на: <b>{new_status}</b>",
        parse_mode="HTML"
    )
    await callback.message.edit_text(
        f"✅ Статус заказа #{order_id} → <b>{new_status}</b>",
        parse_mode="HTML",
        reply_markup=admin_menu_kb()
    )
    await callback.answer()

# ====================== ЗАПУСК ======================

async def main():
    await init_db()
    logging.basicConfig(level=logging.INFO)
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
