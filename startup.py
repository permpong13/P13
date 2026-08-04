# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import shutil
import logging
import json
import sys
import threading
import time
from datetime import datetime

from pyrevit.api import AdWindows


TAB_TITLE = "P13"
PANEL_TITLE = "A-Sync"
OBSOLETE_RELATIVE_PATHS = [
    os.path.join(
        "P13.tab",
        "Import_Export.panel",
        "SheetTools.stack",
        "CopySheets.pushbutton"
    ),
    os.path.join(
        "P13.tab",
        "Import_Export.panel",
        "SheetTools.stack",
        "Sheet_from_Excel.pushbutton"
    ),
    os.path.join(
        "P13.tab",
        "Import_Export.panel",
        "SheetTools.stack"
    ),
]
logger = logging.getLogger(__name__)


def maybe_start_p13_mcp():
    """Start the opt-in P13 MCP HTTP bridge after pyRevit Routes is ready."""
    try:
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        p13_data_directory = os.path.join(appdata, "pyRevit", "P13")
        manager_config_path = os.path.join(p13_data_directory, "mcp_manager.json")
        if not os.path.isfile(manager_config_path):
            return
        with open(manager_config_path, "r") as config_file:
            manager_config = json.load(config_file)
        if not isinstance(manager_config, dict) or not manager_config.get("autostart"):
            return

        extension_root = find_extension_root(os.path.dirname(os.path.abspath(__file__)))
        mcp_directory = os.path.join(extension_root, "mcp_server")
        main_path = os.path.join(mcp_directory, "main.py")
        venv_python_path = os.path.join(mcp_directory, ".venv", "Scripts", "python.exe")
        if not os.path.isfile(main_path):
            logger.warning("P13 MCP autostart skipped because main.py is missing.")
            return

        private_config_path = os.path.join(p13_data_directory, "mcp_config.json")
        port = 8013
        if os.path.isfile(private_config_path):
            with open(private_config_path, "r") as config_file:
                private_config = json.load(config_file)
            port = int(private_config.get("mcp_http_port") or port)

        # Do not create duplicate servers when Routes or MCP is already online.
        from System.Net import WebRequest

        request = WebRequest.Create("http://127.0.0.1:{}/health".format(port))
        request.Method = "GET"
        # The health endpoint checks the pyRevit Routes bridge as well, so allow
        # enough time for Revit's first request after startup.
        request.Timeout = 5000
        response = None
        try:
            response = request.GetResponse()
            return
        except Exception:
            pass
        finally:
            if response is not None:
                response.Close()

        uv_candidates = [
            os.path.join(os.path.expanduser("~"), ".local", "bin", "uv.exe"),
            os.path.join(
                os.environ.get("LOCALAPPDATA") or "",
                "Programs",
                "uv",
                "uv.exe",
            ),
        ]
        path_value = os.environ.get("PATH") or ""
        for directory in path_value.split(os.pathsep):
            if directory:
                uv_candidates.append(os.path.join(directory.strip('"'), "uv.exe"))
        uv_path = next((candidate for candidate in uv_candidates if os.path.isfile(candidate)), None)
        runtime_path = venv_python_path if os.path.isfile(venv_python_path) else uv_path
        if not runtime_path:
            logger.warning("P13 MCP autostart skipped because the Python runtime was not found.")
            return

        from System.Diagnostics import Process, ProcessStartInfo

        process_info = ProcessStartInfo()
        process_info.FileName = runtime_path
        process_info.WorkingDirectory = mcp_directory
        if runtime_path.lower().endswith("python.exe"):
            process_info.Arguments = "main.py --transport streamable-http --port {} --json-response".format(port)
        else:
            process_info.Arguments = "run main.py --transport streamable-http --port {} --json-response".format(port)
        process_info.UseShellExecute = False
        process_info.CreateNoWindow = True
        process = Process.Start(process_info)
        if process is None:
            raise RuntimeError("Windows did not return a P13 MCP process.")
        manager_config["pid"] = int(process.Id)
        manager_config["runtime"] = runtime_path
        manager_config["last_start_utc"] = datetime.utcnow().isoformat() + "Z"
        from System.IO import File

        temporary_path = manager_config_path + ".tmp"
        with open(temporary_path, "w") as config_file:
            json.dump(manager_config, config_file, indent=2, sort_keys=True)
            config_file.write("\n")
        if File.Exists(manager_config_path):
            File.Replace(temporary_path, manager_config_path, None)
        else:
            File.Move(temporary_path, manager_config_path)
        logger.info("P13 MCP autostart requested on port %s.", port)
    except Exception as error:
        logger.warning("P13 MCP autostart failed: %s", str(error))


