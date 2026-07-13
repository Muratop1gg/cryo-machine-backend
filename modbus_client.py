# Добавить в класс ModbusMasterClient:

async def write_register_float(self, address: int, value: float) -> bool:
    """Запись float32 (2 регистра)"""
    import struct
    raw = struct.pack('>f', value)
    regs = struct.unpack('>HH', raw)
    return await self.write_registers(address, list(regs))