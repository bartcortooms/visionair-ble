"""Facade for VMI UI automation.

This module keeps the stable `VMIUI` import path while implementation is
split across focused modules.
"""

from __future__ import annotations

from .ui_actions import VMIUIActionsMixin
from .ui_core import VMIUIBase
from .ui_navigation import VMIUINavigationMixin
from .ui_special_modes import VMIUISpecialModesMixin


class VMIUI(VMIUISpecialModesMixin, VMIUIActionsMixin, VMIUINavigationMixin, VMIUIBase):
    """High-level UI automation API used by vmictl."""

    pass


__all__ = ["VMIUI"]
