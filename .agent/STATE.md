# STATE: ремейк MCP-моста (mcp-agent-bridge)

Оновлено: 2026-11-05 00:10. Задача (slug для тегів): `remake`.

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
- Цей раунд: нова іконка (tools/make_icon.py, варіант deck; є mono і tile),
  іконка в title bar замість сірої крапки, тиша для "context canceled" від
  cloudflared, без ERROR при навмисній зупинці тунелю, get_active_project
  показує шлях до call log, скіли: "Where the work lives" (ПК - основне
  місце, пісочниця - чернетка) + brief: схема тегів, аварійний хендоф без
  інструментів, відновлення через call log.

## Чекає на користувача

- Обрати іконку (deck / mono / tile) і перезапустити панель.
- Відповісти на питання з останнього повідомлення агента (акцент GUI,
  чи додавати brief/v2 як скіли в Notion).

## Наступний крок

Фаза 5: редизайн GUI. Графіт (не чорний), акцент - узгодити (оранжевий лише в
іконці, кнопки - світлі?). Файли: gui/theme.qss, gui/app.py (_dark_palette),
gui/main_window.py, gui/widgets/primitives.py, chrome.py, setup_guide.py.
Перевірка: python tools\screenshot_gui.py, кроп/зменшення PNG перед read_file.
Тег: cp/remake/05-gui; після прийняття - v2.0.

## Для наступного агента

Прочитай цей файл, останній файл у .agent/prompts/, ARCHITECTURE.md,
`git log --oneline -15`, `git tag -n3 -l "cp/remake/*"`, `git status --short`.
