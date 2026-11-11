"""네이버 검색 API(블로그·카페글·뉴스) 수집.

공식 API 이므로 robots.txt 대신 API 약관과 한도를 따른다.
- 인증: 환경변수 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET (저장소 코드·설정에 넣지 않는다)
- 질의어마다 1~N 페이지(1페이지 100건, 최신순)를 읽어 제목·링크만 모은다.
- 한도(일 25,000회)를 넘지 않도록 호출 사이에 간격을 두고, 429 가 오면 즉시 멈춘다.
- 카페글 결과에는 작성 시각이 없다 → 최초 수집 시각을 쓴다. 블로그는 작성일(날짜만)이 있다.
"""
from __future__ import annotations

import hashlib
import html
import logging
import os
import re
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx

from ..config import Source
from .adapters import MAX_TITLE, RawPost
from .timeutil import KST, utcnow

log = logging.getLogger(__name__)

API = "https://openapi.naver.com/v1/search/{endpoint}.json"
ENDPOINTS = {"blog", "cafearticle", "news"}
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


class NaverError(Exception):
    """수집을 멈춰야 하는 오류. blocked=True 이면 한도/차단이라 쉬어야 한다."""

    def __init__(self, message: str, blocked: bool = False):
        super().__init__(message)
        self.blocked = blocked


def credentials(env=None) -> tuple[str, str] | None:
    env = os.environ if env is None else env
    cid, sec = env.get("NAVER_CLIENT_ID", "").strip(), env.get("NAVER_CLIENT_SECRET", "").strip()
    return (cid, sec) if cid and sec else None


def clean(text: str) -> str:
    t = html.unescape(_TAG.sub("", text or ""))
    return _WS.sub(" ", t).strip()[:MAX_TITLE]


def _post_time(item: dict, now: datetime) -> datetime | None:
    """블로그 postdate(yyyymmdd), 뉴스 pubDate. 오늘 날짜(날짜만 아는 경우)는 수집 시각을 쓴다."""
    pd = item.get("postdate")
    if pd and re.fullmatch(r"\d{8}", str(pd)):
        d = datetime.strptime(str(pd), "%Y%m%d").replace(tzinfo=KST)
        if d.date() >= now.astimezone(KST).date():
            return None
        return (d + timedelta(hours=12)).astimezone(now.tzinfo)
    pub = item.get("pubDate")
    if pub:
        try:
            return parsedate_to_datetime(pub).astimezone(now.tzinfo)
        except (TypeError, ValueError):
            return None
    return None


def parse_items(source: Source, items: list[dict], now: datetime) -> list[RawPost]:
    out: dict[str, RawPost] = {}
    for it in items:
        link = (it.get("link") or it.get("originallink") or "").strip()
        title = clean(it.get("title", ""))
        if not link.startswith(("http://", "https://")) or len(title) < 2:
            continue
        no = hashlib.sha1(link.encode("utf-8")).hexdigest()[:16]
        out[no] = RawPost(source.id, no, title, link, _post_time(it, now))
    return list(out.values())


def fetch_posts(source: Source, queries: list[str], creds: tuple[str, str], *,
                transport: httpx.BaseTransport | None = None, pause: float = 0.25,
                sleep=time.sleep, now: datetime | None = None, max_calls: int = 400) -> list[RawPost]:
    """모든 질의어의 결과를 합친다. 인증 오류·한도 초과는 NaverError."""
    if source.endpoint not in ENDPOINTS:
        raise NaverError(f"알 수 없는 endpoint: {source.endpoint}")
    now = now or utcnow()
    headers = {"X-Naver-Client-Id": creds[0], "X-Naver-Client-Secret": creds[1], "User-Agent": "TrendCheckerBot/0.1"}
    merged: dict[str, RawPost] = {}
    calls = 0
    with httpx.Client(timeout=15, headers=headers, transport=transport) as client:
        for q in queries:
            for page in range(source.pages):
                if calls >= max_calls:
                    log.warning("[%s] 호출 상한(%d)에 도달 — 남은 질의어는 다음 실행에서", source.id, max_calls)
                    return list(merged.values())
                calls += 1
                try:
                    r = client.get(API.format(endpoint=source.endpoint),
                                   params={"query": q, "display": 100, "start": 1 + page * 100, "sort": "date"})
                except httpx.HTTPError as e:
                    raise NaverError(f"네트워크 오류: {e.__class__.__name__}") from e
                if r.status_code == 429:
                    raise NaverError("호출 한도 초과(429)", blocked=True)
                if r.status_code in (401, 403):
                    raise NaverError(f"인증 오류({r.status_code}): Client ID/Secret 과 API 사용 권한을 확인하세요")
                if r.status_code >= 400:
                    # 질의어 하나의 오류(400 등)는 건너뛰고 계속
                    log.warning("[%s] 질의어 %r HTTP %s", source.id, q, r.status_code)
                    break
                try:
                    items = r.json().get("items", [])
                except ValueError:
                    log.warning("[%s] 질의어 %r 응답이 JSON 이 아님", source.id, q)
                    break
                for p in parse_items(source, items, now):
                    merged.setdefault(p.post_no, p)
                if len(items) < 100:
                    break
                sleep(pause)
            sleep(pause)
    return list(merged.values())
