# -*- coding: utf-8 -*-
"""Старт, меню, правила, поддержка, проверка подписки."""
from html import escape

from aiogram import Bot, F, Router, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import config, db
from ..keyboards import back_menu, main_menu, subscribe_kb
from ..logs import notify, user_line
from ..texts import START_TEXT, rules_text, subscribe_text, support_text
from ..utils import check_subscription, edit_or_answer, is_admin, notify_admins

router = Router()


class SupportState(StatesGroup):
    message = State()


# ---------- START ----------
@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear()
    args = (message.text or "").split(maxsplit=1)
    ref = None
    if len(args) > 1 and args[1].isdigit():
        ref = int(args[1])
        if ref == message.from_user.id:
            ref = None
    uid = message.from_user.id
    is_new = await db.add_user(uid, message.from_user.username, message.from_user.first_name, ref)
    u = await db.get_user(uid)
    if u and u["is_banned"]:
        try:
            await message.answer("Вы заблокированы.")
        except Exception:
            pass
        return

    # проверка подписки
    if not is_admin(uid) and not await check_subscription(bot, uid):
        try:
            await message.answer(subscribe_text(), reply_markup=subscribe_kb())
        except Exception:
            pass
        return

    banner = await db.get_setting("banner")
    kb = main_menu(is_admin(uid))
    try:
        if banner:
            await message.answer_photo(banner, caption=START_TEXT, reply_markup=kb)
        else:
            await message.answer(START_TEXT, reply_markup=kb)
    except Exception:
        try:
            await message.answer(START_TEXT, reply_markup=kb)
        except Exception:
            pass

    who = user_line(uid, message.from_user.first_name, message.from_user.username)
    if is_new:
        ref_note = f"\nПригласил: <code>{ref}</code>" if ref else ""
        total = await db.count_users()
        await notify(bot, "USER", f"Новый пользователь: {who}{ref_note}\nВсего пользователей: {total}")
    else:
        await notify(bot, "USER", f"Зашёл в бота: {who}")


@router.message(Command("menu"))
async def cmd_menu(message: types.Message, state: FSMContext, bot: Bot):
    await state.clear()
    if not is_admin(message.from_user.id):
        if not await check_subscription(bot, message.from_user.id):
            await message.answer(subscribe_text(), reply_markup=subscribe_kb())
            return
    banner = await db.get_setting("banner")
    kb = main_menu(is_admin(message.from_user.id))
    try:
        if banner:
            await message.answer_photo(banner, caption=START_TEXT, reply_markup=kb)
        else:
            await message.answer(START_TEXT, reply_markup=kb)
    except Exception:
        pass


@router.callback_query(F.data == "check_sub")
async def cb_check_sub(call: types.CallbackQuery, bot: Bot):
    if not await check_subscription(bot, call.from_user.id):
        await call.answer("Ты ещё не подписался на канал.", show_alert=True)
        return
    await call.answer("Подписка подтверждена.")
    banner = await db.get_setting("banner")
    await edit_or_answer(call, START_TEXT, main_menu(is_admin(call.from_user.id)), photo=banner)


@router.callback_query(F.data == "main")
async def cb_main(call: types.CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    if not is_admin(call.from_user.id) and not await check_subscription(bot, call.from_user.id):
        await edit_or_answer(call, subscribe_text(), subscribe_kb())
        await call.answer()
        return
    banner = await db.get_setting("banner")
    await edit_or_answer(call, START_TEXT, main_menu(is_admin(call.from_user.id)), photo=banner)
    await call.answer()


@router.callback_query(F.data == "rules")
async def cb_rules(call: types.CallbackQuery):
    await edit_or_answer(call, rules_text(), back_menu(), preview_off=True)
    await call.answer()


@router.callback_query(F.data == "support")
async def cb_support(call: types.CallbackQuery):
    b = InlineKeyboardBuilder()
    b.button(text="Написать в поддержку", callback_data="support_ticket")
    b.button(text="Открыть контакт", url=f"https://t.me/{config.SUPPORT_USERNAME.lstrip('@')}")
    b.button(text="Назад", callback_data="main")
    b.adjust(1)
    await edit_or_answer(
        call,
        support_text() + "\nИли отправь обращение прямо здесь — оно попадёт администратору.",
        b.as_markup(),
        preview_off=True,
    )
    await call.answer()


@router.callback_query(F.data == "support_ticket")
async def support_ticket_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(SupportState.message)
    await call.message.answer("Опиши вопрос одним сообщением. Мы передадим его администратору.", reply_markup=back_menu())
    await call.answer()


@router.message(SupportState.message)
async def support_ticket_send(message: types.Message, state: FSMContext, bot: Bot):
    body = (message.text or message.caption or "").strip()
    if not body:
        await message.answer("Пожалуйста, отправь текст обращения.")
        return
    await state.clear()
    tid = await db.create_ticket(message.from_user.id, body)
    kb = InlineKeyboardBuilder()
    kb.button(text="✏ Ответить", callback_data=f"adm_reply:{tid}")
    await notify(
        bot, "SUPPORT",
        f"Новое обращение #{tid}\n{user_line(message.from_user.id, message.from_user.first_name, message.from_user.username)}\n\n{escape(body[:800])}",
        reply_markup=kb.as_markup(),
    )
    await notify_admins(
        bot,
        f"<b>Новое обращение #{tid}</b>\nОт: <code>{message.from_user.id}</code> "
        f"(@{message.from_user.username or '-'})\n\n{escape(body[:3500])}\n\n"
        f"Ответить: кнопка «✏ Ответить» в теме «🎫 Поддержка» "
        f"или <code>/reply {message.from_user.id} текст</code>",
    )
    await message.answer(f"Обращение #{tid} отправлено. Ожидай ответа.", reply_markup=back_menu("main"))
