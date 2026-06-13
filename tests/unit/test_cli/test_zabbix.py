import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from unifi_manager.settings import Settings, UnifiAuthSettings


@pytest.mark.fast
def test_zabbix_stats_outputs_lld_json(tmp_path: Path) -> None:
    from unifi_manager.cli.main import app

    runner = CliRunner()
    with (
        patch("unifi_manager.cli.zabbix.load_settings") as mock_settings,
        patch("unifi_manager.cli.zabbix.build_legacy_client") as mock_client_fn,
    ):
        mock_settings.return_value = Settings(
            unifi=UnifiAuthSettings(
                host="1.2.3.4",
                port=11443,
                site="t",
                username=SecretStr("u"),
                password=SecretStr("p"),
            ),
        )
        mock_client = mock_client_fn.return_value
        mock_client.list_devices_raw.return_value = [
            {
                "mac": "aa:01",
                "name": "AP1",
                "model": "U7IW",
                "sysid": 58759,
                "type": "uap",
                "state": 1,
            },
        ]
        result = runner.invoke(app, ["zabbix", "stats"])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "data" in parsed
    assert len(parsed["data"]) == 1
    assert parsed["data"][0]["{#MODEL}"] == "UAP-AC-IW"  # via SYSID_MAP
