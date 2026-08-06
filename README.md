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

## Docker로 실행

Docker Hub 이미지를 내려받아 실행합니다. 회원 및 거래 데이터를 계속 보존하려면
이름이 있는 볼륨을 `/app/data`에 연결하세요.

```bash
docker pull gogumaa/mo-test:0.2
docker run --name motest -p 8080:8080 \
  -v motest-data:/app/data \
  -e MOCK_MARKET_ADMIN_KEY='원하는-비밀키' \
  gogumaa/mo-test:0.2
```

브라우저에서 <http://localhost:8080>을 열고, 종료할 때는
`docker stop motest`를 실행합니다. 운영자 키가 필요하지 않으면 `-e` 줄은 생략할 수
있습니다.

## GitHub Codespaces에서 공유

저장소의 **Code → Codespaces → Create codespace on main**을 선택하면 의존성 설치와
서버 실행, 8080 포트 전달이 자동으로 진행됩니다.

다른 사람에게 실행 중인 앱을 공유하려면 Codespace의 **PORTS** 탭에서 8080 포트를
우클릭하고 **Port Visibility → Public**을 선택한 뒤 표시된 URL을 복사합니다.
Codespace가 중지되면 앱도 중지되며, 재시작 후 포트 공개 설정을 다시 확인해야 합니다.

## 회원 데이터 보존

회원, 계좌, 보유 종목, 거래 내역은 `data/market.sqlite3`에 저장됩니다. 같은
Codespace를 중지·재실행하거나 컨테이너를 Rebuild해도 `/workspaces`의 데이터는
유지됩니다. Codespace를 삭제하고 새로 만들면 데이터가 초기화되므로 수업 기록을
보존하려면 삭제 전에 SQLite 파일을 내려받아 백업하세요.

## 뉴스 발행 보호

기본값은 수업 시연을 위해 운영자 키 없이 뉴스를 발행할 수 있습니다. 실제로
여러 학생에게 공개할 때는 환경변수를 설정하세요.

```bash
MOCK_MARKET_ADMIN_KEY='원하는-비밀키' .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
```

운영자 화면의 `운영자 키` 칸에 같은 값을 입력해야 뉴스가 발행됩니다.

## 테스트

```bash
.venv/bin/pytest -q
```

## 뉴스발행

현재 뉴스는 약 30가지가 랜덤로직으로 인해 발행되고 있습니다. 일정 키워드 변경과 타회사 언급 등을 통해
특정 회사의 주가변동을 예측하여 투자할 수 있습니다.
또한, 두 가지 이상의 종목에 영향을 끼치는 뉴스도 존재하니 재미있게 즐기실 수 있길 바랍니다.
