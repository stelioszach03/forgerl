#!/usr/bin/env python3
"""Generate a measured technical report and reproducible scientific figures.

Optional rendering dependencies: matplotlib and reportlab. This script makes no
model requests. It does not publish or submit a paper anywhere.
"""
from __future__ import annotations
import argparse
import html
import json
import math
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forgerl.bench.router import POLICIES, ACTIONS

NAMES = {"strong_only": "Strong only", "cheap_only": "Cheap only", "escalate_on_failure": "Escalate on failure", "static_router": "Static router", "adaptive": "Adaptive router"}
COLORS = {"strong_only": "#213e5e", "cheap_only": "#7c93a8", "escalate_on_failure": "#5363a1", "static_router": "#bc8941", "adaptive": "#137e80"}
REFERENCES = [
    ("Jimenez et al. SWE-bench: Can Language Models Resolve Real-World GitHub Issues?", "https://arxiv.org/abs/2310.06770"),
    ("Ong et al. RouteLLM: Learning to Route LLMs with Preference Data.", "https://arxiv.org/abs/2406.18665"),
    ("Chen, Zaharia and Zou. FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance.", "https://arxiv.org/abs/2305.05176"),
]


def number(value, digits=2):
    return "not measured" if value is None else f"{value:.{digits}f}"


def percentage(value):
    return "not measured" if value is None else f"{100*value:.1f}%"


def load_input(directory):
    directory = Path(directory)
    benchmark = json.loads((directory/"benchmark.json").read_text())
    if benchmark.get("version") != "0.2":
        raise ValueError("Report requires ForgeBench v0.2 artifacts")
    traces = []
    path = directory/"trajectories.jsonl"
    if path.is_file():
        traces = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return benchmark, traces


