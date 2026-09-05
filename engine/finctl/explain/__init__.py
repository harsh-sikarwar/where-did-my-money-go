"""finctl.explain — see docs/BEHAVIOR.md for this stage's contract.

The only stage that calls a language model, and the only one where a wrong answer is a
badly-phrased sentence rather than a wrong number. Every figure is rendered by the engine;
`render.guard` strips any numeral the model emits. ADR-050.
"""

from finctl.explain.client import NO_LLM_ENV, ExplainUnavailable, LLMConfig
from finctl.explain.render import (
    explain,
    explain_detailed,
    guard,
    has_numerals,
    redact_figures,
    template,
)

__all__ = [
    "NO_LLM_ENV",
    "ExplainUnavailable",
    "LLMConfig",
    "explain",
    "explain_detailed",
    "guard",
    "has_numerals",
    "redact_figures",
    "template",
]
