"""Testy dlya unifi_manager.services.notify.AlertHistory."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from freezegun import freeze_time


@pytest.mark.fast()
def test_alert_history_empty_initially(tmp_path: Path) -> None:
    """Svezhiy state-fayl — net prior alerts."""
    from unifi_manager.services.notify import AlertHistory

    history = AlertHistory(state_file=tmp_path / "alerts.json")
    assert history.is_new_alert(hash_key="ap-down:aa:bb") is True


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_alert_history_records_alert(tmp_path: Path) -> None:
    """Posle zapisi hash bolshe ne schitaetsya novym."""
    from unifi_manager.services.notify import AlertHistory

    history = AlertHistory(state_file=tmp_path / "alerts.json")
    history.record_alert(hash_key="ap-down:aa:bb")
    assert history.is_new_alert(hash_key="ap-down:aa:bb") is False


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_alert_history_persists_to_disk(tmp_path: Path) -> None:
    """State sokhranyaetsya na disk — novyy AlertHistory chitaet sushchestvuyushchiy state."""
    from unifi_manager.services.notify import AlertHistory

    state_file = tmp_path / "alerts.json"
    h1 = AlertHistory(state_file=state_file)
    h1.record_alert(hash_key="ap-down:aa:bb")
    h1.save()

    h2 = AlertHistory(state_file=state_file)
    assert h2.is_new_alert(hash_key="ap-down:aa:bb") is False


@pytest.mark.fast()
def test_alert_history_cooldown_expires(tmp_path: Path) -> None:
    """Posle cooldown_minutes alert snova schitaetsya novym (dlya napominaniya)."""
    from unifi_manager.services.notify import AlertHistory

    with freeze_time("2026-05-16 10:00:00") as frozen:
        history = AlertHistory(state_file=tmp_path / "alerts.json", cooldown=timedelta(hours=1))
        history.record_alert(hash_key="ap-down:aa:bb")
        assert history.is_new_alert(hash_key="ap-down:aa:bb") is False

        frozen.move_to("2026-05-16 11:00:30")  # +1h 30s
        assert history.is_new_alert(hash_key="ap-down:aa:bb") is True


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_alert_history_different_hashes_independent(tmp_path: Path) -> None:
    """Raznye hash — nezavisimye dedup."""
    from unifi_manager.services.notify import AlertHistory

    history = AlertHistory(state_file=tmp_path / "alerts.json")
    history.record_alert(hash_key="ap-down:aa:bb")
    assert history.is_new_alert(hash_key="ap-down:cc:dd") is True
    assert history.is_new_alert(hash_key="high-temp:ee:ff") is True


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_alert_history_state_file_format(tmp_path: Path) -> None:
    """State JSON format — dlya otladki operatorom."""
    from unifi_manager.services.notify import AlertHistory

    state_file = tmp_path / "alerts.json"
    history = AlertHistory(state_file=state_file)
    history.record_alert(hash_key="ap-down:aa:bb")
    history.save()

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert "ap-down:aa:bb" in data
    # ISO timestamp format
    assert "2026-05-16" in data["ap-down:aa:bb"]


@pytest.mark.fast()
def test_alert_history_handles_missing_state_file(tmp_path: Path) -> None:
    """Esli state-fayl ne sushchestvuet — startuem s pustogo history."""
    from unifi_manager.services.notify import AlertHistory

    nonexistent = tmp_path / "subdir" / "alerts.json"
    history = AlertHistory(state_file=nonexistent)
    assert history.is_new_alert(hash_key="anything") is True


@pytest.mark.fast()
def test_alert_history_handles_corrupt_state_file(tmp_path: Path) -> None:
    """Bityy JSON v state-fayle — log warning, startuem s pustogo history."""
    from unifi_manager.services.notify import AlertHistory

    state_file = tmp_path / "alerts.json"
    state_file.write_text("not valid json {{{", encoding="utf-8")

    history = AlertHistory(state_file=state_file)
    assert history.is_new_alert(hash_key="anything") is True


@pytest.mark.fast()
def test_alert_history_handles_non_dict_state_file(tmp_path: Path) -> None:
    """Validnyy JSON, no ne dict — log warning, startuem s pustogo history."""
    from unifi_manager.services.notify import AlertHistory

    state_file = tmp_path / "alerts.json"
    state_file.write_text('["not", "a", "dict"]', encoding="utf-8")

    history = AlertHistory(state_file=state_file)
    assert history.is_new_alert(hash_key="anything") is True


@pytest.mark.fast()
def test_alert_history_save_oserror_logged_not_raised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """save() при OSError (read-only fs) — лог error, не raise."""
    from unifi_manager.services.notify import AlertHistory

    # Mock: state_file в read-only path (используем character device или нет permissions)
    # Простой trick — state_file где parent — это файл, не директория
    state_parent_file = tmp_path / "blocking_file"
    state_parent_file.write_text("not a dir", encoding="utf-8")
    state_file = state_parent_file / "alerts.json"  # parent is a file, mkdir will fail

    history = AlertHistory(state_file=state_file)
    history.record_alert(hash_key="test")

    with caplog.at_level("ERROR"):
        history.save()  # should NOT raise

    assert any("Failed to save" in r.message for r in caplog.records)


@pytest.mark.fast()
@freeze_time("2026-05-16 10:00:00")
def test_alert_history_handles_bad_timestamp_in_state(tmp_path: Path) -> None:
    """Nekorrektnyy timestamp v state — traktuetsya kak novyy alert."""
    import json as _json

    from unifi_manager.services.notify import AlertHistory

    state_file = tmp_path / "alerts.json"
    state_file.write_text(
        _json.dumps({"ap-down:aa:bb": "not-a-timestamp"}),
        encoding="utf-8",
    )

    history = AlertHistory(state_file=state_file)
    assert history.is_new_alert(hash_key="ap-down:aa:bb") is True


# === NotifyService (Task 2 + 3) ===


class _FakeNotifier:
    """Соответствует Notifier-протоколу; пишет вызовы, возвращает заданный bool."""

    def __init__(self, returns: bool = True) -> None:
        self.returns = returns
        self.calls: list[tuple[str, str]] = []

    def send_message(self, text: str, *, hash_key: str) -> bool:
        self.calls.append((text, hash_key))
        return self.returns


def _issue(issue_type: str, mac: str):  # type: ignore[no-untyped-def]
    from unifi_manager.services.audit import AuditIssue

    return AuditIssue(issue_type=issue_type, device_mac=mac, device_name=mac, severity="critical")


def _make_settings(*, telegram_send: bool = True, enabled: bool = True):  # type: ignore[no-untyped-def]
    from unifi_manager.settings import Settings, TelegramSettings, UnifiAuthSettings

    s = Settings(
        unifi=UnifiAuthSettings(host="h", port=11443, site="s"),
        telegram=TelegramSettings(enabled=enabled, bot_token=None, chat_id="1"),
    )
    s.permissions.cli.notify.telegram_send = telegram_send
    return s


def _build(tmp_path, *, telegram_send=True, enabled=True, factory=None):  # type: ignore[no-untyped-def]
    from unifi_manager.services.notify import AlertHistory, NotifyService

    return NotifyService(
        settings=_make_settings(telegram_send=telegram_send, enabled=enabled),
        history=AlertHistory(tmp_path / "alerts.json"),
        notifier_factory=factory or (lambda: _FakeNotifier()),
    )


@pytest.mark.fast()
def test_notify_primitives_exist() -> None:
    from unifi_manager.services.notify import AlertLevel, NotifyReport, NotifyStatus

    assert [lvl.value for lvl in AlertLevel] == ["info", "warn", "crit"]
    assert NotifyStatus.no_issues.value == "no_issues"
    assert "enabled" not in [s.value for s in NotifyStatus]  # internal-only
    rep = NotifyReport(status=NotifyStatus.sent, sent=1)
    assert (rep.sent, rep.skipped_dedup, rep.failed) == (1, 0, 0)


@pytest.mark.fast()
def test_notify_no_issues(tmp_path: Path) -> None:
    from unifi_manager.services.notify import NotifyStatus

    assert _build(tmp_path).notify_audit_issues([]).status == NotifyStatus.no_issues


@pytest.mark.fast()
def test_notify_permission_off_never_builds_notifier(tmp_path: Path) -> None:
    """§8 #1: telegram_send=false → нотифаер НЕ строится, skipped_permissions, без ValueError."""
    from unifi_manager.services.notify import NotifyStatus

    built: list[int] = []
    svc = _build(tmp_path, telegram_send=False, factory=lambda: built.append(1) or _FakeNotifier())
    rep = svc.notify_audit_issues([_issue("offline", "aa:bb")])
    assert rep.status == NotifyStatus.skipped_permissions
    assert built == []


