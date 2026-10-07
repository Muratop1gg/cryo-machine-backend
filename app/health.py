# app/health.py
"""
Вотчдоги для Modbus и Zigbee/MQTT.

Каждое «успешное» событие в соответствующем модуле вызывает
mark_modbus_ok() / mark_zigbee_ok(). Фоновая задача периодически
смотрит, не «протух» ли соответствующий last_ok и рассылает
во фронт событие connection_status.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Literal, Optional

logger = logging.getLogger("vent_backend.health")


Status = Literal["online", "offline"]


# ---------------------------------------------------------------------------
# Пороги «протухания» (в секундах)
# ---------------------------------------------------------------------------
# Modbus читается в цикле sensors_broadcast_loop раз в 0.2с,
# поэтому 3с — с большим запасом.
MODBUS_STALE_AFTER = 3.0

# MQTT: у нас нет периодических событий, но у paho есть ping.
# Если брокер/сеть лежит — on_disconnect вызовется и сам пометит offline.
# Дополнительно считаем «мёртвым» соединение, если давно не было
# ни сообщений, ни подтверждений. Порог с запасом.
ZIGBEE_STALE_AFTER = 60.0

# Как часто проверять
CHECK_INTERVAL = 1.0


# ---------------------------------------------------------------------------
# Хранилище состояния
# ---------------------------------------------------------------------------

_modbus_last_ok: Optional[float] = None
_zigbee_last_ok: Optional[float] = None

_modbus_status: Status = "offline"
_zigbee_status: Status = "offline"

_listener: Optional[Callable[[str, Status], Awaitable[None]]] = None
_watch_task: Optional[asyncio.Task] = None


def set_status_listener(
    listener: Callable[[str, Status], Awaitable[None]],
) -> None:
    """Куда отдавать события о смене статуса."""
    global _listener
    _listener = listener


def mark_modbus_ok() -> None:
    global _modbus_last_ok
    _modbus_last_ok = time.monotonic()


def mark_zigbee_ok() -> None:
    global _zigbee_last_ok
    _zigbee_last_ok = time.monotonic()


def mark_modbus_failed() -> None:
    """Явный сброс — вызывается, когда мы точно знаем, что соединения нет."""
    global _modbus_last_ok, _modbus_status
    _modbus_last_ok = None
    if _modbus_status != "offline":
        _modbus_status = "offline"
        _notify("modbus", "offline")


def mark_zigbee_failed() -> None:
    global _zigbee_last_ok, _zigbee_status
    _zigbee_last_ok = None
    if _zigbee_status != "offline":
        _zigbee_status = "offline"
        _notify("zigbee", "offline")


def get_status() -> dict:
    return {
        "modbus": _modbus_status,
        "zigbee": _zigbee_status,
    }


# ---------------------------------------------------------------------------
# Уведомление слушателя
# ---------------------------------------------------------------------------

def _notify(name: str, status: Status) -> None:
    if _listener is None:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_listener(name, status))
    except RuntimeError:
        # нет активного loop — нечего делать
        pass
    except Exception:
        logger.exception("health: notify failed")


# ---------------------------------------------------------------------------
# Фоновая задача
# ---------------------------------------------------------------------------

def _evaluate(
    now: float,
    last_ok: Optional[float],
    stale_after: float,
    current: Status,
) -> Status:
    if last_ok is None:
        return "offline"
    if now - last_ok > stale_after:
        return "offline"
    return "online"


async def _watch_loop() -> None:
    global _modbus_status, _zigbee_status

    while True:
        try:
            now = time.monotonic()

            new_modbus = _evaluate(
                now, _modbus_last_ok, MODBUS_STALE_AFTER, _modbus_status
            )
            new_zigbee = _evaluate(
                now, _zigbee_last_ok, ZIGBEE_STALE_AFTER, _zigbee_status
            )

            if new_modbus != _modbus_status:
                _modbus_status = new_modbus
                logger.warning("Modbus status -> %s", new_modbus)
                _notify("modbus", new_modbus)

            if new_zigbee != _zigbee_status:
                _zigbee_status = new_zigbee
                logger.warning("Zigbee status -> %s", new_zigbee)
                _notify("zigbee", new_zigbee)

        except Exception:
            logger.exception("health: watch_loop error")

        await asyncio.sleep(CHECK_INTERVAL)


def start_watchdog() -> None:
    global _watch_task
    if _watch_task is None or _watch_task.done():
        _watch_task = asyncio.create_task(_watch_loop())
        logger.info("health: watchdog started")


async def stop_watchdog() -> None:
    global _watch_task
    if _watch_task is not None:
        _watch_task.cancel()
        try:
            await _watch_task
        except asyncio.CancelledError:
            pass
        _watch_task = None
        logger.info("health: watchdog stopped")