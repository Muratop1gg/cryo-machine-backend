import platform
import time
import os
import json
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging

import models
from config_manager import config_manager
from procedure_logger import procedure_logger
from modbus_client import modbus_client, ModbusDataParser
from oxygen_sensor import OxygenSensorClient, oxygen_sensor_polling_loop
from zigbee_client import ZigbeeClient, zigbee_polling_loop
from actuator_controller import ActuatorController, actuator_controller
from command_tracker import command_tracker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ========== CONNECTION MANAGER ==========

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"✅ Client connected. Total: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"❌ Client disconnected. Total: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except WebSocketDisconnect:
                disconnected.append(conn)
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


# ========== SHARED STATE ==========

class SharedState:
    """Хранит актуальное состояние системы"""
    
    def __init__(self):
        self.system_status: Optional[models.SystemStatusModel] = None
        self.telemetry: Optional[models.TelemetryModel] = None
        self.digital_inputs: Optional[models.DigitalInputs] = None
        self.stats: Optional[models.StatsModel] = None
        self.zigbee_data: dict = {}
        self.last_event: Optional[models.Event] = None
        self._lock = asyncio.Lock()
        self.start_time = time.time()
    
    async def update_from_modbus(self, sensor_data: models.SensorData, 
                                  digital_inputs: models.DigitalInputs,
                                  stats: models.StatsModel):
        async with self._lock:
            self.system_status = sensor_data.SystemStatus
            self.telemetry = sensor_data.Telemetry
            self.digital_inputs = digital_inputs
            self.stats = stats
    
    async def update_event(self, event: models.Event):
        async with self._lock:
            self.last_event = event
            # Уведомляем command tracker
            await command_tracker.confirm_command(event.event_id)
    
    async def get_system_info(self) -> Optional[models.SystemInfo]:
        async with self._lock:
            if not all([self.system_status, self.telemetry, self.digital_inputs, self.stats]):
                return None
            
            return models.SystemInfo(
                hostname=platform.node(),
                os=f"{platform.system()} {platform.release()}",
                python_version=platform.python_version(),
                app_version="1.0.0",
                uptime_seconds=time.time() - self.start_time,
                started_at=datetime.fromtimestamp(self.start_time).isoformat(),
                modbus_connected=modbus_client.is_connected,
                zigbee_connected=False,  # обновлять из zigbee_client
                o2_sensor_connected=False,  # обновлять из o2_client
                
                # Телеметрия
                SystemStatus=self.system_status,
                Telemetry=self.telemetry,
                digital_inputs=self.digital_inputs,
                stats=self.stats
            )


shared_state = SharedState()


# ========== LIFESPAN ==========