@pytest.mark.fast()
def test_notify_disabled(tmp_path: Path) -> None:
    from unifi_manager.services.notify import NotifyStatus

    svc = _build(tmp_path, enabled=False)
    assert (
        svc.notify_audit_issues([_issue("offline", "aa:bb")]).status
        == NotifyStatus.skipped_disabled
    )


@pytest.mark.fast()
def test_notify_channel_unavailable_factory_once(tmp_path: Path) -> None:
    """§8 #2/#8: factory кидает ValueError → channel_unavailable, дёрнута один раз, без утечки."""
    from unifi_manager.services.notify import NotifyStatus

    calls: list[int] = []

    def factory():  # type: ignore[no-untyped-def]
        calls.append(1)
        raise ValueError("no token")

    svc = _build(tmp_path, factory=factory)
    rep = svc.notify_audit_issues([_issue("offline", "aa:bb"), _issue("offline", "cc:dd")])
    assert rep.status == NotifyStatus.channel_unavailable
    assert rep.status != NotifyStatus.failed
    assert calls == [1]  # без per-issue retry


@pytest.mark.fast()
@freeze_time("2026-06-14 10:00:00")
def test_notify_sent_factory_memoized(tmp_path: Path) -> None:
    """§8 #5: несколько issues → factory вызвана ровно один раз; status sent."""
    from unifi_manager.services.notify import NotifyStatus

    calls: list[int] = []
    fake = _FakeNotifier(returns=True)

    def factory():  # type: ignore[no-untyped-def]
        calls.append(1)
        return fake

    rep = _build(tmp_path, factory=factory).notify_audit_issues(
        [_issue("offline", "aa:bb"), _issue("high_temperature", "cc:dd")]
    )
    assert rep.status == NotifyStatus.sent
    assert rep.sent == 2
    assert calls == [1]


