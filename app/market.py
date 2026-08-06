"""SQLite-backed, news-driven educational stock market engine."""
from __future__ import annotations

import hashlib
import hmac
import json
import random
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
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
PASSWORD_HASH_ITERATIONS = 210_000
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
USERNAME_PATTERN = re.compile(r"^[0-9A-Za-z가-힣_-]+$")

STOCKS = (
    ("005930", "삼성전자", "반도체", 84_000),
    ("000100", "유한양행", "제약", 120_000),
    ("035420", "NAVER", "인터넷", 192_000),
    ("105560", "KB금융", "금융", 84_000),
    ("005380", "현대차", "자동차", 247_000),
    ("051910", "LG화학", "화학", 318_000),
)

RANDOM_NEWS_SCENARIOS = (
    (
        ("005930",), "negative", "글로벌 메모리 시장 전망, 보수적 시각 늘어",
        "주요 조사기관들이 PC와 모바일 수요 회복 시점을 늦춰 잡고 있다. 현물 가격도 최근 좁은 범위에서 약세를 보였다.",
    ),
    (
        ("005930",), "positive", "북미 클라우드 업체, AI 서버 투자 일정 앞당겨",
        "일부 대형 클라우드 사업자가 하반기 서버 발주를 예정보다 일찍 시작했다. 고대역폭 메모리 수요에도 영향을 줄 수 있다.",
    ),
    (
        ("005930",), "negative", "대만 파운드리 업체, 2나노 투자 일정 앞당겨",
        "경쟁사의 선단 공정 증설 계획이 구체화됐다. 글로벌 대형 고객사를 둘러싼 수주 경쟁이 한층 거세질 전망이다.",
    ),
    (
        ("000100",), "positive", "유한양행, 신약 기술수출 계약 확대 기대",
        "후속 임상과 허가 절차가 진전되면서 단계별 기술료와 해외 판매 수익에 대한 기대가 커지고 있다.",
    ),
    (
        ("000100",), "negative", "신약 후보물질 임상 일정 일부 지연",
        "시험 대상자 모집과 데이터 검토에 예상보다 시간이 걸리면서 주요 임상 결과 발표 일정이 늦춰질 가능성이 제기됐다.",
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
        ("035420", "105560"), "negative", "내수 경기 둔화, 소비와 금융 수요 동반 위축",
        "소비 심리가 약해지면서 온라인 거래와 가계 금융상품 수요가 함께 둔화될 수 있다는 전망이 나왔다.",
    ),
    (
        ("035420", "105560"), "positive", "국내 소비심리 회복, 온라인 거래와 카드 이용 증가",
        "온라인 쇼핑 거래액과 카드 승인액이 함께 늘면서 플랫폼 거래와 금융 수수료 수익 개선 기대가 커지고 있다.",
    ),
    (
        ("035420",), "negative", "생성형 검색 서비스 이용 시간 빠르게 증가",
        "사용자가 기존 검색 포털 대신 대화형 검색으로 정보를 찾는 비중이 늘고 있다. 검색 광고 시장에도 변화가 예상된다.",
    ),
    (
        ("105560",), "positive", "KB금융, 주주환원 확대 계획 발표",
        "자사주 매입과 소각을 포함한 추가 주주환원 계획이 발표되며 자본 효율성과 배당 확대 기대가 높아졌다.",
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
        ("005930", "005380", "051910"), "positive", "원·달러 환율, 수출기업에 유리한 구간 진입",
        "원화 약세가 이어지면서 해외 매출의 원화 환산 효과가 커지고 있다. 다만 수입 원가 부담도 함께 확인할 필요가 있다.",
    ),
    (
        ("005380", "051910"), "negative", "글로벌 전기차 수요 전망 하향",
        "주요 시장의 전기차 판매 전망이 낮아지며 완성차와 배터리 소재 업종의 단기 수요 우려가 커지고 있다.",
    ),
    (
        ("005930",), "positive", "삼성전자, 글로벌 반도체 기업과 파운드리 공급 계약",
        "첨단 공정 기반의 장기 공급 계약이 체결됐다는 소식에 파운드리 가동률과 수익성 개선 기대가 높아지고 있다.",
    ),
    (
        ("005930",), "negative", "스마트폰 부품 품질 점검 확대, 출하 일정 변수",
        "일부 부품의 추가 품질 검사가 진행되면서 신제품 출하 일정과 관련 비용에 대한 불확실성이 커졌다.",
    ),
    (
        ("000100",), "positive", "유한양행 신약, 미국 우선심사 대상 지정",
        "주요 신약 후보가 우선심사 대상으로 지정되며 허가 일정 단축과 해외 시장 진출에 대한 기대가 높아졌다.",
    ),
    (
        ("000100",), "negative", "핵심 의약품 특허 분쟁 장기화 가능성",
        "해외 제약사와의 특허 분쟁에서 추가 심리가 결정되며 법률 비용과 출시 일정의 불확실성이 확대됐다.",
    ),
    (
        ("035420",), "positive", "검색 광고 단가 회복, 신규 광고주 유입 증가",
        "중소형 광고주의 집행이 늘고 주요 검색어 광고 단가도 회복되면서 광고 매출 개선 가능성이 제기됐다.",
    ),
    (
        ("105560",), "negative", "가계대출 연체율 상승, 충당금 부담 확대 우려",
        "취약 차주의 연체율이 오르면서 대손충당금 적립과 은행 수익성에 대한 우려가 확대됐다.",
    ),
    (
        ("005380",), "negative", "완성차 생산라인 부분 파업 예고",
        "노사 협상 결렬로 일부 생산라인의 부분 파업이 예고되면서 단기 생산 차질 가능성이 부각됐다.",
    ),
    (
        ("005380",), "positive", "북미 전기차 공장, 현지 보조금 요건 충족",
        "현지 생산 비율과 배터리 조달 기준을 충족하며 북미 판매 차량의 세액공제 적용 기대가 높아졌다.",
    ),
    (
        ("051910",), "positive", "LG화학, 유럽 완성차 업체와 양극재 장기 공급 계약",
        "대규모 장기 공급 계약으로 배터리 소재 부문의 수주 잔고와 공장 가동률 개선이 기대된다.",
    ),
    (
        ("051910",), "negative", "국제유가 급등, 석유화학 원가 부담 확대",
        "나프타를 비롯한 주요 원재료 가격이 상승하면서 석유화학 제품의 스프레드 축소 우려가 커지고 있다.",
    ),
    (
        ("000100", "051910"), "positive", "정부, 바이오·신약 연구개발 세액공제 확대",
        "신약과 바이오 소재 연구개발에 대한 세제 지원 확대안이 발표되며 관련 기업의 투자 부담 완화가 기대된다.",
    ),
    (
        ("005380", "051910"), "positive", "주요국, 전기차 구매 보조금 확대 합의",
        "전기차 수요 회복을 위해 구매 지원을 늘리기로 하면서 완성차와 배터리 소재 업종의 동반 수혜가 예상된다.",
    ),
    (
        ("005930", "005380", "051910"), "negative", "글로벌 해상운임 급등, 수출기업 물류비 부담",
        "주요 항로의 운임과 보험료가 동시에 상승하면서 해외 매출 비중이 높은 제조업체의 비용 부담이 커지고 있다.",
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
                        buy_volume INTEGER NOT NULL DEFAULT 0,
                        sell_volume INTEGER NOT NULL DEFAULT 0,
                        volume INTEGER NOT NULL DEFAULT 0,
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
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL,
                        username_key TEXT NOT NULL UNIQUE,
                        password_salt BLOB NOT NULL,
                        password_hash BLOB NOT NULL,
                        created_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS sessions (
                        token_hash TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        created_at REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_sessions_user_id
                        ON sessions(user_id);
                    """
                )
                news_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(news)").fetchall()
                }
                if "target_tickers" not in news_columns:
                    conn.execute("ALTER TABLE news ADD COLUMN target_tickers TEXT")
                conn.execute(
                    """UPDATE news SET target_tickers =
                       CASE WHEN ticker IS NULL THEN '[]' ELSE json_array(ticker) END
                       WHERE target_tickers IS NULL"""
                )
                history_columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(price_history)").fetchall()
                }
                for column in ("buy_volume", "sell_volume", "volume"):
                    if column not in history_columns:
                        conn.execute(
                            f"ALTER TABLE price_history ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
                        )
                # Older price records predate virtual volume. Reconstruct a flow that
                # follows the recorded direction and magnitude so the 60-point chart
                # does not contain misleading zero-volume candles.
                zero_volume_rows = conn.execute(
                    """SELECT id, price, change_pct, event_type FROM price_history
                       WHERE volume = 0"""
                ).fetchall()
                for history_row in zero_volume_rows:
                    price = max(1, int(history_row[1]))
                    change_pct = float(history_row[2] or 0)
                    activity = 5.0 if history_row[3] == "news" else (
                        0.8 + min(1.0, abs(change_pct) / 7.0) * 1.2
                    )
                    volume = max(100, int((4_000_000_000 / price) * activity))
                    imbalance = min(0.9, abs(change_pct) / 7.0 * 0.68)
                    if change_pct < 0:
                        imbalance *= -1
                    buy_volume = int(round(volume * (1 + imbalance) / 2))
                    conn.execute(
                        """UPDATE price_history
                           SET buy_volume = ?, sell_volume = ?, volume = ? WHERE id = ?""",
                        (buy_volume, volume - buy_volume, volume, history_row[0]),
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
                legacy_stock = conn.execute(
                    "SELECT price FROM market_state WHERE ticker = ?", ("000660",)
                ).fetchone()
                if legacy_stock:
                    legacy_price = max(1, int(legacy_stock[0]))
                    conn.execute(
                        """UPDATE positions SET ticker = ?, avg_price = avg_price * ? / ?
                           WHERE ticker = ?""",
                        ("000100", 120_000, legacy_price, "000660"),
                    )
                    conn.execute(
                        "UPDATE trades SET ticker = ? WHERE ticker = ?",
                        ("000100", "000660"),
                    )
                    conn.execute("DELETE FROM price_history WHERE ticker = ?", ("000660",))
                    conn.execute(
                        "UPDATE news SET ticker = NULL WHERE ticker = ?", ("000660",)
                    )
                    conn.execute("DELETE FROM market_state WHERE ticker = ?", ("000660",))
                legacy_kakao = conn.execute(
                    "SELECT price FROM market_state WHERE ticker = ?", ("035720",)
                ).fetchone()
                if legacy_kakao:
                    legacy_price = max(1, int(legacy_kakao[0]))
                    conn.execute(
                        """UPDATE positions SET ticker = ?, avg_price = avg_price * ? / ?
                           WHERE ticker = ?""",
                        ("105560", 84_000, legacy_price, "035720"),
                    )
                    conn.execute(
                        "UPDATE trades SET ticker = ? WHERE ticker = ?",
                        ("105560", "035720"),
                    )
                    conn.execute("DELETE FROM price_history WHERE ticker = ?", ("035720",))
                    conn.execute(
                        "UPDATE news SET ticker = ? WHERE ticker = ?",
                        ("105560", "035720"),
                    )
                    conn.execute(
                        "UPDATE news SET target_tickers = REPLACE(target_tickers, ?, ?)",
                        (json.dumps("035720"), json.dumps("105560")),
                    )
                    conn.execute("DELETE FROM market_state WHERE ticker = ?", ("035720",))
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
                               (ticker, price, change_pct, buy_volume, sell_volume, volume,
                                event_type, created_at)
                               VALUES (?, ?, 0, ?, ?, ?, 'initial', ?)""",
                            (ticker, price, int(2_000_000_000 / price),
                             int(2_000_000_000 / price), int(4_000_000_000 / price), now),
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

    def _virtual_flow(self, price: int, *, news_impact: float | None = None) -> tuple[int, int, float]:
        """Generate aggregate order flow and derive its price pressure."""
        baseline_volume = max(100, int((4_000_000_000 / price) * self.rng.uniform(0.85, 1.15)))
        if news_impact is None:
            activity = self.rng.uniform(0.65, 2.1)
            imbalance = self.rng.uniform(0.08, 0.68)
            if self.rng.random() < 0.5:
                imbalance *= -1
            total_volume = max(1, int(baseline_volume * activity))
            pressure = imbalance * 0.065 * (activity ** 0.5)
            magnitude = min(BASE_CHANGE_MAX, max(BASE_CHANGE_MIN, abs(pressure)))
            change = magnitude if pressure >= 0 else -magnitude
        else:
            activity = self.rng.uniform(4.5, 8.5)
            imbalance = self.rng.uniform(0.72, 0.92)
            if news_impact < 0:
                imbalance *= -1
            total_volume = max(1, int(baseline_volume * activity))
            change = news_impact / 100
        buy_volume = max(0, int(round(total_volume * (1 + imbalance) / 2)))
        sell_volume = max(0, total_volume - buy_volume)
        return buy_volume, sell_volume, change

    def _apply_news_event(self, conn: sqlite3.Connection, event: sqlite3.Row, now: float) -> None:
        target_tickers = json.loads(event["target_tickers"] or "[]")
        if target_tickers:
            placeholders = ",".join("?" for _ in target_tickers)
            targets = conn.execute(
                f"SELECT ticker, price FROM market_state WHERE ticker IN ({placeholders})",
                target_tickers,
            ).fetchall()
        else:
            targets = conn.execute("SELECT ticker, price FROM market_state").fetchall()
        for target in targets:
            old_price = int(target["price"])
            buy_volume, sell_volume, requested_change = self._virtual_flow(
                old_price, news_impact=float(event["impact_pct"])
            )
            new_price = _round_price(old_price * (1 + requested_change))
            actual_change = (new_price / old_price - 1) * 100
            conn.execute(
                """UPDATE market_state SET previous_price = price, price = ?, updated_at = ?
                   WHERE ticker = ?""",
                (new_price, event["effective_at"], target["ticker"]),
            )
            conn.execute(
                """INSERT INTO price_history
                   (ticker, price, change_pct, buy_volume, sell_volume, volume,
                    event_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'news', ?)""",
                (target["ticker"], new_price, actual_change, buy_volume, sell_volume,
                 buy_volume + sell_volume, event["effective_at"]),
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
        ticker = tickers[0]
        magnitude = self.rng.uniform(
            RANDOM_NEWS_CHANGE_MIN, RANDOM_NEWS_CHANGE_MAX
        )
        signed_impact = magnitude if sentiment == "positive" else -magnitude
        conn.execute(
            """INSERT INTO news
               (title, content, sentiment, ticker, target_tickers, impact_pct, published_at,
                effective_at, applied_at, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'random')""",
            (
                title, content, sentiment, ticker, json.dumps(tickers),
                round(signed_impact, 2), now, now + NEWS_EFFECT_DELAY_SECONDS,
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
            """SELECT id, ticker, target_tickers, impact_pct, effective_at FROM news
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
                old_price = int(stock["price"])
                buy_volume, sell_volume, requested_change = self._virtual_flow(old_price)
                new_price = _round_price(old_price * (1 + requested_change))
                actual_change = ((new_price / old_price) - 1) * 100
                conn.execute(
                    """UPDATE market_state SET previous_price = price, price = ?, updated_at = ?
                       WHERE ticker = ?""",
                    (new_price, event_at, stock["ticker"]),
                )
                conn.execute(
                    """INSERT INTO price_history
                       (ticker, price, change_pct, buy_volume, sell_volume, volume,
                        event_type, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'tick', ?)""",
                    (stock["ticker"], new_price, actual_change, buy_volume, sell_volume,
                     buy_volume + sell_volume, event_at),
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

    @staticmethod
    def _normalize_username(username: str) -> tuple[str, str]:
        display = unicodedata.normalize("NFKC", username).strip()
        if not 2 <= len(display) <= 20 or not USERNAME_PATTERN.fullmatch(display):
            raise MarketError(422, "아이디는 한글, 영문, 숫자, _, - 조합으로 2~20자여야 합니다.")
        return display, display.casefold()

    @staticmethod
    def _password_hash(password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
        )

    @staticmethod
    def _validate_password(password: str) -> None:
        if not 4 <= len(password) <= 64:
            raise MarketError(422, "비밀번호는 4~64자로 입력하세요.")

    @staticmethod
    def account_id_for_user(user_id: int) -> str:
        return f"member_{user_id}"

    @staticmethod
    def _session_token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _public_user(row: sqlite3.Row) -> dict:
        return {"id": int(row["id"]), "username": row["username"]}

    def _create_session(self, conn: sqlite3.Connection, user_id: int, now: float) -> str:
        token = secrets.token_urlsafe(32)
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute(
            """INSERT INTO sessions(token_hash, user_id, created_at, expires_at)
               VALUES (?, ?, ?, ?)""",
            (
                self._session_token_hash(token), user_id, now,
                now + SESSION_MAX_AGE_SECONDS,
            ),
        )
        return token

    def register_user(self, username: str, password: str) -> tuple[dict, str]:
        display, username_key = self._normalize_username(username)
        self._validate_password(password)
        now = time.time()
        salt = secrets.token_bytes(16)
        password_hash = self._password_hash(password, salt)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = conn.execute(
                    """INSERT INTO users
                       (username, username_key, password_salt, password_hash, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (display, username_key, salt, password_hash, now),
                )
            except sqlite3.IntegrityError as exc:
                raise MarketError(409, "이미 사용 중인 아이디입니다.") from exc
            user_id = int(cursor.lastrowid)
            self._ensure_account(conn, self.account_id_for_user(user_id), now)
            token = self._create_session(conn, user_id, now)
            row = conn.execute(
                "SELECT id, username FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            conn.commit()
        return self._public_user(row), token

    def login_user(self, username: str, password: str) -> tuple[dict, str]:
        _, username_key = self._normalize_username(username)
        self._validate_password(password)
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT id, username, password_salt, password_hash
                   FROM users WHERE username_key = ?""",
                (username_key,),
            ).fetchone()
            if not row:
                raise MarketError(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
            candidate = self._password_hash(password, bytes(row["password_salt"]))
            if not hmac.compare_digest(candidate, bytes(row["password_hash"])):
                raise MarketError(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
            token = self._create_session(conn, int(row["id"]), now)
            conn.commit()
        return self._public_user(row), token

    def user_for_session(self, token: str | None) -> dict | None:
        if not token:
            return None
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                """SELECT u.id, u.username FROM sessions s
                   JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ? AND s.expires_at > ?""",
                (self._session_token_hash(token), now),
            ).fetchone()
        return self._public_user(row) if row else None

    def logout_user(self, token: str | None) -> None:
        if not token:
            return
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (self._session_token_hash(token),),
            )

    def snapshot(
        self,
        user_id: str,
        ticker: str = "005930",
        history_limit: int = 60,
    ) -> dict:
        self._validate_user_id(user_id)
        history_limit = max(10, min(1200, int(history_limit)))
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            next_tick = self._advance(conn, now)
            self._ensure_account(conn, user_id, now)
            if not conn.execute("SELECT 1 FROM market_state WHERE ticker = ?", (ticker,)).fetchone():
                ticker = STOCKS[0][0]
            stocks = conn.execute("SELECT * FROM market_state ORDER BY ticker").fetchall()
            history = conn.execute(
                """SELECT price, change_pct, buy_volume, sell_volume, volume,
                          event_type, created_at FROM price_history
                   WHERE ticker = ? ORDER BY id DESC LIMIT ?""", (ticker, history_limit)
            ).fetchall()
            latest_flows = {
                row["ticker"]: row for row in conn.execute(
                    """SELECT h.ticker, h.buy_volume, h.sell_volume, h.volume
                       FROM price_history h JOIN (
                         SELECT ticker, MAX(id) AS id FROM price_history GROUP BY ticker
                       ) latest ON latest.id = h.id"""
                ).fetchall()
            }
            news = conn.execute(
                """SELECT n.*, m.name AS stock_name FROM news n
                   LEFT JOIN market_state m ON m.ticker = n.ticker
                   ORDER BY n.id DESC LIMIT 30"""
            ).fetchall()
            stock_names = {row["ticker"]: row["name"] for row in stocks}
            trades = conn.execute(
                """SELECT t.*, m.name FROM trades t JOIN market_state m ON m.ticker = t.ticker
                   WHERE t.user_id = ? ORDER BY t.id DESC""", (user_id,)
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
                "buy_volume": int(latest_flows[row["ticker"]]["buy_volume"]),
                "sell_volume": int(latest_flows[row["ticker"]]["sell_volume"]),
                "volume": int(latest_flows[row["ticker"]]["volume"]),
            } for row in stocks],
            "history": [{
                "price": row["price"], "change_pct": round(row["change_pct"], 2),
                "buy_volume": int(row["buy_volume"]),
                "sell_volume": int(row["sell_volume"]), "volume": int(row["volume"]),
                "event_type": row["event_type"], "created_at": _iso(row["created_at"]),
            } for row in reversed(history)],
            "portfolio": portfolio,
            "news": [{
                "id": row["id"], "title": row["title"], "content": row["content"],
                "sentiment": row["sentiment"], "ticker": row["ticker"],
                "affected_tickers": json.loads(row["target_tickers"] or "[]"),
                "stock_name": (
                    ", ".join(stock_names.get(code, code) for code in json.loads(row["target_tickers"] or "[]"))
                    or "전체 시장"
                ),
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
        if side not in {"buy", "sell"} or quantity < 1:
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
                   (title, content, sentiment, ticker, target_tickers, impact_pct, published_at,
                    effective_at, applied_at, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'manual')""",
                (
                    title.strip(), content.strip(), sentiment, ticker,
                    json.dumps([row["ticker"] for row in targets]) if ticker else "[]",
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

    def sell_all(self, user_id: str) -> dict:
        """Sell every position at the prices captured in one transaction."""
        self._validate_user_id(user_id)
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._advance(conn, now)
            self._ensure_account(conn, user_id, now)
            positions = conn.execute(
                """SELECT p.ticker, p.quantity, m.price
                   FROM positions p JOIN market_state m ON m.ticker = p.ticker
                   WHERE p.user_id = ? AND p.quantity > 0""", (user_id,),
            ).fetchall()
            if not positions:
                raise MarketError(400, "매도할 보유 종목이 없습니다.")
            total = 0
            for position in positions:
                quantity, price = int(position["quantity"]), int(position["price"])
                proceeds = quantity * price
                total += proceeds
                conn.execute(
                    """INSERT INTO trades(user_id, ticker, side, quantity, price, total, executed_at)
                       VALUES (?, ?, 'sell', ?, ?, ?, ?)""",
                    (user_id, position["ticker"], quantity, price, proceeds, now),
                )
            conn.execute("UPDATE accounts SET cash = cash + ? WHERE user_id = ?", (total, user_id))
            conn.execute("DELETE FROM positions WHERE user_id = ?", (user_id,))
            portfolio = self._portfolio(conn, user_id)
            conn.commit()
        return {"message": f"보유 종목 {len(positions)}개를 모두 매도했습니다.",
                "sold_count": len(positions), "total": total, "portfolio": portfolio}

    def randomize_market(self) -> dict:
        """Start every quote from a fresh price near its configured baseline."""
        now = time.time()
        prices = {}
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for ticker, _name, _sector, baseline in STOCKS:
                new_price = _round_price(baseline * self.rng.uniform(0.85, 1.15))
                prices[ticker] = new_price
                conn.execute(
                    """UPDATE market_state SET price = ?, previous_price = ?, open_price = ?, updated_at = ?
                       WHERE ticker = ?""", (new_price, new_price, new_price, now, ticker),
                )
                conn.execute("DELETE FROM price_history WHERE ticker = ?", (ticker,))
                conn.execute(
                    """INSERT INTO price_history
                       (ticker, price, change_pct, buy_volume, sell_volume, volume,
                        event_type, created_at)
                       VALUES (?, ?, 0, ?, ?, ?, 'initial', ?)""",
                    (ticker, new_price, int(2_000_000_000 / new_price),
                     int(2_000_000_000 / new_price), int(4_000_000_000 / new_price), now),
                )
            conn.execute("DELETE FROM news")
            conn.execute("UPDATE market_meta SET value = ? WHERE key = 'last_tick_at'", (str(now),))
            conn.execute("UPDATE market_meta SET value = ? WHERE key = 'next_random_news_at'",
                         (str(now + self.rng.uniform(RANDOM_NEWS_INTERVAL_MIN, RANDOM_NEWS_INTERVAL_MAX)),))
            conn.commit()
        return {"message": "전 종목 가격을 랜덤 초기화했습니다.", "prices": prices}
