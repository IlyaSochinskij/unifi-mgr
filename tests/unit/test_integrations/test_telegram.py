"""Тесты для unifi_manager.integrations.telegram."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
import responses
from freezegun import freeze_time
from pydantic import SecretStr

from unifi_manager.settings import Settings, TelegramSettings, UnifiAuthSettings


@pytest.fixture()
def telegram_settings() -> TelegramSettings:
    return TelegramSettings(
        bot_token=SecretStr("123456789:ABCdef-test-token"),
        chat_id="987654321",
        enabled=True,
        parse_mode="MarkdownV2",
        rate_limit_per_hash_seconds=30,
        rate_limit_total_per_minute=5,
    )


@pytest.fixture()
def full_settings_with_telegram(telegram_settings: TelegramSettings) -> Settings:
    return Settings(
        unifi=UnifiAuthSettings(host="1.2.3.4", port=11443, site="test"),
        telegram=telegram_settings,
    )


# === escape_markdown_v2 ===


@pytest.mark.fast()
def test_escape_markdown_v2_basic() -> None:
    """MarkdownV2 reserved chars экранируются backslash."""
    from unifi_manager.integrations.telegram import escape_markdown_v2

    assert escape_markdown_v2("hello") == "hello"
    assert escape_markdown_v2("test.thing") == "test\\.thing"
    assert escape_markdown_v2("a+b=c") == "a\\+b\\=c"


@pytest.mark.fast()
def test_escape_markdown_v2_all_reserved() -> None:
    """Все 18 reserved chars MarkdownV2: _ * [ ] ( ) ~ ` > # + - = | { } . !"""
    from unifi_manager.integrations.telegram import escape_markdown_v2

    raw = "_*[]()~`>#+-=|{}.!"
    escaped = escape_markdown_v2(raw)
    for ch in raw:
        assert f"\\{ch}" in escaped


@pytest.mark.fast()
def test_escape_markdown_v2_preserves_normal_text() -> None:
    from unifi_manager.integrations.telegram import escape_markdown_v2

    assert escape_markdown_v2("Restoran AP offline 5 min") == "Restoran AP offline 5 min"


# === TelegramRateLimiter ===


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_rate_limiter_allows_first_call(
    tmp_path: Path, telegram_settings: TelegramSettings
) -> None:
    from unifi_manager.integrations.telegram import TelegramRateLimiter

    rl = TelegramRateLimiter(state_file=tmp_path / "throttle.json", settings=telegram_settings)
    assert rl.allow(hash_key="ap-down:aa:bb") is True


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_rate_limiter_blocks_same_hash_within_window(
    tmp_path: Path, telegram_settings: TelegramSettings
) -> None:
    """Тот же hash в течение rate_limit_per_hash_seconds (30s) — blocked."""
    from unifi_manager.integrations.telegram import TelegramRateLimiter

    rl = TelegramRateLimiter(state_file=tmp_path / "throttle.json", settings=telegram_settings)
    assert rl.allow(hash_key="ap-down:aa:bb") is True
    assert rl.allow(hash_key="ap-down:aa:bb") is False


@pytest.mark.fast()
def test_rate_limiter_allows_after_hash_cooldown(
    tmp_path: Path, telegram_settings: TelegramSettings
) -> None:
    """После 31 секунды тот же hash снова allow."""
    from unifi_manager.integrations.telegram import TelegramRateLimiter

    with freeze_time("2026-05-16 10:00:00") as frozen:
        rl = TelegramRateLimiter(state_file=tmp_path / "throttle.json", settings=telegram_settings)
        rl.allow(hash_key="ap-down:aa:bb")

        frozen.tick(delta=timedelta(seconds=31))
        assert rl.allow(hash_key="ap-down:aa:bb") is True


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_rate_limiter_blocks_more_than_total_per_minute(
    tmp_path: Path, telegram_settings: TelegramSettings
) -> None:
    """Не более 5 разных msg в минуту суммарно."""
    from unifi_manager.integrations.telegram import TelegramRateLimiter

    rl = TelegramRateLimiter(state_file=tmp_path / "throttle.json", settings=telegram_settings)
    # 5 разных hashes — все allow
    for i in range(5):
        assert rl.allow(hash_key=f"hash-{i}") is True
    # 6-й — blocked
    assert rl.allow(hash_key="hash-6") is False


