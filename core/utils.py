import json
import os
import sys


def resource_path(relative_path):
    """Получает абсолютный путь к файлу, учитывая запуск из .exe"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def load_config(file_name):
    """Читает JSON-файл и возвращает словарь"""
    try:
        with open(resource_path(file_name), "r") as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"Ошибка: Файл {file_name} не найден")
        return {}
    except json.JSONDecodeError:
        print(f"Ошибка: Некорректный JSON в файле {file_name}")
        return {}

