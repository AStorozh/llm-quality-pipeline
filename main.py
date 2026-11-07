#!/usr/bin/env python3
"""Project entry point.

Run the newlxp terminal client:

    python3 main.py

This is a thin launcher that delegates to :func:`newlxp.app.main`; all the
application logic lives in the ``newlxp`` package.
"""
import sys

# Fail early with a friendly message on unsupported interpreters.
if sys.version_info < (3, 9):  # noqa: UP036 - friendly message, not dead code
    sys.exit(
        "newlxp requires Python 3.9 or newer.\n"
        "You are running Python %d.%d. Please upgrade: https://www.python.org/downloads/"
        % (sys.version_info.major, sys.version_info.minor)
    )

from newlxp.app import main  # noqa: E402 - imported after the version guard

if __name__ == "__main__":
    sys.exit(main())
