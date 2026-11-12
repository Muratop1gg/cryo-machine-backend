"""
Пульт управления (Zigbee2MQTT, 11 кнопок).

Сырые пакеты Z2M разбираются по спецификации
"Таблица соответствия команд пульта Zigbee2MQTT" в условные названия кнопок,
затем выполняется действие на ПЛК.

pt_lift_up / pt_lift_down (S6 / S4) - удерживаемые кнопки: пока кнопку держат,
пульт шлёт пакет каждые 300 мс, при отпускании приходит brightness_stop (pt_stop).
Лебёдка пациента едет, пока идут пакеты. Если пакет отпускания потерялся,
лебёдка останавливается сама через PT_HOLD_TIMEOUT без новых пакетов.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Awaitable, Callable, Optional

from app import modbus_integration as mi

logger = logging.getLogger("vent_backend.zigbee_remote")

# Пакеты при удержании идут раз в 300 мс, поэтому 1 с - с запасом на 2 потерянных пакета
PT_HOLD_TIMEOUT = float(os.environ.get("ZIGBEE_PT_HOLD_TIMEOUT", "1.0"))
WATCHDOG_INTERVAL = 0.1


def parse_remote_button(payload: dict) -> Optional[dict]:
    """Пакет Z2M -> {"button": <условное название>, ...} (по спецификации пульта)"""
    action = payload.get("action")
    level = payload.get("action_level")
    step = payload.get("action_step_size")
    rate = payload.get("action_rate")

    if action == "toggle":
        return {"button": "on_off"}
    if action == "brightness_stop":
        return {"button": "pt_stop", "packet_counter": 0}
    if action == "brightness_move_down":
        return {"button": "pt_lift_down", "action_rate": rate}
    if action == "brightness_move_up":
        return {"button": "pt_lift_up", "action_rate": rate}
    if action == "brightness_move_to_level":
        btn = {100: "connect", 3: "precool", 4: "dry"}.get(level)
        return {"button": btn} if btn else None
    if action == "brightness_step_down":
        btn = {2: "pi_dw", 10: "t_dw"}.get(step)
        return {"button": btn} if btn else None
    if action == "brightness_step_up":
        btn = {1: "pi_up", 11: "t_up"}.get(step)
        return {"button": btn} if btn else None
    return None


# ---------------------------------------------------------------------------
# Лебёдка пациента: удержание pt_lift_up / pt_lift_down
# ---------------------------------------------------------------------------

class PatientHoistHold:
    def __init__(self) -> None:
        self.direction: Optional[str] = None  # "up" | "down" | None
        self.last_packet = 0.0
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None

    async def move(self, direction: str) -> bool:
        async with self._lock:
            self.last_packet = time.monotonic()
            if self.direction == direction:
                # повторный пакет удержания - только продлеваем
                return True
            ok = await self._apply(direction)
            self.direction = direction if ok else None
            return ok

    async def stop(self) -> bool:
        async with self._lock:
            ok = await self._apply(None)
            self.direction = None
            return ok

    @staticmethod
    async def _apply(direction: Optional[str]) -> bool:
        # сначала выключаем ненужное направление, потом включаем нужное
        up = direction == "up"
        down = direction == "down"
        order = sorted((("hoist_up", up), ("hoist_down", down)), key=lambda item: item[1])
        success = True
        for command, value in order:
            ok = await mi._execute_coil_command(command, value)
            if ok:
                mi._trigger_states[command] = value
            success &= ok
        return success

    async def _watch_loop(self) -> None:
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL)
            if self.direction is None:
                continue
            if time.monotonic() - self.last_packet > PT_HOLD_TIMEOUT:
                logger.warning("Пульт: нет пакетов удержания %.1f с, останавливаем лебёдку пациента", PT_HOLD_TIMEOUT)
                try:
                    await self.stop()
                except Exception:
                    logger.exception("Пульт: не удалось остановить лебёдку пациента")

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


patient_hoist = PatientHoistHold()


# ---------------------------------------------------------------------------
# Кнопки -> действия
# ---------------------------------------------------------------------------

_procedure_on = False


async def _toggle_procedure() -> bool:
    # TODO: уточнить, что делает on_off (S1); пока - вкл/выкл процедуры, как раньше on/off
    global _procedure_on
    new_state = not _procedure_on
    ok = await mi._execute_coil_command("procedure_start", new_state)
    if ok:
        _procedure_on = new_state
    return ok


TIME_STEP_SEC = 10


async def _change_procedure_time(delta: int) -> bool:
    """t_up / t_dw: длительность процедуры (time_s3_sec) +-10 с"""
    from app import hardware, storage

    settings = await storage.read_settings()
    new_value = max(0, min(65535, int(settings.get("time_s3_sec", 0)) + delta))
    if not await hardware.apply_settings({"time_s3_sec": new_value}):
        return False
    settings["time_s3_sec"] = new_value
    await storage.write_settings(settings)
    logger.info("Пульт: длительность процедуры %s с", new_value)
    return True


async def _ignore() -> bool:
    # connect (S3) - кнопка сопряжения пульта с установкой, обрабатывается самим Zigbee
    return True


ACTIONS: dict[str, Callable[[], Awaitable[bool]]] = {
    "pt_lift_up": lambda: patient_hoist.move("up"),
    "pt_lift_down": lambda: patient_hoist.move("down"),
    "pt_stop": lambda: patient_hoist.stop(),
    "pi_up": lambda: mi._toggle_trigger_command("pipe_hoist_up"),
    "pi_dw": lambda: mi._toggle_trigger_command("pipe_hoist_down"),
    "on_off": _toggle_procedure,
    # TODO: подтвердить: precool/dry - запуск прохолаживания/сушки
    "precool": lambda: mi._execute_coil_command("cooling_start", True),
    "dry": lambda: mi._execute_coil_command("dry_start", True),
    "t_up": lambda: _change_procedure_time(TIME_STEP_SEC),
    "t_dw": lambda: _change_procedure_time(-TIME_STEP_SEC),
    "connect": _ignore,
}


async def handle_remote_payload(payload: dict) -> bool:
    parsed = parse_remote_button(payload)
    if parsed is None:
        logger.warning("Пульт: неизвестный пакет %s", payload)
        return False

    button = parsed["button"]
    logger.info("Пульт: %s (%s)", button, payload)
    return await ACTIONS[button]()
