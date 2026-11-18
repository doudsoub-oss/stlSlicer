import subprocess
import sys

import pytest

from stlsplit import __version__, cli


def test_version_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"stlsplit {__version__}"


def test_help_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "stlsplit", "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert "usage: stlsplit" in result.stdout
