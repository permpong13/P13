# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except,too-many-lines,too-many-instance-attributes
"""Grids 2D Pro - Revit-Native WPF Dialog for converting/resetting Grid extents safely."""

__title__ = "Grids\n2D Pro"
__author__ = "Permpong Thawikul (P13)"
__doc__ = (
    "Manage 2D/3D Grid extents in the active view with a native Revit UI.\n\n"
    "- Convert 3D -> 2D without moving existing customized 2D ends or elbows\n"
    "- Reset distorted 2D ends back to 3D extents and set to 2D\n"
    "- Revert selected Grids back to 3D Model extents\n"
    "- Supports pre-selection, Shift/Ctrl multi-select, and live Apply"
)

import sys
import traceback

import clr
clr.AddReference("System")
clr.AddReference("System.Data")
clr.AddReference("System.Xml")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

import System
from System.Data import DataTable
from System.Windows.Controls import CheckBox
from System.Windows.Controls import DataGridRow
from System.Windows.Controls import DataGridSelectionMode
from System.Windows.Controls import DataGridSelectionUnit
from System.Windows.Input import Key
from System.Windows.Input import Keyboard
from System.Windows.Input import ModifierKeys
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import Color as MediaColor
from System.Windows.Media import SolidColorBrush
from System.Windows.Media import Visual
from System.Windows.Media import VisualTreeHelper

from pyrevit import revit
from pyrevit import DB
from pyrevit import forms
from pyrevit import HOST_APP

try:
    from pyrevit import UI
except Exception:
    clr.AddReference("RevitAPIUI")
    import Autodesk.Revit.UI as UI

PY2 = sys.version_info[0] < 3
TEXT_TYPE = unicode if PY2 else str  # noqa: F821


# ------------------------------------------------------------------------------
# COMPATIBILITY & COLOR BRUSH HELPERS (Revit 2019 - 2026+)
# ------------------------------------------------------------------------------
def to_text(val):
    if val is None:
        return u""
    if isinstance(val, TEXT_TYPE):
        return val
    try:
        return val.decode("utf-8")
    except Exception:
        return TEXT_TYPE(val)


def show_alert(title, msg):
    try:
        UI.TaskDialog.Show(to_text(title), to_text(msg))
    except Exception:
        forms.alert(to_text(msg), title=to_text(title))


def get_id_val(eid):
    if eid is None or eid == DB.ElementId.InvalidElementId:
        return -1
    return int(eid.Value if hasattr(eid, "Value") else eid.IntegerValue)


def set_revit_owner(wpf_win):
    try:
        hwnd = System.IntPtr.Zero
        try:
            hwnd = HOST_APP.uiapp.MainWindowHandle
        except Exception:
            pass
        if hwnd == System.IntPtr.Zero:
            hwnd = System.Diagnostics.Process.GetCurrentProcess().MainWindowHandle
        if hwnd != System.IntPtr.Zero:
            WindowInteropHelper(wpf_win).Owner = hwnd
    except Exception:
        pass


def make_brush(r, g, b):
    br = SolidColorBrush(
        MediaColor.FromArgb(
            System.Byte(255),
            System.Byte(r),
            System.Byte(g),
            System.Byte(b)
        )
    )
    br.Freeze()
    return br


BRUSH_2D_TEXT = make_brush(20, 115, 50)
BRUSH_2D_BG = make_brush(232, 246, 236)
BRUSH_3D_TEXT = make_brush(0, 95, 175)
BRUSH_3D_BG = make_brush(232, 242, 252)
BRUSH_LOCK_TEXT = make_brush(175, 85, 10)
BRUSH_MUTED_TEXT = make_brush(130, 130, 130)
BRUSH_NORMAL_TEXT = make_brush(35, 35, 35)

BRUSH_CARD_ACTIVE_BG = make_brush(240, 247, 255)
BRUSH_CARD_ACTIVE_BDR = make_brush(0, 120, 212)
BRUSH_CARD_WARN_BG = make_brush(255, 248, 238)
BRUSH_CARD_WARN_BDR = make_brush(217, 119, 6)
BRUSH_CARD_IDLE_BG = make_brush(255, 255, 255)
BRUSH_CARD_IDLE_BDR = make_brush(210, 210, 210)


# ------------------------------------------------------------------------------
# GRID INSPECTION & SAFE CONVERSION ENGINE
# ------------------------------------------------------------------------------
def get_scope_box_name(doc, grid):
    """Return Scope Box name if grid is controlled by a Scope Box, else None."""
    try:
        param = grid.get_Parameter(DB.BuiltInParameter.DATUM_VOLUME_OF_INTEREST)
        if param:
            sb_id = param.AsElementId()
            if get_id_val(sb_id) > 0:
                sb_elem = doc.GetElement(sb_id)
                return to_text(sb_elem.Name) if sb_elem else u"Scope Box"
    except Exception:
        pass
    return None


