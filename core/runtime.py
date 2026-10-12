"""Streamlit 런타임 공용 리소스: DB 엔진, 문항은행, 세션 상태 초기화."""

from __future__ import annotations

import uuid
from pathlib import Path

import streamlit as st
from sqlalchemy.engine import Engine

from core import db
from core.item_bank import load_final_items, load_items, load_self_items
from core.schema import Item, Mode, SelfItem

APP_VERSION = "0.1.0"
LOCAL_DB = Path(__file__).resolve().parent.parent / "data" / "eq_test.db"


def _has_sql_secret() -> bool:
    try:
        return "sql" in st.secrets.get("connections", {})
    except Exception:  # secrets.toml 자체가 없을 때
        return False


@st.cache_resource
def get_engine() -> Engine:
    """secrets에 [connections.sql]이 있으면 그것(Supabase), 없으면 로컬 SQLite."""
    if _has_sql_secret():
        conn = st.connection("sql", type="sql")
    else:
        LOCAL_DB.parent.mkdir(exist_ok=True)
        conn = st.connection("sql", type="sql", url=f"sqlite:///{LOCAL_DB.as_posix()}")
    db.init_db(conn.engine)
    return conn.engine


@st.cache_data
def get_items() -> list[Item]:
    return load_items()


@st.cache_data
def get_self_items() -> list[SelfItem]:
    return load_self_items()


@st.cache_data
def get_final_items() -> list[SelfItem]:
    return load_final_items()


def init_state() -> None:
    ss = st.session_state
    # 시작 화면에서 브라우저 localStorage의 익명 ID로 교체된다 (저장소를 못 쓰면 이 값 유지)
    ss.setdefault("client_id", str(uuid.uuid4()))
    ss.setdefault("exam", None)        # 응시 진행 상태 (core.exam)
    ss.setdefault("session_id", None)  # 검사 시작 시 DB 세션 ID
    ss.setdefault("mode", None)        # Mode.QUICK | Mode.FULL
    ss.setdefault("form_seed", None)
    ss.setdefault("series_id", None)   # 차수 묶음 ID (1차 세션 ID)
    ss.setdefault("round", 1)        # 1~3차, 4 = 심층검사
    ss.setdefault("phase", "intro")    # intro → self(자기보고, 1차만) → test → result
    if ss.session_id is None and "s" in st.query_params:
        _resume(st.query_params["s"])


def _resume(session_id: str) -> None:
    """URL의 세션 ID로 진행 중이던 검사(또는 끝난 결과)를 되살린다. 새로고침 대비."""
    row = db.load_session(get_engine(), session_id)
    if not row or not row["progress"]:
        st.query_params.pop("s", None)
        return
    ss = st.session_state
    ss.session_id = row["id"]
    ss.client_id = row["client_id"]
    ss.mode = Mode(row["mode"])
    ss.form_seed = row["form_seed"]
    ss.series_id = row["series_id"] or row["id"]
    ss.round = row["round"] or 1
    ss.exam = row["progress"]
    ss.phase = "result" if row["progress"]["d"] >= len(row["progress"]["domains"]) else "test"


def save_progress() -> None:
    db.save_progress(get_engine(), st.session_state.session_id, st.session_state.exam)
