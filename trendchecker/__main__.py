"""명령줄 진입점.

  python -m trendchecker collect   # 게시판 수집만
  python -m trendchecker build     # 저장된 데이터로 분석 + JSON 산출
  python -m trendchecker run       # collect + build (스케줄러가 부르는 명령)
  python -m trendchecker check     # 게시판별 robots 허용 여부와 목록 파싱 결과 점검(저장 안 함)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import timedelta
from pathlib import Path

from . import __version__
from .analysis.aggregate import analyze_posts
from .analysis.candidates import find_candidates
from .analysis.ads import load_ad_matcher
from .analysis.dedupe import drop_duplicate_disclosures
from .analysis.dictionary import FinanceMatcher
from .analysis.risk import load_risk_matcher
from .collector.adapters import parse
from .collector.http import PoliteClient
from .collector.run import collect_all
from .collector.timeutil import utcnow
from .config import ROOT, load_dictionary, load_excluded_keywords, load_sources, load_stopwords, load_watchlist
from .export.json_export import export_all
from .logutil import setup_logging
from .storage.db import Store

log = logging.getLogger("trendchecker")

DEFAULT_DB = ROOT / "state" / "trend.db"
DEFAULT_OUT = ROOT / "site" / "data"
KEEP_DAYS = 7  # 급상승 기준선(직전 4일)까지 계산하려면 5일보다 길게 보관


def cmd_collect(args) -> int:
    settings = load_sources()
    store = Store(args.db)
    try:
        only = set(args.only.split(",")) if args.only else None
        reports = collect_all(settings, store, only=only)
        store.prune(KEEP_DAYS)
    finally:
        store.close()
    ok = sum(1 for r in reports if r.status in ("ok", "empty"))
    log.info("수집 완료: %d/%d 게시판 정상", ok, len(reports))
    return 0


def cmd_build(args) -> int:
    settings = load_sources()
    matcher = FinanceMatcher(load_dictionary())
    store = Store(args.db)
    try:
        now = utcnow()
        posts = store.posts_since(now - timedelta(days=KEEP_DAYS))
        states = store.all_states(settings.sources)
    finally:
        store.close()
    src_map = {s.id: s for s in settings.sources}
    # 꺼 둔 소스(예: 제외한 카페글)의 이전 수집분은 화면에 내지 않는다
    posts = [p for p in posts if p.source_id in src_map and src_map[p.source_id].enabled]
    posts, dup = drop_duplicate_disclosures(posts, src_map)
    if dup:
        log.info("DART 와 중복된 공시 %d건은 한 번만 집계", dup)
    risk = load_risk_matcher()
    analyzed = analyze_posts(posts, matcher, src_map, load_excluded_keywords(), risk, load_ad_matcher())
    fin_titles = [a.post.title for a in analyzed if a.is_finance]
    try:
        cands = find_candidates(fin_titles, matcher.all_alias_texts | set(matcher.entries), load_stopwords())
    except Exception:
        log.exception("새 키워드 후보 추출 실패(집계는 계속 진행)")
        cands = []
    files = export_all(Path(args.out), settings, states, analyzed, load_watchlist(), cands, now, risk=risk)
    log.info("JSON %d개 생성 → %s", len(files), args.out)
    return 0


def cmd_run(args) -> int:
    cmd_collect(args)
    return cmd_build(args)


def cmd_check(args) -> int:
    settings = load_sources()
    only = set(args.only.split(",")) if args.only else None
    with PoliteClient(settings.defaults.min_interval_sec, settings.defaults.timeout_sec) as client:
        for src in settings.sources:
            if only and src.id not in only:
                continue
            if src.type in ("naver_api", "dart_api"):
                print(f"{src.id:18} {src.type:18} (공식 API: 키를 환경변수로 넣고 `collect --only {src.id}` 실행)")
                continue
            res = client.fetch(src.url)
            line = f"{src.id:18} {res.status:18} {res.detail}"
            if res.status == "ok":
                posts = parse(src, res.url, res.text)
                line += f" 게시물 {len(posts)}건"
                for p in posts[:3]:
                    line += f"\n{'':20}- {p.title[:40]} | {p.url}"
            print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trendchecker", description="국내 게시판 금융 키워드 트렌드 수집기")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("collect", cmd_collect), ("build", cmd_build), ("run", cmd_run), ("check", cmd_check)):
        p = sub.add_parser(name)
        p.add_argument("--db", default=str(DEFAULT_DB))
        p.add_argument("--out", default=str(DEFAULT_OUT))
        p.add_argument("--only", default="", help="쉼표로 구분한 source id")
        p.set_defaults(func=fn)
    args = ap.parse_args(argv)
    setup_logging(verbose=args.verbose)
    try:
        return args.func(args)
    except Exception:
        log.exception("실행 실패")
        return 1


if __name__ == "__main__":
    sys.exit(main())
