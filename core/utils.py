import json

from core.paths import resource_path

__all__ = ["resource_path", "load_config"]


def load_config(file_name):
    """Читает JSON-файл и возвращает словарь"""
    try:
        with open(resource_path(file_name), "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"Ошибка: Файл {file_name} не найден")
        return {}
    except json.JSONDecodeError:
        print(f"Ошибка: Некорректный JSON в файле {file_name}")
        return {}
