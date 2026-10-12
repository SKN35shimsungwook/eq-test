import random
import time

import streamlit as st

from core import components as ui
from core import db
from core import exam as ex
from core import validity as vd
from core.item_bank import IMAGES_DIR, build_form
from core.runtime import get_engine, get_final_items, get_items, get_self_items, save_progress
from core.schema import (BLUEPRINT, DEEP_MAX_ITEMS, DEEP_MIN_ITEMS, DEEP_ROUND, MODE_LABELS, SELF_SCALE, Domain,
                         ItemFormat, round_label)

INTROS = {
    Domain.PER: "글로 묘사된 말투·행동이나 그림 속 표정을 보고 그 사람의 감정을 알아차리는 문제입니다.",
    Domain.UND: "상황에서 어떤 감정이 생기는지, 감정이 어떻게 섞이고 바뀌는지를 묻는 문제입니다.",
    Domain.USE: "일에 맞는 기분, 기분이 판단에 주는 영향, 감정을 행동의 힘으로 쓰는 방법을 묻는 문제입니다.",
    Domain.REG: "내 감정이 크게 흔들리는 상황에서 가장 효과적으로 다스리는 방법을 고르는 문제입니다.",
    Domain.REL: "다른 사람을 위로하고, 갈등을 풀고, 어려운 말을 전하고, 선을 지키는 방법을 고르는 문제입니다.",
    Domain.CON: "새 환경 적응, 배신, 소외, 가족·연애 갈등처럼 관계가 흔들리는 상황에서 알맞은 해결 방법을 고르는 문제입니다.",
    Domain.CRI: "갑작스러운 위기 상황에서 순간적으로 판단하는 문제입니다. **문항마다 짧은 제한시간**이 있고, "
                "시간이 끝나면 그때까지 고른 답으로 넘어갑니다. 앞 문제로 돌아갈 수 없습니다.",
    Domain.CTX: "말 속에 숨은 뜻, 그 자리의 분위기, 말하지 않은 규칙을 읽어 내는 문제입니다.",
}
BW_HELP = ("어려운 문제입니다. 질문에 **가장 맞는 보기**(✓)와 **가장 거리가 먼 보기**(✗)를 하나씩 골라 주세요. "
           "둘 다 맞아야 정답입니다.")

if st.session_state.phase != "test":
    st.info("시작 화면에서 안내에 동의한 뒤 검사를 시작해 주세요.", icon=":material/info:")
    st.page_link("app_pages/home.py", label="시작 화면으로", icon=":material/home:")
    st.stop()

ss = st.session_state
mode, seed = ss.mode, ss.form_seed
items = {it.id: it for it in get_items()}


def prior_rounds() -> list[dict]:
    """같은 묶음에서 끝낸 1~3차의 응답 행 (심층검사의 출발점)."""
    rows = []
    for r in db.series_sessions(get_engine(), ss.series_id):
        if r["completed_at"] and r["progress"] and r["round"] < DEEP_ROUND:
            prog = r["progress"]
            rows += [x for d in prog["domains"] for x in ex.domain_rows(prog, items, Domain(d))]
    return rows


if ss.get("exam") is None:
    seen = db.seen_items(get_engine(), ss.series_id) if ss.get("round", 1) > 1 else set()
    if ss.round == DEEP_ROUND:
        ss.exam = ex.new_deep_exam(prior_rounds(), seen, mode)
    else:
        ss.exam = ex.new_exam(build_form(list(items.values()), seed, mode, exclude=seen), mode)
    ss.exam["self_done"] = ss.round != 1  # 자기평가는 1차 검증 전에 한 번만
    ss.exam["final_done"] = ss.round != 1  # 마지막 질문도 1차 검증 끝에 한 번만
    save_progress()
exam = ss.exam

# ---------------------------------------------------------------- 자기평가 (1차 전 한 번)

if not exam.get("self_done"):
    self_items = get_self_items()
    order = random.Random(seed).sample(self_items, len(self_items))  # 영역이 드러나지 않게 섞는다
    st.caption(f"{MODE_LABELS[mode]} · 시작 전 자기평가")
    st.subheader("나는 어떤 사람일까요?")
    st.markdown("평소의 나에게 얼마나 해당하는지 골라 주세요. 정답은 없고, **EQ 점수에는 들어가지 않습니다.** "
                "결과 화면에서 '내가 보는 나'와 '실제 문제 풀이 결과'를 비교하는 데 씁니다.")
    with st.form("self-report"):
        picked = {}
        for k, it in enumerate(order, 1):
            picked[it.id] = st.radio(f"{k}. {it.text}", options=list(SELF_SCALE), format_func=SELF_SCALE.get,
                                     horizontal=True, index=None, key=f"sr-{it.id}")
        submitted = st.form_submit_button("다음: 검사 시작", type="primary", icon=":material/arrow_forward:")
    if submitted:
        missing = [k for k, it in enumerate(order, 1) if picked[it.id] is None]
        if missing:
            st.error(f"답하지 않은 문항이 있습니다: {', '.join(map(str, missing[:10]))}{' …' if len(missing) > 10 else ''}번")
        else:
            scores = ex.self_scores(self_items, picked)
            db.save_responses(get_engine(), ss.session_id, [
                {"item_id": it.id, "item_version": it.version, "domain": "sr", "answer": str(picked[it.id]),
                 "correct": False, "score": float(picked[it.id] if it.check else it.score(picked[it.id])),
                 "response_ms": None} for it in self_items])
            db.save_self_scores(get_engine(), ss.session_id, scores)
            exam["self_answers"] = picked  # 마지막 질문에서 같은 내용을 다시 물어 일관성을 본다
            exam["self_done"] = True
            save_progress()
            st.rerun()
    st.stop()

