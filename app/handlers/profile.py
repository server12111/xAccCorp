# -*- coding: utf-8 -*-
"""Профиль, мои заказы, реферальная программа, отзывы."""
from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from .. import config, db
from ..keyboards import back_menu, user_orders_kb
from ..logs import esc, notify, user_line
from ..texts import profile_text
from ..utils import edit_or_answer, notify_admins
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()


class ReviewState(StatesGroup):
    comment = State()


@router.callback_query(F.data == "profile")
async def cb_profile(call: types.CallbackQuery):
    u = await db.get_user(call.from_user.id)
    if not u:
        await call.answer("Нажми /start", show_alert=True)
        return
    orders = await db.get_user_orders(call.from_user.id)
    total = sum(o["amount_usd"] for o in orders if o["status"] in ("paid", "issued", "completed"))
    text = profile_text(u, len(orders), total)
    b = InlineKeyboardBuilder()
    b.button(text="Мои заказы", callback_data="my_orders")
    b.button(text="Реферальная ссылка", callback_data="ref_link")
    b.button(text="Назад", callback_data="main")
    b.adjust(1)
    await edit_or_answer(call, text, b.as_markup())
    await call.answer()


@router.callback_query(F.data == "ref_link")
async def cb_ref(call: types.CallbackQuery, bot: Bot):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={call.from_user.id}"
    invited, earned = await db.referral_stats(call.from_user.id)
    percent = f"{float(config.REFERRAL_PERCENT):g}"
    text = (f"<b>РЕФЕРАЛЬНАЯ ПРОГРАММА</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"<code>{link}</code>\n━━━━━━━━━━━━━━━━━━\n"
            f"Приглашено: <b>{invited}</b>\nЗаработано: <b>{earned:.2f} ₽</b>\n"
            f"Бонус: <b>{percent}%</b> с каждой оплаченной покупки приглашённого.\n"
            f"Начисление автоматически на баланс.")
    await edit_or_answer(call, text, back_menu("profile"))
    await call.answer()


@router.callback_query(F.data == "my_orders")
async def cb_my_orders(call: types.CallbackQuery):
    orders = await db.get_user_orders(call.from_user.id)
    if not orders:
        text = "<b>МОИ ЗАКАЗЫ</b>\n━━━━━━━━━━━━━━━━━━\nУ тебя пока нет заказов."
        await edit_or_answer(call, text, back_menu("profile"))
    else:
        text = "<b>МОИ ЗАКАЗЫ</b>\n━━━━━━━━━━━━━━━━━━"
        await edit_or_answer(call, text, user_orders_kb(orders))
    await call.answer()


@router.callback_query(F.data.startswith("my_ord:"))
async def cb_my_order(call: types.CallbackQuery):
    oid = int(call.data.split(":")[1])
    o = await db.get_order(oid)
    if not o or o["user_id"] != call.from_user.id:
        await call.answer("Не найден", show_alert=True)
        return
    text = (
        f"<b>ЗАКАЗ #{o['id']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Товар:</b> {o['product_name']}\n"
        f"<b>Сумма:</b> {o['amount_usd']:.2f} $ / {o['amount_rub']:.2f} ₽\n"
        f"<b>Способ оплаты:</b> {o['payment_method']}\n"
        f"<b>Статус:</b> {o['status']}\n"
        f"<b>Трек:</b> <code>{o['track'] or '-'}</code>\n"
        f"<b>Дата:</b> {o['created_at']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Для получения товара напиши трек в поддержку: {config.SUPPORT_USERNAME}"
    )
    kb = InlineKeyboardBuilder()
    if o["status"] in ("completed", "issued"):
        kb.button(text="Оставить отзыв", callback_data=f"review:{oid}")
    kb.button(text="Назад", callback_data="my_orders")
    kb.adjust(1)
    await edit_or_answer(call, text, kb.as_markup())
    await call.answer()


# ---------- ОТЗЫВЫ ----------
@router.callback_query(F.data.startswith("review:"))
async def cb_review_start(call: types.CallbackQuery, state: FSMContext):
    oid = int(call.data.split(":")[1])
    order = await db.get_order(oid)
    if not order or order["user_id"] != call.from_user.id or order["status"] not in ("completed", "issued"):
        await call.answer("Отзыв доступен после получения заказа", show_alert=True)
        return
    if await db.review_exists(oid):
        await call.answer("Отзыв уже оставлен", show_alert=True)
        return
    await state.update_data(review_order_id=oid)
    b = InlineKeyboardBuilder()
    for n in range(1, 6):
        b.button(text="⭐" * n, callback_data=f"review_rate:{n}")
    b.adjust(1)
    await call.message.answer("Оцени покупку:", reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("review_rate:"))
async def cb_review_rate(call: types.CallbackQuery, state: FSMContext):
    rating = int(call.data.split(":")[1])
    data = await state.get_data()
    oid = data.get("review_order_id")
    order = await db.get_order(oid) if oid else None
    if not order or order["user_id"] != call.from_user.id:
        await call.answer("Сессия отзыва истекла", show_alert=True)
        return
    await state.update_data(review_rating=rating)
    await state.set_state(ReviewState.comment)
    await call.message.answer("Напиши комментарий к отзыву или отправь символ - чтобы пропустить.")
    await call.answer()


@router.message(ReviewState.comment)
async def save_review(message: types.Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    oid = data.get("review_order_id")
    rating = int(data.get("review_rating", 5))
    order = await db.get_order(oid) if oid else None
    if not order or order["user_id"] != message.from_user.id:
        await state.clear()
        await message.answer("Заказ не найден.")
        return
    comment = (message.text or "").strip()
    comment = "" if comment == "-" else comment[:1000]
    ok = await db.add_review(message.from_user.id, oid, order["product_id"], rating, comment)
    if not ok:
        await message.answer("Отзыв по этому заказу уже существует.")
        await state.clear()
        return
    await state.clear()
    await message.answer("Спасибо! Отзыв сохранён.", reply_markup=back_menu("profile"))
    await notify(
        bot, "REVIEW",
        f"Новый отзыв · заказ #{oid} · {'⭐' * rating}\n"
        f"{user_line(message.from_user.id, message.from_user.first_name, message.from_user.username)}\n"
        f"{esc(comment) if comment else 'Без комментария'}",
    )
    await notify_admins(
        bot,
        f"<b>Новый отзыв</b> · заказ #{oid} · {rating}/5\n"
        f"Пользователь <code>{message.from_user.id}</code>\n"
        f"{esc(comment) if comment else 'Без комментария'}",
    )
