from __future__ import annotations

import asyncio
import random
import sqlite3
import time
from pathlib import Path

import httpx
import pytest

from app.main import create_app
from app.market import (
    BASE_CHANGE_MAX,
    OVERHEAT_DOWN_PROBABILITY,
    OVERHEAT_THRESHOLD_RATIO,
    OVERHEAT_UP_MULTIPLIER,
    PRICE_CEILING_RATIO,
    PRICE_FLOOR_RATIO,
    RANDOM_NEWS_CHANGE_MAX,
    RANDOM_NEWS_CHANGE_MIN,
    RANDOM_NEWS_INTERVAL_MAX,
    RANDOM_NEWS_INTERVAL_MIN,
    RANDOM_NEWS_SCENARIOS,
    RECOVERY_DOWN_MULTIPLIER,
    RECOVERY_THRESHOLD_RATIO,
    RECOVERY_UP_PROBABILITY,
    STOCKS,
)


@pytest.fixture()
def market_app(tmp_path):
    database = tmp_path / "test-market.sqlite3"
    app = create_app(database)
    app.state.market.rng = random.Random(42)
    return app, database


def request(app, method, path, **kwargs):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(send())


def snapshot(app, ticker="005930", cookies=None):
    response = request(
        app, "GET", "/api/market/snapshot",
        params={"ticker": ticker}, cookies=cookies,
    )
    assert response.status_code == 200
    return response.json()


def register(app, username="student_test", password="pass1234"):
    response = request(app, "POST", "/api/auth/register", json={
        "username": username, "password": password,
    })
    assert response.status_code == 201
    return dict(response.cookies), response.json()["user"]


def stock(data, ticker="005930"):
    return next(item for item in data["stocks"] if item["ticker"] == ticker)


def test_snapshot_creates_account_and_six_stocks(market_app):
    app, _ = market_app
    data = snapshot(app)
    assert len(data["stocks"]) == 6
    assert data["tick_seconds"] == 15
    assert data["portfolio"]["cash"] == 100_000_000
    assert data["portfolio"]["total_assets"] == 100_000_000


def test_snapshot_supports_extended_chart_history_limits(market_app):
    app, database = market_app
    snapshot(app)
    now = time.time()
    with sqlite3.connect(database) as conn:
        conn.executemany(
            """INSERT INTO price_history
               (ticker, price, change_pct, buy_volume, sell_volume, volume,
                event_type, created_at)
               VALUES ('005930', ?, 0.1, 100, 90, 190, 'tick', ?)""",
            [(84_000 + index * 10, now + index) for index in range(150)],
        )
        conn.commit()

    response = request(
        app,
        "GET",
        "/api/market/snapshot",
        params={"ticker": "005930", "history_limit": 100},
    )
    assert response.status_code == 200
    assert len(response.json()["history"]) == 100
    assert request(
        app, "GET", "/api/market/snapshot", params={"history_limit": 1201}
    ).status_code == 422


def test_normal_tick_moves_every_stock_within_configured_range(market_app):
    assert BASE_CHANGE_MAX == 0.07
    app, database = market_app
    before = snapshot(app)
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'last_tick_at'",
            (str(time.time() - 15.2),),
        )
        conn.commit()
    after = snapshot(app)
    for previous in before["stocks"]:
        current = stock(after, previous["ticker"])
        change = abs((current["price"] / previous["price"] - 1) * 100)
        assert 0.09 <= change <= 7.01
        assert current["volume"] == current["buy_volume"] + current["sell_volume"]
        assert current["volume"] > 0
        assert (current["change_pct"] > 0) == (current["buy_volume"] > current["sell_volume"])


class DirectionRng:
    def __init__(self, direction_roll):
        self.direction_roll = direction_roll

    def uniform(self, low, high):
        return (low + high) / 2

    def random(self):
        return self.direction_roll


