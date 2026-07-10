"""Optional webhook notifications (Discord/Slack-compatible JSON POST)."""

from __future__ import annotations

import json
import urllib.request


class Notifier:
    def __init__(self, webhook_url: str | None = None, store=None):
        self.url = webhook_url
        self.store = store

    def send(self, text: str) -> bool:
        if self.store is not None:
            self.store.add_event("notify", text)
        if not self.url:
            return False
        try:
            body = json.dumps({"content": text, "text": text}).encode()
            req = urllib.request.Request(
                self.url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10):
                return True
        except Exception as e:  # notifications must never crash the loop
            if self.store is not None:
                self.store.add_event("notify_error", str(e), level="warn")
            return False
