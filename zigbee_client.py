import asyncio
import logging
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass
import serial_asyncio
import models

logger = logging.getLogger(__name__)


@dataclass
class ZigbeeDeviceReading:
    """Унифицированный результат чтения с Zigbee-устройства"""
    device_type: str          # "nitrogen_mass" | "remote_control"
    ieee_address: str
    data: dict                # сырые данные в виде dict
    rssi: Optional[int] = None
    timestamp: float = 0.0


class ZigbeeFrameParser:
    """Парсер кадров Zigbee-модема. Адаптируется под конкретный модем."""
    
    @staticmethod
    def parse_raw_frame(raw: bytes) -> Optional[ZigbeeDeviceReading]:
        """
        Парсит сырой кадр от модема.
        Формат зависит от модели модема — здесь пример для API-режима Digi XBee.
        Для других модемов нужно переписать под свой протокол.
        """
        if len(raw) < 4:
            return None
        
        # Пример: API-кадр Digi XBee
        # [0x7E] [lenH] [lenL] [frame_type] [payload...] [checksum]
        if raw[0] != 0x7E:
            return None
        
        # Извлекаем IEEE-адрес источника (8 байт, обычно со смещения 5)
        ieee_bytes = raw[5:13]
        ieee_address = ":".join(f"{b:02X}" for b in ieee_bytes)
        
        # RSSI (если есть в кадре)
        rssi = -raw[13] if len(raw) > 13 else None
        
        # Полезная нагрузка — зависит от типа устройства
        payload = raw[14:-1]  # без checksum
        
        # Определяем тип устройства по IEEE-адресу или по профилю
        device_type = ZigbeeFrameParser._identify_device(ieee_address)
        data = ZigbeeFrameParser._parse_payload(device_type, payload)
        
        if data is None:
            return None
        
        import time
        return ZigbeeDeviceReading(
            device_type=device_type,
            ieee_address=ieee_address,
            data=data,
            rssi=rssi,
            timestamp=time.time(),
        )
    
    @staticmethod
    def _identify_device(ieee: str) -> str:
        """Определяет тип устройства по IEEE-адресу (из конфига)"""
        # Здесь можно расширить: читать из конфига
        # Пока заглушка — возвращаем "unknown"
        return "unknown"
    
    @staticmethod
    def _parse_payload(device_type: str, payload: bytes) -> Optional[dict]:
        """Парсит полезную нагрузку в зависимости от типа устройства"""
        if device_type == "nitrogen_mass":
            return ZigbeeFrameParser._parse_nitrogen_mass(payload)
        elif device_type == "remote_control":
            return ZigbeeFrameParser._parse_remote_control(payload)
        return None
    
    @staticmethod
    def _parse_nitrogen_mass(payload: bytes) -> dict:
        """Парсит данные датчика массы азота (пример: 4 байта float32)"""
        import struct
        if len(payload) < 4:
            return {"mass_kg": 0.0}
        mass = struct.unpack('>f', payload[:4])[0]
        return {"mass_kg": round(mass, 3)}
    
    @staticmethod
    def _parse_remote_control(payload: bytes) -> dict:
        """Парсит нажатия кнопок пульта"""
        # Пример: 1 байт = код кнопки, 1 байт = состояние (0=отпущена, 1=нажата)
        if len(payload) < 2:
            return {}
        btn_code = payload[0]
        pressed = bool(payload[1])
        
        # Маппинг кодов кнопок (из спецификации README)
        btn_map = {
            0x01: "btn_ok",
            0x02: "btn_esc",
            0x03: "btn_reset_fault",
            0x04: "btn_bypass_confirm",
        }
        btn_name = btn_map.get(btn_code, f"unknown_{btn_code:02X}")
        return {btn_name: pressed}


class ZigbeeSerialProtocol(asyncio.Protocol):
    """Asyncio-протокол для чтения данных из последовательного порта"""
    
    def __init__(self, on_data: Callable[[bytes], Awaitable[None]]):
        self.on_data = on_data
        self._buffer = bytearray()
        self.transport = None
    
    def connection_made(self, transport):
        self.transport = transport
        logger.info("✅ Zigbee serial port opened")
    
    def data_received(self, data: bytes):
        self._buffer.extend(data)
        # Ищем кадр по стартовому байту 0x7E
        while True:
            start = self._buffer.find(0x7E)
            if start == -1:
                self._buffer.clear()
                return
            if start > 0:
                self._buffer = self._buffer[start:]
            
            # Проверяем длину кадра
            if len(self._buffer) < 4:
                return
            frame_len = (self._buffer[1] << 8) | self._buffer[2]
            total_len = frame_len + 4  # +start+lenH+lenL+checksum
            
            if len(self._buffer) < total_len:
                return
            
            frame = bytes(self._buffer[:total_len])
            self._buffer = self._buffer[total_len:]
            
            # Асинхронно передаём кадр в обработчик
            asyncio.create_task(self.on_data(frame))
    
    def connection_lost(self, exc):
        logger.warning(f"⚠️ Zigbee serial connection lost: {exc}")


