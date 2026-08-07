# 표준 라이브러리와 FastAPI 구성 요소를 불러옵니다.
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional
import math
import random

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# 실행 위치와 관계없이 같은 폴더의 index.html을 찾기 위한 경로입니다.
BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / "index.html"
TETRIS_FILE = BASE_DIR / "index2.html"

# FastAPI 애플리케이션과 Swagger 문서의 기본 정보를 설정합니다.
app = FastAPI(
    title="Interactive Chart Mockup API",
    description="""
    차트 Mock 데이터와 사용자 관리 기능을 제공하는 백엔드 API입니다.

    ## 주요 기능
    - 주식, 깔때기, 방사형 차트 데이터 조회
    - 포물선 운동 시뮬레이션
    - 사용자 목록 조회
    - 사용자 단건 조회
    - 사용자 생성

    ## 특징
    - 대시보드용 Mock 데이터 제공
    - Mock 데이터 30명 기본 제공
    - Swagger UI 자동 제공 (/docs)
    """,
    version="1.0.0",
    contact={
        "name": "Doyoung Kim",
        "email": "example@email.com"
    }
)

# 프런트를 별도 개발 서버(5500 포트)에서 열 때도 API를 호출할 수 있도록
# 허용할 출처와 HTTP 메서드를 지정합니다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 사용자 생성 요청과 응답 구조를 정의합니다.
# 이 모델은 입력 검증과 Swagger 스키마 생성에 함께 사용됩니다.
class UserCreate(BaseModel):
    username: str = Field(..., example="honggildong", description="사용자 이름")
    email: str = Field(..., example="hong@example.com", description="이메일 주소")
    age: Optional[int] = Field(None, example=25, description="나이")

class UserResponse(BaseModel):
    id: int = Field(..., example=1, description="사용자 ID")
    username: str = Field(..., example="honggildong")
    email: str = Field(..., example="hong@example.com")
    age: Optional[int] = Field(None, example=25)

# 사용자 API를 바로 테스트할 수 있도록 메모리 기반 Mock 사용자를 만듭니다.
# 서버를 재시작하면 생성된 사용자와 추가로 등록한 사용자는 초기화됩니다.
def generate_mock_users():
    users = []
    for i in range(1, 31):
        users.append({
            "id": i,
            "username": f"user{i}",
            "email": f"user{i}@example.com",
            "age": random.randint(18, 60)
        })
    return users

db_users = generate_mock_users()

# 주식 차트의 일별 OHLC(시가·고가·저가·종가)와 거래량을 생성합니다.
# 날짜와 가격 배열은 고정되어 있으므로 서버를 재시작해도 같은 차트가 표시됩니다.
def generate_mock_stock_prices():
    closing_prices = [
        73500, 74200, 73800, 75100, 75900, 75400, 76800, 77200,
        76500, 77800, 78600, 78100, 79300, 80500, 79900, 81200,
        80700, 81600, 82400, 81900, 82800, 83500, 82900, 84100,
        83600, 84400, 83900, 84600, 83200, 81800, 82400, 83000,
        84200
    ]
    open_offsets = [-300, 200, -500, 400, -200, 300, -100]
    high_margins = [900, 700, 1100, 800, 600]
    low_margins = [700, 900, 600, 1000]
    trading_day = date(2026, 6, 16)
    price_data = []

    for index, close in enumerate(closing_prices):
        while trading_day.weekday() >= 5:
            trading_day += timedelta(days=1)

        previous_close = 73200 if index == 0 else closing_prices[index - 1]
        is_latest = index == len(closing_prices) - 1
        open_price = (
            83100
            if is_latest
            else previous_close + open_offsets[index % len(open_offsets)]
        )
        high_price = (
            85000
            if is_latest
            else max(open_price, close) + high_margins[index % len(high_margins)]
        )
        low_price = (
            82700
            if is_latest
            else min(open_price, close) - low_margins[index % len(low_margins)]
        )
        volume = (
            18420315
            if is_latest
            else 8200000 + ((index * 1739581) % 9600000)
        )

        price_data.append({
            "date": trading_day.isoformat(),
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close,
            "volume": volume
        })
        trading_day += timedelta(days=1)

    return price_data


# 종목 기본 정보와 위에서 생성한 일별 시세를 하나의 응답 구조로 묶습니다.
STOCK_PRICES = generate_mock_stock_prices()
STOCK_DATA = {
    "name": "삼성전자",
    "symbol": "005930",
    "market": "KOSPI",
    "currency": "KRW",
    "market_status": "장 마감",
    "latest": {
        "price": STOCK_PRICES[-1]["close"],
        "change": STOCK_PRICES[-1]["close"] - STOCK_PRICES[-2]["close"],
        "change_rate": round(
            (
                (STOCK_PRICES[-1]["close"] - STOCK_PRICES[-2]["close"])
                / STOCK_PRICES[-2]["close"]
            ) * 100,
            2
        ),
        "open": STOCK_PRICES[-1]["open"],
        "high": STOCK_PRICES[-1]["high"],
        "low": STOCK_PRICES[-1]["low"],
        "previous_close": STOCK_PRICES[-2]["close"],
        "volume": STOCK_PRICES[-1]["volume"],
        "trading_value": "1.54조원"
    },
    "daily_prices": STOCK_PRICES
}


