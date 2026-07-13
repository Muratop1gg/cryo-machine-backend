from typing import Literal, List, Optional
from pydantic import BaseModel, Field, ConfigDict

# --- Типы и перечисления ---
SystemMode = Literal["stdby", "standby", "autotest", "drying", "cooling", "working"]

# --- Модели для телеметрии и статуса (Бэк -> Фронт) ---
class SystemStatusModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    currentMode: SystemMode
    errorCode: Optional[List[str]] = Field(default=None, alias="errorCode")
    SteamOnline: bool = Field(alias="SteamOnline")
    HoistOnline: bool = Field(alias="HoistOnline")

class VFDModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    Frequency: float = Field(alias="Frequency")
    ErrorCode: str = Field(alias="ErrorCode")

class VFDStatusesModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    Steam: VFDModel = Field(alias="Steam")
    Hoist: VFDModel = Field(alias="Hoist")

class TemperatureModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    SteamGenerator: float = Field(alias="SteamGenerator")
    HeaterZone: float = Field(alias="HeaterZone")
    AirDuct: float = Field(alias="AirDuct")
    Average: float = Field(alias="Average")
    ChamberZone: float = Field(alias="ChamberZone")

class EnvironmentModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    AirDuctHumidity: float = Field(alias="AirDuctHumidity")
    ChamberHumidity: float = Field(alias="ChamberHumidity")
    ChamberOxygen: float = Field(alias="ChamberOxygen")
    NitrogenLevel: float = Field(alias="NitrogenLevel")

class TelemetryModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    Temperature: TemperatureModel = Field(alias="Temperature")
    Environment: EnvironmentModel = Field(alias="Environment")
    vfdStatus: VFDStatusesModel = Field(alias="vfdStatus")

class SensorData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    SystemStatus: SystemStatusModel = Field(alias="SystemStatus")
    Telemetry: TelemetryModel = Field(alias="Telemetry")

# --- Модели цифровых входов и статистики (Бэк -> Фронт) ---
class HoistInputs(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    lsw_top_emergency: bool
    lsw_top_working: bool
    lsw_bottom_working: bool
    lsw_bottom_emergency: bool

class PatientHoistInputs(HoistInputs):
    patient_present: bool

class SafetyInputs(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    estop_pressed: bool
    cabinet_door_open: bool

class DigitalInputs(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    pipe_hoist: HoistInputs
    patient_hoist: PatientHoistInputs
    safety: SafetyInputs

class StatsModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    patient_hoist: int  # 0-стоп, 1-вверх, 2-вниз, 3-авария
    pipe_hoist: int     # 0-стоп, 1-вверх, 2-вниз, 3-авария
    steam: int          # 0-стоп, 1-вкл, 2-работа, 3-остановка, 4-авария
    charger: int        # 0-стоп, 1-работа, 2-авария
    heater: int         # 0-стоп, 1-работа, 2-авария
    exhaust: int        # 0-стоп, 1-вкл, 2-работа, 3-остановка, 4-авария

# --- Модели событий (Бэк -> Фронт) ---
class Event(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    event_id: int = Field(alias="event_id")
    state_code: Optional[str] = Field(default=None, alias="state_code") # Та самая строка "abc"

# --- Модели команд с Фронта (Фронт -> Бэк) ---
class ModeSelection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    mode: SystemMode

class TechnologicalSettingsModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    time_s1_sec: int = Field(alias="time_s1_sec")
    time_s2_sec: int = Field(alias="time_s2_sec")
    time_s3_sec: int = Field(alias="time_s3_sec")
    temperature_sp1: float = Field(alias="temperature_sp1")
    temperature_sp2: float = Field(alias="temperature_sp2")

class UpdateSettings(BaseModel):
    """Полный POST запрос настроек с фронта"""
    model_config = ConfigDict(populate_by_name=True)
    mode_selection: ModeSelection = Field(alias="mode_selection")
    technological_settings: TechnologicalSettingsModel = Field(alias="technological_settings")

class MotionCommands(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    patient_hoist: Optional[bool] = Field(default=None, alias="patient_hoist") # true-вверх, false-вниз, null-стоп
    pipe_hoist: Optional[bool] = Field(default=None, alias="pipe_hoist")

class UiButtons(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    btn_ok: bool = Field(alias="btn_ok")
    btn_esc: bool = Field(alias="btn_esc")
    btn_reset_fault: bool = Field(alias="btn_reset_fault")
    btn_bypass_confirm: bool = Field(alias="btn_bypass_confirm")

class Security(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    system_code_long: str = Field(alias="system_code_long")

# --- Универсальная модель входящего WebSocket/POST сообщения от фронта ---
class FrontendCommand(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    update_settings: Optional[UpdateSettings] = Field(default=None, alias="update_settings")
    motion_commands: Optional[MotionCommands] = Field(default=None, alias="motion_commands")
    ui_buttons: Optional[UiButtons] = Field(default=None, alias="ui_buttons")
    security: Optional[Security] = Field(default=None, alias="security")
    # Можно добавить service_event и другие по мере необходимости
