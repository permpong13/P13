# -*- coding: utf-8 -*-
"""Remove overlapping lines, dimensions, and tags from the active view."""

# pylint: disable=E0401,C0103
import math
from collections import namedtuple

from pyrevit import DB, forms, revit, script
from pyrevit.compat import get_elementid_value_func
from pyrevit.framework import List


logger = script.get_logger()
UI_FILE = script.get_bundle_file('ui.xaml')

COORDINATE_DIGITS = 4
DIRECTION_DIGITS = 6
OVERLAP_TOLERANCE = 10 ** (-COORDINATE_DIGITS)

_get_elementid_value = get_elementid_value_func()

LineRecord = namedtuple(
    'LineRecord',
    ['element', 'start', 'end', 'depth', 'direction_x', 'direction_y']
)


def element_id_value(element_id):
    """Return an ElementId value across old and new Revit API versions."""
    if element_id is None:
        return None
    return _get_elementid_value(element_id)


def rounded_xyz(point, digits=3):
    """Return a stable coordinate identity for an XYZ point."""
    return (
        round(point.X, digits),
        round(point.Y, digits),
        round(point.Z, digits),
    )


def delete_elements(doc, element_ids):
    """Delete ElementId objects without converting them through API-specific integers."""
    if not element_ids:
        return 0
    doc.Delete(List[DB.ElementId](element_ids))
    return len(element_ids)


def dot(point, vector):
    """Calculate the dot product without relying on runtime-specific overloads."""
    return point.X * vector.X + point.Y * vector.Y + point.Z * vector.Z


class ViewCoordinateSystem(object):
    """Convert model XYZ coordinates to and from the active view coordinate plane."""

    def __init__(self, view):
        self.right = view.RightDirection.Normalize()
        self.up = view.UpDirection.Normalize()
        self.normal = view.ViewDirection.Normalize()

    def project(self, point):
        return (
            dot(point, self.right),
            dot(point, self.up),
            dot(point, self.normal),
        )

    def reconstruct(self, x_value, y_value, depth):
        return DB.XYZ(
            self.right.X * x_value + self.up.X * y_value + self.normal.X * depth,
            self.right.Y * x_value + self.up.Y * y_value + self.normal.Y * depth,
            self.right.Z * x_value + self.up.Z * y_value + self.normal.Z * depth,
        )


def get_line_weight(curve_element):
    """Return the effective line weight used by the original Overkill option."""
    try:
        line_style = curve_element.LineStyle
        category = line_style.GraphicsStyleCategory
        style_type = line_style.GraphicsStyleType
        return category.GetLineWeight(style_type)
    except Exception as error:
        logger.debug('Could not read line weight for %s: %s', curve_element.Id, error)
        return None


def create_line_record(curve_element, coordinates):
    """Create a normalized 2D interval record for a straight CurveElement."""
    geometry = curve_element.GeometryCurve
    if not isinstance(geometry, DB.Line):
        return None

    point_a = coordinates.project(geometry.GetEndPoint(0))
    point_b = coordinates.project(geometry.GetEndPoint(1))
    delta_x = point_b[0] - point_a[0]
    delta_y = point_b[1] - point_a[1]
    length_2d = math.sqrt(delta_x * delta_x + delta_y * delta_y)
    if length_2d <= OVERLAP_TOLERANCE:
        return None

    direction_x = delta_x / length_2d
    direction_y = delta_y / length_2d
    if direction_x < 0.0 or (abs(direction_x) <= OVERLAP_TOLERANCE and direction_y < 0.0):
        direction_x = -direction_x
        direction_y = -direction_y

    start = point_a[0] * direction_x + point_a[1] * direction_y
    end = point_b[0] * direction_x + point_b[1] * direction_y
    if start > end:
        start, end = end, start

    depth = (point_a[2] + point_b[2]) / 2.0
    return LineRecord(
        curve_element,
        start,
        end,
        depth,
        direction_x,
        direction_y,
    )


