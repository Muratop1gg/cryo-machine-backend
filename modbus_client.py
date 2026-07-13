import asyncio
import struct
import logging
from typing import Optional
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

logger = logging.getLogger(__name__)


class ModbusRegisterMap:
    """Карта регистров ПЛК — единая точка истины"""
    # (start_address, count, type)
    # type: 'u16' = uint16, 'i16' = int16, 'f32' = float32, 'bits' = битовое поле
    
    SYSTEM_STATUS = (0, 12, 'u16')      # Блок 1
    TEMPERATURES = (20, 10, 'f32')      # Блок 2
    ENVIRONMENT = (40, 8, 'f32')        # Блок 3
    VFD_STATUS = (60, 8, 'mixed')       # Блок 4 (f32 + u16)
    STATS = (80, 6, 'u16')              # Блок 5
    LIMIT_SWITCHES = (100, 3, 'bits')   # Блок 6
    
    # Быстрые блоки (опрашиваются часто)
    FAST_BLOCKS = ['SYSTEM_STATUS', 'LIMIT_SWITCHES', 'STATS', 'VFD_STATUS']
    # Медленные блоки (опрашиваются реже)
    SLOW_BLOCKS = ['TEMPERATURES', 'ENVIRONMENT']


class ModbusMasterClient:
    def __init__(self, host: str, port: int, unit_id: int = 1):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.client = AsyncModbusTcpClient(host=host, port=port, timeout=3)
        self.is_connected = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 30.0

    async def connect(self) -> bool:
        try:
            connected = await self.client.connect()
            if connected and self.client.connected:
                self.is_connected = True
                self._reconnect_delay = 1.0
                logger.info(f"✅ Modbus connected to {self.host}:{self.port}")
                return True
            logger.error("❌ Modbus connection failed")
            return False
        except Exception as e:
            logger.error(f"❌ Modbus connection error: {e}")
            return False

    async def _ensure_connected(self) -> bool:
        if not self.is_connected or not self.client.connected:
            return await self.connect()
        return True

    async def read_block(self, name: str) -> Optional[list]:
        """Чтение блока регистров по имени из карты"""
        if not await self._ensure_connected():
            return None
        
        start, count, dtype = getattr(ModbusRegisterMap, name)
        
        try:
            result = await self.client.read_holding_registers(
                address=start, count=count, slave=self.unit_id
            )
            if result.isError():
                logger.warning(f"Modbus read error [{name}]: {result}")
                return None
            return self._decode_registers(result.registers, dtype, count)
        except ModbusException as e:
            logger.error(f"Modbus exception [{name}]: {e}")
            self.is_connected = False
            return None
        except Exception as e:
            logger.error(f"Unexpected error [{name}]: {e}")
            return None

    def _decode_registers(self, registers: list[int], dtype: str, count: int) -> list:
        """Декодирование регистров в нужный тип данных"""
        if dtype == 'u16':
            return registers
        elif dtype == 'i16':
            # Знаковое преобразование
            return [r - 0x10000 if r >= 0x8000 else r for r in registers]
        elif dtype == 'f32':
            # Float32 = 2 регистра (Big Endian, word order AB CD)
            floats = []
            for i in range(0, len(registers), 2):
                if i + 1 < len(registers):
                    # Упаковываем 2 uint16 в 4 байта и распаковываем как float32
                    raw_bytes = struct.pack('>HH', registers[i], registers[i+1])
                    value = struct.unpack('>f', raw_bytes)[0]
                    floats.append(value)
            return floats
        elif dtype == 'bits':
            return registers  # Возвращаем как есть, биты распакуем позже
        elif dtype == 'mixed':
            return registers  # Специальная обработка для VFD
        return registers

    async def write_register(self, address: int, value: int) -> bool:
        """Запись одного регистра (для команд)"""
        if not await self._ensure_connected():
            return False
        try:
            result = await self.client.write_register(
                address=address, value=value, slave=self.unit_id
            )
            return not result.isError()
        except ModbusException as e:
            logger.error(f"Modbus write error at {address}: {e}")
            return False

    async def write_registers(self, address: int, values: list[int]) -> bool:
        """Запись нескольких регистров"""
        if not await self._ensure_connected():
            return False
        try:
            result = await self.client.write_registers(
                address=address, values=values, slave=self.unit_id
            )
            return not result.isError()
        except ModbusException as e:
            logger.error(f"Modbus write error at {address}: {e}")
            return False

    async def disconnect(self):
        self.client.close()
        self.is_connected = False
        logger.info("🔌 Modbus disconnected")


