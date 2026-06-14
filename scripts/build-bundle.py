#!/usr/bin/env python3
"""Собирает self-contained deployment-бандл из чистого committed-состояния (git archive HEAD).

Бандл = все tracked-файлы на HEAD (минус release-only tooling) + pre-built wheel + DEPLOY.md.
Источник — `git archive HEAD`, поэтому в бандл попадает только закоммиченный код
(никаких stray untracked-файлов, __pycache__, .env и т.п.).

Usage:
    .venv/Scripts/python -m build --wheel          # сперва собрать wheel
    .venv/Scripts/python scripts/build-bundle.py    # затем бандл

Результат:
    dist/unifi-mgr-<version>-deploy/        (распакованное дерево)
    dist/unifi-mgr-<version>-deploy.tar.gz
    dist/unifi-mgr-<version>-deploy.zip

Версия читается из src/unifi_manager/__init__.py (__version__).
"""

from __future__ import annotations

import datetime as _dt
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

# Release-only tooling — нужно для публикации релиза, НЕ для развёртывания на сервере.
# Исключаем из deploy-бандла (совпадает с curated-раскладкой 0.1.0).
PRUNE: list[str | Path] = [
    "scripts/forgejo_release.py",
    "scripts/build-bundle.py",
    Path("scripts") / "__pycache__",  # на всякий, если git archive что-то прихватит
]
PRUNE_GLOBS = ["RELEASE-NOTES-*.md"]


