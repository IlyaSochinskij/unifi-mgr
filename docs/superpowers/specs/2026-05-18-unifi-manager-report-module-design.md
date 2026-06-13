# UniFi Manager — Report Module (доп. модуль)

**Дата:** 2026-05-18
**Статус:** Draft
**Связь с основным дизайном:** дополняет `2026-05-16-unifi-manager-refactor-design.md` как parallel track. Не блокирует Phase 3-6. Можно делать после Phase 4 (CLI готов) или после Phase 6 (стабилизация).
**Целевая длительность:** 2-3 дня

---

## Контекст

В основном дизайн-доке HTML report был отмечен как defer (D-ID не присвоен явно, но в комментариях review: "если менеджмент попросит — добавим как format в ExportService за 2-3 часа"). После просмотра `FryguyPA/Unifi_Network_Health_Report` (Apache 2.0, 12 commits, 1 автор) стало понятно, что **HTML report — это не "ещё один формат экспорта", а отдельный аналитический слой**. У FryguyPA это видно по структуре: `report/generator.py` отдельно от `unifi/client.py`, recommendations engine на входе шаблона, темы, collapsible, snapshots для diff.

Поэтому делаем не флаг в `ExportService`, а **отдельный `ReportService`**.

### Что берём из FryguyPA (идеи, не код)

- **Self-contained Jinja2 template без CDN** — открывается через год на любом ноутбуке без интернета
- **Inline SVG charts** вместо Chart.js — zero JS framework dependency
- **4 темы через CSS variables + localStorage** — Light, Dark, Slate&Amber, Deep Navy. Lightweight JS theme switcher.
- **Collapsible sections с persistence в localStorage**
- **Recommendations первой секцией** — auto-generated, prioritized action items
- **JSON snapshot рядом с HTML** для historical diff в будущем
- **Threshold-based flagging** с порогами в config

### Что НЕ берём

- Их код напрямую (Apache 2.0 позволяет, но проще написать своё чем адаптировать чужое — кодовая база 12 коммитов, не стоит coupling)
- Их таблицу supported controllers — наш клиент уже работает с self-hosted UniFi OS через `/proxy/network/` префикс из Phase 1
- Веб-сервер режим, авторизацию, multi-user — это CLI tool, генерирует файл, открывает в браузере

### Разница ExportService vs ReportService

| Слой | Назначение | Stateful? | Аналитика? |
|---|---|---|---|
| `ExportService` | сырые данные → CSV/JSON/XLSX | нет | нет |
| `ReportService` | данные → аналитика → recommendations → HTML/JSON | да (snapshots) | да (thresholds, дельты) |

Объединять в один сервис — означает захламить `ExportService` логикой аналитики и thresholds, которая ему не нужна для CSV/JSON экспорта.

---

## Цели / не-цели

**Цели:**
1. Команда `unifi-mgr report generate` производит standalone HTML отчёт с health overview, recommendations, секциями по WAN/AP/Switch/VLAN/firmware/etc.
2. JSON snapshot рядом с HTML для возможности diff между прогонами в будущем
3. Recommendations engine агрегирует findings из существующих сервисов (`AuditService`, `RestartService`) и thresholds
4. Production-specific секции: restart history по AP, активные профили рестарта, AlertHistory статистика, последние Telegram-уведомления
5. Self-contained HTML — никаких внешних зависимостей в браузере

**Не-цели:**
1. Веб-сервер режим / real-time dashboard — это CLI tool, файлы на диске
2. Historical diff в первой версии — только snapshots для будущего сравнения. Diff — отдельная Phase 4R.1.
3. Email / Telegram рассылка отчёта — рендеринг и доставка раздельно. Доставка не входит в этот модуль.
4. Multi-site comparison — один отчёт = один site
5. PDF export — HTML + браузер "Print to PDF" покрывает кейс

---

## Положение в roadmap

**Phase 4R** (Report), parallel track. Не блокирует и не блокируется фазами основного рефакторинга.

- **Минимальная зависимость:** Phase 4 (CLI скелет готов, можно добавить подкоманду `report`)
- **Опциональная зависимость:** Phase 7 (если `audit_baseline.json` появится — recommendations engine может использовать дельты). Но первая версия Phase 4R работает БЕЗ Phase 7.
- **Параллельность с Phase 4M (MCP):** независимы. Если Phase 4M реализован — можно добавить MCP tool `generate_report` который возвращает path к свежесгенерированному HTML. Но это не входит в Phase 4R.

