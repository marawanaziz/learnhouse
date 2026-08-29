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


def test_operations_console_has_guarded_delete_for_training_certificates_only():
    """The Operations member drawer exposes deletion only for issued cert rows."""
    page = console._PAGE
    assert "certificate-delete-trigger" in page
    assert "data-certificate-uuid" in page
    assert "requestCertificateDelete(this)" in page
    assert "Delete issued certificate?" in page
    assert "This removes the issued certificate for" in page
    assert "method:'DELETE'" in page
    assert "CERTIFICATE_ORG_SLUG='bbu'" in page
    assert "openCredentialMember(pending.userId)" in page

    training_start = page.index("const training=")
    issues_start = page.index("const issues=", training_start)
    training_source = page[training_start:issues_start]
    assert "certificate-delete-trigger" in training_source
    assert "data-certificate-uuid" in training_source
    assert "c.uuid&&c.id!=null" in training_source

    issues_source = page[issues_start:page.index("const apps=", issues_start)]
    assert "certificate-delete-trigger" not in issues_source
