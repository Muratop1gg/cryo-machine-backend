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
