from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))


def _reasoning_default_for_env(env: dict[str, str]) -> str:
    sys.modules.pop("common.openai_reasoning", None)
    with patch.dict(os.environ, env, clear=True):
        module = importlib.import_module("common.openai_reasoning")
    sys.modules.pop("common.openai_reasoning", None)
    return str(module.DEFAULT_REASONING_MODEL)


def main() -> int:
    failures: list[str] = []

    if _reasoning_default_for_env({}) != "gpt-5.4-mini":
        failures.append("default_reasoning_model")

    if _reasoning_default_for_env({"OPENAI_MODEL": "openai-env-model"}) != "openai-env-model":
        failures.append("openai_model_override")

    if (
        _reasoning_default_for_env(
            {
                "OPENAI_MODEL": "openai-env-model",
                "PWIN_REASONING_MODEL": "pwin-reasoning-env-model",
            }
        )
        != "pwin-reasoning-env-model"
    ):
        failures.append("pwin_reasoning_model_override")

    output = {
        "status": "OK" if not failures else "FAILED",
        "failed_checks": failures,
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0 if not failures else 10


if __name__ == "__main__":
    raise SystemExit(main())
