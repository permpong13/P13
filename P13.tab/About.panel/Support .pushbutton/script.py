# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except,too-many-lines
"""Support P13.extension development and submit new BIM tool ideas."""

__title__ = "Support\nP13"
__author__ = "Permpong Taweekul (P13)"
__doc__ = (
    "Support P13.extension development & maintenance:\n"
    "- Ko-fi (Card, Apple Pay, Google Pay - no signup required)\n"
    "- GitHub Sponsors\n"
    "- Scan QR (Ko-fi Worldwide & PromptPay Thailand/ASEAN)\n"
    "- Suggest new Revit tool ideas\n\n"
    "Shift+Click: Open Ko-fi page directly in browser"
)

import os
import sys

try:
    from urllib import quote as url_quote
except ImportError:
    from urllib.parse import quote as url_quote

import clr
clr.AddReference("System")
clr.AddReference("System.Xml")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

import System
from System.IO import FileStream, FileMode, FileAccess, FileShare
from System.Windows import Visibility, Clipboard
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption

from pyrevit import script, HOST_APP, EXEC_PARAMS

KOFI_URL = "https://ko-fi.com/permpong13"
GITHUB_SPONSORS_URL = "https://github.com/sponsors/permpong13"
GITHUB_REPO_URL = "https://github.com/permpong13/P13"
GITHUB_ISSUES_NEW_URL = "https://github.com/permpong13/P13/issues/new"


def set_revit_owner(wpf_win):
    try:
        hwnd = HOST_APP.uiapp.MainWindowHandle
        if hwnd != System.IntPtr.Zero:
            WindowInteropHelper(wpf_win).Owner = hwnd
    except Exception:
        pass


def load_unlocked_bitmap(image_path):
    """Load PNG into memory and close stream immediately so Sync/Update never hits a file lock."""
    if not image_path or not os.path.isfile(image_path):
        return None
    stream = None
    try:
        stream = FileStream(image_path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite)
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.StreamSource = stream
        bmp.EndInit()
        bmp.Freeze()
        return bmp
    except Exception:
        return None
    finally:
        if stream is not None:
            stream.Close()
            stream.Dispose()


QR_ZOOM_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Scan QR Code" Width="480" Height="560"
        WindowStartupLocation="CenterOwner" ResizeMode="NoResize"
        Background="#FFFFFF" FontFamily="Segoe UI">
    <Grid Margin="22">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <TextBlock Name="lbl_qr_title" FontSize="17" FontWeight="SemiBold"
                   Foreground="#1F252D" HorizontalAlignment="Center" Margin="0,0,0,10"/>
        <Border Grid.Row="1" BorderBrush="#E2E5EC" BorderThickness="1" CornerRadius="10" Padding="14" Background="#FFFFFF">
            <Image Name="img_zoom" Stretch="Uniform"/>
        </Border>
        <Button Name="btn_close_zoom" Grid.Row="2" Content="Close" Height="32" Width="110"
                Margin="0,14,0,0" HorizontalAlignment="Center" IsCancel="True"
                Background="#F0F2F5" BorderBrush="#C8CCD4" BorderThickness="1"/>
    </Grid>
