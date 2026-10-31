# -*- coding: utf-8 -*-
"""Промокоды для пользователей."""
from aiogram import Bot, F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from .. import db
from ..keyboards import back_menu
from ..logs import esc, notify, user_line
from ..texts import PROMO_TEXT
from ..utils import edit_or_answer

router = Router()


class PromoState(StatesGroup):
    code = State()


@router.callback_query(F.data == "promo")
async def cb_promo(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(PromoState.code)
    await edit_or_answer(call, PROMO_TEXT, back_menu())
    await call.answer()


@router.message(PromoState.code)
async def process_promo(message: types.Message, state: FSMContext, bot: Bot):
    if not message.text or not message.text.strip():
        await message.answer("Отправь код одним сообщением.", reply_markup=back_menu())
        return
    code = message.text.strip().upper()
    await state.clear()
    promo = await db.get_promo(code)
    if not promo:
        await message.answer("Промокод не найден.", reply_markup=back_menu())
        return
    if not promo["is_active"] or promo["uses_left"] <= 0:
        await message.answer("Промокод неактивен.", reply_markup=back_menu())
        return
    if await db.user_used_promo(message.from_user.id, code):
        await message.answer("Ты уже использовал этот промокод.", reply_markup=back_menu())
        return
    if not await db.use_promo(code):
        # Кто-то забрал последние активации первыми
        await message.answer("Промокод закончился.", reply_markup=back_menu())
        return
    await db.update_balance(message.from_user.id, promo["amount"])
    await db.log_promo(message.from_user.id, code)
    await message.answer(
        f"<b>Промокод активирован.</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Зачислено: <b>{promo['amount']:.2f} ₽</b>",
        reply_markup=back_menu(),
    )
    await notify(
        bot, "PROMO",
        f"Активирован промокод <code>{esc(code)}</code> на {promo['amount']:.2f} ₽ "
        f"(осталось активаций: {promo['uses_left'] - 1})\n"
        f"{user_line(message.from_user.id, message.from_user.first_name, message.from_user.username)}",
    )
