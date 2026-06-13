## unifi-mgr v0.1.4 — Deploy Hygiene & Least-Privilege

Патч поверх 0.1.3. Закрывает находки внешнего ревью deploy-бандла **перед Phase 5 cron-cutover**: права в артефакте, модель владения `/opt`, честность verify-гейта и runbook'ов, добор strict-валидации. Рантайм-логика приложения не менялась — это слой развёртывания, безопасности и операторской правды.

### Безопасность / развёртывание

- **Права в бандле нормализованы.** `shutil.make_archive` на Windows писал `666/777` в tar/zip — для release-артефакта недопустимо (нельзя полагаться на umask оператора). Теперь tar и zip собираются с явными Unix-модами (директории и `*.sh` — `755`, остальное — `644`, `uid/gid 0`) + **build-gate**: сборка падает, если в tarball просочился хоть один group/world-writable бит.
- **`/opt/unifi-mgr` теперь root-owned (least privilege).** Раньше сервис-юзер владел собственным деревом кода (venv, symlinks) — скомпрометированный cron/процесс мог закрепиться, подменив свой же исполняемый файл. Теперь `install-production.sh` создаёт `/opt/unifi-mgr/{,releases,bin}` как `root:root 755`, а `deploy.sh` собирает release-dir, venv и ставит wheel от root. Сервис-юзер `unifi-mgr` имеет read/exec на код и **запись только** в `/var/lib/unifi-mgr` и `/var/log/unifi-mgr` (`750`). `/etc/unifi-mgr` — `750 root:unifi-mgr` (секреты `640` внутри).
- **`verify-deployment.sh` — настоящий acceptance-gate.** Убран `eval`; каждая рантайм-проверка (чтение `config`/`.env`, запись в `/var/lib`, `/var/log`) выполняется через `sudo -u unifi-mgr`, а не от root — иначе скрипт проходил от root, но не доказывал, что cron-юзер реально может работать. Скрипт требует root (чтобы дропнуться в сервис-юзера).
- **RELEASE-NOTES кладутся в бандл.** `DEPLOY.md` ссылается на них безусловно, поэтому `build-bundle.py` копирует `RELEASE-NOTES-v{version}.md` в бандл и **падает**, если файла нет — битой ссылки больше не будет.

### CLI / валидация

- **`config validate --strict` требует `site_id_uuid` для Integration API.** Раньше один `api_key` проходил strict, а `login test --api integration` потом падал (`IntegrationClient` нужен и `api_key`, и `site_id_uuid`). Теперь integration-креды считаются полными только при наличии обоих; legacy — `username`+`password`.

### Runbooks (Phase 5)

- **Cron-модель переведена на `/etc/cron.d/unifi-mgr`.** Раньше runbook'и ставили задания через root'овый `crontab -e` (исполнение от root) и ссылались на wheel `0.1.0`. Теперь задания живут в root-owned drop-in с юзером `unifi-mgr` в 6-м поле (исполнение от сервис-юзера), `sudo crontab -e` — только для выключения legacy. Все ручные проверки — через `sudo -u unifi-mgr`; expected-output `login test` приведён к `[OK]`-маркерам; версия `0.1.4`.

### Развёртывание

Артефакты: `unifi-mgr-0.1.4-deploy.tar.gz` / `.zip`. Рантайм-поведение приложения идентично 0.1.3 — изменения только в правах артефакта, install/deploy-скриптах, verify-гейте, strict-валидации и runbook'ах. Безопасный кандидат для Phase 5 cron-cutover.

### Лицензия

MIT © 2026 Ilya Sochinskij
