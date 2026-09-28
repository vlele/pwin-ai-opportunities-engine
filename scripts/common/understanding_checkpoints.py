"""Private, content-addressed model receipts, never substitutes for validation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

FORMAT = 1
MAX_RECORD_BYTES = 32 * 1024 * 1024
MAX_LEDGER_STORAGE_BYTES = 32 * 1024 * 1024
MAX_MODEL_INPUT_CHARS = 640000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def runtime_identity():
    root = Path(__file__).parent
    return digest({
        "common_code": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(root.glob("*.py"))},
        "python": list(sys.version_info[:2]),
        "provider": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    })


def request_chars(prompt, payload, schema):
    # Include instructions and the structured-output schema, not just source text.
    request = {"system_prompt": prompt, "user_payload": payload,
               "response_schema": {"name": "capture_understanding", "schema": schema, "strict": True}}
    return len(json.dumps(request))


def check_request_budget(prompt, payload, schema, limit):
    size = request_chars(prompt, payload, schema)
    if size > limit:
        raise ValueError(f"Model request requires {size} characters; limit is {limit}. "
                         "No silent truncation; coverage-preserving batching is required.")
    return size


def ledger_metrics(facts, coverage):
    size = len(json.dumps(facts).encode())
    return {"fact_count": len(facts), "coverage_count": len(coverage),
            "storage_bytes": size, "storage_limit_bytes": MAX_LEDGER_STORAGE_BYTES,
            "used_as_model_input": False}


def validate_ledger(facts, coverage):
    if not facts:
        raise ValueError("Fact ledger is empty; extraction did not produce material facts.")
    metrics = ledger_metrics(facts, coverage)
    if metrics["storage_bytes"] > MAX_LEDGER_STORAGE_BYTES:
        raise ValueError("Fact ledger exceeds the audit storage safety limit; "
                         "validated batches remain in stage checkpoints. No facts were truncated.")
    return metrics


class StageCheckpoints:
    def __init__(self, folder, *, scope, runtime=None):
        self.folder = Path(folder)
        self.scope = digest(scope)
        self.runtime = runtime or runtime_identity()

    def key(self, stage, prompt, payload, schema, settings):
        return digest({"format": FORMAT, "scope": self.scope, "runtime": self.runtime,
                       "stage": stage, "prompt": prompt, "payload": payload,
                       "schema": schema, "model_settings": settings})

    def load(self, key):
        path = self.folder / (key + ".json")
        if not path.exists():
            return None
        try:
            if path.stat().st_size > MAX_RECORD_BYTES:
                raise ValueError("record exceeds storage safety limit")
            row = json.loads(path.read_text())
            if (row["format"] != FORMAT or row["key"] != key
                    or row["response_sha256"] != digest(row["response"])):
                raise ValueError("receipt identity/integrity mismatch")
            if ("audit_metadata" in row or "audit_metadata_sha256" in row) and (
                    not isinstance(row.get("audit_metadata"), dict)
                    or row.get("audit_metadata_sha256") != digest(row["audit_metadata"])):
                raise ValueError("audit metadata integrity mismatch")
            return row
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"Unreadable stage checkpoint {path.name}: {exc}; "
                             "inspect the receipt, do not silently resample.") from exc

    def save(self, key, response, *, stage, audit_metadata=None):
        row = {"format": FORMAT, "key": key, "stage": stage,
               "response_sha256": digest(response), "response": response}
        if audit_metadata:
            row.update(audit_metadata=audit_metadata, audit_metadata_sha256=digest(audit_metadata))
        text = json.dumps(row, indent=2)
        if len(text.encode()) > MAX_RECORD_BYTES:
            raise ValueError("Stage checkpoint exceeds audit storage safety limit.")
        path = self.folder / (key + ".json")
        temporary = None
        try:
            self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.folder,
                                             prefix=".pending-", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # Publish a complete receipt without overwriting a concurrent
                # run's verdict for the same request.
                os.link(temporary, path)
            except FileExistsError:
                existing = self.load(key)
                if (existing["response_sha256"] != row["response_sha256"]
                        or existing.get("audit_metadata_sha256") != row.get("audit_metadata_sha256")):
                    raise ValueError("Conflicting responses for one stage checkpoint; neither is silently replaced.")
        except OSError as exc:
            raise ValueError(f"Cannot persist validated stage checkpoint: {exc}") from exc
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
