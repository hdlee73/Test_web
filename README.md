# Trend Checker (금융 상시감시용)

국내 커뮤니티 게시판의 **공개 목록 제목**에서 금융·금융회사 키워드를 집계해
오늘 / 최근 3일 / 최근 5일 트렌드와 관심 키워드 게시물 목록을 보여주는 비상업용 공개 웹페이지입니다.

## 소스 카테고리
| 카테고리 | 소스 | 방식 |
| --- | --- | --- |
| 공시 | DART 전자공시 | 오픈API(`DART_API_KEY` 필요, https://opendart.fss.or.kr) |
| 뉴스 | 네이버 뉴스 | 네이버 검색 API(`NAVER_CLIENT_ID/SECRET`), 질의어 `config/naver_news_queries.txt` |
| 게시판 | 커뮤니티 12곳 + 네이버 블로그 | robots.txt 준수, 목록 1페이지/RSS |

제외한 소스(robots.txt 금지: 디시·엠팍·펨코·82쿡·SLR클럽·딴지, 열람 제한: 네이버 카페)는 `sources.yaml` 의 `off_reason` 에 사유를 적고 화면 '수집 현황'에 표시한다.

## 감시 기능
- `config/risk_terms.yaml`: 위험 신호어(6개 분류)와 중요 공시 유형. 제목에서 부분 일치로 찾고 `alerts.json` 으로 내보낸다.
- 화면 구성: 게시판 모니터링(게시판 글의 위험 신호어 + 내 키워드), 뉴스(최근 12시간 TOP10 키워드), 조회공시/풍문(최근 5일), 자금조달(증권신고서 현황, 펀드 제외), 게시판, 키워드 순위, 위험 신호 히트맵, 급상승, 수집 현황.
- 자금조달은 DART 증권신고서 주요정보 API(지분증권 estkRs·채무증권 bdRs 등)로 증권종류·모집(매출)총액·청약일·납입일을 정리해 `funding.json` 으로 낸다.

## 수집 원칙
- 게시판 목록 1페이지 또는 RSS 만 읽습니다. 게시물 본문 페이지는 열지 않습니다.
- 요청마다 robots.txt 를 확인하고, 허용되지 않은 경로는 수집하지 않습니다.
- 같은 사이트에는 6초 이상 간격으로 한 번에 하나씩만 요청합니다.
- 403·429·봇 확인 페이지를 받으면 1→3→6→24시간 쉬고, 4회 연속이면 `disabled` 로 표시합니다. 차단 우회는 하지 않습니다.
- 저장·공개하는 정보는 제목, 원문 링크, 시각, 게시판 이름뿐입니다. 작성자와 본문은 저장하지 않습니다.
- 게시판 운영자가 요청하면 `sources.yaml` 에서 끄고 `Store.delete_source()` 로 데이터를 지웁니다.

## 구조
```
config/                  sources.yaml(게시판) · finance_dict.yaml(금융 사전) · exclude_keywords.txt(집계에서 뺄 광범위 단어) · watchlist.yaml · stopwords.txt
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
| alerts.json | 위험 신호어 분류·급증, 공시 유형별 요약 |
| candidates.json | 사전에 없는 새 키워드 후보 (사전 보강용) |

## 배포 (GitHub Pages)
`.github/workflows/collect.yml` 이 30분마다 수집 → 분석 → `site/data/*.json` 생성 → Pages 배포를 합니다.
- 저장소 Settings → Pages → Source 를 **GitHub Actions** 로 지정(한 번만).
- 공시를 받으려면 Secrets 에 `DART_API_KEY` 를 추가합니다. 키가 없으면 공시만 "API 키 없음"으로 표시됩니다.
- 네이버 검색 API 를 쓰려면 Settings → Secrets and variables → Actions 에 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` 을 추가합니다. 키가 없으면 해당 항목은 "API 키 없음"으로 표시되고 나머지는 정상 동작합니다. 질의어는 `config/naver_queries.txt`.
- 공개 저장소는 60일간 저장소 활동이 없으면 예약 실행이 멈춥니다. 멈추면 Actions 탭에서 Run workflow 로 다시 시작합니다.
- 수집 DB 는 Actions 캐시에 이어 저장되며, 잃어버려도 다음 수집부터 다시 쌓입니다(급상승·3일/5일 집계는 며칠 걸려 채워짐).

## FSS Insights 통합 계획
- 이 저장소(`Test_web`)는 수집·분석과 JSON 산출을 맡고, 화면은 FSS Insights 웹(`fss-insights-web`)의 새 화면 `js/screens/trend.js` 로 만들어 `tools/sync_web_assets.py` 로 앱에 복사합니다.
- 화면은 이 저장소가 공개하는 `data/*.json`(GitHub Pages)만 읽습니다. 관심 키워드는 기존 `store` 규칙대로 브라우저에 저장합니다.
- 디자인은 FSS Insights 네이비 콘솔(파랑 강조, 상승 빨강·하락 파랑, Pretendard)을 따릅니다.
