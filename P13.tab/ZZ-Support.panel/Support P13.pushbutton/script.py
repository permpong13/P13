# -*- coding: utf-8 -*-
# pylint: disable=import-error,invalid-name,broad-except,too-many-lines,too-many-instance-attributes
"""Support P13.extension - Clean Open-Source Supporter Hub (Ko-fi + GitHub + PromptPay)."""
from __future__ import print_function

import os
import sys

try:
    from urllib import quote as _url_quote
except ImportError:
    from urllib.parse import quote as _url_quote

import clr
clr.AddReference("System")
clr.AddReference("System.Xml")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")

import System
from System import Uri
from System.Windows import Clipboard
from System.Windows import Visibility
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Markup import XamlReader
from System.Windows.Media.Imaging import BitmapCacheOption
from System.Windows.Media.Imaging import BitmapCreateOptions
from System.Windows.Media.Imaging import BitmapImage

from pyrevit import EXEC_PARAMS
from pyrevit import forms
from pyrevit import script

try:
    from pyrevit import HOST_APP
except Exception:
    HOST_APP = None


# ------------------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------------------
KOFI_URL = "https://ko-fi.com/permpong13"
GITHUB_SPONSORS_URL = "https://github.com/sponsors/permpong13"
GITHUB_REPO_URL = "https://github.com/permpong13/P13"
GITHUB_NEW_IDEA_URL = "https://github.com/permpong13/P13/issues/new"

PY2 = sys.version_info[0] < 3
TEXT_TYPE = unicode if PY2 else str  # noqa: F821


def to_text(val):
    if val is None:
        return u""
    if isinstance(val, TEXT_TYPE):
        return val
    try:
        return val.decode("utf-8")
    except Exception:
        return TEXT_TYPE(val)


def url_encode(text_val):
    u_txt = to_text(text_val)
    if PY2:
        return _url_quote(u_txt.encode("utf-8"))
    return _url_quote(u_txt)


def load_unlocked_image(img_path):
    """Load PNG into memory and close file handle immediately so Update never locks."""
    if not img_path or not os.path.isfile(img_path):
        return None
    try:
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.CreateOptions = BitmapCreateOptions.IgnoreImageCache
        bmp.UriSource = Uri(os.path.abspath(img_path))
        bmp.EndInit()
        bmp.Freeze()
        return bmp
    except Exception:
        return None


def attach_owner(win, parent_win=None):
    try:
        if parent_win is not None:
            win.Owner = parent_win
            return
        hwnd = HOST_APP.uiapp.MainWindowHandle if HOST_APP else System.IntPtr.Zero
        if hwnd == System.IntPtr.Zero:
            hwnd = System.Diagnostics.Process.GetCurrentProcess().MainWindowHandle
        if hwnd != System.IntPtr.Zero:
            WindowInteropHelper(win).Owner = hwnd
    except Exception:
        pass


# ------------------------------------------------------------------------------
# XAML: QR ZOOM PREVIEW DIALOG
# ------------------------------------------------------------------------------
QR_ZOOM_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Scan QR Code" Width="460" Height="530"
        WindowStartupLocation="CenterOwner" ResizeMode="NoResize"
        Background="#FFFFFF" FontFamily="Segoe UI">
    <Grid Margin="20">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <TextBlock Name="lbl_qr_title" FontSize="18" FontWeight="Bold" Foreground="#111827"
                   HorizontalAlignment="Center"/>
        <TextBlock Name="lbl_qr_sub" Grid.Row="1" FontSize="12" Foreground="#6B7280"
                   HorizontalAlignment="Center" Margin="0,3,0,10"/>
        <Border Grid.Row="2" BorderBrush="#E5E7EB" BorderThickness="1" CornerRadius="8"
                Padding="12" Background="#FAFAFA">
            <Image Name="img_qr_large" Stretch="Uniform"/>
        </Border>
        <StackPanel Grid.Row="3" Orientation="Horizontal" HorizontalAlignment="Center" Margin="0,14,0,0">
            <Button Name="btn_qr_open_url" Content="Open in Browser" Height="30" Padding="14,0"
                    Margin="0,0,8,0" Visibility="Collapsed"/>
            <Button Name="btn_qr_close" Content="Close" Width="100" Height="30" IsCancel="True"/>
        </StackPanel>
    </Grid>
