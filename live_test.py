# -*- coding: utf-8 -*-
"""Живая проверка бота: python live_test.py

Проверяет с реальным токеном:
  1. Что токен рабочий (getMe).
  2. Что бот видит лог-группу и может в ней писать (getChat + права).
  3. Доставку логов (тестовое сообщение в тему SYSTEM).
  4. Сборку и отправку ежесуточной статистики.
  5. Связь с админом в ЛС (нужно для уведомлений об оплатах).

Базу не меняет. Токен не печатает.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.compat import ensure_dependencies

ensure_dependencies()

from aiogram import Bot  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402

from app import config, db, logs  # noqa: E402


def _chat_candidates():
    base = config.LOG_CHAT_ID
    cands = []
    if base:
        cands.append(("как в .env", base))
    if base and not str(base).startswith("-100"):
        cands.append(("с префиксом -100", int(f"-100{abs(base)}")))
    return cands


async def main() -> int:
    if not config.BOT_TOKEN:
        print("❌ BOT_TOKEN пуст — впиши токен от @BotFather в .env и запусти снова.")
        return 2

    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await db.init_db()
        me = await bot.get_me()
        print(f"[1] ✅ Токен рабочий. Бот: @{me.username} (id {me.id})")

        working_chat = None
        for label, chat_id in _chat_candidates():
            try:
                chat = await bot.get_chat(chat_id)
                member = await bot.get_chat_member(chat_id, me.id)
                print(f"[2] ✅ Лог-чат ({label}) {chat_id}: «{chat.title}», тип {chat.type}, статус бота: {member.status}")
                if working_chat is None:
                    working_chat = chat_id
            except Exception as e:
                print(f"[2] ❌ Лог-чат ({label}) {chat_id}: недоступен — {e}")

        if working_chat is None:
            print("\n❌ Бот не видит группу.")
            print("   1) Добавь бота в группу (лучше админом).")
            print("   2) Проверь LOG_CHAT_ID в .env (id группы можно узнать через @getidsbot).")
            return 1

        if not config.LOG_CHAT_ID:
            print("[3] ⚠ LOG_CHAT_ID пуст — логи выключены (включи в .env или в «Переменных»).")
        else:
            ok = await logs.notify(bot, "SYSTEM", "Тест доставки логов — если видишь это сообщение, логи работают.")
            if ok:
                print("[3] ✅ Тестовое сообщение доставлено в лог-чат (тема 🚀 Система).")
            else:
                print("[3] ❌ Сообщение НЕ доставлено — добавь бота в группу и дай право писать.")
                return 1

        text = await logs.build_daily_text()
        ok = await logs.notify(bot, "STATS", text)
        print(f"[4] {'✅' if ok else '❌'} Ежесуточная статистика собрана{' и отправлена (тема 📊 Статистика)' if ok else ', но НЕ отправлена'}:")
        for line in text.splitlines():
            print("      " + line)

        if not config.ADMIN_IDS:
            print("[5] ⚠ ADMIN_IDS не задан — уведомления об оплатах уходить некому.")
        for uid in config.ADMIN_IDS:
            try:
                await bot.send_message(uid, "✅ Тест: бот может отправлять тебе сообщения в ЛС.")
                print(f"[5] ✅ ЛС админу {uid} доставлено — уведомления об оплатах будут доходить.")
            except Exception as e:
                print(f"[5] ⚠ Не удалось написать админу {uid} в ЛС: {e}")
                print("    Этому админу нужно нажать /start у бота, чтобы он мог писать ему.")

        print("\nOK: живая проверка завершена. В группе должны появиться 2 сообщения: 🚀 Система и 📊 Статистика.")
        return 0
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
