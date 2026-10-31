# -*- coding: utf-8 -*-
"""Премиум-эмодзи и тексты бота."""
from . import config

# ============================================================
#  ПРЕМИУМ-ЭМОДЗИ (ID из пака Telegram iOS Icons)
# ============================================================
E_TG       = "6028346797368283073"   # телеграм
E_FOLDER   = "6039630677182254664"   # папка / каталог
E_PROFILE  = "6035084557378654059"   # профиль
E_MONEY    = "5904359114531675993"   # вывод денег / пополнить
E_PRICE    = "5890727932011223292"   # ценник / промокод
E_QUESTION = "6035191085452497972"   # человек с вопросом / поддержка
E_INFO     = "6028435952299413210"   # инфо / правила
E_GEAR     = "6032742198179532882"   # настройки / админка
E_STATS    = "5936143551854285132"   # статистика
E_ADD      = "5882207227997066107"   # добавить
E_FILE     = "6037475557082403885"   # заказы / файл
E_USERS    = "6032609071373226027"   # люди
E_BROADCAST= "6021418126061605425"   # рупор
E_PHOTO    = "6030466823290360017"   # медиа фото / баннер
E_BACK     = "5960671702059848143"   # назад
E_CHECK    = "5774022692642492953"   # галочка / проверка
E_CROSS    = "5774077015388852135"   # крестик
E_GIFT     = "6032644646587338669"   # подарок / выдано
E_TON      = "5778421276024509124"   # TON монеты
E_TON2     = "5769406891289481208"   # TON
E_DOLLAR   = "5904462880941545555"   # доллар
E_CARD     = "5904462880941545555"   # карта (доллар)
E_CRYPTO   = "5769406891289481208"   # крипта (TON)
E_MSG      = "6030784887093464891"   # сообщение
E_BELL     = "6039486778597970865"   # уведомление / подписаться
E_BOOKMARK = "6030425896546996257"   # закладка
E_LOCK     = "6037249452824072506"   # замок
E_GLOBE    = "5776233299424843260"   # глобус
E_CLOCK    = "5983150113483134607"   # часы
E_EYE      = "6037397706505195857"   # глаз
E_SPEAK    = "6032653721853234759"   # говорящий
E_CROWN    = "5805553606635559688"   # корона
E_STAR     = "6034923938486684992"   # звезда
E_VERIFY   = "5938252440926163756"   # верификация


# ============================================================
#  ТЕКСТЫ
#  Тексты, зависящие от переменных (админка → «Переменные»),
#  собираются в момент вызова, а не при импорте.
# ============================================================
def subscribe_text() -> str:
    return f"""<b>ПОДПИСКА НА КАНАЛ</b>
━━━━━━━━━━━━━━━━━━
<tg-emoji emoji-id="{E_BELL}">🔔</tg-emoji> Чтобы пользоваться ботом,
подпишись на наш канал:

<b>{config.CHANNEL_ID}</b>

После подписки нажми
<tg-emoji emoji-id="{E_CHECK}">✅</tg-emoji> <b>Проверить подписку</b>
━━━━━━━━━━━━━━━━━━"""


START_TEXT = f"""<b>X CORP SHOP</b>
━━━━━━━━━━━━━━━━━━
<tg-emoji emoji-id="{E_TG}">✈️</tg-emoji> <b>X CORP SHOP приветствует тебя.</b>

В нашем боте ты можешь купить любые аккаунты:
RU / USA / EU.

<b>Оплата:</b>
<tg-emoji emoji-id="{E_CRYPTO}">💎</tg-emoji> Крипта (CryptoBot)
<tg-emoji emoji-id="{E_DOLLAR}">🪙</tg-emoji> Карта
<tg-emoji emoji-id="{E_TON}">💰</tg-emoji> TON

Все аккаунты без спам-блока.
━━━━━━━━━━━━━━━━━━
Выбери действие ниже."""


