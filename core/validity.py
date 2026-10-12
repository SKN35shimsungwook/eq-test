"""응답 신뢰도: 이 사람의 응답을 믿고 읽어도 되는가 (EQ 점수는 바꾸지 않는다).

거짓말 탐지기가 아니라 경고등이다. 문항 하나하나가 솔직했는지는 알 수 없고, 응답 전체의 패턴만 본다.

신호 (기준값은 scripts/simulate_validity.py의 봇 검증으로 정했다):
1. 좋게 보이려는 경향: 누구나 있는 욕구·실수를 부정하는 진술 8개(시작 점검 4 + 마지막 욕구 4)에 '그렇다' 이상인 수
2. 일관성: 시작 자기평가 문항을 반대로 바꿔 마지막에 다시 물었을 때 3점 이상 어긋난 짝 수 (4쌍)
3. 자기평가 몰아 찍기: 자기평가·마지막 질문 전체에서 가장 많이 고른 칸의 비율 (역문항이 섞여 있어 성실하면 높지 않다)
4. 너무 빠른 응답: 문제 풀이에서 2.5초 안에 답한 비율
5. 한 자리 몰아 찍기: 문제 풀이에서 같은 위치(A~D)를 고른 비율 (정답 위치는 고르게 섞여 있다)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from core.schema import Item, ItemFormat, SelfItem

DENY_LOW, DENY_MID = 6, 4        # 욕구 부정 8개 중 이 이상이면 낮음 / 보통
INCONS_GAP = 3                   # 짝 문항 점수 차이가 이 이상이면 어긋남
INCONS_LOW = 2                   # 어긋난 짝이 이 이상이면 낮음
SELF_SAME_LOW = 0.80             # 자기평가 한 칸 비율
FAST_MS = 2500
FAST_LOW, FAST_MID = 0.50, 0.20  # 너무 빠른 응답 비율
POS_LOW, POS_MID = 0.60, 0.50    # 한 자리 비율
MIN_ROWS = 12                    # 문제 풀이 신호를 보려면 필요한 응답 수

LEVELS = ("높음", "보통", "낮음")


@dataclass
class Validity:
    level: str                               # 높음 | 보통 | 낮음
    reasons: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def low(self) -> bool:
        return self.level == "낮음"


def final_scores(final_items: list[SelfItem], self_items: list[SelfItem],
                 final_answers: dict[str, int], self_answers: dict[str, int]) -> dict:
    """마지막 질문 응답 → self_scores에 합칠 값 (_desire, _incons, _final_n, _self_same)."""
    by_id = {it.id: it for it in self_items}
    desire = sum(final_answers.get(it.id, 0) >= 4 for it in final_items if it.kind == "desire")
    incons, pairs = 0, 0
    for it in final_items:
        if it.kind != "repeat" or it.id not in final_answers or it.pair not in self_answers:
            continue
        pairs += 1
        a = by_id[it.pair].score(self_answers[it.pair])
        b = it.score(final_answers[it.id])
        incons += abs(a - b) >= INCONS_GAP
    answers = list(self_answers.values()) + list(final_answers.values())
    same = Counter(answers).most_common(1)[0][1] / len(answers) if answers else 0.0
    return {"_desire": desire, "_incons": incons, "_pairs": pairs, "_self_same": round(same, 3),
            "_final_n": len(final_answers)}


def careless(rows: list[dict], items: dict[str, Item]) -> dict:
    """문제 풀이 응답 → 너무 빠른 응답 비율, 한 자리 비율, 미응답 비율."""
    answered = [r for r in rows if r.get("answer") and r["item_id"] in items]
    n = len(rows)
    if not answered:
        return {"n": n, "fast": 0.0, "position": 0.0, "blank": 1.0 if n else 0.0}
    timed = [r for r in answered if r.get("response_ms") is not None]
    fast = sum(r["response_ms"] < FAST_MS for r in timed) / len(timed) if timed else 0.0
    pos = Counter(r["answer"].partition(",")[0] if items[r["item_id"]].format is ItemFormat.BEST_WORST
                  else r["answer"] for r in answered)
    return {"n": n, "fast": round(fast, 3), "position": round(pos.most_common(1)[0][1] / len(answered), 3),
            "blank": round(1 - len(answered) / n, 3) if n else 0.0}


def assess(self_scores: dict | None, rows: list[dict], items: dict[str, Item]) -> Validity:
    s = self_scores or {}
    c = careless(rows, items)
    deny = s.get("_checks", 0) + s.get("_desire", 0)
    low, mid = [], []
    if "_desire" in s:  # 마지막 질문까지 답한 경우만 8개 기준
        if deny >= DENY_LOW:
            low.append(f"누구나 있는 감정·욕구를 부정하는 답이 많습니다 ({deny}/8)")
        elif deny >= DENY_MID:
            mid.append(f"좋게 보이려는 답이 조금 있습니다 ({deny}/8)")
    if s.get("_incons", 0) >= INCONS_LOW:
        low.append(f"같은 내용을 다시 물었을 때 답이 크게 달랐습니다 ({s['_incons']}/{s.get('_pairs', 4)}쌍)")
    if s.get("_self_same", 0) >= SELF_SAME_LOW:
        low.append(f"자기평가를 한 칸에 몰아 답했습니다 ({s['_self_same']:.0%})")
    if c["n"] >= MIN_ROWS:
        if c["fast"] >= FAST_LOW:
            low.append(f"문제를 읽기 어려울 만큼 빨리 답한 경우가 많습니다 ({c['fast']:.0%})")
        elif c["fast"] >= FAST_MID:
            mid.append(f"아주 빨리 답한 문제가 꽤 있습니다 ({c['fast']:.0%})")
        if c["position"] >= POS_LOW:
            low.append(f"같은 위치의 보기를 몰아서 골랐습니다 ({c['position']:.0%})")
        elif c["position"] >= POS_MID:
            mid.append(f"같은 위치의 보기를 고른 경우가 많습니다 ({c['position']:.0%})")
    level = "낮음" if low else "보통" if mid else "높음"
    return Validity(level, low + mid, {"deny": deny, **{k: s.get(k) for k in ("_incons", "_self_same")}, **c})


SUMMARY = {
    "높음": "응답이 일관되고 성실해 보입니다. 결과를 그대로 읽어도 좋습니다.",
    "보통": "대체로 믿을 만하지만 아래 점을 감안해 읽어 주세요.",
    "낮음": "응답 패턴상 결과를 조심해서 읽어야 합니다. 자기평가 비교와 유형은 참고로만 보세요. "
            "EQ 점수는 그대로지만 실제보다 낮게 나왔을 수 있습니다.",
}
