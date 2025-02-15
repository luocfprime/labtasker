import pytest
from typer.testing import CliRunner

from labtasker.client.cli import app

runner = CliRunner()


@pytest.mark.unit
@pytest.mark.integration
@pytest.mark.e2e
def test_full_health():
    result = runner.invoke(app, ["health"])
    assert result.exit_code == 0
    assert "healthy" in result.stdout
