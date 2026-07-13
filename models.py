from typing import Literal, List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
import time

# ================= КОНФИГУРАЦИЯ =================

class WifiConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    wifi_ssid: str
    wifi_password: str
    wifi_security: Literal["WPA2", "WPA3", "OPEN"] = "WPA2"

class NitrogenMassSensorConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    present: bool
    connection: Literal["zigbee"] = "zigbee"
    zigbee_ieee_address: Optional[str] = None

class SteamGeneratorConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    drive_type: Literal["vfd", "contactor"]
    vfd_model: Optional[str] = None
    modbus_unit_id: Optional[int] = None
    adaptive_control: bool = False
    max_frequency_hz: float = 50.0
    min_frequency_hz: float = 0.0

class RS485Config(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    port: str
    baudrate: int = 9600
    bytesize: Literal[7, 8] = 8
    parity: Literal["N", "E", "O"] = "N"
    stopbits: Literal[1, 2] = 1
    timeout: float = 1.0
    modbus_unit_id: int = 1
    registers: dict = Field(default_factory=dict)

class OxygenSensorConfig(BaseModel): # <-- ЗАПРОШЕННАЯ МОДЕЛЬ
    model_config = ConfigDict(populate_by_name=True)
    present: bool
    connection_type: Literal["plc", "rs485"]
    rs485: Optional[RS485Config] = None

class PatientHoistConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    present: bool
    vfd_model: Optional[str] = None
    modbus_unit_id: Optional[int] = None
    max_frequency_hz: float = 25.0
    has_load_cell: bool = False

class LedStripConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    present: bool
    type: Literal["argb", "rgb"] = "rgb"
    led_count: int = 60
    gpio_pin: Optional[int] = None

class PulseSensorConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    present: bool
    connection: Literal["bluetooth"] = "bluetooth"
    ble_device_mac: Optional[str] = None

class SpeakerConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    present: bool
    device: str = "hw:0,0"
    default_volume: int = 70

class ZigbeeRemoteConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    present: bool
    connection: Literal["zigbee"] = "zigbee"
    zigbee_ieee_address: str
    button_map: dict = Field(default_factory=dict)

class HardwareConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    nitrogen_mass_sensor: NitrogenMassSensorConfig
    steam_generator: SteamGeneratorConfig
    oxygen_sensor: OxygenSensorConfig
    patient_hoist: PatientHoistConfig
    led_strip: LedStripConfig
    pulse_sensor: PulseSensorConfig
    speaker: SpeakerConfig
    zigbee_remote: ZigbeeRemoteConfig

class ProcedureDefaults(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    working_time_sec: int
    waiting_time_sec: int
    total_time_sec: int
    target_temperature_c: float

class PrecoolingDefaults(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    target_temperature_c: float
    duration_sec: int

class DryingDefaults(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    duration_sec: int
    target_temperature_c: float

class DefaultsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    procedure: ProcedureDefaults
    precooling: PrecoolingDefaults
    drying: DryingDefaults

class ModbusPLCConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    host: str
    port: int = 502
    unit_id: int = 1
    poll_interval_fast_ms: int = 100
    poll_interval_slow_ms: int = 500

class ZigbeeModemConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    port: str
    baudrate: int = 115200
    protocol: Literal["znp", "xbee_api", "ezsp"] = "znp"
    coordinator_type: Literal["CC2652P", "CC2531", "CC1352P"] = "CC2652P"

class AppConfig(BaseModel): # <-- ЗАПРОШЕННАЯ МОДЕЛЬ
    model_config = ConfigDict(populate_by_name=True)
    network: WifiConfig
    hardware: HardwareConfig
    defaults: DefaultsConfig
    modbus_plc: ModbusPLCConfig
    zigbee_modem: ZigbeeModemConfig


# ================= ТЕЛЕМЕТРИЯ И СТАТУСЫ =================

SystemMode = Literal["stdby", "autotest", "drying", "cooling", "working"]

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
    model_config = ConfigDict(populate_by_name=True)
    SystemStatus: SystemStatusModel
    Telemetry: TelemetryModel

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
    model_config = ConfigDict(populate_by_name=True)
    pipe_hoist: Hoist
    patient_hoist: PatientHoist
    safety: SafetyModel

class StatsModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    patient_hoist: int
    pipe_hoist: int
    steam: int
    charger: int
    heater: int
    exhaust: int


# ================= СИСТЕМНАЯ ИНФОРМАЦИЯ =================

class SystemInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    hostname: str
    os: str
    python_version: str
    app_version: str
    uptime_seconds: float
    started_at: str
    modbus_connected: bool
    zigbee_connected: bool
    o2_sensor_connected: bool
    SystemStatus: SystemStatusModel
    Telemetry: TelemetryModel
    digital_inputs: DigitalInputs
    stats: StatsModel


# ================= СОБЫТИЯ =================

class Event(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    event_id: int
    state_code: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)


# ================= КОМАНДЫ С ФРОНТА =================

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
    model_config = ConfigDict(populate_by_name=True)
    mode_selection: ModeSelection
    technological_settings: TechnologicalSettingsModel

class MotionCommands(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    patient_hoist: Optional[bool] = None
    pipe_hoist: Optional[bool] = None

class UiButtons(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    btn_ok: bool
    btn_esc: bool
    btn_reset_fault: bool
    btn_bypass_confirm: bool

class Security(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    system_code_long: str


# ================= ИСПОЛНИТЕЛЬНЫЕ УСТРОЙСТВА =================

# Команды
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
    model_config = ConfigDict(populate_by_name=True)
    device: Literal["blower", "steam_generator", "patient_hoist", "pipe_hoist", "heater", "exhaust_fan", "exhaust_damper", "led_strip"]
    payload: Union[BlowerCommand, SteamGeneratorCommand, HoistCommand, HeaterCommand, ExhaustFanCommand, ExhaustDamperCommand, LedStripCommand]

class AutocalibrationCommand(BaseModel):
    start: bool = True


# Статусы (Вложенные модели вместо dict для строгой типизации)
class BlowerStatus(BaseModel):
    enabled: bool
    frequency_hz: float

class SteamGeneratorStatus(BaseModel):
    enabled: bool
    frequency_hz: float
    direction: Literal["forward", "reverse"]

class HoistStatus(BaseModel):
    state: Literal["stop", "up", "down"]

class HeaterStatus(BaseModel):
    enabled: bool
    power_w: float

class ExhaustFanStatus(BaseModel):
    enabled: bool

class ExhaustDamperStatus(BaseModel):
    state: Literal["open", "closed"]

class LedStripStatus(BaseModel):
    enabled: bool
    color: str
    type: Literal["argb", "rgb"]

class ActuatorStatus(BaseModel): # <-- ЗАПРОШЕННАЯ МОДЕЛЬ
    model_config = ConfigDict(populate_by_name=True)
    blower: BlowerStatus
    steam_generator: SteamGeneratorStatus
    patient_hoist: HoistStatus
    pipe_hoist: HoistStatus
    heater: HeaterStatus
    exhaust_fan: ExhaustFanStatus
    exhaust_damper: ExhaustDamperStatus
    led_strip: LedStripStatus


# ================= ОТВЕТЫ API =================

class CommandResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    status: Literal["success", "error", "timeout"]
    message: str
    event_id: Optional[int] = None
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
