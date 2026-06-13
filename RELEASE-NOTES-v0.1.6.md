## unifi-mgr v0.1.6 — restart-profile offline-AP fix + Telegram HTML + install self-heal

Патч поверх 0.1.5. Главное — устойчивость `restart profile` к оффлайн-точкам (всплыло на проде при Phase 5 dry-run); плюс симметричный добор HTML-escaping и upgrade-safety в установщике. Несёт всё из 0.1.5 (CLI contract hardening) и 0.1.4 (deploy hygiene).

### Рестарт / устойчивость

- **`restart profile` больше не падает на оффлайн-точке (регресс от legacy).** Контроллер отдаёт `404` на `GET /stat/event?mac=` для offline/unknown AP. 0.1.5 это не обрабатывал, и `restart profile` крашился (`UnifiAPIError`) ровно тогда, когда ресторанная точка оффлайн — то есть когда рестарт и нужен. `list_events_raw` теперь трактует `404` как «событий нет» (как делал legacy-скрипт через try/except); не-404 ошибки по-прежнему пробрасываются. **Разблокирует миграцию Stage 4 в cron.**

### Надёжность алертов

- **Telegram HTML escaping (P3).** В 0.1.5 `send_message` экранировал только `MarkdownV2`. Но `parse_mode=HTML` — валидное значение конфига, и под ним сырые `<`, `>`, `&` в имени устройства парсятся как теги или дают Telegram 400. Теперь HTML-ветка экранируется через `html.escape` (симметрично MarkdownV2).

### Установка / апгрейд

- **`install-production.sh` чинит владельца runtime-каталогов (upgrade-safety).** Скрипт создавал `/var/log/unifi-mgr` и `/var/lib/unifi-mgr` от сервис-юзера, но не нормализовал уже лежащее внутри. Root-owned файл (напр. `unifi-mgr.log`, оставленный smoke-тестом от root) блокировал запись сервис-юзеру. Добавлен идемпотентный `chown -R unifi-mgr:unifi-mgr /var/log/unifi-mgr /var/lib/unifi-mgr` — повторный запуск/апгрейд сам лечит владельца. (Всплыло на проде при апгрейде 0.1.1 → 0.1.5.)

### Развёртывание

Артефакты: `unifi-mgr-0.1.6-deploy.tar.gz` / `.zip`. 339 тестов, coverage ≥90%, ruff + mypy чисто, бандл LF-clean с perms/CRLF/notes build-gate.

### Лицензия

MIT © 2026 Ilya Sochinskij
