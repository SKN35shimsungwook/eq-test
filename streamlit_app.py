import streamlit as st

from core.runtime import init_state

st.set_page_config(page_title="EQ 감성지수 테스트", page_icon=":material/favorite:", layout="centered")

init_state()
if st.session_state.session_id and st.query_params.get("s") != st.session_state.session_id:
    st.query_params["s"] = st.session_state.session_id  # 새로고침해도 이어 풀 수 있게

page = st.navigation(
    {
        "": [
            st.Page("app_pages/home.py", title="시작", icon=":material/home:", default=True),
            st.Page("app_pages/test.py", title="검사", icon=":material/edit_note:"),
            st.Page("app_pages/result.py", title="결과", icon=":material/insights:"),
        ],
        "관리": [
            st.Page("app_pages/admin.py", title="분석", icon=":material/admin_panel_settings:"),
        ],
    },
    position="top",
)

page.run()
