import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Карта расшифровки event_id (группа, подгруппа, параметр)
STATE_DESCRIPTIONS = {
    1: {0: "Простой: стоп", 1: "Простой: сон", 2: "Простой: авария"},
    2: {0: "Процедура: стоп", 1: "Процедура: работа", 2: "Процедура: авария"},
    3: {0: "Прохлаживание: стоп", 1: "Прохлаждение: активно", 2: "Прохлаживание: авария"},
    4: {0: "Сушка: стоп", 1: "Сушка: активно", 2: "Сушка: авария"},
    5: {0: "Загрузка азота: стоп", 1: "Загрузка азота: работа", 2: "Загрузка азота: авария"},
    6: {0: "Сервис: стоп", 1: "Сервис: работа", 2: "Сервис: авария"},
}

LOGS_DIR = Path("logs")
ARCHIVE_DIR = LOGS_DIR / "archive"
LAST_LOG = LOGS_DIR / "last_procedure.log"


class ProcedureLogger:
    def __init__(self):
        LOGS_DIR.mkdir(exist_ok=True)
        ARCHIVE_DIR.mkdir(exist_ok=True)
        
        self.current_group: Optional[int] = None
        self.procedure_start_time: Optional[datetime] = None

    def _parse_event_id(self, event_id: int) -> tuple[int, int, int]:
        """Разбирает event_id на группу, подгруппу, параметр"""
        s = str(event_id).zfill(3)
        return int(s[0]), int(s[1]), int(s[2])

    def _get_description(self, group: int, subgroup: int, param: int) -> str:
        group_desc = STATE_DESCRIPTIONS.get(group, {}).get(subgroup, f"Состояние {group}{subgroup}")
        return f"{group_desc} (парам={param})"

    def _archive_previous(self):
        """Архивирует предыдущий лог, если он существует"""
        if LAST_LOG.exists():
            if self.procedure_start_time:
                ts = self.procedure_start_time.strftime("%Y%m%d_%H%M%S")
            else:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_path = ARCHIVE_DIR / f"procedure_{ts}.log"
            LAST_LOG.rename(archive_path)
            logger.info(f"📦 Previous log archived to {archive_path}")

    # === ИСПРАВЛЕНИЕ ЗДЕСЬ: extra: Optional[dict] = None ===
    def log_event(self, event_id: int, state_code: Optional[str] = None, extra: Optional[dict] = None):
        """Логирует изменение event_id. Автоматически открывает новый лог при смене группы."""
        group, subgroup, param = self._parse_event_id(event_id)
        description = self._get_description(group, subgroup, param)
        timestamp = datetime.now()
        
        # Если группа сменилась — новая процедура
        if self.current_group is None or group != self.current_group:
            self._start_new_procedure(group, timestamp)
        
        # Формируем строку лога
        line = f"[{timestamp:%Y-%m-%d %H:%M:%S.%f}] event_id={event_id:03d} state={state_code or '-'} | {description}"
        if extra:
            line += f" | extra={extra}"
        line += "\n"
        
        # Пишем в файл
        try:
            with open(LAST_LOG, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            logger.error(f"❌ Failed to write procedure log: {e}")

    def _start_new_procedure(self, group: int, timestamp: datetime):
        """Открывает новый лог-файл"""
        if self.current_group is not None:
            self._archive_previous()
        
        self.current_group = group
        self.procedure_start_time = timestamp
        
        group_names = {
            1: "Простой", 2: "Процедура", 3: "Прохлаждение", 
            4: "Сушка", 5: "Загрузка N2", 6: "Сервис"
        }
        group_name = group_names.get(group, f"Группа {group}")
        
        # Заголовок нового лога
        header = (
            f"{'=' * 70}\n"
            f"PROCEDURE LOG STARTED\n"
            f"Start time: {timestamp:%Y-%m-%d %H:%M:%S}\n"
            f"Group: {group} ({group_name})\n"
            f"{'=' * 70}\n\n"
        )
        with open(LAST_LOG, "w", encoding="utf-8") as f:
            f.write(header)
        
        logger.info(f"📝 New procedure log started (group={group})")

    def close(self):
        """Завершает текущую процедуру"""
        if self.current_group is not None:
            timestamp = datetime.now()
            try:
                with open(LAST_LOG, "a", encoding="utf-8") as f:
                    f.write(f"\n{'=' * 70}\nPROCEDURE LOG ENDED: {timestamp:%Y-%m-%d %H:%M:%S}\n{'=' * 70}\n")
            except Exception as e:
                logger.error(f"❌ Failed to close procedure log: {e}")
            
            self._archive_previous()
            self.current_group = None
            self.procedure_start_time = None
            logger.info("📝 Procedure log closed")


# Глобальный экземпляр
procedure_logger = ProcedureLogger()
