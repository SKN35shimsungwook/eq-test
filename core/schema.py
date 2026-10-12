"""문항 스키마와 검사 구성(영역·유형·문항 수·제한시간) 정의.

구조는 iq-test와 같다: 영역마다 4유형 × 4난이도 = 16슬롯, 정밀은 8슬롯 · 빠른은 4슬롯 고정 구성,
1·2·3차는 같은 구성에 겹치지 않는 동형 문항, 3차 뒤 심층검사는 영역의 모든 슬롯에서 맞춤 출제.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Domain(str, Enum):
    PER = "per"  # 감정 인식
    UND = "und"  # 감정 이해
    USE = "use"  # 감정 활용
    REG = "reg"  # 감정 조절
    REL = "rel"  # 대인관계·공감
    CRI = "cri"  # 위기 대처
    CTX = "ctx"  # 맥락 파악


class ItemFormat(str, Enum):
    MCQ = "mcq"                # 4지선다: 가장 알맞은 것 하나
    BEST_WORST = "best_worst"  # 4지선다에서 가장 효과적인 것과 가장 덜 효과적인 것을 함께 고름 (둘 다 맞아야 정답)


class Mode(str, Enum):
    QUICK = "quick"  # 영역별 4문항 (난이도 1~4, 유형 모두 다름)
    FULL = "full"    # 영역별 8문항


MODE_LABELS = {Mode.QUICK: "빠른 검사", Mode.FULL: "정밀 검사"}
MAX_ROUNDS = 3      # 1·2·3차 검증
DEEP_ROUND = 4      # 3차 뒤 심층검사의 차수 번호 (sessions.round)
MAX_SAME_TYPE = 2   # 한 검사지·한 영역 안에서 같은 유형 최대 출제 수

# 동형 문항 수: 문항을 직접 쓰므로 1·2·3차가 겹치지 않는 최소량으로 정한다
MIN_FORMS_FIXED = 3  # 고정 구성(정밀·빠른)에 들어가는 슬롯: 1·2·3차에 하나씩
MIN_FORMS_POOL = 2   # 나머지 슬롯: 심층검사용
MIN_DOMAIN_POOL = 40  # 8 × 3 + 8 × 2

# 심층검사 종료 조건 (iq-test 시뮬레이션 기준값, EQ 문항으로 다시 시뮬레이션해 조정)
DEEP_TARGET_SE = 0.33
DEEP_MIN_ITEMS = 3
DEEP_MAX_ITEMS = 6
DEEP_SEC_PER_ITEM = 75

# 위기 대처는 영역 제한시간 대신 문항마다 짧은 제한시간 (읽기 + 순간 판단)
CRISIS_SEC = {1: 25, 2: 25, 3: 35, 4: 35}  # 평균 130자 안팎 읽기 + 판단 (최선·최악은 두 번 고름)

DIFFICULTY_LABELS = {1: "쉬움", 2: "보통", 3: "어려움", 4: "매우 어려움"}
EXPECTED_P = {1: 0.85, 2: 0.65, 3: 0.45, 4: 0.25}  # 난이도별 기본 예상 정답률
FORMAT_BY_LEVEL = {1: ItemFormat.MCQ, 2: ItemFormat.MCQ, 3: ItemFormat.BEST_WORST, 4: ItemFormat.BEST_WORST}

# 이미지가 필요한 유형. 이미지가 준비되지 않으면 같은 영역·난이도의 글 문항으로 대체 출제한다.
IMAGE_SUBTYPES = {"face", "scene"}


def round_label(n: int) -> str:
    return "심층검사" if n == DEEP_ROUND else f"{n}차 검증"


@dataclass(frozen=True)
class SlotSpec:
    id: str          # "영역-유형-난이도", 예: "und-blend-3"
    subtype: str
    difficulty: int  # 1~4


@dataclass(frozen=True)
class DomainSpec:
    label: str
    subtypes: dict[str, str]       # 유형 ID → 화면 이름 (4개)
    full: tuple[str, ...]          # 정밀 검사 고정 구성 (쉬운 문제부터)
    quick: tuple[str, ...]         # 빠른 검사 고정 구성 (정밀 구성의 부분집합, 난이도 1~4 하나씩)
    time_full: int                 # 영역 제한시간(초), 0이면 문항마다 제한시간
    time_quick: int = 0

    def form_for(self, mode: Mode) -> tuple[str, ...]:
        return self.full if mode is Mode.FULL else self.quick

    def time_for(self, mode: Mode) -> int:
        return self.time_full if mode is Mode.FULL else self.time_quick

    @property
    def pool(self) -> tuple[str, ...]:
        return tuple(f"{self._code}-{t}-{lv}" for t in self.subtypes for lv in range(1, 5))

    @property
    def _code(self) -> str:
        return self.full[0].split("-")[0]


def _ids(d: str, text: str) -> tuple[str, ...]:
    """"cause1 blend3" 같은 짧은 표기를 슬롯 ID로 바꾼다."""
    return tuple(f"{d}-{tok[:-1]}-{tok[-1]}" for tok in text.split())


# 검사 구성표 (영역 순서 = 출제 순서). 정밀: 쉬움 1 · 보통 3 · 어려움 3 · 매우 어려움 1, 같은 유형 최대 2번.
# 빠른: 정밀 구성 중 난이도 1~4 하나씩, 유형 모두 다름 (빠른 슬롯도 1·2·3차 동형이 정밀 슬롯과 같이 준비됨).
BLUEPRINT: dict[Domain, DomainSpec] = {
    Domain.PER: DomainSpec(
        "감정 인식",
        {"message": "문자·대화 말투", "behavior": "행동·몸짓 묘사", "face": "얼굴 이미지", "scene": "풍경·추상 이미지"},
        full=_ids("per", "message1 behavior2 face2 scene2 message3 face3 behavior3 scene4"),
        quick=_ids("per", "message1 face2 behavior3 scene4"),
        time_full=4 * 60, time_quick=2 * 60),
    Domain.UND: DomainSpec(
        "감정 이해",
        {"cause": "상황과 감정", "change": "감정 변화", "blend": "복합 감정", "nuance": "비슷한 감정 구분"},
        full=_ids("und", "cause1 change2 blend2 nuance2 cause3 blend3 change3 nuance4"),
        quick=_ids("und", "cause1 blend2 change3 nuance4"),
        time_full=5 * 60, time_quick=150),
    Domain.USE: DomainSpec(
        "감정 활용",
        {"task_mood": "일에 맞는 기분", "mood_effect": "기분이 판단에 주는 영향", "sensation": "감정과 감각 연결",
         "motivate": "감정을 동기로 쓰기"},
        full=_ids("use", "task_mood1 mood_effect2 sensation2 motivate2 task_mood3 mood_effect3 motivate3 sensation4"),
        quick=_ids("use", "task_mood1 motivate2 mood_effect3 sensation4"),
        time_full=4 * 60, time_quick=2 * 60),
    Domain.REG: DomainSpec(
        "감정 조절",
        {"reappraisal": "관점 바꾸기", "impulse": "충동이 이는 순간", "setback": "실패·좌절 후 회복",
         "stress": "오래가는 스트레스"},
        full=_ids("reg", "reappraisal1 impulse2 setback2 stress2 reappraisal3 impulse3 setback3 stress4"),
        quick=_ids("reg", "reappraisal1 impulse2 setback3 stress4"),
        time_full=5 * 60, time_quick=150),
    Domain.REL: DomainSpec(
        "대인관계·공감",
        {"comfort": "위로·지지", "conflict": "갈등", "feedback": "어려운 말 전하기", "boundary": "거절·경계 지키기"},
        full=_ids("rel", "comfort1 conflict2 feedback2 boundary2 comfort3 conflict3 feedback3 boundary4"),
        quick=_ids("rel", "comfort1 feedback2 conflict3 boundary4"),
        time_full=5 * 60, time_quick=150),
    Domain.CRI: DomainSpec(
        "위기 대처",
        {"escalation": "폭발 직전의 상대", "emergency": "돌발 사고", "public": "여럿 앞의 압박",
         "dilemma": "시간에 쫓기는 선택"},
        full=_ids("cri", "escalation1 emergency2 public2 dilemma2 escalation3 emergency3 public3 dilemma4"),
        quick=_ids("cri", "escalation1 emergency2 public3 dilemma4"),
        time_full=0),
    Domain.CTX: DomainSpec(
        "맥락 파악",
        {"sarcasm": "비꼼·농담", "indirect": "돌려 말하기", "atmosphere": "분위기 읽기", "unspoken": "말하지 않은 규칙"},
        full=_ids("ctx", "sarcasm1 indirect2 atmosphere2 unspoken2 sarcasm3 indirect3 atmosphere3 unspoken4"),
        quick=_ids("ctx", "sarcasm1 indirect2 atmosphere3 unspoken4"),
        time_full=5 * 60, time_quick=150),
}


def _slot(slot_id: str) -> SlotSpec:
    _, subtype, level = slot_id.rsplit("-", 2)
    return SlotSpec(slot_id, subtype, int(level))


SLOTS: dict[str, SlotSpec] = {i: _slot(i) for spec in BLUEPRINT.values() for i in spec.pool}
FIXED_SLOTS: set[str] = {i for spec in BLUEPRINT.values() for m in Mode for i in spec.form_for(m)}


@dataclass
class Item:
    id: str                  # 예: "und-blend-3a" (슬롯 und-blend-3의 동형 a)
    domain: Domain
    slot: str
    format: ItemFormat
    subtype: str
    difficulty: int          # 1~4
    prompt: str              # 상황 + 질문
    choices: list[str]
    answer: Any              # MCQ: 보기 인덱스, BEST_WORST: [가장 효과적, 가장 덜 효과적]
    explanation: str = ""    # 응시자에게 보여 줄 해설
    rationale: str = ""      # 정답 근거 이론 (검토·관리용, 응시자에게는 안 보임)
    image: str = ""          # 이미지 문항: assets/images/ 아래 파일 이름
    time_limit: int = 0      # 문항 제한시간(초), 0이면 영역 제한시간
    expected_p: float = 0.5
    version: int = 1
    irt_a: float | None = None
    irt_b: float | None = None
    irt_c: float | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        """영역·유형·난이도·형식·예상 정답률·위기 대처 제한시간은 생략하면 슬롯 정의에서 채운다."""
        d = dict(d)
        slot = SLOTS.get(d["slot"])
        if slot:
            d.setdefault("domain", d["slot"].split("-")[0])
            d.setdefault("subtype", slot.subtype)
            d.setdefault("difficulty", slot.difficulty)
            d.setdefault("format", FORMAT_BY_LEVEL[slot.difficulty].value)
            d.setdefault("expected_p", EXPECTED_P[slot.difficulty])
            if d["domain"] == Domain.CRI.value:
                d.setdefault("time_limit", CRISIS_SEC[slot.difficulty])
        d["domain"] = Domain(d["domain"])
        d["format"] = ItemFormat(d.get("format", "mcq"))
        return cls(**d)

    def validate(self) -> list[str]:
        """문항 자체의 형식 오류 목록 (비어 있으면 통과)."""
        errors = []
        slot = SLOTS.get(self.slot)
        if slot is None:
            errors.append(f"구성표에 없는 slot '{self.slot}'")
        elif (self.subtype, self.difficulty) != (slot.subtype, slot.difficulty):
            errors.append(f"유형·난이도 {self.subtype}/{self.difficulty} 가 슬롯 정의와 다름")
        if self.difficulty in FORMAT_BY_LEVEL and self.format is not FORMAT_BY_LEVEL[self.difficulty]:
            errors.append(f"난이도 {self.difficulty} 는 {FORMAT_BY_LEVEL[self.difficulty].value} 형식이어야 함")
        if not self.id.startswith(self.slot):
            errors.append(f"id '{self.id}' 가 slot '{self.slot}' 으로 시작하지 않음")
        if not 0 < self.expected_p < 1:
            errors.append(f"expected_p {self.expected_p} 는 0~1 사이여야 함")
        if not self.prompt.strip():
            errors.append("prompt 비어 있음")
        if len(self.choices) != 4:
            errors.append(f"보기 {len(self.choices)}개 (4개 필요)")
        if len({c.strip() for c in self.choices}) != len(self.choices):
            errors.append("중복된 보기가 있음")
        n = len(self.choices)
        if self.format is ItemFormat.MCQ:
            if not isinstance(self.answer, int) or not 0 <= self.answer < n:
                errors.append(f"answer {self.answer!r} 가 보기 인덱스 범위 밖")
        else:
            ok = (isinstance(self.answer, list) and len(self.answer) == 2
                  and all(isinstance(a, int) and 0 <= a < n for a in self.answer) and self.answer[0] != self.answer[1])
            if not ok:
                errors.append(f"answer {self.answer!r} 는 [최선, 최악] 서로 다른 보기 인덱스여야 함")
        if not self.explanation.strip():
            errors.append("해설(explanation) 없음")
        if not self.rationale.strip():
            errors.append("정답 근거(rationale) 없음")
        if self.subtype in IMAGE_SUBTYPES and not self.image:
            errors.append("이미지 유형인데 image 없음")
        if self.domain is Domain.CRI and self.time_limit <= 0:
            errors.append("위기 대처 문항은 time_limit 필요")
        return errors

    def is_correct(self, response: Any) -> bool:
        """응답 채점. MCQ는 보기 인덱스, BEST_WORST는 [최선, 최악]."""
        if response is None:
            return False
        if self.format is ItemFormat.MCQ:
            return response == self.answer
        return list(response) == list(self.answer)


# ---------------------------------------------------------------- 자기보고

SELF_SCALE = {1: "전혀 아니다", 2: "아니다", 3: "보통이다", 4: "그렇다", 5: "매우 그렇다"}
SELF_PER_DOMAIN = 4   # 영역당 자기보고 문항
SELF_MIN_REVERSE = 1  # 영역당 최소 역문항 (모두 "그렇다"로 답하는 습관 방지)
SELF_CHECKS = 4       # 지나치게 좋게만 답하는지 보는 점검 문항


@dataclass
class SelfItem:
    """1차 검증 전에 한 번 묻는 자기평가. EQ 점수에는 섞지 않고 '내가 보는 나 vs 실제 수행' 비교에 쓴다."""
    id: str                  # 예: "sr-reg-2", 점검 문항은 "sr-check-1"
    text: str
    domain: Domain | None = None  # 점검 문항은 None
    reverse: bool = False    # 역문항: 점수 = 6 − 응답
    check: bool = False      # 점검 문항: 거의 아무도 "매우 그렇다"일 수 없는 진술 (예: 한 번도 짜증 낸 적이 없다)
    version: int = 1

    @classmethod
    def from_dict(cls, d: dict) -> "SelfItem":
        d = dict(d)
        if d.get("domain"):
            d["domain"] = Domain(d["domain"])
        return cls(**d)

    def score(self, response: int) -> int:
        return 6 - response if self.reverse else response

    def validate(self) -> list[str]:
        errors = []
        if not self.text.strip():
            errors.append("text 비어 있음")
        if self.check and self.domain is not None:
            errors.append("점검 문항은 domain 없음")
        if not self.check and self.domain is None:
            errors.append("domain 필요")
        if self.check and self.reverse:
            errors.append("점검 문항은 역문항이 아님")
        return errors
