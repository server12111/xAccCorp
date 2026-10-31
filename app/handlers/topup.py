# -*- coding: utf-8 -*-
"""Пополнение баланса."""
import time

from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from .. import db
from ..keyboards import back_menu, topup_methods
from ..logs import notify, user_line
from ..utils import edit_or_answer, fetch_rates

router = Router()


class TopUpState(StatesGroup):
    amount = State()


@router.callback_query(F.data == "topup")
async def cb_topup(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(TopUpState.amount)
    text = (
        "<b>ПОПОЛНЕНИЕ БАЛАНСА</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Введи сумму в рублях, на которую хочешь пополнить баланс.\n"
        "Например: <code>500</code>"
    )
    await edit_or_answer(call, text, back_menu())
    await call.answer()


@router.message(TopUpState.amount)
async def process_topup(message: types.Message, state: FSMContext, bot: Bot):
    try:
        amount = float(message.text.replace(",", "."))
        if not 1 <= amount <= 1000000:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        await message.answer("Введи сумму от 1 до 1 000 000 ₽.")
        return
    await state.clear()
    rub, ton = await fetch_rates()
    if not rub or not ton:
        await message.answer("Не удалось получить курс валют. Попробуй позже.")
        return
    usd = amount / rub
    track = f"TOPUP-{message.from_user.id}-{int(time.time())}"
    oid = await db.create_order(
        message.from_user.id, 0, "Пополнение баланса",
        usd, amount, usd / ton, "TOPUP", track, status="awaiting_payment",
    )
    await message.answer(
        f"<b>ПОПОЛНЕНИЕ НА {amount:.2f} ₽</b>\nЭквивалент: {usd:.2f} USDT\nВыбери платёжную систему:",
        reply_markup=topup_methods(oid),
    )
    await notify(
        bot, "PAYMENT",
        f"Запрос пополнения баланса: {amount:.2f} ₽ ({usd:.2f} USDT), заказ #{oid}\n"
        f"{user_line(message.from_user.id, message.from_user.first_name, message.from_user.username)}",
    )
