# -*- coding: utf-8 -*-
"""Работа с SQLite (aiosqlite).

Файл базы лежит в DATA_DIR (по умолчанию /app/data) — эта папка
переживает перезапуск сервера/контейнера. Старый shop.db рядом с
main.py автоматически копируется в новую папку при первом запуске.
"""
import shutil
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from . import config
from .config import DB_PATH, PROJECT_ROOT

FINAL_STATUSES = ("paid", "issued", "completed", "cancelled", "rejected")

# Поля заказа, которые разрешено менять через set_order_field
# (белый список — защита от SQL-инъекций через имя поля).
_ORDER_FIELDS = {"payment_method", "screenshot_id", "status", "track"}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _migrate_legacy_db() -> None:
    """Старый shop.db рядом с main.py переносим в DATA_DIR (один раз)."""
    legacy = PROJECT_ROOT / "shop.db"
    target = Path(DB_PATH)
    try:
        if legacy.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy, target)
    except OSError:
        pass


def connect():
    """Единая точка подключения: ожидание блокировки до 15 сек,
    чтобы БД не падала с 'database is locked' при параллельных запросах."""
    return aiosqlite.connect(DB_PATH, timeout=15.0)


async def backup_to(dest_path: str) -> None:
    """Безопасная копия базы через SQLite backup API (можно при живой записи)."""
    async with connect() as src:
        async with aiosqlite.connect(dest_path) as dst:
            await src.backup(dst)


