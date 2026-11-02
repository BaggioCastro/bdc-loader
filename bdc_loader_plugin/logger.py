"""
logger.py

Centralized logging utility for the BDC Loader Plugin.

Provides:
  - Wrappers around QgsMessageLog (QGIS Log Messages Panel)
  - Persistent JSONL log file stored under the plugin's user data directory
  - In-memory ring buffer (last 200 entries) for the in-dialog log viewer
  - A signal bus so the dialog can subscribe to new log entries at runtime

Log file location:
  <QGIS profile dir>/bdc_loader/logs/bdc_loader.jsonl (see paths.py)

Each JSONL line: {"ts": "ISO-8601", "level": "INFO|WARNING|ERROR", "msg": "..."}

Developed by Baggio Luiz de Castro e Silva
INPE - Sao Jose dos Campos, 2026
"""

import json
import os
import sys
import threading
import traceback
from collections import deque
from datetime import datetime

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QObject, pyqtSignal

TAG = "BDC Loader"
_MAX_MEMORY = 200  # entries kept in the in-process ring buffer
_MAX_FILE_LINES = 2000  # the file is cut to this many lines before the first entry of each session


# ── Log file path ─────────────────────────────────────────────────────────────
def _log_dir() -> str:
    from .paths import data_dir

    return data_dir("logs")


def _log_path() -> str:
    return os.path.join(_log_dir(), "bdc_loader.jsonl")


# ── Signal bus (singleton QObject so non-Qt code can emit) ───────────────────
class _LogBus(QObject):
    new_entry = pyqtSignal(dict)  # emits the entry dict on every new log line


_bus = _LogBus()

# ── In-memory ring buffer ─────────────────────────────────────────────────────
_buffer: deque = deque(maxlen=_MAX_MEMORY)

# Worker threads log too: one writer at a time keeps lines whole.
_file_lock = threading.Lock()
_file_trimmed = False


def get_log_bus() -> _LogBus:
    """Return the singleton signal bus for subscribing to new log entries."""
    return _bus


def get_recent_entries(n: int = 100) -> list:
    """Return the last *n* log entries from the in-memory buffer (newest last)."""
    entries = list(_buffer)
    return entries[-n:]


# ── Internal write ────────────────────────────────────────────────────────────
def _write(level: str, msg: str):
    # Capture calling module name via direct frame access (O(1), no stack unwind)
    src = "?"
    try:
        frame = sys._getframe(2)
        filename = frame.f_code.co_filename
        if filename.endswith("logger.py"):
            # One extra wrapper level — go up one more
            frame = sys._getframe(3)
            filename = frame.f_code.co_filename
        src = os.path.splitext(os.path.basename(filename))[0]
    except ValueError:
        pass
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), "level": level, "src": src, "msg": str(msg)}
    _buffer.append(entry)

    # Write to JSONL file
    global _file_trimmed
    try:
        with _file_lock:
            if not _file_trimmed:
                _file_trimmed = True
                _trim_log_file()
            with open(_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Never let logging crash the plugin

    # Emit signal (caught by the dialog log panel if open)
    try:
        _bus.new_entry.emit(entry)
    except Exception:
        pass


def _trim_log_file():
    """Keep the last _MAX_FILE_LINES lines of the log file (before the first entry of a session)."""
    path = _log_path()
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > _MAX_FILE_LINES:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines[-_MAX_FILE_LINES:])
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────────


def info(msg: str):
    QgsMessageLog.logMessage(str(msg), TAG, Qgis.MessageLevel.Info)
    _write("INFO", msg)


def warning(msg: str):
    QgsMessageLog.logMessage(str(msg), TAG, Qgis.MessageLevel.Warning)
    _write("WARNING", msg)


def error(msg: str, exc_info: bool = False):
    full = str(msg)
    if exc_info:
        tb = traceback.format_exc()
        if tb and tb.strip() != "NoneType: None":
            full = f"{msg}\n{tb}"
    QgsMessageLog.logMessage(full, TAG, Qgis.MessageLevel.Critical)
    _write("ERROR", full)
