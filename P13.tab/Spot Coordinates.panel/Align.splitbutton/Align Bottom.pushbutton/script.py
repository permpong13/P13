# -*- coding: utf-8 -*-
"""Ribbon launcher for Align Spot Coordinates - Bottom."""
import os

MODE_OVERRIDE = "Bottom"
main_script = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "lib",
    "align_spot_core.py",
)
execfile(main_script, globals())
