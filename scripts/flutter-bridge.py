#!/usr/bin/env python3
"""Compatibility entrypoint for the modular Flutter host bridge."""

import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from flutter_bridge_lib import *  # noqa: F401,F403
from flutter_bridge_lib import __all__ as _BRIDGE_ALL

__all__ = list(_BRIDGE_ALL)


if __name__ == "__main__":
    main()
