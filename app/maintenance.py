# -*- coding: utf-8 -*-
"""Обслуживание магазина: автоотмена неоплаченных заказов.

Каждые 5 минут ищутся заказы в статусе awaiting_payment старше
AUTO_CANCEL_HOURS часов (по умолчанию 3) — они отменяются, событие
уходит в «🛒 Заказы», а покупателю — уведомление в ЛС.
"""
import asyncio
import logging

from aiogram import Bot

from . import config, db, logs
from .utils import safe_send

log = logging.getLogger("xcorp.maintenance")


async def cancel_stale(bot: Bot) -> int:
    orders = await db.cancel_stale_orders(config.AUTO_CANCEL_HOURS)
    for o in orders:
        await logs.notify(
            bot, "ORDER",
            f"⏰ Заказ #{o['id']} отменён автоматически: не оплачен за {config.AUTO_CANCEL_HOURS} ч\n"
            f"{logs.esc(o['product_name'])} · {o['amount_rub']:.2f} ₽\n"
            f"Покупатель: <code>{o['user_id']}</code>",
        )
        await safe_send(
            bot, o["user_id"],
            f"⏰ Заказ #{o['id']} ({o['product_name']}) отменён — не был оплачен "
            f"в течение {config.AUTO_CANCEL_HOURS} ч.\nЕсли всё ещё нужен — оформи заново.",
        )
    if orders:
        log.info("Автоотмена: %d заказ(ов)", len(orders))
    return len(orders)


async def auto_cancel_loop(bot: Bot) -> None:
    while True:
        try:
            await cancel_stale(bot)
        except Exception:
            log.exception("auto cancel failed")
        await asyncio.sleep(300)
