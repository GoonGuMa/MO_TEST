# Finance Data Lab 실행 방법

기존 `backend.py`와 별개로 `main.py`를 실행합니다.

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

브라우저에서 다음 주소를 사용할 수 있습니다.

- KRX 시장 스캐너: <http://127.0.0.1:8000/>
- 금융감독원 금융회사 데이터: <http://127.0.0.1:8000/fss>
- KRX 시장 스캐너: <http://127.0.0.1:8000/krx>
- 한국은행 경제지표: <http://127.0.0.1:8000/ecos>
- OpenDART 기업 분석: <http://127.0.0.1:8000/dart>
- API 문서: <http://127.0.0.1:8000/docs>

## 인증키

기본적으로 프로젝트 루트의 `.key`를 읽습니다. `#서비스명` 다음 줄의
`라벨 = 인증키` 또는 `라벨 - 인증키` 형식을 지원하며, 바깥 따옴표 유무와
관계없이 동작합니다. 배포 환경에서는 다음 환경 변수로 대체할 수 있습니다.

- `FSS_API_KEY`
- `KRX_API_KEY`
- `ECOS_API_KEY`
- `DART_API_KEY`

인증키는 HTML 응답이나 상태 API에 포함되지 않습니다. `/health`는 각 키가
설정되었는지만 `true` 또는 `false`로 반환합니다.

KRX는 인증키 발급 외에도 사용할 개별 API 서비스에 대한 이용신청이 필요할
수 있습니다. 외부 기관이 키 오류, 이용 미승인 또는 조회 결과 없음 응답을
보내면 각 화면 상단 상태 영역에 해당 상태가 표시됩니다.