@pytest.mark.fast()
def test_rate_limiter_total_window_resets_after_minute(
    tmp_path: Path, telegram_settings: TelegramSettings
) -> None:
    """После 61 секунды старые алерты выпадают из total count."""
    from unifi_manager.integrations.telegram import TelegramRateLimiter

    with freeze_time("2026-05-16 10:00:00") as frozen:
        rl = TelegramRateLimiter(state_file=tmp_path / "throttle.json", settings=telegram_settings)
        for i in range(5):
            rl.allow(hash_key=f"hash-{i}")

        frozen.tick(delta=timedelta(seconds=61))
        # старые out of window — новый hash снова allow
        assert rl.allow(hash_key="hash-new") is True


# === send_message ===


@pytest.mark.fast()
@responses.activate
@freeze_time("2026-05-16 10:00:00")
def test_send_message_calls_telegram_api(
    tmp_path: Path, full_settings_with_telegram: Settings, fixtures_dir: Path
) -> None:
    from unifi_manager.integrations.telegram import TelegramNotifier

    expected_url = "https://api.telegram.org/bot123456789:ABCdef-test-token/sendMessage"
    response_data = json.loads(
        (fixtures_dir / "telegram_send_response.json").read_text(encoding="utf-8")
    )
    responses.post(expected_url, json=response_data, status=200)

    notifier = TelegramNotifier(
        settings=full_settings_with_telegram.telegram,
        rate_limit_state=tmp_path / "throttle.json",
    )
    result = notifier.send_message("Hello world", hash_key="test")
    assert result is True
    assert len(responses.calls) == 1


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_send_message_blocked_by_rate_limit(
    tmp_path: Path, full_settings_with_telegram: Settings
) -> None:
    """Если rate-limit блокирует — send_message returns False, не делает HTTP."""
    from unifi_manager.integrations.telegram import TelegramNotifier

    notifier = TelegramNotifier(
        settings=full_settings_with_telegram.telegram,
        rate_limit_state=tmp_path / "throttle.json",
    )

    # Первый — отправляется (но без HTTP мока — мы не дойдём до HTTP)
    # Симулируем что rate-limit уже исчерпан для этого hash
    notifier.rate_limiter.allow(hash_key="test")  # records
    result = notifier.send_message("Spam", hash_key="test")
    assert result is False


@pytest.mark.fast()
def test_send_message_disabled_returns_false(
    tmp_path: Path,
) -> None:
    """telegram.enabled=False → send_message всегда False, без HTTP."""
    from unifi_manager.integrations.telegram import TelegramNotifier

    settings = TelegramSettings(
        bot_token=SecretStr("test"),
        chat_id="123",
        enabled=False,
    )
    notifier = TelegramNotifier(
        settings=settings,
        rate_limit_state=tmp_path / "throttle.json",
    )
    assert notifier.send_message("ignored", hash_key="x") is False


@pytest.mark.fast()
def test_send_message_missing_token_raises(tmp_path: Path) -> None:
    """bot_token=None → ValueError при init."""
    from unifi_manager.integrations.telegram import TelegramNotifier

    settings = TelegramSettings(bot_token=None, chat_id="123", enabled=True)
    with pytest.raises(ValueError, match="bot_token required"):
        TelegramNotifier(
            settings=settings,
            rate_limit_state=tmp_path / "throttle.json",
        )


