"""위험 신호어와 공시 유형 분류(상시감시용).

config/risk_terms.yaml 의 신호어를 제목에서 찾는다. 공백·대소문자는 무시하고 부분 일치로 비교한다.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..config import CONFIG_DIR, _load_yaml
from .dictionary import normalize


def _squash(text: str) -> str:
    return "".join(normalize(text).split())


@dataclass(frozen=True)
class RiskHit:
    category: str
    term: str


@dataclass
class RiskMatcher:
    terms: list[tuple[str, str, str]] = field(default_factory=list)       # (분류, 표시용 신호어, 비교용)
    dtypes: list[tuple[str, list[str]]] = field(default_factory=list)      # (유형, 비교용 키워드들)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RiskMatcher":
        m = cls()
        seen: set[str] = set()
        for cat, words in (data.get("risk_categories") or {}).items():
            for w in words or []:
                w = str(w).strip()
                if not w:
                    continue
                if w in seen:
                    raise ValueError(f"위험 신호어가 중복됨: {w}")
                seen.add(w)
                m.terms.append((str(cat), w, _squash(w)))
        for name, words in (data.get("disclosure_types") or {}).items():
            m.dtypes.append((str(name), [_squash(str(w)) for w in words or [] if str(w).strip()]))
        return m

    @property
    def categories(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for cat, w, _ in self.terms:
            out.setdefault(cat, []).append(w)
        return out

    def hits(self, title: str) -> list[RiskHit]:
        t = _squash(title)
        return [RiskHit(cat, w) for cat, w, key in self.terms if key and key in t]

    def disclosure_type(self, title: str) -> str | None:
        t = _squash(title)
        for name, keys in self.dtypes:
            if any(k in t for k in keys):
                return name
        return None


def load_risk_matcher(path: Path | None = None) -> RiskMatcher:
    p = path or CONFIG_DIR / "risk_terms.yaml"
    if not p.exists():
        return RiskMatcher()
    return RiskMatcher.from_dict(_load_yaml(p))


def risk_summary(analyzed: list, now: datetime, windows: dict[str, datetime], top_n: int = 5) -> dict:
    """windows: 이름 → 시작 시각. 분류별·신호어별 건수와 출처 구분(뉴스/공시/게시판)별 건수."""
    out: dict[str, Any] = {}
    for name, start in windows.items():
        cats: dict[str, dict] = {}
        for a in analyzed:
            if a.post.posted_at < start or not a.risks:
                continue
            counted: set[str] = set()
            for h in a.risks:
                c = cats.setdefault(h.category, {"posts": 0, "by_kind": Counter(), "terms": {}})
                if h.category not in counted:  # 분류별 건수는 글 하나당 1회(신호어가 둘 겹쳐도)
                    counted.add(h.category)
                    c["posts"] += 1
                    c["by_kind"][a.category] += 1
                t = c["terms"].setdefault(h.term, {"term": h.term, "posts": 0, "by_kind": Counter(), "posts_list": []})
                t["posts"] += 1
                t["by_kind"][a.category] += 1
                t["posts_list"].append(a)
        res = {}
        for cat, c in cats.items():
            terms = []
            for t in c["terms"].values():
                top = sorted(t["posts_list"], key=lambda a: a.post.posted_at, reverse=True)[:top_n]
                terms.append({"term": t["term"], "posts": t["posts"], "by_kind": dict(t["by_kind"]),
                              "top": [a.post.uid for a in top]})
            terms.sort(key=lambda x: (-x["posts"], x["term"]))
            res[cat] = {"posts": c["posts"], "by_kind": dict(c["by_kind"]), "terms": terms}
        out[name] = dict(sorted(res.items(), key=lambda kv: -kv[1]["posts"]))
    return out


def disclosure_summary(analyzed: list, windows: dict[str, datetime], top_n: int = 5) -> dict:
    """공시 유형별 건수(중요 공시)."""
    out: dict[str, Any] = {}
    for name, start in windows.items():
        by: dict[str, list] = defaultdict(list)
        for a in analyzed:
            if a.category == "disclosure" and a.dtype and a.post.posted_at >= start:
                by[a.dtype].append(a)
        out[name] = {
            t: {"posts": len(v), "top": [a.post.uid for a in sorted(v, key=lambda a: a.post.posted_at, reverse=True)[:top_n]]}
            for t, v in sorted(by.items(), key=lambda kv: -len(kv[1]))
        }
    return out


def risk_spikes(analyzed: list, now: datetime, baseline_days: int = 4, min_recent: int = 2, min_ratio: float = 2.0) -> list[dict]:
    """최근 24시간 신호어 건수를 직전 baseline_days 일 평균과 비교."""
    recent_from = now - timedelta(hours=24)
    base_from = recent_from - timedelta(days=baseline_days)
    recent: Counter[tuple[str, str]] = Counter()
    base: Counter[tuple[str, str]] = Counter()
    have_base = any(a.post.posted_at < recent_from for a in analyzed)
    for a in analyzed:
        t = a.post.posted_at
        keys = {(h.category, h.term) for h in a.risks}
        if t >= recent_from:
            recent.update(keys)
        elif t >= base_from:
            base.update(keys)
    out = []
    for (cat, term), c in recent.items():
        avg = base[(cat, term)] / baseline_days
        ratio = (c + 1) / (avg + 1)
        if c >= min_recent and ratio >= min_ratio:
            out.append({"term": term, "category": cat, "recent_24h": c, "baseline_daily_avg": round(avg, 2),
                        "ratio": round(ratio, 2), "new": base[(cat, term)] == 0})
    out.sort(key=lambda x: (-x["ratio"], -x["recent_24h"]))
    return out if have_base else []
