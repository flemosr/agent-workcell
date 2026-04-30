"""macOS automation import shim."""

import sys

from . import automation as _automation

sys.modules[__name__] = _automation
