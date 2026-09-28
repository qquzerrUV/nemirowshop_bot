import asyncio
import logging
import os
import json
from datetime import datetime

import aiohttp
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
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")

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
            CREATE TABLE IF NOT EXISTS numbers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country_id INTEGER,
                number TEXT NOT NULL,
                is_sold INTEGER DEFAULT 0,
                FOREIGN KEY (country_id) REFERENCES countries(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                country TEXT,
                price INTEGER,
                number TEXT,
                status TEXT DEFAULT 'new',
                invoice_id TEXT,
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

# ====================== CRYPTOBOT ======================

async def create_invoice(amount: int, description: str, order_id: int):
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
    payload = {
        "asset": "USDT",
        "amount": str(amount),
        "description": description,
        "payload": str(order_id),
        "expires_in": 3600
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            data = await resp.json()
            if data.get("ok"):
                return data["result"]
            else:
                logging.error(f"CryptoBot error: {data}")
                return None

async def check_invoice(invoice_id: str):
    url = f"https://pay.crypt.bot/api/getInvoices?invoice_ids={invoice_id}"
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            data = await resp.json()
            if data.get("ok") and data["result"]["items"]:
                return data["result"]["items"][0]
            return None

# ====================== СОСТОЯНИЯ ======================

class AdminStates(StatesGroup):
    add_country_name = State()
    add_country_price = State()
    add_country_desc = State()
    add_numbers = State()
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
    builder.row(InlineKeyboardButton(text="🔢 Добавить номера", callback_data="add_numbers"))
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
        "Выбирай страну → оплачивай → получай номер."
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
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_kb(is_admin))
    except:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb(is_admin))
    await callback.answer()

# ====================== ИНФОРМАЦИЯ ======================

@router.callback_query(F.data == "info")
async def info(callback: CallbackQuery):
    text = (
        "<b>ℹ️ Информация</b>\n\n"
        "• Физические SIM-карты\n"
        "• Оплата через CryptoBot (USDT)\n"
        "• Автоматическая выдача номера после оплаты\n"
        "• Поддержка 24/7"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_to_main_kb())
    await callback.answer()

# ====================== КАТАЛОГ ======================

