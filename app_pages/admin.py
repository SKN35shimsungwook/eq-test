import hmac
from collections import Counter

import streamlit as st

from core import db
from core.item_bank import validate_bank, validate_self_items
from core.runtime import get_engine, get_items, get_self_items
from core.schema import BLUEPRINT, FIXED_SLOTS, MIN_DOMAIN_POOL, MIN_FORMS_FIXED, MIN_FORMS_POOL, SLOTS


def _admin_password() -> str | None:
    try:
        return st.secrets.get("admin_password")
    except Exception:
        return None


expected = _admin_password()
if not expected:
    st.info("`.streamlit/secrets.toml`에 `admin_password`를 설정하면 분석 페이지가 열립니다.", icon=":material/lock:")
    st.stop()

if not st.session_state.get("admin_ok"):
    with st.form("admin_login"):
        pw = st.text_input("관리자 비밀번호", type="password")
        if st.form_submit_button("확인"):
            if hmac.compare_digest(pw, expected):
                st.session_state.admin_ok = True
                st.rerun()
            st.error("비밀번호가 틀렸습니다.")
    st.stop()

st.title("응답 분석")
storage = db.backend(get_engine())
st.caption(f"저장소: {storage}" + (" — 배포 환경이라면 재시작 시 데이터가 사라집니다. Secrets에 [connections.sql]을 설정하세요."
                                  if storage.startswith("SQLite") else ""))

st.subheader("문항은행 현황")
items = get_items()
by_slot = Counter(it.slot for it in items)
rows = []
for domain, spec in BLUEPRINT.items():
    slots = spec.pool
    need = sum(MIN_FORMS_FIXED if s in FIXED_SLOTS else MIN_FORMS_POOL for s in slots)
    have = sum(min(by_slot[s], MIN_FORMS_FIXED if s in FIXED_SLOTS else MIN_FORMS_POOL) for s in slots)
    rows.append({"영역": spec.label, "문항": sum(by_slot[s] for s in slots), "목표": MIN_DOMAIN_POOL,
                 "채운 슬롯 비율": have / need,
                 "빈 슬롯": sum(1 for s in slots if not by_slot[s])})
st.dataframe(rows, hide_index=True,
             column_config={"채운 슬롯 비율": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent")})
st.caption(f"슬롯 {len(SLOTS)}개 · 고정 구성 슬롯은 동형 {MIN_FORMS_FIXED}개, 나머지는 {MIN_FORMS_POOL}개가 목표입니다.")

errors = validate_bank(items) + validate_self_items(get_self_items())
if errors:
    with st.expander(f"문항 오류 {len(errors)}건", icon=":material/error:"):
        st.code("\n".join(errors), language=None)
else:
    st.success(f"문항 {len(items)}개 · 자기평가 {len(get_self_items())}개 형식 오류 없음", icon=":material/check:")
