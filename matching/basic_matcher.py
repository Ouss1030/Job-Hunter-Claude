"""
JOBHUNTER MATCHER VNEXT 1.4 - PRODUCTION FACADE

This file keeps the existing matching.basic_matcher import path stable.

- Legacy V5.1 implementation is frozen in matching/basic_matcher_v51.py
- VNext 1.4 overlay lives in matching/matcher_vnext_overlay.py
- All legacy names are re-exported
- score_job / print_job_match are overridden by VNext

Marker:
    JOBHUNTER_MATCHER_VNEXT_FACADE = True
"""

from __future__ import annotations

from matching import basic_matcher_v51 as _legacy

# Re-export the legacy module as faithfully as possible, including helper
# names that other project modules might import explicitly.
_SKIP = {
    "__name__", "__loader__", "__package__", "__spec__", "__file__",
    "__cached__", "__builtins__"
}
for _name, _value in vars(_legacy).items():
    if _name not in _SKIP:
        globals()[_name] = _value

from matching.matcher_vnext_overlay import (
    OVERLAY_VERSION as VNEXT_OVERLAY_VERSION,
    print_job_match,
    score_job,
)

JOBHUNTER_MATCHER_VNEXT_FACADE = True
MATCHER_VNEXT_VERSION = VNEXT_OVERLAY_VERSION
