"""
Слой связи с вент. контроллером.

Здесь НЕТ реализации самого протокола общения с контроллером - это, как
и было оговорено, делается отдельно и подключается сюда. Все функции ниже -
это точки интеграции: там, где помечено `# TODO: PROTOCOL`, нужно вызвать
реальный код общения по вашему протоколу (UART/Modbus/CAN/сокет - не важно).

Чтобы бэкенд можно было поднять и погонять уже сейчас (в том числе поверх
фронта), по умолчанию включен MOCK-режим: он отдаёт правдоподобные
рандомные данные и просто логирует команды. Отключается переменной
окружения VENT_MOCK_HARDWARE=0.

Событие `event` (WS.Event) контроллер присылает сам, асинхронно,
без запроса от бэка. Чтобы это доставить во фронт, при получении события
от протокола дергайте `push_event(event_id)` (см. пример в фоновой
задаче `_mock_event_generator` ниже - в реальной реализации вместо неё
у вас будет обработчик пришедших от контроллера данных).
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("vent_backend.hardware")

MOCK_MODE = os.environ.get("VENT_MOCK_HARDWARE", "1") != "0"

EventCallback = Callable[[int], Awaitable[None]]
_event_callback: Optional[EventCallback] = None


def set_event_callback(callback: EventCallback) -> None:
    """Вызывается один раз при старте приложения (main.py), чтобы hardware-слой
    знал, куда пробрасывать события `event_id`, пришедшие от контроллера
    вне ответа на запрос (см. WS.Event в README)."""
    global _event_callback
    _event_callback = callback


async def push_event(event_id: int) -> None:
    """Вызывать из кода протокола, когда контроллер прислал событие."""
    if _event_callback is not None:
        await _event_callback(event_id)
    else:
        logger.warning("push_event(%s) called before set_event_callback()", event_id)


# ---------------------------------------------------------------------------
# Периодические данные датчиков (sensors_data, раз в 0.2с)
# ---------------------------------------------------------------------------

async def get_sensors_data() -> dict:
    """Возвращает данные для WS-сообщения sensors_data.

    TODO: PROTOCOL - заменить на реальное чтение состояния с контроллера.
    """
    if MOCK_MODE:
        return _mock_sensors_data()

    raise NotImplementedError(
        "get_sensors_data(): подключите реальный протокол общения с контроллером"
    )


def _mock_sensors_data() -> dict:
    return {
        "digital_inputs": {
            "pipe_hoist": {
                "lsw_top_emergency": False,
                "lsw_top_working": False,
                "lsw_bottom_working": True,
                "lsw_bottom_emergency": False,
            },
            "patient_hoist": {
                "lsw_top_emergency": False,
                "lsw_top_working": False,
                "lsw_bottom_working": True,
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
            "t1": round(20 + random.random() * 2, 2),
            "t2": round(20 + random.random() * 2, 2),
            "t3": round(20 + random.random() * 2, 2),
            "t4": round(20 + random.random() * 2, 2),
            "humidity": round(40 + random.random() * 5, 2),
            "oxygen": round(20.9 + random.random() * 0.1, 2),
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


# ---------------------------------------------------------------------------
# /api/change-procedure-state/
# ---------------------------------------------------------------------------

async def send_procedure_action(action: str) -> bool:
    """TODO: PROTOCOL - отправить команду старт/стоп/пауза/резюм контроллеру."""
    logger.info("send_procedure_action(%s)", action)
    if MOCK_MODE:
        return True
    raise NotImplementedError


# ---------------------------------------------------------------------------
# /api/self-test/
# ---------------------------------------------------------------------------

async def start_self_test(test_type: str) -> bool:
    """TODO: PROTOCOL - запустить само-тест на контроллере."""
    logger.info("start_self_test(%s)", test_type)
    if MOCK_MODE:
        return True
    raise NotImplementedError


async def stop_self_test() -> bool:
    """TODO: PROTOCOL - остановить само-тест на контроллере."""
    logger.info("stop_self_test()")
    if MOCK_MODE:
        return True
    raise NotImplementedError


# ---------------------------------------------------------------------------
# /api/update-settings
# ---------------------------------------------------------------------------

async def apply_settings(settings: dict) -> bool:
    """TODO: PROTOCOL - применить настройки (уставки температур, тайминги,
    цвет LED, wifi) на контроллере/устройстве."""
    logger.info("apply_settings(%s)", {k: v for k, v in settings.items() if k != "wifi"})
    if MOCK_MODE:
        return True
    raise NotImplementedError


# ---------------------------------------------------------------------------
# /api/unlock, /api/unlock/check
# ---------------------------------------------------------------------------

async def request_unlock() -> bool:
    """Инициирует процедуру разблокировки (например, контроллер должен
    подготовить/показать сид для генерации кода, привязанный ко времени).

    TODO: PROTOCOL - реализовать реальный запрос к контроллеру.
    """
    logger.info("request_unlock()")
    if MOCK_MODE:
        return True
    raise NotImplementedError


async def check_unlock_code(code: str) -> tuple[bool, int]:
    """Проверяет код разблокировки, возвращает (accepted, days_left).

    TODO: PROTOCOL - код содержит информацию о времени (согласно README),
    реальная проверка/расшифровка кода должна быть тут.
    """
    logger.info("check_unlock_code(%s)", code)
    if MOCK_MODE:
        # заглушка: код принимается, если он не пустой и состоит из цифр
        accepted = code.isdigit() and len(code) >= 4
        days_left = 30 if accepted else 0
        return accepted, days_left
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Управляющие WS-команды от фронта (machine_controls, steam_speed_control,
# controller_button_pressed/released)
# ---------------------------------------------------------------------------

async def send_button_press(button: str) -> None:
    """TODO: PROTOCOL - сообщить контроллеру о нажатии кнопки на пульте."""
    logger.info("send_button_press(%s)", button)


async def send_button_release() -> None:
    """TODO: PROTOCOL - сообщить контроллеру об отпускании кнопки."""
    logger.info("send_button_release()")


async def send_machine_control(control_type: str, value: bool) -> None:
    """TODO: PROTOCOL - включить/выключить конкретный узел машины."""
    logger.info("send_machine_control(%s, %s)", control_type, value)


async def send_steam_speed(value: int) -> None:
    """TODO: PROTOCOL - установить скорость подачи пара (0..50)."""
    logger.info("send_steam_speed(%s)", value)


# ---------------------------------------------------------------------------
# Демонстрационный генератор случайных событий - ТОЛЬКО для MOCK_MODE.
# В реальной реализации эту функцию не запускать: события должны приходить
# из кода протокола общения с контроллером (там же, где вызывается push_event).
# ---------------------------------------------------------------------------

async def mock_event_generator_task() -> None:
    if not MOCK_MODE:
        return
    while True:
        await asyncio.sleep(30)
        await push_event(int(time.time()) % 1000)
