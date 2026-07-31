# -*- coding: utf-8 -*-
"""P13 View Template Manager Pro for Revit 2026."""
from __future__ import print_function, unicode_literals

import io
import os
import tempfile

import clr

clr.AddReference("RevitAPI")
clr.AddReference("System")
clr.AddReference("System.Windows.Forms")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

from Autodesk.Revit import DB
from System import DateTime
from System.Collections.Generic import List
from System.Windows import WindowState
from System.Windows.Controls import Button
from System.Windows.Input import Cursors, Key
from System.Windows.Media import VisualTreeHelper
from System.Windows.Forms import DialogResult, FolderBrowserDialog
from pyrevit import forms, revit, script


__title__ = "Template\nManager"
__author__ = "P13"

doc = revit.doc
app = __revit__.Application
output = script.get_output()
logger = script.get_logger()
config = script.get_config()

EXPORT_DIRECTORY_KEY = "template_manager_export_directory"

try:
    text_type = unicode
except NameError:
    text_type = str


XAML_UI = r"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="P13 Template Manager Pro"
        Height="800"
        Width="1180"
        MinHeight="620"
        MinWidth="960"
        WindowStartupLocation="CenterScreen"
        WindowStyle="None"
        ResizeMode="CanResizeWithGrip"
        PreviewKeyDown="window_key_down"
        Background="#0A101C">
    <Window.Resources>
        <SolidColorBrush x:Key="WindowBrush" Color="#0A101C"/>
        <SolidColorBrush x:Key="HeaderBrush" Color="#0E1727"/>
        <SolidColorBrush x:Key="SurfaceBrush" Color="#121D30"/>
        <SolidColorBrush x:Key="SurfaceAltBrush" Color="#16243A"/>
        <SolidColorBrush x:Key="HoverBrush" Color="#1D354E"/>
        <SolidColorBrush x:Key="BorderBrush" Color="#30455E"/>
        <SolidColorBrush x:Key="TextBrush" Color="#E8F0F8"/>
        <SolidColorBrush x:Key="MutedBrush" Color="#94A3B8"/>
        <SolidColorBrush x:Key="CyanBrush" Color="#20A4F3"/>
        <SolidColorBrush x:Key="CyanDarkBrush" Color="#0070AA"/>
        <SolidColorBrush x:Key="OrangeBrush" Color="#FF9F1C"/>

        <Style x:Key="BaseButton" TargetType="Button">
            <Setter Property="Height" Value="34"/>
            <Setter Property="Padding" Value="14,0"/>
            <Setter Property="Margin" Value="0,0,8,0"/>
            <Setter Property="Background" Value="{StaticResource SurfaceBrush}"/>
            <Setter Property="Foreground" Value="{StaticResource TextBrush}"/>
            <Setter Property="BorderBrush" Value="{StaticResource BorderBrush}"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="FontFamily" Value="Segoe UI"/>
            <Setter Property="FontSize" Value="12"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="ButtonBorder"
                                Background="{TemplateBinding Background}"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="{TemplateBinding BorderThickness}"
                                CornerRadius="5">
                            <ContentPresenter HorizontalAlignment="Center"
                                              VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="ButtonBorder" Property="Background" Value="{StaticResource HoverBrush}"/>
                                <Setter TargetName="ButtonBorder" Property="BorderBrush" Value="{StaticResource CyanBrush}"/>
                            </Trigger>
                            <Trigger Property="IsPressed" Value="True">
                                <Setter TargetName="ButtonBorder" Property="Background" Value="{StaticResource CyanDarkBrush}"/>
                            </Trigger>
                            <Trigger Property="IsEnabled" Value="False">
                                <Setter Property="Opacity" Value="0.45"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>

        <Style x:Key="PrimaryButton" TargetType="Button" BasedOn="{StaticResource BaseButton}">
            <Setter Property="Background" Value="{StaticResource CyanDarkBrush}"/>
            <Setter Property="BorderBrush" Value="{StaticResource CyanBrush}"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
        </Style>

        <Style x:Key="DangerButton" TargetType="Button" BasedOn="{StaticResource BaseButton}">
            <Setter Property="Background" Value="#371C27"/>
            <Setter Property="Foreground" Value="#FF8A91"/>
            <Setter Property="BorderBrush" Value="#7D3646"/>
        </Style>

        <Style x:Key="WindowButton" TargetType="Button" BasedOn="{StaticResource BaseButton}">
            <Setter Property="Width" Value="42"/>
            <Setter Property="Height" Value="28"/>
            <Setter Property="Padding" Value="0"/>
            <Setter Property="Margin" Value="0"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Background" Value="{StaticResource HeaderBrush}"/>
            <Setter Property="FontSize" Value="14"/>
        </Style>

        <Style TargetType="TextBox">
            <Setter Property="Height" Value="34"/>
            <Setter Property="Padding" Value="9,6"/>
            <Setter Property="Background" Value="{StaticResource SurfaceBrush}"/>
            <Setter Property="Foreground" Value="{StaticResource TextBrush}"/>
            <Setter Property="BorderBrush" Value="{StaticResource BorderBrush}"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="CaretBrush" Value="{StaticResource CyanBrush}"/>
            <Setter Property="FontFamily" Value="Segoe UI"/>
            <Setter Property="FontSize" Value="12"/>
        </Style>

        <Style TargetType="ComboBox">
            <Setter Property="Height" Value="34"/>
            <Setter Property="Padding" Value="8,4"/>
            <Setter Property="Background" Value="{StaticResource SurfaceBrush}"/>
            <Setter Property="Foreground" Value="{StaticResource TextBrush}"/>
            <Setter Property="BorderBrush" Value="{StaticResource BorderBrush}"/>
            <Setter Property="FontFamily" Value="Segoe UI"/>
            <Setter Property="FontSize" Value="12"/>
        </Style>

        <Style TargetType="ComboBoxItem">
            <Setter Property="Background" Value="{StaticResource SurfaceBrush}"/>
            <Setter Property="Foreground" Value="{StaticResource TextBrush}"/>
            <Setter Property="Padding" Value="8,5"/>
            <Style.Triggers>
                <Trigger Property="IsHighlighted" Value="True">
                    <Setter Property="Background" Value="{StaticResource HoverBrush}"/>
                </Trigger>
                <Trigger Property="IsSelected" Value="True">
                    <Setter Property="Background" Value="{StaticResource CyanDarkBrush}"/>
                    <Setter Property="Foreground" Value="White"/>
                </Trigger>
            </Style.Triggers>
        </Style>

        <Style TargetType="GridViewColumnHeader">
            <Setter Property="Height" Value="34"/>
            <Setter Property="Background" Value="{StaticResource HeaderBrush}"/>
            <Setter Property="Foreground" Value="{StaticResource TextBrush}"/>
            <Setter Property="BorderBrush" Value="{StaticResource BorderBrush}"/>
            <Setter Property="BorderThickness" Value="0,0,1,1"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="HorizontalContentAlignment" Value="Left"/>
            <Setter Property="Padding" Value="8,0"/>
        </Style>

        <Style TargetType="ListViewItem">
            <Setter Property="Height" Value="31"/>
            <Setter Property="Background" Value="{StaticResource SurfaceBrush}"/>
            <Setter Property="Foreground" Value="{StaticResource TextBrush}"/>
            <Setter Property="BorderBrush" Value="{StaticResource BorderBrush}"/>
            <Setter Property="BorderThickness" Value="0,0,0,1"/>
            <Setter Property="HorizontalContentAlignment" Value="Stretch"/>
            <Style.Triggers>
                <Trigger Property="IsMouseOver" Value="True">
                    <Setter Property="Background" Value="{StaticResource HoverBrush}"/>
                </Trigger>
                <Trigger Property="IsSelected" Value="True">
                    <Setter Property="Background" Value="#106896"/>
                    <Setter Property="Foreground" Value="White"/>
                </Trigger>
            </Style.Triggers>
        </Style>
    </Window.Resources>

    <Border BorderBrush="{StaticResource BorderBrush}" BorderThickness="1">
        <Grid Background="{StaticResource WindowBrush}">
            <Grid.RowDefinitions>
                <RowDefinition Height="54"/>
                <RowDefinition Height="82"/>
                <RowDefinition Height="54"/>
                <RowDefinition Height="*"/>
                <RowDefinition Height="126"/>
                <RowDefinition Height="28"/>
            </Grid.RowDefinitions>

            <Border Grid.Row="0"
                    Background="{StaticResource HeaderBrush}"
                    BorderBrush="{StaticResource BorderBrush}"
                    BorderThickness="0,0,0,1"
                    MouseLeftButtonDown="header_mouse_down">
                <Grid>
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="*"/>
                        <ColumnDefinition Width="Auto"/>
                    </Grid.ColumnDefinitions>
                    <StackPanel Margin="18,8,0,0">
                        <TextBlock Text="P13 Template Manager Pro"
                                   Foreground="{StaticResource TextBrush}"
                                   FontSize="15"
                                   FontWeight="SemiBold"/>
                        <TextBlock Text="Audit, manage, compare, apply, and exchange Revit view templates"
                                   Foreground="{StaticResource MutedBrush}"
                                   FontSize="10"
                                   Margin="0,2,0,0"/>
                    </StackPanel>
                    <StackPanel Grid.Column="1" Orientation="Horizontal" Margin="0,12,8,0">
                        <Button Tag="WindowControl" Content="—" Style="{StaticResource WindowButton}" Click="window_minimize"/>
                        <Button Tag="WindowControl" Content="□" Style="{StaticResource WindowButton}" Click="window_maximize"/>
                        <Button Tag="WindowControl" Content="×" Style="{StaticResource WindowButton}" Click="window_close"
                                Background="#371C27" Foreground="#FF8A91"/>
                    </StackPanel>
                </Grid>
            </Border>

            <Grid Grid.Row="1" Margin="16,12,16,10">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="12"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="12"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="12"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>

                <Border Grid.Column="0" Background="{StaticResource SurfaceBrush}" BorderBrush="{StaticResource BorderBrush}" BorderThickness="1" CornerRadius="7" Padding="13,9">
                    <StackPanel>
                        <TextBlock Text="TOTAL TEMPLATES" Foreground="{StaticResource MutedBrush}" FontSize="10"/>
                        <TextBlock x:Name="tb_total" Text="0" Foreground="{StaticResource TextBrush}" FontSize="24" FontWeight="SemiBold"/>
                    </StackPanel>
                </Border>
                <Border Grid.Column="2" Background="{StaticResource SurfaceBrush}" BorderBrush="{StaticResource BorderBrush}" BorderThickness="1" CornerRadius="7" Padding="13,9">
                    <StackPanel>
                        <TextBlock Text="IN USE" Foreground="{StaticResource MutedBrush}" FontSize="10"/>
                        <TextBlock x:Name="tb_used" Text="0" Foreground="{StaticResource CyanBrush}" FontSize="24" FontWeight="SemiBold"/>
                    </StackPanel>
                </Border>
                <Border Grid.Column="4" Background="{StaticResource SurfaceBrush}" BorderBrush="{StaticResource BorderBrush}" BorderThickness="1" CornerRadius="7" Padding="13,9">
                    <StackPanel>
                        <TextBlock Text="UNUSED" Foreground="{StaticResource MutedBrush}" FontSize="10"/>
                        <TextBlock x:Name="tb_unused" Text="0" Foreground="{StaticResource OrangeBrush}" FontSize="24" FontWeight="SemiBold"/>
                    </StackPanel>
                </Border>
                <Border Grid.Column="6" Background="{StaticResource SurfaceBrush}" BorderBrush="{StaticResource BorderBrush}" BorderThickness="1" CornerRadius="7" Padding="13,9">
                    <StackPanel>
                        <TextBlock Text="SELECTED" Foreground="{StaticResource MutedBrush}" FontSize="10"/>
                        <TextBlock x:Name="tb_selected" Text="0" Foreground="{StaticResource TextBrush}" FontSize="24" FontWeight="SemiBold"/>
                    </StackPanel>
                </Border>
            </Grid>

            <Grid Grid.Row="2" Margin="16,4,16,10">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="160"/>
                    <ColumnDefinition Width="190"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <TextBox x:Name="txt_search" Grid.Column="0" Margin="0,0,8,0"
                         ToolTip="Search template name, type, status, or element ID"
                         TextChanged="search_changed"/>
                <ComboBox x:Name="cb_status" Grid.Column="1" Margin="0,0,8,0" SelectionChanged="filter_changed">
                    <ComboBoxItem Content="All Status" IsSelected="True"/>
                    <ComboBoxItem Content="In Use"/>
                    <ComboBoxItem Content="Unused"/>
                </ComboBox>
                <ComboBox x:Name="cb_type" Grid.Column="2" Margin="0,0,8,0" SelectionChanged="filter_changed"/>
                <Button Grid.Column="3" Content="Select Visible" Style="{StaticResource BaseButton}" Click="select_visible"/>
                <Button Grid.Column="4" Content="Clear" Style="{StaticResource BaseButton}" Click="clear_selection"/>
                <Button Grid.Column="5" Content="Refresh" Style="{StaticResource PrimaryButton}" Click="refresh_clicked"/>
            </Grid>

            <ListView x:Name="lv_templates"
                      Grid.Row="3"
                      Margin="16,0,16,0"
                      SelectionMode="Extended"
                      Background="{StaticResource SurfaceBrush}"
                      Foreground="{StaticResource TextBrush}"
                      BorderBrush="{StaticResource BorderBrush}"
                      BorderThickness="1"
                      SelectionChanged="template_selection_changed">
                <ListView.View>
                    <GridView>
                        <GridViewColumn Header="Status" Width="90" DisplayMemberBinding="{Binding status}"/>
                        <GridViewColumn Header="View Type" Width="150" DisplayMemberBinding="{Binding type}"/>
                        <GridViewColumn Header="Views" Width="70" DisplayMemberBinding="{Binding count}"/>
                        <GridViewColumn Header="Controlled" Width="90" DisplayMemberBinding="{Binding controlled}"/>
                        <GridViewColumn Header="Template Name" Width="570" DisplayMemberBinding="{Binding name}"/>
                        <GridViewColumn Header="Element ID" Width="110" DisplayMemberBinding="{Binding id}"/>
                    </GridView>
                </ListView.View>
            </ListView>

            <Border Grid.Row="4" Margin="16,10,16,10" Padding="12,9"
                    Background="{StaticResource HeaderBrush}"
                    BorderBrush="{StaticResource BorderBrush}"
                    BorderThickness="1"
                    CornerRadius="7">
                <Grid>
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="10"/>
                        <RowDefinition Height="Auto"/>
                    </Grid.RowDefinitions>
                    <StackPanel Grid.Row="0" Orientation="Horizontal">
                        <TextBlock Text="BATCH" Width="76" Foreground="{StaticResource MutedBrush}" VerticalAlignment="Center" FontWeight="SemiBold"/>
                        <Button Content="Duplicate" Style="{StaticResource BaseButton}" Click="btn_duplicate"/>
                        <Button Content="Rename" Style="{StaticResource BaseButton}" Click="btn_rename"/>
                        <Button Content="Apply to Views" Style="{StaticResource PrimaryButton}" Click="btn_apply"/>
                        <Button Content="Include All Parameters" Style="{StaticResource BaseButton}" Click="btn_include_all"/>
                        <Button Content="Exclude All Parameters" Style="{StaticResource BaseButton}" Click="btn_exclude_all"/>
                        <Button Content="Delete Unused" Style="{StaticResource DangerButton}" Click="btn_delete"/>
                    </StackPanel>
                    <StackPanel Grid.Row="2" Orientation="Horizontal">
                        <TextBlock Text="AUDIT" Width="76" Foreground="{StaticResource MutedBrush}" VerticalAlignment="Center" FontWeight="SemiBold"/>
                        <Button Content="Show Linked Views" Style="{StaticResource BaseButton}" Click="btn_show"/>
                        <Button Content="Compare Settings" Style="{StaticResource BaseButton}" Click="btn_compare"/>
                        <Button Content="Import Templates" Style="{StaticResource BaseButton}" Click="btn_import"/>
                        <Button Content="Export CSV" Style="{StaticResource PrimaryButton}" Click="btn_export"/>
                    </StackPanel>
                </Grid>
            </Border>

            <Border Grid.Row="5" Background="{StaticResource HeaderBrush}" BorderBrush="{StaticResource BorderBrush}" BorderThickness="0,1,0,0">
                <Grid Margin="12,0">
                    <TextBlock x:Name="tb_status" Text="Ready" Foreground="{StaticResource MutedBrush}" VerticalAlignment="Center"/>
                </Grid>
            </Border>
        </Grid>
    </Border>
