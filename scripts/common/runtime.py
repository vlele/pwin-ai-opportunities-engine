from __future__ import annotations


BUNDLE_VERSION = "1.6.0"
BUNDLE_VERSION_LABEL = f"v{BUNDLE_VERSION}"
BUNDLE_VERSION_TOKEN = BUNDLE_VERSION_LABEL.replace(".", "_")
USER_AGENT = f"pwin-ai-opportunities/{BUNDLE_VERSION}"
NOT_IMPLEMENTED_IN_BUNDLE_STATUS = f"not_implemented_in_{BUNDLE_VERSION_TOKEN}"
