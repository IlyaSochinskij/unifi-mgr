"""Тесты для unifi_manager.settings."""

from pathlib import Path

import pytest
from pydantic import ValidationError


@pytest.mark.fast()
def test_settings_loads_from_yaml(fixtures_dir: Path, tmp_config_dir: Path) -> None:
    """Settings парсит config.yaml без обязательных env переменных
    (если все обязательные поля в YAML)."""
    yaml_src = fixtures_dir / "settings_minimal.yaml"
    (tmp_config_dir / "config.yaml").write_bytes(yaml_src.read_bytes())

    from unifi_manager.settings import Settings

    settings = Settings()  # type: ignore[call-arg]
    assert settings.unifi.host == "192.0.2.1"
    assert settings.unifi.port == 11443
    assert settings.unifi.site == "site-1"


@pytest.mark.fast()
def test_settings_loads_full_yaml(fixtures_dir: Path, tmp_config_dir: Path) -> None:
    """Settings парсит config.yaml со всеми секциями без ошибок."""
    yaml_src = fixtures_dir / "settings_full.yaml"
    (tmp_config_dir / "config.yaml").write_bytes(yaml_src.read_bytes())

    from unifi_manager.settings import Settings

    settings = Settings()  # type: ignore[call-arg]

    assert "restaurant" in settings.restart_profiles
    assert settings.restart_profiles["restaurant"].lost_contact_threshold == 3
    assert settings.thresholds.port_error_delta_threshold == 50
    assert settings.audit_health_check.enabled is True
    assert settings.maintenance.max_mute_duration_hours == 24


