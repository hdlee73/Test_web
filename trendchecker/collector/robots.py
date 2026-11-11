"""robots.txt 해석기.

파이썬 표준 urllib.robotparser 는 경로의 `*` 와 `$` 를 지원하지 않아
`Disallow: /*?` 같은 규칙을 놓친다. 여기서는 RFC 9309 방식으로 해석한다.
- 내 User-agent 이름이 포함된 그룹이 있으면 그 그룹만, 없으면 `*` 그룹을 쓴다.
- 경로가 가장 길게 일치하는 규칙이 이긴다. 길이가 같으면 Allow 가 이긴다.
- robots.txt 가 없으면(4xx) 전부 허용, 서버 오류(5xx)나 접속 실패면 전부 금지로 본다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, pattern)


def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    parts = [re.escape(p) for p in pattern.split("*")]
    return re.compile("^" + ".*".join(parts) + ("$" if anchored else ""))


class RobotsPolicy:
    def __init__(self, groups: list[_Group], *, allow_all: bool = False, deny_all: bool = False):
        self._groups = groups
        self.allow_all = allow_all
        self.deny_all = deny_all

    @classmethod
    def parse(cls, text: str) -> "RobotsPolicy":
        groups: list[_Group] = []
        current: _Group | None = None
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "user-agent":
                if current is None or not last_was_agent:
                    current = _Group()
                    groups.append(current)
                current.agents.append(value.lower())
                last_was_agent = True
            elif key in ("allow", "disallow"):
                last_was_agent = False
                if current is None:
                    continue
                if key == "disallow" and value == "":
                    continue  # 빈 Disallow = 제한 없음
                current.rules.append((key == "allow", value))
            else:
                last_was_agent = False  # sitemap, crawl-delay 등은 그룹을 끊지 않지만 agent 연속은 끊는다
        return cls(groups)

    @classmethod
    def allow_everything(cls) -> "RobotsPolicy":
        return cls([], allow_all=True)

    @classmethod
    def deny_everything(cls) -> "RobotsPolicy":
        return cls([], deny_all=True)

    def _rules_for(self, agent: str) -> list[tuple[bool, str]]:
        agent = agent.lower()
        specific = [g for g in self._groups if any(a != "*" and a in agent for a in g.agents)]
        if specific:
            return [r for g in specific for r in g.rules]
        return [r for g in self._groups if "*" in g.agents for r in g.rules]

    def can_fetch(self, agent: str, url: str) -> bool:
        if self.deny_all:
            return False
        if self.allow_all:
            return True
        parts = urlsplit(url)
        path = unquote(parts.path or "/")
        if parts.query:
            path += "?" + unquote(parts.query)
        best_len = -1
        best_allow = True
        for allow, pattern in self._rules_for(agent):
            if not _pattern_to_regex(pattern).match(path):
                continue
            plen = len(pattern)
            if plen > best_len or (plen == best_len and allow):
                best_len = plen
                best_allow = allow
        return best_allow
