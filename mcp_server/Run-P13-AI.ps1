param(
    [Parameter(Mandatory = $true)]
    [string]$RequestFile,

    [Parameter(Mandatory = $false)]
    [string]$UvPath = ""
)

$ErrorActionPreference = "Stop"

# The launcher process has no legacy console window. Surface bootstrap errors
# in a normal dialog so missing runtime files or startup failures stay visible.
trap {
    $errorMessage = $_.Exception.Message
    try {
        Add-Type -AssemblyName PresentationFramework -ErrorAction SilentlyContinue
        [System.Windows.MessageBox]::Show(
            "P13 AI Console could not start.`r`n`r`n$errorMessage",
            "P13 AI Console",
            [System.Windows.MessageBoxButton]::OK,
            [System.Windows.MessageBoxImage]::Error
        ) | Out-Null
    }
    catch {
        # There is no console fallback because this process is intentionally hidden.
    }
    exit 1
}

# Keep every boundary UTF-8. The WPF output window uses a Thai-capable font and
# does not depend on the limited glyph coverage of the legacy Console Host.
$utf8Encoding = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8Encoding
[Console]::OutputEncoding = $utf8Encoding
$OutputEncoding = $utf8Encoding
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$serverDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$agentPath = Join-Path $serverDirectory "ai_agent.py"
$logDirectory = Join-Path $env:APPDATA "pyRevit\P13\logs"
$logPath = Join-Path $logDirectory "ai_runner.log"

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

if (-not $UvPath) {
    $UvPath = (Get-Command "uv" -ErrorAction Stop).Source
}
if (-not (Test-Path -LiteralPath $UvPath -PathType Leaf)) {
    throw "uv.exe was not found at the path supplied by P13 AI Console: $UvPath"
}
if (-not (Test-Path -LiteralPath $RequestFile -PathType Leaf)) {
    throw "The AI request file was not found: $RequestFile"
}

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

$xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="P13 AI Console" Width="1000" Height="760"
        MinWidth="720" MinHeight="480" WindowStartupLocation="CenterScreen"
        Background="#082B5C" FontFamily="Tahoma">
    <Grid Margin="12">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <TextBlock Grid.Row="0" Text="P13 AI Console" Foreground="#7DD3FC"
                   FontSize="20" FontWeight="SemiBold" Margin="2,0,0,10"/>
        <TextBox x:Name="OutputBox" Grid.Row="1" IsReadOnly="True"
                 AcceptsReturn="True" AcceptsTab="True" TextWrapping="Wrap"
                 VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Auto"
                 Background="#082B5C" Foreground="White" BorderBrush="#25588E"
                 FontFamily="Tahoma" FontSize="16" Padding="10"/>
        <Grid Grid.Row="2" Margin="0,10,0,0">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <TextBlock x:Name="StatusText" Grid.Column="0" Text="Task is running..."
                       Foreground="#FDE68A" FontSize="14" VerticalAlignment="Center"/>
            <Button x:Name="CloseButton" Grid.Column="1" Content="Close"
                    Width="100" Height="32" IsEnabled="False"/>
        </Grid>
    </Grid>
</Window>
"@

$xmlReader = New-Object System.Xml.XmlNodeReader ([xml]$xaml)
$window = [Windows.Markup.XamlReader]::Load($xmlReader)
$outputBox = $window.FindName("OutputBox")
$statusText = $window.FindName("StatusText")
$closeButton = $window.FindName("CloseButton")

$jobToken = [Guid]::NewGuid().ToString("N")
$stdoutPath = Join-Path $env:TEMP "p13_ai_$jobToken.stdout.log"
$stderrPath = Join-Path $env:TEMP "p13_ai_$jobToken.stderr.log"
[System.IO.File]::WriteAllText($stdoutPath, "", $utf8Encoding)
[System.IO.File]::WriteAllText($stderrPath, "", $utf8Encoding)

function Append-OutputText {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) {
        return
    }
    $outputBox.AppendText($Text)
    $outputBox.ScrollToEnd()
    [System.IO.File]::AppendAllText($logPath, $Text, $utf8Encoding)
}

function Read-NewOutputText {
    param(
        [string]$Path,
        [ref]$PreviousLength
    )
    try {
        $text = [System.IO.File]::ReadAllText($Path, $utf8Encoding)
        if ($text.Length -gt $PreviousLength.Value) {
            $newText = $text.Substring($PreviousLength.Value)
            $PreviousLength.Value = $text.Length
            return $newText
        }
    }
    catch {
        # The child process can briefly lock a redirected file while flushing.
    }
    return ""
}

$header = "P13 AI Console`r`nThe AI task runs outside Revit and uses the secured P13 MCP tools.`r`n`r`n"
[System.IO.File]::AppendAllText(
    $logPath,
    "`r`n===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') =====`r`n",
    $utf8Encoding
)
Append-OutputText $header

$quotedAgentPath = '"' + $agentPath.Replace('"', '\"') + '"'
$quotedRequestFile = '"' + $RequestFile.Replace('"', '\"') + '"'
$processArguments = "run python $quotedAgentPath --request-file $quotedRequestFile"

$process = Start-Process -FilePath $UvPath `
    -ArgumentList $processArguments `
    -WorkingDirectory $serverDirectory `
    -NoNewWindow `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru

$script:stdoutLength = 0
$script:stderrLength = 0
$script:taskCompleted = $false
$script:allowWindowClose = $false

$timer = New-Object Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(200)
$timer.add_Tick({
    $standardError = Read-NewOutputText $stderrPath ([ref]$script:stderrLength)
    $standardOutput = Read-NewOutputText $stdoutPath ([ref]$script:stdoutLength)
    Append-OutputText $standardError
    Append-OutputText $standardOutput

    if (-not $script:taskCompleted -and $process.HasExited) {
        $process.WaitForExit()
        Append-OutputText (Read-NewOutputText $stderrPath ([ref]$script:stderrLength))
        Append-OutputText (Read-NewOutputText $stdoutPath ([ref]$script:stdoutLength))
        $script:taskCompleted = $true
        $closeButton.IsEnabled = $true

        if ($process.ExitCode -eq 0) {
            $statusText.Text = "Task finished successfully. You can close this window."
            $statusText.Foreground = "#86EFAC"
            Append-OutputText "`r`nTask finished successfully. You can close this window.`r`n"
        }
        else {
            $statusText.Text = "Task failed. Review the output above."
            $statusText.Foreground = "#FCA5A5"
            Append-OutputText "`r`nTask failed. Review the output above before closing this window.`r`n"
        }
        Append-OutputText "Runner log: $logPath`r`n"
    }
})

$closeButton.add_Click({
    $script:allowWindowClose = $true
    $window.Close()
})

$window.add_Closing({
    param($sender, $eventArgs)
    if (-not $script:taskCompleted -and -not $script:allowWindowClose) {
        $answer = [System.Windows.MessageBox]::Show(
            "The AI task is still running. Stop the task and close this window?",
            "P13 AI Console",
            [System.Windows.MessageBoxButton]::YesNo,
            [System.Windows.MessageBoxImage]::Warning
        )
        if ($answer -ne [System.Windows.MessageBoxResult]::Yes) {
            $eventArgs.Cancel = $true
            return
        }
        & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F 2>$null | Out-Null
        $script:allowWindowClose = $true
    }
})

$window.add_Closed({
    $timer.Stop()
    Remove-Item -LiteralPath $stdoutPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
})

$timer.Start()
$window.ShowDialog() | Out-Null
