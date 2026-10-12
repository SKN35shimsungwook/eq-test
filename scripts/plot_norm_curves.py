"""채점 문서용 그래프: python scripts/plot_norm_curves.py  (matplotlib 필요, 개발용)

norms/sim_norms.json을 읽어 docs/images/에 PNG 두 장을 만든다.
  - norm_curves.png: 능력 추정치 θ̂ → EQ 곡선 (보정 전 / 보정 후 종합 / 보정 후 영역)
  - norm_spread.png: 단계별 보정 전 EQ 표준편차 (보정 후에는 모두 15)
규준표를 다시 만들었다면(build_sim_norms.py) 이 스크립트도 다시 실행한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import scoring as sc  # noqa: E402
from core.schema import Domain  # noqa: E402

OUT = ROOT / "docs" / "images"
MODES = {"quick": "빠른 검사", "full": "정밀 검사"}
STAGES = {"1": "1차", "1-2": "1~2차", "1-3": "1~3차", "1-3+deep": "+심층"}
BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#898781"

_installed = {f.name for f in matplotlib.font_manager.fontManager.ttflist}
plt.rcParams["font.family"] = [f for f in ("Malgun Gothic", "AppleGothic", "NanumGothic") if f in _installed] + ["sans-serif"]
plt.rcParams["axes.unicode_minus"] = False


def curves() -> None:
    ts = np.linspace(-3, 3, 121)
    fig, axes = plt.subplots(2, 2, figsize=(10, 8), sharex=True, sharey=True)
    for r, mode in enumerate(MODES):
        norm = sc.Norm(sim=sc.load_sim(mode))
        for c, stage in enumerate(["1", "1-3+deep"]):
            ax = axes[r][c]
            ax.plot(ts, [sc.to_index(t) for t in ts], "--", color=GRAY, lw=2, label="보정 전 (θ̂ 그대로)")
            ax.plot(ts, [sc.to_index(norm.z(t, None, stage)) for t in ts], color=BLUE, lw=2, label="보정 후 종합")
            ax.plot(ts, [sc.to_index(norm.z(t, Domain.UND, stage)) for t in ts], ":", color=ORANGE, lw=2.5,
                    label="보정 후 영역 (감정 이해)")
            ax.set_title(f"{MODES[mode]} · {STAGES[stage]}")
            ax.set_ylim(40, 160)
            ax.set_yticks(range(40, 161, 15))
            ax.grid(color="#e1e0d9")
            ax.axhline(100, color="#c3c2b7", lw=1)
    for ax in axes[1]:
        ax.set_xlabel("능력 추정치 θ̂")
    for ax in axes[:, 0]:
        ax.set_ylabel("EQ")
    axes[0][0].legend(loc="upper left", fontsize=9)
    fig.suptitle("능력 추정치 → EQ 변환 곡선 (봇 시뮬레이션 규준)")
    fig.tight_layout()
    fig.savefig(OUT / "norm_curves.png", dpi=110)
    plt.close(fig)


def spread() -> None:
    data = json.loads(sc.SIM_NORMS.read_text(encoding="utf-8"))["modes"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    x = np.arange(len(STAGES))
    for ax, mode in zip(axes, MODES):
        total = [data[mode][s]["total"]["sd_raw_index"] for s in STAGES]
        dom = [np.mean([v["sd_raw_index"] for k, v in data[mode][s].items() if k != "total"]) for s in STAGES]
        ax.bar(x - 0.2, total, 0.38, color=BLUE, label="종합")
        ax.bar(x + 0.2, dom, 0.38, color=ORANGE, hatch="//", edgecolor="white", label="영역 평균")
        for i, (a, b) in enumerate(zip(total, dom)):
            ax.text(i - 0.2, a + 0.2, f"{a:.1f}", ha="center", fontsize=9)
            ax.text(i + 0.2, b + 0.2, f"{b:.1f}", ha="center", fontsize=9)
        ax.axhline(15, color=GRAY, ls="--", lw=1.5, label="보정 후 (15)")
        ax.set_xticks(x, list(STAGES.values()))
        ax.set_title(MODES[mode])
        ax.set_ylim(0, 17)
        ax.grid(axis="y", color="#e1e0d9")
    axes[0].set_ylabel("보정 전 EQ 표준편차")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", ncol=3, fontsize=9, frameon=False)
    fig.suptitle("단계별 점수 퍼짐: 15보다 작을수록 평균 쪽으로 몰림")
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(OUT / "norm_spread.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    curves()
    spread()
    print(f"저장: {OUT}")
