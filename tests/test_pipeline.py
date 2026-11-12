import json
from datetime import datetime, timedelta, timezone

import httpx

from trendchecker.analysis.aggregate import analyze_posts, aggregate, spikes, daily_series
from trendchecker.analysis.dictionary import FinanceMatcher
from trendchecker.analysis.watch import matches
from trendchecker.collector.adapters import RawPost
from trendchecker.collector.http import PoliteClient, FetchStatus
from trendchecker.collector.run import collect_all, DISABLE_AFTER
from trendchecker.config import Settings, Defaults, WatchItem, load_dictionary, load_sources
from trendchecker.export.json_export import export_all
from trendchecker.storage.db import Store

SOURCES = {s.id: s for s in load_sources().sources}


class FakeTime:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 3))
        self.t += s


def make_client(handler, ft=None):
    ft = ft or FakeTime()
    return PoliteClient(6, 5, transport=httpx.MockTransport(handler), sleep=ft.sleep, clock=ft.clock), ft


def test_rate_limit_and_robots():
    calls = []

    def handler(req):
        calls.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, text="<a href='/b/1'>hello world</a>")

    c, ft = make_client(handler)
    assert c.fetch("https://a.test/list").status == FetchStatus.OK
    assert c.fetch("https://a.test/list2").status == FetchStatus.OK
    assert c.fetch("https://a.test/private/x").status == FetchStatus.ROBOTS
    # robots 1회 + 목록 2회, 같은 호스트는 6초 간격
    assert calls == ["https://a.test/robots.txt", "https://a.test/list", "https://a.test/list2"]
    assert ft.slept == [6, 6]
    # User-Agent 확인
    c.close()


def test_blocked_and_challenge_and_robots_errors():
    def handler(req):
        if req.url.host == "x.test" and req.url.path == "/robots.txt":
            return httpx.Response(503)
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/cf":
            return httpx.Response(200, text="<title>Just a moment...</title>")
        return httpx.Response(429)

    c, _ = make_client(handler)
    assert c.fetch("https://y.test/cf").status == FetchStatus.BLOCKED
    assert c.fetch("https://y.test/list").status == FetchStatus.BLOCKED
    r = c.fetch("https://x.test/list")
    assert r.status == FetchStatus.ERROR and "robots" in r.detail  # robots 5xx → 수집 안 함
    c.close()


def test_network_error_is_reported_not_raised():
    def handler(req):
        raise httpx.ConnectError("boom")

    c, _ = make_client(handler)
    r = c.fetch("https://z.test/list")
    assert r.status == FetchStatus.ERROR  # robots 를 못 가져오면 수집하지 않는다(오류로 보고)
    c.close()


def test_collect_backoff_then_disable(tmp_path):
    src = SOURCES["clien_park"]
    settings = Settings(Defaults(6, 5, (1, 3)), [src])
    store = Store(tmp_path / "t.db")

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(403)

    from trendchecker.collector import run as runmod

    now = datetime(2026, 11, 11, 3, tzinfo=timezone.utc)
    for i in range(DISABLE_AFTER):
        c, _ = make_client(handler)
        r = runmod.collect_source(c, store, src, (1, 3), now=now)
        assert r.status in ("blocked", "disabled")
        # 백오프 중에는 요청하지 않음
        r2 = runmod.collect_source(c, store, src, (1, 3), now=now + timedelta(minutes=30))
        assert r2.status == "backoff"
        now += timedelta(hours=4)
        c.close()
    assert store.get_state(src.id).status == "disabled"
    store.close()