def rules_text() -> str:
    return f"""<b>ПРАВИЛА X CORP SHOP</b>
━━━━━━━━━━━━━━━━━━
<tg-emoji emoji-id="{E_INFO}">ℹ</tg-emoji> Перед покупкой внимательно читай описание.
<tg-emoji emoji-id="{E_CHECK}">✅</tg-emoji> Оплата фиксируется после подтверждения админом.
<tg-emoji emoji-id="{E_QUESTION}">❓</tg-emoji> Выдача — через поддержку {config.SUPPORT_USERNAME}.
<tg-emoji emoji-id="{E_GIFT}">🎁</tg-emoji> Замена аккаунта возможна только по гарантии.
<tg-emoji emoji-id="{E_MONEY}">💰</tg-emoji> Возврат рассматривается индивидуально.
<tg-emoji emoji-id="{E_CROSS}">❌</tg-emoji> Фрод и мошенничество — бан без возврата.
━━━━━━━━━━━━━━━━━━
<b>Канал:</b> {config.CHANNEL_URL}
<b>Поддержка:</b> {config.SUPPORT_USERNAME}"""


def support_text() -> str:
    return f"""<b>ПОДДЕРЖКА</b>
━━━━━━━━━━━━━━━━━━
<tg-emoji emoji-id="{E_QUESTION}">❓</tg-emoji> Напиши нам по любым вопросам:
- Покупка
- Оплата
- Выдача заказа
- Замена аккаунта

<b>Контакт:</b> {config.SUPPORT_USERNAME}
<b>Канал:</b> {config.CHANNEL_URL}
━━━━━━━━━━━━━━━━━━"""


PROMO_TEXT = f"""<b>ПРОМОКОД</b>
━━━━━━━━━━━━━━━━━━
<tg-emoji emoji-id="{E_PRICE}">🏷</tg-emoji> Введи промокод и получи рубли на баланс бота.

Отправь код одним сообщением."""


def profile_text(u, cnt, total):
    return f"""<b>ПРОФИЛЬ</b>
━━━━━━━━━━━━━━━━━━
<tg-emoji emoji-id="{E_PROFILE}">👤</tg-emoji> <b>ID:</b> <code>{u['id']}</code>
<tg-emoji emoji-id="{E_SPEAK}">🗣</tg-emoji> <b>Имя:</b> {u['first_name'] or '-'}
<tg-emoji emoji-id="{E_EYE}">👁</tg-emoji> <b>Username:</b> @{u['username'] or '-'}
<tg-emoji emoji-id="{E_CLOCK}">⏰</tg-emoji> <b>Регистрация:</b> {u['reg_date']}
━━━━━━━━━━━━━━━━━━
<tg-emoji emoji-id="{E_MONEY}">💰</tg-emoji> <b>Баланс:</b> {u['balance']:.2f} ₽
<tg-emoji emoji-id="{E_FILE}">📁</tg-emoji> <b>Покупок:</b> {cnt}
<tg-emoji emoji-id="{E_DOLLAR}">🪙</tg-emoji> <b>Сумма покупок:</b> {total:.2f} $
━━━━━━━━━━━━━━━━━━"""


def product_text(p, rate_rub, rate_ton):
    rub = p["price_usd"] * rate_rub
    ton = p["price_usd"] / rate_ton if rate_ton else 0
    return f"""<b>{p['name']}</b>
━━━━━━━━━━━━━━━━━━
{p['description'] or 'Без описания'}
━━━━━━━━━━━━━━━━━━
<tg-emoji emoji-id="{E_DOLLAR}">🪙</tg-emoji> <b>Цена:</b> {p['price_usd']:.2f} $
<tg-emoji emoji-id="{E_MONEY}">💰</tg-emoji> <b>В рублях:</b> {rub:.2f} ₽
<tg-emoji emoji-id="{E_TON2}">💎</tg-emoji> <b>В TON:</b> {ton:.4f} TON
<tg-emoji emoji-id="{E_FOLDER}">📂</tg-emoji> <b>Категория:</b> {p['category'].upper()}
<tg-emoji emoji-id="{E_CHECK}">✅</tg-emoji> <b>Наличие:</b> {p['stock']} шт
━━━━━━━━━━━━━━━━━━"""
