Тебе после клона репо надо:

1. `python -m venv venv`
2. `source ./venv/bin/activate`

   На Windows: `./venv/Scripts/Activate.ps1`
4. `pip install -r "requirements.txt"`
5. Создать .env в папке app и записать в него:
```
# Modbus настройки
PLC_IP=192.168.0.100
PLC_PORT=502

# Zigbee MQTT настройки
ENABLE_ZIGBEE=1
MQTT_BROKER=localhost
MQTT_PORT=1883
MQTT_TOPIC=zigbee2mqtt/0x7cc6b6fffeab1b60

# Режим разработки (1 = mock, 0 = реальный ПЛК)
VENT_MOCK_HARDWARE=0

# Путь для данных
VENT_DATA_DIR=./data

```

5. uvicorn app.main:app —host 0.0.0.0 —port 8080

## Кнопки контроллера и ручное управление

Кнопки OK / ESC / RESET / CONFIRM из сервисного меню фронта приходят как
`controller_button_pressed` / `controller_button_released` и пишутся в coil (1 - нажата, 0 - отпущена).
Адреса задаются в `MODBUS_CONFIG["buttons"]` (`app/modbus_integration.py`), там же
адреса исполнительных устройств в `MODBUS_CONFIG["actuators"]`. Пока адрес `None`, команда отклоняется,
и фронт получает событие `error`.

Защита от залипания: при отключении клиента его кнопки отпускаются, кнопка, которую держат дольше
`BUTTON_MAX_HOLD_SEC` (по умолчанию 30 с, `0` - выключить), отпускается сама, неудачное отпускание повторяется.

Таймер процедуры на фронте работает от WS-сообщения `procedure_state` (`{action, status}`),
которое рассылается после `/api/change-procedure-state` и при подключении клиента.
