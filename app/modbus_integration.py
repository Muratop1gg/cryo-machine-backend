"""
Модуль интеграции Modbus для управления вентиляционной установкой.

Обрабатывает команды от Zigbee и WebSocket, отправляя их на ПЛК по Modbus.
Также читает датчики и дискретные входы с ПЛК.

Основные особенности:
- постоянное TCP-соединение с ПЛК;
- автоматический reconnect при потере соединения;
- последовательная очередь Modbus-команд;
- защита одного Modbus-клиента от параллельного доступа;
- сохранение текущей логики Zigbee/WebSocket;
- отправка событий об успешно выполненных командах во фронт.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional, Callable, Awaitable, Any

from pyModbusTCP.client import ModbusClient
import paho.mqtt.client as mqtt


logger = logging.getLogger("vent_backend.modbus")


# =====================================================================
# КОНФИГУРАЦИЯ MODBUS АДРЕСОВ
# =====================================================================

MODBUS_CONFIG = {
    # Адреса катушек (Coils)
    "coils": {
        "dry_start": 0,
        "dry_stop": 1,

        "procedure_start": 2,
        "procedure_stop": 3,

        "cooling_start": 804,
        "cooling_stop": 805,

        "hoist_up": 4,
        "hoist_down": 5,

        "pipe_hoist_up": 6,
        "pipe_hoist_down": 7,

        "buzzer": 810,
    },

    # Адреса регистров хранения (Holding Registers)
    "registers": {
        "steam_speed": 100,
        "temperature_sp1": 101,
        "temperature_sp2": 102,
        "time_s1": 103,
        "time_s2": 104,
        "time_s3": 0,
    },

    # Адреса входных регистров (Input Registers)
    "input_registers": {
        "t1": 0,
        "t2": 1,
        "t3": 2,
        "t4": 303,
        "humidity": 304,
        "oxygen": 305,
        "nitrogen_mass": 306,
        "event": 3,  # НОВЫЙ РЕГИСТР СОБЫТИЙ
    },

    # Адреса дискретных входов (Discrete Inputs)
    "discrete_inputs": {
        "lsw_top_emergency_pipe": 1000,
        "lsw_top_working_pipe": 1001,
        "lsw_bottom_working_pipe": 1002,
        "lsw_bottom_emergency_pipe": 1003,

        "lsw_top_emergency_patient": 1004,
        "lsw_top_working_patient": 1005,
        "lsw_bottom_working_patient": 1006,
        "lsw_bottom_emergency_patient": 1007,

        "patient_present": 1008,

        "estop_pressed": 1009,
        "cabinet_door_open": 1010,
    },
}


# =====================================================================
# EVENT CALLBACK ДЛЯ ОТПРАВКИ СОБЫТИЙ ВО ФРОНТ
# =====================================================================

EventCallback = Callable[[int, dict], Awaitable[None]]
PLCEventCallback = Callable[[int],  Awaitable[None]]

_event_callback: Optional[EventCallback] = None
_plc_event_callback: Optional[PLCEventCallback] = None 
_asyncio_loop: Optional[asyncio.AbstractEventLoop] = None
_previous_event_value: Optional[int] = None
_event_initialized = False

def set_asyncio_loop(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """
    Сохранить основной asyncio event loop.

    MQTT работает в отдельном потоке, поэтому
    asyncio.get_running_loop() внутри MQTT callback
    использовать нельзя.
    """
    global _asyncio_loop

    _asyncio_loop = loop

    logger.info(
        "Основной asyncio event loop зарегистрирован"
    )

def _schedule_plc_event (
    event_id: int
) -> None:
    global _asyncio_loop

    if _asyncio_loop is None:
        logger.warning(
            "Не удалось отправить событие во фронт: "
            "asyncio loop не зарегистрирован"
        )
        return

    if _asyncio_loop.is_closed():
        logger.warning(
            "Не удалось отправить событие во фронт: "
            "asyncio loop закрыт"
        )
        return

    try:
        asyncio.run_coroutine_threadsafe(
            send_plc_event_to_front(
                event_id
            ),
            _asyncio_loop,
        )

    except Exception as e:
        logger.error(
            f"Ошибка постановки события во фронт: {e}",
            exc_info=True,
        )

def _schedule_front_event(
    event_id: int,
    payload: dict,
) -> None:
    """
    Безопасно отправить событие во фронт.

    Может вызываться как из asyncio-потока,
    так и из MQTT-потока.
    """

    global _asyncio_loop

    if _asyncio_loop is None:
        logger.warning(
            "Не удалось отправить событие во фронт: "
            "asyncio loop не зарегистрирован"
        )
        return

    if _asyncio_loop.is_closed():
        logger.warning(
            "Не удалось отправить событие во фронт: "
            "asyncio loop закрыт"
        )
        return

    try:
        asyncio.run_coroutine_threadsafe(
            send_event_to_front(
                event_id,
                payload,
            ),
            _asyncio_loop,
        )

    except Exception as e:
        logger.error(
            f"Ошибка постановки события во фронт: {e}",
            exc_info=True,
        )

def set_event_callback(callback: EventCallback) -> None:
    """
    Установить callback для отправки событий во фронт.
    """
    global _event_callback

    _event_callback = callback

    logger.info("Event callback для фронта установлен")

def set_plc_event_callback(callback: PLCEventCallback) -> None:
    """
    Установить callback для отправки событий во фронт.
    """
    global _plc_event_callback

    _plc_event_callback = callback

    logger.info("Event callback для фронта установлен")

async def send_plc_event_to_front(
    event_id: int
) -> None:
    if _plc_event_callback is None:
        logger.warning(
            f"Event callback не установлен, "
            f"событие {event_id} не отправлено"
        )
        return

    try:
        await _plc_event_callback(
            event_id
        )
    except Exception as e:
        logger.error(
            f"Ошибка при отправке события во фронт: {e}",
            exc_info=True,
        )

async def send_event_to_front(
    event_id: int,
    payload: Optional[dict] = None,
) -> None:
    """
    Отправить событие во фронт через WebSocket.
    """
    if _event_callback is None:
        logger.warning(
            f"Event callback не установлен, "
            f"событие {event_id} не отправлено"
        )
        return

    try:
        await _event_callback(
            event_id,
            payload or {},
        )
    except Exception as e:
        logger.error(
            f"Ошибка при отправке события во фронт: {e}",
            exc_info=True,
        )

# =====================================================================
# КЛАСС MODBUS-КЛИЕНТА
# =====================================================================

class ModbusManager:
    """
    Менеджер Modbus-соединения.

    Все операции записи выполняются последовательно через
    asyncio.Lock, чтобы несколько источников команд
    не обращались к одному Modbus TCP client одновременно.

    Важно:
    auto_close=False.

    Соединение не закрывается после каждого запроса.
    """

    def __init__(
        self,
        host: str = "192.168.0.100",
        port: int = 502,
    ):
        self.host = host
        self.port = port

        self.client = ModbusClient(
            host=host,
            port=port,
            auto_open=False,
            auto_close=False,
            timeout=1,
        )

        self._connected = False

        # Обычный threading.Lock здесь не нужен,
        # потому что команды записи выполняются через
        # async-обёртки ниже.
        #
        # Сам pyModbusTCP клиент синхронный, поэтому фактический
        # вызов выполняется в отдельном executor-потоке.
        self._io_lock = asyncio.Lock()

        # Защита состояния подключения.
        self._connection_lock = asyncio.Lock()

    # -----------------------------------------------------------------
    # CONNECTION
    # -----------------------------------------------------------------

    def _connect_sync(self) -> bool:
        """
        Синхронное подключение к Modbus.

        Выполняется в executor, чтобы не блокировать asyncio.
        """
        try:
            result = self.client.open()

            self._connected = bool(result)

            if self._connected:
                logger.info(
                    f"Modbus подключен к "
                    f"{self.host}:{self.port}"
                )
            else:
                logger.error(
                    f"Не удалось подключиться к ПЛК по Modbus "
                    f"{self.host}:{self.port}"
                )

            return self._connected

        except Exception as e:
            self._connected = False

            logger.error(
                f"Ошибка подключения Modbus: {e}",
                exc_info=True,
            )

            return False

    async def connect(self) -> bool:
        """
        Асинхронно установить соединение с ПЛК.
        """
        async with self._connection_lock:
            if self.client.is_open:
                self._connected = True
                return True

            loop = asyncio.get_running_loop()

            return await loop.run_in_executor(
                None,
                self._connect_sync,
            )

    def _disconnect_sync(self) -> None:
        """
        Синхронно закрыть Modbus-соединение.
        """
        try:
            self.client.close()
        except Exception as e:
            logger.warning(
                f"Ошибка закрытия Modbus соединения: {e}"
            )
        finally:
            self._connected = False

    async def disconnect(self) -> None:
        """
        Асинхронно закрыть соединение.
        """
        async with self._connection_lock:
            loop = asyncio.get_running_loop()

            await loop.run_in_executor(
                None,
                self._disconnect_sync,
            )

            logger.info("Modbus соединение закрыто")

    async def ensure_connected(self) -> bool:
        """
        Проверить реальное состояние соединения.

        Не полагаемся только на self._connected:
        проверяем client.is_open.
        """

        if self.client.is_open:
            self._connected = True
            return True

        self._connected = False

        logger.warning(
            "Modbus соединение закрыто. "
            "Выполняем reconnect..."
        )

        return await self.connect()

    # -----------------------------------------------------------------
    # SYNCHRONOUS IO
    # -----------------------------------------------------------------

    def _write_coil_sync(
        self,
        address: int,
        value: bool,
    ) -> bool:
        """
        Синхронная запись coil.
        """
        try:
            return bool(
                self.client.write_single_coil(
                    address,
                    value,
                )
            )

        except Exception as e:
            logger.error(
                f"Ошибка записи coil {address}: {e}",
                exc_info=True,
            )

            return False

    def _write_register_sync(
        self,
        address: int,
        value: int,
    ) -> bool:
        """
        Синхронная запись holding register.
        """
        try:
            return bool(
                self.client.write_single_register(
                    address,
                    value,
                )
            )

        except Exception as e:
            logger.error(
                f"Ошибка записи register {address}: {e}",
                exc_info=True,
            )

            return False

    def _read_holding_register_sync(
        self,
        address: int,
    ) -> Optional[int]:
        """
        Синхронное чтение holding register.
        """
        try:
            result = self.client.read_holding_registers(
                address,
                1,
            )

            if result and len(result) > 0:
                return result[0]

            return None

        except Exception as e:
            logger.error(
                f"Ошибка чтения holding register "
                f"{address}: {e}",
                exc_info=True,
            )

            return None

    def _read_input_register_sync(
        self,
        address: int,
    ) -> Optional[int]:
        """
        Синхронное чтение input register.
        """
        try:
            result = self.client.read_input_registers(
                address,
                1,
            )

            if result and len(result) > 0:
                return result[0]

            return None

        except Exception as e:
            logger.error(
                f"Ошибка чтения input register "
                f"{address}: {e}",
                exc_info=True,
            )

            return None

    def _read_discrete_input_sync(
        self,
        address: int,
    ) -> Optional[bool]:
        """
        Синхронное чтение discrete input.
        """
        try:
            result = self.client.read_discrete_inputs(
                address,
                1,
            )

            if result and len(result) > 0:
                return bool(result[0])

            return None

        except Exception as e:
            logger.error(
                f"Ошибка чтения discrete input "
                f"{address}: {e}",
                exc_info=True,
            )

            return None

    # -----------------------------------------------------------------
    # WRITE
    # -----------------------------------------------------------------

    async def write_coil(
        self,
        address: int,
        value: bool,
    ) -> bool:
        """
        Записать значение в coil.

        Запросы сериализуются через _io_lock.
        """
        async with self._io_lock:

            if not await self.ensure_connected():
                logger.error(
                    f"Modbus write coil {address}: "
                    f"нет соединения"
                )
                return False

            loop = asyncio.get_running_loop()

            try:
                result = await loop.run_in_executor(
                    None,
                    self._write_coil_sync,
                    address,
                    value,
                )

                logger.info(
                    f"MODBUS WRITE COIL | "
                    f"address={address} | "
                    f"value={value} | "
                    f"result={result}"
                )

                if result:
                    return True

                # Если запись вернула False,
                # считаем соединение потенциально потерянным.
                self._connected = False

                logger.warning(
                    f"MODBUS WRITE COIL FAILED | "
                    f"address={address} | "
                    f"value={value}"
                )

                # Пытаемся переподключиться один раз.
                if await self.connect():
                    logger.info(
                        f"Повторная попытка записи coil "
                        f"{address}"
                    )

                    result = await loop.run_in_executor(
                        None,
                        self._write_coil_sync,
                        address,
                        value,
                    )

                    logger.info(
                        f"MODBUS RETRY COIL | "
                        f"address={address} | "
                        f"value={value} | "
                        f"result={result}"
                    )

                    if result:
                        return True

                return False

            except Exception as e:
                self._connected = False

                logger.error(
                    f"Ошибка записи coil "
                    f"{address}: {e}",
                    exc_info=True,
                )

                return False

    async def write_register(
        self,
        address: int,
        value: int,
    ) -> bool:
        """
        Записать значение в holding register.
        """
        async with self._io_lock:

            if not await self.ensure_connected():
                logger.error(
                    f"Modbus write register {address}: "
                    f"нет соединения"
                )
                return False

            loop = asyncio.get_running_loop()

            try:
                result = await loop.run_in_executor(
                    None,
                    self._write_register_sync,
                    address,
                    value,
                )

                logger.info(
                    f"MODBUS WRITE REGISTER | "
                    f"address={address} | "
                    f"value={value} | "
                    f"result={result}"
                )

                if result:
                    return True

                self._connected = False

                logger.warning(
                    f"MODBUS WRITE REGISTER FAILED | "
                    f"address={address} | "
                    f"value={value}"
                )

                if await self.connect():
                    logger.info(
                        f"Повторная попытка записи register "
                        f"{address}"
                    )

                    result = await loop.run_in_executor(
                        None,
                        self._write_register_sync,
                        address,
                        value,
                    )

                    logger.info(
                        f"MODBUS RETRY REGISTER | "
                        f"address={address} | "
                        f"value={value} | "
                        f"result={result}"
                    )

                    if result:
                        return True

                return False

            except Exception as e:
                self._connected = False

                logger.error(
                    f"Ошибка записи register "
                    f"{address}: {e}",
                    exc_info=True,
                )

                return False

    # -----------------------------------------------------------------
    # READ
    # -----------------------------------------------------------------

    async def read_holding_register(
        self,
        address: int,
    ) -> Optional[int]:
        """
        Прочитать holding register.
        """
        async with self._io_lock:

            if not await self.ensure_connected():
                return None

            loop = asyncio.get_running_loop()

            try:
                return await loop.run_in_executor(
                    None,
                    self._read_holding_register_sync,
                    address,
                )

            except Exception as e:
                self._connected = False

                logger.error(
                    f"Ошибка чтения holding register "
                    f"{address}: {e}",
                    exc_info=True,
                )

                return None

    async def read_input_register(
        self,
        address: int,
    ) -> Optional[int]:
        """
        Прочитать input register.
        """
        async with self._io_lock:

            if not await self.ensure_connected():
                return None

            loop = asyncio.get_running_loop()

            try:
                return await loop.run_in_executor(
                    None,
                    self._read_input_register_sync,
                    address,
                )

            except Exception as e:
                self._connected = False

                logger.error(
                    f"Ошибка чтения input register "
                    f"{address}: {e}",
                    exc_info=True,
                )

                return None

    async def read_discrete_input(
        self,
        address: int,
    ) -> Optional[bool]:
        """
        Прочитать discrete input.
        """
        async with self._io_lock:

            if not await self.ensure_connected():
                return None

            loop = asyncio.get_running_loop()

            try:
                return await loop.run_in_executor(
                    None,
                    self._read_discrete_input_sync,
                    address,
                )

            except Exception as e:
                self._connected = False

                logger.error(
                    f"Ошибка чтения discrete input "
                    f"{address}: {e}",
                    exc_info=True,
                )

                return None

    # -----------------------------------------------------------------
    # STATUS
    # -----------------------------------------------------------------

    def is_connected(self) -> bool:
        """
        Проверить состояние Modbus TCP соединения.
        """
        return bool(
            self._connected
            and self.client.is_open
        )


# =====================================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР MODBUS-МЕНЕДЖЕРА
# =====================================================================

_modbus_manager: Optional[ModbusManager] = None


def init_modbus(
    host: str = "192.168.0.100",
    port: int = 502,
) -> bool:
    """
    Инициализировать Modbus-менеджер.

    Функция оставлена синхронной для совместимости
    с существующим кодом проекта.
    """
    global _modbus_manager

    _modbus_manager = ModbusManager(
        host,
        port,
    )

    # Первичное подключение синхронное.
    result = _modbus_manager._connect_sync()

    return result


async def init_modbus_async(
    host: str = "192.168.0.100",
    port: int = 502,
) -> bool:
    """
    Асинхронный вариант инициализации Modbus.
    """
    global _modbus_manager

    _modbus_manager = ModbusManager(
        host,
        port,
    )

    return await _modbus_manager.connect()


def get_modbus_manager() -> ModbusManager:
    """
    Получить экземпляр Modbus-менеджера.
    """
    if _modbus_manager is None:
        raise RuntimeError(
            "Modbus не инициализирован. "
            "Вызовите init_modbus()"
        )

    return _modbus_manager


# =====================================================================
# ОБРАБОТЧИКИ КОМАНД
# =====================================================================

# Хранилище состояний триггерных кнопок.
_trigger_states = {
    "hoist_up": False,
    "hoist_down": False,
    "pipe_hoist_up": False,
    "pipe_hoist_down": False,
}

_TRIGGER_OPPOSITES = {
    "hoist_up": "hoist_down",
    "hoist_down": "hoist_up",

    "pipe_hoist_up": "pipe_hoist_down",
    "pipe_hoist_down": "pipe_hoist_up",
}


async def _execute_coil_command(
    command_name: str,
    value: bool = True,
) -> bool:
    """
    Выполнить команду для катушки.
    """
    config = MODBUS_CONFIG["coils"]

    if command_name not in config:
        logger.error(
            f"Неизвестная команда: {command_name}"
        )
        return False

    address = config[command_name]

    manager = get_modbus_manager()

    logger.info(
        f"MODBUS COMMAND | "
        f"{command_name} -> coil={address}, "
        f"value={value}"
    )

    return await manager.write_coil(
        address,
        value,
    )


async def _toggle_trigger_command(
    command_name: str,
) -> bool:
    """
    Выполнить команду как триггер.

    При включении одного направления автоматически
    выключает противоположное направление.

    Например:
        pipe_hoist_up = True
        -> pipe_hoist_down = False

       и наоборот.

    Состояние обновляется только после успешной записи
    в ПЛК.
    """
    global _trigger_states

    if command_name not in _trigger_states:
        logger.error(
            f"Неизвестный trigger command: {command_name}"
        )
        return False

    current_state = _trigger_states[command_name]
    new_state = not current_state

    logger.info(
        f"Триггер {command_name}: "
        f"{current_state} -> {new_state}"
    )

    # -------------------------------------------------------------
    # Если мы ВКЛЮЧАЕМ направление —
    # сначала выключаем противоположное.
    # -------------------------------------------------------------

    if new_state:
        opposite_command = _TRIGGER_OPPOSITES.get(command_name)

        if opposite_command:
            opposite_state = _trigger_states.get(
                opposite_command,
                False,
            )

            if opposite_state:
                logger.info(
                    f"Выключаем противоположное направление: "
                    f"{opposite_command} -> False"
                )

                opposite_success = await _execute_coil_command(
                    opposite_command,
                    False,
                )

                if not opposite_success:
                    logger.error(
                        f"Не удалось выключить противоположное "
                        f"направление {opposite_command}. "
                        f"Команда {command_name} не выполняется."
                    )

                    return False

                _trigger_states[opposite_command] = False

                logger.info(
                    f"Противоположное направление "
                    f"{opposite_command} успешно выключено"
                )

    # -------------------------------------------------------------
    # Переключаем само направление
    # -------------------------------------------------------------

    success = await _execute_coil_command(
        command_name,
        new_state,
    )

    if success:
        _trigger_states[command_name] = new_state

        logger.info(
            f"Триггер {command_name} успешно изменён: "
            f"{new_state}"
        )

        return True

    logger.error(
        f"Не удалось отправить триггер "
        f"{command_name}, состояние остаётся "
        f"{current_state}"
    )

    return False


async def handle_zigbee_command(
    action: str,
    raw_payload: Optional[dict] = None,
) -> bool:
    """
    Обработать команду от Zigbee-пульта.

    Args:
        action:
            Действие с пульта.

        raw_payload:
            Оригинальный payload для отправки во фронт.

    Returns:
        True если команда выполнена успешно.
    """

    zigbee_trigger_map = {
        "brightness_step_up": "hoist_up",
        "brightness_step_down": "hoist_down",

        "color_temperature_step_down": "pipe_hoist_up",
        "color_temperature_step_up": "pipe_hoist_down",
    }

    zigbee_normal_map = {
        "on": ("procedure_start", True),
        "off": ("procedure_start", False),
    }

    event_payload = {
        "source": "zigbee",
        "action": action,
        "timestamp": time.time(),
    }

    logger.info(
        f"Zigbee команда: {action}"
    )

    # -------------------------------------------------------------
    # Обычная команда
    # -------------------------------------------------------------

    if action in zigbee_normal_map:

        command, value = zigbee_normal_map[action]

        logger.info(
            f"Zigbee -> Modbus: "
            f"{action} -> {command} = {value}"
        )

        success = await _execute_coil_command(
            command,
            value,
        )

        event_payload["command"] = command
        event_payload["value"] = value

    # -------------------------------------------------------------
    # Триггер
    # -------------------------------------------------------------

    elif action in zigbee_trigger_map:

        command = zigbee_trigger_map[action]

        logger.info(
            f"Zigbee триггер -> Modbus: "
            f"{action} -> {command}"
        )

        success = await _toggle_trigger_command(
            command
        )

        event_payload["command"] = command
        event_payload["new_state"] = (
            _trigger_states.get(
                command,
                False,
            )
        )

    # -------------------------------------------------------------
    # Неизвестная команда
    # -------------------------------------------------------------

    else:

        logger.warning(
            f"Неизвестное Zigbee действие: {action}"
        )

        return False

    # -------------------------------------------------------------
    # Отправляем событие во фронт
    # -------------------------------------------------------------

    if success:

        if raw_payload is not None:
            event_payload["payload"] = raw_payload

        # _schedule_front_event(
        #     1000,
        #     event_payload,
        # )

        logger.info(
            f"Zigbee команда успешно выполнена: "
            f"{event_payload}"
        )

    else:

        logger.error(
            f"Zigbee команда НЕ выполнена: "
            f"{event_payload}"
        )

    return success


async def reset_trigger_states() -> None:
    """
    Сбросить все триггерные состояния в False.
    """
    global _trigger_states

    for command in _trigger_states:

        if _trigger_states[command]:

            success = await _execute_coil_command(
                command,
                False,
            )

            if success:
                _trigger_states[command] = False

            else:
                logger.error(
                    f"Не удалось сбросить "
                    f"триггер {command}"
                )

        else:
            # Даже если внутреннее состояние False,
            # отправляем False в ПЛК при запуске,
            # чтобы синхронизировать состояние.
            await _execute_coil_command(
                command,
                False,
            )

            _trigger_states[command] = False

    logger.info(
        "Триггерные состояния сброшены"
    )


def get_trigger_state(
    command_name: str,
) -> bool:
    """
    Получить текущее состояние триггера.
    """
    return _trigger_states.get(
        command_name,
        False,
    )


# =====================================================================
# WEBSOCKET КОМАНДЫ
# =====================================================================

async def handle_web_socket_command(
    event: str,
    payload: dict,
) -> bool:
    """
    Обработать команду, пришедшую по WebSocket.
    """

    # -------------------------------------------------------------
    # machine_controls
    # -------------------------------------------------------------

    if event == "machine_controls":

        control_type = (
            payload.get("control_type")
            or payload.get("type")
        )

        value = bool(
            payload.get(
                "value",
                True,
            )
        )

        type_to_command = {
            "dry": (
                "dry_start"
                if value
                else "dry_stop"
            ),

            "procedure": (
                "procedure_start"
                if value
                else "procedure_stop"
            ),

            "cooling": (
                "cooling_start"
                if value
                else "cooling_stop"
            ),

            "hoist": (
                "hoist_up"
                if value
                else "hoist_down"
            ),

            "pipe_hoist": (
                "pipe_hoist_up"
                if value
                else "pipe_hoist_down"
            ),
        }

        if control_type not in type_to_command:

            logger.warning(
                f"Неизвестный control_type: "
                f"{control_type}"
            )

            return False

        command = type_to_command[control_type]

        logger.info(
            f"WS команда: {command} "
            f"(type={control_type}, "
            f"value={value})"
        )

        success = await _execute_coil_command(
            command,
            value,
        )

        if success:

            event_payload = {
                "source": "websocket",
                "event": event,
                "control_type": control_type,
                "value": value,
                "command": command,
                "timestamp": time.time(),
            }

            _schedule_front_event(
                1001,
                event_payload,
            )

        return success

    # -------------------------------------------------------------
    # Прямые команды
    # -------------------------------------------------------------

    command_map = {
        "dry_start": ("dry_start", True),
        "dry_stop": ("dry_stop", False),

        "procedure_start": (
            "procedure_start",
            True,
        ),

        "procedure_stop": (
            "procedure_stop",
            False,
        ),

        "cooling_start": (
            "cooling_start",
            True,
        ),

        "cooling_stop": (
            "cooling_stop",
            False,
        ),

        "hoist_up": ("hoist_up", True),
        "hoist_down": ("hoist_down", False),

        "pipe_hoist_up": (
            "pipe_hoist_up",
            True,
        ),

        "pipe_hoist_down": (
            "pipe_hoist_down",
            False,
        ),
    }

    if event in command_map:

        command, value = command_map[event]

        logger.info(
            f"WS команда: "
            f"{command} = {value}"
        )

        success = await _execute_coil_command(
            command,
            value,
        )

        if success:

            event_payload = {
                "source": "websocket",
                "event": event,
                "command": command,
                "value": value,
                "timestamp": time.time(),
            }

            _schedule_front_event(
                1001,
                event_payload,
            )

        return success

    logger.warning(
        f"Неизвестное WS событие: {event}"
    )

    return False


# =====================================================================
# ЧТЕНИЕ ДАННЫХ С ПЛК
# =====================================================================

async def _read_scaled_input_register(
    address: int,
    scale: float = 10.0,
) -> Optional[float]:
    """
    Прочитать входной регистр и масштабировать значение.
    """
    manager = get_modbus_manager()

    value = await manager.read_input_register(
        address
    )

    if value is not None:
        return round(
            (value - 16384) / scale,
            2,
        )

    return None


async def _read_boolean_discrete(
    address: int,
) -> bool:
    """
    Прочитать дискретный вход как bool.
    """
    manager = get_modbus_manager()

    value = await manager.read_discrete_input(
        address
    )

    return (
        value
        if value is not None
        else False
    )


async def _read_status_register(
    offset: int,
) -> int:
    """
    Прочитать статусный регистр (0-3).

    Базовый адрес: 200.
    """
    base_address = 200

    manager = get_modbus_manager()

    value = await manager.read_holding_register(
        base_address + offset
    )

    if value is not None and 0 <= value <= 3:
        return value

    return 0

def get_current_event_value() -> Optional[int]:
    """
    Получить текущее значение регистра событий.
    """
    return _previous_event_value

async def _read_input_register_raw(
    address: int,
) -> Optional[int]:
    """
    Прочитать входной регистр без масштабирования (сырое значение).
    """
    manager = get_modbus_manager()
    
    value = await manager.read_input_register(address)
    
    if value is not None:
        return value
    
    return None

async def read_plc_sensors_data() -> dict:
    """
    Прочитать данные датчиков с ПЛК.
    """

    inputs = MODBUS_CONFIG["input_registers"]
    global _event_initialized, _previous_event_value

    # -------------------------------------------------------------
    # Input Registers
    # -------------------------------------------------------------
    t1 = await _read_scaled_input_register(
        inputs["t1"]
    )

    t2 = await _read_scaled_input_register(
        inputs["t2"]
    )

    t3 = await _read_scaled_input_register(
        inputs["t3"]
    )

    print(t1, t2, t3)

    t4 = await _read_scaled_input_register(
        inputs["t4"]
    )

    humidity = await _read_scaled_input_register(
        inputs["humidity"]
    )

    oxygen = await _read_scaled_input_register(
        inputs["oxygen"]
    )

    nitrogen_mass = await _read_scaled_input_register(
        inputs["nitrogen_mass"]
    )

    event_value = await _read_input_register_raw(inputs["event"])

    # -------------------------------------------------------------
    # Discrete Inputs
    # -------------------------------------------------------------

    discrete = MODBUS_CONFIG["discrete_inputs"]

    pipe_top_emergency = await _read_boolean_discrete(
        discrete["lsw_top_emergency_pipe"]
    )

    pipe_top_working = await _read_boolean_discrete(
        discrete["lsw_top_working_pipe"]
    )

    pipe_bottom_working = await _read_boolean_discrete(
        discrete["lsw_bottom_working_pipe"]
    )

    pipe_bottom_emergency = await _read_boolean_discrete(
        discrete["lsw_bottom_emergency_pipe"]
    )

    patient_top_emergency = await _read_boolean_discrete(
        discrete["lsw_top_emergency_patient"]
    )

    patient_top_working = await _read_boolean_discrete(
        discrete["lsw_top_working_patient"]
    )

    patient_bottom_working = await _read_boolean_discrete(
        discrete["lsw_bottom_working_patient"]
    )

    patient_bottom_emergency = await _read_boolean_discrete(
        discrete["lsw_bottom_emergency_patient"]
    )

    patient_present = await _read_boolean_discrete(
        discrete["patient_present"]
    )

    estop_pressed = await _read_boolean_discrete(
        discrete["estop_pressed"]
    )

    cabinet_door_open = await _read_boolean_discrete(
        discrete["cabinet_door_open"]
    )

    # -------------------------------------------------------------
    # Status Registers
    # -------------------------------------------------------------

    patient_hoist_status = await _read_status_register(1)
    pipe_hoist_status = await _read_status_register(2)
    steam_status = await _read_status_register(3)
    charger_status = await _read_status_register(4)
    heater_status = await _read_status_register(5)
    exhaust_status = await _read_status_register(6)

    if event_value is not None:
        
        # Если инициализация ещё не выполнена или значение изменилось
        if not _event_initialized or _previous_event_value != event_value:
            _event_initialized = True
            _previous_event_value = event_value
            
            print(event_value)
            _schedule_plc_event(event_value)
            
            logger.info(f"Новое событие от ПЛК: event_id={event_value}")
    else:
        logger.warning("Не удалось прочитать регистр событий")

    # -------------------------------------------------------------
    # Формируем структуру
    # -------------------------------------------------------------

    return {
        "digital_inputs": {
            "pipe_hoist": {
                "lsw_top_emergency": pipe_top_emergency,
                "lsw_top_working": pipe_top_working,
                "lsw_bottom_working": pipe_bottom_working,
                "lsw_bottom_emergency": pipe_bottom_emergency,
            },

            "patient_hoist": {
                "lsw_top_emergency": patient_top_emergency,
                "lsw_top_working": patient_top_working,
                "lsw_bottom_working": patient_bottom_working,
                "lsw_bottom_emergency": patient_bottom_emergency,
                "patient_present": patient_present,
            },

            "safety": {
                "estop_pressed": estop_pressed,
                "cabinet_door_open": cabinet_door_open,
            },
        },

        "stats": {
            "patient_hoist": patient_hoist_status,
            "pipe_hoist": pipe_hoist_status,
            "steam": steam_status,
            "charger": charger_status,
            "heater": heater_status,
            "exhaust": exhaust_status,
        },

        "sensor_data": {
            "t1": (
                t1
                if t1 is not None
                else 0.0
            ),

            "t2": (
                t2
                if t2 is not None
                else 0.0
            ),

            "t3": (
                t3
                if t3 is not None
                else 0.0
            ),

            "t4": (
                t4
                if t4 is not None
                else 0.0
            ),

            "humidity": (
                humidity
                if humidity is not None
                else 0.0
            ),

            "oxygen": (
                oxygen
                if oxygen is not None
                else 0.0
            ),

            "nitrogen_mass": (
                nitrogen_mass
                if nitrogen_mass is not None
                else 0.0
            ),
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
# ИНИЦИАЛИЗАЦИЯ ZIGBEE (MQTT)
# =====================================================================

_zigbee_client: Optional[mqtt.Client] = None
_zigbee_connected = False


def init_zigbee_mqtt(
    broker: str = "localhost",
    port: int = 1883,
    topic: str = "zigbee2mqtt/0x7cc6b6fffeab1b60",
) -> bool:
    """
    Инициализировать MQTT-клиент для Zigbee.
    """

    global _zigbee_client
    global _zigbee_connected

    # -------------------------------------------------------------
    # Сброс триггерных состояний
    # -------------------------------------------------------------

    #
    # ВАЖНО:
    #
    # init_zigbee_mqtt() может вызываться до запуска asyncio.
    # Поэтому здесь нельзя делать await.
    #
    # Сброс будет выполнен ниже через create_task,
    # если event loop уже существует.
    #
    try:
        loop = asyncio.get_running_loop()

        loop.create_task(
            reset_trigger_states()
        )

    except RuntimeError:
        logger.warning(
            "Нет активного asyncio loop. "
            "Сброс trigger states при старте "
            "не выполнен автоматически."
        )

    # -------------------------------------------------------------
    # MQTT callbacks
    # -------------------------------------------------------------

    def on_connect(
        client: mqtt.Client,
        userdata: Any,
        flags: dict,
        rc: int,
        properties: Any = None,
    ):
        global _zigbee_connected

        if rc == 0:

            _zigbee_connected = True

            logger.info(
                f"Zigbee MQTT подключен к брокеру "
                f"{broker}:{port}"
            )

            try:
                client.subscribe(topic)

                logger.info(
                    f"Zigbee подписан на топик: "
                    f"{topic}"
                )

            except Exception as e:

                logger.error(
                    f"Ошибка подписки Zigbee "
                    f"на {topic}: {e}",
                    exc_info=True,
                )

        else:

            _zigbee_connected = False

            logger.error(
                f"Zigbee MQTT ошибка подключения: "
                f"{rc}"
            )

    def on_disconnect(
        client: mqtt.Client,
        userdata: Any,
        rc: int,
        properties: Any = None,
    ):
        global _zigbee_connected

        _zigbee_connected = False

        logger.warning(
            f"Zigbee MQTT отключен от брокера "
            f"(rc={rc})"
        )

    def on_message(
        client: mqtt.Client,
        userdata: Any,
        msg: mqtt.MQTTMessage,
    ):
        """
        MQTT callback.

        ВАЖНО:
        Здесь не выполняем async handler напрямую.

        Создаём asyncio task, чтобы MQTT callback
        не блокировался на Modbus TCP.
        """

        try:

            payload_str = msg.payload.decode(
                "utf-8",
                errors="replace",
            )

            logger.debug(
                f"Zigbee получено сообщение: "
                f"{payload_str}"
            )

            payload = json.loads(
                payload_str
            )

            action = payload.get("action")

            if not action:
                action = (
                    payload.get("click")
                    or payload.get("button")
                )

            if not action:

                logger.debug(
                    f"Zigbee сообщение без action: "
                    f"{payload}"
                )

                return

            logger.info(
                f"Zigbee получена команда: "
                f"{action} "
                f"(payload: {payload})"
            )

            # -----------------------------------------------------
            # Передаём обработку в asyncio.
            # -----------------------------------------------------

            global _asyncio_loop

            if _asyncio_loop is None:
                logger.error(
                    "Не удалось обработать Zigbee команду: "
                    "asyncio loop не зарегистрирован"
                )
                return

            if _asyncio_loop.is_closed():
                logger.error(
                    "Не удалось обработать Zigbee команду: "
                    "asyncio loop закрыт"
                )
                return

            try:
                future = asyncio.run_coroutine_threadsafe(
                    handle_zigbee_command(
                        action,
                        payload,
                    ),
                    _asyncio_loop,
                )

                def on_command_done(f):
                    try:
                        result = f.result()

                        if result:
                            logger.info(
                                f"Zigbee команда {action} "
                                f"успешно выполнена"
                            )
                        else:
                            logger.error(
                                f"Zigbee команда {action} "
                                f"НЕ выполнена"
                            )

                    except Exception as e:
                        logger.error(
                            f"Ошибка выполнения Zigbee команды "
                            f"{action}: {e}",
                            exc_info=True,
                        )

                future.add_done_callback(on_command_done)

            except Exception as e:
                logger.error(
                    f"Ошибка передачи Zigbee команды "
                    f"в asyncio: {e}",
                    exc_info=True,
                )

        except json.JSONDecodeError as e:

            logger.error(
                f"Zigbee ошибка парсинга JSON: "
                f"{e}, данные={msg.payload!r}"
            )

        except Exception as e:

            logger.error(
                f"Zigbee ошибка обработки: {e}",
                exc_info=True,
            )

    # -------------------------------------------------------------
    # Создание MQTT client
    # -------------------------------------------------------------

    try:

        _zigbee_client = mqtt.Client(
            protocol=mqtt.MQTTv311
        )

        _zigbee_client.on_connect = on_connect
        _zigbee_client.on_disconnect = on_disconnect
        _zigbee_client.on_message = on_message

        _zigbee_client.connect(
            broker,
            port,
            keepalive=60,
        )

        _zigbee_client.loop_start()

        # ---------------------------------------------------------
        # Ждём подключения максимум 5 секунд.
        # ---------------------------------------------------------

        for _ in range(50):

            if _zigbee_connected:
                break

            time.sleep(0.1)

        if _zigbee_connected:

            logger.info(
                f"Zigbee MQTT успешно запущен: "
                f"{broker}:{port}, "
                f"топик: {topic}"
            )

            return True

        logger.warning(
            "Zigbee MQTT подключился, "
            "но не получил подтверждение"
        )

        return True

    except Exception as e:

        logger.error(
            f"Не удалось подключить "
            f"Zigbee MQTT. 1758 строка",
            exc_info=True,
        )

        return False


def stop_zigbee_mqtt():
    """
    Остановить Zigbee MQTT клиент.
    """

    global _zigbee_client
    global _zigbee_connected

    if _zigbee_client:

        try:
            _zigbee_client.loop_stop()

        except Exception as e:
            logger.warning(
                f"Ошибка остановки MQTT loop: {e}"
            )

        try:
            _zigbee_client.disconnect()

        except Exception as e:
            logger.warning(
                f"Ошибка отключения MQTT: {e}"
            )

        _zigbee_client = None
        _zigbee_connected = False

        logger.info(
            "Zigbee MQTT остановлен"
        )


def is_zigbee_connected() -> bool:
    """
    Проверить состояние подключения Zigbee.
    """
    return _zigbee_connected