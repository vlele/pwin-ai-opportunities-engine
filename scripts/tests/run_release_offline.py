"""Run the release fixture suites without provider credentials; preserve every log."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from evaluate_release_readiness import REQUIRED_OFFLINE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    args.output.mkdir(parents=True, exist_ok=False)
    env = {k: v for k, v in os.environ.items()
           if not any(marker in k.upper() for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD"))}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    commands = {"unittest": [sys.executable, "-m", "unittest", "discover", "-s", "scripts/tests", "-p", "test_*.py"]}
    commands.update({name: [sys.executable, f"scripts/tests/{name}.py"]
                     for name in sorted(REQUIRED_OFFLINE - {"unittest", "diff-check"})})
    commands["diff-check"] = ["git", "diff", "--check"]
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (root / "scripts").rglob("*.py")}
    (args.output / "runtime-hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")
    results = []
    for name, command in commands.items():
        try:
            result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=300)
            code, log = result.returncode, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            code, log = 124, "Suite exceeded its 300 second limit.\n"
        (args.output / f"{name}.log").write_text(log)
        results.append({"suite": name, "exit_code": code, "command": command})
        (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps({"suite": name, "exit_code": code}), flush=True)
    current = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in (root / "scripts").rglob("*.py")}
    if current != hashes:
        results.append({"suite": "runtime-integrity", "exit_code": 1, "error": "Source changed during offline verification"})
        (args.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    raise SystemExit(0 if all(r["exit_code"] == 0 for r in results) else 1)


if __name__ == "__main__":
    main()
