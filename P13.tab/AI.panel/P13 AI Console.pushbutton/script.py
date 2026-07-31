# -*- coding: utf-8 -*-
from __future__ import print_function

__title__ = "P13 AI\nConsole"
__doc__ = (
    "Send natural-language Revit tasks to a selected AI provider and model "
    "through the secured P13 MCP tools."
)
__author__ = "P13"

import io
import json
import os
import re
import traceback

try:
    import clr

    # Revit does not guarantee that WPF assemblies are loaded before a pyRevit
    # command starts. Load them before importing System.Windows types.
    clr.AddReference("System")
    clr.AddReference("PresentationFramework")
    clr.AddReference("PresentationCore")
    clr.AddReference("WindowsBase")

    from pyrevit import forms, script

    from System import Environment, EnvironmentVariableTarget, Guid
    from System.Diagnostics import Process, ProcessStartInfo
    from System.IO import Directory, File, Path
    from System.Text import UTF8Encoding
    from System.Windows import MessageBox, MessageBoxButton, MessageBoxImage
    from System.Windows.Controls import ComboBoxItem
except Exception:
    # Import failures occur before the normal UI error handler exists. Persist
    # the traceback with Python I/O so a blank pyRevit output is diagnosable.
    try:
        bootstrap_root = os.path.join(
            os.environ.get("APPDATA") or os.path.expanduser("~"),
            "pyRevit",
            "P13",
        )
        if not os.path.isdir(bootstrap_root):
            os.makedirs(bootstrap_root)
        with io.open(
            os.path.join(bootstrap_root, "ai_console_bootstrap_error.log"),
            "w",
            encoding="utf-8",
        ) as bootstrap_log:
            bootstrap_log.write(traceback.format_exc())
    except Exception:
        pass
    raise


BUNDLE_DIRECTORY = os.path.dirname(__file__)
EXTENSION_ROOT = os.path.abspath(
    os.path.join(BUNDLE_DIRECTORY, os.pardir, os.pardir, os.pardir)
)
MCP_DIRECTORY = os.path.join(EXTENSION_ROOT, "mcp_server")
PROVIDERS_PATH = os.path.join(MCP_DIRECTORY, "ai_providers.json")
AGENT_PATH = os.path.join(MCP_DIRECTORY, "ai_agent.py")
RUNNER_PATH = os.path.join(MCP_DIRECTORY, "Run-P13-AI.ps1")
UI_PATH = script.get_bundle_file("ui.xaml")


def load_json(path):
    with io.open(path, "r", encoding="utf-8") as input_file:
        return json.load(input_file)


def get_environment_value(name):
    value = Environment.GetEnvironmentVariable(name)
    if value:
        return value
    try:
        return Environment.GetEnvironmentVariable(
            name, EnvironmentVariableTarget.User
        )
    except Exception:
        return None


def get_provider_credential(provider):
    for key_name in provider.get("api_key_env") or []:
        if get_environment_value(key_name):
            return key_name
    return None


def codex_cli_is_ready():
    local_appdata = Environment.GetFolderPath(
        Environment.SpecialFolder.LocalApplicationData
    )
    codex_root = os.path.join(local_appdata, "OpenAI", "Codex", "bin")
    auth_path = os.path.join(
        Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        ".codex",
        "auth.json",
    )
    return os.path.isdir(codex_root) and os.path.isfile(auth_path)


def provider_is_ready(provider):
    if not provider:
        return False
    if provider.get("protocol") == "codex_cli":
        return codex_cli_is_ready()
    if provider.get("requires_api_key"):
        return bool(get_provider_credential(provider))
    return True


def provider_uses_remote_service(provider, base_url):
    if not provider:
        return False
    if provider.get("protocol") == "codex_cli":
        return True
    normalized = str(base_url or "").strip().lower()
    return not (
        normalized.startswith("http://127.0.0.1")
        or normalized.startswith("https://127.0.0.1")
        or normalized.startswith("http://localhost")
        or normalized.startswith("https://localhost")
        or normalized.startswith("http://[::1]")
        or normalized.startswith("https://[::1]")
    )


