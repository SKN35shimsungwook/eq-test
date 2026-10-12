import random

import pytest

from core import exam as ex
from core import report as rp
from core import scoring as sc
from core.item_bank import build_form, load_items, load_self_items
from core.schema import BLUEPRINT, CRISIS_SEC, DEEP_MAX_ITEMS, Domain, ItemFormat, Mode

ITEMS = load_items()
BY_ID = {it.id: it for it in ITEMS}


def rows_for(form, correct_fn):
    return [{"item_id": it.id, "domain": d.value, "correct": correct_fn(k, it), "score": float(correct_fn(k, it))}
            for d, its in form.items() for k, it in enumerate(its)]


# ---------------------------------------------------------------- 응답 형식

def test_answer_format_roundtrip():
    mcq = next(it for it in ITEMS if it.format is ItemFormat.MCQ)
    bw = next(it for it in ITEMS if it.format is ItemFormat.BEST_WORST)
    assert ex.format_answer(2) == "2" and ex.parse_answer(mcq, "2") == 2
    assert ex.format_answer(1, 3, best_worst=True) == "1,3" and ex.parse_answer(bw, "1,3") == [1, 3]
    assert ex.format_answer(1, None, best_worst=True) == "1," and not ex.is_complete(bw, "1,")
    assert ex.format_answer(None, None, best_worst=True) is None
    right = ",".join(map(str, bw.answer))
    assert ex.score_item(bw, right) == (True, 1.0)
    assert ex.score_item(bw, f"{bw.answer[0]},") == (False, 0.0)  # 최선만 맞아도 오답
    assert ex.score_item(mcq, str(mcq.answer)) == (True, 1.0) and ex.score_item(mcq, None) == (False, 0.0)


def test_crisis_items_timed_one_by_one():
    assert ex.item_timed(Domain.CRI) and not ex.item_timed(Domain.UND)
    assert ex.domain_time_limit(Domain.CRI, Mode.FULL) == 0
    form = build_form(ITEMS, 1, Mode.FULL)
    exam = ex.new_exam(form, Mode.FULL)
    item = form[Domain.CRI][0]
    ex.start_item(exam, item, now=1000.0)
    assert exam["deadline"] == 1000.0 + CRISIS_SEC[item.difficulty]
    ex.start_item(exam, item, now=1010.0)  # 새로고침해도 마감이 늘어나지 않는다
    assert exam["deadline"] == 1000.0 + CRISIS_SEC[item.difficulty]
    assert ex.is_expired(exam, now=1000.0 + CRISIS_SEC[item.difficulty])


def test_round_flow_and_raw():
    form = build_form(ITEMS, 3, Mode.QUICK)
    exam = ex.new_exam(form, Mode.QUICK)
    for d, its in form.items():
        for it in its:
            exam["answers"][it.id] = str(it.answer) if it.format is ItemFormat.MCQ else ",".join(map(str, it.answer))
        done = ex.finish_domain(exam, ex.domain_rows(exam, BY_ID, d))
    assert done and all(v == len(form[Domain(k)]) for k, v in exam["raw"].items())


# ---------------------------------------------------------------- 심층검사

def test_deep_exam_picks_unseen_adaptive_items():
    form = build_form(ITEMS, 5, Mode.FULL)
    rows = rows_for(form, lambda k, it: k % 2 == 0)
    seen = {it.id for its in form.values() for it in its}
    exam = ex.new_deep_exam(rows, seen, Mode.FULL)
    ex.start_domain(exam, Mode.FULL)
    picked = []
    rng = random.Random(0)
    while (iid := ex.deep_next(exam, BY_ID, seed=9)) is not None:
        picked.append(iid)
        it = BY_ID[iid]
        ok = rng.random() < 0.5
        exam["answers"][iid] = (str(it.answer) if it.format is ItemFormat.MCQ else ",".join(map(str, it.answer))) if ok else None
    assert 1 <= len(picked) <= DEEP_MAX_ITEMS
    assert not set(picked) & seen
    assert all(BY_ID[i].domain is Domain(exam["domains"][0]) for i in picked)


# ---------------------------------------------------------------- 채점

def test_guess_parameters():
    mcq = next(it for it in ITEMS if it.format is ItemFormat.MCQ)
    bw = next(it for it in ITEMS if it.format is ItemFormat.BEST_WORST)
    assert sc.item_params(mcq)[2] == pytest.approx(0.2)
    assert sc.item_params(bw)[2] == pytest.approx(1 / 12)


def test_scores_monotonic_and_full_beats_quick():
    full, quick = build_form(ITEMS, 2, Mode.FULL), build_form(ITEMS, 2, Mode.QUICK)
    lo = sc.estimate(rows_for(full, lambda k, it: False), BY_ID)[1]
    mid = sc.estimate(rows_for(full, lambda k, it: it.difficulty <= 2), BY_ID)[1]
    hi = sc.estimate(rows_for(full, lambda k, it: True), BY_ID)[1]
    assert lo.index < mid.index < hi.index
    q = sc.estimate(rows_for(quick, lambda k, it: it.difficulty <= 2), BY_ID)[1]
    assert mid.se < q.se  # 문항이 많을수록 정밀


def test_levels():
    assert [sc.level(x) for x in (135, 120, 100, 80, 60)] == ["매우 우수", "우수", "보통", "개발 필요", "집중 개선 필요"]
    assert set(sc.TIPS) == set(Domain) and set(sc.ABILITY_TEXT) == set(Domain)


# ---------------------------------------------------------------- 자기평가

