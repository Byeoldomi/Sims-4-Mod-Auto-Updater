import datetime
import shutil
from pathlib import Path
from typing import List, Optional

class BackupManager:
    """모드 백업 및 롤백 관리자"""

    def __init__(self, backup_dir: Path):
        self.backup_dir = backup_dir
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup_session(self, label: str = "auto") -> Path:
        """새 백업 세션 폴더를 생성합니다."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_name = f"{label}_{timestamp}"
        session_dir = self.backup_dir / session_name
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def backup_item(self, source_path: Path, session_dir: Path) -> Optional[Path]:
        """지정된 파일 또는 폴더를 백업 세션 디렉터리로 복사합니다."""
        if not source_path.exists():
            return None

        target_path = session_dir / source_path.name
        if source_path.is_file():
            shutil.copy2(source_path, target_path)
        elif source_path.is_dir():
            shutil.copytree(source_path, target_path, dirs_exist_ok=True)

        return target_path

    def list_backups(self) -> List[Path]:
        """존재하는 백업 세션 목록을 반환합니다 (최신순)."""
        if not self.backup_dir.exists():
            return []
        sessions = [p for p in self.backup_dir.iterdir() if p.is_dir()]
        return sorted(sessions, key=lambda p: p.stat().st_mtime, reverse=True)

    def restore_backup(self, session_dir: Path, mods_folder: Path) -> None:
        """백업 세션의 파일들을 Mods 폴더로 복원합니다."""
        if not session_dir.exists() or not session_dir.is_dir():
            raise FileNotFoundError(f"백업 폴더를 찾을 수 없습니다: {session_dir}")

        for item in session_dir.iterdir():
            target = mods_folder / item.name
            if item.is_file():
                shutil.copy2(item, target)
            elif item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
