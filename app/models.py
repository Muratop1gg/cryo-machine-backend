"""
Pydantic-модели, которые повторяют TS-интерфейсы из README фронтенда.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Общий ответ
# ---------------------------------------------------------------------------

class BasicResponse(BaseModel):
    status_code: str
    message: Optional[str] = None


# ---------------------------------------------------------------------------
# /api/change-procedure-state/
# ---------------------------------------------------------------------------

ProcedureAction = Literal["stop", "pause", "resume", "start"]


class ChangeProcedureStateRequest(BaseModel):
    action: ProcedureAction


# ---------------------------------------------------------------------------
# /api/self-test/
# ---------------------------------------------------------------------------

SelfTestType = Literal["dry", "default"]


class StartSelfTestRequest(BaseModel):
    type: SelfTestType


# ---------------------------------------------------------------------------
# /api/update-settings и /api/settings
# ---------------------------------------------------------------------------

class WifiSettings(BaseModel):
    ssid: str
    # пароль во "внешний мир" не отдаём, только его длину,
    # но при обновлении настроек фронт присылает реальный пароль в этом же поле.
    password_len: Optional[int] = None
    password: Optional[str] = Field(
        default=None,
        description="Реальный пароль, приходит только в POST /api/update-settings",
        exclude=True,
    )


class SettingsUpdateRequest(BaseModel):
    led_color: Optional[str] = None
    time_s1_sec: Optional[float] = None   # работа
    time_s2_sec: Optional[float] = None   # ожидание
    time_s3_sec: Optional[float] = None   # общая длительность процедуры
    temperature_sp1: Optional[float] = None  # уставка s1
    temperature_sp2: Optional[float] = None  # уставка s2
    wifi: Optional[WifiSettings] = None


BlockedState = Literal["yes", "no", "unlocking"]


class SettingsResponse(BaseModel):
    led_color: str
    blocked: BlockedState
    time_s1_sec: float
    time_s2_sec: float
    time_s3_sec: float
    temperature_sp1: float
    temperature_sp2: float
    wifi: Optional[WifiSettings] = None


# ---------------------------------------------------------------------------
# /api/config
# ---------------------------------------------------------------------------
# Формат конфига определяется исключительно содержимым config.json на диске.
# Бэкенд не валидирует структуру и отдаёт/сохраняет её "как есть".

SystemConfiguration = dict[str, Any]


# ---------------------------------------------------------------------------
# /api/unlock, /api/unlock/check
# ---------------------------------------------------------------------------

class CheckUnlockCodeRequest(BaseModel):
    code: str


class CheckUnlockCodeResponse(BaseModel):
    accepted: bool
    days_left: int


# ---------------------------------------------------------------------------
# WebSocket: входящие для фронта (сервер -> клиент)
# ---------------------------------------------------------------------------

class DigitalInputsPipeHoist(BaseModel):
    lsw_top_emergency: bool
    lsw_top_working: bool
    lsw_bottom_working: bool
    lsw_bottom_emergency: bool


class DigitalInputsPatientHoist(BaseModel):
    lsw_top_emergency: bool
    lsw_top_working: bool
    lsw_bottom_working: bool
    lsw_bottom_emergency: bool
    patient_present: bool


class DigitalInputsSafety(BaseModel):
    estop_pressed: bool
    cabinet_door_open: bool


class DigitalInputs(BaseModel):
    pipe_hoist: DigitalInputsPipeHoist
    patient_hoist: DigitalInputsPatientHoist
    safety: DigitalInputsSafety


class Stats(BaseModel):
    patient_hoist: Literal[0, 1, 2, 3]
    pipe_hoist: Literal[0, 1, 2, 3]
    steam: Literal[0, 1, 2, 3]
    charger: Literal[0, 1, 2, 3]
    heater: Literal[0, 1, 2, 3]
    exhaust: Literal[0, 1, 2, 3]


class SensorData(BaseModel):
    t1: float
    t2: float
    t3: float
    t4: float
    humidity: float
    oxygen: float
    nitrogen_mass: Optional[float] = None


class DiagnosticsTest(BaseModel):
    running: bool
    type: Optional[Literal["self_test", "dry_self_test"]] = None
    stage: Optional[str] = None


class Diagnostics(BaseModel):
    test: DiagnosticsTest


class WSSensorsData(BaseModel):
    digital_inputs: DigitalInputs
    stats: Stats
    sensor_data: SensorData
    diagnostics: Diagnostics


class WSEvent(BaseModel):
    event_id: int


# ---------------------------------------------------------------------------
# WebSocket: исходящие от фронта (клиент -> сервер)
# ---------------------------------------------------------------------------

ControllerButton = Literal["OK", "ESC", "RESET", "CONFIRM"]


class WSControllerButtonPressed(BaseModel):
    button: ControllerButton


class WSControllerButtonReleased(BaseModel):
    """У этого события нет данных (`no data` в README)."""


class WSMachineControl(BaseModel):
    # В README поле называется "type" (тип управляемого узла), но само
    # WS-сообщение уже обёрнуто в конверт {"event": "machine_controls", "payload": {...}}
    # (см. ws_manager.py), поэтому здесь оно переименовано во избежание путаницы
    # с полем "event" конверта. На проводе фронт передаёт ключ "type" (алиас).
    control_type: str = Field(alias="type")
    value: bool

    model_config = {"populate_by_name": True}


class WSSteamSpeedControl(BaseModel):
    value: int = Field(ge=0, le=50)


# ---------------------------------------------------------------------------
# Конверт для ВСЕХ WS-сообщений в обе стороны:
#   {"event": "<имя события из README>", "payload": {...}}
# ---------------------------------------------------------------------------

class WSEnvelope(BaseModel):
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)
