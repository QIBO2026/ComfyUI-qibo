# Copyright (C) 2026 wuwukasi (wuwukaka)
# SPDX-License-Identifier: GPL-3.0-only

"""
BodyRatioMapper nodes - Main entry point.
Only ProportionTransfer (correction) node is retained.
Rendering uses ComfyUI core SDPoseDrawKeypoints.
"""

from .core import (
    BodyRatioMapperProportionTransfer,
)

NODE_CLASS_MAPPINGS = {
    "BodyRatioMapperProportionTransfer": BodyRatioMapperProportionTransfer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "BodyRatioMapperProportionTransfer": "BodyRatioMapper Proportion Transfer",
}
