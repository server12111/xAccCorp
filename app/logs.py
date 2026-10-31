# -*- coding: utf-8 -*-
"""Логи в Telegram-группу.

Бот шлёт события по темам: пользователи, заказы, оплаты, товары,
промокоды, поддержка, отзывы, рассылки, ошибки + ежесуточная статистика.

Темы (форум):
  - Если LOG_TOPIC_ID задан — всё шлётся в этот один топик (ручной режим).
  - Если пусто и лог-чат является форумом — бот сам создаёт по теме на
    каждую категорию и раскладывает события по ним.
  - Если чат не форум — события идут обычными сообщениями в чат.

Группа задаётся в .env (LOG_CHAT_ID). Если передан id без префикса -100
или группа была преобразована в супергруппу — бот чинит id сам.
"""
import asyncio
import html
import logging
import re
import time
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from . import config, db

log = logging.getLogger("xcorp.logs")

CATEGORIES = {
    "USER":      ("Пользователи", "👤"),
    "ORDER":     ("Заказы", "🛒"),
    "CHECKOUT":  ("Оформления", "🧾"),
    "PAYMENT":   ("Оплата", "💰"),
    "STOCK":     ("Товары", "📦"),
    "PROMO":     ("Промокоды", "🎟"),
    "BROADCAST": ("Рассылка", "📢"),
    "SUPPORT":   ("Поддержка", "🎫"),
    "REVIEW":    ("Отзывы", "⭐"),
    "ADMIN":     ("Админ-действия", "🛠"),
    "STATS":     ("Статистика", "📊"),
    "SYSTEM":    ("Система", "🚀"),
    "ERROR":     ("Ошибки", "⚠️"),
    "BACKUP":    ("Бэкапы БД", "🗄"),
}

_MIGRATED_RE = re.compile(r"migrated to supergroup with id (-\d+)")

_state = {"resolved": None, "fails": 0, "muted_until": 0.0}
_err_seen: dict = {}

# Авто-топики по категориям
_topic_ids: dict = {}
_forum_ok: bool | None = None  # None — ещё не знаем, False — чат не форум


def esc(v) -> str:
    return html.escape(str(v if v is not None else "-"))


def reset_log_state() -> None:
    """Сбросить кэш доставки логов (смена LOG_CHAT_ID/топика)."""
    _state["resolved"] = None
    _state["fails"] = 0
    _state["muted_until"] = 0.0
    _topic_ids.clear()
    global _forum_ok
    _forum_ok = None


async def reset_topics() -> None:
    """Забыть созданные топики (например, после смены лог-чата)."""
    _topic_ids.clear()
    global _forum_ok
    _forum_ok = None
    for category in CATEGORIES:
        try:
            await db.del_setting(f"log_topic_{category}")
        except Exception:
            pass


def user_line(uid, name=None, username=None) -> str:
    parts = [f"<code>{uid}</code>"]
    if name:
        parts.append(esc(name))
    if username:
        parts.append(f"@{esc(username)}")
    return " · ".join(parts)


def _candidates():
    base = config.LOG_CHAT_ID
    cands = []
    if base:
        cands.append(base)
    # Частая ситуация: скопировали id супергруппы без префикса -100.
    if base and not str(base).startswith("-100"):
        cands.append(int(f"-100{abs(base)}"))
    if _state["resolved"] is not None and _state["resolved"] in cands:
        cands.remove(_state["resolved"])
        cands.insert(0, _state["resolved"])
    return cands


def _topic_name(category: str) -> str:
    title, emoji = CATEGORIES.get(category, ("Лог", "📄"))
    return f"{emoji} {title}"


async def get_topic_id(bot: Bot, category: str) -> int | None:
    """message_thread_id для категории.

    Ручной режим (LOG_TOPIC_ID задан) -> один топик для всего.
    Авто-режим -> топик категории из кэша/БД или создаётся, если чат форум.
    """
    if not config.LOG_CHAT_ID:
        return None
    if config.LOG_TOPIC_ID:
        return config.LOG_TOPIC_ID
    global _forum_ok
    if _forum_ok is False or bot is None:
        return None
    if category in _topic_ids:
        return _topic_ids[category]

    saved = await db.get_setting(f"log_topic_{category}")
    if saved and str(saved).isdigit():
        tid = int(saved)
        _topic_ids[category] = tid
        return tid

    try:
        topic = await bot.create_forum_topic(chat_id=config.LOG_CHAT_ID, name=_topic_name(category))
    except TelegramBadRequest as e:
        if "forum" in str(e).lower():
            _forum_ok = False
            log.warning("Лог-чат не форум (или нет права «Управление темами») — топики отключены")
        else:
            log.warning("Не удалось создать топик %s: %s", category, e)
        return None
    except Exception as e:
        log.warning("Не удалось создать топик %s: %s", category, e)
        return None

    tid = topic.message_thread_id
    _topic_ids[category] = tid
    _forum_ok = True
    try:
        await db.set_setting(f"log_topic_{category}", str(tid))
    except Exception:
        pass
    return tid