</Window>
"""


# ------------------------------------------------------------------------------
# XAML: COMMUNITY IDEA BOX DIALOG
# ------------------------------------------------------------------------------
IDEA_BOX_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Share a Revit Workflow Idea"
        Width="580" Height="510" MinWidth="520" MinHeight="450"
        WindowStartupLocation="CenterOwner"
        Background="#F3F4F6" FontFamily="Segoe UI" FontSize="12"
        UseLayoutRounding="True" SnapsToDevicePixels="True">
    <Grid Margin="18">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <StackPanel Grid.Row="0" Margin="0,0,0,12">
            <TextBlock Text="Share a Script Idea for P13.extension" FontSize="17" FontWeight="Bold" Foreground="#111827"/>
            <TextBlock Text="Tell us about a repetitive Revit task that slows you down. Community ideas help guide future open-source releases."
                       Foreground="#4B5563" TextWrapping="Wrap" Margin="0,4,0,0"/>
        </StackPanel>

        <Grid Grid.Row="1" Margin="0,0,0,10">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="195"/>
                <ColumnDefinition Width="12"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <StackPanel Grid.Column="0">
                <TextBlock Text="Category:" FontWeight="SemiBold" Margin="0,0,0,4"/>
                <ComboBox Name="cmb_category" Height="26" SelectedIndex="0">
                    <ComboBoxItem Content="Sheets, Views &amp; Plotting"/>
                    <ComboBoxItem Content="Filters &amp; Visibility/Graphics"/>
                    <ComboBoxItem Content="Structure, Rebar &amp; Grids"/>
                    <ComboBoxItem Content="Architecture &amp; Modeling"/>
                    <ComboBoxItem Content="MEP Systems"/>
                    <ComboBoxItem Content="Schedules, Parameters &amp; Excel"/>
                    <ComboBoxItem Content="QA/QC &amp; Model Cleanup"/>
                </ComboBox>
            </StackPanel>
            <StackPanel Grid.Column="2">
                <TextBlock Text="Your Name / Handle (Optional - for credit):" FontWeight="SemiBold" Margin="0,0,0,4"/>
                <TextBox Name="txt_author" Height="26" VerticalContentAlignment="Center" Padding="6,0"/>
            </StackPanel>
        </Grid>

        <StackPanel Grid.Row="2" Margin="0,0,0,10">
            <TextBlock Text="Idea Summary:" FontWeight="SemiBold" Margin="0,0,0,4"/>
            <TextBox Name="txt_idea_title" Height="26" VerticalContentAlignment="Center" Padding="6,0"/>
        </StackPanel>

        <Grid Grid.Row="3" Margin="0,0,0,10">
            <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="*"/>
            </Grid.RowDefinitions>
            <TextBlock Text="Workflow Description (What manual steps would this save?):" FontWeight="SemiBold" Margin="0,0,0,4"/>
            <TextBox Name="txt_idea_desc" Grid.Row="1" AcceptsReturn="True" TextWrapping="Wrap"
                     VerticalScrollBarVisibility="Auto" Padding="6"/>
        </Grid>

        <TextBlock Grid.Row="4" Foreground="#6B7280" FontSize="11" TextWrapping="Wrap" Margin="0,0,0,12"
                   Text="Note: Post directly on our GitHub board, or copy your note to include with a coffee on Ko-fi!"/>

        <Grid Grid.Row="5">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="Auto"/>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <Button Name="btn_idea_cancel" Content="Cancel" Width="76" Height="30" IsCancel="True"/>
            <StackPanel Grid.Column="2" Orientation="Horizontal">
                <Button Name="btn_idea_github" Content="Post on GitHub Issues" Height="30" Padding="12,0" Margin="0,0,8,0"
                        Background="#FFFFFF" BorderBrush="#D1D5DB"/>
                <Button Name="btn_idea_kofi" Content="Copy Note &amp; Open Ko-fi" Height="30" Padding="14,0"
                        Background="#FF5E5B" Foreground="#FFFFFF" FontWeight="SemiBold" BorderThickness="0"/>
            </StackPanel>
        </Grid>
    </Grid>
</Window>
"""


