import json
import os
from pathlib import Path
from typing import Optional, Dict, Any

DEFAULT_CONFIG_PATH = Path("config.json")

def detect_sims4_mods_folder() -> Optional[Path]:
    """심즈 4 기본 Mods 폴더 위치를 자동으로 탐색합니다 (OneDrive 경로 포함)."""
    candidates = [
        # 일반 내 문서
        Path.home() / "Documents" / "Electronic Arts" / "The Sims 4" / "Mods",
        # OneDrive 동기화 문서
        Path.home() / "OneDrive" / "Documents" / "Electronic Arts" / "The Sims 4" / "Mods",
        Path.home() / "OneDrive" / "문서" / "Electronic Arts" / "The Sims 4" / "Mods",
        Path.home() / "문서" / "Electronic Arts" / "The Sims 4" / "Mods",
    ]

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate

    return None

class ConfigManager:
    """설정 관리 클래스"""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self.config: Dict[str, Any] = self.load()

    def get_default_config(self) -> Dict[str, Any]:
        detected_mods = detect_sims4_mods_folder()
        return {
            "mods_folder": str(detected_mods) if detected_mods else "",
            "backup_folder": "backups",
            "auto_backup": True,
            "manifest_path": "mods_manifest.json",
        }

    def load(self) -> Dict[str, Any]:
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    defaults = self.get_default_config()
                    defaults.update(data)

                    # 다른 컴퓨터로 이동하여 기존 mods_folder 경로가 존재하지 않는 경우, 현재 PC의 기본 Mods 경로로 자동 재탐색
                    saved_mods = defaults.get("mods_folder", "")
                    if not saved_mods or not Path(saved_mods).exists():
                        detected = detect_sims4_mods_folder()
                        if detected:
                            defaults["mods_folder"] = str(detected)

                    # 다른 컴퓨터의 드라이브/절대경로가 박혀 있어 접근 불가능한 backup_folder는 상대 경로("backups")로 정규화
                    saved_backup = defaults.get("backup_folder", "backups")
                    if Path(saved_backup).is_absolute():
                        defaults["backup_folder"] = "backups"

                    return defaults
            except Exception:
                pass
        defaults = self.get_default_config()
        self.save(defaults)
        return defaults

    def save(self, data: Optional[Dict[str, Any]] = None) -> None:
        if data is not None:
            self.config = data
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)

    @property
    def mods_folder(self) -> Path:
        return Path(self.config.get("mods_folder", ""))

    @property
    def backup_folder(self) -> Path:
        return Path(self.config.get("backup_folder", "backups"))

    @property
    def auto_backup(self) -> bool:
        return bool(self.config.get("auto_backup", True))

    @property
    def manifest_path(self) -> Path:
        return Path(self.config.get("manifest_path", "mods_manifest.json"))
