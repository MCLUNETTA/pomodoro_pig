"""Установщик зависимостей и точка запуска проекта.

Запуск:
    python setup.py
    python setup.py --test

Сначала проверяются нужные модули. Если чего-то нет — пакеты ставятся
с зеркала PyPI, затем запускается main.py с теми же аргументами.
"""

import importlib
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MAIN_SCRIPT = BASE_DIR / "main.py"

MIRROR = "https://pypi.mirrors.ustc.edu.cn/simple/"
MIRROR_HOST = "pypi.mirrors.ustc.edu.cn"

# Имя пакета в pip -> имя модуля, который нужно проверить.
PACKAGES = {
    "PySide6": "PySide6",
    "google-auth": "google.auth",
    "google-auth-oauthlib": "google_auth_oauthlib",
    "google-api-python-client": "googleapiclient",
}


def find_missing():
    missing = []
    for package, module in PACKAGES.items():
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(package)
    return missing


def install(missing):
    if not missing:
        print("Все нужные модули уже установлены.")
        return

    print("Устанавливаем с зеркала", MIRROR)
    print("Пакеты:", ", ".join(missing))

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "-i",
        MIRROR,
        "--trusted-host",
        MIRROR_HOST,
        *missing,
    ]

    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        print("Не удалось установить зависимости:", exc)
        raise SystemExit(exc.returncode)


def main():
    missing = find_missing()
    install(missing)

    print("Запускаем", MAIN_SCRIPT.name)
    try:
        result = subprocess.run(
            [sys.executable, str(MAIN_SCRIPT), *sys.argv[1:]],
            cwd=BASE_DIR,
        )
    except KeyboardInterrupt:
        raise SystemExit(130)

    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
