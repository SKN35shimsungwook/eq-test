"""응시 진행 상태와 채점 (Streamlit 없이 테스트 가능한 순수 로직).

진행 상태는 dict 하나로 st.session_state["exam"]에 보관하고, DB sessions.progress에도 저장해 새로고침 후 이어 간다.
응답 문자열: 4지선다는 "2", 최선·최악은 "1,3"(최선,최악). 최선만 고른 상태는 "1,".
"""

from __future__ import annotations

import random
import time

from core import scoring
from core.schema import (BLUEPRINT, DEEP_MAX_ITEMS, DEEP_MIN_ITEMS, DEEP_SEC_PER_ITEM, DEEP_TARGET_SE, Domain,
                         Item, ItemFormat, Mode)

EXPIRY_SLACK_SEC = 1.0  # 브라우저 타이머가 서버보다 조금 먼저 끝나는 차이를 흡수


def _base(domains: list[str], mode: Mode) -> dict:
    return {
        "domains": domains,
        "d": 0,            # 현재 영역 인덱스
        "stage": "intro",  # intro | items
        "i": 0,            # 현재 문항 인덱스
        "answers": {},     # item_id → 응답 문자열 (미응답이면 없음)
        "ms": {},          # item_id → 누적 응답 시간(ms)
        "deadline": None,  # 영역(또는 위기 대처 문항) 마감 시각 (epoch 초)
        "entered": None,   # 현재 문항을 보기 시작한 시각
        "blurs": 0,        # 탭·창 이탈 횟수
        "raw": {},         # domain → 맞힌 수
        "mode": mode.value,
        "kind": "round",   # round (1·2·3차) | deep (심층검사)
    }


def new_exam(form: dict[Domain, list[Item]], mode: Mode) -> dict:
    """1·2·3차 검사. form: item_bank.build_form 결과 (영역 → 고정 구성 문항)."""
    exam = _base([d.value for d in form], mode)
    exam["items"] = {d.value: [it.id for it in items] for d, items in form.items()}
    return exam


# ---------------------------------------------------------------- 응답 형식

def parse_answer(item: Item, answer: str | None):
    """저장된 응답 문자열 → Item.is_correct가 받는 값 (미완성 응답은 None)."""
    if answer is None or answer == "":
        return None
    if item.format is ItemFormat.MCQ:
        return int(answer)
    best, _, worst = answer.partition(",")
    if best == "" or worst == "":
        return None
    return [int(best), int(worst)]


def format_answer(best: int | None, worst: int | None = None, best_worst: bool = False) -> str | None:
    if not best_worst:
        return None if best is None else str(best)
    if best is None and worst is None:
        return None
    return f"{'' if best is None else best},{'' if worst is None else worst}"


def is_complete(item: Item, answer: str | None) -> bool:
    return parse_answer(item, answer) is not None


# ---------------------------------------------------------------- 심층검사 (컴퓨터 맞춤형 검사)

def new_deep_exam(prior_rows: list[dict], seen: set[str], mode: Mode) -> dict:
    """1~3차 응답을 출발점으로, 영역마다 실력에 가장 정보가 많은 문항을 하나씩 골라 낸다."""
    domains = [d.value for d in BLUEPRINT]
    exam = _base(domains, mode)
    exam["kind"] = "deep"
    exam["items"] = {d: [] for d in domains}
    exam["prior"] = {d: [{k: r[k] for k in ("item_id", "domain", "correct", "score")}
                         for r in prior_rows if r["domain"] == d] for d in domains}
    exam["seen"] = sorted(seen)
    return exam


def deep_estimate(exam: dict, items: dict[str, Item], domain: Domain) -> tuple[float, float]:
    """앞 차수 + 지금까지의 심층검사 응답으로 추정한 (θ, 표준오차)."""
    rows = exam["prior"].get(domain.value, []) + [
        {"item_id": i, "domain": domain.value, "correct": score_item(items[i], exam["answers"].get(i))[0]}
        for i in exam["items"][domain.value]]
    rows = [r for r in rows if r["item_id"] in items]
    if not rows:
        return 0.0, 1.0
    return scoring.eap(scoring._likelihood([items[r["item_id"]] for r in rows], [bool(r["correct"]) for r in rows]))


