"""Phase 0 smoke test: the package imports and the toolchain is wired.

Exists so that `pytest` is green from commit one — a red suite on day one
trains you to ignore the suite.
"""

import finctl


def test_package_imports() -> None:
    assert finctl.__version__ == "0.1.0"
