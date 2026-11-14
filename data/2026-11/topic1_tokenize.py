#!/usr/bin/env python3
"""G1 Topic 1: Tokenization & POS Tagging — Kiwi 형태소 분석으로 명사만 뽑아낸다.

입력: collect.py 가 만든 CSV 파일 하나, 또는 날짜별 파일 폴더(data/YYYY-MM/YYYY-MM-DD.csv)

사용 예
  python topic1_tokenize.py --docs data --out out_t1                 # 전체 기간
  python topic1_tokenize.py --docs data/2026-11 --out out_t1_11      # 11월만
  python topic1_tokenize.py --docs data --out out_t1 --keep-sl       # 영문(AI, BTS 등)도 포함
  python topic1_tokenize.py --docs data --out out_t1 --userdict userdict.txt --stopwords stop.txt

결과 (out 폴더, 엑셀에서 바로 열리도록 UTF-8 BOM)
  tokens.csv          문서별 명사 목록 (date, collected_at, source, kind, title, nouns)
  noun_freq.csv       명사 빈도 (tf: 전체 등장 수, df: 등장한 문서 수) 내림차순
  daily_top.csv       날짜별 상위 명사 (df 기준)
  pos_sample.txt      형태소·품사 태깅 예시 (보고서 캡처용)
  summary.json        전처리 전후 수치 (문서 수, 토큰 수, 어휘 수)
"""
import argparse
import collections
import csv
import glob
import html
import json
import os
import re

from kiwipiepy import Kiwi

NOUN_TAGS = {"NNG", "NNP"}          # 일반명사, 고유명사
STOP = set("""기자 뉴스 단독 속보 오늘 내일 어제 관련 대한 이번 지난 올해 현재 통해 위해 대해 경우 문제 사진 영상 종합
포토 오전 오후 연합뉴스 제공 이후 가운데 사실 지금 우리 정도 최근 때문 사람 이상 이하 가능 이유 상황 결과
발표 진행 개최 예정 확인 시작 계획 지원 대표 주요 전망""".split())


def read_docs(path):
    if os.path.isdir(path):
        files = sorted(glob.glob(os.path.join(path, "**", "*.csv"), recursive=True))
    else:
        files = [path]
    rows = []
    for p in files:
        with open(p, newline="", encoding="utf-8-sig") as f:
            rows += list(csv.DictReader(f))
    return rows, files


def clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))   # HTML 태그 제거
    text = re.sub(r"https?://\S+", " ", text)                   # URL 제거
    text = re.sub(r"\[[^\]]{1,20}\]", " ", text)                # [속보] [단독] 같은 말머리 제거
    return re.sub(r"\s+", " ", text).strip()


