#!/usr/bin/env python3
"""Generate OWASP penetration test reports from pytest-json-report output.

Usage:
    # 1. Run tests with pytest-json-report
    pytest tests/security/owasp/ -v -m security \
        --json-report --json-report-file=owasp_results.json

    # 2. Generate reports
    python -m tests.security.owasp.generate_report \
        --input owasp_results.json \
        --html docs/reports/owasp_report.html \
        --json docs/reports/owasp_report.json

If --input is omitted, reads from owasp_results.json in cwd.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# OWASP category metadata
# ---------------------------------------------------------------------------

CATEGORIES: dict[str, tuple[str, str]] = {
    "owasp_a01": ("A01:2021", "Broken Access Control"),
    "owasp_a02": ("A02:2021", "Cryptographic Failures"),
    "owasp_a03": ("A03:2021", "Injection"),
    "owasp_a04": ("A04:2021", "Insecure Design"),
    "owasp_a05": ("A05:2021", "Security Misconfiguration"),
    "owasp_a07": ("A07:2021", "Identification and Authentication Failures"),
    "owasp_a09": ("A09:2021", "Security Logging and Monitoring Failures"),
}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _extract_category(test: dict) -> str:
    """Extract the OWASP category marker from a test's markers list."""
    for marker in test.get("keywords", []):
        if marker in CATEGORIES:
            return marker
    # Fallback: parse from the nodeid (e.g. test_a01_access_control.py)
    nodeid = test.get("nodeid", "")
    for cat_key in CATEGORIES:
        # cat_key = "owasp_a01" → match "a01" in nodeid
        short = cat_key.replace("owasp_", "")
        if short in nodeid:
            return cat_key
    return "unknown"