def report_sections(benchmark):
    coverage, provenance = benchmark["coverage"], benchmark["provenance"]
    rows = benchmark["summary"]
    tests = [r for r in benchmark["runs"] if r["split"] == "test"]
    adaptive = next((r for r in rows if r["policy"] == "adaptive"), {})
    strong = next((r for r in rows if r["policy"] == "strong_only"), {})
    models = ", ".join(m["id"] for m in benchmark.get("models", [])) or "No models yet observed in evaluation traces"
    families = len({r["family"] for r in tests})
    attempted, successes = len(tests), sum(r["status"] == "completed" and r["solved"] for r in tests)
    observations = (f"Adaptive routing solved {adaptive.get('solved', 0)}/{adaptive.get('n', 0)} test episodes "
        f"({percentage(adaptive.get('solve_rate'))}), compared with {strong.get('solved', 0)}/{strong.get('n', 0)} "
        f"({percentage(strong.get('solve_rate'))}) for strong-only. Mean accounted API cost per attempted episode was "
        f"${number(adaptive.get('mean_cost_usd'), 6)} for adaptive and ${number(strong.get('mean_cost_usd'), 6)} for strong-only. "
        "These are descriptive observations on this authored suite; they do not establish broad model or router superiority.") if adaptive.get("n") and strong.get("n") else "A matched adaptive/strong-only comparison is not yet measured. No cost-quality advantage is claimed."
    learned, fallback = adaptive.get("learned_decisions", 0), adaptive.get("fallback_decisions", 0)
    sections = [
        ("Abstract", f"ForgeBench v0.2 studies observable-state routing for bounded coding repair agents on {benchmark['task_count']} authored miniature Python tasks. "
         f"This artifact contains {coverage['completed']}/{coverage['planned']} planned evaluation episodes and {coverage.get('training_completed', 0)}/{coverage.get('training_planned', 0)} training episodes; status: {benchmark['status']}. "
         f"The test summary covers {attempted} episodes on {len({r['task_id'] for r in tests})} observed tasks from {families} families. "
         "Five policies share the same execution and stopping contract. Full prompts, visible responses, edits and test trajectories are retained. " + observations),
        ("Motivation and related work", "Routing can trade model-call expense against solution quality. RouteLLM studies learned model selection using preference data [2]; FrugalGPT studies learned cascades [3]. "
         "SWE-bench evaluates real GitHub issue resolution [1]. ForgeBench is a small, transparent engineering research platform for repeated multi-file repair decisions; it is not a SWE-bench result, a replication of those methods, or evidence of research novelty by itself."),
        ("Benchmark and split", "The catalog contains ten domain families with five related variants each. The fixed split is 30 training, 10 validation and 10 test tasks with disjoint families. "
         "Tasks cover bug fixes, linked-module changes, features, refactoring, failing tests and integrated multi-requirement stress cases. Every task has a visible reproduction, explicit success criterion, hidden checks and a reference implementation. "
         "Hidden tests are withheld from the agent during episodes; the reproducible repository publishes the test definitions. This does not provide a private, contamination-resistant holdout. Related variants share interfaces and cannot be treated as fully independent repositories."),
        ("Method and baselines", "The harness supplies flat Python modules and visible test feedback to hosted language models. Routing actions are retry, repair, escalate, rollback and stop. "
         "The five policies are strong-only, cheap-only, cheap-to-strong after visible failure, a hand-written router and an offline fitted-Q router. Learned observations contain visible outcomes and budget/attempt state, never task identity, hidden results or reference patches. "
         "A train-only artifact is frozen before validation/test; unseen state/action support uses an explicitly labeled static fallback. Hosted language-model weights are unchanged. "
         f"The adaptive test traces contain {learned} learned decisions and {fallback} fallback decisions. Observed evaluation model IDs: {models}."),
        ("Execution and experiment controls", "Candidate code executes only inside a disposable networkless, read-only, non-root container with resource and output bounds; expected answers remain in the trusted host grader. "
         "Policies share at most six model calls, ten routing decisions, an equal output token ceiling and a 100,000-token episode budget; explicit retry and invalid-response retry limits bound loops. "
         "Public-test success ends routing; hidden grading runs once after all decisions. Seeds 17, 29 and 43 are predeclared independent hosted sampling requests, not guaranteed deterministic samples. "
         "A separate train-only controller is fitted per seed. Validation is reported without parameter selection. Failed and missing episodes remain in the artifacts, and the public demo only reads recorded evidence."),
        ("Metrics and results", observations + " Task success requires all visible and hidden checks with completed grading. Success rates divide solved by attempted episodes, including failed provider or execution attempts. "
         "Hidden-test pass rates describe graded hidden cases and show graded coverage. Token counts remain unknown when accounting is unavailable. "
         f"Cost basis: {provenance.get('cost_basis') or provenance.get('provider', {}).get('cost_basis', 'See provider manifest')}. "
         "Latency includes network, hosted inference and sandbox work, not GPU-seconds. The cost-quality plot displays observed policy means; no Pareto superiority is implied for incomplete or unmatched coverage."),
        ("Failure analysis and action use", "Failure labels describe observable events: invalid candidate, rejected execution, visible regression, repeated identical candidate, or visible-pass/hidden-fail. "
         "Labels can co-occur. Localization, planning and context-loss causes require additional annotation and are not inferred from these proxies. "
         "Regressions count previously passing visible checks made failing. Success-after-repair uses runs with more than one model attempt as its denominator. Escalation frequency counts cheap-to-strong switches, not starting strong. "
         "Unnecessary edits is a post-decision reference-scope proxy: changed files outside the supplied reference patch's file set. Alternative valid solutions may count. Tool calls count harness-orchestrated sandbox checks; the model does not independently operate a shell."),
        ("Uncertainty, ablations and limitations", f"The observed test set has {families} held-out families. Seeds are averaged within tasks and related tasks are grouped by family for paired comparisons. "
         "With fewer than three families, no family-bootstrap interval is estimated. Repeated seeds do not increase the number of independent families. "
         "The baseline comparisons separate policy behavior, but causal ablations of rollback, repair instructions, budget features and reward weights have not been run and are not claimed. "
         "The long_horizon category is an authored multi-requirement stress category, not demonstrated long-horizon autonomy. Small repositories, transparent test definitions, sparse learned-state support, possible pretraining contamination, provider nondeterminism and limited external validity constrain conclusions."),
        ("Reproducibility and next experiments", "The release includes versioned task definitions, an execution contract, frozen controllers, per-event trajectories, source/provenance hashes, results.csv, failure_analysis.csv and bootstrap_results.json. "
         "The CLI plans by default and paid research requires explicit execution with the existing durable ledger. Original study artifacts are not overwritten. "
         "Next work should add genuinely distinct families, preregister causal ablations, audit failure labels manually, and evaluate real repository issues before making broader generalization or long-horizon claims. New model runs must preserve provider, price and configuration provenance."),
    ]
    return sections


