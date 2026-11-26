import datetime
import email.utils
import hashlib
import ipaddress
import logging
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
import webbrowser
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple, Union
import requests
import requests.adapters

try:
    import certifi
except ImportError:
    certifi = None  # type: ignore[assignment]

# 아카이브 보안 제한 상수 (Zip Bomb 및 디스크 고갈 방지)
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 단일 다운로드 최대 2GB
MAX_ZIP_ENTRIES = 10_000  # 단일 압축파일 내 최대 엔트리 개수
MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024  # 압축 해제 총량 최대 4GB

# 네트워크 보안 및 타임아웃 상수 (무한 대기 및 프로토콜 다운그레이드 방지)
DEFAULT_CONNECT_TIMEOUT: float = 10.0  # TCP/TLS 핸드셰이크 기본 타임아웃(초)
DEFAULT_READ_TIMEOUT: float = 15.0  # 소켓 응답 수신 기본 타임아웃(초)
DEFAULT_DOWNLOAD_TIMEOUT: Tuple[float, float] = (10.0, 30.0)  # 대용량 모드 다운로드 타임아웃(연결, 읽기)
MAX_NETWORK_TIMEOUT: float = 60.0  # 단일 요청 최대 허용 타임아웃 상한(초)
MAX_STREAM_ELAPSED_SECONDS: float = 300.0  # 스트리밍 다운로드 전체 최대 경과 시간(Slowloris 무한 대기 차단)
MAX_HTTPS_REDIRECTS: int = 10  # 최대 허용 HTTPS 리다이렉트 홉 수
REDIRECT_STATUS_CODES: FrozenSet[int] = frozenset({301, 302, 303, 307, 308})

# [블랙리스트] 압축 해제 전 엔트리 헤더 검사 단계에서 단 하나라도 발견 시 즉시 격리·삭제할 실행/스크립트 계열 위험 확장자
DANGEROUS_ARCHIVE_EXTENSIONS: FrozenSet[str] = frozenset({
    ".exe",
    ".bat",
    ".cmd",
    ".ps1",
    ".vbs",
    ".msi",
    ".scr",
    ".dll",
    ".lnk",
    ".hta",
    ".com",
    ".js",
})

# [화이트리스트] 임시 폴더 압축 해제 후 실제 심즈 4 Mods 폴더로 이동(반영)을 허용할 안전 파일 확장자
# (기존 코드 점검 결과 Mods 폴더에 설치 허용된 별도 설정/문서 확장자는 없으며 Resource.cfg 덮어쓰기 또한 금지됨)
ALLOWED_MOD_WHITELIST_EXTENSIONS: FrozenSet[str] = frozenset({
    ".package",
    ".ts4script",
})

_SECURITY_LOGGER_NAME = "sims4_mod_updater.security"


class ArchiveSecurityError(ValueError):
    """압축 파일 및 다운로드 파일의 보안 검증 위반 시 발생하는 최상위 보안 예외."""


class ZipSlipSecurityError(ArchiveSecurityError):
    """압축 파일 내부에 상위 경로 이탈(Zip Slip) 또는 비정상 절대 경로 엔트리가 감지되었을 때 발생하는 보안 예외."""


class DangerousFileExtensionError(ArchiveSecurityError):
    """압축 파일 내부 또는 다운로드 대상에서 실행/스크립트 계열 위험 확장자가 감지되었을 때 발생하는 보안 예외."""


class NetworkSecurityError(ValueError):
    """네트워크 프로토콜(HTTP 차단/리다이렉트 다운그레이드) 또는 SSL/TLS 인증서 검증 위반 시 발생하는 보안 예외."""


class InsecureUrlSecurityError(NetworkSecurityError):
    """일반 HTTP URL, 리다이렉트 프로토콜 다운그레이드, 또는 내부망(SSRF) 접근이 감지되었을 때 발생하는 보안 예외."""


class SslCertificateSecurityError(NetworkSecurityError):
    """SSL/TLS 인증서 검증 우회 시도 또는 유효하지 않은 서버 인증서가 감지되었을 때 발생하는 보안 예외."""


