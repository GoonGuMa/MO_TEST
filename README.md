# 뉴스 기반 모의투자

실제 주식 API 없이 운영되는 교육용 모의투자 웹앱입니다.

- 모든 종목은 서버 기준으로 15초마다 `±0.1~1%` 변동
- 긍정 뉴스는 선택 종목 또는 전체 시장을 `+15~25%` 변동
- 부정 뉴스는 선택 종목 또는 전체 시장을 `-15~25%` 변동
- 사용자별 초기자금 1억원, 보유 종목과 거래 내역 SQLite 저장
- 주문 가격과 잔고 계산은 서버에서 처리
- 브라우저를 닫아도 같은 브라우저에서는 계좌 유지

## 실행

```bash
cd /home/goguma/mo_test
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

브라우저에서 <http://localhost:8000>을 엽니다. API 문서는
<http://localhost:8000/docs>에서 확인할 수 있습니다.

## 뉴스 발행 보호

기본값은 수업 시연을 위해 운영자 키 없이 뉴스를 발행할 수 있습니다. 실제로
여러 학생에게 공개할 때는 환경변수를 설정하세요.

```bash
MOCK_MARKET_ADMIN_KEY='원하는-비밀키' .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

운영자 화면의 `운영자 키` 칸에 같은 값을 입력해야 뉴스가 발행됩니다.

## 테스트

```bash
.venv/bin/pytest -q
```
