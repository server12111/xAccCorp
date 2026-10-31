# -*- coding: utf-8 -*-
"""Оплата заказов: CryptoBot, xRocket, TON, карта, баланс. Отмена заказа."""
from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import config, db, logs, payments
from ..keyboards import back_menu, check_crypto_kb, payment_methods
from ..logs import esc, notify, user_line
from ..utils import (
    edit_or_answer, fetch_rates, gen_track, notify_admins, notify_admins_photo,
)

router = Router()


class PaymentState(StatesGroup):
    screenshot = State()


def _who(call_or_msg) -> str:
    u = call_or_msg.from_user
    return user_line(u.id, u.first_name, u.username)


# ---------- ОФОРМЛЕНИЕ ЗАКАЗА ----------
@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: types.CallbackQuery, bot: Bot):
    pid = int(call.data.split(":")[1])
    p = await db.get_product(pid)
    if not p or not p["is_active"]:
        await call.answer("Товар недоступен", show_alert=True)
        return
    if p["stock"] <= 0:
        await call.answer("Нет в наличии", show_alert=True)
        return
    u = await db.get_user(call.from_user.id)
    if u and u["is_banned"]:
        await call.answer("Ты заблокирован", show_alert=True)
        return

    rub, ton = await fetch_rates()
    amount_usd = p["price_usd"]
    amount_rub = amount_usd * rub
    amount_ton = amount_usd / ton if ton else 0
    track = gen_track()

    oid = await db.create_order(
        call.from_user.id, pid, p["name"],
        amount_usd, amount_rub, amount_ton,
        "pending", track, status="awaiting_payment",
    )

    text = (
        f"<b>ОФОРМЛЕНИЕ ЗАКАЗА #{oid}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Товар:</b> {esc(p['name'])}\n"
        f"<b>Цена:</b> {amount_usd:.2f} $ / {amount_rub:.2f} ₽ / {amount_ton:.4f} TON\n"
        f"<b>Трек:</b> <code>{track}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Выбери способ оплаты:"
    )
    await edit_or_answer(call, text, payment_methods(oid))
    await notify(
        bot, "ORDER",
        f"Новый заказ #{oid}\nТовар: {esc(p['name'])} · {amount_usd:.2f} $\n"
        f"Трек: <code>{track}</code>\nПользователь: {_who(call)}",
    )
    await call.answer()