def get_uv_path():
    candidates = [
        os.path.join(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".local",
            "bin",
            "uv.exe",
        ),
        os.path.join(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs",
            "uv",
            "uv.exe",
        ),
    ]
    path_value = Environment.GetEnvironmentVariable("PATH") or ""
    for directory in path_value.split(os.pathsep):
        if directory:
            candidates.append(os.path.join(directory.strip('"'), "uv.exe"))
    for candidate in candidates:
        if candidate and File.Exists(candidate):
            return candidate
    return None


def quote_argument(value):
    return '"{}"'.format(str(value).replace('"', '\\"'))


def message(text, title="P13 AI Console", image=MessageBoxImage.Information):
    MessageBox.Show(text, title, MessageBoxButton.OK, image)


def write_event_log(event_name, details=""):
    try:
        appdata = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData)
        log_directory = Path.Combine(appdata, "pyRevit", "P13", "logs")
        Directory.CreateDirectory(log_directory)
        log_path = Path.Combine(log_directory, "ai_console.log")
        safe_details = str(details or "").replace("\r", " ").replace("\n", " ")
        for pattern in (
            r"(?i)bearer\s+[A-Za-z0-9._~+/-]{16,}",
            r"gh[pousr]_[A-Za-z0-9_]{20,}",
            r"sk-[A-Za-z0-9_-]{16,}",
            r"AIza[0-9A-Za-z_-]{20,}",
        ):
            safe_details = re.sub(pattern, "[REDACTED]", safe_details)
        user_profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile)
        if user_profile:
            safe_details = safe_details.replace(user_profile, "%USERPROFILE%")
        line = "{} | {} | {}\r\n".format(
            __import__("datetime").datetime.utcnow().isoformat() + "Z",
            event_name,
            safe_details,
        )
        File.AppendAllText(log_path, line, UTF8Encoding(False))
        return log_path
    except Exception:
        return None