def _get_app_base_dir() -> Path:
    """실행 환경(.exe 배포 환경 또는 파이썬 소스 환경)의 기준 디렉터리를 반환합니다."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).resolve().parent.parent


def get_security_logger() -> logging.Logger:
    """보안 경고 이벤트를 파일(security.log)과 표준 에러 스트림에 기록하는 전용 로거를 반환합니다."""
    logger = logging.getLogger(_SECURITY_LOGGER_NAME)
    if getattr(logger, "_configured", False):
        return logger

    logger.setLevel(logging.WARNING)
    logger.propagate = False
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [SECURITY] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 배포된 .exe 폴더에 우선 기록하며, 읽기 전용 경로(Program Files 등)일 경우 LOCALAPPDATA / TEMP로 폴백
    log_candidates: List[Path] = [_get_app_base_dir() / "security.log"]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        log_candidates.append(Path(local_app_data) / "Sims4ModAutoUpdater" / "security.log")
    log_candidates.append(Path(tempfile.gettempdir()) / "sims4_mod_updater_security.log")

    for log_path in log_candidates:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            if not os.access(log_path.parent, os.W_OK):
                continue
            file_handler = logging.FileHandler(log_path, encoding="utf-8", delay=True)
            file_handler.setLevel(logging.WARNING)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            break
        except OSError:
            continue

    if sys.stderr is not None and hasattr(sys.stderr, "write"):
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setLevel(logging.WARNING)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    setattr(logger, "_configured", True)
    return logger


def log_security_warning(
    message: str,
    *,
    archive_path: Optional[Path] = None,
    offending_entry: Optional[str] = None,
) -> None:
    """보안 위협 감지 시 상세 보안 경고 로그를 기록합니다."""
    logger = get_security_logger()
    details: List[str] = [message]
    if archive_path is not None:
        details.append(f"archive='{archive_path}'")
    if offending_entry is not None:
        details.append(f"entry={offending_entry!r}")
    logger.warning(" | ".join(details))


def is_safe_subpath(
    target_path: Path,
    base_dir: Path,
    *,
    allow_equal: bool = False,
) -> bool:
    """대상 경로의 최종 절대 경로가 지정된 기준 폴더(base_dir)의 절대 경로 하위인지 검증합니다.
    'C:\\Temp\\Mod'와 'C:\\Temp\\Mod_Evil'을 혼동하는 접두사 비교 버그를 차단하기 위해
    1) 기준 경로 끝에 디렉토리 구분자(os.sep)를 강제한 정규화 접두사 비교,
    2) os.path.commonpath 및 Path.is_relative_to 계층 비교
    를 모두 통과해야만 True를 반환합니다.
    """
    try:
        base_resolved = Path(os.path.abspath(str(base_dir.resolve())))
        target_resolved = Path(os.path.abspath(str(target_path.resolve())))

        base_norm = os.path.normcase(os.path.normpath(str(base_resolved)))
        target_norm = os.path.normcase(os.path.normpath(str(target_resolved)))

        if allow_equal and target_norm == base_norm:
            return True

        base_with_sep = base_norm if base_norm.endswith(os.sep) else (base_norm + os.sep)
        if not target_norm.startswith(base_with_sep):
            return False

        if os.path.commonpath([base_norm, target_norm]) != base_norm:
            return False

        if not target_resolved.is_relative_to(base_resolved):
            return False

        return True
    except (ValueError, OSError, RuntimeError):
        return False


def _normalize_leaf_filename(raw_name: str) -> str:
    """엔트리 경로에서 말단 파일명을 추출하고 Windows NTFS가 무시하는 후행 공백·마침표를 제거합니다."""
    leaf = Path(raw_name.replace("\\", "/")).name
    return leaf.rstrip(" .")


def inspect_dangerous_extension(raw_name: str) -> Optional[str]:
    """압축 해제 전 엔트리 이름에서 실행 및 스크립트 계열 위험 확장자
    (.exe, .bat, .cmd, .ps1, .vbs, .msi, .scr, .dll, .lnk, .hta, .com, .js) 포함 여부를 검사합니다.
    위험 확장자가 감지되면 해당 확장자 문자열(예: '.exe')을 반환하고, 안전하면 None을 반환합니다.
    """
    if not raw_name or raw_name.endswith(("/", "\\")):
        return None
    clean_leaf = _normalize_leaf_filename(raw_name)
    if not clean_leaf:
        return None
    ext = Path(clean_leaf).suffix.lower()
    if ext in DANGEROUS_ARCHIVE_EXTENSIONS:
        return ext
    return None


def is_whitelisted_mod_file(
    file_path: Path,
    allowed_extensions: FrozenSet[str] = ALLOWED_MOD_WHITELIST_EXTENSIONS,
) -> bool:
    """임시 폴더에서 실제 심즈 4 Mods 폴더로 이동할 파일이 화이트리스트 안전 확장자에 해당하는지 검증합니다."""
    try:
        if file_path.is_symlink() or not file_path.is_file():
            return False
        clean_leaf = _normalize_leaf_filename(file_path.name)
        if not clean_leaf or clean_leaf in (".", ".."):
            return False
        if clean_leaf.lower() == "resource.cfg":
            return False
        ext = Path(clean_leaf).suffix.lower()
        if ext in DANGEROUS_ARCHIVE_EXTENSIONS:
            return False
        return ext in allowed_extensions
    except OSError:
        return False


def _inspect_entry_name_stage1(raw_name: str) -> Optional[str]:
    """[1차 검사] 압축 엔트리 헤더 이름 자체에 상위 디렉토리 이동 문자열('../', '..\\', '..' 세그먼트),
    드라이브 절대 경로('C:\\', 'C:/' 등), UNC/루트 절대 경로, NTFS 대체 데이터 스트림(':'),
    또는 널 바이트가 포함되어 있는지 검사합니다.
    """
    if "\x00" in raw_name:
        return "엔트리 이름에 널 바이트(\\x00)가 포함되어 있습니다."

    if "../" in raw_name or "..\\" in raw_name:
        return "엔트리 이름에 상위 디렉토리 이동 문자열('../' 또는 '..\\\\')이 포함되어 있습니다."

    segments = [seg for seg in re.split(r"[\\/]+", raw_name) if seg != ""]
    if ".." in segments:
        return "엔트리 경로 세그먼트에 상위 디렉토리 이동('..')이 포함되어 있습니다."

    if raw_name.startswith(("\\\\", "//")):
        return "엔트리 이름에 네트워크 UNC 절대 경로가 포함되어 있습니다."

    if raw_name.startswith(("/", "\\")):
        return "엔트리 이름이 루트 절대 경로 구분자('/' 또는 '\\\\')로 시작합니다."

    drive_prefix, _ = os.path.splitdrive(raw_name)
    win_path = PureWindowsPath(raw_name)
    posix_path = PurePosixPath(raw_name)
    if (
        drive_prefix
        or win_path.drive
        or re.match(r"^[a-zA-Z]:", raw_name)
        or win_path.is_absolute()
        or posix_path.is_absolute()
    ):
        return "엔트리 이름에 드라이브 문자 또는 절대 경로가 포함되어 있습니다."

    if ":" in raw_name:
        return "엔트리 이름에 허용되지 않는 콜론(':') 또는 NTFS 대체 데이터 스트림(ADS) 표기가 포함되어 있습니다."

    return None


def quarantine_and_delete_archive(
    archive_path: Path,
    *,
    offending_entry: str,
    reason: str,
    temp_extract_dir: Optional[Path] = None,
) -> None:
    """악성/위험 아카이브 감지 시 압축을 풀지 않고 전용 격리 폴더(.quarantine)로 즉시 격리 이동시켜
    실행/접근 가능성을 차단한 뒤 영구 삭제하고 보안 경고 로그를 기록합니다.
    """
    quarantine_root = Path(tempfile.gettempdir()).resolve() / "sims4_updater_quarantine"
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    slot_dir = quarantine_root / f"q_{ts}_{uuid.uuid4().hex[:8]}"
    safe_base = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", archive_path.name).strip(" .") or "unsafe_archive"
    quarantined_file = slot_dir / f"{safe_base}.quarantine"

    quarantined_ok = False
    try:
        if archive_path.exists() or archive_path.is_symlink():
            slot_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(archive_path), str(quarantined_file))
            quarantined_ok = True
    except OSError:
        quarantined_ok = False
    finally:
        # 격리된 파일 및 혹시 남아 있을 원본 경로까지 모두 즉시 영구 삭제
        safe_remove(quarantined_file)
        safe_remove(slot_dir)
        safe_remove(archive_path)
        try:
            if quarantine_root.exists() and not any(quarantine_root.iterdir()):
                quarantine_root.rmdir()
        except OSError:
            pass

    action_desc = (
        f"격리 폴더('{quarantined_file}') 이동 후 즉시 영구 삭제 완료"
        if quarantined_ok
        else "원본 파일 즉시 영구 삭제 완료"
    )
    base_info = f" | 기준 임시 폴더='{temp_extract_dir}'" if temp_extract_dir is not None else ""
    log_security_warning(
        f"압축 해제 차단 및 {action_desc}: {reason}{base_info}",
        archive_path=archive_path,
        offending_entry=offending_entry,
    )


def _abort_and_purge_unsafe_archive(
    archive_path: Path,
    temp_extract_dir: Path,
    offending_entry: str,
    reason: str,
    *,
    is_dangerous_ext: bool = False,
) -> None:
    """악성/위험 아카이브를 즉시 격리 후 삭제하고 보안 경고 로그를 남긴 뒤 적절한 보안 예외를 발생시킵니다."""
    quarantine_and_delete_archive(
        archive_path,
        offending_entry=offending_entry,
        reason=reason,
        temp_extract_dir=temp_extract_dir,
    )
    if is_dangerous_ext:
        raise DangerousFileExtensionError(
            f"[보안 차단] 압축 파일('{archive_path.name}') 내부에서 위험 실행/스크립트 파일({offending_entry!r})이 "
            f"감지되어 압축을 풀지 않고 즉시 격리 후 삭제했습니다. 사유: {reason}"
        )
    raise ZipSlipSecurityError(
        f"[보안 차단] 압축 파일('{archive_path.name}') 내부에서 허용되지 않는 경로 엔트리({offending_entry!r})가 "
        f"감지되어 작업을 즉시 중단하고 압축 파일을 격리 후 삭제했습니다. 사유: {reason}"
    )


def validate_zip_entries(zip_path: Path, temp_extract_dir: Path) -> List[zipfile.ZipInfo]:
    """다운로드된 .zip 파일을 디스크에 실제로 압축 해제하기 전,
    내부 엔트리 목록(헤더)을 먼저 순회하며 보안 위협 여부를 사전 검증합니다.

    검증 항목:
    1) 1차 경로 검사: 엔트리 이름에 '../', '..\\', '..' 세그먼트, 드라이브/루트 절대 경로, 심볼릭 링크 포함 여부 확인
    2) 위험 확장자 검사: 실행 및 스크립트 계열 위험 확장자
       (.exe, .bat, .cmd, .ps1, .vbs, .msi, .scr, .dll, .lnk, .hta, .com, .js) 포함 여부 확인
    3) 2차 경로 계층 검사: 최종 압축 해제 절대 경로가 지정된 임시 작업 폴더(temp_extract_dir) 하위인지
       디렉토리 구분자 강제 비교 + 경로 계층 비교(is_safe_subpath)로 대조

    위반 엔트리가 단 하나라도 발견되면 압축을 풀지 않고 즉시 원본 압축파일을 격리 후 삭제한 뒤
    보안 경고 로그를 남기고 예외(ZipSlipSecurityError / DangerousFileExtensionError)를 발생시킵니다.
    """
    if not zip_path.exists() or not zip_path.is_file():
        raise ValueError(f"검증할 압축 파일이 존재하지 않습니다: {zip_path}")

    base_temp_resolved = Path(os.path.abspath(str(temp_extract_dir.resolve())))
    violation_entry: Optional[str] = None
    violation_reason: Optional[str] = None
    violation_is_dangerous_ext = False
    entries: List[zipfile.ZipInfo] = []

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            entries = zf.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                violation_entry = "<archive_entry_count>"
                violation_reason = f"압축 파일 내 엔트리 개수({len(entries):,}개)가 허용 한도({MAX_ZIP_ENTRIES:,}개)를 초과했습니다."
            else:
                total_uncompressed = 0
                for info in entries:
                    raw_name = info.filename

                    # 1차 검사: 상위 디렉토리 이동 문자열('../', '..\') 및 드라이브/루트 절대 경로 검사
                    stage1_err = _inspect_entry_name_stage1(raw_name)
                    if stage1_err is not None:
                        violation_entry = raw_name
                        violation_reason = stage1_err
                        break

                    # ZIP 헤더 내 심볼릭 링크(S_IFLNK = 0o120000) 엔트리를 통한 우회 차단
                    unix_mode = (info.external_attr >> 16) & 0o170000
                    if unix_mode == 0o120000:
                        violation_entry = raw_name
                        violation_reason = "압축 파일 내부에 심볼릭 링크(Symlink) 엔트리가 포함되어 있습니다."
                        break

                    # 실행 및 스크립트 계열 위험 확장자 검사 (단 하나라도 발견 시 즉시 차단)
                    if not info.is_dir():
                        bad_ext = inspect_dangerous_extension(raw_name)
                        if bad_ext is not None:
                            violation_entry = raw_name
                            violation_reason = (
                                f"실행 및 스크립트 계열 위험 확장자('{bad_ext}') 엔트리가 발견되었습니다."
                            )
                            violation_is_dangerous_ext = True
                            break

                    # 압축 폭탄(Zip Bomb) 방지 검사
                    if info.file_size < 0:
                        violation_entry = raw_name
                        violation_reason = "비정상적인 음수 파일 크기 헤더가 감지되었습니다."
                        break
                    total_uncompressed += info.file_size
                    if total_uncompressed > MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
                        violation_entry = raw_name
                        violation_reason = (
                            f"압축 해제 예상 총 용량이 보안 허용 한도({MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES // (1024 ** 3)}GB)를 초과했습니다."
                        )
                        break

                    # 2차 검사: 최종 압축 해제 대상 절대 경로가 지정된 임시 작업 폴더 절대 경로 하위인지 대조
                    normalized_rel = raw_name.replace("/", os.sep).replace("\\", os.sep)
                    stripped_rel = normalized_rel.strip(os.sep)
                    is_harmless_dot_dir = info.is_dir() and stripped_rel in ("", ".")

                    candidate_target = Path(
                        os.path.abspath(os.path.join(str(base_temp_resolved), normalized_rel))
                    )
                    if not is_safe_subpath(
                        candidate_target,
                        base_temp_resolved,
                        allow_equal=is_harmless_dot_dir,
                    ):
                        violation_entry = raw_name
                        violation_reason = (
                            f"최종 해제 절대 경로('{candidate_target}')가 임시 작업 폴더('{base_temp_resolved}') 바깥을 가리킵니다."
                        )
                        break
    except zipfile.BadZipFile as bad_err:
        safe_remove(zip_path)
        raise ValueError(f"'{zip_path.name}' 파일이 손상되었거나 유효한 ZIP 압축 파일이 아닙니다.") from bad_err

    # Windows 파일 잠금 해제를 위해 with zipfile.ZipFile 블록을 빠져나온 직후 격리·삭제 및 경고 로깅 수행
    if violation_reason is not None:
        _abort_and_purge_unsafe_archive(
            archive_path=zip_path,
            temp_extract_dir=base_temp_resolved,
            offending_entry=violation_entry or "<unknown>",
            reason=violation_reason,
            is_dangerous_ext=violation_is_dangerous_ext,
        )

    return entries


def _resolve_system_tar_executable() -> str:
    """Windows 환경에서 현재 작업 디렉터리(CWD)의 악성 tar.exe 하이재킹을 방지하기 위해
    System32 내장 tar.exe 절대 경로를 우선 반환합니다.
    """
    if os.name == "nt":
        sys_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
        sys_tar = Path(sys_root) / "System32" / "tar.exe"
        if sys_tar.exists() and sys_tar.is_file():
            return str(sys_tar)
    found = shutil.which("tar")
    if not found:
        raise FileNotFoundError("시스템에서 압축 해제 도구(tar)를 찾을 수 없습니다.")
    return found


def validate_archive_entries_via_tar(archive_path: Path, temp_extract_dir: Path) -> None:
    """RAR / 7Z 등 bsdtar로 처리되는 아카이브를 디스크에 압축 해제하기 전,
    엔트리 헤더 목록(tar -tf)을 먼저 조회하여 경로 조작 및 위험 확장자 포함 여부를 사전 검증합니다.
    """
    base_temp_resolved = Path(os.path.abspath(str(temp_extract_dir.resolve())))
    tar_exe = _resolve_system_tar_executable()
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    proc = subprocess.run(
        [tar_exe, "-tf", str(archive_path)],
        check=False,
        capture_output=True,
        timeout=60,
        creationflags=creationflags,
    )
    if proc.returncode != 0:
        safe_remove(archive_path)
        raise ValueError(f"'{archive_path.name}' 압축 파일의 헤더를 읽을 수 없거나 손상된 아카이브입니다.")

    raw_stdout = proc.stdout.decode("utf-8", errors="surrogateescape")
    lines = [line.rstrip("\r\n") for line in raw_stdout.splitlines() if line.strip()]
    if len(lines) > MAX_ZIP_ENTRIES:
        _abort_and_purge_unsafe_archive(
            archive_path=archive_path,
            temp_extract_dir=base_temp_resolved,
            offending_entry="<archive_entry_count>",
            reason=f"압축 파일 내 엔트리 개수({len(lines):,}개)가 허용 한도({MAX_ZIP_ENTRIES:,}개)를 초과했습니다.",
        )

    for raw_name in lines:
        stage1_err = _inspect_entry_name_stage1(raw_name)
        if stage1_err is not None:
            _abort_and_purge_unsafe_archive(
                archive_path=archive_path,
                temp_extract_dir=base_temp_resolved,
                offending_entry=raw_name,
                reason=stage1_err,
            )

        if not raw_name.endswith(("/", "\\")):
            bad_ext = inspect_dangerous_extension(raw_name)
            if bad_ext is not None:
                _abort_and_purge_unsafe_archive(
                    archive_path=archive_path,
                    temp_extract_dir=base_temp_resolved,
                    offending_entry=raw_name,
                    reason=f"실행 및 스크립트 계열 위험 확장자('{bad_ext}') 엔트리가 발견되었습니다.",
                    is_dangerous_ext=True,
                )

        normalized_rel = raw_name.replace("/", os.sep).replace("\\", os.sep)
        stripped_rel = normalized_rel.strip(os.sep)
        is_dot_dir = raw_name.endswith(("/", "\\")) and stripped_rel in ("", ".")
        candidate_target = Path(os.path.abspath(os.path.join(str(base_temp_resolved), normalized_rel)))
        if not is_safe_subpath(candidate_target, base_temp_resolved, allow_equal=is_dot_dir):
            _abort_and_purge_unsafe_archive(
                archive_path=archive_path,
                temp_extract_dir=base_temp_resolved,
                offending_entry=raw_name,
                reason=f"최종 해제 절대 경로('{candidate_target}')가 임시 작업 폴더('{base_temp_resolved}') 바깥을 가리킵니다.",
            )


def validate_https_url(
    url: str,
    *,
    allow_fragment: bool = True,
    purpose: str = "네트워크 요청",
    log_violation: bool = True,
) -> str:
    """원격 카탈로그 조회 및 모드 파일 다운로드 대상 URL이 반드시 안전한 HTTPS 프로토콜인지 검증합니다.
    - 일반 HTTP('http://') 및 비허용 프로토콜('file://', 'ftp://', 'javascript:' 등) 즉시 차단
    - URL 내 제어문자/공백/계정정보(user:pass@host) 삽입 공격 차단
    - 로컬 호스트 및 사설/루프백/링크로컬/예약 대역 IP(SSRF) 차단
    """
    def _reject(reason: str) -> None:
        if log_violation:
            log_security_warning(f"[{purpose}] URL 보안 검증 차단: {reason} | url={url!r}")
        raise InsecureUrlSecurityError(f"[보안 차단] {purpose} 거부: {reason} ({url})")

    if not isinstance(url, str) or not url.strip():
        _reject("유효하지 않은 빈 URL입니다.")

    stripped_url = url.strip()
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F or ch in (" ", "\t") for ch in stripped_url):
        _reject("URL에 허용되지 않는 공백 또는 제어 문자(CRLF 등)가 포함되어 있습니다.")

    if "#" in stripped_url:
        if not allow_fragment:
            _reject("프래그먼트('#')가 포함된 URL은 허용되지 않습니다.")
        clean_url = stripped_url.split("#", 1)[0]
    else:
        clean_url = stripped_url

    parsed = urllib.parse.urlsplit(clean_url)
    scheme_low = parsed.scheme.lower()
    if scheme_low == "http":
        _reject("일반 HTTP 프로토콜은 보안상 차단되며 반드시 HTTPS 프로토콜만 허용됩니다.")
    if scheme_low != "https":
        _reject(f"허용되지 않는 URL 프로토콜('{parsed.scheme or '없음'}')입니다 (반드시 HTTPS만 허용).")

    if not parsed.netloc or not parsed.hostname:
        _reject("URL에 유효한 호스트명이 존재하지 않습니다.")

    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        _reject("URL 내 사용자 인증 정보(userinfo '@') 포함은 보안상 차단됩니다.")

    try:
        port = parsed.port
        if port is not None and not (1 <= port <= 65535):
            _reject(f"비정상적인 포트 번호({port})입니다.")
    except ValueError:
        _reject("URL 포트 형식이 올바르지 않습니다.")

    host_low = parsed.hostname.lower().rstrip(".")
    if (
        not host_low
        or host_low in ("localhost", "localhost.localdomain", "0.0.0.0")
        or host_low.endswith((".localhost", ".local", ".localdomain"))
    ):
        _reject(f"로컬 호스트 주소('{host_low}')로의 접근은 보안상 차단됩니다.")

    try:
        ip_obj = ipaddress.ip_address(host_low)
    except ValueError:
        ip_obj = None

    if ip_obj is not None:
        mapped_v4 = getattr(ip_obj, "ipv4_mapped", None)
        check_ips = [ip_obj, mapped_v4] if mapped_v4 is not None else [ip_obj]
        for candidate_ip in check_ips:
            if (
                candidate_ip.is_loopback
                or candidate_ip.is_private
                or candidate_ip.is_link_local
                or candidate_ip.is_unspecified
                or candidate_ip.is_multicast
                or candidate_ip.is_reserved
            ):
                _reject(f"사설/루프백/내부망 IP 주소('{host_low}')로의 요청은 보안상 차단됩니다.")

    return stripped_url


def is_valid_https_url(url: str) -> bool:
    """주어진 URL이 보안 정책(HTTPS 전용 및 SSRF 방어)을 충족하는지 여부를 불리언으로 반환합니다."""
    try:
        validate_https_url(url, allow_fragment=True, log_violation=False)
        return True
    except (NetworkSecurityError, ValueError):
        return False


def _validate_safe_http_url(url: str) -> None:
    """하위 호환 래퍼: 모든 호출부에서 일반 HTTP를 차단하고 HTTPS 전용 정책을 강제합니다."""
    validate_https_url(url, allow_fragment=True, purpose="URL 안전성 검증")


def normalize_network_timeout(
    timeout: Optional[Union[int, float, Tuple[Union[int, float], Union[int, float]]]] = None,
) -> Tuple[float, float]:
    """모든 네트워크 요청에 무한 대기가 발생하지 않도록 유효한 (connect_timeout, read_timeout) 튜플을 강제합니다."""
    def _clamp(val: Any, default_val: float) -> float:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return default_val
        f_val = float(val)
        if f_val <= 0 or f_val != f_val:  # <= 0 또는 NaN 방지
            return default_val
        return min(max(f_val, 1.0), MAX_NETWORK_TIMEOUT)

    if isinstance(timeout, tuple) and len(timeout) == 2:
        conn_t = _clamp(timeout[0], DEFAULT_CONNECT_TIMEOUT)
        read_t = _clamp(timeout[1], DEFAULT_READ_TIMEOUT)
        return (conn_t, read_t)

    if isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
        read_t = _clamp(timeout, DEFAULT_READ_TIMEOUT)
        conn_t = min(DEFAULT_CONNECT_TIMEOUT, read_t)
        return (conn_t, read_t)

    return (DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT)


_CACHED_CA_BUNDLE: Optional[str] = None
_SHARED_STRICT_SSL_CONTEXT: Optional[ssl.SSLContext] = None
_SSL_CONTEXT_LOCK = threading.Lock()
_THREAD_LOCAL_HTTP = threading.local()


def _get_trusted_ca_bundle() -> Union[str, bool]:
    """신뢰할 수 있는 공인 CA 인증서 번들 경로(certifi) 또는 기본 시스템 인증서 검증(True)을 반환합니다.
    어떠한 경우에도 False나 빈 문자열을 반환하지 않습니다.
    """
    global _CACHED_CA_BUNDLE
    cached = _CACHED_CA_BUNDLE
    if cached and os.path.isfile(cached):
        return cached

    if certifi is not None:
        try:
            ca_path = certifi.where()
            if ca_path and os.path.isfile(ca_path):
                _CACHED_CA_BUNDLE = ca_path
                return ca_path
        except Exception:
            pass
    return True


def _create_strict_ssl_context() -> ssl.SSLContext:
    """유효한 서버 인증서 및 호스트명 일치를 필수 검증하고 TLS 1.2 이상만 허용하는 엄격한 SSLContext를 생성합니다."""
    ca_bundle = _get_trusted_ca_bundle()
    cafile = ca_bundle if isinstance(ca_bundle, str) else None
    ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH, cafile=cafile)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    if hasattr(ssl, "TLSVersion"):
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _get_shared_strict_ssl_context() -> ssl.SSLContext:
    """프로세스 전체에서 안전하게 공유할 엄격한 SSLContext를 반환합니다.
    매 HTTPS 요청마다 certifi CA 번들을 반복 파싱해 발생하는 GIL/CPU 병목을 제거합니다.
    """
    global _SHARED_STRICT_SSL_CONTEXT
    ctx = _SHARED_STRICT_SSL_CONTEXT
    if ctx is not None and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname:
        return ctx

    with _SSL_CONTEXT_LOCK:
        ctx = _SHARED_STRICT_SSL_CONTEXT
        if ctx is None or ctx.verify_mode != ssl.CERT_REQUIRED or not ctx.check_hostname:
            ctx = _create_strict_ssl_context()
            _SHARED_STRICT_SSL_CONTEXT = ctx
        return ctx


class _BlockedPlainHttpAdapter(requests.adapters.BaseAdapter):
    """'http://' 평문 어댑터 계층을 원천 봉쇄하여 어떠한 우회 경로로도 평문 HTTP 패킷이 전송되지 않도록 차단합니다."""

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        bad_url = getattr(request, "url", "")
        log_security_warning(f"어댑터 계층 평문 HTTP 전송 시도 차단: url={bad_url!r}")
        raise InsecureUrlSecurityError(
            f"[보안 차단] 일반 HTTP 평문 통신은 허용되지 않습니다 (HTTPS 필수): {bad_url}"
        )

    def close(self) -> None:
        pass


class _StrictTlsHttpAdapter(requests.adapters.HTTPAdapter):
    """SSL/TLS 인증서 검증 우회(verify=False)를 원천 차단하고 공인 인증서 및 TLS 1.2+만 신뢰하는 전용 HTTPS 어댑터."""

    def init_poolmanager(self, connections: int, maxsize: int, block: bool = False, **pool_kwargs: Any) -> Any:
        pool_kwargs["ssl_context"] = _get_shared_strict_ssl_context()
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any) -> Any:
        proxy_kwargs["ssl_context"] = _get_shared_strict_ssl_context()
        return super().proxy_manager_for(proxy, **proxy_kwargs)

    def build_connection_pool_key_attributes(
        self,
        request: requests.PreparedRequest,
        verify: Any,
        cert: Any = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if verify is False or not verify:
            bad_url = getattr(request, "url", "")
            log_security_warning(f"풀 키 구성 단계 SSL/TLS 인증서 검증 우회(verify={verify!r}) 차단: url={bad_url!r}")
            raise SslCertificateSecurityError(
                "[보안 차단] SSL/TLS 보안 인증서 검증을 우회(verify=False)할 수 없습니다."
            )
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(request, verify, cert)
        default_ca = _get_trusted_ca_bundle()
        if verify is True or verify == default_ca:
            pool_kwargs["ssl_context"] = _get_shared_strict_ssl_context()
            pool_kwargs["cert_reqs"] = "CERT_REQUIRED"
            pool_kwargs.pop("ca_certs", None)
            pool_kwargs.pop("ca_cert_dir", None)
        return host_params, pool_kwargs

    def cert_verify(self, conn: Any, url: str, verify: Any, cert: Any) -> None:
        if not str(url or "").lower().startswith("https://"):
            log_security_warning(f"HTTPS 어댑터에 비-HTTPS URL 전달 감지 및 차단: url={url!r}")
            raise InsecureUrlSecurityError(f"[보안 차단] HTTPS 프로토콜만 허용됩니다: {url}")
        if verify is False or not verify:
            log_security_warning(f"어댑터 계층 SSL/TLS 인증서 검증 우회(verify={verify!r}) 차단: url={url!r}")
            raise SslCertificateSecurityError(
                "[보안 차단] SSL/TLS 보안 인증서 검증을 우회(verify=False)할 수 없습니다."
            )
        default_ca = _get_trusted_ca_bundle()
        if isinstance(verify, str) and verify != default_ca and os.path.exists(verify):
            super().cert_verify(conn, url, verify, cert)
        else:
            super().cert_verify(conn, url, True, cert)
            conn_kw = getattr(conn, "conn_kw", None)
            conn_ctx = getattr(conn, "ssl_context", None) or (
                conn_kw.get("ssl_context") if isinstance(conn_kw, dict) else None
            )
            if (
                conn_ctx is not None
                and conn_ctx.verify_mode == ssl.CERT_REQUIRED
                and conn_ctx.check_hostname
            ):
                # HTTPSConnectionPool(conn)의 conn_kw['ssl_context']에 공인 CA 번들이 이미 로드되어 있으므로
                # 매 소켓 연결마다 urllib3가 load_verify_locations()를 재실행하지 않도록 ca_certs를 비웁니다.
                conn.ca_certs = None
                conn.ca_cert_dir = None
        conn.cert_reqs = "CERT_REQUIRED"


class SafeHttpsSession(requests.Session):
    """HTTPS 전용 프로토콜 강제, 리다이렉트(301/302/303/307/308) 시 프로토콜 다운그레이드 사전 차단,
    엄격한 SSL/TLS 인증서 검증(verify=True 고정), 그리고 모든 요청에 타임아웃을 강제하는 보안 세션입니다.
    """

    def __init__(self) -> None:
        super().__init__()
        self.verify = _get_trusted_ca_bundle()
        self.mount("https://", _StrictTlsHttpAdapter(pool_connections=20, pool_maxsize=20))
        self.mount("http://", _BlockedPlainHttpAdapter())

    def merge_environment_settings(
        self,
        url: Any,
        proxies: Any,
        stream: Any,
        verify: Any,
        cert: Any,
    ) -> Dict[str, Any]:
        """외부 환경변수(REQUESTS_CA_BUNDLE='', CURL_CA_BUNDLE='' 등)를 통한 인증서 검증 약화를 차단합니다."""
        if verify is False or not verify:
            log_security_warning(f"환경 병합 단계 SSL 인증서 검증 비활성화 시도 차단: url={url!r}")
            raise SslCertificateSecurityError(
                "[보안 차단] SSL/TLS 인증서 검증은 비활성화할 수 없으며 유효한 인증서만 신뢰합니다."
            )
        merged = super().merge_environment_settings(url, proxies, stream, verify, cert)
        merged["verify"] = _get_trusted_ca_bundle()
        return merged

    def request(  # type: ignore[override]
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        if "verify" in kwargs:
            v_opt = kwargs.pop("verify")
            if v_opt is False or not v_opt:
                log_security_warning(
                    f"네트워크 요청에서 SSL/TLS 인증서 검증 우회 옵션(verify={v_opt!r}) 차단: url={url!r}"
                )
                raise SslCertificateSecurityError(
                    "[보안 차단] SSL/TLS 보안 인증서 검증을 우회하거나 무시할 수 없습니다."
                )

        trusted_ca = _get_trusted_ca_bundle()
        effective_timeout = normalize_network_timeout(kwargs.pop("timeout", None))
        follow_redirects = bool(kwargs.pop("allow_redirects", True))

        method_upper = (method or "GET").upper()
        validate_https_url(url, allow_fragment=True, purpose=f"최초 {method_upper} 요청 URL")
        current_url = url.strip().split("#", 1)[0]

        cur_method = method_upper
        cur_headers = dict(kwargs.pop("headers", None) or {})
        cur_data = kwargs.pop("data", None)
        cur_json = kwargs.pop("json", None)
        cur_params = kwargs.pop("params", None)
        stream_flag = bool(kwargs.pop("stream", False))
        redirect_history: List[requests.Response] = []

        for hop in range(MAX_HTTPS_REDIRECTS + 1):
            try:
                resp = super().request(
                    method=cur_method,
                    url=current_url,
                    headers=cur_headers if cur_headers else None,
                    data=cur_data,
                    json=cur_json,
                    params=cur_params if hop == 0 else None,
                    stream=stream_flag,
                    timeout=effective_timeout,
                    verify=trusted_ca,
                    allow_redirects=False,
                    **kwargs,
                )
            except requests.exceptions.SSLError as ssl_err:
                log_security_warning(
                    f"유효하지 않은 SSL/TLS 인증서 차단: url='{current_url}' | error={ssl_err}"
                )
                raise SslCertificateSecurityError(
                    f"[보안 차단] 서버('{current_url}')의 SSL/TLS 보안 인증서가 유효하지 않아 연결을 차단했습니다: {ssl_err}"
                ) from ssl_err

            has_location = any(k.lower() == "location" for k in resp.headers.keys())
            is_redirect_hop = (resp.status_code in REDIRECT_STATUS_CODES) and has_location

            if not is_redirect_hop or not follow_redirects:
                if resp.url:
                    validate_https_url(resp.url, allow_fragment=True, purpose="최종 응답 URL")
                resp.history = redirect_history
                return resp

            raw_location = (resp.headers.get("Location") or "").strip()
            hop_source_url = resp.url or current_url
            resp.close()
            redirect_history.append(resp)

            if hop >= MAX_HTTPS_REDIRECTS:
                raise requests.TooManyRedirects(
                    f"최대 허용 HTTPS 리다이렉트 횟수({MAX_HTTPS_REDIRECTS}회)를 초과했습니다: {hop_source_url}",
                    response=resp,
                )

            next_url = urllib.parse.urljoin(hop_source_url, raw_location)
            # 리다이렉트(301, 302, 303, 307, 308) 대상 URL로 실제 이동하기 전 HTTPS 여부를 먼저 검증하여 프로토콜 다운그레이드 원천 차단
            validate_https_url(
                next_url,
                allow_fragment=True,
                purpose=f"HTTP {resp.status_code} 리다이렉트 대상 URL (원본: {hop_source_url})",
            )
            next_clean_url = next_url.split("#", 1)[0]

            prev_host = (urllib.parse.urlsplit(hop_source_url).hostname or "").lower()
            next_host = (urllib.parse.urlsplit(next_clean_url).hostname or "").lower()
            if prev_host != next_host and cur_headers:
                for hdr_key in list(cur_headers.keys()):
                    if hdr_key.lower() in ("authorization", "proxy-authorization", "cookie"):
                        cur_headers.pop(hdr_key, None)

            if resp.status_code == 303 and cur_method != "HEAD":
                cur_method = "GET"
                cur_data = None
                cur_json = None
            elif resp.status_code in (301, 302) and cur_method == "POST":
                cur_method = "GET"
                cur_data = None
                cur_json = None

            if cur_data is None and cur_json is None and cur_headers:
                for hdr_key in list(cur_headers.keys()):
                    if hdr_key.lower() in ("content-length", "content-type", "transfer-encoding"):
                        cur_headers.pop(hdr_key, None)

            current_url = next_clean_url

        raise requests.TooManyRedirects(f"리다이렉트 한도({MAX_HTTPS_REDIRECTS}회)를 초과했습니다.")


def _get_thread_safe_https_session() -> SafeHttpsSession:
    """워커 스레드별로 TLS Keep-Alive 커넥션 풀을 재사용하기 위한 SafeHttpsSession을 반환합니다."""
    sess = getattr(_THREAD_LOCAL_HTTP, "session", None)
    if not isinstance(sess, SafeHttpsSession):
        sess = SafeHttpsSession()
        _THREAD_LOCAL_HTTP.session = sess
    return sess


def safe_https_request(
    method: str,
    url: str,
    *,
    timeout: Optional[Union[int, float, Tuple[Union[int, float], Union[int, float]]]] = None,
    stream: bool = False,
    **kwargs: Any,
) -> requests.Response:
    """단발성 네트워크 요청을 스레드 로컬 SafeHttpsSession 커넥션 풀로 안전하게 수행합니다.
    (HTTPS 전용, 리다이렉트 다운그레이드 차단, 유효 인증서 강제, 타임아웃 필수 적용)
    """
    sess = _get_thread_safe_https_session()
    # 단발성 요청 간 쿠키 간섭이 없도록 요청 전 세션 쿠키만 비우고 TCP/TLS 커넥션 풀은 유지합니다.
    sess.cookies.clear()
    return sess.request(method=method, url=url, timeout=timeout, stream=stream, **kwargs)


def safe_https_get(
    url: str,
    *,
    timeout: Optional[Union[int, float, Tuple[Union[int, float], Union[int, float]]]] = None,
    stream: bool = False,
    **kwargs: Any,
) -> requests.Response:
    """안전한 HTTPS 전용 GET 요청 헬퍼."""
    return safe_https_request("GET", url, timeout=timeout, stream=stream, **kwargs)


def safe_https_post(
    url: str,
    *,
    timeout: Optional[Union[int, float, Tuple[Union[int, float], Union[int, float]]]] = None,
    stream: bool = False,
    **kwargs: Any,
) -> requests.Response:
    """안전한 HTTPS 전용 POST 요청 헬퍼."""
    return safe_https_request("POST", url, timeout=timeout, stream=stream, **kwargs)


def safe_https_head(
    url: str,
    *,
    timeout: Optional[Union[int, float, Tuple[Union[int, float], Union[int, float]]]] = None,
    **kwargs: Any,
) -> requests.Response:
    """안전한 HTTPS 전용 HEAD 요청 헬퍼."""
    return safe_https_request("HEAD", url, timeout=timeout, stream=False, **kwargs)


def safe_open_url(url: str) -> bool:
    """외부 웹 브라우저로 URL을 열기 전 HTTPS 전용 스킴 여부를 검증하여
    평문 HTTP 접속 및 Windows os.startfile 기반 임의 로컬 파일/명령어 실행(RCE)을 차단합니다.
    """
    try:
        validate_https_url(url, allow_fragment=True, purpose="외부 브라우저 URL 열기")
    except ValueError as err:
        log_security_warning(f"비정상 또는 비보안 URL 브라우저 실행 차단: {err} (url={url!r})")
        return False
    return bool(webbrowser.open(url))


def calculate_sha256(file_path: Path) -> str:
    """파일의 SHA256 해시를 계산합니다."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    return sha.hexdigest()


