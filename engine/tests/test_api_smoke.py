"""HTTP-level smoke tests for every endpoint `api/main.py` serves.

Eleven of the twenty-two endpoints had zero coverage above the unit level: nothing
proved they were even wired into the ASGI app, let alone that their JSON matched what
`web/lib/api.ts` promises the frontend. This file trades depth for breadth on purpose —
it is not the place `test_api_upload.py` or `test_explain.py` already are, and it does
not re-test what they cover.

Three things, for (almost) every endpoint:

  1. HAPPY PATH — a 200 whose body has the keys the TypeScript interfaces in
     `web/lib/api.ts` declare. That file makes a claim about the JSON shape that,
     before this file, nothing checked. A missing key here is a real contract break,
     not a test to loosen.
  2. ERRORS — an unknown batch is a 404, never an unhandled 500 reaching the browser.
  3. THE CHAT GUARD — `/api/chat/{batch}` is wired to `source == "template"` when no
     model is configured. The guard itself is `test_explain.py`'s job; this only checks
     the endpoint calls it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[2] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from finctl.config.loader import load_config  # noqa: E402
from finctl.generate.generator import Generator  # noqa: E402
from finctl.generate.writer import write_batch  # noqa: E402


@pytest.fixture(scope="module")
def source_batch(tmp_path_factory) -> Path:
    """One generated batch, reused as the bytes every test uploads.

    `defect_profile="demo"` is the same profile `test_api_upload.py` uses — it is
    guaranteed to plant halted subscriptions (ADR-048's `TestActionsEndpoint` asserts
    exactly 6), which this file leans on to reach the detail/trace/correlation
    endpoints with real findings rather than an empty reconciled batch.
    """
    out = tmp_path_factory.mktemp("source")
    write_batch(Generator(load_config(), seed=20260902, volume=200,
                          defect_profile="demo").generate(), out)
    return out


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A client whose DATA_ROOT is a fresh directory, isolated per test."""
    import main

    data_root = tmp_path / "data"
    monkeypatch.setattr(main, "DATA_ROOT", data_root)
    monkeypatch.setattr(main, "MAPPINGS_PATH", data_root / "column-mappings.json")
    monkeypatch.setattr(main, "RATE_CARD_PATH", data_root / "merchant-rate-card.json")
    monkeypatch.setattr(main, "_cache", {})
    monkeypatch.setattr(main, "_summary_cache", {})
    return TestClient(main.app)


ALL_SLOTS = ("ledger", "bank", "recon", "payments", "subscriptions")


def _files(batch_dir: Path) -> dict:
    names = {
        "ledger": ("ledger.csv", "text/csv"),
        "bank": ("bank.csv", "text/csv"),
        "recon": ("settlement_recon.json", "application/json"),
        "payments": ("payments.json", "application/json"),
        "subscriptions": ("subscriptions.json", "application/json"),
    }
    return {
        slot: (filename, (batch_dir / filename).read_bytes(), mime)
        for slot, (filename, mime) in names.items()
    }


@pytest.fixture
def batch(client, source_batch) -> str:
    """One uploaded, fully reconciled batch, reachable at `/api/*/smoke`."""
    r = client.post("/api/upload", data={"batch": "smoke"}, files=_files(source_batch))
    assert r.status_code == 200, r.json()
    return "smoke"