# ---------- БАЛАНС ----------
@router.callback_query(F.data.startswith("pay_balance:"))
async def cb_pay_balance(call: types.CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    u = await db.get_user(call.from_user.id)
    if not o or not u or o["user_id"] != call.from_user.id or o["status"] != "awaiting_payment" or not o["product_id"]:
        await call.answer("Заказ недоступен", show_alert=True)
        return
    if u["balance"] < o["amount_rub"]:
        await call.answer(f"Недостаточно. Нужно {o['amount_rub']:.2f} ₽", show_alert=True)
        return
    # Одна транзакция защищает баланс от двойных кликов и гонки колбэков.
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        async with conn.execute("SELECT balance FROM users WHERE id=?", (call.from_user.id,)) as c:
            balance_row = await c.fetchone()
        async with conn.execute("SELECT status FROM orders WHERE id=? AND user_id=?", (oid, call.from_user.id)) as c:
            order_row = await c.fetchone()
        async with conn.execute("SELECT stock FROM products WHERE id=?", (o["product_id"],)) as c:
            stock_row = await c.fetchone()
        if (not order_row or order_row[0] != "awaiting_payment" or not balance_row
                or balance_row[0] < o["amount_rub"] or not stock_row or stock_row[0] < 1):
            await conn.rollback()
            await call.answer("Недостаточно средств или товара; обнови заказ.", show_alert=True)
            return
        await conn.execute("UPDATE users SET balance=balance-? WHERE id=?", (o["amount_rub"], call.from_user.id))
        await conn.execute("UPDATE products SET stock=stock-1 WHERE id=? AND stock>0", (o["product_id"],))
        await conn.execute("UPDATE orders SET status='paid',payment_method='Баланс',updated_at=? WHERE id=?", (db.now(), oid))
        await conn.commit()
    await db.apply_referral_reward(oid, call.from_user.id, o["amount_rub"])
    await logs.check_low_stock(bot, o["product_id"])
    await edit_or_answer(
        call,
        f"<b>ОПЛАЧЕНО</b>\nЗаказ: #{oid}\nТрек: <code>{o['track']}</code>\n"
        f"Отправь трек в поддержку {config.SUPPORT_USERNAME}.",
        back_menu("main"),
    )
    await notify(
        bot, "PAYMENT",
        f"Оплата с баланса: заказ #{oid} на {o['amount_rub']:.2f} ₽\nПользователь: {_who(call)}",
    )
    await notify_admins(bot, f"Оплата балансом: заказ #{oid}, пользователь {call.from_user.id}, {o['amount_rub']:.2f} ₽")
    await call.answer("Оплачено")


# ---------- CRYPTOBOT ----------
@router.callback_query(F.data.startswith("pay_crypto:"))
async def cb_pay_crypto(call: types.CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o or o["user_id"] != call.from_user.id or o["status"] != "awaiting_payment":
        await call.answer("Заказ не найден или уже обработан", show_alert=True)
        return
    amount_with_fee = o["amount_usd"] * (1 + config.CRYPTO_FEE / 100)
    pay_url, inv_id = await payments.create_crypto_invoice(amount_with_fee, f"Order #{oid}")
    if not pay_url:
        await notify(bot, "PAYMENT", f"Ошибка создания счёта CryptoBot для заказа #{oid}")
        await call.answer("Ошибка создания счёта. Попробуй другой способ.", show_alert=True)
        return
    await db.set_order_field(oid, "screenshot_id", f"inv:{inv_id}")
    text = (
        f"<b>ОПЛАТА ЧЕРЕЗ CRYPTOBOT</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Заказ:</b> #{oid}\n"
        f"<b>К оплате:</b> {amount_with_fee:.2f} USDT (включена надбавка +{config.CRYPTO_FEE:g}%)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"1. Перейди по ссылке и оплати.\n"
        f"2. Вернись и нажми кнопку «Проверить оплату».\n\n"
        f"<b>Ссылка:</b> {pay_url}"
    )
    await edit_or_answer(call, text, check_crypto_kb(oid), preview_off=True)
    await notify(
        bot, "PAYMENT",
        f"Счёт CryptoBot создан: заказ #{oid} на {amount_with_fee:.2f} USDT\nПользователь: {_who(call)}",
    )
    await call.answer()


@router.callback_query(F.data.startswith("check_crypto:"))
async def cb_check_crypto(call: types.CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o or o["user_id"] != call.from_user.id:
        await call.answer("Заказ не найден", show_alert=True)
        return
    if o["status"] != "awaiting_payment":
        await call.answer("Заказ уже обработан", show_alert=True)
        return
    marker = str(o["screenshot_id"] or "")
    if not marker.startswith("inv:"):
        await call.answer("Счёт не найден", show_alert=True)
        return
    if not await payments.check_crypto_invoice(marker.split("inv:", 1)[1]):
        await call.answer("Оплата ещё не поступила", show_alert=True)
        return
    order, changed = await db.finish_paid_order(oid, call.from_user.id)
    if not changed:
        await call.answer("Платёж уже обработан или заказ недоступен", show_alert=True)
        return
    await logs.check_low_stock(bot, o["product_id"])
    if o["product_id"]:
        success = f"Заказ #{oid} оплачен. Трек: <code>{o['track']}</code>. Отправь его в поддержку {config.SUPPORT_USERNAME}."
    else:
        success = f"На баланс зачислено <b>{o['amount_rub']:.2f} ₽</b>."
    await edit_or_answer(call, f"<b>ОПЛАЧЕНО</b>\n{success}", back_menu("main"))
    await notify(
        bot, "PAYMENT",
        f"CryptoBot: оплата подтверждена — заказ #{oid} на {o['amount_usd']:.2f} $\n"
        f"Товар: {esc(o['product_name'])}\nПользователь: {_who(call)}",
    )
    await notify_admins(
        bot,
        f"<b>Оплата CryptoBot</b>\nЗаказ #{oid}\n"
        f"Пользователь: <code>{call.from_user.id}</code>\n"
        f"Товар: {o['product_name']}\n"
        f"Сумма: {o['amount_usd']:.2f} $\n"
        f"Трек: <code>{o['track']}</code>",
    )
    await call.answer("Оплата подтверждена")


# ---------- XROCKET ----------
@router.callback_query(F.data.startswith("pay_xrocket:"))
async def cb_pay_xrocket(call: types.CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o or o["user_id"] != call.from_user.id or o["status"] != "awaiting_payment":
        await call.answer("Заказ недоступен", show_alert=True)
        return
    url, inv = await payments.create_xrocket_invoice(o["amount_usd"], f"Заказ #{oid}", f"order_{oid}", call.from_user.id)
    if not url or not inv:
        await notify(bot, "PAYMENT", f"Ошибка создания счёта xRocket для заказа #{oid}")
        await call.answer("xRocket не настроен или счёт не создан", show_alert=True)
        return
    await db.set_order_field(oid, "screenshot_id", f"xr:{inv}")
    await db.set_order_field(oid, "payment_method", "xRocket")
    b = InlineKeyboardBuilder()
    b.button(text="Оплатить в xRocket", url=url)
    b.button(text="Проверить оплату", callback_data=f"check_xrocket:{oid}")
    b.button(text="Отмена", callback_data=f"cancel_order:{oid}")
    b.adjust(1)
    await edit_or_answer(call, f"<b>xROCKET · ЗАКАЗ #{oid}</b>\nК оплате: {o['amount_usd']:.2f} USDT", b.as_markup(), preview_off=True)
    await notify(
        bot, "PAYMENT",
        f"Счёт xRocket создан: заказ #{oid} на {o['amount_usd']:.2f} USDT\nПользователь: {_who(call)}",
    )
    await call.answer()


@router.callback_query(F.data.startswith("check_xrocket:"))
async def cb_check_xrocket(call: types.CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o or o["user_id"] != call.from_user.id:
        await call.answer("Заказ не найден", show_alert=True)
        return
    if o["status"] != "awaiting_payment":
        await call.answer("Заказ уже обработан", show_alert=True)
        return
    marker = str(o["screenshot_id"] or "")
    if not marker.startswith("xr:"):
        await call.answer("Счёт не найден", show_alert=True)
        return
    if not await payments.check_xrocket_invoice(marker[3:]):
        await call.answer("Оплата ещё не подтверждена", show_alert=True)
        return
    order, changed = await db.finish_paid_order(oid, call.from_user.id)
    if not changed:
        await call.answer("Платёж уже обработан или заказ недоступен", show_alert=True)
        return
    await logs.check_low_stock(bot, o["product_id"])
    if o["product_id"]:
        result = f"Заказ #{oid} оплачен. Трек: <code>{o['track']}</code>. Напиши в поддержку {config.SUPPORT_USERNAME}."
    else:
        result = f"На баланс зачислено <b>{o['amount_rub']:.2f} ₽</b>."
    await edit_or_answer(call, f"<b>ОПЛАТА ПОДТВЕРЖДЕНА</b>\n{result}", back_menu("main"))
    await notify(
        bot, "PAYMENT",
        f"xRocket: оплата подтверждена — заказ #{oid} на {o['amount_usd']:.2f} $\n"
        f"Товар: {esc(o['product_name'])}\nПользователь: {_who(call)}",
    )
    await notify_admins(bot, f"xRocket: платёж #{oid} подтверждён, пользователь {call.from_user.id}")
    await call.answer("Оплата подтверждена")


# ---------- ПОПОЛНЕНИЕ ЧЕРЕЗ КРИПТУ ----------
@router.callback_query(F.data.startswith("topup_crypto:"))
async def cb_topup_crypto(call: types.CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o or o["user_id"] != call.from_user.id or o["product_id"] != 0 or o["status"] != "awaiting_payment":
        await call.answer("Пополнение не найдено", show_alert=True)
        return
    url, inv = await payments.create_crypto_invoice(o["amount_usd"], f"TopUp #{oid}")
    if not url or not inv:
        await notify(bot, "PAYMENT", f"Ошибка создания счёта CryptoBot для пополнения #{oid}")
        await call.answer("Не удалось создать счёт CryptoBot", show_alert=True)
        return
    await db.set_order_field(oid, "screenshot_id", f"inv:{inv}")
    await db.set_order_field(oid, "payment_method", "CryptoBot")
    await edit_or_answer(
        call,
        f"Пополнение #{oid}: {o['amount_rub']:.2f} ₽\nОплати: {url}\nПосле оплаты нажми проверку.",
        check_crypto_kb(oid),
        preview_off=True,
    )
    await notify(bot, "PAYMENT", f"Счёт CryptoBot создан для пополнения #{oid} ({o['amount_usd']:.2f} USDT)\nПользователь: {_who(call)}")
    await call.answer()


@router.callback_query(F.data.startswith("topup_xrocket:"))
async def cb_topup_xrocket(call: types.CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o or o["user_id"] != call.from_user.id or o["product_id"] != 0 or o["status"] != "awaiting_payment":
        await call.answer("Пополнение не найдено", show_alert=True)
        return
    url, inv = await payments.create_xrocket_invoice(o["amount_usd"], f"Пополнение #{oid}", f"topup_{oid}", call.from_user.id)
    if not url or not inv:
        await notify(bot, "PAYMENT", f"Ошибка создания счёта xRocket для пополнения #{oid}")
        await call.answer("xRocket не настроен или счёт не создан", show_alert=True)
        return
    await db.set_order_field(oid, "screenshot_id", f"xr:{inv}")
    await db.set_order_field(oid, "payment_method", "xRocket")
    b = InlineKeyboardBuilder()
    b.button(text="Оплатить в xRocket", url=url)
    b.button(text="Проверить оплату", callback_data=f"check_xrocket:{oid}")
    b.adjust(1)
    await edit_or_answer(
        call,
        f"Пополнение #{oid}: {o['amount_rub']:.2f} ₽ ({o['amount_usd']:.2f} USDT)",
        b.as_markup(),
        preview_off=True,
    )
    await notify(bot, "PAYMENT", f"Счёт xRocket создан для пополнения #{oid} ({o['amount_usd']:.2f} USDT)\nПользователь: {_who(call)}")
    await call.answer()


# ---------- TON / КАРТА (вручную, по скрину) ----------
@router.callback_query(F.data.startswith("pay_ton:"))
async def cb_pay_ton(call: types.CallbackQuery, state: FSMContext):
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o or o["user_id"] != call.from_user.id or o["status"] != "awaiting_payment":
        await call.answer("Заказ недоступен", show_alert=True)
        return
    await state.update_data(order_id=oid, method="TON")
    await state.set_state(PaymentState.screenshot)
    text = (
        f"<b>ОПЛАТА В TON</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Заказ:</b> #{oid}\n"
        f"<b>Сумма:</b> {o['amount_ton']:.4f} TON\n"
        f"<b>Адрес:</b>\n<code>{config.TON_ADDRESS}</code>\n"
        f"<b>Комментарий:</b> <code>{o['track']}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Обязательно укажи комментарий к переводу.\n"
        f"После оплаты отправь скрин сюда."
    )
    await edit_or_answer(call, text, back_menu())
    await call.answer()


@router.callback_query(F.data.startswith("pay_card:"))
async def cb_pay_card(call: types.CallbackQuery, state: FSMContext):
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o or o["user_id"] != call.from_user.id or o["status"] != "awaiting_payment":
        await call.answer("Заказ недоступен", show_alert=True)
        return
    await state.update_data(order_id=oid, method="CARD")
    await state.set_state(PaymentState.screenshot)
    text = (
        f"<b>ОПЛАТА НА КАРТУ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Заказ:</b> #{oid}\n"
        f"<b>Сумма:</b> {o['amount_rub']:.2f} ₽\n"
        f"<b>Карта:</b>\n<code>{config.CARD_NUMBER}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Переведи точную сумму и отправь скрин сюда.\n"
        f"Админ подтвердит оплату вручную."
    )
    await edit_or_answer(call, text, back_menu())
    await call.answer()


@router.message(PaymentState.screenshot, F.photo)
async def process_screenshot(message: types.Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    oid = data.get("order_id")
    method = data.get("method", "?")
    await state.clear()
    o = await db.get_order(oid) if oid else None
    if not o or o["user_id"] != message.from_user.id or o["status"] != "awaiting_payment":
        await message.answer("Заказ недоступен или уже обработан. Оформи оплату заново.")
        return
    file_id = message.photo[-1].file_id
    await db.set_order_screenshot(oid, file_id)
    await db.set_order_field(oid, "payment_method", method)
    caption = (
        f"<b>НОВАЯ ОПЛАТА НА ПРОВЕРКУ</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Заказ:</b> #{oid}\n"
        f"<b>Метод:</b> {method}\n"
        f"<b>Пользователь:</b> <code>{message.from_user.id}</code> "
        f"(@{message.from_user.username or '-'})\n"
        f"<b>Товар:</b> {esc(o['product_name'])}\n"
        f"<b>Сумма:</b> {o['amount_usd']:.2f} $ / {o['amount_rub']:.2f} ₽ / {o['amount_ton']:.4f} TON\n"
        f"<b>Трек:</b> <code>{o['track']}</code>"
    )
    from ..keyboards import admin_order_actions
    await notify_admins_photo(bot, file_id, caption=caption,
                              reply_markup=admin_order_actions(oid, "on_review"))
    await notify(
        bot, "PAYMENT",
        f"Скрин оплаты отправлен на проверку (метод {method}) — заказ #{oid} на {o['amount_rub']:.2f} ₽\nПользователь: {_who(message)}",
    )
    await message.answer(
        f"<b>Скрин получен</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Заказ #{oid} отправлен на проверку. Ожидай подтверждения.",
        reply_markup=back_menu("main"),
    )


@router.message(PaymentState.screenshot)
async def wrong_screenshot(message: types.Message):
    await message.answer("Отправь именно фото (скрин) оплаты.")


# ---------- ОТМЕНА ----------
@router.callback_query(F.data.startswith("cancel_order:"))
async def cb_cancel_order(call: types.CallbackQuery, bot: Bot):
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o or o["user_id"] != call.from_user.id or o["status"] != "awaiting_payment":
        await call.answer("Заказ не найден или уже обработан", show_alert=True)
        return
    await db.set_order_status(oid, "cancelled")
    await edit_or_answer(call, "Заказ отменён.", back_menu("main"))
    await notify(
        bot, "ORDER",
        f"Заказ #{oid} отменён ({esc(o['product_name'])} · {o['amount_usd']:.2f} $)\nПользователь: {_who(call)}",
    )
    await call.answer()
