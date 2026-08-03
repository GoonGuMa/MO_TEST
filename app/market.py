"""SQLite-backed, news-driven educational stock market engine."""
from __future__ import annotations

import random
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


TICK_SECONDS = 15
BASE_CHANGE_MIN = 0.001
BASE_CHANGE_MAX = 0.01
NEWS_CHANGE_MIN = 15.0
NEWS_CHANGE_MAX = 25.0
INITIAL_CASH = 100_000_000
MAX_CATCHUP_TICKS = 240

STOCKS = (
    ("005930", "삼성전자", "반도체", 84_000),
    ("000660", "SK하이닉스", "반도체", 218_000),
    ("035420", "NAVER", "인터넷", 192_000),
    ("035720", "카카오", "인터넷", 46_500),
    ("005380", "현대차", "자동차", 247_000),
    ("051910", "LG화학", "화학", 318_000),
)


class MarketError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _round_price(value: float) -> int:
    return max(1_000, int(round(value / 10.0) * 10))


class MarketEngine:
    def __init__(self, db_path: Path, rng: random.Random | None = None):
        self.db_path = Path(db_path)
        self.rng = rng or random.SystemRandom()
        self._init_lock = threading.Lock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self._initialize()
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def _initialize(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, timeout=10)
            try:
                conn.executescript(
                    """
                    PRAGMA journal_mode = WAL;
                    PRAGMA foreign_keys = ON;
                    CREATE TABLE IF NOT EXISTS market_state (
                        ticker TEXT PRIMARY KEY, name TEXT NOT NULL, sector TEXT NOT NULL,
                        price INTEGER NOT NULL, previous_price INTEGER NOT NULL,
                        open_price INTEGER NOT NULL, updated_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS market_meta (
                        key TEXT PRIMARY KEY, value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS price_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL,
                        price INTEGER NOT NULL, change_pct REAL NOT NULL,
                        event_type TEXT NOT NULL, created_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_price_history_ticker_id
                        ON price_history(ticker, id DESC);
                    CREATE TABLE IF NOT EXISTS news (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                        content TEXT NOT NULL, sentiment TEXT NOT NULL, ticker TEXT,
                        impact_pct REAL NOT NULL, published_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS accounts (
                        user_id TEXT PRIMARY KEY, cash INTEGER NOT NULL,
                        initial_cash INTEGER NOT NULL, created_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS positions (
                        user_id TEXT NOT NULL, ticker TEXT NOT NULL,
                        quantity INTEGER NOT NULL, avg_price REAL NOT NULL,
                        PRIMARY KEY (user_id, ticker),
                        FOREIGN KEY (user_id) REFERENCES accounts(user_id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
                        ticker TEXT NOT NULL, side TEXT NOT NULL, quantity INTEGER NOT NULL,
                        price INTEGER NOT NULL, total INTEGER NOT NULL, executed_at REAL NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES accounts(user_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_trades_user_id ON trades(user_id, id DESC);
                    """
                )
                now = time.time()
                for ticker, name, sector, price in STOCKS:
                    conn.execute(
                        """INSERT OR IGNORE INTO market_state
                           (ticker, name, sector, price, previous_price, open_price, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (ticker, name, sector, price, price, price, now),
                    )
                    if not conn.execute(
                        "SELECT 1 FROM price_history WHERE ticker = ? LIMIT 1", (ticker,)
                    ).fetchone():
                        conn.execute(
                            """INSERT INTO price_history
                               (ticker, price, change_pct, event_type, created_at)
                               VALUES (?, ?, 0, 'initial', ?)""",
                            (ticker, price, now),
                        )
                conn.execute(
                    "INSERT OR IGNORE INTO market_meta(key, value) VALUES ('last_tick_at', ?)",
                    (str(now),),
                )
                conn.commit()
            finally:
                conn.close()
            self._initialized = True

    def _advance(self, conn: sqlite3.Connection, now: float) -> float:
        row = conn.execute(
            "SELECT value FROM market_meta WHERE key = 'last_tick_at'"
        ).fetchone()
        last_tick = float(row["value"]) if row else now
        elapsed_ticks = max(0, int((now - last_tick) // TICK_SECONDS))
        tick_count = min(elapsed_ticks, MAX_CATCHUP_TICKS)
        if not tick_count:
            return max(0.0, TICK_SECONDS - (now - last_tick))
        if elapsed_ticks > MAX_CATCHUP_TICKS:
            last_tick = now - (MAX_CATCHUP_TICKS * TICK_SECONDS)

        for index in range(tick_count):
            tick_at = last_tick + ((index + 1) * TICK_SECONDS)
            for stock in conn.execute("SELECT ticker, price FROM market_state").fetchall():
                direction = 1 if self.rng.random() >= 0.5 else -1
                requested_change = direction * self.rng.uniform(BASE_CHANGE_MIN, BASE_CHANGE_MAX)
                old_price = int(stock["price"])
                new_price = _round_price(old_price * (1 + requested_change))
                actual_change = ((new_price / old_price) - 1) * 100
                conn.execute(
                    """UPDATE market_state SET previous_price = price, price = ?, updated_at = ?
                       WHERE ticker = ?""",
                    (new_price, tick_at, stock["ticker"]),
                )
                conn.execute(
                    """INSERT INTO price_history
                       (ticker, price, change_pct, event_type, created_at)
                       VALUES (?, ?, ?, 'tick', ?)""",
                    (stock["ticker"], new_price, actual_change, tick_at),
                )
        new_last_tick = last_tick + tick_count * TICK_SECONDS
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'last_tick_at'",
            (str(new_last_tick),),
        )
        return max(0.0, TICK_SECONDS - (now - new_last_tick))

    @staticmethod
    def _ensure_account(conn: sqlite3.Connection, user_id: str, now: float) -> None:
        conn.execute(
            """INSERT OR IGNORE INTO accounts(user_id, cash, initial_cash, created_at)
               VALUES (?, ?, ?, ?)""",
            (user_id, INITIAL_CASH, INITIAL_CASH, now),
        )

    @staticmethod
    def _portfolio(conn: sqlite3.Connection, user_id: str) -> dict:
        account = conn.execute(
            "SELECT cash, initial_cash FROM accounts WHERE user_id = ?", (user_id,)
        ).fetchone()
        rows = conn.execute(
            """SELECT p.ticker, m.name, p.quantity, p.avg_price, m.price
               FROM positions p JOIN market_state m ON m.ticker = p.ticker
               WHERE p.user_id = ? AND p.quantity > 0 ORDER BY m.name""",
            (user_id,),
        ).fetchall()
        positions, stock_value = [], 0
        for row in rows:
            market_value = int(row["price"]) * int(row["quantity"])
            cost = float(row["avg_price"]) * int(row["quantity"])
            profit = market_value - cost
            stock_value += market_value
            positions.append({
                "ticker": row["ticker"], "name": row["name"],
                "quantity": row["quantity"], "avg_price": round(row["avg_price"], 2),
                "price": row["price"], "market_value": market_value,
                "profit": round(profit),
                "profit_pct": round(profit / cost * 100, 2) if cost else 0,
            })
        cash, initial = int(account["cash"]), int(account["initial_cash"])
        total = cash + stock_value
        return {
            "user_id": user_id, "cash": cash, "stock_value": stock_value,
            "total_assets": total, "total_profit": total - initial,
            "total_profit_pct": round((total / initial - 1) * 100, 2),
            "positions": positions,
        }

    @staticmethod
    def _validate_user_id(user_id: str) -> None:
        if not (3 <= len(user_id) <= 80) or not all(c.isalnum() or c in "_-" for c in user_id):
            raise MarketError(422, "올바르지 않은 사용자 ID입니다.")

    def snapshot(self, user_id: str, ticker: str = "005930") -> dict:
        self._validate_user_id(user_id)
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            next_tick = self._advance(conn, now)
            self._ensure_account(conn, user_id, now)
            if not conn.execute("SELECT 1 FROM market_state WHERE ticker = ?", (ticker,)).fetchone():
                ticker = STOCKS[0][0]
            stocks = conn.execute("SELECT * FROM market_state ORDER BY ticker").fetchall()
            history = conn.execute(
                """SELECT price, change_pct, event_type, created_at FROM price_history
                   WHERE ticker = ? ORDER BY id DESC LIMIT 60""", (ticker,)
            ).fetchall()
            news = conn.execute(
                """SELECT n.*, m.name AS stock_name FROM news n
                   LEFT JOIN market_state m ON m.ticker = n.ticker
                   ORDER BY n.id DESC LIMIT 30"""
            ).fetchall()
            trades = conn.execute(
                """SELECT t.*, m.name FROM trades t JOIN market_state m ON m.ticker = t.ticker
                   WHERE t.user_id = ? ORDER BY t.id DESC LIMIT 20""", (user_id,)
            ).fetchall()
            portfolio = self._portfolio(conn, user_id)
            conn.commit()
        return {
            "server_time": _iso(now), "tick_seconds": TICK_SECONDS,
            "next_tick_in_seconds": round(next_tick, 1), "selected_ticker": ticker,
            "stocks": [{
                "ticker": row["ticker"], "name": row["name"], "sector": row["sector"],
                "price": row["price"], "previous_price": row["previous_price"],
                "change_pct": round((row["price"] / row["previous_price"] - 1) * 100, 2),
                "total_change_pct": round((row["price"] / row["open_price"] - 1) * 100, 2),
                "updated_at": _iso(row["updated_at"]),
            } for row in stocks],
            "history": [{
                "price": row["price"], "change_pct": round(row["change_pct"], 2),
                "event_type": row["event_type"], "created_at": _iso(row["created_at"]),
            } for row in reversed(history)],
            "portfolio": portfolio,
            "news": [{
                "id": row["id"], "title": row["title"], "content": row["content"],
                "sentiment": row["sentiment"], "ticker": row["ticker"],
                "stock_name": row["stock_name"] or "전체 시장",
                "impact_pct": row["impact_pct"], "published_at": _iso(row["published_at"]),
            } for row in news],
            "trades": [{
                "id": row["id"], "ticker": row["ticker"], "name": row["name"],
                "side": row["side"], "quantity": row["quantity"], "price": row["price"],
                "total": row["total"], "executed_at": _iso(row["executed_at"]),
            } for row in trades],
        }

    def order(self, user_id: str, ticker: str, side: str, quantity: int) -> dict:
        self._validate_user_id(user_id)
        if side not in {"buy", "sell"} or quantity < 1 or quantity > 1_000_000:
            raise MarketError(422, "주문 값이 올바르지 않습니다.")
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._advance(conn, now)
            self._ensure_account(conn, user_id, now)
            stock = conn.execute("SELECT * FROM market_state WHERE ticker = ?", (ticker,)).fetchone()
            if not stock:
                raise MarketError(404, "존재하지 않는 종목입니다.")
            account = conn.execute("SELECT cash FROM accounts WHERE user_id = ?", (user_id,)).fetchone()
            position = conn.execute(
                "SELECT quantity, avg_price FROM positions WHERE user_id = ? AND ticker = ?",
                (user_id, ticker),
            ).fetchone()
            price, total = int(stock["price"]), int(stock["price"]) * quantity
            if side == "buy":
                if int(account["cash"]) < total:
                    raise MarketError(400, "주문 가능 현금이 부족합니다.")
                old_qty = int(position["quantity"]) if position else 0
                old_avg = float(position["avg_price"]) if position else 0
                new_qty = old_qty + quantity
                new_avg = (old_avg * old_qty + total) / new_qty
                conn.execute("UPDATE accounts SET cash = cash - ? WHERE user_id = ?", (total, user_id))
                conn.execute(
                    """INSERT INTO positions(user_id, ticker, quantity, avg_price) VALUES (?, ?, ?, ?)
                       ON CONFLICT(user_id, ticker) DO UPDATE SET
                         quantity = excluded.quantity, avg_price = excluded.avg_price""",
                    (user_id, ticker, new_qty, new_avg),
                )
            else:
                held = int(position["quantity"]) if position else 0
                if held < quantity:
                    raise MarketError(400, "보유 수량이 부족합니다.")
                remaining = held - quantity
                conn.execute("UPDATE accounts SET cash = cash + ? WHERE user_id = ?", (total, user_id))
                if remaining:
                    conn.execute(
                        "UPDATE positions SET quantity = ? WHERE user_id = ? AND ticker = ?",
                        (remaining, user_id, ticker),
                    )
                else:
                    conn.execute("DELETE FROM positions WHERE user_id = ? AND ticker = ?", (user_id, ticker))
            cursor = conn.execute(
                """INSERT INTO trades(user_id, ticker, side, quantity, price, total, executed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, ticker, side, quantity, price, total, now),
            )
            portfolio = self._portfolio(conn, user_id)
            conn.commit()
        return {
            "message": f"{stock['name']} {quantity:,}주 {('매수' if side == 'buy' else '매도')} 체결",
            "trade_id": cursor.lastrowid, "price": price, "total": total,
            "portfolio": portfolio,
        }

    def publish_news(
        self, *, title: str, content: str, sentiment: str,
        ticker: str | None, impact_pct: float | None,
    ) -> dict:
        if sentiment not in {"positive", "negative"}:
            raise MarketError(422, "뉴스 방향이 올바르지 않습니다.")
        magnitude = impact_pct if impact_pct is not None else self.rng.uniform(NEWS_CHANGE_MIN, NEWS_CHANGE_MAX)
        if not NEWS_CHANGE_MIN <= magnitude <= NEWS_CHANGE_MAX:
            raise MarketError(422, "뉴스 영향률은 15~25% 사이여야 합니다.")
        signed_impact = magnitude if sentiment == "positive" else -magnitude
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._advance(conn, now)
            targets = conn.execute(
                "SELECT ticker, price FROM market_state" + (" WHERE ticker = ?" if ticker else ""),
                (ticker,) if ticker else (),
            ).fetchall()
            if not targets:
                raise MarketError(404, "존재하지 않는 종목입니다.")
            for target in targets:
                old_price = int(target["price"])
                new_price = _round_price(old_price * (1 + signed_impact / 100))
                actual_change = (new_price / old_price - 1) * 100
                conn.execute(
                    """UPDATE market_state SET previous_price = price, price = ?, updated_at = ?
                       WHERE ticker = ?""", (new_price, now, target["ticker"]),
                )
                conn.execute(
                    """INSERT INTO price_history(ticker, price, change_pct, event_type, created_at)
                       VALUES (?, ?, ?, 'news', ?)""",
                    (target["ticker"], new_price, actual_change, now),
                )
            cursor = conn.execute(
                """INSERT INTO news(title, content, sentiment, ticker, impact_pct, published_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (title.strip(), content.strip(), sentiment, ticker, round(signed_impact, 2), now),
            )
            conn.commit()
        return {
            "message": "뉴스가 발행되어 가격에 즉시 반영되었습니다.",
            "news_id": cursor.lastrowid, "impact_pct": round(signed_impact, 2),
            "affected_tickers": [row["ticker"] for row in targets],
        }

    def reset_account(self, user_id: str) -> dict:
        self._validate_user_id(user_id)
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_account(conn, user_id, now)
            conn.execute("DELETE FROM trades WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM positions WHERE user_id = ?", (user_id,))
            conn.execute(
                "UPDATE accounts SET cash = ?, initial_cash = ? WHERE user_id = ?",
                (INITIAL_CASH, INITIAL_CASH, user_id),
            )
            portfolio = self._portfolio(conn, user_id)
            conn.commit()
        return {"message": "계좌를 초기화했습니다.", "portfolio": portfolio}
