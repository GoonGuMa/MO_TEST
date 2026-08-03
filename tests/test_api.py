from __future__ import annotations

import asyncio
import random
import sqlite3
import time

import httpx
import pytest

from app.main import create_app


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


def snapshot(app, user_id="student_test", ticker="005930"):
    response = request(
        app, "GET", "/api/market/snapshot",
        params={"user_id": user_id, "ticker": ticker},
    )
    assert response.status_code == 200
    return response.json()


def stock(data, ticker="005930"):
    return next(item for item in data["stocks"] if item["ticker"] == ticker)


def test_snapshot_creates_account_and_six_stocks(market_app):
    app, _ = market_app
    data = snapshot(app)
    assert len(data["stocks"]) == 6
    assert data["tick_seconds"] == 15
    assert data["portfolio"]["cash"] == 100_000_000
    assert data["portfolio"]["total_assets"] == 100_000_000


def test_normal_tick_moves_every_stock_within_configured_range(market_app):
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
        assert 0.09 <= change <= 1.01


def test_positive_news_applies_twenty_percent_to_selected_stock(market_app):
    app, _ = market_app
    old_price = stock(snapshot(app))["price"]
    response = request(app, "POST", "/api/market/news", json={
        "title": "대규모 수주 계약", "content": "예상치를 크게 웃도는 계약입니다.",
        "sentiment": "positive", "ticker": "005930", "impact_pct": 20,
        "admin_key": "",
    })
    assert response.status_code == 200
    assert response.json()["affected_tickers"] == ["005930"]
    after = snapshot(app)
    assert stock(after)["price"] == round(old_price * 1.2 / 10) * 10
    assert after["news"][0]["impact_pct"] == 20
    assert after["history"][-1]["event_type"] == "news"


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
    price = stock(snapshot(app))["price"]
    buy = request(app, "POST", "/api/market/orders", json={
        "user_id": "student_test", "ticker": "005930", "side": "buy", "quantity": 10,
    })
    assert buy.status_code == 200
    assert buy.json()["portfolio"]["cash"] == 100_000_000 - price * 10
    assert buy.json()["portfolio"]["positions"][0]["quantity"] == 10
    sell = request(app, "POST", "/api/market/orders", json={
        "user_id": "student_test", "ticker": "005930", "side": "sell", "quantity": 4,
    })
    assert sell.status_code == 200
    assert sell.json()["portfolio"]["positions"][0]["quantity"] == 6
    rejected = request(app, "POST", "/api/market/orders", json={
        "user_id": "student_test", "ticker": "005930", "side": "sell", "quantity": 7,
    })
    assert rejected.status_code == 400
    assert "보유 수량" in rejected.json()["detail"]


def test_news_admin_key_is_enforced(market_app, monkeypatch):
    app, _ = market_app
    monkeypatch.setenv("MOCK_MARKET_ADMIN_KEY", "class-secret")
    payload = {
        "title": "신제품 판매 호조", "content": "", "sentiment": "positive",
        "ticker": "035720", "impact_pct": 15, "admin_key": "wrong",
    }
    assert request(app, "POST", "/api/market/news", json=payload).status_code == 403
    payload["admin_key"] = "class-secret"
    assert request(app, "POST", "/api/market/news", json=payload).status_code == 200


def test_account_reset_restores_initial_cash(market_app):
    app, _ = market_app
    snapshot(app)
    request(app, "POST", "/api/market/orders", json={
        "user_id": "student_test", "ticker": "005930", "side": "buy", "quantity": 3,
    })
    response = request(
        app, "POST", "/api/market/accounts/reset", json={"user_id": "student_test"}
    )
    assert response.status_code == 200
    assert response.json()["portfolio"]["cash"] == 100_000_000
    assert response.json()["portfolio"]["positions"] == []