</Window>
"""


IDEA_LAB_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Suggest a Tool Idea - P13.extension"
        Width="540" Height="450" MinWidth="480" MinHeight="410"
        WindowStartupLocation="CenterOwner"
        Background="#F4F5F7" FontFamily="Segoe UI" FontSize="12"
        UseLayoutRounding="True" SnapsToDevicePixels="True">
    <Grid Margin="18">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <StackPanel Grid.Row="0" Margin="0,0,0,12">
            <TextBlock Text="Suggest a New Revit Tool or Improvement" FontSize="16" FontWeight="SemiBold" Foreground="#1F252D"/>
            <TextBlock Text="Describe repetitive BIM tasks you want automated. Great ideas help shape future updates."
                       Foreground="#5A6270" Margin="0,3,0,0" TextWrapping="Wrap"/>
        </StackPanel>

        <Grid Grid.Row="1" Margin="0,0,0,10">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="115"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <TextBlock Text="Discipline:" VerticalAlignment="Center" Foreground="#2C323D"/>
            <ComboBox Name="cmb_cat" Grid.Column="1" Height="26" SelectedIndex="0" VerticalContentAlignment="Center">
                <ComboBoxItem Content="Sheets, Views &amp; Documentation"/>
                <ComboBoxItem Content="Architecture / Structure Modeling"/>
                <ComboBoxItem Content="MEP Systems (Pipes, Ducts, Openings)"/>
                <ComboBoxItem Content="Schedules, Excel &amp; Parameters"/>
                <ComboBoxItem Content="Coordinates &amp; QA/QC Checking"/>
            </ComboBox>
        </Grid>

        <Grid Grid.Row="2" Margin="0,0,0,10">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="115"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <TextBlock Text="Tool Title:" VerticalAlignment="Center" Foreground="#2C323D"/>
            <TextBox Name="txt_idea_title" Grid.Column="1" Height="26" VerticalContentAlignment="Center" Padding="6,0"/>
        </Grid>

        <Grid Grid.Row="3">
            <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="*"/>
            </Grid.RowDefinitions>
            <TextBlock Text="Problem &amp; Expected Result:" Foreground="#2C323D" Margin="0,0,0,5"/>
            <TextBox Name="txt_idea_desc" Grid.Row="1" AcceptsReturn="True" TextWrapping="Wrap"
                     VerticalScrollBarVisibility="Auto" Padding="8"/>
        </Grid>

        <Grid Grid.Row="4" Margin="0,14,0,0">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <Button Name="btn_idea_kofi" Content="Copy Idea &amp; Open Ko-fi" Height="30" Padding="12,0"
                    HorizontalAlignment="Left" Background="#0078D4" Foreground="#FFFFFF" BorderThickness="0"
                    ToolTip="Copy formatted idea to clipboard so you can paste it into a Ko-fi message"/>
            <StackPanel Grid.Column="1" Orientation="Horizontal">
                <Button Name="btn_idea_github" Content="Submit on GitHub" Height="30" Padding="12,0" Margin="0,0,8,0"
                        Background="#24292F" Foreground="#FFFFFF" BorderThickness="0"/>
                <Button Name="btn_idea_close" Content="Cancel" Height="30" Width="76" IsCancel="True"
                        Background="#E4E6EB" Foreground="#1F252D" BorderThickness="0"/>
            </StackPanel>
        </Grid>
    </Grid>
</Window>
"""