def load_words(path):
    if not path:
        return []
    with open(path, encoding="utf-8-sig") as f:
        return [w.strip() for w in f if w.strip() and not w.startswith("#")]


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="data", help="CSV 파일 또는 날짜별 CSV 폴더")
    ap.add_argument("--out", default="out_t1")
    ap.add_argument("--kind", default="news", choices=["news", "trend", "all"],
                    help="news: 뉴스만(기본), trend: 검색어 행만, all: 전부")
    ap.add_argument("--title-only", action="store_true", help="요약은 빼고 제목만 분석")
    ap.add_argument("--keep-sl", action="store_true", help="영문 단어(SL)도 명사처럼 포함")
    ap.add_argument("--userdict", default="", help="사용자 사전: 한 줄에 단어 하나 (고유명사로 등록)")
    ap.add_argument("--stopwords", default="", help="추가 불용어: 한 줄에 단어 하나")
    ap.add_argument("--daily-top", type=int, default=20, help="날짜별 상위 명사 개수")
    a = ap.parse_args()

    rows, files = read_docs(a.docs)
    if a.kind != "all":
        rows = [r for r in rows if r.get("kind") == a.kind]
    if not rows:
        raise SystemExit(f"분석할 행이 없습니다: {a.docs} (kind={a.kind})")
    os.makedirs(a.out, exist_ok=True)

    kiwi = Kiwi()
    for w in load_words(a.userdict):
        kiwi.add_user_word(w, "NNP")
    stop = STOP | set(load_words(a.stopwords))
    keep_tags = NOUN_TAGS | ({"SL"} if a.keep_sl else set())

    tf, df = collections.Counter(), collections.Counter()
    daily_df = collections.defaultdict(collections.Counter)
    daily_docs = collections.Counter()
    pos_lines = []
    tok_all = tok_noun = tok_kept = 0
    vocab_all, vocab_kept = set(), set()
    out_rows = []

    for r in rows:
        raw = r["title"] if a.title_only else f"{r['title']} {r.get('summary') or ''}"
        text = clean(raw)[:500]
        toks = kiwi.tokenize(text)

        nouns = []
        for t in toks:
            vocab_all.add(t.form)
            if t.tag not in keep_tags:
                continue
            tok_noun += 1
            w = t.form.strip()
            if t.tag == "SL":
                w = w.upper() if len(w) <= 3 else w.lower()
            if len(w) < 2 or w in stop:      # 1글자, 불용어 제거
                continue
            nouns.append(w)

        tok_all += len(toks)
        tok_kept += len(nouns)
        vocab_kept.update(nouns)
        tf.update(nouns)
        df.update(set(nouns))
        day = (r.get("collected_at") or "")[:10]
        daily_df[day].update(set(nouns))
        daily_docs[day] += 1
        out_rows.append([day, r.get("collected_at", ""), r.get("source", ""), r.get("kind", ""),
                         r["title"], " ".join(nouns)])

        if len(pos_lines) < 5 and len(toks) >= 5:
            tagged = " ".join(f"{t.form}/{t.tag}" for t in toks)
            pos_lines.append(f"[원문] {text}\n[형태소/품사] {tagged}\n[명사] {' '.join(nouns)}\n")

    write_csv(os.path.join(a.out, "tokens.csv"),
              ["date", "collected_at", "source", "kind", "title", "nouns"], out_rows)
    write_csv(os.path.join(a.out, "noun_freq.csv"), ["noun", "tf", "df"],
              [[w, tf[w], df[w]] for w, _ in df.most_common()])
    daily = []
    for day in sorted(daily_df):
        for rank, (w, n) in enumerate(daily_df[day].most_common(a.daily_top), 1):
            daily.append([day, rank, w, n, daily_docs[day]])
    write_csv(os.path.join(a.out, "daily_top.csv"), ["date", "rank", "noun", "df", "docs_that_day"], daily)
    with open(os.path.join(a.out, "pos_sample.txt"), "w", encoding="utf-8") as f:
        f.write("품사 태그: NNG 일반명사, NNP 고유명사, SL 영문, VV 동사, JKS/JKO 조사 ...\n\n")
        f.write("\n".join(pos_lines))

    days = sorted(d for d in daily_docs if d)
    summary = {
        "input_files": len(files), "docs": len(rows), "kind": a.kind,
        "period": [days[0], days[-1]] if days else [],
        "n_days": len(days),
        "tokens_all": tok_all, "tokens_noun": tok_noun, "tokens_kept": tok_kept,
        "vocab_all": len(vocab_all), "vocab_kept": len(vocab_kept),
        "top20": [[w, df[w]] for w, _ in df.most_common(20)],
    }
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"문서 {len(rows):,}건 ({summary['n_days']}일, 파일 {len(files)}개)")
    print(f"토큰 {tok_all:,} → 명사 {tok_noun:,} → 정제 후 {tok_kept:,}")
    print(f"어휘 {len(vocab_all):,} → {len(vocab_kept):,}")
    print("상위 명사(df):", ", ".join(f"{w}({n})" for w, n in summary["top20"][:10]))
    print(f"저장: {a.out}/ (tokens.csv, noun_freq.csv, daily_top.csv, pos_sample.txt, summary.json)")


if __name__ == "__main__":
    main()
