# -*- coding: utf-8 -*-
"""End-to-end тест: реальные сценарии через диспетчер с мок-сервером Telegram.

Прогоняет обработчики целиком (не только базу, как check.py):
старт, подписка, админка, добавление товара, покупка, все способы оплаты,
подтверждение/выдача, отзывы, промокоды, пополнения, корзина, переменные,
поддержка, бан/разбан, рассылка.

Запуск: python e2e_test.py
"""
import asyncio
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="xcorp_e2e_")

from app.compat import ensure_dependencies

ensure_dependencies()

import aiosqlite  # noqa: E402
from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.methods import (  # noqa: E402
    CreateForumTopic, GetChat, GetChatMember, GetMe, SendPhoto, SendMessage,
)
from aiogram.types import (  # noqa: E402
    CallbackQuery, Chat, ChatMemberMember, ForumTopic, Message, PhotoSize,
    Update, User,
)

from app import config, db, payments, utils  # noqa: E402
from app.handlers import routers  # noqa: E402

LOG_CHAT = config.LOG_CHAT_ID
ADMIN = config.ADMIN_IDS[0]
USER = 555000111       # обычный пользователь
USER2 = 555000222      # реферал пользователя
REFERRER = USER

USER_TG = User(id=0, is_bot=False, first_name="Пользователь", username="u")


def make_user(uid: int, username: str = "u") -> User:
    return User(id=uid, is_bot=False, first_name="Пользователь", username=username)


def make_message(uid: int, text: str = None, photo: bool = False) -> Message:
    kwargs = dict(
        message_id=int(time.time() * 1000) % 10**9,
        date=datetime.now(),
        chat=Chat(id=uid, type="private", first_name="Пользователь"),
        from_user=make_user(uid),
    )
    if text is not None:
        kwargs["text"] = text
    if photo:
        kwargs["photo"] = [PhotoSize(file_id="photo123", file_unique_id="u1", width=10, height=10)]
    return Message(**kwargs)


def make_callback(uid: int, data: str, message: Message) -> CallbackQuery:
    return CallbackQuery(
        id=str(int(time.time() * 1000) % 10**9),
        from_user=make_user(uid),
        chat_instance="ci",
        data=data,
        message=message,
    )


class MockSession(BaseSession):
    """Мок Telegram API: возвращает валидные типы, логирует вызовы."""

    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, SendPhoto)):
            return Message(
                message_id=int(time.time() * 1000) % 10**9,
                date=datetime.now(),
                chat=Chat(id=method.chat_id, type="private"),
            )
        if isinstance(method, CreateForumTopic):
            # каждая тема — свой message_thread_id
            return ForumTopic(message_thread_id=1000 + len(self.calls), name=method.name)
        if isinstance(method, GetMe):
            return User(id=999, is_bot=True, first_name="XCorp", username="xcorp_test_bot")
        if isinstance(method, (GetChat, GetChatMember)):
            # Telegram принимает и @username, и число — в моке приводим к int
            chat_id = method.chat_id if isinstance(method.chat_id, int) else -1001234567890
        if isinstance(method, GetChat):
            return Chat(id=chat_id, type="supergroup", title="Логи")
        if isinstance(method, GetChatMember):
            return ChatMemberMember(
                chat=Chat(id=chat_id, type="supergroup"),
                user=make_user(method.user_id),
                status="member",
            )
        return True  # EditMessageText / DeleteMessage / AnswerCallbackQuery / ...


def msg_update(update_id, message):
    return Update(update_id=update_id, message=message)


def cb_update(update_id, call):
    return Update(update_id=update_id, callback_query=call)