async def _invalidate_topic(category: str) -> None:
    """Топик удалили в Telegram — забыть и пересоздать при следующем событии."""
    _topic_ids.pop(category, None)
    try:
        await db.del_setting(f"log_topic_{category}")
    except Exception:
        pass


async def probe_log_chat(bot: Bot) -> None:
    """Проверка лог-чата при старте: миграция группы, форум, доступность."""
    global _forum_ok
    if not config.LOG_CHAT_ID or bot is None:
        return
    try:
        chat = await bot.get_chat(config.LOG_CHAT_ID)
        _forum_ok = bool(getattr(chat, "is_forum", False))
        log.info("Лог-чат: «%s» (%s, форум: %s)", chat.title, chat.type, _forum_ok)
    except TelegramBadRequest as e:
        m = _MIGRATED_RE.search(str(e))
        if m:
            config.LOG_CHAT_ID = int(m.group(1))
            log.warning("Лог-чат мигрировал в супергруппу, новый id: %s", config.LOG_CHAT_ID)
            try:
                chat = await bot.get_chat(config.LOG_CHAT_ID)
                _forum_ok = bool(getattr(chat, "is_forum", False))
            except Exception as e2:
                log.warning("Лог-чат недоступен: %s", e2)
        else:
            log.warning("Лог-чат %s недоступен: %s", config.LOG_CHAT_ID, e)
    except Exception as e:
        log.warning("Лог-чат %s недоступен: %s", config.LOG_CHAT_ID, e)


LOW_STOCK_THRESHOLD = 3
_low_stock_warned: dict = {}


async def check_low_stock(bot: Bot, pid) -> None:
    """Предупредить в «📦 Товары», когда остаток падает до порога.

    Один товар предупреждается один раз, пока остаток снова не поднимут.
    """
    try:
        p = await db.get_product(pid)
    except Exception:
        return
    if not p:
        return
    stock = p["stock"]
    if stock > LOW_STOCK_THRESHOLD:
        _low_stock_warned[pid] = False
        return
    if _low_stock_warned.get(pid):
        return
    _low_stock_warned[pid] = True
    if stock <= 0:
        text = f"⚠️ Товар закончился: {esc(p['name'])} (#{pid})\nОстаток: 0 шт"
    else:
        text = f"⚠️ Товар заканчивается: {esc(p['name'])} (#{pid})\nОстаток: {stock} шт"
    await notify(bot, "STOCK", text)


async def ensure_all_topics(bot: Bot) -> None:
    """При старте создать все темы: с паузами (Telegram режет флуд создания)
    и одним повтором для неуспешных. Несоздавшиеся создадутся сами при
    первом событии своей категории."""
    pending = list(CATEGORIES)
    for round_num in (1, 2):
        failed = []
        for category in pending:
            if await get_topic_id(bot, category) is None:
                failed.append(category)
            await asyncio.sleep(0.35)
        if not failed:
            return
        if round_num == 1 and failed:
            log.warning("Не создались темы: %s — повтор через 3 сек", ", ".join(failed))
            await asyncio.sleep(3)
        pending = failed
    log.warning("Темы не созданы (создадутся сами при первом событии): %s", ", ".join(pending))


async def notify(bot: Bot, category: str, text: str, reply_markup=None) -> bool:
    """Отправить событие в лог-группу. Никогда не бросает исключений.

    Возвращает True, если сообщение реально доставлено.
    """
    if not config.LOG_CHAT_ID or bot is None:
        return False
    if time.time() < _state["muted_until"]:
        return False
    title, emoji = CATEGORIES.get(category, ("Лог", "📄"))
    msg = f"{emoji} <b>{title}</b>\n{text}"

    for attempt in (1, 2):
        kwargs = {}
        thread = await get_topic_id(bot, category)
        if thread:
            kwargs["message_thread_id"] = thread
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        sent = False
        for chat in _candidates():
            try:
                await bot.send_message(chat, msg, **kwargs)
                _state["resolved"] = chat
                _state["fails"] = 0
                sent = True
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except TelegramForbiddenError:
                # Бота выгнали из чата — молчим полчаса, чтобы не спамить CPU.
                _state["muted_until"] = time.time() + 1800
                log.warning("Лог-чат %s: бот заблокирован, логи приостановлены на 30 мин", chat)
                return sent
            except TelegramBadRequest as e:
                err = str(e)
                m = _MIGRATED_RE.search(err)
                if m:
                    # Группа преобразована в супергруппу — Telegram подсказывает новый id.
                    new_id = int(m.group(1))
                    log.warning("Группа %s мигрировала в супергруппу %s — переключаюсь", chat, new_id)
                    config.LOG_CHAT_ID = new_id
                    _state["resolved"] = None
                    try:
                        await bot.send_message(new_id, msg, **kwargs)
                        _state["resolved"] = new_id
                        _state["fails"] = 0
                        sent = True
                        break
                    except Exception as e2:
                        log.warning("Не удалось отправить лог в новый чат %s: %s", new_id, e2)
                    continue
                if "message thread not found" in err.lower() and attempt == 1:
                    # Топик удалили вручную — пересоздадим и повторим.
                    await _invalidate_topic(category)
                    break
                log.warning("Не удалось отправить лог в %s: %s", chat, e)
            except Exception as e:
                log.warning("Не удалось отправить лог в %s: %s", chat, e)
        if sent:
            return True

    _state["fails"] += 1
    if _state["fails"] >= 5:
        _state["muted_until"] = time.time() + 600
        _state["fails"] = 0
    return False


