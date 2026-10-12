"""문항은행 로드·검증·검사지 구성.

- items/*.json: 능력 문항 (영역별 파일, 예: und.json)
- items/self_report.json: 자기보고 문항
- items/calibration.json: (선택) 관리자 페이지에서 받은 문항 모수 보정값
"""

from __future__ import annotations

import json
import random
import re
import zlib
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

from core.schema import (BLUEPRINT, FIXED_SLOTS, IMAGE_SUBTYPES, MAX_SAME_TYPE, MIN_DOMAIN_POOL, MIN_FORMS_FIXED,
                         MIN_FORMS_POOL, SELF_CHECKS, SELF_MIN_REVERSE, SELF_PER_DOMAIN, SLOTS, Domain, Item,
                         ItemFormat, Mode, SelfItem)

ROOT = Path(__file__).resolve().parent.parent
ITEMS_DIR = ROOT / "items"
IMAGES_DIR = ROOT / "assets" / "images"
SELF_REPORT = "self_report.json"
CALIBRATION = "calibration.json"


def balance_answer_positions(items: list[Item]) -> list[Item]:
    """정답 위치가 한쪽으로 몰리면 찍기가 유리해진다 (직접 쓴 문항은 작성자 습관으로 특히 그렇다).

    슬롯마다 동형 문항이 최선(정답) 위치 A~D를 돌아가며 갖도록 보기를 옮긴다. 최선·최악 문항은 최악 보기도 함께 따라간다.
    """
    out, by_slot = [], defaultdict(list)
    for it in items:
        by_slot[it.slot].append(it)
    for slot, group in by_slot.items():
        h = zlib.crc32(slot.encode())
        order = random.Random(h).sample(range(4), 4)
        for k, it in enumerate(sorted(group, key=lambda x: x.id)):
            best = it.answer if it.format is ItemFormat.MCQ else it.answer[0]
            target = order[k % 4]
            if it.format is ItemFormat.MCQ:
                rest = [i for i in range(len(it.choices)) if i != best]
                perm = rest[:target] + [best] + rest[target:]  # 새 위치 → 원래 인덱스
                out.append(replace(it, choices=[it.choices[i] for i in perm], answer=target,
                                   styles=[it.styles[i] for i in perm] if it.styles else []))
                continue
            worst = it.answer[1]
            free = [p for p in range(4) if p != target]
            worst_at = free[(k + h) % 3]  # 최악 보기도 슬롯 안에서 자리를 돌린다
            others = iter(i for i in range(4) if i not in (best, worst))
            perm = [best if p == target else worst if p == worst_at else next(others) for p in range(4)]
            out.append(replace(it, choices=[it.choices[i] for i in perm], answer=[target, worst_at],
                               styles=[it.styles[i] for i in perm] if it.styles else []))
    return out


def apply_calibration(items: list[Item], path: Path) -> list[Item]:
    if not path.exists():
        return items
    calib = json.loads(path.read_text(encoding="utf-8"))
    return [replace(it, **{k: v for k, v in calib[it.id].items() if k in ("irt_a", "irt_b", "irt_c")})
            if it.id in calib else it for it in items]


def load_items(items_dir: Path = ITEMS_DIR) -> list[Item]:
    items: list[Item] = []
    for path in sorted(items_dir.glob("*.json")):
        if path.name in (SELF_REPORT, CALIBRATION):
            continue
        items.extend(Item.from_dict(d) for d in json.loads(path.read_text(encoding="utf-8")))
    return apply_calibration(balance_answer_positions(items), items_dir / CALIBRATION)


def load_self_items(items_dir: Path = ITEMS_DIR) -> list[SelfItem]:
    path = items_dir / SELF_REPORT
    if not path.exists():
        return []
    return [SelfItem.from_dict(d) for d in json.loads(path.read_text(encoding="utf-8"))]


def _norm(text: str) -> str:
    return re.sub(r"[\s.,!?·…'\"“”‘’]", "", text)


