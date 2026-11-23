"""
Слой связи с вент. контроллером через Modbus.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Callable, Awaitable

from app import modbus_integration

logger = logging.getLogger("vent_backend.hardware")

# ПЛК работает в целых инженерных единицах (°C), поэтому уставка
# пишется как есть. Если в проекте ПЛК появятся десятые доли — 10.
TEMPERATURE_SETPOINT_SCALE = 1


# =====================================================================
# ИНИЦИАЛИЗАЦИЯ MODBUS
# =====================================================================
def init_hardware(plc_ip: str = "192.168.0.100", plc_port: int = 502) -> bool:
    """Инициализировать Modbus-соединение."""
    return modbus_integration.init_modbus(plc_ip, plc_port)


# =====================================================================
# Периодические данные датчиков
# =====================================================================
async def get_sensors_data() -> dict:
    """Возвращает данные для WS-сообщения sensors_data."""
    try:
        return await modbus_integration.read_plc_sensors_data()
    except Exception as e:
        logger.error(f"Ошибка чтения данных с ПЛК: {e}")
        # Возвращаем пустую структуру, но без моков
        return {
            "digital_inputs": {
                "pipe_hoist": {
                    "lsw_top_emergency": False,
                    "lsw_top_working": False,
                    "lsw_bottom_working": False,
                    "lsw_bottom_emergency": False,
                },
                "patient_hoist": {
                    "lsw_top_emergency": False,
                    "lsw_top_working": False,
                    "lsw_bottom_working": False,
                    "lsw_bottom_emergency": False,
                    "patient_present": False,
                },
                "safety": {
                    "estop_pressed": False,
                    "cabinet_door_open": False,
                },
            },
            "stats": {
                "patient_hoist": 0,
                "pipe_hoist": 0,
                "steam": 0,
                "charger": 0,
                "heater": 0,
                "exhaust": 0,
            },
            "sensor_data": {
                "t1": 0.0,
                "t2": 0.0,
                "t3": 0.0,
                "t4": 0.0,
                "humidity": 0.0,
                "oxygen": 0.0,
                "nitrogen_mass": None,
            },
            "diagnostics": {
                "test": {
                    "running": False,
                    "type": None,
                    "stage": None,
                }
            },
        }


# =====================================================================
# WS КОМАНДЫ ОТ ФРОНТА
# =====================================================================
async def handle_ws_command(event: str, payload: dict) -> bool:
    """
    Обработать команду от WebSocket.
    Используется в ws_manager.py.
    """
    return await modbus_integration.handle_web_socket_command(event, payload)


# =====================================================================
# ПРОЧИЕ КОМАНДЫ
# =====================================================================
async def send_procedure_action(action: str) -> bool:
    """Отправить команду старт/стоп/пауза/резюм."""
    command_map = {
        "start": "procedure_start",
        "stop": "procedure_stop",
        "pause": "procedure_stop",
        "resume": "procedure_start",
    }
    command = command_map.get(action)
    if command:
        return await modbus_integration.handle_web_socket_command(command, {})
    return False


async def start_self_test(test_type: str) -> bool:
    """Запустить само-тест."""
    logger.info(f"start_self_test({test_type})")
    # TODO: добавить Modbus команды для само-теста
    return False


async def stop_self_test() -> bool:
    """Остановить само-тест."""
    logger.info("stop_self_test()")
    # TODO: добавить Modbus команды для само-теста
    return False


async def apply_settings(settings: dict) -> bool:
    """Применить настройки на контроллере."""
    logger.info(f"apply_settings({settings})")
    
    # Запись уставок в Modbus
    manager = modbus_integration.get_modbus_manager()
    config = modbus_integration.MODBUS_CONFIG["registers"]
    success = True
    
    if "temperature_sp1" in settings:
        success &= await manager.write_register(
            config["temperature_sp1"],
            int(round(settings["temperature_sp1"] * TEMPERATURE_SETPOINT_SCALE)),
        )
    if "temperature_sp2" in settings:
        success &= await manager.write_register(
            config["temperature_sp2"],
            int(round(settings["temperature_sp2"] * TEMPERATURE_SETPOINT_SCALE)),
        )
    if "time_s1_sec" in settings:
        success &= await manager.write_register(config["time_s1"], int(settings["time_s1_sec"]))
    if "time_s2_sec" in settings:
        success &= await manager.write_register(config["time_s2"], int(settings["time_s2_sec"]))
    if "time_s3_sec" in settings:
        success &= await manager.write_register(config["time_s3"], int(settings["time_s3_sec"]))
    
    # Применение цвета LED (если есть)
    if "led_color" in settings:
        # TODO: добавить Modbus команду для LED
        pass
    
    return success


async def request_unlock() -> bool:
    """Инициировать разблокировку."""
    logger.info("request_unlock()")
    # TODO: реализовать Modbus команду для разблокировки
    return False


async def check_unlock_code(code: str) -> tuple[bool, int]:
    """Проверить код разблокировки."""
    logger.info(f"check_unlock_code({code})")
    # TODO: реализовать проверку кода через Modbus
    return False, 0


async def send_button_press(button: str) -> None:
    """Нажатие кнопки на пульте: импульс в соответствующую катушку."""
    logger.info(f"send_button_press({button})")

    address = modbus_integration.MODBUS_CONFIG["buttons"].get(button)

    if address is None:
        logger.warning(f"Неизвестная кнопка пульта: {button}")
        return

    manager = modbus_integration.get_modbus_manager()

    if await manager.write_coil(address, True):
        await asyncio.sleep(0.2)
        await manager.write_coil(address, False)


async def send_button_release() -> None:
    """Отпускание кнопки (импульс уже снят в send_button_press)."""
    logger.debug("send_button_release()")


async def send_machine_control(control_type: str, value: bool) -> None:
    """Управление узлом машины."""
    logger.info(f"send_machine_control({control_type}, {value})")
    await modbus_integration.handle_web_socket_command(
        "machine_controls", 
        {"control_type": control_type, "value": value}
    )


async def send_steam_speed(value: int) -> None:
    """Установить скорость пара."""
    logger.info(f"send_steam_speed({value})")
    manager = modbus_integration.get_modbus_manager()
    address = modbus_integration.MODBUS_CONFIG["registers"]["steam_speed"]
    await manager.write_register(address, int(value))


# =====================================================================
# Event Callback
# =====================================================================
EventCallback = Callable[[int], Awaitable[None]]
_event_callback: Optional[EventCallback] = None

def set_event_callback(callback: EventCallback) -> None:
    """Установить callback для обработки событий от контроллера."""
    global _event_callback
    _event_callback = callback
    logger.info("Event callback установлен")

async def push_event(event_id: int) -> None:
    """Вызвать callback с событием от контроллера."""
    if _event_callback is not None:
        try:
            await _event_callback(event_id)
        except Exception as e:
            logger.error(f"Ошибка при вызове event callback: {e}")
    else:
        logger.warning(f"push_event({event_id}) вызван, но callback не установлен")