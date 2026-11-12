"""같은 공시가 두 소스(DART, KIND)에 있을 때 한 번만 세기.

키 = 회사명 + 보고서명을 정규화한 문자열(시장 표시 [유]·[코], [정정] 같은 대괄호 표시, 숫자 없는 괄호 설명, 공백·가운뎃점 제거).
같은 키이고 날짜(KST)가 같거나 하루 차이면 중복으로 보고, 소스 설정의 dup_of 쪽을 우선한다.
거래소에만 있는 공시(시장조치 등)는 그대로 남는다.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import timedelta

from ..collector.timeutil import KST
from ..config import Source
from ..storage.db import StoredPost

_BRACKET = re.compile(r"\[[^\]]*\]")
_PAREN = re.compile(r"\([^()\d]*\)")  # 숫자가 없는 괄호 설명: (일반법인), (공정공시), (잠정) — 소스마다 붙이는 말이 달라 뺀다
_NOISE = re.compile(r"[\s·ㆍᆞ・\-_,.]+")  # ㆍ(U+318D)는 NFKC 에서 U+119E 로 바뀜


def dedupe_key(title: str) -> str:
    t = unicodedata.normalize("NFKC", title)
    t = _BRACKET.sub("", t)
    t = _PAREN.sub("", t)   # (2026.09)·(제10회차) 처럼 숫자가 든 괄호는 다른 공시를 가르므로 남긴다
    t = _NOISE.sub("", t)
    return t.lower()


def drop_duplicate_disclosures(posts: list[StoredPost], sources: dict[str, Source]) -> tuple[list[StoredPost], int]:
    """dup_of 가 지정된 소스의 글 중, 원본 소스에 같은 공시가 있는 것을 뺀다. (남은 글, 뺀 개수)"""
    originals: dict[str, dict[str, set]] = {}
    for p in posts:
        for s in sources.values():
            if s.dup_of == p.source_id:
                day = p.posted_at.astimezone(KST).date()
                originals.setdefault(s.dup_of, {}).setdefault(dedupe_key(p.title), set()).add(day)
    kept, dropped = [], 0
    for p in posts:
        src = sources.get(p.source_id)
        if src and src.dup_of:
            days = originals.get(src.dup_of, {}).get(dedupe_key(p.title))
            if days:
                d = p.posted_at.astimezone(KST).date()
                if any(abs((d - x).days) <= 1 for x in days):
                    dropped += 1
                    continue
        kept.append(p)
    return kept, dropped
