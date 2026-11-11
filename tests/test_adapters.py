from datetime import timezone

from trendchecker.collector.adapters import parse, clean_title
from trendchecker.config import load_sources

SRC = {s.id: s for s in load_sources().sources}

CLIEN_HTML = """<html><body>
<div class="list_item"><a class="list_subject" href="/service/board/park/19290505?od=T31&amp;po=0" title="ignored">
 <span class="subject_fixed">아메리카가 물가잡겠다고 금리를 계속 상향시키는데요</span></a>
 <a href="/service/board/park/19290505?od=T31#comment">[12]</a></div>
<div class="list_item"><a href="/service/board/park/19290504"><span>[속보] 기준금리 동결</span></a></div>
<a href="/service/board/park/19290503">3</a>
<script>var x='<a href="/service/board/park/1">스크립트</a>';</script>
<a href="/service/board/notice/1">공지 링크</a>
</body></html>"""


def test_clien_link_regex():
    posts = parse(SRC["clien_park"], "https://www.clien.net/service/board/park", CLIEN_HTML)
    by_no = {p.post_no: p for p in posts}
    assert set(by_no) == {"19290505", "19290504"}
    assert by_no["19290505"].title == "아메리카가 물가잡겠다고 금리를 계속 상향시키는데요"
    assert by_no["19290505"].url == "https://www.clien.net/service/board/park/19290505"
    assert by_no["19290504"].posted_at is None


RSS = """<?xml version="1.0" encoding="euc-kr"?>
<rss version="2.0"><channel><title>뽐뿌 - 증권포럼</title>
<item><title><![CDATA[만약 코스닥 부양책 발표 사실이라면]]></title>
<link>http://www.ppomppu.co.kr/zboard/view.php?id=stock&amp;no=453959</link>
<pubDate>Wed, 11 Nov 2026 04:40:26 GMT</pubDate></item>
<item><title>이마트 신세계는 회복이 안되네요 [3]</title>
<link>http://www.ppomppu.co.kr/zboard/view.php?id=stock&amp;no=453957</link>
<pubDate>Wed, 11 Nov 2026 13:35:40 +0900</pubDate></item>
</channel></rss>"""


def test_ppomppu_rss_euckr():
    from trendchecker.collector.http import decode_body

    text = decode_body(RSS.encode("cp949"), None)
    posts = parse(SRC["ppomppu_stock"], "https://www.ppomppu.co.kr/rss.php?id=stock", text)
    assert len(posts) == 2
    p = {x.post_no: x for x in posts}
    assert p["453959"].title == "만약 코스닥 부양책 발표 사실이라면"
    assert p["453959"].url == "https://www.ppomppu.co.kr/zboard/view.php?id=stock&no=453959"
    assert p["453957"].title == "이마트 신세계는 회복이 안되네요"
    assert p["453957"].posted_at.tzinfo == timezone.utc
    assert p["453957"].posted_at.hour == 4


def test_bobaedream_and_paxnet_patterns():
    html = '<a href="https://www.bobaedream.co.kr/view?code=freeb&amp;No=3450641&amp;rtn=%2F">감 260Kg에 18,980원</a>'
    posts = parse(SRC["bobaedream_free"], "https://www.bobaedream.co.kr/list?code=freeb", html)
    assert posts[0].post_no == "3450641"
    assert posts[0].url == "https://www.bobaedream.co.kr/view?code=freeb&No=3450641"
    html = '<a href="http://www.paxnet.co.kr/tbbs/view?id=N00801&seq=150357590555562&wlog_com=x">삼성전자 비중 축소하며 대응</a>'
    posts = parse(SRC["paxnet_pick"], "https://www.paxnet.co.kr/tbbs/list?tbbsType=L&id=N00820", html)
    assert posts[0].post_no == "150357590555562"


def test_clean_title():
    assert clean_title("  제목&amp;테스트\n  (5) ") == "제목&테스트"
