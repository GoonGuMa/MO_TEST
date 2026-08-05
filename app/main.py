from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .market import MarketEngine, MarketError, SESSION_MAX_AGE_SECONDS


ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT_DIR / "app" / "static"
SESSION_COOKIE = "market_lab_session"


class OrderRequest(BaseModel):
    ticker: str = Field(pattern=r"^\d{6}$")
    side: str = Field(pattern="^(buy|sell)$")
    quantity: int = Field(ge=1, le=1_000_000)


class AuthRequest(BaseModel):
    username: str = Field(min_length=2, max_length=20)
    password: str = Field(min_length=4, max_length=64)


class NewsRequest(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    content: str = Field(default="", max_length=1000)
    sentiment: str = Field(pattern="^(positive|negative)$")
    ticker: str | None = Field(default=None, pattern=r"^\d{6}$")
    impact_pct: float | None = Field(default=None, ge=15.0, le=25.0)
    admin_key: str = Field(default="", max_length=200)


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

    def session_user(request: Request) -> dict | None:
        return engine.user_for_session(request.cookies.get(SESSION_COOKIE))

    async def current_user(request: Request) -> dict:
        user = session_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
        return user

    def set_session_cookie(request: Request, response: Response, token: str) -> None:
        forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        response.set_cookie(
            SESSION_COOKIE, token, max_age=SESSION_MAX_AGE_SECONDS,
            httponly=True, samesite="lax",
            secure=request.url.scheme == "https" or forwarded_proto == "https",
            path="/",
        )

    @app.get("/api/auth/me")
    async def auth_me(request: Request) -> dict:
        return {"user": session_user(request)}

    @app.post("/api/auth/register", status_code=201)
    async def auth_register(payload: AuthRequest, request: Request, response: Response) -> dict:
        user, token = engine.register_user(payload.username, payload.password)
        set_session_cookie(request, response, token)
        return {"message": "회원가입이 완료되었습니다.", "user": user}

    @app.post("/api/auth/login")
    async def auth_login(payload: AuthRequest, request: Request, response: Response) -> dict:
        user, token = engine.login_user(payload.username, payload.password)
        set_session_cookie(request, response, token)
        return {"message": "로그인했습니다.", "user": user}

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request, response: Response) -> dict:
        engine.logout_user(request.cookies.get(SESSION_COOKIE))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"message": "로그아웃했습니다."}

    @app.get("/api/market/snapshot")
    async def snapshot(request: Request, ticker: str = "005930") -> dict:
        user = session_user(request)
        user_id = engine.account_id_for_user(user["id"]) if user else "guest_preview"
        return engine.snapshot(user_id=user_id, ticker=ticker)

    @app.post("/api/market/orders")
    async def order(request: OrderRequest, user: dict = Depends(current_user)) -> dict:
        return engine.order(
            user_id=engine.account_id_for_user(user["id"]),
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
    async def reset(user: dict = Depends(current_user)) -> dict:
        return engine.reset_account(engine.account_id_for_user(user["id"]))

    @app.post("/api/market/accounts/sell-all")
    async def sell_all(user: dict = Depends(current_user)) -> dict:
        return engine.sell_all(engine.account_id_for_user(user["id"]))

    @app.post("/api/market/randomize")
    async def randomize_market(_: dict = Depends(current_user)) -> dict:
        return engine.randomize_market()

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
