# -*- coding: utf-8 -*-
"""Align Spot Coordinate text positions in the active Revit view."""

from pyrevit import DB, forms, revit, script
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType


__title__ = "Align Spot\nCoordinates"
__author__ = "Permpong Taweekul"
__doc__ = (
    "Align Spot Coordinate text positions left, right, top, or bottom, or "
    "distribute them with equal spacing while keeping their referenced model "
    "points unchanged."
)

# Revit's normal two-line Spot Coordinate drag-point offsets, measured in
# paper space from live Revit 2026.4 elements. These repair leaders stretched
# by moving TextPosition without LeaderEndPosition.
LEADER_HORIZONTAL_OFFSET_MM = 1.2
LEADER_VERTICAL_OFFSET_MM = 1.825
MAX_VALID_VERTICAL_OFFSET_MM = 4.0
DISTRIBUTION_SHOULDER_MM = 5.0


class SpotCoordinateSelectionFilter(ISelectionFilter):
    """Allow only Spot Coordinate dimensions in the active view."""

    def AllowElement(self, element):
        return is_spot_coordinate(element)

    def AllowReference(self, reference, point):
        return False


def is_spot_coordinate(element):
    if not isinstance(element, DB.SpotDimension):
        return False
    category = element.Category
    return (
        category is not None
        and category.Id.Value == int(DB.BuiltInCategory.OST_SpotCoordinates)
    )


def get_selected_spots(uidoc, doc, active_view):
    spots = []
    for element_id in uidoc.Selection.GetElementIds():
        element = doc.GetElement(element_id)
        if is_spot_coordinate(element) and element.OwnerViewId == active_view.Id:
            spots.append(element)
    return spots


def pick_spots(uidoc, doc, active_view):
    try:
        references = uidoc.Selection.PickObjects(
            ObjectType.Element,
            SpotCoordinateSelectionFilter(),
            "Select Spot Coordinates, then click Finish",
        )
    except Exception:
        return []

    spots = []
    for reference in references:
        element = doc.GetElement(reference.ElementId)
        if is_spot_coordinate(element) and element.OwnerViewId == active_view.Id:
            spots.append(element)
    return spots


def coordinate(point, axis):
    return point.DotProduct(axis)


def aligned_position(point, axis, target):
    """Change one view-axis coordinate while retaining all other components."""
    return point + axis.Multiply(target - coordinate(point, axis))


def bounding_edge(spot, active_view, axis, use_minimum):
    """Return the projected annotation edge in the requested view direction."""
    box = spot.get_BoundingBox(active_view)
    if box is None:
        return coordinate(spot.TextPosition, axis)
    values = []
    for x_value in (box.Min.X, box.Max.X):
        for y_value in (box.Min.Y, box.Max.Y):
            for z_value in (box.Min.Z, box.Max.Z):
                values.append(coordinate(DB.XYZ(x_value, y_value, z_value), axis))
    return min(values) if use_minimum else max(values)


def move_text_and_leader(spot, axis, distance):
    """Move Spot Coordinate text and leader together in Revit 2026."""
    if abs(distance) < 0.0000001:
        return

    translation = axis.Multiply(distance)
    # In Revit 2026.4, SpotDimension has no LeaderElbowPosition. Moving
    # LeaderEndPosition carries TextPosition by the identical translation,
    # while setting TextPosition alone leaves the leader behind. Do not fall
    # back to TextPosition: if the leader cannot move, the caller must skip the
    # element instead of producing a detached leader.
    spot.LeaderEndPosition = spot.LeaderEndPosition + translation


def repair_leader_gap(spot, active_view):
    """Restore a compact text-to-leader relationship without moving the text."""
    try:
        text_position = spot.TextPosition
        leader_position = spot.LeaderEndPosition
        right_axis = active_view.RightDirection
        up_axis = active_view.UpDirection

        # Point the leader end toward the referenced coordinate location.
        toward_origin = coordinate(spot.Origin - text_position, right_axis)
        horizontal_sign = 1.0 if toward_origin >= 0.0 else -1.0
        horizontal_feet = (
            LEADER_HORIZONTAL_OFFSET_MM * active_view.Scale / 304.8
        )

        current_vertical = coordinate(leader_position - text_position, up_axis)
        current_vertical_mm = current_vertical * 304.8 / active_view.Scale
        if abs(current_vertical_mm) <= MAX_VALID_VERTICAL_OFFSET_MM:
            vertical_feet = current_vertical
        else:
            vertical_feet = (
                -LEADER_VERTICAL_OFFSET_MM * active_view.Scale / 304.8
            )

        repaired_end = (
            text_position
            + right_axis.Multiply(horizontal_sign * horizontal_feet)
            + up_axis.Multiply(vertical_feet)
        )

        # Setting LeaderEndPosition also moves TextPosition. Restore the saved
        # text point afterward; TextPosition can be set independently and this
        # leaves the repaired leader end in place.
        spot.LeaderEndPosition = repaired_end
        spot.TextPosition = text_position
        return True
    except Exception:
        return False


