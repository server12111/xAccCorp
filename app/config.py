# -*- coding: utf-8 -*-
"""Конфигурация: читает .env рядом с main.py и переменные окружения."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None

    env_file = PROJECT_ROOT / ".env"
    if load_dotenv is not None:
        # override=False: переменные окружения сервера важнее .env
        load_dotenv(env_file, override=False)
        return

    # Запасной парсер, если python-dotenv не установлен
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            os.environ.setdefault(key, val)


_load_dotenv()


def _get(name: str, default: str = "") -> str:
    val = os.getenv(name)
    return default if val is None or val == "" else val


def _get_int(name: str, default: int) -> int:
    try:
        return int(str(_get(name, str(default))).strip())
    except (TypeError, ValueError):
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(str(_get(name, str(default))).replace(",", ".").strip())
    except (TypeError, ValueError):
        return default


BOT_TOKEN        = _get("BOT_TOKEN").strip()


def _get_admin_ids():
    """Список админов из ADMIN_IDS («id1,id2») или, по-старому, из ADMIN_ID."""
    raw = _get("ADMIN_IDS", "") or _get("ADMIN_ID", "")
    ids = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            val = int(part)
        except ValueError:
            continue
        if val not in ids:
            ids.append(val)
    return ids


ADMIN_IDS        = _get_admin_ids()
ADMIN_ID         = ADMIN_IDS[0] if ADMIN_IDS else 0  # основной админ (для совместимости)

# --- база данных ---
# По умолчанию /app/data: на сервере перезапуск переживает только эта папка.
DATA_DIR         = Path(_get("DATA_DIR", "/app/data")).expanduser()
DB_NAME          = _get("DB_NAME", "shop.db")
DB_PATH          = str(DATA_DIR / DB_NAME)

# --- логи в Telegram-группу ---
LOG_CHAT_ID      = _get_int("LOG_CHAT_ID", 0)
LOG_TOPIC_ID     = _get_int("LOG_TOPIC_ID", 0) or None
LOG_DAILY_HOUR   = _get_int("LOG_DAILY_HOUR", 12)
BACKUP_HOURS     = _get("BACKUP_HOURS", "6,18")
BACKUP_KEEP      = _get_int("BACKUP_KEEP", 7)
AUTO_CANCEL_HOURS = _get_int("AUTO_CANCEL_HOURS", 3)

# --- платежи ---
CRYPTO_BOT_TOKEN = _get("CRYPTO_BOT_TOKEN").strip()
XROCKET_TOKEN    = _get("XROCKET_TOKEN").strip()
XROCKET_API      = _get("XROCKET_API", "https://pay.api.xrocket.exchange").rstrip("/")
CRYPTO_FEE       = _get_float("CRYPTO_FEE", 3.0)
TON_ADDRESS      = _get("TON_ADDRESS", "UQBKrhfxHUKXbOkrrRJ4LJ175AecBxXgXbKKYgy4NPsidcYy")
CARD_NUMBER      = _get("CARD_NUMBER", "2200701718338822")

# --- канал / поддержка ---
SUPPORT_USERNAME = _get("SUPPORT_USERNAME", "@XcorpServis")
CHANNEL_URL      = _get("CHANNEL_URL", "https://t.me/xcorpServise")
CHANNEL_ID       = _get("CHANNEL_ID", "@xcorpServise")

REFERRAL_PERCENT = _get_float("REFERRAL_PERCENT", 5.0)

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError as e:
    # Не валим запуск, но предупреждаем: база может не сохраниться.
    import logging
    logging.getLogger("xcorp.config").error(
        "Не удалось создать папку данных %s: %s", DATA_DIR, e
    )
