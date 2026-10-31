# -*- coding: utf-8 -*-
"""Админ-панель: статистика, товары, заказы, юзеры, промокоды, рассылка, баннер, отзывы."""
import asyncio
import aiosqlite
from html import escape

from aiogram import Bot, F, Router, types
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import db, logs, variables
from ..keyboards import (
    admin_menu, admin_order_actions, admin_orders_kb, admin_product_card,
    admin_products_kb, back_menu, variables_kb,
)
from ..logs import esc, notify, user_line
from ..utils import edit_or_answer, is_admin, safe_send, safe_send_photo

router = Router()


class AddProduct(StatesGroup):
    name = State()
    description = State()
    price = State()
    category = State()
    stock = State()
    photo = State()


class BroadcastState(StatesGroup):
    text = State()


class AddPromoState(StatesGroup):
    code = State()
    amount = State()
    uses = State()


class AdminWriteState(StatesGroup):
    text = State()


class BannerState(StatesGroup):
    waiting_photo = State()


class StockState(StatesGroup):
    amount = State()


class VarEditState(StatesGroup):
    value = State()


class TicketReplyState(StatesGroup):
    answer = State()


def _who(call_or_msg) -> str:
    u = call_or_msg.from_user
    return user_line(u.id, u.first_name, u.username)


async def _cancel_if_command(message: types.Message, state: FSMContext) -> bool:
    """Команда (начинается с /) в FSM-состоянии отменяет ввод.

    Состояние сбрасывается, команда выполняется обычным обработчиком —
    иначе, например, текст рассылки оказался бы командой, а /start
    превратился бы в название товара.
    """
    if (message.text or "").startswith("/"):
        await state.clear()
        await message.answer("Ввод отменён, состояние сброшено.")
        return True
    return False