@pytest.mark.fast()
def test_telegram_notifier_missing_chat_id_raises(tmp_path: Path) -> None:
    """chat_id=None при enabled=True → ValueError при init."""
    from unifi_manager.integrations.telegram import TelegramNotifier

    settings = TelegramSettings(
        bot_token=SecretStr("test"),
        chat_id=None,
        enabled=True,
    )
    with pytest.raises(ValueError, match="chat_id required"):
        TelegramNotifier(
            settings=settings,
            rate_limit_state=tmp_path / "throttle.json",
        )


# === Additional coverage tests ===


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_rate_limiter_load_corrupted_json(
    tmp_path: Path, telegram_settings: TelegramSettings
) -> None:
    """Повреждённый JSON в state-file — graceful fallback, first call allowed."""
    from unifi_manager.integrations.telegram import TelegramRateLimiter

    state_file = tmp_path / "throttle.json"
    state_file.write_text("not valid json", encoding="utf-8")

    rl = TelegramRateLimiter(state_file=state_file, settings=telegram_settings)
    # corrupted state ignored, first call should be allowed
    assert rl.allow(hash_key="ap-x") is True


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_rate_limiter_bad_timestamp_in_total_skipped(
    tmp_path: Path, telegram_settings: TelegramSettings
) -> None:
    """Некорректный timestamp в total deque — popleft и продолжаем."""
    import json as _json

    from unifi_manager.integrations.telegram import TelegramRateLimiter

    state_file = tmp_path / "throttle.json"
    # Inject a bad total entry (from past, will be cleaned), plus a bad non-parseable one
    state_file.write_text(
        _json.dumps({"hashes": {}, "total": ["not-a-date"]}),
        encoding="utf-8",
    )

    rl = TelegramRateLimiter(state_file=state_file, settings=telegram_settings)
    # bad entry gets popped, call goes through
    assert rl.allow(hash_key="ap-x") is True


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_rate_limiter_bad_hash_timestamp_treated_as_allowed(
    tmp_path: Path, telegram_settings: TelegramSettings
) -> None:
    """Некорректный timestamp для hash — treated as if never sent."""
    import json as _json

    from unifi_manager.integrations.telegram import TelegramRateLimiter

    state_file = tmp_path / "throttle.json"
    state_file.write_text(
        _json.dumps({"hashes": {"ap-down:aa:bb": "not-a-date"}, "total": []}),
        encoding="utf-8",
    )

    rl = TelegramRateLimiter(state_file=state_file, settings=telegram_settings)
    assert rl.allow(hash_key="ap-down:aa:bb") is True


@pytest.mark.fast()
@responses.activate
@freeze_time("2026-05-16 10:00:00")
def test_send_message_http_failure_returns_false(
    tmp_path: Path, full_settings_with_telegram: Settings
) -> None:
    """HTTP error from Telegram API → returns False, logs error."""
    from unifi_manager.integrations.telegram import TelegramNotifier

    expected_url = "https://api.telegram.org/bot123456789:ABCdef-test-token/sendMessage"
    responses.post(expected_url, status=500)

    notifier = TelegramNotifier(
        settings=full_settings_with_telegram.telegram,
        rate_limit_state=tmp_path / "throttle.json",
    )
    result = notifier.send_message("Hello", hash_key="test-fail")
    assert result is False


@pytest.mark.fast()
@responses.activate
@freeze_time("2026-05-16 10:00:00")
def test_failed_send_does_not_consume_rate_limit_budget(
    tmp_path: Path, full_settings_with_telegram: Settings
) -> None:
    """EH3: неудачная отправка НЕ должна тратить rate-limit — иначе немедленный retry заблокирован."""
    from unifi_manager.integrations.telegram import TelegramNotifier

    url = "https://api.telegram.org/bot123456789:ABCdef-test-token/sendMessage"
    responses.post(url, status=500)  # 1-й запрос падает
    responses.post(url, status=200, json={"ok": True})  # 2-й (retry) — успех

    notifier = TelegramNotifier(
        settings=full_settings_with_telegram.telegram,
        rate_limit_state=tmp_path / "throttle.json",
    )
    assert notifier.send_message("Hi", hash_key="dup") is False
    # Тот же hash в том же окне: бюджет не потрачен на провал → retry проходит.
    assert notifier.send_message("Hi retry", hash_key="dup") is True


