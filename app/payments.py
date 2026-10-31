# -*- coding: utf-8 -*-
"""Платёжные API: CryptoBot (Crypto Pay) и xRocket Pay."""
import logging

import aiohttp

from . import config


# ============================================================
#  CRYPTOBOT
# ============================================================
async def create_crypto_invoice(amount_usd, desc):
    headers = {"Crypto-Pay-API-Token": config.CRYPTO_BOT_TOKEN}
    payload = {"asset": "USDT", "amount": f"{amount_usd:.2f}", "description": desc, "expires_in": 3600}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://pay.crypt.bot/api/createInvoice", headers=headers, json=payload, timeout=15
            ) as r:
                d = await r.json()
                if d.get("ok"):
                    inv = d["result"]
                    url = inv.get("bot_invoice_url") or inv.get("pay_url") or inv.get("mini_app_invoice_url")
                    return url, inv.get("invoice_id")
    except Exception:
        pass
    return None, None


async def check_crypto_invoice(inv_id):
    headers = {"Crypto-Pay-API-Token": config.CRYPTO_BOT_TOKEN}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://pay.crypt.bot/api/getInvoices?invoice_ids={inv_id}",
                headers=headers,
                timeout=15,
            ) as r:
                d = await r.json()
                if d.get("ok") and d["result"]["items"]:
                    return d["result"]["items"][0].get("status") == "paid"
    except Exception:
        pass
    return False


# ============================================================
#  XROCKET
# ============================================================
async def create_xrocket_invoice(amount_usdt, description, client_id, user_id):
    if not config.XROCKET_TOKEN: return None, None
    headers = {"Authorization": f"Bearer {config.XROCKET_TOKEN}", "Accept": "application/json"}
    payload = {"priceAmount": f"{amount_usdt:.2f}", "priceCurrency": "USDT",
               "payoutCurrency": "USDT", "clientInvoiceId": str(client_id),
               "description": description[:1000], "expiresIn": 3600000,
               "customer": {"telegramId": str(user_id)}}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{config.XROCKET_API}/api/v1/invoices", headers=headers, json=payload, timeout=20) as r:
                data = await r.json()
                if r.status in (200, 201): return data.get("links", {}).get("telegramBotLink"), data.get("id")
                logging.error("xRocket invoice error %s: %s", r.status, data)
    except Exception: logging.exception("xRocket invoice creation failed")
    return None, None


async def check_xrocket_invoice(invoice_id):
    if not config.XROCKET_TOKEN: return False
    headers = {"Authorization": f"Bearer {config.XROCKET_TOKEN}", "Accept": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{config.XROCKET_API}/api/v1/invoice", params={"invoiceId": str(invoice_id)}, headers=headers, timeout=15) as r:
                data = await r.json()
                if r.status == 200: return data.get("invoice", data).get("status") == "paid"
                logging.error("xRocket status error %s: %s", r.status, data)
    except Exception: logging.exception("xRocket invoice check failed")
    return False