def download_file(
    url: str,
    dest_path: Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    fallback_source_dir: Optional[Path] = None,
    page_url: Optional[str] = None,
    target_mod_name: Optional[str] = None,
) -> Path:
    """HTTPS 전용 검증 및 리다이렉트 프로토콜 다운그레이드 차단을 적용하여 파일을 안전하게 다운로드합니다."""
    validate_https_url(url, allow_fragment=True, purpose="모드 파일 다운로드")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Patreon / Postype 무료 공개 포스트(#free_member_file=...) 처리 (경로 조작 방지를 위해 파일명만 추출)
    if "#free_member_file=" in url:
        base_u, frag = url.split("#", 1)
        validate_https_url(base_u, allow_fragment=False, purpose="무료 공개 포스트 기준 URL 검증")
        qs = urllib.parse.parse_qs(frag)
        raw_target_fn = (qs.get("free_member_file") or [dest_path.name])[0]
        target_fn = Path(raw_target_fn.replace("\\", "/")).name
        if target_fn and target_fn not in (".", ".."):
            if inspect_dangerous_extension(target_fn) is not None:
                log_security_warning(f"위험 확장자 로컬 폴백 복사 차단: {target_fn!r}")
                raise DangerousFileExtensionError(f"[보안 차단] 허용되지 않는 위험 확장자 파일입니다: {target_fn}")
            alt_fn = (
                target_fn.replace("_KOR_", "(KOR)").replace("_kor_", "(KOR)")
                if target_fn.lower().startswith("_kor_")
                else (f"_KOR_{target_fn[5:]}" if target_fn.lower().startswith("(kor)") else target_fn)
            )
            search_dirs = [d for d in (fallback_source_dir, Path.home() / "Downloads") if d and d.exists()]
            for s_dir in search_dirs:
                for cand_name in (target_fn, alt_fn):
                    cand_local = s_dir / cand_name
                    if (
                        is_safe_subpath(cand_local, s_dir)
                        and cand_local.exists()
                        and cand_local.is_file()
                        and not cand_local.is_symlink()
                    ):
                        shutil.copy2(cand_local, dest_path)
                        return dest_path

    # Itch.io 지연 업로드 다운로드 링크(#itchio_upload_id=...) 처리
    if "#itchio_upload_id=" in url:
        base_u, frag = url.split("#", 1)
        validate_https_url(base_u, allow_fragment=False, purpose="Itch.io 업로드 링크 조회")
        qs = urllib.parse.parse_qs(frag)
        target_fn = Path((qs.get("file_name") or [dest_path.name])[0].replace("\\", "/")).name
        from src.finder import inspect_remote_mod_page
        refreshed = inspect_remote_mod_page(base_u, target_mod_name=target_fn, timeout=15)
        if refreshed.get("download_url"):
            url = refreshed["download_url"]

    # MediaFire 파일 공유 페이지(mediafire.com/file/...)인 경우 실제 직접 다운로드 링크(download*.mediafire.com)로 변환
    if "mediafire.com/file/" in url.lower():
        validate_https_url(url, allow_fragment=True, purpose="MediaFire 배포 페이지 조회")
        from src.finder import inspect_remote_mod_page
        mf_res = inspect_remote_mod_page(url, target_mod_name=target_mod_name or dest_path.name, timeout=15)
        if mf_res.get("download_url"):
            url = mf_res["download_url"]

    validate_https_url(url, allow_fragment=True, purpose="모드 파일 최종 다운로드 URL")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    if "dcinside.com" in url.lower():
        headers["Referer"] = "https://gall.dcinside.com/"
    elif "wicked.cc" in url.lower():
        headers["Referer"] = "https://wicked.cc/"
    elif "blog.naver.com" in url.lower():
        headers["Referer"] = "https://blog.naver.com/"
    elif "kemzimamods.com" in url.lower():
        headers["User-Agent"] = "Mozilla/5.0"

    response = safe_https_get(url, headers=headers, stream=True, timeout=DEFAULT_DOWNLOAD_TIMEOUT)
    try:
        # Itch.io R2 서명 URL(유효기간 60초)이 만료되어 400/403이 발생한 경우 즉시 새 서명 URL을 발급받아 재시도
        if response.status_code in (400, 403) and page_url and ".itch.io" in page_url.lower():
            response.close()
            validate_https_url(page_url, allow_fragment=True, purpose="Itch.io 배포 페이지 재조회")
            from src.finder import inspect_remote_mod_page
            refreshed = inspect_remote_mod_page(page_url, target_mod_name=target_mod_name or dest_path.name, timeout=15)
            if refreshed.get("download_url"):
                url = refreshed["download_url"]
                validate_https_url(url, allow_fragment=True, purpose="Itch.io 재발급 다운로드 URL")
                response = safe_https_get(url, headers=headers, stream=True, timeout=DEFAULT_DOWNLOAD_TIMEOUT)

        # 리다이렉트 최종 URL에 대해서도 HTTPS 전용 및 SSRF 재검증
        if response.url:
            validate_https_url(response.url, allow_fragment=True, purpose="모드 다운로드 최종 응답 URL")

        response.raise_for_status()

        raw_cl = response.headers.get("content-length", "0")
        total_size = int(raw_cl) if str(raw_cl).isdigit() else 0
        if total_size > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"다운로드 파일 크기({total_size:,} bytes)가 보안 허용 한도를 초과했습니다.")

        downloaded = 0
        stream_started_at = time.monotonic()
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if time.monotonic() - stream_started_at > MAX_STREAM_ELAPSED_SECONDS:
                    raise TimeoutError(
                        f"다운로드 전체 소요 시간이 제한 시간({int(MAX_STREAM_ELAPSED_SECONDS)}초)을 초과하여 중단되었습니다."
                    )
                if chunk:
                    downloaded += len(chunk)
                    if downloaded > MAX_DOWNLOAD_BYTES:
                        raise ValueError("다운로드 스트림 크기가 보안 허용 한도를 초과하여 중단되었습니다.")
                    f.write(chunk)
                    if progress_callback and total_size > 0:
                        progress_callback(downloaded, total_size)
        last_mod = response.headers.get("Last-Modified")
        if last_mod and dest_path.exists():
            try:
                lm_dt = email.utils.parsedate_to_datetime(last_mod)
                if lm_dt is not None:
                    lm_ts = lm_dt.timestamp()
                    if lm_ts > 0:
                        os.utime(dest_path, (lm_ts, lm_ts))
            except Exception:
                pass
    except Exception:
        safe_remove(dest_path)
        raise
    finally:
        response.close()

    return dest_path


