"""Regression: CLI status output must be encodable on a non-UTF-8 console.

On a Russian-Windows console (cp1251) the decorative status glyphs the CLI used
to print (U+2713 check mark, U+2717 ballot X, U+26A0 warning sign) are not
representable, so commands like `config validate` crashed with
UnicodeEncodeError before reaching their exit. The output must stay ASCII-clean.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.mark.fast
def test_config_validate_output_survives_cp1251_stdout(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    cfg = tmp_path / "config.yaml"
    cfg.write_text("unifi:\n  host: 10.0.0.1\n  site: default\n", encoding="utf-8")

    # cp1251 stdout with strict errors mirrors a Russian-Windows console: any
    # non-cp1251 glyph in the output raises UnicodeEncodeError on write.
    runner = CliRunner(charset="cp1251")
    result = runner.invoke(app, ["config", "validate", "--config", str(cfg)])

    exc = result.exception
    assert not isinstance(exc, UnicodeEncodeError), f"crashed on cp1251 stdout: {exc!r}"
    assert result.exit_code == 0
    # The fix is ASCII status markers ([OK]/[FAIL]/[WARN]), safe on any code page.
    assert result.output.isascii()
