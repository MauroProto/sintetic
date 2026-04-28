from pathlib import Path

from synthetic_ds.verify import run_mock_full_verification


def test_mock_full_verification_cleans_up_workspace(tmp_path: Path) -> None:
    summary = run_mock_full_verification(base_tmp_dir=tmp_path)

    assert summary["ok"] is True
    assert summary["mode"] == "mock-full"
    assert not any(tmp_path.iterdir())
