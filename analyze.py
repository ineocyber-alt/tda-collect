#!/usr/bin/env python3
"""중간 보고서용 초기 분석: 전처리(G1) -> 빈도 분석(Topic 2) -> 공출현 네트워크(Topic 3) -> 교차검증.

사용 예
  python analyze.py --docs data/docs.csv --out out
결과: out/results.json, out/network.png
"""
import argparse
import collections
import csv
import html
import itertools
import json
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
from kiwipiepy import Kiwi
from matplotlib import font_manager

KEEP_TAGS = {"NNG", "NNP", "SL"}
STOP = set("""기자 뉴스 단독 속보 오늘 내일 어제 관련 대한 이번 지난 올해 현재 통해 위해 대해 경우 문제 사진 영상 종합
포토 오전 오후 한국 연합뉴스 제공 이후 가운데 사실 지금 우리 정도 최근 때문 오늘의 사람 이상 이하 가능 이유 상황 결과
발표 진행 개최 예정 확인 시작 계획 지원 대표 주요 전망 논란 위원장""".split())

FONT_CANDIDATES = ["Malgun Gothic", "AppleGothic", "Apple SD Gothic Neo", "NanumGothic",
                   "NanumBarunGothic", "Noto Sans CJK KR", "Noto Sans CJK JP", "Noto Sans CJK SC"]


def pick_font():
    have = {f.name for f in font_manager.fontManager.ttflist}
    for name in FONT_CANDIDATES:
        if name in have:
            return name
    return None


def clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"https?://\S+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def norm_token(form, tag):
    if tag == "SL":
        f = form.strip()
        if len(f) < 2:
            return None
        return f.upper() if len(f) <= 3 else f.lower()
    return form if len(form) >= 2 else None




def read_docs(path):
    """CSV 파일 하나, 또는 날짜별 파일이 든 폴더(data/YYYY-MM/YYYY-MM-DD.csv)를 읽는다."""
    if os.path.isdir(path):
        import glob
        files = sorted(glob.glob(os.path.join(path, "**", "*.csv"), recursive=True))
    else:
        files = [path]
    rows = []
    for p in files:
        with open(p, newline="", encoding="utf-8-sig") as f:
            rows += list(csv.DictReader(f))
    return rows


