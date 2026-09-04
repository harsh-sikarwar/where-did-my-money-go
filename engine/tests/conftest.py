"""Suite-wide fixtures.

The one job here: the test suite must never make a network call.

`/api/verdict` calls the explanation stage, which calls a language model when a key is
configured. A developer with `GROQ_API_KEY` in their shell would therefore run a
different suite from one without — slower (9.4s against 4s), dependent on a third party
being up, and non-deterministic in exactly the layer this project argues is deterministic.
A suite whose result depends on whose laptop it runs on is not evidence of anything.

So the LLM is disabled for every test by default. The explanation stage's own tests use a
stub client and assert both paths (`test_explain.py`); nothing else should know the stage
exists. To exercise the live model, run the engine, not the suite.
"""

from __future__ import annotations

import pytest

# Every name `LLMConfig.from_env` reads. Clearing all of them means an unset stage rather
# than a half-configured one.
_LLM_ENV = (
    "FINCTL_LLM_API_KEY",
    "GROQ_API_KEY",
    "ANTHROPIC_API_KEY",
    "FINCTL_LLM_BASE_URL",
    "FINCTL_LLM_MODEL",
    "FINCTL_LLM_REASONING_EFFORT",
    "FINCTL_LLM_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def _no_live_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the explanation stage's model for every test.

    `autouse` deliberately: opting in per-test would mean the one test someone forgets is
    the one that makes a network call, and it would fail only in CI, only sometimes.
    Tests that want model behaviour set their own config explicitly.
    """
    for name in _LLM_ENV:
        monkeypatch.delenv(name, raising=False)
