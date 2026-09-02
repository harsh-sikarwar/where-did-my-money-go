"""finctl — deterministic settlement reconciliation engine.

Stage order (see docs/BEHAVIOR.md):
    generate -> normalize -> stage -> match -> classify -> correlate -> rank -> explain

Hard rules enforced across this package:
  * Money is ALWAYS an integer number of paise. Never a float. Never rupees.
  * No stage before `explain` may call an LLM.
  * Every classification carries the arithmetic that proves it.
"""

__version__ = "0.1.0"
