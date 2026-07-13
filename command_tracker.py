import asyncio
import logging
from typing import Optional, Dict
from datetime import datetime, timedelta
import models

logger = logging.getLogger(__name__)


class CommandTracker:
    """
    Отслеживает команды, отправленные на ПЛК, и ждёт подтверждения (event_id).
    Логика: фронт шлёт команду → бэк отправляет в ПЛК → ждёт event_id → возвращает фронт результат.
    """
    
    def __init__(self, timeout_sec: float = 5.0):
        self.timeout_sec = timeout_sec
        self.pending_commands: Dict[str, asyncio.Event] = {}
        self.last_event_id: Optional[int] = None
        self._lock = asyncio.Lock()
    
    async def send_command(self, command_id: str) -> bool:
        """
        Регистрирует команду как ожидающую подтверждения.
        Возвращает True, если команда зарегистрирована.
        """
        async with self._lock:
            if command_id in self.pending_commands:
                logger.warning(f"⚠️ Command {command_id} already pending")
                return False
            
            self.pending_commands[command_id] = asyncio.Event()
            logger.debug(f" Command {command_id} sent, waiting for confirmation...")
            return True
    
    async def wait_for_confirmation(self, command_id: str) -> Optional[models.Event]:
        """
        Ждёт подтверждения от ПЛК (event_id).
        Возвращает Event с event_id или None при таймауте.
        """
        async with self._lock:
            event = self.pending_commands.get(command_id)
            if not event:
                logger.error(f"❌ Command {command_id} not found")
                return None
        
        try:
            # Ждём сигнал с таймаутом
            await asyncio.wait_for(event.wait(), timeout=self.timeout_sec)
            
            async with self._lock:
                event_id = self.last_event_id
            
            logger.info(f"✅ Command {command_id} confirmed with event_id={event_id}")
            return models.Event(event_id=event_id) if event_id else None
        
        except asyncio.TimeoutError:
            logger.error(f"⏱️ Command {command_id} timeout ({self.timeout_sec}s)")
            return None
        finally:
            async with self._lock:
                if command_id in self.pending_commands:
                    del self.pending_commands[command_id]
    
    async def confirm_command(self, event_id: int):
        """
        Вызывается при получении event_id от ПЛК.
        Уведомляет все ожидающие команды.
        """
        async with self._lock:
            self.last_event_id = event_id
            
            # Уведомляем все ожидающие команды
            for cmd_id, event in self.pending_commands.items():
                event.set()
                logger.debug(f"📥 Command {cmd_id} confirmed by event_id={event_id}")
    
    def clear(self):
        """Очищает все ожидающие команды"""
        self.pending_commands.clear()
        self.last_event_id = None


# Глобальный экземпляр
command_tracker = CommandTracker(timeout_sec=5.0)