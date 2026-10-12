"""봇 시뮬레이션으로 점수 보정표 만들기: python scripts/build_sim_norms.py [--n 20000] [--workers 8]

가상 응시자(봇)가 실제 출제 로직으로 1·2·3차 검증과 심층검사를 모두 풉니다.
봇의 영역 능력은 서로 다르다: θ_영역 = √ρ·g + √(1−ρ)·e (기본 ρ = 0.5, --rho).
처음에는 모든 영역 능력이 같은 봇(ρ = 1)으로 만들었는데, 영역 능력이 다른 사람에게는 EQ 표준편차가 15가 아니라
약 10으로 좁아져 130 이상이 거의 나오지 않았다 (docs/11). 실제 ρ는 모르므로 '관련은 있지만 같지 않다'는 0.5를 쓴다.
종합의 참값은 영역 능력 평균을 표준화한 값, 영역의 참값은 그 영역 능력이다.
최선·최악 문항은 채점과 같은 순차 모형(부분 점수)으로 답한다.
단계(1차 / 1~2차 / 1~3차 / 1~3차+심층)마다 봇들의 능력 추정치(θ̂) 분포를 저장해, 실제 응시자의 θ̂를
"같은 단계를 마친 봇들 중 몇 번째인가"로 바꿉니다 (백분위 → EQ = 100 + 15·Φ⁻¹(백분위)).
영역 점수는 문항이 4~10개라 θ̂가 몇 개 값으로만 나와 백분위가 들쭉날쭉하므로, 봇 분포의 평균·표준편차로 표준화한다.

왜 필요한가: EAP 추정치는 문항이 적을수록 평균 쪽으로 줄어들어(축소), 그대로 쓰면 EQ 분포의 표준편차가 15보다
작아지고 상위·하위 %가 덜 극단적으로 나온다. 같은 검사를 푼 봇들의 분포와 비교하면 이 치우침이 사라진다.
또 봇의 참 능력과 비교해 90% 범위가 실제로 90%를 맞히는지 재고, 어긋나면 범위 배율을 저장한다.

한계: 봇은 문항 난이도 가정(expected_p 또는 calibration.json)대로 답한다. 실제 사람과의 비교는 실제 응답이
쌓여야 가능하며, 같은 모드 1차 첫 응시가 100명을 넘으면 결과 화면은 실제 분포 기준으로 바뀐다.
결과: norms/sim_norms.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import NormalDist

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import exam as ex  # noqa: E402
from core import scoring as sc  # noqa: E402
from core.item_bank import build_form, load_items  # noqa: E402
from core.schema import BLUEPRINT, ItemFormat, Mode  # noqa: E402

DOMAINS = list(BLUEPRINT)

STAGES = ["1", "1-2", "1-3", "1-3+deep"]
OUT = ROOT / "norms" / "sim_norms.json"
QUANT = np.linspace(0.001, 0.999, 401)  # 저장할 분위수 위치

_ITEMS: list | None = None
_BY_ID: dict | None = None


def _init():
    global _ITEMS, _BY_ID
    _ITEMS = load_items()
    _BY_ID = {it.id: it for it in _ITEMS}


def _p(item, theta: float) -> float:
    a, b, c = sc.item_params(item)
    return c + (1 - c) / (1 + math.exp(-sc.D * a * (theta - b)))


def _draw(item, theta: float, rng: random.Random) -> tuple[float, str]:
    """채점 모형대로 응답 → (점수 1·0.5·0, 응답 문자열). 최선·최악은 부분 점수."""
    probs = [float(x) for x in sc.category_probs(item, theta)]
    k = rng.choices(range(len(probs)), weights=probs)[0]
    if item.format is ItemFormat.MCQ:
        return float(k), str(item.answer if k else (item.answer + 1) % 4)
    best, worst = item.answer
    wrong_best = next(i for i in range(4) if i not in (best, worst))
    wrong_worst = next(i for i in range(4) if i not in (best, worst))
    return [0.0, 0.5, 1.0][k], [f"{wrong_best},{worst}", f"{best},{wrong_worst}", f"{best},{worst}"][k]


def _estimates(rows: list[dict]) -> dict:
    per, total = sc.estimate(rows, _BY_ID)
    return {"total": [total.theta, total.se], **{d.value: [e.theta, e.se] for d, e in per.items()}}


def simulate(args: tuple) -> list[dict]:
    """봇 n명 → [{theta, true: {total, 영역…}, stages: {단계: {total: [θ̂, SE], 영역: [...], ...}}}]"""
    start, mode_value, n, *rest = args
    rho = rest[0] if rest else 1.0
    if _ITEMS is None:
        _init()
    mode = Mode(mode_value)
    rng = random.Random(start)
    out = []
    for k in range(n):
        g = rng.gauss(0, 1)
        th = {d: math.sqrt(rho) * g + math.sqrt(1 - rho) * rng.gauss(0, 1) for d in DOMAINS}
        composite = sum(th.values()) / len(th) / math.sqrt(rho + (1 - rho) / len(th))  # 표준화한 영역 평균
        theta = composite
        seen: set[str] = set()
        rows: list[dict] = []
        stages = {}
        for r in range(3):
            form = build_form(_ITEMS, rng.randrange(2**31), mode, exclude=seen)
            for items in form.values():
                for it in items:
                    score, _ = _draw(it, th[it.domain], rng)
                    rows.append({"item_id": it.id, "domain": it.domain.value, "correct": score == 1, "score": score})
                    seen.add(it.id)
            stages[STAGES[r]] = _estimates(rows)
        # 심층검사: 실제 앱과 같은 선택·종료 로직
        seed = rng.randrange(2**31)
        state = ex.new_deep_exam(rows, seen, mode)
        deep_rows = []
        for i, d in enumerate(state["domains"]):
            state["d"] = i
            while (iid := ex.deep_next(state, _BY_ID, seed)) is not None:
                it = _BY_ID[iid]
                score, ans = _draw(it, th[it.domain], rng)
                state["answers"][iid] = ans
                deep_rows.append({"item_id": iid, "domain": d, "correct": score == 1, "score": score})
        stages["1-3+deep"] = _estimates(rows + deep_rows)
        out.append({"theta": theta, "true": {"total": composite, **{d.value: v for d, v in th.items()}},
                    "stages": stages})
    return out


def summarize(bots: list[dict]) -> dict:
    """단계·영역별 θ̂ 분위수표와 90% 범위 배율."""
    z90 = NormalDist().inv_cdf(0.95)
    result = {}
    for stage in STAGES:
        keys = bots[0]["stages"][stage].keys()
        result[stage] = {}
        for key in keys:
            est = np.array([b["stages"][stage][key][0] for b in bots if key in b["stages"][stage]])
            se = np.array([b["stages"][stage][key][1] for b in bots if key in b["stages"][stage]])
            true = np.array([b.get("true", {}).get(key, b["theta"]) for b in bots if key in b["stages"][stage]])
            q = np.quantile(est, QUANT)
            # 보정 후 점수(백분위 → z)와 참 능력의 차이로 범위 배율을 정한다
            z_hat = np.array([NormalDist().inv_cdf(min(max(np.searchsorted(np.sort(est), x) / len(est), 1e-4), 1 - 1e-4))
                              for x in est]) if key == "total" else None
            entry = {"quantiles": [round(float(v), 5) for v in q], "n": int(len(est)),
                     "mean": round(float(est.mean()), 5), "sd": round(float(est.std()), 5),
                     "mean_se": round(float(se.mean()), 4), "sd_raw_index": round(15 * float(est.std()), 2)}
            if z_hat is not None:
                # 보정 전: θ̂ ± 1.645·SE 가 참 θ를 포함하는 비율
                cover_raw = float(np.mean(np.abs(est - true) <= z90 * se))
                # 보정 후: 범위 끝을 같은 표로 옮겼을 때
                lo = np.interp(est - z90 * se, q, [NormalDist().inv_cdf(p) for p in QUANT])
                hi = np.interp(est + z90 * se, q, [NormalDist().inv_cdf(p) for p in QUANT])
                cover = float(np.mean((lo <= true) & (true <= hi)))
                # 목표 90%에 맞는 배율을 찾는다 (이분 탐색)
                lo_s, hi_s = 0.5, 3.0
                for _ in range(30):
                    mid = (lo_s + hi_s) / 2
                    lo_m = np.interp(est - z90 * se * mid, q, [NormalDist().inv_cdf(p) for p in QUANT])
                    hi_m = np.interp(est + z90 * se * mid, q, [NormalDist().inv_cdf(p) for p in QUANT])
                    if np.mean((lo_m <= true) & (true <= hi_m)) < 0.90:
                        lo_s = mid
                    else:
                        hi_s = mid
                rmse_raw = 15 * float(np.sqrt(np.mean((est - true) ** 2)))
                rmse_cal = 15 * float(np.sqrt(np.mean((z_hat - true) ** 2)))
                entry |= {"ci_scale": round(hi_s, 3), "coverage_raw": round(cover_raw, 3),
                          "coverage_before_scale": round(cover, 3),
                          "sd_raw_index": round(15 * float(est.std()), 2),
                          "rmse_raw": round(rmse_raw, 2), "rmse_calibrated": round(rmse_cal, 2)}
            result[stage][key] = entry
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20000, help="모드별 봇 수")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry", action="store_true", help="저장하지 않고 요약만 출력")
    ap.add_argument("--rho", type=float, default=0.5, help="영역 능력 사이 상관 (1이면 모든 영역 능력이 같음)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    out = {"n_per_mode": args.n, "rho": args.rho, "stages": STAGES, "quantile_probs": [round(float(p), 6) for p in QUANT],
           "built": time.strftime("%Y-%m-%d %H:%M"), "modes": {}}
    for mode in Mode:
        t0 = time.time()
        chunk = max(1, args.n // (args.workers * 4))
        jobs = [(1_000_003 * (i + 1) + (7 if mode is Mode.FULL else 0), mode.value, min(chunk, args.n - i * chunk),
                 args.rho)
                for i in range(math.ceil(args.n / chunk))]
        bots = []
        with ProcessPoolExecutor(max_workers=args.workers, initializer=_init) as pool:
            for part in pool.map(simulate, jobs):
                bots += part
        summary = summarize(bots)
        out["modes"][mode.value] = summary
        print(f"\n[{mode.value}] 봇 {len(bots):,}명 · {time.time() - t0:.0f}초")
        for stage in STAGES:
            t = summary[stage]["total"]
            doms = " ".join(f"{k}:{v['sd_raw_index']:.1f}" for k, v in summary[stage].items() if k != "total")
            print(f"  {stage:<9} 종합 EQ 표준편차 {t['sd_raw_index']:5.2f} · 참값 오차 {t['rmse_raw']:.2f} → "
                  f"{t['rmse_calibrated']:.2f} · 90% 범위 적중(점수 변환 후) {t['coverage_before_scale']:.1%} → 배율 {t['ci_scale']}로 90%")
            print(f"            영역 EQ 표준편차 {doms}")
    if not args.dry:
        OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        print(f"\n저장: {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
