"""
Обновленный менеджер WS-подключений с интеграцией Modbus.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket
from pydantic import ValidationError

from app import hardware
from app.buttons import ButtonNotConfigured, ButtonWriteFailed
from app.models import (
    WSControllerButtonPressed,
    WSControllerButtonReleased,
    WSEvent,
    WSMachineControl,
    WSSensorsData,
    WSSteamSpeedControl,
)
from app import health


logger = logging.getLogger("vent_backend.ws")

async def _on_connection_status(name: str, status: str) -> None:
    await manager.broadcast_connection_status(name, status)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info("WS client connected, total=%d", len(self._connections))

        # Сразу отдаём новому клиенту текущий статус соединений
        try:
            await ws.send_json({
                "event": "connection_status",
                "payload": {
                    "name": "snapshot",
                    "status": health.get_status(),
                },
            })
        except Exception:
            logger.exception("failed to send initial connection_status")

        # и текущее состояние процедуры (для таймера)
        try:
            await ws.send_json({
                "event": "procedure_state",
                "payload": procedure_state_payload(),
            })
        except Exception:
            logger.exception("failed to send initial procedure_state")

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
        logger.info("WS client disconnected, total=%d", len(self._connections))

        # Клиент пропал - отпускаем все кнопки, которые он держал
        try:
            await hardware.send_button_release(id(ws))
        except Exception as e:
            logger.warning(f"Не удалось отпустить кнопки отключившегося клиента: {e}")

    async def broadcast(self, event: str, payload: dict) -> None:
        message = {"event": event, "payload": payload}
        async with self._lock:
            targets = list(self._connections)
        stale: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        if stale:
            async with self._lock:
                for ws in stale:
                    self._connections.discard(ws)

    async def broadcast_sensors_data(self, data: dict) -> None:
        validated = WSSensorsData.model_validate(data)
        await self.broadcast("sensors_data", validated.model_dump())

    async def broadcast_connection_status(self, name: str, status: str) -> None:
        await self.broadcast(
            "connection_status",
            {"name": name, "status": status},
        )

    async def broadcast_zigbee_event(self, event_id: int, payload: dict):
        """Отправить событие от Zigbee всем клиентам."""
        message = {
            "event": "zigbee_event",
            "payload": {
                "event_id": event_id,
                "data": payload
            }
        }
        async with self._lock:
            targets = list(self._connections)
        stale = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        if stale:
            async with self._lock:
                for ws in stale:
                    self._connections.discard(ws)

    async def broadcast_event(self, event_id: int) -> None:
        await self.broadcast("event", WSEvent(event_id=event_id).model_dump())


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Состояние процедуры (для таймера на фронте)
# ---------------------------------------------------------------------------
# Отдельное сообщение procedure_state нужно потому, что коды event_id
# 100-103 заняты группой "Простой" (формат abc), и таймер на фронте
# нельзя завязывать на них.

_PROCEDURE_STATUS_AFTER = {
    "start": "running",
    "resume": "running",
    "pause": "paused",
    "stop": "stopped",
}
_procedure_status = "stopped"


def procedure_state_payload(action: str | None = None) -> dict:
    return {"action": action, "status": _procedure_status}


async def broadcast_procedure_state(action: str) -> None:
    global _procedure_status
    _procedure_status = _PROCEDURE_STATUS_AFTER[action]
    await manager.broadcast("procedure_state", procedure_state_payload(action))

def init_health_watchdog() -> None:
        health.set_status_listener(_on_connection_status)
        health.start_watchdog()
        logger.info("Health watchdog инициализирован")

async def sensors_broadcast_loop() -> None:
    """Раз в 0.2с забирает данные датчиков и рассылает их всем подключенным клиентам."""
    while True:
        try:
            data = await hardware.get_sensors_data()
            await manager.broadcast_sensors_data(data)
        except Exception:
            logger.exception("sensors_broadcast_loop: failed to fetch/broadcast sensors_data")
        await asyncio.sleep(0.2)


async def _send_error(ws: WebSocket, event: str | None, message: str) -> None:
    try:
        await ws.send_json({"event": "error", "payload": {"event": event, "message": message}})
    except Exception:
        pass


async def handle_incoming_message(raw: dict, ws: WebSocket) -> None:
    """
    Разбирает конверт {"event": ..., "payload": ...}, пришедший от фронта,
    и вызывает соответствующую команду.
    """
    event = raw.get("event")
    payload = raw.get("payload") or {}

    try:
        # Обработка команд управления через Modbus
        if event == "machine_controls":
            data = WSMachineControl.model_validate(payload)
            if not await hardware.send_machine_control(data.control_type, data.value):
                await _send_error(ws, event, f"Команда {data.control_type} не выполнена")

        elif event == "steam_speed_control":
            data = WSSteamSpeedControl.model_validate(payload)
            if not await hardware.send_steam_speed(data.value):
                await _send_error(ws, event, "Не удалось задать частоту парогенератора")

        elif event == "controller_button_pressed":
            data = WSControllerButtonPressed.model_validate(payload)
            await hardware.send_button_press(id(ws), data.button)

        elif event == "controller_button_released":
            data = WSControllerButtonReleased.model_validate(payload)
            await hardware.send_button_release(id(ws), data.button)

        # Новые команды для сушки/процедуры/прохлаживания
        elif event in ["dry_start", "dry_stop", "procedure_start", "procedure_stop",
                       "cooling_start", "cooling_stop", "hoist_up", "hoist_down",
                       "pipe_hoist_up", "pipe_hoist_down"]:
            success = await hardware.handle_ws_command(event, payload)
            if success:
                logger.info(f"Команда {event} выполнена успешно")
            else:
                logger.error(f"Ошибка выполнения команды {event}")
        
        else:
            logger.warning("Unknown incoming WS event: %r", event)

    except ValidationError as e:
        logger.warning(f"Invalid payload for WS event {event!r}: {e}")
        await _send_error(ws, event, "Некорректные данные команды")
    except (ButtonNotConfigured, ButtonWriteFailed) as e:
        logger.warning(str(e))
        await _send_error(ws, event, str(e))
    except Exception as e:
        logger.exception(f"Ошибка обработки WS события {event}: {e}")

async def handle_modbus_event(event_id: int, payload: dict) -> None:
    """
    Обработчик событий от Modbus.
    Отправляет событие всем клиентам WebSocket.
    """
    try:
        # Отправляем событие в формате {"event": "event", "payload": {"event_id": value}}
        await manager.broadcast_event(event_id)
        logger.info(f"Modbus событие отправлено в WS: event_id={event_id}, payload={payload}")
    except Exception as e:
        logger.exception(f"Ошибка отправки Modbus события в WS: {e}")

def init_ws_event_handler() -> None:
    """
    Инициализировать обработчик событий от Modbus.
    Должна вызываться при старте приложения.
    """
    from app import modbus_integration as modbus
    
    # Устанавливаем callback для отправки событий от Modbus
    modbus.set_event_callback(handle_modbus_event)
    logger.info("WS event handler для Modbus инициализирован")