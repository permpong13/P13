# -*- coding: utf-8 -*-
"""
openpyxl_loader.py  —  โหลด openpyxl ใน IronPython ผ่าน CPython
=================================================================
วางไฟล์นี้ไว้ใน _schedule_excel_lib/ แล้ว import จาก script หลัก:

    from openpyxl_loader import load_openpyxl
    openpyxl = load_openpyxl()

รองรับ 3 ระดับ fallback ตามลำดับ:
  1. Import ตรงๆ (ถ้า openpyxl ติดตั้งใน IronPython อยู่แล้ว)
  2. เพิ่ม CPython site-packages เข้า sys.path แล้ว import
  3. รัน Excel operations ผ่าน CPython subprocess (JSON bridge)
"""
from __future__ import print_function

import os
import sys
import json
import subprocess
import tempfile

# ─────────────────────────────────────────────────────────────
# ค้นหา CPython executable อัตโนมัติ
# ─────────────────────────────────────────────────────────────
_COMMON_PYTHON_PATHS = [
    r"C:\Python313\python.exe",
    r"C:\Python312\python.exe",
    r"C:\Python311\python.exe",
    r"C:\Python310\python.exe",
    r"C:\Python39\python.exe",
    r"C:\Program Files\Python313\python.exe",
    r"C:\Program Files\Python312\python.exe",
    r"C:\Program Files\Python311\python.exe",
    r"C:\Users\{}\AppData\Local\Programs\Python\Python313\python.exe".format(
        os.environ.get("USERNAME", "")
    ),
    r"C:\Users\{}\AppData\Local\Programs\Python\Python312\python.exe".format(
        os.environ.get("USERNAME", "")
    ),
    r"C:\Users\{}\AppData\Local\Programs\Python\Python311\python.exe".format(
        os.environ.get("USERNAME", "")
    ),
]


def find_cpython():
    """ค้นหา CPython executable — คืน path หรือ None"""

    # 1. ลอง `where python` / `which python`
    try:
        cmd = ["where", "python"] if sys.platform == "win32" else ["which", "python3"]
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode("utf-8", errors="ignore")
        for line in output.strip().splitlines():
            line = line.strip()
            if line and os.path.isfile(line) and "WindowsApps" not in line:
                # ตรวจว่าเป็น CPython จริง ไม่ใช่ IronPython
                test = subprocess.check_output(
                    [line, "-c", "import sys; print(sys.implementation.name)"],
                    stderr=subprocess.STDOUT,
                ).decode("utf-8", errors="ignore").strip()
                if test == "cpython":
                    return line
    except Exception:
        pass

    # 2. ลอง path ที่รู้จัก
    for path in _COMMON_PYTHON_PATHS:
        if os.path.isfile(path):
            return path

    # 3. ลอง PYTHON_HOME environment variable
    python_home = os.environ.get("PYTHON_HOME", "")
    if python_home:
        candidate = os.path.join(python_home, "python.exe")
        if os.path.isfile(candidate):
            return candidate

    return None


def get_cpython_site_packages(python_exe):
    """ดึง path ของ site-packages จาก CPython"""
    try:
        output = subprocess.check_output(
            [python_exe, "-c",
             "import site; print('\\n'.join(site.getsitepackages()))"],
            stderr=subprocess.STDOUT,
        ).decode("utf-8", errors="ignore")
        paths = [p.strip() for p in output.strip().splitlines() if p.strip()]
        return paths
    except Exception:
        return []


def ensure_openpyxl_installed(python_exe):
    """ติดตั้ง openpyxl ใน CPython ถ้ายังไม่มี"""
    try:
        subprocess.check_output(
            [python_exe, "-c", "import openpyxl"],
            stderr=subprocess.STDOUT,
        )
        return True  # มีอยู่แล้ว
    except subprocess.CalledProcessError:
        pass

    print("[openpyxl_loader] กำลังติดตั้ง openpyxl ใน CPython...")
    try:
        subprocess.check_call(
            [python_exe, "-m", "pip", "install", "openpyxl", "--quiet"],
        )
        print("[openpyxl_loader] ติดตั้ง openpyxl สำเร็จ")
        return True
    except Exception as exc:
        print("[openpyxl_loader] ติดตั้งไม่สำเร็จ: {}".format(exc))
        return False


# ─────────────────────────────────────────────────────────────
# APPROACH A  —  เพิ่ม site-packages เข้า sys.path
# ─────────────────────────────────────────────────────────────
def try_import_via_sys_path(python_exe):
    """
    เพิ่ม CPython site-packages เข้า IronPython sys.path
    แล้ว import openpyxl ตรงๆ (ได้ผลเพราะ openpyxl เป็น pure Python)
    """
    site_paths = get_cpython_site_packages(python_exe)
    added = []
    for sp in site_paths:
        if os.path.isdir(sp) and sp not in sys.path:
            sys.path.insert(0, sp)
            added.append(sp)

    try:
        import openpyxl
        print("[openpyxl_loader] โหลด openpyxl {} จาก CPython site-packages สำเร็จ".format(
            openpyxl.__version__
        ))
        return openpyxl
    except ImportError as exc:
        # คืน path ที่เพิ่มไปออก ถ้าโหลดไม่ได้
        for sp in added:
            if sp in sys.path:
                sys.path.remove(sp)
        print("[openpyxl_loader] Approach A ล้มเหลว: {}".format(exc))
        return None


