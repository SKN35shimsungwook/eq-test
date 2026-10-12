"""가상 응시 데이터 생성 (로컬 개발·분석 화면 확인용): python scripts/simulate.py [--n 300] [--reset] [--url ...]

- 능력 θ ~ N(0, 1)인 가상 응시자가 실제 출제 로직(core.exam)으로 자기평가와 1·2·3차, 심층검사를 풉니다.
- 문항의 '참 난이도'를 가정값에서 조금씩 흔들고, 일부 문항은 일부러 아주 쉽게/어렵게 만들어
  관리자 분석이 그런 문항을 찾아내는지 확인할 수 있게 합니다.
- 일부 문항은 '정답 키가 틀린' 상황을 흉내 냅니다: 잘하는 사람일수록 정답이 아닌 다른 보기를 고릅니다
  (관리자 화면의 '다수 응답과 정답 불일치' 판정 확인용).
- 자기평가는 실제 능력과 약하게만 관련되게(r≈0.2) 만들고, 일부는 좋게만 답하게 합니다.
- 세션의 app_version이 "sim"이라 규준 계산에서 빠지고, 분석 화면에서도 기본으로 제외됩니다.
"""

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db  # noqa: E402
from core import exam as ex  # noqa: E402
from core import scoring as sc  # noqa: E402
from core.analysis import SIM_VERSION  # noqa: E402
from core.item_bank import build_form, load_items, load_self_items  # noqa: E402
from core.schema import DEEP_ROUND, Domain, ItemFormat, Mode  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=300)
ap.add_argument("--reset", action="store_true")
ap.add_argument("--db", default=str(ROOT / "data" / "eq_test.db"))
ap.add_argument("--url", help="SQLAlchemy DB URL (지정하면 --db 대신 사용, 예: Postgres 점검용)")
args = ap.parse_args()

engine = sa.create_engine(args.url or f"sqlite:///{Path(args.db).as_posix()}")
Path(args.db).parent.mkdir(exist_ok=True)
db.init_db(engine)
with engine.begin() as conn:
    sim_ids = [r.id for r in conn.execute(sa.select(db.sessions.c.id).where(db.sessions.c.app_version == SIM_VERSION))]
    conn.execute(db.responses.delete().where(db.responses.c.session_id.in_(sim_ids)))
    conn.execute(db.sessions.delete().where(db.sessions.c.app_version == SIM_VERSION))
print(f"기존 시뮬레이션 세션 {len(sim_ids)}개 삭제")
if args.reset:
    sys.exit()

items_list = load_items()
items = {it.id: it for it in items_list}
self_items = load_self_items()
rng = random.Random(7)

# 참 난이도: 가정 b에 잡음을 더하고, 일부 문항은 일부러 크게 어긋나게 한다
true_b = {it.id: sc.item_params(it)[1] + rng.gauss(0, 0.3) for it in items_list}
planted = {}
for iid in rng.sample(list(items), 12):
    shift = rng.choice([-2.5, 2.5])
    true_b[iid] += shift
    planted[iid] = "실제로 훨씬 쉬움" if shift < 0 else "실제로 훨씬 어려움"
# 정답 키가 틀린 문항: 잘하는 사람은 정답 대신 이 보기를 고른다
wrong_key = {}
for iid in rng.sample([i for i in items if i not in planted], 6):
    it = items[iid]
    key = it.answer if it.format is ItemFormat.MCQ else it.answer[0]
    wrong_key[iid] = rng.choice([k for k in range(4) if k != key])
    planted[iid] = f"정답 키 오류 (잘하는 사람은 {'ABCD'[wrong_key[iid]]} 선택)"


def p_correct(item_id: str, theta: float) -> float:
    a, _, c = sc.item_params(items[item_id])
    return c + (1 - c) / (1 + np.exp(-sc.D * a * (theta - true_b[item_id])))


def answer(item_id: str, theta: float) -> str:
    it = items[item_id]
    ok = rng.random() < p_correct(item_id, theta)
    if it.format is ItemFormat.MCQ:
        key = wrong_key.get(item_id, it.answer)
        return str(key if ok else rng.choice([k for k in range(4) if k != key]))
    best, worst = it.answer
    if item_id in wrong_key:
        best = wrong_key[item_id]
        worst = it.answer[1] if it.answer[1] != best else it.answer[0]
    if ok:
        return f"{best},{worst}"
    b = rng.choice([best] + [k for k in range(4) if k != best])  # 틀린 경우에도 최선은 맞히기도 한다
    w = rng.choice([k for k in range(4) if k != b and (b != best or k != worst)])
    return f"{b},{w}"


