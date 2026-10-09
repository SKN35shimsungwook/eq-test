"""문항은행 검증: python scripts/validate_items.py [--strict]

기본: 문항 형식·중복·이미지 파일 확인. --strict: 슬롯별 동형 수, 영역 문항 풀, 자기보고 구성까지 (출시 전 기준).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.item_bank import load_items, load_self_items, validate_blueprint, validate_bank, validate_self_items  # noqa: E402
from core.schema import BLUEPRINT  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    items, self_items = load_items(), load_self_items()
    errors = validate_blueprint() + validate_bank(items, args.strict) + validate_self_items(self_items, args.strict)

    counts = Counter(it.domain for it in items)
    print(f"문항 {len(items)}개 · 자기평가 {len(self_items)}개")
    for domain, spec in BLUEPRINT.items():
        print(f"  {spec.label:<8} {counts[domain]:>3}개")
    if errors:
        print(f"\n오류 {len(errors)}건")
        for e in errors:
            print(" ", e)
        return 1
    print("\n통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
