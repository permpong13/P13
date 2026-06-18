# -*- coding: utf-8 -*-
from __future__ import print_function

import codecs
import os
import tempfile

from pyrevit import forms, script


GITHUB_REPO_URL = "https://github.com/permpong13/P13"


class DonateWindow(forms.WPFWindow):
    def __init__(self, paypal_qr_path, promptpay_qr_path):
        self.temp_xaml = os.path.join(tempfile.gettempdir(), "P13_DonateWindow.xaml")

        xaml = """
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Support p13.extension"
        Width="700"
        Height="650"
        WindowStartupLocation="CenterScreen"
        ResizeMode="NoResize"
        Background="#F2F2F7">
    <Window.Resources>
        <Style TargetType="Button">
            <Setter Property="Height" Value="34"/>
            <Setter Property="Padding" Value="16,0"/>
            <Setter Property="Margin" Value="4"/>
            <Setter Property="BorderThickness" Value="0"/>
            <Setter Property="Cursor" Value="Hand"/>
            <Setter Property="Template">
                <Setter.Value>
                    <ControlTemplate TargetType="Button">
                        <Border Background="{{TemplateBinding Background}}"
                                CornerRadius="7"
                                Padding="{{TemplateBinding Padding}}">
                            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
                        </Border>
                    </ControlTemplate>
                </Setter.Value>
            </Setter>
            <Style.Triggers>
                <Trigger Property="IsMouseOver" Value="True">
                    <Setter Property="Opacity" Value="0.85"/>
                </Trigger>
            </Style.Triggers>
        </Style>
    </Window.Resources>

    <Grid Margin="18">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <StackPanel Grid.Row="0">
            <TextBlock Text="Support p13.extension"
                       FontSize="24"
                       FontWeight="SemiBold"
                       Foreground="#1D1D1F"/>
            <TextBlock Text="Thank you for supporting development and maintenance."
                       Foreground="#6E6E73"
                       Margin="0,4,0,0"/>
        </StackPanel>

        <Border Grid.Row="1"
                Background="White"
                BorderBrush="#E5E5EA"
                BorderThickness="1"
                CornerRadius="10"
                Padding="12"
                Margin="0,14,0,12">
            <Grid>
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <StackPanel Grid.Column="0">
                    <TextBlock Text="GitHub Repository"
                               FontWeight="SemiBold"
                               Foreground="#1D1D1F"/>
                    <TextBlock Text="https://github.com/permpong13/P13"
                               Foreground="#007AFF"
                               Margin="0,4,0,0"/>
                </StackPanel>
                <Button Grid.Column="1"
                        x:Name="btnOpenGithub"
                        Content="Open in Browser"
                        Background="#007AFF"
                        Foreground="White"/>
            </Grid>
        </Border>

        <Grid Grid.Row="2">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="14"/>
                <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>

            <Border Grid.Column="0" Background="White" BorderBrush="#E5E5EA" BorderThickness="1" CornerRadius="10" Padding="14">
                <StackPanel HorizontalAlignment="Center">
                    <TextBlock Text="PayPal" FontSize="16" FontWeight="SemiBold" HorizontalAlignment="Center" Margin="0,0,0,8"/>
                    <Border Width="290" Height="340" ClipToBounds="False">
                        <Image Source="{paypal}" Stretch="Uniform"/>
                    </Border>
                </StackPanel>
            </Border>

            <Border Grid.Column="2" Background="White" BorderBrush="#E5E5EA" BorderThickness="1" CornerRadius="10" Padding="14">
                <StackPanel HorizontalAlignment="Center">
                    <TextBlock Text="PromptPay" FontSize="16" FontWeight="SemiBold" HorizontalAlignment="Center" Margin="0,0,0,8"/>
                    <Border Width="290" Height="340" ClipToBounds="False">
                        <Image Source="{promptpay}" Stretch="Uniform"/>
                    </Border>
                </StackPanel>
            </Border>
        </Grid>

        <StackPanel Grid.Row="3" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,14,0,0">
            <Button x:Name="btnClose"
                    Content="Close"
                    Background="#E5E5EA"
                    Foreground="#1D1D1F"/>
        </StackPanel>
    </Grid>
</Window>
""".format(paypal=paypal_qr_path, promptpay=promptpay_qr_path)

        with codecs.open(self.temp_xaml, "w", encoding="utf-8-sig") as xaml_file:
            xaml_file.write(xaml)

        forms.WPFWindow.__init__(self, self.temp_xaml)
        self.btnOpenGithub.Click += self.open_github_click
        self.btnClose.Click += self.close_click

    def open_github_click(self, sender, args):
        script.open_url(GITHUB_REPO_URL)

    def close_click(self, sender, args):
        self.Close()


def main():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paypal_qr_path = os.path.join(current_dir, "qr_paypal.png")
    promptpay_qr_path = os.path.join(current_dir, "qr_promptpay.png")

    window = DonateWindow(paypal_qr_path, promptpay_qr_path)
    window.ShowDialog()


if __name__ == "__main__":
    main()
