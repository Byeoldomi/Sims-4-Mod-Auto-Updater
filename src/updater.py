import copy
import json
import re
import tempfile
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import requests
from packaging import version

from src.utils import (
    ALLOWED_MOD_WHITELIST_EXTENSIONS,
    ArchiveSecurityError,
    DangerousFileExtensionError,
    InsecureUrlSecurityError,
    NetworkSecurityError,
    SslCertificateSecurityError,
    ZipSlipSecurityError,
    download_file,
    extract_zip,
    find_superseded_mod_files,
    inspect_dangerous_extension,
    is_auxiliary_non_mod_archive,
    is_safe_subpath,
    is_valid_https_url,
    is_whitelisted_mod_file,
    log_security_warning,
    normalize_mod_filename_key,
    safe_https_get,
    safe_remove,
    validate_https_url,
    verify_downloaded_mod_file,
)
from src.backup import BackupManager

class ModUpdater:
    """모드 업데이트 관리 엔진"""

    _MANIFEST_CACHE_LOCK = threading.Lock()
    _MANIFEST_CACHE: Dict[str, Tuple[Tuple[int, int], List[Dict[str, Any]]]] = {}

    def __init__(self, mods_folder: Path, manifest_path: Path, backup_manager: Optional[BackupManager] = None):
        self.mods_folder = mods_folder
        self.manifest_path = manifest_path
        self.backup_manager = backup_manager

    def load_manifest(self) -> List[Dict[str, Any]]:
        """모드 목록 매니페스트를 로드합니다. (동일 파일 mtime/size 기준 스레드 안전 메모리 캐싱)"""
        if not self.manifest_path.exists():
            return []
        try:
            st = self.manifest_path.stat()
            cache_key = str(self.manifest_path.resolve())
            sig = (int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))), int(st.st_size))
            with self._MANIFEST_CACHE_LOCK:
                cached = self._MANIFEST_CACHE.get(cache_key)
                if cached and cached[0] == sig:
                    return copy.deepcopy(cached[1])

            with open(self.manifest_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                mods_data = data.get("mods", [])
                if not isinstance(mods_data, list):
                    mods_data = []

            with self._MANIFEST_CACHE_LOCK:
                self._MANIFEST_CACHE[cache_key] = (sig, copy.deepcopy(mods_data))
            return copy.deepcopy(mods_data)
        except Exception as e:
            print(f"[!] 매니페스트 읽기 실패: {e}")
            return []

    def save_manifest(self, mods: List[Dict[str, Any]]) -> None:
        """매니페스트 변경 사항을 저장합니다."""
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump({"mods": mods}, f, indent=4, ensure_ascii=False)
        try:
            st = self.manifest_path.stat()
            cache_key = str(self.manifest_path.resolve())
            sig = (int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))), int(st.st_size))
            with self._MANIFEST_CACHE_LOCK:
                self._MANIFEST_CACHE[cache_key] = (sig, copy.deepcopy(mods))
        except Exception:
            pass

    def get_pinned_url(self, target_name: str, folder_name: str = "") -> str:
        """mods_manifest.json에 해당 파일명(target_name)으로 검증·고정(Pinning)된 공식 배포 페이지 URL이 있으면 반환합니다.
        (폴더 하나에 여러 모드가 들어있는 경우 다른 모드의 URL을 잘못 가져오지 않도록 폴더명 매칭은 사용하지 않고 파일명만 매칭합니다.)
        """
        mods = self.load_manifest()
        t_low = (target_name or "").strip().lower()
        if not t_low:
            return ""
        is_xml_target = "xml" in t_low and "injector" in t_low
        for entry in mods:
            e_name = (entry.get("name") or "").strip().lower()
            e_local = (entry.get("local_file") or "").strip().lower()
            if t_low in (e_name, e_local) and e_name:
                pinned = (entry.get("pinned_page_url") or entry.get("homepage") or "").strip()
                pinned_low = pinned.lower()
                if not is_xml_target and (
                    "scumbumbomods.com/xml-injector" in pinned_low
                    or "curseforge.com/sims4/mods/xml-injector" in pinned_low
                ):
                    continue
                if pinned.lower().startswith("http://"):
                    log_security_warning(f"매니페스트 내 일반 HTTP 고정 URL 차단: '{pinned}'")
                    return ""
                if is_valid_https_url(pinned) and "google.com/search" not in pinned:
                    return pinned
        return ""

    def pin_verified_url(
        self,
        mod: Dict[str, Any],
        page_url: str,
        latest_ver: str = "",
        local_file_name: str = "",
        asset_name: str = "",
    ) -> None:
        """검증 완료된 모드의 공식 배포 페이지 URL(HTTPS 전용)을 파일명 기준으로 mods_manifest.json에 자동 기록(Pinning)합니다."""
        if not page_url or not is_valid_https_url(page_url) or "google.com/search" in page_url:
            if page_url and page_url.strip().lower().startswith("http://"):
                log_security_warning(f"일반 HTTP 배포 URL 고정(Pinning) 시도 차단: '{page_url}'")
            return
        try:
            mods = self.load_manifest()
            t_name = (local_file_name or mod.get("name") or "").strip()
            f_name = (mod.get("folder_name") or mod.get("install_folder") or t_name).strip()
            clean_asset = (asset_name or "").strip()
            if not t_name:
                return

            local_size: Optional[int] = None
            local_mtime: Optional[int] = None
            cand_paths: List[str] = []
            for ip_str in (mod.get("installed_paths") or []):
                if ip_str and Path(str(ip_str)).name.lower() == t_name.lower():
                    cand_paths.append(str(ip_str))
            fp_str = mod.get("file_path") or (
                mod["selected_file"].get("full_path") if isinstance(mod.get("selected_file"), dict) else ""
            )
            if fp_str and (not local_file_name or Path(str(fp_str)).name.lower() == t_name.lower()):
                cand_paths.append(str(fp_str))
            for cp_str in cand_paths:
                try:
                    cp = Path(cp_str)
                    if cp.exists() and cp.is_file():
                        st = cp.stat()
                        local_size = int(st.st_size)
                        local_mtime = int(st.st_mtime)
                        break
                except OSError:
                    continue

            updated = False
            for entry in mods:
                e_name = (entry.get("name") or "").strip().lower()
                e_local = (entry.get("local_file") or "").strip().lower()
                if t_name.lower() in (e_name, e_local):
                    entry["local_file"] = t_name
                    entry["pinned_page_url"] = page_url
                    if latest_ver:
                        entry["current_version"] = latest_ver
                    if clean_asset:
                        entry["installed_asset_name"] = clean_asset
                    if local_size is not None:
                        entry["local_file_size"] = local_size
                        entry["local_file_mtime"] = local_mtime
                    updated = True
                    break
            if not updated:
                new_entry: Dict[str, Any] = {
                    "name": t_name,
                    "local_file": t_name,
                    "source_type": mod.get("source_type", "generic_web"),
                    "install_folder": f_name or t_name,
                    "pinned_page_url": page_url,
                    "current_version": latest_ver,
                }
                if clean_asset:
                    new_entry["installed_asset_name"] = clean_asset
                if local_size is not None:
                    new_entry["local_file_size"] = local_size
                    new_entry["local_file_mtime"] = local_mtime
                mods.append(new_entry)
            self.save_manifest(mods)
        except Exception:
            pass

    def check_github_update(self, repo: str, current_ver: str) -> Dict[str, Any]:
        """GitHub Releases API(HTTPS 전용)를 통해 최신 버전을 조회합니다."""
        repo_clean = (repo or "").strip().strip("/")
        if (
            not repo_clean
            or ".." in repo_clean
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_clean)
        ):
            log_security_warning(f"비정상 GitHub 저장소 식별자 차단: repo={repo!r}")
            raise InsecureUrlSecurityError(f"[보안 차단] 유효하지 않은 GitHub 저장소 경로입니다: {repo}")

        api_url = f"https://api.github.com/repos/{repo_clean}/releases/latest"
        validate_https_url(api_url, allow_fragment=False, purpose="GitHub 원격 카탈로그 조회")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Sims4ModAutoUpdater/0.1.6",
            "Accept": "application/vnd.github.v3+json"
        }
        try:
            res = safe_https_get(api_url, headers=headers, timeout=(10, 15))
            if res.status_code == 404:
                return {"error": f"저장소 '{repo_clean}'를 찾을 수 없거나 공식 Release가 등록되어 있지 않습니다 (404 Not Found)."}
            elif res.status_code == 403:
                return {"error": "GitHub API 요청 한도를 초과했습니다 (잠시 후 다시 시도하세요)."}
            res.raise_for_status()
            data = res.json()
        except NetworkSecurityError:
            raise
        except requests.exceptions.RequestException as e:
            return {"error": f"네트워크 통신 오류: {e}"}

        latest_tag = data.get("tag_name", "").lstrip("v")
        assets = data.get("assets", [])

        # 다운로드할 asset (주로 zip 또는 package) — 반드시 HTTPS 다운로드 URL만 허용
        download_url = ""
        asset_name = ""
        for asset in assets:
            name_lower = asset.get("name", "").lower()
            if name_lower.endswith(".zip") or name_lower.endswith(".package") or name_lower.endswith(".ts4script"):
                cand_dl = str(asset.get("browser_download_url") or "").strip()
                if cand_dl:
                    validate_https_url(cand_dl, allow_fragment=False, purpose="GitHub 릴리스 에셋 다운로드 URL")
                    download_url = cand_dl
                    asset_name = asset.get("name")
                    break

        has_update = False
        try:
            has_update = version.parse(latest_tag) > version.parse(current_ver) if current_ver else True
        except Exception:
            has_update = (latest_tag != current_ver)

        return {
            "latest_version": latest_tag,
            "has_update": has_update,
            "download_url": download_url,
            "asset_name": asset_name,
            "release_notes": data.get("body", ""),
        }

    def check_mccc_update(self, current_ver: str, target_name: str = "") -> Dict[str, Any]:
        """Deaderpool 공식 다운로드 페이지(https://deaderpool-mccc.com/downloads.html)에서
        MC Command Center 또는 MC Woohoo(MediaFire 링크) 최신 버전을 조회합니다.
        """
        import re
        from bs4 import BeautifulSoup

        url = "https://deaderpool-mccc.com/downloads.html"
        validate_https_url(url, allow_fragment=False, purpose="MCCC 공식 카탈로그 조회")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Sims4ModAutoUpdater/0.1.6"
        }

        try:
            from src.finder import _cached_safe_https_get
            res = _cached_safe_https_get(url, headers=headers, timeout=(10, 15))
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")
        except NetworkSecurityError:
            raise
        except Exception as e:
            return {"error": f"MCCC 웹사이트 접속 실패: {e}"}

        is_woohoo = "woohoo" in (target_name or "").lower()
        latest_version = ""
        download_url = ""
        asset_name = ""

        if is_woohoo:
            # 1) MC Woohoo 버전 텍스트 및 MC Woohoo MediaFire HTTPS 링크 탐색
            for a in soup.find_all("a", href=True):
                text = a.get_text(" ", strip=True)
                href = a["href"].strip()
                if not latest_version:
                    m_ver = re.search(r"MC\s+Woohoo\s+(\d+\.\d+(?:\.\d+)?)", text, re.IGNORECASE)
                    if m_ver:
                        latest_version = m_ver.group(1)
                if "mediafire.com" in href.lower() and "mcwoohoo" in href.lower():
                    if not is_valid_https_url(href):
                        log_security_warning(f"MCCC 페이지 내 비-HTTPS 다운로드 링크 차단: {href!r}")
                        continue
                    download_url = href
                    m_fn = re.search(r"(MCWoohoo_[^/?#]+\.zip)", href, re.IGNORECASE)
                    if m_fn:
                        asset_name = m_fn.group(1)
                    if not latest_version:
                        m_v_url = re.search(r"(\d+_\d+_\d+)", href)
                        if m_v_url:
                            latest_version = m_v_url.group(1).replace("_", ".")
                    break

            if not asset_name and latest_version:
                asset_name = f"MCWoohoo_ScriptAndPackage_{latest_version.replace('.', '_')}.zip"
        else:
            # 2) MC Command Center 본체 버전 및 MediaFire / Google Drive HTTPS 링크 탐색
            fallback_drive_url = ""
            for a in soup.find_all("a", href=True):
                text = a.get_text(" ", strip=True)
                href = a["href"].strip()
                if not latest_version:
                    match = re.search(r"MC Command Center\s+(\d+\.\d+(?:\.\d+)?)", text, re.IGNORECASE)
                    if match and "legacy" not in text.lower():
                        latest_version = match.group(1)
                        if ("drive.google.com" in href or "mediafire.com" in href) and is_valid_https_url(href):
                            fallback_drive_url = href
                if "mediafire.com" in href.lower() and "mccmdcenter" in href.lower():
                    if not is_valid_https_url(href):
                        log_security_warning(f"MCCC 페이지 내 비-HTTPS 다운로드 링크 차단: {href!r}")
                        continue
                    download_url = href
                    m_fn = re.search(r"(McCmdCenter_[^/?#]+\.zip)", href, re.IGNORECASE)
                    if m_fn:
                        asset_name = m_fn.group(1)
                    break

            if not download_url:
                download_url = fallback_drive_url
            if not asset_name and latest_version:
                asset_name = f"McCmdCenter_AllModules_{latest_version.replace('.', '_')}.zip"

        if not latest_version or not download_url:
            return {"error": "MCCC/MC Woohoo 최신 다운로드 링크를 파싱하지 못했습니다."}

        has_update = False
        try:
            has_update = version.parse(latest_version) > version.parse(current_ver) if current_ver else True
        except Exception:
            has_update = (latest_version != current_ver)

        label_prefix = "MC Woohoo" if is_woohoo else "MCCC"
        return {
            "latest_version": f"제작자 자체 사이트 ({latest_version})",
            "has_update": has_update,
            "status_label": "🚀 최신 버전 배포 중",
            "direct_file_detected": True,
            "requires_browser": False,
            "is_early_access": False,
            "download_url": download_url,
            "page_url": url,
            "asset_name": asset_name,
            "detected_filename": asset_name,
            "verification_note": f"Deaderpool 공식 다운로드 페이지 ({label_prefix} MediaFire) 확인됨",
            "release_notes": f"Deaderpool {label_prefix} {latest_version} Official Release (MediaFire: {asset_name})",
        }

    def check_wickedwhims_update(self, current_ver: str, ww_channel: str = "free") -> Dict[str, Any]:
        """WickedWhims 배포 채널(free: Wicked.cc 자동 업데이트 / paid: Patreon 유료 수동 다운로드)에 따라 업데이트 정보를 조회합니다."""
        from src.finder import inspect_remote_mod_page

        if str(ww_channel or "").strip().lower() == "paid":
            patreon_paid_url = "https://www.patreon.com/wickedwoohoo/posts/wickedwhims-v187-134827399"
            cur_norm = (current_ver or "").strip().lstrip("vV").lower()
            has_update = (cur_norm != "187.18") if cur_norm else True
            return {
                "latest_version": "Patreon (v187.18)",
                "has_update": has_update,
                "status_label": "🔒 선배포 버전 (수동 다운로드)",
                "direct_file_detected": False,
                "requires_browser": True,
                "is_paid": True,
                "is_early_access": True,
                "download_url": patreon_paid_url,
                "page_url": patreon_paid_url,
                "patreon_url": patreon_paid_url,
                "asset_name": "WickedWhims_v187.18.zip",
                "release_notes": "WickedWhims 선배포 버전 (Patreon v187.18 · 수동 다운로드 안내)",
            }

        page_url = "https://wicked.cc/mods/TURBODRIVER/wickedwhims"
        itch_url = "https://turbodriver.itch.io/wickedwhims"

        remote_info = inspect_remote_mod_page(page_url, target_mod_name="WickedWhims")
        if remote_info.get("status") == "free_direct" and remote_info.get("download_url"):
            detected_fn = remote_info.get("file_name") or "WickedWhims.zip"
            ver_raw = str(remote_info.get("version") or "").strip() or "185k"
            ver_norm = ver_raw if ver_raw.lower().startswith("v") else f"v{ver_raw}"
            ver_label = f"Wicked.cc ({ver_norm})"
            cur_norm = (current_ver or "").strip().lstrip("vV").lower()
            rem_cmp = ver_norm.lstrip("vV").lower()
            return {
                "latest_version": ver_label,
                "has_update": (rem_cmp != cur_norm) if cur_norm else True,
                "status_label": "🚀 최신 버전 배포 중",
                "direct_file_detected": True,
                "requires_browser": False,
                "is_paid": False,
                "is_early_access": False,
                "download_url": remote_info["download_url"],
                "itch_url": itch_url,
                "asset_name": detected_fn,
                "detected_filename": detected_fn,
                "page_url": page_url,
                "release_notes": f"모드 파일 자동 감지됨 ({detected_fn})",
            }

        return {
            "latest_version": "Wicked.cc (v185k)",
            "has_update": ((current_ver or "").strip().lstrip("vV").lower() != "185k") if current_ver else True,
            "download_url": page_url,
            "page_url": page_url,
            "itch_url": itch_url,
            "asset_name": "WickedWhims.zip",
            "release_notes": "WickedWhims Official Release (공식 배포처: Wicked.cc)",
            "requires_browser": True,
        }

    def check_barambyul_update(self, current_ver: str, target_name: str = "") -> Dict[str, Any]:
        """바람별 한글화 모드 최신 배포 정보를 실시간 조회합니다.
        - 바람별 공식 한글화 모드(!WAMTIK-V97.9.package / 성씨-이름 !WAMTIK-V97.9-FF.package): 네이버 블로그 배포 포스트에서 직접 자동 다운로드 지원
        - 광역후원자 선배포 버전(!WAMTIK-V98G10.package / !WAMTIK-V98G10-FF.package 등): Patreon/Postype 선배포 채널 수동 다운로드 안내
        """
        import re
        from src.finder import _cached_safe_https_get, check_known_catalog, inspect_remote_mod_page

        patreon_url = "https://www.patreon.com/cw/wwindystarZIMS"
        postype_url = "https://www.postype.com/@wwwindystar"
        naver_url = "https://blog.naver.com/wwwindystar"

        cat_match = check_known_catalog(target_name) if target_name else None
        if cat_match and cat_match.get("creator") == "바람별" and not cat_match.get("is_early_access"):
            direct_post_url = cat_match.get("primary_url", "")
            if direct_post_url and is_valid_https_url(direct_post_url) and (
                direct_post_url.startswith("https://blog.naver.com/wwwindystar/")
                or "/posts/" in direct_post_url.lower()
                or "/post/" in direct_post_url.lower()
            ):
                remote_info = inspect_remote_mod_page(direct_post_url, target_mod_name=target_name)
                if remote_info and remote_info.get("status") == "free_direct" and remote_info.get("download_url"):
                    detected_fn = remote_info.get("file_name") or target_name
                    rem_ver_raw = str(remote_info.get("version") or cat_match.get("version") or "97.9").lstrip("vV")
                    if re.match(r"^20\d{2}\.\d{2}\.\d{2}$", rem_ver_raw):
                        latest_ver_str = rem_ver_raw
                    else:
                        latest_ver_str = f"V{rem_ver_raw}"
                    cur_norm = current_ver.strip().lstrip("vV") if current_ver else ""
                    has_update = (cur_norm.lower() != rem_ver_raw.lower()) if cur_norm else True
                    if "patreon.com" in direct_post_url.lower():
                        plat_label = "Patreon"
                    elif "postype.com" in direct_post_url.lower():
                        plat_label = "Postype"
                    else:
                        plat_label = "네이버 블로그"
                    return {
                        "latest_version": f"{plat_label} ({latest_ver_str})",
                        "has_update": has_update,
                        "status_label": "🚀 최신 버전 배포 중",
                        "direct_file_detected": True,
                        "requires_browser": False,
                        "is_paid": False,
                        "is_early_access": False,
                        "download_url": remote_info["download_url"],
                        "page_url": direct_post_url,
                        "patreon_url": direct_post_url if "patreon.com" in direct_post_url.lower() else patreon_url,
                        "postype_url": direct_post_url if "postype.com" in direct_post_url.lower() else postype_url,
                        "naver_blog_url": direct_post_url if "blog.naver.com" in direct_post_url.lower() else naver_url,
                        "asset_name": detected_fn,
                        "detected_filename": detected_fn,
                        "variant_choices": remote_info.get("variant_choices", []),
                        "requires_option_modal": bool(
                            remote_info.get("requires_option_modal") or cat_match.get("requires_option_modal")
                        ),
                        "option_modal_prompt": cat_match.get("option_modal_prompt") or "",
                        "all_remote_files": remote_info.get("all_files", []),
                        "verification_note": "공식 카탈로그 검증됨 (바람별 공식 한글화 모드)",
                        "release_notes": cat_match.get("release_notes") or f"바람별 공식 한글화 모드 ({detected_fn})",
                    }

        t_low = (target_name or "").lower()
        is_ff = "-ff" in t_low
        ff_suffix = "-FF" if is_ff else ""
        ff_desc = " · 풀네임 성씨-이름(FF) 표시" if is_ff else ""
        lead_prefix = "_" if t_low.startswith("_") else "!"

        # 순한맛(순결버전 V98-alpha / V98P8 등) 후원자 전용 버전
        if (
            (cat_match and "9789832" in str(cat_match.get("candidate_links") or ""))
            or re.search(r"v\d+(?:p\d+|-alpha)", t_low)
        ) and not re.search(r"v\d+r-alpha", t_low):
            latest_version = (cat_match.get("version") if cat_match else "") or "V98-alpha"
            post_link = "https://www.postype.com/@wwwindystar/post/9789832"
            try:
                r = _cached_safe_https_get(postype_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=(8, 10))
                if r.status_code == 200:
                    m = re.search(r"통합한글화모음\s*(V\d+(?:P\d+|-alpha))", r.text, flags=re.IGNORECASE)
                    if m:
                        latest_version = m.group(1)
                    link_m = re.search(r'href="(/@wwwindystar/post/\d+)"[^>]*>[^<]*' + re.escape(latest_version), r.text)
                    if link_m:
                        post_link = f"https://www.postype.com{link_m.group(1)}"
            except NetworkSecurityError:
                raise
            except Exception:
                pass

            has_update = (latest_version.upper() != current_ver.strip().upper()) if current_ver else True
            return {
                "latest_version": latest_version,
                "has_update": has_update,
                "is_paid": True,
                "is_early_access": True,
                "download_url": post_link,
                "page_url": post_link,
                "patreon_url": patreon_url,
                "postype_url": post_link,
                "post_link": post_link,
                "naver_blog_url": naver_url,
                "asset_name": f"{lead_prefix}WAMTIK-{latest_version}{ff_suffix}.package",
                "release_notes": f"바람별 한글화 모드 순한맛(순결버전){ff_desc} (최신 빌드: {latest_version} · 수동 다운로드 안내)",
                "requires_browser": True,
            }

        # 베타버전 빨간맛(V98R-alpha / V98B8 등) 또는 카탈로그에 개별 Patreon 포스트가 지정된 후원자 전용 버전
        if (cat_match and "69805432" in (cat_match.get("primary_url") or "")) or re.search(r"v\d+(?:b\d+|r-alpha)", t_low):
            latest_version = (cat_match.get("version") if cat_match else "") or "V98R-alpha"
            patreon_post_url = (
                cat_match.get("primary_url")
                if (cat_match and "/posts/" in (cat_match.get("primary_url") or "").lower())
                else "https://www.patreon.com/wwindystarZIMS/posts/tonghabhangeulhw-69805432"
            )
            post_link = f"{postype_url}/post/11103833"
            try:
                r = _cached_safe_https_get(postype_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=(8, 10))
                if r.status_code == 200:
                    m = re.search(r"통합한글화모음\s*(V\d+(?:B\d+|R-alpha))", r.text, flags=re.IGNORECASE)
                    if m:
                        latest_version = m.group(1)
                    link_m = re.search(r'href="(/@wwwindystar/post/\d+)"[^>]*>[^<]*' + re.escape(latest_version), r.text)
                    if link_m:
                        post_link = f"https://www.postype.com{link_m.group(1)}"
            except NetworkSecurityError:
                raise
            except Exception:
                pass

            has_update = (latest_version.upper() != current_ver.strip().upper()) if current_ver else True
            return {
                "latest_version": latest_version,
                "has_update": has_update,
                "is_paid": True,
                "is_early_access": True,
                "download_url": patreon_post_url,
                "page_url": patreon_post_url,
                "patreon_url": patreon_post_url,
                "postype_url": postype_url,
                "post_link": post_link,
                "naver_blog_url": naver_url,
                "asset_name": f"{lead_prefix}WAMTIK-{latest_version}{ff_suffix}.package",
                "release_notes": f"베타버전 빨간맛{ff_desc} (최신 빌드: {latest_version} · 수동 다운로드 안내)",
                "requires_browser": True,
            }

        latest_version = "V98G10"
        post_link = f"{postype_url}/post/7214790"

        # 포스타입에서 실시간 최신 광역/선배포 버전 검색
        try:
            r = _cached_safe_https_get(postype_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=(8, 10))
            if r.status_code == 200:
                m = re.search(r"통합한글화모음\s*(V\d+G\d+)", r.text)
                if m:
                    latest_version = m.group(1)
                # 해당 포스트 링크 추출
                link_m = re.search(r'href="(/@wwwindystar/post/\d+)"[^>]*>[^<]*' + re.escape(latest_version), r.text)
                if link_m:
                    post_link = f"https://www.postype.com{link_m.group(1)}"
        except NetworkSecurityError:
            raise
        except Exception:
            pass

        has_update = (latest_version != current_ver)

        return {
            "latest_version": latest_version,
            "has_update": has_update,
            "is_paid": True,
            "is_early_access": True,
            "download_url": patreon_url,
            "patreon_url": patreon_url,
            "postype_url": postype_url,
            "post_link": post_link,
            "naver_blog_url": naver_url,
            "asset_name": f"{lead_prefix}WAMTIK-{latest_version}{ff_suffix}.package",
            "release_notes": f"선배포모드 번역이 추가되는 광역후원자 버전{ff_desc} (최신 빌드: {latest_version} · 수동 다운로드 안내)",
            "requires_browser": True
        }

    @staticmethod
    def infer_mod_config(folder_name: str) -> Dict[str, Any]:
        """폴더 이름을 기반으로 모드의 메타데이터 및 기본 설정을 구성합니다."""
        name_upper = folder_name.upper()

        if "MCCC" in name_upper or "COMMAND CENTER" in name_upper:
            return {
                "name": folder_name,
                "source_type": "mccc",
                "folder_keywords": [folder_name, "MOD MCCC", "MOD MC Command Center"],
                "install_folder": folder_name,
            }
        elif "WICKED" in name_upper or name_upper in ("MOD WW", "WW"):
            return {
                "name": folder_name,
                "source_type": "wickedwhims",
                "folder_keywords": [folder_name, "MOD WickedWhims", "MOD WW"],
                "install_folder": folder_name,
                "homepage": "https://wicked.cc/mods/TURBODRIVER/wickedwhims",
            }
        elif "WAMTIK" in name_upper or "한글" in folder_name or "바람별" in folder_name:
            return {
                "name": folder_name,
                "source_type": "barambyul",
                "folder_keywords": [folder_name, "PRIO", "Overrides"],
                "require_script": False,
                "install_folder": folder_name,
                "homepage": "https://www.patreon.com/cw/wwindystarZIMS",
            }
        else:
            return {
                "name": folder_name,
                "source_type": "generic_web",
                "folder_keywords": [folder_name],
                "install_folder": folder_name,
                "download_url": "",
                "homepage": "",
                "creator": "파일 내부 메타데이터 자동 감지",
            }

    def check_mod_update(self, mod: Dict[str, Any]) -> Dict[str, Any]:
        """개별 모드의 업데이트 여부를 확인합니다."""
        source_type = mod.get("source_type", "github")
        current_ver = mod.get("current_version", "")

        # PRIO / Overrides 폴더 내에 있는 일반 모드 파일([NORTHERN SIBERIA WINDS] 등)이
        # 폴더명 때문에 source_type='barambyul'로 잘못 분류된 경우 자동으로 generic_web으로 전환하고 바람별 홈페이지 URL을 제거
        t_name_low = (mod.get("name") or "").strip().lower()
        is_barambyul_target = any(
            k in t_name_low for k in ("wamtik", "바람별", "_kor_", "(kor)", "automaticpreferences")
        )
        if source_type == "barambyul" and t_name_low and not is_barambyul_target:
            source_type = "generic_web"
        if not is_barambyul_target:
            if "windystar" in str(mod.get("homepage") or "").lower():
                mod["homepage"] = ""
            if "windystar" in str(mod.get("download_url") or "").lower():
                mod["download_url"] = ""

        if source_type == "github":
            repo = mod.get("repo", "")
            if not repo:
                return {"error": "저장소(repo)가 지정되지 않았습니다."}
            try:
                info = self.check_github_update(repo, current_ver)
                if "error" not in info:
                    info["mod_name"] = mod["name"]
                    info["current_version"] = current_ver
                return info
            except Exception as e:
                return {"error": f"업데이트 확인 실패: {e}"}

        elif source_type == "mccc":
            try:
                info = self.check_mccc_update(current_ver, target_name=mod.get("name", ""))
                if "error" not in info:
                    info["mod_name"] = mod["name"]
                    info["current_version"] = current_ver
                    info["matched_creator"] = "Deaderpool"
                    info["finder_diagnostics"] = {"match_stage": "dedicated_scraper (MCCC)", "failure_reason": ""}
                return info
            except Exception as e:
                return {"error": f"MCCC 업데이트 확인 실패: {e}"}

        elif source_type == "wickedwhims":
            try:
                ww_channel = str(mod.get("ww_channel") or "free").strip().lower()
                info = self.check_wickedwhims_update(current_ver, ww_channel=ww_channel)
                if "error" not in info:
                    info["mod_name"] = mod["name"]
                    info["current_version"] = current_ver
                    info["matched_creator"] = "TURBODRIVER"
                    info["finder_diagnostics"] = {"match_stage": "dedicated_scraper (WickedWhims)", "failure_reason": ""}
                return info
            except Exception as e:
                return {"error": f"WickedWhims 업데이트 확인 실패: {e}"}

        elif source_type == "barambyul":
            try:
                info = self.check_barambyul_update(current_ver, target_name=mod.get("name", ""))
                if "error" not in info:
                    info["mod_name"] = mod["name"]
                    info["current_version"] = current_ver
                    info["matched_creator"] = "바람별 (wwindystarZIMS)"
                    info["finder_diagnostics"] = {"match_stage": "dedicated_scraper (바람별 한글화)", "failure_reason": ""}
                return info
            except Exception as e:
                return {"error": f"바람별 한글화 정보 조회 실패: {e}"}

        elif source_type == "generic_web":
            creator = mod.get("creator", "공식 배포처")
            matched_creator = ""
            finder_diagnostics: Dict[str, Any] = {}
            raw_cfg_url = (mod.get("download_url") or mod.get("homepage", "") or "").strip()
            if raw_cfg_url and not is_valid_https_url(raw_cfg_url):
                log_security_warning(f"모드 설정 내 비-HTTPS 배포 URL 차단: {raw_cfg_url!r}")
                url = ""
            else:
                url = raw_cfg_url
            candidate_links = mod.get("candidate_links", [])
            extracted_meta: Dict[str, Any] = {}
            latest_ver_label = "공식 배포처 최신본"

            # 파일 경로(file_path)가 있거나 URL이 지정되어 있지 않은 경우 파일 내부 메타데이터 추출 및 검색 수행
            file_path = mod.get("file_path") or (
                mod["selected_file"].get("full_path") if isinstance(mod.get("selected_file"), dict) else None
            )
            folder_name = mod.get("folder_name") or mod.get("install_folder") or ""
            target_name = mod.get("name") or folder_name

            custom_release_notes = ""
            is_paid_catalog = False
            is_early_access_catalog = False
            requires_option_modal = False
            option_modal_mode = ""
            option_modal_prompt = ""
            catalog_option_presets: List[Dict[str, Any]] = []
            catalog_optional_addons: List[Dict[str, Any]] = []
            rpo_channel = str(mod.get("rpo_channel") or "").strip().lower()
            ww_channel = str(mod.get("ww_channel") or "").strip().lower()
            is_unreleased_catalog = bool(
                re.search(r"sulsul[\s_-]*ai", f"{target_name} {folder_name}", flags=re.IGNORECASE)
            )
            is_verified_source = bool(
                self.get_pinned_url(target_name, folder_name)
                or (url and "google.com" not in url)
            )
            if file_path or not url or "google.com" in url or not candidate_links:
                try:
                    from src.finder import find_direct_mod_page
                    finder_res = find_direct_mod_page(
                        target_name,
                        file_path=file_path,
                        folder_name=folder_name,
                        rpo_channel=rpo_channel or None,
                        ww_channel=ww_channel or None,
                    )
                    cand_primary = (finder_res.get("primary_url") or "").strip()
                    if cand_primary and not is_valid_https_url(cand_primary):
                        log_security_warning(f"탐색된 비-HTTPS 배포 URL 차단: {cand_primary!r}")
                        url = ""
                    else:
                        url = cand_primary
                    creator = finder_res["source_name"]
                    candidate_links = finder_res.get("candidate_links", [])
                    extracted_meta = finder_res.get("extracted_meta", {})
                    custom_release_notes = finder_res.get("release_notes", "")
                    is_paid_catalog = bool(finder_res.get("is_paid"))
                    is_early_access_catalog = bool(finder_res.get("is_early_access"))
                    requires_option_modal = bool(finder_res.get("requires_option_modal"))
                    option_modal_mode = str(finder_res.get("option_modal_mode") or "")
                    option_modal_prompt = str(finder_res.get("option_modal_prompt") or "")
                    catalog_option_presets = list(finder_res.get("option_presets") or [])
                    catalog_optional_addons = list(finder_res.get("optional_addons") or [])
                    if finder_res.get("is_unreleased"):
                        is_unreleased_catalog = True
                    finder_diagnostics = dict(finder_res.get("diagnostics") or {})
                    matched_creator = (
                        finder_res.get("creator")
                        or extracted_meta.get("inferred_creator")
                        or (extracted_meta.get("creators")[0] if extracted_meta.get("creators") else "")
                        or finder_diagnostics.get("tokenized_creator")
                        or ""
                    )
                    if finder_res.get("is_verified_source"):
                        is_verified_source = True
                    if extracted_meta.get("binary_version"):
                        current_ver = current_ver or extracted_meta["binary_version"]
                    if extracted_meta.get("version"):
                        ver_val = str(extracted_meta["version"]).strip()
                        if re.match(r"^(?:20\d{2}\.\d{2}\.\d{2}|[ab]\d+\.\d+(?:\.\d+)*)$", ver_val, flags=re.IGNORECASE):
                            latest_ver_label = ver_val
                        else:
                            latest_ver_label = ver_val if ver_val.lower().startswith("v") else f"v{ver_val}"
                    elif "patreon.com" in (url or "").lower():
                        latest_ver_label = "Patreon 최신본"
                except Exception:
                    pass

            # 파일명에 버전이 적혀 있는지 판별하여 웹 최신 버전 표시 문자열 결정
            # (파일명에 버전이 있으면 'Patreon (버전)', 파일명에 버전이 없으면 '수동 확인 필요')
            from src.finder import extract_version_from_filename

            local_fn_ver = extract_version_from_filename(target_name) or extract_version_from_filename(folder_name)

            def _is_remote_newer_or_equal(loc_v: str, rem_v: str) -> bool:
                try:
                    l_s = re.sub(
                        r"\s*\(핫픽스(?:\s*(\d+))?\)",
                        lambda m: f".post{m.group(1) or '1'}",
                        loc_v.lstrip("vV").strip(),
                    )
                    r_s = re.sub(
                        r"\s*\(핫픽스(?:\s*(\d+))?\)",
                        lambda m: f".post{m.group(1) or '1'}",
                        rem_v.lstrip("vV").strip(),
                    )
                    m_l_ab = re.match(r"^([abAB])(\d+(?:\.\d+)*)(.*)$", l_s)
                    if m_l_ab:
                        l_s = f"{m_l_ab.group(2)}{m_l_ab.group(1).lower()}0{m_l_ab.group(3)}"
                    m_r_ab = re.match(r"^([abAB])(\d+(?:\.\d+)*)(.*)$", r_s)
                    if m_r_ab:
                        r_s = f"{m_r_ab.group(2)}{m_r_ab.group(1).lower()}0{m_r_ab.group(3)}"
                    if re.match(r"^\d+\.\d{2,3}$", l_s) and re.match(r"^\d+\.\d{2,3}$", r_s):
                        l_maj, l_min = l_s.split(".")
                        r_maj, r_min = r_s.split(".")
                        return (int(r_maj), int(r_min.ljust(3, "0"))) >= (int(l_maj), int(l_min.ljust(3, "0")))
                    lv = version.parse(l_s)
                    rv = version.parse(r_s)
                    return rv >= lv
                except Exception:
                    return True

            # 미출시 상태 모드는 원격 조회 및 업데이트 대상에서 즉시 제외
            if is_unreleased_catalog:
                return {
                    "latest_version": "미출시",
                    "has_update": False,
                    "status_label": "⏳ 미출시 (업데이트 제외)",
                    "direct_file_detected": False,
                    "is_paid": False,
                    "is_early_access": False,
                    "is_unreleased": True,
                    "requires_browser": False,
                    "download_url": "",
                    "page_url": "",
                    "candidate_links": [],
                    "extracted_meta": extracted_meta,
                    "matched_creator": matched_creator or creator,
                    "finder_diagnostics": finder_diagnostics,
                    "verification_note": "미출시 모드 제외",
                    "release_notes": custom_release_notes or "미출시 상태 모드로 업데이트 대상에서 제외됩니다.",
                    "mod_name": mod["name"],
                    "current_version": current_ver,
                }

            # 프로그램이 자체적으로 배포 페이지(Patreon 등)를 열어 직접 다운로드 가능 여부 / 얼리 액세스 여부 판별
            remote_info: Dict[str, Any] = {"status": "browser_required"}
            verification_note = ""
            try:
                from src.finder import inspect_remote_mod_page, is_safe_remote_file_match
                search_mod_label = target_name or extracted_meta.get("manifest_name") or ""
                # 0순위: mods_manifest.json에 이미 검증·고정(Pinning)되어 있는 공식 HTTPS URL 우선 확인
                pinned_url = self.get_pinned_url(target_name, folder_name)
                # 1순위 URL 및 후보 링크 중 HTTPS 전용 배포 페이지만 선별 검사
                urls_to_check: List[str] = []
                if pinned_url and is_valid_https_url(pinned_url) and rpo_channel not in ("early_access", "free"):
                    urls_to_check.append(pinned_url)
                if url and is_valid_https_url(url) and url not in urls_to_check:
                    urls_to_check.append(url)
                for item in candidate_links[:3]:
                    c_url = (item[2] if len(item) == 3 else item[1]).strip()
                    if not c_url:
                        continue
                    if not is_valid_https_url(c_url):
                        log_security_warning(f"후보 링크 내 비-HTTPS URL 제외: {c_url!r}")
                        continue
                    if c_url not in urls_to_check:
                        urls_to_check.append(c_url)

                for check_u in urls_to_check:
                    try:
                        info_res = inspect_remote_mod_page(check_u, target_mod_name=search_mod_label)
                    except NetworkSecurityError as net_sec_err:
                        verification_note = f"보안 차단 ({net_sec_err})"
                        continue
                    if info_res.get("status") == "free_direct":
                        # 원격 파일명·포스트가 로컬 모드와 실제로 일치하는지 유사도/메타데이터 검증 게이트 통과 확인
                        is_safe, _, match_reason = is_safe_remote_file_match(
                            target_name=target_name,
                            folder_name=folder_name,
                            extracted_meta=extracted_meta,
                            remote_info=info_res,
                            checked_url=check_u,
                        )
                        if not is_safe:
                            # 유사도가 낮아 다른 모드일 리스크가 있으면 자동 다운로드를 차단하고 다음 후보를 확인하거나 브라우저 확인으로 전환
                            verification_note = f"자동 다운로드 보류 ({match_reason} - 브라우저 직접 확인 권장)"
                            continue

                        verification_note = match_reason
                        cand_fn = info_res.get("file_name") or ""
                        cand_ver = extract_version_from_filename(cand_fn)
                        # 원격 미러(예: CurseForge 구버전 v3)가 로컬 파일 버전(예: v4)보다 낮은 경우 다음 후보(Patreon 등) 계속 탐색
                        if rpo_channel != "free" and local_fn_ver and cand_ver and not _is_remote_newer_or_equal(local_fn_ver, cand_ver):
                            if remote_info.get("status") != "free_direct":
                                remote_info = info_res
                            continue
                        remote_info = info_res
                        break
                    elif info_res.get("status") == "early_access":
                        remote_info = info_res
                        if "/posts/" in check_u.lower():
                            break
                    elif info_res.get("version") and not remote_info.get("version"):
                        remote_info = info_res
            except Exception:
                pass

            def _platform_short_label(page_u: str) -> str:
                u_low = (page_u or "").lower()
                if "modthesims.info" in u_low:
                    return "MTS"
                if "patreon.com" in u_low:
                    return "Patreon"
                if "curseforge.com" in u_low:
                    return "CurseForge"
                if "itch.io" in u_low:
                    return "Itch.io"
                if "tumblr.com" in u_low:
                    return "Tumblr"
                if "postype.com" in u_low:
                    return "Postype"
                if "blog.naver.com" in u_low:
                    return "네이버 블로그"
                if "dcinside.com" in u_low:
                    return "디시인사이드"
                if "drive.google.com" in u_low:
                    return "Google Drive"
                if "github.com" in u_low:
                    return "GitHub"
                if "simfileshare.net" in u_low:
                    return "SimFileShare"
                if "loverslab.com" in u_low:
                    return "LoversLab"
                if "wicked.cc" in u_low:
                    return "Wicked.cc"
                if "deaderpool-mccc.com" in u_low:
                    return "제작자 자체 사이트"
                if "mediafire.com" in u_low:
                    return "MediaFire"
                if "scumbumbomods.com" in u_low:
                    return "Scumbumbo"
                if "seebee.de" in u_low:
                    return "sims4me"
                if "kemzimamods.com" in u_low:
                    return "KemZima"
                if "pandasama.com" in u_low:
                    return "Pandasama"
                if "lot51.cc" in u_low or "lot51_core" in (target_name or "").lower():
                    return "제작자 공식 사이트"
                if "sims4ai.virtualconscious.com" in u_low or "s4m-byok.prmptplus.chatgpt.site" in u_low:
                    return "제작자 공식 사이트"
                if "twistedmexi.com" in u_low:
                    return "TwistedMexi"
                return "Patreon"

            def _resolve_web_first_version(rem_info: Dict[str, Any], loc_ver: str) -> str:
                raw_rem_v = str(rem_info.get("version") or "").strip()
                m_hf_rem = re.match(
                    r"^([ab])?v?([0-9]+(?:\.[0-9]+)*[a-z]?)\s*\(핫픽스(?:\s*\d+)?\)$",
                    raw_rem_v,
                    flags=re.IGNORECASE,
                )
                rem_ver = (
                    f"{(m_hf_rem.group(1) or 'v').lower()}{m_hf_rem.group(2)} (핫픽스)"
                    if m_hf_rem
                    else (
                        (raw_rem_v[0].lower() + raw_rem_v[1:])
                        if re.match(r"^[ab][0-9]+(?:\.[0-9]+)*[a-z]?$", raw_rem_v, flags=re.IGNORECASE)
                        else (
                            extract_version_from_filename(raw_rem_v)
                            or (f"v{raw_rem_v}" if re.match(r"^[0-9]+(?:\.[0-9]+)*[a-z]?$", raw_rem_v, flags=re.IGNORECASE) else "")
                            or extract_version_from_filename(str(rem_info.get("file_name") or ""))
                            or extract_version_from_filename(str(rem_info.get("title") or ""))
                        )
                    )
                )
                meta_ver_raw = str(extracted_meta.get("version") or "").strip()
                if re.match(r"^(?:20\d{2}\.\d{1,2}\.\d{1,2}|[ab]\d+\.\d+(?:\.\d+)*)$", meta_ver_raw, flags=re.IGNORECASE):
                    meta_ver = (
                        meta_ver_raw[0].lower() + meta_ver_raw[1:]
                        if re.match(r"^[ab]", meta_ver_raw, flags=re.IGNORECASE)
                        else meta_ver_raw
                    )
                else:
                    meta_ver = (f"v{meta_ver_raw.lstrip('vV')}" if meta_ver_raw else "")
                folder_low = (folder_name or "").strip().lower()
                t_name_low = (target_name or "").strip().lower()
                if "byok" in t_name_low:
                    return rem_ver or "v2.6.1 (핫픽스)"
                if ("ai chat" in folder_low or "aichat" in folder_low or "sims4_ai_chat" in t_name_low or "sims 4 ai chat" in t_name_low) and "byok" not in t_name_low:
                    return rem_ver or "v2.6.1"
                if "volleyball" in folder_low or "volleyball" in (target_name or "").lower():
                    return "v0.2.4"
                if "twister" in folder_low or "twister" in (target_name or "").lower():
                    return "v0.2.3"
                if "ride together" in folder_low or "ride_together" in folder_low or "ride together" in (target_name or "").lower():
                    return "a0.5"
                if "wave-n-grind" in t_name_low or "wave and grind" in t_name_low or "wave_and_grind" in t_name_low or "wave-n-grind" in folder_low or "wave and grind" in folder_low:
                    return "a0.5"
                if "0nizu" in t_name_low or "0nizu" in folder_low:
                    return rem_ver or "2026.11.27"
                if "0zzzy" in t_name_low or "0zzzy" in folder_low:
                    return rem_ver or "v1.0.6"
                if "adakasay" in t_name_low or "adakasay" in folder_low:
                    return rem_ver or "2026.11.04"
                if "aftermathdna" in t_name_low or "aftermathdna" in folder_low:
                    return rem_ver or "v1.0.13"
                if "alchemistanimations" in t_name_low or "ww_alchemist" in t_name_low or ("alchemist" in folder_low and "ww" in folder_low) or "ww animation - alchemist" in t_name_low:
                    return rem_ver or "2026.11.25"
                if "amateurhour47" in t_name_low or "amateurhour47" in folder_low:
                    return rem_ver or "2024.04.20"
                if "amorzinho" in t_name_low or "amorzinho" in folder_low:
                    return rem_ver or "v1.0.0"
                if "amra72" in t_name_low or "amra72" in folder_low:
                    return rem_ver or "2023.04.12"
                if "anarcis" in t_name_low or "anarcis" in folder_low:
                    return rem_ver or "2026.11.27"
                if "anonny" in t_name_low or "anonny" in folder_low:
                    return rem_ver or "v1.7"
                if "artistadebastardo" in t_name_low or "artistadebastardo" in folder_low:
                    return rem_ver or "v1.2.0"
                if "artmiel" in t_name_low or "artmiel" in folder_low:
                    return rem_ver or "v5.5"
                if "asketo" in t_name_low or "asketo" in folder_low:
                    return rem_ver or "2020.09.18"
                if (
                    "ww_aske" in t_name_low
                    or "aske_ww" in t_name_low
                    or "aske_anim" in t_name_low
                    or "ww animation - aske" in t_name_low
                    or re.search(r"(?:^|[^a-z0-9])aske(?:$|[^a-z0-9])", t_name_low)
                ):
                    return rem_ver or "v1.4"
                if "atrois" in t_name_low or "atrois" in folder_low or "a-trois" in t_name_low or "a-trois" in folder_low:
                    return rem_ver or "2026.08.06"
                if "awsome" in t_name_low or "awsome" in folder_low:
                    return rem_ver or "2026.11.22"
                if "ayone" in t_name_low or "ayone" in folder_low:
                    return rem_ver or "2025.01.11"
                if "azmodan22" in t_name_low or "azmodan22" in folder_low:
                    return "2025.02.05"
                if "404dyma" in t_name_low or "404dyma" in folder_low:
                    return rem_ver or "v1.0.0"
                if rpo_channel == "free" and rem_ver:
                    return rem_ver
                ref_loc_ver = loc_ver or meta_ver
                if rem_ver and ref_loc_ver:
                    # 예: XmlInjector_Script_v42.zip(v42) vs XmlInjector_Script_v4.2.ts4script(v4.2)처럼 점(.)만 생략된 동일 버전이거나 v2 vs V2.0처럼 의미상 동일 버전인 경우 로컬/메타 표기 보존
                    if rem_ver.lstrip("vV").replace(".", "") == ref_loc_ver.lstrip("vV").replace(".", "") and "." in ref_loc_ver and "." not in rem_ver:
                        return ref_loc_ver
                    try:
                        def _pep440_ver(v_str: str) -> str:
                            s_v = v_str.lstrip("vV").strip()
                            m_v_ab = re.match(r"^([abAB])(\d+(?:\.\d+)*)(.*)$", s_v)
                            if m_v_ab:
                                return f"{m_v_ab.group(2)}{m_v_ab.group(1).lower()}0{m_v_ab.group(3)}"
                            return s_v

                        if version.parse(_pep440_ver(rem_ver)) == version.parse(_pep440_ver(ref_loc_ver)):
                            return ref_loc_ver
                    except Exception:
                        pass
                    if loc_ver:
                        return rem_ver if _is_remote_newer_or_equal(loc_ver, rem_ver) else loc_ver
                return rem_ver or loc_ver or meta_ver

            def _format_latest_version_label(ver_candidate: str, page_u: str, is_direct: bool = False) -> str:
                plat = _platform_short_label(page_u)
                if ver_candidate:
                    v_clean_date = ver_candidate.lstrip("vV")
                    if re.match(r"^20\d{2}\.\d{1,2}\.\d{1,2}$", v_clean_date):
                        v_norm = v_clean_date
                    elif re.match(r"^V\d+(?:\.\d+)?[GBPR]\d*$", ver_candidate, flags=re.IGNORECASE):
                        v_norm = ver_candidate.upper()
                    elif re.match(r"^[ab]\d+(?:\.\d+)*[a-z]?$", ver_candidate, flags=re.IGNORECASE):
                        v_norm = ver_candidate[0].lower() + ver_candidate[1:]
                    else:
                        v_norm = ver_candidate if ver_candidate.lower().startswith("v") else f"v{ver_candidate}"
                    return f"{plat} ({v_norm})"
                if is_direct:
                    return f"{plat} (최신 배포본)"
                return "수동 확인 필요"

            chosen_ver = _resolve_web_first_version(remote_info, local_fn_ver)
            is_free_direct = bool(remote_info.get("status") == "free_direct" and remote_info.get("download_url"))
            has_ver_found = bool(chosen_ver) or is_free_direct
            status_label = "🚀 최신 버전 배포 중" if has_ver_found else "수동 등록 필요"

            # 0) 카탈로그에 명시적으로 등록된 유료 상품 모드인 경우 (자동 다운로드 불가 안내 및 공식 링크 제공)
            if is_paid_catalog and url:
                paid_ver_label = (
                    _format_latest_version_label(chosen_ver, url)
                    if chosen_ver
                    else f"{_platform_short_label(url)} (유료 상품)"
                )
                return {
                    "latest_version": paid_ver_label,
                    "has_update": False,
                    "status_label": "🔒 유료 상품 (자동 다운로드 불가)",
                    "direct_file_detected": False,
                    "is_paid": True,
                    "is_early_access": False,
                    "requires_browser": True,
                    "download_url": url,
                    "page_url": url,
                    "patreon_url": url if "patreon.com" in url.lower() else "",
                    "candidate_links": candidate_links,
                    "extracted_meta": extracted_meta,
                    "matched_creator": matched_creator or creator,
                    "finder_diagnostics": finder_diagnostics,
                    "verification_note": verification_note,
                    "release_notes": custom_release_notes or "유료 상품이어서 자동 다운로드가 불가능합니다.",
                    "mod_name": mod["name"],
                    "current_version": current_ver,
                }

            # 1) 무료 공개 모드 파일이 페이지에서 직접 감지된 경우 -> 링크 없이 바로 다운로드 지원
            if is_free_direct:
                detected_fn = remote_info.get("file_name") or f"{target_name}.zip"
                final_page_u = remote_info.get("page_url") or url
                label_page_u = (
                    url
                    if (finder_diagnostics.get("match_stage") == "known_catalog" and "tumblr.com" in (url or "").lower())
                    else final_page_u
                )
                all_rem_files = remote_info.get("all_files") or []
                raw_pkg_files = [
                    (fn, dl)
                    for fn, dl in all_rem_files
                    if str(fn).lower().endswith((".package", ".ts4script")) and dl
                ]
                is_multi_pkg_bundle = (
                    len(raw_pkg_files) > 1
                    and str(detected_fn).lower().endswith((".package", ".ts4script"))
                )
                remote_file_size = int(remote_info.get("remote_file_size") or 0)
                if (
                    remote_file_size > 0
                    and str(detected_fn).lower().endswith((".ts4script", ".package"))
                    and not is_multi_pkg_bundle
                    and file_path
                ):
                    try:
                        loc_p = Path(str(file_path))
                        if loc_p.exists() and loc_p.is_file() and loc_p.name.lower() == str(detected_fn).lower():
                            local_fsize = loc_p.stat().st_size
                            bin_norm = str(extracted_meta.get("binary_version") or "").strip().lstrip("vV").lower()
                            eff_cur_norm = bin_norm or str(current_ver or "").strip().lstrip("vV").lower()
                            ch_norm = str(chosen_ver or "").strip().lstrip("vV").lower()
                            if local_fsize != remote_file_size and ch_norm and eff_cur_norm and ch_norm == eff_cur_norm:
                                m_hf_cur = re.match(r"^(.+?)\s*\(핫픽스(?:\s*\d+)?\)$", ch_norm)
                                base_ch = m_hf_cur.group(1).strip() if m_hf_cur else ch_norm
                                chosen_ver = f"v{base_ch} (핫픽스)"
                    except OSError:
                        pass
                detected_ver_label = _format_latest_version_label(chosen_ver, label_page_u, is_direct=True)
                v_badge = f" | 검증: {verification_note}" if verification_note else ""
                bundle_filenames = [fn for fn, _ in raw_pkg_files] if is_multi_pkg_bundle else []
                display_detected_fn = (
                    f"{detected_fn} 외 {len(bundle_filenames) - 1}개 (총 {len(bundle_filenames)}개 파일)"
                    if is_multi_pkg_bundle
                    else detected_fn
                )
                return {
                    "latest_version": detected_ver_label,
                    "has_update": has_ver_found,
                    "status_label": status_label,
                    "direct_file_detected": True,
                    "requires_browser": False,
                    "is_early_access": False,
                    "download_url": remote_info["download_url"],
                    "asset_name": detected_fn,
                    "detected_filename": display_detected_fn,
                    "is_multi_file_bundle": is_multi_pkg_bundle,
                    "bundle_filenames": bundle_filenames,
                    "variant_choices": remote_info.get("variant_choices", []),
                    "requires_option_modal": bool(remote_info.get("requires_option_modal") or requires_option_modal),
                    "option_modal_mode": str(remote_info.get("option_modal_mode") or option_modal_mode),
                    "option_modal_prompt": str(remote_info.get("option_modal_prompt") or option_modal_prompt),
                    "catalog_option_presets": catalog_option_presets,
                    "optional_addons": remote_info.get("optional_addons") or catalog_optional_addons,
                    "all_remote_files": all_rem_files,
                    "remote_file_size": remote_file_size,
                    "page_url": final_page_u,
                    "candidate_links": candidate_links,
                    "extracted_meta": extracted_meta,
                    "matched_creator": matched_creator or creator,
                    "finder_diagnostics": finder_diagnostics,
                    "verification_note": verification_note or "정상 확인됨",
                    "release_notes": f"모드 파일 자동 감지됨 ({display_detected_fn}){v_badge}",
                    "mod_name": mod["name"],
                    "current_version": current_ver,
                }

            # 2) 얼리 액세스(선배포) / 멤버십 제한으로 프로그램이 파일에 직접 접근할 수 없는 경우
            if remote_info.get("status") == "early_access" or is_early_access_catalog:
                ea_page = remote_info.get("page_url") or url
                ea_title = remote_info.get("title") or target_name
                ea_ver_label = _format_latest_version_label(chosen_ver, ea_page)
                return {
                    "latest_version": ea_ver_label,
                    "has_update": has_ver_found,
                    "status_label": status_label,
                    "direct_file_detected": False,
                    "is_early_access": True,
                    "requires_browser": True,
                    "download_url": ea_page,
                    "page_url": ea_page,
                    "variant_choices": remote_info.get("variant_choices", []),
                    "requires_option_modal": bool(remote_info.get("requires_option_modal") or requires_option_modal),
                    "option_modal_mode": str(remote_info.get("option_modal_mode") or option_modal_mode),
                    "option_modal_prompt": str(remote_info.get("option_modal_prompt") or option_modal_prompt),
                    "catalog_option_presets": catalog_option_presets,
                    "optional_addons": remote_info.get("optional_addons") or catalog_optional_addons,
                    "candidate_links": candidate_links,
                    "extracted_meta": extracted_meta,
                    "matched_creator": matched_creator or creator,
                    "finder_diagnostics": finder_diagnostics,
                    "verification_note": verification_note,
                    "release_notes": custom_release_notes or f"얼리 액세스(선배포) 제한 포스트 ({ea_title})",
                    "mod_name": mod["name"],
                    "current_version": current_ver,
                }

            # 웹 검색으로 찾은 비검증 링크가 실제 점검 결과 다른 모드 파일(자동 다운로드 보류)로 판명되었거나, 링크 자체를 찾지 못한 경우
            if not is_verified_source and remote_info.get("status") != "free_direct":
                if verification_note.startswith("자동 다운로드 보류"):
                    finder_diagnostics["failure_reason"] = (
                        f"웹 검색으로 후보 링크({url})를 찾았으나 원격 파일 유사도 안전 검증에서 기각됨 ({verification_note})"
                    )
                    url = ""
                    candidate_links = []

            if not url:
                return {
                    "latest_version": "링크를 찾을 수 없습니다.",
                    "has_update": False,
                    "status_label": "링크를 찾을 수 없습니다.",
                    "link_not_found": True,
                    "direct_file_detected": False,
                    "requires_browser": False,
                    "is_early_access": False,
                    "download_url": "",
                    "page_url": "",
                    "candidate_links": [],
                    "extracted_meta": extracted_meta,
                    "matched_creator": matched_creator,
                    "finder_diagnostics": finder_diagnostics,
                    "verification_note": verification_note,
                    "release_notes": "링크를 찾을 수 없습니다.",
                    "mod_name": mod["name"],
                    "current_version": current_ver,
                }

            # 3) 일반 외부 배포 페이지 안내 (네이버 블로그, 디시인사이드, CurseForge 등 브라우저 접속 필요)
            if custom_release_notes:
                final_release_notes = custom_release_notes
            elif "blog.naver.com" in (url or "").lower():
                final_release_notes = "네이버 블로그 참고 (무료)"
            elif "dcinside.com" in (url or "").lower():
                final_release_notes = "디시인사이드 심즈 갤러리 참고 (무료)"
            else:
                notes_parts = [f"{creator} 확인"]
                if extracted_meta.get("inferred_creator"):
                    notes_parts.append(f"제작자: {extracted_meta['inferred_creator']}")
                if extracted_meta.get("manifest_name"):
                    notes_parts.append(f"모드명: {extracted_meta['manifest_name']}")
                final_release_notes = " | ".join(notes_parts)

            return {
                "latest_version": _format_latest_version_label(chosen_ver, url),
                "has_update": has_ver_found,
                "status_label": status_label,
                "direct_file_detected": False,
                "download_url": url,
                "page_url": url,
                "candidate_links": candidate_links,
                "extracted_meta": extracted_meta,
                "matched_creator": matched_creator or creator,
                "finder_diagnostics": finder_diagnostics,
                "verification_note": verification_note,
                "release_notes": final_release_notes,
                "requires_browser": True,
                "mod_name": mod["name"],
                "current_version": current_ver
            }

        return {"error": f"지원되지 않는 소스 타입: {source_type}"}

    def update_mod(
        self,
        mod: Dict[str, Any],
        update_info: Dict[str, Any],
        overwrite_mode: str = "all",
        skip_backup: bool = False,
        progress_callback: Optional[ Any ] = None,
    ) -> List[str]:
        """모드를 다운로드하고 설치합니다.
        - overwrite_mode == 'single': 사용자가 지정한 단일 파일(selected_file_path)만 덮어씁니다.
        - overwrite_mode == 'all': 압축파일 내 관련 모드 파일 전체 및 동일 배포 페이지의 설치된 관련 파일들을 다 같이 덮어씁니다.
        - skip_backup == True: 이미 사전 일괄 백업을 마친 경우 개별 중복 백업을 생략합니다.
        반환값: 덮어쓰기 완료된 파일명 리스트
        """
        import shutil

        def _notify(stage: str, msg: str) -> None:
            if callable(progress_callback):
                try:
                    progress_callback(stage, msg)
                except Exception:
                    pass

        variant_choices = update_info.get("variant_choices") or []
        selected_variant = str(update_info.get("selected_variant") or "").strip()
        is_multi_file_select_mode = bool(
            str(update_info.get("option_modal_mode") or "").strip().lower() == "multi_file_select"
            or selected_variant.lower() in ("download_mode:all", "download_mode:select")
        )
        archive_only_include_names: Optional[set[str]] = None
        if is_multi_file_select_mode:
            orig_all_pairs = [
                (str(fn), str(dl))
                for fn, dl in (update_info.get("all_remote_files") or [])
                if fn and dl
            ]
            if not orig_all_pairs and update_info.get("download_url"):
                orig_all_pairs = [(
                    str(update_info.get("asset_name") or mod.get("name") or "animation.package"),
                    str(update_info.get("download_url")),
                )]
            pref_arch_upd = str(update_info.get("preferred_archive_name") or "").strip()
            if not pref_arch_upd:
                try:
                    from src.finder import check_known_catalog
                    _cat_arch = check_known_catalog(mod.get("name") or "", is_ww_animation_hint=True)
                    if isinstance(_cat_arch, dict):
                        pref_arch_upd = str(_cat_arch.get("preferred_archive_name") or "").strip()
                except Exception:
                    pass
            if pref_arch_upd and orig_all_pairs:
                pref_u_low = pref_arch_upd.lower()
                pref_u_clean = re.sub(r"[^a-z0-9]", "", pref_u_low)
                matched_arch_pairs = [
                    pair for pair in orig_all_pairs
                    if pair[0].strip().lower() == pref_u_low
                    or (pref_u_clean and re.sub(r"[^a-z0-9]", "", pair[0].lower()) == pref_u_clean)
                ]
                if matched_arch_pairs:
                    orig_all_pairs = matched_arch_pairs

            if selected_variant.lower() == "download_mode:select":
                chosen_addons_raw = [
                    str(x).strip().lower()
                    for x in (update_info.get("selected_addons") or [])
                    if str(x).strip()
                ]
                chosen_stems = {Path(x).stem.lower() for x in chosen_addons_raw}
                if not chosen_addons_raw:
                    raise ValueError("선택 다운로드할 파일이 선택되지 않았습니다. 최소 1개 이상의 파일을 선택해 주세요.")
                selected_pairs = [
                    (fn, dl)
                    for fn, dl in orig_all_pairs
                    if fn.lower() in chosen_addons_raw or Path(fn).stem.lower() in chosen_stems
                ]
                archive_pairs = [
                    (fn, dl)
                    for fn, dl in orig_all_pairs
                    if Path(fn).suffix.lower() in (".zip", ".rar", ".7z")
                ]
                if not selected_pairs and archive_pairs:
                    selected_pairs = archive_pairs
                    archive_only_include_names = set(chosen_addons_raw) | chosen_stems
                if not selected_pairs:
                    raise ValueError("선택 다운로드할 파일이 선택되지 않았습니다. 최소 1개 이상의 파일을 선택해 주세요.")
            else:
                selected_pairs = orig_all_pairs

            if selected_pairs:
                update_info = dict(update_info)
                update_info["download_url"] = selected_pairs[0][1]
                update_info["asset_name"] = selected_pairs[0][0]
                update_info["detected_filename"] = (
                    f"{selected_pairs[0][0]} 외 {len(selected_pairs) - 1}개 (총 {len(selected_pairs)}개 파일)"
                    if len(selected_pairs) > 1
                    else selected_pairs[0][0]
                )
                update_info["all_remote_files"] = selected_pairs
                update_info["is_multi_file_bundle"] = len(selected_pairs) > 1
        elif variant_choices and selected_variant:
            sel_choice = next(
                (vc for vc in variant_choices if str(vc.get("file_name") or "").lower() == selected_variant.lower()),
                None,
            )
            if sel_choice and sel_choice.get("download_url"):
                variant_names_low = {
                    str(vc.get("file_name") or "").lower()
                    for vc in variant_choices
                    if vc.get("file_name")
                }
                variant_dls_low = {
                    str(vc.get("download_url") or "").lower()
                    for vc in variant_choices
                    if vc.get("download_url")
                }
                sel_dl_low = str(sel_choice["download_url"]).lower()
                orig_all = list(update_info.get("all_remote_files") or [])
                filtered_all = [
                    (fn, dl)
                    for fn, dl in orig_all
                    if (
                        str(fn).lower() not in variant_names_low
                        and str(dl or "").lower() not in variant_dls_low
                    )
                    or str(fn).lower() == selected_variant.lower()
                    or str(dl or "").lower() == sel_dl_low
                ]
                if not any(
                    str(fn).lower() == selected_variant.lower()
                    or str(dl or "").lower() == sel_dl_low
                    for fn, dl in filtered_all
                ):
                    filtered_all.append((sel_choice["file_name"], sel_choice["download_url"]))
                update_info = dict(update_info)
                update_info["all_remote_files"] = filtered_all
                cur_asset_low = str(update_info.get("asset_name") or "").lower()
                cur_dl_low = str(update_info.get("download_url") or "").lower()
                if cur_asset_low in variant_names_low or cur_dl_low in variant_dls_low:
                    update_info["download_url"] = sel_choice["download_url"]
                    update_info["asset_name"] = sel_choice["file_name"]
                    update_info["detected_filename"] = sel_choice["file_name"]

        download_url = update_info.get("download_url")
        if not download_url:
            raise ValueError("다운로드 URL이 유효하지 않습니다.")
        validate_https_url(download_url, allow_fragment=True, purpose="모드 파일 다운로드")

        file_path_str = mod.get("file_path") or (
            mod["selected_file"].get("full_path") if isinstance(mod.get("selected_file"), dict) else None
        )
        selected_file_path = Path(file_path_str) if file_path_str else None

        if selected_file_path and selected_file_path.exists():
            target_dir = selected_file_path.parent
        else:
            target_subfolder = mod.get("install_folder") or mod.get("folder_name") or ""
            if target_subfolder:
                candidate_sub = self.mods_folder / target_subfolder
                if not is_safe_subpath(candidate_sub, self.mods_folder, allow_equal=True):
                    log_security_warning(
                        f"비정상 설치 하위 폴더 경로 차단: '{target_subfolder}' (기준 Mods 폴더='{self.mods_folder}')"
                    )
                    raise ZipSlipSecurityError(
                        f"[보안 차단] 설치 대상 폴더('{target_subfolder}')가 Mods 폴더 범위를 벗어나 작업을 중단했습니다."
                    )
                if candidate_sub.is_dir():
                    target_dir = candidate_sub
                else:
                    target_dir = self.mods_folder
            else:
                target_dir = self.mods_folder

        if str(self.mods_folder).strip() and self.mods_folder.exists():
            if not is_safe_subpath(target_dir, self.mods_folder, allow_equal=True):
                log_security_warning(
                    f"설치 대상 경로가 Mods 폴더 바깥을 가리켜 차단됨: target_dir='{target_dir}', mods_folder='{self.mods_folder}'"
                )
                raise ZipSlipSecurityError(
                    f"[보안 차단] 설치 대상 경로('{target_dir}')가 지정된 Mods 폴더 하위 경로가 아닙니다."
                )

        # 1. 자동 백업 (사전 일괄 백업을 이미 수행한 경우 skip_backup=True로 중복 백업 생략)
        backup_session = None
        backed_up_paths: set[str] = set()
        if self.backup_manager and not skip_backup:
            _notify("backup", "기존 파일 백업 중...")
            if selected_file_path and selected_file_path.exists():
                backup_session = self.backup_manager.create_backup_session(label=selected_file_path.stem)
                self.backup_manager.backup_item(selected_file_path, backup_session)
                backed_up_paths.add(str(selected_file_path.resolve()))
            elif target_dir.exists() and target_dir != self.mods_folder:
                backup_session = self.backup_manager.create_backup_session(label=mod["name"])
                self.backup_manager.backup_item(target_dir, backup_session)

        installed_names: List[str] = []
        installed_paths: List[Path] = []
        known_existing_paths = [
            Path(p) for p in (mod.get("unit_files") or []) if p and Path(p).exists()
        ]
        if selected_file_path and selected_file_path.exists() and selected_file_path not in known_existing_paths:
            known_existing_paths.append(selected_file_path)

        known_existing_low_set = {str(p.resolve()).lower() for p in known_existing_paths}
        has_subdir_known = any(
            p.parent.resolve() != target_dir.resolve()
            for p in known_existing_paths
            if is_safe_subpath(p, target_dir, allow_equal=False)
        )

        expected_catalog_id = "" if is_multi_file_select_mode else str(mod.get("catalog_id") or "").strip()
        if not expected_catalog_id and not is_multi_file_select_mode:
            try:
                from src.finder import check_known_catalog
                cat_probe = (
                    (check_known_catalog(selected_file_path.name) if selected_file_path else None)
                    or check_known_catalog(mod.get("name") or "")
                )
                if isinstance(cat_probe, dict) and cat_probe.get("matched_catalog"):
                    expected_catalog_id = str(cat_probe["matched_catalog"]).strip()
            except Exception:
                pass

        from src.scanner import CONTAINER_FOLDER_NAMES, ModScanner
        from src.utils import _can_supersede_renamed_mod_file, _lookup_catalog_id_safe

        shared_container_names = set(CONTAINER_FOLDER_NAMES) | {
            "mod", "mods", "gsm", "gm", "prio", "overrides", "override",
            "lms", "lumpinou", "utopya", "frequentlybasic", "natethel0ser",
            "scumbumbo", "sacrificial", "sims4me", "polarbearsims",
            "simkatu", "ilkavelle", "weerbesu", "turbodriver", "twistedmexi",
            "pandasama", "spinningplumbobs", "kuttoe",
            "animations", "animation", "ww animations", "wickedwhims animations",
            "애니메이션", "애니", "ww 애니", "pose", "poses", "포즈",
        }
        target_dir_name_clean = target_dir.name.strip()
        is_numbered_shared_container = bool(
            re.match(
                r"^(?:[\d\-]+[\.\s_\-]*)?(?:MOD|GSM|GM)(?:[\s_\-]*\[?\d+\]?)?$",
                target_dir_name_clean,
                flags=re.IGNORECASE,
            )
            or ModScanner._is_ww_animation_folder_name(target_dir_name_clean, allow_cc_prefix=True)
            or ModScanner._is_pose_folder_name(target_dir_name_clean)
        )
        has_unrelated_direct_mods = False
        if target_dir.exists() and target_dir.is_dir():
            unit_norm_keys = {
                nk
                for kp in known_existing_paths
                if (nk := normalize_mod_filename_key(kp.name))
            }
            if selected_file_path is not None:
                sel_nk_init = normalize_mod_filename_key(selected_file_path.name)
                if sel_nk_init:
                    unit_norm_keys.add(sel_nk_init)
            for sibling_f in target_dir.iterdir():
                if not sibling_f.is_file() or sibling_f.suffix.lower() not in ALLOWED_MOD_WHITELIST_EXTENSIONS:
                    continue
                if str(sibling_f.resolve()).lower() in known_existing_low_set:
                    continue
                sib_nk = normalize_mod_filename_key(sibling_f.name)
                if sib_nk and sib_nk in unit_norm_keys:
                    continue
                sib_cat = _lookup_catalog_id_safe(sibling_f.name)
                if expected_catalog_id and sib_cat == expected_catalog_id:
                    continue
                has_unrelated_direct_mods = True
                break

        is_dedicated_mod_dir = (
            target_dir.resolve() != self.mods_folder.resolve()
            and target_dir_name_clean.lower() not in shared_container_names
            and not is_numbered_shared_container
            and not has_unrelated_direct_mods
        )
        include_subdirs = bool(has_subdir_known or is_dedicated_mod_dir)
        mods_root_resolved = (
            self.mods_folder.resolve()
            if str(self.mods_folder).strip() and self.mods_folder.exists()
            else None
        )

        def _backup_if_exists(dest_p: Path) -> None:
            nonlocal backup_session
            if not self.backup_manager or not dest_p.exists():
                return
            res_str = str(dest_p.resolve())
            if res_str in backed_up_paths:
                return
            if skip_backup and res_str.lower() in known_existing_low_set:
                return
            if backup_session is None:
                backup_session = self.backup_manager.create_backup_session(
                    label=(selected_file_path.stem if selected_file_path else mod.get("name") or "pre_cleanup")
                )
            self.backup_manager.backup_item(dest_p, backup_session)
            backed_up_paths.add(res_str)

        # 2. 임시 다운로드 및 설치
        with tempfile.TemporaryDirectory(prefix="s4mod_upd_") as tmp_dir:
            tmp_path = Path(tmp_dir).resolve()
            temp_extract_dir = tmp_path / "extract_work"
            temp_extract_dir.mkdir(parents=True, exist_ok=True)

            raw_asset_name = Path(str(update_info.get("asset_name") or "download.zip").replace("\\", "/")).name
            asset_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", raw_asset_name).strip(" .")
            if not asset_name:
                asset_name = "download.zip"
            bad_asset_ext = inspect_dangerous_extension(asset_name)
            if bad_asset_ext is not None:
                log_security_warning(
                    f"다운로드 요청 단계에서 위험 확장자('{bad_asset_ext}') 에셋 차단: '{asset_name}'"
                )
                raise DangerousFileExtensionError(
                    f"[보안 차단] 실행/스크립트 계열 위험 확장자('{bad_asset_ext}') 파일은 다운로드할 수 없습니다: {asset_name}"
                )
            if not asset_name.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")):
                asset_name += ".zip"
            downloaded_file = tmp_path / asset_name
            if not is_safe_subpath(downloaded_file, tmp_path):
                log_security_warning(f"다운로드 임시 파일 경로 이탈 차단: '{downloaded_file}'")
                raise ZipSlipSecurityError("[보안 차단] 다운로드 대상 파일명이 임시 폴더 경로를 벗어납니다.")

            page_url_ref = (update_info.get("page_url") or "").strip()
            if page_url_ref and not is_valid_https_url(page_url_ref):
                log_security_warning(f"모드 업데이트 참조 페이지 비-HTTPS URL 제거: {page_url_ref!r}")
                page_url_ref = ""
            _notify("download", f"다운로드 중 ({asset_name})...")
            download_file(
                download_url,
                downloaded_file,
                fallback_source_dir=target_dir,
                page_url=page_url_ref,
                target_mod_name=mod.get("name") or asset_name,
            )

            # 2-1. 압축 해제 및 덮어쓰기 전 모드 파일 무결성 및 압축 엔트리 헤더 사전 보안 검증 (Zip Slip/HTML 응답/무관한 파일 덮어쓰기 차단)
            _notify("verify", f"파일 안전 검증 중 ({asset_name})...")
            verify_downloaded_mod_file(
                downloaded_file,
                expected_target_name=mod.get("name"),
                target_dir=target_dir,
                temp_extract_dir=temp_extract_dir,
            )

            # 기존 설치 폴더 준비
            target_dir.mkdir(parents=True, exist_ok=True)
            existing_names_map: Dict[str, Path] = {}
            existing_norm_map: Dict[str, Path] = {}
            existing_iter = target_dir.rglob("*") if include_subdirs else target_dir.iterdir()
            for f in existing_iter:
                if not f.is_file() or f.suffix.lower() not in ALLOWED_MOD_WHITELIST_EXTENSIONS:
                    continue
                existing_names_map.setdefault(f.name.lower(), f)
                fn_nk = normalize_mod_filename_key(f.name)
                if fn_nk:
                    existing_norm_map.setdefault(fn_nk, f)
            for kf in known_existing_paths:
                if kf.exists() and kf.is_file() and kf.suffix.lower() in ALLOWED_MOD_WHITELIST_EXTENSIONS:
                    existing_names_map.setdefault(kf.name.lower(), kf)
                    fn_nk = normalize_mod_filename_key(kf.name)
                    if fn_nk:
                        existing_norm_map.setdefault(fn_nk, kf)

            # 3. 설치 (ZIP/RAR/7Z 압축 해제 또는 단일 파일 교체)
            installed_archive_norm_keys: set[str] = set()
            if downloaded_file.suffix.lower() in (".zip", ".rar", ".7z"):
                _notify("extract", f"압축 해제 및 설치 중 ({asset_name})...")
                arch_nk = normalize_mod_filename_key(asset_name)
                if arch_nk:
                    installed_archive_norm_keys.add(arch_nk)
                optional_addons = update_info.get("optional_addons") or []
                has_selected_addons_cfg = bool(optional_addons) and ("selected_addons" in update_info) and (update_info.get("selected_addons") is not None)
                all_opt_low = {
                    str(oa.get("file_name") or "").strip().lower()
                    for oa in optional_addons
                    if isinstance(oa, dict) and oa.get("file_name")
                }
                chosen_opt_low = {
                    str(x).strip().lower()
                    for x in (update_info.get("selected_addons") or [])
                    if str(x).strip()
                }
                unselected_opt_low = all_opt_low - chosen_opt_low

                if has_selected_addons_cfg and target_dir.exists():
                    for opt_f in list(target_dir.iterdir()):
                        if opt_f.is_file() and opt_f.name.lower() in all_opt_low:
                            _backup_if_exists(opt_f)

                target_fn = selected_file_path.name if selected_file_path else None
                extracted_paths = extract_zip(
                    downloaded_file,
                    target_dir,
                    target_filename=target_fn,
                    overwrite_mode=overwrite_mode,
                    temp_work_dir=temp_extract_dir,
                    known_existing_files=known_existing_paths,
                    include_subdirs=include_subdirs,
                    force_include_names=(archive_only_include_names or (chosen_opt_low if has_selected_addons_cfg else None)),
                    only_include_names=archive_only_include_names,
                    pre_remove_callback=_backup_if_exists,
                    selected_file_path=selected_file_path,
                    mods_root_resolved=mods_root_resolved,
                    expected_catalog_id=expected_catalog_id,
                    protected_paths=installed_paths,
                )
                safe_remove(downloaded_file)
                safe_remove(temp_extract_dir)

                if has_selected_addons_cfg and unselected_opt_low and not is_multi_file_select_mode:
                    if target_dir.exists():
                        for rem_opt in list(target_dir.iterdir()):
                            if rem_opt.is_file() and rem_opt.name.lower() in unselected_opt_low:
                                _backup_if_exists(rem_opt)
                                safe_remove(rem_opt)
                    extracted_paths = [ep for ep in extracted_paths if ep.name.lower() not in unselected_opt_low]

                for ep in extracted_paths:
                    if ep not in installed_paths:
                        installed_paths.append(ep)
                    if ep.name not in installed_names:
                        installed_names.append(ep.name)

                # Political World 등 상호 배타적(동시 설치 불가) 에디션(Fictional vs RealLife) 전환 시 이전 에디션 파일 정리
                ext_names_low = [ep.name.lower() for ep in extracted_paths]
                if any("politicalworld" in n for n in ext_names_low):
                    installed_fictional = any("fictional" in n for n in ext_names_low)
                    for ex_file in list(target_dir.iterdir()):
                        if not ex_file.is_file() or ex_file.name in installed_names:
                            continue
                        ex_low = ex_file.name.lower()
                        if "politicalworld" not in ex_low:
                            continue
                        if installed_fictional and ("coremod(realisticedition)_required" in ex_low or "politicalgurus_realisticedition" in ex_low):
                            _backup_if_exists(ex_file)
                            safe_remove(ex_file)
                        elif not installed_fictional and "fictional" in ex_low:
                            _backup_if_exists(ex_file)
                            safe_remove(ex_file)
                elif any("fitnesscontrols-limits" in n for n in ext_names_low):
                    for ex_file in list(target_dir.iterdir()):
                        if not ex_file.is_file() or ex_file.name in installed_names:
                            continue
                        if "fitnesscontrols-limits" in ex_file.name.lower():
                            _backup_if_exists(ex_file)
                            safe_remove(ex_file)
                elif any("lumpinou_firstimpressions" in n and "timedecay" in n and "optional" not in n for n in ext_names_low):
                    ext_low_set = set(ext_names_low)
                    for ex_file in list(target_dir.iterdir()):
                        if not ex_file.is_file():
                            continue
                        ex_low = ex_file.name.lower()
                        if (
                            "lumpinou_firstimpressions" in ex_low
                            and "timedecay" in ex_low
                            and "optional" not in ex_low
                            and ex_low not in ext_low_set
                        ):
                            _backup_if_exists(ex_file)
                            safe_remove(ex_file)

                if selected_file_path:
                    same_ext_files = [
                        ep for ep in extracted_paths
                        if ep.suffix.lower() == selected_file_path.suffix.lower()
                    ]
                    if len(same_ext_files) == 1 and same_ext_files[0].resolve() != selected_file_path.resolve():
                        if _can_supersede_renamed_mod_file(
                            selected_file_path.name,
                            same_ext_files[0].name,
                            _lookup_catalog_id_safe(selected_file_path.name),
                            _lookup_catalog_id_safe(same_ext_files[0].name),
                        ):
                            if selected_file_path.exists():
                                _backup_if_exists(selected_file_path)
                                safe_remove(selected_file_path)
                            mod["file_path"] = str(same_ext_files[0])
                            if isinstance(mod.get("selected_file"), dict):
                                mod["selected_file"]["name"] = same_ext_files[0].name
                                mod["selected_file"]["full_path"] = str(same_ext_files[0])
                    elif same_ext_files:
                        sel_nk = normalize_mod_filename_key(selected_file_path.name)
                        fi_core = next(
                            (
                                ep for ep in same_ext_files
                                if "lumpinou_firstimpressions" in ep.name.lower()
                                and "timedecay" in ep.name.lower()
                                and "optional" not in ep.name.lower()
                            ),
                            None,
                        )
                        matched_rep = fi_core or next(
                            (ep for ep in same_ext_files if normalize_mod_filename_key(ep.name) == sel_nk),
                            same_ext_files[0],
                        )
                        if (
                            selected_file_path.exists()
                            and matched_rep.resolve() != selected_file_path.resolve()
                            and normalize_mod_filename_key(matched_rep.name) == sel_nk
                        ):
                            _backup_if_exists(selected_file_path)
                            safe_remove(selected_file_path)
                        mod["file_path"] = str(matched_rep)
                        if isinstance(mod.get("selected_file"), dict):
                            mod["selected_file"]["name"] = matched_rep.name
                            mod["selected_file"]["full_path"] = str(matched_rep)
            else:
                _notify("extract", f"모드 파일 설치 중 ({downloaded_file.name})...")
                if not is_whitelisted_mod_file(downloaded_file, ALLOWED_MOD_WHITELIST_EXTENSIONS):
                    safe_remove(downloaded_file)
                    raise ValueError(
                        f"화이트리스트에 허용되지 않은 확장자 파일('{downloaded_file.name}')이어서 Mods 폴더 반영을 차단했습니다."
                    )
                superseded_single, dest_parent_hints = find_superseded_mod_files(
                    incoming_names=[downloaded_file.name],
                    target_dir_resolved=target_dir.resolve(),
                    mods_root_resolved=mods_root_resolved,
                    known_existing_files=known_existing_paths,
                    selected_file_path=selected_file_path,
                    include_subdirs=include_subdirs,
                    expected_catalog_id=expected_catalog_id,
                    protected_paths=installed_paths,
                )
                hint_parent = dest_parent_hints.get(downloaded_file.name.lower())
                dest_dir_single = (
                    hint_parent
                    if hint_parent is not None and is_safe_subpath(hint_parent, target_dir, allow_equal=True)
                    else target_dir
                )
                dest = dest_dir_single / downloaded_file.name
                if not is_safe_subpath(dest, target_dir):
                    safe_remove(downloaded_file)
                    raise ZipSlipSecurityError(f"[보안 차단] 설치 대상 경로('{dest}')가 Mods 폴더 범위를 벗어납니다.")

                # 새 버전 파일 배치 전 기존 구버전/동일 카탈로그 파일을 먼저 백업 및 안전 제거
                for old_p in superseded_single:
                    _backup_if_exists(old_p)
                    safe_remove(old_p)
                if (
                    not is_multi_file_select_mode
                    and selected_file_path
                    and selected_file_path.exists()
                    and selected_file_path.suffix.lower() == downloaded_file.suffix.lower()
                    and selected_file_path.resolve() != dest.resolve()
                    and _can_supersede_renamed_mod_file(
                        selected_file_path.name,
                        downloaded_file.name,
                        _lookup_catalog_id_safe(selected_file_path.name),
                        _lookup_catalog_id_safe(downloaded_file.name),
                    )
                ):
                    _backup_if_exists(selected_file_path)
                    safe_remove(selected_file_path)
                _backup_if_exists(dest)
                safe_remove(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(downloaded_file), str(dest))
                installed_paths.append(dest)
                installed_names.append(dest.name)
                mod["file_path"] = str(dest)
                if isinstance(mod.get("selected_file"), dict):
                    mod["selected_file"]["name"] = dest.name
                    mod["selected_file"]["full_path"] = str(dest)

            # 4. 'all'(다 같이 덮어쓰기) 모드이거나 다중 패키지/스크립트 세트(예: Volleyball Mod 5개 파일)인 경우, 동일 배포 페이지의 구성 파일을 모두 다운로드 및 덮어쓰기
            is_multi_bundle = bool(update_info.get("is_multi_file_bundle"))
            if overwrite_mode == "all" or is_multi_bundle:
                from src.utils import _is_variant_or_edition_protected_file, _lookup_catalog_id_safe
                all_remote_files = update_info.get("all_remote_files") or []
                seen_remote_urls = {download_url}
                installed_norm_keys_so_far: set[str] = {
                    nk
                    for n in installed_names
                    if (nk := normalize_mod_filename_key(n))
                }
                installed_cat_ext_core: set[Tuple[str, str]] = set()
                if expected_catalog_id:
                    for n in installed_names:
                        if not _is_variant_or_edition_protected_file(n):
                            installed_cat_ext_core.add((expected_catalog_id, Path(n).suffix.lower()))

                for idx_rem, (rem_fn, rem_dl) in enumerate(all_remote_files):
                    if not rem_fn or not rem_dl or rem_dl in seen_remote_urls or rem_fn in installed_names:
                        continue
                    safe_rem_base = Path(str(rem_fn).replace("\\", "/")).name
                    clean_rem_fn = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", safe_rem_base).strip(" .")
                    if not clean_rem_fn or clean_rem_fn in installed_names:
                        continue
                    if is_auxiliary_non_mod_archive(clean_rem_fn, target_mod_name=mod.get("name") or ""):
                        continue
                    bad_rem_ext = inspect_dangerous_extension(clean_rem_fn)
                    if bad_rem_ext is not None:
                        log_security_warning(
                            f"부가 구성 파일 목록에서 위험 확장자('{bad_rem_ext}') 감지 및 작업 중단: '{clean_rem_fn}'"
                        )
                        raise DangerousFileExtensionError(
                            f"[보안 차단] 부가 다운로드 항목에서 위험 확장자('{bad_rem_ext}')가 감지되어 중단했습니다: {clean_rem_fn}"
                        )
                    validate_https_url(rem_dl, allow_fragment=True, purpose="부가 모드 파일 다운로드")
                    rem_ext = Path(clean_rem_fn).suffix.lower()
                    rem_norm_key = normalize_mod_filename_key(clean_rem_fn)
                    has_existing_match = (
                        clean_rem_fn.lower() in existing_names_map
                        or (bool(rem_norm_key) and rem_norm_key in existing_norm_map)
                    )
                    if rem_ext in ALLOWED_MOD_WHITELIST_EXTENSIONS and (is_multi_bundle or has_existing_match):
                        # 동일 포스트에 남아 있는 구버전 첨부파일 중복 다운로드 차단
                        if rem_norm_key and rem_norm_key in installed_norm_keys_so_far:
                            continue
                        if (
                            not is_multi_bundle
                            and expected_catalog_id
                            and (expected_catalog_id, rem_ext) in installed_cat_ext_core
                            and not _is_variant_or_edition_protected_file(clean_rem_fn)
                            and (_lookup_catalog_id_safe(clean_rem_fn) or expected_catalog_id) == expected_catalog_id
                        ):
                            continue
                        try:
                            seen_remote_urls.add(rem_dl)
                            sub_dl = tmp_path / clean_rem_fn
                            if not is_safe_subpath(sub_dl, tmp_path):
                                raise ZipSlipSecurityError(f"부가 다운로드 파일 경로 이탈 감지: {rem_fn!r}")
                            download_file(rem_dl, sub_dl, page_url=page_url_ref, target_mod_name=clean_rem_fn)
                            verify_downloaded_mod_file(
                                sub_dl,
                                expected_target_name=clean_rem_fn,
                                target_dir=target_dir,
                                temp_extract_dir=temp_extract_dir,
                            )
                            if not is_whitelisted_mod_file(sub_dl, ALLOWED_MOD_WHITELIST_EXTENSIONS):
                                safe_remove(sub_dl)
                                continue
                            superseded_sub, sub_parent_hints = find_superseded_mod_files(
                                incoming_names=[clean_rem_fn],
                                target_dir_resolved=target_dir.resolve(),
                                mods_root_resolved=mods_root_resolved,
                                known_existing_files=known_existing_paths,
                                include_subdirs=include_subdirs,
                                expected_catalog_id=expected_catalog_id,
                                protected_paths=installed_paths,
                            )
                            dest_parent = (
                                existing_names_map[clean_rem_fn.lower()].parent
                                if clean_rem_fn.lower() in existing_names_map
                                else (
                                    existing_norm_map[rem_norm_key].parent
                                    if rem_norm_key in existing_norm_map
                                    else sub_parent_hints.get(clean_rem_fn.lower(), target_dir)
                                )
                            )
                            if not is_safe_subpath(dest_parent, target_dir, allow_equal=True):
                                dest_parent = target_dir
                            dest_sub = dest_parent / clean_rem_fn
                            if not is_safe_subpath(dest_sub, target_dir):
                                raise ZipSlipSecurityError(f"부가 설치 파일 대상 경로 이탈 감지: {clean_rem_fn!r}")
                            for old_sub in superseded_sub:
                                _backup_if_exists(old_sub)
                                safe_remove(old_sub)
                            _backup_if_exists(dest_sub)
                            safe_remove(dest_sub)
                            dest_sub.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(sub_dl), str(dest_sub))
                            if dest_sub not in installed_paths:
                                installed_paths.append(dest_sub)
                            if clean_rem_fn not in installed_names:
                                installed_names.append(clean_rem_fn)
                            if rem_norm_key:
                                installed_norm_keys_so_far.add(rem_norm_key)
                            if expected_catalog_id and not _is_variant_or_edition_protected_file(clean_rem_fn):
                                installed_cat_ext_core.add((expected_catalog_id, rem_ext))
                        except (ArchiveSecurityError, NetworkSecurityError):
                            raise
                        except Exception:
                            pass
                    elif rem_ext in (".zip", ".rar", ".7z"):
                        if rem_norm_key and rem_norm_key in installed_archive_norm_keys:
                            continue
                        # 다중 옵션 아카이브(예: Limits 1.75x, 2.5x, 3.0x 등) 중 현재 폴더에 설치되지 않은 다른 변형 아카이브는 건너뜀
                        rem_stem_low = Path(clean_rem_fn).stem.lower()
                        if "limits" in rem_stem_low and not any(rem_stem_low in ex_n for ex_n in existing_names_map):
                            continue
                        sub_extract_dir = tmp_path / f"extract_sub_{idx_rem}"
                        try:
                            seen_remote_urls.add(rem_dl)
                            sub_dl = tmp_path / clean_rem_fn
                            if not is_safe_subpath(sub_dl, tmp_path):
                                raise ZipSlipSecurityError(f"부가 아카이브 경로 이탈 감지: {rem_fn!r}")
                            sub_extract_dir.mkdir(parents=True, exist_ok=True)
                            download_file(rem_dl, sub_dl, page_url=page_url_ref, target_mod_name=clean_rem_fn)
                            verify_downloaded_mod_file(
                                sub_dl,
                                expected_target_name=clean_rem_fn,
                                target_dir=target_dir,
                                temp_extract_dir=sub_extract_dir,
                            )
                            sub_extracted = extract_zip(
                                sub_dl,
                                target_dir,
                                overwrite_mode="all",
                                temp_work_dir=sub_extract_dir,
                                known_existing_files=known_existing_paths,
                                include_subdirs=include_subdirs,
                                pre_remove_callback=_backup_if_exists,
                                mods_root_resolved=mods_root_resolved,
                                expected_catalog_id=expected_catalog_id,
                                protected_paths=installed_paths,
                            )
                            safe_remove(sub_dl)
                            if rem_norm_key:
                                installed_archive_norm_keys.add(rem_norm_key)
                            for sep in sub_extracted:
                                if sep not in installed_paths:
                                    installed_paths.append(sep)
                                if sep.name not in installed_names:
                                    installed_names.append(sep.name)
                                sep_nk = normalize_mod_filename_key(sep.name)
                                if sep_nk:
                                    installed_norm_keys_so_far.add(sep_nk)
                                if expected_catalog_id and not _is_variant_or_edition_protected_file(sep.name):
                                    installed_cat_ext_core.add((expected_catalog_id, sep.suffix.lower()))
                        except (ArchiveSecurityError, NetworkSecurityError):
                            raise
                        except Exception:
                            pass
                        finally:
                            safe_remove(sub_extract_dir)

            # 4-0. 상호 배타적 단일 옵션 파일 교체 시 기존 타 옵션 파일 백업 후 정리
            installed_low_names = {ip.name.lower() for ip in installed_paths if ip.exists()}
            if any("canvas_frame_override_v" in n for n in installed_low_names):
                for ex_cf in list(target_dir.iterdir()):
                    if (
                        ex_cf.is_file()
                        and "canvas_frame_override_v" in ex_cf.name.lower()
                        and ex_cf.name.lower() not in installed_low_names
                    ):
                        _backup_if_exists(ex_cf)
                        safe_remove(ex_cf)
            if any("simkatu_painting_animation_override" in n for n in installed_low_names):
                for ex_pa in list(target_dir.iterdir()):
                    if (
                        ex_pa.is_file()
                        and "simkatu_painting_animation_override" in ex_pa.name.lower()
                        and ex_pa.name.lower() not in installed_low_names
                    ):
                        _backup_if_exists(ex_pa)
                        safe_remove(ex_pa)
            if any("more_cas_columns" in n for n in installed_low_names):
                for ex_mc in list(target_dir.iterdir()):
                    if (
                        ex_mc.is_file()
                        and "more_cas_columns" in ex_mc.name.lower()
                        and ex_mc.name.lower() not in installed_low_names
                    ):
                        _backup_if_exists(ex_mc)
                        safe_remove(ex_mc)
            if any("tryonweddingpromoutfits_alllots" in n or "tryonweddingpromoutfits_retailthriftlots" in n for n in installed_low_names):
                for ex_tw in list(target_dir.iterdir()):
                    if not ex_tw.is_file():
                        continue
                    ex_tw_low = ex_tw.name.lower()
                    if (
                        ("tryonweddingpromoutfits_alllots" in ex_tw_low or "tryonweddingpromoutfits_retailthriftlots" in ex_tw_low)
                        and ex_tw_low not in installed_low_names
                    ):
                        _backup_if_exists(ex_tw)
                        safe_remove(ex_tw)
            if any(
                n in ("simkatu_mirrorphoto.package", "simkatu_mirrorphoto_v2_genderneutral.package")
                for n in installed_low_names
            ):
                for ex_ms in list(target_dir.iterdir()):
                    if not ex_ms.is_file():
                        continue
                    ex_ms_low = ex_ms.name.lower()
                    if (
                        ex_ms_low in ("simkatu_mirrorphoto.package", "simkatu_mirrorphoto_v2_genderneutral.package")
                        and ex_ms_low not in installed_low_names
                    ):
                        _backup_if_exists(ex_ms)
                        safe_remove(ex_ms)
            if any(
                n in (
                    "simkatu_music_listening_interactions.package",
                    "simkatu_music_listening_interactions_autonomy_off.package",
                )
                for n in installed_low_names
            ):
                for ex_ml in list(target_dir.iterdir()):
                    if not ex_ml.is_file():
                        continue
                    ex_ml_low = ex_ml.name.lower()
                    if (
                        ex_ml_low in (
                            "simkatu_music_listening_interactions.package",
                            "simkatu_music_listening_interactions_autonomy_off.package",
                        )
                        and ex_ml_low not in installed_low_names
                    ):
                        _backup_if_exists(ex_ml)
                        safe_remove(ex_ml)
            if any(
                n in (
                    "simkatu_nap_on_the_table.package",
                    "simkatu_nap_on_the_table_more_energy.package",
                )
                for n in installed_low_names
            ):
                for ex_nt in list(target_dir.iterdir()):
                    if not ex_nt.is_file():
                        continue
                    ex_nt_low = ex_nt.name.lower()
                    if (
                        ex_nt_low in (
                            "simkatu_nap_on_the_table.package",
                            "simkatu_nap_on_the_table_more_energy.package",
                        )
                        and ex_nt_low not in installed_low_names
                    ):
                        _backup_if_exists(ex_nt)
                        safe_remove(ex_nt)
            if any(
                n in (
                    "simkatu_mod_endless_grief_with_autonomy.package",
                    "simkatu_mod_endless_grief_without_autonomy.package",
                )
                for n in installed_low_names
            ):
                for ex_eg in list(target_dir.iterdir()):
                    if not ex_eg.is_file():
                        continue
                    ex_eg_low = ex_eg.name.lower()
                    if (
                        ex_eg_low in (
                            "simkatu_mod_endless_grief_with_autonomy.package",
                            "simkatu_mod_endless_grief_without_autonomy.package",
                        )
                        and ex_eg_low not in installed_low_names
                    ):
                        _backup_if_exists(ex_eg)
                        safe_remove(ex_eg)
            if any(
                n in (
                    "simkatu_nap_with_baby_in_bed.package",
                    "simkatu_nap_with_baby_in_bed_v2_more_energy.package",
                )
                for n in installed_low_names
            ):
                for ex_nb in list(target_dir.iterdir()):
                    if not ex_nb.is_file():
                        continue
                    ex_nb_low = ex_nb.name.lower()
                    if (
                        ex_nb_low in (
                            "simkatu_nap_with_baby_in_bed.package",
                            "simkatu_nap_with_baby_in_bed_v2_more_energy.package",
                        )
                        and ex_nb_low not in installed_low_names
                    ):
                        _backup_if_exists(ex_nb)
                        safe_remove(ex_nb)
            if any(
                n in (
                    "simkatu_kids_interactions_pack_v1_ea_homework.package",
                    "simkatu_kids_interactions_pack_v2_custom_homework.package",
                )
                for n in installed_low_names
            ):
                for ex_kp in list(target_dir.iterdir()):
                    if not ex_kp.is_file():
                        continue
                    ex_kp_low = ex_kp.name.lower()
                    if (
                        ex_kp_low in (
                            "simkatu_kids_interactions_pack_v1_ea_homework.package",
                            "simkatu_kids_interactions_pack_v2_custom_homework.package",
                        )
                        and ex_kp_low not in installed_low_names
                    ):
                        _backup_if_exists(ex_kp)
                        safe_remove(ex_kp)
            if any(
                n in (
                    "simkatu_givemedicine_v1_sickness_gtw.package",
                    "simkatu_givemedicine_v2_sickness_ailments_gtw_ebn.package",
                )
                for n in installed_low_names
            ):
                for ex_gm in list(target_dir.iterdir()):
                    if not ex_gm.is_file():
                        continue
                    ex_gm_low = ex_gm.name.lower()
                    if (
                        ex_gm_low in (
                            "simkatu_givemedicine_v1_sickness_gtw.package",
                            "simkatu_givemedicine_v2_sickness_ailments_gtw_ebn.package",
                        )
                        and ex_gm_low not in installed_low_names
                    ):
                        _backup_if_exists(ex_gm)
                        safe_remove(ex_gm)
            wlpo_core_variants = {
                "wlpo.package",
                "wlpo-nocc.package",
                "wlpo_nocc.package",
                "wlpo-all.package",
                "wlpo_all.package",
            }
            if any(n in wlpo_core_variants for n in installed_low_names):
                for ex_wlpo in list(target_dir.iterdir()):
                    if not ex_wlpo.is_file():
                        continue
                    ex_wlpo_low = ex_wlpo.name.lower()
                    if ex_wlpo_low in wlpo_core_variants and ex_wlpo_low not in installed_low_names:
                        _backup_if_exists(ex_wlpo)
                        safe_remove(ex_wlpo)
            if any("livedrag" in n for n in installed_low_names):
                has_livedrag_all = any("livedragall" in n for n in installed_low_names)
                for ex_ld in list(target_dir.iterdir()):
                    if not ex_ld.is_file():
                        continue
                    ex_ld_low = ex_ld.name.lower()
                    if "livedrag" not in ex_ld_low or ex_ld_low in installed_low_names:
                        continue
                    if has_livedrag_all or "livedragall" in ex_ld_low:
                        _backup_if_exists(ex_ld)
                        safe_remove(ex_ld)
            if any("lumpinou_rpo_collection_m" in n for n in installed_low_names):
                installed_rpo_slots: set[Tuple[str, str]] = set()
                for n in installed_low_names:
                    m_slot = re.search(r"lumpinou_rpo_collection_(m\d+)_", n)
                    if m_slot:
                        installed_rpo_slots.add((m_slot.group(1), Path(n).suffix.lower()))
                for ex_rpo in list(target_dir.iterdir()):
                    if not ex_rpo.is_file():
                        continue
                    ex_low = ex_rpo.name.lower()
                    if ex_low in installed_low_names:
                        continue
                    m_ex_slot = re.search(r"lumpinou_rpo_collection_(m\d+)_", ex_low)
                    if m_ex_slot and (m_ex_slot.group(1), ex_rpo.suffix.lower()) in installed_rpo_slots:
                        _backup_if_exists(ex_rpo)
                        safe_remove(ex_rpo)

            # 4-0. 후속 패치 오버레이(post_install_overlays) 적용 (예: 기본팩 설치 후 Gold_Normal만 최신 패치로 2차 덮어쓰기)
            raw_overlays = list(update_info.get("post_install_overlays") or [])
            if not raw_overlays:
                try:
                    from src.finder import check_known_catalog
                    _cat_ov = (
                        check_known_catalog(mod.get("name") or "", is_ww_animation_hint=True)
                        or (check_known_catalog(selected_file_path.name, is_ww_animation_hint=True) if selected_file_path else None)
                    )
                    if isinstance(_cat_ov, dict):
                        raw_overlays = list(_cat_ov.get("post_install_overlays") or [])
                except Exception:
                    pass
            if raw_overlays:
                from src.finder import inspect_remote_mod_page
                for idx_ov, ov in enumerate(raw_overlays):
                    if not isinstance(ov, dict):
                        continue
                    ov_url = str(ov.get("url") or "").strip()
                    if not ov_url or not is_valid_https_url(ov_url):
                        continue
                    ov_ver = str(ov.get("version") or "").strip()
                    ov_label = str(ov.get("label") or ov_url).strip()
                    ov_tokens = [
                        str(t).strip().lower()
                        for t in (ov.get("target_tokens") or [])
                        if str(t).strip()
                    ]
                    try:
                        _notify("download", f"추가 패치 확인 중 ({ov_label})...")
                        ov_res = inspect_remote_mod_page(ov_url, target_mod_name=(ov_label or mod.get("name") or ""))
                        if not isinstance(ov_res, dict) or ov_res.get("status") != "free_direct":
                            continue
                        ov_dl_url = str(ov_res.get("download_url") or "").strip()
                        if not ov_dl_url:
                            continue
                        validate_https_url(ov_dl_url, allow_fragment=True, purpose="후속 패치 오버레이 다운로드")
                        raw_ov_fn = Path(str(ov_res.get("file_name") or f"overlay_{idx_ov}.package").replace("\\", "/")).name
                        ov_clean_fn = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", raw_ov_fn).strip(" .") or f"overlay_{idx_ov}.package"
                        bad_ov_ext = inspect_dangerous_extension(ov_clean_fn)
                        if bad_ov_ext is not None:
                            raise DangerousFileExtensionError(
                                f"[보안 차단] 후속 패치에서 위험 확장자('{bad_ov_ext}')가 감지되어 중단했습니다: {ov_clean_fn}"
                            )
                        ov_dl_path = tmp_path / f"ov_{idx_ov}_{ov_clean_fn}"
                        if not is_safe_subpath(ov_dl_path, tmp_path):
                            raise ZipSlipSecurityError(f"후속 패치 경로 이탈 감지: {ov_clean_fn!r}")
                        download_file(ov_dl_url, ov_dl_path, page_url=ov_url, target_mod_name=ov_clean_fn)
                        verify_downloaded_mod_file(
                            ov_dl_path,
                            expected_target_name=mod.get("name") or ov_clean_fn,
                            target_dir=target_dir,
                            temp_extract_dir=temp_extract_dir,
                        )
                        ov_applied = False
                        if ov_dl_path.suffix.lower() in (".zip", ".rar", ".7z"):
                            ov_only_names: Optional[set[str]] = None
                            if ov_dl_path.suffix.lower() == ".zip" and ov_tokens and zipfile.is_zipfile(ov_dl_path):
                                with zipfile.ZipFile(ov_dl_path, "r") as zov:
                                    matched_ov_members = {
                                        Path(nm).name.lower()
                                        for nm in zov.namelist()
                                        if any(tok in Path(nm).name.lower() for tok in ov_tokens)
                                        and Path(nm).suffix.lower() in ALLOWED_MOD_WHITELIST_EXTENSIONS
                                    }
                                if matched_ov_members:
                                    ov_only_names = matched_ov_members
                            ov_extract_dir = tmp_path / f"extract_ov_{idx_ov}"
                            ov_ext_paths = extract_zip(
                                ov_dl_path,
                                target_dir,
                                overwrite_mode="all",
                                temp_work_dir=ov_extract_dir,
                                known_existing_files=list(dict.fromkeys(known_existing_paths + installed_paths)),
                                include_subdirs=include_subdirs,
                                force_include_names=ov_only_names,
                                only_include_names=ov_only_names,
                                pre_remove_callback=_backup_if_exists,
                                selected_file_path=selected_file_path,
                                mods_root_resolved=mods_root_resolved,
                                expected_catalog_id="",
                                protected_paths=[],
                            )
                            safe_remove(ov_dl_path)
                            safe_remove(ov_extract_dir)
                            for oep in ov_ext_paths:
                                ov_applied = True
                                if oep not in installed_paths:
                                    installed_paths.append(oep)
                                if oep.name not in installed_names:
                                    installed_names.append(oep.name)
                        else:
                            if not is_whitelisted_mod_file(ov_dl_path, ALLOWED_MOD_WHITELIST_EXTENSIONS):
                                safe_remove(ov_dl_path)
                                continue
                            dest_ov_dir = target_dir
                            if ov_clean_fn.lower() in existing_names_map:
                                cand_ov_p = existing_names_map[ov_clean_fn.lower()].parent
                                if is_safe_subpath(cand_ov_p, target_dir, allow_equal=True):
                                    dest_ov_dir = cand_ov_p
                            elif ov_tokens:
                                for ip_ex in list(installed_paths):
                                    if ip_ex.exists() and any(tok in ip_ex.name.lower() for tok in ov_tokens):
                                        if is_safe_subpath(ip_ex.parent, target_dir, allow_equal=True):
                                            dest_ov_dir = ip_ex.parent
                                            break
                            dest_ov = dest_ov_dir / ov_clean_fn
                            if not is_safe_subpath(dest_ov, target_dir):
                                raise ZipSlipSecurityError(f"후속 패치 대상 경로 이탈 감지: {ov_clean_fn!r}")
                            if ov_tokens:
                                for cand_dir in ({target_dir} | {ip.parent for ip in installed_paths if ip.exists()}):
                                    if not cand_dir.exists() or not is_safe_subpath(cand_dir, target_dir, allow_equal=True):
                                        continue
                                    for old_tok_f in list(cand_dir.iterdir()):
                                        if (
                                            old_tok_f.is_file()
                                            and old_tok_f.suffix.lower() == dest_ov.suffix.lower()
                                            and any(tok in old_tok_f.name.lower() for tok in ov_tokens)
                                            and old_tok_f.resolve() != dest_ov.resolve()
                                        ):
                                            _backup_if_exists(old_tok_f)
                                            safe_remove(old_tok_f)
                                            installed_paths = [p for p in installed_paths if p != old_tok_f]
                                            installed_names = [n for n in installed_names if n.lower() != old_tok_f.name.lower()]
                            _backup_if_exists(dest_ov)
                            safe_remove(dest_ov)
                            dest_ov.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(ov_dl_path), str(dest_ov))
                            ov_applied = True
                            if dest_ov not in installed_paths:
                                installed_paths.append(dest_ov)
                            if dest_ov.name not in installed_names:
                                installed_names.append(dest_ov.name)
                        if ov_applied and ov_ver:
                            update_info = dict(update_info, latest_version=ov_ver)
                    except (ArchiveSecurityError, NetworkSecurityError):
                        raise
                    except Exception:
                        continue

            # 4-1. 새로 설치된 파일과 정규화 키가 일치하는 구버전 파일(예: _v1.972.package -> _v1.98.package) 자동 백업 및 정리
            if installed_paths:
                installed_resolved = {ip.resolve() for ip in installed_paths if ip.exists()}
                installed_norm_keys = {
                    normalize_mod_filename_key(ip.name)
                    for ip in installed_paths
                    if ip.exists() and normalize_mod_filename_key(ip.name)
                }
                if installed_norm_keys:
                    candidate_old_files: List[Path] = list(known_existing_paths)
                    scan_dirs = {target_dir.resolve()} | {ip.parent.resolve() for ip in installed_paths}
                    for sd in scan_dirs:
                        if sd.exists() and is_safe_subpath(sd, self.mods_folder, allow_equal=True):
                            for f in sd.iterdir():
                                if f.is_file() and f.suffix.lower() in ALLOWED_MOD_WHITELIST_EXTENSIONS:
                                    candidate_old_files.append(f)

                    seen_old_resolved: set[Path] = set()
                    for old_f in candidate_old_files:
                        try:
                            if not old_f.exists() or not old_f.is_file() or old_f.is_symlink():
                                continue
                            old_res = old_f.resolve()
                            if old_res in seen_old_resolved or old_res in installed_resolved:
                                continue
                            seen_old_resolved.add(old_res)
                            if not is_safe_subpath(old_res, self.mods_folder, allow_equal=False):
                                continue
                            if normalize_mod_filename_key(old_f.name) in installed_norm_keys:
                                _backup_if_exists(old_f)
                                safe_remove(old_f)
                        except OSError:
                            continue

        mod["installed_paths"] = [str(p) for p in installed_paths if p.exists()]

        # 5. 버전 및 표시 파일명 갱신 + 검증된 배포 URL 자동 고정(Pinning)
        # (.zip 아카이브 이름으로 mod["name"]이 덮어써져 카탈로그/매니페스트 매칭이 끊기지 않도록 실제 설치된 대표 모드 파일명을 유지)
        original_local_name = selected_file_path.name if selected_file_path else mod.get("name", "")
        if overwrite_mode == "single" and installed_names:
            mod["name"] = installed_names[0]
        elif installed_names:
            matched_orig = next(
                (fn for fn in installed_names if fn.lower() == original_local_name.lower()),
                None,
            )
            if matched_orig:
                mod["name"] = matched_orig
            else:
                try:
                    from src.scanner import ModScanner
                    rep_path = ModScanner._select_primary_file([target_dir / fn for fn in installed_names])
                    mod["name"] = rep_path.name
                except Exception:
                    mod["name"] = installed_names[0]
        elif update_info.get("detected_filename") and str(update_info["detected_filename"]).lower().endswith((".package", ".ts4script")):
            mod["name"] = update_info["detected_filename"]
        raw_pin_ver = str(update_info.get("latest_version") or "").strip()
        if not raw_pin_ver or any(k in raw_pin_ver for k in ("최신 배포본", "확인 불가", "수동 확인")):
            try:
                from src.finder import check_known_catalog
                cat_pin = check_known_catalog(mod.get("name") or "") or check_known_catalog(original_local_name)
                if cat_pin and cat_pin.get("version"):
                    raw_pin_ver = str(cat_pin["version"]).strip()
            except Exception:
                pass
        mod["current_version"] = raw_pin_ver

        verified_page = (
            update_info.get("page_url")
            or mod.get("homepage")
            or update_info.get("download_url")
            or ""
        ).strip()
        if verified_page and installed_names:
            names_to_pin: List[str] = []
            for cand_pin in [original_local_name] + list(installed_names):
                c_clean = (cand_pin or "").strip()
                if (
                    c_clean
                    and c_clean.lower().endswith((".package", ".ts4script"))
                    and all(c_clean.lower() != existing.lower() for existing in names_to_pin)
                ):
                    names_to_pin.append(c_clean)
            if not names_to_pin and original_local_name:
                names_to_pin.append(original_local_name)
            pin_asset_name = str(update_info.get("asset_name") or "").strip()
            for pin_fn in names_to_pin:
                self.pin_verified_url(
                    mod,
                    verified_page,
                    mod["current_version"],
                    local_file_name=pin_fn,
                    asset_name=pin_asset_name,
                )

        return installed_names
