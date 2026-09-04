"""The LLM client. OpenAI-compatible, provider-agnostic, and never trusted with a number.

Talks to any endpoint that speaks the OpenAI chat-completions shape. The default is Groq
serving GPT-OSS (Apache 2.0, open weights), but nothing here is Groq-specific: swapping
`FINCTL_LLM_BASE_URL` and `FINCTL_LLM_MODEL` moves it to Together, OpenRouter, or a local
vLLM without a code change. A provider is a config value, not a dependency.

`urllib` rather than a vendor SDK, for the same reason: the wire format is the contract.
The engine installs and runs with zero LLM dependencies (`pyproject.toml` keeps them in
an extra), and this module must not change that.

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
    """


@dataclass(frozen=True)
class LLMConfig:
    """Where the model lives and how patient we are with it."""

    api_key: str | None
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    reasoning_effort: str = DEFAULT_REASONING_EFFORT

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> LLMConfig:
        """Read configuration from the environment.

        `GROQ_API_KEY` is accepted as a fallback so an existing shell that already has
        one just works; `FINCTL_LLM_API_KEY` is the provider-neutral name and wins.
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
        )


def complete(system: str, user: str, config: LLMConfig) -> str:
    """One chat completion. Returns prose, or raises `ExplainUnavailable`.

    Temperature is low but not zero: this is prose, and zero buys a determinism we do not
    need for a sentence a human reads once. The numbers are deterministic regardless,
    because they are not produced here.
    """
    if not config.enabled:
        raise ExplainUnavailable("no API key configured")

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
        raise ExplainUnavailable(f"HTTP {exc.code} from {config.base_url}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ExplainUnavailable(f"cannot reach {config.base_url}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ExplainUnavailable("response was not JSON") from exc

    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ExplainUnavailable(f"unexpected response shape: {str(body)[:200]}") from exc

    content = (message.get("content") or "").strip()
    if not content:
        # A reasoning model that ran out of budget mid-thought returns empty content and
        # `finish_reason: "length"`. Rendering that would put a blank explanation on the
        # verdict screen, which looks like a broken product rather than a missing key.
        reason = body["choices"][0].get("finish_reason", "unknown")
        raise ExplainUnavailable(f"model returned no content (finish_reason={reason})")

    return content
