from __future__ import annotations

import asyncio
import random
import sqlite3
import time

import httpx
import pytest

from app.main import create_app
from app.market import (
    BASE_CHANGE_MAX,
    RANDOM_NEWS_CHANGE_MAX,
    RANDOM_NEWS_CHANGE_MIN,
    RANDOM_NEWS_INTERVAL_MAX,
    RANDOM_NEWS_INTERVAL_MIN,
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
    assert stock(snapshot(app))["price"] == stock(after)["price"]


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
    cookies, _ = register(app)
    request(app, "POST", "/api/market/orders", json={
        "ticker": "005930", "side": "buy", "quantity": 3,
    }, cookies=cookies)
    response = request(app, "POST", "/api/market/accounts/reset", cookies=cookies)
    assert response.status_code == 200
    assert response.json()["portfolio"]["cash"] == 100_000_000
    assert response.json()["portfolio"]["positions"] == []


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
