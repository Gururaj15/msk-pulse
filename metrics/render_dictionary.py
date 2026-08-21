"""
Renders metrics.yml into a readable Markdown doc (docs page for the repo /
GitHub Pages). Keeps the YAML as the single source of truth and the Markdown
as a generated artifact -- never hand-edit the .md output.

Usage: python render_dictionary.py
"""
from pathlib import Path

import yaml

HERE = Path(__file__).parent


def render() -> None:
    with open(HERE / "metrics.yml") as f:
        doc = yaml.safe_load(f)

    lines = [
        "# MSK Pulse — Metrics Dictionary",
        "",
        "> Generated from `metrics/metrics.yml`. Do not hand-edit this file — edit the YAML and re-run `render_dictionary.py`.",
        "",
        "Every number in this repo's dashboards, analyses, and memos traces back to one of these definitions. "
        "If a chart and this page disagree, the chart is wrong.",
        "",
    ]

    for m in doc["metrics"]:
        lines.append(f"## `{m['name']}`")
        lines.append("")
        lines.append(f"**Owner:** {m['owner']}  ")
        lines.append(f"**Grain:** {m['grain']}")
        lines.append("")
        lines.append(m["description"].strip())
        lines.append("")
        lines.append("**Canonical SQL**")
        lines.append("```sql")
        lines.append(m["sql"].strip())
        lines.append("```")
        if m.get("edge_cases"):
            lines.append("")
            lines.append("**Known edge cases**")
            for e in m["edge_cases"]:
                lines.append(f"- {e}")
        lines.append("")
        lines.append("---")
        lines.append("")

    out_path = HERE / "METRICS_DICTIONARY.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path} ({len(doc['metrics'])} metrics)")


if __name__ == "__main__":
    render()
