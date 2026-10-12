"""응답 신뢰도 검증: python scripts/simulate_validity.py [--n 4000] [--workers 8]

응답 방식을 미리 정한 봇들이 1차 검증(시작 자기평가 → 문제 풀이 → 마지막 질문)을 실제 출제 로직으로 풀고,
core.validity가 성실한 봇을 잘못 거르지 않는지, 불성실·꾸밈 봇을 잡아내는지 잰다.

봇 종류 (같은 수):
- 성실: 영역 성향 + 잡음으로 자기평가, 욕구 문항은 사람마다 다른 낮은 확률(평균 13%)로 부정, 문항당 중앙값 약 9초
- 성실·빠른 독자: 성실과 같지만 문항당 중앙값 약 4.5초 (거짓 경보가 가장 나기 쉬운 사람)
- 은근한 꾸밈: 자기평가 +0.5, 욕구 부정 확률 평균 38%
- 강한 꾸밈: 자기평가 +1.0, 욕구 부정 확률 평균 67%
- 무작위: 자기평가·문제 모두 아무렇게나, 문항당 중앙값 약 1.5초
- 대충: 자기평가 85%를 한 칸에, 문제 85%를 한 위치에, 문항당 중앙값 약 1.2초
- 절반 대충: 자기평가는 성실, 문제는 앞 절반 성실·뒤 절반 대충, 마지막 질문은 한 칸에

한계: 사람의 실제 응답 분포가 아니라 가정한 모형이다. 실제 응답이 쌓이면 관리자 페이지의 신뢰도 분포로 다시 확인한다.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import exam as ex  # noqa: E402
from core import scoring as sc  # noqa: E402
from core import validity as vd  # noqa: E402
from core.item_bank import build_form, load_final_items, load_items, load_self_items  # noqa: E402
from core.schema import ItemFormat, Mode  # noqa: E402

KINDS = ["성실", "성실·빠른 독자", "은근한 꾸밈", "강한 꾸밈", "무작위", "대충", "절반 대충"]
HONEST = {"성실", "성실·빠른 독자"}

_ITEMS = _BY_ID = _SELF = _FINAL = None


def _init():
    global _ITEMS, _BY_ID, _SELF, _FINAL
    _ITEMS = load_items()
    _BY_ID = {it.id: it for it in _ITEMS}
    _SELF = load_self_items()
    _FINAL = load_final_items()


def _p(item, theta: float) -> float:
    a, b, c = sc.item_params(item)
    return c + (1 - c) / (1 + math.exp(-sc.D * a * (theta - b)))


def clip5(x: float) -> int:
    return int(min(5, max(1, round(x))))


class Bot:
    def __init__(self, kind: str, rng: random.Random):
        self.kind, self.rng = kind, rng
        self.theta = rng.gauss(0, 1)
        g = rng.gauss(0, 1)
        lift = {"은근한 꾸밈": 0.5, "강한 꾸밈": 1.0}.get(kind, 0.0)
        self.trait = {d: min(4.9, 3.6 + 0.4 * g + 0.35 * rng.gauss(0, 1) + lift) for d in
                      {it.domain for it in _SELF if it.domain}}
        self.acq = rng.gauss(0, 0.3) if kind in HONEST else 0.0   # '그렇다' 쪽으로 답하는 습관
        self.deny_q = {"은근한 꾸밈": rng.betavariate(3, 5), "강한 꾸밈": rng.betavariate(6, 3)}.get(
            kind, rng.betavariate(1.2, 8))
        self.speed = {"성실·빠른 독자": rng.lognormvariate(math.log(4500), 0.25), "무작위": 1500, "대충": 1200}.get(
            kind, rng.lognormvariate(math.log(9000), 0.35))
        self.fav_value = rng.choice([3, 4, 5])
        self.fav_pos = rng.randrange(4)

    # ---------------------------------------------------------- 자기평가·마지막 질문
    def likert(self, it, sloppy: bool) -> int:
        rng = self.rng
        if self.kind == "무작위":
            return rng.randint(1, 5)
        if sloppy:
            return self.fav_value if rng.random() < 0.85 else rng.randint(1, 5)
        if it.check or it.kind == "desire":
            if rng.random() < self.deny_q:
                return 5 if rng.random() < 0.3 else 4
            return rng.choices([1, 2, 3], weights=[0.4, 0.4, 0.2])[0]
        domain = it.domain or next(s.domain for s in _SELF if s.id == it.pair)
        t = self.trait[domain]
        return clip5((6 - t if it.reverse else t) + self.acq + rng.gauss(0, 0.8))

    # ---------------------------------------------------------- 문제 풀이
    def answer(self, it, sloppy: bool) -> dict:
        rng = self.rng
        bw = it.format is ItemFormat.BEST_WORST
        key = it.answer[0] if bw else it.answer
        if self.kind == "무작위":
            best = rng.randrange(4)
        elif sloppy:
            best = self.fav_pos if rng.random() < 0.85 else rng.randrange(4)
        else:
            p_best = float(sc._p3(*sc.bw_steps(it)[0], self.theta)) if bw else _p(it, self.theta)
            best = key if rng.random() < p_best else rng.choice([i for i in range(4) if i != key])
        if bw:
            worst = rng.choice([i for i in range(4) if i != best])
            ans = f"{best},{worst}"
        else:
            ans = str(best)
        speed = 1200 if sloppy and self.kind == "절반 대충" else self.speed
        ms = max(500, int(speed * rng.lognormvariate(0, 0.5) * (1.4 if bw else 1.0)))
        if ex.item_timed(it.domain):
            ms = min(ms, it.time_limit * 1000 if getattr(it, "time_limit", None) else ms)
        return {"item_id": it.id, "domain": it.domain.value, "answer": ans, "response_ms": ms}


def run(args: tuple[int, str, int]) -> list[dict]:
    seed, mode_value, n = args
    if _ITEMS is None:
        _init()
    mode = Mode(mode_value)
    rng = random.Random(seed)
    out = []
    for k in range(n):
        kind = KINDS[k % len(KINDS)]
        bot = Bot(kind, rng)
        sloppy_self = kind == "대충"
        self_ans = {it.id: bot.likert(it, sloppy_self) for it in _SELF}
        form = build_form(_ITEMS, rng.randrange(2**31), mode)
        flat = [it for items in form.values() for it in items]
        rows = [bot.answer(it, kind == "대충" or (kind == "절반 대충" and i >= len(flat) // 2))
                for i, it in enumerate(flat)]
        final_ans = {it.id: bot.likert(it, kind in ("대충", "절반 대충")) for it in _FINAL}
        scores = {**ex.self_scores(_SELF, self_ans), **vd.final_scores(_FINAL, _SELF, final_ans, self_ans)}
        v = vd.assess(scores, rows, _BY_ID)
        v2 = vd.assess(dict(scores), list(reversed(rows)), _BY_ID)
        out.append({"kind": kind, "theta": bot.theta, "level": v.level, "reasons": v.reasons,
                    "deterministic": (v.level, v.reasons) == (v2.level, v2.reasons),
                    "deny": v.metrics["deny"], "incons": scores["_incons"], "same": scores["_self_same"],
                    "fast": v.metrics["fast"], "pos": v.metrics["position"]})
    return out


SIGNALS = [("욕구 부정", "부정하는"), ("좋게 보이려는 답 조금", "좋게 보이려는"), ("다시 물었을 때 어긋남", "다시 물었을"),
           ("자기평가 한 칸", "한 칸에"), ("너무 빠름", "읽기 어려울"), ("빠름 조금", "아주 빨리"),
           ("한 위치 몰아", "몰아서"), ("한 위치 조금", "고른 경우가 많습니다")]


def pct(x: float) -> str:
    return f"{100 * x:5.1f}%"


def report(bots: list[dict], mode: str) -> None:
    print(f"\n================ [{mode}] 봇 {len(bots):,}명 (종류마다 {len(bots) // len(KINDS):,}명) ================")
    print(f"같은 응답 → 같은 판정 (문제 풀이 응답 순서를 뒤집어도): {pct(np.mean([b['deterministic'] for b in bots]))}")
    print("\n1. 판정 분포                높음     보통     낮음")
    for kind in KINDS:
        bs = [b for b in bots if b["kind"] == kind]
        c = Counter(b["level"] for b in bs)
        print(f"   {kind:<12} " + " ".join(pct(c[lv] / len(bs)) for lv in vd.LEVELS))
    print("\n2. 성실 봇, 능력 구간별 (능력과 무관해야 함)")
    hs = [b for b in bots if b["kind"] in HONEST]
    cuts = np.quantile([b["theta"] for b in hs], [1 / 3, 2 / 3])
    for g, lo, hi in (("하", -9, cuts[0]), ("중", cuts[0], cuts[1]), ("상", cuts[1], 9)):
        gb = [b for b in hs if lo <= b["theta"] < hi]
        c = Counter(b["level"] for b in gb)
        print(f"   {g}: " + " · ".join(f"{lv} {pct(c[lv] / len(gb))}" for lv in vd.LEVELS))
    print("\n3. 신호별로 걸린 비율")
    print("   " + " " * 12 + "".join(f"{name:>14}" for name, _ in SIGNALS))
    for kind in KINDS:
        bs = [b for b in bots if b["kind"] == kind]
        cells = [np.mean([any(key in r for r in b["reasons"]) for b in bs]) for _, key in SIGNALS]
        print(f"   {kind:<12}" + "".join(f"{100 * x:13.1f}%" for x in cells))
    print("\n4. 지표 평균 (성실 / 강한 꾸밈 / 무작위 / 대충)")
    for key, label in (("deny", "욕구 부정 수(0~8)"), ("incons", "어긋난 짝(0~4)"), ("same", "자기평가 한 칸 비율"),
                       ("fast", "2.5초 안 응답 비율"), ("pos", "한 위치 비율")):
        vals = [np.mean([b[key] for b in bots if b["kind"] == k]) for k in ("성실", "강한 꾸밈", "무작위", "대충")]
        print(f"   {label:<16} " + " / ".join(f"{v:.2f}" for v in vals))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=7000, help="모드별 봇 수 (7종류로 나눔)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    for mode in Mode:
        t0 = time.time()
        chunk = max(len(KINDS), (args.n // (args.workers * 4)) // len(KINDS) * len(KINDS))
        jobs = [(31 * (i + 1) + (3 if mode is Mode.FULL else 0), mode.value, min(chunk, args.n - i * chunk))
                for i in range(math.ceil(args.n / chunk))]
        bots = []
        with ProcessPoolExecutor(max_workers=args.workers, initializer=_init) as pool:
            for part in pool.map(run, jobs):
                bots += part
        report(bots, mode.value)
        print(f"   ({time.time() - t0:.0f}초)")


if __name__ == "__main__":
    main()