class ZigbeeClient:
    """Высокоуровневый клиент для работы с Zigbee USB-модемом"""
    
    def __init__(self, config: models.AppConfig):
        self.config = config
        self.port = "/dev/ttyUSB1"  # Можно вынести в конфиг
        self.baudrate = 115200
        
        self._transport = None
        self._protocol = None
        self.is_connected = False
        
        # Маппинг IEEE-адресов на типы устройств (из конфига)
        self.device_map: dict[str, str] = {}
        self._init_device_map()
        
        # Callback для передачи данных в основной цикл
        self._on_reading: Optional[Callable[[ZigbeeDeviceReading], Awaitable[None]]] = None
        
        # Последние прочитанные данные
        self.last_nitrogen_mass: Optional[float] = None
        self.last_buttons: dict = {}
    
    def _init_device_map(self):
        """Заполняет маппинг IEEE -> тип устройства из конфига"""
        hw = self.config.hardware
        
        if hw.nitrogen_mass_sensor.present and hw.nitrogen_mass_sensor.zigbee_ieee_address:
            self.device_map[hw.nitrogen_mass_sensor.zigbee_ieee_address] = "nitrogen_mass"
        
        # Если пульт тоже по Zigbee — добавляем его адрес
        # (можно расширить конфиг, добавив секцию remote_control)
    
    def set_reading_callback(self, callback: Callable[[ZigbeeDeviceReading], Awaitable[None]]):
        """Устанавливает callback для обработки прочитанных данных"""
        self._on_reading = callback
    
    async def connect(self) -> bool:
        try:
            loop = asyncio.get_running_loop()
            self._transport, self._protocol = await loop.create_connection(
                lambda: ZigbeeSerialProtocol(self._handle_raw_frame),
                url=self.port,
                baudrate=self.baudrate,
            )
            self.is_connected = True
            logger.info(f"✅ Zigbee modem connected on {self.port}")
            return True
        except Exception as e:
            logger.error(f"❌ Zigbee connection error: {e}")
            self.is_connected = False
            return False
    
    async def disconnect(self):
        if self._transport:
            self._transport.close()
        self.is_connected = False
        logger.info("🔌 Zigbee disconnected")
    
    async def _handle_raw_frame(self, raw: bytes):
        """Обработчик сырого кадра от модема"""
        reading = ZigbeeFrameParser.parse_raw_frame(raw)
        if reading is None:
            return
        
        # Определяем тип устройства по IEEE-адресу
        reading.device_type = self.device_map.get(reading.ieee_address, reading.device_type)
        
        # Сохраняем последние данные
        if reading.device_type == "nitrogen_mass":
            self.last_nitrogen_mass = reading.data.get("mass_kg")
        elif reading.device_type == "remote_control":
            self.last_buttons.update(reading.data)
        
        # Передаём в callback
        if self._on_reading:
            try:
                await self._on_reading(reading)
            except Exception as e:
                logger.error(f"❌ Zigbee reading callback error: {e}")
    
    def get_nitrogen_mass(self) -> Optional[float]:
        return self.last_nitrogen_mass
    
    def get_buttons_state(self) -> dict:
        return self.last_buttons.copy()


# --- Фоновая задача опроса ---
async def zigbee_polling_loop(client: ZigbeeClient, update_callback):
    """
    Фоновая задача. Zigbee работает по прерываниям (кадры приходят сами),
    поэтому здесь только периодическая проверка связи и рассылка накопленных данных.
    """
    await client.connect()
    
    while True:
        try:
            # Собираем текущие Zigbee-данные
            zigbee_data = {
                "nitrogen_mass_kg": client.get_nitrogen_mass(),
                "remote_buttons": client.get_buttons_state(),
            }
            
            # Передаём в основной цикл для слияния с Modbus-данными
            await update_callback(zigbee_data)
            
        except Exception as e:
            logger.error(f"❌ Zigbee polling error: {e}")
            # Пытаемся переподключиться
            await client.disconnect()
            await asyncio.sleep(2.0)
            await client.connect()
        
        # Периодическая рассылка (Zigbee-данные обычно меняются медленно)
        await asyncio.sleep(0.5)