@router.callback_query(F.data == "buy")
async def show_catalog(callback: CallbackQuery):
    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute("""
            SELECT c.id, c.name, c.price, 
                   (SELECT COUNT(*) FROM numbers n WHERE n.country_id = c.id AND n.is_sold = 0) as stock
            FROM countries c
            WHERE c.is_active = 1
            ORDER BY c.name
        """)
        countries = await cursor.fetchall()

    if not countries:
        await callback.message.edit_text(
            "Сейчас нет доступных номеров.",
            reply_markup=back_to_main_kb()
        )
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    for c_id, name, price, stock in countries:
        stock_text = f"({stock} шт)" if stock > 0 else "(нет в наличии)"
        builder.row(InlineKeyboardButton(
            text=f"{name} — {price} ₽ {stock_text}",
            callback_data=f"country_{c_id}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu"))

    await callback.message.edit_text(
        "<b>📱 Выбери страну:</b>",
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
        cursor = await db.execute(
            "SELECT COUNT(*) FROM numbers WHERE country_id = ? AND is_sold = 0", (country_id,)
        )
        stock = (await cursor.fetchone())[0]

    if not row:
        await callback.answer("Страна больше не доступна", show_alert=True)
        return

    name, price, desc = row
    text = (
        f"<b>{name}</b>\n\n"
        f"Цена: <b>{price} ₽</b>\n"
        f"В наличии: <b>{stock} шт</b>\n\n"
        f"{desc or ''}"
    )

    builder = InlineKeyboardBuilder()
    if stock > 0:
        builder.row(InlineKeyboardButton(text="💳 Оплатить", callback_data=f"pay_{country_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="buy"))

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

# ====================== ОПЛАТА ======================

@router.callback_query(F.data.startswith("pay_"))
async def create_payment(callback: CallbackQuery):
    country_id = int(callback.data.split("_")[1])

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            "SELECT name, price FROM countries WHERE id = ?", (country_id,)
        )
        row = await cursor.fetchone()
        cursor = await db.execute(
            "SELECT id, number FROM numbers WHERE country_id = ? AND is_sold = 0 LIMIT 1",
            (country_id,)
        )
        number_row = await cursor.fetchone()

    if not row or not number_row:
        await callback.answer("Номера закончились", show_alert=True)
        return

    name, price = row
    number_id, number = number_row

    # Создаём заказ
    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            """INSERT INTO orders (user_id, username, country, price, number, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (
                callback.from_user.id,
                callback.from_user.username,
                name,
                price,
                number,
                datetime.now().strftime("%Y-%m-%d %H:%M")
            )
        )
        order_id = cursor.lastrowid
        await db.commit()

    # Создаём счёт в CryptoBot
    invoice = await create_invoice(
        amount=price,
        description=f"Номер {name} | Заказ #{order_id}",
        order_id=order_id
    )

    if not invoice:
        await callback.message.edit_text(
            "Ошибка создания счёта. Попробуйте позже.",
            reply_markup=back_to_main_kb()
        )
        return

    invoice_id = invoice["invoice_id"]
    pay_url = invoice["pay_url"]

    # Сохраняем invoice_id
    async with aiosqlite.connect("database.db") as db:
        await db.execute(
            "UPDATE orders SET invoice_id = ? WHERE id = ?",
            (str(invoice_id), order_id)
        )
        await db.commit()

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Оплатить", url=pay_url))
    builder.row(InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_{order_id}"))
    builder.row(InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu"))

    await callback.message.edit_text(
        f"<b>Заказ #{order_id}</b>\n\n"
        f"Страна: {name}\n"
        f"Сумма: <b>{price} ₽</b> (в USDT)\n\n"
        f"Нажми «Оплатить» и после оплаты нажми «Проверить оплату».",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("check_"))
async def check_payment(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            "SELECT invoice_id, status, number, country, user_id FROM orders WHERE id = ?",
            (order_id,)
        )
        row = await cursor.fetchone()

    if not row:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    invoice_id, status, number, country, user_id = row

    if status == "paid":
        await callback.message.edit_text(
            f"✅ <b>Заказ уже оплачен!</b>\n\n"
            f"Ваш номер: <code>{number}</code>\n"
            f"Страна: {country}",
            parse_mode="HTML",
            reply_markup=back_to_main_kb()
        )
        await callback.answer()
        return

    # Проверяем статус в CryptoBot
    invoice = await check_invoice(invoice_id)

    if not invoice:
        await callback.answer("Не удалось проверить оплату", show_alert=True)
        return

    if invoice["status"] == "paid":
        # Выдаём номер
        async with aiosqlite.connect("database.db") as db:
            await db.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (order_id,))
            await db.execute(
                "UPDATE numbers SET is_sold = 1 WHERE number = ?", (number,)
            )
            await db.commit()

        await callback.message.edit_text(
            f"✅ <b>Оплата прошла успешно!</b>\n\n"
            f"Ваш номер: <code>{number}</code>\n"
            f"Страна: {country}\n\n"
            f"Спасибо за покупку!",
            parse_mode="HTML",
            reply_markup=back_to_main_kb()
        )

        # Уведомление админу
        await bot.send_message(
            ADMIN_ID,
            f"✅ <b>Оплачен заказ #{order_id}</b>\n\n"
            f"Пользователь: @{callback.from_user.username or callback.from_user.id}\n"
            f"Страна: {country}\n"
            f"Номер: <code>{number}</code>",
            parse_mode="HTML"
        )
    else:
        await callback.answer("Оплата ещё не поступила", show_alert=True)

    await callback.answer()

# ====================== МОИ ЗАКАЗЫ ======================

@router.callback_query(F.data == "my_orders")
async def my_orders(callback: CallbackQuery):
    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            "SELECT id, country, price, number, status, created_at FROM orders WHERE user_id = ? ORDER BY id DESC",
            (callback.from_user.id,)
        )
        orders = await cursor.fetchall()

    if not orders:
        await callback.message.edit_text("У тебя пока нет заказов.", reply_markup=back_to_main_kb())
        await callback.answer()
        return

    text = "<b>📦 Твои заказы:</b>\n\n"
    for o_id, country, price, number, status, created in orders:
        num_text = f" | <code>{number}</code>" if number and status == "paid" else ""
        text += f"#{o_id} | {country} | {price} ₽ | <b>{status}</b>{num_text}\n"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=back_to_main_kb())
    await callback.answer()

# ====================== ПОДДЕРЖКА ======================

@router.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "💬 <b>Написать продавцу</b>\n\nПросто напиши сообщение в чат.",
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

    if target:
        await bot.send_message(target, f"💬 <b>Ответ продавца:</b>\n\n{message.text}", parse_mode="HTML")
        await message.answer("Сообщение отправлено.")
    else:
        await bot.send_message(
            ADMIN_ID,
            f"💬 Сообщение от @{message.from_user.username or 'нет'} (ID: {message.from_user.id}):\n\n{message.text}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Ответить", callback_data=f"reply_{message.from_user.id}")]
            ])
        )
        await message.answer("Сообщение отправлено продавцу.")
    await state.clear()

@router.callback_query(F.data.startswith("reply_"))
async def admin_reply_start(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[1])
    await state.update_data(target_user=user_id)
    await callback.message.answer("Напиши ответ клиенту:")
    await state.set_state(AdminStates.reply_to_user)
    await callback.answer()

# ====================== АДМИНКА ======================

@router.callback_query(F.data == "admin")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text("⚙️ <b>Админ-панель</b>", parse_mode="HTML", reply_markup=admin_menu_kb())
    await callback.answer()

@router.callback_query(F.data == "upload_banner")
async def upload_banner_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("🖼️ Отправь фото-баннер:")
    await state.set_state(AdminStates.waiting_banner)
    await callback.answer()

@router.message(AdminStates.waiting_banner, F.photo)
async def save_banner(message: Message, state: FSMContext):
    await set_banner(message.photo[-1].file_id)
    await message.answer("✅ Баннер установлен!", reply_markup=main_menu_kb(True))
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
    await message.answer("Цена в рублях (число):")
    await state.set_state(AdminStates.add_country_price)

@router.message(AdminStates.add_country_price)
async def add_country_price(message: Message, state: FSMContext):
    try:
        price = int(message.text)
    except:
        await message.answer("Нужно число:")
        return
    await state.update_data(price=price)
    await message.answer("Описание (или «-»):")
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

    await message.answer(f"✅ Страна «{data['name']}» добавлена.", reply_markup=admin_menu_kb())
    await state.clear()

@router.callback_query(F.data == "add_numbers")
async def add_numbers_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute("SELECT id, name FROM countries ORDER BY name")
        countries = await cursor.fetchall()

    if not countries:
        await callback.answer("Сначала добавьте страны", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for c_id, name in countries:
        builder.row(InlineKeyboardButton(text=name, callback_data=f"addnum_{c_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin"))

    await callback.message.edit_text("Выбери страну для добавления номеров:", reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("addnum_"))
async def add_numbers_country(callback: CallbackQuery, state: FSMContext):
    country_id = int(callback.data.split("_")[1])
    await state.update_data(country_id=country_id)
    await callback.message.edit_text(
        "Отправь номера (каждый с новой строки):\n\n"
        "Пример:\n+79001234567\n+79007654321"
    )
    await state.set_state(AdminStates.add_numbers)
    await callback.answer()

@router.message(AdminStates.add_numbers)
async def save_numbers(message: Message, state: FSMContext):
    data = await state.get_data()
    country_id = data["country_id"]
    numbers = [n.strip() for n in message.text.split("\n") if n.strip()]

    async with aiosqlite.connect("database.db") as db:
        for num in numbers:
            await db.execute(
                "INSERT INTO numbers (country_id, number) VALUES (?, ?)",
                (country_id, num)
            )
        await db.commit()

    await message.answer(f"✅ Добавлено номеров: {len(numbers)}", reply_markup=admin_menu_kb())
    await state.clear()

@router.callback_query(F.data == "list_countries")
async def list_countries(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute("""
            SELECT c.id, c.name, c.price,
                   (SELECT COUNT(*) FROM numbers n WHERE n.country_id = c.id AND n.is_sold = 0) as stock
            FROM countries c ORDER BY c.name
        """)
        countries = await cursor.fetchall()

    text = "<b>📋 Список стран:</b>\n\n"
    for c_id, name, price, stock in countries:
        text += f"#{c_id} {name} — {price} ₽ | Остаток: {stock}\n"

    await callback.message.edit_text(text or "Пусто", parse_mode="HTML", reply_markup=admin_menu_kb())
    await callback.answer()

@router.callback_query(F.data == "all_orders")
async def all_orders(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect("database.db") as db:
        cursor = await db.execute(
            "SELECT id, username, country, price, number, status, created_at FROM orders ORDER BY id DESC LIMIT 15"
        )
        orders = await cursor.fetchall()

    text = "<b>📦 Последние заказы:</b>\n\n"
    for o_id, username, country, price, number, status, created in orders:
        text += f"#{o_id} | @{username or '—'} | {country} | {price}₽ | {status}\n"

    await callback.message.edit_text(text or "Пусто", parse_mode="HTML", reply_markup=admin_menu_kb())
    await callback.answer()

@router.callback_query(F.data == "stats")
async def stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    async with aiosqlite.connect("database.db") as db:
        total = (await (await db.execute("SELECT COUNT(*) FROM orders")).fetchone())[0]
        paid = (await (await db.execute("SELECT COUNT(*) FROM orders WHERE status = 'paid'")).fetchone())[0]
        money = (await (await db.execute("SELECT SUM(price) FROM orders WHERE status = 'paid'")).fetchone())[0] or 0

    text = f"📊 <b>Статистика</b>\n\nВсего заказов: {total}\nОплачено: {paid}\nСумма: {money} ₽"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_menu_kb())
    await callback.answer()

# ====================== ЗАПУСК ======================

async def main():
    await init_db()
    logging.basicConfig(level=logging.INFO)
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
