# 배포 체크리스트 (Supabase + Streamlit Community Cloud)

코드 쪽 준비는 끝나 있습니다. 아래 ①~④는 대시보드에서 직접 해야 하는 일입니다.

## 이미 확인된 것

- DB 계층은 iq-test에서 실제 Postgres(PGlite)로 검증한 코드를 그대로 씀 (`scripts/check_db.py`로 같은 점검 가능)
- 테이블 생성 시 RLS를 자동으로 켬 → Supabase REST API(anon 키)로는 응시 데이터를 읽거나 쓸 수 없음
- 로컬(SQLite)에서 빠른 검사 전 과정(자기평가 → 7개 영역 → 결과) 확인

## ① Supabase 프로젝트 만들기

1. https://supabase.com → New project
   - Region: **Northeast Asia (Seoul)**
   - Database password: 새로 만들고 따로 보관 (아래 URL에 들어감)
2. 프로젝트가 만들어지면 상단 **Connect** → **Session pooler** 탭의 URI를 복사
   - 형식: `postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres`
   - Direct connection(`db.<ref>.supabase.co`)은 IPv6 전용이라 Streamlit Cloud에서 접속되지 않습니다.
3. URL을 앱용으로 고치기
   - `postgresql://` → `postgresql+psycopg2://`
   - `[YOUR-PASSWORD]`에 DB 비밀번호 (특수문자는 URL 인코딩: `@`→`%40`, `#`→`%23`, `/`→`%2F`)
   - 끝에 `?sslmode=require` 추가

테이블은 앱이 처음 켜질 때 자동으로 만들어지므로 SQL을 직접 실행할 필요는 없습니다.

## ② 로컬에서 Supabase 연결 점검

```bash
python scripts/check_db.py "postgresql+psycopg2://postgres.<ref>:<비밀번호>@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres?sslmode=require"
```

`통과: 이 DB로 배포할 수 있습니다.`가 나오면 됩니다. 점검용 행은 스스로 지웁니다.
실패하면 오류 메시지의 단계(접속 / 테이블 생성 / …)를 보고 URL·비밀번호·인코딩을 확인하세요.

## ③ Streamlit Community Cloud에 배포

1. https://share.streamlit.io → **Create app** → *Deploy a public app from GitHub*
2. 설정
   - Repository: `SKN35shimsungwook/eq-test`, Branch: `main`, Main file: `streamlit_app.py`
   - App URL: 원하는 주소 (예: `eq-test`)
   - **Advanced settings**
     - Python version: 3.12 또는 3.13
     - Secrets: 아래를 붙여 넣기

```toml
admin_password = "<새로 만든 긴 비밀번호>"

[connections.sql]
url = "postgresql+psycopg2://postgres.<ref>:<비밀번호>@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres?sslmode=require"
```

3. **Deploy** → 첫 빌드는 2~5분 걸립니다.
4. 다른 사람도 응시하게 하려면 앱 **Share** 설정에서 공개 여부를 확인합니다.

## ④ 배포 후 확인

- [ ] 시작 화면이 뜨고 자기평가 → 빠른 검사를 끝까지 풀 수 있다
- [ ] 위기 대처 문항의 초시계가 끝나면 다음 문항으로 넘어간다
- [ ] 결과 화면 → "2차 검증 하기"가 동작한다
- [ ] 응시 중 새로고침해도 같은 문항으로 돌아온다
- [ ] 관리자 페이지 상단에 **저장소: Postgres**가 보인다 (SQLite로 나오면 Secrets의 URL을 확인)
- [ ] Supabase 대시보드 → Table Editor에 `sessions`, `responses`가 생기고 행이 쌓인다
- [ ] 휴대폰에서 열어 응시 화면이 깨지지 않는다

## 운영 메모

- **규준**: 같은 모드의 1차 검증 첫 응시가 100명을 넘으면 결과의 "상위 %"가 실제 응시자 분포 기준으로 바뀝니다.
- **문항 보정**: 응답이 쌓이면 관리자 페이지 → 내보내기 → 보정값 JSON을 받아 `items/calibration.json`으로 커밋하고, `python scripts/build_sim_norms.py --n 20000 --workers 8`로 규준표를 다시 만듭니다.
- **정답 키 점검**: 관리자 페이지 '다수 응답과 정답 불일치' 문항은 정답 근거를 다시 검토합니다.
- **잠자기**: Community Cloud 앱은 한동안 접속이 없으면 잠들고, 다음 방문 때 깨어나는 데 수십 초 걸립니다.
- **Supabase 무료 플랜**: 1주일 넘게 요청이 없으면 프로젝트가 일시 정지될 수 있습니다 (대시보드에서 다시 켜면 데이터는 그대로).
- **시뮬레이션 데이터**는 배포 DB에 넣지 마세요 (`scripts/simulate.py`는 기본으로 로컬 SQLite에만 씁니다).
