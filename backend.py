from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
import random

app = FastAPI(
    title="User Management API",
    description="""
    사용자 관리 백엔드 API입니다.

    ## 주요 기능
    - 사용자 목록 조회
    - 사용자 단건 조회
    - 사용자 생성

    ## 특징
    - Mock 데이터 30명 기본 제공
    - Swagger UI 자동 제공 (/docs)
    """,
    version="1.0.0",
    contact={
        "name": "Doyoung Kim",
        "email": "example@email.com"
    }
)

# --------------------------------------------------
# 데이터 모델 정의 (Swagger 문서용 설명 포함)
# --------------------------------------------------
class UserCreate(BaseModel):
    username: str = Field(..., example="honggildong", description="사용자 이름")
    email: str = Field(..., example="hong@example.com", description="이메일 주소")
    age: Optional[int] = Field(None, example=25, description="나이")

class UserResponse(BaseModel):
    id: int = Field(..., example=1, description="사용자 ID")
    username: str = Field(..., example="honggildong")
    email: str = Field(..., example="hong@example.com")
    age: Optional[int] = Field(None, example=25)

# --------------------------------------------------
# Mock 데이터 생성
# --------------------------------------------------
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

# --------------------------------------------------
# API 엔드포인트 (Swagger 설명 강화)
# --------------------------------------------------

@app.get(
    "/",
    summary="헬스 체크",
    description="서버 상태를 확인하는 API"
)
def read_root():
    return {"status": "ok", "message": "FastAPI 서버 정상 동작 중"}


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