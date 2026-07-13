import asyncio
import struct
import logging
from typing import Optional
from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusException
import models

logger = logging.getLogger(__name__)


class OxygenSensorData:
    """Структура данных с датчика кислорода"""
    def __init__(self, o2_percent: float, temperature: float, humidity: float):
        self.o2_percent = o2_percent
        self.temperature = temperature
        self.humidity = humidity

    def to_dict(self) -> dict:
        return {
            "ChamberOxygen": round(self.o2_percent, 2),
            "ChamberTemperature": round(self.temperature, 2),
            "ChamberHumidity": round(self.humidity, 2),
        }


class OxygenSensorClient:
    """Асинхронный клиент для RS485-датчика кислорода (Modbus RTU)"""
    
    def __init__(self, config: models.OxygenSensorConfig):
        if not config.present or config.connection_type != "rs485":
            raise ValueError("Oxygen sensor not configured for RS485")
        
        rs485 = config.rs485
        self.port = rs485.port
        self.baudrate = rs485.baudrate
        self.unit_id = rs485.modbus_unit_id
        self.registers = rs485.registers
        
        self.client = AsyncModbusSerialClient(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=rs485.bytesize,
            parity=rs485.parity,
            stopbits=rs485.stopbits,
            timeout=rs485.timeout,
        )
        self.is_connected = False
        self.last_data: Optional[OxygenSensorData] = None

    async def connect(self) -> bool:
        try:
            connected = await self.client.connect()
            if connected and self.client.connected:
                self.is_connected = True
                logger.info(f"✅ O2 sensor connected on {self.port} @ {self.baudrate}")
                return True
            logger.error(f"❌ O2 sensor connection failed on {self.port}")
            return False
        except Exception as e:
            logger.error(f"❌ O2 sensor error: {e}")
            return False

    async def disconnect(self):
        self.client.close()
        self.is_connected = False
        logger.info("🔌 O2 sensor disconnected")

    async def read_data(self) -> Optional[OxygenSensorData]:
        """Чтение всех трёх параметров одним запросом (если регистры идут подряд)"""
        if not self.is_connected:
            if not await self.connect():
                return None
        
        try:
            # Определяем стартовый адрес и количество регистров
            addrs = [
                self.registers.get("o2_percent", 0),
                self.registers.get("temperature", 2),
                self.registers.get("humidity", 4),
            ]
            start = min(addrs)
            count = max(addrs) - start + 2  # +2 т.к. каждый параметр = 2 регистра (float32)
            
            result = await self.client.read_holding_registers(
                address=start, count=count, slave=self.unit_id
            )
            if result.isError():
                logger.warning(f"O2 sensor read error: {result}")
                return None
            
            # Парсим float32 из пар регистров
            def decode_float(offset: int) -> float:
                idx = offset - start
                if idx + 1 >= len(result.registers):
                    return 0.0
                raw = struct.pack('>HH', result.registers[idx], result.registers[idx + 1])
                return struct.unpack('>f', raw)[0]
            
            data = OxygenSensorData(
                o2_percent=decode_float(self.registers.get("o2_percent", 0)),
                temperature=decode_float(self.registers.get("temperature", 2)),
                humidity=decode_float(self.registers.get("humidity", 4)),
            )
            self.last_data = data
            return data
            
        except ModbusException as e:
            logger.error(f"O2 sensor Modbus exception: {e}")
            self.is_connected = False
            return None
        except Exception as e:
            logger.error(f"O2 sensor unexpected error: {e}")
            return None


async def oxygen_sensor_polling_loop(client: OxygenSensorClient, update_callback):
    """Фоновая задача опроса датчика кислорода"""
    await client.connect()
    
    while True:
        try:
            data = await client.read_data()
            if data:
                await update_callback(data.to_dict())
        except Exception as e:
            logger.error(f"❌ O2 polling loop error: {e}")
        
        # Датчик среды медленно меняется — опрос раз в секунду
        await asyncio.sleep(1.0)