def test_recovery_mode_favors_gains_and_halves_losses(market_app):
    assert RECOVERY_THRESHOLD_RATIO == 0.60
    assert RECOVERY_UP_PROBABILITY == 0.65
    assert RECOVERY_DOWN_MULTIPLIER == 0.50
    app, _database = market_app
    engine = app.state.market

    engine.rng = DirectionRng(0.64)
    buy_volume, sell_volume, recovery_gain = engine._virtual_flow(
        50_000, recovery_mode=True,
    )
    assert recovery_gain > 0
    assert buy_volume > sell_volume

    engine.rng = DirectionRng(0.66)
    _buy_volume, _sell_volume, recovery_loss = engine._virtual_flow(
        50_000, recovery_mode=True,
    )
    engine.rng = DirectionRng(0.49)
    _buy_volume, _sell_volume, normal_loss = engine._virtual_flow(50_000)
    assert recovery_loss < 0
    assert recovery_loss == pytest.approx(normal_loss * RECOVERY_DOWN_MULTIPLIER)


def test_overheat_mode_favors_losses_and_halves_gains(market_app):
    assert OVERHEAT_THRESHOLD_RATIO == 1.40
    assert OVERHEAT_DOWN_PROBABILITY == 0.65
    assert OVERHEAT_UP_MULTIPLIER == 0.50
    app, _database = market_app
    engine = app.state.market

    engine.rng = DirectionRng(0.64)
    buy_volume, sell_volume, overheat_loss = engine._virtual_flow(
        150_000, overheat_mode=True,
    )
    assert overheat_loss < 0
    assert buy_volume < sell_volume

    engine.rng = DirectionRng(0.66)
    _buy_volume, _sell_volume, overheat_gain = engine._virtual_flow(
        150_000, overheat_mode=True,
    )
    engine.rng = DirectionRng(0.51)
    _buy_volume, _sell_volume, normal_gain = engine._virtual_flow(150_000)
    assert overheat_gain > 0
    assert overheat_gain == pytest.approx(normal_gain * OVERHEAT_UP_MULTIPLIER)


def test_normal_tick_cannot_fall_below_stock_floor(market_app):
    assert PRICE_FLOOR_RATIO == 0.30
    app, database = market_app
    snapshot(app)
    floor = round(84_000 * PRICE_FLOOR_RATIO / 10) * 10
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE market_state SET price = ?, previous_price = ? WHERE ticker = '005930'",
            (floor, floor),
        )
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'last_tick_at'",
            (str(time.time() - 15.2),),
        )
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'next_random_news_at'",
            (str(time.time() + 300),),
        )
        conn.commit()
    app.state.market.rng = DirectionRng(0.99)

    assert stock(snapshot(app))["price"] == floor


def test_normal_tick_cannot_rise_above_stock_ceiling(market_app):
    assert PRICE_CEILING_RATIO == 2.50
    app, database = market_app
    snapshot(app)
    ceiling = round(84_000 * PRICE_CEILING_RATIO / 10) * 10
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE market_state SET price = ?, previous_price = ? WHERE ticker = '005930'",
            (ceiling, ceiling),
        )
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'last_tick_at'",
            (str(time.time() - 15.2),),
        )
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'next_random_news_at'",
            (str(time.time() + 300),),
        )
        conn.commit()
    app.state.market.rng = DirectionRng(0.99)

    assert stock(snapshot(app))["price"] == ceiling


def test_positive_news_applies_twenty_percent_to_selected_stock(market_app):
    app, database = market_app
    old_price = stock(snapshot(app))["price"]
    response = request(app, "POST", "/api/market/news", json={
        "title": "대규모 수주 계약", "content": "예상치를 크게 웃도는 계약입니다.",
        "sentiment": "positive", "ticker": "005930", "impact_pct": 20,
        "admin_key": "",
    })
    assert response.status_code == 200
    assert response.json()["affected_tickers"] == ["005930"]
    with sqlite3.connect(database) as conn:
        published_at, effective_at = conn.execute(
            "SELECT published_at, effective_at FROM news WHERE id = ?",
            (response.json()["news_id"],),
        ).fetchone()
    assert effective_at - published_at == 60
    pending = snapshot(app)
    assert stock(pending)["price"] == old_price
    assert pending["news"][0]["applied_at"] is None
    assert pending["history"][-1]["event_type"] != "news"

    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE news SET effective_at = ? WHERE id = ?",
            (time.time() - 0.1, response.json()["news_id"]),
        )
        conn.commit()
    after = snapshot(app)
    assert stock(after)["price"] == round(old_price * 1.2 / 10) * 10
    assert after["news"][0]["impact_pct"] == 20
    assert after["news"][0]["source"] == "manual"
    assert after["news"][0]["applied_at"] is not None
    assert after["history"][-1]["event_type"] == "news"
    news_flow = after["history"][-1]
    assert news_flow["volume"] == news_flow["buy_volume"] + news_flow["sell_volume"]
    assert news_flow["buy_volume"] > news_flow["sell_volume"]
    assert stock(snapshot(app))["price"] == stock(after)["price"]


