"""웹 화면용 정적 JSON 산출.

out_dir/
  meta.json            생성 시각, 게시판 목록과 상태, 공지
  trends.json          오늘/3일/5일 키워드 순위, 일자별 추이, 급상승
  posts-YYYYMMDD.json  KST 일자별 게시물(제목·링크·시각·키워드) — 브라우저에서 관심 키워드 검색용
  watchlist.json       config/watchlist.yaml 매칭 결과
  candidates.json      사전에 없는 새 키워드 후보(운영자용)
파일은 임시 파일에 쓴 뒤 교체하여, 쓰는 도중 화면이 깨진 파일을 읽지 않게 한다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..analysis.aggregate import AnalyzedPost, aggregate, daily_series, spikes
from ..analysis.watch import matches
from ..collector.timeutil import KST, kst_midnight, to_iso
from ..config import Settings, WatchItem
from ..storage.db import SourceState

SCHEMA_VERSION = 1
NOTICE = ("각 게시판의 공개 목록에서 제목과 링크만 수집해 키워드를 집계합니다. "
          "게시물 본문과 작성자 정보는 저장하지 않으며, 모든 글의 권리는 원 게시판과 작성자에게 있습니다.")


def _write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=_default), encoding="utf-8")
    os.replace(tmp, path)


def _default(o):
    if isinstance(o, datetime):
        return to_iso(o)
    raise TypeError(type(o))


def _post_obj(a: AnalyzedPost) -> dict:
    p = a.post
    return {
        "id": p.uid,
        "s": p.source_id,
        "t": p.title,
        "u": p.url,
        "at": to_iso(p.posted_at),
        "x": 1 if p.time_exact else 0,
        "k": [e.name for e in a.keywords],
        "f": 1 if a.is_finance else 0,
    }


def export_all(out_dir: Path, settings: Settings, states: list[SourceState], analyzed: list[AnalyzedPost],
               watchlist: list[WatchItem], candidates: list[dict], now: datetime, days: int = 5) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    start = kst_midnight(now, days - 1)
    recent = [a for a in analyzed if a.post.posted_at >= start]

    # meta
    state_by_id = {s.source_id: s for s in states}
    meta = {
        "schema": SCHEMA_VERSION,
        "generated_at": now,
        "timezone": "Asia/Seoul",
        "notice": NOTICE,
        "sources": [
            {
                "id": s.id, "site": s.site, "board": s.board, "url": s.url, "enabled": s.enabled,
                "finance_board": s.finance_board,
                "status": (state_by_id.get(s.id).status if state_by_id.get(s.id) else "pending") if s.enabled else "off",
                "last_success": state_by_id[s.id].last_success if s.id in state_by_id else None,
                "last_count": state_by_id[s.id].last_count if s.id in state_by_id else None,
                "detail": state_by_id[s.id].last_detail if s.id in state_by_id else None,
            }
            for s in settings.sources
        ],
        "post_files": [],
    }

    # posts-YYYYMMDD
    by_day: dict[str, list[dict]] = {}
    for a in recent:
        day = a.post.posted_at.astimezone(KST).strftime("%Y%m%d")
        by_day.setdefault(day, []).append(_post_obj(a))
    for d in range(days):
        day = (now.astimezone(KST) - timedelta(days=d)).strftime("%Y%m%d")
        items = sorted(by_day.get(day, []), key=lambda x: x["at"], reverse=True)
        path = out_dir / f"posts-{day}.json"
        _write(path, {"date": day, "posts": items})
        written.append(path)
        meta["post_files"].append(path.name)
    # 오래된 일자 파일 정리
    keep = set(meta["post_files"])
    for old in out_dir.glob("posts-*.json"):
        if old.name not in keep:
            old.unlink()

    # trends
    agg = aggregate(recent, now)
    referenced = {uid for w in agg.values() for k in w["keywords"] for uid in k["top"]}
    post_lookup = {a.post.uid: _post_obj(a) for a in recent if a.post.uid in referenced}
    trends = {
        "generated_at": now,
        "windows": agg,
        "daily": {
            "days": [(now.astimezone(KST) - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(days - 1, -1, -1)],
            "series": daily_series(recent, now, days),
        },
        "spikes": spikes(analyzed, now),
        "posts": post_lookup,
    }
    p = out_dir / "trends.json"
    _write(p, trends)
    written.append(p)

    # watchlist
    wl = []
    for item in watchlist:
        hits = [a for a in recent if matches(item, a.post.title, a.post.source_id)]
        hits.sort(key=lambda a: a.post.posted_at, reverse=True)
        wl.append({
            "keyword": item.keyword, "synonyms": list(item.synonyms), "exclude": list(item.exclude),
            "sources": list(item.sources), "count": len(hits), "posts": [_post_obj(a) for a in hits[:300]],
        })
    p = out_dir / "watchlist.json"
    _write(p, {"generated_at": now, "items": wl})
    written.append(p)

    p = out_dir / "candidates.json"
    _write(p, {"generated_at": now, "candidates": candidates})
    written.append(p)

    p = out_dir / "meta.json"
    _write(p, meta)  # 마지막에 써서 '갱신 완료' 신호로 사용
    written.append(p)
    return written