# 대시보드 최초 로딩에 필요한 모든 Mock 데이터와 입력 기본값입니다.
# 프런트엔드는 이 값을 하드코딩하지 않고 /api/dashboard에서 가져옵니다.
DASHBOARD_DATA = {
    "updated_at": "2026.07.30 16:00",
    "stock": STOCK_DATA,
    "summary": [
        {
            "key": "visitors",
            "label": "총 유입",
            "value": "12,480",
            "delta": "+8.4%"
        },
        {
            "key": "conversion",
            "label": "최종 전환율",
            "value": "20.9%",
            "delta": "+2.1%p"
        },
        {
            "key": "campaign",
            "label": "캠페인 달성도",
            "value": "86%",
            "delta": "+4.7%p"
        },
        {
            "key": "simulation",
            "label": "시뮬레이션 상태",
            "value": "READY",
            "delta": None
        }
    ],
    "funnel": {
        "conversion_rate": 20.9,
        "stages": [
            {"label": "방문", "value": 12480},
            {"label": "상품 조회", "value": 8940},
            {"label": "장바구니", "value": 4280},
            {"label": "결제 완료", "value": 2610}
        ]
    },
    "radial": [
        {"label": "도달률", "value": 86, "color": "#5b5bd6"},
        {"label": "참여율", "value": 72, "color": "#16b8c4"},
        {"label": "재방문", "value": 64, "color": "#f59e0b"}
    ],
    "simulation": {
        "defaults": {
            "velocity": 42,
            "angle": 45,
            "gravity": 9.81
        },
        "gravity_environments": [
            {"label": "지구", "gravity": 9.81},
            {"label": "화성", "gravity": 3.71},
            {"label": "달", "gravity": 1.62}
        ]
    }
}

# 화면, 상태 확인, 차트 데이터를 제공하는 대시보드 API 라우트입니다.

@app.get(
    "/",
    response_class=FileResponse,
    include_in_schema=False
)
def read_index():
    return FileResponse(INDEX_FILE)


@app.get(
    "/tetris",
    response_class=FileResponse,
    include_in_schema=False
)
def read_tetris():
    return FileResponse(TETRIS_FILE)


@app.get(
    "/health",
    summary="헬스 체크",
    description="서버 상태를 확인하는 API"
)
def read_health():
    return {"status": "ok", "message": "FastAPI 서버 정상 동작 중"}


@app.get(
    "/api/dashboard",
    summary="차트 Mock 데이터 조회",
    description="주식, 깔때기, 방사형 차트와 시뮬레이션 설정을 반환합니다."
)
def get_dashboard_data():
    return DASHBOARD_DATA


# 포물선 운동 공식을 서버에서 계산해 좌표와 주요 측정값을 반환합니다.
# Query 범위를 제한하여 화면의 슬라이더 범위 밖 입력도 검증합니다.
@app.get(
    "/api/simulation",
    summary="포물선 운동 계산",
    description="초기 속도, 발사각, 중력에 따른 포물선 궤적을 계산합니다."
)
def simulate_projectile(
    velocity: float = Query(42, ge=15, le=70, description="초기 속도(m/s)"),
    angle: float = Query(45, ge=10, le=80, description="발사각(도)"),
    gravity: float = Query(9.81, ge=1, le=20, description="중력 가속도(m/s²)")
):
    radians = math.radians(angle)
    flight_time = 2 * velocity * math.sin(radians) / gravity
    max_range = velocity ** 2 * math.sin(2 * radians) / gravity
    max_height = (
        velocity ** 2 * math.sin(radians) ** 2 / (2 * gravity)
    )
    steps = 50
    points = []

    for index in range(steps + 1):
        time = flight_time * index / steps
        x = velocity * math.cos(radians) * time
        y = max(
            0,
            velocity * math.sin(radians) * time
            - 0.5 * gravity * time ** 2
        )
        points.append({
            "x": round(x, 2),
            "y": round(y, 2)
        })

    return {
        "parameters": {
            "velocity": velocity,
            "angle": angle,
            "gravity": gravity
        },
        "metrics": {
            "flight_time": round(flight_time, 2),
            "max_range": round(max_range, 2),
            "max_height": round(max_height, 2)
        },
        "points": points
    }


# 기존 사용자 조회·등록 기능을 제공하는 사용자 API 라우트입니다.
@app.get(
    "/users",
    response_model=List[UserResponse],
    summary="사용자 목록 조회",
    description="전체 사용자 목록을 반환합니다."
)
def get_users():
    return db_users


@app.get(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="사용자 단건 조회",
    description="user_id에 해당하는 사용자를 조회합니다.",
    responses={
        404: {"description": "사용자를 찾을 수 없음"}
    }
)
def get_user(user_id: int):
    for user in db_users:
        if user["id"] == user_id:
            return user
    raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")


@app.post(
    "/users",
    response_model=UserResponse,
    status_code=201,
    summary="사용자 생성",
    description="새로운 사용자를 생성합니다."
)
def create_user(user: UserCreate):
    new_id = len(db_users) + 1

    new_user = {
        "id": new_id,
        "username": user.username,
        "email": user.email,
        "age": user.age
    }

    db_users.append(new_user)
    return new_user
