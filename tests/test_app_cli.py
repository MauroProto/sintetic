from typer.testing import CliRunner

from synthetic_ds.cli import app


def test_app_command_exists() -> None:
    result = CliRunner().invoke(app, ["app", "--help"])

    assert result.exit_code == 0
    assert "local visual app" in result.output.lower()
