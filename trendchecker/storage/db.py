"""SQLite 저장소.

게시물은 제목·링크·시각만 저장한다(본문·작성자 없음).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from ..collector.adapters import RawPost
from ..collector.timeutil import from_iso, to_iso, utcnow
from ..config import Source

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    uid         TEXT PRIMARY KEY,          -- source_id:post_no
    source_id   TEXT NOT NULL,
    post_no     TEXT NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    posted_at   TEXT NOT NULL,             -- UTC ISO. 모르면 최초 수집 시각
    time_exact  INTEGER NOT NULL DEFAULT 0,-- 1: 사이트가 준 시각, 0: 최초 수집 시각
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_time ON posts(posted_at);

CREATE TABLE IF NOT EXISTS funding (
    rcept_no    TEXT PRIMARY KEY,          -- DART 접수번호
    rcept_dt    TEXT NOT NULL,             -- 접수일 YYYYMMDD
    data        TEXT NOT NULL,             -- 정리한 JSON(회사, 신고서 종류, 증권종류, 규모, 청약일, 납입일)
    fetched_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_state (
    source_id            TEXT PRIMARY KEY,
    status               TEXT NOT NULL DEFAULT 'pending',
    consecutive_blocks   INTEGER NOT NULL DEFAULT 0,
    blocked_until        TEXT,
    last_attempt         TEXT,
    last_success         TEXT,
    last_count           INTEGER,
    last_new             INTEGER,
    last_detail          TEXT
);
"""


@dataclass
class StoredPost:
    uid: str
    source_id: str
    title: str
    url: str
    posted_at: datetime
    time_exact: bool


@dataclass
class SourceState:
    source_id: str
    status: str = "pending"
    consecutive_blocks: int = 0
    blocked_until: str | None = None
    last_attempt: str | None = None
    last_success: str | None = None
    last_count: int | None = None
    last_new: int | None = None
    last_detail: str | None = None


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ── 게시물
    def upsert_posts(self, posts: list[RawPost], now: datetime | None = None) -> int:
        """새로 들어온 게시물 수를 돌려준다. 제목이 바뀌면 갱신한다."""
        now_s = to_iso(now or utcnow())
        new = 0
        with self.tx() as c:
            for p in posts:
                uid = f"{p.source_id}:{p.post_no}"
                row = c.execute("SELECT uid FROM posts WHERE uid=?", (uid,)).fetchone()
                if row is None:
                    posted = to_iso(p.posted_at) if p.posted_at else now_s
                    # 사이트 시각이 미래로 찍혀 있으면 수집 시각으로 보정
                    if posted > now_s:
                        posted = now_s
                    c.execute(
                        "INSERT INTO posts(uid, source_id, post_no, title, url, posted_at, time_exact, first_seen, last_seen)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (uid, p.source_id, p.post_no, p.title, p.url, posted, 1 if p.posted_at else 0, now_s, now_s),
                    )
                    new += 1
                else:
                    c.execute("UPDATE posts SET title=?, url=?, last_seen=? WHERE uid=?", (p.title, p.url, now_s, uid))
        return new

    def posts_since(self, since: datetime) -> list[StoredPost]:
        rows = self.conn.execute(
            "SELECT uid, source_id, title, url, posted_at, time_exact FROM posts WHERE posted_at >= ? ORDER BY posted_at DESC",
            (to_iso(since),),
        ).fetchall()
        return [
            StoredPost(r["uid"], r["source_id"], r["title"], r["url"], from_iso(r["posted_at"]), bool(r["time_exact"]))
            for r in rows
        ]

    def prune(self, keep_days: int, now: datetime | None = None) -> int:
        cutoff = to_iso((now or utcnow()) - timedelta(days=keep_days))
        with self.tx() as c:
            cur = c.execute("DELETE FROM posts WHERE posted_at < ?", (cutoff,))
            return cur.rowcount

    def delete_source(self, source_id: str) -> int:
        """운영자 요청 등으로 특정 게시판 데이터를 지울 때."""
        with self.tx() as c:
            return c.execute("DELETE FROM posts WHERE source_id=?", (source_id,)).rowcount

    # ── 증권신고서(자금조달) 정리 결과
    def funding_known(self) -> set[str]:
        return {r["rcept_no"] for r in self.conn.execute("SELECT rcept_no FROM funding")}

    def funding_save(self, rcept_no: str, rcept_dt: str, data_json: str, now: datetime | None = None) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO funding(rcept_no, rcept_dt, data, fetched_at) VALUES (?,?,?,?)"
                      " ON CONFLICT(rcept_no) DO UPDATE SET data=excluded.data, fetched_at=excluded.fetched_at",
                      (rcept_no, rcept_dt, data_json, to_iso(now or utcnow())))

    def funding_since(self, rcept_dt_from: str) -> list[str]:
        """접수일(YYYYMMDD)이 rcept_dt_from 이후인 정리 결과(JSON 문자열)."""
        return [r["data"] for r in self.conn.execute(
            "SELECT data FROM funding WHERE rcept_dt >= ? ORDER BY rcept_dt DESC, rcept_no DESC", (rcept_dt_from,))]

    def funding_prune(self, keep_from: str) -> int:
        with self.tx() as c:
            return c.execute("DELETE FROM funding WHERE rcept_dt < ?", (keep_from,)).rowcount

    # ── 게시판 상태
    def get_state(self, source_id: str) -> SourceState:
        r = self.conn.execute("SELECT * FROM source_state WHERE source_id=?", (source_id,)).fetchone()
        if r is None:
            return SourceState(source_id)
        return SourceState(**{k: r[k] for k in r.keys()})

    def save_state(self, st: SourceState) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO source_state(source_id, status, consecutive_blocks, blocked_until, last_attempt, last_success,"
                " last_count, last_new, last_detail) VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(source_id) DO UPDATE SET status=excluded.status, consecutive_blocks=excluded.consecutive_blocks,"
                " blocked_until=excluded.blocked_until, last_attempt=excluded.last_attempt, last_success=excluded.last_success,"
                " last_count=excluded.last_count, last_new=excluded.last_new, last_detail=excluded.last_detail",
                (
                    st.source_id, st.status, st.consecutive_blocks, st.blocked_until, st.last_attempt,
                    st.last_success, st.last_count, st.last_new, st.last_detail,
                ),
            )

    def all_states(self, sources: list[Source]) -> list[SourceState]:
        return [self.get_state(s.id) for s in sources]
