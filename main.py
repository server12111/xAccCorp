# -*- coding: utf-8 -*-
"""
X CORP SHOP — Telegram Bot.

Запуск: python main.py
Конфигурация — в .env (см. .env.example). База данных лежит в DATA_DIR
(по умолчанию /app/data — эта папка переживает перезапуск сервера).

Структура:
  app/config.py    — конфиг из .env
  app/db.py        — SQLite (таблицы и запросы)
  app/keyboards.py — инлайн-клавиатуры
  app/texts.py     — тексты и премиум-эмодзи
  app/payments.py  — CryptoBot / xRocket API
  app/logs.py      — логи событий в Telegram-группу (по темам) + статистика
  app/backups.py   — бэкапы БД 2 раза в сутки в тему «Бэкапы»
  app/handlers/    — хендлеры (start, catalog, profile, promo, topup, payment, admin)
"""
import asyncio
import logging

from app.compat import ensure_dependencies

ensure_dependencies()

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.storage.memory import MemoryStorage

from app import config
from app.backups import backup_loop
from app.db import init_db
from app.handlers import routers
from app.logs import daily_stats_loop, db_diagnostics, ensure_all_topics, notify, notify_error, probe_log_chat
from app.maintenance import auto_cancel_loop
from app.variables import load_vars

BOT_REF = None


async def errors_handler(event: types.ErrorEvent):
    exc = event.exception
    if isinstance(exc, (TelegramForbiddenError, TelegramBadRequest)):
        logging.warning("Ignored: %s", exc)
        return True
    logging.exception("Unhandled error: %s", exc)
    if BOT_REF is not None:
        await notify_error(BOT_REF, exc)
    return True


async def main():
    global BOT_REF
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not config.BOT_TOKEN:
        raise RuntimeError("Укажи BOT_TOKEN в .env (или в переменной окружения BOT_TOKEN)")

    await init_db()
    await load_vars()

    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    BOT_REF = bot
    dp = Dispatcher(storage=MemoryStorage())

    await probe_log_chat(bot)
    await ensure_all_topics(bot)

    dp.errors.register(errors_handler)
    for r in routers:
        dp.include_router(r)

    stats_loop = asyncio.create_task(daily_stats_loop(bot))
    backups_loop = asyncio.create_task(backup_loop(bot))
    cancel_loop = asyncio.create_task(auto_cancel_loop(bot))

    print("X CORP SHOP БОТ ЗАПУЩЕН")
    await notify(bot, "SYSTEM", f"🚀 Бот запущен\n{await db_diagnostics()}")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        stats_loop.cancel()
        backups_loop.cancel()
        cancel_loop.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
