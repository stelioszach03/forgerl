"""Descriptive primary-split success versus accounted cost; no inference claims."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


LABELS = {
    "adaptive": "Fitted-Q router",
    "cheap_only": "Cheap only",
    "escalate_on_failure": "Escalate on failure",
    "static_router": "Hand-written router",
    "strong_only": "Strong only",
    "supervised_cost": "Supervised baseline",
}
OFFSETS = {
    "adaptive": (-91, -18),
    "cheap_only": (-20, 13),
    "escalate_on_failure": (-64, -18),
    "static_router": (-20, 12),
    "strong_only": (8, 10),
    "supervised_cost": (8, -8),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy-summary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.policy_summary.open(newline="") as file:
        rows = [row for row in csv.DictReader(file) if row["split"] == "test"]
    assert len(rows) == 6
    fig, ax = plt.subplots(figsize=(8.5, 5.2), layout="constrained")
    for row in rows:
        policy = row["policy"]
        x = float(row["mean_cost_usd_per_episode"]) * 1000
        y = 100 * int(row["solved"]) / int(row["attempted"])
        color = "#B35F36" if policy == "adaptive" else "#235C7C"
        ax.scatter(x, y, s=86, color=color, edgecolor="white", linewidth=0.8, zorder=3)
        ax.annotate(LABELS[policy], (x, y), xytext=OFFSETS[policy], textcoords="offset points", fontsize=9, color="#17212F")
    ax.set_xlabel("Accounted model cost per episode (milli-USD)")
    ax.set_ylabel("Task success on exposed primary slice (%)")
    ax.set_xlim(0.10, 0.285)
    ax.set_ylim(79, 94)
    ax.grid(color="#E5ECF2", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("ForgeBench exposed-catalog replication", fontsize=15, fontweight="bold", color="#17212F")
    fig.supxlabel("18 previously inspected tasks × 4 seeds × VERIFY off/on; 144 attempts per policy; failures retained", fontsize=8, color="#536273")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=190, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
