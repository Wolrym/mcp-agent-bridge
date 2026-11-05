"""Windows taskbar identity: which icon and name the taskbar shows.

The panel runs under pythonw.exe, so on its own Windows would file the
window under python and show python's icon - or, with only an explicit
AppUserModelID and nothing describing it, a blank page icon (Windows 11
does that once its icon cache is refreshed). Two things fix it for good:

* the window carries the full set of AppUserModel properties - ID,
  relaunch command, relaunch icon and display name - so the taskbar can
  always draw the button and a pinned button relaunches the panel;
* the shortcuts (tools/make_shortcuts.py) carry the same ID, so a
  button started from a shortcut belongs to that shortcut and takes its
  icon.

Plain ctypes over the shell's IPropertyStore; everything here is
cosmetic and silently does nothing off Windows or when a call fails.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

APP_ID = "MCPAgentBridge.ControlPanel"
DISPLAY_NAME = "MCP Agent Bridge"
ROOT = Path(__file__).resolve().parent.parent
ICON_FILE = ROOT / "assets" / "icon.ico"

_FMTID_APPUSERMODEL = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
_IID_PROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
_PID = {"relaunch_command": 2, "relaunch_icon": 3, "relaunch_name": 4, "id": 5}
_VT_LPWSTR = 31
_GPS_READWRITE = 2


def pythonw() -> Path:
    """The console-less interpreter next to the running one."""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return candidate if candidate.is_file() else exe


def relaunch_command() -> str:
    return f'"{pythonw()}" "{ROOT / "gui" / "app.py"}"'


def _com():
    import ctypes
    from ctypes import POINTER, Structure, WINFUNCTYPE, c_ubyte, c_ulong, c_ushort, c_void_p

    class GUID(Structure):
        _fields_ = [("d1", c_ulong), ("d2", c_ushort), ("d3", c_ushort), ("d4", c_ubyte * 8)]

    class PROPERTYKEY(Structure):
        _fields_ = [("fmtid", GUID), ("pid", c_ulong)]

    class PROPVARIANT(Structure):
        # vt + three reserved words, then the 16-byte value union.
        _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                    ("value", c_void_p), ("pad", c_void_p)]

    def guid(text: str) -> GUID:
        return GUID.from_buffer_copy(uuid.UUID(text).bytes_le)

    def method(obj, index, restype, *argtypes):
        table = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        return WINFUNCTYPE(restype, c_void_p, *argtypes)(table[index])

    return ctypes, GUID, PROPERTYKEY, PROPVARIANT, guid, method


def _write(store, values: dict, commit: bool) -> None:
    """Set string properties on an IPropertyStore, then release it."""
    ctypes, _GUID, PROPERTYKEY, PROPVARIANT, guid, method = _com()
    from ctypes import HRESULT, POINTER, c_ulong, c_void_p

    set_value = method(store, 6, HRESULT, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))
    try:
        for name, text in values.items():
            key = PROPERTYKEY(guid(_FMTID_APPUSERMODEL), _PID[name])
            buffer = ctypes.create_unicode_buffer(text)
            value = PROPVARIANT(_VT_LPWSTR, 0, 0, 0, ctypes.cast(buffer, c_void_p), None)
            set_value(store, ctypes.byref(key), ctypes.byref(value))  # the store copies it
        if commit:
            method(store, 7, HRESULT)(store)
    finally:
        method(store, 2, c_ulong)(store)


def window_values() -> dict:
    values = {
        "relaunch_command": relaunch_command(),
        "relaunch_name": DISPLAY_NAME,
        "id": APP_ID,
    }
    if ICON_FILE.is_file():
        values["relaunch_icon"] = f"{ICON_FILE},0"
    return values


def apply_to_window(hwnd: int) -> bool:
    """Give a top-level window the app's taskbar identity. True on success."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        ctypes, _GUID, _KEY, _PV, guid, _method = _com()
        from ctypes import c_void_p

        store = c_void_p()
        iid = guid(_IID_PROPERTY_STORE)
        shell32 = ctypes.windll.shell32
        shell32.SHGetPropertyStoreForWindow.argtypes = [c_void_p, c_void_p, c_void_p]
        hr = shell32.SHGetPropertyStoreForWindow(
            c_void_p(int(hwnd)), ctypes.byref(iid), ctypes.byref(store)
        )
        if hr != 0 or not store:
            return False
        _write(store, window_values(), commit=False)
        return True
    except Exception:  # noqa: BLE001 - purely cosmetic
        return False


def stamp_shortcut(path: str | Path, app_id: str = APP_ID) -> None:
    """Write the AppUserModelID into a .lnk file. Raises OSError on failure."""
    ctypes, _GUID, _KEY, _PV, guid, _method = _com()
    from ctypes import c_void_p, c_wchar_p

    ctypes.windll.ole32.CoInitialize(None)
    store = c_void_p()
    iid = guid(_IID_PROPERTY_STORE)
    shell32 = ctypes.windll.shell32
    shell32.SHGetPropertyStoreFromParsingName.argtypes = [
        c_wchar_p, c_void_p, ctypes.c_int, c_void_p, c_void_p,
    ]
    hr = shell32.SHGetPropertyStoreFromParsingName(
        str(path), None, _GPS_READWRITE, ctypes.byref(iid), ctypes.byref(store)
    )
    if hr != 0 or not store:
        raise OSError(f"cannot open the properties of {path} (HRESULT {hr & 0xFFFFFFFF:#010x})")
    _write(store, {"id": app_id}, commit=True)


def read_window_id(hwnd: int) -> str:
    """The AppUserModelID set on a window ("" if none) - for checks."""
    if sys.platform != "win32":
        return ""
    ctypes, _GUID, PROPERTYKEY, PROPVARIANT, guid, method = _com()
    from ctypes import HRESULT, POINTER, c_ulong, c_void_p

    store = c_void_p()
    shell32 = ctypes.windll.shell32
    shell32.SHGetPropertyStoreForWindow.argtypes = [c_void_p, c_void_p, c_void_p]
    if shell32.SHGetPropertyStoreForWindow(
        c_void_p(int(hwnd)), ctypes.byref(guid(_IID_PROPERTY_STORE)), ctypes.byref(store)
    ) != 0:
        return ""
    try:
        key = PROPERTYKEY(guid(_FMTID_APPUSERMODEL), _PID["id"])
        value = PROPVARIANT()
        method(store, 5, HRESULT, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))(
            store, ctypes.byref(key), ctypes.byref(value)
        )
        text = ctypes.wstring_at(value.value) if value.vt == _VT_LPWSTR and value.value else ""
        ctypes.windll.ole32.PropVariantClear(ctypes.byref(value))
        return text
    finally:
        method(store, 2, c_ulong)(store)
