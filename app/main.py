from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .market import MarketEngine, MarketError


ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT_DIR / "app" / "static"


class OrderRequest(BaseModel):
    user_id: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    ticker: str = Field(pattern=r"^\d{6}$")
    side: str = Field(pattern="^(buy|sell)$")
    quantity: int = Field(ge=1, le=1_000_000)


class NewsRequest(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    content: str = Field(default="", max_length=1000)
    sentiment: str = Field(pattern="^(positive|negative)$")
    ticker: str | None = Field(default=None, pattern=r"^\d{6}$")
    impact_pct: float | None = Field(default=None, ge=15.0, le=25.0)
    admin_key: str = Field(default="", max_length=200)


class ResetRequest(BaseModel):
    user_id: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


def create_app(db_path: Path | None = None) -> FastAPI:
    database = db_path or Path(os.getenv("MOCK_MARKET_DB", ROOT_DIR / "data" / "market.sqlite3"))
    engine = MarketEngine(database)
    app = FastAPI(
        title="뉴스 기반 모의투자 API",
        version="1.0.0",
        description="실제 시세 API 없이 15초 변동과 뉴스 이벤트로 운영되는 교육용 시장",
    )
    app.state.market = engine

    @app.exception_handler(MarketError)
    async def market_error_handler(_: Request, exc: MarketError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/market/snapshot")
    async def snapshot(user_id: str = "guest", ticker: str = "005930") -> dict:
        return engine.snapshot(user_id=user_id, ticker=ticker)

    @app.post("/api/market/orders")
    async def order(request: OrderRequest) -> dict:
        return engine.order(
            user_id=request.user_id,
            ticker=request.ticker,
            side=request.side,
            quantity=request.quantity,
        )

    @app.post("/api/market/news")
    async def news(request: NewsRequest) -> dict:
        configured_key = os.getenv("MOCK_MARKET_ADMIN_KEY", "")
        if configured_key and not secrets.compare_digest(request.admin_key, configured_key):
            raise HTTPException(status_code=403, detail="운영자 키가 올바르지 않습니다.")
        return engine.publish_news(
            title=request.title,
            content=request.content,
            sentiment=request.sentiment,
            ticker=request.ticker,
            impact_pct=request.impact_pct,
        )

    @app.post("/api/market/accounts/reset")
    async def reset(request: ResetRequest) -> dict:
        return engine.reset_account(request.user_id)

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