@pytest.mark.fast()
@responses.activate
@freeze_time("2026-05-16 10:00:00")
def test_send_failure_does_not_log_bot_token(
    tmp_path: Path, full_settings_with_telegram: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """SEC2: bot-token не должен утечь в лог через текст исключения (URL с /bot<TOKEN>/)."""
    import logging

    from unifi_manager.integrations.telegram import TelegramNotifier

    url = "https://api.telegram.org/bot123456789:ABCdef-test-token/sendMessage"
    responses.post(url, status=500)

    notifier = TelegramNotifier(
        settings=full_settings_with_telegram.telegram,
        rate_limit_state=tmp_path / "throttle.json",
    )
    with caplog.at_level(logging.ERROR):
        notifier.send_message("Hi", hash_key="leak")

    assert "ABCdef-test-token" not in caplog.text
    assert "123456789:ABCdef-test-token" not in caplog.text


@pytest.mark.fast()
@responses.activate
@freeze_time("2026-05-16 10:00:00")
def test_send_message_escapes_markdownv2_reserved_chars(
    tmp_path: Path, full_settings_with_telegram: Settings, fixtures_dir: Path
) -> None:
    """Под parse_mode=MarkdownV2 reserved chars в тексте экранируются.

    Иначе обычное имя вроде 'Restoran (WIFI) ap_offline' даёт Telegram 400 и
    алерт теряется навсегда (retry падает так же).
    """
    from unifi_manager.integrations.telegram import TelegramNotifier

    expected_url = "https://api.telegram.org/bot123456789:ABCdef-test-token/sendMessage"
    response_data = json.loads(
        (fixtures_dir / "telegram_send_response.json").read_text(encoding="utf-8")
    )
    responses.post(expected_url, json=response_data, status=200)

    notifier = TelegramNotifier(
        settings=full_settings_with_telegram.telegram,  # parse_mode=MarkdownV2
        rate_limit_state=tmp_path / "throttle.json",
    )
    result = notifier.send_message("Restoran (WIFI) ap_offline - 5.2", hash_key="esc")
    assert result is True

    sent = json.loads(responses.calls[0].request.body)
    assert sent["parse_mode"] == "MarkdownV2"
    assert sent["text"] == "Restoran \\(WIFI\\) ap\\_offline \\- 5\\.2"


@pytest.mark.fast()
@responses.activate
@freeze_time("2026-05-16 10:00:00")
def test_send_message_escapes_html_reserved_chars(
    tmp_path: Path, full_settings_with_telegram: Settings, fixtures_dir: Path
) -> None:
    """parse_mode=HTML → < > & экранируются, иначе Telegram парсит как теги или 400."""
    from unifi_manager.integrations.telegram import TelegramNotifier

    full_settings_with_telegram.telegram.parse_mode = "HTML"

    expected_url = "https://api.telegram.org/bot123456789:ABCdef-test-token/sendMessage"
    response_data = json.loads(
        (fixtures_dir / "telegram_send_response.json").read_text(encoding="utf-8")
    )
    responses.post(expected_url, json=response_data, status=200)

    notifier = TelegramNotifier(
        settings=full_settings_with_telegram.telegram,
        rate_limit_state=tmp_path / "throttle.json",
    )
    result = notifier.send_message("AP <Restoran> & status", hash_key="html")
    assert result is True

    sent = json.loads(responses.calls[0].request.body)
    assert sent["parse_mode"] == "HTML"
    assert sent["text"] == "AP &lt;Restoran&gt; &amp; status"
