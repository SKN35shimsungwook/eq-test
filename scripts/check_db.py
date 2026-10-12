"""배포 전 DB 연결 점검: python scripts/check_db.py ["postgresql+psycopg2://..."]

URL을 주지 않으면 .streamlit/secrets.toml의 [connections.sql] url을 씁니다.
테이블 생성(RLS 포함) → 세션 저장 → 응답 저장 → 진행 상태 → 완료 → 규준·분석 조회를 실제로 해 보고,
점검용으로 만든 행은 마지막에 지웁니다. 응시 데이터에는 손대지 않습니다.
"""

import sys
import time
import tomllib
from pathlib import Path

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from core import analysis, db  # noqa: E402

CHECK_VERSION = "check"


def get_url() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    secrets = ROOT / ".streamlit" / "secrets.toml"
    try:
        return tomllib.loads(secrets.read_text(encoding="utf-8"))["connections"]["sql"]["url"]
    except (FileNotFoundError, KeyError):
        sys.exit("DB URL이 없습니다. 인자로 주거나 .streamlit/secrets.toml에 [connections.sql] url을 넣으세요.")


def step(name: str, fn):
    t0 = time.perf_counter()
    try:
        out = fn()
    except Exception as e:  # 점검 스크립트라 어떤 오류든 이름을 붙여 보여 준다
        print(f"  ✗ {name}: {type(e).__name__}: {e}")
        sys.exit(1)
    print(f"  ✓ {name} ({(time.perf_counter() - t0) * 1000:.0f}ms)")
    return out


url = get_url()
engine = sa.create_engine(url, pool_pre_ping=True)
print(f"대상: {engine.url.render_as_string(hide_password=True)}")

step("접속", lambda: engine.connect().close())
step("테이블 생성·RLS", lambda: db.init_db(engine))
if engine.dialect.name == "postgresql":
    def rls():
        with engine.connect() as conn:
            rows = conn.execute(sa.text(
                "select relname, relrowsecurity from pg_class where relname in ('sessions','responses')")).all()
        off = [r.relname for r in rows if not r.relrowsecurity]
        assert len(rows) == 2 and not off, f"RLS 꺼짐: {off}"
    step("RLS 켜짐 확인", rls)

sid = step("세션 저장", lambda: db.start_session(engine, "check-client", "quick", 1, CHECK_VERSION))
try:
    step("응답 저장", lambda: db.save_responses(engine, sid, [dict(
        item_id="und-cause-1a", item_version=1, domain="und", answer="0", correct=True, score=1.0, response_ms=1234)]))
    step("응답 다시 저장(중복 방지)", lambda: db.save_responses(engine, sid, [dict(
        item_id="und-cause-1a", item_version=1, domain="und", answer="1", correct=False, score=0.0, response_ms=999)]))
    step("진행 상태 저장", lambda: db.save_progress(engine, sid, {"d": 1, "domains": ["und"], "answers": {"x": "1"}}))

    def load():
        row = db.load_session(engine, sid)
        assert row["progress"]["answers"] == {"x": "1"} and row["round"] == 1 and row["series_id"] == sid
    step("진행 상태 읽기", load)
    step("완료 기록", lambda: db.complete_session(engine, sid, {"und": 0}, {"und": 90.0}, 90.0, 25.0,
                                                 thetas={"total": -0.6, "und": -0.6}, focus_lost=0))
    step("차수·본 문항 조회", lambda: (db.series_sessions(engine, sid), db.seen_items(engine, sid)))
    step("규준 조회", lambda: db.norm_thetas(engine, "quick"))

    def frames():
        s, r = analysis.load_frames(engine, include_sim=True)
        mine = r[r["session_id"] == sid]
        assert len(mine) == 1 and not mine.iloc[0]["correct"], "응답이 덮어써지지 않음"
    step("분석용 데이터 읽기", frames)
finally:
    with engine.begin() as conn:
        conn.execute(db.responses.delete().where(db.responses.c.session_id == sid))
        conn.execute(db.sessions.delete().where(db.sessions.c.id == sid))
    print("  ✓ 점검용 데이터 삭제")
print("\n통과: 이 DB로 배포할 수 있습니다.")
