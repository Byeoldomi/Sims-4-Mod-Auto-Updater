"""빌드 후처리 전용 보조 스크립트 (런타임 코드와 완전 분리)

완성된 배포용 실행 파일(.exe)의 무결성 검증용 SHA-256 해시값을 계산하여
터미널에 출력하고 'release_hash.txt' 파일로 자동 저장합니다.

사용 예시:
    python generate_release_hash.py
    python generate_release_hash.py "배포용/Sims 4 Mod Auto Updater/dist/Sims4ModUpdater_v0.1.5.exe"
    python generate_release_hash.py "배포용/Sims 4 Mod Auto Updater/dist/Sims4ModUpdater_v0.1.5.exe" -o "release_hash.txt"
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import sys
from pathlib import Path
from typing import List, Optional

HASH_CHUNK_SIZE = 1024 * 1024  # 1 MiB 스트리밍 버퍼
DEFAULT_HASH_FILENAME = "release_hash.txt"


def _configure_utf8_console() -> None:
    """Windows 터미널(cmd/PowerShell)에서 한글 출력 깨짐(cp949 오류)을 방지합니다."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def find_built_executable(base_dir: Path) -> Optional[Path]:
    """명시적인 .exe 경로가 주어지지 않았을 때 빌드 결과물 디렉터리(dist/)에서 최신 .exe 파일을 자동 탐색합니다."""
    candidate_dirs = [
        base_dir / "dist",
        base_dir / "배포용" / "Sims 4 Mod Auto Updater" / "dist",
        Path.cwd() / "dist",
        Path.cwd() / "배포용" / "Sims 4 Mod Auto Updater" / "dist",
    ]

    exe_candidates: List[Path] = []
    seen_resolved: set[Path] = set()

    for d in candidate_dirs:
        if not d.exists() or not d.is_dir():
            continue
        for p in d.glob("*.exe"):
            if p.is_symlink() or not p.is_file():
                continue
            resolved = p.resolve()
            if resolved not in seen_resolved:
                seen_resolved.add(resolved)
                exe_candidates.append(resolved)

    if not exe_candidates:
        return None

    # Sims4ModUpdater*.exe 이름을 우선하되, 동일 조건에서는 가장 최근 빌드된(mtime 기준) 파일 선택
    exe_candidates.sort(
        key=lambda p: (
            1 if p.name.lower().startswith("sims4modupdater") else 0,
            p.stat().st_mtime,
        ),
        reverse=True,
    )
    return exe_candidates[0]


def validate_executable_file(exe_path: Path) -> None:
    """해시 계산 전 대상 .exe 파일이 유효한 Windows PE 실행 파일인지 검증합니다."""
    if not exe_path.exists():
        raise FileNotFoundError(f"대상 실행 파일을 찾을 수 없습니다: {exe_path}")
    if exe_path.is_symlink():
        raise ValueError(f"심볼릭 링크 파일은 허용되지 않습니다: {exe_path}")
    if not exe_path.is_file():
        raise ValueError(f"지정된 경로가 일반 파일이 아닙니다: {exe_path}")
    if exe_path.suffix.lower() != ".exe":
        raise ValueError(f"배포용 실행 파일(.exe)만 지원합니다: {exe_path.name}")

    file_size = exe_path.stat().st_size
    if file_size <= 0:
        raise ValueError(f"실행 파일 크기가 0 바이트입니다 (불완전한 빌드): {exe_path}")

    with open(exe_path, "rb") as f:
        magic = f.read(2)
    if magic != b"MZ":
        raise ValueError(
            f"유효한 Windows 실행 파일(PE 'MZ' 헤더)이 아닙니다: {exe_path}"
        )


