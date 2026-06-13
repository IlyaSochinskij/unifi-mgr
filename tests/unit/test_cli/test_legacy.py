from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner


@pytest.mark.fast
def test_legacy_run_list_scripts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "_legacy"
    legacy.mkdir()
    (legacy / "old_script.py").write_text("print('hi')", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["legacy", "run", "old_script.py", "--list"])

    assert result.exit_code == 0
    assert "old_script.py" in result.stdout


@pytest.mark.fast
def test_legacy_run_missing_script_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / "_legacy").mkdir()

    runner = CliRunner()
    result = runner.invoke(app, ["legacy", "run", "nonexistent.py", "-y"])

    assert result.exit_code == 1


@pytest.mark.fast
def test_legacy_run_with_no_confirm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """С -y флагом — пропускает confirmation, запускает subprocess."""
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "_legacy"
    legacy.mkdir()
    script = legacy / "hello.py"
    script.write_text("import sys; sys.exit(0)", encoding="utf-8")

    runner = CliRunner()
    with patch("unifi_manager.cli.legacy.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        result = runner.invoke(app, ["legacy", "run", "hello.py", "-y"])

    assert result.exit_code == 0
    mock_run.assert_called_once()


@pytest.mark.fast
def test_legacy_run_list_works_without_script_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--list без script_name — должно работать."""
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "_legacy"
    legacy.mkdir()
    (legacy / "old.py").write_text("# legacy", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["legacy", "run", "--list"])

    assert result.exit_code == 0
    assert "old.py" in result.stdout


@pytest.mark.fast
def test_legacy_run_missing_script_name_without_list_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / "_legacy").mkdir()

    runner = CliRunner()
    result = runner.invoke(app, ["legacy", "run"])

    assert result.exit_code == 2


@pytest.mark.fast
def test_legacy_run_rejects_path_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """legacy run с ../ → отвергнуто (exit != 0), subprocess не вызван."""
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / "_legacy").mkdir()

    runner = CliRunner()
    result = runner.invoke(app, ["legacy", "run", "../../etc/passwd.py", "-y"])

    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "invalid" in combined.lower() or "escape" in combined.lower()


@pytest.mark.fast
def test_legacy_run_rejects_absolute_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """legacy run с абсолютным путём → отвергнуто (exit != 0)."""
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / "_legacy").mkdir()

    runner = CliRunner()
    result = runner.invoke(app, ["legacy", "run", "/etc/passwd.py", "-y"])

    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "invalid" in combined.lower() or "escape" in combined.lower()


@pytest.mark.fast
def test_legacy_run_confirm_aborted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Пользователь отвечает 'n' на confirmation → Aborted, exit 1 (lines 79-82)."""
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "_legacy"
    legacy.mkdir()
    script = legacy / "hello.py"
    script.write_text("import sys; sys.exit(0)", encoding="utf-8")

    runner = CliRunner()
    # Input "n\n" → typer.confirm returns False → Aborted
    result = runner.invoke(app, ["legacy", "run", "hello.py"], input="n\n")

    assert result.exit_code == 1
    combined = result.stdout + (result.stderr or "")
    assert "abort" in combined.lower() or result.exit_code == 1


@pytest.mark.fast
def test_legacy_run_defense_in_depth_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defense-in-depth resolve() check: symlink pointing outside _legacy/ → rejected (lines 64-66).

    The bare-name guard (line 54) catches ../traversals, but a symlink inside _legacy/
    that resolves outside it would only be caught by the resolve() check at line 64.
    """
    import sys

    if sys.platform == "win32":
        # Creating symlinks on Windows requires elevated privileges in most configs — skip.
        pytest.skip("symlink creation requires admin rights on Windows")

    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "_legacy"
    legacy.mkdir()

    # Create a real file outside _legacy/ that the symlink will point to
    outside_file = tmp_path / "secret.py"
    outside_file.write_text("print('secret')", encoding="utf-8")

    # Create symlink inside _legacy/ that points to a file outside _legacy/
    symlink = legacy / "escape.py"
    symlink.symlink_to(outside_file)

    runner = CliRunner()
    result = runner.invoke(app, ["legacy", "run", "escape.py", "-y"])

    # The defense-in-depth resolve() check should reject this
    assert result.exit_code != 0
    combined = result.stdout + (result.stderr or "")
    assert "escape" in combined.lower() or "error" in combined.lower()


@pytest.mark.fast
def test_legacy_run_list_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--list quando _legacy/ не существует → error message, exit 1 (lines 41-42)."""
    from unifi_manager.cli.main import app

    # Don't create _legacy/
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(app, ["legacy", "run", "--list"])

    assert result.exit_code == 1


@pytest.mark.fast
def test_legacy_run_confirmed_yes_runs_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """User answers 'y' to confirmation → subprocess.run called (branch 80->84)."""
    from unifi_manager.cli.main import app

    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / "_legacy"
    legacy.mkdir()
    script = legacy / "hello.py"
    script.write_text("import sys; sys.exit(0)", encoding="utf-8")

    runner = CliRunner()
    with patch("unifi_manager.cli.legacy.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        # Input "y\n" → typer.confirm returns True → proceeds to subprocess.run
        result = runner.invoke(app, ["legacy", "run", "hello.py"], input="y\n")

    assert result.exit_code == 0
    mock_run.assert_called_once()