async def init_db() -> None:
    _migrate_legacy_db()
    async with connect() as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0,
            reg_date TEXT,
            is_banned INTEGER DEFAULT 0,
            referrer_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            price_usd REAL NOT NULL,
            category TEXT DEFAULT 'other',
            stock INTEGER DEFAULT 0,
            photo_id TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_id INTEGER,
            product_name TEXT,
            amount_usd REAL,
            amount_rub REAL,
            amount_ton REAL,
            payment_method TEXT,
            status TEXT DEFAULT 'pending',
            track TEXT,
            screenshot_id TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            amount REAL,
            uses_left INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS promo_uses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            code TEXT,
            used_at TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS referral_rewards (
            order_id INTEGER PRIMARY KEY, referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL, amount REAL NOT NULL, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS cart_items (
            user_id INTEGER NOT NULL, product_id INTEGER NOT NULL, quantity INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(user_id, product_id)
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, order_id INTEGER NOT NULL UNIQUE,
            product_id INTEGER, rating INTEGER NOT NULL, comment TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, message TEXT NOT NULL,
            status TEXT DEFAULT 'open', created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
        CREATE INDEX IF NOT EXISTS idx_promo_uses ON promo_uses(user_id, code);
        CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referrer_id);
        """)
        await db.commit()


# --- users ---
async def get_user(uid):
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id=?", (uid,)) as c:
            return await c.fetchone()


async def add_user(uid, username, first_name, ref=None) -> bool:
    """Создаёт пользователя. Возвращает True, если он новый.

    У существующего обновляет username/имя — иначе в профиле и логах
    остаются устаревшие данные после смены ника."""
    async with connect() as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO users (id,username,first_name,reg_date,referrer_id) VALUES (?,?,?,?,?)",
            (uid, username, first_name, now(), ref),
        )
        is_new = cur.rowcount > 0
        if not is_new:
            await db.execute(
                "UPDATE users SET username=?, first_name=? "
                "WHERE id=? AND (username IS NOT ? OR first_name IS NOT ?)",
                (username, first_name, uid, username, first_name),
            )
        await db.commit()
        return is_new


async def update_balance(uid, delta):
    async with connect() as db:
        await db.execute("UPDATE users SET balance=balance+? WHERE id=?", (delta, uid))
        await db.commit()


async def set_balance(uid, val):
    async with connect() as db:
        await db.execute("UPDATE users SET balance=? WHERE id=?", (val, uid))
        await db.commit()


async def ban_user(uid, s=1):
    async with connect() as db:
        await db.execute("UPDATE users SET is_banned=? WHERE id=?", (s, uid))
        await db.commit()


async def all_users():
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users ORDER BY reg_date DESC") as c:
            return await c.fetchall()


async def count_users():
    async with connect() as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            return (await c.fetchone())[0]


async def referral_stats(uid):
    async with connect() as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (uid,)) as c:
            invited = (await c.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(amount),0) FROM referral_rewards WHERE referrer_id=?", (uid,)) as c:
            earned = (await c.fetchone())[0]
    return invited, earned


async def apply_referral_reward(order_id, buyer_id, amount_rub):
    async with connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute("SELECT referrer_id FROM users WHERE id=?", (buyer_id,)) as c:
            row = await c.fetchone()
        if not row or not row[0] or row[0] == buyer_id:
            await db.commit(); return 0.0
        async with db.execute("SELECT 1 FROM referral_rewards WHERE order_id=?", (order_id,)) as c:
            if await c.fetchone():
                await db.commit(); return 0.0
        # Процент можно менять в админке («Переменные»); config держит актуальное значение.
        try: percent = float(config.REFERRAL_PERCENT)
        except (TypeError, ValueError): percent = 5.0
        reward = round(max(0, amount_rub) * min(max(percent, 0), 50) / 100, 2)
        if reward:
            await db.execute("UPDATE users SET balance=balance+? WHERE id=?", (reward, row[0]))
            await db.execute("INSERT INTO referral_rewards VALUES(?,?,?,?,?)", (order_id,row[0],buyer_id,reward,now()))
        await db.commit()
        return reward


async def finish_paid_order(oid, user_id):
    """Атомарно закрывает заказ как оплаченный.

    - Для товарного заказа: проверяет и уменьшает остаток, ставит статус paid.
    - Для пополнения (product_id == 0): зачисляет баланс в той же транзакции.
    Повторный вызов ничего не меняет (идемпотентно).
    Возвращает (order, changed).
    """
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (oid,user_id)) as c:
            order = await c.fetchone()
        if not order or order['status'] in FINAL_STATUSES:
            await db.rollback(); return order, False
        if order['product_id']:
            async with db.execute("SELECT stock FROM products WHERE id=?", (order['product_id'],)) as c:
                product = await c.fetchone()
            if not product or product['stock'] < 1:
                await db.rollback(); return order, False
            await db.execute("UPDATE products SET stock=stock-1 WHERE id=? AND stock>0", (order['product_id'],))
        elif order['product_id'] == 0:
            # Пополнение баланса — начисляем в той же транзакции, чтобы
            # оплата не потерялась при сбое между шагами.
            await db.execute("UPDATE users SET balance=balance+? WHERE id=?", (order['amount_rub'] or 0, user_id))
        await db.execute("UPDATE orders SET status='paid',updated_at=? WHERE id=?", (now(),oid))
        await db.commit()
    if order["product_id"]:
        await apply_referral_reward(oid, user_id, order["amount_rub"])
    return order, True


# --- products ---
async def add_product(name, desc, price, cat, stock, photo=None):
    async with connect() as db:
        await db.execute(
            "INSERT INTO products (name,description,price_usd,category,stock,photo_id,created_at) VALUES (?,?,?,?,?,?,?)",
            (name, desc, price, cat, stock, photo, now()),
        )
        await db.commit()


async def get_product(pid):
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM products WHERE id=?", (pid,)) as c:
            return await c.fetchone()


async def get_products(cat=None):
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        if cat and cat != "all":
            q = "SELECT * FROM products WHERE is_active=1 AND category=? ORDER BY id DESC"
            args = (cat,)
        else:
            q = "SELECT * FROM products WHERE is_active=1 ORDER BY id DESC"
            args = ()
        async with db.execute(q, args) as c:
            return await c.fetchall()


async def get_all_products():
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM products ORDER BY id DESC") as c:
            return await c.fetchall()


async def set_stock(pid, stock):
    async with connect() as db:
        await db.execute("UPDATE products SET stock=? WHERE id=?", (stock, pid))
        await db.commit()


async def toggle_product(pid):
    async with connect() as db:
        await db.execute("UPDATE products SET is_active=1-is_active WHERE id=?", (pid,))
        await db.commit()


async def del_product(pid):
    async with connect() as db:
        await db.execute("DELETE FROM products WHERE id=?", (pid,))
        await db.commit()


# --- orders ---
async def create_order(uid, pid, pname, usd, rub, ton, method, track, status="awaiting_payment"):
    async with connect() as db:
        cur = await db.execute(
            """INSERT INTO orders
            (user_id,product_id,product_name,amount_usd,amount_rub,amount_ton,
             payment_method,status,track,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (uid, pid, pname, usd, rub, ton, method, status, track, now(), now()),
        )
        await db.commit()
        return cur.lastrowid


async def get_order(oid):
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM orders WHERE id=?", (oid,)) as c:
            return await c.fetchone()


async def get_user_orders(uid):
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,)
        ) as c:
            return await c.fetchall()