# ---------- ГЛАВНАЯ АДМИНКИ ----------
@router.callback_query(F.data == "admin")
async def cb_admin(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await edit_or_answer(call, "<b>АДМИН-ПАНЕЛЬ</b>\n━━━━━━━━━━━━━━━━━━", admin_menu())
    await call.answer()


# ---------- ПЕРЕМЕННЫЕ ----------
@router.callback_query(F.data == "adm:vars")
async def cb_vars(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.clear()
    await edit_or_answer(call, variables.vars_text(), variables_kb())
    await call.answer()


@router.callback_query(F.data.startswith("adm_var:"))
async def cb_var_edit(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    key = call.data.split(":", 1)[1]
    if key not in variables.VAR_DEFS or not variables.VAR_DEFS[key][2]:
        await call.answer("Эту переменную менять нельзя", show_alert=True)
        return
    title, _kind, _editable, hint = variables.VAR_DEFS[key]
    await state.update_data(var_key=key)
    await state.set_state(VarEditState.value)
    await call.message.answer(
        f"<b>Переменная:</b> {esc(title)}\n"
        f"<b>Текущее значение:</b> <code>{esc(variables.display(key))}</code>\n\n"
        f"{esc(hint)}\n\n"
        f"Отправь новое значение одним сообщением,\n"
        f"или <code>-</code> — вернуть значение из .env:",
        reply_markup=back_menu("adm:vars"),
    )
    await call.answer()


@router.message(VarEditState.value)
async def process_var_edit(message: types.Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    if await _cancel_if_command(message, state):
        raise SkipHandler
    data = await state.get_data()
    key = data.get("var_key")
    await state.clear()
    if not key or key not in variables.VAR_DEFS:
        await message.answer("Сессия редактирования истекла. Открой «Переменные» заново.", reply_markup=admin_menu())
        return
    raw = (message.text or "").strip()
    if raw == "-":
        if await variables.reset_var(key):
            await message.answer(
                f"↩ Возвращено значение из .env: <code>{esc(variables.display(key))}</code>",
                reply_markup=variables_kb(),
            )
            await notify(bot, "ADMIN", f"Переменная {esc(key)} сброшена на значение из .env")
        else:
            await message.answer("Эту переменную сбрасывать нельзя.", reply_markup=variables_kb())
        return

    err = await variables.set_var(key, raw, bot=bot)
    if err:
        await message.answer(f"❌ {esc(err)}.\n\nПопробуй ещё раз или отправь <code>-</code>, чтобы сбросить.")
        # Оставляем режим редактирования, чтобы можно было повторить ввод
        await state.update_data(var_key=key)
        await state.set_state(VarEditState.value)
        return
    title = variables.VAR_DEFS[key][0]
    await message.answer(
        f"✅ Сохранено (без перезапуска).\n<b>{esc(title)}</b> = <code>{esc(variables.display(key))}</code>",
        reply_markup=variables_kb(),
    )
    await notify(bot, "ADMIN", f"Переменная {esc(key)} изменена на <code>{esc(variables.display(key))}</code>")


# ---------- СТАТИСТИКА ----------
@router.callback_query(F.data == "adm:stats")
async def cb_stats(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    s = await db.stats()
    users = await db.count_users()
    text = (
        f"<b>СТАТИСТИКА</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Пользователей:</b> {users}\n"
        f"<b>Заказов (оплачено):</b> {s['orders']}\n"
        f"<b>Выручка:</b> {s['revenue']:.2f} $\n"
        f"<b>Заказов сегодня:</b> {s['today']} (оплачено: {s['paid_today']})\n"
        f"<b>Выручка сегодня:</b> {s['revenue_today_rub']:.2f} ₽\n"
        f"<b>Пополнений сегодня:</b> {s['topups_today']} на {s['topup_rub_today']:.2f} ₽\n"
        f"<b>Новых пользователей сегодня:</b> {s['new_users']}\n"
        f"<b>Ожидают оплаты:</b> {s['pending']}\n"
        f"<b>Товаров в наличии:</b> {s['available']}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    await edit_or_answer(call, text, back_menu("admin"))
    await call.answer()


# ---------- ТОВАРЫ ----------
async def _products_view(call: types.CallbackQuery):
    products = await db.get_all_products()
    if not products:
        text = "<b>ТОВАРЫ</b>\n━━━━━━━━━━━━━━━━━━\nСписок пуст."
        kb = back_menu("admin")
    else:
        text = "<b>ТОВАРЫ</b>\n━━━━━━━━━━━━━━━━━━"
        kb = admin_products_kb(products)
    await edit_or_answer(call, text, kb)


@router.callback_query(F.data == "adm:products")
async def cb_admin_products(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await _products_view(call)
    await call.answer()


@router.callback_query(F.data.startswith("adm_prod:"))
async def cb_admin_product(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    pid = int(call.data.split(":")[1])
    p = await db.get_product(pid)
    if not p:
        await call.answer("Не найден", show_alert=True)
        return
    text = (
        f"<b>ТОВАР #{p['id']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Название:</b> {esc(p['name'])}\n"
        f"<b>Цена:</b> {p['price_usd']} $\n"
        f"<b>Категория:</b> {p['category']}\n"
        f"<b>Наличие:</b> {p['stock']}\n"
        f"<b>Активен:</b> {'да' if p['is_active'] else 'нет'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{esc(p['description'] or '')}"
    )
    await edit_or_answer(call, text, admin_product_card(pid))
    await call.answer()


@router.callback_query(F.data.startswith("adm_toggle:"))
async def cb_toggle(call: types.CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        return
    pid = int(call.data.split(":")[1])
    await db.toggle_product(pid)
    p = await db.get_product(pid)
    await call.answer("Переключено")
    await _products_view(call)
    if p:
        await notify(bot, "STOCK", f"Товар #{pid} {esc(p['name'])} — {'ВКЛЮЧЁН' if p['is_active'] else 'ВЫКЛЮЧЕН'}")


@router.callback_query(F.data.startswith("adm_del:"))
async def cb_del(call: types.CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        return
    pid = int(call.data.split(":")[1])
    p = await db.get_product(pid)
    await db.del_product(pid)
    await call.answer("Удалено")
    await _products_view(call)
    if p:
        await notify(bot, "STOCK", f"Товар #{pid} {esc(p['name'])} — УДАЛЁН")


@router.callback_query(F.data.startswith("adm_stock:"))
async def cb_stock_edit(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    pid = int(call.data.split(":")[1])
    p = await db.get_product(pid)
    if not p:
        await call.answer("Товар не найден", show_alert=True)
        return
    await state.update_data(stock_product_id=pid)
    await state.set_state(StockState.amount)
    await call.message.answer(f"Сейчас в наличии: {p['stock']} шт. Введи новое количество (0 или больше):")
    await call.answer()


@router.message(StockState.amount)
async def process_stock_edit(message: types.Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    if await _cancel_if_command(message, state):
        raise SkipHandler
    try:
        stock = int((message.text or "").strip())
        if stock < 0:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        await message.answer("Введи целое число 0 или больше.")
        return
    data = await state.get_data()
    pid = data["stock_product_id"]
    await db.set_stock(pid, stock)
    await logs.check_low_stock(bot, pid)
    await state.clear()
    await message.answer(f"Наличие обновлено: {stock} шт.", reply_markup=admin_menu())
    p = await db.get_product(pid)
    await notify(bot, "STOCK", f"Наличие товара #{pid} {esc(p['name']) if p else '?'}: {stock} шт.")


# ---------- ДОБАВЛЕНИЕ ТОВАРА ----------
@router.callback_query(F.data == "adm:add_product")
async def cb_add_product(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AddProduct.name)
    await edit_or_answer(call, "Введи название товара:", back_menu("admin"))
    await call.answer()


@router.message(AddProduct.name)
async def ap_name(message: types.Message, state: FSMContext):
    if await _cancel_if_command(message, state):
        raise SkipHandler
    await state.update_data(name=(message.text or "").strip())
    await state.set_state(AddProduct.description)
    await message.answer("Введи описание:")


@router.message(AddProduct.description)
async def ap_desc(message: types.Message, state: FSMContext):
    if await _cancel_if_command(message, state):
        raise SkipHandler
    await state.update_data(description=(message.text or "").strip())
    await state.set_state(AddProduct.price)
    await message.answer("Введи цену в $ (например 5.5):")


@router.message(AddProduct.price)
async def ap_price(message: types.Message, state: FSMContext):
    if await _cancel_if_command(message, state):
        raise SkipHandler
    try:
        price = float((message.text or "").replace(",", "."))
        if price <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("Введи число.")
        return
    await state.update_data(price=price)
    await state.set_state(AddProduct.category)
    await message.answer("Категория (ru/usa/eu/other):")


@router.message(AddProduct.category)
async def ap_cat(message: types.Message, state: FSMContext):
    if await _cancel_if_command(message, state):
        raise SkipHandler
    cat = (message.text or "").strip().lower()
    # Категория попадает в callback-кнопки пагинации — без пробелов и спецсимволов
    if not cat or len(cat) > 20 or any(ch in cat for ch in " :/\\?#@$"):
        await message.answer("Категория — одним словом, латиница/цифры (например ru, usa, eu, other). Попробуй ещё раз:")
        return
    await state.update_data(category=cat)
    await state.set_state(AddProduct.stock)
    await message.answer("Количество в наличии:")


@router.message(AddProduct.stock)
async def ap_stock(message: types.Message, state: FSMContext):
    if await _cancel_if_command(message, state):
        raise SkipHandler
    try:
        stock = int((message.text or "").strip())
        if stock < 0:
            raise ValueError
    except ValueError:
        await message.answer("Введи целое число.")
        return
    await state.update_data(stock=stock)
    await state.set_state(AddProduct.photo)
    await message.answer("Отправь фото товара или напиши '-' чтобы пропустить:")


@router.message(AddProduct.photo)
async def ap_photo(message: types.Message, state: FSMContext, bot: Bot):
    if await _cancel_if_command(message, state):
        raise SkipHandler
    data = await state.get_data()
    photo_id = message.photo[-1].file_id if message.photo else None
    await db.add_product(
        data["name"], data["description"], data["price"],
        data["category"], data["stock"], photo_id,
    )
    await state.clear()
    await message.answer("<b>Товар добавлен.</b>", reply_markup=admin_menu())
    await notify(
        bot, "STOCK",
        f"Добавлен товар: {esc(data['name'])} · {data['price']:.2f} $ · "
        f"категория {esc(data['category'])} · {data['stock']} шт.",
    )


# ---------- ЗАКАЗЫ ----------
@router.callback_query(F.data == "adm:orders")
async def cb_admin_orders(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    orders = await db.get_all_orders()
    if not orders:
        text = "<b>ЗАКАЗЫ</b>\n━━━━━━━━━━━━━━━━━━\nПусто."
        kb = back_menu("admin")
    else:
        text = "<b>ЗАКАЗЫ (последние 100)</b>\n━━━━━━━━━━━━━━━━━━"
        kb = admin_orders_kb(orders)
    await edit_or_answer(call, text, kb)
    await call.answer()


@router.callback_query(F.data.startswith("adm_ord:"))
async def cb_admin_order(call: types.CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        return
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o:
        await call.answer("Не найден", show_alert=True)
        return
    text = (
        f"<b>ЗАКАЗ #{o['id']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Пользователь:</b> <code>{o['user_id']}</code>\n"
        f"<b>Товар:</b> {esc(o['product_name'])}\n"
        f"<b>Сумма:</b> {o['amount_usd']:.2f} $ / {o['amount_rub']:.2f} ₽ / {o['amount_ton']:.4f} TON\n"
        f"<b>Метод:</b> {o['payment_method']}\n"
        f"<b>Статус:</b> {o['status']}\n"
        f"<b>Трек:</b> <code>{o['track'] or '-'}</code>\n"
        f"<b>Дата:</b> {o['created_at']}"
    )
    await edit_or_answer(call, text, admin_order_actions(oid, o["status"]))
    marker = str(o["screenshot_id"] or "")
    # Скрины от пользователей; служебные маркеры счетов (inv:/xr:) — не фото.
    if marker and not marker.startswith(("inv:", "xr:")):
        await safe_send_photo(bot, call.from_user.id, marker, caption=f"Скрин оплаты к #{oid}")
    await call.answer()


@router.callback_query(F.data.startswith("adm_confirm:"))
async def cb_confirm(call: types.CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        return
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o:
        await call.answer("Не найден", show_alert=True)
        return
    # Идемпотентная транзакция: не даст списать товар дважды и начислит реф-бонус.
    order, changed = await db.finish_paid_order(oid, o["user_id"])
    if not changed:
        await call.answer("Уже обработано или товара нет в наличии", show_alert=True)
        return
    await call.answer("Подтверждено")
    await logs.check_low_stock(bot, o["product_id"])
    if o["product_id"]:
        await safe_send(
            bot, o["user_id"],
            f"<b>ОПЛАТА ПОДТВЕРЖДЕНА</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"<b>Заказ:</b> #{oid}\n"
            f"<b>Трек:</b> <code>{o['track']}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Отправь трек в поддержку для получения товара.",
        )
    else:
        await safe_send(
            bot, o["user_id"],
            f"<b>ОПЛАТА ПОДТВЕРЖДЕНА</b>\nНа баланс зачислено {o['amount_rub']:.2f} ₽.",
        )
    try:
        await call.message.edit_text(
            f"Заказ #{oid}: оплата подтверждена.",
            reply_markup=admin_order_actions(oid, "paid"),
        )
    except Exception:
        pass
    method = o["payment_method"] if o["payment_method"] not in (None, "", "pending", "TOPUP") else "не указан"
    if o["product_id"]:
        await notify(
            bot, "ORDER",
            f"✅ КУПЛЕНО — заказ #{oid} ({esc(o['product_name'])} · {o['amount_rub']:.2f} ₽)\n"
            f"Способ оплаты: {esc(method)} (скрин подтвердил админ)\n"
            f"Покупатель: <code>{o['user_id']}</code>",
        )
    else:
        await notify(
            bot, "PAYMENT",
            f"✅ Пополнение подтверждено админом: +{o['amount_rub']:.2f} ₽\n"
            f"Пользователь: <code>{o['user_id']}</code>",
        )


@router.callback_query(F.data.startswith("adm_reject:"))
async def cb_reject(call: types.CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        return
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o:
        return
    await db.set_order_status(oid, "rejected")
    await call.answer("Отклонено")
    await safe_send(bot, o["user_id"], f"Оплата по заказу #{oid} отклонена. Свяжись с поддержкой.")
    try:
        await call.message.edit_text(
            f"Заказ #{oid}: отклонён.",
            reply_markup=admin_order_actions(oid, "rejected"),
        )
    except Exception:
        pass
    await notify(
        bot, "ORDER",
        f"❌ Оплата отклонена — заказ #{oid} ({esc(o['product_name'])})\n"
        f"Способ оплаты: {esc(o['payment_method'] or 'не указан')}\n"
        f"Покупатель: <code>{o['user_id']}</code>",
    )


@router.callback_query(F.data.startswith("adm_issued:"))
async def cb_issued(call: types.CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        return
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o:
        return
    await db.set_order_status(oid, "completed")
    await call.answer("Выдано")
    await safe_send(bot, o["user_id"], f"Заказ #{oid} выдан. Спасибо за покупку.")
    try:
        await call.message.edit_text(
            f"Заказ #{oid}: выдан.",
            reply_markup=admin_order_actions(oid, "completed"),
        )
    except Exception:
        pass
    await notify(
        bot, "ORDER",
        f"📦 Заказ #{oid} ВЫДАН ({esc(o['product_name'])})\n"
        f"Способ оплаты: {esc(o['payment_method'] or 'не указан')}\n"
        f"Покупатель: <code>{o['user_id']}</code>",
    )


@router.callback_query(F.data.startswith("adm_write:"))
async def cb_write(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o:
        return
    await state.update_data(target=o["user_id"])
    await state.set_state(AdminWriteState.text)
    await call.message.answer("Введи текст сообщения пользователю:")
    await call.answer()


@router.message(AdminWriteState.text)
async def send_write(message: types.Message, state: FSMContext, bot: Bot):
    if await _cancel_if_command(message, state):
        raise SkipHandler
    data = await state.get_data()
    await state.clear()
    try:
        await bot.send_message(data["target"], message.text)
        await message.answer("Отправлено.")
        await notify(bot, "ADMIN", f"Сообщение пользователю <code>{data['target']}</code>:\n{esc(message.text or '')}")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


# ---------- ПОЛЬЗОВАТЕЛИ ----------
@router.callback_query(F.data == "adm:users")
async def cb_users(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    users = await db.all_users()
    text = "<b>ПОЛЬЗОВАТЕЛИ (последние 20)</b>\n━━━━━━━━━━━━━━━━━━\n"
    for u in users[:20]:
        text += f"<code>{u['id']}</code> @{u['username'] or '-'} | {u['balance']:.2f} ₽\n"
    text += (
        "━━━━━━━━━━━━━━━━━━\n"
        "Команды:\n"
        "/setbal &lt;id&gt; &lt;сумма&gt;\n"
        "/ban &lt;id&gt;\n"
        "/unban &lt;id&gt;\n"
        "/write &lt;id&gt; &lt;текст&gt;"
    )
    await edit_or_answer(call, text, back_menu("admin"))
    await call.answer()


@router.message(Command("setbal"))
async def cmd_setbal(message: types.Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    try:
        _, uid, amount = message.text.split()
        val = float(amount)
        if val < 0:
            raise ValueError
        await db.set_balance(int(uid), val)
        await message.answer("OK")
        await notify(bot, "ADMIN", f"Баланс пользователя <code>{uid}</code> установлен: {val:.2f} ₽")
    except Exception:
        await message.answer("Формат: /setbal <id> <сумма> (сумма — число 0 или больше)")


@router.message(Command("ban"))
async def cmd_ban(message: types.Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    try:
        _, uid = message.text.split()
        await db.ban_user(int(uid), 1)
        await message.answer("Забанен")
        await notify(bot, "ADMIN", f"Пользователь <code>{uid}</code> ЗАБАНЕН")
    except Exception:
        await message.answer("Формат: /ban <id>")


@router.message(Command("unban"))
async def cmd_unban(message: types.Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    try:
        _, uid = message.text.split()
        await db.ban_user(int(uid), 0)
        await message.answer("Разбанен")
        await notify(bot, "ADMIN", f"Пользователь <code>{uid}</code> РАЗБАНЕН")
    except Exception:
        await message.answer("Формат: /unban <id>")


@router.message(Command("write"))
async def cmd_write(message: types.Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    try:
        parts = message.text.split(maxsplit=2)
        uid = int(parts[1])
        text = parts[2]
        await bot.send_message(uid, text)
        await message.answer("Отправлено")
        await notify(bot, "ADMIN", f"Сообщение пользователю <code>{uid}</code>:\n{esc(text)}")
    except Exception:
        await message.answer("Формат: /write <id> <текст>")


# ---------- ПРОМОКОДЫ ----------
@router.callback_query(F.data == "adm:promos")
async def cb_promos(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AddPromoState.code)
    await edit_or_answer(call, "Введи код промокода:", back_menu("admin"))
    await call.answer()


@router.message(AddPromoState.code)
async def ap_code(message: types.Message, state: FSMContext):
    if await _cancel_if_command(message, state):
        raise SkipHandler
    await state.update_data(code=(message.text or "").strip().upper())
    await state.set_state(AddPromoState.amount)
    await message.answer("Сумма в рублях:")


@router.message(AddPromoState.amount)
async def ap_amount(message: types.Message, state: FSMContext):
    if await _cancel_if_command(message, state):
        raise SkipHandler
    try:
        amount = float((message.text or "").replace(",", "."))
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("Введи число больше 0 (иначе баланс уйдёт в минус).")
        return
    await state.update_data(amount=amount)
    await state.set_state(AddPromoState.uses)
    await message.answer("Количество активаций:")


@router.message(AddPromoState.uses)
async def ap_uses(message: types.Message, state: FSMContext, bot: Bot):
    if await _cancel_if_command(message, state):
        raise SkipHandler
    try:
        uses = int((message.text or "").strip())
    except ValueError:
        await message.answer("Введи целое.")
        return
    data = await state.get_data()
    await db.create_promo(data["code"], data["amount"], uses)
    await state.clear()
    await message.answer(f"Промокод {data['code']} создан.", reply_markup=admin_menu())
    await notify(bot, "PROMO", f"Создан промокод <code>{esc(data['code'])}</code> на {data['amount']:.2f} ₽, активаций: {uses}")


# ---------- РАССЫЛКА ----------
@router.callback_query(F.data == "adm:broadcast")
async def cb_broadcast(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(BroadcastState.text)
    await edit_or_answer(call, "Введи текст рассылки:", back_menu("admin"))
    await call.answer()


@router.message(BroadcastState.text)
async def do_broadcast(message: types.Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    # Без этой защиты текст рассылки мог стать командой (и наоборот):
    # "/setbal ..." попал бы всем пользователям.
    if await _cancel_if_command(message, state):
        raise SkipHandler
    await state.clear()
    try:
        text = message.html_text
    except Exception:
        text = escape(message.text or "")
    users = await db.all_users()
    total = sum(1 for u in users if not u["is_banned"])
    sent = 0
    for u in users:
        if u["is_banned"]:
            continue
        try:
            await bot.send_message(u["id"], text)
            sent += 1
            await asyncio.sleep(0.05)  # лимит Telegram ~30 сообщ/сек
        except Exception:
            pass
    await message.answer(f"Отправлено: {sent}", reply_markup=admin_menu())
    await notify(bot, "BROADCAST", f"Рассылка завершена: доставлено {sent} из {total}")


# ---------- БАННЕР ----------
@router.callback_query(F.data == "adm:banner")
async def cb_banner(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    current = await db.get_setting("banner")
    text = "<b>БАННЕР ГЛАВНОЙ</b>\n━━━━━━━━━━━━━━━━━━\n"
    if current:
        text += "Сейчас баннер установлен.\nОтправь новое фото — заменится, или нажми «Убрать»."
    else:
        text += "Баннер не установлен.\nОтправь фото, чтобы установить."

    b = InlineKeyboardBuilder()
    b.button(text="Установить / Заменить", callback_data="adm:banner_set")
    b.button(text="Убрать", callback_data="adm:banner_del")
    b.button(text="Назад", callback_data="admin")
    b.adjust(1)

    if current:
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.message.answer_photo(current, caption=text, reply_markup=b.as_markup())
    else:
        await edit_or_answer(call, text, b.as_markup())
    await call.answer()


@router.callback_query(F.data == "adm:banner_set")
async def cb_banner_set(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(BannerState.waiting_photo)
    await call.message.answer("Отправь фото для баннера одним сообщением:")
    await call.answer()


@router.message(BannerState.waiting_photo, F.photo)
async def banner_photo(message: types.Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    file_id = message.photo[-1].file_id
    await db.set_setting("banner", file_id)
    await state.clear()
    await message.answer("<b>Баннер установлен.</b>", reply_markup=admin_menu())
    await notify(bot, "ADMIN", "Баннер главной обновлён")


@router.message(BannerState.waiting_photo)
async def banner_wrong(message: types.Message, state: FSMContext):
    if await _cancel_if_command(message, state):
        raise SkipHandler
    await message.answer("Отправь именно фото.")


@router.callback_query(F.data == "adm:banner_del")
async def cb_banner_del(call: types.CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        return
    await db.del_setting("banner")
    await call.answer("Баннер убран")
    await edit_or_answer(call, "<b>Баннер убран.</b>", admin_menu())
    await notify(bot, "ADMIN", "Баннер главной убран")


# ---------- ОТЗЫВЫ (просмотр) ----------
@router.callback_query(F.data == "adm:reviews")
async def cb_admin_reviews(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    async with db.connect() as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT * FROM reviews ORDER BY id DESC LIMIT 20") as cur:
            rows = await cur.fetchall()
    if not rows:
        text = "<b>ОТЗЫВЫ</b>\n━━━━━━━━━━━━━━━━━━\nПока отзывов нет."
    else:
        text = "<b>ПОСЛЕДНИЕ ОТЗЫВЫ</b>\n━━━━━━━━━━━━━━━━━━"
        for r in rows:
            text += (
                f"\n\n#{r['id']} · заказ {r['order_id']} · {'⭐' * r['rating']}\n"
                f"ID: <code>{r['user_id']}</code>\n{r['comment'] or 'Без комментария'}"
            )
    await edit_or_answer(call, text, back_menu("admin"))
    await call.answer()


# ---------- ОТВЕТ НА ОБРАЩЕНИЕ ПРЯМО ИЗ ГРУППЫ ----------
@router.callback_query(F.data.startswith("adm_reply:"))
async def cb_ticket_reply(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Только для админов", show_alert=True)
        return
    tid = int(call.data.split(":")[1])
    ticket = await db.get_ticket(tid)
    if not ticket:
        await call.answer("Обращение не найдено", show_alert=True)
        return
    await state.update_data(ticket_id=tid, ticket_user=ticket["user_id"])
    await state.set_state(TicketReplyState.answer)
    # В форуме отвечаем в той же теме, где нажали кнопку (иначе уйдёт в «Общий»)
    thread = getattr(call.message, "message_thread_id", None)
    kwargs = {"message_thread_id": thread} if thread else {}
    await call.message.answer(
        f"✏ <b>Ответ на обращение #{tid}</b>\n"
        f"Кому: <code>{ticket['user_id']}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{esc(ticket['message'][:300])}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Отправь ответ одним сообщением прямо сюда.\n"
        f"(команда — отменит ввод)",
        **kwargs,
    )
    await call.answer()


@router.message(TicketReplyState.answer)
async def process_ticket_reply(message: types.Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    if await _cancel_if_command(message, state):
        raise SkipHandler
    data = await state.get_data()
    await state.clear()
    tid = data.get("ticket_id")
    target = data.get("ticket_user")
    # Ответ администратора пишется в той же теме форума, где тикет
    thread = getattr(message, "message_thread_id", None)
    kwargs = {"message_thread_id": thread} if thread else {}
    if not target:
        await message.answer("Сессия истекла — нажми «✏ Ответить» на обращении заново.", **kwargs)
        return
    body = (message.text or "").strip()
    if not body:
        await message.answer("Пустой ответ — нажми «✏ Ответить» и напиши текст.", **kwargs)
        return
    await db.set_ticket_status(tid, "answered")
    delivered = await safe_send(
        bot, target,
        f"<b>Ответ поддержки</b> (обращение #{tid})\n\n{escape(body)}",
    )
    await message.answer(
        "✅ Ответ отправлен пользователю." if delivered else "❌ Не доставлен: пользователь не писал боту (/start).",
        **kwargs,
    )
    await notify(bot, "SUPPORT", f"Ответ на обращение #{tid} отправлен пользователю <code>{target}</code>:\n{esc(body[:400])}")


# ---------- ОТВЕТ ПОДДЕРЖКИ (командой) ----------
@router.message(Command("reply"))
async def cmd_reply_ticket(message: types.Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    try:
        parts = message.text.split(maxsplit=2)
        uid = int(parts[1])
        body = parts[2]
        await bot.send_message(uid, f"<b>Ответ поддержки</b>\n\n{escape(body)}")
        await message.answer("Ответ отправлен.")
        await notify(bot, "SUPPORT", f"Ответ поддержки → <code>{uid}</code>:\n{esc(body[:500])}")
    except Exception:
        await message.answer("Формат: /reply ID текст")
