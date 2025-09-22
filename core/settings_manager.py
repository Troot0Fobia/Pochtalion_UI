import sys
import appdirs
import json
from pathlib import Path
from core.logger import setup_logger
from core.utils import load_config
from shutil import copyfile

class SettingsManager:
    def __init__(self, main_window):
        # Динамический путь в зависимости от режима выполнения
        if getattr(sys, '_MEIPASS', False):
            base_path = Path(sys._MEIPASS)
        else:
            base_path = Path(__file__).parent.parent
        self.settings_dir = base_path / "settings"
        self.default_settings_path = self.settings_dir / 'defaults.json'
        self.settings_file_path = self.settings_dir / 'settings.json'
        self.default_settings = load_config(self.default_settings_path)
        self.main_window = main_window
        self.logger = setup_logger("Pochtalion.Settings", "settings_manager.log")
        self.settings = None

    def start(self):
        # Используем appdirs для хранения настроек в AppData
        self.app_dir = Path(appdirs.user_data_dir("Pochtalion", "Pochtalion"))
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.settings_file_path = self.app_dir / "settings.json"

        if not self.default_settings_path.exists():
            self.logger.error(f"Default settings file not found at {self.default_settings_path}")
            self.main_window.show_notification("Ошибка", "Файл стандартных настроек не существует")
            return False

        if not self.settings_file_path.exists():
            try:
                copyfile(self.default_settings_path, self.settings_file_path)
            except Exception as e:
                self.logger.error(f"Error while creating custom settings: {e}", exc_info=True)
                return False

        try:
            self._load()
        except json.JSONDecodeError as e:
            self.logger.error(f"Error while decoding json settings file: {e}", exc_info=True)
            return False

        return True

    def _load(self):
        with self.settings_file_path.open('r', encoding='utf-8') as f:
            self.settings = json.load(f)

    def update_settings(self, key, value):
        self.logger.info(f"User changes settings '{key}': {value}")
        self.settings[key] = value
        if key == 'api_keys':
            self.main_window.initSessionManager()

    def get_setting(self, key):
        return self.settings.get(key, None)

    def get_settings(self):
        return self.settings

    def save_settings(self):
        with self.settings_file_path.open('w', encoding='utf-8') as f:
            json.dump(self.settings, f, indent=4, ensure_ascii=False)

    def reset_defaults(self):
        try:
            copyfile(self.default_settings_path, self.settings_file_path)
        except Exception as e:
            self.logger.error(f"Error while restoring default settings: {e}", exc_info=True)
            self.main_window.show_notification("Ошибка", "Ошибка во время восстановления стандартных настроек")
            return

        try:
            self._load()
        except json.JSONDecodeError as e:
            self.logger.error(f"Error while decoding json settings file: {e}", exc_info=True)