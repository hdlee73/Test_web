"""설정 파일 로딩."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

VALID_TYPES = {"rss", "link_regex", "naver_api", "dart_api", "dart_funding"}
VALID_CATEGORIES = {"news", "disclosure", "board", "blog"}


@dataclass(frozen=True)
class Source:
    id: str
    site: str
    board: str
    type: str
    url: str
    post_pattern: re.Pattern[str]
    link_template: str | None = None
    finance_board: bool = False
    enabled: bool = True
    verified: str = "unknown"
    endpoint: str | None = None      # naver_api: blog | cafearticle | news
    pages: int = 1                   # naver_api: 질의어당 읽을 페이지 수(1페이지 = 최대 100건)
    category: str = "board"          # news | disclosure | board | blog (화면의 카테고리)
    off_reason: str = ""             # enabled=false 인 이유(게시판 상태 화면에 표시)
    queries_file: str | None = None  # naver_api: config/ 아래 질의어 파일(기본 naver_queries.txt)
    dup_of: str | None = None        # 같은 글이 이 source 에도 있으면 이쪽을 버린다(공시 이중 집계 방지)

    @property
    def label(self) -> str:
        return f"{self.site} {self.board}"


@dataclass(frozen=True)
class Defaults:
    min_interval_sec: float = 6.0
    timeout_sec: float = 15.0
    backoff_hours: tuple[float, ...] = (1, 3, 6, 24)


@dataclass(frozen=True)
class WatchItem:
    keyword: str
    synonyms: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


@dataclass
class Settings:
    defaults: Defaults
    sources: list[Source] = field(default_factory=list)


def _load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_sources(path: Path | None = None) -> Settings:
    data = _load_yaml(path or CONFIG_DIR / "sources.yaml")
    d = data.get("defaults") or {}
    defaults = Defaults(
        min_interval_sec=float(d.get("min_interval_sec", 6)),
        timeout_sec=float(d.get("timeout_sec", 15)),
        backoff_hours=tuple(float(x) for x in d.get("backoff_hours", (1, 3, 6, 24))) or (1,),
    )
    seen: set[str] = set()
    sources: list[Source] = []
    for raw in data.get("sources") or []:
        sid = str(raw["id"])
        if sid in seen:
            raise ValueError(f"중복된 source id: {sid}")
        seen.add(sid)
        stype = str(raw.get("type", "link_regex"))
        if stype not in VALID_TYPES:
            raise ValueError(f"{sid}: 알 수 없는 type {stype}")
        cat = str(raw.get("category", "board"))
        if cat not in VALID_CATEGORIES:
            raise ValueError(f"{sid}: 알 수 없는 category {cat}")
        sources.append(
            Source(
                id=sid,
                site=str(raw.get("site", sid)),
                board=str(raw.get("board", "")),
                type=stype,
                url=str(raw["url"]),
                post_pattern=re.compile(str(raw.get("post_pattern", "."))),
                link_template=raw.get("link_template"),
                finance_board=bool(raw.get("finance_board", False)),
                enabled=bool(raw.get("enabled", True)),
                verified=str(raw.get("verified", "unknown")),
                endpoint=raw.get("endpoint"),
                pages=max(1, min(10, int(raw.get("pages", 1)))),
                category=cat,
                off_reason=str(raw.get("off_reason", "")),
                queries_file=raw.get("queries_file"),
                dup_of=raw.get("dup_of"),
            )
        )
    ids = {x.id for x in sources}
    for x in sources:
        if x.dup_of and x.dup_of not in ids:
            raise ValueError(f"{x.id}: dup_of 가 없는 source: {x.dup_of}")
    return Settings(defaults=defaults, sources=sources)


def load_dictionary(path: Path | None = None) -> dict[str, Any]:
    return _load_yaml(path or CONFIG_DIR / "finance_dict.yaml")


def load_watchlist(path: Path | None = None) -> list[WatchItem]:
    p = path or CONFIG_DIR / "watchlist.yaml"
    if not p.exists():
        return []
    items = []
    for raw in (_load_yaml(p).get("watchlist") or []):
        kw = str(raw.get("keyword", "")).strip()
        if not kw:
            continue
        items.append(
            WatchItem(
                keyword=kw,
                synonyms=tuple(str(x).strip() for x in raw.get("synonyms") or [] if str(x).strip()),
                exclude=tuple(str(x).strip() for x in raw.get("exclude") or [] if str(x).strip()),
                sources=tuple(str(x) for x in raw.get("sources") or []),
            )
        )
    return items


def load_naver_queries(path: Path | None = None, name: str | None = None) -> list[str]:
    p = path or CONFIG_DIR / (name or "naver_queries.txt")
    if not p.exists():
        return []
    out: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line not in out:
            out.append(line)
    return out


def load_excluded_keywords(path: Path | None = None) -> set[str]:
    """집계에서 뺄 광범위 대표어(config/exclude_keywords.txt)."""
    p = path or CONFIG_DIR / "exclude_keywords.txt"
    if not p.exists():
        return set()
    out = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(line)
    return out


def load_stopwords(path: Path | None = None) -> set[str]:
    p = path or CONFIG_DIR / "stopwords.txt"
    if not p.exists():
        return set()
    words = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.add(line)
    return words
