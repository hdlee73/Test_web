"""목록 페이지/RSS 에서 게시물(제목, 링크, 시각)만 뽑는다."""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

from ..config import Source
from .timeutil import KST

_WS = re.compile(r"\s+")
_TRAILING_COUNT = re.compile(r"\s*[\[\(]\s*\d+\s*[\]\)]\s*$")
_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.I)
MAX_TITLE = 200


@dataclass(frozen=True)
class RawPost:
    source_id: str
    post_no: str
    title: str
    url: str
    posted_at: datetime | None  # UTC, 알 수 없으면 None(수집 시각으로 대체)


def clean_title(text: str) -> str:
    t = html.unescape(text or "")
    t = _WS.sub(" ", t).strip()
    t = _TRAILING_COUNT.sub("", t).strip()
    return t[:MAX_TITLE]


def _post_no(source: Source, url: str) -> str | None:
    m = source.post_pattern.search(url)
    if not m:
        return None
    for g in m.groups():
        if g:
            return g
    return m.group(0)


def _canonical(source: Source, post_no: str, absolute: str) -> str:
    if source.link_template:
        return source.link_template.format(id=post_no)
    return absolute


class _LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._stack: list[tuple[str, list[str]]] = []
        self._skip = 0  # script/style 내부

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            title_attr = dict(attrs).get("title") or ""
            self._stack.append((href, [title_attr] if title_attr else []))
            self._stack[-1][1].append("\x00")  # 본문 텍스트 시작 표시

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag == "a" and self._stack:
            href, parts = self._stack.pop()
            # title 속성이 있으면 후보로, 본문 텍스트도 후보로 둔다
            if "\x00" in parts:
                i = parts.index("\x00")
                attr_text = "".join(parts[:i])
                body_text = "".join(parts[i + 1 :])
            else:
                attr_text, body_text = "", "".join(parts)
            self.links.append((href, body_text if clean_title(body_text) else attr_text))

    def handle_data(self, data):
        if self._skip:
            return
        for _, parts in self._stack:
            parts.append(data)


def parse_link_list(source: Source, page_url: str, text: str) -> list[RawPost]:
    collector = _LinkCollector()
    collector.feed(text)
    collector.close()
    best: dict[str, RawPost] = {}
    for href, raw_title in collector.links:
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        absolute = urljoin(page_url, html.unescape(href))
        no = _post_no(source, href) or _post_no(source, absolute)
        if not no:
            continue
        title = clean_title(raw_title)
        if len(title) < 2 or title.isdigit():
            continue  # 댓글 수 링크, 번호 링크 등
        prev = best.get(no)
        if prev is None or len(title) > len(prev.title):
            best[no] = RawPost(source.id, no, title, _canonical(source, no, absolute), None)
    return list(best.values())


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        # 시간대가 없으면 한국 사이트이므로 KST 로 간주
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(timezone.utc)


def parse_rss(source: Source, text: str) -> list[RawPost]:
    body = _XML_DECL.sub("", text, count=1).lstrip("﻿")
    root = ET.fromstring(body)
    posts: dict[str, RawPost] = {}
    for item in root.iter("item"):
        title = clean_title(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        link = html.unescape(link)
        no = _post_no(source, link)
        if not no or len(title) < 2:
            continue
        posts[no] = RawPost(
            source.id,
            no,
            title,
            _canonical(source, no, link.replace("http://", "https://", 1)),
            _parse_date(item.findtext("pubDate")),
        )
    return list(posts.values())


def parse(source: Source, page_url: str, text: str) -> list[RawPost]:
    if source.type == "rss":
        return parse_rss(source, text)
    return parse_link_list(source, page_url, text)