</Window>
"""


def element_id_value(element_id):
    """Return an ElementId integer across Revit API versions."""
    if hasattr(element_id, "Value"):
        return int(element_id.Value)
    return int(element_id.IntegerValue)


def parameter_text(parameter):
    """Return a stable display value for a Revit parameter."""
    if parameter is None or not parameter.HasValue:
        return ""
    try:
        value = parameter.AsValueString()
        if value:
            return value
    except Exception:
        pass
    try:
        value = parameter.AsString()
        if value:
            return value
    except Exception:
        pass
    try:
        storage = parameter.StorageType
        if storage == DB.StorageType.Integer:
            return text_type(parameter.AsInteger())
        if storage == DB.StorageType.Double:
            return text_type(parameter.AsDouble())
        if storage == DB.StorageType.ElementId:
            return text_type(element_id_value(parameter.AsElementId()))
    except Exception:
        pass
    return ""


def csv_field(value):
    """Return one RFC 4180-compatible CSV field."""
    value = "" if value is None else text_type(value)
    if '"' in value:
        value = value.replace('"', '""')
    if "," in value or '"' in value or "\n" in value or "\r" in value:
        return '"{}"'.format(value)
    return value


def template_type_name(template):
    """Return a concise non-localized view type label."""
    return text_type(template.ViewType).replace("ViewType.", "")


def get_template_data():
    """Collect templates and usage records without modifying the document."""
    templates = [
        view
        for view in DB.FilteredElementCollector(doc).OfClass(DB.View)
        if view.IsTemplate
    ]
    usage = {}
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if view.IsTemplate:
            continue
        try:
            template_id = view.ViewTemplateId
            value = element_id_value(template_id)
            if value > 0:
                usage.setdefault(value, []).append(view)
        except Exception:
            continue

    records = []
    for template in templates:
        template_id = element_id_value(template.Id)
        linked_views = sorted(
            usage.get(template_id, []),
            key=lambda item: (text_type(item.ViewType), item.Name.lower()),
        )
        controlled_count = 0
        try:
            all_ids = list(template.GetTemplateParameterIds())
            excluded = set(
                element_id_value(item)
                for item in template.GetNonControlledTemplateParameterIds()
            )
            controlled_count = len(
                [item for item in all_ids if element_id_value(item) not in excluded]
            )
        except Exception as error:
            logger.warning(
                "Could not read controlled parameters for template {}: {}".format(
                    template.Name, error
                )
            )
        records.append(
            {
                "element": template,
                "name": template.Name or "",
                "count": len(linked_views),
                "id": template_id,
                "type": template_type_name(template),
                "linked": linked_views,
                "controlled": controlled_count,
            }
        )
    return sorted(records, key=lambda item: (item["type"], item["name"].lower()))


class TemplateItem(object):
    """Plain WPF binding adapter for a template audit record."""

    def __init__(self, data):
        self.data = data

    @property
    def name(self):
        return self.data["name"]

    @property
    def type(self):
        return self.data["type"]

    @property
    def status(self):
        return "IN USE" if self.data["count"] else "UNUSED"

    @property
    def count(self):
        return text_type(self.data["count"])

    @property
    def controlled(self):
        return text_type(self.data["controlled"])

    @property
    def id(self):
        return text_type(self.data["id"])


class RevitViewOption(forms.TemplateListItem):
    """Selectable Revit view label."""

    @property
    def name(self):
        return "{} | {} | {}".format(
            self.item.Name,
            text_type(self.item.ViewType),
            element_id_value(self.item.Id),
        )


class RevitDocumentOption(forms.TemplateListItem):
    """Selectable open Revit document label."""

    @property
    def name(self):
        return self.item.Title


class ViewTemplateManagerUI(forms.WPFWindow):
    """Dark, transaction-safe view template management hub."""

    def __init__(self, xaml_path):
        self.all_data = []
        self.visible_items = []
        forms.WPFWindow.__init__(self, xaml_path)
        self.refresh_data()

    def _set_status(self, message):
        self.tb_status.Text = message

    def _selected_combo_text(self, combo, fallback):
        selected = combo.SelectedItem
        if selected is None:
            return fallback
        return text_type(getattr(selected, "Content", selected))

    def refresh_data(self):
        selected_ids = set(item["id"] for item in self.get_selected())
        try:
            self.Cursor = Cursors.Wait
            self._set_status("Scanning view templates and usage...")
            self.all_data = get_template_data()
            self.tb_total.Text = text_type(len(self.all_data))
            used_count = len([item for item in self.all_data if item["count"] > 0])
            self.tb_used.Text = text_type(used_count)
            self.tb_unused.Text = text_type(len(self.all_data) - used_count)

            previous_type = self._selected_combo_text(self.cb_type, "All Types")
            type_names = sorted(set(item["type"] for item in self.all_data))
            self.cb_type.Items.Clear()
            self.cb_type.Items.Add("All Types")
            for type_name in type_names:
                self.cb_type.Items.Add(type_name)
            if previous_type in type_names:
                self.cb_type.SelectedItem = previous_type
            else:
                self.cb_type.SelectedIndex = 0

            self.apply_filters()
            for item in self.lv_templates.Items:
                if item.data["id"] in selected_ids:
                    self.lv_templates.SelectedItems.Add(item)
            self._set_status(
                "Ready | {} template(s), {} in use, {} unused".format(
                    len(self.all_data),
                    used_count,
                    len(self.all_data) - used_count,
                )
            )
        except Exception as error:
            logger.exception("Template Manager refresh failed")
            forms.alert(
                "Could not refresh Template Manager data.\n\n{}".format(error),
                title="Template Manager Pro",
            )
            self._set_status("Refresh failed")
        finally:
            self.Cursor = Cursors.Arrow

    def apply_filters(self):
        if not hasattr(self, "lv_templates"):
            return
        search = text_type(self.txt_search.Text or "").strip().lower()
        status_filter = self._selected_combo_text(self.cb_status, "All Status")
        type_filter = self._selected_combo_text(self.cb_type, "All Types")

        visible = []
        for record in self.all_data:
            status = "In Use" if record["count"] else "Unused"
            searchable = "{} | {} | {} | {}".format(
                record["name"], record["type"], status, record["id"]
            ).lower()
            if search and search not in searchable:
                continue
            if status_filter != "All Status" and status_filter != status:
                continue
            if type_filter != "All Types" and type_filter != record["type"]:
                continue
            visible.append(TemplateItem(record))

        self.visible_items = visible
        self.lv_templates.ItemsSource = visible
        self.tb_selected.Text = "0"
        self._set_status(
            "Showing {} of {} template(s)".format(len(visible), len(self.all_data))
        )

    def get_selected(self):
        if not hasattr(self, "lv_templates"):
            return []
        return [item.data for item in self.lv_templates.SelectedItems]

    def _require_selected(self, exact_count=None):
        selected = self.get_selected()
        if exact_count is not None and len(selected) != exact_count:
            forms.alert(
                "Select exactly {} template(s).".format(exact_count),
                title="Template Manager Pro",
            )
            return []
        if not selected:
            forms.alert(
                "Select one or more templates first.",
                title="Template Manager Pro",
            )
            return []
        return selected

    def header_mouse_down(self, sender, event_args):
        source = getattr(event_args, "OriginalSource", None)
        current = source
        while current is not None:
            if isinstance(current, Button):
                if text_type(current.Tag or "") == "WindowControl":
                    return
                break
            try:
                current = VisualTreeHelper.GetParent(current)
            except Exception:
                break
        if event_args.ClickCount == 2:
            self._toggle_maximize()
        else:
            try:
                self.DragMove()
            except Exception:
                pass

    def _toggle_maximize(self):
        self.WindowState = (
            WindowState.Normal
            if self.WindowState == WindowState.Maximized
            else WindowState.Maximized
        )

    def window_minimize(self, sender, event_args):
        self.WindowState = WindowState.Minimized

    def window_maximize(self, sender, event_args):
        self._toggle_maximize()

    def window_close(self, sender, event_args):
        self.Close()

    def window_key_down(self, sender, event_args):
        if event_args.Key == Key.Escape:
            self.Close()

    def search_changed(self, sender, event_args):
        self.apply_filters()

    def filter_changed(self, sender, event_args):
        self.apply_filters()

    def template_selection_changed(self, sender, event_args):
        self.tb_selected.Text = text_type(len(self.get_selected()))

    def select_visible(self, sender, event_args):
        self.lv_templates.SelectAll()

    def clear_selection(self, sender, event_args):
        self.lv_templates.UnselectAll()

    def refresh_clicked(self, sender, event_args):
        self.refresh_data()

    def btn_duplicate(self, sender, event_args):
        selected = self._require_selected()
        if not selected:
            return
        suffix = forms.ask_for_string(
            default="_Copy",
            prompt="Enter the suffix for duplicated templates:",
            title="Duplicate View Templates",
        )
        if suffix is None or not suffix:
            return

        existing_names = set(item["name"].lower() for item in self.all_data)
        candidates = []
        skipped = []
        reserved = set(existing_names)
        for record in selected:
            desired_name = record["name"] + suffix
            if desired_name.lower() in reserved:
                skipped.append("{} (name already exists)".format(desired_name))
                continue
            reserved.add(desired_name.lower())
            candidates.append((record, desired_name))
        if not candidates:
            forms.alert(
                "No templates can be duplicated with this suffix.",
                title="Duplicate View Templates",
            )
            return

        transaction = DB.Transaction(doc, "P13 Duplicate View Templates")
        transaction.Start()
        created = []
        try:
            for record, desired_name in candidates:
                subtransaction = DB.SubTransaction(doc)
                subtransaction.Start()
                try:
                    new_id = record["element"].Duplicate(
                        DB.ViewDuplicateOption.Duplicate
                    )
                    new_template = doc.GetElement(new_id)
                    new_template.Name = desired_name
                    created.append(desired_name)
                    subtransaction.Commit()
                except Exception as error:
                    subtransaction.RollBack()
                    skipped.append(
                        "{} ({})".format(record["name"], text_type(error))
                    )
            transaction.Commit()
        except Exception as error:
            transaction.RollBack()
            logger.exception("Template duplication failed")
            forms.alert(
                "Could not duplicate templates. No partial changes were kept.\n\n{}".format(
                    error
                ),
                title="Duplicate View Templates",
            )
            return

        self.refresh_data()
        message = "Created {} template(s).".format(len(created))
        if skipped:
            message += "\n\nSkipped:\n{}".format("\n".join(skipped))
        forms.alert(message, title="Duplicate View Templates")

    def btn_rename(self, sender, event_args):
        selected = self._require_selected()
        if not selected:
            return
        prefix = forms.ask_for_string(
            default="",
            prompt="Optional prefix:",
            title="Batch Rename View Templates",
        )
        if prefix is None:
            return
        find_text = forms.ask_for_string(
            default="",
            prompt="Optional text to find:",
            title="Batch Rename View Templates",
        )
        if find_text is None:
            return
        replace_text = ""
        if find_text:
            replace_text = forms.ask_for_string(
                default="",
                prompt="Replacement text:",
                title="Batch Rename View Templates",
            )
            if replace_text is None:
                return

        selected_ids = set(record["id"] for record in selected)
        reserved = set(
            record["name"].lower()
            for record in self.all_data
            if record["id"] not in selected_ids
        )
        edits = []
        conflicts = []
        for record in selected:
            new_name = record["name"]
            if find_text:
                new_name = new_name.replace(find_text, replace_text)
            if prefix:
                new_name = prefix + new_name
            new_name = new_name.strip()
            if not new_name or new_name == record["name"]:
                continue
            if new_name.lower() in reserved:
                conflicts.append(new_name)
                continue
            reserved.add(new_name.lower())
            edits.append((record, new_name))

        if conflicts:
            forms.alert(
                "Rename conflicts were found:\n\n{}".format(
                    "\n".join(sorted(conflicts))
                ),
                title="Batch Rename View Templates",
            )
            return
        if not edits:
            forms.alert(
                "The rename rules do not produce any changes.",
                title="Batch Rename View Templates",
            )
            return
        if not forms.alert(
            "Rename {} selected template(s)?".format(len(edits)),
            title="Batch Rename View Templates",
            yes=True,
            no=True,
        ):
            return

        transaction = DB.Transaction(doc, "P13 Batch Rename View Templates")
        transaction.Start()
        try:
            for record, new_name in edits:
                record["element"].Name = "P13_TMP_{}".format(record["id"])
            for record, new_name in edits:
                record["element"].Name = new_name
            transaction.Commit()
        except Exception as error:
            transaction.RollBack()
            logger.exception("Template rename failed")
            forms.alert(
                "Could not rename templates. No partial changes were kept.\n\n{}".format(
                    error
                ),
                title="Batch Rename View Templates",
            )
            return
        self.refresh_data()
        forms.alert(
            "Renamed {} template(s).".format(len(edits)),
            title="Batch Rename View Templates",
        )

    def btn_delete(self, sender, event_args):
        selected = self._require_selected()
        if not selected:
            return
        deletable = [record for record in selected if record["count"] == 0]
        protected = [record["name"] for record in selected if record["count"] > 0]
        if not deletable:
            forms.alert(
                "All selected templates are in use and are protected from deletion.",
                title="Delete Unused Templates",
            )
            return

        preview_names = [record["name"] for record in deletable[:12]]
        preview = "\n".join(preview_names)
        if len(deletable) > 12:
            preview += "\n... and {} more".format(len(deletable) - 12)
        message = "Delete {} unused template(s)?\n\n{}".format(
            len(deletable), preview
        )
        if protected:
            message += "\n\n{} in-use template(s) will be skipped.".format(
                len(protected)
            )
        if not forms.alert(
            message,
            title="Delete Unused Templates",
            yes=True,
            no=True,
        ):
            return

        transaction = DB.Transaction(doc, "P13 Delete Unused View Templates")
        transaction.Start()
        try:
            for record in deletable:
                doc.Delete(record["element"].Id)
            transaction.Commit()
        except Exception as error:
            transaction.RollBack()
            logger.exception("Unused template deletion failed")
            forms.alert(
                "Could not delete the selected templates. No partial changes were kept.\n\n{}".format(
                    error
                ),
                title="Delete Unused Templates",
            )
            return
        self.refresh_data()
        forms.alert(
            "Deleted {} unused template(s).{}"
            .format(
                len(deletable),
                "\nSkipped {} in-use template(s).".format(len(protected))
                if protected
                else "",
            ),
            title="Delete Unused Templates",
        )

    def btn_show(self, sender, event_args):
        selected = self._require_selected(exact_count=1)
        if not selected:
            return
        record = selected[0]
        if not record["linked"]:
            forms.alert(
                "This template is not assigned to any view.",
                title="Linked Views",
            )
            return
        forms.SelectFromList.show(
            [RevitViewOption(view) for view in record["linked"]],
            title="Views using: {}".format(record["name"]),
            multiselect=False,
            button_name="Close",
        )

    def _parameter_map(self, template):
        values = {}
        for parameter in template.Parameters:
            try:
                name = parameter.Definition.Name
            except Exception:
                continue
            values[name] = parameter_text(parameter)
        return values

    def btn_compare(self, sender, event_args):
        selected = self._require_selected(exact_count=2)
        if not selected:
            return
        first = selected[0]
        second = selected[1]
        first_values = self._parameter_map(first["element"])
        second_values = self._parameter_map(second["element"])
        differences = []
        for name in sorted(set(first_values.keys()).union(second_values.keys())):
            first_value = first_values.get(name, "N/A")
            second_value = second_values.get(name, "N/A")
            if first_value != second_value:
                differences.append([name, first_value, second_value])

        output.print_md("## View Template Comparison")
        output.print_md(
            "**A:** {}  \n**B:** {}".format(first["name"], second["name"])
        )
        if differences:
            output.print_table(
                differences,
                columns=["Parameter", "Template A", "Template B"],
            )
            forms.alert(
                "Found {} parameter difference(s). Review the pyRevit output window.".format(
                    len(differences)
                ),
                title="Compare View Templates",
            )
        else:
            output.print_md("No parameter value differences were found.")
            forms.alert(
                "The selected templates have matching parameter values.",
                title="Compare View Templates",
            )

    def btn_apply(self, sender, event_args):
        selected = self._require_selected(exact_count=1)
        if not selected:
            return
        template = selected[0]["element"]
        compatible_views = []
        for view in DB.FilteredElementCollector(doc).OfClass(DB.View):
            if view.IsTemplate:
                continue
            try:
                if view.IsValidViewTemplate(template.Id):
                    compatible_views.append(view)
            except Exception:
                continue
        if not compatible_views:
            forms.alert(
                "No compatible views were found for this template.",
                title="Apply View Template",
            )
            return
        chosen = forms.SelectFromList.show(
            [
                RevitViewOption(view)
                for view in sorted(compatible_views, key=lambda item: item.Name.lower())
            ],
            multiselect=True,
            title="Apply '{}' to Views".format(template.Name),
            button_name="Apply",
        )
        if not chosen:
            return

        transaction = DB.Transaction(doc, "P13 Apply View Template")
        transaction.Start()
        changed = 0
        failed = []
        try:
            for view in chosen:
                subtransaction = DB.SubTransaction(doc)
                subtransaction.Start()
                try:
                    view.ViewTemplateId = template.Id
                    changed += 1
                    subtransaction.Commit()
                except Exception as error:
                    subtransaction.RollBack()
                    failed.append("{} ({})".format(view.Name, error))
            transaction.Commit()
        except Exception as error:
            transaction.RollBack()
            logger.exception("Applying view template failed")
            forms.alert(
                "Could not apply the template. No partial changes were kept.\n\n{}".format(
                    error
                ),
                title="Apply View Template",
            )
            return
        self.refresh_data()
        message = "Applied the template to {} view(s).".format(changed)
        if failed:
            message += "\n\nFailed:\n{}".format("\n".join(failed))
        forms.alert(message, title="Apply View Template")

    def _set_controlled_parameters(self, include_all):
        selected = self._require_selected()
        if not selected:
            return
        action = "Include" if include_all else "Exclude"
        if not forms.alert(
            "{} all available parameters for {} template(s)?".format(
                action, len(selected)
            ),
            title="{} Template Parameters".format(action),
            yes=True,
            no=True,
        ):
            return

        transaction = DB.Transaction(
            doc, "P13 {} All Template Parameters".format(action)
        )
        transaction.Start()
        changed = 0
        failed = []
        try:
            for record in selected:
                subtransaction = DB.SubTransaction(doc)
                subtransaction.Start()
                try:
                    noncontrolled_ids = (
                        List[DB.ElementId]()
                        if include_all
                        else List[DB.ElementId](
                            list(record["element"].GetTemplateParameterIds())
                        )
                    )
                    record["element"].SetNonControlledTemplateParameterIds(
                        noncontrolled_ids
                    )
                    changed += 1
                    subtransaction.Commit()
                except Exception as error:
                    subtransaction.RollBack()
                    failed.append("{} ({})".format(record["name"], error))
            transaction.Commit()
        except Exception as error:
            transaction.RollBack()
            logger.exception("Template parameter control update failed")
            forms.alert(
                "Could not update parameter controls. No partial changes were kept.\n\n{}".format(
                    error
                ),
                title="Template Parameter Controls",
            )
            return
        self.refresh_data()
        message = "Updated parameter controls on {} template(s).".format(changed)
        if failed:
            message += "\n\nFailed:\n{}".format("\n".join(failed))
        forms.alert(message, title="Template Parameter Controls")

    def btn_include_all(self, sender, event_args):
        self._set_controlled_parameters(True)

    def btn_exclude_all(self, sender, event_args):
        self._set_controlled_parameters(False)

    def btn_import(self, sender, event_args):
        source_documents = [
            document
            for document in app.Documents
            if not document.IsFamilyDocument and document.Title != doc.Title
        ]
        if not source_documents:
            forms.alert(
                "Open another Revit project before importing templates.",
                title="Import View Templates",
            )
            return
        source_document = forms.SelectFromList.show(
            [RevitDocumentOption(document) for document in source_documents],
            title="Select Source Project",
            multiselect=False,
        )
        if not source_document:
            return
        source_templates = [
            view
            for view in DB.FilteredElementCollector(source_document).OfClass(DB.View)
            if view.IsTemplate
        ]
        if not source_templates:
            forms.alert(
                "The selected source project has no view templates.",
                title="Import View Templates",
            )
            return
        selected_templates = forms.SelectFromList.show(
            sorted(source_templates, key=lambda item: item.Name.lower()),
            name_attr="Name",
            multiselect=True,
            title="Select View Templates to Import",
            button_name="Import",
        )
        if not selected_templates:
            return

        existing_names = set(record["name"].lower() for record in self.all_data)
        importable = [
            template
            for template in selected_templates
            if template.Name.lower() not in existing_names
        ]
        skipped = [
            template.Name
            for template in selected_templates
            if template.Name.lower() in existing_names
        ]
        if not importable:
            forms.alert(
                "All selected template names already exist in this project.",
                title="Import View Templates",
            )
            return

        transaction = DB.Transaction(doc, "P13 Import View Templates")
        transaction.Start()
        try:
            source_ids = List[DB.ElementId]([item.Id for item in importable])
            copied_ids = DB.ElementTransformUtils.CopyElements(
                source_document,
                source_ids,
                doc,
                DB.Transform.Identity,
                DB.CopyPasteOptions(),
            )
            transaction.Commit()
        except Exception as error:
            transaction.RollBack()
            logger.exception("Template import failed")
            forms.alert(
                "Could not import view templates. No partial changes were kept.\n\n{}".format(
                    error
                ),
                title="Import View Templates",
            )
            return
        self.refresh_data()
        message = "Imported {} template(s).".format(len(list(copied_ids)))
        if skipped:
            message += "\n\nSkipped existing names:\n{}".format(
                "\n".join(sorted(skipped))
            )
        forms.alert(message, title="Import View Templates")

    def _choose_export_directory(self, force_picker=False):
        current = text_type(
            config.get_option(EXPORT_DIRECTORY_KEY, "") or ""
        )
        if current and os.path.isdir(current) and not force_picker:
            return current
        dialog = FolderBrowserDialog()
        dialog.Description = "Select the folder for Template Manager reports."
        dialog.ShowNewFolderButton = True
        if current and os.path.isdir(current):
            dialog.SelectedPath = current
        if dialog.ShowDialog() != DialogResult.OK:
            return None
        selected = text_type(dialog.SelectedPath)
        config.set_option(EXPORT_DIRECTORY_KEY, selected)
        script.save_config()
        return selected

    def btn_export(self, sender, event_args):
        current = text_type(
            config.get_option(EXPORT_DIRECTORY_KEY, "") or ""
        )
        force_picker = False
        if current and os.path.isdir(current):
            choice = forms.alert(
                "Current export folder:\n{}\n\nChoose an export action.".format(
                    current
                ),
                title="Export Template Audit",
                options=["Export Here", "Change Folder", "Cancel"],
            )
            if choice == "Cancel" or not choice:
                return
            force_picker = choice == "Change Folder"
        export_directory = self._choose_export_directory(force_picker)
        if not export_directory:
            return

        timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss")
        export_path = os.path.join(
            export_directory,
            "P13_View_Template_Audit_{}.csv".format(timestamp),
        )
        headers = [
            "Status",
            "View Type",
            "Template Name",
            "Used By Views",
            "Controlled Parameters",
            "Element ID",
            "Linked Views",
        ]
        lines = [u",".join(csv_field(value) for value in headers)]
        for record in self.all_data:
            linked_names = "; ".join(view.Name for view in record["linked"])
            values = [
                "In Use" if record["count"] else "Unused",
                record["type"],
                record["name"],
                record["count"],
                record["controlled"],
                record["id"],
                linked_names,
            ]
            lines.append(u",".join(csv_field(value) for value in values))
        try:
            with io.open(export_path, "w", encoding="utf-8-sig") as report:
                report.write(u"\r\n".join(lines))
        except Exception as error:
            logger.exception("Template audit export failed")
            forms.alert(
                "Could not export the template audit.\n\n{}".format(error),
                title="Export Template Audit",
            )
            return
        self._set_status("Exported audit: {}".format(export_path))
        forms.alert(
            "Exported {} template record(s).\n\n{}".format(
                len(self.all_data), export_path
            ),
            title="Export Template Audit",
        )


if __name__ == "__main__":
    file_descriptor, xaml_path = tempfile.mkstemp(suffix=".xaml")

    try:
        os.close(file_descriptor)
    except Exception:
        pass

    try:
        with io.open(xaml_path, "w", encoding="utf-8") as xaml_file:
            xaml_file.write(XAML_UI)
        ViewTemplateManagerUI(xaml_path).ShowDialog()
    finally:
        if xaml_path and os.path.isfile(xaml_path):
            try:
                os.remove(xaml_path)
            except Exception:
                logger.warning(
                    "Could not remove temporary XAML file: {}".format(xaml_path)
                )
