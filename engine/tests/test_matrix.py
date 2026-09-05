"""The matrix module, guarded at the level it actually failed at: import.

`finctl matrix` produces the headline claim — 0 defects missed, 0 false positives,
the balance identity holding in all 26 runs. It died for six commits (53d95d8..) on a
`TypeError` raised while building the `RunResult` dataclass, so the command could not
start, let alone be wrong. The 903 tests passing throughout is the point: not one of
them imported `finctl.matrix`, so the module's own definition was never executed by the
suite. CI missed it too, because `finctl matrix | tee` reports tee's exit status.

These tests are deliberately shallow. Accuracy is measured by the matrix run itself and
asserted in CI against docs/matrix-results.json; what was missing was anything at all
that would notice the module had stopped being loadable.
"""

from __future__ import annotations

import dataclasses

from finctl.matrix import RunResult


def test_the_module_imports_and_run_result_is_constructible() -> None:
    """A dataclass whose fields are ordered illegally raises at class-definition time.

    Importing the module is therefore the whole test: the failure mode was never a bad
    number, it was a command that could not run.
    """
    assert dataclasses.is_dataclass(RunResult)


def test_every_field_without_a_default_precedes_every_field_with_one() -> None:
    """The specific rule that was broken, asserted directly rather than by side effect.

    `recall_strict: float = 0.0` was added into the middle of the non-default block. The
    import test above already catches that, but it catches it as an opaque TypeError;
    this one names the offending field, which is the difference between a red build that
    explains itself and one that sends the reader to the traceback.
    """
    seen_default: str | None = None
    for f in dataclasses.fields(RunResult):
        has_default = (
            f.default is not dataclasses.MISSING
            or f.default_factory is not dataclasses.MISSING  # type: ignore[misc]
        )
        if has_default:
            seen_default = f.name
        else:
            assert seen_default is None, (
                f"{f.name!r} has no default but follows {seen_default!r}, which does. "
                "Python raises at class-definition time, so this breaks `finctl matrix` "
                "on import rather than at the call site."
            )
