"""선택 유형 분석: 단서를 놓쳤을 때 어느 쪽으로 기우는지로 영역별 유형과 종합 프로필을 만든다 (점수와 별개).

왜 '놓쳤을 때'만 보나: 정답 보기의 유형은 영역마다 고르지 않다 (예: 관계 갈등은 대화형이 정답인 문항이 많다).
고른 보기를 그냥 세면 정답을 많이 맞힌 사람이 '정답에 많은 유형'으로 나와, 유형이 능력을 따라간다.
그래서 정답을 고른 문항은 '상황에 맞춤'으로만 세고, 정답이 아닌 보기를 고른 문항에서
"그 문항이 내놓은 오답 보기들 가운데 무엇을 골랐나"를 우연 기대치와 비교한다.

- 기대치: 오답 보기 3개 중 하나를 고르게 고르면 각 유형이 뽑힐 기대 횟수 (한 문항에 같은 유형 보기가 둘이면 2/3).
- 영역 유형: 정답 비율 75% 이상 → 상황맞춤형(해석 영역은 정확형). 아니면 우연 기대보다 뚜렷하게(z ≥ 2.3,
  1.5배 이상, 3번 이상) 많이 고른 유형이 기우는 방향. 없으면 유연형. 응답이 3개 미만이면 판단 보류.
- 세 축(A 감정↔문제, B 다가감↔거리, C 표현↔절제): 행동 영역에서 놓친 문항마다
  (고른 보기의 축 − 그 문항 오답 보기들의 평균 축)을 더해 (놓친 수 + 4)로 나눈다. 버릇이 없으면 0 근처.
  뚜렷한 축 = 그 기울기가 우연이 아닐 때(z ≥ 2.3)이고 점수 절댓값 0.15 이상.
- 이름: 뚜렷한 축 중 가장 강한 축의 명사 + 둘째 축의 꾸밈말.
  뚜렷한 축이 없으면 행동 영역 정답 비율에 따라 상황맞춤형 / 균형형.
검증: scripts/simulate_styles.py (참 성향을 심은 봇으로 회복률·재검사 일치·능력과의 얽힘을 잰다).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from core.schema import BLUEPRINT, READING_DOMAINS, STYLES, Domain, Item, ItemFormat

MATCH_SHARE = 0.75   # 이 이상 정답이면 상황맞춤형 / 정확형
LEAN_Z = 2.3         # 기우는 방향: 우연 기대보다 이 표준오차 배 이상 많이 골라야 (우연이면 약 1%)
LEAN_LIFT = 1.5      #   + 기대의 1.5배 이상
LEAN_MIN = 3         #   + 최소 3번
AXIS_PRIOR = 4       # 축 점수(그래프) 축소: 놓친 문항이 적으면 0 쪽으로
AXIS_Z = 2.3         # 뚜렷한 축: 놓친 문항들의 기울기가 우연이 아닐 것 (우연이면 축마다 약 2%)
AXIS_STRONG = 0.15   #   + 축 점수 절댓값 이 이상
MIN_PICKS = 3        # 영역 유형을 말하려면 필요한 최소 응답 수

AXES = [
    ("A", "마음을 먼저 살피는", "해결을 먼저 찾는", "감정 중심", "문제 중심"),
    ("B", "먼저 다가가는", "한 걸음 물러서 보는", "다가감", "거리 둠"),
    ("C", "솔직하게 드러내는", "차분하게 다스리는", "표현", "절제"),
]
AXIS_NOUNS = {("A", 1): "마음 중심형", ("A", -1): "해결 중심형", ("B", 1): "관계 지향형", ("B", -1): "독립형",
              ("C", 1): "표현형", ("C", -1): "절제형"}
AXIS_ADVICE = {
    ("A", 1): "판단이 애매할 때 감정을 먼저 챙기는 편입니다. 상황이 해결책을 요구할 때를 알아차리면 더 든든한 사람이 됩니다.",
    ("A", -1): "판단이 애매할 때 해결부터 찾는 편입니다. 상대가 해결보다 공감을 원할 때를 알아차리면 관계가 더 깊어집니다.",
    ("B", 1): "판단이 애매할 때 먼저 다가가는 편입니다. 상대가 혼자 있고 싶다는 신호를 보낼 때는 기다려 주는 것도 다가감입니다.",
    ("B", -1): "판단이 애매할 때 한발 물러서는 편입니다. 오해가 쌓이기 전에 먼저 말을 거는 연습을 해 보세요.",
    ("C", 1): "판단이 애매할 때 마음을 드러내는 편입니다. 감정이 아주 강할 때는 잠시 가라앉힌 뒤 말하면 더 잘 전해집니다.",
    ("C", -1): "판단이 애매할 때 감정을 누르는 편입니다. 다스리기만 하지 말고 믿는 사람에게 털어놓는 통로도 열어 두세요.",
}
READING_LABELS = {  # 해석 영역의 잘못 읽는 경향 (영역마다 코드는 달라도 뜻이 같은 것끼리)
    "pos": "밝게 읽는", "neg": "무겁게 읽는", "over": "무겁게 읽는", "lit": "겉으로 읽는", "under": "가볍게 읽는",
    "shift": "원인을 달리 보는", "sus": "숨은 뜻을 더 읽는",
}


@dataclass
class DomainStyle:
    domain: Domain
    n: int                        # 유형이 있는 응답 수
    n_miss: int                   # 정답이 아닌 보기를 고른 수
    lift: dict[str, float]        # 유형 → 기대 대비 배율 (놓친 문항 기준)
    code: str | None              # 기우는 방향 (None = 상황맞춤·유연·보류)
    matched: bool = False         # 정답 비율이 높아 상황맞춤형 / 정확형
    flexible: bool = False        # 놓쳐도 특정 방향으로 기울지 않음

    @property
    def label(self) -> str:
        return BLUEPRINT[self.domain].label

    @property
    def reading(self) -> bool:
        return self.domain in READING_DOMAINS

    @property
    def name(self) -> str:
        if self.n < MIN_PICKS:
            return "판단 보류"
        if self.matched:
            return "정확형" if self.reading else "상황맞춤형"
        if self.code is None:
            return "유연형"
        return STYLES[self.domain][self.code].name

    @property
    def desc(self) -> str:
        if self.n < MIN_PICKS:
            return f"이 영역 응답이 {self.n}개뿐이라 유형을 정하기 어렵습니다."
        if self.matched:
            return STYLES[self.domain]["acc"].desc if self.reading else "상황이 요구하는 방법을 대부분 정확히 골랐습니다."
        if self.code is None:
            return "단서를 놓친 문제에서도 특정 방식에 치우치지 않았습니다."
        return f"단서를 놓쳤을 때 이쪽으로 기웁니다: {STYLES[self.domain][self.code].desc}."


@dataclass
class Profile:
    domains: list[DomainStyle]
    axes: dict[str, float]        # "A"/"B"/"C" → −1~1
    name: str
    reading: str                  # 해석 경향 한 줄
    advice: list[str] = field(default_factory=list)
    n_action: int = 0             # 행동 영역 응답 수
    n_action_miss: int = 0
    axes_z: dict[str, float] = field(default_factory=dict)  # 축마다 우연 대비 z (|z| ≥ AXIS_Z면 뚜렷)


@dataclass
class Pick:
    domain: Domain
    item: Item
    chosen: int
    key: int

    @property
    def miss(self) -> bool:
        return self.chosen != self.key

    @property
    def distractors(self) -> list[str]:
        return [s for i, s in enumerate(self.item.styles) if i != self.key]


def picks(rows: list[dict], items: dict[str, Item]) -> list[Pick]:
    """응답 행 → 고른 보기 (최선·최악 문항은 '최선'). 유형이 없는 문항·미응답은 뺀다. 순서는 문항 ID 순."""
    out = []
    for r in rows:
        it = items.get(r["item_id"])
        if it is None or not it.styles or not r.get("answer"):
            continue
        bw = it.format is ItemFormat.BEST_WORST
        best = r["answer"].partition(",")[0] if bw else r["answer"]
        if best == "":
            continue
        out.append(Pick(it.domain, it, int(best), it.answer[0] if bw else it.answer))
    return sorted(out, key=lambda p: p.item.id)


def _counts(ps: list[Pick]) -> tuple[Counter, Counter]:
    """놓친 문항에서 유형별 실제 고른 수와 우연 기대 수."""
    obs, exp = Counter(), Counter()
    for p in ps:
        if p.miss:
            obs[p.item.styles[p.chosen]] += 1
            for s in p.distractors:
                exp[s] += 1 / len(p.distractors)
    return obs, exp


def _lift(obs: Counter, exp: Counter) -> dict[str, float]:
    return {s: obs[s] / exp[s] for s in sorted(exp) if exp[s] > 0}


def _lean(obs: Counter, exp: Counter) -> str | None:
    """우연 기대보다 뚜렷하게 많이 고른 유형. 놓친 문항마다 오답 3개 중 하나 → 각 유형은 이항(p≈1/3)."""
    cands = []
    for s in sorted(exp):
        e = exp[s]
        if e <= 0 or obs[s] < LEAN_MIN or obs[s] / e < LEAN_LIFT:
            continue
        z = (obs[s] - e) / math.sqrt(e * (2 / 3))
        if z >= LEAN_Z:
            cands.append((z, obs[s], s))
    return max(cands)[2] if cands else None  # 동점이면 횟수 → 코드 순으로 정해 결과가 응답 순서와 무관


def domain_style(domain: Domain, ps: list[Pick]) -> DomainStyle:
    n, n_miss = len(ps), sum(p.miss for p in ps)
    obs, exp = _counts(ps)
    lift = _lift(obs, exp)
    if n < MIN_PICKS:
        return DomainStyle(domain, n, n_miss, lift, None)
    if (n - n_miss) / n >= MATCH_SHARE:
        return DomainStyle(domain, n, n_miss, lift, "acc" if domain in READING_DOMAINS else None, matched=True)
    code = _lean(obs, exp)
    return DomainStyle(domain, n, n_miss, lift, code, flexible=code is None)


def axis_scores(ps: list[Pick]) -> tuple[dict[str, float], dict[str, float]]:
    """행동 영역에서 놓친 문항마다 c = (고른 보기 축 − 오답 보기 평균 축).
    점수 = Σc / (놓친 수 + AXIS_PRIOR) (−1~1), z = Σc / √Σ(오답 보기 축의 분산) — 버릇이 없으면 z ~ N(0, 1)."""
    total, var = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    misses = [p for p in ps if p.miss and p.domain not in READING_DOMAINS]
    for p in misses:
        st = STYLES[p.domain]
        chosen = st[p.item.styles[p.chosen]].axes
        others = [st[s].axes for s in p.distractors]
        for j in range(3):
            m = sum(o[j] for o in others) / len(others)
            total[j] += chosen[j] - m
            var[j] += sum((o[j] - m) ** 2 for o in others) / len(others)
    keys = [k for k, *_ in AXES]
    score = {k: max(-1.0, min(1.0, total[j] / (len(misses) + AXIS_PRIOR))) for j, k in enumerate(keys)}
    z = {k: total[j] / math.sqrt(var[j]) if var[j] > 0 else 0.0 for j, k in enumerate(keys)}
    return score, z


def profile(rows: list[dict], items: dict[str, Item]) -> Profile:
    ps = picks(rows, items)
    by_domain: dict[Domain, list[Pick]] = {d: [] for d in BLUEPRINT}
    for p in ps:
        by_domain[p.domain].append(p)
    domains = [domain_style(d, by_domain[d]) for d in BLUEPRINT if by_domain[d]]

    action = [p for p in ps if p.domain not in READING_DOMAINS]
    n_miss = sum(p.miss for p in action)
    axes, z = axis_scores(action)

    # 이름: 가장 뚜렷한 축의 명사 + 둘째 축의 꾸밈말
    strong = sorted([(k, v) for k, v in axes.items() if abs(v) >= AXIS_STRONG and abs(z[k]) >= AXIS_Z],
                    key=lambda kv: (-abs(z[kv[0]]), kv[0]))[:2]
    sign = {k: 1 if v > 0 else -1 for k, v in strong}
    if not action:
        name = "판단 보류"
    elif not strong:
        name = "상황맞춤형" if (len(action) - n_miss) / len(action) >= MATCH_SHARE else "균형형"
    else:
        noun = AXIS_NOUNS[(strong[0][0], sign[strong[0][0]])]
        if len(strong) > 1:
            k = strong[1][0]
            adj = next(pos if sign[k] > 0 else neg for kk, pos, neg, *_ in AXES if kk == k)
            name = f"{adj} {noun}"
        else:
            name = noun

    # 해석 경향: 해석 영역 전체에서
    reading_ps = [p for p in ps if p.domain in READING_DOMAINS]
    if not reading_ps:
        reading = ""
    elif sum(not p.miss for p in reading_ps) / len(reading_ps) >= MATCH_SHARE:
        reading = "감정과 말의 숨은 뜻을 대체로 정확하게 읽습니다."
    else:
        obs, exp = _counts(reading_ps)
        # 영역마다 코드가 달라도 뜻이 같은 것끼리 합친다
        o2, e2 = Counter(), Counter()
        for s in exp:
            o2[READING_LABELS[s]] += obs[s]
            e2[READING_LABELS[s]] += exp[s]
        lean = _lean(o2, e2)
        reading = (f"잘못 읽을 때는 주로 '{lean}' 쪽으로 기웁니다." if lean
                   else "잘못 읽을 때 특정 방향으로 치우치지는 않습니다.")

    advice = [AXIS_ADVICE[(k, sign[k])] for k, _ in strong]
    return Profile(domains, axes, name, reading, advice, len(action), n_miss, z)
