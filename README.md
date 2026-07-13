#  Cryo Chamber Backend

Бэкенд-сервер для управления криокамерой. Обеспечивает связь между фронтендом, ПЛК (ModbusTCP), Zigbee-устройствами (USB-модем CC2652P) и RS485-датчиком кислорода.

---

## 🏗️ Архитектура

```
┌──────────────┐     HTTP/WS      ┌──────────────┐   ModbusTCP    ┌──────────┐
│   Фронтенд   │ ◄──────────────► │   Backend    │ ◄────────────► │   ПЛК    │
│  (React/Vue) │   REST + WS      │  (FastAPI)   │                │          │
└──────────────┘                  └──────┬───────┘                └──────────┘
                                         │
                        ┌────────────────┼────────────────
                        ▼                ▼                ▼
                  ┌──────────┐    ┌──────────┐    ┌──────────┐
                  │ Zigbee   │    │  RS485   │    │  config  │
                  │  CC2652P │    │  O2 дат. │    │  .json   │
                  └──────────    └──────────┘    └──────────┘
```

**Ключевая логика:** фронтенд шлёт команду → бэкенд записывает в ПЛК → ждёт `event_id` (подтверждение "roger") → возвращает результат.

---

## 📁 Структура проекта

```
cryo-backend/
├── main.py                  # FastAPI приложение, эндпоинты, lifespan
├── models.py                # Pydantic-модели (валидация JSON)
├── config.json              # Конфигурация установки
├── config_manager.py        # Загрузка и валидация config.json
── modbus_client.py         # Клиент ModbusTCP (опрос ПЛК)
├── command_tracker.py       # Ожидание event_id от ПЛК
├── procedure_logger.py      # Лог последней процедуры
├── actuator_controller.py   # Транслятор команд в регистры ПЛК
├── zigbee_client.py         # Клиент Zigbee (CC2652P, ZNP)
── oxygen_sensor.py         # Клиент RS485 (датчик O₂)
└── logs/
    ├── last_procedure.log   # Текущий лог процедуры
    ── archive/             # Архив завершённых процедур
```

---

## ️ Установка и запуск

### Зависимости
```bash
pip install fastapi uvicorn pydantic pymodbus pyserial-asyncio
```

### Запуск
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Сервер стартует на `http://localhost:8000`. Swagger UI доступен по адресу `/docs`.

---

##  Конфигурация (`config.json`)

Хранит все параметры установки. Основные секции:

| Секция | Назначение |
|--------|------------|
| `network` | Wi-Fi (SSID, пароль) |
| `hardware.nitrogen_mass_sensor` | Датчик массы азота (Zigbee) |
| `hardware.steam_generator` | Парогенератор (VFD/контактор, адаптивное управление) |
| `hardware.oxygen_sensor` | Датчик O₂ (PLC или RS485 с параметрами COM-порта) |
| `hardware.patient_hoist` | Лебёдка пациента (VFD, скорость) |
| `hardware.led_strip` | Светодиодная лента (argb/rgb) |
| `hardware.pulse_sensor` | Датчик пульса (Bluetooth) |
| `hardware.speaker` | Динамик |
| `hardware.zigbee_remote` | Пульт + биндинг кнопок (Zigbee + клавиатурные дублёры) |
| `defaults` | Уставки по умолчанию (процедура, прохолаживание, сушка) |
| `modbus_plc` | Параметры подключения к ПЛК |
| `zigbee_modem` | Параметры Zigbee-модема (порт, baudrate, протокол) |

---

## 🌐 API Reference

### GET-эндпоинты (чтение состояния)

#### `GET /api/config`
Возвращает полную конфигурацию установки из `config.json`.

**Ответ:**
```json
{
  "network": { "wifi_ssid": "...", "wifi_password": "..." },
  "hardware": { ... },
  "defaults": { ... },
  "modbus_plc": { ... },
  "zigbee_modem": { ... }
}
```

---

#### `GET /api/system_info`
Возвращает **всё** состояние системы в одном запросе: системную информацию, телеметрию, концевики, статусы оборудования.

