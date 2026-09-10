"""
JOB HUNTER BELGIUM
APPLICATION QUEUE - VERSION 1.2 OVERLAY

La Queue existante reste intacte.

Correction V1.2 :
- la zone préférée est détectée par limites lexicales ;
- "Evere" correspond à Evere ;
- "Evere" ne correspond PLUS à "Beveren".

Toutes les autres règles, scores, doublons et exports sont délégués
à matching.application_queue.
"""

from __future__ import annotations

import re
from contextlib import contextmanager

import matching.application_queue as base_queue
from config.profile import PREFERRED_LOCATIONS


QUEUE_VERSION = "1.2"


def clean_text(value):
    return base_queue.clean_text(value)


def normalize(value):
    return base_queue.normalize(value)


_PREFERRED_NORM = tuple(
    sorted(
        {
            normalize(value)
            for value in PREFERRED_LOCATIONS
            if normalize(value)
        },
        key=len,
        reverse=True,
    )
)


def _bounded_phrase_in_text(phrase, text):
    if not phrase or not text:
        return False

    pattern = (
        r"(?<![a-z0-9])"
        + re.escape(phrase)
        + r"(?![a-z0-9])"
    )
    return re.search(pattern, text) is not None


def location_is_preferred(location):
    norm = normalize(location)
    if not norm:
        return False

    return any(
        _bounded_phrase_in_text(term, norm)
        for term in _PREFERRED_NORM
    )


@contextmanager
def _safe_location_detector():
    original = base_queue.location_is_preferred
    base_queue.location_is_preferred = location_is_preferred
    try:
        yield
    finally:
        base_queue.location_is_preferred = original


def _stamp_version(items):
    for item in items:
        item["queue_version"] = QUEUE_VERSION
    return items


def build_application_queue_from_gate_payload(payload):
    with _safe_location_detector():
        items = base_queue.build_application_queue_from_gate_payload(payload)
    return _stamp_version(items)


def build_application_queue(gated_jobs):
    with _safe_location_detector():
        items = base_queue.build_application_queue(gated_jobs)
    return _stamp_version(items)


def export_application_queue(items, project_root):
    return base_queue.export_application_queue(items, project_root)


partition_application_queue = base_queue.partition_application_queue
queue_summary = base_queue.queue_summary
source_reference_from_url = base_queue.source_reference_from_url
stable_application_item_key = base_queue.stable_application_item_key
QUEUE_STATUS_ORDER = base_queue.QUEUE_STATUS_ORDER
QUEUE_STATUS_LABELS = base_queue.QUEUE_STATUS_LABELS
CV_TRACKS = base_queue.CV_TRACKS
