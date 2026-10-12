"""문항 작성 도우미: 영역별 작성 스크립트(scripts/items_<영역>.py)가 이 함수로 items/<영역>.json을 쓴다.

Q(slot, prompt, choices, answer, explanation, rationale) 순서로 적으면 같은 슬롯 안에서 a, b, c… ID가 붙는다.
"""

from __future__ import annotations

import json
import string
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def Q(slot: str, prompt: str, choices: list[str], answer, explanation: str, rationale: str,
      styles: str | None = None, **extra) -> dict:
    """styles: 보기 순서대로 선택 유형 코드를 공백으로 (예: "talk accept guard bridge")."""
    d = {"slot": slot, "prompt": prompt, "choices": choices, "answer": answer,
         "explanation": explanation, "rationale": rationale, **extra}
    if styles:
        d["styles"] = styles.split()
    return d


def tag(items: list[dict], styles: list[str | None]) -> list[dict]:
    """문항 목록에 순서대로 선택 유형을 붙인다 (None은 개념 문항이라 유형 없음)."""
    assert len(items) == len(styles), (len(items), len(styles))
    for it, st in zip(items, styles):
        if st:
            it["styles"] = st.split()
    return items


FILE_NAMES = {"con": "conflict"}


def write(domain: str, items: list[dict]) -> None:
    count: dict[str, int] = defaultdict(int)
    out = []
    for it in items:
        letter = string.ascii_lowercase[count[it["slot"]]]
        count[it["slot"]] += 1
        out.append({"id": f"{it['slot']}{letter}", **it})
    # "con"은 Windows 예약 이름(CON)이라 파일로 만들 수 없음 → conflict.json
    path = ROOT / "items" / f"{FILE_NAMES.get(domain, domain)}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{path.name}: {len(out)}문항")
