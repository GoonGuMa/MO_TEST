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
BASE_CHANGE_MAX = 0.07
NEWS_CHANGE_MIN = 15.0
NEWS_CHANGE_MAX = 25.0
NEWS_EFFECT_DELAY_SECONDS = 60
RANDOM_NEWS_INTERVAL_MIN = 180
RANDOM_NEWS_INTERVAL_MAX = 300
RANDOM_NEWS_INTERVAL_VERSION = "3-5-min-v1"
RANDOM_NEWS_CHANGE_MIN = 7.0
RANDOM_NEWS_CHANGE_MAX = 10.0
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

RANDOM_NEWS_SCENARIOS = (
    (
        ("005930", "000660"), "negative", "글로벌 메모리 시장 전망, 보수적 시각 늘어",
        "주요 조사기관들이 PC와 모바일 수요 회복 시점을 늦춰 잡고 있다. 현물 가격도 최근 좁은 범위에서 약세를 보였다.",
    ),
    (
        ("005930", "000660"), "positive", "북미 클라우드 업체, AI 서버 투자 일정 앞당겨",
        "일부 대형 클라우드 사업자가 하반기 서버 발주를 예정보다 일찍 시작했다. 고대역폭 메모리 수요에도 영향을 줄 수 있다.",
    ),
    (
        ("005930",), "negative", "대만 파운드리 업체, 2나노 투자 일정 앞당겨",
        "경쟁사의 선단 공정 증설 계획이 구체화됐다. 글로벌 대형 고객사를 둘러싼 수주 경쟁이 한층 거세질 전망이다.",
    ),
    (
        ("000660",), "negative", "미국 메모리 업체, 차세대 HBM 인증 진전",
        "경쟁사가 주요 고객사의 품질 검증 단계에서 진전을 보인 것으로 전해졌다. 공급사 다변화 가능성이 시장의 관심을 받고 있다.",
    ),
    (
        ("005380",), "negative", "테슬라, 분기 영업이익 시장 예상 웃돌아",
        "테슬라의 판매량과 수익성이 함께 개선됐다. 북미와 유럽 전기차 시장의 가격 경쟁이 다시 강해질 가능성이 있다.",
    ),
    (
        ("005380",), "positive", "유럽, 하이브리드 규제 적용 유예 검토",
        "유럽 일부 국가가 친환경차 전환 과정에서 하이브리드 차량의 규제 적용을 늦추는 방안을 논의하고 있다.",
    ),
    (
        ("005380",), "negative", "중국 전기차 업체, 유럽 판매망 확대",
        "중국 주요 완성차 업체들이 현지 딜러 계약을 늘리고 있다. 중저가 전기차 시장의 경쟁 구도가 달라질 수 있다는 분석이다.",
    ),
    (
        ("035420", "035720"), "negative", "광고 예산, 포털에서 숏폼으로 이동하는 흐름",
        "소비재 기업들의 신규 광고 집행이 짧은 영상 플랫폼에 집중되고 있다. 검색과 메신저 광고의 성장 속도는 다소 둔화됐다.",
    ),
    (
        ("035420", "035720"), "positive", "국내 온라인 쇼핑 거래액 예상치 상회",
        "최근 온라인 쇼핑과 간편결제 거래가 함께 늘었다. 플랫폼 내 광고와 커머스 거래 활성화 여부가 주목된다.",
    ),
    (
        ("035420",), "negative", "생성형 검색 서비스 이용 시간 빠르게 증가",
        "사용자가 기존 검색 포털 대신 대화형 검색으로 정보를 찾는 비중이 늘고 있다. 검색 광고 시장에도 변화가 예상된다.",
    ),
    (
        ("035720",), "positive", "모바일 콘텐츠 결제액 두 달 연속 증가",
        "웹툰과 음악 등 모바일 콘텐츠 소비가 회복되는 흐름이다. 플랫폼 내 유료 서비스 이용률도 완만하게 높아졌다.",
    ),
    (
        ("051910",), "negative", "리튬 가격 반등, 배터리 원가 변수로 부상",
        "주요 배터리 원료 가격이 최근 저점에서 반등했다. 제품 가격에 비용을 전가하는 시점에 따라 수익성이 달라질 수 있다.",
    ),
    (
        ("051910",), "negative", "완성차 업계, 보급형 LFP 배터리 채택 확대",
        "글로벌 완성차 업체들이 저가 전기차에 LFP 배터리를 적용하는 비중을 늘리고 있다. 고부가 소재 수요 전망이 엇갈린다.",
    ),
    (
        ("051910",), "positive", "중국 양극재 공장, 환경 점검으로 가동 조정",
        "일부 경쟁 업체가 당국 점검으로 생산량을 줄인 것으로 알려졌다. 단기 공급 물량과 제품 가격에 영향을 줄 가능성이 있다.",
    ),
    (
        ("005930", "005380"), "positive", "원·달러 환율, 수출기업에 유리한 구간 진입",
        "원화 약세가 이어지면서 해외 매출의 원화 환산 효과가 커지고 있다. 다만 수입 원가 부담도 함께 확인할 필요가 있다.",
    ),
    (
        ("035420", "035720"), "negative", "미국 장기금리 상승세 재개",
        "글로벌 성장주의 할인율 부담이 다시 커지고 있다. 국내 인터넷 업종의 투자 심리에도 간접적인 영향이 예상된다.",
    ),
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
                        impact_pct REAL NOT NULL, published_at REAL NOT NULL,
                        effective_at REAL NOT NULL, applied_at REAL,
                        source TEXT NOT NULL DEFAULT 'manual'
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
                news_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(news)").fetchall()
                }
                migrated_news_schedule = False
                if "effective_at" not in news_columns:
                    conn.execute("ALTER TABLE news ADD COLUMN effective_at REAL")
                    migrated_news_schedule = True
                if "applied_at" not in news_columns:
                    conn.execute("ALTER TABLE news ADD COLUMN applied_at REAL")
                    migrated_news_schedule = True
                if "source" not in news_columns:
                    conn.execute(
                        "ALTER TABLE news ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'"
                    )
                if migrated_news_schedule:
                    conn.execute(
                        """UPDATE news SET effective_at = published_at,
                           applied_at = published_at
                           WHERE effective_at IS NULL OR applied_at IS NULL"""
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
                conn.execute(
                    """INSERT OR IGNORE INTO market_meta(key, value)
                       VALUES ('next_random_news_at', ?)""",
                    (str(now + self.rng.uniform(
                        RANDOM_NEWS_INTERVAL_MIN, RANDOM_NEWS_INTERVAL_MAX
                    )),),
                )
                scheduled_random_news = conn.execute(
                    "SELECT value FROM market_meta WHERE key = 'next_random_news_at'"
                ).fetchone()
                interval_version = conn.execute(
                    "SELECT value FROM market_meta WHERE key = 'random_news_interval_version'"
                ).fetchone()
                if not interval_version or interval_version[0] != RANDOM_NEWS_INTERVAL_VERSION:
                    conn.execute(
                        """UPDATE market_meta SET value = ?
                           WHERE key = 'next_random_news_at'""",
                        (str(now + self.rng.uniform(
                            RANDOM_NEWS_INTERVAL_MIN, RANDOM_NEWS_INTERVAL_MAX
                        )),),
                    )
                    conn.execute(
                        """INSERT INTO market_meta(key, value)
                           VALUES ('random_news_interval_version', ?)
                           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                        (RANDOM_NEWS_INTERVAL_VERSION,),
                    )
                elif (
                    scheduled_random_news
                    and float(scheduled_random_news[0]) > now + RANDOM_NEWS_INTERVAL_MAX
                ):
                    conn.execute(
                        """UPDATE market_meta SET value = ?
                           WHERE key = 'next_random_news_at'""",
                        (str(now + self.rng.uniform(
                            RANDOM_NEWS_INTERVAL_MIN, RANDOM_NEWS_INTERVAL_MAX
                        )),),
                    )
                conn.commit()
            finally:
                conn.close()
            self._initialized = True

    def _apply_news_event(self, conn: sqlite3.Connection, event: sqlite3.Row, now: float) -> None:
        targets = conn.execute(
            "SELECT ticker, price FROM market_state" + (" WHERE ticker = ?" if event["ticker"] else ""),
            (event["ticker"],) if event["ticker"] else (),
        ).fetchall()
        for target in targets:
            old_price = int(target["price"])
            new_price = _round_price(old_price * (1 + float(event["impact_pct"]) / 100))
            actual_change = (new_price / old_price - 1) * 100
            conn.execute(
                """UPDATE market_state SET previous_price = price, price = ?, updated_at = ?
                   WHERE ticker = ?""",
                (new_price, event["effective_at"], target["ticker"]),
            )
            conn.execute(
                """INSERT INTO price_history
                   (ticker, price, change_pct, event_type, created_at)
                   VALUES (?, ?, ?, 'news', ?)""",
                (target["ticker"], new_price, actual_change, event["effective_at"]),
            )
        conn.execute("UPDATE news SET applied_at = ? WHERE id = ?", (now, event["id"]))

    def _publish_random_news_if_due(self, conn: sqlite3.Connection, now: float) -> None:
        row = conn.execute(
            "SELECT value FROM market_meta WHERE key = 'next_random_news_at'"
        ).fetchone()
        next_news_at = float(row["value"]) if row else now + self.rng.uniform(
            RANDOM_NEWS_INTERVAL_MIN, RANDOM_NEWS_INTERVAL_MAX
        )
        if now < next_news_at:
            return

        tickers, sentiment, title, content = self.rng.choice(
            RANDOM_NEWS_SCENARIOS
        )
        ticker = self.rng.choice(tickers)
        magnitude = self.rng.uniform(
            RANDOM_NEWS_CHANGE_MIN, RANDOM_NEWS_CHANGE_MAX
        )
        signed_impact = magnitude if sentiment == "positive" else -magnitude
        conn.execute(
            """INSERT INTO news
               (title, content, sentiment, ticker, impact_pct, published_at,
                effective_at, applied_at, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'random')""",
            (
                title, content,
                sentiment, ticker, round(signed_impact, 2), now,
                now + NEWS_EFFECT_DELAY_SECONDS,
            ),
        )
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'next_random_news_at'",
            (str(now + self.rng.uniform(
                RANDOM_NEWS_INTERVAL_MIN, RANDOM_NEWS_INTERVAL_MAX
            )),),
        )

    def _advance(self, conn: sqlite3.Connection, now: float) -> float:
        self._publish_random_news_if_due(conn, now)
        row = conn.execute(
            "SELECT value FROM market_meta WHERE key = 'last_tick_at'"
        ).fetchone()
        last_tick = float(row["value"]) if row else now
        elapsed_ticks = max(0, int((now - last_tick) // TICK_SECONDS))
        tick_count = min(elapsed_ticks, MAX_CATCHUP_TICKS)
        if elapsed_ticks > MAX_CATCHUP_TICKS:
            last_tick = now - (MAX_CATCHUP_TICKS * TICK_SECONDS)

        scheduled_events = [
            (last_tick + ((index + 1) * TICK_SECONDS), "tick", None)
            for index in range(tick_count)
        ]
        due_news = conn.execute(
            """SELECT id, ticker, impact_pct, effective_at FROM news
               WHERE applied_at IS NULL AND effective_at <= ?
               ORDER BY effective_at, id""",
            (now,),
        ).fetchall()
        scheduled_events.extend(
            (float(event["effective_at"]), "news", event) for event in due_news
        )

        for event_at, event_type, news_event in sorted(scheduled_events, key=lambda item: item[0]):
            if event_type == "news":
                self._apply_news_event(conn, news_event, now)
                continue
            for stock in conn.execute("SELECT ticker, price FROM market_state").fetchall():
                direction = 1 if self.rng.random() >= 0.5 else -1
                requested_change = direction * self.rng.uniform(BASE_CHANGE_MIN, BASE_CHANGE_MAX)
                old_price = int(stock["price"])
                new_price = _round_price(old_price * (1 + requested_change))
                actual_change = ((new_price / old_price) - 1) * 100
                conn.execute(
                    """UPDATE market_state SET previous_price = price, price = ?, updated_at = ?
                       WHERE ticker = ?""",
                    (new_price, event_at, stock["ticker"]),
                )
                conn.execute(
                    """INSERT INTO price_history
                       (ticker, price, change_pct, event_type, created_at)
                       VALUES (?, ?, ?, 'tick', ?)""",
                    (stock["ticker"], new_price, actual_change, event_at),
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
                "effective_at": _iso(row["effective_at"]),
                "applied_at": _iso(row["applied_at"]) if row["applied_at"] else None,
                "source": row["source"],
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
        effective_at = now + NEWS_EFFECT_DELAY_SECONDS
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._advance(conn, now)
            targets = conn.execute(
                "SELECT ticker FROM market_state" + (" WHERE ticker = ?" if ticker else ""),
                (ticker,) if ticker else (),
            ).fetchall()
            if not targets:
                raise MarketError(404, "존재하지 않는 종목입니다.")
            cursor = conn.execute(
                """INSERT INTO news
                   (title, content, sentiment, ticker, impact_pct, published_at,
                    effective_at, applied_at, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'manual')""",
                (
                    title.strip(), content.strip(), sentiment, ticker,
                    round(signed_impact, 2), now, effective_at,
                ),
            )
            conn.commit()
        return {
            "message": "뉴스가 발행되었습니다. 가격은 1분 뒤 반영됩니다.",
            "news_id": cursor.lastrowid, "impact_pct": round(signed_impact, 2),
            "effective_at": _iso(effective_at),
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