# ------------------------------------------------------------------------------
# XAML: MAIN SUPPORT P13 WINDOW
# ------------------------------------------------------------------------------
SUPPORT_WINDOW_XAML = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Support P13.extension"
        Width="780" Height="680" MinWidth="680" MinHeight="600"
        WindowStartupLocation="CenterScreen"
        Background="#F3F4F6" FontFamily="Segoe UI" FontSize="12"
        UseLayoutRounding="True" SnapsToDevicePixels="True">
    <Window.Resources>
        <Style x:Key="ActionBtn" TargetType="Button">
            <Setter Property="Height" Value="30"/>
            <Setter Property="Padding" Value="12,0"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="BorderThickness" Value="1"/>
            <Setter Property="FontWeight" Value="SemiBold"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Name="bdr" Background="{TemplateBinding Background}"
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

    <Grid Margin="18">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- 1. Header -->
        <Grid Grid.Row="0">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <StackPanel Grid.Column="0">
                <StackPanel Orientation="Horizontal">
                    <TextBlock Text="Support P13.extension" FontSize="21" FontWeight="Bold" Foreground="#111827"/>
                    <Border Background="#DCFCE7" BorderBrush="#86EFAC" BorderThickness="1"
                            CornerRadius="4" Padding="7,2" Margin="10,0,0,0" VerticalAlignment="Center">
                        <TextBlock Text="100% FREE &amp; OPEN-SOURCE" FontSize="10.5" FontWeight="Bold" Foreground="#166534"/>
                    </Border>
                </StackPanel>
                <TextBlock Text="Developed by Permpong Thawikul (P13). Every tool is unlocked and free for everyone - your optional support keeps updates alive!"
                           Foreground="#4B5563" TextWrapping="Wrap" Margin="0,4,12,0"/>
            </StackPanel>
            <StackPanel Grid.Column="1" Orientation="Horizontal" VerticalAlignment="Top">
                <Button Name="btn_star_repo" Style="{StaticResource ActionBtn}"
                        Content="Star on GitHub" Background="#FFFFFF" Foreground="#1F2937" BorderBrush="#D1D5DB" Margin="0,0,6,0"/>
                <Button Name="btn_share_link" Style="{StaticResource ActionBtn}"
                        Content="Copy Repo Link" Background="#FFFFFF" Foreground="#0284C7" BorderBrush="#93C5FD"/>
            </StackPanel>
        </Grid>

        <!-- 2. Global Instant Support Card (Ko-fi Stripe + GitHub Sponsors) -->
        <Border Grid.Row="1" Background="#FFFFFF" BorderBrush="#E5E7EB" BorderThickness="1"
                CornerRadius="8" Padding="14,12" Margin="0,12,0,10">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <StackPanel Grid.Column="0" Margin="0,0,12,0">
                    <TextBlock Text="Worldwide Support (Card / Apple Pay / Google Pay / GitHub)" FontSize="14" FontWeight="Bold" Foreground="#111827"/>
                    <TextBlock Text="Fast global checkout via Ko-fi powered by Stripe (no account needed) or via GitHub Sponsors."
                               Foreground="#4B5563" TextWrapping="Wrap" Margin="0,3,0,0"/>
                </StackPanel>
                <StackPanel Grid.Column="1" Orientation="Horizontal" VerticalAlignment="Center">
                    <Button Name="btn_kofi" Style="{StaticResource ActionBtn}"
                            Content="Support on Ko-fi" Background="#FF5E5B" Foreground="#FFFFFF" BorderBrush="#FF5E5B" Margin="0,0,6,0"/>
                    <Button Name="btn_copy_kofi" Style="{StaticResource ActionBtn}"
                            Content="Copy URL" Background="#F9FAFB" Foreground="#374151" BorderBrush="#D1D5DB" Margin="0,0,6,0"
                            ToolTip="Copy https://ko-fi.com/permpong13"/>
                    <Button Name="btn_sponsors" Style="{StaticResource ActionBtn}"
                            Content="GitHub Sponsors" Background="#24292F" Foreground="#FFFFFF" BorderBrush="#24292F"/>
                </StackPanel>
            </Grid>
        </Border>

        <!-- 3. Community Workflow Idea Banner -->
        <Border Grid.Row="2" Background="#EFF6FF" BorderBrush="#BFDBFE" BorderThickness="1"
                CornerRadius="8" Padding="14,9" Margin="0,0,0,10">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <TextBlock Grid.Column="0" Foreground="#1E3A8A" VerticalAlignment="Center" TextWrapping="Wrap" Margin="0,0,10,0"
                           Text="Have an idea for a Revit script that isn't in P13 yet? Share your workflow pain points with us!"/>
                <Button Name="btn_open_ideabox" Grid.Column="1" Style="{StaticResource ActionBtn}"
                        Content="Suggest a Tool Idea" Background="#1D4ED8" Foreground="#FFFFFF" BorderBrush="#1D4ED8"/>
            </Grid>
        </Border>

        <!-- 4. QR Cards (Ko-fi Mobile QR Worldwide & PromptPay Thailand/ASEAN) -->
        <Grid Grid.Row="3">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="12"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>

            <!-- Left Card: Ko-fi QR (Worldwide Phone Camera -> Apple Pay / Google Pay / Card) -->
            <Border Grid.Column="0" Background="#FFFFFF" BorderBrush="#E5E7EB" BorderThickness="1" CornerRadius="8" Padding="12">
                <Grid>
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="*"/>
                        <RowDefinition Height="Auto"/>
                    </Grid.RowDefinitions>
                    <TextBlock Text="Ko-fi Mobile QR (Worldwide)" FontSize="14.5" FontWeight="Bold" Foreground="#D9383A" HorizontalAlignment="Center"/>
                    <TextBlock Grid.Row="1" Text="Scan with Phone Camera - Apple Pay / Google Pay / Card" FontSize="11" Foreground="#6B7280" HorizontalAlignment="Center" Margin="0,2,0,6"/>
                    <Border Name="bdr_kofi_qr" Grid.Row="2" Background="#FAFAFA" BorderBrush="#F3F4F6" BorderThickness="1" CornerRadius="6" Padding="8" Cursor="Hand"
                            ToolTip="Click to enlarge QR Code or open Ko-fi">
                        <Grid>
                            <Image Name="img_kofi" Stretch="Uniform" HorizontalAlignment="Center" VerticalAlignment="Center"/>
                            <StackPanel Name="pnl_kofi_fallback" VerticalAlignment="Center" HorizontalAlignment="Center" Visibility="Collapsed" Margin="12">
                                <TextBlock Text="Support on Mobile or Desktop" FontSize="13.5" FontWeight="Bold" Foreground="#111827" HorizontalAlignment="Center"/>
                                <TextBlock Text="Accepts Visa, Mastercard, Apple Pay &amp; Google Pay worldwide with no login required."
                                           Foreground="#4B5563" TextWrapping="Wrap" TextAlignment="Center" Margin="0,6,0,12"/>
                                <Button Name="btn_kofi_card_fallback" Style="{StaticResource ActionBtn}"
                                        Content="Open ko-fi.com/permpong13" Background="#FF5E5B" Foreground="#FFFFFF" BorderBrush="#FF5E5B"
                                        HorizontalAlignment="Center"/>
                                <TextBlock Text="(Add qr_kofi.png to button folder to display scannable QR)"
                                           FontSize="10" Foreground="#9CA3AF" HorizontalAlignment="Center" Margin="0,10,0,0"/>
                            </StackPanel>
                        </Grid>
                    </Border>
                    <TextBlock Grid.Row="3" Text="ko-fi.com/permpong13 (Stripe Verified)" FontSize="11" FontWeight="SemiBold"
                               Foreground="#374151" HorizontalAlignment="Center" Margin="0,6,0,0"/>
                </Grid>
            </Border>

            <!-- Right Card: PromptPay / ASEAN Cross-Border QR -->
            <Border Grid.Column="2" Background="#FFFFFF" BorderBrush="#E5E7EB" BorderThickness="1" CornerRadius="8" Padding="12">
                <Grid>
                    <Grid.RowDefinitions>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="Auto"/>
                        <RowDefinition Height="*"/>
                        <RowDefinition Height="Auto"/>
                    </Grid.RowDefinitions>
                    <TextBlock Text="PromptPay / ASEAN QR" FontSize="14.5" FontWeight="Bold" Foreground="#113566" HorizontalAlignment="Center"/>
                    <TextBlock Grid.Row="1" Text="Thai Banking &amp; Cross-Border QR (Click QR to enlarge)" FontSize="11" Foreground="#6B7280" HorizontalAlignment="Center" Margin="0,2,0,6"/>
                    <Border Name="bdr_promptpay_qr" Grid.Row="2" Background="#FAFAFA" BorderBrush="#F3F4F6" BorderThickness="1" CornerRadius="6" Padding="8" Cursor="Hand"
                            ToolTip="Click to enlarge PromptPay QR Code">
                        <Grid>
                            <Image Name="img_promptpay" Stretch="Uniform" HorizontalAlignment="Center" VerticalAlignment="Center"/>
                            <TextBlock Name="lbl_no_promptpay" Text="qr_promptpay.png not found" Foreground="#9CA3AF"
                                       HorizontalAlignment="Center" VerticalAlignment="Center" Visibility="Collapsed"/>
                        </Grid>
                    </Border>
                    <TextBlock Name="lbl_promptpay_acct" Grid.Row="3" Text="PERMPONG TAWEEKUL" FontSize="11" FontWeight="SemiBold"
                               Foreground="#374151" HorizontalAlignment="Center" Margin="0,6,0,0"/>
                </Grid>
            </Border>
        </Grid>

        <!-- 5. Status Feedback -->
        <TextBlock Name="lbl_feedback" Grid.Row="4" Text="" Foreground="#059669" FontWeight="SemiBold"
                   Margin="4,8,4,0" Visibility="Collapsed"/>

        <!-- 6. Footer -->
        <Border Grid.Row="5" BorderBrush="#E5E7EB" BorderThickness="0,1,0,0" Padding="0,10,0,0" Margin="0,10,0,0">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <TextBlock Text="Thank you for using P13.extension and sharing it with fellow engineers!"
                           Foreground="#6B7280" VerticalAlignment="Center"/>
                <Button Name="btn_close" Grid.Column="1" Style="{StaticResource ActionBtn}"
                        Content="Close" Width="90" Background="#E5E7EB" Foreground="#111827" BorderBrush="#D1D5DB" IsCancel="True"/>
            </Grid>
        </Border>
    </Grid>