SUPPORT_WINDOW_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Support P13.extension"
        Width="750" Height="710" MinWidth="690" MinHeight="650"
        WindowStartupLocation="CenterScreen"
        Background="#F3F4F6" FontFamily="Segoe UI" FontSize="12"
        UseLayoutRounding="True" SnapsToDevicePixels="True">
    <Window.Resources>
        <Style x:Key="ActionBtn" TargetType="Button">
            <Setter Property="Height" Value="32"/>
            <Setter Property="Padding" Value="14,0"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border x:Name="bdr" Background="{TemplateBinding Background}"
                                BorderBrush="{TemplateBinding BorderBrush}"
                                BorderThickness="{TemplateBinding BorderThickness}"
                                CornerRadius="6" Padding="{TemplateBinding Padding}">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                        <ControlTemplate.Triggers>
                            <Trigger Property="IsMouseOver" Value="True">
                                <Setter TargetName="bdr" Property="Opacity" Value="0.88"/>
                            </Trigger>
                        </ControlTemplate.Triggers>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
        </Style>
    </Window.Resources>

    <Grid>
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- 1. Revit 2026 Dark Slate Header -->
        <Border Grid.Row="0" Background="#1F252D" Padding="22,15">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="Auto"/>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <Border Width="42" Height="42" CornerRadius="8" Background="#0696D7" Margin="0,0,14,0" VerticalAlignment="Center">
                    <TextBlock Text="P13" Foreground="#FFFFFF" FontSize="16" FontWeight="Bold"
                               HorizontalAlignment="Center" VerticalAlignment="Center"/>
                </Border>
                <StackPanel Grid.Column="1" VerticalAlignment="Center">
                    <TextBlock Text="P13.extension &#x2014; BIM Automation Toolkit" FontSize="17" FontWeight="SemiBold" Foreground="#FFFFFF"/>
                    <TextBlock Text="Developed by Permpong Taweekul &#x2022; Keeping practical Revit tools free and updated for everyone."
                               Foreground="#B8C1CC" FontSize="11.5" Margin="0,3,0,0" TextWrapping="Wrap"/>
                </StackPanel>
                <Border Grid.Column="2" Background="#183D2C" BorderBrush="#2D7A53" BorderThickness="1"
                        CornerRadius="4" Padding="9,4" VerticalAlignment="Center">
                    <TextBlock Text="100% Free &amp; Open-Source" Foreground="#6EE7B7" FontSize="11" FontWeight="SemiBold"/>
                </Border>
            </Grid>
        </Border>

        <!-- 2. Main Content Body -->
        <Grid Grid.Row="1" Margin="20,14,20,12">
            <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="*"/>
            </Grid.RowDefinitions>

            <!-- Primary Instant Support Card -->
            <Border Grid.Row="0" Background="#FFFFFF" BorderBrush="#D0D7DE" BorderThickness="1"
                    CornerRadius="8" Padding="16,13" Margin="0,0,0,10">
                <Grid>
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="*"/>
                        <ColumnDefinition Width="Auto"/>
                    </Grid.ColumnDefinitions>
                    <StackPanel VerticalAlignment="Center" Margin="0,0,12,0">
                        <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
                            <Border Background="#E6F4FF" CornerRadius="4" Padding="7,2" Margin="0,0,8,0">
                                <TextBlock Text="WORLDWIDE" Foreground="#0066B8" FontSize="10" FontWeight="Bold"/>
                            </Border>
                            <TextBlock Text="Buy P13 a Coffee (Ko-fi / GitHub Sponsors)" FontSize="14.5" FontWeight="SemiBold" Foreground="#1F252D"/>
                        </StackPanel>
                        <TextBlock Text="Pay with Credit/Debit Card, Apple Pay, or Google Pay. No Ko-fi account required."
                                   Foreground="#57606A" FontSize="11.5" Margin="0,5,0,0"/>
                    </StackPanel>
                    <StackPanel Grid.Column="1" Orientation="Horizontal" VerticalAlignment="Center">
                        <Button Name="btn_kofi" Style="{StaticResource ActionBtn}"
                                Content="Support on Ko-fi" FontWeight="SemiBold"
                                Background="#0078D4" BorderBrush="#006CBE" Foreground="#FFFFFF" Margin="0,0,6,0"/>
                        <Button Name="btn_copy_kofi" Style="{StaticResource ActionBtn}"
                                Content="Copy Link" Background="#F6F8FA" BorderBrush="#D0D7DE" Foreground="#24292F" Margin="0,0,8,0"/>
                        <Button Name="btn_sponsors" Style="{StaticResource ActionBtn}"
                                Content="GitHub Sponsors" Background="#24292F" BorderBrush="#24292F" Foreground="#FFFFFF"/>
                    </StackPanel>
                </Grid>
            </Border>

            <!-- Restored Light-Blue Idea Callout Banner -->
            <Border Grid.Row="1" Background="#F2F7FF" BorderBrush="#CFE2FF" BorderThickness="1"
                    CornerRadius="8" Padding="14,9" Margin="0,0,0,10">
                <Grid>
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="*"/>
                        <ColumnDefinition Width="Auto"/>
                    </Grid.ColumnDefinitions>
                    <TextBlock Text="Have an idea for a Revit script that isn't in P13 yet? Share your workflow pain points with us!"
                               Foreground="#1E3A5F" FontSize="12" VerticalAlignment="Center" TextWrapping="Wrap" Margin="0,0,12,0"/>
                    <Button Name="btn_suggest_idea" Grid.Column="1" Style="{StaticResource ActionBtn}"
                            Content="Suggest a Tool Idea" Height="30" FontWeight="SemiBold"
                            Background="#1652F0" BorderBrush="#1652F0" Foreground="#FFFFFF"/>
                </Grid>
            </Border>

            <!-- Two Equal QR Cards -->
            <Grid Grid.Row="2">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="14"/>
                    <ColumnDefinition Width="*"/>
                </Grid.ColumnDefinitions>

                <!-- Left Card: Ko-fi Mobile QR -->
                <Border Grid.Column="0" Background="#FFFFFF" BorderBrush="#D0D7DE" BorderThickness="1" CornerRadius="8" Padding="14">
                    <Grid>
                        <Grid.RowDefinitions>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="*"/>
                            <RowDefinition Height="Auto"/>
                        </Grid.RowDefinitions>
                        <StackPanel HorizontalAlignment="Center" Margin="0,0,0,6">
                            <TextBlock Text="Scan via Phone (Global)" FontSize="14" FontWeight="SemiBold" Foreground="#1F252D" HorizontalAlignment="Center"/>
                            <TextBlock Text="Apple Pay &#x2022; Google Pay &#x2022; Card (Click QR to enlarge)" FontSize="11" Foreground="#6E7781" HorizontalAlignment="Center" Margin="0,2,0,0"/>
                        </StackPanel>
                        <Border Name="bdr_kofi_qr" Grid.Row="1" Cursor="Hand" Background="#FFFFFF" Padding="4" ToolTip="Click to zoom QR code">
                            <Image Name="img_kofi_qr" Stretch="Uniform" HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                        <TextBlock Name="lbl_kofi_missing" Grid.Row="1" Text="Place qr_kofi.png in button folder"
                                   Foreground="#8C959F" HorizontalAlignment="Center" VerticalAlignment="Center" Visibility="Collapsed"/>
                        <TextBlock Grid.Row="2" Text="ko-fi.com/permpong13" FontSize="11.5" FontWeight="SemiBold"
                                   Foreground="#0078D4" HorizontalAlignment="Center" Margin="0,6,0,0"/>
                    </Grid>
                </Border>

                <!-- Right Card: PromptPay QR -->
                <Border Grid.Column="2" Background="#FFFFFF" BorderBrush="#D0D7DE" BorderThickness="1" CornerRadius="8" Padding="14">
                    <Grid>
                        <Grid.RowDefinitions>
                            <RowDefinition Height="Auto"/>
                            <RowDefinition Height="*"/>
                            <RowDefinition Height="Auto"/>
                        </Grid.RowDefinitions>
                        <StackPanel HorizontalAlignment="Center" Margin="0,0,0,6">
                            <TextBlock Text="PromptPay / ASEAN QR" FontSize="14" FontWeight="SemiBold" Foreground="#1F252D" HorizontalAlignment="Center"/>
                            <TextBlock Text="Thai Banking Apps &amp; Cross-Border QR (Click to enlarge)" FontSize="11" Foreground="#6E7781" HorizontalAlignment="Center" Margin="0,2,0,0"/>
                        </StackPanel>
                        <Border Name="bdr_pp_qr" Grid.Row="1" Cursor="Hand" Background="#FFFFFF" Padding="4" ToolTip="Click to zoom QR code">
                            <Image Name="img_pp_qr" Stretch="Uniform" HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                        <TextBlock Name="lbl_pp_missing" Grid.Row="1" Text="Place qr_promptpay.png in button folder"
                                   Foreground="#8C959F" HorizontalAlignment="Center" VerticalAlignment="Center" Visibility="Collapsed"/>
                        <TextBlock Grid.Row="2" Text="PERMPONG TAWEEKUL (Zero-Fee Direct Transfer)" FontSize="11.5" FontWeight="SemiBold"
                                   Foreground="#1F252D" HorizontalAlignment="Center" Margin="0,6,0,0"/>
                    </Grid>
                </Border>
            </Grid>
        </Grid>

        <!-- 3. Footer with Star on GitHub + Copy Repo Link + Close -->
        <Border Grid.Row="2" Background="#FFFFFF" BorderBrush="#D8DEE4" BorderThickness="0,1,0,0" Padding="20,12">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
                    <Button Name="btn_star_github" Style="{StaticResource ActionBtn}"
                            Content="Star on GitHub" Height="30"
                            Background="#FFFFFF" BorderBrush="#D0D7DE" Foreground="#1F252D" Margin="0,0,8,0"/>
                    <Button Name="btn_copy_repo" Style="{StaticResource ActionBtn}"
                            Content="Copy Repo Link" Height="30"
                            Background="#F5FAFF" BorderBrush="#94C6FF" Foreground="#0066B8" Margin="0,0,12,0"/>
                    <TextBlock Name="lbl_toast" Text="" Foreground="#1A7F37" FontSize="11.5" VerticalAlignment="Center"/>
                </StackPanel>
                <Button Name="btn_close" Grid.Column="1" Style="{StaticResource ActionBtn}"
                        Content="Close" Height="30" Width="86" IsCancel="True"
                        Background="#EAECEF" BorderBrush="#D0D7DE" Foreground="#1F252D"/>
            </Grid>
        </Border>
    </Grid>
