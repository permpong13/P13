# -*- coding: utf-8 -*-
from __future__ import print_function

from p13_view_annotation_sync import (
    apply_annotation_sync,
    prepare_annotation_sync,
    preview_to_data as annotation_preview_to_data,
)


def prepare(doc, uidoc, payload):
    return prepare_annotation_sync(
        doc,
        payload.get("source_view_id"),
        payload.get("target_view_id"),
        payload.get("mode") or "replace",
        bool(payload.get("include_tags", True)),
        bool(payload.get("include_dimensions", True)),
        bool(payload.get("align_target_scale", False)),
    )


def preview_to_data(prepared):
    return annotation_preview_to_data(prepared)


def apply(doc, uidoc, payload, prepared):
    return apply_annotation_sync(doc, prepared)
