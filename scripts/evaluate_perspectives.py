"""세 시점(실무자·연구자·이용자) 평가용 봇 시뮬레이션: python scripts/evaluate_perspectives.py [--n 3000] [--workers 8]

지금까지의 검증과 다른 점: 영역마다 능력이 다르다 (θ_영역 = √ρ·g + √(1−ρ)·e, ρ = 0.5).
그래서 영역 점수·강점이 실제 영역 차이를 잡는지 볼 수 있다. 읽기 속도·생각 시간도 사람마다 다르게 둔다.

봇 한 명이 1·2·3차(겹치지 않음)를 실제 출제 로직으로 푼다.
- 정답: 3PL(영역 θ). 놓치면 성향(연속 축 벡터)대로 기운다.
- 응답 시간: (문제+보기 글자 수) / 읽기 속도(중앙값 초당 8자) + 생각 시간(중앙값 4초, 어려울수록 길게).
  위기 대처는 문항 제한시간을 넘으면 미응답(오답).
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import exam as ex  # noqa: E402
from core import report as rp  # noqa: E402
from core import scoring as sc  # noqa: E402
from core import style as sty  # noqa: E402
from core.item_bank import build_form, load_items  # noqa: E402
from core.schema import BLUEPRINT, READING_DOMAINS, STYLES, Domain, ItemFormat, Mode  # noqa: E402

RHO = 0.5        # 영역 능력 사이 상관 (--rho)
SPEED = 8.0      # 읽기 속도 중앙값, 초당 글자 (--speed)
TWO_PHASE = True  # 위기 대처: 상황 읽기와 판단 시간 분리 (--old-crisis면 예전 방식)
DOMAINS = list(BLUEPRINT)
_ITEMS = _BY_ID = None
_NORMS: dict = {}


def _init():
    global _ITEMS, _BY_ID
    _ITEMS = load_items()
    _BY_ID = {it.id: it for it in _ITEMS}
    for m in Mode:
        _NORMS[m.value] = sc.build_norm([], sim=sc.load_sim(m.value))


def _p(item, theta: float) -> float:
    a, b, c = sc.item_params(item)
    return c + (1 - c) / (1 + math.exp(-sc.D * a * (theta - b)))


def _steps(item, theta: float) -> tuple[float, float]:
    """최선·최악: (최선 맞힐 확률, 최선을 맞혔을 때 최악도 맞힐 확률) — 채점과 같은 순차 모형."""
    s1, s2 = sc.bw_steps(item)
    return float(sc._p3(*s1, theta)), float(sc._p3(*s2, theta))


def chars(it) -> int:
    return len(it.prompt) + sum(len(c) for c in it.choices)


def respond(it, th: dict, v, bias, strength, speed, think, rng) -> dict:
    d = it.domain
    p = _p(it, th[d])
    bw = it.format is ItemFormat.BEST_WORST
    key = it.answer[0] if bw else it.answer
    thinking = think * rng.lognormvariate(0, 0.4) * (1 + 0.25 * (it.difficulty - 1))
    read_ms = 0
    if ex.item_timed(d) and TWO_PHASE:
        # 위기 대처: 상황은 시간 제한 없이 읽고, 보기를 연 뒤 (보기 읽기 + 판단)만 제한시간에 든다
        read_ms = int(1000 * len(it.prompt) / speed)
        ms = int(1000 * (sum(len(c) for c in it.choices) / speed + thinking))
    else:
        ms = int(1000 * (chars(it) / speed + thinking))
    if ex.item_timed(d) and ms > it.time_limit * 1000:
        return {"item_id": it.id, "domain": d.value, "answer": None, "correct": False, "score": 0.0,
                "response_ms": it.time_limit * 1000, "read_ms": read_ms, "timeout": True, "partial": False}
    p1, p2 = _steps(it, th[d]) if bw else (p, 0.0)
    if rng.random() < p1:
        best = key
    else:
        if not it.styles:
            w = [1.0] * 4
        elif d in READING_DOMAINS:
            w = [math.exp(strength if s == bias[d] else 0.0) for s in it.styles]
        else:
            w = [math.exp(strength * sum(a * b for a, b in zip(STYLES[d][s].axes, v))) for s in it.styles]
        others = [i for i in range(4) if i != key]  # 놓치면 오답 보기 중에서 (정답률은 3PL 그대로)
        best = rng.choices(others, weights=[w[i] for i in others])[0]
    partial = False
    if bw:
        wk = it.answer[1]
        if best == key and rng.random() < p2:
            worst = wk
        else:  # 최악을 놓치면 정답 최악이 아닌 보기 중에서 (정답률은 3PL 그대로)
            worst = rng.choice([i for i in range(4) if i not in (best, wk)])
        ok = best == key and worst == wk
        partial = best == key and not ok
        ans = f"{best},{worst}"
    else:
        ok, ans = best == key, str(best)
    score = 1.0 if ok else 0.5 if partial else 0.0
    return {"item_id": it.id, "domain": d.value, "answer": ans, "correct": ok, "score": score, "response_ms": ms,
            "read_ms": read_ms, "timeout": False, "partial": partial}


def run(args: tuple) -> list[dict]:
    seed, mode_value, n, rho, speed_med = args
    if _ITEMS is None:
        _init()
    mode = Mode(mode_value)
    norm = _NORMS[mode_value]
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        g = rng.gauss(0, 1)
        th = {d: math.sqrt(rho) * g + math.sqrt(1 - rho) * rng.gauss(0, 1) for d in DOMAINS}
        strength = rng.uniform(0, 2)
        v = [rng.gauss(0, 1) for _ in range(3)]
        bias = {d: rng.choice([c for c in STYLES[d] if c != "acc"]) for d in READING_DOMAINS}
        speed = rng.lognormvariate(math.log(speed_med), 0.3)     # 초당 글자
        think = rng.lognormvariate(math.log(4), 0.3)     # 초
        seen: set[str] = set()
        rounds, used = [], []
        for _r in range(3):
            form = build_form(_ITEMS, rng.randrange(2**31), mode, exclude=seen)
            rows = [respond(it, th, v, bias, strength, speed, think, rng) for items in form.values() for it in items]
            seen |= {r["item_id"] for r in rows}
            used.append([r["item_id"] for r in rows])
            rounds.append(rows)
        reps = [rp.report(r, _BY_ID, norm, stage="1") for r in rounds[:2]]
        rep13 = rp.report([x for r in rounds for x in r], _BY_ID, norm, stage="1-3")
        prof = [sty.profile(r, _BY_ID) for r in rounds[:2]]
        sw = sc.strengths_weaknesses({dd.domain: (dd.score.index, dd.score.margin / sc.CI_Z) for dd in reps[0].domains})
        r1 = rounds[0]
        out.append({
            "g": g, "th": {d.value: th[d] for d in DOMAINS}, "speed": speed, "strength": strength,
            "eq": [reps[0].total.index, reps[1].total.index, rep13.total.index],
            "lo_hi": [reps[0].total.lo, reps[0].total.hi],
            "boundary": sc.near_boundary(reps[0].total.index, reps[0].total.margin) is not None,
            "level": [sc.level(reps[0].total.index), sc.level(reps[1].total.index)],
            "dom1": {dd.domain.value: dd.score.index for dd in reps[0].domains},
            "dom2": {dd.domain.value: dd.score.index for dd in reps[1].domains},
            "dom13": {dd.domain.value: dd.score.index for dd in rep13.domains},
            "margin1": float(np.mean([dd.score.margin for dd in reps[0].domains])),
            "strong": [d.value for d, _ in sw[0]], "weak": [d.value for d, _ in sw[1]],
            "name": [p.name for p in prof], "axes": [[p.axes[k] for k in "ABC"] for p in prof],
            "minutes": sum(r["response_ms"] + r["read_ms"] for r in r1) / 60000,
            "timeouts": sum(r["timeout"] for r in r1), "n_cri": sum(r["domain"] == "cri" for r in r1),
            "timeouts_by_level": Counter(_BY_ID[r["item_id"]].difficulty for r in r1 if r["timeout"]),
            "bw": sum(_BY_ID[r["item_id"]].format is ItemFormat.BEST_WORST for r in r1),
            "partial": sum(r["partial"] for r in r1),
            "correct_share": float(np.mean([r["correct"] for r in r1])),
            "cri_eq": reps[0].domains and next(dd.score.index for dd in reps[0].domains if dd.domain is Domain.CRI),
            "used": used,
        })
    return out


def corr(a, b) -> float:
    return float(np.corrcoef(a, b)[0, 1])


def pctl(x, q) -> float:
    return float(np.percentile(x, q))


def extremes(mode: Mode) -> tuple[float, float]:
    """모두 맞힘 / 모두 틀림일 때의 EQ (1차)."""
    norm = sc.build_norm([], sim=sc.load_sim(mode.value))
    form = build_form(_ITEMS, 1, mode)
    its = [it for items in form.values() for it in items]
    hi = rp.report([{"item_id": it.id, "domain": it.domain.value, "answer": "x", "correct": True, "score": 1.0}
                    for it in its], _BY_ID, norm, stage="1").total.index
    lo = rp.report([{"item_id": it.id, "domain": it.domain.value, "answer": "x", "correct": False, "score": 0.0}
                    for it in its], _BY_ID, norm, stage="1").total.index
    return hi, lo


def report(bots: list[dict], mode: Mode, rho: float, speed: float) -> None:
    n = len(bots)
    dv = [d.value for d in DOMAINS]
    print(f"\n================ [{mode.value}] 봇 {n:,}명 (영역 능력 상관 ρ = {rho}, 읽기 속도 중앙값 초당 {speed:g}자) ================")

    # ---------------------------------------------------------- 실무자
    print("\n[실무자] 운영·문항은행")
    m = [b["minutes"] for b in bots]
    print(f"  P1 1차 문제 풀이 시간(분): 중앙값 {np.median(m):.1f} · 90% {pctl(m, 90):.1f} · 최대 {max(m):.1f}"
          f"  (+ 자기평가 36·마지막 8문항 약 4~5분)")
    to = [b["timeouts"] / b["n_cri"] for b in bots if b["n_cri"]]
    by_lv = Counter()
    for b in bots:
        by_lv.update(b["timeouts_by_level"])
    slow = sorted(bots, key=lambda b: b["speed"])[: n // 4]
    print(f"  P2 위기 대처 시간 초과: 문항 평균 {100 * np.mean(to):.1f}% · 1개 이상 초과한 사람 {100 * np.mean([b['timeouts'] > 0 for b in bots]):.0f}%"
          f" · 읽기 느린 1/4은 문항 {100 * np.mean([b['timeouts'] / b['n_cri'] for b in slow]):.1f}%"
          f" · 난이도별 초과 건수 {dict(sorted(by_lv.items()))}")
    use = Counter(i for b in bots for r in b["used"] for i in r)
    n_bank = len(_ITEMS)
    exp1 = Counter(i for b in bots for i in b["used"][0])
    rates = np.array([exp1[it.id] / n for it in _ITEMS])
    print(f"  P3 문항 노출(1차): 한 번도 안 나온 문항 {np.sum(rates == 0)}/{n_bank} · 노출률 중앙값 {100 * np.median(rates[rates > 0]):.1f}%"
          f" · 최대 {100 * rates.max():.1f}% · 1~3차 전체에서 안 쓰인 문항 {n_bank - len(use)}")
    need = 30 / rates[rates > 0]
    print(f"  P4 문항 판정(응답 30개)에 필요한 1차 응시자 수: 중앙값 {np.median(need):.0f}명 · 90% {pctl(need, 90):.0f}명 · 최대 {need.max():.0f}명")
    hi, lo = extremes(mode)
    cs = [b["correct_share"] for b in bots]
    print(f"  P5 1차 만점 EQ {hi:.0f} · 전부 틀림 EQ {lo:.0f} · 만점 봇 {100 * np.mean([c == 1 for c in cs]):.2f}% · 정답률 중앙값 {100 * np.median(cs):.0f}%")

    # ---------------------------------------------------------- 연구자
    print("\n[연구자] 신뢰도·타당도")
    g = [b["g"] for b in bots]
    mean_th = [np.mean(list(b["th"].values())) for b in bots]
    eq1 = [b["eq"][0] for b in bots]
    eq2 = [b["eq"][1] for b in bots]
    print(f"  R1 종합 EQ: 참 평균 능력과 상관 1차 {corr(eq1, mean_th):.2f} · 1~3차 {corr([b['eq'][2] for b in bots], mean_th):.2f}"
          f" · 재검사(1차↔2차) {corr(eq1, eq2):.2f}")
    conv = [corr([b["dom1"][d] for b in bots], [b["th"][d] for b in bots]) for d in dv]
    conv13 = [corr([b["dom13"][d] for b in bots], [b["th"][d] for b in bots]) for d in dv]
    disc = [np.mean([corr([b["dom1"][d] for b in bots], [b["th"][o] for b in bots]) for o in dv if o != d]) for d in dv]
    print("  R2 영역 점수 ↔ 그 영역 참 능력(수렴) vs 다른 영역 참 능력(변별), 1차 → 1~3차 수렴")
    for d, c1, c3, dd in zip(DOMAINS, conv, conv13, disc):
        print(f"     {BLUEPRINT[d].label:<8} 수렴 {c1:.2f} → {c3:.2f} · 변별 {dd:.2f} · 차이 {c1 - dd:+.2f}")
    # 프로필(개인 안 영역 차이) 회복: 영역 점수 − 본인 평균 vs 참 영역 θ − 본인 평균
    def prof_r(key):
        xs, ys = [], []
        for b in bots:
            s = np.array([b[key][d] for d in dv]); t = np.array([b["th"][d] for d in dv])
            xs += list(s - s.mean()); ys += list(t - t.mean())
        return corr(xs, ys)
    print(f"  R3 개인 프로필(영역 간 차이) 회복 상관: 1차 {prof_r('dom1'):.2f} · 1~3차 {prof_r('dom13'):.2f}")
    print(f"     → 영역 점수 차이의 신뢰도: 참 영역 차이의 분산 비율 (1차 기준) 위 상관의 제곱 ≈ {prof_r('dom1') ** 2:.2f}")
    dom_rt = [corr([b["dom1"][d] for b in bots], [b["dom2"][d] for b in bots]) for d in dv]
    print(f"  R4 영역 점수 재검사 상관 (1차↔2차): {min(dom_rt):.2f} ~ {max(dom_rt):.2f}")
    part = sum(b["partial"] for b in bots) / max(1, sum(b["bw"] for b in bots))
    print(f"  R5 최선·최악 문항에서 최선만 맞힌 응답: {100 * part:.1f}% (부분 점수 0.5로 추정에 반영)")
    cri = [b["cri_eq"] for b in bots]
    th_c = [b["th"]["cri"] for b in bots]
    sp = [math.log(b["speed"]) for b in bots]
    # 위기 대처 점수에 읽기 속도가 섞였는지: 참 능력을 통제한 편상관
    r_cs, r_ct, r_ts = corr(cri, sp), corr(cri, th_c), corr(th_c, sp)
    pr = (r_cs - r_ct * r_ts) / math.sqrt((1 - r_ct ** 2) * (1 - r_ts ** 2))
    other = [np.mean([b["dom1"][d] for d in dv if d != "cri"]) for b in bots]
    print(f"  R6 위기 대처 점수와 읽기 속도의 편상관(참 능력 통제): {pr:.2f} (다른 영역 평균과 읽기 속도 상관 {corr(other, sp):.2f})")
    print(f"  R7 EQ 분포: 평균 {np.mean(eq1):.1f} · 표준편차 {np.std(eq1):.1f} · 130 이상 {100 * np.mean(np.array(eq1) >= 130):.1f}%"
          f" (기대 2.3%) · 70 미만 {100 * np.mean(np.array(eq1) < 70):.1f}% (기대 2.3%)")

    # ---------------------------------------------------------- 이용자
    print("\n[이용자] 다시 하면? 내 강점은? 유형은?")
    diff = np.abs(np.array(eq1) - np.array(eq2))
    print(f"  U1 다시 풀었을 때(겹치지 않는 2차) EQ 차이: 중앙값 {np.median(diff):.1f}점 · 90% {pctl(diff, 90):.1f}점 · 15점 이상 {100 * np.mean(diff >= 15):.1f}%")
    flip = np.mean([b["level"][0] != b["level"][1] for b in bots])
    print(f"     수준 이름(보통·우수 등)이 바뀜 {100 * flip:.0f}% · 1차 90% 범위가 2차 점수를 포함 "
          f"{100 * np.mean([b['lo_hi'][0] <= b['eq'][1] <= b['lo_hi'][1] for b in bots]):.0f}%")
    flipped = [b for b in bots if b["level"][0] != b["level"][1]]
    print(f"     '경계 근처' 안내를 받은 사람 {100 * np.mean([b['boundary'] for b in bots]):.0f}%"
          f" · 수준 이름이 바뀐 사람 중 1차에 안내를 받았던 비율 {100 * np.mean([b['boundary'] for b in flipped]):.0f}%"
          f" · 안내 없이 바뀐 사람 {100 * np.mean([not b['boundary'] for b in flipped]) * len(flipped) / n:.1f}%")
    print(f"  U2 영역 점수 오차(1차 평균 90% 범위 반폭) ±{np.mean([b['margin1'] for b in bots]):.1f}점")
    shown = [b for b in bots if b["strong"]]
    ok = []
    for b in shown:
        t = b["th"]; mt = np.mean(list(t.values()))
        ok += [t[d] > mt for d in b["strong"]]
    best_hit = []
    for b in shown:
        t = b["th"]
        best_hit.append(max(t, key=t.get) in b["strong"])
    print(f"  U3 '상대적 강점'이 표시된 사람 {100 * len(shown) / n:.0f}% · 표시된 강점이 실제로 본인 평균보다 높음 {100 * np.mean(ok):.0f}%"
          f" · 실제 최고 영역이 강점에 포함 {100 * np.mean(best_hit):.0f}%")
    wshown = [b for b in bots if b["weak"]]
    wok = [b["th"][d] < np.mean(list(b["th"].values())) for b in wshown for d in b["weak"]]
    print(f"     '더 키우면 좋은 영역' 표시 {100 * len(wshown) / n:.0f}% · 실제로 본인 평균보다 낮음 {100 * np.mean(wok):.0f}%")
    names = Counter(b["name"][0] for b in bots)
    print(f"  U4 유형 이름 (1차): 서로 다른 이름 {len(names)}개 · 상위 5개 "
          + ", ".join(f"{k} {100 * c / n:.0f}%" for k, c in names.most_common(5)))
    print(f"     상황맞춤형+균형형 {100 * (names['상황맞춤형'] + names['균형형']) / n:.0f}%"
          f" · 재검사 같은 이름 {100 * np.mean([b['name'][0] == b['name'][1] for b in bots]):.0f}%")
    hi_s = [b for b in bots if b["strength"] > 1.33]
    lo_s = [b for b in bots if b["strength"] < 0.67]
    plain = {"상황맞춤형", "균형형"}
    print(f"     성향이 강한 1/3: 축 이름 받음 {100 * np.mean([b['name'][0] not in plain for b in hi_s]):.0f}%"
          f" · 약한 1/3: {100 * np.mean([b['name'][0] not in plain for b in lo_s]):.0f}%")
    gq = np.quantile(g, [1 / 3, 2 / 3])
    for lab, sel in (("능력 하", lambda x: x < gq[0]), ("능력 상", lambda x: x >= gq[1])):
        gb = [b for b in bots if sel(b["g"])]
        c = Counter(b["name"][0] for b in gb)
        print(f"     {lab}: " + ", ".join(f"{k} {100 * v / len(gb):.0f}%" for k, v in c.most_common(3)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000, help="모드별 봇 수")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--rho", type=float, default=RHO, help="영역 능력 사이 상관 (1이면 모든 영역 능력 같음)")
    ap.add_argument("--speed", type=float, default=SPEED, help="읽기 속도 중앙값 (초당 글자)")
    ap.add_argument("--old-crisis", action="store_true", help="위기 대처를 예전처럼 문제+보기 전체에 시간 제한")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    global TWO_PHASE
    TWO_PHASE = not args.old_crisis
    _init()
    for mode in Mode:
        t0 = time.time()
        chunk = max(1, args.n // (args.workers * 4))
        jobs = [(7919 * (i + 1) + (11 if mode is Mode.FULL else 0), mode.value, min(chunk, args.n - i * chunk),
                 args.rho, args.speed)
                for i in range(math.ceil(args.n / chunk))]
        bots = []
        with ProcessPoolExecutor(max_workers=args.workers, initializer=_init) as pool:
            for part in pool.map(run, jobs):
                bots += part
        report(bots, mode, args.rho, args.speed)
        print(f"  ({time.time() - t0:.0f}초)")


if __name__ == "__main__":
    main()