def verify_downloaded_mod_file(
    file_path: Path,
    expected_target_name: Optional[str] = None,
    target_dir: Optional[Path] = None,
    temp_extract_dir: Optional[Path] = None,
) -> None:
    """다운로드된 파일이 실제 유효한 심즈 4 모드(.package, .ts4script) 또는 모드 압축 파일(.zip 등)인지
    압축 해제 및 덮어쓰기 전에 사전 검증합니다.
    (Zip Slip 경로 조작, 위험 실행/스크립트 확장자, 위장 PE 실행 파일, 잘못된 HTML 응답 차단)
    """
    if not file_path.exists() or file_path.stat().st_size == 0:
        raise ValueError("다운로드된 파일이 비어 있거나 존재하지 않습니다.")

    check_base_dir = (temp_extract_dir or (file_path.parent / "_zip_verify_stage")).resolve()

    # 다운로드된 파일 자체의 확장자가 위험 확장자인 경우 즉시 격리 후 삭제
    bad_self_ext = inspect_dangerous_extension(file_path.name)
    if bad_self_ext is not None:
        quarantine_and_delete_archive(
            file_path,
            offending_entry=file_path.name,
            reason=f"다운로드된 파일 자체가 위험 확장자('{bad_self_ext}')입니다.",
            temp_extract_dir=check_base_dir,
        )
        raise DangerousFileExtensionError(
            f"[보안 차단] 위험 확장자('{bad_self_ext}') 파일 다운로드가 감지되어 즉시 격리 후 삭제했습니다: {file_path.name}"
        )

    with open(file_path, "rb") as f:
        head = f.read(512)

    # Windows 실행 파일(PE 'MZ' 헤더)이 .package / .zip 등으로 위장된 경우 즉시 격리 후 삭제
    if head.startswith(b"MZ"):
        quarantine_and_delete_archive(
            file_path,
            offending_entry=file_path.name,
            reason="모드/압축 파일로 위장된 Windows 실행 파일(PE MZ 헤더)이 감지되었습니다.",
            temp_extract_dir=check_base_dir,
        )
        raise DangerousFileExtensionError(
            f"[보안 차단] '{file_path.name}' 파일이 실행 파일(PE 바이너리)로 확인되어 즉시 격리 후 삭제했습니다."
        )

    head_strip = head.lstrip().lower()
    if head_strip.startswith((b"<!doctype html", b"<html", b"<head", b"<script", b"<?xml")):
        safe_remove(file_path)
        raise ValueError(
            "다운로드된 파일이 모드 파일이 아닌 웹 페이지(HTML) 응답입니다. "
            "로그인이 필요하거나 직접 다운로드가 차단된 링크일 수 있으므로 브라우저에서 직접 다운로드해 주세요."
        )

    suffix = Path(_normalize_leaf_filename(file_path.name)).suffix.lower()

    if suffix == ".package":
        if not head.startswith(b"DBPF"):
            safe_remove(file_path)
            raise ValueError(f"'{file_path.name}' 파일이 유효한 심즈 4 .package(DBPF) 형식이 아닙니다.")
        return

    if suffix == ".ts4script":
        if not zipfile.is_zipfile(file_path):
            safe_remove(file_path)
            raise ValueError(f"'{file_path.name}' 파일이 유효한 심즈 4 .ts4script 아카이브 형식이 아닙니다.")
        # .ts4script 또한 ZIP 포맷이므로 내부 엔트리 헤더 보안 검증(경로 조작 + 위험 확장자 차단) 수행
        validate_zip_entries(file_path, check_base_dir)
        return

    if suffix == ".zip":
        if not zipfile.is_zipfile(file_path):
            safe_remove(file_path)
            raise ValueError(f"'{file_path.name}' 파일이 손상되었거나 유효한 ZIP 압축 파일이 아닙니다.")

        # 디스크 압축 해제 전 ZIP 엔트리 헤더 전체 보안 검증 (위반 시 즉시 격리·삭제 + 보안 로그 기록 + 예외 발생)
        entries = validate_zip_entries(file_path, check_base_dir)

        whitelisted_names = [
            _normalize_leaf_filename(m.filename)
            for m in entries
            if not m.is_dir()
            and Path(_normalize_leaf_filename(m.filename)).suffix.lower() in ALLOWED_MOD_WHITELIST_EXTENSIONS
            and _normalize_leaf_filename(m.filename).lower() != "resource.cfg"
        ]
        if not whitelisted_names:
            safe_remove(file_path)
            raise ValueError(
                f"압축 파일('{file_path.name}') 내부에 허용된 심즈 4 모드 파일(.package / .ts4script)이 포함되어 있지 않아 설치를 중단했습니다."
            )
        return

    if suffix in (".rar", ".7z"):
        validate_archive_entries_via_tar(file_path, check_base_dir)
        return

    safe_remove(file_path)
    raise ValueError(f"허용되지 않는 다운로드 파일 형식입니다: '{file_path.name}'")


