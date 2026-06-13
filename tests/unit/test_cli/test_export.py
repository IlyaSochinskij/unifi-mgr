"""Тесты для unifi_manager.cli.export."""

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from unifi_manager.settings import Settings, UnifiAuthSettings


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(
        unifi=UnifiAuthSettings(
            host="1.2.3.4", port=11443, site="t", username=SecretStr("u"), password=SecretStr("p")
        ),
    )


@pytest.mark.fast
def test_export_clients_csv_to_stdout(tmp_path: Path) -> None:
    """Без --out — пишет в stdout."""
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.export.load_settings") as mock_settings,
        patch("unifi_manager.cli.export.build_legacy_client"),
        patch("unifi_manager.cli.export.ExportService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)

        def fake_export(output, fmt):
            output.write("mac,hostname\naa:bb,laptop\n")

        mock_svc.return_value.export_clients.side_effect = fake_export

        result = runner.invoke(app, ["export", "clients", "--format", "csv"])

    assert result.exit_code == 0
    assert "mac,hostname" in result.stdout


@pytest.mark.fast
def test_export_clients_csv_to_file(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    out_path = tmp_path / "clients.csv"
    runner = CliRunner()
    with (
        patch("unifi_manager.cli.export.load_settings") as mock_settings,
        patch("unifi_manager.cli.export.build_legacy_client"),
        patch("unifi_manager.cli.export.ExportService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)

        def fake_export(output, fmt):
            output.write("mac\naa:bb\n")

        mock_svc.return_value.export_clients.side_effect = fake_export

        result = runner.invoke(
            app, ["export", "clients", "--format", "csv", "--out", str(out_path)]
        )

    assert result.exit_code == 0
    assert out_path.exists()
    assert "mac" in out_path.read_text(encoding="utf-8")


@pytest.mark.fast
def test_export_devices_json(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.export.load_settings") as mock_settings,
        patch("unifi_manager.cli.export.build_legacy_client"),
        patch("unifi_manager.cli.export.ExportService") as mock_svc,
    ):
        mock_settings.return_value = _test_settings(tmp_path)

        def fake_export(output, fmt, **kwargs):
            output.write('[{"mac": "aa:bb"}]')

        mock_svc.return_value.export_devices.side_effect = fake_export

        result = runner.invoke(app, ["export", "devices", "--format", "json"])

    assert result.exit_code == 0
    assert '"mac"' in result.stdout


@pytest.mark.fast
def test_export_invalid_format_exits_nonzero(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.export.load_settings") as mock_settings,
        patch("unifi_manager.cli.export.build_legacy_client"),
    ):
        mock_settings.return_value = _test_settings(tmp_path)

        result = runner.invoke(app, ["export", "clients", "--format", "xml"])

    assert result.exit_code != 0


@pytest.mark.fast
def test_export_devices_default_omits_secret_fields(tmp_path: Path) -> None:
    """export devices (no --raw) не выводит x_authkey и другие секретные поля."""
    from unittest.mock import MagicMock

    from unifi_manager.cli.main import app

    runner = CliRunner()

    fake_client = MagicMock()
    fake_client.list_devices_raw.return_value = [
        {
            "type": "uap",
            "mac": "aa:bb:cc:dd:ee:ff",
            "model": "U7PG2",
            "name": "AP-Lobby",
            "ip": "10.0.1.1",
            "state": 1,
            "x_authkey": "AUTHSECRET",
            "x_adopt_password": "ADOPTPW",
            "x_ssh_hostkey_fingerprint": "FP",
        }
    ]
    fake_client.list_clients_raw.return_value = []

    with (
        patch("unifi_manager.cli.export.load_settings") as mock_settings,
        patch("unifi_manager.cli.export.build_legacy_client", return_value=fake_client),
    ):
        mock_settings.return_value = _test_settings(tmp_path)
        result = runner.invoke(app, ["export", "devices", "--format", "csv"])

    assert result.exit_code == 0
    assert "x_authkey" not in result.stdout
    assert "AUTHSECRET" not in result.stdout
    assert "x_adopt_password" not in result.stdout
    assert "ADOPTPW" not in result.stdout
    assert "x_ssh_hostkey_fingerprint" not in result.stdout
    # safe fields must be present
    assert "aa:bb:cc:dd:ee:ff" in result.stdout
    assert "AP-Lobby" in result.stdout
