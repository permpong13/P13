# -*- coding: utf-8 -*-
from __future__ import print_function

"""Allowlisted hot-loaded operation dispatcher for P13 Revit MCP."""

import hashlib
import json
import os
import re

try:
    import imp
except ImportError:
    imp = None

try:
    import importlib.util as importlib_util
except ImportError:
    importlib_util = None


MAX_PAYLOAD_CHARACTERS = 262144
VALID_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MODULE_CACHE = {}


def _load_source(module_name, path):
    if imp is not None:
        return imp.load_source(module_name, path)
    if importlib_util is None:
        raise RuntimeError("No supported dynamic module loader is available.")
    specification = importlib_util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError("Could not create a module specification for the operation.")
    module = importlib_util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def operations_root():
    library_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(library_root, "p13_mcp_operations")


def manifest_path():
    return os.path.join(operations_root(), "manifest.json")


def _load_manifest():
    path = manifest_path()
    if not os.path.isfile(path):
        raise ValueError("P13 hot-operation manifest was not found.")
    with open(path, "r") as manifest_file:
        manifest = json.load(manifest_file)
    operations = manifest.get("operations")
    if not isinstance(operations, dict):
        raise ValueError("P13 hot-operation manifest must contain an operations object.")
    return manifest, operations


def _validate_operation(name, entry):
    name = str(name or "")
    if not VALID_NAME.match(name):
        raise ValueError("operation must contain only lowercase letters, numbers, and underscores.")
    if not isinstance(entry, dict):
        raise ValueError("Operation metadata must be a JSON object.")
    access = str(entry.get("access") or "read").lower()
    if access not in ("read", "write"):
        raise ValueError("Operation access must be read or write.")
    filename = str(entry.get("module") or "")
    if not filename or os.path.basename(filename) != filename or not filename.endswith(".py"):
        raise ValueError("Operation module must be a local Python filename.")
    root = os.path.abspath(operations_root())
    path = os.path.abspath(os.path.join(root, filename))
    if not path.startswith(root + os.sep) or not os.path.isfile(path):
        raise ValueError("Operation module is outside the allowlisted operation directory.")
    return access, path


def _load_operation(name):
    manifest, operations = _load_manifest()
    if name not in operations:
        raise ValueError("Unknown P13 operation: {}".format(name))
    entry = operations[name]
    access, path = _validate_operation(name, entry)
    fingerprint = "{}:{}".format(os.path.getmtime(path), os.path.getsize(path))
    cached = _MODULE_CACHE.get(name)
    if cached and cached[0] == fingerprint:
        return cached[1], entry, access, fingerprint
    module_name = "_p13_hot_{}_{}".format(
        name,
        hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:12],
    )
    module = _load_source(module_name, path)
    _MODULE_CACHE[name] = (fingerprint, module)
    return module, entry, access, fingerprint


def _validate_payload(payload):
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object.")
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(serialized) > MAX_PAYLOAD_CHARACTERS:
        raise ValueError("payload exceeds the 262144-character limit.")
    return payload


def list_operations():
    manifest, operations = _load_manifest()
    result = []
    for name in sorted(operations.keys()):
        entry = operations[name]
        access, path = _validate_operation(name, entry)
        result.append(
            {
                "name": name,
                "access": access,
                "description": str(entry.get("description") or ""),
                "module": os.path.basename(path),
                "supports_hot_reload": True,
            }
        )
    return {
        "status": "success",
        "schema_version": int(manifest.get("schema_version") or 1),
        "operations": result,
        "reload_policy": "Operation files and manifest changes are detected without reloading pyRevit.",
    }


def _signature(doc, name, fingerprint, payload, preview):
    document_path = ""
    document_title = ""
    try:
        document_path = str(doc.PathName or "")
        document_title = str(doc.Title or "")
    except Exception:
        pass
    signature_payload = {
        "operation": name,
        "module_fingerprint": fingerprint,
        "document_path": document_path,
        "document_title": document_title,
        "payload": payload,
        "preview": preview,
    }
    serialized = json.dumps(signature_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def execute_read(doc, uidoc, name, payload):
    payload = _validate_payload(payload)
    module, entry, access, fingerprint = _load_operation(name)
    if access != "read":
        raise ValueError("Write operations require preview and apply.")
    if not hasattr(module, "execute"):
        raise ValueError("Read operation does not expose execute().")
    result = module.execute(doc, uidoc, payload)
    if not isinstance(result, dict):
        raise ValueError("Operation execute() must return a JSON object.")
    result.setdefault("status", "success")
    result["operation"] = name
    result["module_fingerprint"] = fingerprint
    return result


def preview_write(doc, uidoc, name, payload):
    payload = _validate_payload(payload)
    module, entry, access, fingerprint = _load_operation(name)
    if access != "write":
        raise ValueError("Read operations use execute.")
    if not hasattr(module, "prepare") or not hasattr(module, "preview_to_data"):
        raise ValueError("Write operation must expose prepare() and preview_to_data().")
    prepared = module.prepare(doc, uidoc, payload)
    preview = module.preview_to_data(prepared)
    if not isinstance(preview, dict):
        raise ValueError("Operation preview_to_data() must return a JSON object.")
    preview["operation"] = name
    preview["module_fingerprint"] = fingerprint
    preview["preview_signature"] = _signature(doc, name, fingerprint, payload, preview)
    preview.setdefault("workflow_stage", "preview")
    preview.setdefault("status", "success")
    return preview


def apply_write(doc, uidoc, name, payload, preview_signature):
    payload = _validate_payload(payload)
    module, entry, access, fingerprint = _load_operation(name)
    if access != "write":
        raise ValueError("Read operations cannot be applied.")
    prepared = module.prepare(doc, uidoc, payload)
    preview = module.preview_to_data(prepared)
    preview["operation"] = name
    preview["module_fingerprint"] = fingerprint
    current_signature = _signature(doc, name, fingerprint, payload, preview)
    if current_signature != str(preview_signature or ""):
        raise ValueError("Preview no longer matches. Run the hot-operation preview again.")
    if preview.get("safe_to_apply") is False:
        raise ValueError("The operation preview is not safe to apply.")
    if not hasattr(module, "apply"):
        raise ValueError("Write operation does not expose apply().")
    result = module.apply(doc, uidoc, payload, prepared)
    if not isinstance(result, dict):
        raise ValueError("Operation apply() must return a JSON object.")
    result.setdefault("status", "success")
    result.setdefault("workflow_stage", "applied")
    result["operation"] = name
    result["module_fingerprint"] = fingerprint
    result["preview_signature"] = current_signature
    return result
