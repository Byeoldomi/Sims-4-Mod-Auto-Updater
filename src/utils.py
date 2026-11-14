import hashlib
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Optional, Callable
import requests

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
    """URL에서 파일을 다운로드합니다."""
    import urllib.parse

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Patreon / Postype 무료 공개 포스트(#free_member_file=...) 처리
    if "#free_member_file=" in url:
        base_u, frag = url.split("#", 1)
        qs = urllib.parse.parse_qs(frag)
        target_fn = (qs.get("free_member_file") or [dest_path.name])[0]
        alt_fn = (
            target_fn.replace("_KOR_", "(KOR)").replace("_kor_", "(KOR)")
            if target_fn.lower().startswith("_kor_")
            else (f"_KOR_{target_fn[5:]}" if target_fn.lower().startswith("(kor)") else target_fn)
        )
        search_dirs = [d for d in (fallback_source_dir, Path.home() / "Downloads") if d and d.exists()]
        for s_dir in search_dirs:
            for cand_name in (target_fn, alt_fn):
                cand_local = s_dir / cand_name
                if cand_local.exists() and cand_local.is_file():
                    shutil.copy2(cand_local, dest_path)
                    return dest_path

    # Itch.io 지연 업로드 다운로드 링크(#itchio_upload_id=...) 처리
    if "#itchio_upload_id=" in url:
        base_u, frag = url.split("#", 1)
        qs = urllib.parse.parse_qs(frag)
        target_fn = (qs.get("file_name") or [dest_path.name])[0]
        from src.finder import inspect_remote_mod_page
        refreshed = inspect_remote_mod_page(base_u, target_mod_name=target_fn, timeout=15)
        if refreshed.get("download_url"):
            url = refreshed["download_url"]

    # MediaFire 파일 공유 페이지(mediafire.com/file/...)인 경우 실제 직접 다운로드 링크(download*.mediafire.com)로 변환
    if "mediafire.com/file/" in url.lower():
        from src.finder import inspect_remote_mod_page
        mf_res = inspect_remote_mod_page(url, target_mod_name=target_mod_name or dest_path.name, timeout=15)
        if mf_res.get("download_url"):
            url = mf_res["download_url"]

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

    response = requests.get(url, headers=headers, stream=True, timeout=30)
    # Itch.io R2 서명 URL(유효기간 60초)이 만료되어 400/403이 발생한 경우 즉시 새 서명 URL을 발급받아 재시도
    if response.status_code in (400, 403) and page_url and ".itch.io" in page_url.lower():
        response.close()
        from src.finder import inspect_remote_mod_page
        refreshed = inspect_remote_mod_page(page_url, target_mod_name=target_mod_name or dest_path.name, timeout=15)
        if refreshed.get("download_url"):
            url = refreshed["download_url"]
            response = requests.get(url, headers=headers, stream=True, timeout=30)

    response.raise_for_status()

    total_size = int(response.headers.get("content-length", 0))
    downloaded = 0

    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_size > 0:
                    progress_callback(downloaded, total_size)

    return dest_path

def verify_downloaded_mod_file(
    file_path: Path,
    expected_target_name: Optional[str] = None,
    target_dir: Optional[Path] = None,
) -> None:
    """다운로드된 파일이 실제 유효한 심즈 4 모드(.package, .ts4script) 또는 모드 압축 파일(.zip 등)인지
    압축 해제 및 덮어쓰기 전에 사전 검증합니다. (잘못된 웹 페이지 응답이나 무관한 파일 덮어쓰기 방지)
    """
    if not file_path.exists() or file_path.stat().st_size == 0:
        raise ValueError("다운로드된 파일이 비어 있거나 존재하지 않습니다.")

    with open(file_path, "rb") as f:
        head = f.read(512)

    head_strip = head.lstrip().lower()
    if head_strip.startswith((b"<!doctype html", b"<html", b"<head", b"<script", b"<?xml")):
        raise ValueError(
            "다운로드된 파일이 모드 파일이 아닌 웹 페이지(HTML) 응답입니다. "
            "로그인이 필요하거나 직접 다운로드가 차단된 링크일 수 있으므로 브라우저에서 직접 다운로드해 주세요."
        )

    suffix = file_path.suffix.lower()
    if suffix == ".package":
        if not head.startswith(b"DBPF"):
            raise ValueError(f"'{file_path.name}' 파일이 유효한 심즈 4 .package(DBPF) 형식이 아닙니다.")
        return

    if suffix == ".ts4script":
        if not zipfile.is_zipfile(file_path):
            raise ValueError(f"'{file_path.name}' 파일이 유효한 심즈 4 .ts4script 아카이브 형식이 아닙니다.")
        return

    if suffix == ".zip":
        if not zipfile.is_zipfile(file_path):
            raise ValueError(f"'{file_path.name}' 파일이 손상되었거나 유효한 ZIP 압축 파일이 아닙니다.")
        with zipfile.ZipFile(file_path, "r") as zf:
            names = [
                Path(m.filename.replace("\\", "/")).name
                for m in zf.infolist()
                if not m.is_dir()
                and Path(m.filename.replace("\\", "/")).name not in ("", ".DS_Store", "Thumbs.db")
            ]
            mod_files = [
                n for n in names
                if Path(n).suffix.lower() in (
                    ".package", ".ts4script",
                    ".trayitem", ".blueprint", ".bpi", ".householdbinary", ".hhi", ".sgi", ".rmi", ".room",
                )
            ]
            if not mod_files:
                raise ValueError(
                    f"압축 파일('{file_path.name}') 내부에 심즈 4 모드/부지·심 파일(.package / .ts4script / Tray 파일)이 포함되어 있지 않아 설치를 중단했습니다."
                )


def extract_zip(
    zip_path: Path,
    target_dir: Path,
    target_filename: Optional[str] = None,
    overwrite_mode: str = "all",
) -> list[Path]:
    """ZIP / RAR / 7Z 압축 파일 내부의 하위 폴더 구조를 무시하고, 파일만 대상 디렉터리(target_dir)에 직접 덮어쓰기 형태로 추출합니다.
    - overwrite_mode == 'single': target_filename과 일치하는 단일 파일(또는 동일 확장자 본체 파일 1개)만 추출합니다.
    - overwrite_mode == 'all': 압축 파일 내 모드 파일 전체(다중 선택형 Constructor 아카이브의 경우 target_dir에 이미 설치된 모든 일치 파일)를 추출합니다.
    """
    import subprocess
    import tempfile

    target_dir.mkdir(parents=True, exist_ok=True)
    extracted_files: list[Path] = []
    suffix = zip_path.suffix.lower()
    existing_names_lower = {f.name.lower() for f in target_dir.iterdir() if f.is_file()}
    target_ext = Path(target_filename).suffix.lower() if target_filename else ""

    if suffix == ".zip" and zipfile.is_zipfile(zip_path):
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = [
                m for m in zf.infolist()
                if not m.is_dir()
                and not m.filename.replace("\\", "/").startswith("__MACOSX/")
                and "/__MACOSX/" not in m.filename.replace("\\", "/")
                and Path(m.filename.replace("\\", "/")).name not in ("", ".DS_Store", "Thumbs.db")
            ]
            mod_members = [
                m for m in members
                if Path(m.filename.replace("\\", "/")).suffix.lower() in (".package", ".ts4script")
            ]
            if mod_members:
                members = mod_members

            if overwrite_mode == "single" and target_filename:
                exact_matches = [
                    m for m in members
                    if Path(m.filename.replace("\\", "/")).name.lower() == target_filename.lower()
                ]
                if exact_matches:
                    members = [exact_matches[0]]
                elif target_ext:
                    same_ext = [
                        m for m in members
                        if Path(m.filename.replace("\\", "/")).suffix.lower() == target_ext
                    ]
                    if same_ext:
                        members = [same_ext[0]]
            elif overwrite_mode == "all":
                installed_matches = [
                    m for m in members
                    if Path(m.filename.replace("\\", "/")).name.lower() in existing_names_lower
                ]
                has_choose_one = any("choose" in m.filename.lower() for m in members)
                is_all_aichat = all("sims4_ai_chat" in Path(m.filename.replace("\\", "/")).name.lower() for m in members)
                if not is_all_aichat and installed_matches and len(members) > len(installed_matches) and (len(members) > 4 or has_choose_one):
                    members = installed_matches
                elif not installed_matches and target_filename and (len(members) > 4 or has_choose_one):
                    exact_m = [
                        m for m in members
                        if Path(m.filename.replace("\\", "/")).name.lower() == target_filename.lower()
                    ]
                    if exact_m:
                        members = exact_m

            for member in members:
                base_name = Path(member.filename.replace("\\", "/")).name
                dest_file = target_dir / base_name
                with zf.open(member, "r") as src_f, open(dest_file, "wb") as dst_f:
                    shutil.copyfileobj(src_f, dst_f)
                extracted_files.append(dest_file)
        return extracted_files

    # RAR / 7Z 등 아카이브는 Windows 내장 bsdtar(tar.exe)로 임시 폴더에 압축 해제 후 복사
    with tempfile.TemporaryDirectory() as tmp_ext:
        tmp_ext_path = Path(tmp_ext)
        subprocess.run(["tar", "-xf", str(zip_path), "-C", str(tmp_ext_path)], check=True, capture_output=True)
        all_candidates = [
            f for f in tmp_ext_path.rglob("*")
            if f.is_file() and f.name not in (".DS_Store", "Thumbs.db")
        ]
        mod_only = [f for f in all_candidates if f.suffix.lower() in (".package", ".ts4script")]
        if mod_only:
            all_candidates = mod_only

        if overwrite_mode == "single" and target_filename:
            exact_matches = [f for f in all_candidates if f.name.lower() == target_filename.lower()]
            if exact_matches:
                all_candidates = [exact_matches[0]]
            elif target_ext:
                same_ext = [f for f in all_candidates if f.suffix.lower() == target_ext]
                if same_ext:
                    all_candidates = [same_ext[0]]
        elif overwrite_mode == "all":
            installed_matches = [f for f in all_candidates if f.name.lower() in existing_names_lower]
            if installed_matches:
                all_candidates = installed_matches

        for src_file in all_candidates:
            dest_file = target_dir / src_file.name
            shutil.copy2(src_file, dest_file)
            extracted_files.append(dest_file)

    return extracted_files

def safe_remove(path: Path) -> None:
    """파일 또는 디렉터리를 안전하게 삭제합니다."""
    if not path.exists():
        return
    if path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
