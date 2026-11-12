"""광고·홍보성 글 의심 판정(제목만 사용). 설정: config/ad_terms.yaml"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import CONFIG_DIR, _load_yaml
from .dedupe import dedupe_key
from .dictionary import normalize


def _squash(text: str) -> str:
    return "".join(normalize(text).split())


@dataclass
class AdMatcher:
    apply_to: set[str] = field(default_factory=lambda: {"blog"})
    strong: list[str] = field(default_factory=list)
    weak: list[str] = field(default_factory=list)
    patterns: list[re.Pattern[str]] = field(default_factory=list)
    repeat_min: int = 3

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AdMatcher":
        return cls(
            apply_to=set(d.get("apply_to") or ["blog"]),
            strong=[_squash(str(x)) for x in d.get("strong") or [] if str(x).strip()],
            weak=[_squash(str(x)) for x in d.get("weak") or [] if str(x).strip()],
            patterns=[re.compile(str(x)) for x in d.get("patterns") or []],
            repeat_min=int(d.get("repeat_title_min") or 3),
        )

    def is_ad(self, title: str) -> bool:
        raw = normalize(title)
        t = _squash(title)
        if any(s in t for s in self.strong):
            return True
        if any(p.search(raw) for p in self.patterns):
            return True
        return len({w for w in self.weak if w in t}) >= 2

    def repeated_titles(self, titles: list[str]) -> set[str]:
        """같은 제목이 repeat_min 번 이상이면 그 정규화 키들."""
        c = Counter(dedupe_key(t) for t in titles)
        return {k for k, n in c.items() if k and n >= self.repeat_min}


def load_ad_matcher(path: Path | None = None) -> AdMatcher:
    p = path or CONFIG_DIR / "ad_terms.yaml"
    return AdMatcher.from_dict(_load_yaml(p)) if p.exists() else AdMatcher()