def test_negative_news_cannot_break_stock_floor(market_app):
    app, database = market_app
    snapshot(app)
    floor = round(84_000 * PRICE_FLOOR_RATIO / 10) * 10
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE market_state SET price = 26000, previous_price = 26000 "
            "WHERE ticker = '005930'"
        )
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'last_tick_at'",
            (str(time.time()),),
        )
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'next_random_news_at'",
            (str(time.time() + 300),),
        )
        conn.commit()
    response = request(app, "POST", "/api/market/news", json={
        "title": "최저가 검증 뉴스", "content": "가격 하한을 검증합니다.",
        "sentiment": "negative", "ticker": "005930", "impact_pct": 25,
        "admin_key": "",
    })
    assert response.status_code == 200
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE news SET effective_at = ? WHERE id = ?",
            (time.time() - 0.1, response.json()["news_id"]),
        )
        conn.commit()

    after = snapshot(app)
    assert stock(after)["price"] == floor
    assert after["history"][-1]["event_type"] == "news"


def test_positive_news_cannot_break_stock_ceiling(market_app):
    app, database = market_app
    snapshot(app)
    ceiling = round(84_000 * PRICE_CEILING_RATIO / 10) * 10
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE market_state SET price = 205000, previous_price = 205000 "
            "WHERE ticker = '005930'"
        )
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'last_tick_at'",
            (str(time.time()),),
        )
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'next_random_news_at'",
            (str(time.time() + 300),),
        )
        conn.commit()
    response = request(app, "POST", "/api/market/news", json={
        "title": "최고가 검증 뉴스", "content": "가격 상한을 검증합니다.",
        "sentiment": "positive", "ticker": "005930", "impact_pct": 25,
        "admin_key": "",
    })
    assert response.status_code == 200
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE news SET effective_at = ? WHERE id = ?",
            (time.time() - 0.1, response.json()["news_id"]),
        )
        conn.commit()

    after = snapshot(app)
    assert stock(after)["price"] == ceiling
    assert after["history"][-1]["event_type"] == "news"



def test_random_news_catalog_has_requested_size_and_valid_targets():
    valid_tickers = {ticker for ticker, _name, _sector, _price in STOCKS}
    assert len(RANDOM_NEWS_SCENARIOS) == 30
    assert sum(len(tickers) >= 2 for tickers, *_rest in RANDOM_NEWS_SCENARIOS) == 7
    for tickers, sentiment, title, content in RANDOM_NEWS_SCENARIOS:
        assert tickers
        assert set(tickers) <= valid_tickers
        assert len(tickers) == len(set(tickers))
        assert sentiment in {"positive", "negative"}
        assert title.strip()
        assert content.strip()



def test_random_news_uses_its_own_schedule_and_impact_range(market_app):
    app, database = market_app
    before = snapshot(app)
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'next_random_news_at'",
            (str(time.time() - 1),),
        )
        conn.commit()

    pending = snapshot(app)
    event = pending["news"][0]
    assert event["source"] == "random"
    assert RANDOM_NEWS_CHANGE_MIN <= abs(event["impact_pct"]) <= RANDOM_NEWS_CHANGE_MAX
    assert stock(pending, event["ticker"])["price"] == stock(before, event["ticker"])["price"]
    assert event["applied_at"] is None

    with sqlite3.connect(database) as conn:
        published_at, effective_at = conn.execute(
            "SELECT published_at, effective_at FROM news WHERE id = ?", (event["id"],)
        ).fetchone()
        next_random_news_at = float(conn.execute(
            "SELECT value FROM market_meta WHERE key = 'next_random_news_at'"
        ).fetchone()[0])
        conn.execute(
            "UPDATE news SET effective_at = ? WHERE id = ?",
            (time.time() - 0.1, event["id"]),
        )
        conn.commit()
    assert effective_at - published_at == 60
    assert RANDOM_NEWS_INTERVAL_MIN <= next_random_news_at - published_at <= RANDOM_NEWS_INTERVAL_MAX

    applied = snapshot(app, ticker=event["ticker"])
    old_price = stock(before, event["ticker"])["price"]
    expected = round(old_price * (1 + event["impact_pct"] / 100) / 10) * 10
    assert stock(applied, event["ticker"])["price"] == expected
    assert applied["news"][0]["applied_at"] is not None


