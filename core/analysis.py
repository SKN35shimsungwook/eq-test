"""관리자 분석: 문항 분석, 신뢰도, 응시 흐름, 문항 모수 보정 (Streamlit 없이 테스트 가능한 순수 로직).

적응형 출제에서는 어려운 문항을 잘하는 사람만 보므로 단순 정답률이 실제 난이도를 왜곡한다.
그래서 문항마다 '그 문항을 본 사람들의 능력으로 모형이 예측한 정답률'과 실제 정답률을 비교한다.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from core import db
from core import exam as ex
from core import scoring as sc
from core.schema import BLUEPRINT, DEEP_ROUND, DIFFICULTY_LABELS, Domain, Item, ItemFormat, SelfItem, round_label

MIN_N = 30          # 문항 판정에 필요한 최소 응답 수
SIM_VERSION = "sim"  # 시뮬레이션 데이터 표시


def load_frames(engine: Engine, include_sim: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(세션, 응답) 데이터프레임. 응답에는 그 세션의 종합 θ가 붙는다. 자기평가 "sr", 마지막 질문 "fc"."""
    with engine.connect() as conn:
        sessions = pd.DataFrame([dict(r._mapping) for r in conn.execute(sa.select(db.sessions))])
        responses = pd.DataFrame([dict(r._mapping) for r in conn.execute(sa.select(db.responses))])
    if sessions.empty:
        return sessions, responses
    if not include_sim:
        sessions = sessions[sessions["app_version"] != SIM_VERSION]
    sessions = sessions.assign(
        completed=sessions["completed_at"].notna(),
        theta=sessions["thetas"].map(lambda t: (t or {}).get("total") if isinstance(t, dict) else None),
    )
    if not responses.empty:
        responses = responses.merge(
            sessions[["id", "mode", "round", "is_first_attempt", "completed", "theta"]],
            left_on="session_id", right_on="id", suffixes=("", "_s"))
        responses = responses[responses["completed"]]
    return sessions, responses


def _p(item: Item, theta: np.ndarray) -> np.ndarray:
    """완전히 맞힐 확률 (최선·최악은 둘 다)."""
    return sc.p_correct(item, theta)


def ability(responses: pd.DataFrame) -> pd.DataFrame:
    return responses[~responses["domain"].isin(("sr", "fc"))] if not responses.empty else responses


