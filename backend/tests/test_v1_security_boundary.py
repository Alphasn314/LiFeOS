from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
PYTHON_PRODUCTION_ROOTS = (
    REPOSITORY_ROOT / "backend" / "lifeos",
    REPOSITORY_ROOT / "windows-agent" / "src",
)
FORBIDDEN_IMPORT_ROOTS = {
    "cv2",
    "mss",
    "pyaudio",
    "sounddevice",
    "subprocess",
    "winreg",
}
FORBIDDEN_EXECUTION_TOKENS = {
    "CreateProcessW(",
    "ImageGrab.grab(",
    "ShellExecuteW(",
    "TerminateProcess(",
    "taskkill.exe",
}


def test_v1_ships_no_camera_audio_shell_or_real_blocking_capability() -> None:
    imported_roots: set[str] = set()
    production_text = ""
    for root in PYTHON_PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            production_text += source
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_roots.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported_roots.add(node.module.split(".")[0])

    assert not (imported_roots & FORBIDDEN_IMPORT_ROOTS)
    assert not any(token in production_text for token in FORBIDDEN_EXECUTION_TOKENS)
