## Типы ивентов

### Информация с сенсоров:

```json
{
    "type": "sensor_data",
    "data": {
        "SystemStatus": {
            "currentMode": "cooling",
            "errorCode": [],
            "SteamOnline": true,
            "HoistOnline": true
        },
        "Telemetry": {
            "Temperature": {
                "SteamGenerator": 0.0,
                "HeaterZone": 0.0,
                "AirDuct": 0.0,
                "Humidity": 0.0,
                "ChamberZone": 0.0
            },
            "Environment": {
                "AirDuctHumidity": 0.0,
                "ChamberHumidity": 0.0,
                "ChamberOxygen": 0.0,
                "NitrogenLevel": 0.0
            },
            "vfdStatus": {
                "Steam": {
                    "Frequency": 0.0,
                    "ErrorCode": ""
                },
                "Hoist": {
                    "Frequency": 0.0,
                    "ErrorCode": ""
                }
            }
        }
    },
    "timestamp": "2026-06-21T23:20:24.220353"
}
```
### Ивенты:

```json
{
    "type": "event",
    "data": {
        "EventType": 0
    },
    "timestamp": "2026-06-21T23:19:32.538796"
}
```
### Типы ивентов:


### Типы ошибок:

