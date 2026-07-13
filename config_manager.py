import json
import logging
from pathlib import Path
from pydantic import ValidationError
import models

logger = logging.getLogger(__name__)
CONFIG_PATH = Path("config.json")


class ConfigManager:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self.config: models.AppConfig | None = None

    def load(self) -> models.AppConfig:
        if not self.path.exists():
            raise FileNotFoundError(f"Config file not found: {self.path}")
        
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.config = models.AppConfig(**raw)
            logger.info(f"✅ Config loaded from {self.path}")
            return self.config
        except ValidationError as e:
            logger.error(f"❌ Config validation error: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"❌ Config JSON parse error: {e}")
            raise

    def save(self) -> None:
        if self.config is None:
            raise RuntimeError("Config not loaded")
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.config.model_dump(), f, indent=2, ensure_ascii=False)
        logger.info(f"💾 Config saved to {self.path}")

    def get(self) -> models.AppConfig:
        if self.config is None:
            self.load()
        return self.config


# Глобальный экземпляр
config_manager = ConfigManager()