def read_version() -> str:
    init = (ROOT / "src" / "unifi_manager" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    if not m:
        sys.exit("ERROR: cannot find __version__ in src/unifi_manager/__init__.py")
    return m.group(1)


DEPLOY_MD = """# unifi-mgr — Deployment Bundle

**Version:** {version} | **License:** MIT | **Собрано:** {date}

Deployment bundle для развёртывания `unifi-mgr` на production Linux server.
Требует доступ к PyPI для установки зависимостей; версии пиннятся через `constraints.txt`.

> **{version} — production release.** Полная история изменений: `RELEASE-NOTES-v{version}.md`
> (в этом бандле). Не разворачивай `0.1.0` — там blast-radius баги (FileLock не подключён,
> неограниченный restart-cap, non-atomic history, verify_ssl insecure, path-traversal),
> закрытые в 0.1.1+.

---

## Содержимое

| Путь | Что |
|---|---|
| `unifi_mgr-{version}-py3-none-any.whl` | Pre-built пакет (готов к install, не нужно собирать) |
| `constraints.txt` | Пины версий runtime-зависимостей (deploy.sh подхватывает автоматически) |
| `src/`, `tests/`, `pyproject.toml` | Полный исходник (можно пересобрать wheel) |
| `scripts/install-production.sh` | One-time setup (user/group/dirs) |
| `scripts/deploy.sh` | Release rotation через symlinks |
| `scripts/verify-deployment.sh` | Post-install smoke checks |
| `scripts/observe.sh` | Daily observation helper (Phase 5) |
| `config.yaml.example` | Шаблон публичного конфига |
| `.env.example` | Шаблон секретов |
| `docs/INSTALL.md` | Установка на чистый сервер (step-by-step) |
| `docs/ARCHITECTURE.md` | Архитектура (current) |
| `docs/ROADMAP.md` | Дорожная карта (сделано / в работе / отложено) |
| `docs/specs/` | Design-спеки (NotifyService, Report module) |
| `README.md`, `LICENSE` | Описание + лицензия |

---

## Требования

- Ubuntu 24.04 LTS (или совместимый Linux)
- Python 3.12+
- sudo доступ
- UniFi controller доступен с сервера

---

## Quick start

```bash
# 0. Распаковать bundle на сервере
tar xzf unifi-mgr-{version}-deploy.tar.gz
cd unifi-mgr-{version}-deploy

# 1. One-time setup (создаёт user/group unifi-mgr + директории)
sudo bash scripts/install-production.sh

# 2. Конфигурация
sudo install -m 640 -o root -g unifi-mgr config.yaml.example /etc/unifi-mgr/config.yaml
sudo nano /etc/unifi-mgr/config.yaml      # host, port, site, site_id_uuid, verify_ssl
sudo install -m 640 -o root -g unifi-mgr .env.example /etc/unifi-mgr/.env
sudo nano /etc/unifi-mgr/.env             # UNIFI_UNIFI__USERNAME/PASSWORD/API_KEY

# 3. Deploy wheel (создаёт /opt/unifi-mgr/, переключает symlink)
sudo bash scripts/deploy.sh unifi_mgr-{version}-py3-none-any.whl

# 4. Verify (runs as the unifi-mgr service user — proves cron runtime)
sudo bash scripts/verify-deployment.sh        # → All checks PASSED

# 5. Smoke test (service user; no `cd` needed — .env resolved from /etc/unifi-mgr)
sudo -u unifi-mgr /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml config validate --strict
sudo -u unifi-mgr /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml login test
sudo -u unifi-mgr /opt/unifi-mgr/bin/unifi-mgr --config /etc/unifi-mgr/config.yaml audit status
```

## Scheduling (cron)

Опционально — задания от сервис-юзера через `/etc/cron.d`. Пример и пошаговая
установка с нуля: **`docs/INSTALL.md`** (раздел «Scheduling»).

---

## Альтернатива: пересборка wheel из исходника

Если нужна свежая сборка (или другая версия Python):

```bash
python3.12 -m venv .venv-build
.venv-build/bin/pip install build
.venv-build/bin/python -m build --wheel
# → dist/unifi_mgr-{version}-py3-none-any.whl
```

---

## Важные замечания

- **Telegram отключён по умолчанию** (`telegram.enabled: false` в config) — заблокирован в РФ. Код рабочий, включить если `api.telegram.org` доступен (VPN/proxy). Matrix-канал — в планах.
- **Permissions kill-switch:** `permissions.cli.restart.execute: false` в config.yaml — экстренная остановка всех restart-команд без правки cron.
- **FileLock:** `restart auto/profile/device` исполняются под `FileLock` (cron `*/30` не запустит параллельные инстансы; занятый lock → статус `skipped_locked`).
- **Fail-closed history:** битый state-файл **блокирует** рестарты (не сбрасывает cooldown). Файл сохраняется для разбора, не перезаписывается.
- **Rollback:** legacy скрипты на сервере остаются работоспособными до Phase 6 cleanup. Откат cron — одна строка в crontab.
- **Секреты:** никогда не коммитить `/etc/unifi-mgr/.env`. Bundle содержит только `.env.example` с placeholders.
- **Runtime user:** сервис рассчитан на запуск от `unifi-mgr` (least privilege). `config.yaml` и `.env` — `640 root:unifi-mgr`. Cron-задачи Phase 5 запускать от `unifi-mgr`, НЕ от root.
- **`.env` resolution:** ищется по цепочке `--env-file` → `UNIFI_ENV_FILE` → рядом с `config.yaml` → `/etc/unifi-mgr/.env`. `cd` больше не нужен.
- **`export devices`:** по умолчанию выводит только безопасные колонки. Сырой дамп (с секретами) — явный `--raw` с предупреждением.

---

## Проверка integrity bundle

```bash
# Версия из wheel
python3 -c "import zipfile; z=zipfile.ZipFile('unifi_mgr-{version}-py3-none-any.whl'); print([n for n in z.namelist() if 'METADATA' in n])"

# Tests (если развернули source)
pip install -e ".[dev]" && pytest    # full suite, coverage 93% (gate 90%)
```
"""


def main() -> None:
    version = read_version()
    wheel = DIST / f"unifi_mgr-{version}-py3-none-any.whl"
    if not wheel.is_file():
        sys.exit(
            f"ERROR: wheel not found: {wheel}\nRun first:  .venv/Scripts/python -m build --wheel"
        )

    bundle_name = f"unifi-mgr-{version}-deploy"
    bundle_dir = DIST / bundle_name
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True)

    # 1. Чистый snapshot tracked-файлов на HEAD через git archive.
    print(f"==> git archive HEAD -> {bundle_dir}")
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
        tmp_tar = Path(tmp.name)
    try:
        subprocess.run(
            ["git", "archive", "--format=tar", "-o", str(tmp_tar), "HEAD"],
            cwd=ROOT,
            check=True,
        )
        with tarfile.open(tmp_tar) as tf:
            tf.extractall(bundle_dir)  # - trusted source (own repo HEAD)
    finally:
        tmp_tar.unlink(missing_ok=True)

    # 2. Убрать release-only tooling.
    for rel in PRUNE:
        target = bundle_dir / rel
        if target.is_dir():
            shutil.rmtree(target)
            print(f"    pruned dir  {rel}")
        elif target.is_file():
            target.unlink()
            print(f"    pruned file {rel}")
    for pattern in PRUNE_GLOBS:
        for hit in bundle_dir.glob(pattern):
            hit.unlink()
            print(f"    pruned glob {hit.relative_to(bundle_dir)}")

    # 3. Положить pre-built wheel.
    shutil.copy2(wheel, bundle_dir / wheel.name)
    print(f"    + {wheel.name}")

    # 3b. Release notes текущей версии. DEPLOY.md ссылается на них безусловно,
    # поэтому отсутствие файла = битый бандл → fail-fast, а не молчаливый skip.
    notes = ROOT / f"RELEASE-NOTES-v{version}.md"
    if not notes.is_file():
        sys.exit(f"ERROR: release notes not found: {notes.name} (DEPLOY.md references it)")
    shutil.copy2(notes, bundle_dir / notes.name)
    print(f"    + {notes.name}")

    # 4. Сгенерировать DEPLOY.md.
    today = _dt.date.today().isoformat()
    # newline="\n": на Windows write_text по умолчанию пишет \r\n (text mode);
    # бандл должен быть LF-clean (.gitattributes-policy + Linux-таргет).
    (bundle_dir / "DEPLOY.md").write_text(
        DEPLOY_MD.format(version=version, date=today), encoding="utf-8", newline="\n"
    )
    print("    + DEPLOY.md")

    # 5. Архивы с НОРМАЛИЗОВАННЫМИ Unix-правами. shutil.make_archive на Windows
    # ставит 666/777 — для release-артефакта недопустимо. Моды задаём явно:
    # dirs 755, *.sh 755, остальное 644, uid/gid 0.
    print("==> creating archives (normalized perms)")

    def _norm(ti: tarfile.TarInfo) -> tarfile.TarInfo:
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = ""
        if ti.isdir() or ti.name.endswith(".sh"):
            ti.mode = 0o755
        else:
            ti.mode = 0o644
        return ti

    tgz = DIST / f"{bundle_name}.tar.gz"
    with tarfile.open(tgz, "w:gz") as tf:
        tf.add(bundle_dir, arcname=bundle_name, filter=_norm)
    print(f"    {tgz.name}  ({tgz.stat().st_size:,} bytes)")

    zp = DIST / f"{bundle_name}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_dir():
                continue
            arc = f"{bundle_name}/{path.relative_to(bundle_dir).as_posix()}"
            zi = zipfile.ZipInfo(
                arc, _dt.datetime.fromtimestamp(path.stat().st_mtime).timetuple()[:6]
            )
            zi.external_attr = ((0o755 if path.suffix == ".sh" else 0o644) & 0xFFFF) << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, path.read_bytes())
    print(f"    {zp.name}  ({zp.stat().st_size:,} bytes)")

    # 6. Build-gate: ни одного group/world-writable бита в tar.
    with tarfile.open(tgz) as tf:
        bad = [m.name for m in tf.getmembers() if m.mode & 0o022]
    if bad:
        sys.exit(f"ERROR: group/world-writable entries in {tgz.name}: {bad[:5]}")
    print(f"    perms gate OK (no group/world-writable in {tgz.name})")

    # 7. Build-gate: ни одного CRLF в текстовых файлах. Генерённый DEPLOY.md на
    # Windows мог получить \r\n; деплой-скрипты с CRLF ломаются на Linux (#!/bin/bash\r).
    text_ext = (".sh", ".md", ".py", ".yaml", ".yml", ".toml", ".txt", ".cfg")
    crlf = []
    with tarfile.open(tgz) as tf:
        for m in tf.getmembers():
            if not (m.isfile() and m.name.endswith(text_ext)):
                continue
            fh = tf.extractfile(m)
            if fh is not None and b"\r" in fh.read():
                crlf.append(m.name)
    if crlf:
        sys.exit(f"ERROR: CRLF in text files in {tgz.name}: {crlf[:5]}")
    print(f"    CRLF gate OK (text files are LF in {tgz.name})")

    print(f"==> Done. version={version}")


if __name__ == "__main__":
    main()
