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
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile
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

def main_kb(is_admin: bool = False):
    builder = ReplyKeyboardBuilder()
    builder.button(text="📱 Купить номер")
    builder.button(text="📦 Мои заказы")
    builder.button(text="💬 Написать продавцу")
    builder.button(text="ℹ️ Информация")
    if is_admin:
        builder.button(text="⚙️ Админ-панель")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def admin_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Добавить страну")
    builder.button(text="📋 Список стран")
    builder.button(text="📦 Все заказы")
    builder.button(text="🖼️ Загрузить баннер")
    builder.button(text="📊 Статистика")
    builder.button(text="◀️ В меню")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

# ====================== СТАРТ ======================

@router.message(CommandStart())
async def cmd_start(message: Message):
    is_admin = message.from_user.id == ADMIN_ID
    banner = await get_banner()

    text = (
        f"Привет, <b>{message.from_user.first_name}</b>!\n\n"
        "Я бот по продаже физических SIM-карт и номеров.\n"
        "Выбирай страну → оформляй заказ → получай номер."
    )

    if banner:
        await message.answer_photo(
            photo=banner,
            caption=text,
            parse_mode="HTML",
            reply_markup=main_kb(is_admin)
        )
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=main_kb(is_admin))

@router.message(F.text == "◀️ В меню")
async def back_to_menu(message: Message, state: FSMContext):
    await state.clear()
    is_admin = message.from_user.id == ADMIN_ID
    await message.answer("Главное меню", reply_markup=main_kb(is_admin))

@router.message(F.text == "ℹ️ Информация")
async def info(message: Message):
    await message.answer(
        "<b>Информация о магазине</b>\n\n"
        "• Продаём физические SIM-карты\n"
        "• Работаем по предоплате\n"
        "• Доставка / встреча — по договорённости\n\n"
        "По всем вопросам пишите через кнопку «Написать продавцу»",
        parse_mode="HTML"
    )

# ====================== КАТАЛОГ ======================

@router.message(F.text == "📱 Купить номер")
async def show_catalog(message: Message):
    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            "SELECT id, name, price FROM countries WHERE is_active = 1 ORDER BY name"
        )
        countries = await cursor.fetchall()

    if not countries:
        await message.answer("Сейчас нет доступных номеров. Загляни позже.")
        return

    builder = InlineKeyboardBuilder()
    for c_id, name, price in countries:
        builder.button(text=f"{name} — {price} ₽", callback_data=f"country_{c_id}")
    builder.adjust(1)

    await message.answer("Выбери страну / оператора:", reply_markup=builder.as_markup())

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

# ====================== ОФОРМЛЕНИЕ ЗАКАЗА (упрощённое) ======================

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

    await callback.message.answer(
        f"✅ Заказ <b>#{order_id}</b> принят!\n\n"
        f"Страна: {name}\n"
        f"Цена: {price} ₽\n\n"
        "Скоро с тобой свяжется администратор.",
        parse_mode="HTML"
    )

    # Уведомление админу
    text_admin = (
        f"🆕 <b>Новый заказ #{order_id}</b>\n\n"
        f"От: @{callback.from_user.username or 'нет'} (ID: {callback.from_user.id})\n"
        f"Страна: {name}\n"
        f"Цена: {price} ₽"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Ответить", callback_data=f"reply_{callback.from_user.id}")
    builder.button(text="📦 Статус", callback_data=f"status_{order_id}")

    await bot.send_message(ADMIN_ID, text_admin, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()

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

# ====================== ПЕРЕПИСКА ======================

@router.message(F.text == "💬 Написать продавцу")
async def start_chat(message: Message, state: FSMContext):
    await message.answer(
        "Напиши сообщение продавцу. Он получит его и сможет ответить.",
        reply_markup=cancel_kb()
    )
    await state.set_state(AdminStates.reply_to_user)
    await state.update_data(target_user=None)

@router.message(AdminStates.reply_to_user)
async def process_message(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        is_admin = message.from_user.id == ADMIN_ID
        await message.answer("Отменено", reply_markup=main_kb(is_admin) if not is_admin else admin_kb())
        return

    data = await state.get_data()
    target = data.get("target_user")

    if target:  # админ → клиент
        await bot.send_message(target, f"💬 <b>Ответ продавца:</b>\n\n{message.text}", parse_mode="HTML")
        await message.answer("Сообщение отправлено клиенту.", reply_markup=admin_kb())
    else:  # клиент → админ
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

@router.message(F.text == "🖼️ Загрузить баннер")
async def upload_banner_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "Отправь фото, которое будет показываться при /start\n"
        "(просто пришли картинку)",
        reply_markup=cancel_kb()
    )
    await state.set_state(AdminStates.waiting_banner)

@router.message(AdminStates.waiting_banner, F.photo)
async def save_banner(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await set_banner(file_id)
    await message.answer("✅ Баннер успешно установлен!", reply_markup=admin_kb())
    await state.clear()

@router.message(AdminStates.waiting_banner)
async def banner_wrong(message: Message):
    if message.text == "❌ Отмена":
        await message.answer("Отменено", reply_markup=admin_kb())
        await message.answer.fsm_context.clear() if hasattr(message, 'answer') else None
        return
    await message.answer("Пришли именно фото.")

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

# Статусы заказа
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
