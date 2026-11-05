# STATE: ремейк MCP-моста (mcp-agent-bridge)

Оновлено: 2026-11-05 15:30. Задачі (slug для тегів): `remake` (закрита, v2.0),
`skills` (скіли: глобальні + проєктні).

## Проєкт

Два локальні MCP-сервери (Files System :9500, Terminal :9501), PySide6-панель і
Cloudflare Tunnel. Будь-який MCP-клієнт працює з файлами і терміналом на ПК.
Windows, shell = cmd.exe. Деталі: README.md, ARCHITECTURE.md.
Промпти користувача дослівно: .agent/prompts/ (не в git).
Скіли для роботи: skills/mcp-coding-agent-brief (локально), дизайн: skills/design/*.
Оригінальний скіл: skills/legacy/mcp-coding-agent. Вимкнені скіли: skills/bin/.

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
- Раунд 5 (cp/remake/05-gui): GUI з sidebar, графітова тема з токенами
  (gui/widgets/tokens.py, @name у theme.qss), іконка-міст; скіли brief
  (хендоф + Resume block) і v2; у Notion - сторінки-скіли
  mcp-coding-agent-brief (авто) і -v2 (вручну), старий заархівовано.
  Тексти - з skills/*/SKILL.md; при зміні файлів оновлювати і сторінки.
- Раунд 6: 22060c4 (рядки не блимають окремими вікнами), 85b4881
  (графітові пігулки, теплий glow). Користувач прийняв панель -> тег v2.0.
- Раунд 7 (`skills`): list_skills = глобальні скіли + проєктні
  (.agents/.agent/.claude/.opencode skills) в одному списку, проєктний
  перемагає при збігу імені; з project=... показує AGENTS.md / CLAUDE.md /
  GEMINI.md; skills/bin/ прихована; оригінал -> skills/legacy/;
  core.skills.pack + tools/pack_skill.py + кнопка "Pack as .zip" у guide;
  у скілах розділ "Getting oriented" (спершу AGENTS.md). Notion-сторінки
  скілів оновлено. Чому "двічі": FastMCP віддавав і text, і
  structuredContent - тепер structured_output=False.

## Чекає на користувача

- Перезапустити панель, щоб нові list_skills / pack діяли; новий чат, щоб
  Notion побачив нові описи інструментів (кешує їх на чат).
- Перевірити один .zip через Notion: Library > Skills > Upload skill.
- Пуш на GitHub - коли все доробимо (сказав сам). Перейменування папки - сам.
- Вимкнути File backups на сторінці Projects (сам).
- Чи видаляти локальні (gitignored) gui/main_window_v2.py,
  gui/widgets/setup_guide_v2.py, start_gui_v2.bat.

## Наступний крок

Чекати відгуку. Перевірка GUI: python tools\screenshot_gui.py (усі
сторінки + guide), кроп/зменшення PNG перед read_file.

## Для наступного агента

Прочитай цей файл, останній файл у .agent/prompts/, ARCHITECTURE.md,
`git log --oneline -15`, `git tag -n3 -l "cp/*"`, `git status --short`.
