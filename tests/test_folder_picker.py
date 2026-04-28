import subprocess

from synthetic_ds import folder_picker


def test_pick_directory_uses_osascript_on_macos(monkeypatch) -> None:
    monkeypatch.setattr(folder_picker.sys, "platform", "darwin")

    def fake_run(cmd, capture_output, text, check):
        assert cmd == [
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Seleccionar carpeta de PDFs")',
        ]
        assert capture_output is True
        assert text is True
        assert check is True
        return subprocess.CompletedProcess(cmd, 0, stdout="/Users/mauro/Desktop/proyectos/datasetsintético/demo_pdfs\n")

    monkeypatch.setattr(folder_picker.subprocess, "run", fake_run)

    result = folder_picker.pick_directory()

    assert result == "/Users/mauro/Desktop/proyectos/datasetsintético/demo_pdfs"


def test_pick_directory_returns_none_when_osascript_is_cancelled(monkeypatch) -> None:
    monkeypatch.setattr(folder_picker.sys, "platform", "darwin")

    def fake_run(cmd, capture_output, text, check):
        raise subprocess.CalledProcessError(1, cmd, stderr="User canceled")

    monkeypatch.setattr(folder_picker.subprocess, "run", fake_run)

    result = folder_picker.pick_directory()

    assert result is None
