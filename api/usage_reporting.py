"""Best-effort, durable per-turn usage export to the tenant CRM ledger.

Only aggregate token counts, model name, profile identity and an idempotency ID
leave Hermes. Conversation contents are never included.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)
_worker_lock = threading.Lock()
_worker_started = False


def build_usage_batch(*, profile: str, turn_id: str, input_tokens: int, output_tokens: int, model: str | None = None):
    """Return a tenant-tagged batch, or None when this profile is not billable."""
    endpoint = os.environ.get("HERMES_WEBUI_USAGE_INGEST_URL", "").strip()
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    if parsed.path.rstrip("/") != "/api/v1/platform/usage/events" or parsed.query or parsed.fragment:
        return None
    try:
        mapping = json.loads(os.environ.get("HERMES_WEBUI_USAGE_PROFILE_MAP", "{}"))
    except (TypeError, ValueError):
        return None
    profile_config = mapping.get(profile) if isinstance(mapping, dict) else None
    tenant_slug = profile_config.get("tenantSlug") if isinstance(profile_config, dict) else None
    api_key = profile_config.get("apiKey") if isinstance(profile_config, dict) else None
    if not isinstance(tenant_slug, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,78}", tenant_slug):
        return None
    if not isinstance(api_key, str) or not api_key.strip():
        return None
    digest = hashlib.sha256(f"{profile}\0{turn_id}".encode()).hexdigest()[:40]
    events = []
    for metric, quantity in (("input_tokens", input_tokens), ("output_tokens", output_tokens)):
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            continue
        events.append({
            "eventId": f"hermes-webui:{digest}:{metric}",
            "source": "hermes_webui",
            "metric": metric,
            "quantity": quantity,
            "unit": "tokens",
            "model": str(model or "")[:160] or None,
            "metadata": {"profile": profile[:80]},
        })
    if not events:
        return None
    return {"tenantSlug": tenant_slug, "events": events}


def enqueue_turn_usage(*, profile: str, turn_id: str, input_tokens: int, output_tokens: int, model: str | None = None) -> bool:
    """Persist usage locally and wake a retry worker; never block the chat turn."""
    batch = build_usage_batch(profile=profile, turn_id=turn_id, input_tokens=input_tokens, output_tokens=output_tokens, model=model)
    if batch is None:
        return False
    db_path = _outbox_path()
    if db_path is None:
        return False
    now = time.time()
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path, timeout=5) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS pending_usage (
                event_id TEXT PRIMARY KEY,
                tenant_slug TEXT NOT NULL,
                profile_name TEXT NOT NULL DEFAULT '',
                event_json TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL,
                created_at REAL NOT NULL
            )""")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(pending_usage)")}
            if "profile_name" not in columns:
                conn.execute("ALTER TABLE pending_usage ADD COLUMN profile_name TEXT NOT NULL DEFAULT ''")
            for event in batch["events"]:
                conn.execute("INSERT OR IGNORE INTO pending_usage(event_id, tenant_slug, profile_name, event_json, next_attempt_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                             (event["eventId"], batch["tenantSlug"], profile, json.dumps(event, separators=(",", ":")), now, now))
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass
        _start_retry_worker()
        return True
    except Exception:
        logger.warning("Could not persist Hermes usage for reporting", exc_info=True)
        return False


def flush_pending_usage(*, limit: int = 50) -> dict[str, int]:
    """Attempt ready outbox deliveries. Exposed for deterministic tests/ops."""
    db_path = _outbox_path()
    if db_path is None or not db_path.exists():
        return {"sent": 0, "failed": 0}
    now = time.time()
    try:
        with sqlite3.connect(db_path, timeout=5) as conn:
            rows = conn.execute("SELECT event_id, tenant_slug, profile_name, event_json, attempts FROM pending_usage WHERE next_attempt_at <= ? ORDER BY created_at LIMIT ?", (now, min(500, max(1, limit)))).fetchall()
    except Exception:
        logger.warning("Could not read Hermes usage outbox", exc_info=True)
        return {"sent": 0, "failed": 0}
    if not rows:
        return {"sent": 0, "failed": 0}
    groups: dict[tuple[str, str], list[tuple[str, dict, int]]] = {}
    for event_id, tenant_slug, profile_name, payload, attempts in rows:
        groups.setdefault((tenant_slug, profile_name), []).append((event_id, json.loads(payload), attempts))
    sent = 0
    failed = 0
    for (tenant_slug, profile_name), group in groups.items():
        payload = {"tenantSlug": tenant_slug, "events": [row[1] for row in group]}
        success = _post_batch(payload, _profile_api_key(profile_name))
        with sqlite3.connect(db_path, timeout=5) as conn:
            for event_id, _event, attempts in group:
                if success:
                    conn.execute("DELETE FROM pending_usage WHERE event_id = ?", (event_id,))
                    sent += 1
                else:
                    delay = min(3600, 30 * (2 ** min(attempts, 7)))
                    conn.execute("UPDATE pending_usage SET attempts = attempts + 1, next_attempt_at = ? WHERE event_id = ?", (time.time() + delay, event_id))
                    failed += 1
    return {"sent": sent, "failed": failed}


def _profile_api_key(profile: str) -> str:
    try:
        mapping = json.loads(os.environ.get("HERMES_WEBUI_USAGE_PROFILE_MAP", "{}"))
        profile_config = mapping.get(profile) if isinstance(mapping, dict) else None
        key = profile_config.get("apiKey") if isinstance(profile_config, dict) else None
        return key.strip() if isinstance(key, str) else ""
    except (TypeError, ValueError):
        return ""


def _post_batch(payload: dict, api_key: str) -> bool:
    endpoint = os.environ.get("HERMES_WEBUI_USAGE_INGEST_URL", "").strip()
    if not endpoint or not api_key:
        return False
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json",
    }, method="POST")

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(request, timeout=8) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError, urllib.error.HTTPError):
        return False


def _outbox_path() -> Path | None:
    explicit = os.environ.get("HERMES_WEBUI_USAGE_OUTBOX_PATH", "").strip()
    if explicit:
        return Path(explicit)
    state_dir = os.environ.get("HERMES_WEBUI_STATE_DIR", "").strip()
    if state_dir:
        return Path(state_dir) / "crm-usage-outbox" / "events.sqlite3"
    return None


def _start_retry_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True

    def run():
        try:
            while True:
                flush_pending_usage()
                time.sleep(60)
        except Exception:
            logger.warning("Hermes usage retry worker stopped unexpectedly", exc_info=True)

    threading.Thread(target=run, name="hermes-crm-usage-outbox", daemon=True).start()
