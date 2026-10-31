# -*- coding: utf-8 -*-
"""Все inline-клавиатуры бота."""
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import config
from .texts import (
    E_ADD, E_BACK, E_BELL, E_BOOKMARK, E_BROADCAST, E_CHECK, E_CROSS,
    E_CRYPTO, E_DOLLAR, E_FILE, E_FOLDER, E_GEAR, E_GIFT, E_INFO, E_MONEY,
    E_MSG, E_PHOTO, E_PRICE, E_PROFILE, E_QUESTION, E_STATS, E_STAR,
    E_TG, E_TON2, E_USERS,
)
from .utils import _style


def subscribe_kb():
    b = InlineKeyboardBuilder()
    b.button(text="Подписаться", url=config.CHANNEL_URL)
    b.button(text="Проверить подписку", callback_data="check_sub")
    b.adjust(1)
    kb = b.as_markup()
    _style(kb, 0, 0, "primary", E_BELL)
    _style(kb, 1, 0, "success", E_CHECK)
    return kb


def main_menu(is_admin=False):
    b = InlineKeyboardBuilder()
    b.button(text="Каталог", callback_data="catalog")
    b.button(text="Корзина", callback_data="cart")
    b.button(text="Профиль", callback_data="profile")
    b.button(text="Пополнить", callback_data="topup")
    b.button(text="Промокод", callback_data="promo")
    b.button(text="Поддержка", callback_data="support")
    b.button(text="Канал", url=config.CHANNEL_URL)
    b.button(text="Правила", callback_data="rules")
    if is_admin:
        b.button(text="Админ-панель", callback_data="admin")
    b.adjust(2, 2, 2, 2, 1, 1)
    kb = b.as_markup()
    _style(kb, 0, 0, "primary", E_FOLDER)
    _style(kb, 0, 1, "primary", E_BOOKMARK)
    _style(kb, 1, 0, "primary", E_PROFILE)
    _style(kb, 1, 1, "success", E_MONEY)
    _style(kb, 2, 0, "primary", E_PRICE)
    _style(kb, 2, 1, "primary", E_QUESTION)
    _style(kb, 3, 0, None, E_TG)
    _style(kb, 3, 1, None, E_INFO)
    if is_admin:
        _style(kb, 4, 0, "danger", E_GEAR)
    return kb


def back_menu(cb="main"):
    b = InlineKeyboardBuilder()
    b.button(text="Назад", callback_data=cb)
    kb = b.as_markup()
    _style(kb, 0, 0, None, E_BACK)
    return kb


def catalog_categories():
    b = InlineKeyboardBuilder()
    b.button(text="Все товары", callback_data="cat:all")
    b.button(text="RU", callback_data="cat:ru")
    b.button(text="USA", callback_data="cat:usa")
    b.button(text="EU", callback_data="cat:eu")
    b.button(text="Другое", callback_data="cat:other")
    b.button(text="Назад", callback_data="main")
    b.adjust(1)
    kb = b.as_markup()
    _style(kb, 0, 0, "primary", E_FOLDER)
    _style(kb, 5, 0, None, E_BACK)
    return kb


def products_list(products, cat="all", page=0, total_pages=1):
    """Список товаров страницы + навигация (если страниц больше одной)."""
    b = InlineKeyboardBuilder()
    for p in products:
        b.button(
            text=f"{p['name']} | {p['price_usd']}$ | {p['stock']} шт",
            callback_data=f"prod:{p['id']}",
        )
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀", callback_data=f"cat:{cat}:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="▶", callback_data=f"cat:{cat}:{page + 1}"))
        b.row(*nav)
    b.row(InlineKeyboardButton(text="◀ Категории", callback_data="catalog"))
    b.row(InlineKeyboardButton(text="Назад", callback_data="main"))
    kb = b.as_markup()
    for i in range(len(products)):
        _style(kb, i, 0, "primary", E_BOOKMARK)
    _style(kb, len(products) + (1 if total_pages > 1 else 0), 0, None, E_BACK)
    return kb


