"""금융 사전 매칭.

- 겹치는 표현은 가장 긴 것이 이긴다(예: "기준금리" 안의 "금리"는 따로 세지 않음).
- 영문 별칭은 대소문자 무시, 앞뒤가 영문/숫자이면 매칭하지 않는다("KB" ≠ "KBO").
- ambiguous 표현은 같은 글에 다른 금융 표현(사전 항목 또는 context_words)이 있을 때만 인정한다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

_WS = re.compile(r"\s+")
_ASCII_WORD = re.compile(r"[A-Za-z0-9]")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = re.sub(r"(.)\1{3,}", r"\1\1\1", t)  # ㅋㅋㅋㅋㅋ → ㅋㅋㅋ
    return _WS.sub(" ", t).strip()


@dataclass(frozen=True)
class Entry:
    name: str
    category: str
    kind: str  # company | topic


@dataclass
class _Alias:
    text: str
    entry: Entry
    ambiguous: bool
    ascii_edge: bool  # 앞/뒤 경계 검사 필요(영문 시작/끝)
    pattern: re.Pattern[str] = field(init=False)
    lower: str = field(init=False)

    def __post_init__(self):
        self.lower = self.text.lower()
        self.pattern = re.compile(re.escape(self.text), re.I if self.text.isascii() else 0)


@dataclass(frozen=True)
class Match:
    entry: Entry
    alias: str
    start: int
    end: int
    ambiguous: bool


class FinanceMatcher:
    def __init__(self, data: dict[str, Any]):
        self.entries: dict[str, Entry] = {}
        self._aliases: list[_Alias] = []
        for kind, key in (("company", "companies"), ("topic", "topics")):
            for raw in data.get(key) or []:
                e = Entry(str(raw["name"]), str(raw.get("category", "")), kind)
                if e.name in self.entries:
                    raise ValueError(f"사전에 중복된 대표어: {e.name}")
                self.entries[e.name] = e
                for a in raw.get("aliases") or []:
                    self._add(str(a), e, False)
                for a in raw.get("ambiguous") or []:
                    self._add(str(a), e, True)
        self.context_words = [normalize(w) for w in data.get("context_words") or [] if str(w).strip()]
        # 긴 별칭 먼저 → 같은 시작점에서는 긴 것이 이김
        self._aliases.sort(key=lambda a: -len(a.text))

    def _add(self, text: str, entry: Entry, ambiguous: bool) -> None:
        t = normalize(text)
        if not t:
            return
        edge = bool(_ASCII_WORD.match(t[0])) or bool(_ASCII_WORD.match(t[-1]))
        self._aliases.append(_Alias(t, entry, ambiguous, edge))

    @property
    def all_alias_texts(self) -> set[str]:
        return {a.text for a in self._aliases}

    def _raw_matches(self, text: str) -> list[Match]:
        found: list[Match] = []
        lowered = text.lower()
        for a in self._aliases:
            if a.lower not in lowered:  # 빠른 사전 검사
                continue
            for m in a.pattern.finditer(text):
                s, e = m.start(), m.end()
                if a.ascii_edge:
                    if _ASCII_WORD.match(a.text[0]) and s > 0 and _ASCII_WORD.match(text[s - 1]):
                        continue
                    if _ASCII_WORD.match(a.text[-1]) and e < len(text) and _ASCII_WORD.match(text[e]):
                        continue
                found.append(Match(a.entry, a.text, s, e, a.ambiguous))
        # 가장 긴 것 우선. 이미 잡힌 표현 안에 완전히 들어가는 짧은 표현은 버린다
        # (부분적으로만 겹치면 둘 다 인정: "기준금리 인하" → 기준금리 + 금리인하)
        found.sort(key=lambda m: (-(m.end - m.start), m.start))
        taken: list[Match] = []
        for m in found:
            if not any(t.start <= m.start and m.end <= t.end for t in taken):
                taken.append(m)
        return sorted(taken, key=lambda m: m.start)

    def match(self, text: str) -> list[Match]:
        text = normalize(text)
        ms = self._raw_matches(text)
        if not any(m.ambiguous for m in ms):
            return ms
        # 문맥 판단 시 모호한 표현 자신은 지우고 본다("코인노래방"의 '코인'이 문맥어로 잡히지 않게)
        rest = text
        for m in sorted((m for m in ms if m.ambiguous), key=lambda m: -m.start):
            rest = rest[: m.start] + " " + rest[m.end :]
        has_context = any(not m.ambiguous for m in ms) or any(w in rest for w in self.context_words)
        return [m for m in ms if not m.ambiguous or has_context]

    def keywords(self, text: str) -> list[Entry]:
        """글 하나에서 나온 대표어 목록(중복 제거, 등장 순서)."""
        seen: dict[str, Entry] = {}
        for m in self.match(text):
            seen.setdefault(m.entry.name, m.entry)
        return list(seen.values())
