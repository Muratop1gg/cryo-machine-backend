"""
Кнопки, дублирующие кнопки контроллера (OK / ESC / RESET / CONFIRM).

Фронт присылает controller_button_pressed при нажатии и
controller_button_released при отпускании. В ПЛК уходит coil = 1 / 0.

Защита от "залипания" кнопки:
- кнопка считается нажатой, пока её держит хотя бы один клиент;
- при отключении клиента все его кнопки отпускаются;
- кнопка, которую держат дольше BUTTON_MAX_HOLD_SEC, отпускается сама;
- если отпускание не удалось записать в ПЛК, оно повторяется.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

from app import modbus_integration

logger = logging.getLogger("vent_backend.buttons")

BUTTON_MAX_HOLD_SEC = float(os.environ.get("BUTTON_MAX_HOLD_SEC", "30"))
WATCHDOG_INTERVAL = 0.5


class ButtonNotConfigured(Exception):
    """Для кнопки не задан адрес coil в MODBUS_CONFIG["buttons"]"""


class ButtonWriteFailed(Exception):
    """ПЛК не принял запись"""


def _address(button: str) -> int:
    address = modbus_integration.MODBUS_CONFIG["buttons"].get(button)
    if address is None:
        raise ButtonNotConfigured(f"Не задан адрес coil для кнопки {button}")
    return address


async def _write(button: str, pressed: bool) -> None:
    manager = modbus_integration.get_modbus_manager()
    if not await manager.write_coil(_address(button), pressed):
        raise ButtonWriteFailed(f"ПЛК не принял {'нажатие' if pressed else 'отпускание'} {button}")


class ButtonManager:
    def __init__(self) -> None:
        # кнопка -> {client_id: время нажатия}
        self._holders: dict[str, dict[int, float]] = {
            button: {} for button in modbus_integration.MODBUS_CONFIG["buttons"]
        }
        # кнопки, отпускание которых не удалось записать
        self._pending_release: set[str] = set()
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None

    async def press(self, client_id: int, button: str) -> None:
        async with self._lock:
            holders = self._holders[button]
            first = not holders
            holders[client_id] = time.monotonic()
            if not first:
                return
            try:
                await _write(button, True)
            except Exception:
                holders.pop(client_id, None)
                raise
            self._pending_release.discard(button)
            logger.info("Кнопка %s нажата", button)

    async def release(self, client_id: int, button: Optional[str] = None) -> None:
        """Отпустить кнопку (или все кнопки клиента, если button не указан)"""
        buttons = [button] if button else list(self._holders)
        errors: list[Exception] = []
        async with self._lock:
            for name in buttons:
                holders = self._holders[name]
                if client_id not in holders:
                    continue
                del holders[client_id]
                if holders:
                    continue
                try:
                    await self._send_release(name)
                except Exception as e:
                    errors.append(e)
        if errors:
            raise errors[0]

    async def _send_release(self, button: str) -> None:
        try:
            await _write(button, False)
        except Exception:
            self._pending_release.add(button)
            raise
        self._pending_release.discard(button)
        logger.info("Кнопка %s отпущена", button)

    async def _watch_loop(self) -> None:
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL)
            try:
                async with self._lock:
                    now = time.monotonic()
                    for button, holders in self._holders.items():
                        if BUTTON_MAX_HOLD_SEC > 0:
                            for client_id, pressed_at in list(holders.items()):
                                if now - pressed_at > BUTTON_MAX_HOLD_SEC:
                                    logger.warning("Кнопку %s держат слишком долго, отпускаем", button)
                                    del holders[client_id]
                                    if not holders:
                                        self._pending_release.add(button)

                        if button in self._pending_release and not holders:
                            try:
                                await self._send_release(button)
                            except Exception as e:
                                logger.debug("Повтор отпускания %s не удался: %s", button, e)
            except Exception:
                logger.exception("buttons: watch_loop error")

    def start_watchdog(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._watch_loop())

    async def stop_watchdog(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


buttons = ButtonManager()
