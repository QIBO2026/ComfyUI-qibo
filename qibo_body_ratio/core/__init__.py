# Copyright (C) 2026 wuwukasi (wuwukaka)
# SPDX-License-Identifier: GPL-3.0-only

"""
BodyRatioMapper nodes package.
Only ProportionTransfer (correction) node is retained.
Rendering is handled by ComfyUI core SDPoseDrawKeypoints.
"""

from .proportion_transfer_node import (
    BodyRatioMapperProportionTransfer,
)

__all__ = [
    "BodyRatioMapperProportionTransfer",
]