class TestHappyPathContractsAgainstApiTs:
    """Every GET the dashboard makes, checked against the interfaces it was written to.

    Only key PRESENCE is asserted, never exact values — a value assertion here would
    make this file re-test the engine's arithmetic, which is `engine/tests/*` job, and
    would fail on every seed or defect-profile change with nothing wrong.
    """

    def test_health_reports_the_llm_state_honestly(self, client) -> None:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        for key in (
            "engine", "engine_version", "batches", "llm_credential_present",
            "llm_disabled", "llm_enabled", "llm_model", "llm_base_url",
            "llm_last_summary_source", "llm_last_summary_reason",
            "summaries_cached", "timestamp",
        ):
            assert key in body, key

    def test_batches_lists_the_seeded_batch(self, client, batch) -> None:
        listed = client.get("/api/batches").json()["batches"]
        row = next(b for b in listed if b["name"] == batch)
        for key in ("name", "has_ground_truth", "uploaded", "generated"):
            assert key in row, key

    def test_generate_options_matches_the_dropdowns_contract(self, client) -> None:
        body = client.get("/api/generate/options").json()
        for key in (
            "archetypes", "payment_mixes", "defect_profiles", "defect_types",
            "defaults", "limits",
        ):
            assert key in body, key
        assert body["archetypes"]
        for k in ("name", "description", "stresses", "expected_correlation_gain",
                  "ticket_min_paise", "ticket_max_paise", "default_mix"):
            assert k in body["archetypes"][0], k
        for k in ("archetype", "payment_mix", "defect_profile", "volume",
                  "cycle_days", "seed"):
            assert k in body["defaults"], k
        for k in ("max_volume", "min_volume"):
            assert k in body["limits"], k

    def test_rate_card_matches_the_ratecard_interface(self, client) -> None:
        body = client.get("/api/rate-card").json()
        for key in ("name", "is_merchant_supplied", "gst_rate_bps",
                    "fixed_fee_paise", "methods"):
            assert key in body, key
        for key in ("method", "mdr_bps", "percent", "source", "note"):
            assert key in body["methods"][0], key

    def test_mappings_is_listable_even_when_empty(self, client) -> None:
        assert client.get("/api/mappings").json() == {"mappings": []}

    def test_rules_matches_the_rulesconfig_interface(self, client) -> None:
        body = client.get("/api/rules").json()
        for key in (
            "cycle_days", "grace_days", "count_working_days_only", "rounding",
            "material", "actionable_above", "always_benign", "always_actionable",
            "rate_card", "classifications",
        ):
            assert key in body, key
        for key in ("name", "label", "hint", "policy"):
            assert key in body["classifications"][0], key

    def test_verdict_matches_the_verdict_interface(self, client, batch) -> None:
        body = client.get(f"/api/verdict/{batch}").json()
        for key in (
            "batch", "expected", "received", "gap", "headline", "summary",
            "summary_source", "actionable_total", "benign_total", "unexplained",
            "unexplained_count", "residual", "missing_sources", "missing_note",
            "late", "lines", "match", "performance",
        ):
            assert key in body, key
        assert body["lines"], "the demo batch must produce at least one verdict line"
        for key in ("classification", "label", "explanation", "count", "amount",
                    "actionable", "note"):
            assert key in body["lines"][0], key
        for leg in ("pass1", "pass2"):
            for key in ("leg", "question", "total", "matched", "unmatched", "match_rate"):
                assert key in body["match"][leg], (leg, key)
        for key in ("elapsed_seconds", "rows_processed", "rows_per_second"):
            assert key in body["performance"], key

    def test_timeline_matches_the_timeline_interface(self, client, batch) -> None:
        body = client.get(f"/api/timeline/{batch}").json()
        for key in ("batch", "gap", "dated", "undated", "days", "peak"):
            assert key in body, key
        assert body["days"], "a reconciled batch must have at least one dated day"
        for key in ("day", "amount", "orders", "actionable", "expected", "received"):
            assert key in body["days"][0], key

    def test_actions_matches_the_actions_interface(self, client, batch) -> None:
        body = client.get(f"/api/actions/{batch}").json()
        for key in ("batch", "headline", "total", "chase_total", "chase_count",
                    "count", "groups"):
            assert key in body, key
        assert body["groups"], "the demo batch must produce at least one action group"
        group = body["groups"][0]
        for key in ("classification", "next_step", "count", "total", "items"):
            assert key in group, key
        for key in ("order_id", "classification", "amount", "customer_id", "email",
                    "contact", "subscription_id", "payment_id", "reason", "detail"):
            assert key in group["items"][0], key

    def test_actions_csv_downloads_a_csv_file(self, client, batch) -> None:
        r = client.get(f"/api/actions/{batch}/csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]

    def test_detail_matches_the_detail_interface(self, client, batch) -> None:
        body = client.get(f"/api/detail/{batch}/HALTED_SUBSCRIPTION").json()
        for key in ("batch", "classification", "label", "explanation", "count",
                    "total", "truncated", "findings"):
            assert key in body, key
        assert body["count"] == 6, "the demo batch plants exactly 6 halted subscriptions"
        for key in ("order_id", "settlement_id", "amount", "proof", "candidates"):
            assert key in body["findings"][0], key

    def test_correlation_matches_the_correlation_interface(self, client, batch) -> None:
        body = client.get(f"/api/correlation/{batch}").json()
        for key in ("batch", "before", "after", "resolved", "gain_ratio",
                    "resolved_count", "still_unexplained_count",
                    "resolved_by_class", "still_unexplained"):
            assert key in body, key
        assert body["resolved_by_class"], "the demo batch must resolve something"
        for key in ("classification", "count", "amount"):
            assert key in body["resolved_by_class"][0], key

    def test_audit_matches_the_audit_interface(self, client, batch) -> None:
        body = client.get(f"/api/audit/{batch}").json()
        for key in ("batch", "manifest", "total_events", "by_stage",
                    "filtered_count", "truncated", "events"):
            assert key in body, key
        for key in ("batch_id", "created_at", "sealed", "sources"):
            assert key in body["manifest"], key
        assert body["events"], "reconciling a batch must log at least one audit event"
        for key in ("seq", "at", "batch", "stage", "event", "detail"):
            assert key in body["events"][0], key

    def test_trace_matches_the_trace_interface(self, client, batch) -> None:
        order_id = client.get(f"/api/detail/{batch}/HALTED_SUBSCRIPTION").json()[
            "findings"
        ][0]["order_id"]
        body = client.get(f"/api/trace/{batch}/{order_id}").json()
        for key in ("batch", "order_id", "ledger", "settlement", "outcome", "events"):
            assert key in body, key
        assert body["events"]
        for key in ("seq", "at", "stage", "event", "detail"):
            assert key in body["events"][0], key
        if body["outcome"] is not None:
            for key in ("classification", "amount", "proof"):
                assert key in body["outcome"], key

    def test_score_matches_ground_truth_for_a_generated_batch(self, client) -> None:
        """`/api/score` needs `ground_truth.json`, which only `/api/generate` writes —
        an uploaded batch has none, so this exercises the generate path too."""
        gen = client.post("/api/generate", json={
            "batch": "scored", "archetype": "saas_subscription", "volume": 200,
            "seed": 1,
        })
        assert gen.status_code == 200, gen.json()
        for key in ("batch", "generated", "rows_processed", "missing_sources",
                    "note", "headline", "manifest", "files", "scenario"):
            assert key in gen.json(), key

        body = client.get("/api/score/scored").json()
        assert body["batch"] == "scored"

    def test_chat_is_wired_to_the_template_guard_with_no_key_configured(
        self, client, batch
    ) -> None:
        """The guard's own logic is `test_explain.py`'s job (`TestTheModelCannotPutANumberOnScreen`);
        this only checks the endpoint calls it rather than, say, returning the raw
        `complete()` output. `conftest.py`'s autouse fixture clears every LLM env var,
        so no key is configured here."""
        r = client.post(f"/api/chat/{batch}", json={"message": "why is money missing?"})
        assert r.status_code == 200
        body = r.json()
        assert body["source"] == "template"
        assert body["source"] != "model"
        assert body["answer"]


class TestUnknownBatchIsA404NeverA500:
    """An unhandled exception reaching the judge's browser is worse than a 404. Every
    `{batch}` route must resolve an unknown name to a clean 404, not let `_load`'s
    `path.is_dir()` check get bypassed by something further down the handler."""

    def test_verdict_of_an_unknown_batch_is_a_404(self, client) -> None:
        assert client.get("/api/verdict/does-not-exist").status_code == 404

    def test_timeline_of_an_unknown_batch_is_a_404(self, client) -> None:
        assert client.get("/api/timeline/does-not-exist").status_code == 404

    def test_actions_of_an_unknown_batch_is_a_404(self, client) -> None:
        assert client.get("/api/actions/does-not-exist").status_code == 404

    def test_detail_of_an_unknown_batch_is_a_404(self, client) -> None:
        assert client.get("/api/detail/does-not-exist/FEE").status_code == 404

    def test_correlation_of_an_unknown_batch_is_a_404(self, client) -> None:
        assert client.get("/api/correlation/does-not-exist").status_code == 404

    def test_score_of_an_unknown_batch_is_a_404(self, client) -> None:
        assert client.get("/api/score/does-not-exist").status_code == 404

    def test_audit_of_an_unknown_batch_is_a_404(self, client) -> None:
        assert client.get("/api/audit/does-not-exist").status_code == 404

    def test_trace_of_an_unknown_batch_is_a_404(self, client) -> None:
        assert client.get("/api/trace/does-not-exist/ord_1").status_code == 404


class TestChatInputValidation:
    def test_an_empty_message_is_refused(self, client, batch) -> None:
        r = client.post(f"/api/chat/{batch}", json={"message": "   "})
        assert r.status_code == 400

    def test_a_non_list_history_is_refused(self, client, batch) -> None:
        r = client.post(
            f"/api/chat/{batch}",
            json={"message": "hello", "history": "not-a-list"},
        )
        assert r.status_code == 400
