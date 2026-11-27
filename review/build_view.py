"""Rebuild the standalone operator replay from the local agent's actual report."""
import json
import subprocess
import sys
from pathlib import Path

from replay_steps import replay_steps

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
    for case in report["cases"]:
        case["steps"] = replay_steps(case)
    embedded = json.dumps(report, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    template = (HERE / "view_template.html").read_text(encoding="utf-8")
    assets = {
        "__REPLAY_CSS__": (HERE / "replay.css").read_text(encoding="utf-8"),
        "__REPLAY_JS__": (HERE / "replay.js").read_text(encoding="utf-8"),
        "__PICKUP_REPORT_JSON__": embedded,
    }
    for token, value in assets.items():
        if template.count(token) != 1:
            raise ValueError(f"Expected one {token} placeholder in the replay template.")
        template = template.replace(token, value)
    output = HERE / "Pickup_Operations.html"
    output.write_bytes(template.encode("utf-8"))
    print(f"{output.name}: {len(report['cases'])} cases and {sum(len(c['turns']) for c in report['cases'])} turns.")


if __name__ == "__main__":
    build()