def validate_bank(items: list[Item], strict: bool = False, images_dir: Path = IMAGES_DIR) -> list[str]:
    """문항은행 검증. strict=False면 문항 자체 오류와 중복만, True면 슬롯별 동형 수·영역 풀 크기까지."""
    errors = [f"[{it.id}] {e}" for it in items for e in it.validate()]

    counts = Counter(it.id for it in items)
    errors += [f"[{i}] 중복 ID" for i, n in counts.items() if n > 1]

    # 같은 상황을 두 번 쓰거나, 같은 영역에서 같은 문장을 정답으로 반복하면 동형 문항끼리 답이 새어 나간다
    seen_prompt: dict[str, str] = {}
    for it in items:
        key = _norm(it.prompt)
        if key in seen_prompt:
            errors.append(f"[{it.id}] 문제 문장이 {seen_prompt[key]} 와 같음")
        seen_prompt.setdefault(key, it.id)
    seen_answer: dict[tuple, str] = {}
    for it in items:
        best = it.answer if it.format is ItemFormat.MCQ else it.answer[0]
        if not isinstance(best, int) or not 0 <= best < len(it.choices):
            continue
        key = (it.domain, _norm(it.choices[best]))
        if key in seen_answer:
            errors.append(f"[{it.id}] 정답 보기가 {seen_answer[key]} 의 정답과 같음")
        seen_answer.setdefault(key, it.id)

    for it in items:
        if it.image and not (images_dir / it.image).exists():
            errors.append(f"[{it.id}] 이미지 파일 없음: {it.image}")

    if strict:
        by_slot = Counter(it.slot for it in items)
        for slot_id, slot in SLOTS.items():
            need = MIN_FORMS_FIXED if slot_id in FIXED_SLOTS else MIN_FORMS_POOL
            if by_slot[slot_id] < need:
                tag = " (이미지 대기 — 글 문항으로 대체 출제됨)" if slot.subtype in IMAGE_SUBTYPES else ""
                errors.append(f"[{slot_id}] 동형 {by_slot[slot_id]}개 / 필요 {need}개{tag}")
        errors += _substitute_capacity(items)
        pool = Counter(it.domain for it in items)
        for domain, spec in BLUEPRINT.items():
            if pool[domain] < spec.min_pool:
                errors.append(f"[{domain.value}] 문항 풀 {pool[domain]}개 / 필요 {spec.min_pool}개")
    return errors


def _substitute_capacity(items: list[Item]) -> list[str]:
    """이미지 문항이 없는 슬롯은 같은 난이도의 글 문항으로 대체되므로, 정밀 검사 1·2·3차를 겹치지 않게 치를 만큼
    난이도별 글 문항이 있는지 확인한다 (이미지가 준비되면 자동으로 통과)."""
    errors = []
    filled = {it.slot for it in items}
    for domain, spec in BLUEPRINT.items():
        empty = [s for s in spec.full if s not in filled and SLOTS[s].subtype in IMAGE_SUBTYPES]
        for level in sorted({SLOTS[s].difficulty for s in empty}):
            need = sum(1 for s in spec.full if SLOTS[s].difficulty == level) * MIN_FORMS_FIXED
            have = sum(1 for it in items if it.domain is domain and it.difficulty == level and it.slot in filled
                       and it.subtype not in IMAGE_SUBTYPES)
            if have < need:
                errors.append(f"[{domain.value}] 난이도 {level} 글 문항 {have}개 / 이미지 대체 포함 {need}개 필요 (이미지 대기)")
    return errors


