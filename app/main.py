"""
FastAPI-бэкенд для панели управления вент. установкой.
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app import hardware, storage
from app.models import (
    BasicResponse,
    ChangeProcedureStateRequest,
    CheckUnlockCodeRequest,
    CheckUnlockCodeResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    StartSelfTestRequest,
    SystemConfiguration,
)
from app.ws_manager import handle_incoming_message, manager, sensors_broadcast_loop
from app.modbus_integration import init_zigbee_mqtt, stop_zigbee_mqtt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vent_backend")

app = FastAPI(title="Vent Controller Backend")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_background_tasks: set[asyncio.Task] = set()


@app.on_event("startup")
async def on_startup() -> None:
    # Инициализация Modbus
    plc_ip = os.environ.get("PLC_IP", "192.168.0.100")
    plc_port = int(os.environ.get("PLC_PORT", "502"))
    
    if not hardware.init_hardware(plc_ip, plc_port):
        logger.error(f"Не удалось подключиться к ПЛК {plc_ip}:{plc_port}")
    else:
        logger.info(f"Modbus инициализирован: {plc_ip}:{plc_port}")
    
    # Инициализация Zigbee (MQTT)
    mqtt_broker = os.environ.get("MQTT_BROKER", "localhost")
    mqtt_port = int(os.environ.get("MQTT_PORT", "1883"))
    mqtt_topic = os.environ.get("MQTT_TOPIC", "zigbee2mqtt/0x7cc6b6fffeab1b60")
    
    if not init_zigbee_mqtt(mqtt_broker, mqtt_port, mqtt_topic):
        logger.warning("Zigbee MQTT не запущен (возможно брокер недоступен)")
    
    # Пробрасываем событие от контроллера в WS-рассылку
    hardware.set_event_callback(manager.broadcast_event)

    # Цикл рассылки sensors_data раз в 0.2с
    task = asyncio.create_task(sensors_broadcast_loop())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    for task in list(_background_tasks):
        task.cancel()
    
    # Остановка Zigbee
    stop_zigbee_mqtt()
    
    logger.info("Сервис остановлен")


# ---------------------------------------------------------------------------
# POST /api/change-procedure-state/
# ---------------------------------------------------------------------------

@app.post("/api/change-procedure-state/", response_model=BasicResponse)
async def change_procedure_state(body: ChangeProcedureStateRequest):
    ok = await hardware.send_procedure_action(body.action)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Не удалось выполнить действие '{body.action}'")
    return BasicResponse(status_code="200", message=f"Процедура: {body.action}")


# ---------------------------------------------------------------------------
# POST /api/self-test/, POST /api/self-test/stop
# ---------------------------------------------------------------------------

@app.post("/api/self-test/", response_model=BasicResponse)
async def start_self_test(body: StartSelfTestRequest):
    ok = await hardware.start_self_test(body.type)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Не удалось запустить само-тест")
    return BasicResponse(status_code="200", message=f"Само-тест запущен: {body.type}")


@app.post("/api/self-test/stop", response_model=BasicResponse)
async def stop_self_test():
    ok = await hardware.stop_self_test()
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Не удалось остановить само-тест")
    return BasicResponse(status_code="200", message="Само-тест остановлен")


# ---------------------------------------------------------------------------
# POST /api/update-settings, GET /api/settings
# ---------------------------------------------------------------------------

@app.post("/api/update-settings", response_model=BasicResponse)
async def update_settings(body: SettingsUpdateRequest):
    current = await storage.read_settings()
    update_data = body.model_dump(exclude_none=True)

    if "wifi" in update_data:
        wifi_in = update_data.pop("wifi")
        password = wifi_in.pop("password", None)
        wifi_in["password_len"] = len(password) if password is not None else wifi_in.get("password_len", 0)
        current["wifi"] = wifi_in

    current.update(update_data)

    ok = await hardware.apply_settings(current)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Не удалось применить настройки на контроллере")

    await storage.write_settings(current)
    return BasicResponse(status_code="200", message="Настройки обновлены")


@app.get("/api/settings", response_model=SettingsResponse)
async def get_settings():
    data = await storage.read_settings()
    return SettingsResponse(**data)


# ---------------------------------------------------------------------------
# GET/POST /api/config
# ---------------------------------------------------------------------------

@app.get("/api/config", response_model=SystemConfiguration)
async def get_config():
    return await storage.read_config()


@app.post("/api/config", response_model=BasicResponse)
async def post_config(body: SystemConfiguration):
    await storage.write_config(body)
    return BasicResponse(status_code="200", message="Конфигурация сохранена")


# ---------------------------------------------------------------------------
# POST /api/unlock, POST /api/unlock/check
# ---------------------------------------------------------------------------

@app.post("/api/unlock", response_model=BasicResponse)
async def request_unlock():
    settings = await storage.read_settings()
    settings["blocked"] = "unlocking"
    await storage.write_settings(settings)

    ok = await hardware.request_unlock()
    if not ok:
        settings["blocked"] = "yes"
        await storage.write_settings(settings)
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Не удалось инициировать разблокировку")

    return BasicResponse(status_code="200", message="Запрос на разблокировку отправлен")


@app.post("/api/unlock/check", response_model=CheckUnlockCodeResponse)
async def check_unlock_code(body: CheckUnlockCodeRequest):
    accepted, days_left = await hardware.check_unlock_code(body.code)

    settings = await storage.read_settings()
    settings["blocked"] = "no" if accepted else "yes"
    await storage.write_settings(settings)

    return CheckUnlockCodeResponse(accepted=accepted, days_left=days_left)


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            raw = await ws.receive_json()
            await handle_incoming_message(raw)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WS error")
    finally:
        await manager.disconnect(ws)