def test_collect_ok_and_export(tmp_path):
    src = SOURCES["clien_park"]
    settings = Settings(Defaults(6, 5, (1,)), [src, SOURCES["ppomppu_stock"]])
    html = """<a href="/service/board/park/100"><span>카뱅 파킹통장 금리 인하 소식</span></a>
              <a href="/service/board/park/101"><span>오늘 점심 뭐 먹지</span></a>
              <a href="/service/board/park/102"><span>코스피 폭락 ETF 손절각</span></a>"""
    rss = """<?xml version="1.0" encoding="utf-8"?><rss><channel>
      <item><title>파킹 통장 어디가 좋나요</title><link>http://www.ppomppu.co.kr/zboard/view.php?id=stock&amp;no=9</link>
      <pubDate>{PUB}</pubDate></item></channel></rss>"""

    from email.utils import format_datetime
    rss = rss.replace("{PUB}", format_datetime(datetime.now(timezone.utc) - timedelta(seconds=30)))  # 날짜가 바뀌어도 '오늘' 글이 되게

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if "ppomppu" in req.url.host:
            return httpx.Response(200, content=rss.encode())
        return httpx.Response(200, content=html.encode("utf-8"), headers={"content-type": "text/html; charset=utf-8"})

    store = Store(tmp_path / "t.db")
    c, _ = make_client(handler)
    reports = collect_all(settings, store, client=c)
    assert [r.status for r in reports] == ["ok", "ok"]
    assert [r.new for r in reports] == [3, 1]
    # 두 번째 수집에서는 신규 0
    reports = collect_all(settings, store, client=c)
    assert [r.new for r in reports] == [0, 0]
    c.close()

    now = datetime.now(timezone.utc)
    posts = store.posts_since(now - timedelta(days=7))
    matcher = FinanceMatcher(load_dictionary())
    analyzed = analyze_posts(posts, matcher, {s.id: s for s in settings.sources})
    watch = [WatchItem("파킹통장", ("파킹 통장",), ("주차",))]
    files = export_all(tmp_path / "out", settings, store.all_states(settings.sources), analyzed, watch, [], now)
    names = {f.name for f in files}
    assert {"meta.json", "trends.json", "watchlist.json", "candidates.json"} <= names
    trends = json.loads((tmp_path / "out" / "trends.json").read_text(encoding="utf-8"))
    kws = {k["keyword"]: k for k in trends["windows"]["today"]["keywords"]}
    assert kws["파킹통장"]["posts"] == 2
    assert kws["파킹통장"]["sources"] == {"clien_park": 1, "ppomppu_stock": 1}
    assert all(uid in trends["posts"] for uid in kws["파킹통장"]["top"])
    wl = json.loads((tmp_path / "out" / "watchlist.json").read_text(encoding="utf-8"))
    assert wl["items"][0]["count"] == 2
    meta = json.loads((tmp_path / "out" / "meta.json").read_text(encoding="utf-8"))
    assert {s["id"]: s["status"] for s in meta["sources"]} == {"clien_park": "ok", "ppomppu_stock": "ok"}
    assert len(meta["post_files"]) == 5
    # 본문/작성자 필드가 없어야 함
    day = json.loads((tmp_path / "out" / meta["post_files"][0]).read_text(encoding="utf-8"))
    for p in day["posts"]:
        assert set(p) <= {"id", "s", "t", "u", "at", "x", "k", "f", "c", "r", "d"} and not ({"author", "body"} & set(p))
    store.close()


def _post(uid, title, at, src="clien_park"):
    from trendchecker.storage.db import StoredPost
    return StoredPost(uid, src, title, "https://x/" + uid, at, True)


def test_windows_kst_and_spikes():
    now = datetime(2026, 11, 11, 3, 0, tzinfo=timezone.utc)  # KST 12:00
    m = FinanceMatcher(load_dictionary())
    posts = [
        _post("a", "금리 인하", datetime(2026, 11, 10, 16, 0, tzinfo=timezone.utc)),   # KST 11/11 01:00 → today
        _post("b", "금리 인하", datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)),   # KST 11/10 23:00 → 3d
        _post("c", "금리 인하", datetime(2026, 11, 7, 16, 0, tzinfo=timezone.utc)),    # KST 11/08 01:00 → 5d
        _post("d", "금리 인하", datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc)),    # KST 11/06 → 범위 밖
    ]
    a = analyze_posts(posts, m, SOURCES)
    agg = aggregate(a, now)
    cnt = lambda w: next(k["posts"] for k in agg[w]["keywords"] if k["keyword"] == "금리인하")
    assert (cnt("today"), cnt("3d"), cnt("5d")) == (1, 2, 3)
    ser = daily_series(a, now, 5)["금리인하"]
    assert ser == [0, 1, 0, 1, 1]

    burst = [_post(f"s{i}", "비트코인 급등", now - timedelta(hours=i)) for i in range(5)]
    old = [_post("o1", "비트코인 얘기", now - timedelta(days=3))]
    sp = spikes(analyze_posts(burst + old, m, SOURCES), now)
    assert sp and sp[0]["keyword"] == "비트코인" and sp[0]["recent_24h"] == 5


def test_watch_rules():
    w = WatchItem("파킹통장", ("파킹 적금",), ("주차",), ("clien_park",))
    assert matches(w, "토스 파킹 통장 금리", "clien_park")
    assert not matches(w, "파킹통장 주차 할인", "clien_park")
    assert not matches(w, "파킹통장", "ppomppu_stock")


def test_build_cli_end_to_end(tmp_path, monkeypatch):
    """저장된 DB → build 명령 → JSON (Kiwi 후보 추출 포함)"""
    from trendchecker import __main__ as cli
    store = Store(tmp_path / "t.db")
    now = datetime.now(timezone.utc)
    store.upsert_posts([RawPost("ppomppu_stock", str(i), f"스테이블코인 수혜주 {i}번 정리 원화코인", "https://x/" + str(i), now - timedelta(hours=i))
                        for i in range(6)], now)
    store.close()
    rc = cli.main(["build", "--db", str(tmp_path / "t.db"), "--out", str(tmp_path / "out")])
    assert rc == 0
    cands = json.loads((tmp_path / "out" / "candidates.json").read_text(encoding="utf-8"))["candidates"]
    words = [c["word"] for c in cands]
    assert "수혜" in words and "스테이블코인" not in words and "정리" not in words


def test_naver_api(tmp_path):
    from trendchecker.collector.run import collect_naver
    from trendchecker.collector.naver import parse_items, credentials

    src = SOURCES["naver_blog"]
    now = datetime(2026, 11, 11, 3, tzinfo=timezone.utc)  # KST 12:00
    seen = []

    def handler(req):
        seen.append((req.url.params["query"], req.headers.get("x-naver-client-id")))
        if req.url.params["query"] == "에러":
            return httpx.Response(500)
        items = [
            {"title": "<b>파킹통장</b> 금리 비교 &amp; 후기", "link": "https://blog.naver.com/a/1", "postdate": "20261111"},
            {"title": "예전 글 <b>금리</b>", "link": "https://blog.naver.com/a/2", "postdate": "20261109"},
            {"title": "x", "link": "https://blog.naver.com/a/3"},                      # 제목 너무 짧음
            {"title": "위험 링크", "link": "javascript:alert(1)"},
        ]
        return httpx.Response(200, json={"items": items})

    store = Store(tmp_path / "n.db")
    tr = httpx.MockTransport(handler)
    # 키 없음
    r = collect_naver(store, src, (1,), env={}, transport=tr, now=now, queries=["금리"], sleep=lambda s: None)
    assert r.status == "no_key" and seen == []
    env = {"NAVER_CLIENT_ID": "id", "NAVER_CLIENT_SECRET": "sec"}
    r = collect_naver(store, src, (1,), env=env, transport=tr, now=now, queries=["금리", "에러", "파킹통장"], sleep=lambda s: None)
    assert r.status == "ok" and r.fetched == 2 and r.new == 2
    assert [q for q, _ in seen] == ["금리", "에러", "파킹통장"] and all(i == "id" for _, i in seen)
    posts = {p.title: p for p in store.posts_since(now - timedelta(days=5))}
    assert "파킹통장 금리 비교 & 후기" in posts and "예전 글 금리" in posts
    old = posts["예전 글 금리"]
    assert old.posted_at.astimezone(timezone(timedelta(hours=9))).strftime("%m-%d %H") == "11-09 12"  # 어제 이전 글은 그날 정오(KST)
    assert posts["파킹통장 금리 비교 & 후기"].posted_at == now                                         # 오늘 글은 수집 시각

    # 인증 오류·한도 초과
    r = collect_naver(store, src, (1,), env=env, transport=httpx.MockTransport(lambda q: httpx.Response(401)), now=now, queries=["a"], sleep=lambda s: None)
    assert r.status == "error" and "인증" in r.detail
    r = collect_naver(store, src, (1, 3), env=env, transport=httpx.MockTransport(lambda q: httpx.Response(429)), now=now, queries=["a"], sleep=lambda s: None)
    assert r.status == "blocked"
    r = collect_naver(store, src, (1, 3), env=env, transport=tr, now=now + timedelta(minutes=10), queries=["a"], sleep=lambda s: None)
    assert r.status == "backoff"
    store.close()
    assert credentials({"NAVER_CLIENT_ID": " ", "NAVER_CLIENT_SECRET": "x"}) is None


