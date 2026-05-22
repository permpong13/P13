# -*- coding: utf-8 -*-
from __future__ import print_function

import codecs
import csv
import math
import os
import traceback

import clr

clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("System.Windows.Forms")

from Autodesk.Revit.DB import *  # noqa
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler
from pyrevit import forms, revit, script
from System.Collections.Generic import List
from System.Collections.ObjectModel import ObservableCollection
from System.Windows import RoutedEventHandler, TextDecorationCollection, TextDecorations, Visibility
from System.Windows.Controls import Button
from System.Windows.Controls.Primitives import ButtonBase
from System.Windows.Forms import DialogResult, SaveFileDialog
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media import Color, SolidColorBrush, VisualTreeHelper


__title__ = "MH Connection QA"
__doc__ = "Scan manhole conduit connections, preview changes, and commit connection depths without Dynamo."
__author__ = "OHM"


doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

CLR_OK = SolidColorBrush(Color.FromRgb(46, 125, 50))
CLR_CHANGED = SolidColorBrush(Color.FromRgb(230, 81, 0))
CLR_WARN = SolidColorBrush(Color.FromRgb(183, 28, 28))
CLR_MUTED = SolidColorBrush(Color.FromRgb(150, 150, 150))
OPEN_FORMS = []

XAML = r"""
<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Manhole QA" Height="720" Width="1260"
    WindowStartupLocation="CenterScreen"
    Background="#F5F5F5" FontFamily="Segoe UI" FontSize="13">

    <Window.Resources>
        <Style TargetType="Button">
            <Setter Property="Height" Value="30"/>
            <Setter Property="Padding" Value="14,0"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="BorderBrush" Value="#CCCCCC"/>
            <Setter Property="Background" Value="White"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Background="{TemplateBinding Background}"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="{TemplateBinding BorderThickness}"
                                CornerRadius="4" Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter Property="Background" Value="#F0F0F0"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
    </Window.Resources>

    <DockPanel Margin="16">
        <StackPanel DockPanel.Dock="Top" Orientation="Horizontal" Margin="0,0,0,12" Height="36">
            <TextBlock Text="Workset" VerticalAlignment="Center" Margin="0,0,6,0" Foreground="#666"/>
            <ComboBox x:Name="CbWorkset" Width="170" Height="30" VerticalContentAlignment="Center"/>

            <TextBlock Text="Status" VerticalAlignment="Center" Margin="12,0,6,0" Foreground="#666"/>
            <ComboBox x:Name="CbStatus" Width="150" Height="30" VerticalContentAlignment="Center">
                <ComboBoxItem Content="All" IsSelected="True"/>
                <ComboBoxItem Content="Changed"/>
                <ComboBoxItem Content="Review"/>
                <ComboBoxItem Content="Unchanged"/>
            </ComboBox>

            <TextBlock Text="Search" VerticalAlignment="Center" Margin="12,0,6,0" Foreground="#666"/>
            <TextBox x:Name="TxtSearch" Width="170" Height="30" VerticalContentAlignment="Center"/>

            <Button x:Name="BtnScan" Content="Scan View" Margin="12,0,0,0" Width="110"/>
            <CheckBox x:Name="ChkDryRun" Content="Preview only" IsChecked="True"
                      VerticalAlignment="Center" Margin="20,0,0,0" Foreground="#444"/>
            <Button x:Name="BtnCommit" Content="Commit Selected" Margin="10,0,0,0" Width="130"
                    Background="#FFEBEE" BorderBrush="#EF9A9A"/>
            <Button x:Name="BtnSelect" Content="Select" Margin="8,0,0,0" Width="82"/>
            <Button x:Name="BtnIsolate" Content="Isolate" Margin="8,0,0,0" Width="82"/>
            <Button x:Name="BtnExport" Content="Export CSV" Margin="8,0,0,0" Width="100"/>
        </StackPanel>

        <Grid DockPanel.Dock="Top" Margin="0,0,0,12">
            <Grid.ColumnDefinitions>
                <ColumnDefinition/><ColumnDefinition/><ColumnDefinition/><ColumnDefinition/>
            </Grid.ColumnDefinitions>
            <Border Grid.Column="0" Background="White" BorderBrush="#E0E0E0"
                    BorderThickness="1" CornerRadius="6" Padding="12,8" Margin="0,0,8,0">
                <StackPanel>
                    <TextBlock Text="Total Manholes" FontSize="11" Foreground="#888"/>
                    <TextBlock x:Name="StatTotal" Text="-" FontSize="22" FontWeight="Medium"/>
                </StackPanel>
            </Border>
            <Border Grid.Column="1" Background="White" BorderBrush="#E0E0E0"
                    BorderThickness="1" CornerRadius="6" Padding="12,8" Margin="0,0,8,0">
                <StackPanel>
                    <TextBlock Text="Unchanged" FontSize="11" Foreground="#888"/>
                    <TextBlock x:Name="StatOk" Text="-" FontSize="22" FontWeight="Medium" Foreground="#2E7D32"/>
                </StackPanel>
            </Border>
            <Border Grid.Column="2" Background="White" BorderBrush="#E0E0E0"
                    BorderThickness="1" CornerRadius="6" Padding="12,8" Margin="0,0,8,0">
                <StackPanel>
                    <TextBlock Text="Changed" FontSize="11" Foreground="#888"/>
                    <TextBlock x:Name="StatChanged" Text="-" FontSize="22" FontWeight="Medium" Foreground="#E65100"/>
                </StackPanel>
            </Border>
            <Border Grid.Column="3" Background="White" BorderBrush="#E0E0E0"
                    BorderThickness="1" CornerRadius="6" Padding="12,8">
                <StackPanel>
                    <TextBlock Text="Review" FontSize="11" Foreground="#888"/>
                    <TextBlock x:Name="StatWarn" Text="-" FontSize="22" FontWeight="Medium" Foreground="#B71C1C"/>
                </StackPanel>
            </Border>
        </Grid>

        <Border DockPanel.Dock="Bottom" Background="White" BorderBrush="#E0E0E0"
                BorderThickness="0,1,0,0" Padding="0,8,0,0" Margin="0,8,0,0">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="220"/>
                </Grid.ColumnDefinitions>
                <Label Grid.Column="0" x:Name="LblStatus" Content="Click Scan View to start."
                       Foreground="#888" FontSize="12"/>
                <ProgressBar Grid.Column="1" x:Name="ScanProgress" Minimum="0" Maximum="100"
                             Height="14" Margin="0,0,16,8" Visibility="Hidden"
                             Foreground="#2E7D32"/>
            </Grid>
        </Border>

        <Grid>
            <Grid.RowDefinitions>
                <RowDefinition Height="*"/>
                <RowDefinition Height="Auto"/>
                <RowDefinition x:Name="DetailRow" Height="150"/>
            </Grid.RowDefinitions>

            <Border Grid.Row="0" Background="White" BorderBrush="#E0E0E0" BorderThickness="1" CornerRadius="6">
                <DataGrid x:Name="ListRecords"
                          AutoGenerateColumns="False"
                          CanUserAddRows="False"
                          CanUserDeleteRows="False"
                          CanUserResizeRows="False"
                          GridLinesVisibility="Horizontal"
                          HeadersVisibility="Column"
                          SelectionMode="Extended"
                          Background="White"
                          BorderThickness="0"
                          RowBackground="White"
                          AlternatingRowBackground="#FAFAFA"
                          HorizontalGridLinesBrush="#F0F0F0"
                          FontSize="12">
                    <DataGrid.Columns>
                        <DataGridTemplateColumn Header="" Width="32">
                            <DataGridTemplateColumn.CellTemplate>
                                <DataTemplate>
                                    <CheckBox IsChecked="{Binding checked, Mode=TwoWay, UpdateSourceTrigger=PropertyChanged}"
                                              HorizontalAlignment="Center"/>
                                </DataTemplate>
                            </DataGridTemplateColumn.CellTemplate>
                        </DataGridTemplateColumn>
                        <DataGridTextColumn Header="ID" Binding="{Binding id}" Width="82" IsReadOnly="True"/>
                        <DataGridTextColumn Header="CNT Number" Binding="{Binding cnt_number}" Width="115" IsReadOnly="True"/>
                        <DataGridTextColumn Header="CNT Zone" Binding="{Binding cnt_zone}" Width="105" IsReadOnly="True"/>
                        <DataGridTextColumn Header="Workset" Binding="{Binding ws}" Width="120" IsReadOnly="True"/>

                        <DataGridTemplateColumn Header="Status" Width="92">
                            <DataGridTemplateColumn.CellTemplate>
                                <DataTemplate>
                                    <Border CornerRadius="10" Padding="6,2" HorizontalAlignment="Center">
                                        <Border.Style>
                                            <Style TargetType="Border">
                                                <Style.Triggers>
                                                    <DataTrigger Binding="{Binding status}" Value="ok">
                                                        <Setter Property="Background" Value="#E8F5E9"/>
                                                    </DataTrigger>
                                                    <DataTrigger Binding="{Binding status}" Value="changed">
                                                        <Setter Property="Background" Value="#FFF3E0"/>
                                                    </DataTrigger>
                                                    <DataTrigger Binding="{Binding status}" Value="warn">
                                                        <Setter Property="Background" Value="#FFEBEE"/>
                                                    </DataTrigger>
                                                </Style.Triggers>
                                            </Style>
                                        </Border.Style>
                                        <TextBlock Text="{Binding status_label}" FontSize="11">
                                            <TextBlock.Style>
                                                <Style TargetType="TextBlock">
                                                    <Style.Triggers>
                                                        <DataTrigger Binding="{Binding status}" Value="ok">
                                                            <Setter Property="Foreground" Value="#2E7D32"/>
                                                        </DataTrigger>
                                                        <DataTrigger Binding="{Binding status}" Value="changed">
                                                            <Setter Property="Foreground" Value="#E65100"/>
                                                        </DataTrigger>
                                                        <DataTrigger Binding="{Binding status}" Value="warn">
                                                            <Setter Property="Foreground" Value="#B71C1C"/>
                                                        </DataTrigger>
                                                    </Style.Triggers>
                                                </Style>
                                            </TextBlock.Style>
                                        </TextBlock>
                                    </Border>
                                </DataTemplate>
                            </DataGridTemplateColumn.CellTemplate>
                        </DataGridTemplateColumn>

                        <DataGridTemplateColumn Header="C1 Main" Width="68"><DataGridTemplateColumn.CellTemplate><DataTemplate><TextBlock Text="{Binding c1m}" HorizontalAlignment="Center" Foreground="{Binding c1m_color}"/></DataTemplate></DataGridTemplateColumn.CellTemplate></DataGridTemplateColumn>
                        <DataGridTemplateColumn Header="C2 Main" Width="68"><DataGridTemplateColumn.CellTemplate><DataTemplate><TextBlock Text="{Binding c2m}" HorizontalAlignment="Center" Foreground="{Binding c2m_color}"/></DataTemplate></DataGridTemplateColumn.CellTemplate></DataGridTemplateColumn>
                        <DataGridTemplateColumn Header="C3 Main" Width="68"><DataGridTemplateColumn.CellTemplate><DataTemplate><TextBlock Text="{Binding c3m}" HorizontalAlignment="Center" Foreground="{Binding c3m_color}"/></DataTemplate></DataGridTemplateColumn.CellTemplate></DataGridTemplateColumn>
                        <DataGridTemplateColumn Header="C4 Main" Width="68"><DataGridTemplateColumn.CellTemplate><DataTemplate><TextBlock Text="{Binding c4m}" HorizontalAlignment="Center" Foreground="{Binding c4m_color}"/></DataTemplate></DataGridTemplateColumn.CellTemplate></DataGridTemplateColumn>
                        <DataGridTemplateColumn Header="E1 Extra" Width="68"><DataGridTemplateColumn.CellTemplate><DataTemplate><TextBlock Text="{Binding e1}" HorizontalAlignment="Center" Foreground="{Binding e1_color}"/></DataTemplate></DataGridTemplateColumn.CellTemplate></DataGridTemplateColumn>
                        <DataGridTemplateColumn Header="E2 Extra" Width="68"><DataGridTemplateColumn.CellTemplate><DataTemplate><TextBlock Text="{Binding e2}" HorizontalAlignment="Center" Foreground="{Binding e2_color}"/></DataTemplate></DataGridTemplateColumn.CellTemplate></DataGridTemplateColumn>
                        <DataGridTemplateColumn Header="E3 Extra" Width="68"><DataGridTemplateColumn.CellTemplate><DataTemplate><TextBlock Text="{Binding e3}" HorizontalAlignment="Center" Foreground="{Binding e3_color}"/></DataTemplate></DataGridTemplateColumn.CellTemplate></DataGridTemplateColumn>
                        <DataGridTemplateColumn Header="E4 Extra" Width="68"><DataGridTemplateColumn.CellTemplate><DataTemplate><TextBlock Text="{Binding e4}" HorizontalAlignment="Center" Foreground="{Binding e4_color}"/></DataTemplate></DataGridTemplateColumn.CellTemplate></DataGridTemplateColumn>
                        <DataGridTemplateColumn Header="" Width="66">
                            <DataGridTemplateColumn.CellTemplate>
                                <DataTemplate>
                                    <Button Content="Focus" Width="54" Height="24" Padding="4,0"/>
                                </DataTemplate>
                            </DataGridTemplateColumn.CellTemplate>
                        </DataGridTemplateColumn>
                    </DataGrid.Columns>
                </DataGrid>
            </Border>

            <GridSplitter Grid.Row="1" Height="6" HorizontalAlignment="Stretch"
                          Background="Transparent" Cursor="SizeNS"
                          ResizeDirection="Rows" ResizeBehavior="PreviousAndNext"/>

            <Border Grid.Row="2" Background="White" BorderBrush="#E0E0E0" BorderThickness="1"
                    CornerRadius="6" Padding="16">
                <Grid>
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="*"/>
                        <ColumnDefinition Width="*"/>
                    </Grid.ColumnDefinitions>
                    <StackPanel Grid.Column="0" Margin="0,0,16,0">
                        <TextBlock Text="MAIN CONNECTION" FontSize="11" Foreground="#888"
                                   FontWeight="Medium" Margin="0,0,0,8"/>
                        <ItemsControl x:Name="DetailMain">
                            <ItemsControl.ItemTemplate>
                                <DataTemplate>
                                    <Grid Margin="0,4">
                                        <Grid.ColumnDefinitions>
                                            <ColumnDefinition Width="130"/>
                                            <ColumnDefinition Width="80"/>
                                            <ColumnDefinition Width="25"/>
                                            <ColumnDefinition Width="80"/>
                                        </Grid.ColumnDefinitions>
                                        <TextBlock Grid.Column="0" Text="{Binding label}" Foreground="#666"/>
                                        <TextBlock Grid.Column="1" Text="{Binding old_val}" Foreground="#AAAAAA" TextDecorations="{Binding strike}"/>
                                        <TextBlock Grid.Column="2" Text="->" Foreground="#CCC" HorizontalAlignment="Center" Visibility="{Binding arrow_vis}"/>
                                        <TextBlock Grid.Column="3" Text="{Binding new_val}" Foreground="{Binding val_color}" FontWeight="{Binding val_weight}"/>
                                    </Grid>
                                </DataTemplate>
                            </ItemsControl.ItemTemplate>
                        </ItemsControl>
                    </StackPanel>
                    <StackPanel Grid.Column="1">
                        <TextBlock Text="EXTRA CONNECTION" FontSize="11" Foreground="#888"
                                   FontWeight="Medium" Margin="0,0,0,8"/>
                        <ItemsControl x:Name="DetailExtra">
                            <ItemsControl.ItemTemplate>
                                <DataTemplate>
                                    <Grid Margin="0,4">
                                        <Grid.ColumnDefinitions>
                                            <ColumnDefinition Width="130"/>
                                            <ColumnDefinition Width="80"/>
                                            <ColumnDefinition Width="25"/>
                                            <ColumnDefinition Width="80"/>
                                        </Grid.ColumnDefinitions>
                                        <TextBlock Grid.Column="0" Text="{Binding label}" Foreground="#666"/>
                                        <TextBlock Grid.Column="1" Text="{Binding old_val}" Foreground="#AAAAAA" TextDecorations="{Binding strike}"/>
                                        <TextBlock Grid.Column="2" Text="->" Foreground="#CCC" HorizontalAlignment="Center" Visibility="{Binding arrow_vis}"/>
                                        <TextBlock Grid.Column="3" Text="{Binding new_val}" Foreground="{Binding val_color}" FontWeight="{Binding val_weight}"/>
                                    </Grid>
                                </DataTemplate>
                            </ItemsControl.ItemTemplate>
                        </ItemsControl>
                    </StackPanel>
                </Grid>
            </Border>
        </Grid>
    </DockPanel>
</Window>
"""