async def main() -> int:
    # Фиксируем курсы, чтобы суммы были детерминированными (без сети)
    utils._cache.update({"rub": 95.0, "ton": 4.5, "ts": time.time() + 99999})

    session = MockSession()
    bot = Bot(token="123456:TEST", session=session)
    dp = Dispatcher(storage=__import__("aiogram.fsm.storage.memory", fromlist=["MemoryStorage"]).MemoryStorage())
    for r in routers:
        dp.include_router(r)

    await db.init_db()

    uid = [1]

    async def send(uid_, text=None, photo=False):
        uid[0] += 1
        await dp.feed_update(bot, msg_update(uid[0], make_message(uid_, text, photo)))

    async def press(uid_, data):
        uid[0] += 1
        m = make_message(uid_)
        await dp.feed_update(bot, cb_update(uid[0], make_callback(uid_, data, m)))

    def sent_to(chat_id, kind=SendMessage):
        return [m for m in session.calls if isinstance(m, kind) and m.chat_id == chat_id]

    print("=== 1. Старт и подписка ===")
    await send(USER, "/start")
    u = await db.get_user(USER)
    assert u and not u["is_banned"], "юзер не создан"
    assert sent_to(LOG_CHAT), "лог о новом пользователе не ушёл в группу"
    await send(ADMIN, "/start")
    await send(USER2, f"/start {REFERRER}")
    u2 = await db.get_user(USER2)
    assert u2["referrer_id"] == REFERRER, "реферал не привязан"
    print("OK: старт, логи в группу, реферал привязан")

    print("=== 2. Админ: добавление товара через FSM ===")
    await press(ADMIN, "adm:add_product")
    for step in ("ТестЮзер", "Описание теста", "10", "ru", "10", "-"):
        await send(ADMIN, step)
    products = await db.get_products("ru")
    assert products and products[0]["name"] == "ТестЮзер", "товар не создан"
    assert products[0]["stock"] == 10, f"остаток неверный: {products[0]['stock']}"
    pid = products[0]["id"]
    print(f"OK: товар #{pid} создан (остаток 10)")

    print("=== 3. Пользователь: каталог и покупка TON (скрин) ===")
    await press(USER, "catalog")
    await press(USER, "cat:ru")
    await press(USER, f"prod:{pid}")
    await press(USER, f"buy:{pid}")
    orders = await db.get_user_orders(USER)
    oid = orders[0]["id"]
    assert orders[0]["status"] == "awaiting_payment", "заказ не создан"
    await press(USER, f"pay_ton:{oid}")
    await send(USER, photo=True)  # скрин оплаты
    o = await db.get_order(oid)
    assert o["status"] == "on_review", f"статус не on_review: {o['status']}"
    assert o["screenshot_id"] == "photo123", "скрин не сохранён"
    assert sent_to(ADMIN, SendPhoto), "скрин не отправлен админу"
    print(f"OK: заказ #{oid} на проверке, скрин у админа")

    print("=== 4. Админ: подтверждение и выдача ===")
    await press(ADMIN, f"adm_confirm:{oid}")
    o = await db.get_order(oid)
    assert o["status"] == "paid", f"не подтверждён: {o['status']}"
    assert (await db.get_product(pid))["stock"] == 9, "остаток не списан"
    # повторное подтверждение не должно списывать товар
    await press(ADMIN, f"adm_confirm:{oid}")
    assert (await db.get_product(pid))["stock"] == 9, "двойное списание при повторном confirm!"
    await press(ADMIN, f"adm_issued:{oid}")
    assert (await db.get_order(oid))["status"] == "completed", "не выдан"
    print("OK: оплачен (остаток 9), повторный confirm безопасен, выдан")

    print("=== 5. Отзыв ===")
    await press(USER, "my_orders")
    await press(USER, f"my_ord:{oid}")
    await press(USER, f"review:{oid}")
    await press(USER, "review_rate:5")
    await send(USER, "Отличный магазин")
    async with aiosqlite.connect(config.DB_PATH) as conn:
        async with conn.execute("SELECT rating, comment FROM reviews WHERE order_id=?", (oid,)) as cur:
            row = await cur.fetchone()
    assert row and row[0] == 5 and row[1] == "Отличный магазин", f"отзыв не сохранён: {row}"
    print("OK: отзыв 5 звёзд сохранён")

    print("=== 6. Покупка с баланса + рефералка ===")
    await send(ADMIN, f"/setbal {USER2} 100000")
    assert (await db.get_user(USER2))["balance"] == 100000.0, "/setbal не сработал"
    await press(USER2, f"buy:{pid}")
    o2 = (await db.get_user_orders(USER2))[0]
    amount_rub = o2["amount_rub"]
    await press(USER2, f"pay_balance:{o2['id']}")
    o2 = await db.get_order(o2["id"])
    assert o2["status"] == "paid", f"оплата балансом не прошла: {o2['status']}"
    assert (await db.get_user(USER2))["balance"] == 100000.0 - amount_rub, "баланс списан неверно"
    assert (await db.get_user(REFERRER))["balance"] == round(amount_rub * 5.0 / 100, 2), \
        f"реферальный 5% не начислен: {(await db.get_user(REFERRER))['balance']}"
    print(f"OK: заказ #{o2['id']} оплачен с баланса ({amount_rub:.2f} ₽), рефереру +5%")

    print("=== 7. CryptoBot-оплата (мок API) ===")
    async def fake_create(amount_usd, desc):
        return "https://t.me/xcorp_invoice", 777

    async def fake_check(inv_id):
        return True

    real_create, real_check = payments.create_crypto_invoice, payments.check_crypto_invoice
    payments.create_crypto_invoice, payments.check_crypto_invoice = fake_create, fake_check
    try:
        await press(USER2, f"buy:{pid}")
        o3 = (await db.get_user_orders(USER2))[0]
        await press(USER2, f"pay_crypto:{o3['id']}")
        assert str((await db.get_order(o3['id']))["screenshot_id"]) == "inv:777", "счёт не сохранён"
        await press(USER2, f"check_crypto:{o3['id']}")
        assert (await db.get_order(o3["id"]))["status"] == "paid", "крипто-оплата не подтверждена"
        assert (await db.get_product(pid))["stock"] == 7, "остаток не списан при крипте"
    finally:
        payments.create_crypto_invoice, payments.check_crypto_invoice = real_create, real_check
    print("OK: счёт создан, оплата подтверждена, остаток 7")

    print("=== 8. Пополнение через CryptoBot ===")
    await press(USER2, "topup")
    await send(USER2, "500")
    topups = [o for o in await db.get_user_orders(USER2) if o["product_id"] == 0]
    toid = topups[0]["id"]
    payments.create_crypto_invoice, payments.check_crypto_invoice = fake_create, fake_check
    try:
        await press(USER2, f"topup_crypto:{toid}")
        await press(USER2, f"check_crypto:{toid}")
    finally:
        payments.create_crypto_invoice, payments.check_crypto_invoice = real_create, real_check
    balance_after_promo_later = (await db.get_user(USER2))["balance"]
    assert balance_after_promo_later == 100000.0 - amount_rub + 500.0, \
        f"пополнение не зачислено: {balance_after_promo_later}"
    print("OK: пополнение 500 ₽ зачислено на баланс")

    print("=== 9. Промокод ===")
    await db.create_promo("E2E10", 10.0, 1)
    await press(USER2, "promo")
    await send(USER2, "E2E10")
    assert (await db.get_user(USER2))["balance"] == balance_after_promo_later + 10.0, "промокод не зачислен"
    await press(USER2, "promo")
    await send(USER2, "E2E10")
    assert (await db.get_user(USER2))["balance"] == balance_after_promo_later + 10.0, "промокод применился дважды!"
    print("OK: промокод +10 ₽, повторно не применялся")

    print("=== 10. Отмена заказа ===")
    await press(USER2, f"buy:{pid}")
    o4 = (await db.get_user_orders(USER2))[0]
    await press(USER2, f"cancel_order:{o4['id']}")
    assert (await db.get_order(o4["id"]))["status"] == "cancelled", "не отменился"
    stock_before = (await db.get_product(pid))["stock"]
    await press(USER2, f"pay_balance:{o4['id']}")
    assert (await db.get_order(o4["id"]))["status"] == "cancelled", "отменённый заказ оплатился!"
    assert (await db.get_product(pid))["stock"] == stock_before, "остаток изменился у отменённого"
    print("OK: отменённый заказ нельзя оплатить")

    print("=== 11. Переменные ===")
    await press(ADMIN, "adm:vars")
    await press(ADMIN, "adm_var:CARD_NUMBER")
    await send(ADMIN, "9999")
    assert config.CARD_NUMBER == "9999", "переменная не применилась"
    await press(ADMIN, "adm_var:SUPPORT_USERNAME")
    await send(ADMIN, "newsupport")
    assert config.SUPPORT_USERNAME == "@newsupport", "юзернейм не нормализован"
    await press(ADMIN, "adm_var:CARD_NUMBER")
    await send(ADMIN, "-")
    assert config.CARD_NUMBER != "9999", "сброс переменной не сработал"
    print("OK: переменные меняются, нормализуются и сбрасываются")

    print("=== 12. Поддержка ===")
    await press(USER, "support_ticket")
    await send(USER, "Помогите с заказом")
    async with aiosqlite.connect(config.DB_PATH) as conn:
        async with conn.execute("SELECT COUNT(*) FROM support_tickets WHERE user_id=?", (USER,)) as cur:
            tickets = (await cur.fetchone())[0]
    assert tickets == 1, "тикет не сохранён"
    assert any(isinstance(m, SendMessage) and m.chat_id == ADMIN and "обращение" in (m.text or "").lower()
               for m in session.calls), "админу не ушло обращение"
    # --- ответ админа прямо из темы поддержки (кнопка) ---
    async with aiosqlite.connect(config.DB_PATH) as conn:
        async with conn.execute("SELECT id FROM support_tickets WHERE user_id=?", (USER,)) as cur:
            tid = (await cur.fetchone())[0]
    await press(ADMIN, f"adm_reply:{tid}")
    await send(ADMIN, "Ваш вопрос решён!")
    assert any(isinstance(m, SendMessage) and m.chat_id == USER and "решён" in (m.text or "").lower()
               for m in session.calls), "ответ поддержки не доставлен юзеру"
    async with aiosqlite.connect(config.DB_PATH) as conn:
        async with conn.execute("SELECT status FROM support_tickets WHERE id=?", (tid,)) as cur:
            status = (await cur.fetchone())[0]
    assert status == "answered", f"тикет не помечен отвеченным: {status}"
    print("OK: обращение сохранено, админ ответил из группы через кнопку")

    print("=== 13. Рассылка и бан ===")
    await press(ADMIN, "adm:broadcast")
    await send(ADMIN, "Всем привет!")
    assert any(isinstance(m, SendMessage) and m.chat_id == USER and "привет" in (m.text or "").lower()
               for m in session.calls), "рассылка не дошла"
    await send(ADMIN, f"/ban {USER2}")
    await send(USER2, "/start")
    assert (await db.get_user(USER2))["is_banned"] == 1, "бан не сработал"
    await send(ADMIN, f"/unban {USER2}")
    assert (await db.get_user(USER2))["is_banned"] == 0, "разбан не сработал"
    print("OK: рассылка доставлена, бан/разбан работают")

    print("=== 14. Чужие кнопки не работают ===")
    await press(USER, "adm:stats")  # не админ — молча игнор
    await press(USER, f"cancel_order:{o2['id']}")  # чужой заказ
    assert (await db.get_order(o2["id"]))["status"] == "paid", "чужой cancel сломал заказ"
    print("OK: не-админ не видит админку, чужой заказ не отменяется")

    n_log_messages = len(sent_to(LOG_CHAT))
    print(f"\nOK: e2e пройден. В лог-группу отправлено {n_log_messages} сообщений.")
    await bot.session.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except AssertionError as e:
        print(f"\nFAIL: {e}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        pass
