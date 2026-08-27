from __future__ import annotations

import asyncio

import httpx
import pytest

from app.finance import (
    PAGE_FILES,
    app as mounted_finance_app,
    is_closed_financial_company,
)
from app.main import create_app


@pytest.fixture()
def finance_app(tmp_path):
    return create_app(tmp_path / "finance-test.sqlite3")


def request(app, path: str) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get(path)

    return asyncio.run(send())


@pytest.mark.parametrize(
    ("page", "path", "active_label"),
    [
        ("fss", "/fss", "금융회사"),
        ("krx", "/krx", "시장"),
        ("ecos", "/ecos", "경제"),
        ("dart", "/dart", "기업공시"),
    ],
)
def test_finance_pages_share_market_lab_navigation(page, path, active_label):
    html = PAGE_FILES[page].read_text(encoding="utf-8")
    registered_paths = {route.path for route in mounted_finance_app.routes}

    assert path in registered_paths
    assert active_label in html
    assert '<a class="drawer-item" href="/">' in html
    assert 'class="market-link"' not in html
    assert "/finance/static/finance.css" in html
    assert 'id="menu-toggle"' in html
    assert 'id="app-menu"' in html


def test_finance_layout_uses_market_lab_width_and_drawer_script():
    css = (PAGE_FILES["krx"].parent / "finance.css").read_text(encoding="utf-8")
    javascript = (PAGE_FILES["krx"].parent / "finance.js").read_text(encoding="utf-8")

    assert "width: min(1500px, calc(100% - 48px))" in css
    assert "width: 100vw" in css
    assert "margin-left: calc(50% - 50vw)" in css
    assert 'document.querySelector("#menu-toggle")' in javascript


def test_finance_health_reports_environment_configuration(finance_app, monkeypatch):
    monkeypatch.setenv("KRX_API_KEY", "configured-for-test")
    monkeypatch.delenv("FSS_API_KEY", raising=False)
    monkeypatch.delenv("ECOS_API_KEY", raising=False)
    monkeypatch.delenv("DART_API_KEY", raising=False)

    response = request(finance_app, "/finance/health")

    assert response.status_code == 200
    assert response.json()["configured"] == {
        "fss": False,
        "krx": True,
        "ecos": False,
        "dart": False,
    }
    assert "configured-for-test" not in response.text


def test_finance_api_requires_container_environment_key(finance_app, monkeypatch):
    monkeypatch.delenv("KRX_API_KEY", raising=False)

    response = request(finance_app, "/finance/api/krx/market?base_date=2026-08-01")

    assert response.status_code == 503
    assert "환경 변수" in response.json()["detail"]


def test_closed_financial_companies_are_filtered():
    assert is_closed_financial_company("테스트은행 [폐]") is True
    assert is_closed_financial_company("정상은행") is False
