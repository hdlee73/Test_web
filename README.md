# Trend Checker

국내 커뮤니티 게시판의 **공개 목록 제목**에서 금융·금융회사 키워드를 집계해
오늘 / 최근 3일 / 최근 5일 트렌드와 관심 키워드 게시물 목록을 보여주는 비상업용 공개 웹페이지입니다.

## 수집 원칙
- 게시판 목록 1페이지 또는 RSS 만 읽습니다. 게시물 본문 페이지는 열지 않습니다.
- 요청마다 robots.txt 를 확인하고, 허용되지 않은 경로는 수집하지 않습니다.
- 같은 사이트에는 6초 이상 간격으로 한 번에 하나씩만 요청합니다.
- 403·429·봇 확인 페이지를 받으면 1→3→6→24시간 쉬고, 4회 연속이면 `disabled` 로 표시합니다. 차단 우회는 하지 않습니다.
- 저장·공개하는 정보는 제목, 원문 링크, 시각, 게시판 이름뿐입니다. 작성자와 본문은 저장하지 않습니다.
- 게시판 운영자가 요청하면 `sources.yaml` 에서 끄고 `Store.delete_source()` 로 데이터를 지웁니다.

## 구조
```
config/                  sources.yaml(게시판) · finance_dict.yaml(금융 사전) · watchlist.yaml · stopwords.txt
trendchecker/collector/  robots 해석, 예의 있는 HTTP 클라이언트, RSS·링크 목록 파서, 수집 루프
trendchecker/analysis/   사전 매칭(가장 긴 표현 우선, 모호어는 문맥 필요), 집계, 급상승, Kiwi 새 키워드 후보
trendchecker/storage/    SQLite (state/trend.db, 7일 보관)
trendchecker/export/     웹 화면용 정적 JSON (site/data/)
```

## 로컬 실행 (Python 3.11+)
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python -m trendchecker check          # 게시판별 robots 허용 여부와 목록 파싱 결과 점검(저장 안 함)
python -m trendchecker run            # 수집 + 분석 + site/data/*.json 생성
python -m pytest -q                   # 테스트
```
`check` 결과에서 `게시물 0건` 인 게시판은 `post_pattern` 을 고쳐야 합니다.
오류는 `logs/error-YYYYMMDD.log` 에 traceback 과 함께 기록됩니다.

## 산출 JSON (site/data)
| 파일 | 내용 |
| --- | --- |
| meta.json | 생성 시각, 게시판 목록·상태, 고지문, 일자별 게시물 파일 목록 |
| trends.json | `windows.today/3d/5d` 키워드 순위(게시물 수, 게시판별 수, 종합 점수), 일자별 추이, 급상승, 대표 게시물 |
| posts-YYYYMMDD.json | 일자별 게시물 `{id, s(게시판), t(제목), u(링크), at, x(시각 정확 여부), k(키워드), f(금융글)}` |
| watchlist.json | `config/watchlist.yaml` 매칭 결과 |
| candidates.json | 사전에 없는 새 키워드 후보 (사전 보강용) |

## 배포
GitHub Actions 워크플로(`collect.yml`)는 수동 실행만 켜져 있습니다. 정기 실행과 Pages 배포는 명시적으로 지시할 때 켭니다.