</Window>
"""


# ------------------------------------------------------------------------------
# DIALOG CONTROLLERS
# ------------------------------------------------------------------------------
class IdeaBoxDialog(object):
    def __init__(self, parent_win):
        self.win = XamlReader.Parse(IDEA_BOX_XAML)
        attach_owner(self.win, parent_win)
        self.submitted_mode = None

        self.cmb_category = self.win.FindName("cmb_category")
        self.txt_author = self.win.FindName("txt_author")
        self.txt_idea_title = self.win.FindName("txt_idea_title")
        self.txt_idea_desc = self.win.FindName("txt_idea_desc")

        try:
            if HOST_APP and HOST_APP.username:
                self.txt_author.Text = to_text(HOST_APP.username)
        except Exception:
            pass

        self.win.FindName("btn_idea_kofi").Click += self._on_copy_and_kofi
        self.win.FindName("btn_idea_github").Click += self._on_post_github
        self.win.FindName("btn_idea_cancel").Click += lambda s, a: self.win.Close()

    def _build_idea_text(self):
        cat_item = self.cmb_category.SelectedItem
        cat = to_text(cat_item.Content) if cat_item else u"General"
        title = to_text(self.txt_idea_title.Text).strip()
        desc = to_text(self.txt_idea_desc.Text).strip()
        author = to_text(self.txt_author.Text).strip() or u"Community User"

        if not title:
            forms.alert("Please enter a short Idea Summary.", title="Suggest a Tool Idea")
            return None, None, None

        gh_title = u"[Tool Idea] {} ({})".format(title, cat)
        gh_body = u"\n".join([
            u"### Tool Idea for P13.extension",
            u"- **Category:** {}".format(cat),
            u"- **Suggested By:** {}".format(author),
            u"",
            u"### Workflow / Problem to Automate",
            desc or u"(No extra details)"
        ])
        kofi_note = u"[Idea: {} - {}] {} (from {})".format(
            cat, title, desc if desc else u"Hope this helps inspire a future tool!", author
        )
        return gh_title, gh_body, kofi_note

    def _on_copy_and_kofi(self, _sender, _args):
        gh_title, _gh_body, kofi_note = self._build_idea_text()
        if not gh_title:
            return
        try:
            Clipboard.SetText(kofi_note)
        except Exception:
            pass
        script.open_url(KOFI_URL)
        self.submitted_mode = "kofi"
        self.win.Close()

    def _on_post_github(self, _sender, _args):
        gh_title, gh_body, _note = self._build_idea_text()
        if not gh_title:
            return
        target_url = "{}?title={}&body={}".format(
            GITHUB_NEW_IDEA_URL,
            url_encode(gh_title),
            url_encode(gh_body)
        )
        script.open_url(target_url)
        self.submitted_mode = "github"
        self.win.Close()

    def show_dialog(self):
        self.win.ShowDialog()
        return self.submitted_mode


class SupportCleanDialog(object):
    def __init__(self, kofi_qr_path, promptpay_qr_path):
        self.win = XamlReader.Parse(SUPPORT_WINDOW_XAML)
        attach_owner(self.win)

        self.kofi_bmp = load_unlocked_image(kofi_qr_path)
        self.promptpay_bmp = load_unlocked_image(promptpay_qr_path)

        for cname in [
            "btn_star_repo", "btn_share_link",
            "btn_kofi", "btn_copy_kofi", "btn_sponsors",
            "btn_open_ideabox",
            "bdr_kofi_qr", "img_kofi", "pnl_kofi_fallback", "btn_kofi_card_fallback",
            "bdr_promptpay_qr", "img_promptpay", "lbl_no_promptpay", "lbl_promptpay_acct",
            "lbl_feedback", "btn_close"
        ]:
            setattr(self, cname, self.win.FindName(cname))

        thai_name = u"\u0e19\u0e32\u0e22 \u0e40\u0e1e\u0e34\u0e48\u0e21\u0e1e\u0e07\u0e29\u0e4c \u0e17\u0e27\u0e35\u0e01\u0e38\u0e25"
        self.lbl_promptpay_acct.Text = u"PERMPONG TAWEEKUL ({})".format(thai_name)

        self._bind_qr_images()

        self.btn_kofi.Click += self._on_open_kofi
        self.btn_kofi_card_fallback.Click += self._on_open_kofi
        self.btn_copy_kofi.Click += self._on_copy_kofi
        self.btn_sponsors.Click += self._on_open_sponsors
        self.btn_open_ideabox.Click += self._on_open_ideabox
        self.btn_star_repo.Click += self._on_open_repo
        self.btn_share_link.Click += self._on_copy_repo
        self.btn_close.Click += lambda s, a: self.win.Close()

    def _bind_qr_images(self):
        if self.kofi_bmp is not None:
            self.img_kofi.Source = self.kofi_bmp
            self.bdr_kofi_qr.MouseLeftButtonUp += lambda s, a: self._zoom_qr(
                "Ko-fi Mobile QR (Worldwide)",
                "Scan with phone camera for Apple Pay, Google Pay, or Card",
                self.kofi_bmp,
                KOFI_URL
            )
        else:
            self.img_kofi.Visibility = Visibility.Collapsed
            self.pnl_kofi_fallback.Visibility = Visibility.Visible

        if self.promptpay_bmp is not None:
            self.img_promptpay.Source = self.promptpay_bmp
            self.bdr_promptpay_qr.MouseLeftButtonUp += lambda s, a: self._zoom_qr(
                "PromptPay / ASEAN QR",
                "Thai Banking Apps & Supported Cross-Border QR",
                self.promptpay_bmp,
                None
            )
        else:
            self.lbl_no_promptpay.Visibility = Visibility.Visible

    def _zoom_qr(self, title_str, sub_str, bmp, target_url=None):
        zwin = XamlReader.Parse(QR_ZOOM_XAML)
        attach_owner(zwin, self.win)
        zwin.FindName("lbl_qr_title").Text = to_text(title_str)
        zwin.FindName("lbl_qr_sub").Text = to_text(sub_str)
        zwin.FindName("img_qr_large").Source = bmp

        btn_url = zwin.FindName("btn_qr_open_url")
        if target_url:
            btn_url.Visibility = Visibility.Visible
            btn_url.Click += lambda s, a: script.open_url(target_url)

        zwin.FindName("btn_qr_close").Click += lambda s, a: zwin.Close()
        zwin.ShowDialog()

    def _show_feedback(self, msg):
        self.lbl_feedback.Text = to_text(msg)
        self.lbl_feedback.Visibility = Visibility.Visible

    def _on_open_ideabox(self, _sender, _args):
        dlg = IdeaBoxDialog(self.win)
        mode = dlg.show_dialog()
        if mode == "kofi":
            self._show_feedback(u"Idea note copied to clipboard & Ko-fi opened! Paste (Ctrl+V) into your message.")
        elif mode == "github":
            self._show_feedback(u"Opened GitHub Issues with your idea pre-filled. Thank you!")

    def _on_open_kofi(self, _sender, _args):
        script.open_url(KOFI_URL)
        self._show_feedback(u"Opened Ko-fi in your browser. Thank you for your kindness!")

    def _on_copy_kofi(self, _sender, _args):
        try:
            Clipboard.SetText(KOFI_URL)
            self._show_feedback(u"Copied '{}' to clipboard!".format(KOFI_URL))
        except Exception:
            script.open_url(KOFI_URL)

    def _on_open_sponsors(self, _sender, _args):
        script.open_url(GITHUB_SPONSORS_URL)
        self._show_feedback(u"Opened GitHub Sponsors in your browser.")

    def _on_open_repo(self, _sender, _args):
        script.open_url(GITHUB_REPO_URL)
        self._show_feedback(u"Opened GitHub repository - clicking 'Star' top-right helps P13 reach more engineers!")

    def _on_copy_repo(self, _sender, _args):
        try:
            Clipboard.SetText(GITHUB_REPO_URL)
            self._show_feedback(u"Copied '{}' to clipboard!".format(GITHUB_REPO_URL))
        except Exception:
            script.open_url(GITHUB_REPO_URL)

    def show_dialog(self):
        self.win.ShowDialog()


def main():
    is_shift = bool(getattr(EXEC_PARAMS, "config_mode", False)) or bool(globals().get("__shiftclick__", False))
    if is_shift:
        script.open_url(KOFI_URL)
        return

    current_dir = os.path.dirname(os.path.abspath(__file__))
    kofi_qr_path = os.path.join(current_dir, "qr_kofi.png")
    promptpay_qr_path = os.path.join(current_dir, "qr_promptpay.png")

    try:
        dlg = SupportCleanDialog(kofi_qr_path, promptpay_qr_path)
        dlg.show_dialog()
    except Exception as exc:
        forms.alert("Could not open Support P13 window:\n{}".format(exc), title="Support P13")


main()
