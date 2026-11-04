# STATE: ремейк MCP-моста (mcp-agent-bridge)

Оновлено: 2026-11-04. Фази 1-4 готові й закомічені. Фаза 5 (GUI) не почата.

## Проєкт

Два локальні MCP-сервери (Files System :9500, Terminal :9501), PySide6-панель і
Cloudflare Tunnel. Будь-який MCP-клієнт працює з файлами і терміналом на ПК.
Windows, shell = cmd.exe. Деталі: README.md, ARCHITECTURE.md.

## Жорсткі заборони

- НЕ перезапускати і не зупиняти MCP-сервери, панель і cloudflared.
- НЕ чіпати auth/token у config/settings.json.
- Завжди абсолютні шляхи; у run_command/start_process завжди cwd.
- Серверний код діє лише після перезапуску панелі КОРИСТУВАЧЕМ.
  Перед цим прогнати тести (нижче).

## Зроблено (коміти)

- afbd1dc тести notifier/backups більше не пишуть у справжній settings.json
- b300d32 логи: консоль + logs/bridge.log, старт без консолі, один екземпляр
- bac724e безпека: guard, гальмо перебору токена, /health без шляхів
- ea46831 інструменти: без дубля результату, to_thread, авто-фон run_command,
  wait_process until/tail, CRLF/BOM, read_file для зображень, pack/unpack_files
- 31f598f, 58582c5 скіли: UI-стек не трекається; mcp-coding-agent-v2
- f9be187 іконка, ярлики "MCP Agent Bridge" (pythonw) і "(debug)" (консоль)
- 347494f ізольований gui-тест, tools/screenshot_gui.py -> .mcp-runs/shots
- 2231b3e без брендингу Notion; 2b29673 README/ARCHITECTURE
- Теги: pre-remake, pre-remake-wip, checkpoint/2026-11-04-tools-rework,
  checkpoint/2026-11-04-generic-bridge, pre-gui-redesign (= 2b29673)
- Локально (не в git): skills/design|animation|frontend/,
  skills/mcp-coding-agent-brief/SKILL.md

## Тести (усі зелені на 2b29673)

tests/tools_test.py, jobs_test.py, smoke_test.py (порти 9400/9401),
backups_test.py, test_notifier.py, gui_controls_test.py, health_selftest.py.

## Інциденти (повідомлено користувачу)

- Токен Telegram-бота засвітився в чаті -> відкликати в @BotFather.
- Старий test_notifier.py затер bot_token/chat_id у settings.json. Панель
  тримає правильні значення в пам'яті: перемкнути будь-який параметр у
  панелі перед перезапуском, щоб вона записала їх назад.
- Можливий зайвий журнал .mcp-backups у C:\Users\Dima\VSCodeProjects.

## Наступний крок

1. Користувач перезапускає панель через ярлик "MCP Agent Bridge".
2. Живий тест у клієнті: read_file на PNG, pack_files/unpack_files,
   run_command > 45 с (має піти у фон), list_skills (групи), /health.
3. Фаза 5: редизайн GUI (графіт, не чорний; акцент teal #2DD4BF; єдині
   компоненти). Файли: gui/theme.qss, gui/app.py (_dark_palette),
   gui/main_window.py, gui/widgets/primitives.py, chrome.py, setup_guide.py.
   Перевірка: python tools\screenshot_gui.py + read_file на PNG.
   Окремий коміт і тег checkpoint/<дата>-gui-redesign.

## Для наступного агента

Прочитай цей файл, ARCHITECTURE.md, skills/mcp-coding-agent-v2/SKILL.md,
`git log --oneline -15`, `git status --short`.
