"""유형 판정 검증: python scripts/simulate_styles.py [--n 6000] [--workers 8]

봇마다 '참 성향'을 심어 두고 실제 출제 로직으로 1·2·3차를 풀게 한 뒤, core.style이 그 성향을 얼마나 되찾는지 잰다.

봇의 응답 모형:
- 능력 θ ~ N(0, 1). 문항마다 3PL 확률로 '단서를 읽고' 정답을 고른다 (최선·최악 문항은 최선을 √p로).
- 단서를 놓치면 버릇대로 고른다. 행동 영역: 보기 가중치 exp(강도 × 참 축 벡터 · 보기 유형의 축).
  해석 영역: 심어 둔 '잘못 읽는 방향' 보기에 exp(강도).
- 참 축 벡터: 세 축마다 −1·0·+1 중 하나 (모두 0이면 다시 뽑음).
- 봇 종류: 강한 성향(강도 2.0) · 약한 성향(강도 1.0) · 무성향(버릇 없음) 같은 수.

재는 것:
1. 결정성: 같은 응답을 순서만 섞어 다시 넣어도 같은 결과인가
2. 축 회복: 참 축과 추정 축의 상관, 뚜렷하다고 표시한 축의 방향이 참과 맞는 비율(정밀도), 참이 0인데 뚜렷하다고 한 비율
3. 이름: 이름의 중심 축 방향이 참 성향과 맞는 비율, 무성향 봇이 상황맞춤형·균형형으로 나오는 비율
4. 영역 유형: '기우는 방향'을 말했을 때 맞는 비율(정밀도)과 말한 비율(회복률)
5. 재검사: 겹치지 않는 1차·2차를 따로 풀었을 때 축 상관·이름 일치·영역 유형 일치
6. 능력과의 얽힘: 무성향 봇의 능력 구간별 '거짓 유형' 비율
7. 영역 점수(1차)와 참 능력의 상관 (관계 갈등 포함)
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

from core import scoring as sc  # noqa: E402
from core import style as sty  # noqa: E402
from core.item_bank import build_form, load_items  # noqa: E402
from core.schema import BLUEPRINT, READING_DOMAINS, STYLES, ItemFormat, Mode  # noqa: E402

KINDS = {"강한 성향": 2.0, "약한 성향": 1.0, "무성향": 0.0}
ACTION = [d for d in BLUEPRINT if d not in READING_DOMAINS]
READING = [d for d in BLUEPRINT if d in READING_DOMAINS]
AXIS_KEYS = [k for k, *_ in sty.AXES]

_ITEMS: list | None = None
_BY_ID: dict | None = None


def _init():
    global _ITEMS, _BY_ID
    _ITEMS = load_items()
    _BY_ID = {it.id: it for it in _ITEMS}


def _p(item, theta: float) -> float:
    a, b, c = sc.item_params(item)
    return c + (1 - c) / (1 + math.exp(-sc.D * a * (theta - b)))


def expected_lean(domain, v) -> list[str]:
    """참 축 벡터로 본 그 영역의 버릇 유형들 (가장 끌리는 유형, 동점이면 모두). 끌림이 없으면 []."""
    scores = {c: sum(a * b for a, b in zip(STYLES[domain][c].axes, v)) for c in STYLES[domain]}
    top = max(scores.values())
    return sorted(c for c, x in scores.items() if x == top) if top > 0 else []


def answer(item, theta, v, bias, strength, rng) -> dict:
    p = _p(item, theta)
    bw = item.format is ItemFormat.BEST_WORST
    key = item.answer[0] if bw else item.answer
    if rng.random() < (math.sqrt(p) if bw else p):
        best = key
    else:
        st = STYLES[item.domain]
        if not item.styles or strength == 0:
            w = [1.0] * 4
        elif item.domain in READING_DOMAINS:
            w = [math.exp(strength if s == bias[item.domain] else 0.0) for s in item.styles]
        else:
            w = [math.exp(strength * sum(a * b for a, b in zip(st[s].axes, v))) for s in item.styles]
        best = rng.choices(range(4), weights=w)[0]
    if bw:
        wk = item.answer[1]
        worst = wk if (best == key and rng.random() < math.sqrt(p)) else rng.choice([i for i in range(4) if i != best])
        ok, ans = best == key and worst == wk, f"{best},{worst}"
    else:
        ok, ans = best == key, str(best)
    return {"item_id": item.id, "domain": item.domain.value, "answer": ans, "correct": ok, "score": float(ok)}


def summarize_profile(p: sty.Profile) -> dict:
    return {"name": p.name, "axes": [p.axes[k] for k in AXIS_KEYS],
            "strong": [abs(p.axes[k]) >= sty.AXIS_STRONG and abs(p.axes_z[k]) >= sty.AXIS_Z for k in AXIS_KEYS],
            "dom": {d.domain.value: d.name for d in p.domains},
            "lean": {d.domain.value: d.code for d in p.domains if d.code and not d.matched and d.n >= sty.MIN_PICKS}}


def run(args: tuple[int, str, int]) -> list[dict]:
    seed, mode_value, n = args
    if _ITEMS is None:
        _init()
    mode = Mode(mode_value)
    rng = random.Random(seed)
    out = []
    for k in range(n):
        kind = list(KINDS)[k % 3]
        strength = KINDS[kind]
        theta = rng.gauss(0, 1)
        v = [0, 0, 0]
        while strength and v == [0, 0, 0]:
            v = [rng.choice([-1, 0, 1]) for _ in range(3)]
        bias = {d: rng.choice([c for c in STYLES[d] if c != "acc"]) for d in READING}
        seen: set[str] = set()
        rounds = []
        for _ in range(3):
            form = build_form(_ITEMS, rng.randrange(2**31), mode, exclude=seen)
            rows = [answer(it, theta, v, bias, strength, rng) for items in form.values() for it in items]
            seen |= {r["item_id"] for r in rows}
            rounds.append(rows)
        all_rows = [r for rows in rounds for r in rows]
        p1, p2, p13 = (sty.profile(r, _BY_ID) for r in (rounds[0], rounds[1], all_rows))
        shuffled = all_rows[:]
        rng.shuffle(shuffled)
        a, b = summarize_profile(p13), summarize_profile(sty.profile(shuffled, _BY_ID))
        per, _ = sc.estimate(rounds[0], _BY_ID)
        out.append({
            "kind": kind, "theta": theta, "v": v, "bias": {d.value: c for d, c in bias.items()},
            "exp_lean": {d.value: expected_lean(d, v) if strength else [] for d in ACTION},
            "p1": summarize_profile(p1), "p2": summarize_profile(p2), "p13": a, "deterministic": a == b,
            "dom_theta": {d.value: e.theta for d, e in per.items()},
        })
    return out


def pct(x) -> str:
    return f"{100 * x:5.1f}%" if not (isinstance(x, float) and math.isnan(x)) else "  -  "


def name_axis(name: str) -> tuple[str, int] | None:
    for (k, s), noun in sty.AXIS_NOUNS.items():
        if name.endswith(noun):
            return k, s
    return None


def report(bots: list[dict], mode: str) -> None:
    print(f"\n================ [{mode}] 봇 {len(bots):,}명 (종류마다 {len(bots) // 3:,}명) ================")
    print(f"1. 결정성 (같은 응답, 순서만 섞음 → 같은 결과): {pct(np.mean([b['deterministic'] for b in bots]))}")

    for stage, key in (("1차만", "p1"), ("1~3차 합산", "p13")):
        print(f"\n--- {stage} ---")
        print("2. 축 회복  [참·추정 상관 A/B/C] [뚜렷한 축 정밀도] [참이 0인 축을 뚜렷하다고 함] [참이 ±1인 축을 뚜렷하게 잡음]")
        for kind in KINDS:
            bs = [b for b in bots if b["kind"] == kind]
            if kind != "무성향":
                r = [np.corrcoef([b["v"][j] for b in bs], [b[key]["axes"][j] for b in bs])[0, 1] for j in range(3)]
                strong = [(b["v"][j], b[key]["axes"][j]) for b in bs for j in range(3) if b[key]["strong"][j]]
                prec = np.mean([t != 0 and np.sign(t) == np.sign(e) for t, e in strong]) if strong else float("nan")
                fp = np.mean([b[key]["strong"][j] for b in bs for j in range(3) if b["v"][j] == 0])
                hit = np.mean([b[key]["strong"][j] and np.sign(b[key]["axes"][j]) == b["v"][j]
                               for b in bs for j in range(3) if b["v"][j] != 0])
                print(f"   {kind}: 상관 {r[0]:.2f}/{r[1]:.2f}/{r[2]:.2f} · 정밀도 {pct(prec)} · 거짓 표시 {pct(fp)} · 잡아냄 {pct(hit)}")
            else:
                fp = np.mean([b[key]["strong"][j] for b in bs for j in range(3)])
                print(f"   {kind}: 뚜렷하다고 잘못 표시한 축 {pct(fp)}")

        print("3. 이름  [중심 축이 참 성향과 같은 방향] [이름 분포 상위]")
        for kind in KINDS:
            bs = [b for b in bots if b["kind"] == kind]
            axes = [(name_axis(b[key]["name"]), b["v"]) for b in bs]
            named = [(na, v) for na, v in axes if na]
            ok = np.mean([v[AXIS_KEYS.index(na[0])] == na[1] for na, v in named]) if named else float("nan")
            top = Counter(b[key]["name"] for b in bs).most_common(3)
            print(f"   {kind}: 축 이름이 붙은 비율 {pct(len(named) / len(bs))} · 그중 방향 맞음 {pct(ok)} · "
                  + ", ".join(f"{n} {100 * c / len(bs):.0f}%" for n, c in top))

        print("4. 영역 유형 '기우는 방향'  [말했을 때 맞음(정밀도)] [참 버릇이 있을 때 말한 비율] [무성향인데 말함]")
        for d in BLUEPRINT:
            dv = d.value
            if d in READING_DOMAINS:
                truth = lambda b: [b["bias"][dv]] if b["kind"] != "무성향" else []  # noqa: E731
            else:
                truth = lambda b: b["exp_lean"][dv]  # noqa: E731
            claims = [(b[key]["lean"][dv], truth(b)) for b in bots if dv in b[key]["lean"] and b["kind"] != "무성향"]
            prec = np.mean([c in t for c, t in claims]) if claims else float("nan")
            has = [b for b in bots if truth(b)]
            recall = np.mean([b[key]["lean"].get(dv) in truth(b) for b in has]) if has else float("nan")
            none = [b for b in bots if b["kind"] == "무성향"]
            fp = np.mean([dv in b[key]["lean"] for b in none])
            print(f"   {BLUEPRINT[d].label:<8} 정밀도 {pct(prec)} · 회복률 {pct(recall)} · 거짓 {pct(fp)}")

    print("\n5. 재검사 (겹치지 않는 1차와 2차를 따로)")
    for kind in KINDS:
        bs = [b for b in bots if b["kind"] == kind]
        r = [np.corrcoef([b["p1"]["axes"][j] for b in bs], [b["p2"]["axes"][j] for b in bs])[0, 1] for j in range(3)]
        name = np.mean([b["p1"]["name"] == b["p2"]["name"] for b in bs])
        center = np.mean([name_axis(b["p1"]["name"]) == name_axis(b["p2"]["name"]) for b in bs])
        dom = np.mean([b["p1"]["dom"].get(d.value) == b["p2"]["dom"].get(d.value) for b in bs for d in BLUEPRINT])
        print(f"   {kind}: 축 상관 {r[0]:.2f}/{r[1]:.2f}/{r[2]:.2f} · 이름 완전 같음 {pct(name)} · 중심 축 같음 {pct(center)}"
              f" · 영역 유형 같음 {pct(dom)}")

    print("\n6. 능력과의 얽힘: 무성향 봇, 능력 구간별 (1~3차)")
    bs = [b for b in bots if b["kind"] == "무성향"]
    cuts = np.quantile([b["theta"] for b in bs], [1 / 3, 2 / 3])
    for g, lo, hi in (("하", -9, cuts[0]), ("중", cuts[0], cuts[1]), ("상", cuts[1], 9)):
        gb = [b for b in bs if lo <= b["theta"] < hi]
        fake_axis = np.mean([any(b["p13"]["strong"]) for b in gb])
        fake_lean = np.mean([len(b["p13"]["lean"]) for b in gb])
        names = Counter(b["p13"]["name"] for b in gb).most_common(2)
        print(f"   {g}: 거짓 축 이름 {pct(fake_axis)} · 거짓 기우는 방향 평균 {fake_lean:.2f}개/8영역 · "
              + ", ".join(f"{n} {100 * c / len(gb):.0f}%" for n, c in names))

    print("\n7. 영역 점수(1차)와 참 능력의 상관")
    print("   " + " · ".join(f"{d.value} {np.corrcoef([b['theta'] for b in bots], [b['dom_theta'][d.value] for b in bots])[0, 1]:.2f}"
                             for d in BLUEPRINT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6000, help="모드별 봇 수 (3종류로 나눔)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    for mode in Mode:
        t0 = time.time()
        chunk = max(3, (args.n // (args.workers * 4)) // 3 * 3)
        jobs = [(97 * (i + 1) + (5 if mode is Mode.FULL else 0), mode.value, min(chunk, args.n - i * chunk))
                for i in range(math.ceil(args.n / chunk))]
        bots = []
        with ProcessPoolExecutor(max_workers=args.workers, initializer=_init) as pool:
            for part in pool.map(run, jobs):
                bots += part
        report(bots, mode.value)
        print(f"   ({time.time() - t0:.0f}초)")


if __name__ == "__main__":
    main()
