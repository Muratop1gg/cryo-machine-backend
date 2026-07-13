from typing import Literal, List, Optional
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
import time

# --- Типы ---
SystemMode = Literal["stdby", "autotest", "drying", "cooling", "working"]

# ========== МОДЕЛИ ДЛЯ ОТОБРАЖЕНИЯ (БЭК → ФРОНТ) ==========

class SystemStatusModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    currentMode: SystemMode
    errorCode: Optional[List[str]] = None
    SteamOnline: bool
    HoistOnline: bool


class VFDModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    Frequency: float
    ErrorCode: str


class VFDStatusesModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    Steam: VFDModel
    Hoist: VFDModel


class TemperatureModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    SteamGenerator: float
    HeaterZone: float
    AirDuct: float
    Average: float
    ChamberZone: float


class EnvironmentModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    AirDuctHumidity: float
    ChamberHumidity: float
    ChamberOxygen: float
    NitrogenLevel: float


class TelemetryModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    Temperature: TemperatureModel
    Environment: EnvironmentModel
    vfdStatus: VFDStatusesModel


class SensorData(BaseModel):
    """Основная телеметрия (по запросу с фронта)"""
    model_config = ConfigDict(populate_by_name=True)
    SystemStatus: SystemStatusModel
    Telemetry: TelemetryModel


# ========== ЦИФРОВЫЕ ВХОДЫ И СТАТИСТИКА ==========

class Hoist(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    lsw_top_emergency: bool
    lsw_top_working: bool
    lsw_bottom_working: bool
    lsw_bottom_emergency: bool


class PatientHoist(Hoist):
    patient_present: bool


class SafetyModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    estop_pressed: bool
    cabinet_door_open: bool


class DigitalInputs(BaseModel):
    """Концевики и безопасность"""
    model_config = ConfigDict(populate_by_name=True)
    pipe_hoist: Hoist
    patient_hoist: PatientHoist
    safety: SafetyModel


class StatsModel(BaseModel):
    """Статусы оборудования"""
    model_config = ConfigDict(populate_by_name=True)
    patient_hoist: int  # 0-стоп, 1-вверх, 2-вниз, 3-авария
    pipe_hoist: int      # 0-стоп, 1-вверх, 2-вниз, 3-авария
    steam: int           # 0-стоп, 1-вкл, 2-работа, 3-остановка, 4-авария
    charger: int         # 0-стоп, 1-работа, 2-авария
    heater: int          # 0-стоп, 1-работа, 2-авария
    exhaust: int         # 0-стоп, 1-вкл, 2-работа, 3-остановка, 4-авария


# ========== СИСТЕМНАЯ ИНФОРМАЦИЯ ==========

class SystemInfo(BaseModel):
    """Расширенная системная информация + концевики"""
    model_config = ConfigDict(populate_by_name=True)
    
    # Системные данные
    hostname: str
    os: str
    python_version: str
    app_version: str
    uptime_seconds: float
    started_at: str
    
    # Статусы подключений
    modbus_connected: bool
    zigbee_connected: bool
    o2_sensor_connected: bool
    
    # Текущая телеметрия
    SystemStatus: SystemStatusModel
    Telemetry: TelemetryModel
    digital_inputs: DigitalInputs
    stats: StatsModel


# ========== СОБЫТИЯ ОТ ПЛК ==========

class Event(BaseModel):
    """Событие от ПЛК (event_id + строка состояния)"""
    model_config = ConfigDict(populate_by_name=True)
    event_id: int
    state_code: Optional[str] = None  # Строка "abc" из README
    timestamp: float = Field(default_factory=time.time)


# ========== КОМАНДЫ С ФРОНТА (ФРОНТ → БЭК) ==========

class ModeSelection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    mode: SystemMode


class TechnologicalSettingsModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    time_s1_sec: int
    time_s2_sec: int
    time_s3_sec: int
    temperature_sp1: float
    temperature_sp2: float


class UpdateSettings(BaseModel):
    """POST /api/settings"""
    model_config = ConfigDict(populate_by_name=True)
    mode_selection: ModeSelection
    technological_settings: TechnologicalSettingsModel


class MotionCommands(BaseModel):
    """POST /api/motion — команды лебёдкам"""
    model_config = ConfigDict(populate_by_name=True)
    patient_hoist: Optional[bool] = None  # true=вверх, false=вниз, null=стоп
    pipe_hoist: Optional[bool] = None     # true=вверх, false=вниз, null=стоп


class UiButtons(BaseModel):
    """POST /api/ui_buttons — дубли кнопок контроллера"""
    model_config = ConfigDict(populate_by_name=True)
    btn_ok: bool
    btn_esc: bool
    btn_reset_fault: bool
    btn_bypass_confirm: bool


class Security(BaseModel):
    """POST /api/security — разблокировка"""
    model_config = ConfigDict(populate_by_name=True)
    system_code_long: str


# ========== УПРАВЛЕНИЕ ИСПОЛНИТЕЛЬНЫМИ УСТРОЙСТВАМИ ==========

class BlowerCommand(BaseModel):
    enabled: bool
    frequency_hz: float = Field(ge=0, le=50)


class SteamGeneratorCommand(BaseModel):
    enabled: bool
    frequency_hz: float = Field(ge=0, le=50)
    direction: Literal["forward", "reverse"] = "forward"


class HoistCommand(BaseModel):
    state: Literal["stop", "up", "down"]


class HeaterCommand(BaseModel):
    enabled: bool
    power_w: float = Field(default=500, ge=0, le=500)


class ExhaustFanCommand(BaseModel):
    enabled: bool


class ExhaustDamperCommand(BaseModel):
    state: Literal["open", "closed"]


class LedStripCommand(BaseModel):
    enabled: bool
    color: str = "#000000"
    type: Literal["argb", "rgb"] = "rgb"


class ActuatorCommand(BaseModel):
    """Универсальная команда для исполнительных устройств"""
    model_config = ConfigDict(populate_by_name=True)
    device: Literal[
        "blower", "steam_generator", "patient_hoist", "pipe_hoist",
        "heater", "exhaust_fan", "exhaust_damper", "led_strip"
    ]
    payload: dict  # Одна из команд выше


# ========== АВТОКАЛИБРОВКА ==========

class AutocalibrationCommand(BaseModel):
    start: bool = True


# ========== ОТВЕТЫ API ==========

class CommandResponse(BaseModel):
    """Ответ на команду с подтверждением от ПЛК"""
    model_config = ConfigDict(populate_by_name=True)
    status: Literal["success", "error", "timeout"]
    message: str
    event_id: Optional[int] = None  # Подтверждение от ПЛК
    data: Optional[dict] = None


class LogResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    content: str
    lines_count: int
    last_modified: Optional[str] = None


class ConfigResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    network: dict
    hardware: dict
    defaults: dict
    modbus_plc: dict
    zigbee_modem: dict