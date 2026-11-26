import datetime
import hashlib
import os
import subprocess
import sys
from pathlib import Path

APP_NAME = "Sims4ModUpdater_v0.1.6"
ENTRY_SCRIPT = "main.py"
ICON_PATH = Path(__file__).parent.resolve() / "ui" / "app_icon.ico"


def compute_sha256(file_path: Path) -> str:
    """지정된 파일의 SHA-256 해시값을 계산하여 16진수 문자열로 반환합니다."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def build_executable() -> int:
    project_root = Path(__file__).parent.resolve()
    os.chdir(project_root)

    # Windows PyInstaller --add-data 구분자(';')
    sep = ";" if os.name == "nt" else ":"

    add_data_args = []
    ui_dir = project_root / "ui"
    if ui_dir.exists() and ui_dir.is_dir():
        for asset_name in ("index.html", "styles.css", "app.js", "app_icon.ico"):
            asset_path = ui_dir / asset_name
            if asset_path.exists():
                add_data_args.extend(["--add-data", f"ui/{asset_name}{sep}."])
        add_data_args.extend(["--add-data", f"ui{sep}ui"])

    icon_args = []
    if ICON_PATH.exists() and ICON_PATH.is_file():
        icon_args = ["--icon", str(ICON_PATH)]

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--collect-all",
        "webview",
        "--collect-data",
        "certifi",
        "--hidden-import",
        "src.finder",
        "--exclude-module",
        "rich",
        "--exclude-module",
        "numpy",
        "--exclude-module",
        "PIL",
        "--exclude-module",
        "pygame",
        "--exclude-module",
        "lxml",
        "--exclude-module",
        "generate_release_hash",
        *icon_args,
        *add_data_args,
        "--name",
        APP_NAME,
        ENTRY_SCRIPT,
    ]

    print("=" * 70)
    print(f"[Build] '{APP_NAME}.exe' 단일 실행 파일 빌드를 시작합니다...")
    print(f"[Command] {' '.join(cmd)}")
    print("=" * 70)

    result = subprocess.run(cmd, cwd=str(project_root), timeout=600)
    if result.returncode != 0:
        print(f"\n[Error] PyInstaller 빌드가 실패했습니다 (종료 코드: {result.returncode}).")
        return result.returncode

    exe_suffix = ".exe" if os.name == "nt" else ""
    exe_path = project_root / "dist" / f"{APP_NAME}{exe_suffix}"
    if not exe_path.exists():
        print(f"\n[Error] 빌드 결과 파일을 찾을 수 없습니다: {exe_path}")
        return 1

    sha256_value = compute_sha256(exe_path)
    file_size_bytes = exe_path.stat().st_size
    file_size_mb = file_size_bytes / (1024 * 1024)
    built_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    checksum_content = (
        f"파일명: {exe_path.name}\n"
        f"빌드 일시: {built_at}\n"
        f"파일 크기: {file_size_mb:.2f} MB ({file_size_bytes:,} bytes)\n"
        f"SHA-256: {sha256_value}\n"
    )

    root_checksum_path = project_root / "checksum.txt"
    dist_checksum_path = project_root / "dist" / "checksum.txt"
    root_checksum_path.write_text(checksum_content, encoding="utf-8")
    dist_checksum_path.write_text(checksum_content, encoding="utf-8")

    print("\n" + "=" * 70)
    print("[Build Success] 단일 실행 파일 빌드 및 SHA-256 해시 생성 완료")
    print("-" * 70)
    print(checksum_content.strip())
    print("=" * 70)

    post_build_script = project_root / "generate_release_hash.py"
    if post_build_script.exists():
        subprocess.run([sys.executable, str(post_build_script)], cwd=str(project_root), check=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(build_executable())
