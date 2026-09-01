Тебе после клона репо надо:

1. `python -m venv venv`
2. `./venv/bin/activate.sh1` я так понимаю на винде
3. `pip install -r "requirements.txt"`
4. Создать .env в папке app и записать в него:
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