_OPTION_FOLDER_KEYWORDS = (
    "choose",
    "option",
    "select one",
    "pick one",
    "variant",
    "선택",
    "택1",
)


def normalize_mod_filename_key(filename: str) -> str:
    """모드 파일명에서 버전 번호 및 날짜 표기만 제거하여 업데이트 전/후 동일 모듈을 식별하는 정규화 키를 반환합니다.
    (예: 'Pandasama_ChildBirth_mod_v1.972.package' -> 'pandasama_childbirth_mod.package')
    """
    raw_name = Path(str(filename or "").replace("\\", "/")).name.strip()
    if not raw_name:
        return ""

    p = Path(raw_name)
    ext = p.suffix.lower()
    stem = p.stem

    # 0) 로드 순서 우선순위용 선행 특수기호(!, _, ~ 등) 및 스타일 변형 번호(_v1~_v3 on canvas_frame_override) 정규화
    stem = re.sub(r"^[!_~\s]+", "", stem)
    stem = re.sub(
        r"(?<=canvas_frame_override)_v([123])(?=$|[^a-zA-Z0-9])",
        r"__cfostyle\1__",
        stem,
        flags=re.IGNORECASE,
    )

    # 1) 괄호로 감싸진 순수 날짜/버전/핫픽스 블록 전체 제거 (예: '(v1.1)', '[v1.1]', '[20260315]', '(2026.05.13)' -> 여닫는 괄호 동시 제거)
    stem = re.sub(
        r"[\[\(]\s*(?:"
        r"(?:201[4-9]|202[0-9])[\.\-_]?(?:0?[1-9]|1[0-2])[\.\-_]?(?:0?[1-9]|[12][0-9]|3[01])|"
        r"(?:0?[1-9]|[12][0-9]|3[01])[\.\-_](?:0?[1-9]|1[0-2])[\.\-_](?:201[4-9]|202[0-9]|[12][0-9])|"
        r"[0-3][0-9][\.\-_][0-3][0-9][\.\-_][0-3][0-9]|"
        r"2[0-9](?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01])"
        r")\s*[\]\)]",
        " ",
        stem,
        flags=re.IGNORECASE,
    )
    stem = re.sub(
        r"[\[\(]\s*(?:"
        r"(?:v|ver|version|alpha|beta|rc|hotfix|hf)\.?\s*[0-9]+(?:\.[0-9]+)*[a-wyz]?|"
        r"[ab][0-9]+(?:\.[0-9]+)+[a-wyz]?|"
        r"[0-9]+(?:\.[0-9]+)+[a-wyz]?|"
        r"[0-9]{2,4}[a-z]|"
        r"(?:hotfix|hf|patch)\s*[0-9]*"
        r")(?:\s*(?:hotfix|hf|patch)\s*[0-9]*)?\s*[\]\)]",
        " ",
        stem,
        flags=re.IGNORECASE,
    )

    # 2) 바람별 통합한글화(WAMTIK) 스타일 버전 정규화 (예: V98G8 -> g, V97.8R -> r, -FF 여부는 유지)
    stem = re.sub(
        r"(?:^|(?<=[\s_.\-\[\(]))v[0-9]+(?:\.[0-9]+)?([gbpr])[0-9]*(?=$|[^a-zA-Z0-9.])",
        r" \1 ",
        stem,
        flags=re.IGNORECASE,
    )

    # 3) 날짜 표기 제거 (구분자 미소비 lookbehind 사용으로 인접 괄호/하이픈 훼손 방지)
    # 3-a) YYYY.MM.DD / DD.MM.YYYY / MM.DD.YYYY
    stem = re.sub(
        r"(?:^|(?<=[\s_.\-\[\(]))(?:201[4-9]|202[0-9])[\.\-_](?:0?[1-9]|1[0-2])[\.\-_](?:0?[1-9]|[12][0-9]|3[01])(?=$|[^0-9])",
        " ",
        stem,
    )
    stem = re.sub(
        r"(?:^|(?<=[\s_.\-\[\(]))(?:0?[1-9]|[12][0-9]|3[01])[\.\-_](?:0?[1-9]|1[0-2])[\.\-_](?:201[4-9]|202[0-9])(?=$|[^0-9])",
        " ",
        stem,
    )
    # 3-b) 2자리 연도 날짜 (예: 26.03.15, 27.09.25)
    stem = re.sub(
        r"(?:^|(?<=[\s_.\-\[\(]))[0-3][0-9][\.\-_][0-3][0-9][\.\-_][0-3][0-9](?=$|[^0-9.])",
        " ",
        stem,
    )
    # 3-c) 8자리 YYYYMMDD / 구분자 뒤 6자리 YYMMDD
    stem = re.sub(
        r"(?:^|(?<=[\s_.\-\[\(]))(?:201[4-9]|202[0-9])(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01])(?=$|[^0-9])",
        " ",
        stem,
    )
    stem = re.sub(
        r"(?<=[\s_.\-\[\(])(?:2[0-9])(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01])(?=$|[^0-9])",
        " ",
        stem,
    )
    # 3-d) 영문 월 포함 날짜 (예: Oct_23_2026, 23_Oct_2026, Nov-2026)
    _MONTH_PAT = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    stem = re.sub(
        rf"(?:^|(?<=[\s_.\-\[\(])){_MONTH_PAT}[\s_.\-]+(?:0?[1-9]|[12][0-9]|3[01])(?:[\s_.\-,]+(?:201[4-9]|202[0-9]))?(?=$|[^a-zA-Z0-9])",
        " ",
        stem,
        flags=re.IGNORECASE,
    )
    stem = re.sub(
        rf"(?:^|(?<=[\s_.\-\[\(]))(?:0?[1-9]|[12][0-9]|3[01])[\s_.\-]+{_MONTH_PAT}[\s_.\-]+(?:201[4-9]|202[0-9])(?=$|[^a-zA-Z0-9])",
        " ",
        stem,
        flags=re.IGNORECASE,
    )
    stem = re.sub(
        rf"(?:^|(?<=[\s_.\-\[\(])){_MONTH_PAT}[\s_.\-]+(?:201[4-9]|202[0-9])(?=$|[^a-zA-Z0-9])",
        " ",
        stem,
        flags=re.IGNORECASE,
    )

    # 4) 점(.)으로 구분된 버전 제거 (a0.5, b1.0, 0.1, v1.972 등 / 단, 1.75x 같은 배수 표기 제외)
    stem = re.sub(
        r"(?:^|(?<=[\s_.\-\[\(]))(?:(?:v|ver|version|alpha|beta|rc)\.?\s*|[ab])?[0-9]+(?:\.[0-9]+)+(?:[a-wyz]|[\s_\-]*(?:alpha|beta|rc|hf|hotfix)[0-9]*)?(?=$|[^a-zA-Z0-9.xX])",
        " ",
        stem,
        flags=re.IGNORECASE,
    )
    # 5) 명시적 v/ver/version/alpha/beta/rc/hf 접두사가 붙은 단일 숫자 버전 제거 (예: _v2, _v4, _v185k, ChatPackv2, alpha1)
    stem = re.sub(
        r"(?:^|(?<=[\s_.\-\[\(]))(?:v|ver|version|alpha|beta|rc|hotfix|hf)\.?\s*[0-9]+[a-wyz]?(?=$|[^a-zA-Z0-9.xX])",
        " ",
        stem,
        flags=re.IGNORECASE,
    )
    stem = re.sub(
        r"(?<=[a-zA-Z])(?:v|ver|version)\.?[0-9]+[a-wyz]?(?=$|[^a-zA-Z0-9.xX])",
        " ",
        stem,
        flags=re.IGNORECASE,
    )
    stem = re.sub(
        r"(?:^|(?<=[\s_.\-\[\(]))(?:hotfix|hf)(?=$|[^a-zA-Z0-9.xX])",
        " ",
        stem,
        flags=re.IGNORECASE,
    )
    # 6) 빈 괄호 정리 및 스타일 번호 복원
    stem = re.sub(r"\[\s*\]", " ", stem)
    stem = re.sub(r"\(\s*\)", " ", stem)
    stem = re.sub(r"__cfostyle([123])__", r"_v\1", stem, flags=re.IGNORECASE)

    # 구분자 정규화 (공백/언더바/하이픈/점은 '_'로 통일)
    stem = re.sub(r"[\s_.\-]+", "_", stem).strip("_").lower()
    return f"{stem}{ext}" if stem else raw_name.lower()