def validate_self_items(items: list[SelfItem], strict: bool = False) -> list[str]:
    errors = [f"[{it.id}] {e}" for it in items for e in it.validate()]
    counts = Counter(it.id for it in items)
    errors += [f"[{i}] 중복 ID" for i, n in counts.items() if n > 1]
    if strict:
        for d in Domain:
            mine = [it for it in items if it.domain is d]
            if len(mine) != SELF_PER_DOMAIN:
                errors.append(f"[sr-{d.value}] 자기보고 {len(mine)}개 / 필요 {SELF_PER_DOMAIN}개")
            if sum(it.reverse for it in mine) < SELF_MIN_REVERSE:
                errors.append(f"[sr-{d.value}] 역문항 {SELF_MIN_REVERSE}개 이상 필요")
        n_check = sum(it.check for it in items)
        if n_check != SELF_CHECKS:
            errors.append(f"[sr-check] 점검 문항 {n_check}개 / 필요 {SELF_CHECKS}개")
    return errors


def validate_blueprint() -> list[str]:
    """구성표 규칙.

    - 영역마다 유형 4~5개, 고정 구성의 슬롯은 모두 영역 풀에 있고 쉬운 문제부터 놓인다
    - 정밀: 8문항, 난이도 1·2·2·2·3·3·3·4, 같은 유형 최대 MAX_SAME_TYPE번
    - 빠른: 정밀 구성의 부분집합, 난이도 1~4 하나씩, 모두 다른 유형
    """
    errors = []
    for domain, spec in BLUEPRINT.items():
        tag = f"[{domain.value}]"
        if not 4 <= len(spec.subtypes) <= 5:
            errors.append(f"{tag} 유형 {len(spec.subtypes)}개 (4~5개)")
        if not all(s.startswith(domain.value + "-") for s in spec.full + spec.quick):
            errors.append(f"{tag} 다른 영역 슬롯이 섞임")
        for mode in Mode:
            form = spec.form_for(mode)
            mtag = f"[{domain.value}/{mode.value}]"
            errors += [f"{mtag} 풀에 없는 슬롯 {x}" for x in form if x not in spec.pool]
            if len(set(form)) != len(form):
                errors.append(f"{mtag} 같은 슬롯이 두 번")
            levels = [SLOTS[x].difficulty for x in form if x in SLOTS]
            if levels != sorted(levels):
                errors.append(f"{mtag} 쉬운 문제부터 놓이지 않음 {levels}")
            types = Counter(SLOTS[x].subtype for x in form if x in SLOTS)
            limit = 1 if mode is Mode.QUICK else MAX_SAME_TYPE
            errors += [f"{mtag} {t} {n}회" for t, n in types.items() if n > limit]
        if [SLOTS[x].difficulty for x in spec.full] != [1, 2, 2, 2, 3, 3, 3, 4]:
            errors.append(f"{tag} 정밀 난이도 구성이 1·2·2·2·3·3·3·4가 아님")
        if sorted(SLOTS[x].difficulty for x in spec.quick) != [1, 2, 3, 4]:
            errors.append(f"{tag} 빠른 검사 난이도가 1~4 하나씩이 아님")
        if not set(spec.quick) <= set(spec.full):
            errors.append(f"{tag} 빠른 구성이 정밀 구성의 부분집합이 아님")
    return errors


def items_by_slot(items: list[Item]) -> dict[str, list[Item]]:
    out: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        out[it.slot].append(it)
    return out


def _substitute(pool: dict[str, list[Item]], slot_id: str, form_slots: tuple[str, ...], used: set[str],
                exclude, rng) -> Item | None:
    """슬롯에 문항이 하나도 없을 때(주로 이미지 대기) 같은 영역·난이도의 다른 글 유형에서 대신 고른다.

    같은 검사지의 다른 슬롯과 문항이 겹치지 않도록 고정 구성 밖의 슬롯(심층검사용)을 먼저 쓴다.
    """
    slot = SLOTS[slot_id]
    others = [s for s in BLUEPRINT[Domain(slot_id.split("-")[0])].pool
              if SLOTS[s].difficulty == slot.difficulty and s != slot_id and SLOTS[s].subtype not in IMAGE_SUBTYPES]
    for group in ([s for s in others if s not in form_slots], [s for s in others if s in form_slots]):
        left = {s: [it for it in pool.get(s, []) if it.id not in exclude and it.id not in used] for s in group}
        left = {s: v for s, v in left.items() if v}
        if left:
            # 남은 문항이 가장 많은 슬롯에서 가져와, 한 슬롯이 먼저 바닥나 뒤 차수에서 문항이 겹치지 않게 한다
            most = max(len(v) for v in left.values())
            slot = rng.choice(sorted(s for s, v in left.items() if len(v) == most))
            return rng.choice(sorted(left[slot], key=lambda it: it.id))
    return None


