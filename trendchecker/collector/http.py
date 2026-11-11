"""예의 있는 HTTP 클라이언트.

- 호스트별 최소 요청 간격을 지킨다(동시 요청 없음).
- 모든 요청 전에 robots.txt 를 확인한다(실행 단위로 캐시).
- 차단 신호(403, 429, 503, 봇 챌린지 페이지)를 구분해 돌려준다.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from .robots import RobotsPolicy

log = logging.getLogger(__name__)

BOT_NAME = "TrendCheckerBot"
USER_AGENT = f"{BOT_NAME}/0.1 (non-commercial keyword statistics; titles and links only)"

_CHALLENGE_MARKERS = (
    "cf-chl",
    "challenge-platform",
    "just a moment...",
    "attention required! | cloudflare",
)
_META_CHARSET = re.compile(rb"""<meta[^>]+charset=["']?([A-Za-z0-9_\-]+)""", re.I)
_XML_ENCODING = re.compile(rb"""<\?xml[^>]+encoding=["']([A-Za-z0-9_\-]+)["']""", re.I)


class FetchStatus:
    OK = "ok"
    BLOCKED = "blocked"          # 403/429/503/챌린지 → 쉬어야 함
    ROBOTS = "robots_disallowed" # robots.txt 가 금지
    ERROR = "error"              # 네트워크/기타 오류


@dataclass
class FetchResult:
    status: str
    url: str
    text: str = ""
    http_status: int | None = None
    detail: str = ""


def decode_body(content: bytes, header_charset: str | None) -> str:
    """헤더 → XML/HTML 선언 → UTF-8 → CP949 순서로 디코딩."""
    candidates: list[str] = []
    if header_charset:
        candidates.append(header_charset)
    for rx in (_XML_ENCODING, _META_CHARSET):
        m = rx.search(content[:4096])
        if m:
            candidates.append(m.group(1).decode("ascii", "ignore"))
    candidates += ["utf-8", "cp949"]
    for enc in candidates:
        enc = enc.lower()
        if enc in ("euc-kr", "ks_c_5601-1987", "ksc5601"):
            enc = "cp949"  # EUC-KR 상위 호환
        try:
            return content.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", "replace")


def looks_like_challenge(text: str) -> bool:
    head = text[:5000].lower()
    return any(m in head for m in _CHALLENGE_MARKERS)


class PoliteClient:
    def __init__(
        self,
        min_interval_sec: float = 6.0,
        timeout_sec: float = 15.0,
        user_agent: str = USER_AGENT,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.min_interval = min_interval_sec
        self.user_agent = user_agent
        self._sleep = sleep
        self._clock = clock
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotsPolicy] = {}
        self._client = httpx.Client(
            timeout=timeout_sec,
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept-Language": "ko-KR,ko;q=0.9"},
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── 내부
    def _wait_turn(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            remaining = self.min_interval - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request[host] = self._clock()

    def _raw_get(self, url: str) -> httpx.Response:
        host = urlsplit(url).netloc
        self._wait_turn(host)
        return self._client.get(url)

    def robots_for(self, url: str) -> tuple[RobotsPolicy | None, FetchResult | None]:
        """(정책, None) 또는 확인 실패 시 (None, 실패 결과). 성공한 정책만 캐시한다."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin], None
        robots_url = origin + "/robots.txt"
        try:
            resp = self._raw_get(robots_url)
        except httpx.HTTPError as e:
            return None, FetchResult(FetchStatus.ERROR, url, detail=f"robots.txt 확인 실패({e.__class__.__name__}) → 수집 안 함")
        if resp.status_code in (401, 403, 429):
            # RFC 상 4xx 는 '제한 없음'이지만, 봇 차단일 가능성이 커서 보수적으로 차단으로 취급
            return None, FetchResult(FetchStatus.BLOCKED, url, http_status=resp.status_code, detail=f"robots.txt HTTP {resp.status_code}")
        if resp.status_code >= 500:
            return None, FetchResult(FetchStatus.ERROR, url, http_status=resp.status_code, detail=f"robots.txt 서버 오류 {resp.status_code} → 수집 안 함")
        if resp.status_code >= 400:
            policy = RobotsPolicy.allow_everything()  # 404 등: robots.txt 없음 = 제한 없음
        else:
            text = decode_body(resp.content, resp.charset_encoding)
            if looks_like_challenge(text):
                return None, FetchResult(FetchStatus.BLOCKED, url, http_status=resp.status_code, detail="robots.txt 대신 봇 확인 페이지")
            policy = RobotsPolicy.parse(text)
        self._robots[origin] = policy
        return policy, None

    # ── 공개 API
    def fetch(self, url: str) -> FetchResult:
        policy, failure = self.robots_for(url)
        if failure is not None:
            return failure
        if not policy.can_fetch(BOT_NAME, url):
            return FetchResult(FetchStatus.ROBOTS, url, detail="robots.txt 가 이 경로를 허용하지 않음")
        try:
            resp = self._raw_get(url)
        except httpx.HTTPError as e:
            return FetchResult(FetchStatus.ERROR, url, detail=f"{e.__class__.__name__}: {e}")
        if resp.status_code in (403, 429, 503):
            return FetchResult(FetchStatus.BLOCKED, url, http_status=resp.status_code, detail=f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            return FetchResult(FetchStatus.ERROR, url, http_status=resp.status_code, detail=f"HTTP {resp.status_code}")
        text = decode_body(resp.content, resp.charset_encoding)
        if looks_like_challenge(text):
            return FetchResult(FetchStatus.BLOCKED, url, http_status=resp.status_code, detail="봇 확인(챌린지) 페이지")
        return FetchResult(FetchStatus.OK, str(resp.url), text=text, http_status=resp.status_code)
