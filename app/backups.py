# -*- coding: utf-8 -*-
"""Бэкапы базы данных.

По расписанию (BACKUP_HOURS, по умолчанию 2 раза в сутки) бот:
  1. Делает безопасную копию shop.db через SQLite backup API
     (можно прямо при живой записи — копия всегда консистентна).
  2. Складывает её в DATA_DIR/backups (хранятся последние BACKUP_KEEP штук).
  3. Отправляет файл в лог-группу, в тему «🗄 Бэкапы БД»
     (если чат — форум; иначе просто в чат).
"""
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from . import config, db, logs

log = logging.getLogger("xcorp.backups")


def parse_hours() -> list:
    """Часы бэкапа из BACKUP_HOURS (например '6,18'). Пусто/мусор -> [6, 18]."""
    hours = []
    for part in str(config.BACKUP_HOURS).replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            h = int(part)
            if 0 <= h <= 23 and h not in hours:
                hours.append(h)
    return sorted(hours) or [6, 18]


async def make_backup() -> Path:
    """Локальная копия БД + ротация старых копий. Возвращает путь к свежей."""
    backup_dir = Path(config.DATA_DIR) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"shop-{datetime.now().strftime('%Y-%m-%d_%H-%M')}.db"
    await db.backup_to(str(dest))

    keep = max(1, int(config.BACKUP_KEEP))
    files = sorted(backup_dir.glob("shop-*.db"))
    for old in files[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass
    return dest


async def send_backup(bot: Bot) -> bool:
    """Сделать копию и отправить её в лог-группу. Возвращает успех."""
    path = await make_backup()
    size_kb = path.stat().st_size / 1024
    chat = config.LOG_CHAT_ID
    if not chat or bot is None:
        log.info("Бэкап сохранён локально: %s (%.1f KB), лог-чат выключен", path.name, size_kb)
        return False

    kwargs = {}
    thread = await logs.get_topic_id(bot, "BACKUP")
    if thread:
        kwargs["message_thread_id"] = thread
    try:
        await bot.send_document(
            chat,
            document=FSInputFile(str(path)),
            caption=(
                "🗄 <b>Бэкап базы данных</b>\n"
                f"Файл: <code>{path.name}</code>\n"
                f"Размер: {size_kb:.1f} KB\n"
                f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            ),
            **kwargs,
        )
        log.info("Бэкап отправлен: %s (%.1f KB)", path.name, size_kb)
        return True
    except Exception as e:
        log.warning("Бэкап сохранён локально (%s), но не отправлен: %s", path.name, e)
        return False


async def backup_loop(bot: Bot) -> None:
    """Ждёт ближайший час из BACKUP_HOURS и шлёт бэкап. 2+ раза в сутки."""
    while True:
        now = datetime.now()
        targets = []
        for h in parse_hours():
            t = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if t <= now:
                t += timedelta(days=1)
            targets.append(t)
        target = min(targets)
        log.info("Следующий бэкап БД: %s", target.strftime("%Y-%m-%d %H:%M"))
        await asyncio.sleep(max(1.0, (target - now).total_seconds()))
        try:
            await send_backup(bot)
        except Exception:
            log.exception("backup failed")
