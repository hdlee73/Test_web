"""게시판 순회 수집."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..config import Settings, Source, load_naver_queries
from ..storage.db import SourceState, Store
from .adapters import parse
from .http import FetchStatus, PoliteClient
from .naver import NaverError, credentials, fetch_posts
from .timeutil import from_iso, to_iso, utcnow

log = logging.getLogger(__name__)

# 연속 차단이 이 횟수에 도달하면 'disabled' 로 표시(수동 확인 전까지 백오프 최대치 유지)
DISABLE_AFTER = 4


@dataclass
class CollectReport:
    source_id: str
    status: str
    fetched: int = 0
    new: int = 0
    detail: str = ""


def _in_backoff(st: SourceState, now: datetime) -> bool:
    return bool(st.blocked_until) and from_iso(st.blocked_until) > now


def collect_source(client: PoliteClient, store: Store, src: Source, backoff_hours: tuple[float, ...],
                   now: datetime | None = None) -> CollectReport:
    now = now or utcnow()
    st = store.get_state(src.id)
    if _in_backoff(st, now):
        return CollectReport(src.id, "backoff", detail=f"{st.blocked_until} 까지 대기")

    st.last_attempt = to_iso(now)
    try:
        res = client.fetch(src.url)
        if res.status == FetchStatus.OK:
            posts = parse(src, res.url, res.text)
            new = store.upsert_posts(posts, now)
            st.status = "ok" if posts else "empty"
            st.consecutive_blocks = 0
            st.blocked_until = None
            st.last_success = to_iso(now)
            st.last_count = len(posts)
            st.last_new = new
            st.last_detail = "" if posts else "목록에서 게시물을 찾지 못함(페이지 구조 변경 가능성)"
            if not posts:
                log.warning("[%s] 게시물 0건 — post_pattern 점검 필요", src.id)
            return CollectReport(src.id, st.status, len(posts), new, st.last_detail or "")
        if res.status == FetchStatus.ROBOTS:
            st.status = "robots_disallowed"
            st.last_detail = res.detail
            log.info("[%s] robots.txt 금지 → 건너뜀", src.id)
            return CollectReport(src.id, st.status, detail=res.detail)
        if res.status == FetchStatus.BLOCKED:
            st.consecutive_blocks += 1
            idx = min(st.consecutive_blocks, len(backoff_hours)) - 1
            st.blocked_until = to_iso(now + timedelta(hours=backoff_hours[idx]))
            st.status = "disabled" if st.consecutive_blocks >= DISABLE_AFTER else "blocked"
            st.last_detail = res.detail
            log.warning("[%s] 차단 신호(%s) → %s 까지 쉼", src.id, res.detail, st.blocked_until)
            return CollectReport(src.id, st.status, detail=res.detail)
        st.status = "error"
        st.last_detail = res.detail
        log.error("[%s] 수집 오류: %s", src.id, res.detail)
        return CollectReport(src.id, "error", detail=res.detail)
    except Exception as e:  # 한 게시판의 실패가 전체를 멈추지 않도록
        st.status = "error"
        st.last_detail = f"{e.__class__.__name__}: {e}"[:300]
        log.exception("[%s] 처리 중 예외", src.id)
        return CollectReport(src.id, "error", detail=st.last_detail)
    finally:
        store.save_state(st)


def collect_naver(store: Store, src: Source, backoff_hours: tuple[float, ...], *, env=None, transport=None,
                  now: datetime | None = None, queries: list[str] | None = None, sleep=None) -> CollectReport:
    """네이버 검색 API 수집(robots.txt 없음, 인증 키 필요)."""
    import time as _time

    now = now or utcnow()
    st = store.get_state(src.id)
    if _in_backoff(st, now):
        return CollectReport(src.id, "backoff", detail=f"{st.blocked_until} 까지 대기")
    st.last_attempt = to_iso(now)
    try:
        creds = credentials(env)
        if creds is None:
            st.status = "no_key"
            st.last_detail = "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 이 설정되지 않음"
            return CollectReport(src.id, st.status, detail=st.last_detail)
        qs = queries if queries is not None else load_naver_queries()
        if not qs:
            st.status = "error"
            st.last_detail = "config/naver_queries.txt 에 질의어가 없음"
            return CollectReport(src.id, "error", detail=st.last_detail)
        try:
            posts = fetch_posts(src, qs, creds, transport=transport, now=now, sleep=sleep or _time.sleep)
        except NaverError as e:
            if e.blocked:
                st.consecutive_blocks += 1
                idx = min(st.consecutive_blocks, len(backoff_hours)) - 1
                st.blocked_until = to_iso(now + timedelta(hours=backoff_hours[idx]))
                st.status = "blocked"
            else:
                st.status = "error"
            st.last_detail = str(e)[:300]
            log.error("[%s] %s", src.id, e)
            return CollectReport(src.id, st.status, detail=st.last_detail)
        new = store.upsert_posts(posts, now)
        st.status = "ok" if posts else "empty"
        st.consecutive_blocks = 0
        st.blocked_until = None
        st.last_success = to_iso(now)
        st.last_count = len(posts)
        st.last_new = new
        st.last_detail = "" if posts else "검색 결과가 없음"
        return CollectReport(src.id, st.status, len(posts), new, st.last_detail or "")
    except Exception as e:
        st.status = "error"
        st.last_detail = f"{e.__class__.__name__}: {e}"[:300]
        log.exception("[%s] 처리 중 예외", src.id)
        return CollectReport(src.id, "error", detail=st.last_detail)
    finally:
        store.save_state(st)


def collect_all(settings: Settings, store: Store, client: PoliteClient | None = None,
                only: set[str] | None = None) -> list[CollectReport]:
    own = client is None
    client = client or PoliteClient(settings.defaults.min_interval_sec, settings.defaults.timeout_sec)
    reports = []
    try:
        for src in settings.sources:
            if not src.enabled or (only and src.id not in only):
                continue
            if src.type == "naver_api":
                r = collect_naver(store, src, settings.defaults.backoff_hours)
            else:
                r = collect_source(client, store, src, settings.defaults.backoff_hours)
            log.info("[%s] %s 수집 %d건, 신규 %d건 %s", src.id, r.status, r.fetched, r.new, r.detail)
            reports.append(r)
    finally:
        if own:
            client.close()
    return reports
