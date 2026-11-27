"""Rebuild the standalone operator replay from the local agent's actual report."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent / "agent" / "demo.py"


def build():
    run = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", str(DEMO), "--report"],
        cwd=DEMO.parent, check=True, stdout=subprocess.PIPE, encoding="utf-8",
    )
    report = json.loads(run.stdout)
    if not report["cases"] or any(not case["turns"] for case in report["cases"]):
        raise ValueError("Each replay needs at least one recorded turn.")
    embedded = json.dumps(report, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    template = (HERE / "view_template.html").read_text(encoding="utf-8")
    token = "__PICKUP_REPORT_JSON__"
    if template.count(token) != 1:
        raise ValueError("The replay template must have exactly one data location.")
    output = HERE / "Pickup_Operations.html"
    output.write_bytes(template.replace(token, embedded).encode("utf-8"))
    print(f"{output.name}: {len(report['cases'])} cases and {sum(len(c['turns']) for c in report['cases'])} turns.")


if __name__ == "__main__":
    build()
