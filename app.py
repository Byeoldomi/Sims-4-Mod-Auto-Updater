"""하위 호환용 GUI 진입점 래퍼.

GUI 구현은 main.py로 통합되었습니다.
"""

from main import (
    BASE_DIR,
    BUNDLE_DIR,
    Sims4ModUpdaterAPI,
    create_app_window,
    main,
    resolve_ui_entry,
)

__all__ = [
    "BASE_DIR",
    "BUNDLE_DIR",
    "Sims4ModUpdaterAPI",
    "create_app_window",
    "main",
    "resolve_ui_entry",
]

if __name__ == "__main__":
    create_app_window()
