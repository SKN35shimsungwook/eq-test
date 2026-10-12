"""응시 화면용 인라인 커스텀 컴포넌트 (Streamlit Custom Components v2).

- client_id: 브라우저 localStorage에 익명 ID를 만들어 재응시를 판별
- countdown: 남은 시간 표시 + 만료 알림 + 탭 이탈 횟수 집계 (영역 또는 위기 대처 문항)
- choice_list: 4지선다 보기 (문장 보기를 한 줄씩), 1~4·A~D 키 지원
- best_worst: 보기마다 '가장 효과적'·'가장 덜 효과적' 버튼, 각각 하나씩만 고를 수 있음
- result_card: 결과 카드 PNG

각 컴포넌트는 data.token이 같으면 화면을 다시 만들지 않아, 재실행돼도 진행 중인 상태가 끊기지 않는다.
문서 전체에 붙는 리스너는 인스턴스마다 하나만 두고, 화면에서 사라지면 스스로 떼어 낸다(iq-test에서 찾은 문제).
"""

from __future__ import annotations

import html as html_lib

import streamlit as st

BASE_CSS = """
:host { --pri: var(--st-primary-color, #0F766E); --txt: var(--st-text-color, #111827);
        --bg2: var(--st-secondary-background-color, #f3f4f6); --bd: var(--st-border-color, #d1d5db);
        font-family: var(--st-font, sans-serif); color: var(--txt); }
* { box-sizing: border-box; user-select: none; -webkit-user-select: none; }
button { font: inherit; cursor: pointer; }
.btn { border: 1px solid var(--bd); background: var(--bg2); color: var(--txt); border-radius: 8px;
       padding: 10px 18px; font-size: 16px; }
.btn.pri { background: var(--pri); border-color: var(--pri); color: #fff; font-weight: 600; }
"""

# ---------------------------------------------------------------- 익명 브라우저 ID

_CLIENT_ID = st.components.v2.component(
    "eq_client_id",
    html="<span></span>",
    js="""
export default function (component) {
  const { data, setStateValue } = component
  let id = null
  try {
    id = localStorage.getItem("eq_cid")
    if (!id) {
      id = crypto.randomUUID()
      localStorage.setItem("eq_cid", id)
    }
  } catch (e) {
    return
  }
  if (data.cid !== id) setStateValue("cid", id)
}
""",
)


def client_id(current: str | None) -> str | None:
    """localStorage의 익명 ID. 저장소를 쓸 수 없으면 None."""
    result = _CLIENT_ID(key="eq_cid", data={"cid": current}, default={"cid": None}, on_cid_change=lambda: None)
    return result.cid


# ---------------------------------------------------------------- 남은 시간

_COUNTDOWN = st.components.v2.component(
    "eq_countdown",
    html="<div class='cd'><span class='t'></span><div class='bar'><div class='fill'></div></div></div>",
    css=BASE_CSS + """
.cd { display: flex; align-items: center; gap: 10px; min-width: 200px; }
.t { font-variant-numeric: tabular-nums; font-weight: 700; font-size: 18px; min-width: 56px; }
.bar { flex: 1; height: 8px; background: var(--bg2); border-radius: 4px; overflow: hidden; }
.fill { height: 100%; background: var(--pri); transition: width .25s linear; }
.low .t { color: #dc2626; } .low .fill { background: #dc2626; }
""",
    js="""
export default function (component) {
  const { data, parentElement, setTriggerValue, setStateValue } = component
  const s = parentElement.__cd || (parentElement.__cd = { blurs: data.blurs || 0 })
  if (s.token !== data.token) { s.token = data.token; s.firedAt = 0 }
  s.endAt = performance.now() + data.remaining_ms
  s.total = data.total_ms
  s.lowAt = data.low_ms
  const box = parentElement.querySelector(".cd")
  const tick = () => {
    const left = Math.max(0, s.endAt - performance.now())
    const sec = Math.ceil(left / 1000)
    box.querySelector(".t").textContent = `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`
    box.querySelector(".fill").style.width = `${(left / s.total) * 100}%`
    box.classList.toggle("low", left < s.lowAt)
    if (left <= 0 && (!s.firedAt || performance.now() - s.firedAt > 3000)) {
      s.firedAt = performance.now()
      setTriggerValue("expired", s.token)
    }
  }
  tick()
  if (!s.timer) s.timer = setInterval(tick, 250)
  if (!s.onVis) {
    s.onVis = () => {
      if (!box.isConnected) { document.removeEventListener("visibilitychange", s.onVis); return }
      if (document.hidden) { s.blurs += 1; setStateValue("blurs", s.blurs) }
    }
    document.addEventListener("visibilitychange", s.onVis)
  }
  return () => {
    clearInterval(s.timer)
    document.removeEventListener("visibilitychange", s.onVis)
    parentElement.__cd = null
  }
}
""",
)