def test_excluded_broad_keywords_are_not_counted():
    from trendchecker.config import load_excluded_keywords
    from trendchecker.storage.db import StoredPost
    ex = load_excluded_keywords()
    assert {"주식", "대출", "금리"} <= ex
    m = FinanceMatcher(load_dictionary())
    at = datetime(2026, 11, 11, 3, tzinfo=timezone.utc)
    posts = [StoredPost("1", "clien_park", "주식 대출 금리 얘기", "https://x/1", at, True),
             StoredPost("2", "clien_park", "카카오뱅크 대출 후기", "https://x/2", at, True),
             StoredPost("3", "clien_park", "오늘 점심 뭐 먹지", "https://x/3", at, True)]
    out = analyze_posts(posts, m, SOURCES, ex)
    assert [e.name for e in out[0].keywords] == [] and out[0].is_finance  # 금융 글로는 세지만 키워드 순위엔 안 나옴
    assert [e.name for e in out[1].keywords] == ["카카오뱅크"]
    assert not out[2].is_finance
    assert [e.name for e in analyze_posts(posts, m, SOURCES)[0].keywords] == ["주식", "대출", "금리"]


def _dart_transport(pages, status="000"):
    def handler(req):
        page = int(req.url.params["page_no"])
        if status != "000":
            return httpx.Response(200, json={"status": status, "message": "x"})
        return httpx.Response(200, json={"status": "000", "page_no": page, "total_page": len(pages), "list": pages[page - 1]})
    return httpx.MockTransport(handler)


def test_dart_collect_paging_and_errors(tmp_path):
    from trendchecker.collector.run import collect_dart
    src = SOURCES["dart_disclosure"]
    now = datetime.now(timezone.utc)
    pages = [[{"rcept_no": "20261112000001", "corp_name": "가나다", "report_nm": "횡령ㆍ배임혐의발생", "rcept_dt": now.astimezone(timezone(timedelta(hours=9))).strftime("%Y%m%d")}],
             [{"rcept_no": "20261112000002", "corp_name": "라마바", "report_nm": "유상증자결정", "rcept_dt": "20200101"}]]
    store = Store(tmp_path / "d.db")
    r = collect_dart(store, src, (1,), env={}, now=now)
    assert r.status == "no_key"
    r = collect_dart(store, src, (1,), env={"DART_API_KEY": "k"}, transport=_dart_transport(pages), now=now, sleep=lambda s: None)
    assert (r.status, r.fetched, r.new) == ("ok", 2, 2)
    posts = {p.uid: p for p in store.posts_since(now - timedelta(days=3650))}
    p1 = posts["dart_disclosure:20261112000001"]
    assert p1.title == "가나다 횡령ㆍ배임혐의발생" and p1.url.startswith("https://dart.fss.or.kr/dsaf001/main.do?rcpNo=")
    store2 = Store(tmp_path / "e.db")
    r = collect_dart(store2, src, (1, 3), env={"DART_API_KEY": "k"}, transport=_dart_transport([], "020"), now=now)
    assert r.status == "blocked" and "한도" in r.detail
    r = collect_dart(Store(tmp_path / "f.db"), src, (1,), env={"DART_API_KEY": "k"}, transport=_dart_transport([], "010"), now=now)
    assert r.status == "error"
    r = collect_dart(Store(tmp_path / "g.db"), src, (1,), env={"DART_API_KEY": "k"}, transport=_dart_transport([], "013"), now=now)
    assert r.status == "empty"