def align_spots(spots, mode, active_view):
    axis = active_view.RightDirection if mode in ("Left", "Right") else active_view.UpDirection
    use_minimum = mode in ("Left", "Bottom")

    aligned = 0
    skipped = []
    with revit.Transaction("Align Spot Coordinates - {0}".format(mode)):
        for spot in spots:
            repair_leader_gap(spot, active_view)
        doc.Regenerate()
        values = [bounding_edge(spot, active_view, axis, use_minimum) for spot in spots]
        target = min(values) if use_minimum else max(values)

        for spot in spots:
            try:
                if spot.Pinned or not spot.IsTextPositionAdjustable():
                    skipped.append(spot.Id.Value)
                    continue
                current_edge = bounding_edge(spot, active_view, axis, use_minimum)
                move_text_and_leader(spot, axis, target - current_edge)
                aligned += 1
            except Exception:
                skipped.append(spot.Id.Value)
        doc.Regenerate()

        # Revit recalculates annotation extents after text and elbow movement.
        # A correction pass removes small residual differences in the true
        # rendered text edges.
        for spot in spots:
            if spot.Id.Value in skipped:
                continue
            try:
                current_edge = bounding_edge(spot, active_view, axis, use_minimum)
                move_text_and_leader(spot, axis, target - current_edge)
            except Exception:
                if spot.Id.Value not in skipped:
                    skipped.append(spot.Id.Value)
    return aligned, skipped


def copy_writable_parameters(source, target):
    """Copy compatible writable instance parameter values to a recreated spot."""
    for source_parameter in source.Parameters:
        try:
            target_parameter = target.LookupParameter(source_parameter.Definition.Name)
            if (
                target_parameter is None
                or target_parameter.IsReadOnly
                or source_parameter.StorageType != target_parameter.StorageType
            ):
                continue

            storage_type = source_parameter.StorageType
            if storage_type == DB.StorageType.Double:
                target_parameter.Set(source_parameter.AsDouble())
            elif storage_type == DB.StorageType.Integer:
                target_parameter.Set(source_parameter.AsInteger())
            elif storage_type == DB.StorageType.String:
                value = source_parameter.AsString()
                if value is not None:
                    target_parameter.Set(value)
            elif storage_type == DB.StorageType.ElementId:
                target_parameter.Set(source_parameter.AsElementId())
        except Exception:
            continue


def recreate_spot_at_text_position(spot, target_text, active_view):
    """Recreate a Spot Coordinate so Revit rebuilds its inaccessible bend."""
    if spot.References is None or spot.References.Size == 0:
        raise Exception("Spot Coordinate has no reference")

    reference = spot.References.get_Item(0)
    origin = spot.Origin
    text_to_end = spot.TextPosition - spot.LeaderEndPosition
    target_end = target_text - text_to_end
    right_axis = active_view.RightDirection
    toward_origin = coordinate(origin - target_end, right_axis)
    direction = 1.0 if toward_origin >= 0.0 else -1.0
    shoulder_feet = DISTRIBUTION_SHOULDER_MM * active_view.Scale / 304.8
    bend = target_end + right_axis.Multiply(direction * shoulder_feet)

    new_spot = doc.Create.NewSpotCoordinate(
        active_view,
        reference,
        origin,
        bend,
        target_end,
        origin,
        spot.HasLeader,
    )
    new_spot.ChangeTypeId(spot.GetTypeId())
    copy_writable_parameters(spot, new_spot)

    try:
        overrides = active_view.GetElementOverrides(spot.Id)
        active_view.SetElementOverrides(new_spot.Id, overrides)
    except Exception:
        pass

    was_pinned = spot.Pinned
    old_id = spot.Id
    doc.Delete(old_id)
    new_spot.Pinned = was_pinned
    return new_spot


