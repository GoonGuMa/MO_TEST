# 뉴스 기반 모의투자

실제 주식 API 없이 운영되는 교육용 모의투자 웹앱입니다.

- 모든 종목은 서버 기준으로 15초마다 랜덤거래량에 따라 '0~+-7%' 변동
- 긍정 뉴스는 선택 종목 또는 전체 시장을 `+15~25%` 변동
- 부정 뉴스는 선택 종목 또는 전체 시장을 `-15~25%` 변동
- 3~5분마다 자동 뉴스가 발행되며 선택 종목을 `±7~10%` 변동
- 모든 뉴스의 가격 영향은 발행 1분 후 반영
- 사용자별 초기자금 1억원, 보유 종목과 거래 내역 SQLite 저장
- 한글 아이디를 지원하는 회원가입·로그인과 사용자별 계좌 분리
- 비밀번호 해시 저장 및 7일 로그인 세션 쿠키
- 주문 가격과 잔고 계산은 서버에서 처리
- 같은 아이디로 로그인하면 다른 브라우저에서도 계좌 유지

## 실행

```bash
cd /home/goguma/mo_test
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

브라우저에서 <http://localhost:8080>을 엽니다. API 문서는
<http://localhost:8080/docs>에서 확인할 수 있습니다.

왼쪽 메뉴의 **금융 데이터 랩**을 선택하면 통합된 금융 화면으로 이동합니다.

- KRX 시장: <http://localhost:8080/finance/krx>
- 금융감독원 금융회사: <http://localhost:8080/finance/fss>
- 한국은행 경제지표: <http://localhost:8080/finance/ecos>
- OpenDART 기업공시: <http://localhost:8080/finance/dart>
- 금융 API 문서: <http://localhost:8080/finance/docs>

## Docker로 실행

프로젝트 루트에서 환경변수 예시 파일을 복사하고 필요한 API 키를 입력합니다.

```bash
cp .env.example .env
docker volume create motest-data
docker compose up --build -d
```

`.env`에는 필요한 값만 입력하면 됩니다.

```dotenv
MOCK_MARKET_ADMIN_KEY=뉴스발행용비밀키
FSS_API_KEY=금융감독원_API키
KRX_API_KEY=한국거래소_API키
ECOS_API_KEY=한국은행_API키
DART_API_KEY=OpenDART_API키
```

브라우저에서 <http://localhost:8080>을 엽니다. 컨테이너를 종료할 때는
`docker compose down`, 다시 시작할 때는 `docker compose up -d`를 사용합니다.
회원·거래 데이터는 기존 0.3 버전과 같은 `motest-data` Docker 볼륨에 보존됩니다. `.env`는 Git에서
제외되며 Docker 이미지 안에도 복사되지 않습니다.

## GitHub Codespaces에서 공유

저장소의 **Code → Codespaces → Create codespace on main**을 선택하면 의존성 설치와
서버 실행, 8080 포트 전달이 자동으로 진행됩니다.

다른 사람에게 실행 중인 앱을 공유하려면 Codespace의 **PORTS** 탭에서 8080 포트를
우클릭하고 **Port Visibility → Public**을 선택한 뒤 표시된 URL을 복사합니다.
Codespace가 중지되면 앱도 중지되며, 재시작 후 포트 공개 설정을 다시 확인해야 합니다.

## 회원 데이터 보존

회원, 계좌, 보유 종목, 거래 내역은 컨테이너의 `/app/data/market.sqlite3`에
저장됩니다. `compose.yaml`이 외부 `motest-data` 볼륨을 재사용하므로 컨테이너를
다시 만들거나 이미지를 재빌드해도 데이터가 유지되고, `docker compose down -v`에도
이 외부 볼륨은 삭제되지 않습니다.

## 뉴스 발행 보호

기본값은 수업 시연을 위해 운영자 키 없이 뉴스를 발행할 수 있습니다. 실제로
여러 학생에게 공개할 때는 환경변수를 설정하세요.

```bash
MOCK_MARKET_ADMIN_KEY='원하는-비밀키' .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
```

운영자 화면의 `운영자 키` 칸에 같은 값을 입력해야 뉴스가 발행됩니다.

## 테스트

```bash
.venv/bin/python -m pytest -q
```

## 뉴스발행

현재 뉴스는 약 30가지가 랜덤로직으로 인해 발행되고 있습니다. 일정 키워드 변경과 타회사 언급 등을 통해
특정 회사의 주가변동을 예측하여 투자할 수 있습니다.
또한, 두 가지 이상의 종목에 영향을 끼치는 뉴스도 존재하니 재미있게 즐기실 수 있길 바랍니다.