</Window>
"""


class SupportP13Controller(object):
    def __init__(self, bundle_dir):
        self.win = XamlReader.Parse(SUPPORT_WINDOW_XAML)
        set_revit_owner(self.win)

        self.kofi_bmp = load_unlocked_bitmap(os.path.join(bundle_dir, "qr_kofi.png"))
        self.pp_bmp = load_unlocked_bitmap(os.path.join(bundle_dir, "qr_promptpay.png"))

        img_kofi = self.win.FindName("img_kofi_qr")
        if self.kofi_bmp is not None:
            img_kofi.Source = self.kofi_bmp
            self.win.FindName("bdr_kofi_qr").MouseLeftButtonUp += lambda s, a: self._zoom_qr(
                "Ko-fi Mobile QR (ko-fi.com/permpong13)", self.kofi_bmp
            )
        else:
            self.win.FindName("lbl_kofi_missing").Visibility = Visibility.Visible

        img_pp = self.win.FindName("img_pp_qr")
        if self.pp_bmp is not None:
            img_pp.Source = self.pp_bmp
            self.win.FindName("bdr_pp_qr").MouseLeftButtonUp += lambda s, a: self._zoom_qr(
                "PromptPay QR - PERMPONG TAWEEKUL", self.pp_bmp
            )
        else:
            self.win.FindName("lbl_pp_missing").Visibility = Visibility.Visible

        self.lbl_toast = self.win.FindName("lbl_toast")
        self.win.FindName("btn_kofi").Click += lambda s, a: script.open_url(KOFI_URL)
        self.win.FindName("btn_copy_kofi").Click += self._copy_kofi_link
        self.win.FindName("btn_sponsors").Click += lambda s, a: script.open_url(GITHUB_SPONSORS_URL)
        self.win.FindName("btn_suggest_idea").Click += self._open_idea_dialog
        self.win.FindName("btn_star_github").Click += lambda s, a: script.open_url(GITHUB_REPO_URL)
        self.win.FindName("btn_copy_repo").Click += self._copy_repo_link
        self.win.FindName("btn_close").Click += lambda s, a: self.win.Close()

    def _copy_kofi_link(self, sender, args):
        try:
            Clipboard.SetText(KOFI_URL)
            self.lbl_toast.Text = "Copied ko-fi.com/permpong13!"
        except Exception:
            pass

    def _copy_repo_link(self, sender, args):
        try:
            Clipboard.SetText(GITHUB_REPO_URL)
            self.lbl_toast.Text = "Copied github.com/permpong13/P13!"
        except Exception:
            pass

    def _zoom_qr(self, title_text, bmp):
        zwin = XamlReader.Parse(QR_ZOOM_XAML)
        zwin.Owner = self.win
        zwin.FindName("lbl_qr_title").Text = title_text
        zwin.FindName("img_zoom").Source = bmp
        zwin.FindName("btn_close_zoom").Click += lambda s, a: zwin.Close()
        zwin.ShowDialog()

    def _open_idea_dialog(self, sender, args):
        iwin = XamlReader.Parse(IDEA_LAB_XAML)
        iwin.Owner = self.win
        cmb = iwin.FindName("cmb_cat")
        txt_title = iwin.FindName("txt_idea_title")
        txt_desc = iwin.FindName("txt_idea_desc")

        def _format_idea():
            cat = cmb.SelectedItem.Content if cmb.SelectedItem else "General"
            t = (txt_title.Text or "").strip() or "New Revit Tool Suggestion"
            d = (txt_desc.Text or "").strip() or "-"
            revit_ver = HOST_APP.version if HOST_APP else "Revit"
            body = "[Category] {0}\n[Revit] {1}\n[Idea] {2}\n\n{3}".format(cat, revit_ver, t, d)
            return t, body

        def _on_kofi_idea(s, a):
            _, body = _format_idea()
            try:
                Clipboard.SetText(body)
            except Exception:
                pass
            script.open_url(KOFI_URL)
            iwin.Close()
            self.lbl_toast.Text = "Idea copied! Paste (Ctrl+V) in your Ko-fi message."

        def _on_github_idea(s, a):
            t, body = _format_idea()
            url = "{0}?title={1}&body={2}".format(
                GITHUB_ISSUES_NEW_URL,
                url_quote("[Tool Idea] " + t.encode("utf-8") if sys.version_info[0] < 3 else "[Tool Idea] " + t),
                url_quote(body.encode("utf-8") if sys.version_info[0] < 3 else body)
            )
            script.open_url(url)
            iwin.Close()

        iwin.FindName("btn_idea_kofi").Click += _on_kofi_idea
        iwin.FindName("btn_idea_github").Click += _on_github_idea
        iwin.FindName("btn_idea_close").Click += lambda s, a: iwin.Close()
        iwin.ShowDialog()

    def show(self):
        self.win.ShowDialog()


def main():
    is_shift = bool(getattr(EXEC_PARAMS, "config_mode", False)) or bool(globals().get("__shiftclick__", False))
    if is_shift:
        script.open_url(KOFI_URL)
        return

    bundle_dir = os.path.dirname(os.path.abspath(__file__))
    SupportP13Controller(bundle_dir).show()


if __name__ == "__main__":
    main()
else:
    main()