@asynccontextmanager
async def lifespan(myapp: FastAPI):
    global actuator_controller
    
    logger.info("🚀 Starting server...")
    config = config_manager.load()
    
    # Инициализация
    actuator_controller = ActuatorController(modbus_client)
    
    tasks = []
    
    # 1. Modbus polling
    async def modbus_loop():
        await modbus_client.connect()
        while True:
            try:
                # Чтение всех данных
                raw = await modbus_client.read_all_data()
                parser = ModbusDataParser()
                
                # Парсинг
                system_status = parser.parse_system_status(raw.get("system_status", []))
                temps = parser.parse_temperatures(raw.get("temperatures", []))
                env = parser.parse_environment(raw.get("environment", []))
                vfd = parser.parse_vfd_status(raw.get("vfd_status", []))
                ls = parser.parse_limit_switches(raw.get("digital_inputs", []))
                stats_dict = parser.parse_stats(raw.get("stats", []))
                
                # Формируем модели
                sensor_data = models.SensorData(
                    SystemStatus=models.SystemStatusModel(**system_status),
                    Telemetry=models.TelemetryModel(
                        Temperature=models.TemperatureModel(**temps),
                        Environment=models.EnvironmentModel(**env),
                        vfdStatus=models.VFDStatusesModel(
                            Steam=models.VFDModel(**vfd["Steam"]),
                            Hoist=models.VFDModel(**vfd["Hoist"])
                        )
                    )
                )
                digital_inputs = models.DigitalInputs(**ls)
                stats = models.StatsModel(**stats_dict)
                
                # Обновляем состояние
                await shared_state.update_from_modbus(sensor_data, digital_inputs, stats)
                
                # Рассылаем телеметрию
                await manager.broadcast({
                    "SystemStatus": system_status,
                    "Telemetry": {
                        "Temperature": temps,
                        "Environment": env,
                        "vfdStatus": vfd
                    },
                    "timestamp": datetime.now().isoformat()
                })
                
            except Exception as e:
                logger.error(f"❌ Modbus loop error: {e}")
            
            await asyncio.sleep(0.2)
    
    tasks.append(asyncio.create_task(modbus_loop()))
    
    # 2. Event polling (отдельная задача для event_id)
    async def event_loop():
        while True:
            try:
                # Читаем регистр с event_id (адрес 400 — пример)
                event_regs = await modbus_client.read_holding_registers(400, 2)
                if event_regs and len(event_regs) >= 1:
                    event_id = event_regs[0]
                    state_code = f"{event_id // 100}{(event_id // 10) % 10}{event_id % 10}"
                    
                    event = models.Event(
                        event_id=event_id,
                        state_code=state_code,
                        timestamp=time.time()
                    )
                    
                    await shared_state.update_event(event)
                    
                    # Логируем в процедуру
                    procedure_logger.log_event(
                        event_id=event_id,
                        state_code=state_code
                    )
            except Exception as e:
                logger.error(f" Event loop error: {e}")
            
            await asyncio.sleep(0.5)
    
    tasks.append(asyncio.create_task(event_loop()))
    
    # 3. Zigbee (опционально)
    zigbee_client = None
    if config.hardware.zigbee_remote.present or config.hardware.nitrogen_mass_sensor.present:
        zigbee_client = ZigbeeClient(config)
        tasks.append(asyncio.create_task(zigbee_polling_loop(zigbee_client, shared_state.update_zigbee)))
    
    # 4. RS485 O2 (опционально)
    if config.hardware.oxygen_sensor.present and config.hardware.oxygen_sensor.connection_type == "rs485":
        o2_client = OxygenSensorClient(config.hardware.oxygen_sensor)
        tasks.append(asyncio.create_task(oxygen_sensor_polling_loop(o2_client, shared_state.update_zigbee)))
    
    logger.info("✅ Background tasks started")
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down...")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    
    if zigbee_client:
        await zigbee_client.disconnect()
    await modbus_client.disconnect()
    procedure_logger.close()
    logger.info("✅ Shutdown complete")


# ========== FASTAPI APP ==========

