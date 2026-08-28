"""Minimal, read-only Windows activity sensors behind an injectable boundary."""

from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol

import psutil

from .models import ObservationPayload

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RawWindowsSample:
    process_id: int | None
    window_title: str | None
    idle_seconds: int | None
    is_locked: bool | None


class SensorBackend(Protocol):
    def collect(self) -> RawWindowsSample: ...


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class CtypesWindowsSensor:
    """Read only documented desktop state; never captures input content."""

    _DESKTOP_SWITCHDESKTOP = 0x0100

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows sensors are only available on Windows")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._user32.GetWindowTextW.restype = ctypes.c_int
        self._user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LastInputInfo)]
        self._user32.GetLastInputInfo.restype = wintypes.BOOL
        self._kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        self._user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._user32.OpenInputDesktop.restype = wintypes.HANDLE
        self._user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
        self._user32.SwitchDesktop.restype = wintypes.BOOL
        self._user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        self._user32.CloseDesktop.restype = wintypes.BOOL

    def collect(self) -> RawWindowsSample:
        process_id, title = self._foreground()
        return RawWindowsSample(
            process_id=process_id,
            window_title=title,
            idle_seconds=self._idle_seconds(),
            is_locked=self._is_locked(),
        )

    def _foreground(self) -> tuple[int | None, str | None]:
        window = self._user32.GetForegroundWindow()
        if not window:
            return None, None
        process_id = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
        title_buffer = ctypes.create_unicode_buffer(257)
        copied = self._user32.GetWindowTextW(window, title_buffer, len(title_buffer))
        title = title_buffer.value[:256] if copied > 0 else None
        return int(process_id.value) or None, title

    def _idle_seconds(self) -> int:
        info = _LastInputInfo(cbSize=ctypes.sizeof(_LastInputInfo), dwTime=0)
        if not self._user32.GetLastInputInfo(ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        current_tick = int(self._kernel32.GetTickCount64()) & 0xFFFFFFFF
        elapsed_ms = (current_tick - int(info.dwTime)) & 0xFFFFFFFF
        return min(elapsed_ms // 1000, 86400)

    def _is_locked(self) -> bool | None:
        desktop = self._user32.OpenInputDesktop(0, False, self._DESKTOP_SWITCHDESKTOP)
        if not desktop:
            # Failure to inspect a secure desktop must not be interpreted as user activity.
            return None
        try:
            return not bool(self._user32.SwitchDesktop(desktop))
        finally:
            self._user32.CloseDesktop(desktop)


class ActivityCollector:
    def __init__(self, backend: SensorBackend | None = None) -> None:
        self._backend = backend
        if backend is None:
            try:
                self._backend = CtypesWindowsSensor()
            except OSError:
                self._backend = None

    def collect(self) -> tuple[ObservationPayload, list[str]]:
        if self._backend is None:
            return ObservationPayload(sensor_ok=False), ["SENSOR_FAILURE"]
        try:
            sample = self._backend.collect()
            process_name = self._resolve_process_name(sample.process_id)
            payload = ObservationPayload(
                foreground_process=process_name[:128] if process_name else None,
                window_title=sample.window_title[:256] if sample.window_title else None,
                idle_seconds=sample.idle_seconds,
                is_locked=sample.is_locked,
                sensor_ok=True,
            )
            return payload, ["SENSOR_SAMPLE"]
        except (OSError, psutil.Error, ctypes.ArgumentError, ValueError):
            logger.warning("Windows sensor sample failed", exc_info=True)
            return ObservationPayload(sensor_ok=False), ["SENSOR_FAILURE"]

    @staticmethod
    def _resolve_process_name(process_id: int | None) -> str | None:
        if process_id is None:
            return None
        return str(psutil.Process(process_id).name())