class AIConsoleWindow(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, UI_PATH)
        self._bind_events()
        write_event_log("window_initialized", "P13 AI Console XAML loaded")
        provider_data = load_json(PROVIDERS_PATH)
        self.providers = provider_data.get("providers") or []
        self.provider_lookup = {}
        self.provider_items = {}
        self.base_url_settings = {}
        self._loading = True
        self._load_settings()
        self._populate_providers()
        self._loading = False
        self._select_saved_provider()

    def toggle_maximize(self, sender=None, args=None):
        try:
            from System.Windows import WindowState
            if self.WindowState == WindowState.Maximized:
                self.WindowState = WindowState.Normal
            else:
                self.WindowState = WindowState.Maximized
        except Exception:
            pass

    def _bind_events(self):
        """Bind explicitly so event failures cannot be hidden by XAML loading."""
        if hasattr(self, "closeButton") and self.closeButton:
            self.closeButton.Click += lambda s, e: self.Close()
        if hasattr(self, "minimizeButton") and self.minimizeButton:
            def min_win(s, e):
                from System.Windows import WindowState
                self.WindowState = WindowState.Minimized
            self.minimizeButton.Click += min_win
        if hasattr(self, "maximizeButton") and self.maximizeButton:
            self.maximizeButton.Click += self.toggle_maximize
        if hasattr(self, "titleBar") and self.titleBar:
            def drag_win(s, e):
                try:
                    self.DragMove()
                except Exception:
                    pass
            self.titleBar.MouseLeftButtonDown += drag_win

        self.providerCombo.SelectionChanged += self.provider_changed
        if hasattr(self, "apiKeyBox") and self.apiKeyBox:
            self.apiKeyBox.TextChanged += self.api_key_changed
        self.testRuntimeButton.Click += self.test_runtime_clicked
        self.refreshModelsButton.Click += self.refresh_models_clicked
        self.historyButton.Click += self.history_clicked
        self.cancelButton.Click += self.cancel_clicked
        self.startButton.Click += self.start_clicked

    def _load_settings(self):
        config = script.get_config()
        self.saved_provider_id = getattr(config, "provider_id", "gemini")
        self.saved_model = getattr(config, "model", "")
        raw_base_urls = getattr(config, "base_urls", "{}")
        try:
            self.base_url_settings = json.loads(raw_base_urls)
        except Exception:
            self.base_url_settings = {}

    def _save_settings(self, provider, model, base_url):
        config = script.get_config()
        config.provider_id = provider.get("id")
        config.model = model
        self.base_url_settings[provider.get("id")] = base_url
        config.base_urls = json.dumps(self.base_url_settings)
        script.save_config()

    def _populate_providers(self):
        self.providerCombo.Items.Clear()
        for provider in self.providers:
            provider_id = provider.get("id")
            if not provider_id:
                continue
            self.provider_lookup[provider_id] = provider
            item = ComboBoxItem()
            item.Content = provider.get("name") or provider_id
            item.Tag = provider_id
            self.providerCombo.Items.Add(item)
            self.provider_items[provider_id] = item

    def _select_saved_provider(self):
        item = self.provider_items.get(self.saved_provider_id)
        if item is None and self.providerCombo.Items.Count:
            item = self.providerCombo.Items[0]
        self.providerCombo.SelectedItem = item
        self._update_provider_controls(self.current_provider())

    def current_provider(self):
        item = self.providerCombo.SelectedItem
        if item is None:
            return None
        return self.provider_lookup.get(str(item.Tag))

    def api_key_changed(self, sender, args):
        if self._loading:
            return
        provider = self.current_provider()
        if not provider:
            return
        key_value = self.apiKeyBox.Text.strip()
        key_names = provider.get("api_key_env") or []
        if key_names and key_value:
            primary_env = key_names[0]
            try:
                Environment.SetEnvironmentVariable(primary_env, key_value, EnvironmentVariableTarget.Process)
                Environment.SetEnvironmentVariable(primary_env, key_value, EnvironmentVariableTarget.User)
            except Exception:
                pass
        self._update_provider_status(provider)

    def _update_provider_controls(self, provider):
        if not provider:
            return
        provider_id = provider.get("id")
        if provider.get("base_url_policy") == "fixed":
            base_url = provider.get("base_url") or ""
        else:
            base_url = self.base_url_settings.get(
                provider_id, provider.get("base_url") or ""
            )
        self.baseUrlBox.Text = base_url
        is_codex = provider.get("protocol") == "codex_cli"
        self.baseUrlBox.IsEnabled = not is_codex
        self.baseUrlBox.IsReadOnly = provider.get("base_url_policy") == "fixed"

        key_names = provider.get("api_key_env") or []
        if hasattr(self, "apiKeyBox") and self.apiKeyBox:
            if is_codex or not (key_names or provider.get("requires_api_key")):
                self.apiKeyBox.Text = ""
                self.apiKeyBox.IsEnabled = False
                if hasattr(self, "apiKeyLabel") and self.apiKeyLabel:
                    self.apiKeyLabel.Content = "API Key (Not required for {})".format(provider.get("name"))
            else:
                self.apiKeyBox.IsEnabled = True
                if hasattr(self, "apiKeyLabel") and self.apiKeyLabel:
                    self.apiKeyLabel.Content = "API Key ({})".format(" / ".join(key_names))
                credential_env = get_provider_credential(provider)
                if credential_env:
                    val = get_environment_value(credential_env)
                    self.apiKeyBox.Text = val
                else:
                    self.apiKeyBox.Text = ""

        self.modelCombo.Items.Clear()
        for model in provider.get("models") or []:
            self.modelCombo.Items.Add(model)
        if provider_id == self.saved_provider_id and self.saved_model:
            self.modelCombo.Text = self.saved_model
        elif self.modelCombo.Items.Count:
            self.modelCombo.SelectedIndex = 0
        else:
            self.modelCombo.Text = ""
        self._update_provider_status(provider)

    def _update_provider_status(self, provider):
        if provider.get("protocol") == "codex_cli":
            if codex_cli_is_ready():
                self.providerStatusText.Text = (
                    "Ready. Uses the existing Codex CLI and ChatGPT sign-in."
                )
            else:
                self.providerStatusText.Text = (
                    "Codex CLI or ChatGPT sign-in was not found on this computer."
                )
            return
        key_names = provider.get("api_key_env") or []
        available_key = get_provider_credential(provider)
        if available_key:
            status = "Ready. Credential found in {}.".format(available_key)
        elif provider.get("requires_api_key"):
            status = "Enter API Key above or set user environment variable: {}.".format(
                " or ".join(key_names)
            )
        elif key_names:
            status = (
                "API key is optional. For authenticated servers, set: {}."
            ).format(" or ".join(key_names))
        else:
            status = "Local provider. Start its local model server before running a task."
        self.providerStatusText.Text = status

    def provider_changed(self, sender, args):
        if self._loading:
            return
        self._update_provider_controls(self.current_provider())

    def test_runtime_clicked(self, sender, args):
        write_event_log("test_runtime_clicked")
        uv_path = get_uv_path()
        if not uv_path:
            message(
                "uv was not found. Install uv or add uv.exe to PATH.",
                image=MessageBoxImage.Warning,
            )
            return
        self.testRuntimeButton.IsEnabled = False
        self.providerStatusText.Text = "Testing the local P13 MCP runtime..."
        try:
            process_info = ProcessStartInfo()
            process_info.FileName = uv_path
            process_info.WorkingDirectory = MCP_DIRECTORY
            process_info.Arguments = "run python {} --transport stdio".format(
                quote_argument(os.path.join(MCP_DIRECTORY, "smoke_test.py"))
            )
            process_info.UseShellExecute = False
            process_info.CreateNoWindow = True
            process_info.RedirectStandardOutput = True
            process_info.RedirectStandardError = True
            process = Process.Start(process_info)
            if not process.WaitForExit(45000):
                process.Kill()
                raise Exception("The runtime test timed out after 45 seconds.")
            output = process.StandardOutput.ReadToEnd().strip()
            error_output = process.StandardError.ReadToEnd().strip()
            if process.ExitCode != 0:
                raise Exception(error_output or output or "The runtime test failed.")
            tool_line = ""
            for line in output.splitlines():
                if line.startswith("Tools:"):
                    tool_line = line
                    break
            status = "P13 MCP runtime is ready. {}".format(tool_line).strip()
            self.providerStatusText.Text = status
            write_event_log("test_runtime_passed", status)
            message(status)
        except Exception:
            details = traceback.format_exc()
            write_event_log("test_runtime_failed", details)
            self._update_provider_status(self.current_provider())
            message(
                "P13 MCP runtime test failed.\n\n{}".format(details),
                image=MessageBoxImage.Error,
            )
        finally:
            self.testRuntimeButton.IsEnabled = True

    def refresh_models_clicked(self, sender, args):
        write_event_log("refresh_models_clicked")
        provider = self.current_provider()
        if not provider:
            return
        uv_path = get_uv_path()
        if not uv_path:
            message(
                "uv was not found. Install uv or add uv.exe to PATH before refreshing models.",
                image=MessageBoxImage.Warning,
            )
            return
        self.refreshModelsButton.IsEnabled = False
        self.providerStatusText.Text = "Contacting the provider model endpoint..."
        try:
            process_info = ProcessStartInfo()
            process_info.FileName = uv_path
            process_info.WorkingDirectory = MCP_DIRECTORY
            process_info.Arguments = "run python {} --list-models --provider {} --base-url {}".format(
                quote_argument(AGENT_PATH),
                quote_argument(provider.get("id")),
                quote_argument(self.baseUrlBox.Text.strip()),
            )
            process_info.UseShellExecute = False
            process_info.CreateNoWindow = True
            process_info.RedirectStandardOutput = True
            process_info.RedirectStandardError = True
            process = Process.Start(process_info)
            if not process.WaitForExit(35000):
                process.Kill()
                raise Exception("Model discovery timed out after 35 seconds.")
            output = process.StandardOutput.ReadToEnd().strip()
            error_output = process.StandardError.ReadToEnd().strip()
            if not output:
                raise Exception(error_output or "The provider returned no model list.")
            result = json.loads(output.splitlines()[-1])
            if result.get("status") != "ok":
                raise Exception(result.get("error") or error_output or "Model discovery failed.")
            models = result.get("models") or []
            current_model = self.modelCombo.Text.strip()
            self.modelCombo.Items.Clear()
            for model in models:
                self.modelCombo.Items.Add(model)
            if current_model:
                self.modelCombo.Text = current_model
            elif self.modelCombo.Items.Count:
                self.modelCombo.SelectedIndex = 0
            self.providerStatusText.Text = "Loaded {} available model(s).".format(
                len(models)
            )
        except Exception as error:
            self._update_provider_status(provider)
            message(
                "Could not refresh models.\n\n{}\n\nYou can still enter a valid Model ID manually.".format(
                    error
                ),
                image=MessageBoxImage.Warning,
            )
        finally:
            self.refreshModelsButton.IsEnabled = True

    def _jobs_directory(self):
        appdata = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData)
        return Path.Combine(appdata, "pyRevit", "P13", "ai_jobs")

    def _history_directory(self):
        appdata = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData)
        return Path.Combine(appdata, "pyRevit", "P13", "ai_history")

    def history_clicked(self, sender, args):
        try:
            history_directory = self._history_directory()
            Directory.CreateDirectory(history_directory)
            Process.Start("explorer.exe", quote_argument(history_directory))
            write_event_log("history_opened", history_directory)
        except Exception:
            details = traceback.format_exc()
            write_event_log("history_failed", details)
            message(
                "Could not open AI task history.\n\n{}".format(details),
                image=MessageBoxImage.Error,
            )

    def start_clicked(self, sender, args):
        write_event_log("start_clicked")
        try:
            self._start_task()
        except Exception:
            details = traceback.format_exc()
            log_path = write_event_log("start_failed", details)
            message(
                "Could not start the P13 AI task.\n\n{}\n\nLog: {}".format(
                    details,
                    log_path or "Unavailable",
                ),
                image=MessageBoxImage.Error,
            )

    def _start_task(self):
        provider = self.current_provider()
        model = self.modelCombo.Text.strip()
        prompt = self.promptBox.Text.strip()
        base_url = self.baseUrlBox.Text.strip()
        if not provider:
            message("Select an AI provider.", image=MessageBoxImage.Warning)
            return
        if not model:
            message(
                "Select or enter a Model ID.", image=MessageBoxImage.Warning
            )
            return
        if not prompt:
            message("Enter a task prompt.", image=MessageBoxImage.Warning)
            return
        if provider.get("requires_api_key") and not get_provider_credential(provider):
            key_names = provider.get("api_key_env") or []
            message(
                "{} is not configured on this computer.\n\n"
                "Set one of these user environment variables:\n{}\n\n"
                "Alternatively, select OpenAI Codex (ChatGPT Sign-In), which "
                "does not require an API key.".format(
                    provider.get("name") or provider.get("id"),
                    "\n".join(key_names),
                ),
                image=MessageBoxImage.Warning,
            )
            write_event_log(
                "start_blocked_missing_credential",
                "provider={} expected={}".format(
                    provider.get("id"),
                    ",".join(key_names),
                ),
            )
            return
        if (
            provider.get("protocol") != "codex_cli"
            and not base_url.startswith("http://")
            and not base_url.startswith("https://")
        ):
            message(
                "Provider Base URL must start with http:// or https://.",
                image=MessageBoxImage.Warning,
            )
            return
        if not File.Exists(RUNNER_PATH) or not File.Exists(AGENT_PATH):
            message(
                "P13 AI runtime files are missing. Repair the P13.extension installation.",
                image=MessageBoxImage.Error,
            )
            return
        uv_path = get_uv_path()
        if not uv_path:
            message(
                "uv was not found. Install uv and run this command again.",
                image=MessageBoxImage.Error,
            )
            return

        allow_write = bool(self.allowWriteCheck.IsChecked)
        save_history = bool(self.saveHistoryCheck.IsChecked)

        if provider_uses_remote_service(provider, base_url):
            cloud_confirmation = MessageBox.Show(
                "This provider runs outside this computer. The task prompt and "
                "the Revit data returned by MCP tools may be sent to {}.\n\n"
                "P13 hides the document title and full file path by default, but "
                "view names, element metadata, tags, and dimensions may still be "
                "required for the task.\n\nContinue?".format(
                    provider.get("name") or provider.get("id")
                ),
                "Confirm Cloud AI Data Sharing",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning,
            )
            if str(cloud_confirmation) != "Yes":
                return

        if allow_write:
            confirmation = MessageBox.Show(
                "This task may make confirmed changes in the active Revit document.\n\n"
                "Continue with write permission enabled?",
                "Confirm AI Write Permission",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning,
            )
            if str(confirmation) != "Yes":
                return

        job_id = Guid.NewGuid().ToString("N")
        jobs_directory = self._jobs_directory()
        Directory.CreateDirectory(jobs_directory)
        request_path = Path.Combine(
            jobs_directory, "{}.request.json".format(job_id)
        )
        request = {
            "schema_version": 1,
            "job_id": job_id,
            "provider_id": provider.get("id"),
            "model": model,
            "base_url": base_url,
            "prompt": prompt,
            "allow_write": allow_write,
            "save_history": save_history,
            "max_steps": 12,
        }
        File.WriteAllText(
            request_path,
            json.dumps(request, ensure_ascii=False, indent=2),
            UTF8Encoding(False),
        )
        write_event_log(
            "request_created",
            "job_id={} provider={} model={} allow_write={}".format(
                job_id,
                provider.get("id"),
                model,
                allow_write,
            ),
        )
        self._save_settings(provider, model, base_url)

        process_info = ProcessStartInfo()
        process_info.FileName = Path.Combine(
            Environment.SystemDirectory,
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe",
        )
        process_info.WorkingDirectory = MCP_DIRECTORY
        process_info.Arguments = (
            "-NoLogo -NoProfile -Sta -ExecutionPolicy Bypass "
            "-File {} -RequestFile {} -UvPath {}"
        ).format(
            quote_argument(RUNNER_PATH),
            quote_argument(request_path),
            quote_argument(uv_path),
        )
        # The runner displays its own Unicode-capable WPF output window. Avoid
        # creating the legacy Console Host, whose font cannot render Thai.
        process_info.UseShellExecute = False
        process_info.CreateNoWindow = True
        try:
            process = Process.Start(process_info)
            if process is None:
                raise Exception("Windows did not return a process for the AI runner.")
        except Exception as error:
            write_event_log("runner_launch_failed", traceback.format_exc())
            message(
                "Could not start the P13 AI task.\n\n{}".format(error),
                image=MessageBoxImage.Error,
            )
            return
        write_event_log("runner_started", "job_id={} pid={}".format(job_id, process.Id))
        self.Close()

    def cancel_clicked(self, sender, args):
        write_event_log("cancel_clicked")
        self.Close()