def _parse_results(raw: dict) -> dict:
    """Parse pytest-json-report output into a structured report."""
    tests = raw.get("tests", [])
    env = raw.get("environment", {})

    # Group tests by OWASP category
    by_category: dict[str, list[dict]] = {k: [] for k in CATEGORIES}
    by_category["unknown"] = []

    for test in tests:
        cat = _extract_category(test)
        outcome = test.get("outcome", "unknown")

        entry = {
            "name": test.get("nodeid", "").split("::")[-1],
            "nodeid": test.get("nodeid", ""),
            "outcome": outcome,
            "duration": round(test.get("duration", 0), 3),
        }

        # Include failure details
        if outcome == "failed":
            call = test.get("call", {})
            entry["message"] = call.get("longrepr", "")[:500]
            entry["crash"] = call.get("crash", {})

        # Include skip reason
        if outcome == "skipped":
            setup = test.get("setup", {})
            call = test.get("call", {})
            longrepr = (
                setup.get("longrepr", "") or call.get("longrepr", "")
            )
            entry["skip_reason"] = str(longrepr)[:200]

        by_category.get(cat, by_category["unknown"]).append(entry)

    # Remove empty unknown bucket
    if not by_category["unknown"]:
        del by_category["unknown"]

    # Build category summaries
    category_summaries = {}
    total_pass = total_fail = total_skip = 0
    for cat_key, cat_tests in by_category.items():
        passed = sum(1 for t in cat_tests if t["outcome"] == "passed")
        failed = sum(1 for t in cat_tests if t["outcome"] == "failed")
        skipped = sum(1 for t in cat_tests if t["outcome"] == "skipped")
        total = len(cat_tests)

        total_pass += passed
        total_fail += failed
        total_skip += skipped

        if cat_key in CATEGORIES:
            code, name = CATEGORIES[cat_key]
        else:
            code, name = "???", "Unknown"

        status = "FAIL" if failed > 0 else ("PASS" if passed > 0 else "SKIP")

        category_summaries[cat_key] = {
            "code": code,
            "name": name,
            "status": status,
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "tests": cat_tests,
        }

    total_tests = total_pass + total_fail + total_skip
    pass_rate = f"{(total_pass / total_tests * 100):.1f}%" if total_tests else "0%"

    return {
        "report_date": datetime.now(UTC).isoformat(),
        "environment": {
            "platform": env.get("Platform", "unknown"),
            "python": env.get("Python", "unknown"),
            "base_url": os.environ.get("TEST_API_URL", "ASGI (in-process)"),
        },
        "summary": {
            "total_tests": total_tests,
            "passed": total_pass,
            "failed": total_fail,
            "skipped": total_skip,
            "pass_rate": pass_rate,
        },
        "categories": category_summaries,
    }


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def write_json_report(report: dict, output_path: Path) -> None:
    """Write the structured report as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"  JSON report: {output_path}")


# ---------------------------------------------------------------------------
# HTML output
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rapport OWASP Top 10 — CRI Chatbot Platform</title>
<style>
  :root {{
    --pass: #5F8B5F; --fail: #B5544B; --skip: #888;
    --bg: #FAF7F2; --card: #fff; --border: #e5ddd5;
    --text: #1a1a1a; --muted: #666;
    --terracotta: #C4704B; --sable: #D4A574;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Inter', system-ui, sans-serif;
    background: var(--bg); color: var(--text);
    line-height: 1.6; padding: 2rem;
  }}
  h1 {{ font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
       font-size: 1.75rem; font-weight: 700; color: var(--terracotta); }}
  h2 {{ font-size: 1.25rem; font-weight: 600; margin-top: 2rem; }}
  .meta {{ color: var(--muted); font-size: 0.85rem; margin: 0.5rem 0 1.5rem; }}
  .summary-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 1rem; margin-bottom: 2rem;
  }}
  .summary-card {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 8px; padding: 1rem; text-align: center;
  }}
  .summary-card .value {{ font-size: 1.8rem; font-weight: 700; }}
  .summary-card .label {{ font-size: 0.8rem; color: var(--muted); text-transform: uppercase; }}
  .v-pass {{ color: var(--pass); }}
  .v-fail {{ color: var(--fail); }}
  .v-skip {{ color: var(--skip); }}
  table {{
    width: 100%; border-collapse: collapse; margin: 1rem 0;
    background: var(--card); border-radius: 8px; overflow: hidden;
    border: 1px solid var(--border);
  }}
  th, td {{ padding: 0.65rem 1rem; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ background: #f5f0ea; font-size: 0.8rem; text-transform: uppercase;
       color: var(--muted); font-weight: 600; }}
  .badge {{
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 0.75rem; font-weight: 600; color: #fff;
  }}
  .badge-pass {{ background: var(--pass); }}
  .badge-fail {{ background: var(--fail); }}
  .badge-skip {{ background: var(--skip); }}
  details {{ margin: 0.25rem 0; }}
  details summary {{ cursor: pointer; font-size: 0.85rem; color: var(--muted); }}
  details pre {{
    background: #f5f0ea; padding: 0.75rem; border-radius: 4px;
    font-size: 0.8rem; overflow-x: auto; margin-top: 0.5rem;
    white-space: pre-wrap; word-break: break-word;
  }}
  footer {{ margin-top: 3rem; font-size: 0.8rem; color: var(--muted); text-align: center; }}
</style>
</head>
<body>

<h1>Rapport de Tests de Pénétration OWASP Top 10</h1>
<p class="meta">
  CRI Chatbot Platform &mdash; {report_date}<br>
  Environnement : {env_url} | Python {python_ver} | {platform}
</p>

<!-- Summary cards -->
<div class="summary-grid">
  <div class="summary-card"><div class="value">{total}</div><div class="label">Total</div></div>
  <div class="summary-card"><div class="value v-pass">{passed}</div><div class="label">Réussis</div></div>
  <div class="summary-card"><div class="value v-fail">{failed}</div><div class="label">Échoués</div></div>
  <div class="summary-card"><div class="value v-skip">{skipped}</div><div class="label">Ignorés</div></div>
  <div class="summary-card"><div class="value">{pass_rate}</div><div class="label">Taux réussite</div></div>
</div>

<!-- Category table -->
<h2>Résultats par catégorie OWASP</h2>
<table>
  <thead><tr>
    <th>Code</th><th>Catégorie</th><th>Statut</th>
    <th>Réussis</th><th>Échoués</th><th>Ignorés</th>
  </tr></thead>
  <tbody>
{category_rows}
  </tbody>
</table>

<!-- Detailed results -->
<h2>Détail des tests</h2>
{detail_sections}

<footer>
  Généré automatiquement par <code>generate_report.py</code> &mdash;
  Livrable CPS L5 — Appel d'offres N° 02/2026/CRI RSK
</footer>
</body>
</html>
"""


