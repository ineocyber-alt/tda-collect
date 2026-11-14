#!/usr/bin/env python3
"""공개 RSS 기반 수집기 (제목·요약·링크만 저장).

사용 예
  python collect.py                       # 1회 수집
  python collect.py --rounds 12 --interval 30   # 30분 간격으로 12회 (약 6시간)

원칙
  - 공개 RSS / 공식 피드만 사용합니다. 로그인·우회·IP 변경 없음.
  - 본문은 저장하지 않고 제목, 요약, 링크, 시각만 저장합니다.
  - 피드 사이에 1초 이상 간격을 둡니다. 실패한 피드는 건너뛰고 로그만 남깁니다.
  - feeds.json 의 URL 은 직접 확인하세요. 언론사별 RSS 이용 조건은 각 사이트 안내를 따릅니다.
"""
import argparse
import csv
import datetime as dt
import glob
import json
import os
import sys
import time
import xml.etree.ElementTree as ET

import feedparser
import requests

KST = dt.timezone(dt.timedelta(hours=9))
UA = "TDA-course-project/1.0 (academic coursework; RSS titles only)"
FIELDS = ["collected_at", "source", "kind", "title", "summary", "link", "published", "traffic"]

DEFAULT_FEEDS = [
    {"name": "google_trends", "kind": "trend", "url": "https://trends.google.com/trending/rss?geo=KR"},
    {"name": "yonhap", "kind": "news", "url": "https://www.yna.co.kr/rss/news.xml"},
    {"name": "khan", "kind": "news", "url": "https://www.khan.co.kr/rss/rssdata/total_news.xml"},
    {"name": "donga", "kind": "news", "url": "https://rss.donga.com/total.xml"},
    {"name": "joongang", "kind": "news", "url": "https://rss.joins.com/joins_news_list.xml"},
    {"name": "hankyung", "kind": "news", "url": "https://www.hankyung.com/feed/all-news"},
    {"name": "mk", "kind": "news", "url": "https://www.mk.co.kr/rss/30000001/"},
    {"name": "jtbc", "kind": "news", "url": "https://fs.jtbc.co.kr/RSS/newsflash.xml"},
    {"name": "ohmynews", "kind": "news", "url": "http://rss.ohmynews.com/rss/ohmynews.xml"},
]


def now_kst():
    return dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def local(tag):
    return tag.split("}")[-1]


def fetch_trends(feed, stamp):
    """Google Trends RSS: 키워드, 대략적 검색량, 연결된 뉴스 제목."""
    r = requests.get(feed["url"], headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    rows = []
    for item in root.iter("item"):
        title, traffic, pub, news_titles = "", "", "", []
        for el in item.iter():
            name = local(el.tag)
            txt = (el.text or "").strip()
            if name == "title" and el is not None and not title and el.tag == "title":
                title = txt
            elif name == "approx_traffic":
                traffic = txt
            elif name == "pubDate":
                pub = txt
            elif name == "news_item_title" and txt:
                news_titles.append(txt)
        if title:
            rows.append({"collected_at": stamp, "source": feed["name"], "kind": "trend",
                         "title": title, "summary": " / ".join(news_titles), "link": "",
                         "published": pub, "traffic": traffic})
    return rows


def fetch_news(feed, stamp):
    r = requests.get(feed["url"], headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    parsed = feedparser.parse(r.content)
    rows = []
    for e in parsed.entries:
        title = (e.get("title") or "").strip()
        if not title:
            continue
        rows.append({"collected_at": stamp, "source": feed["name"], "kind": "news",
                     "title": title, "summary": (e.get("summary") or "").strip()[:500],
                     "link": e.get("link", ""), "published": e.get("published", ""), "traffic": ""})
    return rows


def load_seen(path):
    seen = set()
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r["kind"] == "news":
                    seen.add((r["source"], r["link"] or r["title"]))
    return seen


def daily_path(daily_dir, stamp):
    """2026-11-14 12:00:00 -> data/2026-11/2026-11-14.csv (KST 날짜 기준)"""
    day = stamp[:10]
    return os.path.join(daily_dir, day[:7], f"{day}.csv")


def load_seen_daily(daily_dir, days=3):
    """최근 며칠 치 파일만 읽어 중복 판단 (RSS 는 최신 글 위주라 이 정도면 충분)."""
    files = sorted(glob.glob(os.path.join(daily_dir, "*", "*.csv")))[-days:]
    seen = set()
    for p in files:
        seen |= load_seen(p)
    return seen


def append_rows(path, rows):
    new = not os.path.exists(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)


def run_once(feeds, out, seen, daily_dir=""):
    stamp = now_kst()
    if daily_dir:
        out = daily_path(daily_dir, stamp)
    total, report = 0, []
    for feed in feeds:
        try:
            rows = fetch_trends(feed, stamp) if feed["kind"] == "trend" else fetch_news(feed, stamp)
            if feed["kind"] == "news":
                rows = [r for r in rows if (r["source"], r["link"] or r["title"]) not in seen]
                seen.update((r["source"], r["link"] or r["title"]) for r in rows)
            append_rows(out, rows)
            total += len(rows)
            report.append(f"  ok   {feed['name']:<14} +{len(rows)}")
        except Exception as ex:  # 피드 하나가 실패해도 계속 진행
            report.append(f"  FAIL {feed['name']:<14} {type(ex).__name__}: {ex}")
        time.sleep(1.0)
    print(f"[{stamp}] 새로 저장 {total}건")
    print("\n".join(report))
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feeds", default="feeds.json")
    ap.add_argument("--out", default="data/docs.csv")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--interval", type=float, default=30, help="회차 간 간격(분)")
    ap.add_argument("--daily-dir", default="",
                    help="지정하면 날짜별 파일로 저장: <dir>/YYYY-MM/YYYY-MM-DD.csv (--out 무시)")
    a = ap.parse_args()

    feeds = DEFAULT_FEEDS
    if os.path.exists(a.feeds):
        feeds = json.load(open(a.feeds, encoding="utf-8"))
    else:
        json.dump(DEFAULT_FEEDS, open(a.feeds, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"{a.feeds} 생성됨 - 접속되지 않는 피드는 URL을 고치거나 지우세요.")

    seen = load_seen_daily(a.daily_dir) if a.daily_dir else load_seen(a.out)
    for i in range(a.rounds):
        print(f"--- round {i + 1}/{a.rounds}")
        run_once(feeds, a.out, seen, a.daily_dir)
        if i < a.rounds - 1:
            time.sleep(a.interval * 60)
    print(f"완료: {a.daily_dir or a.out}")


if __name__ == "__main__":
    sys.exit(main())