def compute_sha256(file_path: Path) -> str:
    """대용량 실행 파일도 메모리 부담 없이 처리하도록 청크 단위로 SHA-256 해시값을 계산합니다."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(HASH_CHUNK_SIZE):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def build_release_hash_report(exe_path: Path, sha256_value: str) -> str:
    """release_hash.txt에 기록할 상세 무결성 정보 및 표준 sha256sum 호환 라인을 생성합니다."""
    stat_info = exe_path.stat()
    file_size_bytes = stat_info.st_size
    file_size_mb = file_size_bytes / (1024 * 1024)
    modified_at = datetime.datetime.fromtimestamp(stat_info.st_mtime).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    generated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return (
        f"파일명: {exe_path.name}\n"
        f"파일 크기: {file_size_mb:.2f} MB ({file_size_bytes:,} bytes)\n"
        f"빌드(수정) 일시: {modified_at}\n"
        f"해시 생성 일시: {generated_at}\n"
        f"SHA-256: {sha256_value}\n"
        f"\n"
        f"# sha256sum / PowerShell 검증 호환 형식\n"
        f"{sha256_value} *{exe_path.name}\n"
    )


def write_text_atomic(target_path: Path, content: str) -> None:
    """파일 쓰기 중단으로 인한 손상을 방지하기 위해 임시 파일에 기록한 뒤 원자적으로 교체합니다."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f".{target_path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, target_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def resolve_output_paths(
    exe_path: Path,
    script_dir: Path,
    explicit_output: Optional[str],
) -> List[Path]:
    """출력 파일 경로를 결정합니다.
    - -o/--output 지정 시: 지정된 경로에만 저장
    - 미지정 시: 실행 파일이 위치한 배포 폴더(dist/release_hash.txt) 및 스크립트 기준 폴더(release_hash.txt)에 저장
    """
    if explicit_output:
        out_p = Path(explicit_output)
        if out_p.exists() and out_p.is_dir():
            out_p = out_p / DEFAULT_HASH_FILENAME
        return [out_p.resolve()]

    targets: List[Path] = []
    for candidate in (
        exe_path.parent / DEFAULT_HASH_FILENAME,
        script_dir / DEFAULT_HASH_FILENAME,
    ):
        resolved = candidate.resolve()
        if resolved not in targets:
            targets.append(resolved)
    return targets


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="완성된 배포용 실행 파일(.exe)의 SHA-256 해시값을 계산하고 release_hash.txt로 저장하는 빌드 후처리 스크립트"
    )
    parser.add_argument(
        "exe_path",
        nargs="?",
        default=None,
        help="해시를 계산할 배포용 .exe 파일 경로 (생략 시 dist/ 폴더 내 최신 .exe 자동 탐색)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help=f"결과를 저장할 파일 경로 (기본값: dist/{DEFAULT_HASH_FILENAME} 및 프로젝트 폴더 {DEFAULT_HASH_FILENAME})",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    _configure_utf8_console()
    args = parse_args(argv)
    script_dir = Path(__file__).resolve().parent

    try:
        if args.exe_path:
            target_exe = Path(args.exe_path).resolve()
        else:
            found_exe = find_built_executable(script_dir)
            if found_exe is None:
                print(
                    "[오류] 배포용 실행 파일(.exe)을 찾을 수 없습니다. 먼저 빌드를 수행하거나 .exe 경로를 인자로 지정해 주세요.",
                    file=sys.stderr,
                )
                return 1
            target_exe = found_exe

        validate_executable_file(target_exe)
        sha256_value = compute_sha256(target_exe)
        report_content = build_release_hash_report(target_exe, sha256_value)
        output_paths = resolve_output_paths(target_exe, script_dir, args.output)

        for out_path in output_paths:
            write_text_atomic(out_path, report_content)

        print("=" * 72)
        print("[Post-Build] 배포용 실행 파일(.exe) SHA-256 무결성 해시 생성 완료")
        print("-" * 72)
        print(f"대상 경로: {target_exe}")
        print(report_content.strip())
        print("-" * 72)
        for idx, saved_path in enumerate(output_paths, 1):
            label = f"저장 위치 {idx}" if len(output_paths) > 1 else "저장 위치"
            print(f"{label}: {saved_path}")
        print("=" * 72)
        return 0

    except Exception as exc:
        print(f"[오류] SHA-256 해시 생성 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
