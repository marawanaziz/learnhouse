"""Regression coverage for the Operations console's rendered JavaScript."""
import shutil
import subprocess

import pytest

from src.bbu_admin import console


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node.js is required to parse the rendered Operations script",
)
def test_operations_console_inline_script_is_valid_javascript():
    """The Python f-string must render to JavaScript the browser can execute."""
    script = console._PAGE.split("<script>", 1)[1].split("</script>", 1)[0]

    result = subprocess.run(
        ["node", "--check", "-"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
