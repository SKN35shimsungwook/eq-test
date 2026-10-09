import streamlit as st

from core.runtime import get_items, get_self_items
from core.schema import BLUEPRINT, MODE_LABELS, Mode

st.title("EQ 감성지수 테스트")
st.markdown(
    "감정을 알아차리고, 이해하고, 활용하고, 다루는 힘을 7개 영역에서 측정합니다. "
    "문제마다 정답이 있는 **상황 판단 검사**이고, 시작 전에 **나를 어떻게 보는지** 묻는 짧은 자기평가가 있습니다. "
    "점수는 IQ와 같은 척도(평균 100, 표준편차 15)의 **EQ**로 알려 드립니다."
)

st.subheader("측정 영역")
st.dataframe(
    {
        "영역": [spec.label for spec in BLUEPRINT.values()],
        "문제 유형": [" · ".join(spec.subtypes.values()) for spec in BLUEPRINT.values()],
    },
    hide_index=True,
)

st.subheader("검사 방식")
st.dataframe(
    {
        "방식": [MODE_LABELS[m] for m in Mode],
        "문항": [f"영역마다 {len(next(iter(BLUEPRINT.values())).form_for(m))}문항 · 모두 {sum(len(s.form_for(m)) for s in BLUEPRINT.values())}문항"
               for m in Mode],
    },
    hide_index=True,
)
st.caption("1차 검증 뒤 원하면 겹치지 않는 새 문제로 2·3차 검증을, 3차 뒤에는 실력에 맞춘 심층검사를 이어 할 수 있습니다.")

items, self_items = get_items(), get_self_items()
st.info(f"검사 화면은 준비 중입니다. 현재 문항 {len(items)}개 · 자기평가 {len(self_items)}개", icon=":material/construction:")

st.caption("본 검사는 온라인 정서 역량 테스트이며, 표준화된 전문 심리검사를 대체하지 않습니다.")