# --- Парсер сырых данных в Pydantic-модели ---
class ModbusDataParser:
    """Преобразует сырые регистры в структурированные модели"""
    
    @staticmethod
    def parse_system_status(regs: list[int]) -> dict:
        if not regs or len(regs) < 12:
            return {}
        
        mode_map = {0: "standby", 1: "autotest", 2: "drying", 3: "cooling", 4: "working"}
        mode = mode_map.get(regs[0], "standby")
        err_count = regs[1]
        error_codes = [str(c) for c in regs[2:12] if c != 0][:err_count]
        
        flags = regs[12] if len(regs) > 12 else 0
        return {
            "currentMode": mode,
            "errorCode": error_codes if error_codes else None,
            "SteamOnline": bool(flags & 0x01),
            "HoistOnline": bool(flags & 0x02),
        }

    @staticmethod
    def parse_temperatures(regs: list[float]) -> dict:
        if not regs or len(regs) < 5:
            return {}
        return {
            "SteamGenerator": round(regs[0], 2),
            "HeaterZone": round(regs[1], 2),
            "AirDuct": round(regs[2], 2),
            "Average": round(regs[3], 2),
            "ChamberZone": round(regs[4], 2),
        }

    @staticmethod
    def parse_environment(regs: list[float]) -> dict:
        if not regs or len(regs) < 4:
            return {}
        return {
            "AirDuctHumidity": round(regs[0], 2),
            "ChamberHumidity": round(regs[1], 2),
            "ChamberOxygen": round(regs[2], 2),
            "NitrogenLevel": round(regs[3], 2),
        }

    @staticmethod
    def parse_vfd_status(regs: list[int]) -> dict:
        """VFD: float32 + uint16 + float32 + uint16"""
        if not regs or len(regs) < 8:
            return {}
        
        def to_float(i):
            raw = struct.pack('>HH', regs[i], regs[i+1])
            return round(struct.unpack('>f', raw)[0], 2)
        
        return {
            "Steam": {
                "Frequency": to_float(0),
                "ErrorCode": str(regs[2])
            },
            "Hoist": {
                "Frequency": to_float(4),
                "ErrorCode": str(regs[6])
            }
        }

    @staticmethod
    def parse_stats(regs: list[int]) -> dict:
        if not regs or len(regs) < 6:
            return {}
        return {
            "patient_hoist": regs[0],
            "pipe_hoist": regs[1],
            "steam": regs[2],
            "charger": regs[3],
            "heater": regs[4],
            "exhaust": regs[5],
        }

    @staticmethod
    def parse_limit_switches(regs: list[int]) -> dict:
        """Распаковка битовых полей из 3 регистров"""
        if not regs or len(regs) < 3:
            return {}
        
        pipe = regs[0]
        patient = regs[1]
        safety = regs[2]
        
        return {
            "pipe_hoist": {
                "lsw_top_emergency": bool(pipe & 0x01),
                "lsw_top_working": bool(pipe & 0x02),
                "lsw_bottom_working": bool(pipe & 0x04),
                "lsw_bottom_emergency": bool(pipe & 0x08),
            },
            "patient_hoist": {
                "lsw_top_emergency": bool(patient & 0x01),
                "lsw_top_working": bool(patient & 0x02),
                "lsw_bottom_working": bool(patient & 0x04),
                "lsw_bottom_emergency": bool(patient & 0x08),
                "patient_present": bool(patient & 0x10),
            },
            "safety": {
                "estop_pressed": bool(safety & 0x01),
                "cabinet_door_open": bool(safety & 0x02),
            }
        }


# Глобальные экземпляры
modbus_client = ModbusMasterClient("192.168.1.100", 502, unit_id=1)
parser = ModbusDataParser()

async def write_register_float(self, address: int, value: float) -> bool:
    """Запись float32 (2 регистра)"""
    import struct
    raw = struct.pack('>f', value)
    regs = struct.unpack('>HH', raw)
    return await self.write_registers(address, list(regs))
