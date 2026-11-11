from trendchecker.collector.robots import RobotsPolicy

CLIEN_LIKE = """
User-agent: *
Allow: /service/board/
Disallow: /service/board/sold/
Disallow: /*?
Disallow: /service/search

User-agent: GPTBot
User-agent: anthropic-ai
Disallow: /
"""


def test_wildcard_query_blocked():
    r = RobotsPolicy.parse(CLIEN_LIKE)
    assert r.can_fetch("TrendCheckerBot", "https://www.clien.net/service/board/park")
    # RFC 9309: 더 긴 Allow(/service/board/)가 짧은 Disallow(/*?)보다 우선
    assert r.can_fetch("TrendCheckerBot", "https://www.clien.net/service/board/park?po=1")
    assert not r.can_fetch("TrendCheckerBot", "https://www.clien.net/main?x=1")
    assert not r.can_fetch("TrendCheckerBot", "https://www.clien.net/service/board/sold/1")
    assert not r.can_fetch("TrendCheckerBot", "https://www.clien.net/service/search")


def test_specific_group_used_for_named_agent():
    r = RobotsPolicy.parse(CLIEN_LIKE)
    assert not r.can_fetch("GPTBot/1.0", "https://www.clien.net/service/board/park")
    assert not r.can_fetch("anthropic-ai", "https://www.clien.net/")


def test_longest_match_and_allow_tie():
    r = RobotsPolicy.parse("User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /x$\n")
    assert not r.can_fetch("bot", "https://h/a/c")
    assert r.can_fetch("bot", "https://h/a/b/1")
    assert not r.can_fetch("bot", "https://h/x")
    assert r.can_fetch("bot", "https://h/xy")


def test_empty_disallow_and_no_star_group():
    assert RobotsPolicy.parse("User-agent: *\nDisallow:\n").can_fetch("b", "https://h/anything")
    only_named = RobotsPolicy.parse("User-agent: GPTBot\nDisallow: /\n")
    assert only_named.can_fetch("TrendCheckerBot", "https://h/pt")


def test_ppomppu_rules():
    r = RobotsPolicy.parse("User-agent: *\nAllow: /zboard/\nDisallow: /zboard/view.php?id=my\nDisallow: /search_bbs.php\n")
    assert r.can_fetch("TrendCheckerBot", "https://www.ppomppu.co.kr/rss.php?id=stock")
    assert not r.can_fetch("TrendCheckerBot", "https://www.ppomppu.co.kr/zboard/view.php?id=my&no=1")


def test_deny_all():
    assert not RobotsPolicy.deny_everything().can_fetch("b", "https://h/")
