from collections import Counter
from dataclasses import replace

import pytest
import sqlalchemy as sa

from core import db
from core.item_bank import (balance_answer_positions, build_form, load_items, load_self_items, validate_bank,
                            validate_blueprint, validate_self_items)
from core.schema import (BLUEPRINT, FIXED_SLOTS, IMAGE_SUBTYPES, MIN_DOMAIN_POOL, MIN_FORMS_FIXED, MIN_FORMS_POOL,
                         SLOTS, Domain, Item, ItemFormat, Mode, SelfItem)

ITEMS = load_items()


def make_item(slot: str, letter: str = "a", **kw) -> Item:
    level = SLOTS[slot].difficulty
    d = {"id": f"{slot}{letter}", "slot": slot, "prompt": f"{slot}{letter} 상황",
         "choices": [f"{slot}{letter} 보기{i}" for i in range(4)],
         "answer": 0 if level <= 2 else [0, 3], "explanation": "해설", "rationale": "근거"}
    if SLOTS[slot].subtype in IMAGE_SUBTYPES:
        d["image"] = "x.png"
    d.update(kw)
    return Item.from_dict(d)


# ---------------------------------------------------------------- 구성표

def test_blueprint_rules():
    assert validate_blueprint() == []


def test_blueprint_shape():
    assert len(BLUEPRINT) == 7
    for spec in BLUEPRINT.values():
        assert len(spec.pool) == 16
        assert len(spec.full) == 8 and len(spec.quick) == 4
    # 고정 구성 슬롯 8 × 3 + 나머지 8 × 2 = 영역당 40
    per_domain = 8 * MIN_FORMS_FIXED + 8 * MIN_FORMS_POOL
    assert per_domain == MIN_DOMAIN_POOL
    assert len(FIXED_SLOTS) == 7 * 8


# ---------------------------------------------------------------- 문항

def test_sample_bank_valid():
    assert validate_bank(ITEMS) == []
    assert validate_self_items(load_self_items()) == []


def test_from_dict_fills_slot_defaults():
    it = make_item("cri-public-3")
    assert it.domain is Domain.CRI and it.difficulty == 3
    assert it.format is ItemFormat.BEST_WORST
    assert it.time_limit == 35 and it.expected_p == 0.45


def test_validate_catches_errors():
    assert any("형식" in e for e in make_item("und-cause-3", format="mcq", answer=0).validate())
    assert any("[최선, 최악]" in e for e in make_item("und-cause-3", answer=[1, 1]).validate())
    assert any("rationale" in e for e in make_item("und-cause-1", rationale="").validate())
    assert any("image" in e for e in make_item("per-face-2", image="").validate())
    assert any("중복된 보기" in e for e in make_item("und-cause-1", choices=["a", "a", "b", "c"]).validate())


def test_scoring_best_worst():
    it = make_item("reg-stress-4")
    assert it.is_correct([0, 3])
    assert not it.is_correct([0, 2]) and not it.is_correct([3, 0]) and not it.is_correct(None)


def test_duplicate_prompt_and_answer_detected():
    a = make_item("und-cause-1", "a")
    b = make_item("und-cause-1", "b", prompt=a.prompt)
    c = make_item("und-change-2", "a", choices=[a.choices[0], "x", "y", "z"])
    errors = validate_bank([a, b, c])
    assert any("문제 문장" in e for e in errors)
    assert any("정답 보기" in e for e in errors)


def test_strict_reports_missing_forms():
    errors = validate_bank(ITEMS, strict=True)
    assert any("필요 3개" in e for e in errors) and any("필요 2개" in e for e in errors)
    assert any("이미지 대기" in e for e in errors)


def test_balance_keeps_best_and_worst():
    group = [make_item("rel-boundary-4", ch) for ch in "abcd"]
    out = balance_answer_positions(group)
    assert sorted(it.answer[0] for it in out) == [0, 1, 2, 3]
    for before, after in zip(sorted(group, key=lambda x: x.id), sorted(out, key=lambda x: x.id)):
        assert after.choices[after.answer[0]] == before.choices[before.answer[0]]
        assert after.choices[after.answer[1]] == before.choices[before.answer[1]]
        assert sorted(after.choices) == sorted(before.choices)


# ---------------------------------------------------------------- 검사지

def full_bank() -> list[Item]:
    items = []
    for sid in SLOTS:
        if SLOTS[sid].subtype in IMAGE_SUBTYPES:
            continue  # 이미지 대기 상태를 흉내
        n = MIN_FORMS_FIXED if sid in FIXED_SLOTS else MIN_FORMS_POOL
        if sid.startswith("per-") and SLOTS[sid].difficulty > 1:
            n = 5  # 이미지 대기 중에는 글 유형 동형을 늘려 대체분을 채운다
        items += [make_item(sid, "abcde"[k]) for k in range(n)]
    return items


