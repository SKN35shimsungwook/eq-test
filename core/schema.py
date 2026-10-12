"""문항 스키마와 검사 구성(영역·유형·문항 수·제한시간) 정의.

구조는 iq-test와 같다: 영역마다 4~5유형 × 4난이도 슬롯, 정밀은 8슬롯 · 빠른은 4슬롯 고정 구성,
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
    CON = "con"  # 관계 갈등 (배신·소외·가족·연애·새 환경 적응)
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
MIN_DOMAIN_POOL = 40  # 4유형 영역 기준 8 × 3 + 8 × 2 (5유형 영역은 DomainSpec.min_pool)

# 심층검사 종료 조건 (iq-test 시뮬레이션 기준값, EQ 문항으로 다시 시뮬레이션해 조정)
DEEP_TARGET_SE = 0.33
DEEP_MIN_ITEMS = 3
DEEP_MAX_ITEMS = 6
DEEP_SEC_PER_ITEM = 75

# 위기 대처는 영역 제한시간 대신 문항마다 짧은 제한시간 (읽기 + 순간 판단)
# 위기 대처: 상황은 시간 제한 없이 읽고, 보기를 연 뒤부터 이 시간 안에 고른다 (보기 70~80자 읽기 + 판단).
# 읽기 속도까지 재던 예전 방식(문제+보기 25·35초)은 시간 초과 19~24%였다 (docs/11).
CRISIS_SEC = {1: 25, 2: 25, 3: 30, 4: 30}

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

    @property
    def min_pool(self) -> int:
        """1·2·3차 고정 슬롯은 동형 3개, 나머지 슬롯은 2개."""
        fixed = set(self.full) | set(self.quick)
        return sum(MIN_FORMS_FIXED if s in fixed else MIN_FORMS_POOL for s in self.pool)


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
    Domain.CON: DomainSpec(
        "관계 갈등",
        {"adapt": "새 환경 적응", "betrayal": "배신·신뢰 깨짐", "exclusion": "소외", "family": "가족 갈등",
         "romance": "연애 갈등"},
        full=_ids("con", "adapt1 betrayal2 family2 romance2 exclusion3 betrayal3 family3 romance4"),
        quick=_ids("con", "adapt1 family2 exclusion3 romance4"),
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


# ---------------------------------------------------------------- 선택 유형 (보기마다 붙는 대처·해석 방식)
#
# 보기 4개가 모두 '괜찮은' 반응이 되도록 쓰고, 보기마다 어떤 방식인지 표시한다. 정답과 별개로
# 무엇을 골랐는지 모아 영역별 유형과 종합 프로필을 만든다 (core/style.py).
# 행동 영역의 유형은 세 축에 점수를 준다: A 감정 중심(+)↔문제 중심(−), B 다가감(+)↔거리 둠(−), C 표현(+)↔절제(−)
# 해석 영역(인식·이해·맥락)의 유형은 '잘못 읽을 때의 경향'이라 축에 넣지 않고 따로 보여 준다. acc = 정확한 해석.

@dataclass(frozen=True)
class StyleSpec:
    name: str
    desc: str
    axes: tuple[int, int, int] = (0, 0, 0)


STYLES: dict[Domain, dict[str, StyleSpec]] = {
    Domain.PER: {
        "acc": StyleSpec("정확형", "단서를 고르게 보고 감정을 정확히 읽는다"),
        "pos": StyleSpec("좋게 읽는 형", "상대의 감정을 실제보다 밝게 읽는 편"),
        "neg": StyleSpec("어둡게 읽는 형", "상대의 감정을 실제보다 무겁거나 부정적으로 읽는 편"),
        "lit": StyleSpec("겉으로 읽는 형", "말이나 표정의 겉모습을 그대로 받아들이는 편"),
    },
    Domain.UND: {
        "acc": StyleSpec("정확형", "감정이 생긴 원인과 세기를 정확히 짚는다"),
        "over": StyleSpec("크게 읽는 형", "감정을 실제보다 강하거나 무겁게 보는 편"),
        "under": StyleSpec("가볍게 읽는 형", "감정을 실제보다 약하거나 단순하게 보는 편"),
        "shift": StyleSpec("원인을 달리 보는 형", "감정이 생긴 원인을 다른 데서 찾는 편"),
    },
    Domain.USE: {
        "tune": StyleSpec("맞춤형", "할 일에 맞게 기분을 조절한다", (-1, 0, -1)),
        "ride": StyleSpec("몰입형", "지금의 감정을 그대로 살려 쓴다", (1, 0, 1)),
        "check": StyleSpec("점검형", "감정이 판단을 흐리지 않는지 먼저 의심한다", (-1, 0, -1)),
        "drive": StyleSpec("동력형", "감정을 행동의 힘으로 바꾼다", (0, 0, 1)),
    },
    Domain.REG: {
        "reframe": StyleSpec("관점전환형", "상황을 다르게 해석해 마음을 다스린다", (0, 0, -1)),
        "express": StyleSpec("표현형", "털어놓거나 적으며 감정을 밖으로 낸다", (1, 1, 1)),
        "pause": StyleSpec("거리두기형", "시간을 두거나 주의를 돌려 가라앉힌다", (0, -1, -1)),
        "act": StyleSpec("행동형", "원인을 해결하거나 몸을 움직여 푼다", (-1, 0, 0)),
    },
    Domain.REL: {
        "empath": StyleSpec("공감형", "상대의 감정을 먼저 받아 준다", (1, 1, 0)),
        "solve": StyleSpec("해결형", "실질적인 도움과 해결책을 건넨다", (-1, 1, 0)),
        "respect": StyleSpec("존중형", "상대의 속도와 선택을 존중하며 기다린다", (0, -1, -1)),
        "honest": StyleSpec("솔직형", "내 생각과 마음을 분명히 말한다", (0, 1, 1)),
    },
    Domain.CON: {
        "talk": StyleSpec("대화형", "당사자와 직접 이야기해 푼다", (0, 1, 1)),
        "accept": StyleSpec("수용형", "상대 사정을 이해하고 너그럽게 넘긴다", (1, 1, -1)),
        "guard": StyleSpec("경계형", "선을 긋고 나를 지킨다", (0, -1, 0)),
        "bridge": StyleSpec("연결형", "다른 사람·관계망의 도움으로 푼다", (-1, 0, 0)),
    },
    Domain.CRI: {
        "calm": StyleSpec("정리형", "멈추고 상황부터 파악한다", (-1, 0, -1)),
        "act": StyleSpec("즉시행동형", "바로 움직여 조치한다", (-1, 0, 1)),
        "ally": StyleSpec("협력형", "알리고 도움을 모은다", (0, 1, 1)),
        "protect": StyleSpec("보호형", "사람의 마음과 안전부터 챙긴다", (1, 1, 0)),
    },
    Domain.CTX: {
        "acc": StyleSpec("정확형", "말과 상황을 함께 보고 숨은 뜻을 정확히 읽는다"),
        "lit": StyleSpec("겉말형", "말을 문자 그대로 받아들이는 편"),
        "sus": StyleSpec("의심형", "없는 숨은 뜻까지 읽어 내는 편"),
        "pos": StyleSpec("좋게 보는 형", "애매한 말을 좋은 쪽으로 해석하는 편"),
    },
}
READING_DOMAINS = {Domain.PER, Domain.UND, Domain.CTX}  # 정확형(acc) + 잘못 읽는 경향


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
    styles: list[str] = field(default_factory=list)  # 보기마다의 선택 유형 코드 (STYLES), 개념 문항은 비움
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
        if self.styles:
            codes = STYLES.get(self.domain, {})
            if len(self.styles) != len(self.choices):
                errors.append(f"styles {len(self.styles)}개 (보기 수와 같아야 함)")
            bad = [c for c in self.styles if c not in codes]
            if bad:
                errors.append(f"정의되지 않은 유형 {bad}")
            if self.domain in READING_DOMAINS and self.styles:
                key = self.answer if self.format is ItemFormat.MCQ else (self.answer[0] if isinstance(self.answer, list) else None)
                if isinstance(key, int) and 0 <= key < len(self.styles) and self.styles[key] != "acc":
                    errors.append("해석 영역의 정답 보기는 유형 acc여야 함")
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
FINAL_DESIRE = 4      # 마지막 질문: 누구나 있는 욕구를 부정하는지 (좋게 보이려는 경향)
FINAL_REPEAT = 4      # 마지막 질문: 시작 자기평가 문항을 반대로 바꿔 다시 묻기 (일관성)


@dataclass
class SelfItem:
    """1차 검증 전에 한 번 묻는 자기평가. EQ 점수에는 섞지 않고 '내가 보는 나 vs 실제 수행' 비교에 쓴다."""
    id: str                  # 예: "sr-reg-2", 점검 문항은 "sr-check-1"
    text: str
    domain: Domain | None = None  # 점검 문항은 None
    reverse: bool = False    # 역문항: 점수 = 6 − 응답
    check: bool = False      # 점검 문항: 거의 아무도 "매우 그렇다"일 수 없는 진술 (예: 한 번도 짜증 낸 적이 없다)
    kind: str = ""           # 마지막 질문만: "desire"(욕구 부정) | "repeat"(시작 자기평가 다시 묻기)
    pair: str | None = None  # repeat: 짝이 되는 시작 자기평가 문항 ID
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
        if self.kind not in ("", "desire", "repeat"):
            errors.append(f"kind 오류: {self.kind}")
        if (self.check or self.kind) and self.domain is not None:
            errors.append("점검·마지막 질문은 domain 없음")
        if not (self.check or self.kind) and self.domain is None:
            errors.append("domain 필요")
        if (self.check or self.kind == "desire") and self.reverse:
            errors.append("점검·욕구 문항은 역문항이 아님")
        if (self.kind == "repeat") != bool(self.pair):
            errors.append("repeat 문항에만 pair 필요")
        return errors