def test_self_scores_and_inflation_flag():
    self_items = load_self_items()
    honest = {it.id: (2 if it.check else 4) for it in self_items}
    s = ex.self_scores(self_items, honest)
    assert not s["_inflated"] and s["_checks"] == 0
    rev = next(it for it in self_items if it.reverse)
    assert it_score(s, rev.domain.value) < 4  # 역문항이 뒤집혀 평균이 4보다 낮아진다
    faking = {it.id: 5 for it in self_items}
    assert ex.self_scores(self_items, faking)["_inflated"]


def it_score(scores, domain):
    return scores[domain]


def test_self_comparison_verdicts():
    form = build_form(ITEMS, 4, Mode.FULL)
    final = rp.report(rows_for(form, lambda k, it: it.difficulty <= 1), BY_ID, sc.Norm())
    over = rp.self_comparison({d.value: 5.0 for d in Domain} | {"_inflated": False}, final)
    assert over[0].label == "종합" and over[0].verdict == "과대평가"
    assert "낮게" in rp.self_summary(over, inflated=False)
    match = {d.value: 3.6 for d in Domain}
    calm = rp.self_comparison(match, rp.report(rows_for(form, lambda k, it: it.difficulty <= 2), BY_ID, sc.Norm()))
    assert all(g.verdict in ("비슷함", "과소평가", "과대평가") for g in calm)
    assert rp.self_comparison({}, final) == []


def test_level_guide_covers_range():
    lows = [a for a, *_ in rp.LEVEL_GUIDE]
    assert lows == sorted(lows, reverse=True) and rp.LEVEL_GUIDE[-1][0] == 40
    assert all(len(g) == 5 for g in rp.LEVEL_GUIDE)


# ---------------------------------------------------------------- 봇 시뮬레이션 규준

@pytest.mark.parametrize("mode", ["quick", "full"])
def test_sim_norm_centered_and_monotonic(mode):
    import numpy as np
    sim = sc.load_sim(mode)
    assert sim is not None and sim.n >= 10000
    norm = sc.Norm(sim=sim)
    assert norm.simulated
    for stage in ("1", "1-2", "1-3", "1-3+deep"):
        idx = [sc.to_index(norm.z(t, None, stage)) for t in np.linspace(-3, 3, 61)]
        assert all(b >= a for a, b in zip(idx, idx[1:]))
        median = float(np.median(sim.total[stage]))
        assert sc.to_index(norm.z(median, None, stage)) == pytest.approx(100, abs=1)
        for d in Domain:
            m, _ = sim.domain[stage][d.value]
            assert sc.to_index(norm.z(m, d, stage)) == pytest.approx(100, abs=0.1)


def test_empirical_norm_overrides_sim():
    import numpy as np
    norm = sc.build_norm([{"total": t} for t in np.linspace(-1, 1, sc.MIN_NORM_N)], sim=sc.load_sim("quick"))
    fewer = sc.build_norm([{"total": t} for t in np.linspace(-1, 1, sc.MIN_NORM_N - 1)], sim=sc.load_sim("quick"))
    assert not fewer.empirical  # 기준보다 적으면 아직 시뮬레이션 규준
    assert norm.empirical and not norm.simulated
    assert norm.z(norm.mean, None, "1") == pytest.approx(0)


def test_stage_names_and_scale_range():
    assert [rp.stage(n) for n in (1, 2, 3)] == ["1", "1-2", "1-3"] and rp.stage(3, deep=True) == "1-3+deep"
    norm = sc.Norm(sim=sc.load_sim("full"))
    for theta in (-2.5, -0.5, 0, 1.2, 2.8):
        s = rp.scale(theta, 0.3, norm, stage="1-2")
        assert 40 <= s.lo <= s.index <= s.hi <= 160


def test_crisis_reading_then_decision():
    """위기 대처: 상황 읽기는 시간 제한 없음, 보기를 연 뒤부터 판단 시간."""
    items = {it.id: it for it in load_items()}
    item = next(it for it in items.values() if it.domain is Domain.CRI)
    exam = {"deadline": 999.0, "entered": None, "ms": {}}
    assert ex.reading(exam, item)
    ex.start_reading(exam, item, now=100.0)
    assert exam["deadline"] is None and not ex.is_expired(exam, now=10_000.0)  # 오래 읽어도 넘어가지 않음
    ex.finish_reading(exam, item, now=160.0)
    assert exam["read_ms"][item.id] == 60_000
    assert not ex.reading(exam, item)
    assert exam["deadline"] == 160.0 + CRISIS_SEC[item.difficulty]
    ex.start_reading(exam, item, now=170.0)  # 새로고침: 이미 보기를 열었으면 읽기 단계로 돌아가지 않음
    assert exam["deadline"] == 160.0 + CRISIS_SEC[item.difficulty]


def test_best_worst_partial_credit():
    items = {it.id: it for it in load_items()}
    it = next(i for i in items.values() if i.format is ItemFormat.BEST_WORST)
    b, w = it.answer
    other = next(k for k in range(4) if k not in (b, w))
    assert ex.score_item(it, f"{b},{w}") == (True, 1.0)
    assert ex.score_item(it, f"{b},{other}") == (False, 0.5)
    assert ex.score_item(it, f"{other},{w}") == (False, 0.0)
    # 최선만 맞히면 다 틀린 것보다 높고 다 맞힌 것보다 낮게 추정
    rows = lambda s: [{"item_id": it.id, "domain": it.domain.value, "correct": s == 1, "score": s}] * 6  # noqa: E731
    th = [sc.estimate(rows(s), items)[1].theta for s in (0.0, 0.5, 1.0)]
    assert th[0] < th[1] < th[2]
    # 둘 다 맞힐 확률은 예전 3모수와 같게 (θ = 0)
    assert abs(float(sc.p_correct(it, 0.0)) - it.expected_p) < 1e-6