def get_leader_safe(grid, end, view):
    try:
        if hasattr(grid, "IsLeaderValid") and not grid.IsLeaderValid(end, view):
            return None
        return grid.GetLeader(end, view)
    except Exception:
        return None


def restore_leader_safe(grid, end, view, leader):
    if leader is None:
        return
    try:
        grid.SetLeader(end, view, leader)
    except Exception:
        pass


def get_view_curve_safe(grid, extent_type, view):
    try:
        curves = grid.GetCurvesInView(extent_type, view)
        if curves and curves.Count == 1:
            return curves[0]
    except Exception:
        pass
    return None


def convert_single_grid(grid, view, mode):
    """Process a single Grid in view. Returns (changed_ends, preserved_ends)."""
    changed = 0
    preserved = 0

    end0_type = grid.GetDatumExtentTypeInView(DB.DatumEnds.End0, view)
    end1_type = grid.GetDatumExtentTypeInView(DB.DatumEnds.End1, view)

    if mode == "safe":
        # Backup current visible 2D/3D curve endpoints before touching anything
        ref_type = (
            DB.DatumExtentType.ViewSpecific
            if (end0_type == DB.DatumExtentType.ViewSpecific or end1_type == DB.DatumExtentType.ViewSpecific)
            else DB.DatumExtentType.Model
        )
        orig_curve = get_view_curve_safe(grid, ref_type, view)
        ldr0 = get_leader_safe(grid, DB.DatumEnds.End0, view)
        ldr1 = get_leader_safe(grid, DB.DatumEnds.End1, view)

        if end0_type == DB.DatumExtentType.Model:
            grid.SetDatumExtentType(DB.DatumEnds.End0, view, DB.DatumExtentType.ViewSpecific)
            changed += 1
        else:
            preserved += 1

        if end1_type == DB.DatumExtentType.Model:
            grid.SetDatumExtentType(DB.DatumEnds.End1, view, DB.DatumExtentType.ViewSpecific)
            changed += 1
        else:
            preserved += 1

        # Ensure exact curve endpoints did not shift if any conversion happened
        if changed > 0 and orig_curve is not None and isinstance(orig_curve, DB.Line):
            try:
                cur_curve = get_view_curve_safe(grid, DB.DatumExtentType.ViewSpecific, view)
                if cur_curve is not None and isinstance(cur_curve, DB.Line):
                    p0 = orig_curve.GetEndPoint(0)
                    p1 = orig_curve.GetEndPoint(1)
                    c0 = cur_curve.GetEndPoint(0)
                    c1 = cur_curve.GetEndPoint(1)
                    if p0.DistanceTo(c0) > 1e-5 or p1.DistanceTo(c1) > 1e-5:
                        exact_line = DB.Line.CreateBound(p0, p1)
                        grid.SetCurveInView(DB.DatumExtentType.ViewSpecific, view, exact_line)
            except Exception:
                pass

        if changed > 0:
            restore_leader_safe(grid, DB.DatumEnds.End0, view, ldr0)
            restore_leader_safe(grid, DB.DatumEnds.End1, view, ldr1)

    elif mode == "reset_2d":
        for end, cur_t in [(DB.DatumEnds.End0, end0_type), (DB.DatumEnds.End1, end1_type)]:
            if cur_t == DB.DatumExtentType.ViewSpecific:
                grid.SetDatumExtentType(end, view, DB.DatumExtentType.Model)
            grid.SetDatumExtentType(end, view, DB.DatumExtentType.ViewSpecific)
            changed += 1

    elif mode == "to_3d":
        for end, cur_t in [(DB.DatumEnds.End0, end0_type), (DB.DatumEnds.End1, end1_type)]:
            if cur_t == DB.DatumExtentType.ViewSpecific:
                grid.SetDatumExtentType(end, view, DB.DatumExtentType.Model)
                changed += 1
            else:
                preserved += 1

    return changed, preserved