def test_risk_terms_and_disclosure_types_and_alerts(tmp_path):
    from trendchecker.analysis.risk import load_risk_matcher
    from trendchecker.storage.db import StoredPost
    risk = load_risk_matcher()
    assert any(h.category == "사기·유사수신" for h in risk.hits("유사 수신 업체 리딩 방 주의"))
    assert risk.hits("오늘 점심 뭐 먹지") == []
    assert risk.disclosure_type("가나다 횡령ㆍ배임혐의발생") == "횡령·배임"
    assert risk.disclosure_type("정기 주주총회 소집공고") is None
    now = datetime.now(timezone.utc)
    mk = lambda uid, src, title, h=1: StoredPost(uid, src, title, "https://x/" + uid, now - timedelta(hours=h), True)
    posts = [mk("a", "dart_disclosure", "가나다 횡령ㆍ배임혐의발생"), mk("b", "naver_news", "금감원 리딩방 일제 점검"),
             mk("c", "clien_park", "이거 리딩방 사기 아니냐"), mk("d", "clien_park", "점심 뭐 먹지")]
    settings = Settings(Defaults(6, 5, (1,)), [SOURCES[i] for i in ("dart_disclosure", "naver_news", "clien_park")])
    analyzed = analyze_posts(posts, FinanceMatcher(load_dictionary()), {s.id: s for s in settings.sources}, risk=risk)
    assert [a.category for a in analyzed] == ["disclosure", "news", "board", "board"]
    assert analyzed[0].dtype == "횡령·배임"
    export_all(tmp_path / "o", settings, [], analyzed, [], [], now, risk=risk)
    al = json.loads((tmp_path / "o" / "alerts.json").read_text(encoding="utf-8"))
    # 게시판 모니터링: 게시판 글만 센다(뉴스 b, 공시 a 제외)
    assert al["windows"]["5d"]["사기·유사수신"]["by_kind"] == {"board": 1}
    assert "내부통제·횡령·배임" not in al["windows"]["5d"]
    tr = json.loads((tmp_path / "o" / "trends.json").read_text(encoding="utf-8"))
    assert set(tr["cats"]) == {"news", "disclosure", "board", "blog"}


def test_kind_dart_duplicate_disclosures_counted_once():
    from trendchecker.analysis.dedupe import dedupe_key, drop_duplicate_disclosures
    from trendchecker.storage.db import StoredPost
    assert dedupe_key("[코]가나다전자 [정정]횡령ㆍ배임혐의발생") == dedupe_key("가나다전자 횡령·배임혐의발생")
    assert dedupe_key("[코]파인텍 분기보고서(일반법인)(2026.09)") == dedupe_key("파인텍 분기보고서 (2026.09)")
    assert dedupe_key("가나 전환사채권발행결정(제10회차)") != dedupe_key("가나 전환사채권발행결정(제11회차)")
    sources = {s.id: s for s in load_sources().sources}
    assert sources["kind_disclosure"].dup_of == "dart_disclosure" and sources["kind_disclosure"].category == "disclosure"
    now = datetime.now(timezone.utc)
    mk = lambda uid, src, t, h=1: StoredPost(uid, src, t, "https://x/" + uid, now - timedelta(hours=h), True)
    posts = [mk("d1", "dart_disclosure", "가나다전자 횡령ㆍ배임혐의발생"),
             mk("k1", "kind_disclosure", "[코]가나다전자 횡령ㆍ배임혐의발생"),          # 중복 → 제외
             mk("k2", "kind_disclosure", "[유]라마바 공매도 과열종목 지정"),            # KIND 에만 있음 → 유지
             mk("k3", "kind_disclosure", "[코]가나다전자 횡령ㆍ배임혐의발생", h=24 * 5)]  # 날짜가 멀면 별개 공시
    kept, dropped = drop_duplicate_disclosures(posts, sources)
    assert dropped == 1 and {p.uid for p in kept} == {"d1", "k2", "k3"}
    # DART 가 없으면(키 없음 등) KIND 글이 그대로 남는다
    kept, dropped = drop_duplicate_disclosures([p for p in posts if p.source_id != "dart_disclosure"], sources)
    assert dropped == 0 and len(kept) == 3