**Ответ:**
```json
{
  "hostname": "cryo-pc",
  "os": "Linux 6.1.0",
  "python_version": "3.11.5",
  "app_version": "1.0.0",
  "uptime_seconds": 3600.5,
  "started_at": "2026-07-13T10:00:00",
  "modbus_connected": true,
  "zigbee_connected": true,
  "o2_sensor_connected": true,

  "SystemStatus": {
    "currentMode": "cooling",
    "errorCode": null,
    "SteamOnline": true,
    "HoistOnline": true
  },

  "Telemetry": {
    "Temperature": {
      "SteamGenerator": 0, "HeaterZone": 0,
      "AirDuct": -110.5, "Average": -110.5, "ChamberZone": -110.5
    },
    "Environment": {
      "AirDuctHumidity": 0, "ChamberHumidity": 0,
      "ChamberOxygen": 20.9, "NitrogenLevel": 85.0
    },
    "vfdStatus": {
      "Steam": { "Frequency": 25.0, "ErrorCode": "" },
      "Hoist": { "Frequency": 0, "ErrorCode": "" }
    }
  },

  "digital_inputs": {
    "pipe_hoist": {
      "lsw_top_emergency": false, "lsw_top_working": false,
      "lsw_bottom_working": true, "lsw_bottom_emergency": false
    },
    "patient_hoist": {
      "lsw_top_emergency": false, "lsw_top_working": false,
      "lsw_bottom_working": true, "lsw_bottom_emergency": false,
      "patient_present": true
    },
    "safety": { "estop_pressed": false, "cabinet_door_open": false }
  },

  "stats": {
    "patient_hoist": 0, "pipe_hoist": 0,
    "steam": 2, "charger": 1, "heater": 1, "exhaust": 2
  }
}
```

---

#### `GET /api/actuators/status`
Возвращает статусы исполнительных устройств (нагнетатель, парогенератор, лебёдки, ТЭН, вытяжка, заслонка, LED).

**Ответ:**
```json
{
  "blower": { "enabled": true, "frequency_hz": 30.0 },
  "steam_generator": { "enabled": true, "frequency_hz": 25.0, "direction": "forward" },
  "patient_hoist": { "state": "stop" },
  "pipe_hoist": { "state": "up" },
  "heater": { "enabled": true, "power_w": 500 },
  "exhaust_fan": { "enabled": true },
  "exhaust_damper": { "state": "open" },
  "led_strip": { "enabled": true, "color": "#FF5500", "type": "argb" }
}
```

---

#### `GET /api/log?lines=100`
Возвращает содержимое лога последней процедуры.

**Параметры:**
- `lines` (int, default=100) — количество последних строк

**Ответ:**
```json
{
  "content": "[2026-07-13 12:00:00.123] event_id=210 state=210 | Процедура: работа...",
  "lines_count": 42,
  "last_modified": "2026-07-13T12:05:30"
}
```

---

### POST-эндпоинты (команды)

Все POST-эндпоинты работают по схеме **"команда → ожидание event_id → ответ"**. Бэкенд записывает команду в ПЛК, ждёт подтверждения (`event_id`) и возвращает результат. Таймаут ожидания — 5 секунд.

**Общий формат ответа:**
```json
{
  "status": "success | error | timeout",
  "message": "Описание результата",
  "event_id": 210,
  "data": { ... }
}
```

---

#### `POST /api/settings`
Обновление настроек процедуры (режим + уставки).

**Тело запроса:**
```json
{
  "mode_selection": { "mode": "cooling" },
  "technological_settings": {
    "time_s1_sec": 30,
    "time_s2_sec": 10,
    "time_s3_sec": 5,
    "temperature_sp1": -110.0,
    "temperature_sp2": -80.0
  }
}
```

---

#### `POST /api/motion`
Команды движения лебёдок.

**Тело запроса:**
```json
{
  "patient_hoist": true,   // true=вверх, false=вниз, null=стоп
  "pipe_hoist": false
}
```

---

#### `POST /api/ui_buttons`
Дублирование кнопок контроллера.

