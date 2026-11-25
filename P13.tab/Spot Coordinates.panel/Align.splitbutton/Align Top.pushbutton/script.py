# -*- coding: utf-8 -*-
"""Ribbon launcher for Align Spot Coordinates - Top."""
import os

MODE_OVERRIDE = "Top"
main_script = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "lib",
    "align_spot_core.py",
)
execfile(main_script, globals())
