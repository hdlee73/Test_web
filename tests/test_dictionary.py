from trendchecker.analysis.dictionary import FinanceMatcher
from trendchecker.config import load_dictionary

M = FinanceMatcher(load_dictionary())


def names(t):
    return [e.name for e in M.keywords(t)]


def test_alias_to_canonical():
    assert names("카뱅 파킹통장 금리 또 내렸네") == ["카카오뱅크", "파킹통장", "금리"]
    assert names("국민은행 주담대 갈아탔어요") == ["KB국민은행", "주택담보대출"]


def test_longest_wins():
    assert names("기준금리 인하 전망") == ["기준금리", "금리인하"]
    assert names("기준금리 동결") == ["기준금리"]
    assert names("미국 주식 vs 국내 주식") == ["미국주식", "국내주식"]


def test_ascii_boundary():
    assert "KB국민은행" not in names("KBO 한국시리즈 결과")
    assert names("ETF 추천 좀") == ["ETF"]
    assert names("SETF") == []


def test_ambiguous_needs_context():
    assert names("키움 오늘 경기 이겼다") == []
    assert names("키움 앱으로 주식 매수") == ["키움증권", "주식"]
    assert names("코인노래방 갔다옴") == []
    assert names("코인 폭락 무섭네요") == ["가상자산"]
    assert names("리플 달아주세요") == []


def test_one_count_per_post():
    assert names("금리 금리 금리") == ["금리"]
