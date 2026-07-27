"""
Менеджер WS-подключений.

Формат сообщений в обе стороны - конверт:
    {"event": "<имя>", "payload": {...}}

где "<имя>" совпадает с названиями из README (`sensors_data`, `event`,
`controller_button_pressed`, `controller_button_released`,
`machine_controls`, `steam_speed_control`).
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket
from pydantic import ValidationError

from app import hardware
from app.models import (
    WSControllerButtonPressed,
    WSEvent,
    WSMachineControl,
    WSSensorsData,
    WSSteamSpeedControl,
)

logger = logging.getLogger("vent_backend.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info("WS client connected, total=%d", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
        logger.info("WS client disconnected, total=%d", len(self._connections))

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
        # валидация формы данных перед отправкой (сгорит рано, если протокол
        # начнёт присылать не то, что описано в README)
        validated = WSSensorsData.model_validate(data)
        await self.broadcast("sensors_data", validated.model_dump())

    async def broadcast_event(self, event_id: int) -> None:
        await self.broadcast("event", WSEvent(event_id=event_id).model_dump())


manager = ConnectionManager()


async def sensors_broadcast_loop() -> None:
    """Раз в 0.2с забирает данные датчиков и рассылает их всем подключенным
    клиентам, как указано в задаче (`asyncio.sleep(0.2)`)."""
    while True:
        try:
            data = await hardware.get_sensors_data()
            await manager.broadcast_sensors_data(data)
        except Exception:
            logger.exception("sensors_broadcast_loop: failed to fetch/broadcast sensors_data")
        await asyncio.sleep(0.2)


async def handle_incoming_message(raw: dict) -> None:
    """Разбирает конверт {"event": ..., "payload": ...}, пришедший от фронта,
    и вызывает соответствующую команду в hardware.py."""
    event = raw.get("event")
    payload = raw.get("payload") or {}

    try:
        if event == "controller_button_pressed":
            data = WSControllerButtonPressed.model_validate(payload)
            await hardware.send_button_press(data.button)

        elif event == "controller_button_released":
            await hardware.send_button_release()

        elif event == "machine_controls":
            data = WSMachineControl.model_validate(payload)
            await hardware.send_machine_control(data.control_type, data.value)

        elif event == "steam_speed_control":
            data = WSSteamSpeedControl.model_validate(payload)
            await hardware.send_steam_speed(data.value)

        else:
            logger.warning("Unknown incoming WS event: %r", event)

    except ValidationError:
        logger.warning("Invalid payload for WS event %r: %r", event, payload)