def is_auxiliary_non_mod_archive(filename: str, target_mod_name: str = "") -> bool:
    """아카이브가 제작자 리소스/문서/트레일러/부지 등 일반 모드 본체가 아닌 보조 파일인지 판별합니다."""
    fn_low = (filename or "").lower()
    t_low = (target_mod_name or "").lower()
    aux_tokens = (
        "creator_resource",
        "creatorresource",
        "moodtestingandinstructions",
        "instructions",
        "documentation",
        "readme",
        "trailer",
        "lot&sims",
        "lot_and_sims",
    )
    for tok in aux_tokens:
        if tok in fn_low and tok not in t_low:
            return True
    return False


def _is_option_or_addon_filename(filename: str) -> bool:
    """파일명이 선택형 옵션/애드온 모듈 성격인지 판별합니다."""
    low = (filename or "").lower()
    return any(
        tok in low
        for tok in (
            "optional",
            "addon",
            "add-on",
            "choose",
            "workingtime",
            "lockedstats",
            "noautocooking",
            "noautoputaway",
            "nogardening",
            "nocooking",
            "cannotdie",
            "costfix",
            "gotosleep",
            "hiremore",
            "nouniform",
            "forbiddenmoods",
            "age_adult",
            "age_elder",
            "age_youngadult",
            "test_users",
            "_columns",
            "lovestruck",
            "nolovestruck",
            "limits-",
            "limits_",
            "fictionalgurus",
            "reallifegurus",
        )
    )


def _select_mods_for_installation(
    whitelisted_files: List[Path],
    existing_names_lower: set[str],
    target_filename: Optional[str],
    overwrite_mode: str,
    existing_norm_keys: Optional[set[str]] = None,
    force_include_names: Optional[set[str]] = None,
) -> List[Path]:
    """화이트리스트 검증을 통과한 임시 폴더 내 모드 파일들 중 overwrite_mode 정책에 따라
    실제 Mods 폴더로 이동시킬 최종 대상 파일 목록을 선별합니다.
    (버전 번호가 바뀐 파일명도 정규화 키로 매칭하여 일부 파일만 업데이트되는 문제를 방지합니다.)
    """
    if not whitelisted_files:
        return []

    force_low = {str(n).strip().lower() for n in (force_include_names or set()) if str(n).strip()}

    def _with_forced(selected: List[Path]) -> List[Path]:
        if not force_low:
            return selected
        out = list(selected)
        for wf in whitelisted_files:
            if wf.name.lower() in force_low and wf not in out:
                out.append(wf)
        return out

    target_ext = Path(target_filename).suffix.lower() if target_filename else ""

    if overwrite_mode == "single" and target_filename:
        exact_matches = [f for f in whitelisted_files if f.name.lower() == target_filename.lower()]
        if exact_matches:
            return _with_forced([exact_matches[0]])
        target_norm = normalize_mod_filename_key(target_filename)
        if target_norm:
            norm_matches = [f for f in whitelisted_files if normalize_mod_filename_key(f.name) == target_norm]
            if norm_matches:
                return _with_forced([norm_matches[0]])
        if target_ext:
            same_ext = [f for f in whitelisted_files if f.suffix.lower() == target_ext]
            if same_ext:
                return _with_forced([same_ext[0]])
        return _with_forced(whitelisted_files)

    if overwrite_mode == "all":
        norm_keys = set(existing_norm_keys or set())
        for ex_name in existing_names_lower:
            nk = normalize_mod_filename_key(ex_name)
            if nk:
                norm_keys.add(nk)

        existing_rpo_slots: set[Tuple[str, str]] = set()
        for ex_name in existing_names_lower:
            m_rpo_ex = re.search(r"lumpinou_rpo_collection_(m\d+)_", ex_name)
            if m_rpo_ex:
                existing_rpo_slots.add((m_rpo_ex.group(1), Path(ex_name).suffix.lower()))

        installed_matches = [
            f
            for f in whitelisted_files
            if f.name.lower() in existing_names_lower
            or (norm_keys and normalize_mod_filename_key(f.name) in norm_keys)
            or (
                existing_rpo_slots
                and (m_rpo_f := re.search(r"lumpinou_rpo_collection_(m\d+)_", f.name.lower()))
                and (m_rpo_f.group(1), f.suffix.lower()) in existing_rpo_slots
            )
        ]
        has_choose_one = any(
            any(kw in str(f).lower() for kw in _OPTION_FOLDER_KEYWORDS)
            for f in whitelisted_files
        )
        is_all_aichat = all("sims4_ai_chat" in f.name.lower() for f in whitelisted_files)

        if (
            not is_all_aichat
            and installed_matches
            and len(whitelisted_files) > len(installed_matches)
            and (len(whitelisted_files) > 4 or has_choose_one)
        ):
            # 안전장치: .ts4script 등 일부만 매칭되고 본체/모듈 .package가 0개 매칭된 경우,
            # 선택형 옵션이 아닌 핵심 .package 파일이 아카이브에 존재하면 함께 포함시켜 스크립트-패키지 버전 불일치를 방지합니다.
            matched_pkgs = [f for f in installed_matches if f.suffix.lower() == ".package"]
            matched_scrs = [f for f in installed_matches if f.suffix.lower() == ".ts4script"]
            has_core_pkg_matched = any(not _is_option_or_addon_filename(f.name) for f in matched_pkgs)
            core_pkgs = [
                f
                for f in whitelisted_files
                if f.suffix.lower() == ".package" and not _is_option_or_addon_filename(f.name)
            ]
            if (matched_scrs and not matched_pkgs and not has_choose_one) or (
                not has_core_pkg_matched and len(core_pkgs) == 1
            ):
                for cp in core_pkgs:
                    if cp not in installed_matches:
                        installed_matches.append(cp)
            return _with_forced(installed_matches)
        if not installed_matches and target_filename and (len(whitelisted_files) > 4 or has_choose_one):
            exact_m = [f for f in whitelisted_files if f.name.lower() == target_filename.lower()]
            if exact_m:
                return _with_forced(exact_m)
            target_norm = normalize_mod_filename_key(target_filename)
            if target_norm:
                norm_m = [f for f in whitelisted_files if normalize_mod_filename_key(f.name) == target_norm]
                if norm_m:
                    return _with_forced(norm_m)

    return _with_forced(whitelisted_files)


def _resolve_install_dest_path(
    src_file: Path,
    staging_dir: Path,
    target_dir_resolved: Path,
    existing_rel_map: Optional[Dict[str, Path]] = None,
    existing_norm_rel_map: Optional[Dict[str, Path]] = None,
) -> Path:
    """설치할 화이트리스트 파일의 최종 대상 경로를 결정합니다.
    기존에 target_dir 하위 폴더(예: SP_DA_CAS/)에 설치된 파일이면 기존 하위 폴더 위치를 유지하고,
    그렇지 않으면 target_dir 루트에 배치합니다.
    """
    clean_name = _normalize_leaf_filename(src_file.name)
    low_name = clean_name.lower()
    norm_key = normalize_mod_filename_key(clean_name)

    if existing_rel_map and low_name in existing_rel_map:
        cand_parent = existing_rel_map[low_name].parent
        if is_safe_subpath(cand_parent, target_dir_resolved, allow_equal=True):
            return Path(os.path.abspath(os.path.join(str(cand_parent), clean_name)))

    if existing_norm_rel_map and norm_key in existing_norm_rel_map:
        cand_parent = existing_norm_rel_map[norm_key].parent
        if is_safe_subpath(cand_parent, target_dir_resolved, allow_equal=True):
            return Path(os.path.abspath(os.path.join(str(cand_parent), clean_name)))

    # 기존 파일이 이미 하위 폴더 구조를 사용해 배치된 경우, 새 파일의 아카이브 내 상대 하위 폴더도 매칭 시 유지
    if existing_rel_map and any(p.parent != target_dir_resolved for p in existing_rel_map.values()):
        try:
            rel_in_stage = src_file.resolve().relative_to(staging_dir.resolve())
            parts = list(rel_in_stage.parts[:-1])
            if parts and not any(any(kw in pt.lower() for kw in _OPTION_FOLDER_KEYWORDS) for pt in parts):
                # 최상위 1단계가 단일 래퍼 폴더(예: SpinningPlumbobs_DivineAscension/)이고 target_dir에 동일 이름 폴더가 없으면 벗겨냄
                if len(parts) >= 2 or (target_dir_resolved / parts[0]).is_dir():
                    rel_sub = parts[1:] if len(parts) >= 2 and not (target_dir_resolved / parts[0]).is_dir() else parts
                    if rel_sub:
                        sub_dir = Path(os.path.abspath(os.path.join(str(target_dir_resolved), *rel_sub)))
                        if is_safe_subpath(sub_dir, target_dir_resolved, allow_equal=True):
                            return Path(os.path.abspath(os.path.join(str(sub_dir), clean_name)))
        except Exception:
            pass

    return Path(os.path.abspath(os.path.join(str(target_dir_resolved), clean_name)))


def _is_variant_or_edition_protected_file(filename: str) -> bool:
    """카탈로그 ID 기반 자동 개명 교체에서 제외해야 하는 변형/모듈/에디션 파일인지 판별합니다."""
    low = (filename or "").lower()
    if _is_option_or_addon_filename(low):
        return True
    if "canvas_frame_override_v" in low:
        return True
    if re.search(r"lumpinou_rpo_collection_m\d+_", low):
        return True
    if "wamtik" in low:
        return True
    return False


def _lookup_catalog_id_safe(filename: str) -> str:
    """순환 임포트를 피해 check_known_catalog에서 모드 고유 카탈로그 식별자(matched_catalog)를 조회합니다."""
    try:
        from src.finder import check_known_catalog
        cat = check_known_catalog(filename)
        if isinstance(cat, dict) and cat.get("matched_catalog"):
            return str(cat["matched_catalog"]).strip()
    except Exception:
        pass
    return ""


