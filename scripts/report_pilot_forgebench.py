#!/usr/bin/env python3
"""Render actual reconciled pilot results; never generate synthetic evidence.

Optional dependencies: matplotlib, numpy, reportlab. This analysis-only script
does not change the frozen runner, task protocol, controllers or source traces.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyze_pilot_forgebench import analyze, read_runs

POLICIES = (
    "strong_only",
    "cheap_only",
    "escalate_on_failure",
    "static_router",
    "adaptive",
    "supervised_cost",
)
NAMES = {
    "strong_only": "Strong only",
    "cheap_only": "Cheap only",
    "escalate_on_failure": "Escalate on failure",
    "static_router": "Hand-written router",
    "adaptive": "Fitted-Q transfer",
    "supervised_cost": "Supervised return",
}
SHORT = {**NAMES, "escalate_on_failure": "Escalate", "static_router": "Hand-written"}
COLORS = {
    "strong_only": "#203d60",
    "cheap_only": "#8dabc0",
    "escalate_on_failure": "#756493",
    "static_router": "#b67f35",
    "adaptive": "#007f79",
    "supervised_cost": "#ba5c6b",
}


def percentage(value):
    return "unmeasured" if value is None else f"{value:.1%}"


def number(value, places=2):
    return "unmeasured" if value is None else f"{value:.{places}f}"


def selected(report, split):
    return [
        next(r for r in report["summary"] if r["split"] == split and r["policy"] == p)
        for p in POLICIES
    ]


def create_figures(report, rows, directory):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    directory.mkdir(parents=True, exist_ok=False)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 13,
            "axes.labelsize": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
            "axes.titleweight": "bold",
            "svg.fonttype": "none",
            "savefig.facecolor": "white",
        }
    )
    captions = {}
    summary = selected(report, "test")
    primary = [r for r in rows if r["split"] == "test"]

    def save(fig, name, caption):
        fig.tight_layout(pad=1.5)
        for extension in ("png", "svg", "pdf"):
            fig.savefig(directory / f"{name}.{extension}", dpi=240, bbox_inches="tight")
        plt.close(fig)
        captions[name] = caption

    fig, ax = plt.subplots(figsize=(8.6, 5.1))
    markers = ("s", "o", "^", "D", "P", "X")
    available = [r for r in summary if r["family_weighted_success"] is not None]
    for index, row in enumerate(summary):
        if row["family_weighted_success"] is None:
            continue
        policy = row["policy"]
        label = (
            f"{NAMES[policy]}: {percentage(row['family_weighted_success'])}, "
            f"${row['family_weighted_cost_usd']:.6f}"
        )
        ax.scatter(
            row["family_weighted_cost_usd"],
            row["family_weighted_success"] * 100,
            s=100,
            marker=markers[index],
            color=COLORS[policy],
            edgecolor="white",
            linewidth=0.8,
            label=label,
            zorder=3 + index,
        )
    if available:
        max_cost = max(r["family_weighted_cost_usd"] for r in available)
        ax.set_xlim(0, max_cost * 1.25 or 0.001)
        ax.legend(
            frameon=False,
            fontsize=8.8,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.2),
            ncol=2,
        )
    else:
        ax.text(
            0.5,
            0.5,
            "No measured primary results",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
    ax.set(
        title="Primary test: success versus accounted API cost",
        xlabel="Equally family-weighted cost per attempted episode (USD)",
        ylabel="Equally family-weighted success (%)",
        ylim=(-3, 105),
    )
    ax.ticklabel_format(axis="x", style="plain", useOffset=False)
    ax.grid(alpha=0.18)
    save(
        fig,
        "success-vs-cost",
        "Observed means over six authored test families, with three related tasks per family and one requested seed. "
        "Failed provider/executor attempts remain unsolved. Points are not jittered; overlapping points are disclosed in the numeric legend. "
        "No population confidence intervals, significance test, or general superiority claim.",
    )

    families = sorted(
        {r["family"] for r in report["family_metrics"] if r["split"] == "test"}
    )
    fig, ax = plt.subplots(figsize=(8.6, 5.2))
    matrix = np.full((len(families), len(POLICIES)), np.nan)
    cell = {}
    for row in report["family_metrics"]:
        if row["split"] == "test":
            i, j = families.index(row["family"]), POLICIES.index(row["policy"])
            matrix[i, j] = row["success_rate"]
            count = sum(
                r["success"]
                for r in primary
                if r["family"] == row["family"] and r["policy"] == row["policy"]
            )
            cell[(i, j)] = f"{count}/{row['attempted']}" + (
                f"\n({row['planned']} planned)"
                if row["attempted"] != row["planned"]
                else ""
            )
    if families:
        cmap = plt.get_cmap("YlGnBu").copy()
        cmap.set_bad("#eef1f4")
        graphic = ax.imshow(matrix, vmin=0, vmax=1, cmap=cmap, aspect="auto")
        for i in range(len(families)):
            for j in range(len(POLICIES)):
                ax.text(
                    j,
                    i,
                    cell.get((i, j), "missing"),
                    ha="center",
                    va="center",
                    fontsize=10,
                    color="white" if matrix[i, j] > 0.65 else "#203d60",
                )
        fig.colorbar(graphic, ax=ax, label="Solved / attempted", shrink=0.78)
    ax.set(
        xticks=range(len(POLICIES)),
        xticklabels=[SHORT[p] for p in POLICIES],
        yticks=range(len(families)),
        yticklabels=[f.replace("_", " ") for f in families],
        title="Primary outcomes by held-out family",
    )
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    save(
        fig,
        "family-outcomes",
        "Cells show solved/attempted episodes, not independent seed replicates. Each family contains three related variants. "
        "The two validation families and the source-derived Boltons family are excluded from this primary matrix.",
    )

    fig, axes = plt.subplots(
        1, 2, figsize=(10.1, 5.2), gridspec_kw={"width_ratios": [1.1, 1]}
    )
    y = np.arange(len(POLICIES))
    solved, graded_failed, ungraded, missing = [], [], [], []
    for row in summary:
        group = [r for r in primary if r["policy"] == row["policy"]]
        solved.append(sum(r["success"] for r in group))
        graded_failed.append(
            sum(r["hidden_passed"] is not None and not r["success"] for r in group)
        )
        ungraded.append(sum(r["hidden_passed"] is None for r in group))
        missing.append(row["planned"] - row["attempted"])
    left = np.zeros(len(POLICIES))
    for label, values, color in (
        ("Solved", solved, "#007f79"),
        ("Graded, unsolved", graded_failed, "#d3a257"),
        ("No final grade", ungraded, "#a96970"),
        ("Unattempted", missing, "#e0e6eb"),
    ):
        axes[0].barh(y, values, left=left, label=label, color=color, edgecolor="white")
        for i, value in enumerate(values):
            if value:
                axes[0].text(
                    left[i] + value / 2,
                    i,
                    str(value),
                    ha="center",
                    va="center",
                    fontsize=9,
                )
        left += np.array(values)
    axes[0].set(
        yticks=y,
        yticklabels=[SHORT[p] for p in POLICIES],
        xlabel="Episodes",
        title="Final-grading coverage",
        xlim=(0, 18),
    )
    axes[0].invert_yaxis()
    axes[0].legend(
        frameon=False,
        fontsize=8,
        ncol=2,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
    )
    primary_labeled = graded_labeled = False
    for i, row in enumerate(summary):
        if row["family_weighted_success"] is not None:
            axes[1].barh(
                i - 0.16,
                100 * row["family_weighted_success"],
                height=0.28,
                color="#203d60",
                label="Primary: failed attempts retained"
                if not primary_labeled
                else None,
            )
            primary_labeled = True
        if row["graded_only_success_rate"] is not None:
            axes[1].barh(
                i + 0.16,
                100 * row["graded_only_success_rate"],
                height=0.28,
                color="#8dabc0",
                label="Secondary: graded episodes only" if not graded_labeled else None,
            )
            graded_labeled = True
        else:
            axes[1].text(
                1, i + 0.16, "graded-only: unmeasured", fontsize=8, va="center"
            )
    axes[1].set(
        yticks=y,
        yticklabels=[],
        xlabel="Success (%)",
        xlim=(0, 105),
        title="Conditional sensitivity",
    )
    axes[1].invert_yaxis()
    axes[1].legend(
        frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.16)
    )
    axes[1].grid(axis="x", alpha=0.15)
    save(
        fig,
        "infrastructure-sensitivity",
        "No final grade includes provider/executor failures and bounded stops; these remain in the primary attempted denominator. "
        "The graded-only success fraction is a secondary episode-weighted view conditional on infrastructure availability. "
        "It does not replace the family-weighted primary metric. Unattempted cells remain missing, never fabricated failures.",
    )

    fig, axes = plt.subplots(
        1, 2, figsize=(10.1, 5.3), gridspec_kw={"width_ratios": [1.1, 1]}
    )
    for i, row in enumerate(summary):
        axes[0].barh(
            i - 0.16,
            row["verification_calls"],
            height=0.28,
            color="#8dabc0",
            label="Supplemental executions" if i == 0 else None,
        )
        axes[0].barh(
            i + 0.16,
            row["caught_supplemental_failures"],
            height=0.28,
            color="#b67f35",
            label="Executions finding failures" if i == 0 else None,
        )
    axes[0].set(
        yticks=y,
        yticklabels=[SHORT[p] for p in POLICIES],
        xlabel="Actual sandbox calls",
        title="Supplemental verification",
    )
    axes[0].invert_yaxis()
    axes[0].legend(
        frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.16)
    )
    learned_rows = [
        r for r in summary if r["policy"] in ("adaptive", "supervised_cost")
    ]
    ly = np.arange(len(learned_rows))
    learned = [r["non_stop_non_verify_learned_decisions"] for r in learned_rows]
    fallback = [r["non_stop_non_verify_fallback_decisions"] for r in learned_rows]
    provider_retry = [r["non_stop_non_verify_provider_retry_decisions"] for r in learned_rows]
    other = [r["non_stop_non_verify_other_decisions"] for r in learned_rows]
    axes[1].barh(ly, learned, color="#007f79", label="Supported learned selection")
    axes[1].barh(
        ly, fallback, left=learned, color="#d3a257", label="Explicit heuristic fallback"
    )
    after_fallback = np.array(learned) + np.array(fallback)
    axes[1].barh(
        ly, provider_retry, left=after_fallback, color="#756493", label="Provider-retry override"
    )
    if any(other):
        axes[1].barh(
            ly, other, left=after_fallback + np.array(provider_retry), color="#aab3bd", label="Other recorded source"
        )
    for i, (a, b) in enumerate(zip(learned, fallback)):
        axes[1].text(
            a / 2 if a else 0.5,
            i,
            str(a),
            ha="center",
            va="center",
            color="white" if a else "#203d60",
        )
        if b:
            axes[1].text(a + b / 2, i, str(b), ha="center", va="center")
        if provider_retry[i]:
            axes[1].text(a + b + provider_retry[i] / 2, i, str(provider_retry[i]), ha="center", va="center", color="white")
    axes[1].set(
        yticks=ly,
        yticklabels=["Fitted-Q", "Supervised"],
        xlabel="Recorded actions excluding STOP / VERIFY",
        title="Selection sources (post-run diagnostic)",
    )
    axes[1].invert_yaxis()
    axes[1].legend(
        frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.16)
    )
    save(
        fig,
        "verification-and-support",
        "All policies share the same verify-on-visible-green rule; VERIFY is not learned. "
        "Right panel is a post-run clarification: all STOP and VERIFY actions are excluded, and provider-retry overrides are shown separately. "
        "The original all-action learned/fallback counts remain in the data. Forced STOP provenance differs between the two frozen selectors; raw fallback totals are not directly comparable selection coverage. "
        "A caught supplemental failure is an observed signal, not evidence of causal benefit or independent grading.",
    )
    (directory / "captions.json").write_text(json.dumps(captions, indent=2) + "\n")
    return captions


def sections(report, rows, frozen, manifest):
    primary = selected(report, "test")
    by_policy = {r["policy"]: r for r in primary}
    observed = sum(r["attempted"] for r in primary)
    failed = sum(r["hidden_passed"] is None for r in rows if r["split"] == "test")
    caught = sum(r["caught_supplemental_failures"] for r in primary)
    repaired = sum(r["success_after_supplemental_failure"] for r in primary)
    missed = sum(r["supplemental_missed_failures"] for r in primary)
    rejected = sum(r["supplemental_false_rejections"] for r in primary)
    config = frozen["configuration"]
    comparison = " ".join(
        f"{NAMES[p]} recorded {percentage(by_policy[p]['family_weighted_success'])} success at "
        f"${number(by_policy[p]['family_weighted_cost_usd'], 6)} accounted API cost/task."
        for p in ("adaptive", "supervised_cost", "strong_only", "cheap_only")
    )
    coverage_rows = [by_policy[p] for p in ("adaptive", "supervised_cost")]
    coverage = " ".join(
        f"{NAMES[row['policy']]} retains {row['learned_decisions']} learned and {row['fallback_decisions']} fallback "
        f"events in the original all-action totals. Excluding STOP/VERIFY leaves "
        f"{row['non_stop_non_verify_learned_decisions']} learned, "
        f"{row['non_stop_non_verify_fallback_decisions']} heuristic and "
        f"{row['non_stop_non_verify_provider_retry_decisions']} provider-retry actions "
        f"({row['non_stop_non_verify_decisions']} total). Its {row['stop_decisions']} STOP events include "
        f"{row['stop_constraint_decisions']} constraint and {row['stop_fallback_decisions']} fallback labels."
        for row in coverage_rows
    )
    return {
        "Scope": (
            f"This prospective transfer pilot recorded {report['completed']}/{report['planned']} prespecified episodes; "
            f"status: {report['status']}. Primary test evidence covers {observed}/108 planned episodes across six fresh authored "
            "families and three related tasks per family. Six validation tasks and three source-derived tasks are reported separately. "
            "The prior 50 tasks / ten families were already inspected and remain development material, never fresh holdouts."
        ),
        "Method": (
            "Six policies share original-visible tests, at most two supplemental verifications, and final-only hidden grading. "
            "Historical completed training transitions from the original 30 train tasks fit two frozen observational selectors: "
            "tabular fitted-Q and a simpler mean discounted-return regressor. Unobserved actions have no fabricated labels; unseen "
            "states/actions use a recorded heuristic fallback. Historical VERIFY support is zero, so every policy shares an explicit "
            "verify-on-visible-green rule. This experiment does not learn verification or update language-model weights."
        ),
        "Primary observations": comparison
        + " These observations do not establish broad superiority, statistical significance, or a deployment recommendation.",
        "Infrastructure and costs": (
            f"Among attempted primary test episodes, {failed} lack a final grade. They remain unsolved in the primary "
            "attempted denominator. The graded-only view is explicitly secondary and conditional on successful infrastructure. "
            "Unattempted matrix cells remain missing. Accounted cost includes conservative retained reserves when a provider charge "
            "cannot be confirmed; it excludes credit-purchase fees, VPS costs, local CPU monetary estimates and GPU expenses. "
            f"The shared-ledger pilot delta was ${number(manifest.get('accounted_cost_delta_usd'), 6)} against the frozen $1 total cap."
        ),
        "Verification and support": (
            f"Within the primary test split, supplemental calls found {caught} failing visible-green candidates; {repaired} episodes later "
            f"succeeded after an observed supplemental failure. The final candidate comparison records {missed} missed failures "
            f"(supplemental pass, final failure) and {rejected} false rejections (supplemental failure, final success). "
            "Missing either measurement yields null disagreement. These correlated author-written checks are not an independent oracle, "
            "and observed repair after verification does not identify a causal benefit without a matched no-VERIFY ablation."
        ),
        "Selection-coverage clarification": (
            "Primary-test post-run diagnostic, added after inspecting the recorded source labels; it does not alter primary scores, "
            "the frozen runtime or the preregistered all-action counts. " + coverage + " "
            "The original fallback totals are therefore dominated by a terminal-label asymmetry, not evidence that one selector "
            "had proportionally more unsupported routing states. Provider-retry overrides remain a separate source, not learned choices."
        ),
        "Controls": (
            f"Requested seed {config['seed']}; GPT-OSS-20B and GPT-OSS-120B pinned through OpenRouter to CoreWeave/fp4 with no fallback. "
            "Both receive max 4,096 output tokens, temperature 0.2, up to six actual provider requests, ten routing decisions and 100,000 "
            "bounded tokens per episode. HTTP 429 retries are capped at two and consume the same request/decision budgets. "
            "The historical $1 episode cap preserves state-encoding semantics; the independent $1 total pilot cap uses the original durable ledger. "
            "Hosted checkpoint revisions are unavailable and requested seeds do not guarantee determinism."
        ),
        "Source-derived track": (
            "Three artificial mutation tasks use actual Boltons clamp/ceil/floor source at immutable revision "
            "4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d with original BSD-3-Clause notices. The adapter, faults and checks are newly authored. "
            "This is not an upstream issue benchmark, SWE-bench, an upstream endorsement, or evidence of contamination-free generalization. "
            "The external family is descriptive only and never pooled with the six authored primary families."
        ),
        "Limitations": (
            "This is one seed, six authored primary families, compact flat Python repositories, correlated variants, AI-assisted task/check "
            "construction, and author-correlated supplemental/final grading. Historical behavioral propensities are missing, so no importance-weighted "
            "or causal off-policy claim is supported. Inference/provider nondeterminism and selected compatible upstream functions constrain external validity. "
            "All comparisons are descriptive; no population confidence interval or significance claim is made. Full v0.3 still requires broader "
            "external issues, prospective exploration with logged action probabilities, supported learned VERIFY, matched ablations and more seeds."
        ),
        "Artifact provenance": (
            f"Source commit: {frozen['source_commit']}. Runtime SHA256: {frozen['source_manifest']['sha256']}. "
            f"Frozen protocol SHA256: {frozen['sha256']}. Catalog SHA256: {config['task_manifest_sha256']}. "
            "The report is generated from immutable real run records reconciled against the frozen execution matrix. "
            "Source code, controller evidence, full visible trajectories, partial coverage and negative outcomes remain inspectable. "
            "This technical artifact is not peer reviewed, published as an academic paper or submitted as a preprint."
        ),
    }


def write_markdown(report, rows, paragraphs, captions, output):
    lines = [
        "# ForgeBench v0.3 prospective transfer pilot",
        "",
        "Stelios Zacharioudakis",
        "",
        "Technical research artifact; not peer reviewed or submitted as a preprint.",
        "",
    ]
    for heading, text in paragraphs.items():
        lines.extend([f"## {heading}", "", text, ""])
        if heading == "Primary observations":
            for split in ("test", "validation", "external"):
                lines.extend(
                    [
                        f"### {split}",
                        "",
                        "| Policy | Attempted/planned | Family-weighted success | Accounted cost/task | Graded-only success | Graded n |",
                        "| --- | ---: | ---: | ---: | ---: | ---: |",
                    ]
                )
                for r in selected(report, split):
                    lines.append(
                        f"| {NAMES[r['policy']]} | {r['attempted']}/{r['planned']} | {percentage(r['family_weighted_success'])} | "
                        f"${number(r['family_weighted_cost_usd'], 6)} | {percentage(r['graded_only_success_rate'])} | {r['graded_episodes']} |"
                    )
                lines.append("")
    for name, caption in captions.items():
        lines.extend([f"![{name}](figures/{name}.svg)", "", caption, ""])
    lines.extend(
        [
            "## Source references",
            "",
            "- [Boltons source at pinned revision](https://github.com/mahmoud/boltons/blob/4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d/boltons/mathutils.py)",
            "- [Retained upstream license](https://github.com/mahmoud/boltons/blob/4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d/LICENSE)",
            "- [Frozen protocol and source](https://github.com/stelioszach03/forgerl/tree/7b383887eaa69e970e00060a6fc8c16e6fe73567)",
            "",
        ]
    )
    (output / "pilot-report.md").write_text("\n".join(lines))


def write_pdf(report, paragraphs, captions, output):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        Image,
        PageBreak,
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="PilotTitle",
            fontName="Helvetica-Bold",
            fontSize=25,
            leading=29,
            textColor=colors.HexColor("#203d60"),
            spaceAfter=13,
        )
    )
    styles.add(
        ParagraphStyle(
            name="PilotBody",
            fontName="Helvetica",
            fontSize=9.2,
            leading=13,
            spaceAfter=9,
            allowOrphans=False,
            allowWidows=False,
            splitLongWords=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="PilotCaption",
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#526176"),
            spaceAfter=8,
            splitLongWords=True,
        )
    )
    styles["Heading2"].textColor = colors.HexColor("#007f79")
    styles["Heading2"].keepWithNext = True
    flow = []

    def paragraph(heading):
        flow.extend(
            [
                Paragraph(heading, styles["Heading2"]),
                Paragraph(html.escape(paragraphs[heading]), styles["PilotBody"]),
            ]
        )

    def table(split):
        values = [["Policy", "n / planned", "Success", "API cost/task", "Graded only"]]
        for row in selected(report, split):
            values.append(
                [
                    NAMES[row["policy"]],
                    f"{row['attempted']}/{row['planned']}",
                    percentage(row["family_weighted_success"]),
                    f"${number(row['family_weighted_cost_usd'], 6)}",
                    percentage(row["graded_only_success_rate"])
                    + f" (n={row['graded_episodes']})",
                ]
            )
        content = [
            [Paragraph(html.escape(str(cell)), styles["PilotCaption"]) for cell in row]
            for row in values
        ]
        block = Table(content, colWidths=[127, 64, 65, 90, 145], repeatRows=1)
        block.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf0f4")),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f6f8fa")],
                    ),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#b4c6d3")),
                ]
            )
        )
        flow.extend([block, Spacer(1, 9)])

    def figure(name):
        image = Image(str(output / "figures" / f"{name}.png"))
        # ReportLab loads image dimensions lazily and resets drawWidth while
        # doing so. Resolve both dimensions before assigning the display size.
        intrinsic_width, intrinsic_height = image.imageWidth, image.imageHeight
        image.drawWidth = 491
        image.drawHeight = intrinsic_height * 491 / intrinsic_width
        flow.extend(
            [
                image,
                Spacer(1, 9),
                Paragraph(html.escape(captions[name]), styles["PilotCaption"]),
            ]
        )

    flow.extend(
        [
            Paragraph(
                "Routing transfer with<br/>shared verification", styles["PilotTitle"]
            ),
            Paragraph("ForgeBench v0.3 prospective pilot", styles["Heading2"]),
            Paragraph(
                "Stelios Zacharioudakis | Technical research artifact",
                styles["PilotBody"],
            ),
            Paragraph(
                "Not peer reviewed; not submitted as a preprint. Results are descriptive and include failed attempts.",
                styles["PilotCaption"],
            ),
        ]
    )
    paragraph("Scope")
    paragraph("Method")
    flow.append(Paragraph("Primary test summary", styles["Heading2"]))
    table("test")
    flow.append(
        Paragraph(
            "Success and cost are equally family-weighted over observed primary test families. Graded-only is a secondary episode-weighted conditional view. Coverage is explicit; incomplete matrices do not support a complete-study claim.",
            styles["PilotCaption"],
        )
    )
    flow.append(PageBreak())
    flow.append(Paragraph("1. Primary success and cost", styles["PilotTitle"]))
    figure("success-vs-cost")
    paragraph("Primary observations")
    paragraph("Controls")
    flow.append(PageBreak())
    flow.append(Paragraph("2. Family-level outcomes", styles["PilotTitle"]))
    figure("family-outcomes")
    paragraph("Limitations")
    flow.append(PageBreak())
    flow.append(Paragraph("3. Infrastructure sensitivity", styles["PilotTitle"]))
    figure("infrastructure-sensitivity")
    paragraph("Infrastructure and costs")
    flow.append(Paragraph("Interpretation", styles["Heading2"]))
    flow.append(
        Paragraph(
            "Differences between primary and graded-only success can reflect provider availability. The conditional view does not estimate how failed requests would have performed, and unavailable hidden results are not zero hidden-test measurements. Costs with unknown billing remain conservative reservations, not confirmed provider charges.",
            styles["PilotBody"],
        )
    )
    flow.append(PageBreak())
    flow.append(Paragraph("4. Verification and support", styles["PilotTitle"]))
    figure("verification-and-support")
    paragraph("Verification and support")
    paragraph("Selection-coverage clarification")
    flow.append(PageBreak())
    flow.append(Paragraph("5. Separate secondary tracks", styles["PilotTitle"]))
    flow.append(Paragraph("Validation - reporting without tuning", styles["Heading2"]))
    table("validation")
    flow.append(
        Paragraph(
            "External source-derived mutations - descriptive only", styles["Heading2"]
        )
    )
    table("external")
    paragraph("Source-derived track")
    paragraph("Artifact provenance")

    def footer(canvas, document):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#526176"))
        canvas.drawString(
            50, 28, "ForgeBench v0.3 pilot | Recorded experimental evidence"
        )
        canvas.drawRightString(A4[0] - 50, 28, str(document.page))

    document = SimpleDocTemplate(
        str(output / "pilot-report.pdf"),
        pagesize=A4,
        leftMargin=50,
        rightMargin=50,
        topMargin=42,
        bottomMargin=48,
        title="ForgeBench v0.3 prospective transfer pilot",
        author="Stelios Zacharioudakis",
    )
    document.build(flow, onFirstPage=footer, onLaterPages=footer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "study",
        type=Path,
        help="Actual finalized study directory with frozen protocol and immutable runs",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New output directory, never overwrites prior evidence",
    )
    parser.add_argument("--pdf", action="store_true")
    args = parser.parse_args()
    report, rows = analyze(args.study)
    if not rows:
        raise ValueError(
            "No actual recorded pilot outcomes; no results plot will be created"
        )
    frozen, manifest, _, _ = read_runs(args.study)
    args.output.mkdir(parents=True, exist_ok=False)
    captions = create_figures(report, rows, args.output / "figures")
    paragraphs = sections(report, rows, frozen, manifest)
    write_markdown(report, rows, paragraphs, captions, args.output)
    if args.pdf:
        write_pdf(report, paragraphs, captions, args.output)
    provenance = {
        "freeze_sha256": frozen["sha256"],
        "study_status": report["status"],
        "completed": report["completed"],
        "planned": report["planned"],
        "report_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "analysis_source_sha256": report["analysis_source_sha256"],
        "outputs": {
            str(p.relative_to(args.output)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(args.output.rglob("*"))
            if p.is_file()
        },
        "performance_numbers_fabricated": False,
        "task_scope": "Authored miniature programs and source-derived artificial mutations",
        "public_inference": False,
        "publication_status": "Technical artifact; no peer-review or preprint submission claim",
    }
    (args.output / "report-provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "recorded_episodes": len(rows),
                "figures": len(captions),
                "pdf_created": args.pdf,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