# ------------------------------------------------------------------------------
# MULTI-SELECT CONTROLLER (SHIFT+CLICK, CTRL+CLICK, SPACEBAR)
# ------------------------------------------------------------------------------
class MultiSelectGridController(object):
    def __init__(self, dg, dt, info_label):
        self.dg = dg
        self.dt = dt
        self.info_label = info_label
        self.last_idx = None
        self.dg.SelectionMode = DataGridSelectionMode.Extended
        self.dg.SelectionUnit = DataGridSelectionUnit.FullRow
        self.dg.PreviewMouseLeftButtonDown += self._on_mouse_down
        self.dg.PreviewKeyDown += self._on_key_down
        self.dg.SelectionChanged += self._on_sel_changed

    def _find_ancestors(self, dep_obj):
        cb, row = None, None
        curr = dep_obj
        while curr is not None:
            if cb is None and isinstance(curr, CheckBox):
                cb = curr
            if row is None and isinstance(curr, DataGridRow):
                row = curr
                break
            if not isinstance(curr, Visual):
                break
            curr = VisualTreeHelper.GetParent(curr)
        return cb, row

    def _on_mouse_down(self, sender, args):
        cb, row = self._find_ancestors(args.OriginalSource)
        if cb is None or row is None:
            return
        drv = row.Item
        if bool(drv["IsLocked"]):
            args.Handled = True
            return

        cur_idx = row.GetIndex()
        new_val = not bool(drv["IsChecked"])
        mods = Keyboard.Modifiers

        if (mods & ModifierKeys.Shift) == ModifierKeys.Shift and self.last_idx is not None:
            s_i = min(self.last_idx, cur_idx)
            e_i = max(self.last_idx, cur_idx)
            for i in range(s_i, min(e_i + 1, self.dg.Items.Count)):
                if not bool(self.dg.Items[i]["IsLocked"]):
                    self.dg.Items[i]["IsChecked"] = new_val
            self.last_idx = cur_idx
            args.Handled = True
            return

        if row.IsSelected and self.dg.SelectedItems.Count > 1:
            for item in list(self.dg.SelectedItems):
                if not bool(item["IsLocked"]):
                    item["IsChecked"] = new_val
            self.last_idx = cur_idx
            args.Handled = True
            return

        drv["IsChecked"] = new_val
        self.last_idx = cur_idx
        if (mods & ModifierKeys.Control) != ModifierKeys.Control:
            self.dg.SelectedIndex = cur_idx
        args.Handled = True

    def _on_key_down(self, sender, args):
        if args.Key == Key.Space and self.dg.SelectedItems.Count > 0:
            editable = [it for it in list(self.dg.SelectedItems) if not bool(it["IsLocked"])]
            if editable:
                new_val = not bool(editable[0]["IsChecked"])
                for it in editable:
                    it["IsChecked"] = new_val
            args.Handled = True

    def _on_sel_changed(self, sender, args):
        if self.info_label is not None:
            cnt = self.dg.SelectedItems.Count
            if cnt > 1:
                self.info_label.Text = u"{} rows highlighted (Press Spacebar to toggle check)".format(cnt)
            else:
                self.info_label.Text = u"Tip: Shift+Click or Ctrl+Click to select multiple rows"


