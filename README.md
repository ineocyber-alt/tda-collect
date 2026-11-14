# 핫이슈 수집 (GitHub Actions)

GitHub Actions 가 매시간 `collect.py` 를 실행해 공개 RSS 의 제목·요약·링크를
`data/YYYY-MM/YYYY-MM-DD.csv` (한국 시간 기준 날짜별 파일)에 쌓고, 저장소에 자동 커밋합니다.

- 수집 주기: `.github/workflows/collect.yml` 의 `cron` (UTC 기준)
- 피드 목록: `feeds.json` (접속 실패하는 피드는 주소를 고치거나 지우세요)
- 뉴스는 최근 3일 치 파일과 비교해 같은 기사를 다시 저장하지 않습니다. 검색어(trend)는 회차마다 저장합니다.

## 분석
```
git pull
python analyze.py --docs data --out out            # 전체 기간
python analyze.py --docs data/2026-11 --out out_11  # 11월만
python analyze.py --docs data/2026-11/2026-11-14.csv --out out_1114  # 하루만
```
