"""Command line entry point package. See app.py for the implementation.

Split into its own package (rather than a single cli.py) so command
dispatch/argument parsing (app.py) stays separate from the text-formatting
helpers in slotmath.reporting -- the `slotmath.cli:main` console-script entry
point in pyproject.toml is unaffected by this being a package instead of a
module.
"""

from __future__ import annotations

from slotmath.cli.app import main

__all__ = ["main"]