def distribute_spots(spots, mode, active_view):
    """Evenly distribute text drag points between the two outermost spots."""
    axis = (
        active_view.RightDirection
        if mode == "Distribute Horizontally"
        else active_view.UpDirection
    )
    ordered_spots = sorted(
        spots,
        key=lambda item: coordinate(item.TextPosition, axis),
    )
    first_value = coordinate(ordered_spots[0].TextPosition, axis)
    last_value = coordinate(ordered_spots[-1].TextPosition, axis)
    spacing = (last_value - first_value) / float(len(ordered_spots) - 1)

    moved = 0
    skipped = []
    with revit.Transaction("Align Spot Coordinates - {0}".format(mode)):
        for spot in ordered_spots:
            repair_leader_gap(spot, active_view)
        doc.Regenerate()

        # Keep both outermost Spot Coordinates fixed, matching Revit's
        # distribute behavior. Recreate only intermediate annotations because
        # Revit 2026 does not expose the bend point and rejects vertical changes
        # to LeaderEndPosition when Leader Shoulder is enabled.
        for index, spot in enumerate(ordered_spots[1:-1], start=1):
            try:
                if (
                    spot.Pinned
                    or not spot.IsTextPositionAdjustable()
                    or spot.GroupId.Value != -1
                ):
                    skipped.append(spot.Id.Value)
                    continue
                target = first_value + (spacing * index)
                current = coordinate(spot.TextPosition, axis)
                target_text = aligned_position(spot.TextPosition, axis, target)
                recreate_spot_at_text_position(spot, target_text, active_view)
                moved += 1
            except Exception:
                skipped.append(spot.Id.Value)
        doc.Regenerate()
    return moved, skipped


def reset_spots(spots):
    """Restore Revit's native text and leader positions."""
    reset_count = 0
    skipped = []
    with revit.Transaction("Reset Spot Coordinate Text Positions"):
        for spot in spots:
            try:
                if spot.Pinned:
                    skipped.append(spot.Id.Value)
                    continue
                spot.ResetTextPosition()
                reset_count += 1
            except Exception:
                skipped.append(spot.Id.Value)
        doc.Regenerate()
    return reset_count, skipped


doc = revit.doc
uidoc = revit.uidoc
view = doc.ActiveView

spots = get_selected_spots(uidoc, doc, view)
mode = forms.CommandSwitchWindow.show(
    [
        "Left",
        "Right",
        "Top",
        "Bottom",
        "Distribute Horizontally",
        "Distribute Vertically",
        "Reset Text Position",
    ],
    message="Choose an alignment or distribution mode",
    title="Align Spot Coordinates",
)
if not mode:
    script.exit()

if not spots:
    spots = pick_spots(uidoc, doc, view)

if not spots:
    forms.alert(
        "No Spot Coordinates were found in the active view.",
        title="Align Spot Coordinates",
        warn_icon=True,
    )
    script.exit()

if mode == "Reset Text Position":
    aligned_count, skipped_ids = reset_spots(spots)
elif mode.startswith("Distribute"):
    if len(spots) < 3:
        forms.alert(
            "Select at least three Spot Coordinates to distribute them evenly.",
            title="Align Spot Coordinates",
            warn_icon=True,
        )
        script.exit()
    aligned_count, skipped_ids = distribute_spots(spots, mode, view)
else:
    if len(spots) < 2:
        forms.alert(
            "Select at least two Spot Coordinates to align them.",
            title="Align Spot Coordinates",
            warn_icon=True,
        )
        script.exit()
    aligned_count, skipped_ids = align_spots(spots, mode, view)
if skipped_ids:
    forms.alert(
        "Aligned: {0}\nSkipped: {1}\n\nSkipped elements are pinned or do not allow text movement.\nElement IDs: {2}".format(
            aligned_count,
            len(skipped_ids),
            ", ".join(str(element_id) for element_id in skipped_ids),
        ),
        title="Align Spot Coordinates",
        warn_icon=True,
    )
elif aligned_count == 0:
    forms.alert(
        "No Spot Coordinates could be aligned.",
        title="Align Spot Coordinates",
        warn_icon=True,
    )
