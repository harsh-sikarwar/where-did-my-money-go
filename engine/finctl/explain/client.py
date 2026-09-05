"""The LLM client. OpenAI-compatible, provider-agnostic, and never trusted with a number.

Talks to any endpoint that speaks the OpenAI chat-completions shape. The default is Groq
serving GPT-OSS (Apache 2.0, open weights), but nothing here is Groq-specific: swapping
`FINCTL_LLM_BASE_URL` and `FINCTL_LLM_MODEL` moves it to Together, OpenRouter, or a local
vLLM without a code change. A provider is a config value, not a dependency.

`urllib` rather than a vendor SDK, for the same reason: the wire format is the contract.
The engine installs and runs with zero LLM dependencies (`pyproject.toml` keeps them in
an extra), and this module must not change that.

OFF IS A SUPPORTED STATE. `FINCTL_NO_LLM=1` (or the CLI's `--no-llm`) makes this module
make no network call at all, and every caller falls back to the deterministic template it
already has. The engine has no LLM dependency to begin with; this makes the offline path
something an operator can switch on and a judge can verify, rather than something that
happens to be true when a key is absent.

WHAT THIS IS ALLOWED TO DO. Write prose. That is the whole list. It never sees a decision
to make: matching, fee arithmetic, classification and correlation are all resolved before
a prompt is built, and every rupee figure on screen is rendered by `format_rupees` from an
integer this module never touched. See ADR-050 and `render.py`.

GPT-OSS IS A REASONING MODEL. At the default effort it spends its entire token budget on
hidden reasoning and returns `content: ""` with `finish_reason: "length"` — a silently
blank explanation, which is the worst failure available to a demo. `reasoning_effort` is
set low and an empty response is treated as a failure, not as an answer.
"""

from __future__ import annotations

import contextlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_REASONING_EFFORT = "low"

# The operator's kill switch. Set it and this module makes no network call at all,
# regardless of what keys are lying around in the environment or in .env — which is the
# point: "unset the key" is not a switch you can demonstrate, because you cannot prove a
# key was absent for the right reason. See `LLMConfig.disabled`.
NO_LLM_ENV = "FINCTL_NO_LLM"

# Deliberately not `bool(value)`: the string "0" and the string "false" are both true in
# Python, and an env var that turns the model OFF when set to "false" is a trap.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in _TRUTHY

# Long enough for three sentences, short enough that a runaway reasoning trace cannot
# stall the verdict screen.
MAX_COMPLETION_TOKENS = 400

# Any non-default value works; the default `Python-urllib/3.x` does not. See `complete`.
USER_AGENT = "finctl/0.1 (+reconciliation-engine)"


