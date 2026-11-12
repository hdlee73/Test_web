"""DART 전자공시 오픈API(금융감독원) 수집.

- 인증: 환경변수 DART_API_KEY (저장소 코드·설정에 넣지 않는다). 발급: https://opendart.fss.or.kr
- 최근 며칠의 공시 목록(list.json)을 접수일 기준으로 읽는다. 제목은 "회사명 보고서명", 링크는 DART 원문 페이지.
  본문은 읽지 않는다.
- 응답 status: 000 정상, 013 조회 결과 없음, 020 요청 한도 초과, 그 밖의 코드는 키·요청 오류.
- 접수일은 날짜만 있다. 오늘 접수분은 수집 시각을 쓰고, 지난 날짜는 그날 정오(KST)로 둔다.
"""
from __future__ import annotations

import html
import logging
import os
import re
import time
from datetime import datetime, timedelta

import httpx

from ..config import Source
from .adapters import MAX_TITLE, RawPost
from .timeutil import KST, utcnow

log = logging.getLogger(__name__)

VIEW_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
_WS = re.compile(r"\s+")


class DartError(Exception):
    """수집을 멈춰야 하는 오류. blocked=True 이면 한도 초과라 쉬어야 한다."""

    def __init__(self, message: str, blocked: bool = False):
        super().__init__(message)
        self.blocked = blocked


def credentials(env=None) -> str | None:
    env = os.environ if env is None else env
    key = env.get("DART_API_KEY", "").strip()
    return key or None


def _posted_at(rcept_dt: str, now: datetime) -> datetime | None:
    if not re.fullmatch(r"\d{8}", rcept_dt or ""):
        return None
    d = datetime.strptime(rcept_dt, "%Y%m%d").replace(tzinfo=KST)
    if d.date() >= now.astimezone(KST).date():
        return None
    return (d + timedelta(hours=12)).astimezone(now.tzinfo)


def parse_items(source: Source, items: list[dict], now: datetime) -> list[RawPost]:
    out: dict[str, RawPost] = {}
    for it in items:
        no = str(it.get("rcept_no") or "").strip()
        corp = _WS.sub(" ", html.unescape(str(it.get("corp_name") or ""))).strip()
        rep = _WS.sub(" ", html.unescape(str(it.get("report_nm") or ""))).strip()
        if not no or not rep:
            continue
        title = f"{corp} {rep}".strip()[:MAX_TITLE]
        out[no] = RawPost(source.id, no, title, VIEW_URL.format(rcept_no=no), _posted_at(str(it.get("rcept_dt") or ""), now))
    return list(out.values())


def fetch_posts(source: Source, key: str, *, transport: httpx.BaseTransport | None = None, now: datetime | None = None,
                days: int = 3, max_pages: int = 10, pause: float = 0.3, sleep=time.sleep) -> list[RawPost]:
    now = now or utcnow()
    end = now.astimezone(KST).date()
    bgn = end - timedelta(days=days - 1)
    merged: dict[str, RawPost] = {}
    with httpx.Client(timeout=20, headers={"User-Agent": "TrendCheckerBot/0.1"}, transport=transport) as client:
        page = 1
        while page <= max_pages:
            try:
                r = client.get(source.url, params={"crtfc_key": key, "bgn_de": bgn.strftime("%Y%m%d"),
                                                   "end_de": end.strftime("%Y%m%d"), "page_no": page, "page_count": 100})
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
            status = str(data.get("status", ""))
            if status == "013":  # 조회된 데이터 없음
                break
            if status == "020":
                raise DartError("요청 한도 초과(020)", blocked=True)
            if status != "000":
                raise DartError(f"DART 응답 오류 {status}: {data.get('message', '')}"[:200])
            for p in parse_items(source, data.get("list") or [], now):
                merged.setdefault(p.post_no, p)
            if page >= int(data.get("total_page") or 1):
                break
            page += 1
            sleep(pause)
    return list(merged.values())
