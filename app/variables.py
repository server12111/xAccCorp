# -*- coding: utf-8 -*-
"""Редактируемые переменные бота (админ-панель → «Переменные»).

Значения хранятся в БД (settings, ключ var_<ИМЯ>) и применяются сразу,
без перезапуска. По умолчанию берутся из .env. Токены и админы сюда
не входят: их нельзя посмотреть или поменять из чата.
"""
from html import escape

import aiohttp

from . import config, db


async def _check_cryptobot_token(token: str) -> bool:
    """Crypto Pay API: getMe отвечает ok:true только с валидным токеном."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://pay.crypt.bot/api/getMe",
                headers={"Crypto-Pay-API-Token": token},
                timeout=15,
            ) as r:
                return bool((await r.json()).get("ok"))
    except Exception:
        return False

# ИМЯ: (заголовок, тип, редактируемая?, подсказка)
# типы: text — строка; number — число; hour — час 0-23;
#       chat — id чата (проверяется через Telegram); topic — id топика;
#       secret — токен (маскируется, полное значение нигде не показывается); info — только просмотр
VAR_DEFS = {
    "TON_ADDRESS":      ("TON-адрес для оплаты", "text", True, "Сюда пользователи переводят TON"),
    "CARD_NUMBER":      ("Номер карты", "text", True, "Показывается при оплате картой"),
    "SUPPORT_USERNAME": ("Юзернейм поддержки", "text", True, "Например @XcorpServis"),
    "CHANNEL_URL":      ("Ссылка на канал", "text", True, "Кнопка «Канал» в меню"),
    "CHANNEL_ID":       ("ID канала (подписка)", "text", True, "Например @xcorpServise — по нему проверяется подписка"),
    "REFERRAL_PERCENT": ("Реферальный процент", "number", True, "0-50, % с покупки приглашённого"),
    "CRYPTO_FEE":       ("Надбавка CryptoBot", "number", True, "0-50, % сверху суммы счёта"),
    "CRYPTO_BOT_TOKEN": ("Токен CryptoBot (Crypto Pay)", "secret", True,
                         "Из @CryptoBot → Crypto Pay → Create App. Проверяется через API перед сохранением"),
    "XROCKET_TOKEN":    ("Токен xRocket Pay", "secret", True,
                         "Длинная строка eyJ... из @xRocketPay. Применяется сразу"),
    "XROCKET_API":      ("Адрес API xRocket", "text", True,
                         "НЕ ТРОГАТЬ без необходимости! Всегда начинается с https://"),
    "LOG_CHAT_ID":      ("ID лог-группы", "chat", True, "Куда шлются события; бот проверит чат перед сохранением"),
    "LOG_TOPIC_ID":     ("ID топика лог-группы", "topic", True, "0 или пусто = без топика"),
    "LOG_DAILY_HOUR":   ("Час суточной статистики", "hour", True, "0-23, время сервера"),
    "DATA_DIR":         ("Папка базы данных", "info", False, "Меняется только в .env (нужен перезапуск)"),
}

VAR_ORDER = list(VAR_DEFS.keys())

# Значения по умолчанию из .env (зафиксированы на момент запуска)
_DEFAULTS = {
    "TON_ADDRESS": config.TON_ADDRESS,
    "CARD_NUMBER": config.CARD_NUMBER,
    "SUPPORT_USERNAME": config.SUPPORT_USERNAME,
    "CHANNEL_URL": config.CHANNEL_URL,
    "CHANNEL_ID": config.CHANNEL_ID,
    "REFERRAL_PERCENT": config.REFERRAL_PERCENT,
    "CRYPTO_FEE": config.CRYPTO_FEE,
    "CRYPTO_BOT_TOKEN": config.CRYPTO_BOT_TOKEN,
    "XROCKET_TOKEN": config.XROCKET_TOKEN,
    "LOG_CHAT_ID": config.LOG_CHAT_ID,
    "LOG_TOPIC_ID": config.LOG_TOPIC_ID or 0,
    "LOG_DAILY_HOUR": config.LOG_DAILY_HOUR,
    "XROCKET_API": config.XROCKET_API,
    "DATA_DIR": str(config.DATA_DIR),
}


def _parse(key, raw):
    """Приводит строку к типу переменной. Бросает ValueError при мусоре."""
    kind = VAR_DEFS[key][1] if key in VAR_DEFS else "text"
    raw = str(raw).strip()
    if kind == "number":
        return float(raw.replace(",", "."))
    if kind == "hour":
        return int(float(raw.replace(",", ".")))
    if kind in ("chat", "topic"):
        return int(raw or "0")
    return raw


def _apply(key, raw):
    try:
        setattr(config, key, _parse(key, raw))
    except (ValueError, TypeError):
        pass


async def load_vars() -> None:
    """При старте: применяет сохранённые в БД значения поверх .env."""
    for key in VAR_DEFS:
        val = await db.get_setting(f"var_{key}")
        if val is not None:
            _apply(key, val)
    # Старый ключ referral_percent (если меняли вручную в БД) мигрируем
    if await db.get_setting("var_REFERRAL_PERCENT") is None:
        legacy = await db.get_setting("referral_percent")
        if legacy is not None:
            _apply("REFERRAL_PERCENT", str(legacy))


def display(key) -> str:
    """Человекочитаемое текущее значение."""
    v = getattr(config, key, "")
    kind = VAR_DEFS[key][1] if key in VAR_DEFS else "text"
    if key == "REFERRAL_PERCENT":
        return f"{float(v):g} %"
    if key == "CRYPTO_FEE":
        return f"{float(v):g} %"
    if key == "LOG_DAILY_HOUR":
        return f"{int(v):02d}:00 (время сервера)"
    if key == "LOG_TOPIC_ID":
        return "(без топика)" if not v else str(v)
    if key == "LOG_CHAT_ID":
        return str(v) if v else "выключено"
    if kind == "secret":
        # Токен никогда не показывается целиком — только хвост
        return f"задан (····{str(v)[-4:]})" if v else "не задан"
    return str(v)


def vars_text() -> str:
    """Текст экрана «Переменные» для админки."""
    lines = [
        "<b>ПЕРЕМЕННЫЕ БОТА</b>",
        "━━━━━━━━━━━━━━━━━━",
        "✏ — можно менять прямо здесь, применяется сразу, без перезапуска.",
        "При изменении можно отправить <code>-</code> — вернётся значение из .env.",
        "Значения из БД важнее .env.",
        "━━━━━━━━━━━━━━━━━━",
    ]
    for key in VAR_ORDER:
        title, _kind, editable, _hint = VAR_DEFS[key]
        mark = "✏" if editable else "ℹ"
        lines.append(f"{mark} <b>{escape(title)}</b> — <code>{escape(display(key))}</code>")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("🔑 <b>BOT_TOKEN и админы:</b> скрыты, меняются только в .env")
    return "\n".join(lines)


async def set_var(key, raw, bot=None):
    """Сохранить значение. Возвращает None при успехе или текст ошибки."""
    if key not in VAR_DEFS or not VAR_DEFS[key][2]:
        return "Неизвестная или нередактируемая переменная"
    kind = VAR_DEFS[key][1]
    raw = (raw or "").strip()
    if len(raw) > 300:
        return "Слишком длинное значение (максимум 300 символов)"

    # Пустое значение для LOG_CHAT_ID/LOG_TOPIC_ID = выключить
    if kind in ("chat", "topic") and raw == "":
        raw = "0"

    if kind in ("number", "hour", "chat", "topic"):
        try:
            num = float(raw.replace(",", "."))
        except ValueError:
            return "Нужно число (например 5 или 5.5)"
        if kind == "hour":
            if not (0 <= num <= 23 and num == int(num)):
                return "Час должен быть целым числом от 0 до 23"
        elif key == "REFERRAL_PERCENT":
            if not 0 <= num <= 50:
                return "Реферальный процент: от 0 до 50"
        elif key == "CRYPTO_FEE":
            if not 0 <= num <= 50:
                return "Надбавка CryptoBot: от 0 до 50"
        elif kind == "chat":
            try:
                cid = int(raw)
            except ValueError:
                return "ID чата — целое число (например -1001234567890)"
            if bot is not None and cid:
                found = False
                candidates = [cid]
                if not str(cid).startswith("-100"):
                    candidates.append(int(f"-100{abs(cid)}"))
                for cand in candidates:
                    try:
                        await bot.get_chat(cand)
                        cid = cand
                        found = True
                        break
                    except Exception:
                        continue
                if not found:
                    return "Бот не нашёл такой чат. Добавь бота в группу и проверь ID"
            raw = str(cid)
        elif kind == "topic":
            if num < 0:
                return "ID топика — положительное число или 0"
    else:
        if not raw:
            return "Значение не может быть пустым (отправь '-', чтобы вернуть значение из .env)"
        if key == "SUPPORT_USERNAME" and not raw.startswith("@"):
            raw = "@" + raw.lstrip("@")
        if key == "XROCKET_API" and not raw.startswith(("http://", "https://")):
            return "Адрес API должен начинаться с https:// (например https://pay.api.xrocket.exchange). Токен вставляется в «Токен xRocket Pay»"
        if key == "XROCKET_TOKEN" and raw.startswith(("http://", "https://")):
            return "Это похоже на адрес API, а не токен. Токен xRocket — длинная строка eyJ..."
        if kind == "secret":
            if key == "CRYPTO_BOT_TOKEN" and raw.startswith(("http://", "https://")):
                return "Это похоже на ссылку, а не токен. Токен CryptoBot — из Crypto Pay → Create App"
            if len(raw) < 8:
                return "Токен слишком короткий"
            if key == "CRYPTO_BOT_TOKEN" and bot is not None:
                # CryptoBot проверяет токен сразу через свой API
                if not await _check_cryptobot_token(raw):
                    return "CryptoBot не принял токен. Возьми его в @CryptoBot → Crypto Pay → Create App"
            if key == "XROCKET_TOKEN" and bot is not None:
                try:
                    async with aiohttp.ClientSession() as s:
                        async with s.get(
                            f"{config.XROCKET_API}/api/v1/me",
                            headers={"Authorization": f"Bearer {raw}"},
                            timeout=15,
                        ) as r:
                            if r.status in (401, 403):
                                return "xRocket не принял токен. Возьми его в приложении @xRocketPay"
                except Exception:
                    pass  # сеть недоступна — сохраняем без проверки
        if key == "CHANNEL_ID":
            ok = raw.startswith("@") or (raw.startswith("-100") and raw[4:].isdigit()) or raw.isdigit()
            if not ok:
                return "ID канала: @username (например @xcorpServise) или числовой id (-100...)"
            # Бот должен видеть канал, иначе проверка подписки заблокирует всех
            if bot is not None:
                try:
                    await bot.get_chat(raw)
                except Exception:
                    return "Бот не видит такой канал. Добавь бота админом в канал и попробуй снова"
        if key in ("XROCKET_API", "CHANNEL_URL") and raw.endswith("/"):
            raw = raw.rstrip("/")

    try:
        _parse(key, raw)  # финальная проверка перед сохранением
    except (ValueError, TypeError):
        return "Не удалось разобрать значение"

    await db.set_setting(f"var_{key}", raw)
    _apply(key, raw)
    if key in ("LOG_CHAT_ID", "LOG_TOPIC_ID"):
        # Смена лог-чата: сбрасываем кэш доставки и созданные темы
        from . import logs
        logs.reset_log_state()
        await logs.reset_topics()
    return None


async def reset_var(key) -> bool:
    """Вернуть значение из .env (удалить переопределение из БД)."""
    if key not in VAR_DEFS or not VAR_DEFS[key][2]:
        return False
    await db.del_setting(f"var_{key}")
    setattr(config, key, _DEFAULTS[key])
    if key in ("LOG_CHAT_ID", "LOG_TOPIC_ID"):
        from . import logs
        logs.reset_log_state()
        await logs.reset_topics()
    return True
