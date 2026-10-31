# -*- coding: utf-8 -*-
"""Каталог, карточка товара, корзина."""
from aiogram import Bot, F, Router, types

from .. import db
from ..keyboards import (
    back_menu, cart_keyboard, catalog_categories, payment_methods, product_card,
    products_list,
)
from ..logs import esc, notify, user_line
from ..texts import product_text
from ..utils import edit_or_answer, fetch_rates, gen_track

router = Router()


# ---------- КАТАЛОГ ----------
@router.callback_query(F.data == "catalog")
async def cb_catalog(call: types.CallbackQuery):
    text = "<b>КАТАЛОГ</b>\n━━━━━━━━━━━━━━━━━━\nВыбери категорию:"
    await edit_or_answer(call, text, catalog_categories())
    await call.answer()


PAGE_SIZE = 8  # товаров на страницу каталога


@router.callback_query(F.data.startswith("cat:"))
async def cb_cat(call: types.CallbackQuery):
    parts = call.data.split(":")
    cat = parts[1] if len(parts) > 1 else "all"
    try:
        page = max(0, int(parts[2])) if len(parts) > 2 else 0
    except ValueError:
        page = 0
    all_products = await db.get_products(cat)
    if not all_products:
        text = "<b>КАТАЛОГ</b>\n━━━━━━━━━━━━━━━━━━\nВ этой категории пока нет товаров."
        await edit_or_answer(call, text, catalog_categories())
        await call.answer()
        return
    total_pages = max(1, (len(all_products) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages - 1)
    page_products = all_products[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    text = f"<b>КАТАЛОГ / {cat.upper()}</b>\n━━━━━━━━━━━━━━━━━━"
    if total_pages > 1:
        text += f"\nСтраница {page + 1} из {total_pages} · всего {len(all_products)} шт"
    text += "\nВыбери товар:"
    await edit_or_answer(call, text, products_list(page_products, cat, page, total_pages))
    await call.answer()


@router.callback_query(F.data.startswith("prod:"))
async def cb_prod(call: types.CallbackQuery):
    pid = int(call.data.split(":")[1])
    p = await db.get_product(pid)
    if not p:
        await call.answer("Товар не найден", show_alert=True)
        return
    rub, ton = await fetch_rates()
    text = product_text(p, rub, ton)
    await edit_or_answer(call, text, product_card(pid), photo=p["photo_id"])
    await call.answer()


# ---------- КОРЗИНА ----------
@router.callback_query(F.data.startswith("cart_add:"))
async def cb_cart_add(call: types.CallbackQuery):
    pid = int(call.data.split(":")[1])
    product = await db.get_product(pid)
    if not product or not product["is_active"] or product["stock"] < 1:
        await call.answer("Товар закончился или недоступен", show_alert=True)
        return
    await db.cart_add(call.from_user.id, pid)
    await call.answer("Добавлено в корзину")


@router.callback_query(F.data == "cart")
async def cb_cart(call: types.CallbackQuery):
    items = await db.cart_get(call.from_user.id)
    if not items:
        await edit_or_answer(
            call,
            "<b>КОРЗИНА</b>\n━━━━━━━━━━━━━━━━━━\nПока пусто. Добавь товары из каталога.",
            back_menu("catalog"),
        )
    else:
        rub, _ton = await fetch_rates()
        total = 0
        lines = ["<b>ТВОЯ КОРЗИНА</b>", "━━━━━━━━━━━━━━━━━━"]
        for it in items:
            subtotal = it["price_usd"] * it["quantity"]
            total += subtotal
            lines.append(f"• {it['name']} × {it['quantity']} — {subtotal:.2f} $")
            if not it["is_active"] or it["stock"] < it["quantity"]:
                lines.append("  ⚠ Недостаточно наличия")
        lines += ["━━━━━━━━━━━━━━━━━━", f"Итого: <b>{total:.2f} $ / {total*rub:.2f} ₽</b>"]
        await edit_or_answer(call, "\n".join(lines), cart_keyboard(items))
    await call.answer()


@router.callback_query(F.data.startswith("cart_del:"))
async def cb_cart_del(call: types.CallbackQuery):
    await db.cart_remove(call.from_user.id, int(call.data.split(":")[1]))
    items = await db.cart_get(call.from_user.id)
    if not items:
        await edit_or_answer(call, "Корзина пуста.", back_menu("catalog"))
    else:
        await edit_or_answer(call, "Товар удалён. Открой корзину ещё раз.", back_menu("cart"))
    await call.answer("Удалено")


@router.callback_query(F.data == "cart_clear")
async def cb_cart_clear(call: types.CallbackQuery):
    await db.cart_clear(call.from_user.id)
    await edit_or_answer(call, "Корзина очищена.", back_menu("catalog"))
    await call.answer()


@router.callback_query(F.data == "cart_checkout")
async def cb_cart_checkout(call: types.CallbackQuery, bot: Bot):
    items = await db.cart_get(call.from_user.id)
    if not items:
        await call.answer("Корзина пуста", show_alert=True)
        return
    rub, ton = await fetch_rates()
    for it in items:
        if not it["is_active"] or it["stock"] < it["quantity"]:
            await call.answer(f"Недостаточно товара: {it['name']}", show_alert=True)
            return
    # Каждая позиция — обычный заказ, так что работают все способы оплаты и проверки.
    made = []
    for it in items:
        for _ in range(it["quantity"]):
            track = gen_track()
            usd = float(it["price_usd"])
            oid = await db.create_order(
                call.from_user.id, it["product_id"], it["name"],
                usd, usd * rub, usd / ton if ton else 0,
                "pending", track, status="awaiting_payment",
            )
            made.append((oid, it["name"], usd))
    await db.cart_clear(call.from_user.id)
    await call.message.answer(f"Создано заказов: {len(made)}. Оплати каждый заказ отдельно:")
    for oid, name, usd in made:
        await call.message.answer(
            f"<b>Заказ #{oid}</b> · {esc(name)} · {usd:.2f} $",
            reply_markup=payment_methods(oid),
        )
    total_usd = sum(usd for _, _, usd in made)
    made_lines = "\n".join(f"#{oid} · {esc(name)} · {usd:.2f} $" for oid, name, usd in made[:10])
    await notify(
        bot, "CHECKOUT",
        f"🧾 Оформлена корзина: {len(made)} заказ(ов) на {total_usd:.2f} $ — НЕ оплачены\n"
        f"Пользователь: {user_line(call.from_user.id, call.from_user.first_name, call.from_user.username)}\n{made_lines}",
    )
    await call.answer("Заказы созданы")
