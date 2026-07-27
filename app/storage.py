"""
Простое хранилище на JSON-файлах для конфига и настроек.

CONFIG_PATH  - произвольный JSON, который целиком отдаётся/принимается на /api/config.
SETTINGS_PATH - структурированные настройки (см. models.SettingsResponse).

Оба файла лежат в директории DATA_DIR, которую можно переопределить
переменной окружения VENT_DATA_DIR (удобно для тестов / разных сборок /
прод-деплоя на мини-ПК).

По умолчанию используется папка `data/` в корне проекта - она создаётся
автоматически и не требует прав root (в отличие от системных путей вроде
/var/lib/...). Для прод-окружения на мини-ПК можно явно задать системный
путь, например:
    export VENT_DATA_DIR=/var/lib/vent-backend
(тогда убедитесь, что у пользователя, от которого запущен процесс, есть
права на запись в эту директорию - создайте её и chown заранее).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

DATA_DIR = Path(os.environ.get("VENT_DATA_DIR", str(_DEFAULT_DATA_DIR)))
CONFIG_PATH = DATA_DIR / "config.json"
SETTINGS_PATH = DATA_DIR / "settings.json"

_lock = asyncio.Lock()

DEFAULT_SETTINGS: dict[str, Any] = {
    "led_color": "#ffffff",
    "blocked": "no",
    "time_s1_sec": 0,
    "time_s2_sec": 0,
    "time_s3_sec": 0,
    "temperature_sp1": 0,
    "temperature_sp2": 0,
    "wifi": None,
}

DEFAULT_CONFIG: dict[str, Any] = {}


def _ensure_data_dir() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise PermissionError(
            f"Нет прав на создание/запись директории {DATA_DIR}. "
            f"Укажите доступную папку через переменную окружения VENT_DATA_DIR "
            f"(например: export VENT_DATA_DIR=~/vent-data)."
        ) from exc


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    _ensure_data_dir()
    if not path.exists():
        _write_json(path, default)
        return dict(default)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    _ensure_data_dir()
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)  # атомарная замена, чтобы не словить битый файл


async def read_config() -> dict[str, Any]:
    async with _lock:
        return await asyncio.to_thread(_read_json, CONFIG_PATH, DEFAULT_CONFIG)


async def write_config(data: dict[str, Any]) -> None:
    async with _lock:
        await asyncio.to_thread(_write_json, CONFIG_PATH, data)


async def read_settings() -> dict[str, Any]:
    async with _lock:
        return await asyncio.to_thread(_read_json, SETTINGS_PATH, DEFAULT_SETTINGS)


async def write_settings(data: dict[str, Any]) -> None:
    async with _lock:
        await asyncio.to_thread(_write_json, SETTINGS_PATH, data)