def deep_next(exam: dict, items: dict[str, Item], seed: int) -> str | None:
    """현재 영역의 다음 심층검사 문항을 골라 붙인다. 목표 정확도나 최대 문항에 닿았으면 None."""
    d = current_domain(exam)
    chosen = exam["items"][d.value]
    theta, se = deep_estimate(exam, items, d)
    exam.setdefault("estimates", {})[d.value] = [theta, se]
    if len(chosen) >= DEEP_MAX_ITEMS or (len(chosen) >= DEEP_MIN_ITEMS and se <= DEEP_TARGET_SE):
        return None
    seen = set(exam["seen"])
    cands = [it for it in items.values() if it.domain is d and it.id not in chosen and it.id not in seen]
    if not cands:
        return None
    ranked = sorted(cands, key=lambda it: (-scoring.information(it, theta), it.id))
    last = items[chosen[-1]].subtype if chosen else None
    top = [it for it in ranked[:6] if it.subtype != last] or ranked[:6]
    pick = random.Random(f"{seed}:{d.value}:{len(chosen)}").choice(top[:3])  # 같은 문항만 반복 노출되지 않게
    chosen.append(pick.id)
    return pick.id


# ---------------------------------------------------------------- 시간

def item_timed(domain: Domain) -> bool:
    """문항마다 제한시간이 있는 영역(위기 대처): 한 문항씩, 되돌아갈 수 없음."""
    return BLUEPRINT[domain].time_full == 0


def domain_time_limit(domain: Domain, mode: Mode, deep: bool = False) -> int:
    """영역 제한시간(초). 문항마다 시간을 재는 영역은 0."""
    if item_timed(domain):
        return 0
    return DEEP_MAX_ITEMS * DEEP_SEC_PER_ITEM if deep else BLUEPRINT[domain].time_for(mode)


def current_domain(exam: dict) -> Domain:
    return Domain(exam["domains"][exam["d"]])


def start_domain(exam: dict, mode: Mode, now: float | None = None) -> None:
    now = time.time() if now is None else now
    limit = domain_time_limit(current_domain(exam), mode, deep=exam.get("kind") == "deep")
    exam.update(stage="items", i=0, entered=now, deadline=now + limit if limit else None)


def start_item(exam: dict, item: Item, now: float | None = None) -> None:
    """문항 제한시간이 있는 문항을 보여 주기 시작할 때 마감을 정한다 (이미 정했으면 유지 — 새로고침 대비)."""
    now = time.time() if now is None else now
    if item.time_limit and exam.get("item_id") != item.id:
        exam.update(item_id=item.id, deadline=now + item.time_limit, entered=now)


def is_expired(exam: dict, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return exam["deadline"] is not None and now >= exam["deadline"] - EXPIRY_SLACK_SEC


def track_time(exam: dict, item_id: str, now: float | None = None) -> None:
    """지금 보고 있던 문항에 머문 시간을 더하고 시계를 다시 맞춘다."""
    now = time.time() if now is None else now
    if exam["entered"] is not None:
        exam["ms"][item_id] = exam["ms"].get(item_id, 0) + int((now - exam["entered"]) * 1000)
    exam["entered"] = now


# ---------------------------------------------------------------- 채점

def score_item(item: Item, answer: str | None) -> tuple[bool, float]:
    ok = item.is_correct(parse_answer(item, answer))
    return ok, float(ok)


def domain_rows(exam: dict, items: dict[str, Item], domain: Domain) -> list[dict]:
    rows = []
    for item_id in exam["items"][domain.value]:
        item = items[item_id]
        answer = exam["answers"].get(item_id)
        correct, score = score_item(item, answer)
        rows.append({"item_id": item_id, "item_version": item.version, "domain": domain.value,
                     "answer": answer, "correct": correct, "score": score,
                     "response_ms": exam["ms"].get(item_id)})
    return rows


def finish_domain(exam: dict, rows: list[dict]) -> bool:
    """영역 맞힌 수를 기록하고 다음 영역으로. 모든 영역이 끝났으면 True."""
    domain = current_domain(exam)
    exam["raw"][domain.value] = sum(r["score"] for r in rows)
    exam.update(d=exam["d"] + 1, stage="intro", i=0, deadline=None, entered=None, item_id=None)
    return exam["d"] >= len(exam["domains"])


# ---------------------------------------------------------------- 자기평가

def self_scores(self_items: list, answers: dict[str, int]) -> dict:
    """자기평가 응답 → 영역별 평균(1~5, 역문항 반영)과 응답 점검 결과.

    점검 문항(거의 누구도 '그렇다'일 수 없는 진술)에 4점 이상으로 답한 수가 2개 이상이면 과장 가능성으로 표시한다.
    """
    by_domain: dict[str, list[int]] = {}
    checks = 0
    for it in self_items:
        a = answers.get(it.id)
        if a is None:
            continue
        if it.check:
            checks += a >= 4
        else:
            by_domain.setdefault(it.domain.value, []).append(it.score(a))
    out = {d: round(sum(v) / len(v), 2) for d, v in by_domain.items()}
    out["_checks"] = checks
    out["_inflated"] = checks >= 2
    return out