def create_figures(benchmark, traces, directory):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 14, "axes.labelsize": 11, "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "white", "axes.titleweight": "bold", "svg.fonttype": "none"})
    summaries = benchmark["summary"]
    tests = [r for r in benchmark["runs"] if r["split"] == "test"]
    captions = {}
    def save(fig, name, caption):
        fig.text(.02, .02, caption, ha="left", va="bottom", fontsize=8, color="#526176", wrap=True)
        fig.tight_layout(rect=(0, .09, 1, 1))
        for extension in ("png", "svg", "pdf"):
            fig.savefig(directory/(name+"."+extension), dpi=220, bbox_inches="tight")
        plt.close(fig)
        captions[name] = caption
    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    rows = [r for r in summaries if r.get("mean_cost_usd") is not None and r.get("solve_rate") is not None]
    if rows:
        for index, row in enumerate(rows):
            ax.scatter(row["mean_cost_usd"], row["solve_rate"]*100, s=110, color=COLORS[row["policy"]], marker=("o", "s", "^", "D", "P")[index], zorder=3, label=f"{NAMES[row['policy']]} (n={row['n']})")
        ax.legend(fontsize=8, frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1))
        ax.set_xlim(left=0, right=max(r["mean_cost_usd"] for r in rows)*1.5 or .001)
    else:
        ax.text(.5, .5, "No measured test-policy results", transform=ax.transAxes, ha="center")
    ax.set(title="Success versus accounted cost", xlabel="Mean accounted API cost per attempted test episode (USD)", ylabel="Test episodes solved (%)", ylim=(-3, 110))
    ax.grid(alpha=.18)
    save(fig, "success-vs-cost", "Observed policy means; attempted runs retained. No uncertainty interval with only two held-out families.")
    labels = sorted({label for run in tests for label in run.get("failure_labels", [])})
    fig, ax = plt.subplots(figsize=(9.0, 5.1))
    if labels:
        x, width = np.arange(len(labels)), .15
        for index, policy in enumerate(POLICIES):
            subset = [r for r in tests if r["policy"] == policy]
            values = [100*sum(label in r.get("failure_labels", []) for r in subset)/len(subset) if subset else float("nan") for label in labels]
            ax.bar(x+(index-2)*width, values, width, label=NAMES[policy], color=COLORS[policy])
        ax.set_xticks(x, [label.replace(":", ":\n").replace("_", " ") for label in labels], fontsize=8)
        ax.legend(fontsize=8, ncol=3, frameon=False)
    else:
        ax.text(.5, .5, "No recorded failure proxies in available test runs", transform=ax.transAxes, ha="center", wrap=True)
    ax.set(title="Observed failure proxies", ylabel="Attempted test runs with label (%)", ylim=(0, 110))
    save(fig, "failure-proxies", "Nonexclusive labels describe observable events; they do not identify causal planning or localization failures.")
    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    counts = {policy: Counter() for policy in POLICIES}
    for record in traces:
        run = record["run"]
        if record.get("phase") == "evaluation" and run.get("split") == "test" and run.get("policy") in counts:
            for event in run.get("events", []):
                if event.get("kind") == "decision" and event.get("data", {}).get("action") in ACTIONS:
                    counts[run["policy"]][event["data"]["action"]] += 1
    bottom, x = np.zeros(len(POLICIES)), np.arange(len(POLICIES))
    for action, color in zip(ACTIONS, ("#7c93a8", "#137e80", "#213e5e", "#bc8941", "#9e6973")):
        values = np.array([counts[policy][action] for policy in POLICIES])
        ax.bar(x, values, bottom=bottom, label=action, color=color)
        bottom += values
    ax.set_xticks(x, [NAMES[p].replace(" ", "\n") for p in POLICIES])
    ax.set(title="Actual routing decisions", ylabel="Recorded test-episode decisions")
    ax.legend(ncol=5, loc="upper center", fontsize=8, frameon=False)
    ax.set_ylim(0, max(1, float(bottom.max()))*1.3)
    save(fig, "routing-decisions", "Counts come from recorded decision events. A zero is an observed absence, not proof that an action is unnecessary.")
    fig, ax = plt.subplots(figsize=(9.0, 5.0))
    categories = sorted({r["category"] for r in tests})
    if categories:
        values = np.full((len(POLICIES), len(categories)), np.nan)
        for i, policy in enumerate(POLICIES):
            for j, category in enumerate(categories):
                subset = [r for r in tests if r["policy"] == policy and r["category"] == category]
                if subset:
                    solved = sum(r["status"] == "completed" and r["solved"] for r in subset)
                    values[i, j] = solved/len(subset)
                    ax.text(j, i, f"{solved}/{len(subset)}", ha="center", va="center", color="white" if values[i,j] > .55 else "#172c40", fontsize=10)
        image = ax.imshow(values, vmin=0, vmax=1, cmap="PuBuGn", aspect="auto")
        ax.set_xticks(range(len(categories)), [c.replace("_", "\n") for c in categories])
        ax.set_yticks(range(len(POLICIES)), [NAMES[p] for p in POLICIES])
        fig.colorbar(image, ax=ax, label="Observed solve rate")
    else:
        ax.text(.5, .5, "No category results measured", transform=ax.transAxes, ha="center")
    ax.set_title("Success by authored task category")
    save(fig, "task-categories", "Cells show solved/attempted episodes. 'long horizon' is a multi-requirement stress label, not demonstrated autonomy.")
    (directory/"captions.json").write_text(json.dumps(captions, indent=2)+"\n")
    return captions