def test_negative_news_can_affect_entire_market(market_app):
    app, _ = market_app
    response = request(app, "POST", "/api/market/news", json={
        "title": "시장 유동성 위기", "content": "전 종목에 부정적인 충격이 발생했습니다.",
        "sentiment": "negative", "ticker": None, "impact_pct": 15, "admin_key": "",
    })
    assert response.status_code == 200
    assert response.json()["impact_pct"] == -15
    assert len(response.json()["affected_tickers"]) == 6


def test_buy_and_sell_update_cash_and_position(market_app):
    app, _ = market_app
    cookies, _ = register(app)
    price = stock(snapshot(app, cookies=cookies))["price"]
    buy = request(app, "POST", "/api/market/orders", json={
        "ticker": "005930", "side": "buy", "quantity": 10,
    }, cookies=cookies)
    assert buy.status_code == 200
    assert buy.json()["portfolio"]["cash"] == 100_000_000 - price * 10
    assert buy.json()["portfolio"]["positions"][0]["quantity"] == 10
    sell = request(app, "POST", "/api/market/orders", json={
        "ticker": "005930", "side": "sell", "quantity": 4,
    }, cookies=cookies)
    assert sell.status_code == 200
    assert sell.json()["portfolio"]["positions"][0]["quantity"] == 6
    rejected = request(app, "POST", "/api/market/orders", json={
        "ticker": "005930", "side": "sell", "quantity": 7,
    }, cookies=cookies)
    assert rejected.status_code == 400
    assert "보유 수량" in rejected.json()["detail"]


def test_reserved_buy_locks_cash_and_executes_at_the_first_matching_price(market_app):
    app, database = market_app
    cookies, _ = register(app, username="reserved_buyer")
    current_price = stock(snapshot(app, cookies=cookies))["price"]
    target_price = current_price - 1_000

    response = request(app, "POST", "/api/market/reserved-orders", json={
        "ticker": "005930", "side": "buy", "quantity": 10,
        "target_price": target_price,
    }, cookies=cookies)
    assert response.status_code == 201
    assert response.json()["status"] == "pending"

    pending = snapshot(app, cookies=cookies)
    assert pending["reserved_orders"][0]["target_price"] == target_price
    assert pending["portfolio"]["cash"] == 100_000_000
    assert pending["portfolio"]["reserved_cash"] == target_price * 10
    assert pending["portfolio"]["available_cash"] == 100_000_000 - target_price * 10

    execution_price = target_price - 10
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE market_state SET price = ?, previous_price = ? WHERE ticker = '005930'",
            (execution_price, execution_price),
        )
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'last_tick_at'", (str(time.time()),)
        )
        conn.commit()

    executed = snapshot(app, cookies=cookies)
    assert executed["reserved_orders"] == []
    assert executed["trades"][0]["side"] == "buy"
    assert executed["trades"][0]["price"] == execution_price
    assert executed["portfolio"]["positions"][0]["quantity"] == 10
    assert executed["portfolio"]["cash"] == 100_000_000 - execution_price * 10
    assert executed["portfolio"]["reserved_cash"] == 0