app = FastAPI(title="Cryo Chamber Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== GET ENDPOINTS ==========

@app.get("/api/config", response_model=models.ConfigResponse)
async def get_config():
    """Системная конфигурация"""
    try:
        config = config_manager.get()
        return models.ConfigResponse(
            network=config.network.model_dump(),
            hardware=config.hardware.model_dump(),
            defaults=config.defaults.model_dump(),
            modbus_plc=config.modbus_plc.model_dump(),
            zigbee_modem=config.zigbee_modem.model_dump()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/system_info", response_model=models.SystemInfo)
async def get_system_info():
    """
    Системная информация + телеметрия + концевики + статистика.
    Всё в одном запросе.
    """
    info = await shared_state.get_system_info()
    if not info:
        raise HTTPException(status_code=503, detail="System not ready")
    return info


@app.get("/api/actuators/status")
async def get_actuators_status():
    """Статусы исполнительных устройств"""
    if not actuator_controller or not shared_state.stats:
        return models.ActuatorStatus().model_dump()
    
    status = actuator_controller.get_status(
        shared_state.stats.model_dump(),
        shared_state.digital_inputs.model_dump() if shared_state.digital_inputs else {}
    )
    return status.model_dump()


@app.get("/api/log")
async def get_log(lines: int = Query(default=100, ge=1, le=1000)):
    """Лог последней процедуры"""
    log_path = Path("logs/last_procedure.log")
    if not log_path.exists():
        return {"content": "", "lines_count": 0}
    
    try:
        all_lines = log_path.read_text(encoding="utf-8").splitlines()
        selected = all_lines[-lines:] if len(all_lines) > lines else all_lines
        return models.LogResponse(
            content="\n".join(selected),
            lines_count=len(selected),
            last_modified=datetime.fromtimestamp(log_path.stat().st_mtime).isoformat()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== POST ENDPOINTS ==========

@app.post("/api/settings", response_model=models.CommandResponse)
async def update_settings(settings: models.UpdateSettings):
    """Обновление настроек процедуры"""
    command_id = f"settings_{time.time()}"
    
    # Регистрируем команду
    if not await command_tracker.send_command(command_id):
        return models.CommandResponse(
            status="error",
            message="Command already pending"
        )
    
    try:
        # Записываем в ПЛК (пример)
        ok = await modbus_client.write_register(200, 0)  # mode
        # ... записать остальные уставки
        
        if not ok:
            return models.CommandResponse(
                status="error",
                message="Failed to write to PLC"
            )
        
        # Ждём подтверждения
        event = await command_tracker.wait_for_confirmation(command_id)
        
        if event:
            return models.CommandResponse(
                status="success",
                message="Settings updated",
                event_id=event.event_id,
                data=settings.model_dump()
            )
        else:
            return models.CommandResponse(
                status="timeout",
                message="No confirmation from PLC"
            )
    
    except Exception as e:
        return models.CommandResponse(
            status="error",
            message=str(e)
        )


@app.post("/api/motion", response_model=models.CommandResponse)
async def motion_command(cmd: models.MotionCommands):
    """Команды движения лебёдкам"""
    command_id = f"motion_{time.time()}"
    
    if not await command_tracker.send_command(command_id):
        return models.CommandResponse(status="error", message="Command already pending")
    
    try:
        # Формируем значение для регистра
        value = 0
        if cmd.patient_hoist is True:
            value |= 0x02  # patient up
        elif cmd.patient_hoist is False:
            value |= 0x04  # patient down
        if cmd.pipe_hoist is True:
            value |= 0x08  # pipe up
        elif cmd.pipe_hoist is False:
            value |= 0x10  # pipe down
        
        ok = await modbus_client.write_register(210, value)
        if not ok:
            return models.CommandResponse(status="error", message="Failed to write to PLC")
        
        # Ждём event_id
        event = await command_tracker.wait_for_confirmation(command_id)
        
        if event:
            return models.CommandResponse(
                status="success",
                message="Motion command executed",
                event_id=event.event_id
            )
        else:
            return models.CommandResponse(
                status="timeout",
                message="No confirmation from PLC"
            )
    
    except Exception as e:
        return models.CommandResponse(status="error", message=str(e))


@app.post("/api/ui_buttons", response_model=models.CommandResponse)
async def ui_buttons(cmd: models.UiButtons):
    """Дубли кнопок контроллера"""
    command_id = f"buttons_{time.time()}"
    
    if not await command_tracker.send_command(command_id):
        return models.CommandResponse(status="error", message="Command already pending")
    
    try:
        value = 0
        if cmd.btn_ok: value |= 0x01
        if cmd.btn_esc: value |= 0x02
        if cmd.btn_reset_fault: value |= 0x04
        if cmd.btn_bypass_confirm: value |= 0x08
        
        ok = await modbus_client.write_register(211, value)
        if not ok:
            return models.CommandResponse(status="error", message="Failed to write to PLC")
        
        event = await command_tracker.wait_for_confirmation(command_id)
        
        if event:
            return models.CommandResponse(
                status="success",
                message="Button command executed",
                event_id=event.event_id
            )
        else:
            return models.CommandResponse(
                status="timeout",
                message="No confirmation from PLC"
            )
    
    except Exception as e:
        return models.CommandResponse(status="error", message=str(e))


@app.post("/api/security", response_model=models.CommandResponse)
async def security_unlock(cmd: models.Security):
    """Разблокировка без интернета"""
    command_id = f"security_{time.time()}"
    
    if not await command_tracker.send_command(command_id):
        return models.CommandResponse(status="error", message="Command already pending")
    
    try:
        # Проверка кода (пример)
        if cmd.system_code_long != "sdfbjkhds1212367t21asd":
            return models.CommandResponse(
                status="error",
                message="Invalid security code"
            )
        
        # Запись в ПЛК
        ok = await modbus_client.write_register(220, 1)
        if not ok:
            return models.CommandResponse(status="error", message="Failed to write to PLC")
        
        event = await command_tracker.wait_for_confirmation(command_id)
        
        if event:
            return models.CommandResponse(
                status="success",
                message="System unlocked",
                event_id=event.event_id
            )
        else:
            return models.CommandResponse(
                status="timeout",
                message="No confirmation from PLC"
            )
    
    except Exception as e:
        return models.CommandResponse(status="error", message=str(e))


@app.post("/api/autocalibration", response_model=models.CommandResponse)
async def autocalibration(cmd: models.AutocalibrationCommand):
    """Запуск автокалибровки"""
    if not cmd.start:
        return models.CommandResponse(status="success", message="Calibration idle")
    
    command_id = f"autocal_{time.time()}"
    
    if not await command_tracker.send_command(command_id):
        return models.CommandResponse(status="error", message="Command already pending")
    
    try:
        ok = await modbus_client.write_register(250, 1)
        if not ok:
            return models.CommandResponse(status="error", message="Failed to start calibration")
        
        event = await command_tracker.wait_for_confirmation(command_id)
        
        if event:
            return models.CommandResponse(
                status="success",
                message="Autocalibration started",
                event_id=event.event_id
            )
        else:
            return models.CommandResponse(
                status="timeout",
                message="No confirmation from PLC"
            )
    
    except Exception as e:
        return models.CommandResponse(status="error", message=str(e))


@app.post("/api/actuators/command", response_model=models.CommandResponse)
async def actuator_command(cmd: models.ActuatorCommand):
    """Универсальная команда для исполнительных устройств"""
    if not actuator_controller:
        raise HTTPException(status_code=503, detail="Actuator controller not initialized")
    
    command_id = f"actuator_{cmd.device}_{time.time()}"
    
    if not await command_tracker.send_command(command_id):
        return models.CommandResponse(status="error", message="Command already pending")
    
    try:
        ok = await actuator_controller.execute(cmd)
        if not ok:
            return models.CommandResponse(
                status="error",
                message=f"Failed to control {cmd.device}"
            )
        
        event = await command_tracker.wait_for_confirmation(command_id)
        
        if event:
            return models.CommandResponse(
                status="success",
                message=f"Actuator {cmd.device} controlled",
                event_id=event.event_id
            )
        else:
            return models.CommandResponse(
                status="timeout",
                message="No confirmation from PLC"
            )
    
    except Exception as e:
        return models.CommandResponse(status="error", message=str(e))


# ========== WEBSOCKET ==========

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    
    try:
        # Приветствие
        await websocket.send_json({
            "type": "connection_established",
            "message": "Connected to telemetry stream",
            "timestamp": datetime.now().isoformat()
        })
        
        # Отправляем текущее состояние
        info = await shared_state.get_system_info()
        if info:
            await websocket.send_json({
                "SystemStatus": info.SystemStatus.model_dump(),
                "Telemetry": info.Telemetry.model_dump(),
                "digital_inputs": info.digital_inputs.model_dump(),
                "stats": info.stats.model_dump(),
                "timestamp": datetime.now().isoformat()
            })
        
        # Цикл
        while True:
            try:
                data = await websocket.receive_text()
                logger.debug(f"📩 WS: {data}")
                # Можно обрабатывать быстрые команды, если нужно
            except WebSocketDisconnect:
                break
    finally:
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")