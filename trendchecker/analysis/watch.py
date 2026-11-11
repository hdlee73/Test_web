"""관심 키워드 매칭. 화면(브라우저)에서도 같은 규칙을 쓰도록 단순하게 유지한다.

규칙: 제목과 검색어를 모두 소문자·공백 제거한 뒤 부분 일치.
대표어 또는 동의어 중 하나라도 있고, 제외어가 하나도 없으면 매칭.
"""
from __future__ import annotations

import re
import unicodedata

from ..config import WatchItem

_WS = re.compile(r"\s+")


def compact(text: str) -> str:
    return _WS.sub("", unicodedata.normalize("NFKC", text or "")).lower()


def matches(item: WatchItem, title: str, source_id: str) -> bool:
    if item.sources and source_id not in item.sources:
        return False
    t = compact(title)
    terms = [compact(x) for x in (item.keyword, *item.synonyms)]
    if not any(term and term in t for term in terms):
        return False
    return not any(compact(x) and compact(x) in t for x in item.exclude)
