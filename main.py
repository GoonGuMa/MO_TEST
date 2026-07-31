"""금융 공공 API 대시보드용 독립 FastAPI 애플리케이션.

기존 backend.py와 별개로 실행합니다.

    python -m uvicorn main:app --reload
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parent
KEY_FILE = BASE_DIR / ".key"
STATIC_DIR = BASE_DIR / "static"

PAGE_FILES = {
    "fss": BASE_DIR / "index3.html",
    "krx": BASE_DIR / "index4.html",
    "ecos": BASE_DIR / "index5.html",
    "dart": BASE_DIR / "index6.html",
}

KEY_ALIASES = {
    "금융감독원": "fss",
    "fss": "fss",
    "fisis": "fss",
    "krx": "krx",
    "한국은행 경제통계시스템": "ecos",
    "한국은행": "ecos",
    "ecos": "ecos",
    "open dart": "dart",
    "opendart": "dart",
    "dart": "dart",
}

app = FastAPI(
    title="Korea Finance Data Lab API",
    description="금융감독원·KRX·한국은행 ECOS·OpenDART API를 연결하는 대시보드 백엔드",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def load_api_keys() -> dict[str, str]:
    """`.key`의 `#서비스명` 다음 줄에서 인증키를 읽습니다.

    `라벨 = 실제키`, `라벨 - 실제키`, 키만 적은 형식을 모두 지원합니다.
    환경 변수가 있으면 환경 변수 값을 우선합니다.
    """

    keys: dict[str, str] = {}
    current_service: str | None = None

    if KEY_FILE.exists():
        for raw_line in KEY_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                label = line[1:].strip().lower()
                current_service = KEY_ALIASES.get(label)
                continue
            if not current_service:
                continue

            parts = re.split(r"\s+(?:=|-)\s+", line, maxsplit=1)
            secret = parts[-1].strip()
            if (
                len(secret) >= 2
                and secret[0] == secret[-1]
                and secret[0] in {'"', "'"}
            ):
                secret = secret[1:-1].strip()
            if secret:
                keys[current_service] = secret
            current_service = None

    env_names = {
        "fss": "FSS_API_KEY",
        "krx": "KRX_API_KEY",
        "ecos": "ECOS_API_KEY",
        "dart": "DART_API_KEY",
    }
    for service, env_name in env_names.items():
        if os.getenv(env_name):
            keys[service] = os.environ[env_name].strip()
    return keys


def require_key(service: str) -> str:
    key = load_api_keys().get(service)
    if not key:
        raise HTTPException(
            status_code=503,
            detail=f"{service.upper()} 인증키를 .key 또는 환경 변수에 설정해 주세요.",
        )
    return key


def clean_number(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def public_api_error(service: str, exc: Exception) -> HTTPException:
    """URL에 포함될 수 있는 인증키가 오류 응답으로 노출되지 않게 합니다."""

    if isinstance(exc, httpx.TimeoutException):
        detail = f"{service} 응답 시간이 초과되었습니다."
    elif isinstance(exc, httpx.HTTPStatusError):
        detail = f"{service}가 HTTP {exc.response.status_code} 오류를 반환했습니다."
    else:
        detail = f"{service} 연결에 실패했습니다."
    return HTTPException(status_code=502, detail=detail)


_CACHE: dict[str, tuple[float, Any]] = {}


def cache_get(key: str) -> Any | None:
    cached = _CACHE.get(key)
    if not cached:
        return None
    expires_at, value = cached
    if expires_at <= time.monotonic():
        _CACHE.pop(key, None)
        return None
    return value


def cache_set(key: str, value: Any, ttl_seconds: int) -> Any:
    _CACHE[key] = (time.monotonic() + ttl_seconds, value)
    return value


async def get_json(
    service: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "KoreaFinanceDataLab/1.0"},
        ) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise public_api_error(service, exc) from None


@app.get("/", response_class=FileResponse, include_in_schema=False)
def root_page() -> FileResponse:
    return FileResponse(PAGE_FILES["krx"])


@app.get("/fss", response_class=FileResponse, include_in_schema=False)
@app.get("/index3.html", response_class=FileResponse, include_in_schema=False)
def fss_page() -> FileResponse:
    return FileResponse(PAGE_FILES["fss"])


@app.get("/krx", response_class=FileResponse, include_in_schema=False)
@app.get("/index4.html", response_class=FileResponse, include_in_schema=False)
def krx_page() -> FileResponse:
    return FileResponse(PAGE_FILES["krx"])


@app.get("/ecos", response_class=FileResponse, include_in_schema=False)
@app.get("/index5.html", response_class=FileResponse, include_in_schema=False)
def ecos_page() -> FileResponse:
    return FileResponse(PAGE_FILES["ecos"])


@app.get("/dart", response_class=FileResponse, include_in_schema=False)
@app.get("/index6.html", response_class=FileResponse, include_in_schema=False)
def dart_page() -> FileResponse:
    return FileResponse(PAGE_FILES["dart"])


@app.get("/health", tags=["system"])
def health() -> dict[str, Any]:
    keys = load_api_keys()
    return {
        "status": "ok",
        "app": "Korea Finance Data Lab",
        "configured": {name: name in keys for name in ("fss", "krx", "ecos", "dart")},
    }


# ---------------------------------------------------------------------------
# 금융감독원 금융통계정보시스템(FISIS)

FSS_BASE_URL = "https://fisis.fss.or.kr/openapi"


def fss_result_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result") or {}
    rows = result.get("list") or []
    if isinstance(rows, dict):
        rows = [rows]
    return rows if isinstance(rows, list) else []


def fss_result_message(payload: dict[str, Any]) -> str | None:
    result = payload.get("result") or {}
    for key in ("err_msg", "message", "errMsg", "error_message"):
        if result.get(key):
            return str(result[key])
    return None


def is_closed_financial_company(name: str) -> bool:
    compact_name = re.sub(r"\s+", "", name)
    return any(
        marker in compact_name
        for marker in ("[폐]", "(폐)", "［폐］", "（폐）")
    )


@app.get("/api/fss/companies", tags=["FSS"])
async def fss_companies(
    sector: str = Query("A", min_length=1, max_length=4),
) -> dict[str, Any]:
    cache_key = f"fss:companies:{sector.upper()}"
    if cached := cache_get(cache_key):
        return cached

    payload = await get_json(
        "금융감독원 FISIS",
        f"{FSS_BASE_URL}/companySearch.json",
        params={"lang": "kr", "auth": require_key("fss"), "partDiv": sector.upper()},
    )
    rows = fss_result_list(payload)
    companies = [
        {
            "code": row.get("finance_cd", ""),
            "name": row.get("finance_nm", ""),
            "address": row.get("finance_addr", ""),
            "phone": row.get("finance_tel", ""),
            "raw": row,
        }
        for row in rows
        if row.get("finance_nm")
        and not is_closed_financial_company(str(row["finance_nm"]))
    ]
    result = {
        "sector": sector.upper(),
        "count": len(companies),
        "companies": companies,
        "message": fss_result_message(payload),
    }
    return cache_set(cache_key, result, 60 * 60 * 12)


@app.get("/api/fss/statistics", tags=["FSS"])
async def fss_statistics(
    finance_code: str = Query(..., min_length=1, max_length=20),
    list_no: str = Query("SA030", min_length=1, max_length=20),
    term: str = Query("Q", pattern="^[YHQM]$"),
    start: str | None = Query(None, pattern="^[0-9]{6}$"),
    end: str | None = Query(None, pattern="^[0-9]{6}$"),
) -> dict[str, Any]:
    today = date.today()
    end_month = end or today.strftime("%Y%m")
    start_month = start or f"{today.year - 3}{today.month:02d}"
    params = {
        "lang": "kr",
        "auth": require_key("fss"),
        "financeCd": finance_code,
        "listNo": list_no.upper(),
        "term": term,
        "startBaseMm": start_month,
        "endBaseMm": end_month,
    }
    payload = await get_json(
        "금융감독원 FISIS",
        f"{FSS_BASE_URL}/statisticsInfoSearch.json",
        params=params,
    )
    rows = fss_result_list(payload)
    return {
        "finance_code": finance_code,
        "list_no": list_no.upper(),
        "term": term,
        "period": {"start": start_month, "end": end_month},
        "count": len(rows),
        "rows": rows,
        "message": fss_result_message(payload),
    }


# ---------------------------------------------------------------------------
# 한국거래소(KRX) 일별 시장 스캐너

KRX_MARKET_URLS = {
    "KOSPI": "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd",
    "KOSDAQ": "https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd",
}


async def fetch_krx_market(market: str, base_date: str, key: str) -> list[dict[str, Any]]:
    payload = await get_json(
        "KRX",
        KRX_MARKET_URLS[market],
        params={"basDd": base_date},
        headers={"AUTH_KEY": key},
    )
    rows = payload.get("OutBlock_1") or []
    if not isinstance(rows, list):
        return []
    normalized = []
    for row in rows:
        open_price = clean_number(row.get("TDD_OPNPRC"))
        close_price = clean_number(row.get("TDD_CLSPRC"))
        open_change_rate = (
            round((close_price - open_price) / open_price * 100, 2)
            if open_price
            else 0.0
        )
        normalized.append(
            {
                "market": market,
                "symbol": row.get("ISU_SRT_CD") or row.get("ISU_CD") or "",
                "name": row.get("ISU_ABBRV") or row.get("ISU_NM") or "",
                "close": close_price,
                "change": clean_number(row.get("CMPPREVDD_PRC")),
                "change_rate": clean_number(row.get("FLUC_RT")),
                "open": open_price,
                "open_change_rate": open_change_rate,
                "high": clean_number(row.get("TDD_HGPRC")),
                "low": clean_number(row.get("TDD_LWPRC")),
                "volume": clean_number(row.get("ACC_TRDVOL")),
                "trading_value": clean_number(row.get("ACC_TRDVAL")),
                "market_cap": clean_number(row.get("MKTCAP")),
            }
        )
    return normalized


@app.get("/api/krx/market", tags=["KRX"])
async def krx_market(
    base_date: str | None = Query(None, pattern="^[0-9]{4}-?[0-9]{2}-?[0-9]{2}$"),
) -> dict[str, Any]:
    requested = (
        datetime.strptime(base_date.replace("-", ""), "%Y%m%d").date()
        if base_date
        else date.today() - timedelta(days=1)
    )
    key = require_key("krx")

    # 휴일 또는 아직 게시되지 않은 날짜라면 직전 영업일을 자동 탐색합니다.
    rows: list[dict[str, Any]] = []
    effective_date = requested
    for offset in range(8):
        candidate = requested - timedelta(days=offset)
        if candidate.weekday() >= 5:
            continue
        candidate_text = candidate.strftime("%Y%m%d")
        cache_key = f"krx:market:{candidate_text}"
        cached = cache_get(cache_key)
        if cached is not None:
            rows = cached
        else:
            results = await asyncio.gather(
                *[
                    fetch_krx_market(market, candidate_text, key)
                    for market in KRX_MARKET_URLS
                ]
            )
            rows = [item for market_rows in results for item in market_rows]
            cache_set(cache_key, rows, 60 * 60 * 6)
        if rows:
            effective_date = candidate
            break

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="최근 영업일의 KRX 데이터를 찾지 못했습니다. API 이용신청 상태를 확인해 주세요.",
        )

    total_value = sum(row["trading_value"] for row in rows)
    summary = {
        "issues": len(rows),
        "advancers": sum(row["change_rate"] > 0 for row in rows),
        "decliners": sum(row["change_rate"] < 0 for row in rows),
        "unchanged": sum(row["change_rate"] == 0 for row in rows),
        "trading_value": total_value,
    }
    return {
        "requested_date": requested.isoformat(),
        "effective_date": effective_date.isoformat(),
        "summary": summary,
        "top_market_cap": sorted(rows, key=lambda row: row["market_cap"], reverse=True)[:15],
        "top_trading_value": sorted(
            rows, key=lambda row: row["trading_value"], reverse=True
        )[:15],
        "top_gainers": sorted(
            rows, key=lambda row: row["open_change_rate"], reverse=True
        )[:15],
        "top_decliners": sorted(rows, key=lambda row: row["open_change_rate"])[:15],
    }


# ---------------------------------------------------------------------------
# 한국은행 경제통계시스템(ECOS)

ECOS_SERIES = {
    "base_rate": {
        "label": "한국은행 기준금리",
        "stat_code": "722Y001",
        "cycle": "M",
        "item_code": "0101000",
    },
    "usd_krw": {
        "label": "원/달러 환율",
        "stat_code": "731Y001",
        "cycle": "D",
        "item_code": "0000001",
    },
    "cny_krw": {
        "label": "원/위안 환율",
        "stat_code": "731Y001",
        "cycle": "D",
        "item_code": "0000053",
    },
    "jpy_krw": {
        "label": "원/100엔 환율",
        "stat_code": "731Y001",
        "cycle": "D",
        "item_code": "0000002",
    },
    "cpi": {
        "label": "소비자물가지수",
        "stat_code": "901Y009",
        "cycle": "M",
        "item_code": "0",
    },
    "m2": {
        "label": "광의통화 M2",
        "stat_code": "161Y007",
        "cycle": "M",
        "item_code": "BBGS00",
    },
    "gdp": {
        "label": "명목 국내총생산",
        "stat_code": "200Y113",
        "cycle": "A",
        "item_code": "10106",
    },
}


def ecos_period(cycle: str) -> tuple[str, str]:
    today = date.today()
    if cycle == "D":
        return (today - timedelta(days=370)).strftime("%Y%m%d"), today.strftime("%Y%m%d")
    if cycle == "Q":
        return f"{today.year - 5}Q1", f"{today.year}Q4"
    if cycle == "A":
        return str(today.year - 10), str(today.year)
    return f"{today.year - 5}01", today.strftime("%Y%m")


async def fetch_ecos_series(series_id: str, key: str) -> dict[str, Any]:
    config = ECOS_SERIES[series_id]
    start, end = ecos_period(config["cycle"])
    cache_key = f"ecos:{series_id}:{start}:{end}"
    if cached := cache_get(cache_key):
        return cached

    path_parts = [
        key,
        "json",
        "kr",
        "1",
        "1000",
        config["stat_code"],
        config["cycle"],
        start,
        end,
        config["item_code"],
    ]
    url = "https://ecos.bok.or.kr/api/StatisticSearch/" + "/".join(
        quote(part, safe="") for part in path_parts
    )
    payload = await get_json("한국은행 ECOS", url)
    block = payload.get("StatisticSearch")
    if not isinstance(block, dict):
        message = (payload.get("RESULT") or {}).get("MESSAGE", "조회 결과가 없습니다.")
        return {"id": series_id, **config, "points": [], "error": message}

    points = []
    for row in block.get("row") or []:
        value = clean_number(row.get("DATA_VALUE"))
        points.append(
            {
                "time": row.get("TIME", ""),
                "value": value,
                "unit": row.get("UNIT_NAME", ""),
                "item": row.get("ITEM_NAME1", ""),
            }
        )
    result = {"id": series_id, **config, "points": points, "error": None}
    return cache_set(cache_key, result, 60 * 60 * 6)


@app.get("/api/ecos/indicators", tags=["ECOS"])
async def ecos_indicators(
    series: str = Query("base_rate,usd_krw,cpi,m2,gdp"),
) -> dict[str, Any]:
    requested = list(dict.fromkeys(item.strip() for item in series.split(",") if item.strip()))
    unknown = [item for item in requested if item not in ECOS_SERIES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 지표: {', '.join(unknown)}")
    if not requested:
        raise HTTPException(status_code=400, detail="지표를 한 개 이상 선택해 주세요.")

    key = require_key("ecos")
    results = await asyncio.gather(
        *[fetch_ecos_series(item, key) for item in requested],
        return_exceptions=True,
    )
    indicators = []
    for series_id, result in zip(requested, results):
        if isinstance(result, Exception):
            indicators.append(
                {
                    "id": series_id,
                    **ECOS_SERIES[series_id],
                    "points": [],
                    "error": "API 호출에 실패했습니다.",
                }
            )
        else:
            indicators.append(result)
    return {"updated_at": datetime.now().isoformat(timespec="seconds"), "indicators": indicators}


# ---------------------------------------------------------------------------
# OpenDART

DART_BASE_URL = "https://opendart.fss.or.kr/api"
DART_CORP_CACHE = Path("/tmp/api-test-dart-corp-codes.json")


async def get_dart_corporations(key: str) -> list[dict[str, str]]:
    cached = cache_get("dart:corp-codes")
    if cached:
        return cached

    if DART_CORP_CACHE.exists():
        age = time.time() - DART_CORP_CACHE.stat().st_mtime
        if age < 60 * 60 * 24 * 7:
            try:
                data = json.loads(DART_CORP_CACHE.read_text(encoding="utf-8"))
                return cache_set("dart:corp-codes", data, 60 * 60 * 24)
            except (OSError, json.JSONDecodeError):
                pass

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(
                f"{DART_BASE_URL}/corpCode.xml",
                params={"crtfc_key": key},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise public_api_error("OpenDART 법인코드", exc) from None

    try:
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        xml_data = archive.read("CORPCODE.xml")
    except (zipfile.BadZipFile, KeyError):
        message = "법인코드 파일 대신 오류 응답을 받았습니다."
        try:
            error_root = ElementTree.fromstring(response.content)
            message = error_root.findtext("message") or message
        except ElementTree.ParseError:
            try:
                error_payload = response.json()
                message = error_payload.get("message") or message
            except (json.JSONDecodeError, AttributeError):
                pass
        raise HTTPException(status_code=502, detail=f"OpenDART: {message}")

    root = ElementTree.fromstring(xml_data)
    companies = []
    for item in root.findall("list"):
        company = {
            "corp_code": (item.findtext("corp_code") or "").strip(),
            "corp_name": (item.findtext("corp_name") or "").strip(),
            "stock_code": (item.findtext("stock_code") or "").strip(),
            "modify_date": (item.findtext("modify_date") or "").strip(),
        }
        if company["corp_code"] and company["corp_name"]:
            companies.append(company)

    try:
        DART_CORP_CACHE.write_text(
            json.dumps(companies, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
    return cache_set("dart:corp-codes", companies, 60 * 60 * 24)


@app.get("/api/dart/search", tags=["OpenDART"])
async def dart_search(
    q: str = Query(..., min_length=1, max_length=50),
) -> dict[str, Any]:
    query = q.strip().lower()
    companies = await get_dart_corporations(require_key("dart"))
    exact = []
    partial = []
    for company in companies:
        name = company["corp_name"].lower()
        stock_code = company["stock_code"]
        if query in {name, stock_code, company["corp_code"]}:
            exact.append(company)
        elif query in name or (stock_code and query in stock_code):
            partial.append(company)
    rows = (exact + partial)[:30]
    return {"query": q, "count": len(rows), "companies": rows}


def dart_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("list") or []
    return rows if isinstance(rows, list) else []


@app.get("/api/dart/company", tags=["OpenDART"])
async def dart_company(
    corp_code: str = Query(..., pattern="^[0-9]{8}$"),
    year: int = Query(date.today().year - 1, ge=2015, le=date.today().year),
) -> dict[str, Any]:
    key = require_key("dart")
    today = date.today()
    start_date = (today - timedelta(days=365)).strftime("%Y%m%d")
    end_date = today.strftime("%Y%m%d")

    company_task = get_json(
        "OpenDART",
        f"{DART_BASE_URL}/company.json",
        params={"crtfc_key": key, "corp_code": corp_code},
    )
    disclosure_task = get_json(
        "OpenDART",
        f"{DART_BASE_URL}/list.json",
        params={
            "crtfc_key": key,
            "corp_code": corp_code,
            "bgn_de": start_date,
            "end_de": end_date,
            "page_count": 30,
            "sort": "date",
            "sort_mth": "desc",
        },
    )
    company, disclosure_payload = await asyncio.gather(company_task, disclosure_task)

    financial_payload: dict[str, Any] = {}
    financial_year = year
    for candidate_year in range(year, max(2014, year - 3), -1):
        financial_payload = await get_json(
            "OpenDART",
            f"{DART_BASE_URL}/fnlttSinglAcnt.json",
            params={
                "crtfc_key": key,
                "corp_code": corp_code,
                "bsns_year": candidate_year,
                "reprt_code": "11011",
            },
        )
        if dart_rows(financial_payload):
            financial_year = candidate_year
            break

    financials = []
    for row in dart_rows(financial_payload):
        financials.append(
            {
                "account": row.get("account_nm", ""),
                "statement": row.get("sj_nm", ""),
                "current": row.get("thstrm_amount", ""),
                "previous": row.get("frmtrm_amount", ""),
                "currency": row.get("currency", ""),
                "fs_div": row.get("fs_div", ""),
            }
        )

    disclosures = [
        {
            "receipt_no": row.get("rcept_no", ""),
            "date": row.get("rcept_dt", ""),
            "report": row.get("report_nm", ""),
            "submitter": row.get("flr_nm", ""),
            "remark": row.get("rm", ""),
            "url": (
                f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row.get('rcept_no', '')}"
            ),
        }
        for row in dart_rows(disclosure_payload)
    ]

    if company.get("status") not in {None, "000"}:
        raise HTTPException(
            status_code=404,
            detail=company.get("message", "기업 정보를 찾을 수 없습니다."),
        )

    return {
        "company": {
            "corp_code": company.get("corp_code", corp_code),
            "name": company.get("corp_name", ""),
            "name_en": company.get("corp_name_eng", ""),
            "stock_code": company.get("stock_code", ""),
            "ceo": company.get("ceo_nm", ""),
            "market": company.get("corp_cls", ""),
            "industry_code": company.get("induty_code", ""),
            "address": company.get("adres", ""),
            "website": company.get("hm_url", ""),
            "fiscal_month": company.get("acc_mt", ""),
        },
        "financial_year": financial_year,
        "financials": financials,
        "disclosures": disclosures,
    }
