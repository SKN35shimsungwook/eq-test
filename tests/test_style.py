from core import style as sty
from core.item_bank import load_items
from core.schema import STYLES, Domain, ItemFormat

ITEMS = {it.id: it for it in load_items()}


def rows_choosing(domain: Domain, code: str, n: int) -> list[dict]:
    """해당 영역에서 code 유형 보기를 n번 고른 응답 행."""
    rows = []
    for it in ITEMS.values():
        if it.domain is not domain or not it.styles or code not in it.styles:
            continue
        i = it.styles.index(code)
        if it.format is ItemFormat.BEST_WORST:
            ans = f"{i},{(i + 1) % 4}"
        else:
            ans = str(i)
        rows.append({"item_id": it.id, "answer": ans})
        if len(rows) == n:
            break
    return rows


def test_every_styled_item_has_valid_codes():
    for it in ITEMS.values():
        if it.styles:
            assert len(it.styles) == len(it.choices)
            assert set(it.styles) <= set(STYLES[it.domain])


def test_dominant_style_named():
    p = sty.profile(rows_choosing(Domain.REL, "empath", 6), ITEMS)
    rel = next(d for d in p.domains if d.domain is Domain.REL)
    assert rel.code == "empath" and rel.name == STYLES[Domain.REL]["empath"].name
    assert p.axes["A"] > 0 and p.axes["B"] > 0
    assert "마음을 먼저 살피는" in p.name or "먼저 다가가는" in p.name


def test_mixed_choices_are_flexible():
    rows = []
    for c in STYLES[Domain.CON]:
        rows += rows_choosing(Domain.CON, c, 2)
    ds = sty.profile(rows, ITEMS).domains[0]
    assert ds.flexible and ds.name == "유연형"


def test_reading_domain_accuracy():
    p = sty.profile(rows_choosing(Domain.CTX, "acc", 6), ITEMS)
    assert p.domains[0].code == "acc"
    assert "정확" in p.reading
    p = sty.profile(rows_choosing(Domain.CTX, "sus", 6), ITEMS)
    assert p.domains[0].code == "sus"
    assert "숨은 뜻" in p.reading
    assert p.name == "판단 보류"  # 행동 영역 선택이 없으면 종합 이름은 보류


def test_too_few_picks_withheld():
    ds = sty.profile(rows_choosing(Domain.REG, "pause", 2), ITEMS).domains[0]
    assert ds.name == "판단 보류"


def test_unanswered_ignored():
    assert sty.picks([{"item_id": next(iter(ITEMS)), "answer": ""}], ITEMS) == []