def build_form(items: list[Item], seed: int, mode: Mode = Mode.FULL,
               exclude: set[str] | frozenset[str] = frozenset()) -> dict[Domain, list[Item]]:
    """시드로 슬롯마다 동형 문항을 골라 1·2·3차 검사지를 만든다 (구성은 모두 같고 문항만 다름).

    - exclude: 앞 차수에서 이미 본 문항 ID (차수끼리 겹치지 않게)
    - 슬롯에 문항이 없으면 같은 영역·난이도의 글 문항으로 대체하고, 그것도 없으면 건너뛴다 (개발 중 부분 문항은행 허용)
    """
    rng = random.Random(seed)
    pool = items_by_slot(items)
    form = {}
    for domain, spec in BLUEPRINT.items():
        slots = spec.form_for(mode)
        chosen: dict[str, Item] = {}
        # 문항이 있는 슬롯을 먼저 채우고, 빈 슬롯의 대체 문항은 그 뒤에 골라 같은 검사지 안에서 겹치지 않게 한다
        for sid in slots:
            if pool.get(sid):
                cands = [it for it in pool[sid] if it.id not in exclude] or pool[sid]
                chosen[sid] = rng.choice(sorted(cands, key=lambda it: it.id))
        for sid in slots:
            if sid not in chosen:
                used = {it.id for it in chosen.values()}
                if (sub := _substitute(pool, sid, slots, used, exclude, rng)) is not None:
                    chosen[sid] = sub
        picked = [chosen[s] for s in slots if s in chosen]
        if picked:
            form[domain] = picked
    return form


# ---------------------------------------------------------------- 문항 품질 점검 (경고)

# 오답이 '나쁜 행동'이면 감정 능력이 아니라 예의·상식으로 풀린다 → 보기는 모두 괜찮은 행동·감정이어야 한다
OBVIOUS_WRONG = ("화를 내", "화를 낸", "소리를 지르", "소리친", "소리를 질", "욕을", "욕한", "무시한", "복수", "때리",
                 "던지", "험담", "비꼬", "따진다", "따지", "모른 척", "못 들은 척", "거짓말", "정색", "핀잔", "고함")


def lint_items(items: list[Item]) -> list[str]:
    """출제 품질 경고: (1) 오답에 뻔히 나쁜 행동이 있음 (2) 정답 보기만 유독 김 (길이로 정답이 드러남)."""
    warnings = []
    for it in items:
        key = it.answer if it.format is ItemFormat.MCQ else it.answer[0]
        worst = None if it.format is ItemFormat.MCQ else it.answer[1]
        for i, c in enumerate(it.choices):
            if i == key:
                continue
            hits = [w for w in OBVIOUS_WRONG if w in c]
            if hits and i != worst:
                warnings.append(f"[{it.id}] 오답 {'ABCD'[i]}에 뻔한 나쁜 행동 표현: {', '.join(hits)}")
        others = [len(c) for i, c in enumerate(it.choices) if i != key]
        if len(it.choices[key]) > 1.4 * max(others) and len(it.choices[key]) - max(others) >= 8:
            warnings.append(f"[{it.id}] 정답 보기만 유독 김 ({len(it.choices[key])}자 vs 최대 {max(others)}자)")
    return warnings
