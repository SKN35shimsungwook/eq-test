# EQ 감성지수 테스트

감정을 알아차리고, 이해하고, 활용하고, 다루는 힘을 7개 영역에서 측정하는 Streamlit 앱입니다.
정답이 있는 **상황 판단 검사**로 EQ(평균 100, 표준편차 15)를 내고, 시작 전 **자기평가**와 비교해
"내가 보는 나 vs 실제 수행"을 보여 줍니다. 구조는 자매 프로젝트 [iq-test](https://github.com/SKN35shimsungwook/iq-test)와 같습니다.

**자세한 문서는 [docs/](docs/README.md)에 있습니다** — 연구 정리, 개발 과정, 응시자·운영자·개발자 가이드, 검증 기록, 채점 원리, 이미지 문항 제작.

> 온라인 정서 역량 테스트이며, 표준화된 전문 심리검사를 대체하지 않습니다.

## 측정 영역

| 영역 | 문제 유형 (영역마다 4유형 × 난이도 4단계) |
|---|---|
| 감정 인식 | 문자·대화 말투 · 행동·몸짓 묘사 · 얼굴 이미지 · 풍경·추상 이미지 |
| 감정 이해 | 상황과 감정 · 감정 변화 · 복합 감정 · 비슷한 감정 구분 |
| 감정 활용 | 일에 맞는 기분 · 기분이 판단에 주는 영향 · 감정과 감각 연결 · 감정을 동기로 쓰기 |
| 감정 조절 | 관점 바꾸기 · 충동이 이는 순간 · 실패·좌절 후 회복 · 오래가는 스트레스 |
| 대인관계·공감 | 위로·지지 · 갈등 · 어려운 말 전하기 · 거절·경계 지키기 |
| 위기 대처 | 폭발 직전의 상대 · 돌발 사고 · 여럿 앞의 압박 · 시간에 쫓기는 선택 (문항마다 25~35초) |
| 맥락 파악 | 비꼼·농담 · 돌려 말하기 · 분위기 읽기 · 말하지 않은 규칙 |

## 검사 구성

| | 빠른 검사 | 정밀 검사 |
|---|---|---|
| 시간 | 약 20분 | 약 40분 |
| 영역당 문항 | 4 (난이도 1~4 하나씩, 유형 모두 다름) | 8 (쉬움 1 · 보통 3 · 어려움 3 · 매우 어려움 1) |
| 전체 | 28문항 | 56문항 |

- **응답 형식**: 쉬움·보통은 4지선다, 어려움·매우 어려움은 **✓ 가장 맞음**과 **✗ 가장 아님**을 함께 골라 둘 다 맞아야 정답
- **자기평가**: 1차 전 한 번, 영역당 4문항(역문항 포함) + 응답 점검 4문항. EQ 점수에는 섞지 않음
- **1·2·3차 검증**: 같은 구성, 겹치지 않는 새 문제. 3차 뒤 **심층검사**(실력에 맞춘 맞춤형 출제)
- **점수**: 3PL IRT + EAP → EQ. 실제 첫 응시 100명 전에는 봇 2만 명(모드별) 시뮬레이션 규준
- **결과**: EQ·90% 범위·상위 %·수준, 차수별 탭, 영역 프로필, 강점, 자기평가 비교, 키우는 방법, 결과 카드

## 현재 상태

| 항목 | 상태 |
|---|---|
| 문항 | 267개 + 자기평가 32개 (감정 인식의 얼굴·풍경 **이미지 20장 대기**, 그동안 같은 난이도 글 문항으로 대체 출제) |
| 검사·결과·관리자 화면 | 완료 |
| 시뮬레이션 규준 | `norms/sim_norms.json` (모드별 2만 명) |
| 테스트 | 33개 통과 |
| 배포 | [DEPLOY.md](DEPLOY.md) 절차 대기 |

## 실행

```bash
pip install -r requirements-dev.txt
streamlit run streamlit_app.py
python -m pytest -q
python scripts/validate_items.py --strict     # 문항 검증 (출시 기준)
python scripts/render_review.py               # 문항 검토 화면 → review/items_review.html
python scripts/simulate.py --n 600            # 가상 응시 데이터 (관리자 화면 확인용, 로컬)
python scripts/build_sim_norms.py --n 20000 --workers 8   # 시뮬레이션 규준 다시 만들기
```

관리자 페이지를 쓰려면 `.streamlit/secrets.toml.example`을 `secrets.toml`로 복사해 `admin_password`를 정합니다.
Supabase를 연결하지 않으면 `data/eq_test.db`(SQLite)에 저장됩니다.

## 구조

```
streamlit_app.py      내비게이션
app_pages/            시작 · 검사 · 결과 · 관리자 분석
core/                 schema, item_bank, exam, scoring, report, charts, components, analysis, db, runtime
items/                영역별 문항 JSON, self_report.json
norms/                시뮬레이션 규준표
scripts/              items_<영역>.py(문항 작성), validate_items, render_review, simulate, build_sim_norms,
                      plot_norm_curves, check_db
docs/                 문서
tests/                pytest
```
