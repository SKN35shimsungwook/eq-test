"""선택 유형 분석: 무엇을 골랐는지로 영역별 유형과 종합 프로필을 만든다 (정답 여부와 별개).

- 보기마다 붙은 유형 코드(schema.STYLES)를 모은다. 최선·최악 문항은 '최선'으로 고른 보기를 쓴다.
- 행동 영역(활용·조절·대인관계·관계 갈등·위기 대처): 가장 많이 고른 유형이 그 영역의 유형.
  한 유형이 40% 미만이면 '유연형'(상황에 따라 방법을 바꿈).
- 해석 영역(인식·이해·맥락): 정확히 읽은 비율이 75% 이상이면 '정확형', 아니면 잘못 읽을 때의 경향.
- 종합: 행동 영역의 선택을 세 축(A 감정↔문제, B 다가감↔거리, C 표현↔절제)에 모아,
  뚜렷한 축 1~2개와 가장 많이 고른 방식을 엮어 이름을 만든다 (MBTI처럼 정해진 칸이 아니라 조합).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from core import exam as ex
from core.schema import BLUEPRINT, READING_DOMAINS, STYLES, Domain, Item, ItemFormat

FLEX_SHARE = 0.40      # 이보다 낮으면 그 영역은 유연형
ACCURATE_SHARE = 0.75  # 해석 영역: 이 이상 정확하면 정확형
AXIS_STRONG = 0.15     # 축 평균이 이 이상이면 이름에 반영
MIN_PICKS = 3          # 영역 유형을 말하려면 필요한 최소 선택 수

AXES = [
    ("A", "마음을 먼저 살피는", "해결을 먼저 찾는", "감정 중심", "문제 중심"),
    ("B", "먼저 다가가는", "한 걸음 물러서 보는", "다가감", "거리 둠"),
    ("C", "솔직하게 드러내는", "차분하게 다스리는", "표현", "절제"),
]
AXIS_ADVICE = {
    ("A", 1): "감정을 먼저 알아주는 힘이 큽니다. 문제가 급할 때는 해결책을 함께 건네면 더 든든한 사람이 됩니다.",
    ("A", -1): "문제를 빨리 푸는 힘이 큽니다. 상대가 해결보다 공감을 원할 때를 알아차리면 관계가 더 깊어집니다.",
    ("B", 1): "먼저 다가가 관계를 잇는 힘이 큽니다. 상대가 혼자 있고 싶다는 신호를 보낼 때는 기다려 주는 것도 다가감입니다.",
    ("B", -1): "한발 물러서 상황을 보는 신중함이 있습니다. 오해가 쌓이기 전에 먼저 말을 거는 연습을 해 보세요.",
    ("C", 1): "마음을 솔직하게 드러내는 힘이 큽니다. 감정이 아주 강할 때는 잠시 가라앉힌 뒤 말하면 더 잘 전해집니다.",
    ("C", -1): "감정을 차분하게 다스리는 힘이 큽니다. 다스리기만 하지 말고 믿는 사람에게 털어놓는 통로도 열어 두세요.",
}
READING_LABELS = {  # 해석 영역의 잘못 읽는 경향 (영역마다 코드는 달라도 뜻이 같은 것끼리)
    "pos": "밝게 읽는", "neg": "무겁게 읽는", "over": "무겁게 읽는", "lit": "겉으로 읽는", "under": "가볍게 읽는",
    "shift": "원인을 달리 보는", "sus": "숨은 뜻을 더 읽는",
}


@dataclass
class DomainStyle:
    domain: Domain
    n: int
    shares: dict[str, float]      # 유형 코드 → 비율
    code: str | None              # 대표 유형 (None = 유연형 또는 판단 보류)
    flexible: bool = False

    @property
    def label(self) -> str:
        return BLUEPRINT[self.domain].label

    @property
    def name(self) -> str:
        if self.n < MIN_PICKS:
            return "판단 보류"
        if self.code is None:
            return "유연형"
        return STYLES[self.domain][self.code].name

    @property
    def desc(self) -> str:
        if self.n < MIN_PICKS:
            return f"이 영역 선택이 {self.n}개뿐이라 유형을 정하기 어렵습니다."
        if self.code is None:
            return "상황에 따라 방법을 바꿔 고르는 편입니다. 특정 방식에 치우치지 않는 것도 정서 역량입니다."
        return STYLES[self.domain][self.code].desc


@dataclass
class Profile:
    domains: list[DomainStyle]
    axes: dict[str, float]        # "A"/"B"/"C" → −1~1
    name: str
    reading: str                  # 해석 경향 한 줄
    advice: list[str] = field(default_factory=list)
    n_action: int = 0


def picks(rows: list[dict], items: dict[str, Item]) -> list[tuple[Domain, str]]:
    """응답 행 → (영역, 고른 보기의 유형 코드). 유형이 없는 문항·미응답은 뺀다."""
    out = []
    for r in rows:
        it = items.get(r["item_id"])
        if it is None or not it.styles or not r.get("answer"):
            continue
        best = r["answer"].partition(",")[0] if it.format is ItemFormat.BEST_WORST else r["answer"]
        if best == "":
            continue
        out.append((it.domain, it.styles[int(best)]))
    return out


def domain_style(domain: Domain, codes: list[str]) -> DomainStyle:
    n = len(codes)
    cnt = Counter(codes)
    shares = {c: cnt[c] / n for c in STYLES[domain]} if n else {c: 0.0 for c in STYLES[domain]}
    if n < MIN_PICKS:
        return DomainStyle(domain, n, shares, None)
    if domain in READING_DOMAINS:
        if shares.get("acc", 0) >= ACCURATE_SHARE:
            return DomainStyle(domain, n, shares, "acc")
        miss = Counter(c for c in codes if c != "acc")
        return DomainStyle(domain, n, shares, miss.most_common(1)[0][0])
    top, share = max(shares.items(), key=lambda kv: kv[1])
    if share < FLEX_SHARE:
        return DomainStyle(domain, n, shares, None, flexible=True)
    return DomainStyle(domain, n, shares, top)


def profile(rows: list[dict], items: dict[str, Item]) -> Profile:
    chosen = picks(rows, items)
    by_domain: dict[Domain, list[str]] = {d: [] for d in BLUEPRINT}
    for d, c in chosen:
        by_domain[d].append(c)
    domains = [domain_style(d, by_domain[d]) for d in BLUEPRINT if by_domain[d]]

    # 세 축: 행동 영역 선택의 평균
    action = [(d, c) for d, c in chosen if d not in READING_DOMAINS]
    axes = {k: 0.0 for k, *_ in AXES}
    for d, c in action:
        for (k, *_), v in zip(AXES, STYLES[d][c].axes):
            axes[k] += v
    if action:
        axes = {k: v / len(action) for k, v in axes.items()}

    # 이름: 뚜렷한 축(최대 2개) + 가장 많이 고른 방식
    strong = sorted([(k, v) for k, v in axes.items() if abs(v) >= AXIS_STRONG], key=lambda kv: -abs(kv[1]))[:2]
    adjs = [next(pos if v > 0 else neg for kk, pos, neg, *_ in AXES if kk == k) for k, v in strong]
    top_counts = Counter(STYLES[d][c].name for d, c in action)
    if action and top_counts.most_common(1)[0][1] / len(action) >= 0.25:
        noun = top_counts.most_common(1)[0][0]
    else:
        noun = "유연형"
    if not action:
        name = "판단 보류"
    elif adjs:
        name = f"{' · '.join(adjs)} {noun}"
    else:
        name = f"균형 잡힌 {noun}"

    # 해석 경향
    reading_codes = [c for d, c in chosen if d in READING_DOMAINS]
    if not reading_codes:
        reading = ""
    elif sum(c == "acc" for c in reading_codes) / len(reading_codes) >= ACCURATE_SHARE:
        reading = "감정과 말의 숨은 뜻을 대체로 정확하게 읽습니다."
    else:
        miss = Counter(READING_LABELS[c] for c in reading_codes if c != "acc")
        reading = f"잘못 읽을 때는 주로 '{miss.most_common(1)[0][0]}' 쪽으로 기웁니다."

    advice = [AXIS_ADVICE[(k, 1 if v > 0 else -1)] for k, v in strong]
    return Profile(domains, axes, name, reading, advice, len(action))