# ---------------------------------------------------------------- 마지막 질문 (1차 끝에 한 번)

if exam["d"] >= len(exam["domains"]):
    if exam.get("final_done", True):
        ss.phase = "result"
        st.switch_page("app_pages/result.py")
    final_items = get_final_items()
    order = random.Random(seed + 1).sample(final_items, len(final_items))
    st.caption(f"{MODE_LABELS[mode]} · 마지막 질문")
    st.subheader("마지막으로, 솔직하게 답해 주세요")
    st.markdown("평소의 나에게 얼마나 해당하는지 골라 주세요. 정답은 없고 **EQ 점수에는 들어가지 않습니다.** "
                "응답이 일관되고 솔직했는지 살펴 결과를 얼마나 믿고 읽을지 알려 드리는 데 씁니다.")
    with st.form("final-check"):
        picked = {}
        for k, it in enumerate(order, 1):
            picked[it.id] = st.radio(f"{k}. {it.text}", options=list(SELF_SCALE), format_func=SELF_SCALE.get,
                                     horizontal=True, index=None, key=f"fc-{it.id}")
        submitted = st.form_submit_button("결과 보기", type="primary", icon=":material/arrow_forward:")
    if submitted:
        missing = [k for k, it in enumerate(order, 1) if picked[it.id] is None]
        if missing:
            st.error(f"답하지 않은 문항이 있습니다: {', '.join(map(str, missing))}번")
        else:
            db.save_responses(get_engine(), ss.session_id, [
                {"item_id": it.id, "item_version": it.version, "domain": "fc", "answer": str(picked[it.id]),
                 "correct": False, "score": float(picked[it.id]), "response_ms": None} for it in final_items])
            current = (db.load_session(get_engine(), ss.session_id) or {}).get("self_scores") or {}
            extra = vd.final_scores(final_items, get_self_items(), picked, exam.get("self_answers") or {})
            db.save_self_scores(get_engine(), ss.session_id, {**current, **extra})
            exam["final_done"] = True
            save_progress()
            ss.phase = "result"
            st.switch_page("app_pages/result.py")
    st.stop()

deep = exam.get("kind") == "deep"
domain = ex.current_domain(exam)
spec = BLUEPRINT[domain]
ids = exam["items"][domain.value]
timed = ex.item_timed(domain)


def close_domain() -> None:
    """현재 영역을 채점·저장하고 다음 영역(또는 결과)으로 넘어간다."""
    if exam["stage"] == "items" and ids and exam["i"] < len(ids):
        ex.track_time(exam, ids[exam["i"]])
    rows = ex.domain_rows(exam, items, domain)
    db.save_responses(get_engine(), ss.session_id, rows)
    finished = ex.finish_domain(exam, rows)
    save_progress()
    if finished and not exam.get("final_done", True):
        st.rerun()  # 마지막 질문으로
    if finished:
        ss.phase = "result"
        st.switch_page("app_pages/result.py")
    st.rerun()


def advance() -> None:
    """현재 문항을 마치고 다음 문항으로. 더 낼 문항이 없으면 영역을 닫는다."""
    ex.track_time(exam, ids[exam["i"]])
    if deep:
        if ex.deep_next(exam, items, seed) is None:
            close_domain()
    elif exam["i"] >= len(ids) - 1:
        close_domain()
    exam["i"] += 1
    exam["entered"] = time.time()
    save_progress()
    st.rerun()


def go_to(i: int) -> None:
    ex.track_time(exam, ids[exam["i"]])
    exam["i"] = i
    save_progress()


# ---------------------------------------------------------------- 영역 안내

