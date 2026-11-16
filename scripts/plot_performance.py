"""Plot saved measurements. Requires the optional requirements-analysis.txt."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("output/performance/recommendations.json"))
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    rows = data["scenarios"]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), layout="constrained")
    for mode, label, color in [("rebuild_each_request", "Rebuild each request", "#222222"), ("cached_snapshot", "Cached similarities", "#cc2929")]:
        axes[0].plot([row["events"] for row in rows], [row[mode]["p50_ms"] for row in rows], marker="o", label=label, color=color)
    axes[0].set(xscale="log", yscale="log", xlabel="Interaction events", ylabel="HTTP p50 (ms, log scale)", title="Same CF results, lower retrieval cost")
    axes[0].legend(frameon=False)
    axes[0].grid(alpha=0.2)
    axes[1].plot([row["events"] for row in rows], [row["cached_snapshot"]["p50_ms"] for row in rows], marker="o", label="p50", color="#cc2929")
    axes[1].plot([row["events"] for row in rows], [row["cached_snapshot"]["p95_ms"] for row in rows], marker="s", label="p95", color="#777777")
    axes[1].set(xscale="log", xlabel="Interaction events", ylabel="HTTP latency (ms)", title="Warm snapshot, sequential requests")
    axes[1].legend(frameon=False)
    axes[1].grid(alpha=0.2)
    fig.suptitle("Local recommendation performance on synthetic preference cohorts", fontsize=14)
    fig.savefig(args.input.parent / "recommendation-latency.png", dpi=180)
    fig.savefig(args.input.parent / "recommendation-latency.svg")
    plt.close(fig)
    print("Saved PNG and SVG performance figures")


if __name__ == "__main__":
    main()