@pytest.mark.fast()
def test_env_overrides_yaml(
    fixtures_dir: Path, tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ENV переменные имеют приоритет над YAML."""
    yaml_src = fixtures_dir / "settings_minimal.yaml"
    (tmp_config_dir / "config.yaml").write_bytes(yaml_src.read_bytes())

    monkeypatch.setenv("UNIFI_UNIFI__HOST", "10.0.0.99")
    monkeypatch.setenv("UNIFI_UNIFI__USERNAME", "TestUser")
    monkeypatch.setenv("UNIFI_UNIFI__PASSWORD", "test-secret-pass")

    from unifi_manager.settings import Settings

    settings = Settings()  # type: ignore[call-arg]
    assert settings.unifi.host == "10.0.0.99"
    assert settings.unifi.username is not None
    assert settings.unifi.username.get_secret_value() == "TestUser"
    assert settings.unifi.password is not None
    assert settings.unifi.password.get_secret_value() == "test-secret-pass"


@pytest.mark.fast()
def test_secrets_are_masked_in_repr(tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SecretStr скрывает значение в repr — защита от случайного print."""
    (tmp_config_dir / "config.yaml").write_text(
        """
unifi:
  host: 1.2.3.4
  port: 11443
  site: test
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("UNIFI_UNIFI__PASSWORD", "super-secret-do-not-leak")

    from unifi_manager.settings import Settings

    settings = Settings()  # type: ignore[call-arg]
    assert "super-secret-do-not-leak" not in repr(settings)
    assert "super-secret-do-not-leak" not in str(settings.unifi)


@pytest.mark.fast()
def test_missing_required_field_raises(tmp_config_dir: Path) -> None:
    """Settings падает с ValidationError если нет обязательного unifi.host."""
    (tmp_config_dir / "config.yaml").write_text(
        """
unifi:
  port: 11443
  site: test
""",
        encoding="utf-8",
    )
    from unifi_manager.settings import Settings

    with pytest.raises(ValidationError) as exc_info:
        Settings()  # type: ignore[call-arg]
    assert "host" in str(exc_info.value)


@pytest.mark.fast()
def test_extra_field_forbidden(tmp_config_dir: Path) -> None:
    """extra='forbid' на верхнем уровне — опечатки в YAML дают ошибку."""
    (tmp_config_dir / "config.yaml").write_text(
        """
unifi:
  host: 1.2.3.4
  port: 11443
  site: test
unknown_typo_section:
  something: 42
""",
        encoding="utf-8",
    )
    from unifi_manager.settings import Settings

    with pytest.raises(ValidationError) as exc_info:
        Settings()  # type: ignore[call-arg]
    assert "unknown_typo_section" in str(exc_info.value) or "Extra" in str(exc_info.value)


@pytest.mark.fast()
def test_restart_profiles_dict_works(tmp_config_dir: Path) -> None:
    """restart_profiles — dict[str, RestartProfile]."""
    (tmp_config_dir / "config.yaml").write_text(
        """
unifi:
  host: 1.2.3.4
  port: 11443
  site: test

restart_profiles:
  restaurant:
    filter_names: [Restoran]
    lost_contact_threshold: 3
  office:
    filter_patterns: ["^office.*"]
    lost_contact_threshold: 5
""",
        encoding="utf-8",
    )
    from unifi_manager.settings import Settings

    settings = Settings()  # type: ignore[call-arg]
    assert set(settings.restart_profiles.keys()) == {"restaurant", "office"}
    assert settings.restart_profiles["restaurant"].lost_contact_threshold == 3
    assert settings.restart_profiles["office"].filter_patterns == ["^office.*"]


@pytest.mark.fast()
def test_find_yaml_uses_env_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """UNIFI_CONFIG_PATH env var указывает на конкретный YAML, минуя стандартный поиск."""
    yaml_file = tmp_path / "custom-name.yaml"
    yaml_file.write_text(
        "unifi:\n  host: 5.6.7.8\n  port: 11443\n  site: custom-site\n",
        encoding="utf-8",
    )
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.chdir(empty_dir)  # ./config.yaml не существует — должны взять UNIFI_CONFIG_PATH
    monkeypatch.setenv("UNIFI_CONFIG_PATH", str(yaml_file))

    from unifi_manager.settings import Settings

    settings = Settings()  # type: ignore[call-arg]
    assert settings.unifi.host == "5.6.7.8"
    assert settings.unifi.site == "custom-site"


@pytest.mark.fast()
def test_find_yaml_raises_on_nonexistent_env_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UNIFI_CONFIG_PATH указывает на несуществующий файл → ValueError с описательным сообщением."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UNIFI_CONFIG_PATH", str(tmp_path / "does-not-exist.yaml"))

    from unifi_manager.settings import Settings

    with pytest.raises(ValueError, match="UNIFI_CONFIG_PATH"):
        Settings()  # type: ignore[call-arg]


@pytest.mark.fast
def test_max_restarts_per_run_rejects_zero(tmp_config_dir: Path) -> None:
    """max_restarts_per_run=0 → ValidationError (cap must be >=1)."""
    (tmp_config_dir / "config.yaml").write_text(
        "unifi:\n  host: 192.0.2.1\n  port: 11443\n  site: site-1\n"
        "auto_restart:\n  max_restarts_per_run: 0\n",
        encoding="utf-8",
    )
    from unifi_manager.settings import Settings

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


@pytest.mark.fast
def test_max_restarts_per_run_rejects_too_high(tmp_config_dir: Path) -> None:
    (tmp_config_dir / "config.yaml").write_text(
        "unifi:\n  host: 192.0.2.1\n  port: 11443\n  site: site-1\n"
        "auto_restart:\n  max_restarts_per_run: 999\n",
        encoding="utf-8",
    )
    from unifi_manager.settings import Settings

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


@pytest.mark.fast
def test_max_restarts_per_run_assignment_validates(tmp_config_dir: Path) -> None:
    """validate_assignment=True — присваивание невалидного значения тоже падает."""
    (tmp_config_dir / "config.yaml").write_text(
        "unifi:\n  host: 192.0.2.1\n  port: 11443\n  site: site-1\n",
        encoding="utf-8",
    )
    from unifi_manager.settings import Settings

    s = Settings()  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        s.auto_restart.max_restarts_per_run = -1


@pytest.mark.fast
def test_cooldown_minutes_rejects_negative(tmp_config_dir: Path) -> None:
    (tmp_config_dir / "config.yaml").write_text(
        "unifi:\n  host: 192.0.2.1\n  port: 11443\n  site: site-1\n"
        "auto_restart:\n  cooldown_minutes: -5\n",
        encoding="utf-8",
    )
    from unifi_manager.settings import Settings

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


@pytest.mark.fast()
def test_find_env_file_prefers_beside_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unifi_manager.settings import find_env_file

    monkeypatch.delenv("UNIFI_ENV_FILE", raising=False)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("unifi:\n  host: h\n  site: s\n", encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text("UNIFI_UNIFI__API_KEY=k\n", encoding="utf-8")
    monkeypatch.setenv("UNIFI_CONFIG_PATH", str(cfg))

    assert find_env_file() == env


@pytest.mark.fast()
def test_find_env_file_explicit_env_var_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unifi_manager.settings import find_env_file

    explicit = tmp_path / "custom.env"
    explicit.write_text("X=1\n", encoding="utf-8")
    monkeypatch.setenv("UNIFI_ENV_FILE", str(explicit))
    assert find_env_file() == explicit
