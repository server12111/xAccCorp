# -*- coding: utf-8 -*-
"""Быстрая самопроверка проекта без запуска бота: python check.py

Проверяет: импорты всех модулей, схему БД, ключевые операции
(заказы, пополнения, рефералка, промокоды), сборку клавиатур/текстов,
регистрацию всех хендлеров в диспетчере.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Временная папка данных, чтобы не трогать настоящую базу
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="xcorp_check_")

from app.compat import ensure_dependencies

ensure_dependencies()

from app import config, db, keyboards, logs, texts, utils, variables  # noqa: E402
from app import backups  # noqa: E402
import aiosqlite  # noqa: E402
from app.handlers import routers  # noqa: E402


async def main() -> None:
    print(f"DATA_DIR = {config.DATA_DIR}")
    print(f"DB_PATH  = {config.DB_PATH}")

    await db.init_db()
    assert Path(config.DB_PATH).exists(), "БД не создана"

    # --- админы ---
    if config.ADMIN_IDS:
        assert utils.is_admin(config.ADMIN_IDS[0]) is True
        assert utils.is_admin(-1) is False
    else:
        print("⚠ ADMIN_IDS не задан — админ-панель будет недоступна")

    # --- пользователи ---
    assert await db.add_user(1, "tester", "Тест") is True
    assert await db.add_user(1, "tester", "Тест") is False  # повторно — не новый
    u = await db.get_user(1)
    assert u["id"] == 1

    # --- товары и заказы ---
    await db.add_product("Тест-аккаунт", "Описание", 2.0, "ru", 5)
    products = await db.get_products("ru")
    assert products and products[0]["name"] == "Тест-аккаунт"
    pid = products[0]["id"]

    oid = await db.create_order(1, pid, "Тест-аккаунт", 2.0, 200.0, 0.5, "test", "XC-TEST1", status="awaiting_payment")
    order, changed = await db.finish_paid_order(oid, 1)
    assert changed, "заказ не оплачен"
    assert (await db.get_order(oid))["status"] == "paid", "статус не стал paid"
    p = await db.get_product(pid)
    assert p["stock"] == 4, f"остаток не списан: {p['stock']}"
    _, changed_again = await db.finish_paid_order(oid, 1)
    assert not changed_again, "повторная оплата заказа прошла (двойное списание!)"
    p = await db.get_product(pid)
    assert p["stock"] == 4, "двойное списание остатка"

    # --- пополнение: баланс должен начисляться атомарно ---
    oid2 = await db.create_order(1, 0, "Пополнение баланса", 1.0, 100.0, 0.25, "TOPUP", "TOPUP-1")
    _, changed2 = await db.finish_paid_order(oid2, 1)
    assert changed2
    u = await db.get_user(1)
    assert abs(u["balance"] - 100.0) < 1e-6, f"пополнение не зачислено: {u['balance']}"

    # --- рефералка ---
    assert await db.add_user(2, "ref", "Реф", ref=1) is True
    oid3 = await db.create_order(2, pid, "Тест-аккаунт", 2.0, 200.0, 0.5, "test", "XC-TEST2")
    _, changed3 = await db.finish_paid_order(oid3, 2)
    assert changed3
    invited, earned = await db.referral_stats(1)
    assert invited == 1
    u1 = await db.get_user(1)
    # 5% от 200 ₽ = 10 ₽ + 100 ₽ пополнение
    assert abs(u1["balance"] - 110.0) < 1e-6, f"рефералка не начислена: {u1['balance']}"

    # --- промокоды ---
    await db.create_promo("TEST10", 50.0, 1)
    assert await db.use_promo("TEST10") is True
    assert await db.use_promo("TEST10") is False, "промокод применили больше раз, чем разрешено"
    await db.log_promo(1, "TEST10")
    assert await db.user_used_promo(1, "TEST10") is True

    # --- обновление профиля при повторном /start ---
    await db.add_user(1, "newname", "Тест2")
    u = await db.get_user(1)
    assert u["username"] == "newname" and u["first_name"] == "Тест2", "профиль не обновился"
    assert await db.add_user(2, "ref", "Реф", ref=1) is False  # user 2 уже был — не новый

    # --- тикеты и отзывы ---
    tid = await db.create_ticket(1, "Помогите")
    assert tid >= 1
    assert await db.add_review(1, oid, pid, 5, "Отлично") is True
    assert await db.add_review(1, oid, pid, 4, "повтор") is False  # UNIQUE по order_id
    assert await db.review_exists(oid) is True
    ticket = await db.get_ticket(tid)
    assert ticket and ticket['user_id'] == 1 and ticket['message'] == 'Помогите'
    await db.set_ticket_status(tid, 'answered')
    assert (await db.get_ticket(tid))['status'] == 'answered'

    # --- статистика ---
    s = await db.stats()
    for key in ("orders", "revenue", "pending", "today", "new_users", "available",
                "paid_today", "revenue_today_rub", "topups_today", "topup_rub_today"):
        assert key in s, f"нет ключа {key}"
    assert s["orders"] == 2, f"заказы: {s['orders']}"
    assert s["topups_today"] == 1, "пополнения не посчитаны"
    top = await db.top_products(3)
    assert top and top[0]["c"] == 2

    # --- корзина ---
    await db.cart_add(1, pid)
    await db.cart_add(1, pid)
    items = await db.cart_get(1)
    assert items and items[0]["quantity"] == 2
    await db.cart_remove(1, pid)
    await db.cart_clear(1)
    assert not await db.cart_get(1)

    # --- клавиатуры и тексты собираются ---
    kb = keyboards.main_menu(True)
    assert kb.inline_keyboard
    keyboards.payment_methods(1)
    keyboards.topup_methods(1)
    keyboards.check_crypto_kb(1)
    keyboards.catalog_categories()
    kb = keyboards.products_list(products[:2], "ru", 0, 2)
    assert any(getattr(btn, "callback_data", "") == "cat:ru:1"
               for row in kb.inline_keyboard for btn in row), "нет кнопки следующей страницы"
    keyboards.products_list(products, "ru", 0, 1)
    keyboards.products_list([], "ru", 1, 2)
    keyboards.product_card(pid)
    keyboards.admin_menu()
    keyboards.admin_products_kb(products)
    keyboards.admin_product_card(pid)
    keyboards.admin_orders_kb([])
    keyboards.admin_order_actions(1, "on_review")
    keyboards.admin_order_actions(1, "paid")
    keyboards.user_orders_kb([])
    keyboards.cart_keyboard([])
    keyboards.subscribe_kb()
    keyboards.back_menu("profile")
    texts.profile_text(u, 2, 4.0)
    texts.product_text(products[0], 90.0, 4.5)

    # --- ежедневная статистика собирается в текст ---
    daily = await logs.build_daily_text()
    assert "Ежедневная статистика" in daily

    # --- переменные (админка → «Переменные») ---
    old_card = config.CARD_NUMBER
    assert await variables.set_var("CARD_NUMBER", "4111111111111111") is None
    assert config.CARD_NUMBER == "4111111111111111"
    assert variables.display("CARD_NUMBER") == "4111111111111111"

    assert await variables.set_var("REFERRAL_PERCENT", "7") is None
    assert abs(float(config.REFERRAL_PERCENT) - 7.0) < 1e-9
    assert await variables.set_var("REFERRAL_PERCENT", "abc") is not None, "мусор принят как процент"
    assert await variables.set_var("REFERRAL_PERCENT", "150") is not None, "процент > 50 принят"
    assert await variables.set_var("LOG_DAILY_HOUR", "25") is not None, "час > 23 принят"
    assert await variables.set_var("LOG_DAILY_HOUR", "9") is None
    assert int(config.LOG_DAILY_HOUR) == 9
    assert await variables.set_var("SUPPORT_USERNAME", "") is not None, "пустое значение принято"
    assert await variables.set_var("DATA_DIR", "/tmp") is not None, "info-переменная отредактировалась"

    # нормализация и валидация текстовых переменных
    assert await variables.set_var("SUPPORT_USERNAME", "XcorpServis") is None
    assert config.SUPPORT_USERNAME == "@XcorpServis", "юзернейм поддержки не нормализован с @"
    assert await variables.set_var("XROCKET_API", "https://pay.api.xrocket.exchange/") is None
    assert config.XROCKET_API == "https://pay.api.xrocket.exchange", "слэш на конце не убран"
    assert await variables.set_var("CHANNEL_ID", "мусор") is not None, "кривой CHANNEL_ID принят"
    assert await variables.set_var("CHANNEL_ID", "@newchannel") is None
    assert config.CHANNEL_ID == "@newchannel"
    assert await variables.set_var("LOG_CHAT_ID", "") is None, "пустой LOG_CHAT_ID не выключил логи"
    assert config.LOG_CHAT_ID == 0
    assert "None" not in variables.display("LOG_TOPIC_ID"), "в отображении топика торчит None"

    # load_vars восстанавливает сохранённое поверх .env
    await variables.load_vars()
    assert config.CARD_NUMBER == "4111111111111111"

    # сброс возвращает значение из .env
    assert await variables.reset_var("CARD_NUMBER") is True
    assert config.CARD_NUMBER == old_card
    await variables.reset_var("REFERRAL_PERCENT")
    await variables.reset_var("LOG_DAILY_HOUR")

    txt = variables.vars_text()
    assert "ПЕРЕМЕННЫЕ БОТА" in txt and "скрыты" in txt
    keyboards.variables_kb()
    texts.subscribe_text()
    texts.rules_text()
    texts.support_text()

    # --- автоотмена зависших заказов ---
    stale_oid = await db.create_order(1, pid, "Тест-аккаунт", 2.0, 200.0, 0.5, "test", "XC-STALE", status="awaiting_payment")
    async with db.connect() as c:
        await c.execute("UPDATE orders SET created_at='2020-01-01 00:00:00' WHERE id=?", (stale_oid,))
        await c.commit()
    cancelled = await db.cancel_stale_orders(3)
    assert any(o["id"] == stale_oid for o in cancelled), "зависший заказ не отменён"
    assert (await db.get_order(stale_oid))["status"] == "cancelled", "статус не cancelled"
    fresh_oid = await db.create_order(1, pid, "Тест-аккаунт", 2.0, 200.0, 0.5, "test", "XC-FRESH", status="awaiting_payment")
    cancelled = await db.cancel_stale_orders(3)
    assert not any(o["id"] == fresh_oid for o in cancelled), "свежий заказ не должен отменяться"
    await db.set_order_status(fresh_oid, "cancelled")  # убрать из pending для чистоты

    # --- уведомление о заканчивающемся товаре ---
    class _FakeBot:
        def __init__(self):
            self.sent = []
        async def send_message(self, chat_id, text, **kwargs):
            self.sent.append(text)

    fb = _FakeBot()
    config.LOG_CHAT_ID = -100  # тест переменных выше выключал логи — вернуть
    logs.reset_log_state()
    logs._low_stock_warned.clear()
    await db.set_stock(pid, 2)
    await logs.check_low_stock(fb, pid)
    assert fb.sent and "заканчивается" in fb.sent[0], "нет предупреждения о малом остатке"
    await logs.check_low_stock(fb, pid)
    assert len(fb.sent) == 1, "предупреждение дублируется"
    await db.set_stock(pid, 10)
    await logs.check_low_stock(fb, pid)
    assert logs._low_stock_warned[pid] is False, "флаг не сброшен после пополнения"
    await db.set_stock(pid, 9)

    # --- бэкап БД (SQLite backup API) ---
    backup_path = await backups.make_backup()
    assert backup_path.exists() and backup_path.stat().st_size > 0, "файл бэкапа пуст"
    async with aiosqlite.connect(str(backup_path)) as bconn:
        async with bconn.execute("SELECT COUNT(*) FROM orders") as cur:
            assert (await cur.fetchone())[0] >= 1, "в бэкапе нет заказов"
    assert backups.parse_hours() == [6, 18], f"parse_hours: {backups.parse_hours()}"
    n_backups = len(list((Path(config.DATA_DIR) / "backups").glob("shop-*.db")))
    assert n_backups == 1, f"ожидается 1 бэкап, найдено {n_backups}"

    # --- хелпер обновления сообщения заказа (текст/фото) ---
    from app.handlers import admin as admin_mod

    class _FakeMsg:
        def __init__(self, mode):
            self.mode = mode
            self.calls = []
        async def edit_text(self, text, reply_markup=None):
            if self.mode == 'photo':
                raise RuntimeError('no text in photo message')
            self.calls.append(('text', text))
        async def edit_caption(self, caption, reply_markup=None):
            if self.mode == 'photo':
                self.calls.append(('caption', caption))
            else:
                raise RuntimeError('no caption')
        async def edit_reply_markup(self, reply_markup=None):
            self.calls.append(('markup',))

    class _FakeCall:
        def __init__(self, msg):
            self.message = msg

    msg = _FakeMsg('text')
    await admin_mod._settle_order_message(_FakeCall(msg), 'тест', 'KB')
    assert msg.calls[0][0] == 'text', 'текстовое сообщение не обновилось'

    msg = _FakeMsg('photo')
    await admin_mod._settle_order_message(_FakeCall(msg), 'тест', 'KB')
    assert msg.calls[0][0] == 'caption', 'фото-сообщение не обновилось через caption'

    class _DeadMsg(_FakeMsg):
        async def edit_text(self, text, reply_markup=None):
            raise RuntimeError('x')
        async def edit_caption(self, caption, reply_markup=None):
            raise RuntimeError('x')
        async def edit_reply_markup(self, reply_markup=None):
            raise RuntimeError('x')
    await admin_mod._settle_order_message(_FakeCall(_DeadMsg('x')), 'тест', 'KB')  # не должно падать
    print('OK: _settle_order_message (текст/фото/всё-упало)')

    # --- все хендлеры регистрируются ---
    from aiogram import Dispatcher

    bot = None
    try:
        from aiogram import Bot
        bot = Bot(token="123456:TEST")
    except Exception:
        pass
    dp = Dispatcher(storage=None)
    for r in routers:
        dp.include_router(r)
    n_callbacks = sum(len(r.callback_query.handlers) for r in routers)
    n_messages = sum(len(r.message.handlers) for r in routers)
    print(f"Роутеры: {len(routers)}, callback-хендлеров: {n_callbacks}, message-хендлеров: {n_messages}")
    if bot is not None:
        await bot.session.close()

    print("\nOK: check.py пройден без ошибок ✔")


if __name__ == "__main__":
    asyncio.run(main())
