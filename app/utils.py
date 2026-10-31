# -*- coding: utf-8 -*-
"""Общие утилиты: админ, клавиатурные стили, безопасные отправки, курсы валют."""
import logging
import random
import string
import time

import aiohttp
from aiogram import Bot, types
from aiogram.types import LinkPreviewOptions

from . import config


def is_admin(uid) -> bool:
    return uid in config.ADMIN_IDS


async def notify_admins(bot: Bot, text: str, **kwargs):
    """Отправить сообщение всем админам в ЛС (без исключений)."""
    for uid in config.ADMIN_IDS:
        await safe_send(bot, uid, text, **kwargs)


async def notify_admins_photo(bot: Bot, photo, caption: str = None, **kwargs):
    """Отправить фото всем админам в ЛС (без исключений)."""
    for uid in config.ADMIN_IDS:
        await safe_send_photo(bot, uid, photo, caption=caption, **kwargs)


def gen_track() -> str:
    return "XC-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def _style(kb, row, col, style=None, icon=None):
    """Вешает стиль/премиум-иконку на кнопку (если версия aiogram их поддерживает)."""
    try:
        btn = kb.inline_keyboard[row][col]
        if style:
            btn.style = style
        if icon:
            btn.icon_custom_emoji_id = icon
    except Exception:
        pass
    return kb


async def edit_or_answer(call: types.CallbackQuery, text: str, kb=None,
                         photo=None, preview_off: bool = False) -> None:
    """Правит сообщение, а если нельзя (например это фото) — шлёт новое. Не бросает исключений."""
    kwargs = {"reply_markup": kb}
    if preview_off:
        kwargs["link_preview_options"] = LinkPreviewOptions(is_disabled=True)
    try:
        if photo:
            try:
                await call.message.delete()
            except Exception:
                pass
            await call.message.answer_photo(photo, caption=text, **kwargs)
        else:
            await call.message.edit_text(text, **kwargs)
    except Exception:
        try:
            await call.message.answer(text, **kwargs)
        except Exception:
            pass


async def safe_send(bot: Bot, chat_id, text: str, **kwargs):
    """Отправка сообщения без исключений (например, если админ заблокировал бота)."""
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except Exception:
        return None


async def safe_send_photo(bot: Bot, chat_id, photo, caption: str = None, **kwargs):
    try:
        return await bot.send_photo(chat_id, photo, caption=caption, **kwargs)
    except Exception:
        return None


async def check_subscription(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(config.CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logging.warning(f"sub check error: {e}")
        return False


# ============================================================
#  КУРСЫ ВАЛЮТ (кэш на 10 минут)
# ============================================================
_cache = {"rub": 95.0, "ton": 4.5, "ts": 0}

# Без User-Agent публичные API курсов иногда отдают 403
_RATES_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; XCorpShopBot/1.0)"}


async def fetch_rates():
    if time.time() - _cache["ts"] < 600:
        return _cache["rub"], _cache["ton"]
    rub, ton = _cache["rub"], _cache["ton"]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://open.er-api.com/v6/latest/USD", headers=_RATES_HEADERS, timeout=10) as r:
                d = await r.json()
                if "rates" in d and "RUB" in d["rates"]:
                    rub = float(d["rates"]["RUB"])
    except Exception:
        pass
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd",
                headers=_RATES_HEADERS, timeout=10,
            ) as r:
                d = await r.json()
                ton = float(d["the-open-network"]["usd"])
    except Exception:
        pass
    _cache.update({"rub": rub, "ton": ton, "ts": time.time()})
    return rub, ton