def countdown(token: str, remaining_ms: int, total_ms: int, blurs: int, key: str, low_ms: int = 30000):
    """(만료 trigger, 누적 탭 이탈 수)"""
    r = _COUNTDOWN(key=key, data={"token": token, "remaining_ms": remaining_ms, "total_ms": total_ms, "blurs": blurs,
                                  "low_ms": low_ms},
                   default={"blurs": blurs}, on_blurs_change=lambda: None, on_expired_change=lambda: None)
    return r.expired, r.blurs


# ---------------------------------------------------------------- 4지선다

_CHOICES = st.components.v2.component(
    "eq_choice_list",
    html="<div class='list'></div>",
    css=BASE_CSS + """
.list { display: flex; flex-direction: column; gap: 8px; }
.row { display: flex; gap: 10px; align-items: flex-start; border: 2px solid var(--bd); background: var(--bg2);
       color: var(--txt); border-radius: 10px; padding: 12px 14px; text-align: left; width: 100%; }
.row:hover { border-color: var(--pri); }
.row.on { border-color: var(--pri); box-shadow: 0 0 0 3px color-mix(in srgb, var(--pri) 25%, transparent); }
.lab { font-weight: 700; opacity: .55; min-width: 18px; }
.row.on .lab { color: var(--pri); opacity: 1; }
.body { font-size: 16px; line-height: 1.5; }
""",
    js="""
export default function (component) {
  const { data, parentElement, setStateValue } = component
  const list = parentElement.querySelector(".list")
  if (list.dataset.token !== data.token) {
    list.dataset.token = data.token
    list.innerHTML = ""
    data.choices.forEach((content, i) => {
      const b = document.createElement("button")
      b.type = "button"
      b.className = "row"
      b.dataset.i = i
      b.innerHTML = `<span class="lab">${"ABCD"[i]}</span><span class="body">${content}</span>`
      b.onclick = () => pick(i)
      list.appendChild(b)
    })
  }
  const mark = (sel) => list.querySelectorAll(".row").forEach(
    (t) => t.classList.toggle("on", Number(t.dataset.i) === sel))
  const pick = (i) => { mark(i); setStateValue("selected", i) }
  mark(data.selected ?? -1)
  if (parentElement.__onKey) document.removeEventListener("keydown", parentElement.__onKey)
  const onKey = (e) => {
    if (!list.isConnected) { document.removeEventListener("keydown", onKey); return }
    if (e.target.closest && e.target.closest("input, textarea")) return
    const k = e.key.toUpperCase()
    const i = "1234".indexOf(k) >= 0 ? "1234".indexOf(k) : "ABCD".indexOf(k)
    if (i >= 0 && k.length === 1) pick(i)
  }
  parentElement.__onKey = onKey
  document.addEventListener("keydown", onKey)
  return () => { document.removeEventListener("keydown", onKey); parentElement.__onKey = null }
}
""",
)


def choice_list(choices: list[str], selected: int | None, key: str) -> int | None:
    content = [html_lib.escape(str(c)) for c in choices]
    r = _CHOICES(key=key, data={"token": key, "choices": content, "selected": selected},
                 default={"selected": selected}, on_selected_change=lambda: None)
    return r.selected


