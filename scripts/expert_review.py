"""전문가 정답 검토: 검토지 내보내기와 결과 집계.

  python scripts/expert_review.py export [--out review/expert_review.csv]
      → 문항마다 상황·보기(유형)·현재 정답·해설과 빈 검토 칸이 있는 CSV (엑셀에서 바로 열림)
  python scripts/expert_review.py summarize review/filled/*.csv [--out review/expert_summary.csv]
      → 검토자 여러 명의 CSV를 모아 문항별 정답 동의율·다른 정답 제안·단서 명확성 평균, 다시 볼 문항 목록

검토자는 '정답 동의'(Y/N), 동의하지 않으면 '내가 고른 정답'(A~D, 최선·최악은 'A,C'), '단서 명확성'(1~5), '의견'을 채운다.
판정: 동의율 70% 미만이거나 단서 명확성 평균 3 미만이면 '다시 보기'. 검토자 3명 이상을 권장한다.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.item_bank import load_items  # noqa: E402
from core.schema import BLUEPRINT, DIFFICULTY_LABELS, STYLES, ItemFormat  # noqa: E402

LETTERS = "ABCD"
REVIEW_COLS = ["정답 동의(Y/N)", "내가 고른 정답", "단서 명확성(1~5)", "의견"]
AGREE_MIN = 0.70
CLARITY_MIN = 3.0


def key_text(it) -> str:
    if it.format is ItemFormat.BEST_WORST:
        b, w = it.answer
        return f"{LETTERS[b]},{LETTERS[w]}"
    return LETTERS[it.answer]


def export(out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    items = sorted(load_items(), key=lambda it: it.id)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["문항", "영역", "난이도", "형식", "상황", "A", "B", "C", "D", "현재 정답", "해설", "근거"] + REVIEW_COLS)
        for it in items:
            names = ([f" [{STYLES[it.domain][s].name}]" for s in it.styles] if it.styles else [""] * 4)
            w.writerow([it.id, BLUEPRINT[it.domain].label, DIFFICULTY_LABELS[it.difficulty],
                        "최선,최악" if it.format is ItemFormat.BEST_WORST else "4지선다", it.prompt,
                        *[c + n for c, n in zip(it.choices, names)], key_text(it), it.explanation, it.rationale]
                       + [""] * len(REVIEW_COLS))
    print(f"저장: {out} ({len(items)}문항). 검토자마다 복사해 '{REVIEW_COLS[0]}'부터 채워 주세요.")


def summarize(files: list[Path], out: Path) -> None:
    items = {it.id: it for it in load_items()}
    votes: dict[str, list[dict]] = defaultdict(list)
    for p in files:
        with p.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get(REVIEW_COLS[0], "").strip():
                    votes[row["문항"]].append(row)
    rows = []
    for iid, vs in sorted(votes.items()):
        if iid not in items:
            continue
        agree = [v[REVIEW_COLS[0]].strip().upper().startswith("Y") for v in vs]
        alt = Counter(v[REVIEW_COLS[1]].strip().upper().replace(" ", "") for v, a in zip(vs, agree) if not a and v[REVIEW_COLS[1]].strip())
        clarity = [float(v[REVIEW_COLS[2]]) for v in vs if v[REVIEW_COLS[2]].strip().replace(".", "").isdigit()]
        rate = sum(agree) / len(agree)
        mean_c = sum(clarity) / len(clarity) if clarity else float("nan")
        flag = rate < AGREE_MIN or (clarity and mean_c < CLARITY_MIN)
        rows.append({"문항": iid, "검토자": len(vs), "정답 동의율": f"{rate:.0%}", "현재 정답": key_text(items[iid]),
                     "다른 정답 제안": ", ".join(f"{k}×{n}" for k, n in alt.most_common()),
                     "단서 명확성 평균": "" if not clarity else f"{mean_c:.1f}", "판정": "다시 보기" if flag else "통과",
                     "의견": " / ".join(v[REVIEW_COLS[3]].strip() for v in vs if v[REVIEW_COLS[3]].strip())})
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["문항"])
        w.writeheader()
        w.writerows(rows)
    flagged = [r for r in rows if r["판정"] == "다시 보기"]
    print(f"검토 파일 {len(files)}개 · 문항 {len(rows)}개 집계 · 다시 볼 문항 {len(flagged)}개 → {out}")
    for r in flagged[:20]:
        print(f"  {r['문항']}: 동의 {r['정답 동의율']} · 제안 {r['다른 정답 제안'] or '-'} · 명확성 {r['단서 명확성 평균'] or '-'}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--out", type=Path, default=ROOT / "review" / "expert_review.csv")
    s = sub.add_parser("summarize")
    s.add_argument("files", nargs="+", type=Path)
    s.add_argument("--out", type=Path, default=ROOT / "review" / "expert_summary.csv")
    args = ap.parse_args()
    if args.cmd == "export":
        export(args.out)
    else:
        summarize(args.files, args.out)


if __name__ == "__main__":
    main()