# ------------------------------------------------------------------------------
# REVIT-NATIVE WPF XAML
# ------------------------------------------------------------------------------
MAIN_WINDOW_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Datum Extents Manager - Grids 2D Pro"
        Width="860" Height="640" MinWidth="740" MinHeight="540"
        WindowStartupLocation="CenterScreen"
        Background="#F0F0F0" FontFamily="Segoe UI" FontSize="12"
        UseLayoutRounding="True" SnapsToDevicePixels="True">
    <Window.Resources>
        <Style x:Key="RevitBtn" TargetType="Button">
            <Setter Property="Height" Value="24"/>
            <Setter Property="MinWidth" Value="74"/>
            <Setter Property="Padding" Value="10,2"/>
            <Setter Property="Background" Value="#FBFBFB"/>
            <Setter Property="Foreground" Value="#1E1E1E"/>
            <Setter Property="BorderBrush" Value="#ABADB3"/>
            <Setter Property="BorderThickness" Value="1"/>
        </Style>
        <Style x:Key="RevitPrimaryBtn" TargetType="Button" BasedOn="{StaticResource RevitBtn}">
            <Setter Property="BorderBrush" Value="#0078D4"/>
            <Setter Property="BorderThickness" Value="1.5"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
        </Style>
        <Style TargetType="DataGridColumnHeader">
            <Setter Property="Background" Value="#F5F6F7"/>
            <Setter Property="Foreground" Value="#1E1E1E"/>
            <Setter Property="BorderBrush" Value="#D8D8D8"/>
            <Setter Property="BorderThickness" Value="0,0,1,1"/>
            <Setter Property="Padding" Value="8,5"/>
        </Style>
        <Style TargetType="DataGridRow">
            <Style.Triggers>
                <Trigger Property="IsSelected" Value="True">
                    <Setter Property="Background" Value="#CDE4FA"/>
                    <Setter Property="Foreground" Value="#111111"/>
                </Trigger>
            </Style.Triggers>
        </Style>
        <Style TargetType="DataGridCell">
            <Setter Property="BorderThickness" Value="0"/>
            <Style.Triggers>
                <Trigger Property="IsSelected" Value="True">
                    <Setter Property="Background" Value="#CDE4FA"/>
                    <Setter Property="Foreground" Value="#111111"/>
                </Trigger>
            </Style.Triggers>
        </Style>
    </Window.Resources>

    <Grid>
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- 1. Revit Context Header -->
        <Border Grid.Row="0" Background="#FFFFFF" BorderBrush="#D9D9D9" BorderThickness="0,0,0,1" Padding="14,9">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
                    <Border Width="4" Height="18" Background="#0696D7" Margin="0,0,9,0"/>
                    <TextBlock Name="lbl_view_title" Text="Active View: -" FontWeight="SemiBold" Foreground="#1E1E1E" VerticalAlignment="Center"/>
                </StackPanel>
                <Border Grid.Column="1" Background="#F3F6F9" BorderBrush="#D0DCE8" BorderThickness="1" CornerRadius="2" Padding="9,3">
                    <TextBlock Name="lbl_summary_counts" Text="Grids: 0" FontSize="11.5" Foreground="#2B4C6F" FontWeight="SemiBold"/>
                </Border>
            </Grid>
        </Border>

        <!-- 2. Easy-to-Understand Action Mode Cards -->
        <Border Grid.Row="1" Margin="12,10,12,6" Background="#FFFFFF" BorderBrush="#CCCCCC" BorderThickness="1" Padding="12,10">
            <StackPanel>
                <StackPanel Orientation="Horizontal" Margin="0,0,0,8">
                    <Border Background="#0078D4" CornerRadius="2" Padding="6,1" Margin="0,0,8,0">
                        <TextBlock Text="STEP 1" Foreground="#FFFFFF" FontSize="10.5" FontWeight="Bold"/>
                    </Border>
                    <TextBlock Text="Select Grid Extent Action Mode (เลือกโหมดจัดการเส้น Grid)" FontWeight="Bold" Foreground="#1E1E1E"/>
                </StackPanel>

                <!-- Card 1: Safe 2D -->
                <Border Name="card_safe" Background="#F0F7FF" BorderBrush="#0078D4" BorderThickness="1.5" CornerRadius="2" Padding="10,7" Margin="0,0,0,6" Cursor="Hand">
                    <Grid>
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="Auto"/>
                        </Grid.ColumnDefinitions>
                        <StackPanel>
                            <RadioButton Name="rb_safe" IsChecked="True" FontWeight="SemiBold" Foreground="#004E8C"
                                         Content="1. Convert 3D to 2D  -  Keep Existing Ends &amp; Elbows (Safe Mode)"/>
                            <TextBlock Text="แปลงเฉพาะปลายที่เป็น 3D ให้เป็น 2D โดยล็อกตำแหน่งปลายเส้น 2D และข้อต่อหักหลบเดิมไว้ ไม่ให้ขยับ"
                                       Foreground="#444444" FontSize="11" Margin="22,2,0,0"/>
                        </StackPanel>
                        <Border Grid.Column="1" Background="#E6F4EA" BorderBrush="#A8DAB5" BorderThickness="1" CornerRadius="2" Padding="7,2" VerticalAlignment="Center">
                            <TextBlock Text="Recommended" Foreground="#137333" FontSize="10.5" FontWeight="SemiBold"/>
                        </Border>
                    </Grid>
                </Border>

                <!-- Card 2: Reset 3D then 2D -->
                <Border Name="card_reset2d" Background="#FFFFFF" BorderBrush="#D2D2D2" BorderThickness="1" CornerRadius="2" Padding="10,7" Margin="0,0,0,6" Cursor="Hand">
                    <Grid>
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="*"/>
                            <ColumnDefinition Width="Auto"/>
                        </Grid.ColumnDefinitions>
                        <StackPanel>
                            <RadioButton Name="rb_reset2d" FontWeight="SemiBold" Foreground="#1E1E1E"
                                         Content="2. Reset Grids to 3D Extents  -&gt;  Convert to 2D (Reset Ends)"/>
                            <TextBlock Text="รีเซ็ตดึงปลายเส้นกลับไปเท่ากับขอบเขตโมเดล 3D ก่อน แล้วตั้งเป็น 2D ใหม่ทั้งหมด (ระวัง: ปลายเส้นจะขยับกลับค่าเริ่มต้น)"
                                       Foreground="#555555" FontSize="11" Margin="22,2,0,0"/>
                        </StackPanel>
                        <Border Grid.Column="1" Background="#FEF3C7" BorderBrush="#F59E0B" BorderThickness="1" CornerRadius="2" Padding="7,2" VerticalAlignment="Center">
                            <TextBlock Text="Resets Ends" Foreground="#B45309" FontSize="10.5" FontWeight="SemiBold"/>
                        </Border>
                    </Grid>
                </Border>

                <!-- Card 3: Revert to 3D -->
                <Border Name="card_to3d" Background="#FFFFFF" BorderBrush="#D2D2D2" BorderThickness="1" CornerRadius="2" Padding="10,7" Cursor="Hand">
                    <StackPanel>
                        <RadioButton Name="rb_to3d" FontWeight="SemiBold" Foreground="#1E1E1E"
                                     Content="3. Revert to 3D Model Extents Only (3D Mode)"/>
                        <TextBlock Text="คืนค่าเส้น Grid ที่เลือกกลับไปผูกกับระนาบโมเดล 3D ตามเดิม"
                                   Foreground="#555555" FontSize="11" Margin="22,2,0,0"/>
                    </StackPanel>
                </Border>
            </StackPanel>
        </Border>

        <!-- 3. Revit-Style Grids Status Table -->
        <Border Grid.Row="2" Margin="12,0,12,8" Background="#FFFFFF" BorderBrush="#CCCCCC" BorderThickness="1" Padding="12,8">
            <Grid>
                <Grid.RowDefinitions>
                    <RowDefinition Height="Auto"/>
                    <RowDefinition Height="*"/>
                    <RowDefinition Height="Auto"/>
                </Grid.RowDefinitions>

                <Grid Grid.Row="0" Margin="0,0,0,6">
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="Auto"/>
                        <ColumnDefinition Width="*"/>
                        <ColumnDefinition Width="200"/>
                    </Grid.ColumnDefinitions>
                    <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
                        <Border Background="#3B4956" CornerRadius="2" Padding="6,1" Margin="0,0,8,0">
                            <TextBlock Text="STEP 2" Foreground="#FFFFFF" FontSize="10.5" FontWeight="Bold"/>
                        </Border>
                        <TextBlock Text="Target Grids in View:" FontWeight="Bold" Foreground="#1E1E1E"/>
                    </StackPanel>
                    <TextBlock Name="lbl_sel_hint" Grid.Column="1" Text="Tip: Shift+Click or Ctrl+Click to select multiple rows"
                               Foreground="#0066B4" FontSize="11" HorizontalAlignment="Right" VerticalAlignment="Center" Margin="0,0,10,0"/>
                    <TextBox Name="txt_search" Grid.Column="2" Height="23" VerticalContentAlignment="Center" Padding="5,0"
                             BorderBrush="#ABADB3" ToolTip="Search Grid Name"/>
                </Grid>

                <DataGrid Name="dg_grids" Grid.Row="1" AutoGenerateColumns="False" CanUserAddRows="False"
                          CanUserDeleteRows="False" CanUserResizeRows="False" HeadersVisibility="Column"
                          GridLinesVisibility="All" HorizontalGridLinesBrush="#E4E4E4" VerticalGridLinesBrush="#E4E4E4"
                          Background="#FFFFFF" BorderBrush="#ABADB3" BorderThickness="1" RowHeight="25">
                    <DataGrid.Columns>
                        <DataGridTemplateColumn Header="Use" Width="44">
                            <DataGridTemplateColumn.CellTemplate>
                                <DataTemplate>
                                    <CheckBox IsChecked="{Binding IsChecked, Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}"
                                              IsEnabled="{Binding IsEditable}" HorizontalAlignment="Center" VerticalAlignment="Center"/>
                                </DataTemplate>
                            </DataGridTemplateColumn.CellTemplate>
                        </DataGridTemplateColumn>
                        <DataGridTextColumn Header="Grid" Binding="{Binding GridName}" Width="110" IsReadOnly="True" FontWeight="SemiBold"/>
                        <DataGridTemplateColumn Header="End 0 Extent" Width="130">
                            <DataGridTemplateColumn.CellTemplate>
                                <DataTemplate>
                                    <Border Background="{Binding End0Bg}" CornerRadius="2" Padding="6,1" Margin="6,2" HorizontalAlignment="Left">
                                        <TextBlock Text="{Binding End0Text}" Foreground="{Binding End0Fg}" FontSize="11" FontWeight="SemiBold"/>
                                    </Border>
                                </DataTemplate>
                            </DataGridTemplateColumn.CellTemplate>
                        </DataGridTemplateColumn>
                        <DataGridTemplateColumn Header="End 1 Extent" Width="130">
                            <DataGridTemplateColumn.CellTemplate>
                                <DataTemplate>
                                    <Border Background="{Binding End1Bg}" CornerRadius="2" Padding="6,1" Margin="6,2" HorizontalAlignment="Left">
                                        <TextBlock Text="{Binding End1Text}" Foreground="{Binding End1Fg}" FontSize="11" FontWeight="SemiBold"/>
                                    </Border>
                                </DataTemplate>
                            </DataGridTemplateColumn.CellTemplate>
                        </DataGridTemplateColumn>
                        <DataGridTextColumn Header="Elbows / Leaders" Binding="{Binding ElbowText}" Width="130" IsReadOnly="True"/>
                        <DataGridTemplateColumn Header="Scope Box / Note" Width="*">
                            <DataGridTemplateColumn.CellTemplate>
                                <DataTemplate>
                                    <TextBlock Text="{Binding NoteText}" Foreground="{Binding NoteFg}" Margin="6,0" VerticalAlignment="Center"/>
                                </DataTemplate>
                            </DataGridTemplateColumn.CellTemplate>
                        </DataGridTemplateColumn>
                    </DataGrid.Columns>
                </DataGrid>

                <StackPanel Grid.Row="2" Orientation="Horizontal" Margin="0,6,0,0">
                    <Button Name="btn_chk_all" Content="Check All" Style="{StaticResource RevitBtn}" Margin="0,0,6,0"/>
                    <Button Name="btn_chk_none" Content="Check None" Style="{StaticResource RevitBtn}" Margin="0,0,6,0"/>
                    <Button Name="btn_chk_3d_only" Content="Check Only 3D Grids" Style="{StaticResource RevitBtn}"/>
                </StackPanel>
            </Grid>
        </Border>

        <!-- 4. Revit Standard Dialog Footer -->
        <Border Grid.Row="3" Background="#F0F0F0" BorderBrush="#D6D6D6" BorderThickness="0,1,0,0" Padding="12,8,12,10">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <TextBlock Name="lbl_status" Text="Ready." Foreground="#444444" VerticalAlignment="Center" TextTrimming="CharacterEllipsis" Margin="2,0,12,0"/>
                <StackPanel Grid.Column="1" Orientation="Horizontal">
                    <Button Name="btn_ok" Content="OK" Style="{StaticResource RevitPrimaryBtn}" Width="86" Margin="0,0,8,0"/>
                    <Button Name="btn_cancel" Content="Cancel" Style="{StaticResource RevitBtn}" Width="80" Margin="0,0,8,0" IsCancel="True"/>
                    <Button Name="btn_apply" Content="Apply" Style="{StaticResource RevitBtn}" Width="86"/>
                </StackPanel>
            </Grid>
        </Border>
    </Grid>