async def notify_photo(bot: Bot, category: str, photo, caption: str, reply_markup=None) -> bool:
    """Фото с подписью в лог-группу (в свою тему). Никогда не бросает исключений."""
    if not config.LOG_CHAT_ID or bot is None:
        return False
    if time.time() < _state["muted_until"]:
        return False
    title, emoji = CATEGORIES.get(category, ("Лог", "📄"))
    cap = f"{emoji} <b>{title}</b>\n{caption}"[:1024]

    for attempt in (1, 2):
        kwargs = {}
        thread = await get_topic_id(bot, category)
        if thread:
            kwargs["message_thread_id"] = thread
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        try:
            await bot.send_photo(config.LOG_CHAT_ID, photo=photo, caption=cap, **kwargs)
            _state["resolved"] = config.LOG_CHAT_ID
            _state["fails"] = 0
            return True
        except TelegramBadRequest as e:
            err = str(e)
            m = _MIGRATED_RE.search(err)
            if m and attempt == 1:
                config.LOG_CHAT_ID = int(m.group(1))
                continue
            if "message thread not found" in err.lower() and attempt == 1:
                await _invalidate_topic(category)
                continue
            log.warning("notify_photo: %s", e)
        except Exception as e:
            log.warning("notify_photo: %s", e)

    _state["fails"] += 1
    if _state["fails"] >= 5:
        _state["muted_until"] = time.time() + 600
        _state["fails"] = 0
    return False


async def notify_error(bot: Bot, exc: Exception, context: str = "") -> None:
    """Лог ошибки с троттлингом одинаковых ошибок (10 минут)."""
    if bot is None:
        return
    key = f"{type(exc).__name__}:{str(exc)[:120]}"
    t = time.time()
    if t - _err_seen.get(key, 0) < 600:
        return
    _err_seen[key] = t
    if len(_err_seen) > 200:
        _err_seen.clear()
    body = f"<code>{esc(f'{type(exc).__name__}: {exc}')[:900]}</code>"
    if context:
        body = f"Контекст: {esc(context[:200])}\n" + body
    await notify(bot, "ERROR", body)


# ============================================================
#  ЕЖЕСУТОЧНАЯ СТАТИСТИКА
# ============================================================
async def build_daily_text() -> str:
    s = await db.stats()
    users = await db.count_users()
    top = await db.top_products(3)
    lines = [
        "📊 <b>Ежедневная статистика X CORP SHOP</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"👤 Пользователей всего: <b>{users}</b> (новых сегодня: {s['new_users']})",
        f"🛒 Заказов создано сегодня: <b>{s['today']}</b>",
        f"✅ Оплачено заказов сегодня: <b>{s['paid_today']}</b>",
        f"💵 Выручка за сегодня: <b>{s['revenue_today_rub']:.2f} ₽</b> (всего: {s['revenue']:.2f} $)",
        f"💰 Пополнений сегодня: <b>{s['topups_today']}</b> на {s['topup_rub_today']:.2f} ₽",
        f"⏳ Ожидают оплаты: <b>{s['pending']}</b>",
        f"📦 Активных товаров с наличием: <b>{s['available']}</b>",
    ]
    if top:
        lines.append("🏆 Топ товаров: " + ", ".join(f"{esc(r['product_name'])} ({r['c']})" for r in top))
    return "\n".join(lines)


async def send_daily_stats(bot: Bot) -> None:
    await notify(bot, "STATS", await build_daily_text())


async def daily_stats_loop(bot: Bot) -> None:
    """Раз в сутки в LOG_DAILY_HOUR (по времени сервера) шлёт статистику."""
    while True:
        now = datetime.now()
        target = now.replace(hour=config.LOG_DAILY_HOUR, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep(max(1.0, (target - now).total_seconds()))
        try:
            await send_daily_stats(bot)
        except Exception:
            log.exception("daily stats failed")
