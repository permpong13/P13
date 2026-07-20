# -*- coding: utf-8 -*-
"""Ribbon launcher for Reset Spot Coordinate Text Position."""
import os

MODE_OVERRIDE = "Reset Text Position"
main_script = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "lib",
    "align_spot_core.py",
)
execfile(main_script, globals())