def validate_installation():
    missing = []
    for path in (PROVIDERS_PATH, AGENT_PATH, RUNNER_PATH, UI_PATH):
        if not path or not os.path.isfile(path):
            missing.append(path)
    if missing:
        forms.alert(
            "P13 AI Console installation is incomplete. Missing:\n\n{}".format(
                "\n".join(missing)
            ),
            title="P13 AI Console",
            exitscript=True,
        )


def write_error_log(error_text):
    try:
        appdata = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData)
        log_directory = Path.Combine(appdata, "pyRevit", "P13")
        Directory.CreateDirectory(log_directory)
        log_path = Path.Combine(log_directory, "ai_console_error.log")
        File.WriteAllText(log_path, error_text, UTF8Encoding(False))
        return log_path
    except Exception:
        return None


try:
    write_event_log("module_ready", "Imports and installation validation started")
    validate_installation()
    AIConsoleWindow().ShowDialog()
except Exception:
    error_details = traceback.format_exc()
    print(error_details)
    error_log_path = write_error_log(error_details)
    if error_log_path:
        forms.alert(
            "P13 AI Console could not start.\n\nError log:\n{}".format(
                error_log_path
            ),
            title="P13 AI Console",
        )
    else:
        forms.alert(
            "P13 AI Console could not start.\n\n{}".format(error_details),
            title="P13 AI Console",
        )