def test_blog_ads_flagged_and_blog_excluded_from_default_ranking(tmp_path):
    from trendchecker.analysis.ads import load_ad_matcher
    from trendchecker.analysis.risk import load_risk_matcher
    from trendchecker.storage.db import StoredPost
    ads = load_ad_matcher()
    assert ads.is_ad("무직자 당일대출 가능한 곳 무료상담")
    assert ads.is_ad("대출 문의 010-1234-5678")
    assert ads.is_ad("최저금리 비교 추천 총정리")          # 약한 말 3개
    assert not ads.is_ad("저축은행 예금 인출 사태 정리")    # 약한 말 0~1개
    assert not ads.is_ad("카카오뱅크 파킹통장 금리 인하")
    now = datetime.now(timezone.utc)
    mk = lambda uid, src, t: StoredPost(uid, src, t, "https://x/" + uid, now - timedelta(hours=1), True)
    posts = [mk("b1", "naver_blog", "무직자 당일대출 상담 파킹통장"),
             mk("b2", "naver_blog", "유사수신 업체 피해 사례 무료상담"),       # 광고처럼 보이지만 사기·유사수신 → 위험 집계에 남김
             mk("b3", "naver_blog", "먹튀 거래소 출금 정지 후기"),
             mk("b4", "naver_blog", "반복 제목 글"), mk("b5", "naver_blog", "반복 제목 글"), mk("b6", "naver_blog", "반복 제목 글"),
             mk("n1", "naver_news", "카카오뱅크 파킹통장 금리 인하")]
    settings = Settings(Defaults(6, 5, (1,)), [SOURCES["naver_blog"], SOURCES["naver_news"]])
    risk = load_risk_matcher()
    an = analyze_posts(posts, FinanceMatcher(load_dictionary()), {s.id: s for s in settings.sources}, risk=risk, ads=ads)
    by = {a.post.uid: a for a in an}
    assert by["b1"].ad and by["b2"].ad and not by["b3"].ad
    assert all(by[u].ad for u in ("b4", "b5", "b6"))
    assert not by["n1"].ad and by["b1"].category == "blog"
    export_all(tmp_path / "o", settings, [], an, [], [], now, risk=risk)
    tr = json.loads((tmp_path / "o" / "trends.json").read_text(encoding="utf-8"))
    kws = {k["keyword"] for k in tr["windows"]["today"]["keywords"]}
    assert "파킹통장" in kws and tr["windows"]["today"]["total_posts"] == 1       # 블로그·광고 제외, 뉴스만
    assert tr["cats"]["blog"]["today"]["total_posts"] == 1                         # 블로그 탭엔 광고 아닌 b3 만
    al = json.loads((tmp_path / "o" / "alerts.json").read_text(encoding="utf-8"))
    assert al["windows"]["today"] == {}                                             # 블로그·뉴스는 게시판 모니터링에서 제외
    day = json.loads(next((tmp_path / "o").glob("posts-*.json")).read_text(encoding="utf-8"))
    assert any(p.get("a") == 1 for f in (tmp_path / "o").glob("posts-*.json") for p in json.loads(f.read_text(encoding="utf-8"))["posts"])


def test_funding_classify_summarize_and_collect(tmp_path):
    from trendchecker.collector import funding as fd
    from trendchecker.collector.run import collect_funding
    assert fd.classify("증권신고서(지분증권)") == ("estkRs", "지분증권")
    assert fd.classify("[기재정정]증권신고서(채무증권)") == ("bdRs", "채무증권")
    assert fd.classify("증권신고서(집합투자증권-신탁형)") is None      # 펀드 제외
    assert fd.classify("투자설명서") is None and fd.classify("분기보고서") is None
    assert fd.to_won("100,000,000,000") == 100_000_000_000 and fd.to_won("-") is None
    assert fd.fmt_dates("2026년 11월 20일 ~ 2026년 11월 21일") == "2026-11-20 ~ 2026-11-21" and fd.fmt_dates("-") == ""
    now = datetime.now(timezone.utc)
    today = now.astimezone(timezone(timedelta(hours=9))).strftime("%Y%m%d")
    filings = [{"rcept_no": "20261112000010", "corp_code": "00111111", "corp_name": "가나다", "report_nm": "증권신고서(지분증권)", "rcept_dt": today, "stock_code": "000001"},
               {"rcept_no": "20261112000011", "corp_code": "00222222", "corp_name": "라마바", "report_nm": "증권신고서(채무증권)", "rcept_dt": today},
               {"rcept_no": "20261112000012", "corp_code": "00333333", "corp_name": "펀드운용", "report_nm": "증권신고서(집합투자증권-신탁형)", "rcept_dt": today},
               {"rcept_no": "20261112000013", "corp_code": "00444444", "corp_name": "투자", "report_nm": "투자설명서", "rcept_dt": today}]
    calls = []

    def handler(req):
        calls.append(req.url.path)
        if req.url.path.endswith("/list.json"):
            return httpx.Response(200, json={"status": "000", "total_page": 1, "list": filings})
        if req.url.path.endswith("/estkRs.json"):
            return httpx.Response(200, json={"status": "000", "group": [
                {"title": "일반사항", "list": [{"rcept_no": "20261112000010", "sbd": "2026년 11월 20일 ~ 2026년 11월 21일", "pymd": "2026년 11월 28일"}]},
                {"title": "증권의종류", "list": [{"rcept_no": "20261112000010", "stksen": "보통주", "slta": "50,000,000,000"},
                                               {"rcept_no": "20261112000010", "stksen": "우선주", "slta": "25,000,000,000"}]}]})
        if req.url.path.endswith("/bdRs.json"):
            return httpx.Response(200, json={"status": "000", "group": [
                {"title": "일반사항", "list": [{"rcept_no": "20261112000011", "bdnmn": "제5회 무보증사채", "slta": "30,000,000,000", "sbd": "2026-11-18", "pymd": "2026-11-19"},
                                            {"rcept_no": "20261112000011", "bdnmn": "제6회 무보증사채", "slta": "20,000,000,000", "sbd": "2026-11-18", "pymd": "2026-11-19"}]}]})
        return httpx.Response(404)

    store = Store(tmp_path / "f.db")
    src = SOURCES["dart_funding"]
    r = collect_funding(store, src, (1,), env={"DART_API_KEY": "k"}, transport=httpx.MockTransport(handler), now=now, sleep=lambda s: None)
    assert (r.status, r.fetched, r.new) == ("ok", 2, 2)
    assert not any("mgRs" in c or "dvRs" in c for c in calls)
    rows = {json.loads(x)["rcept_no"]: json.loads(x) for x in store.funding_since("20000101")}
    a, b = rows["20261112000010"], rows["20261112000011"]
    assert a["security"] == "보통주, 우선주" and a["amount_eok"] == 750.0 and a["sub_date"] == "2026-11-20 ~ 2026-11-21" and a["pay_date"] == "2026-11-28"
    assert b["amount_eok"] == 500.0 and "제5회" in b["security"] and b["kind"] == "채무증권"
    assert a["url"].endswith("rcpNo=20261112000010")
    # 두 번째 실행: 이미 정리한 접수번호는 상세 API 를 다시 부르지 않는다
    calls.clear()
    r = collect_funding(store, src, (1,), env={"DART_API_KEY": "k"}, transport=httpx.MockTransport(handler), now=now, sleep=lambda s: None)
    assert r.new == 0 and calls == ["/api/list.json"]


