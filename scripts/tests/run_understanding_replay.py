"""Replay frozen understanding packets; not an end-to-end capture quality test.

Each worker has a new checkpoint workspace. All API calls are retained, including
failed correction attempts. Expected labels are never supplied to the model.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n")


def worker(packet_path, output):
    from common import capture_clarification as gate
    from common import openai_reasoning as reasoning
    from common.capture_understanding import model_settings
    output.mkdir(parents=True, exist_ok=False)
    packet = json.loads(packet_path.read_text())
    save(output / "packet.json", packet)
    sequence = [0]
    factory = reasoning._openai_client

    class AuditedClient:
        def __init__(self, client):
            self.client = client
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def with_options(self, **options):
            return AuditedClient(self.client.with_options(**options))

        def create(self, **kwargs):
            sequence[0] += 1
            prefix = output / "calls" / f"{sequence[0]:02d}"
            save(prefix.with_suffix(".request.json"), kwargs)
            try:
                result = self.client.chat.completions.create(**kwargs)
            except Exception as error:
                body = getattr(error, "body", {}) or {}
                detail = body.get("error", body) if isinstance(body, dict) else {}
                save(prefix.with_suffix(".error.json"), {"type": type(error).__name__, "status": getattr(error, "status_code", None),
                                                         "provider_code": detail.get("code")})
                raise
            save(prefix.with_suffix(".response.json"), result.model_dump())
            return result

    def client_factory():
        client = factory()
        return AuditedClient(client.with_options(max_retries=0)) if client else None

    reasoning._openai_client = client_factory
    state = gate.checkpoint(output / "workspace", packet)
    save(output / "state.json", state)
    report = {"status": state["status"], "calls": sequence[0], "questions": len(state["questions"]),
              "technical_issues": state["technical_issues"], "input_sha256": hashlib.sha256(packet_path.read_bytes()).hexdigest(),
              "source_packet": str(packet_path), "stage": "understanding_only_no_market_research_or_final_memo",
              "model": model_settings()["model"], "model_settings": model_settings()}
    save(output / "result.json", report)
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", default=",".join(f"C{i:02d}" for i in range(1, 26)))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    if args.packet:
        worker(args.packet, args.output)
        return
    if not args.baseline:
        parser.error("--baseline or --packet is required")
    args.output.mkdir(parents=True, exist_ok=False)
    jobs = [(case, repeat, args.baseline / f"{case}-focused-r{repeat}" / "audit/understanding-input.json")
            for case in args.cases.split(",") for repeat in range(1, args.repeats + 1)]
    from common.capture_understanding import model_settings
    save(args.output / "plan.json", {"model_settings": model_settings(), "jobs": [{"case": c, "repeat": r, "input": str(p),
                                              "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for c, r, p in jobs],
                                     "note": "Frozen model inputs; inspect model_settings and runtime snapshot for experimental changes. No expected labels in prompts."})

    def run(job):
        case, repeat, packet = job
        folder = args.output / f"{case}-r{repeat}"
        try:
            result = subprocess.run([sys.executable, __file__, "--packet", str(packet), "--output", str(folder)],
                                    text=True, capture_output=True, timeout=1200)
            save(folder / "worker.json", {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
            if result.returncode:
                return {"case": case, "repeat": repeat, "status": "WORKER_ERROR"}
            return {"case": case, "repeat": repeat, **json.loads((folder / "result.json").read_text())}
        except subprocess.TimeoutExpired:
            save(folder / "worker.json", {"error": "timeout_after_1200_seconds"})
            return {"case": case, "repeat": repeat, "status": "WORKER_TIMEOUT"}

    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(run, job) for job in jobs]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            save(args.output / "progress.json", results)
            print(json.dumps(result), flush=True)
    save(args.output / "results.json", results)


if __name__ == "__main__":
    main()