def self_answers(theta: float) -> dict[str, int]:
    """자기평가: 능력과 약하게(r≈0.2) 관련, 15%는 좋게만 답하는 응답자."""
    faking = rng.random() < 0.15
    out = {}
    for it in self_items:
        if it.check:
            out[it.id] = rng.choice([4, 5]) if faking else rng.choice([1, 1, 2, 2, 3])
            continue
        latent = 3.6 + 0.55 * (0.2 * theta + 0.98 * rng.gauss(0, 1)) + (0.6 if faking else 0)
        v = min(5, max(1, round(latent)))
        out[it.id] = 6 - v if it.reverse else v
    return out


def finish(sid: str, state: dict, rows: list[dict]) -> None:
    per, total = sc.estimate(rows, items)
    db.save_progress(engine, sid, state)
    db.complete_session(engine, sid, {d.value: e.raw for d, e in per.items()},
                        {d.value: round(e.index, 1) for d, e in per.items()}, round(total.index, 1),
                        round(sc.percentile(total.theta), 1),
                        thetas={"total": total.theta, **{d.value: e.theta for d, e in per.items()}},
                        focus_lost=rng.choice([0, 0, 0, 1, 2]))


def ms_for(iid: str) -> int:
    return int(rng.lognormvariate(9.6 + 0.15 * items[iid].difficulty, 0.4))  # 약 15~30초


def run_round(theta: float, mode: Mode, client: str, series: str | None, round_no: int, seen: set):
    seed = rng.randrange(2**31)
    sid = db.start_session(engine, client, mode.value, seed, SIM_VERSION, series_id=series, round_no=round_no)
    state = ex.new_exam(build_form(items_list, seed, mode, exclude=seen), mode)
    if round_no == 1:
        sa_ = self_answers(theta)
        db.save_responses(engine, sid, [
            {"item_id": it.id, "item_version": it.version, "domain": "sr", "answer": str(sa_[it.id]), "correct": False,
             "score": float(sa_[it.id] if it.check else it.score(sa_[it.id])), "response_ms": None} for it in self_items])
        db.save_self_scores(engine, sid, ex.self_scores(self_items, sa_))
    all_rows = []
    while state["d"] < len(state["domains"]):
        d = ex.current_domain(state)
        for iid in state["items"][d.value]:
            state["answers"][iid] = answer(iid, theta)
            state["ms"][iid] = ms_for(iid)
        rows = ex.domain_rows(state, items, d)
        db.save_responses(engine, sid, rows)
        all_rows += rows
        ex.finish_domain(state, rows)
    finish(sid, state, all_rows)
    return sid, {r["item_id"] for r in all_rows}, all_rows


def run_deep(theta: float, mode: Mode, client: str, series: str, seen: set, prior: list[dict]) -> None:
    seed = rng.randrange(2**31)
    sid = db.start_session(engine, client, mode.value, seed, SIM_VERSION, series_id=series, round_no=DEEP_ROUND)
    state = ex.new_deep_exam(prior, seen, mode)
    all_rows = []
    while state["d"] < len(state["domains"]):
        d = ex.current_domain(state)
        while (iid := ex.deep_next(state, items, seed)) is not None:
            state["answers"][iid] = answer(iid, theta)
            state["ms"][iid] = ms_for(iid)
        rows = ex.domain_rows(state, items, d)
        db.save_responses(engine, sid, rows)
        all_rows += rows
        ex.finish_domain(state, rows)
    finish(sid, state, all_rows)


for i in range(args.n):
    theta = rng.gauss(0, 1)
    mode = Mode.QUICK if rng.random() < 0.6 else Mode.FULL
    series, seen, prior = None, set(), []
    for r in range(1, 4):  # 1차는 모두, 2차 40%, 3차는 그중 70%
        if r == 2 and rng.random() > 0.4 or r == 3 and rng.random() > 0.7:
            break
        sid, shown, rows = run_round(theta + 0.05 * (r - 1), mode, f"sim-{i}", series, r, seen)
        series = series or sid
        seen |= shown
        prior += rows
    else:
        if rng.random() < 0.8:  # 3차까지 한 사람의 80%가 심층검사
            run_deep(theta, mode, f"sim-{i}", series, seen, prior)
    if (i + 1) % 50 == 0:
        print(f"  {i + 1}/{args.n}명")

print(f"시뮬레이션 응시자 {args.n}명 저장 (app_version='{SIM_VERSION}')")
print("일부러 어긋나게 만든 문항:", json.dumps(planted, ensure_ascii=False))
