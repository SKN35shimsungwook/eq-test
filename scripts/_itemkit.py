"""문항 작성 도우미: 영역별 작성 스크립트(scripts/items_<영역>.py)가 이 함수로 items/<영역>.json을 쓴다.

Q(slot, prompt, choices, answer, explanation, rationale) 순서로 적으면 같은 슬롯 안에서 a, b, c… ID가 붙는다.
"""

from __future__ import annotations

import json
import string
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def Q(slot: str, prompt: str, choices: list[str], answer, explanation: str, rationale: str, **extra) -> dict:
    return {"slot": slot, "prompt": prompt, "choices": choices, "answer": answer,
            "explanation": explanation, "rationale": rationale, **extra}


def write(domain: str, items: list[dict]) -> None:
    count: dict[str, int] = defaultdict(int)
    out = []
    for it in items:
        letter = string.ascii_lowercase[count[it["slot"]]]
        count[it["slot"]] += 1
        out.append({"id": f"{it['slot']}{letter}", **it})
    path = ROOT / "items" / f"{domain}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{path.name}: {len(out)}문항")
