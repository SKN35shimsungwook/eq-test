"""결과 화면용 분석 (Streamlit 없이 테스트 가능한 순수 로직).

차수(1·2·3차·심층검사)마다의 평가와, 모든 차수를 합친 최종 결과를 계산한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from core import exam as ex
from core import scoring as sc
from core.schema import BLUEPRINT, DEEP_ROUND, DIFFICULTY_LABELS, Domain, Item, round_label

GUESS_SEC = 4.0  # 상황을 읽기도 전에 낸 오답 → 찍었을 가능성이 높다 (EQ 문항은 문장이 길어 IQ보다 길게)


@dataclass
class Score:
    """θ 추정치를 EQ(평균 100, 표준편차 15)로 옮긴 값."""
    theta: float
    se: float
    index: float
    lo: float
    hi: float
    pct: float

    @property
    def margin(self) -> float:
        return (self.hi - self.lo) / 2


def stage(n_rounds: int, deep: bool = False) -> str:
    """시뮬레이션 규준의 단계 이름: 1차만 "1", 1~2차 "1-2", 1~3차 "1-3", 심층검사까지 "1-3+deep"."""
    base = "1" if n_rounds <= 1 else f"1-{min(n_rounds, 3)}"
    return f"{base}+deep" if deep else base


def scale(theta: float, se: float, norm: sc.Norm, domain: Domain | None = None, stage: str | None = None) -> Score:
    """θ̂·SE → EQ 척도. 90% 범위는 θ̂ ± 1.645·SE의 양 끝을 같은 기준으로 옮겨 구한다."""
    z = norm.z(theta, domain, stage)
    index = sc.to_index(z)
    lo = sc.to_index(norm.z(theta - sc.CI_Z * se, domain, stage))
    hi = sc.to_index(norm.z(theta + sc.CI_Z * se, domain, stage))
    return Score(theta, se, index, min(lo, index), max(hi, index), sc.percentile(z))


@dataclass
class RoundData:
    round: int
    seed: int
    progress: dict
    rows: list[dict]
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def label(self) -> str:
        return round_label(self.round)

    @property
    def deep(self) -> bool:
        return self.round == DEEP_ROUND


def load_rounds(series_rows: list[dict], items: dict[str, Item]) -> list[RoundData]:
    """db.series_sessions 결과 → 끝낸 차수들 (차수 순)."""
    out = []
    for r in series_rows:
        prog = r.get("progress")
        if not r.get("completed_at") or not prog:
            continue
        rows = [x for d in prog["domains"] for x in ex.domain_rows(prog, items, Domain(d))]
        out.append(RoundData(r["round"], r["form_seed"], prog, rows, r.get("started_at"), r.get("completed_at")))
    return sorted(out, key=lambda x: x.round)


@dataclass
class DomainResult:
    domain: Domain
    score: Score
    correct: int
    n: int
    raw: float
    avg_sec: float | None

    @property
    def label(self) -> str:
        return BLUEPRINT[self.domain].label


@dataclass
class RoundReport:
    total: Score
    domains: list[DomainResult]
    by_level: dict[int, tuple[int, int]] = field(default_factory=dict)  # 난이도 → (맞힌 수, 문항 수)
    correct: int = 0
    n: int = 0
    minutes: float | None = None
    quick_wrong: int = 0      # 3초 안에 낸 오답 (찍기 의심)
    blurs: int = 0


def report(rows: list[dict], items: dict[str, Item], norm: sc.Norm, rd: RoundData | None = None,
           stage: str | None = None) -> RoundReport:
    per, total = sc.estimate(rows, items)
    domains = []
    for d in sc.DOMAIN_ORDER:
        if d not in per:
            continue
        drows = [r for r in rows if r["domain"] == d.value]
        secs = [r["response_ms"] / 1000 for r in drows if r.get("response_ms")]
        domains.append(DomainResult(
            d, scale(per[d].theta, per[d].se, norm, d, stage),
            correct=sum(1 for r in drows if r["correct"]), n=len(drows), raw=per[d].raw,
            avg_sec=float(np.mean(secs)) if secs else None))
    by_level: dict[int, list[int]] = {}
    scored = rows
    for r in scored:
        lv = items[r["item_id"]].difficulty
        by_level.setdefault(lv, [0, 0])
        by_level[lv][0] += int(bool(r["correct"]))
        by_level[lv][1] += 1
    quick_wrong = sum(1 for r in rows if not r["correct"] and r.get("answer") and (r.get("response_ms") or 1e9) < GUESS_SEC * 1000)
    minutes = None
    if rd and rd.started_at and rd.completed_at:
        minutes = (rd.completed_at - rd.started_at).total_seconds() / 60
    return RoundReport(
        total=scale(total.theta, total.se, norm, stage=stage), domains=domains,
        by_level={k: (v[0], v[1]) for k, v in sorted(by_level.items())},
        correct=sum(1 for r in scored if r["correct"]), n=len(scored), minutes=minutes,
        quick_wrong=quick_wrong, blurs=(rd.progress.get("blurs", 0) if rd else 0))


def level_comment(by_level: dict[int, tuple[int, int]]) -> str:
    """난이도별 정답률에서 '어디서부터 막히는지'를 한 문장으로."""
    rates = {lv: c / n for lv, (c, n) in by_level.items() if n}
    if not rates:
        return ""
    parts = " · ".join(f"{DIFFICULTY_LABELS[lv]} {rates[lv]:.0%}" for lv in sorted(rates))
    drop = next((lv for lv in sorted(rates) if rates[lv] < 0.5), None)
    if drop is None:
        tail = "가장 어려운 단계까지 절반 이상 맞혔습니다."
    elif drop == min(rates):
        tail = "가장 쉬운 단계부터 정답률이 절반에 못 미칩니다."
    else:
        tail = f"'{DIFFICULTY_LABELS[drop]}' 단계부터 정답률이 절반 아래로 떨어집니다."
    return f"{parts} — {tail}"


def cumulative(rounds: list[RoundData], items: dict[str, Item], norm: sc.Norm) -> list[tuple[str, Score]]:
    """1차 → 1~2차 → … 처럼 차수를 하나씩 더할 때마다의 점수와 범위."""
    out, acc, n = [], [], 0
    for rd in rounds:
        acc += rd.rows
        n += not rd.deep
        _, total = sc.estimate(acc, items)
        label = rd.label if len(out) == 0 else f"+ {rd.label}"
        out.append((label, scale(total.theta, total.se, norm, stage=stage(n, rd.deep))))
    return out


def deep_trace(prior_rows: list[dict], deep_rows: list[dict], items: dict[str, Item], norm: sc.Norm) -> list[dict]:
    """심층검사에서 문항을 하나 풀 때마다 영역 점수가 어떻게 좁혀졌는지."""
    out = []
    for d in sc.DOMAIN_ORDER:
        drows = [r for r in deep_rows if r["domain"] == d.value]
        if not drows:
            continue
        prior = [r for r in prior_rows if r["domain"] == d.value]
        for k in range(len(drows) + 1):
            use = prior + drows[:k]
            like = sc._likelihood([items[r["item_id"]] for r in use], [sc.row_score(r) for r in use])
            theta, se = sc.eap(like)
            s = scale(theta, se, norm, d, "1-3+deep" if k else "1-3")
            row = {"영역": BLUEPRINT[d].label, "단계": k, "지수": s.index, "하한": s.lo, "상한": s.hi}
            if k:
                it = items[drows[k - 1]["item_id"]]
                row |= {"난이도": DIFFICULTY_LABELS[it.difficulty], "결과": "정답" if drows[k - 1]["correct"] else "오답"}
            else:
                row |= {"난이도": "1~3차", "결과": "출발"}
            out.append(row)
    return out


def consistency(indices: list[float], margin: float) -> str:
    """차수별 점수가 얼마나 일관된지 한 문장으로."""
    if len(indices) < 2:
        return ""
    spread = max(indices) - min(indices)
    if spread <= margin:
        return (f"차수별 점수 차이가 최대 {spread:.0f}점으로 측정 오차(±{margin:.0f}점) 안에 있어 "
                "결과가 안정적입니다.")
    return (f"차수별 점수 차이가 최대 {spread:.0f}점으로 측정 오차(±{margin:.0f}점)보다 큽니다. "
            "컨디션, 집중도, 문제 유형에 대한 익숙함이 영향을 줬을 수 있습니다.")


LEVEL_GUIDE = [  # (하한, 상한, 수준, 인구 비율, 뜻) — MSCEIT·EQ-i 해석 구간 참고
    (130, 160, "매우 우수", "상위 약 2%", "감정의 미묘한 차이까지 읽고 다루는 매우 발달된 정서 역량"),
    (115, 129, "우수", "상위 약 2~16%", "감정을 유연하게 읽고 다루는 뛰어난 정서 역량"),
    (90, 114, "보통", "가운데 약 60%", "일상생활과 대인관계에 충분한 정서 역량"),
    (70, 89, "개발 필요", "하위 약 2~25%", "감정을 읽거나 다루는 데 실수가 생길 수 있어 연습하면 좋아지는 수준"),
    (40, 69, "집중 개선 필요", "하위 약 2%", "감정 정보를 다루는 데 어려움을 자주 겪을 수 있어 꾸준한 연습과 도움이 권장되는 수준"),
]


# ---------------------------------------------------------------- 자기평가 비교

# 자기평가 평균(1~5)의 가정 분포. 자기평가는 대체로 좋게 답하는 경향이 있어 중앙값을 3보다 높게 둔다.
# 응답이 쌓이면 관리자 페이지의 실제 평균·표준편차로 바꾼다 (SELF_NORM을 덮어쓰기).
SELF_NORM = {"mean": 3.6, "sd": 0.55}
GAP_POINTS = 15  # 자기평가와 실제 수행이 이만큼(1 표준편차) 넘게 차이 나면 과대·과소평가로 표시


def self_index(mean: float, norm: dict | None = None) -> float:
    n = norm or SELF_NORM
    return sc.to_index((mean - n["mean"]) / n["sd"])


@dataclass
class SelfGap:
    domain: Domain | None   # None = 종합
    self_index: float
    ability_index: float

    @property
    def gap(self) -> float:
        return self.self_index - self.ability_index

    @property
    def verdict(self) -> str:
        if self.gap >= GAP_POINTS:
            return "과대평가"
        if self.gap <= -GAP_POINTS:
            return "과소평가"
        return "비슷함"

    @property
    def label(self) -> str:
        return "종합" if self.domain is None else BLUEPRINT[self.domain].label


def self_comparison(self_scores: dict, final: "RoundReport", norm: dict | None = None) -> list[SelfGap]:
    """자기평가(영역 평균 1~5) vs 실제 수행(EQ). 첫 줄은 종합."""
    means = {Domain(k): v for k, v in self_scores.items() if not k.startswith("_")}
    if not means:
        return []
    by = {d.domain: d.score.index for d in final.domains}
    out = [SelfGap(None, self_index(sum(means.values()) / len(means), norm), final.total.index)]
    out += [SelfGap(d, self_index(m, norm), by[d]) for d, m in means.items() if d in by]
    return out


def self_summary(gaps: list[SelfGap], inflated: bool) -> str:
    """자기평가 비교를 한두 문장으로."""
    if not gaps:
        return ""
    total = gaps[0]
    over = [g.label for g in gaps[1:] if g.verdict == "과대평가"]
    under = [g.label for g in gaps[1:] if g.verdict == "과소평가"]
    head = {"과대평가": "스스로 생각하는 것보다 실제 문제 풀이 결과가 낮게 나왔습니다.",
            "과소평가": "스스로 생각하는 것보다 실제 문제 풀이 결과가 높게 나왔습니다. 자신의 감정 역량을 낮춰 보는 편입니다.",
            "비슷함": "스스로 생각하는 정서 역량과 실제 문제 풀이 결과가 비슷합니다. 자신을 꽤 정확하게 알고 있습니다."}[total.verdict]
    parts = [head]
    if over:
        parts.append(f"특히 {', '.join(over)}은(는) 스스로 높게 보지만 문제 풀이에서는 낮게 나왔습니다.")
    if under:
        parts.append(f"{', '.join(under)}은(는) 생각보다 실제로 더 잘하는 영역입니다.")
    if inflated:
        parts.append("다만 '한 번도 화를 낸 적이 없다' 같은 문항에 그렇다고 답해, 자기평가가 실제보다 좋게 기울었을 수 있습니다.")
    return " ".join(parts)