@pytest.mark.fast()
@freeze_time("2026-06-14 10:00:00")
def test_notify_failed(tmp_path: Path) -> None:
    """§8 #7: send→False на каждый новый issue → failed."""
    from unifi_manager.services.notify import NotifyStatus

    rep = _build(tmp_path, factory=lambda: _FakeNotifier(returns=False)).notify_audit_issues(
        [_issue("offline", "aa:bb")]
    )
    assert rep.status == NotifyStatus.failed
    assert (rep.sent, rep.failed) == (0, 1)


@pytest.mark.fast()
@freeze_time("2026-06-14 10:00:00")
def test_notify_all_deduped_completed(tmp_path: Path) -> None:
    """§8 #6: всё задедуплено (real AlertHistory) → completed, sent=0."""
    from unifi_manager.services.notify import AlertHistory, NotifyService, NotifyStatus

    pre = AlertHistory(tmp_path / "alerts.json")
    pre.record_alert(hash_key="offline:aa:bb")
    pre.save()
    svc = NotifyService(
        settings=_make_settings(),
        history=AlertHistory(tmp_path / "alerts.json"),
        notifier_factory=lambda: _FakeNotifier(),
    )
    rep = svc.notify_audit_issues([_issue("offline", "aa:bb")])
    assert rep.status == NotifyStatus.completed
    assert (rep.sent, rep.skipped_dedup) == (0, 1)


@pytest.mark.fast()
@freeze_time("2026-06-14 10:00:00")
def test_notify_record_only_after_success(tmp_path: Path) -> None:
    """§8 #9: send False → record_alert НЕ вызван (alert остаётся новым)."""
    from unifi_manager.services.notify import AlertHistory, NotifyService

    hist = AlertHistory(tmp_path / "alerts.json")
    svc = NotifyService(
        settings=_make_settings(),
        history=hist,
        notifier_factory=lambda: _FakeNotifier(returns=False),
    )
    svc.notify_audit_issues([_issue("offline", "aa:bb")])
    assert hist.is_new_alert(hash_key="offline:aa:bb") is True


@pytest.mark.fast()
@freeze_time("2026-06-14 10:00:00")
def test_notify_send_and_test_status(tmp_path: Path) -> None:
    """send/test → sent при успехе, failed при False; без completed."""
    from unifi_manager.services.notify import AlertLevel, NotifyStatus

    svc = _build(tmp_path)
    assert svc.send("hi", level=AlertLevel.warn).status == NotifyStatus.sent
    assert svc.test().status == NotifyStatus.sent
    svc2 = _build(tmp_path, factory=lambda: _FakeNotifier(returns=False))
    assert svc2.send("hi", level=AlertLevel.info).status == NotifyStatus.failed


@pytest.mark.fast()
@freeze_time("2026-06-14 10:00:00")
def test_notify_partial_mixed_results(tmp_path: Path) -> None:
    """Смешанный результат: один успех, один провал → partial."""
    from unifi_manager.services.notify import NotifyStatus

    class MixedNotifier:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []
            self._i = 0

        def send_message(self, text: str, *, hash_key: str) -> bool:
            self.calls.append((text, hash_key))
            self._i += 1
            return self._i == 1  # first succeeds, subsequent fail

    notifier = MixedNotifier()

    def factory() -> MixedNotifier:
        return notifier

    rep = _build(
        tmp_path,
        factory=factory,
    ).notify_audit_issues([_issue("offline", "aa:bb"), _issue("offline", "cc:dd")])

    assert rep.status == NotifyStatus.partial
    assert (rep.sent, rep.failed) == (1, 1)


@pytest.mark.fast()
def test_format_issue_pinned(tmp_path: Path) -> None:
    """Проверка жёстко зафиксированного формата сообщения для audit issue."""
    notifier = _FakeNotifier()

    _build(tmp_path, factory=lambda: notifier).notify_audit_issues([_issue("offline", "aa:bb")])

    assert notifier.calls == [("⚠ critical: aa:bb — offline", "offline:aa:bb")]