def get_id_value(element_id):
    return getattr(element_id, "Value", getattr(element_id, "IntegerValue", str(element_id)))


def get_parameter_text(element, param_name):
    param = element.LookupParameter(param_name) if element else None
    if not param:
        return ""
    try:
        value = param.AsString()
        if value:
            return value
    except Exception:
        pass
    try:
        value = param.AsValueString()
        if value:
            return value
    except Exception:
        pass
    return ""


def get_workset_name(document, element):
    try:
        return document.GetWorksetTable().GetWorkset(element.WorksetId).Name
    except Exception:
        return "No Workset"


def mm_to_ft(value_mm):
    return float(value_mm) / 304.8


def ft_to_mm(value_ft):
    return int(round(float(value_ft) * 304.8))


def endpoint_in_bbox(point, min_point, max_point):
    return (
        min_point.X <= point.X <= max_point.X
        and min_point.Y <= point.Y <= max_point.Y
        and min_point.Z <= point.Z <= max_point.Z
    )


def get_floor_z(manhole, origin):
    try:
        options = Options()
        options.ComputeReferences = True
        options.DetailLevel = ViewDetailLevel.Fine
        geometry = manhole.get_Geometry(options)
        floor_candidates = {}

        def scan_geometry(geometry_items):
            for obj in geometry_items:
                if isinstance(obj, Solid) and obj.Volume > 0:
                    for face in obj.Faces:
                        normal = face.ComputeNormal(UV(0.5, 0.5))
                        if normal.IsAlmostEqualTo(XYZ.BasisZ):
                            face_z = face.Evaluate(UV(0.5, 0.5)).Z
                            if face_z < (origin.Z - 0.5):
                                key = round(face_z, 4)
                                floor_candidates[key] = floor_candidates.get(key, 0) + face.Area
                elif isinstance(obj, GeometryInstance):
                    scan_geometry(obj.GetInstanceGeometry())

        scan_geometry(geometry)
        if floor_candidates:
            return max(floor_candidates, key=floor_candidates.get)
    except Exception:
        pass

    bbox = manhole.get_BoundingBox(None)
    return bbox.Min.Z if bbox else origin.Z