def test_reserved_sell_locks_shares_and_can_be_cancelled(market_app):
    app, database = market_app
    cookies, _ = register(app, username="reserved_seller")
    current_price = stock(snapshot(app, cookies=cookies))["price"]
    assert request(app, "POST", "/api/market/orders", json={
        "ticker": "005930", "side": "buy", "quantity": 10,
    }, cookies=cookies).status_code == 200

    reserved = request(app, "POST", "/api/market/reserved-orders", json={
        "ticker": "005930", "side": "sell", "quantity": 7,
        "target_price": current_price + 1_000, "cost_method": "fifo",
    }, cookies=cookies)
    assert reserved.status_code == 201
    assert reserved.json()["status"] == "pending"
    portfolio = reserved.json()["portfolio"]
    assert portfolio["positions"][0]["reserved_quantity"] == 7
    assert portfolio["positions"][0]["available_quantity"] == 3

    rejected = request(app, "POST", "/api/market/orders", json={
        "ticker": "005930", "side": "sell", "quantity": 4,
    }, cookies=cookies)
    assert rejected.status_code == 400

    cancelled = request(
        app, "DELETE", f"/api/market/reserved-orders/{reserved.json()['order_id']}",
        cookies=cookies,
    )
    assert cancelled.status_code == 200
    after = snapshot(app, cookies=cookies)
    assert after["reserved_orders"] == []
    assert after["portfolio"]["positions"][0]["available_quantity"] == 10

    second = request(app, "POST", "/api/market/reserved-orders", json={
        "ticker": "005930", "side": "sell", "quantity": 7,
        "target_price": current_price + 1_000, "cost_method": "fifo",
    }, cookies=cookies)
    assert second.status_code == 201
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE market_state SET price = ?, previous_price = ? WHERE ticker = '005930'",
            (current_price + 1_010, current_price + 1_010),
        )
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'last_tick_at'", (str(time.time()),)
        )
        conn.commit()
    executed = snapshot(app, cookies=cookies)
    assert executed["reserved_orders"] == []
    assert executed["trades"][0]["side"] == "sell"
    assert executed["trades"][0]["quantity"] == 7
    assert executed["trades"][0]["cost_method"] == "fifo"
    assert executed["portfolio"]["positions"][0]["quantity"] == 3


def test_reserved_order_executes_immediately_when_price_already_matches(market_app):
    app, _ = market_app
    cookies, _ = register(app, username="instant_reserved")
    current_price = stock(snapshot(app, cookies=cookies))["price"]
    response = request(app, "POST", "/api/market/reserved-orders", json={
        "ticker": "005930", "side": "buy", "quantity": 2,
        "target_price": current_price,
    }, cookies=cookies)
    assert response.status_code == 201
    assert response.json()["status"] == "executed"
    assert response.json()["trade_id"] is not None
    assert response.json()["portfolio"]["positions"][0]["quantity"] == 2


def test_order_panel_has_separate_immediate_and_reserved_modes():
    root = Path(__file__).parents[1]
    html = (root / "app" / "static" / "index.html").read_text()
    css = (root / "app" / "static" / "styles.css").read_text()
    script = (root / "app" / "static" / "app.js").read_text()
    for mode in ("buy", "sell", "reserved-buy", "reserved-sell"):
        assert f'data-order-mode="{mode}"' in html
    assert 'id="reserve-order-submit"' not in html
    assert ".order-mode-toggle button.active.buy" in css
    assert ".order-mode-toggle button.active.sell" in css
    assert "state.orderType === 'reserved'" in script
    assert "평단가 ${integer.format(Math.round(position.avg_price))}원" in script
    assert 'class="reservation buy"></i>예수' in html
    assert 'class="reservation sell"></i>예도' in html
    assert ".reservation-price-level.buy line" in css
    assert ".reservation-price-level.sell line" in css
    assert "const reservationLines = reservationLevels.map" in script


@pytest.mark.parametrize(
    ("cost_method", "expected_cost", "expected_profit", "remaining_average"),
    (
        ("fifo", 32_000, 7_000, 68_000 / 6),
        ("lifo", 33_000, 6_000, 67_000 / 6),
        ("lofo", 31_000, 8_000, 69_000 / 6),
    ),
)
def test_sell_cost_method_consumes_the_selected_purchase_lots(
    market_app, cost_method, expected_cost, expected_profit, remaining_average,
):
    app, database = market_app
    cookies, _ = register(app, username=f"method_{cost_method}")
    snapshot(app, cookies=cookies)

    for price, quantity in ((10_000, 2), (12_000, 3), (11_000, 4)):
        with sqlite3.connect(database) as conn:
            conn.execute(
                "UPDATE market_state SET price = ?, previous_price = ? WHERE ticker = '005930'",
                (price, price),
            )
            conn.execute(
                "UPDATE market_meta SET value = ? WHERE key = 'last_tick_at'",
                (str(time.time()),),
            )
            conn.commit()
        response = request(app, "POST", "/api/market/orders", json={
            "ticker": "005930", "side": "buy", "quantity": quantity,
        }, cookies=cookies)
        assert response.status_code == 200

    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE market_state SET price = 13000, previous_price = 13000 "
            "WHERE ticker = '005930'"
        )
        conn.execute(
            "UPDATE market_meta SET value = ? WHERE key = 'last_tick_at'",
            (str(time.time()),),
        )
        conn.commit()
    response = request(app, "POST", "/api/market/orders", json={
        "ticker": "005930", "side": "sell", "quantity": 3,
        "cost_method": cost_method,
    }, cookies=cookies)
    assert response.status_code == 200
    result = response.json()
    assert result["cost_method"] == cost_method
    assert result["cost_basis"] == expected_cost
    assert result["realized_profit"] == expected_profit
    assert result["realized_profit_pct"] == round(expected_profit / expected_cost * 100, 2)
    assert result["portfolio"]["positions"][0]["quantity"] == 6
    assert result["portfolio"]["positions"][0]["avg_price"] == round(remaining_average, 2)
    api_lots = result["portfolio"]["positions"][0]["lots"]
    assert sum(lot["remaining_quantity"] for lot in api_lots) == 6
    assert all({"original_quantity", "price", "acquired_at"} <= lot.keys() for lot in api_lots)

    recorded = snapshot(app, cookies=cookies)["trades"][0]
    assert recorded["cost_method"] == cost_method
    assert recorded["cost_basis"] == expected_cost
    assert recorded["realized_profit"] == expected_profit
    with sqlite3.connect(database) as conn:
        lots = conn.execute(
            """SELECT original_quantity, remaining_quantity, price
               FROM position_lots WHERE remaining_quantity > 0 ORDER BY id"""
        ).fetchall()
    assert sum(row[1] for row in lots) == 6


