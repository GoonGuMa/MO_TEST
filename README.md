# api-test

## 실행

```bash
python -m pip install -r requirements.txt
python -m uvicorn backend:app --reload
```

서버 실행 후 아래 주소를 사용할 수 있습니다.

- 웹 화면: http://127.0.0.1:8000/
- 테트리스: http://127.0.0.1:8000/tetris
- API 문서: http://127.0.0.1:8000/docs
- 헬스 체크: http://127.0.0.1:8000/health
- 차트 Mock 데이터: http://127.0.0.1:8000/api/dashboard
- 포물선 시뮬레이션: http://127.0.0.1:8000/api/simulation
