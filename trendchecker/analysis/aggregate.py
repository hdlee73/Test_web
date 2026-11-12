"""오늘 / 최근 3일 / 최근 5일 키워드 집계와 급상승 지표."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..collector.timeutil import kst_midnight
from ..config import Source
from ..storage.db import StoredPost
from .dictionary import Entry, FinanceMatcher

WINDOWS = {"today": 0, "3d": 2, "5d": 4}  # KST 자정 기준 며칠 전부터
TOP_POSTS = 5


@dataclass
class AnalyzedPost:
    post: StoredPost
    keywords: list[Entry]
    is_finance: bool
    category: str = "board"                # news | disclosure | board
    risks: list = field(default_factory=list)  # RiskHit 목록
    dtype: str | None = None               # 공시 유형(공시일 때만)


def analyze_posts(posts: list[StoredPost], matcher: FinanceMatcher, sources: dict[str, Source],
                  exclude: frozenset[str] | set[str] = frozenset(), risk=None) -> list[AnalyzedPost]:
    """exclude: 너무 광범위해 집계에서 뺄 대표어. 글은 여전히 '금융 관련'으로 센다."""
    out = []
    for p in posts:
        found = matcher.keywords(p.title)
        kws = [e for e in found if e.name not in exclude]
        src = sources.get(p.source_id)
        cat = src.category if src else "board"
        out.append(AnalyzedPost(
            p, kws, bool(found) or bool(src and src.finance_board), cat,
            risk.hits(p.title) if risk else [],
            risk.disclosure_type(p.title) if risk and cat == "disclosure" else None))
    return out


def window_start(name: str, now: datetime) -> datetime:
    return kst_midnight(now, WINDOWS[name])


def aggregate(analyzed: list[AnalyzedPost], now: datetime) -> dict:
    """windows[name] = {total_posts, finance_posts, by_source, keywords:[...]}"""
    result = {}
    for name in WINDOWS:
        start = window_start(name, now)
        in_win = [a for a in analyzed if a.post.posted_at >= start]
        total_by_src: Counter[str] = Counter(a.post.source_id for a in in_win)
        kw_count: Counter[str] = Counter()
        kw_src: dict[str, Counter[str]] = defaultdict(Counter)
        kw_entry: dict[str, Entry] = {}
        kw_posts: dict[str, list[AnalyzedPost]] = defaultdict(list)
        for a in in_win:
            for e in a.keywords:  # 글 하나당 1회
                kw_count[e.name] += 1
                kw_src[e.name][a.post.source_id] += 1
                kw_entry[e.name] = e
                kw_posts[e.name].append(a)
        n_sources = max(1, len(total_by_src))
        keywords = []
        for name_, cnt in kw_count.items():
            # 종합 점수: 게시판별 '천 건당 언급 수'의 평균 → 글이 많은 게시판의 독점을 줄임
            share = sum(c / total_by_src[s] for s, c in kw_src[name_].items()) / n_sources
            top = sorted(kw_posts[name_], key=lambda a: a.post.posted_at, reverse=True)[:TOP_POSTS]
            keywords.append({
                "keyword": name_,
                "category": kw_entry[name_].category,
                "kind": kw_entry[name_].kind,
                "posts": cnt,
                "score": round(share * 1000, 2),
                "sources": dict(kw_src[name_].most_common()),
                "top": [a.post.uid for a in top],
            })
        keywords.sort(key=lambda k: (-k["posts"], -k["score"], k["keyword"]))
        result[name] = {
            "from": start,
            "total_posts": len(in_win),
            "finance_posts": sum(1 for a in in_win if a.is_finance),
            "by_source": dict(total_by_src.most_common()),
            "keywords": keywords,
        }
    return result


def daily_series(analyzed: list[AnalyzedPost], now: datetime, days: int = 5) -> dict[str, list[int]]:
    """키워드별 KST 일자별 게시물 수 (오래된 날 → 오늘)."""
    starts = [kst_midnight(now, d) for d in range(days - 1, -1, -1)]
    series: dict[str, list[int]] = defaultdict(lambda: [0] * days)
    for a in analyzed:
        t = a.post.posted_at
        if t < starts[0]:
            continue
        idx = max(i for i, s in enumerate(starts) if t >= s)
        for e in a.keywords:
            series[e.name][idx] += 1
    return dict(series)


def spikes(analyzed: list[AnalyzedPost], now: datetime, baseline_days: int = 4,
           min_recent: int = 3, min_ratio: float = 2.0) -> list[dict]:
    """최근 24시간 언급 수를 직전 baseline_days 일 평균과 비교."""
    recent_from = now - timedelta(hours=24)
    base_from = recent_from - timedelta(days=baseline_days)
    recent: Counter[str] = Counter()
    base: Counter[str] = Counter()
    have_base = any(a.post.posted_at < recent_from for a in analyzed)
    for a in analyzed:
        t = a.post.posted_at
        names = {e.name for e in a.keywords}
        if t >= recent_from:
            recent.update(names)
        elif t >= base_from:
            base.update(names)
    out = []
    for k, c in recent.items():
        avg = base[k] / baseline_days
        ratio = (c + 1) / (avg + 1)
        if c >= min_recent and ratio >= min_ratio:
            out.append({"keyword": k, "recent_24h": c, "baseline_daily_avg": round(avg, 2), "ratio": round(ratio, 2),
                        "new": base[k] == 0})
    out.sort(key=lambda x: (-x["ratio"], -x["recent_24h"]))
    return out if have_base else []