def test_assets_view_is_available_from_the_main_menu():
    html = (Path(__file__).parents[1] / "app" / "static" / "index.html").read_text()
    assert 'data-view-target="assets"' in html
    assert 'id="view-assets"' in html
    assert 'id="asset-chart"' in html
    assert 'id="asset-position-list"' in html


def test_news_admin_key_is_enforced(market_app, monkeypatch):
    app, _ = market_app
    monkeypatch.setenv("MOCK_MARKET_ADMIN_KEY", "class-secret")
    payload = {
        "title": "신제품 판매 호조", "content": "", "sentiment": "positive",
        "ticker": "105560", "impact_pct": 15, "admin_key": "wrong",
    }
    assert request(app, "POST", "/api/market/news", json=payload).status_code == 403
    payload["admin_key"] = "class-secret"
    assert request(app, "POST", "/api/market/news", json=payload).status_code == 200


def test_account_reset_restores_initial_cash(market_app):
    app, _ = market_app
    cookies, _ = register(app)
    request(app, "POST", "/api/market/orders", json={
        "ticker": "005930", "side": "buy", "quantity": 3,
    }, cookies=cookies)
    response = request(app, "POST", "/api/market/accounts/reset", cookies=cookies)
    assert response.status_code == 200
    assert response.json()["portfolio"]["cash"] == 100_000_000
    assert response.json()["portfolio"]["positions"] == []


def test_sell_all_closes_every_position_at_current_prices(market_app):
    app, _ = market_app
    cookies, _ = register(app)
    before = snapshot(app, cookies=cookies)
    for ticker, quantity in (("005930", 3), ("105560", 5)):
        assert request(app, "POST", "/api/market/orders", json={
            "ticker": ticker, "side": "buy", "quantity": quantity,
        }, cookies=cookies).status_code == 200
    response = request(app, "POST", "/api/market/accounts/sell-all", cookies=cookies)
    assert response.status_code == 200
    result = response.json()
    expected = stock(before, "005930")["price"] * 3 + stock(before, "105560")["price"] * 5
    assert result["sold_count"] == 2
    assert result["total"] == expected
    assert result["portfolio"]["positions"] == []
    assert result["portfolio"]["cash"] == 100_000_000
    assert request(app, "POST", "/api/market/accounts/sell-all", cookies=cookies).status_code == 400



def test_news_with_multiple_targets_moves_every_target(market_app):
    app, database = market_app
    before = snapshot(app)
    now = time.time()
    with sqlite3.connect(database) as conn:
        conn.execute(
            """INSERT INTO news
               (title, content, sentiment, ticker, target_tickers, impact_pct,
                published_at, effective_at, applied_at, source)
               VALUES (?, ?, 'positive', ?, ?, 8.0, ?, ?, NULL, 'random')""",
            (
                "원·달러 환율, 수출기업에 유리한 구간 진입",
                "수출 비중이 높은 여러 기업에 긍정적인 환경이다.",
                "005930",
                '["005930", "005380", "051910"]',
                now - 61,
                now - 1,
            ),
        )
        conn.commit()

    after = snapshot(app)
    event = after["news"][0]
    assert event["affected_tickers"] == ["005930", "005380", "051910"]
    assert event["stock_name"] == "삼성전자, 현대차, LG화학"
    for ticker in event["affected_tickers"]:
        assert stock(after, ticker)["price"] > stock(before, ticker)["price"]