def find_superseded_mod_files(
    incoming_names: List[str],
    target_dir_resolved: Path,
    mods_root_resolved: Optional[Path] = None,
    known_existing_files: Optional[List[Path]] = None,
    selected_file_path: Optional[Path] = None,
    include_subdirs: bool = False,
    expected_catalog_id: Optional[str] = None,
    protected_paths: Optional[List[Path]] = None,
) -> Tuple[List[Path], Dict[str, Path]]:
    """새 버전 파일 배치 전, 카탈로그 고유 식별자 및 정규화 파일명 패턴을 기준으로
    로컬 폴더(target_dir_resolved 및 known_existing_files) 내 기존 구버전 파일을 먼저 탐색합니다.
    반환값: (제거할 기존 구버전 파일 Path 목록, 새 파일명(소문자) -> 기존 파일 부모 디렉터리 힌트 맵)
    """
    if not incoming_names:
        return [], {}

    safe_root = (mods_root_resolved if mods_root_resolved is not None else target_dir_resolved).resolve()
    target_dir_res = target_dir_resolved.resolve()
    protected_res: set[Path] = set()
    for pp in protected_paths or []:
        try:
            protected_res.add(pp.resolve())
        except OSError:
            continue

    raw_candidates: List[Path] = []
    if target_dir_res.exists():
        iterator = target_dir_res.rglob("*") if include_subdirs else target_dir_res.iterdir()
        for f in iterator:
            raw_candidates.append(f)

    unit_files: List[Path] = []
    for kf in known_existing_files or []:
        raw_candidates.append(kf)
        unit_files.append(kf)
    if selected_file_path is not None:
        raw_candidates.append(selected_file_path)
        unit_files.append(selected_file_path)

    unit_res_set: set[Path] = set()
    for uf in unit_files:
        try:
            if uf.exists() and uf.is_file() and not uf.is_symlink():
                unit_res_set.add(uf.resolve())
        except OSError:
            continue

    candidates: List[Path] = []
    seen_res: set[Path] = set()
    for cand in raw_candidates:
        try:
            if not cand.exists() or not cand.is_file() or cand.is_symlink():
                continue
            if cand.suffix.lower() not in ALLOWED_MOD_WHITELIST_EXTENSIONS:
                continue
            cand_res = cand.resolve()
            if cand_res in seen_res or cand_res in protected_res:
                continue
            if not is_safe_subpath(cand_res, safe_root, allow_equal=False):
                continue
            seen_res.add(cand_res)
            candidates.append(cand)
        except OSError:
            continue

    if not candidates:
        return [], {}

    exp_cat = (expected_catalog_id or "").strip()
    incoming_meta: List[Dict[str, Any]] = []
    incoming_core_by_cat_ext: Dict[Tuple[str, str], List[str]] = {}
    incoming_core_by_ext: Dict[str, List[str]] = {}

    for inc in incoming_names:
        clean_inc = _normalize_leaf_filename(inc)
        if not clean_inc:
            continue
        inc_low = clean_inc.lower()
        inc_ext = Path(clean_inc).suffix.lower()
        if inc_ext not in ALLOWED_MOD_WHITELIST_EXTENSIONS:
            continue
        inc_nk = normalize_mod_filename_key(clean_inc)
        inc_rpo = re.search(r"lumpinou_rpo_collection_(m\d+)_", inc_low)
        inc_special = _is_variant_or_edition_protected_file(clean_inc)
        inc_cat = _lookup_catalog_id_safe(clean_inc) or exp_cat
        incoming_meta.append(
            {
                "name": clean_inc,
                "low": inc_low,
                "ext": inc_ext,
                "nk": inc_nk,
                "rpo_slot": inc_rpo.group(1) if inc_rpo else "",
                "special": inc_special,
                "cat": inc_cat,
            }
        )
        if not inc_special:
            incoming_core_by_ext.setdefault(inc_ext, []).append(inc_low)
            if inc_cat:
                incoming_core_by_cat_ext.setdefault((inc_cat, inc_ext), []).append(inc_low)

    cand_meta: List[Dict[str, Any]] = []
    target_core_nks_by_cat_ext: Dict[Tuple[str, str], set[str]] = {}
    unit_core_nks_by_ext: Dict[str, set[str]] = {}

    for cand in candidates:
        cand_res = cand.resolve()
        cand_low = cand.name.lower()
        cand_ext = cand.suffix.lower()
        cand_nk = normalize_mod_filename_key(cand.name)
        cand_rpo = re.search(r"lumpinou_rpo_collection_(m\d+)_", cand_low)
        cand_special = _is_variant_or_edition_protected_file(cand.name)
        cand_cat = _lookup_catalog_id_safe(cand.name)
        in_unit = cand_res in unit_res_set
        cand_info = {
            "path": cand,
            "res": cand_res,
            "low": cand_low,
            "ext": cand_ext,
            "nk": cand_nk,
            "rpo_slot": cand_rpo.group(1) if cand_rpo else "",
            "special": cand_special,
            "cat": cand_cat,
            "in_unit": in_unit,
        }
        cand_meta.append(cand_info)
        if not cand_special:
            if cand_cat and is_safe_subpath(cand_res, target_dir_res, allow_equal=False):
                target_core_nks_by_cat_ext.setdefault((cand_cat, cand_ext), set()).add(cand_nk or cand_low)
            if in_unit:
                unit_core_nks_by_ext.setdefault(cand_ext, set()).add(cand_nk or cand_low)

    superseded: List[Path] = []
    seen_superseded: set[Path] = set()
    dest_parent_hints: Dict[str, Path] = {}

    for c_info in cand_meta:
        matched_inc: Optional[Dict[str, Any]] = None
        for inc_m in incoming_meta:
            if c_info["ext"] != inc_m["ext"]:
                continue

            # 1) 정확히 일치 또는 버전/날짜 정규화 키 일치
            if c_info["low"] == inc_m["low"] or (inc_m["nk"] and c_info["nk"] == inc_m["nk"]):
                matched_inc = inc_m
                break

            # 2) RPO Collection 모듈 슬롯(M00~M19) 일치
            if inc_m["rpo_slot"] and c_info["rpo_slot"] == inc_m["rpo_slot"]:
                matched_inc = inc_m
                break

            # 3) 카탈로그 고유 식별자 또는 업데이트 대상 단일 코어 유닛 개명 교체
            if not c_info["special"] and not inc_m["special"]:
                inc_cat = inc_m["cat"]
                cand_cat = c_info["cat"] or (exp_cat if c_info["in_unit"] else "")
                if (
                    inc_cat
                    and cand_cat == inc_cat
                    and len(incoming_core_by_cat_ext.get((inc_cat, inc_m["ext"]), [])) == 1
                ):
                    target_nks = target_core_nks_by_cat_ext.get((inc_cat, inc_m["ext"]), set())
                    unit_nks = unit_core_nks_by_ext.get(inc_m["ext"], set())
                    if len(target_nks) <= 1 or (c_info["in_unit"] and len(unit_nks) <= 1):
                        matched_inc = inc_m
                        break

                if (
                    c_info["in_unit"]
                    and len(incoming_core_by_ext.get(inc_m["ext"], [])) == 1
                    and len(unit_core_nks_by_ext.get(inc_m["ext"], set())) <= 1
                ):
                    matched_inc = inc_m
                    break

        if matched_inc is not None:
            cand_p = c_info["path"]
            if c_info["res"] not in seen_superseded:
                seen_superseded.add(c_info["res"])
                superseded.append(cand_p)
            try:
                if is_safe_subpath(cand_p.parent, target_dir_res, allow_equal=True):
                    dest_parent_hints.setdefault(matched_inc["low"], cand_p.parent)
            except OSError:
                pass

    return superseded, dest_parent_hints


def _verify_and_move_whitelisted_files(
    selected_files: List[Path],
    archive_path: Path,
    staging_dir: Path,
    target_dir_resolved: Path,
    existing_rel_map: Optional[Dict[str, Path]] = None,
    existing_norm_rel_map: Optional[Dict[str, Path]] = None,
    pre_remove_callback: Optional[Callable[[Path], None]] = None,
    known_existing_files: Optional[List[Path]] = None,
    selected_file_path: Optional[Path] = None,
    include_subdirs: bool = False,
    mods_root_resolved: Optional[Path] = None,
    expected_catalog_id: Optional[str] = None,
    protected_paths: Optional[List[Path]] = None,
) -> List[Path]:
    """선별된 화이트리스트 파일(.package, .ts4script)의 바이너리 헤더 및 경로 안전성을 전수 검증한 뒤,
    로컬 폴더 내 구버전/동일 카탈로그 파일을 먼저 백업 및 안전 제거하고 새 버전 파일을 배치합니다.
    """
    verified_files: List[Path] = []
    for src_file in selected_files:
        if not is_whitelisted_mod_file(src_file, ALLOWED_MOD_WHITELIST_EXTENSIONS):
            continue

        # 1단계: 확장자만 .package / .ts4script로 위장한 PE 실행 파일('MZ') 사전 차단 (로컬 파일 손상 전 중단)
        with open(src_file, "rb") as sf:
            magic = sf.read(4)
        if magic.startswith(b"MZ"):
            _abort_and_purge_unsafe_archive(
                archive_path=archive_path,
                temp_extract_dir=staging_dir,
                offending_entry=src_file.name,
                reason="허용 확장자로 위장된 Windows 실행 파일(PE MZ 헤더)이 감지되었습니다.",
                is_dangerous_ext=True,
            )
        verified_files.append(src_file)

    if not verified_files:
        return []

    incoming_names = [_normalize_leaf_filename(sf.name) for sf in verified_files]
    superseded_files, dest_parent_hints = find_superseded_mod_files(
        incoming_names=incoming_names,
        target_dir_resolved=target_dir_resolved,
        mods_root_resolved=mods_root_resolved,
        known_existing_files=known_existing_files,
        selected_file_path=selected_file_path,
        include_subdirs=include_subdirs,
        expected_catalog_id=expected_catalog_id,
        protected_paths=protected_paths,
    )

    merged_rel_map: Dict[str, Path] = dict(existing_rel_map or {})
    for inc_low, hint_parent in dest_parent_hints.items():
        if inc_low not in merged_rel_map and is_safe_subpath(hint_parent, target_dir_resolved, allow_equal=True):
            merged_rel_map[inc_low] = hint_parent / inc_low

    planned_moves: List[Tuple[Path, Path]] = []
    for src_file in verified_files:
        dest_file = _resolve_install_dest_path(
            src_file=src_file,
            staging_dir=staging_dir,
            target_dir_resolved=target_dir_resolved,
            existing_rel_map=merged_rel_map,
            existing_norm_rel_map=existing_norm_rel_map,
        )
        if not is_safe_subpath(dest_file, target_dir_resolved):
            _abort_and_purge_unsafe_archive(
                archive_path=archive_path,
                temp_extract_dir=staging_dir,
                offending_entry=src_file.name,
                reason=f"최종 이동 경로('{dest_file}')가 대상 Mods 폴더('{target_dir_resolved}') 바깥을 가리킵니다.",
            )
        planned_moves.append((src_file, dest_file))

    # 2단계: 새 버전 파일 배치 전 기존 구버전/동일 대상 파일 먼저 백업 및 안전 제거
    removed_res: set[Path] = set()
    for old_f in superseded_files:
        try:
            old_res = old_f.resolve()
            if old_res in removed_res:
                continue
            removed_res.add(old_res)
        except OSError:
            pass
        if pre_remove_callback is not None:
            pre_remove_callback(old_f)
        safe_remove(old_f)

    for _, dest_file in planned_moves:
        if dest_file.exists() or dest_file.is_symlink():
            if pre_remove_callback is not None and dest_file.exists():
                pre_remove_callback(dest_file)
            safe_remove(dest_file)

    # 3단계: 검증된 새 버전 파일 배치
    moved_files: List[Path] = []
    for src_file, dest_file in planned_moves:
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_file), str(dest_file))
        if dest_file not in moved_files:
            moved_files.append(dest_file)

    return moved_files