def _badge(outcome: str) -> str:
    cls = {"passed": "badge-pass", "failed": "badge-fail"}.get(outcome, "badge-skip")
    label = {"passed": "PASS", "failed": "FAIL", "skipped": "SKIP"}.get(
        outcome, outcome.upper()
    )
    return f'<span class="badge {cls}">{label}</span>'


def _status_badge(status: str) -> str:
    cls = {"PASS": "badge-pass", "FAIL": "badge-fail"}.get(status, "badge-skip")
    return f'<span class="badge {cls}">{status}</span>'


def write_html_report(report: dict, output_path: Path) -> None:
    """Render the report as a styled HTML file."""
    summary = report["summary"]
    env = report["environment"]

    # Category rows
    cat_rows = []
    for cat in report["categories"].values():
        cat_rows.append(
            f"    <tr>"
            f"<td><strong>{html.escape(cat['code'])}</strong></td>"
            f"<td>{html.escape(cat['name'])}</td>"
            f"<td>{_status_badge(cat['status'])}</td>"
            f"<td>{cat['passed']}</td>"
            f"<td>{cat['failed']}</td>"
            f"<td>{cat['skipped']}</td>"
            f"</tr>"
        )

    # Detail sections
    detail_parts = []
    for cat_key, cat in report["categories"].items():
        rows = []
        for t in cat["tests"]:
            extra = ""
            if t["outcome"] == "failed" and t.get("message"):
                msg = html.escape(t["message"])
                extra = (
                    f"<details><summary>Détails erreur</summary>"
                    f"<pre>{msg}</pre></details>"
                )
            elif t["outcome"] == "skipped" and t.get("skip_reason"):
                reason = html.escape(t["skip_reason"])
                extra = f'<span style="font-size:0.8rem;color:var(--muted)">— {reason}</span>'
            rows.append(
                f"    <tr>"
                f"<td>{html.escape(t['name'])}</td>"
                f"<td>{_badge(t['outcome'])}</td>"
                f"<td>{t['duration']}s</td>"
                f"<td>{extra}</td>"
                f"</tr>"
            )
        section = (
            f"<h3 style='margin-top:1.5rem'>{html.escape(cat['code'])} — "
            f"{html.escape(cat['name'])}</h3>\n"
            f"<table><thead><tr>"
            f"<th>Test</th><th>Résultat</th><th>Durée</th><th>Détails</th>"
            f"</tr></thead><tbody>\n"
            + "\n".join(rows)
            + "\n  </tbody></table>"
        )
        detail_parts.append(section)

    rendered = _HTML_TEMPLATE.format(
        report_date=report["report_date"][:19].replace("T", " "),
        env_url=html.escape(env.get("base_url", "unknown")),
        python_ver=html.escape(env.get("python", "?")),
        platform=html.escape(env.get("platform", "?")),
        total=summary["total_tests"],
        passed=summary["passed"],
        failed=summary["failed"],
        skipped=summary["skipped"],
        pass_rate=summary["pass_rate"],
        category_rows="\n".join(cat_rows),
        detail_sections="\n".join(detail_parts),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"  HTML report: {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate OWASP penetration test report from pytest-json-report"
    )
    parser.add_argument(
        "--input",
        default="owasp_results.json",
        help="Path to pytest-json-report JSON file (default: owasp_results.json)",
    )
    parser.add_argument("--html", default=None, help="Output HTML report path")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        print(
            "\nRun tests first:\n"
            "  pytest tests/security/owasp/ -v -m security "
            f"--json-report --json-report-file={input_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    raw = json.loads(input_path.read_text(encoding="utf-8"))
    report = _parse_results(raw)

    print(f"\nOWASP Penetration Test Report")
    print(f"  Total: {report['summary']['total_tests']}")
    print(f"  Passed: {report['summary']['passed']}")
    print(f"  Failed: {report['summary']['failed']}")
    print(f"  Skipped: {report['summary']['skipped']}")
    print(f"  Pass rate: {report['summary']['pass_rate']}")
    print()

    if args.json:
        write_json_report(report, Path(args.json))
    if args.html:
        write_html_report(report, Path(args.html))

    if not args.json and not args.html:
        # Default: write both to docs/reports/
        write_json_report(report, Path("docs/reports/owasp_report.json"))
        write_html_report(report, Path("docs/reports/owasp_report.html"))

    # Exit with non-zero if any test failed
    if report["summary"]["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
