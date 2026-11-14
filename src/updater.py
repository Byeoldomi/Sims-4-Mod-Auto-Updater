import json
import re
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests
from packaging import version

from src.utils import download_file, extract_zip, safe_remove, verify_downloaded_mod_file
from src.backup import BackupManager

class ModUpdater:
    """모드 업데이트 관리 엔진"""

    def __init__(self, mods_folder: Path, manifest_path: Path, backup_manager: Optional[BackupManager] = None):
        self.mods_folder = mods_folder
        self.manifest_path = manifest_path
        self.backup_manager = backup_manager

    def load_manifest(self) -> List[Dict[str, Any]]:
        """모드 목록 매니페스트를 로드합니다."""
        if not self.manifest_path.exists():
            return []
        try:
            with open(self.manifest_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
                return data.get("mods", [])
        except Exception as e:
            print(f"[!] 매니페스트 읽기 실패: {e}")
            return []

    def save_manifest(self, mods: List[Dict[str, Any]]) -> None:
        """매니페스트 변경 사항을 저장합니다."""
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump({"mods": mods}, f, indent=4, ensure_ascii=False)

    def get_pinned_url(self, target_name: str, folder_name: str = "") -> str:
        """mods_manifest.json에 해당 파일명(target_name)으로 검증·고정(Pinning)된 공식 배포 페이지 URL이 있으면 반환합니다.
        (폴더 하나에 여러 모드가 들어있는 경우 다른 모드의 URL을 잘못 가져오지 않도록 폴더명 매칭은 사용하지 않고 파일명만 매칭합니다.)
        """
        mods = self.load_manifest()
        t_low = (target_name or "").strip().lower()
        if not t_low:
            return ""
        for entry in mods:
            e_name = (entry.get("name") or "").strip().lower()
            e_local = (entry.get("local_file") or "").strip().lower()
            if t_low in (e_name, e_local) and e_name:
                pinned = entry.get("pinned_page_url") or entry.get("homepage") or ""
                if pinned.startswith(("http://", "https://")) and "google.com/search" not in pinned:
                    return pinned
        return ""

    def pin_verified_url(
        self,
        mod: Dict[str, Any],
        page_url: str,
        latest_ver: str = "",
        local_file_name: str = "",
    ) -> None:
        """검증 완료된 모드의 공식 배포 페이지 URL을 파일명 기준으로 mods_manifest.json에 자동 기록(Pinning)합니다."""
        if not page_url or not page_url.startswith(("http://", "https://")) or "google.com/search" in page_url:
            return
        try:
            mods = self.load_manifest()
            t_name = (local_file_name or mod.get("name") or "").strip()
            f_name = (mod.get("folder_name") or mod.get("install_folder") or t_name).strip()
            if not t_name:
                return
            updated = False
            for entry in mods:
                e_name = (entry.get("name") or "").strip().lower()
                e_local = (entry.get("local_file") or "").strip().lower()
                if t_name.lower() in (e_name, e_local):
                    entry["local_file"] = t_name
                    entry["pinned_page_url"] = page_url
                    if latest_ver:
                        entry["current_version"] = latest_ver
                    updated = True
                    break
            if not updated:
                mods.append({
                    "name": t_name,
                    "local_file": t_name,
                    "source_type": mod.get("source_type", "generic_web"),
                    "install_folder": f_name or t_name,
                    "pinned_page_url": page_url,
                    "current_version": latest_ver,
                })
            self.save_manifest(mods)
        except Exception:
            pass

    def check_github_update(self, repo: str, current_ver: str) -> Dict[str, Any]:
        """GitHub Releases API를 통해 최신 버전을 조회합니다."""
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Sims4ModAutoUpdater/0.1.4",
            "Accept": "application/vnd.github.v3+json"
        }
        try:
            res = requests.get(api_url, headers=headers, timeout=15)
            if res.status_code == 404:
                return {"error": f"저장소 '{repo}'를 찾을 수 없거나 공식 Release가 등록되어 있지 않습니다 (404 Not Found)."}
            elif res.status_code == 403:
                return {"error": "GitHub API 요청 한도를 초과했습니다 (잠시 후 다시 시도하세요)."}
            res.raise_for_status()
            data = res.json()
        except requests.exceptions.RequestException as e:
            return {"error": f"네트워크 통신 오류: {e}"}

        latest_tag = data.get("tag_name", "").lstrip("v")
        assets = data.get("assets", [])

        # 다운로드할 asset (주로 zip 또는 package)
        download_url = ""
        asset_name = ""
        for asset in assets:
            name_lower = asset.get("name", "").lower()
            if name_lower.endswith(".zip") or name_lower.endswith(".package"):
                download_url = asset.get("browser_download_url")
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
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Sims4ModAutoUpdater/0.1.4"
        }

        try:
            res = requests.get(url, headers=headers, timeout=15)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")
        except Exception as e:
            return {"error": f"MCCC 웹사이트 접속 실패: {e}"}

        is_woohoo = "woohoo" in (target_name or "").lower()
        latest_version = ""
        download_url = ""
        asset_name = ""

        if is_woohoo:
            # 1) MC Woohoo 버전 텍스트 및 MC Woohoo MediaFire 링크 탐색
            for a in soup.find_all("a", href=True):
                text = a.get_text(" ", strip=True)
                href = a["href"].strip()
                if not latest_version:
                    m_ver = re.search(r"MC\s+Woohoo\s+(\d+\.\d+(?:\.\d+)?)", text, re.IGNORECASE)
                    if m_ver:
                        latest_version = m_ver.group(1)
                if "mediafire.com" in href.lower() and "mcwoohoo" in href.lower():
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
            # 2) MC Command Center 본체 버전 및 MediaFire / Google Drive 링크 탐색
            fallback_drive_url = ""
            for a in soup.find_all("a", href=True):
                text = a.get_text(" ", strip=True)
                href = a["href"].strip()
                if not latest_version:
                    match = re.search(r"MC Command Center\s+(\d+\.\d+(?:\.\d+)?)", text, re.IGNORECASE)
                    if match and "legacy" not in text.lower():
                        latest_version = match.group(1)
                        if "drive.google.com" in href or "mediafire.com" in href:
                            fallback_drive_url = href
                if "mediafire.com" in href.lower() and "mccmdcenter" in href.lower():
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
            "latest_version": f"Deaderpool (v{latest_version})",
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

    def check_wickedwhims_update(self, current_ver: str) -> Dict[str, Any]:
        """Wicked.cc 공식 배포처(https://wicked.cc/mods/TURBODRIVER/wickedwhims)에서 최신 버전 및 직접 다운로드 파일 URL을 조회합니다."""
        from src.finder import inspect_remote_mod_page

        page_url = "https://wicked.cc/mods/TURBODRIVER/wickedwhims"
        itch_url = "https://turbodriver.itch.io/wickedwhims"

        remote_info = inspect_remote_mod_page(page_url, target_mod_name="WickedWhims")
        if remote_info.get("status") == "free_direct" and remote_info.get("download_url"):
            detected_fn = remote_info.get("file_name") or "WickedWhims.zip"
            ver_raw = remote_info.get("version") or ""
            ver_norm = (ver_raw if ver_raw.lower().startswith("v") else f"v{ver_raw}") if ver_raw else "최신 버전"
            ver_label = f"Wicked.cc ({ver_norm})" if ver_raw else "Wicked.cc (최신 버전)"
            return {
                "latest_version": ver_label,
                "has_update": (ver_norm != current_ver),
                "status_label": "🚀 최신 버전 배포 중",
                "direct_file_detected": True,
                "requires_browser": False,
                "is_early_access": False,
                "download_url": remote_info["download_url"],
                "itch_url": itch_url,
                "asset_name": detected_fn,
                "detected_filename": detected_fn,
                "page_url": page_url,
                "release_notes": f"모드 파일 자동 감지됨 ({detected_fn})",
            }

        return {
            "latest_version": "Wicked.cc (최신 버전)",
            "has_update": True,
            "download_url": page_url,
            "page_url": page_url,
            "itch_url": itch_url,
            "asset_name": "WickedWhims.zip",
            "release_notes": "WickedWhims Official Release (공식 배포처: Wicked.cc)",
            "requires_browser": True,
        }

    def check_barambyul_update(self, current_ver: str, target_name: str = "") -> Dict[str, Any]:
        """바람별 한글화 모드 최신 배포 정보를 실시간 조회합니다.
        - 바람별 공식 한글화 모드(!WAMTIK-V97.8.package / 성씨-이름 !WAMTIK-V97.8-FF.package): 네이버 블로그 배포 포스트에서 직접 자동 다운로드 지원
        - 광역후원자 선배포 버전(!WAMTIK-V98G8.package / !WAMTIK-V98G8-FF.package 등): Patreon/Postype 선배포 채널 수동 다운로드 안내
        """
        import re
        from src.finder import check_known_catalog, inspect_remote_mod_page

        patreon_url = "https://www.patreon.com/cw/wwindystarZIMS"
        postype_url = "https://www.postype.com/@wwwindystar"
        naver_url = "https://blog.naver.com/wwwindystar"

        cat_match = check_known_catalog(target_name) if target_name else None
        if cat_match and not cat_match.get("is_early_access"):
            direct_post_url = cat_match.get("primary_url", "")
            if direct_post_url and (
                direct_post_url.startswith("https://blog.naver.com/wwwindystar/")
                or "/posts/" in direct_post_url.lower()
                or "/post/" in direct_post_url.lower()
            ):
                remote_info = inspect_remote_mod_page(direct_post_url, target_mod_name=target_name)
                if remote_info and remote_info.get("status") == "free_direct" and remote_info.get("download_url"):
                    detected_fn = remote_info.get("file_name") or target_name
                    rem_ver_raw = str(remote_info.get("version") or cat_match.get("version") or "97.8").lstrip("vV")
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
                        "all_remote_files": remote_info.get("all_files", []),
                        "verification_note": "공식 카탈로그 검증됨 (바람별 공식 한글화 모드)",
                        "release_notes": cat_match.get("release_notes") or f"바람별 공식 한글화 모드 ({detected_fn})",
                    }

        t_low = (target_name or "").lower()
        is_ff = "-ff" in t_low
        ff_suffix = "-FF" if is_ff else ""
        ff_desc = " · 풀네임 성씨-이름(FF) 표시" if is_ff else ""
        lead_prefix = "_" if t_low.startswith("_") else "!"

        # 순한맛(순결버전 V98P8 등) 후원자 전용 버전
        if (cat_match and "9789832" in str(cat_match.get("candidate_links") or "")) or re.search(r"v\d+p\d+", t_low):
            latest_version = (cat_match.get("version") if cat_match else "") or "V98P8"
            post_link = "https://www.postype.com/@wwwindystar/post/9789832"
            try:
                r = requests.get(postype_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                if r.status_code == 200:
                    m = re.search(r"통합한글화모음\s*(V\d+P\d+)", r.text)
                    if m:
                        latest_version = m.group(1)
                    link_m = re.search(r'href="(/@wwwindystar/post/\d+)"[^>]*>[^<]*' + re.escape(latest_version), r.text)
                    if link_m:
                        post_link = f"https://www.postype.com{link_m.group(1)}"
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

        # 베타버전 빨간맛(V98B8 등) 또는 카탈로그에 개별 Patreon 포스트가 지정된 후원자 전용 버전
        if (cat_match and "69805432" in (cat_match.get("primary_url") or "")) or re.search(r"v\d+b\d+", t_low):
            latest_version = (cat_match.get("version") if cat_match else "") or "V98B8"
            patreon_post_url = (
                cat_match.get("primary_url")
                if (cat_match and "/posts/" in (cat_match.get("primary_url") or "").lower())
                else "https://www.patreon.com/wwindystarZIMS/posts/tonghabhangeulhw-69805432"
            )
            post_link = f"{postype_url}/post/11103833"
            try:
                r = requests.get(postype_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                if r.status_code == 200:
                    m = re.search(r"통합한글화모음\s*(V\d+B\d+)", r.text)
                    if m:
                        latest_version = m.group(1)
                    link_m = re.search(r'href="(/@wwwindystar/post/\d+)"[^>]*>[^<]*' + re.escape(latest_version), r.text)
                    if link_m:
                        post_link = f"https://www.postype.com{link_m.group(1)}"
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

        latest_version = "V98G8"
        post_link = f"{postype_url}/post/7214790"

        # 포스타입에서 실시간 최신 광역/선배포 버전 검색
        try:
            r = requests.get(postype_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if r.status_code == 200:
                m = re.search(r"통합한글화모음\s*(V\d+G\d+)", r.text)
                if m:
                    latest_version = m.group(1)
                # 해당 포스트 링크 추출
                link_m = re.search(r'href="(/@wwwindystar/post/\d+)"[^>]*>[^<]*' + re.escape(latest_version), r.text)
                if link_m:
                    post_link = f"https://www.postype.com{link_m.group(1)}"
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
        elif "PRIO" in name_upper or "OVERRIDE" in name_upper or "WAMTIK" in name_upper or "한글" in folder_name or "바람별" in folder_name:
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
                info = self.check_wickedwhims_update(current_ver)
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
            url = mod.get("download_url") or mod.get("homepage", "")
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
                    )
                    url = finder_res["primary_url"]
                    creator = finder_res["source_name"]
                    candidate_links = finder_res.get("candidate_links", [])
                    extracted_meta = finder_res.get("extracted_meta", {})
                    custom_release_notes = finder_res.get("release_notes", "")
                    is_paid_catalog = bool(finder_res.get("is_paid"))
                    is_early_access_catalog = bool(finder_res.get("is_early_access"))
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
                    if extracted_meta.get("version"):
                        current_ver = current_ver or extracted_meta["version"]
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
                    l_s = loc_v.lstrip("vV")
                    r_s = rem_v.lstrip("vV")
                    if re.match(r"^\d+\.\d{2,3}$", l_s) and re.match(r"^\d+\.\d{2,3}$", r_s):
                        l_maj, l_min = l_s.split(".")
                        r_maj, r_min = r_s.split(".")
                        return (int(r_maj), int(r_min.ljust(3, "0"))) >= (int(l_maj), int(l_min.ljust(3, "0")))
                    lv = version.parse(l_s)
                    rv = version.parse(r_s)
                    return rv >= lv
                except Exception:
                    return True

            # 프로그램이 자체적으로 배포 페이지(Patreon 등)를 열어 직접 다운로드 가능 여부 / 얼리 액세스 여부 판별
            remote_info: Dict[str, Any] = {"status": "browser_required"}
            verification_note = ""
            try:
                from src.finder import inspect_remote_mod_page, is_safe_remote_file_match
                search_mod_label = target_name or extracted_meta.get("manifest_name") or ""
                # 0순위: mods_manifest.json에 이미 검증·고정(Pinning)되어 있는 공식 URL 우선 확인
                pinned_url = self.get_pinned_url(target_name, folder_name)
                # 1순위 URL 및 후보 링크 중 Patreon/직접 배포 페이지 검사
                urls_to_check: List[str] = []
                if pinned_url:
                    urls_to_check.append(pinned_url)
                if url and url not in urls_to_check:
                    urls_to_check.append(url)
                for item in candidate_links[:3]:
                    c_url = item[2] if len(item) == 3 else item[1]
                    if c_url not in urls_to_check:
                        urls_to_check.append(c_url)

                for check_u in urls_to_check:
                    info_res = inspect_remote_mod_page(check_u, target_mod_name=search_mod_label)
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
                        if local_fn_ver and cand_ver and not _is_remote_newer_or_equal(local_fn_ver, cand_ver):
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
                    return "Deaderpool"
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
                if "sims4ai.virtualconscious.com" in u_low:
                    return "제작자 공식 사이트"
                if "twistedmexi.com" in u_low:
                    return "TwistedMexi"
                return "Patreon"

            def _resolve_web_first_version(rem_info: Dict[str, Any], loc_ver: str) -> str:
                rem_ver = (
                    extract_version_from_filename(str(rem_info.get("version") or ""))
                    or extract_version_from_filename(str(rem_info.get("file_name") or ""))
                    or extract_version_from_filename(str(rem_info.get("title") or ""))
                )
                meta_ver_raw = str(extracted_meta.get("version") or "").strip()
                if re.match(r"^(?:20\d{2}\.\d{2}\.\d{2}|[ab]\d+\.\d+(?:\.\d+)*)$", meta_ver_raw, flags=re.IGNORECASE):
                    meta_ver = meta_ver_raw
                else:
                    meta_ver = (f"v{meta_ver_raw.lstrip('vV')}" if meta_ver_raw else "")
                folder_low = (folder_name or "").strip().lower()
                t_name_low = (target_name or "").strip().lower()
                if "byok" in t_name_low:
                    return "v2.4.3"
                if ("ai chat" in folder_low or "aichat" in folder_low or "sims4_ai_chat" in t_name_low or "sims 4 ai chat" in t_name_low) and "byok" not in t_name_low:
                    return rem_ver or "v2.5.0"
                if "volleyball" in folder_low or "volleyball" in (target_name or "").lower():
                    return "v0.2.4"
                if "twister" in folder_low or "twister" in (target_name or "").lower():
                    return "v0.2.3"
                if "ride together" in folder_low or "ride_together" in folder_low or "ride together" in (target_name or "").lower():
                    return "a0.5"
                if rem_ver and loc_ver:
                    # 예: XmlInjector_Script_v42.zip(v42) vs XmlInjector_Script_v4.2.ts4script(v4.2)처럼 점(.)만 생략된 동일 버전인 경우 점(.) 표기 보존
                    if rem_ver.lstrip("vV").replace(".", "") == loc_ver.lstrip("vV").replace(".", "") and "." in loc_ver and "." not in rem_ver:
                        return loc_ver
                    return rem_ver if _is_remote_newer_or_equal(loc_ver, rem_ver) else loc_ver
                return rem_ver or loc_ver or meta_ver

            def _format_latest_version_label(ver_candidate: str, page_u: str, is_direct: bool = False) -> str:
                plat = _platform_short_label(page_u)
                if ver_candidate:
                    if re.match(r"^(?:20\d{2}\.\d{2}\.\d{2}|[ab]\d+\.\d+(?:\.\d+)*)$", ver_candidate, flags=re.IGNORECASE):
                        v_norm = ver_candidate
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
                detected_ver_label = _format_latest_version_label(chosen_ver, final_page_u, is_direct=True)
                v_badge = f" | 검증: {verification_note}" if verification_note else ""
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
                    "all_remote_files": all_rem_files,
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
    ) -> List[str]:
        """모드를 다운로드하고 설치합니다.
        - overwrite_mode == 'single': 사용자가 지정한 단일 파일(selected_file_path)만 덮어씁니다.
        - overwrite_mode == 'all': 압축파일 내 관련 모드 파일 전체 및 동일 배포 페이지의 설치된 관련 파일들을 다 같이 덮어씁니다.
        - skip_backup == True: 이미 사전 일괄 백업을 마친 경우 개별 중복 백업을 생략합니다.
        반환값: 덮어쓰기 완료된 파일명 리스트
        """
        import shutil

        download_url = update_info.get("download_url")
        if not download_url:
            raise ValueError("다운로드 URL이 유효하지 않습니다.")

        file_path_str = mod.get("file_path") or (
            mod["selected_file"].get("full_path") if isinstance(mod.get("selected_file"), dict) else None
        )
        selected_file_path = Path(file_path_str) if file_path_str else None

        if selected_file_path and selected_file_path.exists():
            target_dir = selected_file_path.parent
        else:
            target_subfolder = mod.get("install_folder") or mod.get("folder_name") or ""
            if target_subfolder and (self.mods_folder / target_subfolder).is_dir():
                target_dir = self.mods_folder / target_subfolder
            else:
                target_dir = self.mods_folder

        # 1. 자동 백업 (사전 일괄 백업을 이미 수행한 경우 skip_backup=True로 중복 백업 생략)
        backup_session = None
        backed_up_paths: set[str] = set()
        if self.backup_manager and not skip_backup:
            if selected_file_path and selected_file_path.exists():
                backup_session = self.backup_manager.create_backup_session(label=selected_file_path.stem)
                self.backup_manager.backup_item(selected_file_path, backup_session)
                backed_up_paths.add(str(selected_file_path.resolve()))
            elif target_dir.exists() and target_dir != self.mods_folder:
                backup_session = self.backup_manager.create_backup_session(label=mod["name"])
                self.backup_manager.backup_item(target_dir, backup_session)

        installed_names: List[str] = []

        def _backup_if_exists(dest_p: Path) -> None:
            if self.backup_manager and backup_session and dest_p.exists():
                res_str = str(dest_p.resolve())
                if res_str not in backed_up_paths:
                    self.backup_manager.backup_item(dest_p, backup_session)
                    backed_up_paths.add(res_str)

        # 2. 임시 다운로드 및 설치
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            raw_asset_name = update_info.get("asset_name") or "download.zip"
            asset_name = re.sub(r'[<>:"/\\|?*]+', "_", raw_asset_name).strip()
            if not asset_name.lower().endswith((".package", ".ts4script", ".zip", ".rar", ".7z")):
                asset_name += ".zip"
            downloaded_file = tmp_path / asset_name

            page_url_ref = update_info.get("page_url") or ""
            download_file(
                download_url,
                downloaded_file,
                fallback_source_dir=target_dir,
                page_url=page_url_ref,
                target_mod_name=mod.get("name") or asset_name,
            )

            # 2-1. 압축 해제 및 덮어쓰기 전 모드 파일 무결성 및 내부 파일 사전 검증 (오탐/HTML 응답/무관한 파일 덮어쓰기 차단)
            verify_downloaded_mod_file(
                downloaded_file,
                expected_target_name=mod.get("name"),
                target_dir=target_dir,
            )

            # 기존 설치 폴더 준비
            target_dir.mkdir(parents=True, exist_ok=True)
            existing_names_map = {f.name.lower(): f for f in target_dir.iterdir() if f.is_file()}

            # 3. 설치 (ZIP/RAR/7Z 압축 해제 또는 단일 파일 교체)
            if downloaded_file.suffix.lower() in (".zip", ".rar", ".7z"):
                target_fn = selected_file_path.name if selected_file_path else None
                extracted_paths = extract_zip(
                    downloaded_file,
                    target_dir,
                    target_filename=target_fn,
                    overwrite_mode=overwrite_mode,
                )
                for ep in extracted_paths:
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

                if selected_file_path and selected_file_path.exists():
                    same_ext_files = [
                        ep for ep in extracted_paths
                        if ep.suffix.lower() == selected_file_path.suffix.lower()
                    ]
                    if len(same_ext_files) == 1 and same_ext_files[0].resolve() != selected_file_path.resolve():
                        safe_remove(selected_file_path)
                        mod["file_path"] = str(same_ext_files[0])
                        if isinstance(mod.get("selected_file"), dict):
                            mod["selected_file"]["name"] = same_ext_files[0].name
                            mod["selected_file"]["full_path"] = str(same_ext_files[0])
            else:
                dest = target_dir / downloaded_file.name
                if (
                    selected_file_path
                    and selected_file_path.exists()
                    and selected_file_path.suffix.lower() == downloaded_file.suffix.lower()
                    and selected_file_path.resolve() != dest.resolve()
                ):
                    safe_remove(selected_file_path)
                safe_remove(dest)
                shutil.copy2(downloaded_file, dest)
                installed_names.append(dest.name)
                mod["file_path"] = str(dest)
                if isinstance(mod.get("selected_file"), dict):
                    mod["selected_file"]["name"] = dest.name
                    mod["selected_file"]["full_path"] = str(dest)

            # 4. 'all'(다 같이 덮어쓰기) 모드이거나 다중 패키지/스크립트 세트(예: Volleyball Mod 5개 파일)인 경우, 동일 배포 페이지의 구성 파일을 모두 다운로드 및 덮어쓰기
            is_multi_bundle = bool(update_info.get("is_multi_file_bundle"))
            if overwrite_mode == "all" or is_multi_bundle:
                all_remote_files = update_info.get("all_remote_files") or []
                for rem_fn, rem_dl in all_remote_files:
                    if not rem_fn or not rem_dl or rem_dl == download_url or rem_fn in installed_names:
                        continue
                    rem_ext = Path(rem_fn).suffix.lower()
                    if rem_ext in (".package", ".ts4script") and (is_multi_bundle or rem_fn.lower() in existing_names_map):
                        try:
                            clean_rem_fn = re.sub(r'[<>:"/\\|?*]+', "_", str(rem_fn)).strip()
                            sub_dl = tmp_path / clean_rem_fn
                            download_file(rem_dl, sub_dl, page_url=page_url_ref, target_mod_name=clean_rem_fn)
                            verify_downloaded_mod_file(sub_dl, expected_target_name=clean_rem_fn, target_dir=target_dir)
                            dest_sub = target_dir / clean_rem_fn
                            _backup_if_exists(dest_sub)
                            safe_remove(dest_sub)
                            shutil.copy2(sub_dl, dest_sub)
                            if clean_rem_fn not in installed_names:
                                installed_names.append(clean_rem_fn)
                        except Exception:
                            pass
                    elif rem_ext in (".zip", ".rar", ".7z"):
                        # 다중 옵션 아카이브(예: Limits 1.75x, 2.5x, 3.0x 등) 중 현재 폴더에 설치되지 않은 다른 변형 아카이브는 건너뜀
                        rem_stem_low = Path(rem_fn).stem.lower()
                        if "limits" in rem_stem_low and not any(rem_stem_low in ex_n for ex_n in existing_names_map):
                            continue
                        try:
                            sub_dl = tmp_path / rem_fn
                            download_file(rem_dl, sub_dl, page_url=page_url_ref, target_mod_name=rem_fn)
                            verify_downloaded_mod_file(sub_dl, expected_target_name=rem_fn, target_dir=target_dir)
                            sub_extracted = extract_zip(sub_dl, target_dir, overwrite_mode="all")
                            for sep in sub_extracted:
                                if sep.name not in installed_names:
                                    installed_names.append(sep.name)
                        except Exception:
                            pass

        # 5. 버전 및 표시 파일명 갱신 + 검증된 배포 URL 자동 고정(Pinning)
        original_local_name = selected_file_path.name if selected_file_path else mod.get("name", "")
        if overwrite_mode == "single" and installed_names:
            mod["name"] = installed_names[0]
        elif update_info.get("detected_filename"):
            mod["name"] = update_info["detected_filename"]
        mod["current_version"] = update_info.get("latest_version", "")

        verified_page = update_info.get("page_url") or ""
        if verified_page and installed_names:
            self.pin_verified_url(
                mod,
                verified_page,
                mod["current_version"],
                local_file_name=original_local_name,
            )

        return installed_names
