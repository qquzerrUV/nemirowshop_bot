import asyncio
import logging
import os
from datetime import datetime

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
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

# ====================== БАЗА ======================

async def init_db():
    async with aiosqlite.connect("database.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS countries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                price INTEGER NOT NULL,
                description TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS numbers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country_id INTEGER,
                number TEXT NOT NULL,
                is_sold INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                country TEXT,
                price INTEGER,
                number TEXT,
                status TEXT DEFAULT 'pending',
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS test_users (
                user_id INTEGER PRIMARY KEY
            )
        """)
        await db.commit()

async def get_setting(key: str, default=None):
    async with aiosqlite.connect("database.db") as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default

async def set_setting(key: str, value: str):
    async with aiosqlite.connect("database.db") as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

async def is_test_user(user_id: int):
    async with aiosqlite.connect("database.db") as db:
        cur = await db.execute("SELECT 1 FROM test_users WHERE user_id = ?", (user_id,))
        return await cur.fetchone() is not None

# ====================== Безопасное редактирование ======================

async def safe_edit(callback: CallbackQuery, text: str, reply_markup=None, parse_mode="HTML"):
    try:
        await callback.message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)

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
            return data.get("result") if data.get("ok") else None

# ====================== FSM ======================

class Form(StatesGroup):
    add_country_name = State()
    add_country_price = State()
    add_country_desc = State()
    add_numbers = State()
    reply_user = State()
    add_test_user = State()

# ====================== КЛАВИАТУРЫ ======================

def main_kb(is_admin=False):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📱  Купить номер", callback_data="buy"))
    b.row(InlineKeyboardButton(text="📦  Мои заказы", callback_data="my_orders"))
    b.row(InlineKeyboardButton(text="💬  Поддержка", callback_data="support"))
    b.row(InlineKeyboardButton(text="ℹ️  Информация", callback_data="info"))
    if is_admin:
        b.row(InlineKeyboardButton(text="⚙️  Админ-панель", callback_data="admin"))
    return b.as_markup()

def admin_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📦  Номера и страны", callback_data="numbers_menu"))
    b.row(InlineKeyboardButton(text="📋  Заказы", callback_data="all_orders"))
    b.row(InlineKeyboardButton(text="🧪  Тестовый режим", callback_data="test_mode"))
    b.row(InlineKeyboardButton(text="📊  Статистика", callback_data="stats"))
    b.row(InlineKeyboardButton(text="◀️  Главное меню", callback_data="main_menu"))
    return b.as_markup()

def numbers_kb():
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕  Добавить страну", callback_data="add_country"))
    b.row(InlineKeyboardButton(text="📋  Управление странами", callback_data="manage_countries"))
    b.row(InlineKeyboardButton(text="🔢  Добавить номера", callback_data="add_numbers"))
    b.row(InlineKeyboardButton(text="◀️  Назад", callback_data="admin"))
    return b.as_markup()

def back_kb(callback="main_menu"):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️  Назад", callback_data=callback))
    return b.as_markup()

# ====================== ГЛАВНОЕ МЕНЮ ======================

async def show_main_menu(target, user_id: int):
    is_admin = user_id == ADMIN_ID
    banner = await get_setting("banner")

    text = (
        f"Привет, <b>{target.from_user.first_name}</b> 👋\n\n"
        f"Nemirow Shop — магазин физических номеров\n\n"
        f"Выбери нужный раздел:"
    )
    kb = main_kb(is_admin)

    if isinstance(target, Message):
        if banner:
            await target.answer_photo(banner, caption=text, parse_mode="HTML", reply_markup=kb)
        else:
            await target.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        try:
            await target.message.delete()
        except Exception:
            pass
        if banner:
            await target.message.answer_photo(banner, caption=text, parse_mode="HTML", reply_markup=kb)
        else:
            await target.message.answer(text, parse_mode="HTML", reply_markup=kb)

@router.message(CommandStart())
async def cmd_start(message: Message):
    await show_main_menu(message, message.from_user.id)

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    await show_main_menu(callback, callback.from_user.id)
    await callback.answer()

# ====================== ИНФО И ПОДДЕРЖКА ======================

@router.callback_query(F.data == "info")
async def cb_info(callback: CallbackQuery):
    text = (
        "<b>ℹ️ Информация</b>\n\n"
        "• Физические SIM-карты\n"
        "• Оплата в USDT через CryptoBot\n"
        "• Мгновенная выдача после оплаты\n"
        "• Поддержка 24/7"
    )
    await safe_edit(callback, text, back_kb())
    await callback.answer()

@router.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery, state: FSMContext):
    await safe_edit(callback, "💬 <b>Поддержка</b>\n\nНапишите ваш вопрос прямо в чат.", back_kb())
    await state.set_state(Form.reply_user)
    await state.update_data(target=None)
    await callback.answer()

@router.message(Form.reply_user)
async def process_support(message: Message, state: FSMContext):
    data = await state.get_data()
    target = data.get("target")

    if target:
        await bot.send_message(target, f"💬 <b>Ответ поддержки:</b>\n\n{message.text}", parse_mode="HTML")
        await message.answer("✅ Отправлено")
    else:
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="Ответить", callback_data=f"reply_{message.from_user.id}"))
        await bot.send_message(
            ADMIN_ID,
            f"💬 <b>Сообщение от @{message.from_user.username or message.from_user.id}</b>\n\n{message.text}",
            parse_mode="HTML",
            reply_markup=kb.as_markup()
        )
        await message.answer("✅ Сообщение отправлено в поддержку")
    await state.clear()

@router.callback_query(F.data.startswith("reply_"))
async def cb_reply(callback: CallbackQuery, state: FSMContext):
    uid = int(callback.data.split("_")[1])
    await state.set_state(Form.reply_user)
    await state.update_data(target=uid)
    await callback.message.answer("Введите ответ:")
    await callback.answer()

# ====================== КАТАЛОГ ======================

@router.callback_query(F.data == "buy")
async def cb_buy(callback: CallbackQuery):
    async with aiosqlite.connect("database.db") as db:
        cur = await db.execute("""
            SELECT c.id, c.name, c.price,
                (SELECT COUNT(*) FROM numbers n WHERE n.country_id=c.id AND n.is_sold=0) as stock
            FROM countries c WHERE c.is_active=1 ORDER BY c.name
        """)
        rows = await cur.fetchall()

    if not rows:
        await safe_edit(callback, "Пока нет доступных номеров.", back_kb())
        await callback.answer()
        return

    b = InlineKeyboardBuilder()
    for cid, name, price, stock in rows:
        mark = f"· {stock} шт" if stock > 0 else "· нет в наличии"
        b.row(InlineKeyboardButton(text=f"{name}  —  {price} ₽  {mark}", callback_data=f"country_{cid}"))
    b.row(InlineKeyboardButton(text="◀️  Назад", callback_data="main_menu"))

    await safe_edit(callback, "<b>📱 Выберите страну</b>", b.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("country_"))
async def cb_country(callback: CallbackQuery):
    cid = int(callback.data.split("_")[1])
    async with aiosqlite.connect("database.db") as db:
        cur = await db.execute("SELECT name, price, description FROM countries WHERE id=?", (cid,))
        row = await cur.fetchone()
        cur = await db.execute("SELECT COUNT(*) FROM numbers WHERE country_id=? AND is_sold=0", (cid,))
        stock = (await cur.fetchone())[0]

    if not row:
        await callback.answer("Недоступно", show_alert=True)
        return

    name, price, desc = row
    text = f"<b>{name}</b>\n\nЦена: <b>{price} ₽</b>\nВ наличии: <b>{stock}</b>\n\n{desc or ''}"

    b = InlineKeyboardBuilder()
    if stock > 0:
        b.row(InlineKeyboardButton(text="💳  Оплатить", callback_data=f"pay_{cid}"))
    b.row(InlineKeyboardButton(text="◀️  Назад", callback_data="buy"))

    await safe_edit(callback, text, b.as_markup())
    await callback.answer()

# ====================== ОПЛАТА ======================

@router.callback_query(F.data.startswith("pay_"))
async def cb_pay(callback: CallbackQuery):
    cid = int(callback.data.split("_")[1])
    user_id = callback.from_user.id

    async with aiosqlite.connect("database.db") as db:
        cur = await db.execute("SELECT name, price FROM countries WHERE id=?", (cid,))
        row = await cur.fetchone()
        cur = await db.execute("SELECT id, number FROM numbers WHERE country_id=? AND is_sold=0 LIMIT 1", (cid,))
        num_row = await cur.fetchone()

    if not row or not num_row:
        await callback.answer("Номера закончились", show_alert=True)
        return

    name, price = row
    number_id, number = num_row

    # Тестовый режим / админ — сразу выдаём
    if await is_test_user(user_id) or user_id == ADMIN_ID:
        async with aiosqlite.connect("database.db") as db:
            await db.execute("UPDATE numbers SET is_sold=1 WHERE id=?", (number_id,))
            await db.execute(
                "INSERT INTO orders (user_id, username, country, price, number, status, created_at) VALUES (?,?,?,?,?,'paid',?)",
                (user_id, callback.from_user.username, name, price, number, datetime.now().strftime("%Y-%m-%d %H:%M"))
            )
            await db.commit()

        await safe_edit(callback, f"✅ <b>Тестовая выдача</b>\n\nСтрана: {name}\nНомер: <code>{number}</code>", back_kb())
        await callback.answer()
        return

    # Создание заказа + счёта
    async with aiosqlite.connect("database.db") as db:
        cur = await db.execute(
            "INSERT INTO orders (user_id, username, country, price, number, status, created_at) VALUES (?,?,?,?,?,'pending',?)",
            (user_id, callback.from_user.username, name, price, number, datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        order_id = cur.lastrowid
        await db.commit()

    invoice = await create_invoice(price, f"{name} | Заказ #{order_id}", order_id)
    if not invoice:
        await safe_edit(callback, "Ошибка создания счёта. Попробуйте позже.", back_kb())
        return

    async with aiosqlite.connect("database.db") as db:
        await db.execute("UPDATE orders SET invoice_id=? WHERE id=?", (str(invoice["invoice_id"]), order_id))
        await db.commit()

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="💳  Оплатить", url=invoice["pay_url"]))
    b.row(InlineKeyboardButton(text="◀️  В меню", callback_data="main_menu"))

    await safe_edit(
        callback,
        f"<b>Заказ #{order_id}</b>\n\n"
        f"Страна: {name}\n"
        f"Сумма: <b>{price} ₽</b>\n\n"
        f"После оплаты номер будет выдан автоматически.",
        b.as_markup()
    )
    await callback.answer()

# ====================== МОИ ЗАКАЗЫ ======================

@router.callback_query(F.data == "my_orders")
async def cb_my_orders(callback: CallbackQuery):
    async with aiosqlite.connect("database.db") as db:
        cur = await db.execute(
            "SELECT id, country, price, number, status, created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 20",
            (callback.from_user.id,)
        )
        rows = await cur.fetchall()

    if not rows:
        await safe_edit(callback, "У вас пока нет заказов.", back_kb())
        await callback.answer()
        return

    text = "<b>📦 Ваши заказы</b>\n\n"
    for oid, country, price, number, status, created in rows:
        extra = f"\n<code>{number}</code>" if status == "paid" and number else ""
        text += f"#{oid}  {country}  {price}₽  · {status}{extra}\n\n"

    await safe_edit(callback, text, back_kb())
    await callback.answer()

# ====================== АДМИНКА ======================

@router.callback_query(F.data == "admin")
async def cb_admin(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await safe_edit(callback, "⚙️ <b>Админ-панель</b>", admin_kb())
    await callback.answer()

# --- Блок "Номера и страны" ---
@router.callback_query(F.data == "numbers_menu")
async def cb_numbers_menu(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await safe_edit(callback, "📦 <b>Номера и страны</b>", numbers_kb())
    await callback.answer()

@router.callback_query(F.data == "add_country")
async def cb_add_country(callback: CallbackQuery, state: FSMContext):
    await safe_edit(callback, "Название страны:")
    await state.set_state(Form.add_country_name)
    await callback.answer()

@router.message(Form.add_country_name)
async def add_c_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Цена (только число):")
    await state.set_state(Form.add_country_price)

@router.message(Form.add_country_price)
async def add_c_price(message: Message, state: FSMContext):
    try:
        price = int(message.text.strip())
    except:
        await message.answer("Введите число")
        return
    await state.update_data(price=price)
    await message.answer("Описание (или -):")
    await state.set_state(Form.add_country_desc)

@router.message(Form.add_country_desc)
async def add_c_desc(message: Message, state: FSMContext):
    data = await state.get_data()
    desc = message.text.strip() if message.text.strip() != "-" else ""
    async with aiosqlite.connect("database.db") as db:
        try:
            await db.execute("INSERT INTO countries (name, price, description) VALUES (?,?,?)",
                             (data["name"], data["price"], desc))
            await db.commit()
            await message.answer(f"✅ Страна «{data['name']}» добавлена")
        except:
            await message.answer("❌ Такая страна уже существует")
    await state.clear()

@router.callback_query(F.data == "manage_countries")
async def cb_manage(callback: CallbackQuery):
    async with aiosqlite.connect("database.db") as db:
        cur = await db.execute("""
            SELECT c.id, c.name, c.price, c.is_active,
                (SELECT COUNT(*) FROM numbers n WHERE n.country_id=c.id AND n.is_sold=0)
            FROM countries c ORDER BY c.name
        """)
        rows = await cur.fetchall()

    if not rows:
        await safe_edit(callback, "Стран пока нет.", back_kb("numbers_menu"))
        await callback.answer()
        return

    b = InlineKeyboardBuilder()
    for cid, name, price, active, stock in rows:
        status = "✅" if active else "❌"
        b.row(InlineKeyboardButton(text=f"{status} {name} · {price}₽ · {stock} шт", callback_data=f"editc_{cid}"))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="numbers_menu"))

    await safe_edit(callback, "<b>Управление странами</b>\nНажмите на страну для настройки", b.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("editc_"))
async def cb_edit_country(callback: CallbackQuery):
    cid = int(callback.data.split("_")[1])
    async with aiosqlite.connect("database.db") as db:
        cur = await db.execute("SELECT name, price, is_active FROM countries WHERE id=?", (cid,))
        row = await cur.fetchone()
        cur = await db.execute("SELECT COUNT(*) FROM numbers WHERE country_id=? AND is_sold=0", (cid,))
        stock = (await cur.fetchone())[0]

    name, price, active = row
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 Включить / Выключить", callback_data=f"toggle_{cid}"))
    b.row(InlineKeyboardButton(text="🗑 Удалить страну", callback_data=f"delc_{cid}"))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="manage_countries"))

    status = "Активна" if active else "Выключена"
    await safe_edit(callback, f"<b>{name}</b>\nЦена: {price}₽\nОстаток: {stock}\nСтатус: {status}", b.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("toggle_"))
async def cb_toggle(callback: CallbackQuery):
    cid = int(callback.data.split("_")[1])
    async with aiosqlite.connect("database.db") as db:
        await db.execute("UPDATE countries SET is_active = 1 - is_active WHERE id=?", (cid,))
        await db.commit()
    await callback.answer("Статус изменён")
    callback.data = f"editc_{cid}"
    await cb_edit_country(callback)

@router.callback_query(F.data.startswith("delc_"))
async def cb_del_country(callback: CallbackQuery):
    cid = int(callback.data.split("_")[1])
    async with aiosqlite.connect("database.db") as db:
        await db.execute("DELETE FROM numbers WHERE country_id=?", (cid,))
        await db.execute("DELETE FROM countries WHERE id=?", (cid,))
        await db.commit()
    await callback.answer("Страна удалена")
    await cb_manage(callback)

@router.callback_query(F.data == "add_numbers")
async def cb_add_numbers(callback: CallbackQuery):
    async with aiosqlite.connect("database.db") as db:
        cur = await db.execute("SELECT id, name FROM countries ORDER BY name")
        rows = await cur.fetchall()

    if not rows:
        await callback.answer("Сначала добавьте страну", show_alert=True)
        return

    b = InlineKeyboardBuilder()
    for cid, name in rows:
        b.row(InlineKeyboardButton(text=name, callback_data=f"addnum_{cid}"))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="numbers_menu"))
    await safe_edit(callback, "Выберите страну для добавления номеров:", b.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("addnum_"))
async def cb_addnum(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split("_")[1])
    await state.update_data(cid=cid)
    await safe_edit(callback, "Отправьте номера (каждый с новой строки):")
    await state.set_state(Form.add_numbers)
    await callback.answer()

@router.message(Form.add_numbers)
async def save_numbers(message: Message, state: FSMContext):
    data = await state.get_data()
    cid = data["cid"]
    nums = [n.strip() for n in message.text.splitlines() if n.strip()]

    async with aiosqlite.connect("database.db") as db:
        added = 0
        for n in nums:
            cur = await db.execute("SELECT 1 FROM numbers WHERE number=?", (n,))
            if not await cur.fetchone():
                await db.execute("INSERT INTO numbers (country_id, number) VALUES (?,?)", (cid, n))
                added += 1
        await db.commit()

    await message.answer(f"✅ Добавлено новых номеров: {added}")
    await state.clear()

# --- Тестовый режим ---
@router.callback_query(F.data == "test_mode")
async def cb_test_mode(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ Добавить пользователя", callback_data="add_test_user"))
    b.row(InlineKeyboardButton(text="📋 Список тестовых", callback_data="list_test_users"))
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin"))
    await safe_edit(callback, "🧪 <b>Тестовый режим</b>\n\nПользователи из списка получают номера без оплаты.", b.as_markup())
    await callback.answer()

@router.callback_query(F.data == "add_test_user")
async def cb_add_test_user(callback: CallbackQuery, state: FSMContext):
    await safe_edit(callback, "Отправьте Telegram ID пользователя:")
    await state.set_state(Form.add_test_user)
    await callback.answer()

@router.message(Form.add_test_user)
async def process_add_test(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
    except:
        await message.answer("Нужен числовой ID")
        return
    async with aiosqlite.connect("database.db") as db:
        await db.execute("INSERT OR IGNORE INTO test_users (user_id) VALUES (?)", (uid,))
        await db.commit()
    await message.answer(f"✅ Пользователь {uid} добавлен в тестовый режим")
    await state.clear()

@router.callback_query(F.data == "list_test_users")
async def cb_list_test(callback: CallbackQuery):
    async with aiosqlite.connect("database.db") as db:
        cur = await db.execute("SELECT user_id FROM test_users")
        rows = await cur.fetchall()
    text = "<b>Тестовые пользователи:</b>\n\n" + "\n".join(str(r[0]) for r in rows) if rows else "Список пуст"
    await safe_edit(callback, text, back_kb("test_mode"))
    await callback.answer()

# --- Заказы и статистика ---
@router.callback_query(F.data == "all_orders")
async def cb_all_orders(callback: CallbackQuery):
    async with aiosqlite.connect("database.db") as db:
        cur = await db.execute("SELECT id, username, country, price, status FROM orders ORDER BY id DESC LIMIT 15")
        rows = await cur.fetchall()

    text = "<b>📦 Последние заказы</b>\n\n"
    for r in rows:
        text += f"#{r[0]} @{r[1] or '—'} {r[2]} {r[3]}₽ · {r[4]}\n"
    await safe_edit(callback, text or "Пусто", back_kb("admin"))
    await callback.answer()

@router.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery):
    async with aiosqlite.connect("database.db") as db:
        total = (await (await db.execute("SELECT COUNT(*) FROM orders")).fetchone())[0]
        paid = (await (await db.execute("SELECT COUNT(*) FROM orders WHERE status='paid'")).fetchone())[0]
        money = (await (await db.execute("SELECT SUM(price) FROM orders WHERE status='paid'")).fetchone())[0] or 0
    text = f"📊 <b>Статистика</b>\n\nВсего заказов: {total}\nОплачено: {paid}\nСумма: {money} ₽"
    await safe_edit(callback, text, back_kb("admin"))
    await callback.answer()

# ====================== ЗАПУСК ======================

async def main():
    await init_db()
    logging.basicConfig(level=logging.INFO)
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