# ─────────────────────────────────────────────────────────────
# APPROACH B  —  JSON Subprocess Bridge
# ─────────────────────────────────────────────────────────────
_BRIDGE_SCRIPT = r"""
# cpython_bridge.py  —  รันโดย CPython ผ่าน subprocess
import sys, json, traceback

def read_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    result = {}
    for name in wb.sheetnames:
        ws = wb[name]
        result[name] = []
        for row in ws.iter_rows(values_only=True):
            result[name].append([
                str(v) if v is not None else None for v in row
            ])
    wb.close()
    return result

def write_xlsx(path, sheets_data):
    import openpyxl
    wb = openpyxl.load_workbook(path)
    for sheet_info in sheets_data:
        name = sheet_info["name"]
        rows = sheet_info["rows"]
        if name not in wb.sheetnames:
            continue
        ws = wb[name]
        for r_idx, row_data in enumerate(rows):
            for c_idx, value in enumerate(row_data):
                ws.cell(row=r_idx + 1, column=c_idx + 1).value = value if value != "" else None
    wb.save(path)
    wb.close()

try:
    payload = json.loads(sys.stdin.read())
    action  = payload["action"]

    if action == "read":
        data = read_xlsx(payload["path"])
        print(json.dumps({"ok": True, "data": data}))

    elif action == "write":
        write_xlsx(payload["path"], payload["sheets"])
        print(json.dumps({"ok": True}))

    else:
        print(json.dumps({"ok": False, "error": "Unknown action: " + action}))

except Exception:
    print(json.dumps({"ok": False, "error": traceback.format_exc()}))
"""


class SubprocessExcelBridge(object):
    """
    ใช้ CPython subprocess แทน openpyxl โดยตรง
    API เหมือนกับ openpyxl helper ใน script หลัก
    """
    def __init__(self, python_exe):
        self.python_exe  = python_exe
        self._bridge_path = self._write_bridge_script()

    def _write_bridge_script(self):
        """เขียน bridge script ลง temp file"""
        fd, path = tempfile.mkstemp(suffix=".py", prefix="p13_bridge_")
        with os.fdopen(fd, "w") as f:
            f.write(_BRIDGE_SCRIPT)
        return path

    def _call(self, payload):
        """ส่ง JSON ไป CPython และรับผลลัพธ์กลับ"""
        proc = subprocess.Popen(
            [self.python_exe, self._bridge_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdin_data = json.dumps(payload).encode("utf-8")
        stdout, stderr = proc.communicate(input=stdin_data)

        try:
            result = json.loads(stdout.decode("utf-8", errors="ignore"))
        except ValueError:
            raise RuntimeError(
                "Bridge ไม่ตอบสนอง:\nstdout={}\nstderr={}".format(stdout, stderr)
            )

        if not result.get("ok"):
            raise RuntimeError("Bridge error:\n{}".format(result.get("error", "unknown")))

        return result

    def read_xlsx(self, path):
        """อ่าน xlsx คืน dict{ sheet_name: [[values]] }"""
        result = self._call({"action": "read", "path": path})
        return result["data"]

    def write_xlsx(self, path, sheets_data):
        """
        เขียน xlsx
        sheets_data: list ของ {"name": str, "rows": [[values]]}
        """
        self._call({"action": "write", "path": path, "sheets": sheets_data})

    def cleanup(self):
        """ลบ bridge script temp file"""
        try:
            os.remove(self._bridge_path)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────
def load_openpyxl(auto_install=True):
    """
    โหลด openpyxl ด้วยวิธีที่ดีที่สุดที่ทำได้
    คืน openpyxl module หรือ raise RuntimeError

    ใช้งาน:
        openpyxl = load_openpyxl()
        wb = openpyxl.load_workbook("file.xlsx")
    """
    # ── ลองตรงๆ ก่อน ──────────────────────────────────────
    try:
        import openpyxl
        return openpyxl
    except ImportError:
        pass

    # ── หา CPython ────────────────────────────────────────
    python_exe = find_cpython()
    if python_exe is None:
        raise RuntimeError(
            "ไม่พบ CPython interpreter\n\n"
            "กรุณาติดตั้ง Python จาก https://python.org\n"
            "หรือวาง openpyxl/ folder ใน _schedule_excel_lib/ โดยตรง"
        )

    print("[openpyxl_loader] พบ CPython: {}".format(python_exe))

    # ── ติดตั้ง openpyxl ถ้ายังไม่มี ──────────────────────
    if auto_install:
        ensure_openpyxl_installed(python_exe)

    # ── Approach A: import ผ่าน sys.path ──────────────────
    openpyxl = try_import_via_sys_path(python_exe)
    if openpyxl is not None:
        return openpyxl

    # ── Approach B: Subprocess bridge ─────────────────────
    print("[openpyxl_loader] ใช้ Subprocess JSON bridge แทน")
    raise RuntimeError(
        "Approach A ล้มเหลว\n"
        "ใช้ get_subprocess_bridge() เพื่อรับ SubprocessExcelBridge แทน"
    )


def get_subprocess_bridge(auto_install=True):
    """
    คืน SubprocessExcelBridge สำหรับ read/write Excel ผ่าน CPython

    ใช้งาน:
        bridge = get_subprocess_bridge()
        data   = bridge.read_xlsx("schedule.xlsx")
        bridge.write_xlsx("schedule.xlsx", sheets_data)
        bridge.cleanup()
    """
    python_exe = find_cpython()
    if python_exe is None:
        raise RuntimeError(
            "ไม่พบ CPython interpreter\n"
            "กรุณาติดตั้ง Python จาก https://python.org"
        )

    if auto_install:
        ensure_openpyxl_installed(python_exe)

    return SubprocessExcelBridge(python_exe)
