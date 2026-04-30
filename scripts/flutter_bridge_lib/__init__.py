"""Modular import surface for the Flutter host bridge."""

from .automation import *  # noqa: F401,F403
from .automation import __all__ as _AUTOMATION_ALL

__all__ = list(_AUTOMATION_ALL)
