import random

from core import style as sty
from core.item_bank import load_items
from core.schema import BLUEPRINT, READING_DOMAINS, STYLES, Domain, ItemFormat

ITEMS = {it.id: it for it in load_items()}


def key_of(it) -> int:
    return it.answer[0] if it.format is ItemFormat.BEST_WORST else it.answer


def row(it, best: int) -> dict:
    ans = f"{best},{(best + 1) % 4}" if it.format is ItemFormat.BEST_WORST else str(best)
    return {"item_id": it.id, "answer": ans}


def styled(domain: Domain) -> list:
    return sorted((it for it in ITEMS.values() if it.domain is domain and it.styles), key=lambda it: it.id)


def miss_toward(domain: Domain, code: str, n: int) -> list[dict]:
    """정답이 아닌 code 유형 보기를 n번 고른 응답 (code가 오답 보기로 있는 문항만)."""
    rows = []
    for it in styled(domain):
        k = key_of(it)
        idx = [i for i, s in enumerate(it.styles) if s == code and i != k]
        if idx:
            rows.append(row(it, idx[0]))
        if len(rows) == n:
            break
    return rows


def test_every_styled_item_has_valid_codes():
    for it in ITEMS.values():
        if it.styles:
            assert len(it.styles) == len(it.choices)
            assert set(it.styles) <= set(STYLES[it.domain])
            if it.domain in READING_DOMAINS:
                assert it.styles[key_of(it)] == "acc"


def test_all_correct_is_situational():
    rows = [row(it, key_of(it)) for d in BLUEPRINT for it in styled(d)[:8]]
    p = sty.profile(rows, ITEMS)
    assert p.name == "상황맞춤형"
    assert all(v == 0 for v in p.axes.values())
    assert all(d.matched for d in p.domains)
    assert {d.name for d in p.domains} == {"상황맞춤형", "정확형"}


def test_consistent_miss_gives_lean():
    p = sty.profile(miss_toward(Domain.CON, "guard", 10), ITEMS)
    con = p.domains[0]
    assert con.code == "guard" and con.name == STYLES[Domain.CON]["guard"].name
    assert "기웁니다" in con.desc


def test_reading_lean():
    p = sty.profile(miss_toward(Domain.CTX, "sus", 10), ITEMS)
    assert p.domains[0].code == "sus"
    assert "숨은 뜻" in p.reading
    assert p.name == "판단 보류"  # 행동 영역 응답이 없으면 종합 이름은 보류


def test_axis_lean_named():
    """행동 영역에서 놓칠 때마다 감정 쪽(A+) 보기를 고르면 A축이 뚜렷하고 이름 방향이 맞는다."""
    rows = []
    for d in BLUEPRINT:
        if d in READING_DOMAINS:
            continue
        for it in styled(d)[:12]:
            k = key_of(it)
            cands = [i for i in range(4) if i != k]
            rows.append(row(it, max(cands, key=lambda i: (STYLES[d][it.styles[i]].axes[0], -i))))
    p = sty.profile(rows, ITEMS)
    assert p.axes["A"] > 0 and abs(p.axes_z["A"]) >= sty.AXIS_Z
    assert "마음" in p.name


def test_few_misses_no_lean():
    rows = [row(it, key_of(it)) for it in styled(Domain.REL)[:3]] + miss_toward(Domain.REL, "respect", 2)
    rel = sty.profile(rows, ITEMS).domains[0]
    assert rel.code is None


def test_too_few_answers_withheld():
    rel = sty.profile(miss_toward(Domain.REL, "respect", 2), ITEMS).domains[0]
    assert rel.name == "판단 보류"


def test_order_independent():
    rng = random.Random(3)
    rows = []
    for d in BLUEPRINT:
        for it in styled(d)[:10]:
            rows.append(row(it, rng.randrange(4)))
    a = sty.profile(rows, ITEMS)
    for _ in range(5):
        rng.shuffle(rows)
        b = sty.profile(rows, ITEMS)
        assert (a.name, a.axes, [d.name for d in a.domains]) == (b.name, b.axes, [d.name for d in b.domains])


def test_unanswered_ignored():
    assert sty.picks([{"item_id": next(iter(ITEMS)), "answer": ""}], ITEMS) == []
