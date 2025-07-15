from core.paths import SETTINGS
from core.logger import setup_logger
from shutil import copyfile
import json

class SettingsManager:
    def __init__(self, main_window):
        self.default_settings = SETTINGS / 'defaults.json'
        self.settings_file = SETTINGS / 'settings.json'
        self.main_window = main_window
        self.logger = setup_logger("Pochtalion.Settings", "settings_manager.log")
        self.settings = None


    def start(self):
        if not self.default_settings.exists():
            self.logger.error("Default settings file does not exist")
            self.main_window.show_notification("Ошибка", "Файл стандартных настроек не существует")
            return False

        if not self.settings_file.exists():
            try:
                copyfile(self.default_settings, self.settings_file)
            except Exception as e:
                self.logger.error(f"Error while creating custom settings", exc_info=True)
                return False

        try:
            self._load()
        except json.JSONDecodeError:
            self.logger.error('Error while decoding json settings file', exc_info=True)
            return False

        return True


    def _load(self):
        with self.settings_file.open('r', encoding='utf-8') as f:
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
        with self.settings_file.open('w', encoding='utf-8') as f:
            json.dump(self.settings, f, indent=4, ensure_ascii=False)

    
    def reset_defaults(self):
        try:
            copyfile(self.default_settings, self.settings_file)
        except Exception as e:
            self.logger.error("Error while restore defaults settings", exc_info=True)
            self.main_window.show_notification("Ошибка", "Ошибка во время восстановления стандартных настроек")
            return

        try:
            self._load()
        except json.JSONDecodeError:
            self.logger.error('Error while decoding json settings file', exc_info=True)
        