step = f"{exam['d'] + 1}/{len(exam['domains'])}"
if exam["stage"] == "intro":
    st.caption(f"{MODE_LABELS[mode]} · {round_label(ss.round)} · 영역 {step}")
    st.subheader(spec.label)
    limit = ex.domain_time_limit(domain, mode, deep)
    with st.container(border=True):
        st.markdown(INTROS[domain])
        if deep:
            facts = ["지금까지의 결과에 맞춰 **한 문제씩** 고릅니다",
                     f"정확도가 충분해지면 다음 영역으로 (**{DEEP_MIN_ITEMS}~{DEEP_MAX_ITEMS}문항**)",
                     "답을 확인하면 앞 문제로 돌아갈 수 없습니다"]
        else:
            facts = [f"**{len(ids)}문항**", "쉬운 문제부터 어려운 문제 순서입니다"]
        if limit:
            facts.append(f"제한시간 **{limit // 60}분{f' {limit % 60}초' if limit % 60 else ''}**")
        elif timed:
            facts.append("문항마다 **25~35초**")
        st.markdown(" · ".join(facts))
        st.caption("어려운 문제는 가장 맞는 보기와 가장 거리가 먼 보기를 함께 고르는 방식입니다.")
    if st.button("시작", type="primary", icon=":material/play_arrow:"):
        ex.start_domain(exam, mode)
        if deep and ex.deep_next(exam, items, seed) is None:
            close_domain()
        save_progress()
        st.rerun()
    st.stop()

# ---------------------------------------------------------------- 문항

if exam["i"] >= len(ids):
    close_domain()
item = items[ids[exam["i"]]]
if timed:
    ex.start_item(exam, item)
    save_progress()

if ex.is_expired(exam):
    if timed:
        st.toast("시간이 끝나 다음 문항으로 넘어갑니다.", icon=":material/timer_off:")
        advance()
    st.toast(f"{spec.label} 영역 시간이 끝났습니다.", icon=":material/timer_off:")
    close_domain()

with st.container(horizontal=True, vertical_alignment="center"):
    progress = f"{exam['i'] + 1}번째 문항" if deep else f"{exam['i'] + 1} / {len(ids)}"
    st.markdown(f"**{spec.label}** · {progress}")
    if exam["deadline"]:
        remaining = int((exam["deadline"] - time.time()) * 1000)
        total = (item.time_limit if timed else ex.domain_time_limit(domain, mode, deep)) * 1000
        token = f"{ss.round}-{exam['d']}" + (f"-{item.id}" if timed else "")
        expired, blurs = ui.countdown(token, remaining, total, exam["blurs"], key="countdown",
                                      low_ms=10000 if timed else 30000)
        exam["blurs"] = blurs or exam["blurs"]
        if expired:
            st.rerun()

st.markdown(f"#### {item.prompt}")
if item.image and (IMAGES_DIR / item.image).exists():
    st.image(str(IMAGES_DIR / item.image), width=360)

prev = exam["answers"].get(item.id)
key = f"{ss.round}-{item.id}"
if item.format is ItemFormat.MCQ:
    sel = ui.choice_list(item.choices, int(prev) if prev else None, key=f"choice-{key}")
    new = ex.format_answer(sel)
else:
    st.caption(BW_HELP)
    b0, _, w0 = (prev or ",").partition(",")
    best, worst = ui.best_worst(item.choices, int(b0) if b0 else None, int(w0) if w0 else None, key=f"bw-{key}")
    new = ex.format_answer(best, worst, best_worst=True)
if new != prev:
    if new is None:
        exam["answers"].pop(item.id, None)
    else:
        exam["answers"][item.id] = new
    save_progress()

complete = ex.is_complete(item, exam["answers"].get(item.id))
st.space("small")
if deep or timed:
    # 심층검사·위기 대처: 한 문제씩 확정하고 앞으로만 간다
    if st.button("확인", type="primary", icon=":material/check:", disabled=not complete and not timed):
        advance()
    if timed and not complete:
        st.caption("시간 안에 고르지 못하면 그때까지의 답으로 넘어갑니다.")
else:
    answered = [i for i, x in enumerate(ids) if ex.is_complete(items[x], exam["answers"].get(x))]
    last = exam["i"] == len(ids) - 1
    with st.container(horizontal=True):
        st.button("이전", icon=":material/arrow_back:", disabled=exam["i"] == 0, on_click=go_to, args=(exam["i"] - 1,))
        if not last:
            st.button("다음", type="primary", icon=":material/arrow_forward:", on_click=go_to, args=(exam["i"] + 1,))
        elif st.button("영역 제출", type="primary", icon=":material/check:"):
            ss.confirm_submit = True

    jump = st.pills(
        "문항 이동", options=list(range(len(ids))), selection_mode="single", default=exam["i"],
        format_func=lambda k: f"{k + 1}{' ✓' if k in answered else ''}",
        key=f"jump-{ss.round}-{exam['d']}-{exam['i']}",
    )
    if jump is not None and jump != exam["i"]:
        go_to(jump)
        st.rerun()

    if ss.get("confirm_submit"):
        missing = len(ids) - len(answered)

        @st.dialog("영역을 제출할까요?")
        def confirm():
            if missing:
                st.warning(f"답을 끝까지 고르지 않은 문항이 {missing}개 있습니다. 제출하면 이 영역으로 다시 돌아올 수 없습니다.")
            else:
                st.write("제출하면 이 영역으로 다시 돌아올 수 없습니다.")
            with st.container(horizontal=True):
                if st.button("계속 풀기"):
                    ss.confirm_submit = False
                    st.rerun()
                if st.button("제출", type="primary"):
                    ss.confirm_submit = False
                    close_domain()

        confirm()
