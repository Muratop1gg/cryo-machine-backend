# Vent Backend (FastAPI)

Бэкенд для панели управления вент. установкой, реализующий REST/WS API из
README фронтенда.

## Структура

```
app/
  main.py         # FastAPI-приложение, все REST-эндпоинты, WS-эндпоинт /ws
  models.py       # Pydantic-модели по TS-интерфейсам из README фронта
  storage.py      # чтение/запись config.json и settings.json (атомарно)
  hardware.py     # ТОЧКА ИНТЕГРАЦИИ с протоколом контроллера (см. ниже)
  ws_manager.py   # менеджер WS-подключений, broadcast, разбор входящих сообщений
requirements.txt
```

## Запуск

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export VENT_DATA_DIR=/var/lib/vent-backend   # необязательно, по умолчанию этот путь
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

По умолчанию включен `VENT_MOCK_HARDWARE=1` - `hardware.py` отдаёт
рандомные, но валидные данные и просто логирует команды, так что можно
поднять бэкенд и погонять фронт ещё до подключения реального протокола.
Отключается через `export VENT_MOCK_HARDWARE=0`.

## Что нужно доделать (интеграция с контроллером)

Вся логика общения по вашему протоколу с вент. контроллером сознательно
не реализована - в `app/hardware.py` для каждой операции есть функция с
комментарием `# TODO: PROTOCOL`, куда нужно подставить реальный вызов:

- `get_sensors_data()` - опрос текущего состояния для `sensors_data` (дергается раз в 0.2с)
- `send_procedure_action(action)` - `/api/change-procedure-state/`
- `start_self_test(type)` / `stop_self_test()` - `/api/self-test/*`
- `apply_settings(settings)` - `/api/update-settings`
- `request_unlock()` / `check_unlock_code(code)` - `/api/unlock*`
- `send_button_press/release`, `send_machine_control`, `send_steam_speed` - входящие WS-команды от фронта
- `push_event(event_id)` - вызывать из кода протокола, когда контроллер
  сам прислал асинхронное событие (`event` в README). Функция уже
  подключена к WS-рассылке через `set_event_callback` в `main.py`.

## config.json / settings.json

- `GET/POST /api/config` читает и целиком перезаписывает файл `config.json`
  в `VENT_DATA_DIR` (по умолчанию `/var/lib/vent-backend/config.json`).
  Бэкенд не валидирует структуру - что прислали, то и сохраняется,
  что лежит в файле, то и отдаётся.
- `GET/POST /api/settings` и `/api/update-settings` работают со
  структурированными настройками (`settings.json`), см. `models.py`.
  `update-settings` мержит присланные поля в уже сохранённые (partial update).

## Формат WebSocket-сообщений

Все сообщения (в обе стороны) обёрнуты в конверт:

```json
{ "event": "sensors_data", "payload": { ... } }
```

где `event` - одно из имён из README (`sensors_data`, `event`,
`controller_button_pressed`, `controller_button_released`,
`machine_controls`, `steam_speed_control`), а `payload` - соответствующий
объект данных (без обёрточного поля `type`, оно ушло в `event` конверта).

Например, нажатие кнопки от фронта на бэк:

```json
{ "event": "controller_button_pressed", "payload": { "button": "OK" } }
```

`sensors_data` рассылается всем подключенным клиентам раз в 0.2 секунды
фоновой задачей `sensors_broadcast_loop` (запускается при старте приложения).

## Коды ответов

Все успешные ответы возвращают `BasicResponse { status_code: "200", message?: string }`
с HTTP-статусом 200. Ошибки бизнес-логики (отказ контроллера выполнить
команду и т.п.) возвращают HTTP 400 с телом `{"detail": "..."}` (стандартный
формат FastAPI/HTTPException).