def get_location_point(element):
    location = getattr(element, "Location", None)
    if not location:
        return None
    if hasattr(location, "Point"):
        return location.Point
    if hasattr(location, "Curve") and location.Curve:
        return location.Curve.Evaluate(0.5, True)
    return None


def get_side_from_local_point(local_point):
    angle_deg = math.degrees(math.atan2(local_point.Y, local_point.X))
    if angle_deg >= 135 or angle_deg <= -135:
        return 0
    if -135 < angle_deg <= -45:
        return 1
    if -45 < angle_deg <= 45:
        return 2
    return 3


def read_connection_mm(manhole, param_name):
    param = manhole.LookupParameter(param_name)
    if not param or not param.HasValue:
        return 0
    try:
        return ft_to_mm(param.AsDouble())
    except Exception:
        try:
            return int(round(float(param.AsValueString())))
        except Exception:
            return 0


def scan_manholes(document, active_view_id, progress_callback=None):
    try:
        view_equipments = (
            FilteredElementCollector(document, active_view_id)
            .OfCategory(BuiltInCategory.OST_ElectricalEquipment)
            .WhereElementIsNotElementType()
            .ToElements()
        )
        view_conduits = (
            FilteredElementCollector(document, active_view_id)
            .OfCategory(BuiltInCategory.OST_Conduit)
            .WhereElementIsNotElementType()
            .ToElements()
        )
        view_fittings = (
            FilteredElementCollector(document, active_view_id)
            .OfCategory(BuiltInCategory.OST_ConduitFitting)
            .WhereElementIsNotElementType()
            .ToElements()
        )
    except Exception as exc:
        raise Exception("Unable to collect elements in the active view: {}".format(exc))

    valid_manholes = [
        item
        for item in view_equipments
        if item.LookupParameter("CNT_Connection 1") and item.Location is not None
    ]

    total_manholes = len(valid_manholes)
    results = []

    for index, manhole in enumerate(valid_manholes):
        try:
            transform = manhole.GetTransform()
            origin = transform.Origin
            bbox = manhole.get_BoundingBox(None)
            base_z = get_floor_z(manhole, origin)

            main_depths = [[], [], [], []]
            extra_depths = [[], [], [], []]
            has_fitting = [False, False, False, False]

            if bbox:
                buffer_ft = mm_to_ft(1.0)
                limit_min = XYZ(bbox.Min.X - buffer_ft, bbox.Min.Y - buffer_ft, bbox.Min.Z - buffer_ft)
                limit_max = XYZ(bbox.Max.X + buffer_ft, bbox.Max.Y + buffer_ft, bbox.Max.Z + buffer_ft)
            else:
                limit_min = limit_max = None

            for conduit in view_conduits:
                if not hasattr(conduit.Location, "Curve"):
                    continue
                curve = conduit.Location.Curve
                point_0 = curve.GetEndPoint(0)
                point_1 = curve.GetEndPoint(1)

                selected_point = None
                if limit_min and limit_max:
                    in_0 = endpoint_in_bbox(point_0, limit_min, limit_max)
                    in_1 = endpoint_in_bbox(point_1, limit_min, limit_max)
                    if in_0 or in_1:
                        selected_point = point_0 if in_0 else point_1

                if not selected_point:
                    dist_0 = point_0.DistanceTo(origin)
                    dist_1 = point_1.DistanceTo(origin)
                    if min(dist_0, dist_1) > 10.0:
                        continue
                    selected_point = point_0 if dist_0 < dist_1 else point_1

                local_point = transform.Inverse.OfPoint(selected_point)
                side = get_side_from_local_point(local_point)

                conduit_type = document.GetElement(conduit.GetTypeId())
                type_name = ""
                if conduit_type:
                    type_param = conduit_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
                    type_name = type_param.AsString().lower() if type_param else ""
                conduit_name = conduit.Name.lower() if conduit.Name else ""
                is_extra = "without duct" in type_name or "without duct" in conduit_name

                depth = selected_point.Z - base_z
                if is_extra:
                    extra_depths[side].append(depth)
                else:
                    main_depths[side].append(depth)

            for fitting in view_fittings:
                fitting_point = get_location_point(fitting)
                if not fitting_point or fitting_point.DistanceTo(origin) > 10.0:
                    continue
                local_point = transform.Inverse.OfPoint(fitting_point)
                has_fitting[get_side_from_local_point(local_point)] = True

            def get_new_value(depths, side_has_fitting):
                if depths:
                    return ft_to_mm(max(0.0, min(depths)))
                return None if side_has_fitting else 0

            new_main = [get_new_value(main_depths[i], has_fitting[i]) for i in range(4)]
            new_extra = [get_new_value(extra_depths[i], has_fitting[i]) for i in range(4)]
            old_main = [read_connection_mm(manhole, "CNT_Connection {}".format(i)) for i in range(1, 5)]
            old_extra = [read_connection_mm(manhole, "CNT_Connection {} Extra".format(i)) for i in range(1, 5)]

            final_main = [new_main[i] if new_main[i] is not None else old_main[i] for i in range(4)]
            final_extra = [new_extra[i] if new_extra[i] is not None else old_extra[i] for i in range(4)]

            has_change = old_main != final_main or old_extra != final_extra
            has_warn = any(final_main[i] == 0 and old_main[i] > 0 for i in range(4))
            status = "warn" if has_warn else "changed" if has_change else "ok"

            results.append(
                {
                    "id": str(get_id_value(manhole.Id)),
                    "element": manhole,
                    "cnt_number": get_parameter_text(manhole, "CNT_Number"),
                    "cnt_zone": get_parameter_text(manhole, "CNT_Zone"),
                    "ws": get_workset_name(document, manhole),
                    "status": status,
                    "old_main": old_main,
                    "new_main": final_main,
                    "old_extra": old_extra,
                    "new_extra": final_extra,
                }
            )
        except Exception as exc:
            output.print_md("Skipped manhole `{}`: `{}`".format(get_id_value(manhole.Id), exc))

        if progress_callback:
            progress_callback(index + 1, total_manholes)

    return results