async def get_all_orders():
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 100") as c:
            return await c.fetchall()


async def set_order_status(oid, status):
    async with connect() as db:
        await db.execute("UPDATE orders SET status=?,updated_at=? WHERE id=?", (status, now(), oid))
        await db.commit()


async def set_order_screenshot(oid, fid):
    async with connect() as db:
        await db.execute(
            "UPDATE orders SET screenshot_id=?,status='on_review',updated_at=? WHERE id=?",
            (fid, now(), oid),
        )
        await db.commit()


async def set_order_field(oid, field, value):
    if field not in _ORDER_FIELDS:
        raise ValueError(f"Недопустимое поле заказа: {field}")
    async with connect() as db:
        await db.execute(f"UPDATE orders SET {field}=? WHERE id=?", (value, oid))
        await db.commit()


async def stats():
    """Статистика для админки и ежедневных логов.

    Пополнения (product_id == 0) не считаются заказами и выручкой —
    они учитываются отдельно, иначе цифры завышаются.
    """
    async with connect() as db:
        async with db.execute(
            "SELECT COUNT(*),COALESCE(SUM(amount_usd),0) FROM orders "
            "WHERE status IN ('paid','issued','completed') AND product_id IS NOT NULL AND product_id != 0"
        ) as c:
            row = await c.fetchone()
        async with db.execute("SELECT COUNT(*) FROM orders WHERE status='awaiting_payment'") as c:
            pending = (await c.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM orders WHERE date(created_at)=date('now') AND product_id IS NOT NULL AND product_id != 0"
        ) as c:
            today = (await c.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*),COALESCE(SUM(amount_rub),0) FROM orders "
            "WHERE status IN ('paid','issued','completed') AND product_id IS NOT NULL AND product_id != 0 "
            "AND date(updated_at)=date('now')"
        ) as c:
            paid_today, revenue_today_rub = await c.fetchone()
        async with db.execute(
            "SELECT COUNT(*),COALESCE(SUM(amount_rub),0) FROM orders "
            "WHERE product_id=0 AND status IN ('paid','issued','completed') AND date(updated_at)=date('now')"
        ) as c:
            topups_today, topup_rub_today = await c.fetchone()
        async with db.execute("SELECT COUNT(*) FROM users WHERE date(reg_date)=date('now')") as c:
            new_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM products WHERE is_active=1 AND stock>0") as c:
            available = (await c.fetchone())[0]
        return {
            "orders": row[0], "revenue": row[1], "pending": pending,
            "today": today, "new_users": new_users, "available": available,
            "paid_today": paid_today, "revenue_today_rub": revenue_today_rub,
            "topups_today": topups_today, "topup_rub_today": topup_rub_today,
        }


async def cancel_stale_orders(hours) -> list:
    """Отменяет заказы, висящие 'awaiting_payment' дольше hours часов.

    Возвращает список отменённых заказов (id, user_id, product_name, amount_rub).
    """
    async with connect() as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("BEGIN IMMEDIATE")
        async with conn.execute(
            "SELECT id, user_id, product_name, amount_rub FROM orders "
            "WHERE status='awaiting_payment' AND created_at <= datetime('now', ?)",
            (f"-{int(hours)} hours",),
        ) as cur:
            rows = await cur.fetchall()
        for r in rows:
            await conn.execute(
                "UPDATE orders SET status='cancelled',updated_at=? WHERE id=?",
                (now(), r["id"]),
            )
        await conn.commit()
        return [dict(r) for r in rows]


async def get_last_topup(uid):
    """Последнее подтверждённое пополнение баланса юзера (для пометки при покупке)."""
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT amount_rub, payment_method FROM orders "
            "WHERE user_id=? AND product_id=0 AND status IN ('paid','issued','completed') "
            "ORDER BY updated_at DESC LIMIT 1",
            (uid,),
        ) as c:
            return await c.fetchone()