def layout_components(G):
    """연결 요소마다 따로 배치한 뒤 격자에 놓아, 떨어진 군집끼리 겹치거나 한 점으로 뭉치지 않게 한다."""
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    cols = max(1, int(len(comps) ** 0.5 + 0.999))
    pos = {}
    for i, comp in enumerate(comps):
        sub = G.subgraph(comp)
        n = len(comp)
        if n == 1:
            local = {next(iter(comp)): (0.0, 0.0)}
        else:
            local = nx.spring_layout(sub, k=2.0 / n ** 0.5, iterations=300, seed=42, weight="weight")
        r = min(2.1, 0.5 + 0.38 * n ** 0.5)
        cx, cy = (i % cols) * 4.6, -(i // cols) * 4.6
        for node, (x, y) in local.items():
            pos[node] = (cx + x * r, cy + y * r)
    return pos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="data/docs.csv")
    ap.add_argument("--out", default="out")
    ap.add_argument("--topn", type=int, default=15)
    ap.add_argument("--net_nodes", type=int, default=40)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    rows = read_docs(a.docs)
    if not rows:
        raise SystemExit("docs.csv 가 비어 있습니다. collect.py 를 먼저 실행하세요.")
    kiwi = Kiwi()

    news = [r for r in rows if r["kind"] == "news"]
    trends = [r for r in rows if r["kind"] == "trend"]
    stamps = sorted({r["collected_at"] for r in rows})

    # ---------- 1. 전처리 ----------
    raw_chars = clean_chars = 0
    all_tokens = kept_tokens = 0
    vocab_all, vocab_kept = set(), set()
    doc_tokens = []
    examples = []
    for r in news:
        text = clean(r["title"] + " " + (r["summary"] or ""))[:400]
        raw_chars += len(r["title"]) + len(r["summary"] or "")
        clean_chars += len(text)
        toks = kiwi.tokenize(text)
        n_all = len(toks)
        kept = []
        for t in toks:
            vocab_all.add(t.form)
            if t.tag in KEEP_TAGS:
                w = norm_token(t.form, t.tag)
                if w and w not in STOP:
                    kept.append(w)
        all_tokens += n_all
        kept_tokens += len(kept)
        vocab_kept.update(kept)
        doc_tokens.append(kept)
        if len(examples) < 3 and len(kept) >= 4:
            examples.append({"source": r["source"], "title": r["title"], "tokens": kept[:10]})

    # ---------- 2. 빈도 분석 (문서빈도 DF) ----------
    df = collections.Counter()
    tf = collections.Counter()
    for kept in doc_tokens:
        tf.update(kept)
        df.update(set(kept))
    top_df = [{"word": w, "df": c, "tf": tf[w]} for w, c in df.most_common(a.topn)]
    src_counts = collections.Counter(r["source"] for r in rows)
    src_counts_ordered = [{"source": s, "n": n} for s, n in src_counts.most_common()]

    # ---------- 3. 공출현 네트워크 ----------
    cand = [w for w, c in df.most_common(a.net_nodes) if c >= 2]
    cset = set(cand)
    co = collections.Counter()
    for kept in doc_tokens:
        ws = sorted(set(kept) & cset)
        for x, y in itertools.combinations(ws, 2):
            co[(x, y)] += 1
    G = nx.Graph()
    for (x, y), w in co.items():
        if w >= 2:
            G.add_edge(x, y, weight=w)
    net = {"nodes": 0, "edges": 0, "density": 0.0, "communities": [], "top_edges": [], "top_degree": []}
    if G.number_of_edges() > 0:
        comms = list(nx.algorithms.community.greedy_modularity_communities(G, weight="weight"))
        comms.sort(key=lambda c: -sum(df[w] for w in c))
        palette = ["#004B85", "#C0603A", "#0E7490", "#6E3FA0", "#8FA0B3", "#3F4E63"]
        color = {}
        for i, c in enumerate(comms):
            for w in c:
                color[w] = palette[i % len(palette)]
        pos = layout_components(G)
        font = pick_font()
        if font:
            plt.rcParams["font.family"] = font
        plt.rcParams["axes.unicode_minus"] = False
        fig, ax = plt.subplots(figsize=(8.2, 6.4), dpi=170)
        maxw = max(d["weight"] for _, _, d in G.edges(data=True))
        nx.draw_networkx_edges(G, pos, ax=ax, edge_color="#8FA0B3", alpha=0.55,
                               width=[0.6 + 3.2 * d["weight"] / maxw for _, _, d in G.edges(data=True)])
        nx.draw_networkx_nodes(G, pos, ax=ax, node_color=[color[n] for n in G.nodes()],
                               node_size=[90 + 28 * df[n] for n in G.nodes()], alpha=0.92, linewidths=0)
        nx.draw_networkx_labels(G, pos, ax=ax, font_size=12, font_color="#22303E")
        ax.axis("off")
        fig.tight_layout(pad=0.2)
        fig.savefig(os.path.join(a.out, "network.png"), facecolor="white")
        plt.close(fig)
        net = {
            "nodes": G.number_of_nodes(), "edges": G.number_of_edges(),
            "density": round(nx.density(G), 3),
            "communities": [{"color": palette[i % len(palette)],
                             "words": sorted(c, key=lambda w: -df[w])[:6]} for i, c in enumerate(comms[:4])],
            "top_edges": [{"a": x, "b": y, "w": w} for (x, y), w in co.most_common(5)],
            "top_degree": [{"word": w, "deg": d} for w, d in sorted(G.degree(), key=lambda t: -t[1])[:5]],
        }

    # ---------- 4. 교차검증: 검색 급상승어 vs 뉴스 ----------
    def norm(s):
        return re.sub(r"\s+", "", s or "").lower()

    news_norm = [(r["source"], norm(clean(r["title"] + " " + (r["summary"] or "")))) for r in news]
    kw_rounds = collections.defaultdict(set)
    kw_traffic = {}
    for r in trends:
        kw_rounds[r["title"]].add(r["collected_at"])
        kw_traffic[r["title"]] = r["traffic"] or kw_traffic.get(r["title"], "")
    cross = []
    for kw, rs in kw_rounds.items():
        k = norm(kw)
        hits = [s for s, t in news_norm if k and k in t]
        cross.append({"keyword": kw, "traffic": kw_traffic.get(kw, ""), "rounds": len(rs),
                      "news_docs": len(hits), "news_sources": len(set(hits))})
    cross.sort(key=lambda d: (-d["news_docs"], -d["rounds"]))
    matched = sum(1 for d in cross if d["news_docs"] > 0)
    cv = {"n_keywords": len(cross), "matched": matched,
          "ratio": round(matched / len(cross), 3) if cross else 0.0, "rows": cross[:8]}

    # ---------- 5. 자동 관찰 ----------
    obs = []
    if top_df:
        obs.append("뉴스 문서빈도 상위 키워드는 " + ", ".join(d["word"] for d in top_df[:5]) + " 입니다.")
    if cv["n_keywords"]:
        obs.append(f"구글 급상승어 {cv['n_keywords']}개 중 {matched}개({cv['ratio']*100:.0f}%)가 "
                   f"수집한 뉴스 제목·요약에서 확인되었습니다.")
    if net["communities"]:
        obs.append(f"공출현 네트워크는 {net['nodes']}개 단어, {net['edges']}개 연결, "
                   f"{len(net['communities'])}개 이상의 주제 군집으로 나뉩니다.")

    results = {
        "n_docs": len(rows), "n_news": len(news), "n_trend": len(trends),
        "n_sources": len(src_counts), "sources": src_counts_ordered,
        "period": [stamps[0], stamps[-1]], "n_rounds": len(stamps),
        "prep": {"raw_chars": raw_chars, "clean_chars": clean_chars,
                 "tokens_all": all_tokens, "tokens_kept": kept_tokens,
                 "vocab_all": len(vocab_all), "vocab_kept": len(vocab_kept),
                 "examples": examples},
        "top_df": top_df, "network": net, "cross": cv, "observations": obs,
        "has_network_png": os.path.exists(os.path.join(a.out, "network.png")),
    }
    with open(os.path.join(a.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"완료: {a.out}/results.json  (문서 {len(rows)}건, 뉴스 {len(news)}건, 트렌드 {len(trends)}건)")


if __name__ == "__main__":
    main()
