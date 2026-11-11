"""사전에 없는 '새 금융 키워드 후보'를 Kiwi 형태소 분석으로 찾는다.

금융글(사전 매칭 1개 이상 또는 금융 게시판)의 제목에서 명사를 뽑아
사전에 없는 것 중 여러 글에 나온 것을 후보로 돌려준다. 운영자가 보고 사전에 추가한다.
Kiwi 가 설치되어 있지 않으면 빈 목록을 돌려준다.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Iterable

log = logging.getLogger(__name__)

_NOUN_TAGS = {"NNG", "NNP", "SL"}
_kiwi = None
_kiwi_failed = False


def _get_kiwi(user_words: Iterable[str]):
    global _kiwi, _kiwi_failed
    if _kiwi is not None or _kiwi_failed:
        return _kiwi
    try:
        from kiwipiepy import Kiwi
    except ImportError:
        log.warning("kiwipiepy 가 없어 새 키워드 후보 추출을 건너뜀")
        _kiwi_failed = True
        return None
    k = Kiwi()
    for w in user_words:
        if " " not in w and 2 <= len(w) <= 20:
            try:
                k.add_user_word(w, "NNP")
            except Exception:  # 일부 특수문자 포함 단어는 등록 실패 가능
                pass
    _kiwi = k
    return k


def find_candidates(titles: list[str], known: set[str], stopwords: set[str],
                    min_docs: int = 3, limit: int = 50) -> list[dict]:
    kiwi = _get_kiwi(known)
    if kiwi is None or not titles:
        return []
    known_l = {k.lower() for k in known}
    stop_l = {s.lower() for s in stopwords}
    doc_freq: Counter[str] = Counter()
    for tokens in kiwi.tokenize(titles):
        seen = set()
        for t in tokens:
            if t.tag not in _NOUN_TAGS:
                continue
            w = t.form.strip()
            wl = w.lower()
            if len(w) < 2 or wl in known_l or wl in stop_l or w.isdigit():
                continue
            if t.tag == "SL" and len(w) < 3:
                continue  # 짧은 영문 조각 제외
            seen.add(w)
        doc_freq.update(seen)
    return [{"word": w, "posts": c} for w, c in doc_freq.most_common() if c >= min_docs][:limit]
