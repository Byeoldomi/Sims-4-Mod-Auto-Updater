import datetime
import re
import shutil
from pathlib import Path
from typing import List, Optional

from src.utils import is_safe_subpath, log_security_warning


class BackupManager:
    """모드 백업 및 롤백 관리자"""

    def __init__(self, backup_dir: Path):
        self.backup_dir = backup_dir.resolve()
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup_session(self, label: str = "auto") -> Path:
        """새 백업 세션 폴더를 생성합니다 (레이블 경로 조작 방지 포함)."""
        safe_label = Path(str(label or "auto").replace("\\", "/")).name
        safe_label = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", safe_label).strip(" .")
        if not safe_label or safe_label in (".", ".."):
            safe_label = "auto"

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        session_name = f"{safe_label}_{timestamp}"
        session_dir = (self.backup_dir / session_name).resolve()
        if not is_safe_subpath(session_dir, self.backup_dir):
            log_security_warning(f"비정상 백업 세션 경로 차단: '{session_dir}'")
            raise ValueError(f"허용되지 않는 백업 세션 이름입니다: {label}")
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def backup_item(self, source_path: Path, session_dir: Path) -> Optional[Path]:
        """지정된 파일 또는 폴더를 백업 세션 디렉터리로 복사합니다 (심볼릭 링크 제외)."""
        if not source_path.exists() or source_path.is_symlink():
            return None

        session_resolved = session_dir.resolve()
        safe_name = Path(source_path.name).name
        target_path = (session_resolved / safe_name).resolve()
        if not is_safe_subpath(target_path, session_resolved):
            log_security_warning(f"비정상 백업 항목 경로 차단: '{target_path}'")
            return None

        if source_path.is_file():
            shutil.copy2(source_path, target_path)
        elif source_path.is_dir():
            shutil.copytree(source_path, target_path, symlinks=False, dirs_exist_ok=True)

        return target_path

    def list_backups(self) -> List[Path]:
        """존재하는 백업 세션 목록을 반환합니다 (최신순)."""
        if not self.backup_dir.exists():
            return []
        sessions = [
            p for p in self.backup_dir.iterdir()
            if p.is_dir() and not p.is_symlink() and is_safe_subpath(p, self.backup_dir)
        ]
        return sorted(sessions, key=lambda p: p.stat().st_mtime, reverse=True)

    def restore_backup(self, session_dir: Path, mods_folder: Path) -> None:
        """백업 세션의 파일들을 Mods 폴더로 안전하게 복원합니다."""
        session_resolved = session_dir.resolve()
        if not session_resolved.exists() or not session_resolved.is_dir():
            raise FileNotFoundError(f"백업 폴더를 찾을 수 없습니다: {session_dir}")
        if not is_safe_subpath(session_resolved, self.backup_dir):
            log_security_warning(f"허용되지 않은 외부 백업 폴더 복원 시도 차단: '{session_resolved}'")
            raise ValueError("백업 관리 폴더 외부의 경로에서는 복원할 수 없습니다.")

        mods_resolved = mods_folder.resolve()
        for item in session_resolved.iterdir():
            if item.is_symlink():
                continue
            target = (mods_resolved / item.name).resolve()
            if not is_safe_subpath(target, mods_resolved):
                log_security_warning(f"백업 복원 중 경로 이탈 차단: '{target}'")
                raise ValueError(f"복원 대상 경로가 Mods 폴더를 벗어납니다: {item.name}")
            if item.is_file():
                shutil.copy2(item, target)
            elif item.is_dir():
                shutil.copytree(item, target, symlinks=False, dirs_exist_ok=True)
