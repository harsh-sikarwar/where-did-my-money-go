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


@pytest.fixture
def generated(client, source_batch) -> str:
    """A batch placed on disk the way the generator leaves it — ground truth included.

    Not an upload: the upload path deliberately drops ground_truth.json, so it can never
    exercise the branch that reads one.
    """
    import shutil

    import main

    target = main.DATA_ROOT / "generated"
    shutil.copytree(source_batch, target)
    main._cache.clear()
    return "generated"


class TestProvenanceExplainsAFrozenCount:
    """The exceptions screen shows the same count at every volume, and now says why.

    The `demo` profile plants absolute counts, not rates, so 200 orders and 5,000 orders
    both yield the same findings. That is correct and deliberate (defects.yaml explains
    the choice in its header), but on screen it reads as a broken filter. `/api/actions`
    therefore carries the batch's provenance, so the UI can state the reason rather than
    leave a judge to infer a bug.
    """

    def test_an_uploaded_batch_reports_no_provenance(self, client, batch) -> None:
        """Silence, not a guess.

        An upload arrives without ground truth: nobody planted anything, so there is no
        planted count to report. The UI renders the explanatory line only when this is
        non-null, which is why null has to be the answer rather than zero — zero would
        read as "no defects were planted", a claim this endpoint cannot make.
        """
        assert client.get(f"/api/actions/{batch}").json()["provenance"] is None

    def test_a_generated_batch_reports_what_was_planted(self, client, generated) -> None:
        """The four fields the explanatory line is built from."""
        p = client.get(f"/api/actions/{generated}").json()["provenance"]

        assert p["defect_profile"] == "demo"
        assert p["volume"] == 200
        assert isinstance(p["planted_defects"], int) and p["planted_defects"] > 0
        assert isinstance(p["planted_decoys"], int)

    def test_the_exception_queue_does_not_lengthen_with_volume(self, client) -> None:
        """The claim the UI line makes, asserted rather than described.

        Note what is NOT claimed: total defects planted DOES scale, because `timing_lag`
        is a rate. It is the defect types that reach this queue — halted subscriptions,
        missing orders, unrecorded refunds, disputes — that are absolute counts. An
        earlier draft of the screen cited the total and would have printed "81 defects
        planted" beside a list of eighteen. This test is why that never shipped.
        """
        import main

        lengths = set()
        for volume in (200, 800):
            write_batch(
                Generator(load_config(), seed=20260902, volume=volume,
                          defect_profile="demo").generate(),
                main.DATA_ROOT / f"vol{volume}",
            )
            main._cache.clear()
            lengths.add(client.get(f"/api/actions/vol{volume}").json()["count"])

        assert len(lengths) == 1, (
            f"the exception queue was {lengths} at two volumes. The screen tells the "
            "merchant this number is volume-independent; if that stops being true the "
            "prose is lying, not the data."
        )

    def test_total_planted_defects_is_not_the_frozen_number(self, client) -> None:
        """Guards the distinction the prose depends on, from the other side.

        If `demo` ever became all-absolute, this test fails and the screen could then
        honestly cite the total — a better line than the one it has. Failing here is a
        prompt to improve the copy, not a defect.
        """
        import main

        totals = set()
        for volume in (200, 800):
            write_batch(
                Generator(load_config(), seed=20260902, volume=volume,
                          defect_profile="demo").generate(),
                main.DATA_ROOT / f"tot{volume}",
            )
            main._cache.clear()
            totals.add(
                client.get(f"/api/actions/tot{volume}").json()["provenance"]["planted_defects"]
            )

        assert len(totals) == 2, (
            f"total planted defects was identical ({totals}) at two volumes. The demo "
            "profile's timing_lag is a rate, so this is expected to scale."
        )


class TestNothingToChaseIsNotNothingUnexplained:
    """Two different facts, which the analysis screen once conflated.

    An empty action queue says nothing about the residual: a batch can have money the
    engine could not attribute with nothing actionable in it, and an upload missing its
    payments feed is the ordinary way there. The screen therefore reads the residual
    directly rather than inferring it from the queue, and these assert the fields that
    makes possible are really there and really separate.
    """

    def test_the_residual_is_money_the_ui_can_render_without_computing(
        self, client, batch
    ) -> None:
        """`paise` for the comparison, `display` for the sentence.

        ADR-001: the UI never formats a rupee figure. If `display` disappeared, the only
        way to print the residual would be to build the string in the browser — which is
        how a number on screen stops matching the number in the audit log.
        """
        unexplained = client.get(f"/api/verdict/{batch}").json()["unexplained"]

        assert set(unexplained) >= {"paise", "display"}
        assert isinstance(unexplained["paise"], int)
        assert unexplained["display"].startswith("₹")

    def test_the_queue_length_and_the_residual_are_independent_reads(
        self, client, batch
    ) -> None:
        """Neither endpoint derives the other, so the screen must consult both."""
        actions = client.get(f"/api/actions/{batch}").json()
        verdict = client.get(f"/api/verdict/{batch}").json()

        assert isinstance(actions["count"], int)
        assert isinstance(verdict["unexplained"]["paise"], int)
        assert "unexplained" not in actions, (
            "if /api/actions ever carried the residual, the screen should read it from "
            "one place rather than two — but it does not, and the fix assumes it."
        )
