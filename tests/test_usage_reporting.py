import json
import sqlite3
from datetime import datetime

from api import usage_reporting


def _configure_usage_reporting(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_WEBUI_USAGE_INGEST_URL", "https://crm.example.test/api/v1/platform/usage/events")
    monkeypatch.setenv("HERMES_WEBUI_USAGE_PROFILE_MAP", json.dumps({"store-a": {"tenantSlug": "store-a", "apiKey": "tenant-test-key"}}))
    monkeypatch.setenv("HERMES_WEBUI_USAGE_OUTBOX_PATH", str(tmp_path / "outbox.sqlite3"))


def test_usage_batch_maps_profile_and_exports_only_token_metadata(monkeypatch, tmp_path):
    _configure_usage_reporting(monkeypatch, tmp_path)
    payload = usage_reporting.build_usage_batch(
        profile="store-a", turn_id="turn-1", input_tokens=120, output_tokens=24, model="provider/model"
    )
    assert payload["tenantSlug"] == "store-a"
    assert [event["metric"] for event in payload["events"]] == ["input_tokens", "output_tokens"]
    assert all(event["source"] == "hermes_webui" for event in payload["events"])
    assert all(event["model"] == "provider/model" for event in payload["events"])
    timestamps = {event["occurredAt"] for event in payload["events"]}
    assert len(timestamps) == 1
    datetime.fromisoformat(timestamps.pop().replace("Z", "+00:00"))
    assert "content" not in json.dumps(payload)
    assert usage_reporting.build_usage_batch(
        profile="unmapped", turn_id="turn-2", input_tokens=1, output_tokens=1
    ) is None


def test_usage_outbox_is_idempotent_and_retries_until_worker_accepts(monkeypatch, tmp_path):
    _configure_usage_reporting(monkeypatch, tmp_path)
    monkeypatch.setattr(usage_reporting, "_start_retry_worker", lambda: None)
    args = {"profile": "store-a", "turn_id": "stable-turn", "input_tokens": 15, "output_tokens": 5}
    assert usage_reporting.enqueue_turn_usage(**args)
    assert usage_reporting.enqueue_turn_usage(**args)
    outbox = tmp_path / "outbox.sqlite3"
    with sqlite3.connect(outbox) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pending_usage").fetchone()[0] == 2
        persisted_timestamps = {json.loads(row[0])["occurredAt"] for row in conn.execute("SELECT event_json FROM pending_usage")}
    assert len(persisted_timestamps) == 1

    monkeypatch.setattr(usage_reporting, "_post_batch", lambda _payload, _key: False)
    assert usage_reporting.flush_pending_usage() == {"sent": 0, "failed": 2}
    with sqlite3.connect(outbox) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pending_usage WHERE attempts = 1").fetchone()[0] == 2
        assert {json.loads(row[0])["occurredAt"] for row in conn.execute("SELECT event_json FROM pending_usage")} == persisted_timestamps

    monkeypatch.setattr(usage_reporting, "_post_batch", lambda payload, key: payload["tenantSlug"] == "store-a" and key == "tenant-test-key")
    with sqlite3.connect(outbox) as conn:
        conn.execute("UPDATE pending_usage SET next_attempt_at = 0")
    assert usage_reporting.flush_pending_usage() == {"sent": 2, "failed": 0}
    with sqlite3.connect(outbox) as conn:
        assert conn.execute("SELECT COUNT(*) FROM pending_usage").fetchone()[0] == 0


def test_usage_export_rejects_non_https_or_wrong_endpoint(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_USAGE_INGEST_URL", "http://crm.example.test/api/v1/platform/usage/events")
    monkeypatch.setenv("HERMES_WEBUI_USAGE_PROFILE_MAP", json.dumps({"store-a": {"tenantSlug": "store-a", "apiKey": "tenant-test-key"}}))
    assert usage_reporting.build_usage_batch(
        profile="store-a", turn_id="turn-1", input_tokens=1, output_tokens=1
    ) is None
    monkeypatch.setenv("HERMES_WEBUI_USAGE_INGEST_URL", "https://crm.example.test/redirect")
    assert usage_reporting.build_usage_batch(
        profile="store-a", turn_id="turn-1", input_tokens=1, output_tokens=1
    ) is None