**Тело запроса:**
```json
{
  "btn_ok": false,
  "btn_esc": false,
  "btn_reset_fault": true,
  "btn_bypass_confirm": false
}
```

---

#### `POST /api/security`
Разблокировка системы без интернета.

**Тело запроса:**
```json
{
  "system_code_long": "sdfbjkhds1212367t21asd"
}
```

---

#### `POST /api/autocalibration`
Запуск автокалибровки.

**Тело запроса:**
```json
{ "start": true }
```

---

#### `POST /api/actuators/command`
Универсальная команда для управления любым исполнительным устройством.

**Тело запроса (примеры):**

Нагнетатель:
```json
{
  "device": "blower",
  "payload": { "enabled": true, "frequency_hz": 30.0 }
}
```

Парогенератор:
```json
{
  "device": "steam_generator",
  "payload": { "enabled": true, "frequency_hz": 25.0, "direction": "forward" }
}
```

Лебёдка пациента:
```json
{
  "device": "patient_hoist",
  "payload": { "state": "up" }
}
```

ТЭН:
```json
{
  "device": "heater",
  "payload": { "enabled": true, "power_w": 500 }
}
```

Вытяжка:
```json
{
  "device": "exhaust_fan",
  "payload": { "enabled": true }
}
```

Заслонка:
```json
{
  "device": "exhaust_damper",
  "payload": { "state": "open" }
}
```

LED лента:
```json
{
  "device": "led_strip",
  "payload": { "enabled": true, "color": "#FF5500" }
}
```

---

## 🔌 WebSocket

### `WS /ws`
Стрим телеметрии в реальном времени.

**При подключении** сервер отправляет:
```json
{
  "type": "connection_established",
  "message": "Connected to telemetry stream",
  "timestamp": "2026-07-13T12:00:00"
}
```

**Периодически (каждые 200мс)** сервер рассылает:
```json
{
  "SystemStatus": { ... },
  "Telemetry": { ... },
  "digital_inputs": { ... },
  "stats": { ... },
  "timestamp": "2026-07-13T12:00:00.200"
}
```

Клиент также может отправлять сообщения (для быстрых команд, если потребуется).

---

## 🔄 Логика работы "команда → event_id"

```
1. Фронт → POST /api/motion { patient_hoist: true }
2. Бэк → регистрирует команду в command_tracker
3. Бэк → записывает бит в регистр ПЛК (адрес 210)
4. Бэк → ждёт event_id от ПЛК (регистр 400)
5. ПЛК → выполняет команду → записывает event_id=210
6. Бэк → получает event_id → разблокирует ответ
7. Бэк → возвращает фронт: { status: "success", event_id: 210 }
```

Если ПЛК не ответил за 5 секунд → `status: "timeout"`.

---

##  Формат event_id

Строка состояния `abc`, где:
- **a** — группа (1-Простой, 2-Процедура, 3-Прохлаживание, 4-Сушка, 5-Загрузка азота, 6-Сервис)
- **b** — подгруппа (0-общий, 1-Лебёдка пациента, 2-Трубоподъемник, 3-Парогенератор, 4-Нагнетатель, 5-Нагреватель, 6-Вытяжка)
- **c** — параметр (0-стоп, 1-работа/вверх, 2-вниз/авария, и т.д.)

Пример: `event_id=210` → группа 2 (Процедура), подгруппа 1 (Лебёдка пациента), параметр 0 (стоп).

---

## 📊 Логи процедур

- **Текущий лог:** `logs/last_procedure.log`
- **Архив:** `logs/archive/procedure_YYYYMMDD_HHMMSS.log`

Лог автоматически архивируется при смене группы (начало новой процедуры).

---

## 🛠️ Разработка

### Добавление нового устройства
1. Добавить секцию в `config.json`
2. Создать модель в `models.py`
3. Добавить логику опроса в соответствующий клиент (Modbus/Zigbee/RS485)
4. Интегрировать в `main.py` (lifespan)

### Изменение карты регистров ПЛК
Отредактировать `ModbusRegisterMap` в `modbus_client.py` и парсеры в `ModbusDataParser`.

---