# ---------------------------------------------------------------- 최선·최악 고르기

_BEST_WORST = st.components.v2.component(
    "eq_best_worst",
    html="<div class='list'></div>",
    css=BASE_CSS + """
.list { display: flex; flex-direction: column; gap: 8px; }
.row { border: 2px solid var(--bd); background: var(--bg2); border-radius: 10px; padding: 10px 12px; }
.row.best { border-color: #16a34a; } .row.worst { border-color: #dc2626; }
.top { display: flex; gap: 10px; align-items: flex-start; }
.lab { font-weight: 700; opacity: .55; min-width: 18px; }
.body { font-size: 16px; line-height: 1.5; flex: 1; }
.acts { display: flex; gap: 6px; margin-top: 8px; justify-content: flex-end; }
.tag { border: 1px solid var(--bd); background: transparent; color: var(--txt); border-radius: 999px;
       padding: 4px 12px; font-size: 13px; }
.tag.b.on { background: #16a34a; border-color: #16a34a; color: #fff; }
.tag.w.on { background: #dc2626; border-color: #dc2626; color: #fff; }
""",
    js="""
export default function (component) {
  const { data, parentElement, setStateValue } = component
  const list = parentElement.querySelector(".list")
  const s = parentElement.__bw || (parentElement.__bw = {})
  if (list.dataset.token !== data.token) {
    list.dataset.token = data.token
    s.best = data.best ?? null; s.worst = data.worst ?? null
    list.innerHTML = ""
    data.choices.forEach((content, i) => {
      const row = document.createElement("div")
      row.className = "row"
      row.dataset.i = i
      row.innerHTML = `<div class="top"><span class="lab">${"ABCD"[i]}</span><span class="body">${content}</span></div>
        <div class="acts"><button type="button" class="tag b">${data.best_label}</button>
        <button type="button" class="tag w">${data.worst_label}</button></div>`
      row.querySelector(".b").onclick = () => set("best", i)
      row.querySelector(".w").onclick = () => set("worst", i)
      list.appendChild(row)
    })
  }
  const paint = () => list.querySelectorAll(".row").forEach((r) => {
    const i = Number(r.dataset.i)
    r.classList.toggle("best", s.best === i); r.classList.toggle("worst", s.worst === i)
    r.querySelector(".b").classList.toggle("on", s.best === i)
    r.querySelector(".w").classList.toggle("on", s.worst === i)
  })
  const set = (which, i) => {
    const other = which === "best" ? "worst" : "best"
    s[which] = s[which] === i ? null : i   // 다시 누르면 취소
    if (s[other] === i) s[other] = null      // 한 보기가 최선이면서 최악일 수는 없다
    paint()
    setStateValue("pick", { best: s.best, worst: s.worst })
  }
  paint()
}
""",
)


def best_worst(choices: list[str], best: int | None, worst: int | None, key: str,
               best_label: str = "✓ 가장 맞음", worst_label: str = "✗ 가장 아님") -> tuple[int | None, int | None]:
    content = [html_lib.escape(str(c)) for c in choices]
    r = _BEST_WORST(key=key, data={"token": key, "choices": content, "best": best, "worst": worst,
                                   "best_label": best_label, "worst_label": worst_label},
                    default={"pick": {"best": best, "worst": worst}}, on_pick_change=lambda: None)
    pick = r.pick or {}
    return pick.get("best"), pick.get("worst")


# ---------------------------------------------------------------- 결과 카드