def test_substitute_capacity_check():
    bank = full_bank()
    assert not [e for e in validate_bank(bank, strict=True) if "이미지 대체" in e]
    thin = [it for it in bank if not (it.slot == "per-message-3" and it.id[-1] in "de")
            and not (it.slot == "per-behavior-3" and it.id[-1] in "de")]
    assert any("난이도 3 글 문항 6개 / 이미지 대체 포함 9개" in e for e in validate_bank(thin, strict=True))


@pytest.mark.parametrize("mode", list(Mode))
def test_rounds_do_not_overlap(mode):
    bank, seen = full_bank(), set()
    for r in range(3):
        form = build_form(bank, seed=100 + r, mode=mode, exclude=seen)
        ids = [it.id for items in form.values() for it in items]
        assert len(ids) == len(set(ids)) == 7 * (8 if mode is Mode.FULL else 4)
        assert not seen & set(ids)
        seen |= set(ids)


def test_image_slots_substituted_with_same_level_text():
    form = build_form(full_bank(), seed=1, mode=Mode.FULL)
    per = form[Domain.PER]
    want = [SLOTS[s].difficulty for s in BLUEPRINT[Domain.PER].full]
    assert [it.difficulty for it in per] == want
    assert not {it.subtype for it in per} & IMAGE_SUBTYPES


def test_form_is_deterministic():
    bank = full_bank()
    a = build_form(bank, seed=7, mode=Mode.QUICK)
    b = build_form(bank, seed=7, mode=Mode.QUICK)
    assert {d: [i.id for i in v] for d, v in a.items()} == {d: [i.id for i in v] for d, v in b.items()}


# ---------------------------------------------------------------- 자기보고

def test_self_item_reverse_and_checks():
    rev = SelfItem.from_dict({"id": "sr-rel-1", "domain": "rel", "text": "t", "reverse": True})
    assert rev.score(5) == 1 and rev.score(2) == 4
    assert SelfItem.from_dict({"id": "sr-check-9", "text": "t", "check": True}).validate() == []
    assert SelfItem.from_dict({"id": "sr-check-9", "text": "t", "check": True, "domain": "rel"}).validate()
    # 자기평가는 영역당 4문항(역문항 1개 이상) + 점검 4문항으로 완성됨
    assert validate_self_items(load_self_items(), strict=True) == []
    thin = [it for it in load_self_items() if it.id != "sr-ctx-3"]
    assert any("sr-ctx" in e for e in validate_self_items(thin, strict=True))


# ---------------------------------------------------------------- DB

@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite://")
    db.init_db(eng)
    return eng


def test_session_flow(engine):
    sid = db.start_session(engine, "c1", "full", 1, "test")
    db.save_self_scores(engine, sid, {"reg": 3.5, "check_flag": False})
    db.save_responses(engine, sid, [
        {"item_id": "sr-reg-1", "item_version": 1, "domain": "sr", "answer": "4", "correct": False, "score": 4},
        {"item_id": "und-cause-1a", "item_version": 1, "domain": "und", "answer": "0", "correct": True, "score": 1},
    ])
    # 자기보고는 '본 문항'에서 빠져 뒤 차수 출제에 영향을 주지 않는다
    assert db.seen_items(engine, sid) == {"und-cause-1a"}
    db.complete_session(engine, sid, {"und": 1}, {"und": 104.0}, eq_index=103.0, percentile=58.0,
                        thetas={"total": 0.2})
    row = db.load_session(engine, sid)
    assert row["eq_index"] == 103.0 and row["self_scores"]["reg"] == 3.5
    # 같은 브라우저 재응시는 규준 제외 표시
    sid2 = db.start_session(engine, "c1", "full", 2, "test")
    assert db.load_session(engine, sid2)["is_first_attempt"] is False


def test_save_responses_idempotent(engine):
    sid = db.start_session(engine, "c2", "quick", 1, "test")
    row = {"item_id": "ctx-sarcasm-1a", "item_version": 1, "domain": "ctx", "answer": "0", "correct": True, "score": 1}
    db.save_responses(engine, sid, [row])
    db.save_responses(engine, sid, [row])
    with engine.connect() as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(db.responses)).scalar_one()
    assert n == 1


@pytest.mark.parametrize("mode", list(Mode))
def test_real_bank_three_rounds_never_overlap(mode):
    """실제 문항은행으로 1·2·3차를 겹치지 않게 낼 수 있다 (이미지 대기 중 대체 출제 포함)."""
    n = 7 * (8 if mode is Mode.FULL else 4)
    for seed in range(200):
        seen = set()
        for r in range(3):
            ids = [it.id for its in build_form(ITEMS, seed * 7 + r, mode, exclude=seen).values() for it in its]
            assert len(ids) == len(set(ids)) == n and not seen & set(ids), (seed, r)
            seen |= set(ids)
