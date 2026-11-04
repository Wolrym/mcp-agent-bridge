# STATE: ремейк MCP-моста (mcp-agent-bridge)

Оновлено: 2026-11-05 01:45. Задача (slug для тегів): `remake`.

## Проєкт

Два локальні MCP-сервери (Files System :9500, Terminal :9501), PySide6-панель і
Cloudflare Tunnel. Будь-який MCP-клієнт працює з файлами і терміналом на ПК.
Windows, shell = cmd.exe. Деталі: README.md, ARCHITECTURE.md.
Промпти користувача дослівно: .agent/prompts/ (не в git).
Скіли для роботи: skills/mcp-coding-agent-brief (локально), дизайн: skills/design/*.

## Жорсткі заборони

- НЕ перезапускати і не зупиняти MCP-сервери, панель і cloudflared.
- НЕ чіпати auth/token у config/settings.json.
- Завжди абсолютні шляхи; у run_command/start_process завжди cwd.
- Серверний код діє лише після перезапуску панелі КОРИСТУВАЧЕМ; перед цим тести.

## Теги (схема з 2026-11-05)

- `cp/<task>/<NN>-<що>` - проміжна стабільна точка; `00-start` = стан до задачі.
- `vX.Y` - реліз, лише коли користувач прийняв результат.
- Перейменовано: pre-remake -> v1.0; pre-remake-wip -> cp/remake/00-start;
  checkpoint/...-tools-rework -> cp/remake/01-tools;
  checkpoint/...-generic-bridge -> cp/remake/02-generic;
  pre-gui-redesign -> cp/remake/03-docs.

## Зроблено

- Фази 1-4 (інструменти, логи, безпека, ребрендинг, скіли v2, ярлики, доки).
- Живий тест після перезапуску (2026-11-04 23:48): 14/14 PASS
  (.mcp-runs/live_probe.py): pack/unpack, read_file PNG, CRLF, settings.json
  захищений, wait_process until, run_command сам іде у фон ~50 с.
- Знахідка: Notion віддає image-результат моделі як base64-текст (~22K
  символів на іконку 256 px), а не як картинку. Записано в скіли.
- Раунд 4 (cp/remake/04-icon-logs): тиша для "context canceled" від
  cloudflared, без ERROR при навмисній зупинці тунелю, get_active_project
  показує шлях до call log, схема тегів, аварійний хендоф.
- Раунд 5 (cp/remake/05-gui):
  - GUI: бокова навігація (Overview/Projects/Tunnel/Security/Notifications/
    Activity, Ctrl+1..6), графітова тема з токенами (gui/widgets/tokens.py,
    @name у theme.qss), лінійні іконки (icons.py), групи-картки в стилі
    settings, світла primary-кнопка, градієнтна рамка з бліком зверху,
    оранжевий лише як акцент (фокус, вибраний пункт, іконка). Setup guide
    теж із sidebar. Тести gui_controls_test проходять (ПК і пісочниця).
  - Іконка: підвісний міст, білий на оранжевій плитці (tile за замовч.).
  - Скіли: brief - плановий/аварійний хендоф + готовий "Resume block"
    з порожнім "My notes:"; "Where the work lives" пом'якшено (уникати
    всієї роботи в пісочниці, чесно сказати, якщо так вийшло). v2 - без
    розділу про пісочницю, загальний.
  - Notion: скіли mcp-coding-agent-brief (авто) і mcp-coding-agent-v2
    (вручну) створено як сторінки-скіли; старий mcp-coding-agent вимкнено
    і заархівовано (відновлюваний). Тексти - з skills/*/SKILL.md; при зміні
    файлів оновлювати і сторінки.

## Чекає на користувача

- Перезапустити панель і подивитись новий GUI/іконку; прийняти -> тег v2.0.
- Вимкнути File backups на сторінці Projects (сам).
- Чи видаляти застарілі gui/main_window_v2.py, gui/widgets/setup_guide_v2.py,
  start_gui_v2.bat (альтернативний GUI попереднього агента, не використовується).

## Наступний крок

Після відгуку про GUI: дрібні правки, потім v2.0. Перевірка GUI:
python tools\screenshot_gui.py (усі сторінки + guide), кроп/зменшення PNG
перед read_file.

## Для наступного агента

Прочитай цей файл, останній файл у .agent/prompts/, ARCHITECTURE.md,
`git log --oneline -15`, `git tag -n3 -l "cp/remake/*"`, `git status --short`.