def line_group_key(record, coordinates, include_line_weights):
    """Group collinear lines while keeping separate planes and optional weights."""
    geometry = record.element.GeometryCurve
    point = geometry.GetEndPoint(0)
    direction_x = record.direction_x
    direction_y = record.direction_y

    # The signed perpendicular offset prevents mirrored parallel lines from merging.
    projected_point = coordinates.project(point)
    view_x = projected_point[0]
    view_y = projected_point[1]
    offset = -direction_y * view_x + direction_x * view_y

    weight = get_line_weight(record.element) if include_line_weights else None
    return (
        round(direction_x, DIRECTION_DIGITS),
        round(direction_y, DIRECTION_DIGITS),
        round(offset, COORDINATE_DIGITS),
        round(record.depth, COORDINATE_DIGITS),
        weight,
    )


def merge_line_cluster(doc, coordinates, records):
    """Extend one keeper line across a cluster and delete its overlaps."""
    if len(records) < 2:
        return 0

    keeper = records[0]
    cluster_start = min(record.start for record in records)
    cluster_end = max(record.end for record in records)

    geometry = keeper.element.GeometryCurve
    projected_point = coordinates.project(geometry.GetEndPoint(0))
    perpendicular_offset = (
        -keeper.direction_y * projected_point[0]
        + keeper.direction_x * projected_point[1]
    )

    start_x = keeper.direction_x * cluster_start - keeper.direction_y * perpendicular_offset
    start_y = keeper.direction_y * cluster_start + keeper.direction_x * perpendicular_offset
    end_x = keeper.direction_x * cluster_end - keeper.direction_y * perpendicular_offset
    end_y = keeper.direction_y * cluster_end + keeper.direction_x * perpendicular_offset

    start_point = coordinates.reconstruct(start_x, start_y, keeper.depth)
    end_point = coordinates.reconstruct(end_x, end_y, keeper.depth)

    try:
        merged_geometry = DB.Line.CreateBound(start_point, end_point)
        keeper.element.SetGeometryCurve(merged_geometry, True)
    except Exception as error:
        logger.warning('Skipped line cluster at element %s: %s', keeper.element.Id, error)
        return 0

    duplicate_ids = [record.element.Id for record in records[1:]]
    return delete_elements(doc, duplicate_ids)


