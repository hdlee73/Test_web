"""증권신고서 제출 현황(자금조달) 수집: DART 오픈API.

1) list.json 에서 최근 며칠의 발행공시(pblntf_ty=C) 중 '증권신고서'(정정 포함)만 고른다. 펀드(집합투자증권)는 뺀다.
2) 아직 정리하지 않은 접수번호만, 증권 종류별 주요정보 API(지분 estkRs / 채무 bdRs / 증권예탁 stkdpRs /
   합병 mgRs / 주식의포괄적교환·이전 extrRs / 분할 dvRs)로 증권종류·모집(매출)총액·청약일·납입일을 받아 정리해 저장한다.
   (이 API 들은 회사 고유번호와 접수일 범위를 받고, 그 범위의 신고서 전부를 돌려준다.)
3) 신고서 본문은 읽지 않는다. 바로보기는 DART 원문 주소로 연결만 한다.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta

import httpx

from ..config import Source
from .dart import DartError
from .timeutil import KST, utcnow

log = logging.getLogger(__name__)

API = "https://opendart.fss.or.kr/api/{endpoint}.json"
VIEW_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

# 보고서명 괄호 안의 말 → (API 이름, 표시용 종류)
KINDS = [
    ("지분증권", "estkRs", "지분증권"),
    ("채무증권", "bdRs", "채무증권"),
    ("증권예탁증권", "stkdpRs", "증권예탁증권"),
    ("합병", "mgRs", "합병"),
    ("포괄적교환", "extrRs", "주식의 포괄적 교환·이전"),
    ("분할", "dvRs", "분할"),
]
_DATE = re.compile(r"(\d{4})\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})")


def classify(report_nm: str) -> tuple[str, str] | None:
    """증권신고서 보고서명이면 (API 이름, 종류). 펀드·그 밖의 서류는 None."""
    nm = report_nm.replace(" ", "")
    if "증권신고서" not in nm or "집합투자" in nm or "투자설명서" in nm:
        return None
    for key, api, label in KINDS:
        if key in nm:
            return api, label
    return None


def to_won(text) -> int | None:
    t = re.sub(r"[,\s원]", "", str(text or ""))
    return int(t) if t.isdigit() else None


def fmt_dates(text) -> str:
    """'2026년 11월 20일 ~ 2026년 11월 21일' → '2026-11-20 ~ 2026-11-21'. 해석 못 하면 원문."""
    raw = str(text or "").strip()
    ds = [f"{y}-{int(m):02d}-{int(d):02d}" for y, m, d in _DATE.findall(raw)]
    if ds:
        return " ~ ".join(dict.fromkeys(ds)) if len(ds) > 1 else ds[0]
    return "" if raw in ("-", "") else raw


def _groups(data: dict) -> dict[str, list[dict]]:
    return {g.get("title", ""): g.get("list") or [] for g in data.get("group") or []}


def summarize(kind: str, data: dict) -> dict[str, dict]:
    """주요정보 API 응답 → {접수번호: {security, amount_won, sub_date, pay_date}}."""
    gs = _groups(data)
    out: dict[str, dict] = {}

    def slot(no: str) -> dict:
        return out.setdefault(no, {"types": [], "amount": 0, "has_amount": False, "sub": "", "pay": ""})

    for row in gs.get("일반사항", []):
        no = str(row.get("rcept_no") or "")
        if not no:
            continue
        o = slot(no)
        o["sub"] = o["sub"] or fmt_dates(row.get("sbd"))
        o["pay"] = o["pay"] or fmt_dates(row.get("pymd"))
        if kind == "채무증권":  # 채무증권은 일반사항에 회차별 명칭·총액이 있다
            name = str(row.get("bdnmn") or "").strip()
            if name:
                o["types"].append(name)
            w = to_won(row.get("slta"))
            if w is not None:
                o["amount"] += w
                o["has_amount"] = True
        if kind in ("합병", "주식의 포괄적 교환·이전", "분할"):
            etc = str(row.get("mgdt_etc") or "").strip()
            o["pay"] = o["pay"] or fmt_dates(etc) or etc
    for row in gs.get("증권의종류", []) + gs.get("발행증권", []):
        no = str(row.get("rcept_no") or "")
        if not no:
            continue
        o = slot(no)
        t = str(row.get("stksen") or row.get("kndn") or "").strip()
        if t:
            o["types"].append(t)
        w = to_won(row.get("slta"))
        if w is not None:
            o["amount"] += w
            o["has_amount"] = True
    res = {}
    for no, o in out.items():
        types = list(dict.fromkeys(o["types"]))
        res[no] = {
            "security": ", ".join(types[:3]) + (f" 외 {len(types) - 3}" if len(types) > 3 else ""),
            "amount_won": o["amount"] if o["has_amount"] else None,
            "sub_date": o["sub"],
            "pay_date": o["pay"],
        }
    return res


def _get(client: httpx.Client, endpoint: str, params: dict) -> dict:
    try:
        r = client.get(API.format(endpoint=endpoint), params=params)
    except httpx.HTTPError as e:
        raise DartError(f"네트워크 오류: {e.__class__.__name__}") from e
    if r.status_code == 429:
        raise DartError("호출 한도 초과(429)", blocked=True)
    if r.status_code >= 400:
        raise DartError(f"HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError as e:
        raise DartError("응답이 JSON 이 아님") from e
    st = str(data.get("status", ""))
    if st == "020":
        raise DartError("요청 한도 초과(020)", blocked=True)
    if st not in ("000", "013"):
        raise DartError(f"DART 응답 오류 {st}: {data.get('message', '')}"[:200])
    return data


def fetch_filings(client: httpx.Client, key: str, now: datetime, days: int, max_pages: int, pause: float, sleep) -> list[dict]:
    end = now.astimezone(KST).date()
    bgn = end - timedelta(days=days - 1)
    items: list[dict] = []
    page = 1
    while page <= max_pages:
        data = _get(client, "list", {"crtfc_key": key, "bgn_de": bgn.strftime("%Y%m%d"), "end_de": end.strftime("%Y%m%d"),
                                     "pblntf_ty": "C", "page_no": page, "page_count": 100})
        if str(data.get("status")) == "013":
            break
        items += data.get("list") or []
        if page >= int(data.get("total_page") or 1):
            break
        page += 1
        sleep(pause)
    return items


def collect(source: Source, key: str, known: set[str], *, transport: httpx.BaseTransport | None = None,
            now: datetime | None = None, days: int = 6, max_pages: int = 15, pause: float = 0.3,
            sleep=time.sleep) -> tuple[list[tuple[str, str, dict]], int]:
    """새로 정리한 (접수번호, 접수일, 데이터) 목록과 대상 신고서 수."""
    now = now or utcnow()
    out: list[tuple[str, str, dict]] = []
    with httpx.Client(timeout=20, headers={"User-Agent": "TrendCheckerBot/0.1"}, transport=transport) as client:
        filings = []
        for it in fetch_filings(client, key, now, days, max_pages, pause, sleep):
            c = classify(str(it.get("report_nm") or ""))
            if c and it.get("rcept_no") and it.get("corp_code"):
                filings.append((it, c))
        todo: dict[tuple[str, str, str], list] = {}
        for it, (api, label) in filings:
            if str(it["rcept_no"]) in known:
                continue
            todo.setdefault((str(it["corp_code"]), api, label), []).append(it)
        for (corp, api, label), its in todo.items():
            dts = sorted(str(i.get("rcept_dt") or "") for i in its)
            data = _get(client, api, {"crtfc_key": key, "corp_code": corp, "bgn_de": dts[0], "end_de": dts[-1]})
            summ = summarize(label, data)
            for it in its:
                no = str(it["rcept_no"])
                s = summ.get(no) or {"security": "", "amount_won": None, "sub_date": "", "pay_date": ""}
                nm = str(it.get("report_nm") or "").strip()
                rec = {
                    "rcept_no": no, "rcept_dt": str(it.get("rcept_dt") or ""), "corp_name": str(it.get("corp_name") or "").strip(),
                    "stock_code": str(it.get("stock_code") or "").strip(), "report_nm": nm, "kind": label,
                    "corrected": "정정" in nm, "security": s["security"] or label,
                    "amount_eok": round(s["amount_won"] / 1e8, 1) if s["amount_won"] is not None else None,
                    "sub_date": s["sub_date"], "pay_date": s["pay_date"], "url": VIEW_URL.format(rcept_no=no),
                }
                out.append((no, rec["rcept_dt"], rec))
            sleep(pause)
    return out, len(filings)
