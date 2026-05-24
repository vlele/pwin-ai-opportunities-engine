from __future__ import annotations

import sys
from types import ModuleType


def _install_optional_dependency_fallbacks() -> None:
    try:
        import PyPDF2  # noqa: F401
    except ImportError:
        fallback = ModuleType("PyPDF2")

        class _MissingPdfReader:
            def __init__(self, *args: object, **kwargs: object) -> None:
                raise RuntimeError("PyPDF2 unavailable")

        fallback.PdfReader = _MissingPdfReader  # type: ignore[attr-defined]
        sys.modules.setdefault("PyPDF2", fallback)


_install_optional_dependency_fallbacks()