async def top_products(limit=3):
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT product_name, COUNT(*) AS c FROM orders "
            "WHERE status IN ('paid','issued','completed') AND product_id IS NOT NULL AND product_id != 0 "
            "GROUP BY product_name ORDER BY c DESC LIMIT ?",
            (limit,),
        ) as c:
            return await c.fetchall()


# --- promo ---
async def create_promo(code, amount, uses):
    async with connect() as db:
        await db.execute(
            "INSERT OR REPLACE INTO promocodes (code,amount,uses_left,is_active,created_at) VALUES (?,?,?,1,?)",
            (code.upper(), amount, uses, now()),
        )
        await db.commit()


async def get_promo(code):
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM promocodes WHERE code=?", (code.upper(),)) as c:
            return await c.fetchone()


async def use_promo(code) -> bool:
    """Списывает одну активацию. Защита от гонки: только если uses_left > 0."""
    async with connect() as db:
        cur = await db.execute(
            "UPDATE promocodes SET uses_left=uses_left-1 WHERE code=? AND is_active=1 AND uses_left>0",
            (code.upper(),),
        )
        await db.commit()
        return cur.rowcount > 0


async def log_promo(uid, code):
    async with connect() as db:
        await db.execute(
            "INSERT INTO promo_uses (user_id,code,used_at) VALUES (?,?,?)",
            (uid, code.upper(), now()),
        )
        await db.commit()


async def user_used_promo(uid, code):
    async with connect() as db:
        async with db.execute(
            "SELECT 1 FROM promo_uses WHERE user_id=? AND code=?", (uid, code.upper())
        ) as c:
            return await c.fetchone() is not None


# --- settings ---
async def get_setting(key, default=None):
    async with connect() as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as c:
            row = await c.fetchone()
            return row[0] if row else default


async def set_setting(key, value):
    async with connect() as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        await db.commit()


async def del_setting(key):
    async with connect() as db:
        await db.execute("DELETE FROM settings WHERE key=?", (key,))
        await db.commit()


# --- поддержка / отзывы ---
async def create_ticket(uid, body) -> int:
    async with connect() as db:
        cur = await db.execute(
            "INSERT INTO support_tickets(user_id,message,created_at) VALUES(?,?,?)",
            (uid, body[:3500], now()),
        )
        await db.commit()
        return cur.lastrowid


async def get_ticket(tid):
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM support_tickets WHERE id=?", (tid,)) as c:
            return await c.fetchone()


async def set_ticket_status(tid, status):
    async with connect() as db:
        await db.execute("UPDATE support_tickets SET status=? WHERE id=?", (status, tid))
        await db.commit()


async def review_exists(oid) -> bool:
    async with connect() as db:
        async with db.execute("SELECT 1 FROM reviews WHERE order_id=?", (oid,)) as c:
            return await c.fetchone() is not None


async def add_review(uid, oid, product_id, rating, comment) -> bool:
    try:
        async with connect() as db:
            await db.execute(
                "INSERT INTO reviews(user_id,order_id,product_id,rating,comment,created_at) VALUES(?,?,?,?,?,?)",
                (uid, oid, product_id, rating, comment, now()),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


# --- корзина ---
async def cart_add(uid, pid):
    async with connect() as db:
        await db.execute(
            "INSERT INTO cart_items(user_id,product_id,quantity) VALUES(?,?,1) "
            "ON CONFLICT(user_id,product_id) DO UPDATE SET quantity=quantity+1",
            (uid, pid),
        )
        await db.commit()


async def cart_get(uid):
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT c.product_id,c.quantity,p.name,p.price_usd,p.stock,p.is_active "
            "FROM cart_items c JOIN products p ON p.id=c.product_id "
            "WHERE c.user_id=? ORDER BY p.id",
            (uid,),
        ) as cur:
            return await cur.fetchall()


async def cart_remove(uid, pid):
    async with connect() as db:
        await db.execute("DELETE FROM cart_items WHERE user_id=? AND product_id=?", (uid,pid))
        await db.commit()


async def cart_clear(uid):
    async with connect() as db:
        await db.execute("DELETE FROM cart_items WHERE user_id=?", (uid,))
        await db.commit()