def get_current_username():
    return (os.environ.get("USERNAME") or os.environ.get("USER") or "").strip()


def is_admin_user():
    # A Git checkout is a development installation. Release packages do not
    # contain .git, so end users retain the normal update controls without a
    # hardcoded developer username or Windows domain in public source code.
    extension_root = find_extension_root(os.path.dirname(os.path.abspath(__file__)))
    return os.path.isdir(os.path.join(extension_root, ".git"))


def hide_admin_sync_panel():
    if not is_admin_user():
        return

    ribbon = AdWindows.ComponentManager.Ribbon
    if not ribbon:
        return

    for tab in ribbon.Tabs:
        if tab.Title != TAB_TITLE:
            continue

        for panel in tab.Panels:
            try:
                panel_title = panel.Source.Title
            except Exception:
                panel_title = ""

            if panel_title == PANEL_TITLE:
                panel.IsVisible = False
                return


def find_extension_root(start_path):
    current_path = os.path.abspath(start_path)
    while not os.path.basename(current_path).startswith("P13.extension"):
        parent_path = os.path.dirname(current_path)
        if parent_path == current_path:
            break
        current_path = parent_path
    return current_path


def cleanup_obsolete_paths():
    extension_root = find_extension_root(os.path.dirname(os.path.abspath(__file__)))

    for relative_path in OBSOLETE_RELATIVE_PATHS:
        target_path = os.path.abspath(os.path.join(extension_root, relative_path))
        if not target_path.startswith(extension_root):
            continue

        try:
            if os.path.isdir(target_path):
                shutil.rmtree(target_path)
            elif os.path.isfile(target_path):
                os.remove(target_path)
        except Exception:
            pass


def ensure_extension_lib_path():
    extension_root = find_extension_root(os.path.dirname(os.path.abspath(__file__)))
    library_path = os.path.join(extension_root, "lib")
    if os.path.isdir(library_path) and library_path not in sys.path:
        sys.path.insert(0, library_path)