def _collect_existing_target_files(
    target_dir_resolved: Path,
    include_subdirs: bool = False,
) -> Tuple[set[str], set[str], Dict[str, Path], Dict[str, Path]]:
    """대상 설치 폴더(필요 시 모드 전용 하위 폴더 포함)의 기존 모드 파일 이름 및 정규화 키 맵을 수집합니다."""
    existing_names_lower: set[str] = set()
    existing_norm_keys: set[str] = set()
    existing_rel_map: Dict[str, Path] = {}
    existing_norm_rel_map: Dict[str, Path] = {}

    iterator = target_dir_resolved.rglob("*") if include_subdirs else target_dir_resolved.iterdir()
    for f in iterator:
        if not f.is_file() or f.is_symlink():
            continue
        if f.suffix.lower() not in ALLOWED_MOD_WHITELIST_EXTENSIONS:
            continue
        low = f.name.lower()
        nk = normalize_mod_filename_key(f.name)
        existing_names_lower.add(low)
        if nk:
            existing_norm_keys.add(nk)
        if low not in existing_rel_map:
            existing_rel_map[low] = f
        if nk and nk not in existing_norm_rel_map:
            existing_norm_rel_map[nk] = f

    return existing_names_lower, existing_norm_keys, existing_rel_map, existing_norm_rel_map


def extract_zip(
    zip_path: Path,
    target_dir: Path,
    target_filename: Optional[str] = None,
    overwrite_mode: str = "all",
    temp_work_dir: Optional[Path] = None,
    known_existing_files: Optional[List[Path]] = None,
    include_subdirs: bool = False,
    force_include_names: Optional[set[str]] = None,
    pre_remove_callback: Optional[Callable[[Path], None]] = None,
    selected_file_path: Optional[Path] = None,
    mods_root_resolved: Optional[Path] = None,
    expected_catalog_id: Optional[str] = None,
    protected_paths: Optional[List[Path]] = None,
) -> list[Path]:
    """ZIP / RAR / 7Z 압축 파일을 디스크에 추출하기 전 엔트리 헤더 전체를 보안 검증(경로 이탈 및 위험 확장자 차단)하고,
    임시 작업 폴더에 먼저 압축을 푼 뒤 화이트리스트 확장자(.package, .ts4script) 파일만 실제 대상 폴더(target_dir)로
    이동(move)시키며, 나머지 불필요한 모든 파일은 임시 폴더 정리 시 즉시 폐기합니다.
    """
    suffix = zip_path.suffix.lower()

    # 1. ZIP 파일 처리
    if suffix == ".zip":
        if not zipfile.is_zipfile(zip_path):
            safe_remove(zip_path)
            raise ValueError(f"'{zip_path.name}' 파일이 유효한 ZIP 압축 파일이 아닙니다.")

        primary_check_dir = (temp_work_dir if temp_work_dir is not None else target_dir).resolve()
        all_entries = validate_zip_entries(zip_path, primary_check_dir)

        target_dir_resolved = Path(os.path.abspath(str(target_dir.resolve())))
        target_dir_resolved.mkdir(parents=True, exist_ok=True)
        existing_names_lower, existing_norm_keys, existing_rel_map, existing_norm_rel_map = (
            _collect_existing_target_files(target_dir_resolved, include_subdirs=include_subdirs)
        )
        for kf in known_existing_files or []:
            if kf.exists() and kf.is_file() and kf.suffix.lower() in ALLOWED_MOD_WHITELIST_EXTENSIONS:
                low = kf.name.lower()
                nk = normalize_mod_filename_key(kf.name)
                existing_names_lower.add(low)
                if nk:
                    existing_norm_keys.add(nk)
                existing_rel_map.setdefault(low, kf)
                if nk:
                    existing_norm_rel_map.setdefault(nk, kf)

        stage_parent = temp_work_dir.resolve() if temp_work_dir is not None else None
        if stage_parent is not None:
            stage_parent.mkdir(parents=True, exist_ok=True)

        run_stage_dir = Path(
            tempfile.mkdtemp(
                prefix="s4mod_zip_stage_",
                dir=str(stage_parent) if stage_parent is not None else None,
            )
        ).resolve()

        try:
            # 실제 압축이 풀리는 전용 임시 폴더 기준으로도 경로 계층 재검증
            validate_zip_entries(zip_path, run_stage_dir)

            extracted_in_stage: List[Path] = []
            violation_entry: Optional[str] = None
            violation_reason: Optional[str] = None

            with zipfile.ZipFile(zip_path, "r") as zf:
                for idx_m, member in enumerate(all_entries):
                    if member.is_dir():
                        continue
                    norm_slash = member.filename.replace("\\", "/")
                    if norm_slash.startswith("__MACOSX/") or "/__MACOSX/" in norm_slash:
                        continue
                    leaf_name = _normalize_leaf_filename(norm_slash)
                    if leaf_name in ("", ".DS_Store", "Thumbs.db"):
                        continue

                    normalized_rel = norm_slash.replace("/", os.sep)
                    staged_path = Path(os.path.abspath(os.path.join(str(run_stage_dir), normalized_rel)))
                    if not is_safe_subpath(staged_path, run_stage_dir):
                        violation_entry = member.filename
                        violation_reason = (
                            f"임시 폴더 해제 경로('{staged_path}')가 기준 임시 폴더('{run_stage_dir}') 바깥을 가리킵니다."
                        )
                        break

                    # Windows MAX_PATH(260자) 초과 중첩 폴더의 경우에도 임시 폴더 내부 하위 슬롯에 안전하게 해제
                    if os.name == "nt" and len(str(staged_path)) >= 240:
                        staged_path = run_stage_dir / f"_long_{idx_m}" / leaf_name
                        if not is_safe_subpath(staged_path, run_stage_dir):
                            violation_entry = member.filename
                            violation_reason = "임시 폴더 긴 경로 슬롯 검증에 실패했습니다."
                            break

                    staged_path.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member, "r") as src_f, open(staged_path, "wb") as dst_f:
                        shutil.copyfileobj(src_f, dst_f)
                    try:
                        if member.date_time and member.date_time[0] >= 1980:
                            entry_ts = datetime.datetime(*member.date_time[:6]).timestamp()
                            if entry_ts > 0:
                                os.utime(staged_path, (entry_ts, entry_ts))
                    except Exception:
                        pass
                    extracted_in_stage.append(staged_path)

            if violation_reason is not None:
                _abort_and_purge_unsafe_archive(
                    archive_path=zip_path,
                    temp_extract_dir=run_stage_dir,
                    offending_entry=violation_entry or "<unknown>",
                    reason=violation_reason,
                )

            # 화이트리스트(.package, .ts4script)에 해당하는 파일만 선별 (나머지 .txt, .png, .cfg 등은 임시 폴더에 잔류 후 폐기)
            whitelisted_candidates = [
                f for f in extracted_in_stage
                if is_whitelisted_mod_file(f, ALLOWED_MOD_WHITELIST_EXTENSIONS)
            ]
            selected_to_move = _select_mods_for_installation(
                whitelisted_files=whitelisted_candidates,
                existing_names_lower=existing_names_lower,
                target_filename=target_filename,
                overwrite_mode=overwrite_mode,
                existing_norm_keys=existing_norm_keys,
                force_include_names=force_include_names,
            )
            return _verify_and_move_whitelisted_files(
                selected_files=selected_to_move,
                archive_path=zip_path,
                staging_dir=run_stage_dir,
                target_dir_resolved=target_dir_resolved,
                existing_rel_map=existing_rel_map,
                existing_norm_rel_map=existing_norm_rel_map,
                pre_remove_callback=pre_remove_callback,
                known_existing_files=known_existing_files,
                selected_file_path=selected_file_path,
                include_subdirs=include_subdirs,
                mods_root_resolved=mods_root_resolved,
                expected_catalog_id=expected_catalog_id,
                protected_paths=protected_paths,
            )
        finally:
            # 화이트리스트로 이동되지 않은 나머지 불필요한 모든 파일 및 임시 스테이징 폴더 즉시 폐기
            safe_remove(run_stage_dir)

    # 2. RAR / 7Z 등 아카이브 처리 (사전 헤더 검증 -> 임시 폴더 해제 -> 화이트리스트만 이동 -> 잔여 파일 일괄 폐기)
    target_dir_resolved = Path(os.path.abspath(str(target_dir.resolve())))
    target_dir_resolved.mkdir(parents=True, exist_ok=True)
    existing_names_lower, existing_norm_keys, existing_rel_map, existing_norm_rel_map = (
        _collect_existing_target_files(target_dir_resolved, include_subdirs=include_subdirs)
    )
    for kf in known_existing_files or []:
        if kf.exists() and kf.is_file() and kf.suffix.lower() in ALLOWED_MOD_WHITELIST_EXTENSIONS:
            low = kf.name.lower()
            nk = normalize_mod_filename_key(kf.name)
            existing_names_lower.add(low)
            if nk:
                existing_norm_keys.add(nk)
            existing_rel_map.setdefault(low, kf)
            if nk:
                existing_norm_rel_map.setdefault(nk, kf)

    stage_parent = temp_work_dir.resolve() if temp_work_dir is not None else None
    if stage_parent is not None:
        stage_parent.mkdir(parents=True, exist_ok=True)

    tmp_ext_path = Path(
        tempfile.mkdtemp(
            prefix="s4mod_tar_stage_",
            dir=str(stage_parent) if stage_parent is not None else None,
        )
    ).resolve()

    try:
        validate_archive_entries_via_tar(zip_path, tmp_ext_path)

        tar_exe = _resolve_system_tar_executable()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        subprocess.run(
            [tar_exe, "-xf", str(zip_path), "-C", str(tmp_ext_path)],
            check=True,
            capture_output=True,
            timeout=120,
            creationflags=creationflags,
        )

        whitelisted_candidates = []
        for f in tmp_ext_path.rglob("*"):
            if f.is_symlink():
                _abort_and_purge_unsafe_archive(
                    archive_path=zip_path,
                    temp_extract_dir=tmp_ext_path,
                    offending_entry=str(f),
                    reason="압축 해제된 임시 폴더 내부에서 심볼릭 링크(Symlink)가 감지되었습니다.",
                )
            if not is_safe_subpath(f, tmp_ext_path):
                _abort_and_purge_unsafe_archive(
                    archive_path=zip_path,
                    temp_extract_dir=tmp_ext_path,
                    offending_entry=str(f),
                    reason="압축 해제된 엔트리가 임시 작업 폴더 바깥을 가리킵니다.",
                )
            if f.is_file():
                bad_ext = inspect_dangerous_extension(f.name)
                if bad_ext is not None:
                    _abort_and_purge_unsafe_archive(
                        archive_path=zip_path,
                        temp_extract_dir=tmp_ext_path,
                        offending_entry=f.name,
                        reason=f"임시 폴더 내 위험 확장자('{bad_ext}') 파일이 감지되었습니다.",
                        is_dangerous_ext=True,
                    )
                if is_whitelisted_mod_file(f, ALLOWED_MOD_WHITELIST_EXTENSIONS):
                    whitelisted_candidates.append(f)

        selected_to_move = _select_mods_for_installation(
            whitelisted_files=whitelisted_candidates,
            existing_names_lower=existing_names_lower,
            target_filename=target_filename,
            overwrite_mode=overwrite_mode,
            existing_norm_keys=existing_norm_keys,
            force_include_names=force_include_names,
        )
        return _verify_and_move_whitelisted_files(
            selected_files=selected_to_move,
            archive_path=zip_path,
            staging_dir=tmp_ext_path,
            target_dir_resolved=target_dir_resolved,
            existing_rel_map=existing_rel_map,
            existing_norm_rel_map=existing_norm_rel_map,
            pre_remove_callback=pre_remove_callback,
            known_existing_files=known_existing_files,
            selected_file_path=selected_file_path,
            include_subdirs=include_subdirs,
            mods_root_resolved=mods_root_resolved,
            expected_catalog_id=expected_catalog_id,
            protected_paths=protected_paths,
        )
    finally:
        # 이동되지 않은 모든 비화이트리스트 파일 및 임시 폴더 즉시 폐기
        safe_remove(tmp_ext_path)


def safe_remove(path: Path) -> None:
    """파일 또는 디렉터리를 안전하게 삭제합니다 (심볼릭 링크는 대상 추적 없이 링크 자체만 제거)."""
    try:
        if path.is_symlink():
            path.unlink(missing_ok=True)
            return
        if not path.exists():
            return
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass
