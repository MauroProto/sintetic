from __future__ import annotations

import subprocess
import sys


def _pick_directory_macos() -> tuple[bool, str | None]:
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'POSIX path of (choose folder with prompt "Seleccionar carpeta de PDFs")',
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        return False, None
    except subprocess.CalledProcessError:
        return True, None
    selected = result.stdout.strip()
    return True, selected or None


def _pick_directory_tk() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return filedialog.askdirectory() or None
    finally:
        root.destroy()


def pick_directory() -> str | None:
    if sys.platform == "darwin":
        handled, selected = _pick_directory_macos()
        if handled:
            return selected
    return _pick_directory_tk()
