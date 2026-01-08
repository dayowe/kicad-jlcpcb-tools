"""Contains helper function used all over the plugin."""

import hashlib
import os
from pathlib import Path
import re
import tempfile

import wx  # pylint: disable=import-error
import wx.dataview  # pylint: disable=import-error

PLUGIN_PATH = Path(__file__).resolve().parent

EXCLUDE_FROM_POS = 2
EXCLUDE_FROM_BOM = 3


def getWxWidgetsVersion():
    """Get wx widgets version."""
    v = re.search(r"wxWidgets\s([\d\.]+)", wx.version())
    v = int(v.group(1).replace(".", ""))
    return v


def getVersion():
    """READ Version from file."""
    if not os.path.isfile(os.path.join(PLUGIN_PATH, "VERSION")):
        return "unknown"
    with open(os.path.join(PLUGIN_PATH, "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


def GetOS():
    """Get String with OS type."""
    return wx.PlatformInformation.Get().GetOperatingSystemIdName()


def is_wsl_unc_path(path: str) -> bool:
    """Returns True if the path points to a WSL UNC share from Windows."""
    if os.name != "nt":
        return False
    p = (path or "").replace("\\", "/").lower()
    return p.startswith("//wsl.localhost/") or p.startswith("//wsl$/")


def get_project_db_path(project_path: str) -> str:
    """Return the path to the per-project SQLite database used by the plugin.

    On Windows, SQLite file locking can be unreliable on network shares (including
    WSL UNC paths like \\\\wsl$ and //wsl.localhost). For such projects, store the
    database under LOCALAPPDATA instead, while keeping generated fabrication files
    in the project folder.
    """
    if os.name != "nt" or not is_wsl_unc_path(project_path):
        return os.path.join(project_path, "jlcpcb", "project.db")

    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base:
        base = tempfile.gettempdir()

    normalized = project_path.replace("\\", "/")
    project_id = hashlib.sha1(normalized.encode("utf-8"), usedforsecurity=False).hexdigest()  # nosec B303
    dbdir = os.path.join(base, "kicad-jlcpcb-tools", "projects", project_id)
    Path(dbdir).mkdir(parents=True, exist_ok=True)
    return os.path.join(dbdir, "project.db")


def get_windows_locking_processes(path: str):
    """Best-effort list of processes locking a file on Windows.

    Uses the Windows Restart Manager API (rstrtmgr.dll). Returns an empty list on
    non-Windows platforms or if the API is unavailable.
    """
    if os.name != "nt":
        return []

    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return []

    ERROR_MORE_DATA = 234
    CCH_RM_SESSION_KEY = 32
    CCH_RM_MAX_APP_NAME = 255
    CCH_RM_MAX_SVC_NAME = 63

    class RM_UNIQUE_PROCESS(ctypes.Structure):
        _fields_ = [
            ("dwProcessId", wintypes.DWORD),
            ("ProcessStartTime", wintypes.FILETIME),
        ]

    class RM_PROCESS_INFO(ctypes.Structure):
        _fields_ = [
            ("Process", RM_UNIQUE_PROCESS),
            ("strAppName", wintypes.WCHAR * (CCH_RM_MAX_APP_NAME + 1)),
            ("strServiceShortName", wintypes.WCHAR * (CCH_RM_MAX_SVC_NAME + 1)),
            ("ApplicationType", wintypes.DWORD),
            ("AppStatus", wintypes.DWORD),
            ("TSSessionId", wintypes.DWORD),
            ("bRestartable", wintypes.BOOL),
        ]

    try:
        rstrtmgr = ctypes.WinDLL("rstrtmgr")  # pylint: disable=invalid-name
    except Exception:
        return []

    session_handle = wintypes.DWORD()
    session_key = (wintypes.WCHAR * (CCH_RM_SESSION_KEY + 1))()
    try:
        res = rstrtmgr.RmStartSession(ctypes.byref(session_handle), 0, session_key)
        if res != 0:
            return []

        resources = (wintypes.LPCWSTR * 1)()
        resources[0] = path
        res = rstrtmgr.RmRegisterResources(
            session_handle, 1, resources, 0, None, 0, None
        )
        if res != 0:
            return []

        needed = wintypes.DWORD(0)
        count = wintypes.DWORD(0)
        reboot_reasons = wintypes.DWORD(0)
        res = rstrtmgr.RmGetList(
            session_handle,
            ctypes.byref(needed),
            ctypes.byref(count),
            None,
            ctypes.byref(reboot_reasons),
        )
        if res not in (0, ERROR_MORE_DATA):
            return []

        if needed.value == 0:
            return []

        count = wintypes.DWORD(needed.value)
        proc_info = (RM_PROCESS_INFO * count.value)()
        res = rstrtmgr.RmGetList(
            session_handle,
            ctypes.byref(needed),
            ctypes.byref(count),
            proc_info,
            ctypes.byref(reboot_reasons),
        )
        if res != 0:
            return []

        out = []
        for i in range(count.value):
            info = proc_info[i]
            out.append(
                {
                    "pid": int(info.Process.dwProcessId),
                    "app_name": str(info.strAppName).strip("\x00"),
                    "service": str(info.strServiceShortName).strip("\x00"),
                    "app_type": int(info.ApplicationType),
                }
            )
        return out
    finally:
        try:
            rstrtmgr.RmEndSession(session_handle)
        except Exception:
            pass


def GetScaleFactor(window):
    """Workaround if wxWidgets Version does not support GetDPIScaleFactor, for Mac OS always return 1.0."""
    if "Apple Mac OS" in GetOS():
        return 1.0
    if hasattr(window, "GetDPIScaleFactor"):
        return window.GetDPIScaleFactor()
    return 1.0


def HighResWxSize(window, size):
    """Workaround if wxWidgets Version does not support FromDIP."""
    if hasattr(window, "FromDIP"):
        return window.FromDIP(size)
    return size


def loadBitmapScaled(filename, scale=1.0, static=False):
    """Load a scaled bitmap, handle differences between Kicad versions."""
    if filename:
        path = os.path.join(PLUGIN_PATH, "icons", filename)
        bmp = wx.Bitmap(path)
        w, h = bmp.GetSize()
        img = bmp.ConvertToImage()
        if hasattr(wx.SystemSettings, "GetAppearance") and hasattr(
            wx.SystemSettings.GetAppearance, "IsUsingDarkBackground"
        ):
            if wx.SystemSettings.GetAppearance().IsUsingDarkBackground():
                img.Replace(0, 0, 0, 255, 255, 255)
            bmp = wx.Bitmap(img.Scale(int(w * scale), int(h * scale)))
    else:
        bmp = wx.Bitmap()
    if getWxWidgetsVersion() > 315 and not static:
        return wx.BitmapBundle(bmp)
    return bmp


def loadIconScaled(filename, scale=1.0):
    """Load a scaled icon, handle differences between Kicad versions."""
    bmp = loadBitmapScaled(filename, scale=scale, static=False)
    if getWxWidgetsVersion() > 315:
        return bmp
    return wx.Icon(bmp)


def natural_sort_collation(a, b):
    """Natural sort collation for use in sqlite."""
    if a == b:
        return 0

    def convert(text):
        return int(text) if text.isdigit() else text.lower()

    def alphanum_key(key):
        return [convert(c) for c in re.split("([0-9]+)", key)]

    natorder = sorted([a, b], key=alphanum_key)
    return -1 if natorder.index(a) == 0 else 1


def dict_factory(cursor, row) -> dict:
    """Row factory that returns a dict."""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


def get_lcsc_value(fp):
    """Get the first lcsc number (C123456 for example) from the properties of the footprint."""
    # KiCad 7.99
    try:
        for field in fp.GetFields():
            if re.match(r"lcsc|jlc", field.GetName(), re.IGNORECASE) and re.match(
                r"^C\d+$", field.GetText()
            ):
                return field.GetText()
    # KiCad <= V7
    except AttributeError:
        for key, value in fp.GetProperties().items():
            if re.match(r"lcsc|jlc", key, re.IGNORECASE) and re.match(r"^C\d+$", value):
                return value
    return ""


def set_lcsc_value(fp, lcsc: str):
    """Set an lcsc number to the first matching propertie of the footprint, use LCSC as property name if not found."""
    lcsc_field = None
    for field in fp.GetFields():
        if re.match(r"lcsc|jlc", field.GetName(), re.IGNORECASE) and re.match(
            r"^C\d+$", field.GetText()
        ):
            lcsc_field = field

    if lcsc_field:
        fp.SetField(lcsc_field.GetName(), lcsc)
    else:
        fp.SetField("LCSC", lcsc)
        field = fp.GetFieldByName("LCSC")
        field.SetVisible(False)


def get_valid_footprints(board):
    """Get all footprints that have a valid reference.

    Drop all REF** for example
    Drop kibuzzard footprints (length check)
    """
    footprints = []
    for fp in board.GetFootprints():
        if re.match(r"[\w\d-]+", fp.GetReference()) and len(fp.GetReference()) < 8:
            footprints.append(fp)
    return footprints


def get_bit(value, bit):
    """Get the nth bit of a byte."""
    return value & (1 << bit)


def toggle_bit(value, bit):
    """Toggle the nth bit of a byte."""
    return value ^ (1 << bit)


def get_exclude_from_pos(footprint):
    """Get the 'exclude from POS' property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    return bool(get_bit(val, EXCLUDE_FROM_POS))


def get_exclude_from_bom(footprint):
    """Get the 'exclude from BOM' property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    return bool(get_bit(val, EXCLUDE_FROM_BOM))


def toggle_exclude_from_pos(footprint):
    """Toggle the 'exclude from POS' property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    val = toggle_bit(val, EXCLUDE_FROM_POS)
    footprint.SetAttributes(val)
    return bool(get_bit(val, EXCLUDE_FROM_POS))


def toggle_exclude_from_bom(footprint):
    """Toggle the 'exclude from BOM' property of a footprint."""
    if not footprint:
        return None
    val = footprint.GetAttributes()
    val = toggle_bit(val, EXCLUDE_FROM_BOM)
    footprint.SetAttributes(val)
    return bool(get_bit(val, EXCLUDE_FROM_BOM))
