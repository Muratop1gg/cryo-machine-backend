import logging
from typing import Optional, Union, cast
import models

logger = logging.getLogger(__name__)


class ActuatorController:
    """
    Транслирует высокоуровневые команды в запись регистров ПЛК.
    Адреса регистров — из карты ПЛК (заглушки, заменить на реальные).
    """
    
    REGISTERS = {
        "blower_enable": 300,
        "blower_frequency": 301,
        "steam_enable": 303,
        "steam_frequency": 304,
        "steam_direction": 306,
        "patient_hoist": 307,
        "pipe_hoist": 308,
        "heater_enable": 309,
        "heater_power": 310,
        "exhaust_fan_enable": 312,
        "exhaust_damper": 313,
        "led_enable": 314,
        "led_color_r": 315,
        "led_color_g": 316,
        "led_color_b": 317,
    }

    def __init__(self, modbus_client):
        self.modbus = modbus_client
        self._last_commands: dict = {}

    async def execute(self, command: models.ActuatorCommand) -> bool:
        """Выполняет команду на устройстве"""
        device = command.device
        payload = command.payload
        
        logger.info(f"️ Actuator command: {device} -> {payload}")
        
        try:
            if device == "blower":
                return await self._set_blower(payload)
            elif device == "steam_generator":
                return await self._set_steam_generator(payload)
            elif device == "patient_hoist":
                return await self._set_hoist("patient_hoist", payload)
            elif device == "pipe_hoist":
                return await self._set_hoist("pipe_hoist", payload)
            elif device == "heater":
                return await self._set_heater(payload)
            elif device == "exhaust_fan":
                return await self._set_exhaust_fan(payload)
            elif device == "exhaust_damper":
                return await self._set_exhaust_damper(payload)
            elif device == "led_strip":
                return await self._set_led(payload)
            else:
                logger.error(f"❌ Unknown device: {device}")
                return False
        except Exception as e:
            logger.error(f"❌ Failed to execute command on {device}: {e}")
            return False

    async def _set_blower(self, cmd: Union[models.BlowerCommand, dict]) -> bool:
        # Явное приведение типа для Pylance
        if isinstance(cmd, dict):
            cmd = models.BlowerCommand(**cmd)
        cmd = cast(models.BlowerCommand, cmd)
        
        ok1 = await self.modbus.write_register(
            self.REGISTERS["blower_enable"], 1 if cmd.enabled else 0
        )
        ok2 = await self.modbus.write_register_float(
            self.REGISTERS["blower_frequency"], cmd.frequency_hz
        )
        self._last_commands["blower"] = cmd.model_dump()
        return ok1 and ok2

    async def _set_steam_generator(self, cmd: Union[models.SteamGeneratorCommand, dict]) -> bool:
        if isinstance(cmd, dict):
            cmd = models.SteamGeneratorCommand(**cmd)
        cmd = cast(models.SteamGeneratorCommand, cmd)
        
        ok1 = await self.modbus.write_register(
            self.REGISTERS["steam_enable"], 1 if cmd.enabled else 0
        )
        ok2 = await self.modbus.write_register_float(
            self.REGISTERS["steam_frequency"], cmd.frequency_hz
        )
        ok3 = await self.modbus.write_register(
            self.REGISTERS["steam_direction"], 0 if cmd.direction == "forward" else 1
        )
        self._last_commands["steam_generator"] = cmd.model_dump()
        return ok1 and ok2 and ok3

    async def _set_hoist(self, name: str, cmd: Union[models.HoistCommand, dict]) -> bool:
        if isinstance(cmd, dict):
            cmd = models.HoistCommand(**cmd)
        cmd = cast(models.HoistCommand, cmd)
        
        state_map = {"stop": 0, "up": 1, "down": 2}
        ok = await self.modbus.write_register(
            self.REGISTERS[name], state_map[cmd.state]
        )
        self._last_commands[name] = cmd.model_dump()
        return ok

    async def _set_heater(self, cmd: Union[models.HeaterCommand, dict]) -> bool:
        if isinstance(cmd, dict):
            cmd = models.HeaterCommand(**cmd)
        cmd = cast(models.HeaterCommand, cmd)
        
        ok1 = await self.modbus.write_register(
            self.REGISTERS["heater_enable"], 1 if cmd.enabled else 0
        )
        ok2 = await self.modbus.write_register_float(
            self.REGISTERS["heater_power"], cmd.power_w
        )
        self._last_commands["heater"] = cmd.model_dump()
        return ok1 and ok2

    async def _set_exhaust_fan(self, cmd: Union[models.ExhaustFanCommand, dict]) -> bool:
        if isinstance(cmd, dict):
            cmd = models.ExhaustFanCommand(**cmd)
        cmd = cast(models.ExhaustFanCommand, cmd)
        
        ok = await self.modbus.write_register(
            self.REGISTERS["exhaust_fan_enable"], 1 if cmd.enabled else 0
        )
        self._last_commands["exhaust_fan"] = cmd.model_dump()
        return ok

    async def _set_exhaust_damper(self, cmd: Union[models.ExhaustDamperCommand, dict]) -> bool:
        if isinstance(cmd, dict):
            cmd = models.ExhaustDamperCommand(**cmd)
        cmd = cast(models.ExhaustDamperCommand, cmd)
        
        ok = await self.modbus.write_register(
            self.REGISTERS["exhaust_damper"], 1 if cmd.state == "open" else 0
        )
        self._last_commands["exhaust_damper"] = cmd.model_dump()
        return ok

    async def _set_led(self, cmd: Union[models.LedStripCommand, dict]) -> bool:
        if isinstance(cmd, dict):
            cmd = models.LedStripCommand(**cmd)
        cmd = cast(models.LedStripCommand, cmd)
        
        color = cmd.color.lstrip("#")
        r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
        
        ok1 = await self.modbus.write_register(
            self.REGISTERS["led_enable"], 1 if cmd.enabled else 0
        )
        ok2 = await self.modbus.write_register(self.REGISTERS["led_color_r"], r)
        ok3 = await self.modbus.write_register(self.REGISTERS["led_color_g"], g)
        ok4 = await self.modbus.write_register(self.REGISTERS["led_color_b"], b)
        
        self._last_commands["led_strip"] = cmd.model_dump()
        return ok1 and ok2 and ok3 and ok4

    def get_status(self, raw_stats: dict, raw_inputs: dict) -> models.ActuatorStatus:
        """Формирует статусы устройств из сырых данных ПЛК."""
        hoist_state_map = {0: "stop", 1: "up", 2: "down", 3: "stop"}
        
        return models.ActuatorStatus(
            blower=models.BlowerStatus(
                enabled=raw_stats.get("charger", 0) == 1,
                frequency_hz=0.0
            ),
            steam_generator=models.SteamGeneratorStatus(
                enabled=raw_stats.get("steam", 0) in [1, 2],
                frequency_hz=0.0,
                direction="forward"
            ),
            patient_hoist=models.HoistStatus(
                state=hoist_state_map.get(raw_stats.get("patient_hoist", 0), "stop")
            ),
            pipe_hoist=models.HoistStatus(
                state=hoist_state_map.get(raw_stats.get("pipe_hoist", 0), "stop")
            ),
            heater=models.HeaterStatus(
                enabled=raw_stats.get("heater", 0) == 1,
                power_w=0.0
            ),
            exhaust_fan=models.ExhaustFanStatus(
                enabled=raw_stats.get("exhaust", 0) in [1, 2]
            ),
            exhaust_damper=models.ExhaustDamperStatus(
                state="open"
            ),
            led_strip=models.LedStripStatus(
                enabled=False,
                color="#000000",
                type="rgb"
            ),
        )


# Глобальный экземпляр
actuator_controller: Optional[ActuatorController] = None
