import random

import streamlit as st

from core import db
from core.components import client_id
from core.runtime import APP_VERSION, get_engine, get_final_items, get_self_items
from core.schema import BLUEPRINT, MODE_LABELS, Mode


def fmt_time(sec: int) -> str:
    if not sec:
        return "문항마다 25~35초"
    return f"{sec // 60}분" if sec % 60 == 0 else f"{sec // 60}분 {sec % 60}초" if sec > 60 else f"{sec}초"


st.title("EQ 감성지수 테스트")
st.caption(f"감정을 알아차리고, 이해하고, 활용하고, 다루는 힘을 {len(BLUEPRINT)}개 영역에서 측정하는 온라인 정서 역량 테스트")

mode = st.segmented_control("검사 방식", options=list(Mode), format_func=MODE_LABELS.get, default=Mode.FULL,
                            key="mode_choice")
mode = mode or Mode.FULL

with st.container(border=True):
    if mode is Mode.QUICK:
        st.markdown("**빠른 검사** · 약 20분 · 종합 EQ 중심 (영역 점수는 참고용)")
    else:
        st.markdown("**정밀 검사** · 약 40분 · 영역별 강점·약점과 자기평가 비교")
    st.table({
        "영역": [spec.label for spec in BLUEPRINT.values()],
        "문항": [f"{len(spec.form_for(mode))}문항" for spec in BLUEPRINT.values()],
        "제한시간": [fmt_time(spec.time_for(mode)) for spec in BLUEPRINT.values()],
    })
    st.caption(f"시작 전에 '나는 어떤 사람인지' 묻는 자기평가 {len(get_self_items())}문항(약 4분), "
               f"1차 끝에 솔직성을 확인하는 마지막 질문 {len(get_final_items())}문항(약 1분)이 있습니다. "
               "문제는 모두 정답이 있는 상황 판단 문제이고, 어려운 문제는 가장 맞는 보기와 가장 거리가 먼 보기를 함께 고릅니다. "
               "점수와 함께, 무엇을 골랐는지로 나의 정서 유형(세 가지 축 + 조합 이름)도 알려 드립니다.")

st.warning("본 결과는 온라인 정서 역량 테스트의 결과이며, 표준화된 전문 심리검사를 대체하지 않습니다.",
           icon=":material/info:")

with st.container(border=True):
    st.markdown("**응답 데이터 활용 안내**")
    st.markdown(
        "- 이름·연락처 등 개인을 식별할 수 있는 정보는 수집하지 않습니다.\n"
        "- 문항별 응답과 응답 시간은 익명으로 저장되어 문항 품질 개선과 점수 기준(규준) 계산에만 사용됩니다.\n"
        "- 동의하지 않으면 검사를 진행할 수 없습니다."
    )
    agreed = st.checkbox("위 내용에 동의합니다", value=False, key="consent")

cid = client_id(st.session_state.client_id)
if cid:
    st.session_state.client_id = cid  # 같은 브라우저 재응시를 규준에서 빼기 위한 익명 ID

if st.button("검사 시작", type="primary", disabled=not agreed, icon=":material/play_arrow:"):
    seed = random.randrange(2**31)
    st.session_state.mode = mode
    st.session_state.form_seed = seed
    st.session_state.exam = None
    st.session_state.session_id = db.start_session(get_engine(), st.session_state.client_id, mode.value, seed,
                                                   APP_VERSION)
    st.session_state.series_id = st.session_state.session_id
    st.session_state.round = 1
    st.session_state.phase = "test"
    st.switch_page("app_pages/test.py")

st.caption("1차 검증 뒤 원하면 겹치지 않는 새 문제로 2·3차 검증을, 3차 뒤에는 실력에 맞춘 심층검사를 이어 할 수 있습니다.")