---

## Архитектура

```
src/unifi_manager/
├── services/
│   ├── report.py                 # НОВОЕ: ReportService
│   ├── recommendations.py        # НОВОЕ: RecommendationEngine
│   └── ...                       # существующие
├── reporting/                    # НОВЫЙ слой
│   ├── __init__.py
│   ├── templates/
│   │   ├── report.html.j2        # главный Jinja2 template (self-contained)
│   │   ├── _section_wan.html.j2
│   │   ├── _section_aps.html.j2
│   │   ├── _section_switches.html.j2
│   │   ├── _section_restart_history.html.j2     # production-specific
│   │   ├── _section_alert_history.html.j2       # production-specific
│   │   └── _section_recommendations.html.j2
│   ├── charts.py                 # генератор inline SVG charts
│   ├── themes.css                # CSS variables для 4 тем
│   └── snapshot.py               # JSON snapshot serializer
└── cli/
    └── report.py                 # НОВЫЙ Typer subcommand
```

### Слои

```
cli/report.py
     ↓
services/report.py (ReportService)
     ├──→ services/audit.py (existing — getDevices/getEvents)
     ├──→ services/restart.py (existing — getHistory)
     ├──→ services/notify.py (existing — getAlertHistory)
     ├──→ services/recommendations.py (new)
     └──→ reporting/{charts, snapshot, templates}
```

**Принципы:**
- `ReportService` ничего не знает про HTTP, только агрегирует данные из других сервисов
- `RecommendationEngine` — чистая функция: `(audit_data, thresholds, history) → list[Recommendation]`. Тестируется без I/O.
- `reporting/` — слой рендеринга. Не зависит от `clients/`, использует только domain-объекты.

---

## Recommendations engine

Самая интересная часть и единственная requiring design, остальное boilerplate.

### Модель

```python
class Recommendation(BaseModel):
    severity: Literal["critical", "warning", "info"]
    category: Literal["ap_health", "switch", "firmware", "restart_pattern",
                      "alert_noise", "sysid_gap", "poe_budget", "wifi_config"]
    title: str                     # короткий заголовок для UI
    description: str               # развёрнутое объяснение
    affected_devices: list[str]    # список MAC или names
    suggested_action: str | None   # что сделать (CLI команда, изменение config)
    source_data: dict              # сырые метрики для debug, опц.
```

### Правила (первая версия)

| Категория | Правило | Severity |
|---|---|---|
| `ap_health` | TX retry % > `thresholds.ap_retry_pct` | warning |
| `ap_health` | AP перезагружался > N раз за 7 дней (без cron-рестарта профиля) | warning |
| `ap_health` | AP оффлайн > `offline_threshold_min`, но не в exclude_patterns | critical |
| `switch` | port_error_count > `thresholds.switch_error_rate` | warning |
| `switch` | PoE used > `critical_poe_percent` от total | warning |
| `firmware` | available_upgrade=True для устройств | info |
| `restart_pattern` | один AP рестартился > 3 раз за 24 часа через `restart auto` | critical |
| `restart_pattern` | профиль `restaurant` сработал, но cooldown скипнул > 5 событий | warning |
| `alert_noise` | rate-limit Telegram сработал > 10 раз за сутки на один `(mac, error_type)` | info (threshold слишком чувствительный) |
| `sysid_gap` | UniFi вернул model code не в `SYSID_MAP` | info (надо обновить map) |
| `wifi_config` | SSID без WPA2/WPA3, не guest | warning |
| `wifi_config` | дублированные SSID на разных диапазонах с разной security | warning |

**Приоритизация:** sort по `(severity, len(affected_devices))` desc. Critical всегда сверху, дальше по охвату.

**Edge case PoE (фикс ZeroDivisionError из аудита):**
```python
def poe_usage_percent(used: int, total: int) -> float | None:
    if total <= 0:
        return None  # не флагуем, не показываем bar
    return (used / total) * 100
```

В шаблоне: `{% if poe_pct is not none %}<bar/>{% else %}<span class="poe-unknown">PoE budget data unavailable</span>{% endif %}`.

---

## CLI поверхность