def product_card(pid):
    b = InlineKeyboardBuilder()
    b.button(text="Купить сейчас", callback_data=f"buy:{pid}")
    b.button(text="Добавить в корзину", callback_data=f"cart_add:{pid}")
    b.button(text="Назад", callback_data="catalog")
    b.adjust(1)
    kb = b.as_markup()
    _style(kb, 0, 0, "success", E_CHECK)
    _style(kb, 1, 0, "primary", E_BOOKMARK)
    _style(kb, 2, 0, None, E_BACK)
    return kb


def payment_methods(oid):
    b = InlineKeyboardBuilder()
    b.button(text="CryptoBot (+3%)", callback_data=f"pay_crypto:{oid}")
    b.button(text="xRocket", callback_data=f"pay_xrocket:{oid}")
    b.button(text="TON", callback_data=f"pay_ton:{oid}")
    b.button(text="Карта", callback_data=f"pay_card:{oid}")
    b.button(text="Баланс бота", callback_data=f"pay_balance:{oid}")
    b.button(text="Отмена", callback_data=f"cancel_order:{oid}")
    b.adjust(1)
    kb = b.as_markup()
    _style(kb, 0, 0, "primary", E_CRYPTO)
    _style(kb, 1, 0, "primary", E_CRYPTO)
    _style(kb, 2, 0, "primary", E_TON2)
    _style(kb, 3, 0, "primary", E_DOLLAR)
    _style(kb, 4, 0, "success", E_MONEY)
    _style(kb, 5, 0, "danger", E_CROSS)
    return kb


def topup_methods(oid):
    b = InlineKeyboardBuilder()
    b.button(text="CryptoBot", callback_data=f"topup_crypto:{oid}")
    b.button(text="xRocket", callback_data=f"topup_xrocket:{oid}")
    b.button(text="Назад", callback_data="main")
    b.adjust(1)
    kb = b.as_markup()
    _style(kb, 0, 0, "primary", E_CRYPTO)
    _style(kb, 1, 0, "primary", E_CRYPTO)
    _style(kb, 2, 0, None, E_BACK)
    return kb


def check_crypto_kb(oid):
    b = InlineKeyboardBuilder()
    b.button(text="Проверить оплату", callback_data=f"check_crypto:{oid}")
    b.button(text="Отмена", callback_data=f"cancel_order:{oid}")
    b.adjust(1)
    kb = b.as_markup()
    _style(kb, 0, 0, "success", E_CHECK)
    _style(kb, 1, 0, "danger", E_CROSS)
    return kb


def admin_menu():
    b = InlineKeyboardBuilder()
    b.button(text="Статистика", callback_data="adm:stats")
    b.button(text="Товары", callback_data="adm:products")
    b.button(text="Добавить товар", callback_data="adm:add_product")
    b.button(text="Заказы", callback_data="adm:orders")
    b.button(text="Пользователи", callback_data="adm:users")
    b.button(text="Промокоды", callback_data="adm:promos")
    b.button(text="Рассылка", callback_data="adm:broadcast")
    b.button(text="Баннер", callback_data="adm:banner")
    b.button(text="Отзывы", callback_data="adm:reviews")
    b.button(text="Переменные", callback_data="adm:vars")
    b.button(text="Назад", callback_data="main")
    b.adjust(2, 2, 2, 2, 2, 1)
    kb = b.as_markup()
    _style(kb, 0, 0, "primary", E_STATS)
    _style(kb, 0, 1, "primary", E_FOLDER)
    _style(kb, 1, 0, "success", E_ADD)
    _style(kb, 1, 1, "primary", E_FILE)
    _style(kb, 2, 0, "primary", E_USERS)
    _style(kb, 2, 1, "primary", E_PRICE)
    _style(kb, 3, 0, "primary", E_BROADCAST)
    _style(kb, 3, 1, "primary", E_PHOTO)
    _style(kb, 4, 0, "primary", E_STAR)
    _style(kb, 4, 1, "primary", E_GEAR)
    _style(kb, 5, 0, None, E_BACK)
    return kb