def consensus(item: Item, g: pd.DataFrame, top: float = 0.5) -> dict | None:
    """능력 상위 절반 응시자가 가장 많이 고른 (최선) 보기가 정답과 같은지.

    정서 문항은 정답 기준이 이론이라, 잘하는 사람들의 다수 선택이 정답과 다르면 정답이나 보기를 다시 검토한다
    (전문가 채점과 다수 합의 채점은 r≈.9 이상 일치한다는 연구가 근거 — 크게 어긋나면 문항 문제일 가능성).
    """
    g = g[g["answer"].notna() & (g["answer"] != "")]
    if g.empty:
        return None
    hi = g[g["theta"] >= g["theta"].quantile(1 - top)]
    picks = hi["answer"].astype(str).str.split(",").str[0]
    picks = picks[picks != ""]
    if picks.empty:
        return None
    share = picks.value_counts(normalize=True)
    key = str(item.answer if item.format is ItemFormat.MCQ else item.answer[0])
    mode = share.index[0]
    return {"상위 다수 선택": int(mode), "다수 비율": float(share.iloc[0]), "정답 선택 비율": float(share.get(key, 0.0)),
            "불일치": mode != key and share.iloc[0] - share.get(key, 0.0) >= 0.10 and len(picks) >= MIN_N // 2}


def item_stats(responses: pd.DataFrame, items: dict[str, Item], min_n: int = MIN_N) -> pd.DataFrame:
    """문항별 통계와 경고 (자기평가 제외)."""
    out = []
    df = ability(responses)
    df = df[df["theta"].notna()]
    for item_id, g in df.groupby("item_id"):
        it = items.get(item_id)
        if it is None:
            continue
        correct = g["correct"].astype(float).to_numpy()
        theta = g["theta"].astype(float).to_numpy()
        n = len(g)
        p_obs = correct.mean()
        p_each = _p(it, theta)
        p_pred = p_each.mean()
        z = (p_obs - p_pred) / (math.sqrt((p_each * (1 - p_each)).sum()) / n)  # 우연으로 생길 만한 차이인가
        r_pb = float(np.corrcoef(correct, theta)[0, 1]) if n > 2 and correct.std() > 0 and theta.std() > 0 else np.nan
        flags = []
        if n >= min_n:
            if p_obs > 0.9:
                flags.append("너무 쉬움")
            if p_obs < 0.1:
                flags.append("너무 어려움")
            if not np.isnan(r_pb) and r_pb < 0.2:
                flags.append("변별도 낮음")
            if p_obs - p_pred > 0.15 and z > 3:
                flags.append("예상보다 쉬움")
            if p_pred - p_obs > 0.15 and z < -3:
                flags.append("예상보다 어려움")
            if (cons := consensus(it, g)) and cons["불일치"]:
                flags.append("다수 응답과 정답 불일치")
        out.append({
            "문항": item_id, "영역": BLUEPRINT[it.domain].label, "유형": it.subtype,
            "난이도": DIFFICULTY_LABELS[it.difficulty], "응답 수": n, "정답률": p_obs, "예측 정답률": p_pred,
            "차이": p_obs - p_pred, "변별도": r_pb,
            "응답 시간(초)": g["response_ms"].dropna().median() / 1000 if g["response_ms"].notna().any() else np.nan,
            "판정": ", ".join(flags) if flags else ("정상" if n >= min_n else "데이터 부족"),
        })
    return pd.DataFrame(out)


def domain_reliability(responses: pd.DataFrame, items: dict[str, Item]) -> pd.DataFrame:
    """영역별 주변 신뢰도 = var(θ̂) / (var(θ̂) + 평균 SE²). 적응형 검사에서 쓰는 신뢰도 지표."""
    rows = []
    totals, total_se = [], []
    responses = ability(responses)
    for _, sg in responses.groupby("session_id"):
        _, tot = sc.estimate(sg[["item_id", "domain", "correct", "score"]].to_dict("records"), items)
        totals.append(tot.theta)
        total_se.append(tot.se)
    if len(totals) >= 3:
        var_t, mse = float(np.var(totals, ddof=1)), float(np.mean(np.square(total_se)))
        rows.append({"영역": "종합 (EQ)", "응시 수": len(totals), "신뢰도": var_t / (var_t + mse),
                     "평균 표준오차(지수)": 15 * float(np.mean(total_se))})
    for domain in sc.DOMAIN_ORDER:
        g = responses[responses["domain"] == domain.value]
        if g.empty:
            continue
        thetas, ses = [], []
        for _, sg in g.groupby("session_id"):
            recs = sg[["item_id", "domain", "correct", "score"]].to_dict("records")
            per, _ = sc.estimate(recs, items)
            if domain in per:
                thetas.append(per[domain].theta)
                ses.append(per[domain].se)
        if len(thetas) < 3:
            continue
        var_t, mse = float(np.var(thetas, ddof=1)), float(np.mean(np.square(ses)))
        rows.append({"영역": BLUEPRINT[domain].label, "응시 수": len(thetas),
                     "신뢰도": var_t / (var_t + mse) if var_t + mse > 0 else np.nan,
                     "평균 표준오차(지수)": 15 * float(np.mean(ses))})
    return pd.DataFrame(rows)


def alternate_forms(sessions: pd.DataFrame) -> tuple[float, int]:
    """같은 사람이 겹치지 않는 문제로 푼 1·2차 종합 θ의 상관 (동형 검사 신뢰도)."""
    done = sessions[sessions["completed"] & sessions["theta"].notna()]
    r1 = done[done["round"] == 1].set_index("series_id")["theta"]
    r2 = done[done["round"] == 2].set_index("series_id")["theta"]
    pair = pd.concat([r1, r2], axis=1, join="inner").dropna()
    if len(pair) < 3:
        return float("nan"), len(pair)
    return float(pair.corr().iloc[0, 1]), len(pair)


def deep_usage(sessions: pd.DataFrame) -> pd.DataFrame:
    """심층검사에서 영역마다 몇 문항으로 끝났고, 마지막 오차가 얼마였는지."""
    rows = []
    done = sessions[sessions["completed"] & (sessions["round"] == DEEP_ROUND)]
    for prog in done["progress"]:
        prog = prog or {}
        for d, ids in (prog.get("items") or {}).items():
            est = (prog.get("estimates") or {}).get(d)
            rows.append({"영역": BLUEPRINT[Domain(d)].label, "문항 수": len(ids),
                         "최종 오차(지수)": 15 * est[1] if est else np.nan})
    if not rows:
        return pd.DataFrame(columns=["영역", "응시", "평균 문항 수", "평균 최종 오차(지수)"])
    df = pd.DataFrame(rows)
    return df.groupby("영역", sort=False).agg(**{"응시": ("문항 수", "size"), "평균 문항 수": ("문항 수", "mean"),
                                               "평균 최종 오차(지수)": ("최종 오차(지수)", "mean")}).reset_index()


def round_usage(sessions: pd.DataFrame) -> pd.DataFrame:
    """묶음(같은 사람)마다 어디까지 했는지: 1차만 / 2차까지 / 3차까지 / 심층검사까지."""
    done = sessions[sessions["completed"]]
    if done.empty:
        return pd.DataFrame(columns=["진행", "응시자"])
    last = done.groupby("series_id")["round"].max().value_counts().sort_index()
    return pd.DataFrame({"진행": [f"{round_label(k)}까지" for k in last.index], "응시자": last.values})


def calibrate(responses: pd.DataFrame, items: dict[str, Item], min_n: int = 50) -> dict[str, dict]:
    """응답이 충분한 문항의 난이도 b를 다시 추정한다 (a, c는 고정, 응시자 θ는 현재 추정치).

    결과는 문항 JSON에 irt_b로 넣을 수 있는 제안값이다.
    """
    grid = np.linspace(-3.5, 3.5, 141)
    out = {}
    df = ability(responses)
    df = df[df["theta"].notna()]
    for item_id, g in df.groupby("item_id"):
        it = items.get(item_id)
        if it is None or len(g) < min_n:
            continue
        a, b0, c = sc.item_params(it)
        u = g["correct"].astype(float).to_numpy()[:, None]
        th = g["theta"].astype(float).to_numpy()[:, None]
        p = c + (1 - c) / (1 + np.exp(-sc.D * a * (th - grid[None, :])))
        ll = (u * np.log(p) + (1 - u) * np.log(1 - p)).sum(axis=0)
        b = float(grid[ll.argmax()])
        out[item_id] = {"irt_a": a, "irt_b": round(b, 2), "irt_c": c, "n": len(g), "기존_b": round(b0, 2)}
    return out


def session_rows(prog: dict, items: dict[str, Item]) -> list[dict]:
    return [r for d in prog["domains"] for r in ex.domain_rows(prog, items, Domain(d))]


def summary(sessions: pd.DataFrame) -> dict:
    started = len(sessions)
    done = sessions[sessions["completed"]]
    dur = (done["completed_at"] - done["started_at"]).dt.total_seconds() / 60 if len(done) else pd.Series(dtype=float)
    return {
        "시작": started, "완료": len(done),
        "완료율": len(done) / started if started else math.nan,
        "첫 응시 완료": int((done["is_first_attempt"] & (done["round"] == 1)).sum()),
        "평균 소요(분)": float(dur.median()) if len(dur) else math.nan,
        "탭 이탈 평균": float(done["focus_lost"].fillna(0).mean()) if len(done) else math.nan,
    }


# ---------------------------------------------------------------- 자기평가

def self_reliability(responses: pd.DataFrame, self_items: list[SelfItem]) -> pd.DataFrame:
    """자기평가 영역별 크론바흐 α (역문항 반영 점수). 4문항 척도라 0.6 이상이면 무난, 0.7 이상이면 양호."""
    sr = responses[responses["domain"] == "sr"] if not responses.empty else responses
    if sr.empty:
        return pd.DataFrame()
    wide = sr.pivot_table(index="session_id", columns="item_id", values="score", aggfunc="first")
    rows = []
    groups = {d: [it.id for it in self_items if it.domain is d] for d in Domain}
    groups["전체"] = [it.id for it in self_items if not it.check]
    for key, ids in groups.items():
        cols = [c for c in ids if c in wide.columns]
        x = wide[cols].dropna()
        if len(x) < 10 or len(cols) < 2:
            continue
        k = len(cols)
        alpha = k / (k - 1) * (1 - x.var(ddof=1).sum() / x.sum(axis=1).var(ddof=1))
        rows.append({"영역": "전체" if key == "전체" else BLUEPRINT[key].label, "응답 수": len(x), "문항": k,
                     "α": float(alpha), "평균(1~5)": float(x.mean(axis=1).mean()), "표준편차": float(x.mean(axis=1).std(ddof=1))})
    return pd.DataFrame(rows)


def self_checks(responses: pd.DataFrame, self_items: list[SelfItem]) -> pd.DataFrame:
    """응답 점검 문항별 '그렇다(4~5)' 응답 비율. 30%를 넘으면 문항 표현이 너무 쉬운지 점검."""
    sr = responses[responses["domain"] == "sr"] if not responses.empty else responses
    rows = []
    for it in self_items:
        if not it.check:
            continue
        g = sr[sr["item_id"] == it.id]
        if g.empty:
            continue
        rows.append({"문항": it.text, "응답 수": len(g), "그렇다 비율": float((g["score"] >= 4).mean())})
    return pd.DataFrame(rows)


def self_ability_corr(sessions: pd.DataFrame) -> tuple[float, int]:
    """자기평가 전체 평균과 1차 종합 θ의 상관 (연구에서는 r≈0.2 안팎)."""
    first = sessions[sessions["completed"] & (sessions["round"] == 1) & sessions["theta"].notna()]
    vals = []
    for _, r in first.iterrows():
        ss = r.get("self_scores") or {}
        means = [v for k, v in ss.items() if not k.startswith("_")]
        if means:
            vals.append((sum(means) / len(means), r["theta"]))
    if len(vals) < 10:
        return float("nan"), len(vals)
    arr = np.asarray(vals)
    return float(np.corrcoef(arr[:, 0], arr[:, 1])[0, 1]), len(vals)


def validity_table(sessions: pd.DataFrame, items: dict[str, Item]) -> pd.DataFrame:
    """1차를 마친 세션마다 응답 신뢰도 판정 (core.validity). 결과 화면과 같은 규칙."""
    from core import validity as vd
    rows = []
    done = sessions[sessions["completed"] & (sessions["round"] == 1)] if not sessions.empty else sessions
    for _, s in done.iterrows():
        prog = s["progress"] if isinstance(s["progress"], dict) else None
        if not prog:
            continue
        v = vd.assess(s["self_scores"] if isinstance(s["self_scores"], dict) else None, session_rows(prog, items), items)
        rows.append({"세션": s["id"], "모드": s["mode"], "판정": v.level, "이유": " / ".join(v.reasons),
                     "욕구 부정(0~8)": v.metrics["deny"], "어긋난 짝": v.metrics.get("_incons"),
                     "빠른 응답": v.metrics["fast"], "한 위치": v.metrics["position"]})
    return pd.DataFrame(rows)
