import json
from shutil import copyfile

from core.logger import setup_logger
from core.paths import DEFAULTS, SETTINGS
from core.utils import load_config


class SettingsManager:

    def __init__(self, main_window):
        # defaults.json ships with the app (read-only); settings.json is user data.
        self.default_settings_path = DEFAULTS
        self.settings_file_path = SETTINGS / "settings.json"
        self.default_settings = load_config(self.default_settings_path)
        self.main_window = main_window
        self.logger = setup_logger("Pochtalion.Settings", "settings_manager.log")
        self.settings = None

    def start(self):
        SETTINGS.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_settings()

        if not self.default_settings_path.exists():
            self.logger.error(
                f"Default settings file not found at {self.default_settings_path}"
            )
            self.main_window.show_notification(
                "Ошибка", "Файл стандартных настроек не существует"
            )
            return False

        if not self.settings_file_path.exists():
            try:
                copyfile(self.default_settings_path, self.settings_file_path)
            except Exception as e:
                self.logger.error(
                    f"Error while creating custom settings: {e}", exc_info=True
                )
                return False

        try:
            self._load()
        except json.JSONDecodeError as e:
            self.logger.error(
                f"Error while decoding json settings file: {e}", exc_info=True
            )
            return False

        return True

    def _migrate_legacy_settings(self):
        """Older builds kept settings.json in the appdirs data directory. If that file
        exists and the current one does not, move it to the new location once."""
        if self.settings_file_path.exists():
            return
        try:
            from platformdirs import PlatformDirs

            legacy = (
                PlatformDirs("Pochtalion", appauthor="Pochtalion").user_data_path
                / "settings.json"
            )
            if legacy.resolve() == self.settings_file_path.resolve():
                return
            if legacy.exists():
                copyfile(legacy, self.settings_file_path)
                self.logger.info("Migrated legacy settings from %s", legacy)
        except Exception as e:
            self.logger.warning("Legacy settings migration skipped: %s", e)

    def _load(self):
        with self.settings_file_path.open("r", encoding="utf-8") as f:
            self.settings = json.load(f)
        missing = {k: v for k, v in self.default_settings.items() if k not in self.settings}
        if missing:
            self.settings.update(missing)
            self.save_settings()
            self.logger.info("Merged %d new default setting(s): %s", len(missing), list(missing.keys()))

    def update_settings(self, key, value):
        if self.settings is None:
            return
        self.settings[key] = value
        if key == "api_keys":
            self.main_window.initSessionManager()

    def get_setting(self, key):
        if self.settings:
            return self.settings.get(key, None)
        else:
            return None

    def get_settings(self):
        return self.settings

    def save_settings(self):
        with self.settings_file_path.open("w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=4, ensure_ascii=False)

    def reset_defaults(self):
        try:
            copyfile(self.default_settings_path, self.settings_file_path)
        except Exception as e:
            self.logger.error(
                f"Error while restoring default settings: {e}", exc_info=True
            )
            self.main_window.show_notification(
                "Ошибка", "Ошибка во время восстановления стандартных настроек"
            )
            return

        try:
            self._load()
        except json.JSONDecodeError as e:
            self.logger.error(
                f"Error while decoding json settings file: {e}", exc_info=True
            )