def commit_manholes(document, records):
    tx = Transaction(document, "Commit Manhole QA Connections")
    tx.Start()
    try:
        for record in records:
            manhole = record["element"]
            for index in range(4):
                for key, suffix in (("main", ""), ("extra", " Extra")):
                    param = manhole.LookupParameter("CNT_Connection {}{}".format(index + 1, suffix))
                    if not param or param.IsReadOnly:
                        continue
                    value_ft = mm_to_ft(record["new_{}".format(key)][index])
                    if abs(param.AsDouble() - value_ft) > 0.001:
                        param.Set(value_ft)
        tx.Commit()
    except Exception:
        if tx.HasStarted() and not tx.HasEnded():
            tx.RollBack()
        raise


class ManholeRow(object):
    def __init__(self, record):
        self._record = record
        self._checked = False

    @property
    def checked(self):
        return self._checked

    @checked.setter
    def checked(self, value):
        self._checked = value

    @property
    def id(self):
        return self._record["id"]

    @property
    def cnt_number(self):
        return self._record["cnt_number"]

    @property
    def cnt_zone(self):
        return self._record["cnt_zone"]

    @property
    def ws(self):
        return self._record["ws"]

    @property
    def status(self):
        return self._record["status"]

    @property
    def status_label(self):
        return {"ok": "Unchanged", "changed": "Changed", "warn": "Review"}.get(self._record["status"], "?")

    @property
    def element(self):
        return self._record["element"]

    def _value_text(self, value):
        return str(value) if value else "-"

    def _value_color(self, new_value, old_value):
        if new_value == 0 and old_value > 0:
            return CLR_WARN
        if new_value != old_value:
            return CLR_CHANGED
        if new_value == 0:
            return CLR_MUTED
        return CLR_OK

    @property
    def c1m(self):
        return self._value_text(self._record["new_main"][0])

    @property
    def c2m(self):
        return self._value_text(self._record["new_main"][1])

    @property
    def c3m(self):
        return self._value_text(self._record["new_main"][2])

    @property
    def c4m(self):
        return self._value_text(self._record["new_main"][3])

    @property
    def c1m_color(self):
        return self._value_color(self._record["new_main"][0], self._record["old_main"][0])

    @property
    def c2m_color(self):
        return self._value_color(self._record["new_main"][1], self._record["old_main"][1])

    @property
    def c3m_color(self):
        return self._value_color(self._record["new_main"][2], self._record["old_main"][2])

    @property
    def c4m_color(self):
        return self._value_color(self._record["new_main"][3], self._record["old_main"][3])

    @property
    def e1(self):
        return self._value_text(self._record["new_extra"][0])

    @property
    def e2(self):
        return self._value_text(self._record["new_extra"][1])

    @property
    def e3(self):
        return self._value_text(self._record["new_extra"][2])

    @property
    def e4(self):
        return self._value_text(self._record["new_extra"][3])

    @property
    def e1_color(self):
        return self._value_color(self._record["new_extra"][0], self._record["old_extra"][0])

    @property
    def e2_color(self):
        return self._value_color(self._record["new_extra"][1], self._record["old_extra"][1])

    @property
    def e3_color(self):
        return self._value_color(self._record["new_extra"][2], self._record["old_extra"][2])

    @property
    def e4_color(self):
        return self._value_color(self._record["new_extra"][3], self._record["old_extra"][3])


