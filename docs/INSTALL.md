# Установка unifi-mgr на production-сервер

Полная установка на **чистый** Linux-сервер (Ubuntu 24.04+/Debian 12+, Python 3.12+).
First-time setup — без миграций с legacy.

## 0. Требования

- Linux с systemd, Python 3.12+, `sudo`.
- Сетевой доступ к UniFi-контроллеру с сервера (обычно порт 11443).
- Артефакт `unifi-mgr`: wheel или deploy-бандл (из GitHub Releases или собранный локально).

## 1. Получить артефакт

Готовый бандл — со страницы релизов (`unifi-mgr-<ver>-deploy.tar.gz`), либо собрать на dev-машине:

```bash
python -m build --wheel        # → dist/unifi_mgr-<ver>-py3-none-any.whl
python scripts/build-bundle.py # → dist/unifi-mgr-<ver>-deploy.tar.gz (wheel + scripts + config)
```

Распакуйте бандл на сервере и работайте из его каталога.

## 2. One-time setup (root)

Создаёт системного пользователя `unifi-mgr` и каталоги по least-privilege модели:

```bash
sudo bash scripts/install-production.sh
# /opt/unifi-mgr            755 root:root        (код — root-owned, runtime только read/exec)
# /etc/unifi-mgr            750 root:unifi-mgr   (конфиг; секреты 640 внутри)
# /var/log/unifi-mgr        750 unifi-mgr        (логи)
# /var/lib/unifi-mgr        750 unifi-mgr        (state: cooldown/throttle/history)
```

Идемпотентно — безопасно перезапускать при апгрейде.

## 3. Конфигурация

```bash
sudo install -m 640 -o root -g unifi-mgr config.yaml.example /etc/unifi-mgr/config.yaml
sudo nano /etc/unifi-mgr/config.yaml   # host, port, site, site_id_uuid, verify_ssl, restart_profiles
sudo install -m 640 -o root -g unifi-mgr .env.example /etc/unifi-mgr/.env
sudo nano /etc/unifi-mgr/.env          # UNIFI_UNIFI__USERNAME / PASSWORD / API_KEY [, TELEGRAM__BOT_TOKEN]
```

- **TLS:** для self-signed контроллера запиньте его сертификат
  (`verify_ssl: /etc/unifi-mgr/controller-ca.pem`), а не ставьте `verify_ssl: false` —
  иначе admin-креды уходят по непроверённому каналу. См. комментарий в `config.yaml.example`.
- `.env` хранит только секреты и никогда не коммитится.

## 4. Deploy

```bash
sudo bash scripts/deploy.sh dist/unifi_mgr-<ver>-py3-none-any.whl
# venv + установка wheel (+ constraints.txt из бандла) + atomic symlink switch
# + проверка версии от сервис-юзера unifi-mgr
```

## 5. Verify

```bash
sudo bash scripts/verify-deployment.sh   # → All checks PASSED
```

Проверки выполняются **от сервис-юзера** (`sudo -u unifi-mgr`), доказывая, что cron-рантайм
сможет читать конфиг и писать state/логи. `login test` требует доступного контроллера.

## 6. Smoke test (от сервис-юзера)

```bash
BIN=/opt/unifi-mgr/bin/unifi-mgr
CFG=/etc/unifi-mgr/config.yaml
sudo -u unifi-mgr "$BIN" --config "$CFG" config validate --strict
sudo -u unifi-mgr "$BIN" --config "$CFG" login test
sudo -u unifi-mgr "$BIN" --config "$CFG" audit status
```

## 7. Scheduling (cron) — опционально

Задания исполняются **от `unifi-mgr`** через root-owned drop-in `/etc/cron.d/unifi-mgr`
(6-е поле строки — юзер). Пример:

```cron
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# критические проблемы каждые 15 мин (+ Telegram-алерт при наличии)
*/15 * * * * unifi-mgr /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml audit critical --telegram --json >> /var/log/unifi-mgr/cron-audit-critical.log 2>&1
# auto-restart проблемных AP каждые 30 мин
*/30 * * * * unifi-mgr /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml restart auto --json >> /var/log/unifi-mgr/cron-restart-auto.log 2>&1
# профильный рестарт — по вашим restart_profiles из config.yaml:
# 0 7 * * * unifi-mgr /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml restart profile <name> --apply --json >> /var/log/unifi-mgr/cron-restart-<name>.log 2>&1
```

Установка: `sudo install -m 644 -o root -g root <файл> /etc/cron.d/unifi-mgr`.
Расписания и набор профилей — специфика вашего деплоя; держите их в своём приватном конфиге.

## Обновление (upgrade)

Повторный `deploy.sh` с новым wheel — atomic symlink switch (старый релиз остаётся для отката):

```bash
sudo bash scripts/deploy.sh dist/unifi_mgr-<new>-py3-none-any.whl
# откат: sudo ln -sfn /opt/unifi-mgr/releases/<previous> /opt/unifi-mgr/current
```

## Логи, state, аварийный стоп

- Логи: `/var/log/unifi-mgr/` (JSON, ротация).
- State: `/var/lib/unifi-mgr/` (cooldown-история рестартов, throttle алертов).
- **Аварийный стоп:** `permissions.cli.restart.execute: false` в `config.yaml` — мгновенно
  переводит все restart-команды в `skipped_permissions` без правки cron.