class ExplainUnavailable(Exception):
    """The model could not be reached, or said nothing usable.

    Never fatal. Every caller falls back to the deterministic template, because a
    verdict screen that fails to render because a network call failed would be a worse
    product than one that never called a model at all.

    `reason` is a stable machine-readable tag, because "unavailable" turned out to cover
    two situations a merchant should not be told the same story about. A missing key is
    a permanent state the operator can fix; a rate limit is a temporary one that clears
    on its own in under a minute. Collapsing them into one message meant the product
    said "I can't reach the model right now" while the model was reachable, answering,
    and merely rationing — which is not a thing this project is willing to say.
    """

    def __init__(self, message: str, *, reason: str = "unavailable") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class LLMConfig:
    """Where the model lives and how patient we are with it."""

    api_key: str | None
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    reasoning_effort: str = DEFAULT_REASONING_EFFORT

    # Set by `FINCTL_NO_LLM` or the CLI's `--no-llm`. Kept as its own field rather than
    # folded into `api_key = None`, because the two states are not the same fact and the
    # product says different things about them: a missing key is a misconfiguration
    # somebody should fix, and this is a choice somebody made on purpose.
    disabled: bool = False

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) and not self.disabled

    @property
    def off_reason(self) -> str:
        """Why there will be no model call — for callers that report the fallback path.

        Only meaningful when `enabled` is false. The order matters: an operator who
        passed `--no-llm` with a key configured is told the switch is on, not that their
        key is missing, because the second sentence would send them looking for a
        problem they do not have.
        """
        if self.disabled:
            return "disabled"
        return "no_key"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> LLMConfig:
        """Read configuration from the environment.

        `GROQ_API_KEY` is accepted as a fallback so an existing shell that already has
        one just works; `FINCTL_LLM_API_KEY` is the provider-neutral name and wins.

        `FINCTL_NO_LLM=1` overrides all of it. This is the one place the switch is read,
        so every caller in the project inherits it — there is no second path to the
        model that could stay open after the switch is thrown.
        """
        e = os.environ if env is None else env

        def get(name: str, default: str = "") -> str:
            return (e.get(name) or "").strip() or default

        timeout = get("FINCTL_LLM_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        try:
            timeout_seconds = float(timeout)
        except ValueError:
            timeout_seconds = DEFAULT_TIMEOUT_SECONDS

        return cls(
            api_key=get("FINCTL_LLM_API_KEY") or get("GROQ_API_KEY") or None,
            base_url=get("FINCTL_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            model=get("FINCTL_LLM_MODEL", DEFAULT_MODEL),
            timeout_seconds=timeout_seconds,
            reasoning_effort=get("FINCTL_LLM_REASONING_EFFORT", DEFAULT_REASONING_EFFORT),
            disabled=_is_truthy(get(NO_LLM_ENV)),
        )


def complete(system: str, user: str, config: LLMConfig) -> str:
    """One chat completion. Returns prose, or raises `ExplainUnavailable`.

    Temperature is low but not zero: this is prose, and zero buys a determinism we do not
    need for a sentence a human reads once. The numbers are deterministic regardless,
    because they are not produced here.
    """
    if not config.enabled:
        message = (
            f"{NO_LLM_ENV} is set — no model call was attempted"
            if config.disabled
            else "no API key configured"
        )
        raise ExplainUnavailable(message, reason=config.off_reason)

    payload = json.dumps({
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        # `max_completion_tokens`, not `max_tokens`: on a reasoning model the hidden
        # reasoning counts against the budget, and the older field does not reserve room
        # for the answer itself.
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "reasoning_effort": config.reasoning_effort,
        "temperature": 0.2,
    }).encode()

    request = urllib.request.Request(
        f"{config.base_url}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            # Required, not cosmetic. `urllib` sends `Python-urllib/3.x` by default and
            # Groq sits behind Cloudflare, which rejects it outright: HTTP 403 with
            # `error code: 1010` and no mention of a user agent anywhere in the response.
            # The same request through curl succeeds, which is what makes this worth a
            # comment — the obvious reading of that 403 is a bad key.
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # The body often names the real cause (a bad model id, a revoked key). Read it
        # where we can: "HTTP 404" alone sends someone hunting for a network problem
        # that is actually a typo in an env var.
        detail = ""
        with contextlib.suppress(Exception):    # the original error is what matters
            detail = exc.read().decode()[:200]
        # 429 is not a failure of the same kind as the rest. The endpoint is up and the
        # key is good; the account is out of tokens for the minute. Callers that treat
        # it as "unavailable" send the operator hunting for a broken integration.
        reason = "rate_limited" if exc.code == 429 else "http_error"
        raise ExplainUnavailable(
            f"HTTP {exc.code} from {config.base_url}: {detail}", reason=reason
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        timed_out = isinstance(exc, TimeoutError) or "timed out" in str(exc)
        raise ExplainUnavailable(
            f"cannot reach {config.base_url}: {exc}",
            reason="timeout" if timed_out else "unreachable",
        ) from exc
    except json.JSONDecodeError as exc:
        raise ExplainUnavailable("response was not JSON", reason="bad_response") from exc

    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ExplainUnavailable(
            f"unexpected response shape: {str(body)[:200]}", reason="bad_response"
        ) from exc

    content = (message.get("content") or "").strip()
    if not content:
        # A reasoning model that ran out of budget mid-thought returns empty content and
        # `finish_reason: "length"`. Rendering that would put a blank explanation on the
        # verdict screen, which looks like a broken product rather than a missing key.
        finish = body["choices"][0].get("finish_reason", "unknown")
        raise ExplainUnavailable(
            f"model returned no content (finish_reason={finish})", reason="empty_response"
        )

    return content