def test_dart_retries_on_timeout_then_succeeds():
    from trendchecker.collector.dart import DartError, get_with_retry
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        if n["c"] < 3:
            raise httpx.ConnectTimeout("slow")
        return httpx.Response(200, json={"status": "000"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert get_with_retry(c, "https://x/api", {}, sleep=lambda s: None).status_code == 200 and n["c"] == 3
    n["c"] = -10
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        try:
            get_with_retry(c, "https://x/api", {}, attempts=2, sleep=lambda s: None)
            raise AssertionError("should fail")
        except DartError as e:
            assert "ConnectTimeout" in str(e)


def test_funding_corrected_filing_inherits_original_terms(tmp_path):
    from trendchecker.collector.run import collect_funding
    now = datetime.now(timezone.utc)
    today = now.astimezone(timezone(timedelta(hours=9))).strftime("%Y%m%d")
    filings = [{"rcept_no": "20261111000099", "corp_code": "00555555", "corp_name": "정정회사", "report_nm": "[기재정정]증권신고서(지분증권)", "rcept_dt": today}]
    seen = {}

    def handler(req):
        if req.url.path.endswith("/list.json"):
            return httpx.Response(200, json={"status": "000", "total_page": 1, "list": filings})
        seen["bgn"] = req.url.params["bgn_de"]
        return httpx.Response(200, json={"status": "000", "group": [
            {"title": "일반사항", "list": [{"rcept_no": "20261101000001", "sbd": "2026-12-01", "pymd": "2026-12-03"}]},
            {"title": "증권의종류", "list": [{"rcept_no": "20261101000001", "stksen": "보통주", "slta": "10,000,000,000"}]}]})

    store = Store(tmp_path / "g.db")
    r = collect_funding(store, SOURCES["dart_funding"], (1,), env={"DART_API_KEY": "k"}, transport=httpx.MockTransport(handler), now=now, sleep=lambda s: None)
    row = json.loads(store.funding_since("20000101")[0])
    assert row["amount_eok"] == 100.0 and row["security"] == "보통주" and row["from_original"] and row["corrected"]
    assert seen["bgn"] < today   # 접수일 하루가 아니라 넓게 조회
    assert store.funding_known(complete_only=True) == {"20261111000099"}
