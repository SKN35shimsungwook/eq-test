"""문항 검토용 HTML 생성: python scripts/render_review.py [영역 코드 ...] → review/items_review.html

영역·유형·난이도 순으로 모든 문항(동형 포함)을 보여 준다. 최선(정답) 보기는 초록, 최악 보기는 빨강으로 표시하고
응시자에게 보이는 해설과 검토용 정답 근거를 함께 싣는다. 자기평가 문항도 뒤에 붙인다.
정답 위치는 출제 때처럼 슬롯마다 섞인 상태로 보여 준다.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.item_bank import items_by_slot, load_items, load_self_items  # noqa: E402
from core.schema import BLUEPRINT, DIFFICULTY_LABELS, FIXED_SLOTS, SLOTS, Domain, ItemFormat  # noqa: E402

OUT = ROOT / "review" / "items_review.html"
LETTERS = "ABCD"

CSS = """
body{font-family:-apple-system,'Malgun Gothic',sans-serif;max-width:920px;margin:24px auto;padding:0 16px;
     color:#111827;background:#f9fafb;line-height:1.6}
h1{font-size:22px} h2{margin-top:44px;border-bottom:2px solid #0F766E;padding-bottom:6px}
h3{margin:28px 0 4px;font-size:15px;color:#374151}
.item{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;margin:10px 0}
.meta{font-size:13px;color:#6b7280}
.id{font-family:monospace;font-weight:700;color:#0F766E}
.prompt{font-size:16px;margin:6px 0 10px}
.choice{border:2px solid #e5e7eb;border-radius:8px;padding:6px 10px;margin:6px 0}
.choice b{color:#6b7280;margin-right:6px}
.best{border-color:#16a34a;background:#f0fdf4} .worst{border-color:#dc2626;background:#fef2f2}
.tag{font-size:12px;font-weight:700;margin-left:6px} .best .tag{color:#16a34a} .worst .tag{color:#dc2626}
.exp{margin-top:8px;font-size:14px;background:#ecfdf5;border-radius:6px;padding:8px 10px}
.why{margin-top:6px;font-size:13px;color:#4b5563;background:#f3f4f6;border-radius:6px;padding:6px 10px}
table{border-collapse:collapse;width:100%;background:#fff} td,th{border:1px solid #e5e7eb;padding:6px 8px;font-size:14px}
.empty{color:#9ca3af;font-size:13px}
"""


def render_item(it) -> str:
    best, worst = (it.answer, None) if it.format is ItemFormat.MCQ else it.answer
    rows = []
    for i, c in enumerate(it.choices):
        cls, tag = ("best", "정답" if worst is None else "가장 효과적") if i == best else \
                   ("worst", "가장 덜 효과적") if i == worst else ("", "")
        rows.append(f'<div class="choice {cls}"><b>{LETTERS[i]}</b>{html.escape(c)}'
                    f'{f"<span class=tag>{tag}</span>" if tag else ""}</div>')
    timer = f" · {it.time_limit}초" if it.time_limit else ""
    fmt = "4지선다" if it.format is ItemFormat.MCQ else "최선·최악"
    return (f'<div class="item"><div class="meta"><span class="id">{it.id}</span> · {fmt}{timer} · '
            f'예상 정답률 {it.expected_p:.0%}</div><div class="prompt">{html.escape(it.prompt)}</div>{"".join(rows)}'
            f'<div class="exp">해설: {html.escape(it.explanation)}</div>'
            f'<div class="why">근거: {html.escape(it.rationale)}</div></div>')


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    only = {Domain(a) for a in sys.argv[1:]} or set(Domain)
    items = load_items()
    pool = items_by_slot(items)
    parts = [f"<h1>EQ 문항 검토 ({len([i for i in items if i.domain in only])}문항)</h1>",
             "<p class=meta>초록 = 정답(가장 효과적), 빨강 = 가장 덜 효과적. 정답 위치는 출제 때처럼 슬롯마다 섞여 있습니다.</p>"]
    for domain, spec in BLUEPRINT.items():
        if domain not in only:
            continue
        n = sum(len(pool.get(s, [])) for s in spec.pool)
        parts.append(f"<h2>{spec.label} ({n}문항)</h2>")
        for subtype, name in spec.subtypes.items():
            for level in range(1, 5):
                sid = f"{domain.value}-{subtype}-{level}"
                group = sorted(pool.get(sid, []), key=lambda it: it.id)
                role = "1·2·3차 고정" if sid in FIXED_SLOTS else "심층검사용"
                parts.append(f"<h3>{name} · {DIFFICULTY_LABELS[level]} <span class=meta>({sid}, {role}, {len(group)}개)</span></h3>")
                parts += [render_item(it) for it in group] or ["<p class=empty>아직 없음</p>"]
    self_items = load_self_items()
    rows = "".join(
        f"<tr><td class=id>{it.id}</td><td>{BLUEPRINT[it.domain].label if it.domain else '응답 점검'}</td>"
        f"<td>{html.escape(it.text)}</td><td>{'역문항' if it.reverse else ''}{'점검' if it.check else ''}</td></tr>"
        for it in self_items)
    parts.append(f"<h2>자기평가 ({len(self_items)}문항)</h2><p class=meta>1(전혀 아니다) ~ 5(매우 그렇다). "
                 "역문항은 점수를 뒤집고, 점검 문항은 지나치게 좋게만 답하는지 봅니다.</p>"
                 f"<table><tr><th>ID</th><th>영역</th><th>문항</th><th>구분</th></tr>{rows}</table>")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(f"<!doctype html><meta charset=utf-8><title>EQ 문항 검토</title><style>{CSS}</style>{''.join(parts)}",
                   encoding="utf-8")
    print(f"저장: {OUT}")


if __name__ == "__main__":
    main()