_CARD = st.components.v2.component(
    "eq_result_card",
    html="<div class='wrap'><canvas width='1080' height='1350'></canvas><button class='btn pri'>결과 카드 저장 (PNG)</button></div>",
    css=BASE_CSS + """
.wrap { display: flex; flex-direction: column; align-items: center; gap: 12px; }
canvas { width: 100%; max-width: 360px; height: auto; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.12); }
""",
    js="""
export default function (component) {
  const { data, parentElement } = component
  const cv = parentElement.querySelector("canvas")
  const g = cv.getContext("2d")
  const W = 1080, H = 1350, P = "#0F766E"
  const font = (w, s) => `${w} ${s}px "Pretendard", "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", sans-serif`
  g.fillStyle = "#ffffff"; g.fillRect(0, 0, W, H)
  g.fillStyle = P; g.fillRect(0, 0, W, 300)
  g.fillStyle = "#ffffff"; g.textAlign = "center"
  g.font = font(600, 40); g.fillText("EQ 감성지수", W / 2, 110)
  g.font = font(800, 150); g.fillText(Math.round(data.index), W / 2, 260)
  g.fillStyle = "#111827"
  g.font = font(700, 52); g.fillText(`${data.position} · ${data.level}`, W / 2, 390)
  if (data.type_name) { g.fillStyle = P; g.font = font(700, 38); g.fillText(data.type_name, W / 2, 452) }
  g.fillStyle = "#6b7280"; g.font = font(400, 30)
  g.fillText(`${data.mode} · 평균 100, 표준편차 15 기준`, W / 2, data.type_name ? 500 : 450)

  const cx = W / 2, cy = 900, R = 270, lo = 55, hi = 145
  const n = data.domains.length
  const pt = (i, v) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n
    const r = (Math.min(Math.max(v, lo), hi) - lo) / (hi - lo) * R
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)]
  }
  g.strokeStyle = "#e5e7eb"; g.lineWidth = 2
  for (const v of [70, 85, 115, 130, 145]) {
    g.beginPath(); data.domains.forEach((_, i) => { const [x, y] = pt(i, v); i ? g.lineTo(x, y) : g.moveTo(x, y) })
    g.closePath(); g.stroke()
  }
  g.setLineDash([10, 8]); g.strokeStyle = "#9ca3af"
  g.beginPath(); data.domains.forEach((_, i) => { const [x, y] = pt(i, 100); i ? g.lineTo(x, y) : g.moveTo(x, y) })
  g.closePath(); g.stroke(); g.setLineDash([])
  g.strokeStyle = "#e5e7eb"
  data.domains.forEach((_, i) => { const [x, y] = pt(i, hi); g.beginPath(); g.moveTo(cx, cy); g.lineTo(x, y); g.stroke() })
  g.beginPath()
  data.domains.forEach((d, i) => { const [x, y] = pt(i, d.index); i ? g.lineTo(x, y) : g.moveTo(x, y) })
  g.closePath(); g.fillStyle = "rgba(15,118,110,.22)"; g.fill(); g.strokeStyle = P; g.lineWidth = 5; g.stroke()
  data.domains.forEach((d, i) => {
    const [x, y] = pt(i, d.index)
    g.beginPath(); g.arc(x, y, 10, 0, 2 * Math.PI); g.fillStyle = P; g.fill()
    const [lx, ly] = pt(i, hi + 28)
    g.fillStyle = "#111827"; g.font = font(700, 32); g.fillText(d.label, lx, ly)
    g.fillStyle = P; g.font = font(700, 30); g.fillText(Math.round(d.index), lx, ly + 36)
  })
  g.fillStyle = "#9ca3af"; g.font = font(400, 26)
  g.fillText(`${data.date} · 온라인 정서 역량 테스트이며 전문 심리검사를 대체하지 않습니다`, W / 2, H - 50)

  parentElement.querySelector("button").onclick = () => {
    const a = document.createElement("a")
    a.download = `EQ-${Math.round(data.index)}.png`
    a.href = cv.toDataURL("image/png")
    a.click()
  }
}
""",
)


def result_card(index: float, position: str, level: str, mode: str, date: str, domains: list[dict],
                type_name: str = "") -> None:
    """domains: [{"label": "감정 인식", "index": 108.2}, ...], type_name: 종합 유형 이름"""
    _CARD(key="result-card", data={"index": index, "position": position, "level": level, "mode": mode, "date": date,
                                   "domains": domains, "type_name": type_name})
