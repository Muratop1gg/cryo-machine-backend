from typing import Literal, List

from pydantic import BaseModel

type SystemMode = Literal[
    "standby",
    "autotest",
    "drying",
    "cooling",
    "working"
]

class SystemStatusModel(BaseModel):
    currentMode: SystemMode
    errorCode: List[str]
    SteamOnline: bool
    HoistOnline: bool


class VFDModel(BaseModel):
    Frequency: float
    ErrorCode: str


class VFDStatusesModel(BaseModel):
    Steam: VFDModel
    Hoist: VFDModel

class TemperatureModel(BaseModel):
    SteamGenerator: float
    HeaterZone: float
    AirDuct: float
    Average: float
    ChamberZone: float

class EnvironmentModel(BaseModel):
    AirDuctHumidity: float
    ChamberHumidity: float
    ChamberOxygen: float
    NitrogenLevel: float


class TelemetryModel(BaseModel):
    Temperature: TemperatureModel
    Environment: EnvironmentModel
    vfdStatus: VFDStatusesModel


# --- Модели данных ---
class SensorData(BaseModel): # Это для отображения основной инфы по запросу с фронта
    SystemStatus: SystemStatusModel
    Telemetry: TelemetryModel

class Hoist(BaseModel):
    lswTopEmergency: bool
    lswBottomEmergency: bool
    lswTopWork: bool
    lswBottomWork: bool

class PatientHoist(Hoist):
    PatientPresent: bool

class SafetyModel(BaseModel):
    EStopPressed: bool
    CabinetDoorOpen: bool


class DigitalInputs(BaseModel):
    PipeHoist: Hoist
    PatientHoist: PatientHoist
    Safety: SafetyModel

class Event(BaseModel):
    EventType: int

class TechnologicalSettingsModel(BaseModel):
    WorkingTime: int
    WaitingTime: int
    ProcedureTime: int
    S1Temperature: float
    S2Temperature: float


class UpdateSettings(BaseModel):
    Mode: SystemMode
    TechnologicalSettings: TechnologicalSettingsModel

class PatientMotion(BaseModel):
    Motion: bool | None

class PipeMotion(BaseModel):
    Motion: bool | None

class ButtonEvent(BaseModel):
    type: Literal["OK", "ESC", "RESET_FAULT", "BYPASS_CONFIRM"]

class UnlockEvent(BaseModel):
    code: str

class ServiceEvent(BaseModel):
    type: str
    value: str


# ========== МОДЕЛИ ДЛЯ КОМАНД ПРОЦЕДУРЫ ==========

class StartProcedure(BaseModel):
    """Модель для команды запуска процедуры"""
    # Можно добавить дополнительные параметры при необходимости
    pass

class PauseProcedure(BaseModel):
    """Модель для команды паузы процедуры"""
    pass

class ResumeProcedure(BaseModel):
    """Модель для команды возобновления процедуры"""
    pass

class StopProcedure(BaseModel):
    """Модель для команды остановки процедуры"""
    pass


# ========== МОДЕЛИ ДЛЯ АКТУАТОРОВ ==========

class BlowerCommand(BaseModel):
    enabled: bool
    frequency_hz: float

class SteamGeneratorCommand(BaseModel):
    enabled: bool
    frequency_hz: float
    direction: Literal['forward', 'reverse']

class HoistCommand(BaseModel):
    state: Literal['stop', 'up', 'down']

class HeaterCommand(BaseModel):
    enabled: bool
    power_w: float

class ExhaustFanCommand(BaseModel):
    enabled: bool

class ExhaustDamperCommand(BaseModel):
    state: Literal['open', 'closed']

class LedStripCommand(BaseModel):
    enabled: bool
    color: str
    type: Literal['argb', 'rgb']

class ActuatorCommand(BaseModel):
    device: Literal[
        'blower', 
        'steam_generator', 
        'patient_hoist', 
        'pipe_hoist',
        'heater', 
        'exhaust_fan', 
        'exhaust_damper', 
        'led_strip'
    ]
    payload: BlowerCommand | SteamGeneratorCommand | HoistCommand | \
             HeaterCommand | ExhaustFanCommand | ExhaustDamperCommand | \
             LedStripCommand


# ========== МОДЕЛИ ДЛЯ ОТВЕТОВ ==========

class CommandResponse(BaseModel):
    status: Literal['success', 'error', 'timeout']
    message: str
    event_id: int | None = None
    data: dict | None = None


# ========== МОДЕЛИ ДЛЯ СТАТУСА ПРОЦЕДУРЫ ==========

class ProcedureStatus(BaseModel):
    status: Literal['stopped', 'running', 'paused']
    is_running: bool
    is_paused: bool
    start_time: str | None = None
    elapsed_time: float