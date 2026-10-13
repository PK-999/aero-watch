import subprocess
import sys
from pathlib import Path


def test_install_verifier_rejects_missing_wheel(tmp_path):
    script = Path(__file__).parents[1] / "scripts" / "verify_install.py"
    result = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "missing.whl")],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 2
    assert "existing .whl file" in result.stderr