class DetailRow(object):
    def __init__(self, label, old_value, new_value):
        self.label = label
        self.old_val = "{} mm".format(old_value) if old_value is not None else "-"
        self.new_val = "{} mm".format(new_value) if new_value is not None else "-"
        changed = old_value != new_value
        self.val_color = CLR_WARN if new_value == 0 and old_value > 0 else CLR_CHANGED if changed else CLR_OK
        self.val_weight = "SemiBold" if changed else "Normal"
        self.strike = TextDecorations.Strikethrough if changed else TextDecorationCollection()
        self.arrow_vis = Visibility.Visible if changed else Visibility.Collapsed


class RevitActionHandler(IExternalEventHandler):
    def __init__(self):
        self.action = None
        self.owner = None

    def Execute(self, ui_application):
        try:
            if self.action:
                self.action(ui_application)
        except Exception:
            forms.alert(traceback.format_exc(), title="Manhole QA")
        finally:
            self.action = None
            if self.owner:
                self.owner.set_busy(False)

    def GetName(self):
        return "Manhole QA Revit Action"


class ManholeQAForm(object):
    def __init__(self, document, ui_document):
        self.doc = document
        self.uidoc = ui_document
        self.records = []
        self.rows = ObservableCollection[ManholeRow]()
        self.window = XamlReader.Parse(XAML)
        self.revit_handler = RevitActionHandler()
        self.revit_handler.owner = self
        self.revit_event = ExternalEvent.Create(self.revit_handler)

        self.grid = self.window.FindName("ListRecords")
        self.btn_scan = self.window.FindName("BtnScan")
        self.btn_commit = self.window.FindName("BtnCommit")
        self.btn_export = self.window.FindName("BtnExport")
        self.btn_select = self.window.FindName("BtnSelect")
        self.btn_isolate = self.window.FindName("BtnIsolate")
        self.cb_dry = self.window.FindName("ChkDryRun")
        self.cb_ws = self.window.FindName("CbWorkset")
        self.cb_status = self.window.FindName("CbStatus")
        self.txt_search = self.window.FindName("TxtSearch")
        self.lbl_status = self.window.FindName("LblStatus")
        self.pb = self.window.FindName("ScanProgress")
        self.stat_total = self.window.FindName("StatTotal")
        self.stat_ok = self.window.FindName("StatOk")
        self.stat_changed = self.window.FindName("StatChanged")
        self.stat_warn = self.window.FindName("StatWarn")
        self.det_main = self.window.FindName("DetailMain")
        self.det_extra = self.window.FindName("DetailExtra")
        self.grid.ItemsSource = self.rows

        self.btn_scan.Click += self.on_scan
        self.btn_commit.Click += self.on_commit
        self.btn_export.Click += self.on_export
        self.btn_select.Click += self.on_select_elements
        self.btn_isolate.Click += self.on_isolate_elements
        self.cb_status.SelectionChanged += self.on_filter
        self.cb_ws.SelectionChanged += self.on_filter
        self.txt_search.TextChanged += self.on_filter
        self.grid.SelectionChanged += self.on_select_row
        self.grid.AddHandler(ButtonBase.ClickEvent, RoutedEventHandler(self.on_grid_button_click))
        self.window.Closed += self.on_closed

        self.cb_ws.Items.Add("All")
        try:
            for workset in FilteredWorksetCollector(document).OfKind(WorksetKind.UserWorkset):
                self.cb_ws.Items.Add(workset.Name)
        except Exception:
            pass
        self.cb_ws.SelectedIndex = 0

        try:
            WindowInteropHelper(self.window).Owner = ui_document.Application.MainWindowHandle
        except Exception:
            pass

    def show(self):
        self.window.Show()

    def on_closed(self, sender, args):
        try:
            self.revit_event.Dispose()
        except Exception:
            pass
        if self in OPEN_FORMS:
            OPEN_FORMS.remove(self)

    def set_busy(self, is_busy):
        try:
            self.btn_scan.IsEnabled = not is_busy
            self.btn_commit.IsEnabled = not is_busy
            self.btn_select.IsEnabled = not is_busy
            self.btn_isolate.IsEnabled = not is_busy
            self.pb.Visibility = Visibility.Visible if is_busy else Visibility.Hidden
        except Exception:
            pass

    def _update_revit_context(self, ui_application):
        active_uidoc = ui_application.ActiveUIDocument
        if active_uidoc:
            self.uidoc = active_uidoc
            self.doc = active_uidoc.Document

    def _raise_revit_action(self, action, status_text):
        if self.revit_handler.action:
            forms.alert("Another Manhole QA action is still running.", title="Manhole QA")
            return
        self.revit_handler.action = action
        self.lbl_status.Content = status_text
        self.set_busy(True)
        self.revit_event.Raise()

    def on_scan(self, sender, args):
        self._raise_revit_action(self._scan_in_revit_context, "Scanning active view...")

    def _scan_in_revit_context(self, ui_application):
        try:
            self._update_revit_context(ui_application)
            self.pb.Visibility = Visibility.Visible
            self.pb.Value = 0
            self.lbl_status.Content = "Scanning active view..."

            def update_progress(current, total):
                value = (float(current) / total) * 100 if total else 0
                self.pb.Value = value
                self.lbl_status.Content = "Scanning {}/{}...".format(current, total)

            self.records = scan_manholes(self.doc, self.doc.ActiveView.Id, update_progress)
            if not self.records:
                forms.alert("No valid manholes were found in the active view.", title="Manhole QA")
            self.cb_status.SelectedIndex = 0
            self._refresh_rows()
        except Exception:
            forms.alert(traceback.format_exc(), title="Scan Error")
        finally:
            self.pb.Visibility = Visibility.Hidden

    def _selected_status_filter(self):
        item = self.cb_status.SelectedItem
        if hasattr(item, "Content"):
            label = str(item.Content).strip()
            return {"Changed": "changed", "Review": "warn", "Unchanged": "ok"}.get(label)
        return None

    def _selected_workset_filter(self):
        item = self.cb_ws.SelectedItem
        return str(item).strip() if item else "All"

    def _search_filter(self):
        try:
            return str(self.txt_search.Text).strip().lower()
        except Exception:
            return ""

    def _record_matches_search(self, record, search_text):
        if not search_text:
            return True
        values = [
            record.get("id", ""),
            record.get("cnt_number", ""),
            record.get("cnt_zone", ""),
            record.get("ws", ""),
            record.get("status", ""),
        ]
        return search_text in " ".join([str(value).lower() for value in values])

    def _refresh_rows(self):
        selected_status = self._selected_status_filter()
        selected_workset = self._selected_workset_filter()
        search_text = self._search_filter()

        self.rows.Clear()
        filtered = []
        for record in self.records:
            if selected_status and record["status"] != selected_status:
                continue
            if selected_workset != "All" and record["ws"] != selected_workset:
                continue
            if not self._record_matches_search(record, search_text):
                continue
            filtered.append(record)
            self.rows.Add(ManholeRow(record))

        ok_count = sum(1 for item in filtered if item["status"] == "ok")
        changed_count = sum(1 for item in filtered if item["status"] == "changed")
        warn_count = sum(1 for item in filtered if item["status"] == "warn")
        self.stat_total.Text = str(len(filtered))
        self.stat_ok.Text = str(ok_count)
        self.stat_changed.Text = str(changed_count)
        self.stat_warn.Text = str(warn_count)
        self.lbl_status.Content = "Total {} | Unchanged {} | Changed {} | Review {}".format(
            len(filtered), ok_count, changed_count, warn_count
        )

    def on_filter(self, sender, args):
        if self.records:
            self._refresh_rows()

    def on_select_row(self, sender, args):
        try:
            row = self.grid.SelectedItem
            if not isinstance(row, ManholeRow):
                return
            record = row._record
            self.det_main.ItemsSource = [
                DetailRow("Connection {}".format(i + 1), record["old_main"][i], record["new_main"][i])
                for i in range(4)
            ]
            self.det_extra.ItemsSource = [
                DetailRow("Connection {} Extra".format(i + 1), record["old_extra"][i], record["new_extra"][i])
                for i in range(4)
            ]
        except Exception:
            pass

    def on_grid_button_click(self, sender, args):
        button = self._find_button(args.OriginalSource)
        if not button or str(button.Content) != "Focus":
            return
        row = button.DataContext
        if isinstance(row, ManholeRow):
            self.focus_rows([row])
            args.Handled = True

    def _find_button(self, source):
        current = source
        while current:
            if isinstance(current, Button):
                return current
            try:
                current = VisualTreeHelper.GetParent(current)
            except Exception:
                return None
        return None

    def _checked_records(self):
        return [row._record for row in self.rows if row.checked]

    def _selected_or_checked_rows(self):
        rows = []
        for item in self.grid.SelectedItems:
            if isinstance(item, ManholeRow):
                rows.append(item)
        if rows:
            return rows
        return [row for row in self.rows if row.checked]

    def on_select_elements(self, sender, args):
        rows = self._selected_or_checked_rows()
        if not rows:
            forms.alert("Select or check at least one manhole row.", title="Manhole QA")
            return
        self._raise_revit_action(lambda uiapp: self._select_rows_in_revit_context(uiapp, rows), "Selecting manholes...")

    def _select_rows_in_revit_context(self, ui_application, rows):
        self._update_revit_context(ui_application)
        element_ids = List[ElementId]([row.element.Id for row in rows])
        self.uidoc.Selection.SetElementIds(element_ids)
        self.lbl_status.Content = "Selected {} manhole(s).".format(len(rows))

    def focus_rows(self, rows):
        self._raise_revit_action(lambda uiapp: self._focus_rows_in_revit_context(uiapp, rows), "Focusing manhole...")

    def _focus_rows_in_revit_context(self, ui_application, rows):
        self._select_rows_in_revit_context(ui_application, rows)
        element_ids = List[ElementId]([row.element.Id for row in rows])
        try:
            self.uidoc.ShowElements(element_ids)
        except Exception:
            self.uidoc.ShowElements(element_ids[0])
        self.lbl_status.Content = "Focused {} manhole(s).".format(len(rows))

    def on_isolate_elements(self, sender, args):
        rows = self._selected_or_checked_rows()
        if not rows:
            forms.alert("Select or check at least one manhole row.", title="Manhole QA")
            return
        self._raise_revit_action(lambda uiapp: self._isolate_rows_in_revit_context(uiapp, rows), "Isolating manholes...")

    def _isolate_rows_in_revit_context(self, ui_application, rows):
        self._update_revit_context(ui_application)
        element_ids = List[ElementId]([row.element.Id for row in rows])
        tx = Transaction(self.doc, "Isolate Manholes")
        tx.Start()
        try:
            self.doc.ActiveView.IsolateElementsTemporary(element_ids)
            tx.Commit()
        except Exception:
            if tx.HasStarted() and not tx.HasEnded():
                tx.RollBack()
            raise
        self.uidoc.Selection.SetElementIds(element_ids)
        self.lbl_status.Content = "Isolated {} manhole(s).".format(len(rows))

    def on_commit(self, sender, args):
        if self.cb_dry.IsChecked:
            forms.alert("Preview only is enabled. Turn it off before committing.", title="Manhole QA")
            return

        records = self._checked_records()
        if not records:
            forms.alert("Check at least one manhole row before committing.", title="Manhole QA")
            return

        self._raise_revit_action(lambda uiapp: self._commit_in_revit_context(uiapp, records), "Committing selected manholes...")

    def _commit_in_revit_context(self, ui_application, records):
        try:
            self._update_revit_context(ui_application)
            commit_manholes(self.doc, records)
            forms.alert("Committed {} manhole(s).".format(len(records)), title="Manhole QA")
            self._scan_in_revit_context(ui_application)
        except Exception:
            forms.alert(traceback.format_exc(), title="Commit Error")

    def on_export(self, sender, args):
        dialog = SaveFileDialog()
        dialog.Filter = "CSV files (*.csv)|*.csv"
        dialog.FileName = "ManholeQA.csv"
        if dialog.ShowDialog() != DialogResult.OK:
            return

        headers = [
            "ID",
            "CNT_Number",
            "CNT_Zone",
            "Workset",
            "Status",
            "C1_old",
            "C2_old",
            "C3_old",
            "C4_old",
            "C1_new",
            "C2_new",
            "C3_new",
            "C4_new",
            "E1_old",
            "E2_old",
            "E3_old",
            "E4_old",
            "E1_new",
            "E2_new",
            "E3_new",
            "E4_new",
        ]

        with codecs.open(dialog.FileName, "w", "utf-8-sig") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(headers)
            for record in self.records:
                writer.writerow(
                    [
                        record["id"],
                        record["cnt_number"],
                        record["cnt_zone"],
                        record["ws"],
                        record["status"],
                    ]
                    + record["old_main"]
                    + record["new_main"]
                    + record["old_extra"]
                    + record["new_extra"]
                )

        forms.alert("Exported CSV:\n{}".format(dialog.FileName), title="Manhole QA")


def main():
    if not doc:
        forms.alert("No open Revit document found.", exitscript=True)

    output.print_md("# Manhole QA")
    output.print_md("This command now runs fully from `script.py` and does not call external Dynamo graphs.")
    form = ManholeQAForm(doc, uidoc)
    OPEN_FORMS.append(form)
    form.show()


if __name__ == "__main__":
    main()
