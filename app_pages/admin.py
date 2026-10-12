import hmac
import json
import math
from collections import Counter

import altair as alt
import pandas as pd
import streamlit as st

from core import analysis as an
from core import db
from core.charts import PRIMARY
from core.item_bank import validate_bank, validate_self_items
from core.runtime import get_engine, get_items, get_self_items
from core.schema import (BLUEPRINT, DEEP_MAX_ITEMS, DEEP_MIN_ITEMS, DEEP_TARGET_SE, FIXED_SLOTS,
                         MIN_FORMS_FIXED, MIN_FORMS_POOL, MODE_LABELS, SLOTS, Mode)

st.set_page_config(layout="wide")  # 분석 표가 넓어 이 페이지만 넓게


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


@st.cache_data(ttl=120, show_spinner="응답 데이터를 불러오는 중…")
def load(include_sim: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    return an.load_frames(get_engine(), include_sim)


@st.cache_data(ttl=120, show_spinner="문항을 분석하는 중…")
def analyze(responses: pd.DataFrame, mode: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    items = {it.id: it for it in get_items()}
    r = responses if mode == "all" else responses[responses["mode"] == mode]
    return an.item_stats(r, items), an.domain_reliability(r, items), an.calibrate(r, items)


st.title("응답 분석")
storage = db.backend(get_engine())
st.caption(f"저장소: {storage}" + (" — 배포 환경이라면 재시작 시 데이터가 사라집니다. Secrets에 [connections.sql]을 설정하세요."
                                  if storage.startswith("SQLite") else ""))
with st.container(horizontal=True, vertical_alignment="bottom"):
    mode = st.segmented_control("검사 방식", ["all", Mode.QUICK.value, Mode.FULL.value], default="all",
                                format_func=lambda m: "전체" if m == "all" else MODE_LABELS[Mode(m)])
    include_sim = st.toggle("시뮬레이션 데이터 포함", value=False,
                            help="scripts/simulate.py로 만든 가상 응시 데이터 (규준 계산에는 항상 제외)")
    if st.button("새로고침", icon=":material/refresh:"):
        st.cache_data.clear()
mode = mode or "all"

sessions, responses = load(include_sim)


def bank_status() -> None:
    items = get_items()
    by_slot = Counter(it.slot for it in items)
    rows = []
    for spec in BLUEPRINT.values():
        need = sum(MIN_FORMS_FIXED if s in FIXED_SLOTS else MIN_FORMS_POOL for s in spec.pool)
        have = sum(min(by_slot[s], MIN_FORMS_FIXED if s in FIXED_SLOTS else MIN_FORMS_POOL) for s in spec.pool)
        rows.append({"영역": spec.label, "문항": sum(by_slot[s] for s in spec.pool), "목표": spec.min_pool,
                     "채운 슬롯 비율": have / need, "빈 슬롯": sum(1 for s in spec.pool if not by_slot[s])})
    st.dataframe(rows, hide_index=True, column_config={
        "채운 슬롯 비율": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent")})
    st.caption(f"슬롯 {len(SLOTS)}개 · 1·2·3차 고정 구성 슬롯은 동형 {MIN_FORMS_FIXED}개, 나머지(심층검사용)는 "
               f"{MIN_FORMS_POOL}개가 목표입니다. 감정 인식의 빈 슬롯은 얼굴·풍경 이미지 문항으로, 준비 전에는 글 문항으로 대체 출제됩니다.")
    errors = validate_bank(items) + validate_self_items(get_self_items())
    if errors:
        with st.expander(f"문항 오류 {len(errors)}건", icon=":material/error:"):
            st.code("\n".join(errors), language=None)
    else:
        st.success(f"문항 {len(items)}개 · 자기평가 {len(get_self_items())}개 형식 오류 없음", icon=":material/check:")


if sessions.empty:
    st.info("아직 응시 기록이 없습니다.", icon=":material/inbox:")
    st.subheader("문항은행 현황")
    bank_status()
    st.stop()
if mode != "all":
    sessions = sessions[sessions["mode"] == mode]

# ---------------------------------------------------------------- 개요

s = an.summary(sessions)
with st.container(horizontal=True):
    st.metric("시작한 검사", f"{s['시작']:,}", border=True)
    st.metric("완료", f"{s['완료']:,}", f"완료율 {s['완료율']:.0%}" if s["시작"] else None, delta_color="off", border=True)
    st.metric("규준에 쓰이는 첫 응시", f"{s['첫 응시 완료']:,}", border=True)
    st.metric("소요 시간 중앙값", "–" if math.isnan(s["평균 소요(분)"]) else f"{s['평균 소요(분)']:.0f}분", border=True)
    st.metric("평균 탭 이탈", "–" if math.isnan(s["탭 이탈 평균"]) else f"{s['탭 이탈 평균']:.1f}회", border=True)

done = sessions[sessions["completed"] & sessions["eq_index"].notna()]
if not done.empty:
    first = done[done["is_first_attempt"] & (done["round"] == 1)]
    st.subheader("점수 분포")
    st.caption(f"첫 응시 {len(first):,}명 · 평균 {first['eq_index'].mean():.1f} · 표준편차 {first['eq_index'].std():.1f} "
               "(가정 기준으로 매긴 점수. 실제 분포가 평균 100·표준편차 15에서 멀면 문항 난이도 가정을 손봐야 합니다)")
    hist = alt.Chart(first).mark_bar(color=PRIMARY, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("eq_index:Q", bin=alt.Bin(step=5, extent=[40, 160]), title="EQ"),
        y=alt.Y("count():Q", title="응시자 수"),
        tooltip=[alt.Tooltip("eq_index:Q", bin=alt.Bin(step=5, extent=[40, 160]), title="구간"),
                 alt.Tooltip("count():Q", title="응시자 수")],
    ).properties(height=220)
    st.altair_chart(hist)

items_tab, rel_tab, self_tab, flow_tab, bank_tab, export_tab = st.tabs(
    ["문항 분석", "신뢰도", "자기평가", "차수·심층검사", "문항은행", "내보내기"])
with bank_tab:
    bank_status()
if responses.empty:
    st.stop()
r_mode = responses if mode == "all" else responses[responses["mode"] == mode]
stats, rel, calib = analyze(r_mode, "all")

# ---------------------------------------------------------------- 문항 분석

with items_tab:
    st.caption(f"응답이 {an.MIN_N}개 이상인 문항만 판정합니다. 적응형 출제라 어려운 문항은 잘하는 사람만 보므로, "
               "'예측 정답률'(그 문항을 본 사람들의 능력으로 예상한 값)과 실제 정답률을 비교해 난이도 가정을 점검합니다.")
    if stats.empty:
        st.info("분석할 응답이 없습니다.")
    else:
        flagged = stats[~stats["판정"].isin(["정상", "데이터 부족"])]
        with st.container(horizontal=True):
            st.metric("판정 가능한 문항", f"{(stats['응답 수'] >= an.MIN_N).sum():,} / {len(stats):,}", border=True)
            st.metric("점검 필요", f"{len(flagged):,}", border=True)
            for label in ("너무 쉬움", "변별도 낮음", "예상보다 쉬움", "예상보다 어려움", "다수 응답과 정답 불일치"):
                st.metric(label, f"{stats['판정'].str.contains(label).sum():,}", border=True)
        with st.container(horizontal=True):
            show = st.pills("보기", ["점검 필요", "전체"], default="점검 필요", key="item_filter")
            domain = st.selectbox("영역", ["전체"] + [spec.label for spec in BLUEPRINT.values()],
                                  label_visibility="collapsed")
        view = flagged if show != "전체" else stats
        if domain != "전체":
            view = view[view["영역"] == domain]
        st.dataframe(
            view.sort_values(["판정", "응답 수"], ascending=[True, False]),
            hide_index=True,
            column_config={
                "정답률": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                "예측 정답률": st.column_config.NumberColumn(format="percent"),
                "차이": st.column_config.NumberColumn(format="%+.2f", help="실제 − 예측"),
                "변별도": st.column_config.NumberColumn(format="%.2f", help="정답 여부와 응시자 능력의 상관 (0.2 미만이면 낮음)"),
                "응답 시간(초)": st.column_config.NumberColumn(format="%.1f"),
            },
        )
        st.caption("처리: '너무 쉬움'·'변별도 낮음'은 문항을 고치거나 교체하고, '예상보다 쉬움/어려움'은 아래 "
                   "'내보내기'의 문항 모수 보정값을 적용하면 채점에 실제 난이도가 반영됩니다. "
                   "'다수 응답과 정답 불일치'는 능력 상위 절반이 정답이 아닌 보기를 가장 많이 고른 문항으로, "
                   "정답 근거(rationale)와 보기 표현을 다시 검토합니다.")
        pick = st.selectbox("보기 선택 분포 확인", ["선택 안 함"] + list(view["문항"]))
        if pick != "선택 안 함":
            it = {i.id: i for i in get_items()}[pick]
            g = an.ability(r_mode)
            g = g[(g["item_id"] == pick) & g["answer"].notna() & (g["answer"] != "")]
            best = g["answer"].astype(str).str.split(",").str[0]
            dist = best[best != ""].astype(int).value_counts(normalize=True).reindex(range(4), fill_value=0)
            key = it.answer if isinstance(it.answer, int) else it.answer[0]
            st.markdown(f"**{it.prompt}**")
            st.dataframe({"보기": [f"{'ABCD'[i]}. {c}" + (" ← 정답" if i == key else "") for i, c in enumerate(it.choices)],
                          "선택 비율": list(dist.values)}, hide_index=True,
                         column_config={"선택 비율": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)})
            st.caption(f"정답 근거: {it.rationale}")

# ---------------------------------------------------------------- 신뢰도

with rel_tab:
    st.caption("주변 신뢰도 = 점수 분산 ÷ (점수 분산 + 평균 오차²). 적응형 검사에서 쓰는 신뢰도 지표로, "
               "0.8 이상이면 개인 비교에 쓸 만하고 0.7 미만이면 참고용입니다.")
    if rel.empty:
        st.info("신뢰도를 계산할 응시가 부족합니다.")
    else:
        st.dataframe(rel, hide_index=True, column_config={
            "신뢰도": st.column_config.ProgressColumn(format="%.2f", min_value=0, max_value=1),
            "평균 표준오차(지수)": st.column_config.NumberColumn(format="±%.1f"),
        })
    r_alt, n_alt = an.alternate_forms(sessions)
    st.metric("동형 검사 신뢰도 (1·2차 상관)", "–" if math.isnan(r_alt) else f"{r_alt:.2f}",
              f"{n_alt}명", delta_color="off", border=True,
              help="같은 사람이 겹치지 않는 문제로 두 번 푼 점수의 상관. 연습 효과가 섞여 있으니 참고용입니다.")

# ---------------------------------------------------------------- 자기평가

with self_tab:
    self_items = get_self_items()
    st.caption("자기평가는 EQ 점수에 들어가지 않고 '내가 보는 나 vs 실제 수행' 비교에만 씁니다. 영역당 4문항이라 "
               "α 0.6 이상이면 무난합니다. 아래 평균·표준편차가 쌓이면 core/report.py의 SELF_NORM(가정: 평균 3.6, 표준편차 0.55)을 바꿉니다.")
    sr_rel = an.self_reliability(responses, self_items)
    if sr_rel.empty:
        st.info("자기평가 응답이 10명 이상 쌓이면 보입니다.")
    else:
        st.dataframe(sr_rel, hide_index=True, column_config={
            "α": st.column_config.ProgressColumn(format="%.2f", min_value=0, max_value=1),
            "평균(1~5)": st.column_config.NumberColumn(format="%.2f"),
            "표준편차": st.column_config.NumberColumn(format="%.2f")})
    checks = an.self_checks(responses, self_items)
    if not checks.empty:
        st.markdown("**응답 점검 문항**")
        st.dataframe(checks, hide_index=True, column_config={
            "그렇다 비율": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)})
        st.caption("거의 아무도 '그렇다'일 수 없는 진술입니다. 두 개 이상에 4~5점으로 답하면 결과에 '자기평가가 좋게 기울었을 수 있음'을 표시합니다.")
    r_sa, n_sa = an.self_ability_corr(sessions)
    st.metric("자기평가 ↔ 실제 EQ 상관", "–" if math.isnan(r_sa) else f"{r_sa:.2f}", f"{n_sa}명", delta_color="off",
              border=True, help="연구에서 자기보고와 능력형 EQ의 상관은 0.2 안팎으로 낮은 편입니다.")

# ---------------------------------------------------------------- 응시 흐름

with flow_tab:
    st.markdown("**차수별 진행**")
    st.caption("1차만 하고 끝낸 사람, 2·3차 검증까지 한 사람, 심층검사까지 마친 사람의 수입니다.")
    st.dataframe(an.round_usage(sessions), hide_index=True)
    st.markdown("**심층검사**")
    deep_df = an.deep_usage(sessions)
    if deep_df.empty:
        st.info("심층검사를 마친 기록이 아직 없습니다.")
    else:
        st.caption(f"영역마다 오차가 ±{15 * DEEP_TARGET_SE:.0f}점 안쪽이 되면 끝납니다 (최소 {DEEP_MIN_ITEMS} · 최대 "
                   f"{DEEP_MAX_ITEMS}문항). 평균 문항 수가 최대에 가까우면 그 영역의 문항 풀에 실력대에 맞는 문항이 부족하다는 뜻입니다.")
        st.dataframe(deep_df, hide_index=True, column_config={
            "평균 문항 수": st.column_config.NumberColumn(format="%.1f"),
            "평균 최종 오차(지수)": st.column_config.NumberColumn(format="±%.1f"),
        })

# ---------------------------------------------------------------- 내보내기

with export_tab:
    st.markdown("**원자료**")
    with st.container(horizontal=True):
        st.download_button("응답 CSV", r_mode.drop(columns=["id_s"], errors="ignore").to_csv(index=False).encode("utf-8-sig"),
                           "responses.csv", "text/csv", icon=":material/download:")
        st.download_button("세션 CSV", sessions.drop(columns=["progress"]).to_csv(index=False).encode("utf-8-sig"),
                           "sessions.csv", "text/csv", icon=":material/download:")
    st.markdown("**문항 모수 보정값**")
    st.caption("응답이 50개 이상인 문항의 난이도(irt_b)를 실제 응답으로 다시 추정한 값입니다. "
               "문항 JSON에 irt_a/irt_b/irt_c로 넣으면 채점이 가정값 대신 이 값을 씁니다. "
               "응시자 능력은 현재 가정값으로 추정한 것이므로, 적용 후 데이터가 더 쌓이면 다시 보정합니다.")
    if calib:
        diff = pd.DataFrame([{"문항": k, "응답 수": v["n"], "기존 b": v["기존_b"], "보정 b": v["irt_b"],
                              "변화": v["irt_b"] - v["기존_b"]} for k, v in calib.items()])
        st.dataframe(diff.sort_values("변화", key=abs, ascending=False), hide_index=True,
                     column_config={"변화": st.column_config.NumberColumn(format="%+.2f")})
        payload = {k: {kk: vv for kk, vv in v.items() if kk.startswith("irt_")} for k, v in calib.items()}
        st.download_button("보정값 JSON", json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8"),
                           "item_calibration.json", "application/json", icon=":material/download:")
    else:
        st.info("보정할 만큼 응답이 쌓인 문항이 아직 없습니다.")