def write_markdown(benchmark, sections, captions, path):
    rows = ["# Adaptive routing for bounded coding agents", "", "## ForgeBench v0.2 technical report", "", "Stelios Zacharioudakis  |  Research software artifact; not peer reviewed or submitted as a preprint.", "", f"Evidence generated: {benchmark['generated_at']}  |  Coverage status: **{benchmark['status']}**", ""]
    for heading, paragraph in sections:
        rows.extend(["## "+heading, "", paragraph, ""])
        if heading == "Metrics and results":
            rows.extend(["| Policy | Solved / attempted | Success | Mean cost (USD) | Mean tokens | Mean latency (s) |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
            for row in benchmark["summary"]:
                rows.append(f"| {NAMES[row['policy']]} | {row['solved']}/{row['n']} | {percentage(row.get('solve_rate'))} | {number(row.get('mean_cost_usd'), 6)} | {number(row.get('mean_tokens'), 1)} | {number(row.get('mean_latency_s'), 1)} |")
            rows.append("")
    rows.extend(["## Figures", ""])
    for name, caption in captions.items():
        rows.extend([f"![{caption}](figures/{name}.svg)", "", caption, ""])
    rows.extend(["## References", ""]+[f"{i}. [{title}]({url})" for i, (title, url) in enumerate(REFERENCES, 1)]+[""])
    Path(path).write_text("\n".join(rows))


def write_pdf(benchmark, sections, captions, directory):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, KeepTogether
    directory = Path(directory)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=colors.HexColor("#213e5e"), spaceAfter=16))
    styles.add(ParagraphStyle(name="ReportBody", fontName="Helvetica", fontSize=10, leading=14, spaceAfter=10))
    styles.add(ParagraphStyle(name="ReportCaption", fontName="Helvetica", fontSize=8, leading=11, textColor=colors.HexColor("#526176"), spaceAfter=10))
    styles["Heading2"].textColor = colors.HexColor("#137e80")
    styles["Heading2"].keepWithNext = True
    styles["Heading1"].keepWithNext = True
    styles["ReportBody"].allowOrphans = False
    styles["ReportBody"].allowWidows = False
    flow = [Paragraph("Adaptive routing for<br/>bounded coding agents", styles["ReportTitle"]), Paragraph("ForgeBench v0.2 technical report", styles["Heading2"]), Paragraph("Stelios Zacharioudakis", styles["ReportBody"]), Paragraph("Research software artifact. Not peer reviewed; not submitted as a preprint.", styles["ReportCaption"]), Paragraph(html.escape(f"Evidence: {benchmark['generated_at']} | Coverage: {benchmark['status']}"), styles["ReportCaption"]), Spacer(1, 12)]
    for heading, paragraph in sections:
        flow.append(Paragraph(heading, styles["Heading2"]))
        flow.append(Paragraph(html.escape(paragraph), styles["ReportBody"]))
        if heading == "Metrics and results":
            table = [["Policy", "Solved / n", "Success", "Cost (USD)", "Latency (s)"]]
            for row in benchmark["summary"]:
                table.append([NAMES[row["policy"]], f"{row['solved']}/{row['n']}", percentage(row.get("solve_rate")), number(row.get("mean_cost_usd"), 6), number(row.get("mean_latency_s"), 1)])
            table = [[Paragraph(html.escape(str(cell)), styles["ReportCaption"]) for cell in row] for row in table]
            block = Table(table, colWidths=[132, 70, 72, 90, 85], repeatRows=1)
            block.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,0),colors.HexColor("#edf3f6")), ("VALIGN",(0,0),(-1,-1),"TOP"), ("BOTTOMPADDING",(0,0),(-1,-1),7), ("TOPPADDING",(0,0),(-1,-1),7), ("LINEBELOW",(0,0),(-1,0),.5,colors.HexColor("#b4c6d3")), ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f7f9fb")])]))
            flow.extend([block, Spacer(1, 12)])
    flow.append(Spacer(1, 16))
    flow.append(Paragraph("Recorded results: figures", styles["Heading1"]))
    for index, (name, caption) in enumerate(captions.items(), 1):
        image = Image(str(directory/"figures"/(name+".png")))
        image.drawHeight = image.imageHeight * (450/image.imageWidth)
        image.drawWidth = 450
        flow.append(KeepTogether([image, Paragraph(f"Figure {index}. "+html.escape(caption), styles["ReportCaption"])]))
    flow.append(Paragraph("References", styles["Heading2"]))
    for index, (title, url) in enumerate(REFERENCES, 1):
        flow.append(Paragraph(f'{index}. {html.escape(title)} <link href="{url}" color="#137e80">{url}</link>', styles["ReportBody"]))
    def footer(canvas, document):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#526176"))
        canvas.drawString(50, 28, "ForgeBench v0.2 | Technical report | Recorded experimental evidence")
        canvas.drawRightString(A4[0]-50, 28, str(document.page))
    document = SimpleDocTemplate(str(directory/"technical-report.pdf"), pagesize=A4, leftMargin=50, rightMargin=50, topMargin=45, bottomMargin=48, title="Adaptive routing for bounded coding agents: ForgeBench v0.2", author="Stelios Zacharioudakis")
    document.build(flow, onFirstPage=footer, onLaterPages=footer)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--input", type=Path, required=True, help="Aggregated benchmark and trajectory export directory")
    cli.add_argument("--output", type=Path, help="Defaults to the input directory")
    cli.add_argument("--pdf", action="store_true", help="Also render a PDF with reportlab; visually verify before publication")
    args = cli.parse_args()
    benchmark, traces = load_input(args.input)
    output = args.output or args.input
    output.mkdir(parents=True, exist_ok=True)
    captions = create_figures(benchmark, traces, output/"figures")
    sections = report_sections(benchmark)
    write_markdown(benchmark, sections, captions, output/"technical-report.md")
    if args.pdf:
        write_pdf(benchmark, sections, captions, output)
    print(json.dumps({"output": str(output), "figure_count": len(captions), "status": benchmark["status"], "pdf_created": args.pdf}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