def test_randomize_market_resets_quotes_near_baselines_and_keeps_positions(market_app):
    app, database = market_app
    cookies, _ = register(app)
    request(app, "POST", "/api/market/orders", json={
        "ticker": "005930", "side": "buy", "quantity": 2,
    }, cookies=cookies)
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE market_state SET price = price * 20")
        conn.commit()
    request(app, "POST", "/api/market/news", json={
        "title": "초기화 대상 뉴스", "content": "", "sentiment": "positive",
        "ticker": "005930", "impact_pct": 15, "admin_key": "",
    })
    response = request(app, "POST", "/api/market/randomize", cookies=cookies)
    assert response.status_code == 200
    after = snapshot(app, cookies=cookies)
    assert after["news"] == []
    baselines = {"005930": 84_000, "000100": 120_000, "035420": 192_000,
                 "105560": 84_000, "005380": 247_000, "051910": 318_000}
    for item in after["stocks"]:
        assert baselines[item["ticker"]] * .85 <= item["price"] <= baselines[item["ticker"]] * 1.15
        assert item["total_change_pct"] == 0
    assert after["portfolio"]["positions"][0]["quantity"] == 2


def test_auth_register_login_logout_and_duplicate_username(market_app):
    app, database = market_app
    cookies, user = register(app, username="오준영", password="class1234")
    assert user["username"] == "오준영"

    me = request(app, "GET", "/api/auth/me", cookies=cookies)
    assert me.status_code == 200
    assert me.json()["user"] == user

    duplicate = request(app, "POST", "/api/auth/register", json={
        "username": "오준영", "password": "other1234",
    })
    assert duplicate.status_code == 409
    wrong = request(app, "POST", "/api/auth/login", json={
        "username": "오준영", "password": "wrong1234",
    })
    assert wrong.status_code == 401

    logout = request(app, "POST", "/api/auth/logout", cookies=cookies)
    assert logout.status_code == 200
    assert request(app, "GET", "/api/auth/me", cookies=cookies).json()["user"] is None
    login = request(app, "POST", "/api/auth/login", json={
        "username": "오준영", "password": "class1234",
    })
    assert login.status_code == 200

    with sqlite3.connect(database) as conn:
        stored_hash = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", ("오준영",)
        ).fetchone()[0]
    assert stored_hash != b"class1234"


def test_orders_require_login_and_accounts_are_isolated(market_app):
    app, _ = market_app
    order_payload = {"ticker": "005930", "side": "buy", "quantity": 2}
    assert request(app, "POST", "/api/market/orders", json=order_payload).status_code == 401

    first_cookies, _ = register(app, username="student_one")
    second_cookies, _ = register(app, username="student_two")
    price = stock(snapshot(app, cookies=first_cookies))["price"]
    assert request(
        app, "POST", "/api/market/orders", json=order_payload, cookies=first_cookies
    ).status_code == 200

    first = snapshot(app, cookies=first_cookies)["portfolio"]
    second = snapshot(app, cookies=second_cookies)["portfolio"]
    assert first["cash"] == 100_000_000 - price * 2
    assert first["positions"][0]["quantity"] == 2
    assert second["cash"] == 100_000_000
    assert second["positions"] == []


def test_account_data_survives_app_restart(market_app):
    app, database = market_app
    cookies, _ = register(app, username="restart_student", password="pass1234")
    response = request(app, "POST", "/api/market/orders", json={
        "ticker": "035420", "side": "buy", "quantity": 5,
    }, cookies=cookies)
    assert response.status_code == 200

    restarted_app = create_app(database)
    me = request(restarted_app, "GET", "/api/auth/me", cookies=cookies)
    assert me.json()["user"]["username"] == "restart_student"
    restarted = snapshot(restarted_app, cookies=cookies)["portfolio"]
    assert restarted["positions"][0]["ticker"] == "035420"
    assert restarted["positions"][0]["quantity"] == 5