</Window>
"""


# ------------------------------------------------------------------------------
# MAIN DIALOG CONTROLLER
# ------------------------------------------------------------------------------
class Grids2DProWindow(object):
    def __init__(self, doc, uidoc, view, grids, preselected_ids):
        self.win = XamlReader.Parse(MAIN_WINDOW_XAML)
        set_revit_owner(self.win)

        self.doc = doc
        self.uidoc = uidoc
        self.view = view
        self.grids = sorted(grids, key=lambda g: to_text(g.Name))
        self.preselected_ids = preselected_ids
        self.checked_map = {}

        for cname in [
            "lbl_view_title", "lbl_summary_counts",
            "card_safe", "card_reset2d", "card_to3d",
            "rb_safe", "rb_reset2d", "rb_to3d",
            "lbl_sel_hint", "txt_search", "dg_grids",
            "btn_chk_all", "btn_chk_none", "btn_chk_3d_only",
            "lbl_status", "btn_ok", "btn_cancel", "btn_apply"
        ]:
            setattr(self, cname, self.win.FindName(cname))

        self.lbl_view_title.Text = u"Active View: [{}] {}".format(
            to_text(self.view.ViewType), to_text(self.view.Name)
        )

        # Build DataTable
        b_type = System.Windows.Media.Brush
        self.dt = DataTable("GridsTable")
        for col, dtype in [
            ("IsChecked", System.Boolean),
            ("IsEditable", System.Boolean),
            ("IsLocked", System.Boolean),
            ("GridName", System.String),
            ("End0Text", System.String),
            ("End0Fg", b_type),
            ("End0Bg", b_type),
            ("End1Text", System.String),
            ("End1Fg", b_type),
            ("End1Bg", b_type),
            ("ElbowText", System.String),
            ("NoteText", System.String),
            ("NoteFg", b_type),
            ("GridIndex", System.Int32)
        ]:
            self.dt.Columns.Add(col, dtype)

        # Initialize selection state (honor Revit pre-selection if any)
        for g in self.grids:
            gid = get_id_val(g.Id)
            if self.preselected_ids:
                self.checked_map[gid] = gid in self.preselected_ids
            else:
                self.checked_map[gid] = True

        self._refresh_table()
        self.dg_grids.ItemsSource = self.dt.DefaultView
        self.ms_ctrl = MultiSelectGridController(self.dg_grids, self.dt, self.lbl_sel_hint)

        self._bind_events()
        self._update_card_styles()

        if self.preselected_ids:
            self._set_status(u"Pre-selected {} Grid(s) from model selection.".format(len(self.preselected_ids)))
        else:
            self._set_status(u"Ready. Choose a mode and click OK or Apply.")

    def show_dialog(self):
        self.win.ShowDialog()

    def _set_status(self, text):
        self.lbl_status.Text = to_text(text)

    def _get_selected_mode(self):
        if bool(self.rb_reset2d.IsChecked):
            return "reset_2d"
        if bool(self.rb_to3d.IsChecked):
            return "to_3d"
        return "safe"

    def _update_card_styles(self):
        mode = self._get_selected_mode()
        if mode == "safe":
            self.card_safe.Background = BRUSH_CARD_ACTIVE_BG
            self.card_safe.BorderBrush = BRUSH_CARD_ACTIVE_BDR
            self.card_safe.BorderThickness = System.Windows.Thickness(1.5)
        else:
            self.card_safe.Background = BRUSH_CARD_IDLE_BG
            self.card_safe.BorderBrush = BRUSH_CARD_IDLE_BDR
            self.card_safe.BorderThickness = System.Windows.Thickness(1)

        if mode == "reset_2d":
            self.card_reset2d.Background = BRUSH_CARD_WARN_BG
            self.card_reset2d.BorderBrush = BRUSH_CARD_WARN_BDR
            self.card_reset2d.BorderThickness = System.Windows.Thickness(1.5)
        else:
            self.card_reset2d.Background = BRUSH_CARD_IDLE_BG
            self.card_reset2d.BorderBrush = BRUSH_CARD_IDLE_BDR
            self.card_reset2d.BorderThickness = System.Windows.Thickness(1)

        if mode == "to_3d":
            self.card_to3d.Background = BRUSH_CARD_ACTIVE_BG
            self.card_to3d.BorderBrush = BRUSH_CARD_ACTIVE_BDR
            self.card_to3d.BorderThickness = System.Windows.Thickness(1.5)
        else:
            self.card_to3d.Background = BRUSH_CARD_IDLE_BG
            self.card_to3d.BorderBrush = BRUSH_CARD_IDLE_BDR
            self.card_to3d.BorderThickness = System.Windows.Thickness(1)

    def _sync_checks_from_dt(self):
        for row in self.dt.Rows:
            g = self.grids[int(row["GridIndex"])]
            self.checked_map[get_id_val(g.Id)] = bool(row["IsChecked"])

    def _refresh_table(self):
        self.dt.Rows.Clear()
        q = to_text(self.txt_search.Text).strip().lower() if self.txt_search else u""

        cnt_3d_ends = 0
        cnt_2d_ends = 0
        cnt_locked = 0

        for idx, g in enumerate(self.grids):
            sb_name = get_scope_box_name(self.doc, g)
            locked = sb_name is not None
            if locked:
                cnt_locked += 1

            e0 = g.GetDatumExtentTypeInView(DB.DatumEnds.End0, self.view)
            e1 = g.GetDatumExtentTypeInView(DB.DatumEnds.End1, self.view)

            if e0 == DB.DatumExtentType.Model:
                cnt_3d_ends += 1
            else:
                cnt_2d_ends += 1
            if e1 == DB.DatumExtentType.Model:
                cnt_3d_ends += 1
            else:
                cnt_2d_ends += 1

            gname = to_text(g.Name)
            if q and q not in gname.lower():
                continue

            row = self.dt.NewRow()
            gid = get_id_val(g.Id)
            row["IsLocked"] = locked
            row["IsEditable"] = not locked
            row["IsChecked"] = False if locked else bool(self.checked_map.get(gid, True))
            row["GridName"] = gname

            if e0 == DB.DatumExtentType.ViewSpecific:
                row["End0Text"], row["End0Fg"], row["End0Bg"] = u"2D (View)", BRUSH_2D_TEXT, BRUSH_2D_BG
            else:
                row["End0Text"], row["End0Fg"], row["End0Bg"] = u"3D (Model)", BRUSH_3D_TEXT, BRUSH_3D_BG

            if e1 == DB.DatumExtentType.ViewSpecific:
                row["End1Text"], row["End1Fg"], row["End1Bg"] = u"2D (View)", BRUSH_2D_TEXT, BRUSH_2D_BG
            else:
                row["End1Text"], row["End1Fg"], row["End1Bg"] = u"3D (Model)", BRUSH_3D_TEXT, BRUSH_3D_BG

            has_ldr0 = get_leader_safe(g, DB.DatumEnds.End0, self.view) is not None
            has_ldr1 = get_leader_safe(g, DB.DatumEnds.End1, self.view) is not None
            if has_ldr0 and has_ldr1:
                row["ElbowText"] = u"Both Ends"
            elif has_ldr0 or has_ldr1:
                row["ElbowText"] = u"1 End (Elbow)"
            else:
                row["ElbowText"] = u"-"

            if locked:
                row["NoteText"] = u"Locked by Scope Box: {}".format(sb_name)
                row["NoteFg"] = BRUSH_LOCK_TEXT
            elif e0 == DB.DatumExtentType.ViewSpecific and e1 == DB.DatumExtentType.ViewSpecific:
                row["NoteText"] = u"Already 2D (Protected in Safe Mode)"
                row["NoteFg"] = BRUSH_MUTED_TEXT
            else:
                row["NoteText"] = u"Ready"
                row["NoteFg"] = BRUSH_NORMAL_TEXT

            row["GridIndex"] = idx
            self.dt.Rows.Add(row)

        self.lbl_summary_counts.Text = u"Total: {} Grids  |  2D Ends: {}  |  3D Ends: {}  |  Scope Box: {}".format(
            len(self.grids), cnt_2d_ends, cnt_3d_ends, cnt_locked
        )

    def _bind_events(self):
        self.card_safe.MouseLeftButtonDown += lambda s, a: self._select_mode_radio(self.rb_safe)
        self.card_reset2d.MouseLeftButtonDown += lambda s, a: self._select_mode_radio(self.rb_reset2d)
        self.card_to3d.MouseLeftButtonDown += lambda s, a: self._select_mode_radio(self.rb_to3d)

        self.rb_safe.Checked += lambda s, a: self._update_card_styles()
        self.rb_reset2d.Checked += lambda s, a: self._update_card_styles()
        self.rb_to3d.Checked += lambda s, a: self._update_card_styles()

        self.txt_search.TextChanged += self._on_search_changed
        self.btn_chk_all.Click += self._on_check_all
        self.btn_chk_none.Click += self._on_check_none
        self.btn_chk_3d_only.Click += self._on_check_3d_only

        self.btn_apply.Click += self._on_apply
        self.btn_ok.Click += self._on_ok
        self.btn_cancel.Click += lambda s, a: self.win.Close()

    def _select_mode_radio(self, rb):
        rb.IsChecked = True
        self._update_card_styles()

    def _on_search_changed(self, sender, args):
        self._sync_checks_from_dt()
        self._refresh_table()

    def _on_check_all(self, sender, args):
        for row in self.dt.Rows:
            if not bool(row["IsLocked"]):
                row["IsChecked"] = True

    def _on_check_none(self, sender, args):
        for row in self.dt.Rows:
            row["IsChecked"] = False

    def _on_check_3d_only(self, sender, args):
        for row in self.dt.Rows:
            if bool(row["IsLocked"]):
                row["IsChecked"] = False
            else:
                g = self.grids[int(row["GridIndex"])]
                e0 = g.GetDatumExtentTypeInView(DB.DatumEnds.End0, self.view)
                e1 = g.GetDatumExtentTypeInView(DB.DatumEnds.End1, self.view)
                row["IsChecked"] = (e0 == DB.DatumExtentType.Model or e1 == DB.DatumExtentType.Model)

    def _execute(self):
        self._sync_checks_from_dt()
        target_grids = [
            g for g in self.grids
            if self.checked_map.get(get_id_val(g.Id), False) and get_scope_box_name(self.doc, g) is None
        ]

        if not target_grids:
            show_alert("Grids 2D Pro", "Please check at least one unlocked Grid in the table.")
            return False

        mode = self._get_selected_mode()
        total_changed = 0
        total_preserved = 0

        with revit.Transaction("Grids 2D Pro ({})".format(mode)):
            for g in target_grids:
                ch, pr = convert_single_grid(g, self.view, mode)
                total_changed += ch
                total_preserved += pr

        try:
            self.uidoc.RefreshActiveView()
        except Exception:
            pass

        self._refresh_table()

        if mode == "safe":
            self._set_status(
                u"Safe 2D Complete: {} end(s) converted to 2D, {} existing 2D end(s) kept untouched.".format(
                    total_changed, total_preserved
                )
            )
        elif mode == "reset_2d":
            self._set_status(u"Reset & Set 2D Complete: {} end(s) reset to 3D extent and set to 2D.".format(total_changed))
        else:
            self._set_status(u"Revert Complete: {} end(s) switched back to 3D Model extent.".format(total_changed))
        return True

    def _on_apply(self, sender, args):
        self._execute()

    def _on_ok(self, sender, args):
        if self._execute():
            self.win.Close()


# ------------------------------------------------------------------------------
# DIRECT EXECUTION ENTRY POINT
# ------------------------------------------------------------------------------
def run_grids_2d_pro():
    try:
        doc = revit.doc
        uidoc = revit.uidoc
        view = revit.active_view

        if not doc or not view:
            show_alert("Grids 2D Pro", "No active Revit view found.")
            return

        if view.IsTemplate or view.ViewType in (
            DB.ViewType.DrawingSheet,
            DB.ViewType.ProjectBrowser,
            DB.ViewType.SystemBrowser,
            DB.ViewType.Schedule
        ):
            show_alert("Grids 2D Pro", u"Active view '{}' does not support 2D Grid extents.".format(to_text(view.Name)))
            return

        grids = list(
            DB.FilteredElementCollector(doc, view.Id)
            .OfClass(DB.Grid)
            .WhereElementIsNotElementType()
            .ToElements()
        )

        if not grids:
            show_alert("Grids 2D Pro", u"No visible Grids found in active view '{}'.".format(to_text(view.Name)))
            return

        preselected_ids = set()
        try:
            for eid in uidoc.Selection.GetElementIds():
                elem = doc.GetElement(eid)
                if isinstance(elem, DB.Grid):
                    preselected_ids.add(get_id_val(eid))
        except Exception:
            pass

        dlg = Grids2DProWindow(doc, uidoc, view, grids, preselected_ids)
        dlg.show_dialog()
    except Exception:
        show_alert("Grids 2D Pro - Script Error", traceback.format_exc())


run_grids_2d_pro()