```
unifi-mgr report
├── generate  [--output html|json|both] [--theme light|dark|slate|navy]
│             [--open] [--out-dir /var/lib/unifi-mgr/reports]
└── snapshots [--list] [--keep N]    # утилита очистки старых snapshots
```

Дефолты:
- `--output both` (HTML + JSON)
- `--theme light` (override через `?theme=...` в URL templates'е тоже работает)
- `--out-dir` из `settings.paths.reports_dir`
- `--open` запускает `xdg-open` / системный handler (опционально)

Имена файлов:
```
reports/
  unifi_report_2026-05-18_140523.html
  json/
    unifi_snapshot_2026-05-18_140523.json
```

Snapshot ретеншн: по умолчанию keep last 30 snapshots, очищаются автоматически при `generate` (если `--keep` указан в config). Без агрессивной чистки HTML — они мелкие.

---

## Configuration

Дополнения к `Settings` (`settings.py`):

```python
class ReportSettings(BaseModel):
    """Phase 4R: HTML report module."""
    enabled: bool = True
    out_dir: Path = Path("/var/lib/unifi-mgr/reports")
    snapshot_keep_count: int = 30
    default_theme: Literal["light", "dark", "slate", "navy"] = "light"
    timezone: str = "Europe/Moscow"   # для timestamps в шаблоне
    site_display_name: str = "Production Network"   # отображается в заголовке отчёта

class Settings(BaseSettings):
    # ... existing
    report: ReportSettings = ReportSettings()
```

Никаких новых secrets — модуль использует существующих клиентов через `AuditService`.

---

## Templates & themes

Один Jinja2 template `report.html.j2` с включениями `{% include "_section_*.html.j2" %}`.

**Принципы:**
- Inline CSS в `<style>`, не внешние файлы
- Inline SVG для charts, не Chart.js
- Vanilla JS для:
  - Theme switcher (3 строки: `document.documentElement.setAttribute('data-theme', value)`)
  - Collapsible sections (5 строк через event delegation)
  - LocalStorage persistence для theme и collapsed state
- Никакого framework — vanilla JS не превышает 30 строк суммарно

**Темы через CSS variables:**
```css
[data-theme="light"]  { --bg: #fff; --fg: #1a1a1a; --accent: #0066cc; }
[data-theme="dark"]   { --bg: #0d1117; --fg: #e6edf3; --accent: #58a6ff; }
[data-theme="slate"]  { --bg: #2a2d3a; --fg: #d4af37; --accent: #d4af37; }
[data-theme="navy"]   { --bg: #001a33; --fg: #b8d4f0; --accent: #00aaff; }
```

Все компоненты используют `var(--bg)`, `var(--fg)`, `var(--accent)` — четыре темы покрываются без дублирования стилей.

**Recommendations rendering:**
- Critical: красная плашка сверху, expanded by default
- Warning: жёлтая плашка, expanded by default
- Info: серая плашка, collapsed by default

---

## Snapshot format

JSON snapshot — компактный slice состояния для будущего diff:

```json
{
  "schema_version": 1,
  "generated_at": "2026-05-18T14:05:23+03:00",
  "site": "site-1",
  "site_display_name": "Production Network",
  "summary": {
    "total_devices": 271,
    "online_aps": 268,
    "online_switches": 14,
    "critical_count": 2,
    "warning_count": 7
  },
  "devices": [
    {
      "mac": "aa:bb:cc:dd:ee:ff",
      "name": "Restoran 1",
      "type": "ap",
      "model": "UAP-AC-Pro",
      "state": "online",
      "uptime_seconds": 1234567,
      "client_count": 12,
      "tx_retry_pct": 2.3,
      "last_seen": "2026-05-18T14:05:00+03:00"
    }
  ],
  "switches": [
    {
      "mac": "...",
      "name": "Switch-Lobby",
      "poe": {"used_w": 65, "total_w": 150, "percent": 43.3},
      "ports": [
        {"port": 1, "error_count": 0, "speed_mbps": 1000, "is_up": true}
      ]
    }
  ],
  "recommendations": [
    {"severity": "critical", "category": "ap_health", "title": "...", "affected": ["aa:bb:..."]}
  ]
}
```

**Зачем schema_version:** будущая Phase 4R.1 (diff между snapshots) может потребовать миграции формата. С версией легче.

**Зачем компактный slice, а не сырой dump UniFi API:** диффать сырой UniFi response невозможно — там меняется куча non-significant полей (uptime в секундах, RSSI, last_seen). Снимок фиксирует только то что важно для health analysis.

---

## Test plan

Юниты в `tests/unit/test_services/`:

- `test_report_service.py` — happy path, integration с мок-AuditService
- `test_recommendations.py` — каждое правило отдельным тестом с fixture данными
- `test_recommendations_edge_cases.py` — пустой PoE, missing thresholds, empty device list
- `test_snapshot_serializer.py` — schema_version validation, JSON round-trip
- `test_charts.py` — SVG валидность через `xml.etree`, base cases (пустые данные, single point, 24h range)

Юниты в `tests/unit/test_reporting/`:

- `test_template_rendering.py` — Jinja2 render не падает на минимальном fixture, optional sections
- `test_theme_isolation.py` — все 4 темы парсятся как валидный CSS

Coverage target: 85%+ для `services/report.py` и `services/recommendations.py`. Шаблоны не покрываются (нет смысла мерить).

**Без integration тестов** против реального UniFi — фикстуры с anonymized JSON dumps из существующих `tests/fixtures/`.

---

## Связь с другими частями системы

| Связь с | Как |
|---|---|
| `AuditService` (Phase 2) | ReportService дёргает `audit_full()` для получения данных. Никаких изменений в AuditService. |
| `RestartService` (Phase 3) | ReportService дёргает `get_history(window=7d)` для restart_pattern recommendations. Никаких изменений. |
| `NotifyService` (Phase 2) | ReportService дёргает `get_alert_stats(window=24h)` для alert_noise recommendations. Может потребоваться добавить метод `get_alert_stats()` если его нет. |
| `audit_baseline.json` (Phase 7) | Если Phase 7 реализован — recommendations engine получает доступ к деривативу port errors. Если нет — соответствующие правила просто отключены. Feature detection через `os.path.exists()`. |
| MCP server (Phase 4M) | Можно добавить tool `generate_report() → path` если 4M реализован. Не входит в Phase 4R. |
| `permissions` settings | `permissions.cli.report.generate: true|false` — kill-switch для cron-генерации. Дефолт `true`. (D30 refinement: `cli` namespace.) |

---

## Decision log (компактный)

| # | Решение | Обоснование |
|---|---|---|
| R1 | Отдельный `ReportService`, не флаг в `ExportService` | Аналитика и thresholds не нужны для CSV/JSON экспорта. Объединение усложнило бы Export. |
| R2 | Jinja2 templates, не string templating / f-strings | Шаблон ~500 строк HTML, без template engine это будет мука. Jinja2 уже в зависимостях (Flask/FastAPI имеют его транзитивно). |
| R3 | Inline SVG, не Chart.js / matplotlib | Self-contained требование. SVG нативно поддерживается браузерами. matplotlib тащит numpy — overkill для 24 точек. |
| R4 | 4 темы через CSS variables, не отдельные CSS файлы | DRY. Одна правка цветовой схемы → меняется во всех темах. |
| R5 | JSON snapshot в первой версии без diff engine | Diff — отдельная задача (Phase 4R.1). Сейчас просто пишем формат на будущее. |
| R6 | Recommendations rules hardcoded в `recommendations.py`, не в config | Правил мало (~12), все в одном месте легче ревьюить. YAML-конфиг правил — overengineering для 12 шт. |
| R7 | Phase 4R параллельный track, не блокирует основной refactor | HTML report не критичен для прода. Можно делать когда настроение. |

---

## Что НЕ входит в этот спек (defer)

- **Diff engine между snapshots** — Phase 4R.1, отдельный документ когда понадобится
- **Email / Telegram рассылка отчёта** — отдельный модуль `delivery/`, использует ReportService на чтение
- **PDF export** — браузер "Print to PDF" покрывает
- **Multi-site comparison** — пока что один отчёт = один site
- **Real-time веб-режим** — это CLI tool, не сервер
- **Сравнение с прошлым месяцем / трендовые графики** — требует diff engine (4R.1) + accumulated snapshots

---

## Следующий шаг

После одобрения этого диздока:
1. Если Phase 4 в основном дизайне завершён — можно начинать Phase 4R сразу
2. Если Phase 4 в работе — закладываем как backlog item, реализуем после
3. Detailed implementation plan по подзадачам — отдельный документ при старте работы (по аналогии с `phase-3-restart-plan.md`)