def overkill_lines(doc, view, include_line_weights):
    """Merge overlapping straight CurveElements in the active view coordinate plane."""
    coordinates = ViewCoordinateSystem(view)

    curve_elements = (
        DB.FilteredElementCollector(doc, view.Id)
        .OfClass(DB.CurveElement)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    grouped_records = {}
    for curve_element in curve_elements:
        try:
            record = create_line_record(curve_element, coordinates)
            if record is None:
                continue
            key = line_group_key(record, coordinates, include_line_weights)
            grouped_records.setdefault(key, []).append(record)
        except Exception as error:
            logger.debug('Skipped curve %s: %s', curve_element.Id, error)

    removed_count = 0
    for records in grouped_records.values():
        records.sort(key=lambda item: (item.start, item.end))
        cluster = []
        cluster_end = None

        for record in records:
            if not cluster or record.start <= cluster_end + OVERLAP_TOLERANCE:
                cluster.append(record)
                cluster_end = record.end if cluster_end is None else max(cluster_end, record.end)
            else:
                removed_count += merge_line_cluster(doc, coordinates, cluster)
                cluster = [record]
                cluster_end = record.end

        removed_count += merge_line_cluster(doc, coordinates, cluster)

    return removed_count


def dimension_reference_key(doc, dimension):
    """Return stable references, or None when the dimension cannot be compared safely."""
    references = []
    try:
        for reference in dimension.References:
            references.append(reference.ConvertToStableRepresentation(doc))
    except Exception as error:
        logger.debug('Could not read references for dimension %s: %s', dimension.Id, error)
        return None
    references.sort()
    return tuple(references)


def overkill_dimensions(doc, view_id):
    """Remove dimensions with matching location, type, and references."""
    dimensions = (
        DB.FilteredElementCollector(doc, view_id)
        .OfClass(DB.Dimension)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    unique_dimensions = {}
    duplicate_ids = []

    for dimension in dimensions:
        try:
            origin = dimension.Origin
            reference_key = dimension_reference_key(doc, dimension)
            if origin is None or reference_key is None:
                continue

            key = (
                rounded_xyz(origin),
                element_id_value(dimension.GetTypeId()),
                reference_key,
            )
            if key in unique_dimensions:
                duplicate_ids.append(dimension.Id)
            else:
                unique_dimensions[key] = dimension.Id
        except Exception as error:
            logger.debug('Skipped dimension %s: %s', dimension.Id, error)

    return delete_elements(doc, duplicate_ids)


def link_element_id_key(link_element_id):
    """Build a Revit-version-safe identity for local and linked tag targets."""
    values = []
    for property_name in ('HostElementId', 'LinkInstanceId', 'LinkedElementId'):
        try:
            values.append(element_id_value(getattr(link_element_id, property_name)))
        except Exception:
            values.append(None)
    return tuple(values)


def tagged_elements_key(tag):
    """Return all targets of an IndependentTag without using IntegerValue."""
    try:
        targets = [link_element_id_key(item) for item in tag.GetTaggedElementIds()]
        targets.sort(key=lambda item: str(item))
        return tuple(targets)
    except Exception as error:
        logger.debug('Could not read modern targets for tag %s: %s', tag.Id, error)

    try:
        return ((element_id_value(tag.TaggedLocalElementId), None, None),)
    except Exception as error:
        logger.debug('Could not read legacy target for tag %s: %s', tag.Id, error)
        return None


def overkill_tags(doc, view_id):
    """Remove tags with matching targets, head location, and type."""
    tags = (
        DB.FilteredElementCollector(doc, view_id)
        .OfClass(DB.IndependentTag)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    unique_tags = {}
    duplicate_ids = []

    for tag in tags:
        try:
            target_key = tagged_elements_key(tag)
            if target_key is None:
                continue

            key = (
                target_key,
                rounded_xyz(tag.TagHeadPosition),
                element_id_value(tag.GetTypeId()),
            )
            if key in unique_tags:
                duplicate_ids.append(tag.Id)
            else:
                unique_tags[key] = tag.Id
        except Exception as error:
            logger.debug('Skipped tag %s: %s', tag.Id, error)

    return delete_elements(doc, duplicate_ids)


def optional_xyz_key(owner, property_name):
    """Read an optional XYZ property as a stable key."""
    try:
        value = getattr(owner, property_name)
        return rounded_xyz(value)
    except Exception:
        return None


def text_leaders_key(text_note):
    """Return leader geometry so notes with different leaders remain separate."""
    try:
        leaders = text_note.GetLeaders()
    except Exception as error:
        logger.debug('Could not read leaders for text note %s: %s', text_note.Id, error)
        return None

    leader_keys = []
    for leader in leaders:
        leader_keys.append((
            str(getattr(leader, 'LeaderType', '')),
            optional_xyz_key(leader, 'Anchor'),
            optional_xyz_key(leader, 'Elbow'),
            optional_xyz_key(leader, 'End'),
        ))
    leader_keys.sort(key=lambda item: str(item))
    return tuple(leader_keys)


def overkill_text_notes(doc, view_id):
    """Remove exactly overlapping TextNotes while preserving formatting and leaders."""
    text_notes = (
        DB.FilteredElementCollector(doc, view_id)
        .OfClass(DB.TextNote)
        .WhereElementIsNotElementType()
        .ToElements()
    )
    unique_notes = {}
    duplicate_ids = []

    for text_note in text_notes:
        try:
            leaders_key = text_leaders_key(text_note)
            if leaders_key is None:
                continue

            key = (
                text_note.Text,
                rounded_xyz(text_note.Coord),
                element_id_value(text_note.GetTypeId()),
                round(text_note.Width, COORDINATE_DIGITS),
                str(text_note.HorizontalAlignment),
                str(text_note.VerticalAlignment),
                optional_xyz_key(text_note, 'BaseDirection'),
                optional_xyz_key(text_note, 'UpDirection'),
                leaders_key,
            )
            if key in unique_notes:
                duplicate_ids.append(text_note.Id)
            else:
                unique_notes[key] = text_note.Id
        except Exception as error:
            logger.debug('Skipped text note %s: %s', text_note.Id, error)

    return delete_elements(doc, duplicate_ids)


def show_results(lines_removed, dimensions_removed, tags_removed, text_notes_removed):
    """Display a concise English-only completion report."""
    message = (
        'View Cleanup Results:\n'
        '- Lines removed: {}\n'
        '- Dimensions removed: {}\n'
        '- Tags removed: {}\n'
        '- Text notes removed: {}'
    ).format(lines_removed, dimensions_removed, tags_removed, text_notes_removed)
    forms.alert(message, title='Overkill Complete', warn_icon=False)


class OverkillWindow(forms.WPFWindow):
    """Modern cleanup-scope dialog for Revit 2026."""

    def __init__(self, active_view):
        forms.WPFWindow.__init__(self, UI_FILE)
        self.cleanup_mode = None
        self.consider_line_weights = True
        self.activeViewText.Text = 'Active view: {}'.format(active_view.Name)
        self.mode_changed(None, None)

    def mode_changed(self, sender, args):
        uses_lines = self.modeEverything.IsChecked or self.modeLines.IsChecked
        self.lineOptionsPanel.IsEnabled = uses_lines
        self.lineOptionsPanel.Opacity = 1.0 if uses_lines else 0.42

    def select_everything(self, sender, args):
        self.modeEverything.IsChecked = True
        self.mode_changed(sender, args)

    def select_lines(self, sender, args):
        self.modeLines.IsChecked = True
        self.mode_changed(sender, args)

    def select_dimensions(self, sender, args):
        self.modeDimensions.IsChecked = True
        self.mode_changed(sender, args)

    def select_tags(self, sender, args):
        self.modeTags.IsChecked = True
        self.mode_changed(sender, args)

    def select_text_notes(self, sender, args):
        self.modeTextNotes.IsChecked = True
        self.mode_changed(sender, args)

    def run_clicked(self, sender, args):
        if self.modeLines.IsChecked:
            self.cleanup_mode = 'Lines'
        elif self.modeDimensions.IsChecked:
            self.cleanup_mode = 'Dimensions'
        elif self.modeTags.IsChecked:
            self.cleanup_mode = 'Tags'
        elif self.modeTextNotes.IsChecked:
            self.cleanup_mode = 'TextNotes'
        else:
            self.cleanup_mode = 'Everything'

        self.consider_line_weights = bool(self.considerLineWeights.IsChecked)
        self.DialogResult = True
        self.Close()

    def cancel_clicked(self, sender, args):
        self.DialogResult = False
        self.Close()


def main():
    """Run the selected cleanup mode in one atomic transaction."""
    doc = revit.doc
    active_view = revit.active_view
    dialog = OverkillWindow(active_view)
    if not dialog.ShowDialog():
        return

    cleanup_mode = dialog.cleanup_mode
    lines_removed = 0
    dimensions_removed = 0
    tags_removed = 0
    text_notes_removed = 0

    with revit.Transaction('View Overkill Cleanup'):
        if cleanup_mode in ('Everything', 'Lines'):
            lines_removed = overkill_lines(
                doc,
                active_view,
                dialog.consider_line_weights,
            )
        if cleanup_mode in ('Everything', 'Dimensions'):
            dimensions_removed = overkill_dimensions(doc, active_view.Id)
        if cleanup_mode in ('Everything', 'Tags'):
            tags_removed = overkill_tags(doc, active_view.Id)
        if cleanup_mode in ('Everything', 'TextNotes'):
            text_notes_removed = overkill_text_notes(doc, active_view.Id)

    show_results(lines_removed, dimensions_removed, tags_removed, text_notes_removed)


if __name__ == '__main__':
    main()
