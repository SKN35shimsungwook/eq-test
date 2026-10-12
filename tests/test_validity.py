from core import validity as vd
from core.item_bank import load_final_items, load_items, load_self_items, validate_final_items
from core.schema import ItemFormat, SelfItem

ITEMS = {it.id: it for it in load_items()}
SELF = load_self_items()
FINAL = load_final_items()


def ability_rows(ms: int = 9000, position: int | None = None, n: int = 40) -> list[dict]:
    rows = []
    for k, it in enumerate(sorted(ITEMS.values(), key=lambda x: x.id)[:n]):
        best = position if position is not None else k % 4
        ans = f"{best},{(best + 1) % 4}" if it.format is ItemFormat.BEST_WORST else str(best)
        rows.append({"item_id": it.id, "answer": ans, "response_ms": ms})
    return rows


def honest_answers() -> tuple[dict, dict]:
    """성실한 응답: 영역 문항 4, 역문항 2, 점검·욕구 문항 2, 짝 문항은 같은 뜻으로."""
    self_ans = {it.id: 2 if it.check else (2 if it.reverse else 4) for it in SELF}
    final_ans = {it.id: 2 if it.kind == "desire" else (2 if it.reverse else 4) for it in FINAL}
    return self_ans, final_ans


def scores(self_ans, final_ans) -> dict:
    from core import exam as ex
    return {**ex.self_scores(SELF, self_ans), **vd.final_scores(FINAL, SELF, final_ans, self_ans)}


def test_final_items_valid():
    assert validate_final_items(FINAL, SELF) == []
    assert not any(it.id in ITEMS for it in FINAL)  # 문제 은행에 섞이지 않음


def test_final_item_rules():
    assert SelfItem(id="x", text="t", kind="repeat").validate()            # pair 없음
    assert SelfItem(id="x", text="t", kind="desire", reverse=True).validate()
    assert SelfItem(id="x", text="t", kind="repeat", pair="sr-reg-1").validate() == []


def test_honest_is_high():
    s = scores(*honest_answers())
    assert s["_desire"] == 0 and s["_incons"] == 0 and s["_pairs"] == 4
    v = vd.assess(s, ability_rows(), ITEMS)
    assert v.level == "높음" and v.reasons == []


def test_denial_flags():
    self_ans, final_ans = honest_answers()
    for it in SELF:
        if it.check:
            self_ans[it.id] = 5
    for it in FINAL:
        if it.kind == "desire":
            final_ans[it.id] = 4
    v = vd.assess(scores(self_ans, final_ans), ability_rows(), ITEMS)
    assert v.level == "낮음" and "8/8" in v.reasons[0]


def test_inconsistent_pairs_flag():
    self_ans, final_ans = honest_answers()
    for it in FINAL:
        if it.kind == "repeat":
            final_ans[it.id] = 5 if it.reverse else 1   # 시작과 정반대
    s = scores(self_ans, final_ans)
    assert s["_incons"] == 4
    assert vd.assess(s, ability_rows(), ITEMS).level == "낮음"


def test_straightline_self_report():
    self_ans = {it.id: 4 for it in SELF}
    final_ans = {it.id: 4 for it in FINAL}
    assert vd.assess(scores(self_ans, final_ans), ability_rows(), ITEMS).level == "낮음"


def test_fast_and_position_flags():
    s = scores(*honest_answers())
    assert any("빨리" in r for r in vd.assess(s, ability_rows(ms=1000), ITEMS).reasons)
    v = vd.assess(s, ability_rows(position=2), ITEMS)
    assert v.level == "낮음" and any("위치" in r for r in v.reasons)


def test_few_rows_skip_ability_signals():
    s = scores(*honest_answers())
    assert vd.assess(s, ability_rows(ms=500, n=5), ITEMS).level == "높음"


def test_without_final_answers_uses_start_only():
    """마지막 질문 전(또는 예전 세션)에는 욕구 8개 기준을 쓰지 않는다."""
    from core import exam as ex
    self_ans, _ = honest_answers()
    s = ex.self_scores(SELF, self_ans)
    assert vd.assess(s, ability_rows(), ITEMS).level == "높음"
    assert vd.assess(None, ability_rows(), ITEMS).level == "높음"
