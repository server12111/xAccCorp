# -*- coding: utf-8 -*-
"""Автоустановка зависимостей при первом запуске.

Модуль специально не импортирует aiogram: он вызывается ДО остальных
импортов, чтобы pip успел поставить недостающее.
"""
import importlib.util
import subprocess
import sys


def ensure_dependencies() -> None:
    packages = {
        "aiogram": "aiogram>=3.4,<4.0",
        "aiosqlite": "aiosqlite",
        "aiohttp": "aiohttp",
        "dotenv": "python-dotenv",
    }
    missing = [package for module, package in packages.items()
               if importlib.util.find_spec(module) is None]
    if not missing:
        return

    print("[AUTO-INSTALL] Не найдены библиотеки: " + ", ".join(missing), flush=True)
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "--disable-pip-version-check", *missing
        ])
    except Exception as first_error:
        # На некоторых образах Python pip не активирован изначально.
        try:
            import ensurepip
            ensurepip.bootstrap()
            subprocess.check_call([
                sys.executable, "-m", "pip", "install",
                "--disable-pip-version-check", *missing
            ])
        except Exception as second_error:
            raise RuntimeError(
                "Не удалось автоматически установить зависимости "
                f"{missing}. Проверь доступ к интернету и разрешение на pip. "
                f"Ошибка: {second_error}"
            ) from first_error