def variables_kb():
    """Список редактируемых переменных (админка → «Переменные»)."""
    from .variables import VAR_DEFS, VAR_ORDER

    b = InlineKeyboardBuilder()
    editable_keys = [k for k in VAR_ORDER if VAR_DEFS[k][2]]
    for key in editable_keys:
        b.button(text=f"✏ {VAR_DEFS[key][0]}", callback_data=f"adm_var:{key}")
    b.button(text="Назад", callback_data="admin")
    b.adjust(1)
    kb = b.as_markup()
    for i in range(len(editable_keys)):
        _style(kb, i, 0, "primary", E_GEAR)
    _style(kb, len(editable_keys), 0, None, E_BACK)
    return kb


def admin_products_kb(products):
    b = InlineKeyboardBuilder()
    for p in products:
        status = "ON" if p["is_active"] else "OFF"
        b.button(text=f"[{status}] #{p['id']} {p['name']}", callback_data=f"adm_prod:{p['id']}")
    b.button(text="Назад", callback_data="admin")
    b.adjust(1)
    kb = b.as_markup()
    for i in range(len(products)):
        _style(kb, i, 0, "primary", E_FOLDER)
    _style(kb, len(products), 0, None, E_BACK)
    return kb


def admin_product_card(pid):
    b = InlineKeyboardBuilder()
    b.button(text="Вкл/Выкл", callback_data=f"adm_toggle:{pid}")
    b.button(text="Удалить", callback_data=f"adm_del:{pid}")
    b.button(text="Изменить наличие", callback_data=f"adm_stock:{pid}")
    b.button(text="Назад", callback_data="adm:products")
    b.adjust(1)
    kb = b.as_markup()
    _style(kb, 0, 0, "primary", E_GEAR)
    _style(kb, 1, 0, "danger", E_CROSS)
    _style(kb, 2, 0, "primary", E_ADD)
    _style(kb, 3, 0, None, E_BACK)
    return kb


def admin_orders_kb(orders):
    b = InlineKeyboardBuilder()
    for o in orders:
        b.button(
            text=f"#{o['id']} | {o['status']} | {o['amount_usd']}$",
            callback_data=f"adm_ord:{o['id']}",
        )
    b.button(text="Назад", callback_data="admin")
    b.adjust(1)
    kb = b.as_markup()
    for i in range(len(orders)):
        _style(kb, i, 0, "primary", E_FILE)
    _style(kb, len(orders), 0, None, E_BACK)
    return kb


def admin_order_actions(oid, status):
    b = InlineKeyboardBuilder()
    if status == "on_review":
        b.button(text="Подтвердить оплату", callback_data=f"adm_confirm:{oid}")
        b.button(text="Отклонить", callback_data=f"adm_reject:{oid}")
    if status in ("paid", "issued"):
        b.button(text="Отметить Выдано", callback_data=f"adm_issued:{oid}")
    b.button(text="Написать пользователю", callback_data=f"adm_write:{oid}")
    b.button(text="Назад", callback_data="adm:orders")
    b.adjust(1)

    kb = b.as_markup()
    row = 0
    if status == "on_review":
        _style(kb, 0, 0, "success", E_CHECK)
        _style(kb, 1, 0, "danger", E_CROSS)
        row = 2
    if status in ("paid", "issued"):
        _style(kb, 0, 0, "success", E_GIFT)
        row = 1
    _style(kb, row, 0, "primary", E_MSG)
    _style(kb, row + 1, 0, None, E_BACK)
    return kb


def user_orders_kb(orders):
    b = InlineKeyboardBuilder()
    for o in orders:
        b.button(
            text=f"#{o['id']} | {o['status']} | {o['product_name']}",
            callback_data=f"my_ord:{o['id']}",
        )
    b.button(text="Назад", callback_data="profile")
    b.adjust(1)
    kb = b.as_markup()
    for i in range(len(orders)):
        _style(kb, i, 0, "primary", E_FILE)
    _style(kb, len(orders), 0, None, E_BACK)
    return kb


def cart_keyboard(items):
    b = InlineKeyboardBuilder()
    for it in items:
        b.button(text=f"Убрать: {it['name']}", callback_data=f"cart_del:{it['product_id']}")
    b.button(text="Оформить корзину", callback_data="cart_checkout")
    b.button(text="Очистить", callback_data="cart_clear")
    b.button(text="В каталог", callback_data="catalog")
    b.button(text="Назад", callback_data="main")
    b.adjust(1)
    return b.as_markup()
