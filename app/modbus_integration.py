"""
Модуль интеграции Modbus для управления вентиляционной установкой.
Обрабатывает команды от Zigbee и WebSocket, отправляя их на ПЛК по Modbus.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from pyModbusTCP.client import ModbusClient
import paho.mqtt.client as mqtt

logger = logging.getLogger("vent_backend.modbus")

# =====================================================================
# КОНФИГУРАЦИЯ MODBUS АДРЕСОВ (настраиваемые)
# =====================================================================
MODBUS_CONFIG = {
    # Адреса катушек (Coils) - для включения/выключения
    "coils": {
        "dry_start": 0,           # Старт сушки
        "dry_stop": 1,            # Стоп сушки
        "procedure_start": 2,     # Старт процедуры
        "procedure_stop": 3,      # Стоп процедуры
        "cooling_start": 804,       # Старт прохлаживания
        "cooling_stop": 805,        # Стоп прохлаживания
        "hoist_up": 4,            # Лебёдка вверх
        "hoist_down": 5,          # Лебёдка вниз
        "pipe_hoist_up": 6,       # Трубоподъемник вверх
        "pipe_hoist_down": 7,     # Трубоподъемник вниз
        "buzzer": 810,              # Буззер
    },
    # Адреса регистров хранения (Holding Registers) - для числовых значений
    "registers": {
        "steam_speed": 100,         # Скорость пара (0-50)
        "temperature_sp1": 101,     # Уставка температуры S1
        "temperature_sp2": 102,     # Уставка температуры S2
        "time_s1": 103,             # Время работы S1
        "time_s2": 104,             # Время ожидания S2
        "time_s3": 0,             # Общая длительность процедуры
    },
    # Адреса входных регистров (Input Registers) - для чтения данных
    "input_registers": {
        "t1": 0,
        "t2": 2,
        "t3": 4,
        "t4": 303,
        "humidity": 304,
        "oxygen": 305,
        "nitrogen_mass": 306,
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
    }
}

# =====================================================================
# КЛАСС MODBUS-КЛИЕНТА
# =====================================================================
class ModbusManager:
    """Менеджер Modbus-соединений."""
    
    def __init__(self, host: str = "192.168.0.100", port: int = 502):
        self.host = host
        self.port = port
        self.client = ModbusClient(host=host, port=port, auto_open=True, auto_close=True)
        self._connected = False
        
    def connect(self) -> bool:
        """Установить соединение с ПЛК."""
        try:
            self._connected = self.client.open()
            if self._connected:
                logger.info(f"Modbus подключен к {self.host}:{self.port}")
            else:
                logger.error("Не удалось подключиться к ПЛК по Modbus")
            return self._connected
        except Exception as e:
            logger.error(f"Ошибка подключения Modbus: {e}")
            return False
    
    def disconnect(self):
        """Закрыть соединение с ПЛК."""
        if self.client:
            self.client.close()
            self._connected = False
            logger.info("Modbus соединение закрыто")
    
    def ensure_connected(self) -> bool:
        """Проверить соединение и переподключить при необходимости."""
        if not self._connected:
            return self.connect()
        return True
    
    def write_coil(self, address: int, value: bool) -> bool:
        """Записать значение в катушку (Coil)."""
        if not self.ensure_connected():
            return False
        try:
            result = self.client.write_single_coil(address, value)
            if result:
                logger.debug(f"Modbus write coil {address}: {value}")
            return result
        except Exception as e:
            logger.error(f"Ошибка записи coil {address}: {e}")
            return False
    
    def write_register(self, address: int, value: int) -> bool:
        """Записать значение в регистр хранения (Holding Register)."""
        if not self.ensure_connected():
            return False
        try:
            result = self.client.write_single_register(address, value)
            if result:
                logger.debug(f"Modbus write register {address}: {value}")
            return result
        except Exception as e:
            logger.error(f"Ошибка записи register {address}: {e}")
            return False
    
    def read_holding_register(self, address: int) -> Optional[int]:
        """Прочитать значение из регистра хранения (Holding Register)."""
        if not self.ensure_connected():
            return None
        try:
            result = self.client.read_holding_registers(address, 1)
            if result and len(result) > 0:
                return result[0]
            return None
        except Exception as e:
            logger.error(f"Ошибка чтения holding register {address}: {e}")
            return None
    
    def read_input_register(self, address: int) -> Optional[int]:
        """Прочитать значение из входного регистра (Input Register)."""
        if not self.ensure_connected():
            return None
        try:
            result = self.client.read_input_registers(address, 1)
            if result and len(result) > 0:
                return result[0]
            return None
        except Exception as e:
            logger.error(f"Ошибка чтения input register {address}: {e}")
            return None
    
    def read_discrete_input(self, address: int) -> Optional[bool]:
        """Прочитать значение дискретного входа (Discrete Input)."""
        if not self.ensure_connected():
            return None
        try:
            result = self.client.read_discrete_inputs(address, 1)
            if result and len(result) > 0:
                return result[0]
            return None
        except Exception as e:
            logger.error(f"Ошибка чтения discrete input {address}: {e}")
            return None


# =====================================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР MODBUS-МЕНЕДЖЕРА
# =====================================================================
_modbus_manager: Optional[ModbusManager] = None

def init_modbus(host: str = "192.168.0.100", port: int = 502) -> bool:
    """Инициализировать Modbus-менеджер."""
    global _modbus_manager
    _modbus_manager = ModbusManager(host, port)
    return _modbus_manager.connect()

def get_modbus_manager() -> ModbusManager:
    """Получить экземпляр Modbus-менеджера."""
    if _modbus_manager is None:
        raise RuntimeError("Modbus не инициализирован. Вызовите init_modbus()")
    return _modbus_manager


# =====================================================================
# ОБРАБОТЧИКИ КОМАНД
# =====================================================================

# Хранилище состояний для триггерных кнопок
_trigger_states = {
    "hoist_up": False,
    "hoist_down": False,
    "pipe_hoist_up": False,
    "pipe_hoist_down": False,
}

async def handle_web_socket_command(event: str, payload: dict) -> bool:
    """
    Обработать команду, пришедшую по WebSocket.
    
    Args:
        event: Имя события из WebSocket
        payload: Данные события
    
    Returns:
        True если команда выполнена успешно
    """
    # Обработка machine_controls
    if event == "machine_controls":
        control_type = payload.get("control_type") or payload.get("type")
        value = payload.get("value", True)
        
        # Маппинг control_type -> команда
        type_to_command = {
            "dry": "dry_start" if value else "dry_stop",
            "procedure": "procedure_start" if value else "procedure_stop",
            "cooling": "cooling_start" if value else "cooling_stop",
            "hoist": "hoist_up" if value else "hoist_down",
            "pipe_hoist": "pipe_hoist_up" if value else "pipe_hoist_down",
        }
        
        if control_type in type_to_command:
            command = type_to_command[control_type]
            logger.info(f"WS команда: {command} (type={control_type}, value={value})")
            return _execute_coil_command(command, value)
        else:
            logger.warning(f"Неизвестный control_type: {control_type}")
            return False
    
    # Прямые команды
    command_map = {
        "dry_start": ("dry_start", True),
        "dry_stop": ("dry_stop", False),
        "procedure_start": ("procedure_start", True),
        "procedure_stop": ("procedure_stop", False),
        "cooling_start": ("cooling_start", True),
        "cooling_stop": ("cooling_stop", False),
        "hoist_up": ("hoist_up", True),
        "hoist_down": ("hoist_down", False),
        "pipe_hoist_up": ("pipe_hoist_up", True),
        "pipe_hoist_down": ("pipe_hoist_down", False),
    }
    
    if event in command_map:
        command, value = command_map[event]
        logger.info(f"WS команда: {command}")
        return _execute_coil_command(command, value)
    
    logger.warning(f"Неизвестное WS событие: {event}")
    return False

def _execute_coil_command(command_name: str, value: bool = True) -> bool:
    """Выполнить команду для катушки (включить/выключить)."""
    config = MODBUS_CONFIG["coils"]
    if command_name not in config:
        logger.error(f"Неизвестная команда: {command_name}")
        return False
    
    address = config[command_name]
    manager = get_modbus_manager()
    return manager.write_coil(address, value)


def _toggle_trigger_command(command_name: str) -> bool:
    """
    Выполнить команду как триггер - переключить состояние.
    Возвращает новое состояние.
    """
    global _trigger_states
    
    # Инвертируем состояние
    current_state = _trigger_states.get(command_name, False)
    new_state = not current_state
    _trigger_states[command_name] = new_state
    
    logger.info(f"Триггер {command_name}: {current_state} -> {new_state}")
    
    # Отправляем новое состояние в Modbus
    success = _execute_coil_command(command_name, new_state)
    
    # Если не удалось отправить, возвращаем состояние обратно
    if not success:
        _trigger_states[command_name] = current_state
        logger.error(f"Не удалось отправить триггер {command_name}")
    
    return success


def handle_zigbee_command(action: str) -> bool:
    """
    Обработать команду от Zigbee пульта.
    
    Args:
        action: Действие с пульта (on, off, brightness_step_up, brightness_step_down)
    
    Returns:
        True если команда выполнена успешно
    """
    # Маппинг Zigbee действий на команды Modbus
    # Для кнопок с триггерным режимом
    zigbee_trigger_map = {
        "brightness_step_up": "hoist_up",
        "brightness_step_down": "hoist_down",
        "color_temperature_step_down": "pipe_hoist_up",
        "color_temperature_step_up": "pipe_hoist_down",
    }
    
    # Для кнопок с обычным режимом (on/off)
    zigbee_normal_map = {
        "on": ("procedure_start", True),
        "off": ("procedure_stop", False),
    }
    
    if action in zigbee_normal_map:
        command, value = zigbee_normal_map[action]
        logger.info(f"Zigbee команда: {action} -> {command} = {value}")
        return _execute_coil_command(command, value)
    
    elif action in zigbee_trigger_map:
        command = zigbee_trigger_map[action]
        logger.info(f"Zigbee триггер: {action} -> {command}")
        return _toggle_trigger_command(command)
    
    else:
        logger.warning(f"Неизвестное Zigbee действие: {action}")
        return False


def reset_trigger_states():
    """
    Сбросить все триггерные состояния в False.
    Можно вызывать при старте или по необходимости.
    """
    global _trigger_states
    for command in _trigger_states:
        _trigger_states[command] = False
        _execute_coil_command(command, False)
    logger.info("Триггерные состояния сброшены")


def get_trigger_state(command_name: str) -> bool:
    """Получить текущее состояние триггера."""
    return _trigger_states.get(command_name, False)


# =====================================================================
# ЧТЕНИЕ ДАННЫХ С ПЛК
# =====================================================================
def _read_scaled_input_register(address: int, scale: float = 10.0) -> Optional[float]:
    """Прочитать входной регистр и масштабировать значение."""
    manager = get_modbus_manager()
    value = manager.read_input_register(address)
    if value is not None:
        return round(value / scale, 2)
    return None


def _read_boolean_discrete(address: int) -> bool:
    """Прочитать дискретный вход как булево значение."""
    manager = get_modbus_manager()
    value = manager.read_discrete_input(address)
    return value if value is not None else False


async def read_plc_sensors_data() -> dict:
    """
    Прочитать данные датчиков с ПЛК.
    """
    manager = get_modbus_manager()
    
    # Чтение входных регистров
    t1 = _read_scaled_input_register(MODBUS_CONFIG["input_registers"]["t1"])
    t2 = _read_scaled_input_register(MODBUS_CONFIG["input_registers"]["t2"])
    t3 = _read_scaled_input_register(MODBUS_CONFIG["input_registers"]["t3"])
    t4 = _read_scaled_input_register(MODBUS_CONFIG["input_registers"]["t4"])
    humidity = _read_scaled_input_register(MODBUS_CONFIG["input_registers"]["humidity"])
    oxygen = _read_scaled_input_register(MODBUS_CONFIG["input_registers"]["oxygen"])
    nitrogen_mass = _read_scaled_input_register(MODBUS_CONFIG["input_registers"]["nitrogen_mass"])
    
    # Чтение дискретных входов
    inputs = MODBUS_CONFIG["discrete_inputs"]
    pipe_top_emergency = _read_boolean_discrete(inputs["lsw_top_emergency_pipe"])
    pipe_top_working = _read_boolean_discrete(inputs["lsw_top_working_pipe"])
    pipe_bottom_working = _read_boolean_discrete(inputs["lsw_bottom_working_pipe"])
    pipe_bottom_emergency = _read_boolean_discrete(inputs["lsw_bottom_emergency_pipe"])
    
    patient_top_emergency = _read_boolean_discrete(inputs["lsw_top_emergency_patient"])
    patient_top_working = _read_boolean_discrete(inputs["lsw_top_working_patient"])
    patient_bottom_working = _read_boolean_discrete(inputs["lsw_bottom_working_patient"])
    patient_bottom_emergency = _read_boolean_discrete(inputs["lsw_bottom_emergency_patient"])
    patient_present = _read_boolean_discrete(inputs["patient_present"])
    
    estop_pressed = _read_boolean_discrete(inputs["estop_pressed"])
    cabinet_door_open = _read_boolean_discrete(inputs["cabinet_door_open"])
    
    # Формируем структуру данных
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
            "patient_hoist": _read_status_register(1),
            "pipe_hoist": _read_status_register(2),
            "steam": _read_status_register(3),
            "charger": _read_status_register(4),
            "heater": _read_status_register(5),
            "exhaust": _read_status_register(6),
        },
        "sensor_data": {
            "t1": t1 if t1 is not None else 0.0,
            "t2": t2 if t2 is not None else 0.0,
            "t3": t3 if t3 is not None else 0.0,
            "t4": t4 if t4 is not None else 0.0,
            "humidity": humidity if humidity is not None else 0.0,
            "oxygen": oxygen if oxygen is not None else 0.0,
            "nitrogen_mass": nitrogen_mass,
        },
        "diagnostics": {
            "test": {
                "running": False,
                "type": None,
                "stage": None,
            }
        },
    }


def _read_status_register(offset: int) -> int:
    """Прочитать статусный регистр (0-3)."""
    base_address = 200  # Базовый адрес регистров статуса
    manager = get_modbus_manager()
    value = manager.read_holding_register(base_address + offset)
    if value is not None and 0 <= value <= 3:
        return value
    return 0


# =====================================================================
# ИНИЦИАЛИЗАЦИЯ ZIGBEE (MQTT)
# =====================================================================
_zigbee_client: Optional[mqtt.Client] = None
_zigbee_connected = False

def init_zigbee_mqtt(broker: str = "localhost", port: int = 1883, 
                     topic: str = "zigbee2mqtt/0x7cc6b6fffeab1b60") -> bool:
    """Инициализировать MQTT-клиент для Zigbee."""
    global _zigbee_client, _zigbee_connected
    
    # Сброс триггерных состояний при старте
    reset_trigger_states()
    
    def on_connect(client, userdata, flags, rc):
        global _zigbee_connected
        if rc == 0:
            _zigbee_connected = True
            logger.info(f"Zigbee MQTT подключен к брокеру {broker}:{port}")
            client.subscribe(topic)
            logger.info(f"Zigbee подписан на топик: {topic}")
        else:
            _zigbee_connected = False
            logger.error(f"Zigbee MQTT ошибка подключения: {rc}")
    
    def on_disconnect(client, userdata, rc):
        global _zigbee_connected
        _zigbee_connected = False
        logger.warning("Zigbee MQTT отключен от брокера")
    
    def on_message(client, userdata, msg):
        try:
            # Парсим JSON
            payload_str = msg.payload.decode()
            logger.debug(f"Zigbee получено сообщение: {payload_str}")
            payload = json.loads(payload_str)
            
            # Получаем action из payload
            action = payload.get("action")
            
            # Также проверяем другие возможные поля
            if not action:
                # Для некоторых устройств может быть поле "click" или "button"
                action = payload.get("click") or payload.get("button")
            
            if action:
                logger.info(f"Zigbee получена команда: {action} (payload: {payload})")
                # Вызываем обработчик Zigbee команд
                success = handle_zigbee_command(action)
                if success:
                    logger.info(f"Zigbee команда {action} успешно выполнена")
                else:
                    logger.error(f"Zigbee команда {action} не выполнена")
            else:
                logger.debug(f"Zigbee сообщение без action: {payload}")
                
        except json.JSONDecodeError as e:
            logger.error(f"Zigbee ошибка парсинга JSON: {e}, данные: {msg.payload}")
        except Exception as e:
            logger.error(f"Zigbee ошибка обработки: {e}")
    
    try:
        # Создаем клиент с явным указанием protocol version
        _zigbee_client = mqtt.Client(protocol=mqtt.MQTTv311)
        _zigbee_client.on_connect = on_connect
        _zigbee_client.on_disconnect = on_disconnect
        _zigbee_client.on_message = on_message
        
        # Устанавливаем таймауты
        _zigbee_client.connect(broker, port, keepalive=60)
        
        # Запускаем цикл в отдельном потоке
        _zigbee_client.loop_start()
        
        # Ждем подключения (максимум 5 секунд)
        import time
        for _ in range(50):
            if _zigbee_connected:
                break
            time.sleep(0.1)
        
        if _zigbee_connected:
            logger.info(f"Zigbee MQTT успешно запущен: {broker}:{port}, топик: {topic}")
            return True
        else:
            logger.warning("Zigbee MQTT подключился, но не получил подтверждение")
            return True  # Все равно возвращаем True, т.к. клиент запущен
            
    except Exception as e:
        logger.error(f"Не удалось подключить Zigbee MQTT: {e}")
        return False


def stop_zigbee_mqtt():
    """Остановить Zigbee MQTT клиент."""
    global _zigbee_client, _zigbee_connected
    if _zigbee_client:
        _zigbee_client.loop_stop()
        _zigbee_client.disconnect()
        _zigbee_client = None
        _zigbee_connected = False
        logger.info("Zigbee MQTT остановлен")


def is_zigbee_connected() -> bool:
    """Проверить состояние подключения Zigbee."""
    return _zigbee_connected