def make_pyrevit_routes_worker_safe():
    """Make pyRevit Routes safe for concurrent MCP clients and .NET 8.

    Python's BaseHTTPRequestHandler writes every response to sys.stderr through
    log_message(). In pyRevit on .NET 8, stderr is the WPF script console. A
    Routes worker therefore attempts to construct that window outside Revit's
    STA thread and can terminate the host process. Disabling only this access
    log leaves routing, responses, and P13 diagnostics unchanged.

    pyRevit Routes also owns one global ExternalEvent handler that is reused by
    every HTTP worker. Without serialization, a second MCP request can replace
    the first request while Revit is still executing it. This patch queues route
    handling and replaces the original CPU-intensive infinite waits with bounded
    waits. It applies to the shared Routes server so P13 and other MCP clients
    can coexist without corrupting one another's requests.
    """
    try:
        from pyrevit.routes.server.server import (
            HTTPServer,
            HttpRequestHandler,
            ThreadedHttpServer,
        )

        def write_worker_diagnostic(context, error):
            try:
                from p13_mcp.security import redact_sensitive_text

                log_directory = os.path.join(
                    os.environ.get("APPDATA") or os.path.expanduser("~"),
                    "pyRevit",
                    "P13",
                )
                if not os.path.isdir(log_directory):
                    os.makedirs(log_directory)
                log_path = os.path.join(log_directory, "pyrevit_routes_worker.log")
                timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                safe_context = redact_sensitive_text(context or "pyRevit Routes worker").replace("\r", " ").replace("\n", " ")
                safe_error = redact_sensitive_text(error or "Unknown error").replace("\r", " ").replace("\n", " ")
                with open(log_path, "a") as log_file:
                    log_file.write("{} | {} | {}\n".format(timestamp, safe_context, safe_error))
            except Exception:
                pass

        def silent_log_message(self, format_string, *arguments):
            return None

        def safe_shutdown(self):
            HTTPServer.shutdown(self)
            self.server_close()

        def silent_handle_error(self, request, client_address):
            write_worker_diagnostic(
                "pyRevit Routes worker exception for {}".format(client_address),
                sys.exc_info()[1],
            )

        # Keep one lock on the handler class so re-running startup does not
        # create separate queues around an already patched method.
        if not hasattr(HttpRequestHandler, "_p13_route_lock"):
            HttpRequestHandler._p13_route_lock = threading.Lock()

        if not hasattr(HttpRequestHandler, "_p13_original_handle_route"):
            HttpRequestHandler._p13_original_handle_route = HttpRequestHandler._handle_route

            def serialized_handle_route(self, method):
                route_lock = HttpRequestHandler._p13_route_lock
                acquired = False
                deadline = time.time() + 300.0
                while time.time() < deadline:
                    if route_lock.acquire(False):
                        acquired = True
                        break
                    time.sleep(0.02)

                if not acquired:
                    raise RuntimeError(
                        "pyRevit Routes is busy. Close any abandoned AI task and try again."
                    )

                try:
                    return HttpRequestHandler._p13_original_handle_route(self, method)
                finally:
                    route_lock.release()

            HttpRequestHandler._handle_route = serialized_handle_route

        if not hasattr(HttpRequestHandler, "_p13_original_call_host_event_sync"):
            HttpRequestHandler._p13_original_call_host_event_sync = (
                HttpRequestHandler._call_host_event_sync
            )

            def efficient_call_host_event_sync(self, request_handler, event_handler):
                self._call_host_event(request_handler, event_handler)

                event_deadline = time.time() + 180.0
                while event_handler.IsPending:
                    if time.time() >= event_deadline:
                        raise RuntimeError(
                            "Revit did not accept the MCP ExternalEvent within 180 seconds."
                        )
                    time.sleep(0.01)

                completion_deadline = time.time() + 180.0
                while not request_handler.done:
                    if time.time() >= completion_deadline:
                        raise RuntimeError(
                            "The MCP route did not finish within 180 seconds."
                        )
                    time.sleep(0.01)

            HttpRequestHandler._call_host_event_sync = efficient_call_host_event_sync

        HttpRequestHandler.log_message = silent_log_message
        ThreadedHttpServer.shutdown = safe_shutdown
        ThreadedHttpServer.handle_error = silent_handle_error
    except Exception as error:
        logger.warning("P13 could not apply the pyRevit Routes worker safety patch: %s", str(error))


def register_p13_mcp_routes():
    """Register P13 MCP routes without affecting normal P13 startup on failure."""
    try:
        from pyrevit import routes
        from p13_mcp import API_NAME
        from p13_mcp.routes import register_routes

        api = routes.API(API_NAME)
        register_routes(api)
    except Exception as error:
        logger.warning("P13 MCP routes were not registered: %s", str(error))


cleanup_obsolete_paths()
hide_admin_sync_panel()
ensure_extension_lib_path()

# P13 MCP is archived and disabled. The original pyRevit MCP extension owns
# the standard ``revit_mcp`` API and remains the active integration.
