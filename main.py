from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from packaging import version

# 실행 경로 및 PyInstaller 번들(_MEIPASS / _internal) 경로 처리
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent.resolve()
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR)).resolve()
else:
    BASE_DIR = Path(__file__).parent.resolve()
    BUNDLE_DIR = BASE_DIR

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(BUNDLE_DIR) not in sys.path:
    sys.path.insert(0, str(BUNDLE_DIR))

from src.backup import BackupManager
from src.config import ConfigManager, detect_sims4_mods_folder
from src.finder import (
    _is_library_catalog_mismatch,
    check_known_catalog,
    extract_mod_file_metadata,
    extract_version_from_filename,
)
from src.scanner import ModScanner
from src.updater import ModUpdater
from src.utils import _get_shared_strict_ssl_context, is_safe_subpath, is_valid_https_url


def resolve_ui_entry() -> Path:
    """소스 실행 및 PyInstaller(onedir/onefile) 환경 모두에서 ui/index.html 경로를 탐색합니다."""
    candidates = [
        BASE_DIR / "ui" / "index.html",
        BUNDLE_DIR / "ui" / "index.html",
        BASE_DIR / "_internal" / "ui" / "index.html",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


class Sims4ModUpdaterAPI:
    """pywebview 프론트엔드(ui/app.js)와 Python 백엔드(src/*)를 연결하는 엔드포인트 클래스."""

    SCAN_CACHE_SCHEMA_VERSION = 34

    @staticmethod
    def _is_variant_installed(vc: Dict[str, Any], unit_names_low: set[str]) -> bool:
        fn_low = str(vc.get("file_name") or "").strip().lower()
        if not fn_low or not unit_names_low:
            return False
        if fn_low in unit_names_low:
            return True
        toks = [str(t).strip().lower() for t in (vc.get("match_tokens") or []) if str(t).strip()]
        if not toks:
            for auto_tok in ("withtimedecay", "notimedecay"):
                if auto_tok in fn_low:
                    toks.append(auto_tok)
        if toks:
            return any(all(tok in un for tok in toks) for un in unit_names_low)
        return False

    def __init__(self, base_dir: Path = BASE_DIR) -> None:
        self.base_dir = base_dir.resolve()
        self.config_manager = ConfigManager(self.base_dir / "config.json")
        self._window: Optional[Any] = None
        self._cache_lock = threading.Lock()
        self._progress_lock = threading.Lock()
        self._last_progress_emit = 0.0
        self._scan_seq = 0
        self._mod_cache: Dict[str, Dict[str, Any]] = {}
        threading.Thread(
            target=self._warmup_ssl_context,
            name="ssl-warmup",
            daemon=True,
        ).start()

    @staticmethod
    def _warmup_ssl_context() -> None:
        """앱 시작 직후 백그라운드에서 공유 SSLContext를 선행 초기화해 첫 스캔 지연을 방지합니다."""
        try:
            _get_shared_strict_ssl_context()
        except Exception:
            pass

    def set_window(self, window: Any) -> None:
        """pywebview 윈도우 인스턴스를 주입합니다."""
        self._window = window

    # ------------------------------------------------------------------
    # 내부 헬퍼 메서드
    # ------------------------------------------------------------------
    def _resolve_mods_folder(self) -> Path:
        configured = self.config_manager.mods_folder
        if str(configured).strip() and configured.exists() and configured.is_dir():
            return configured.resolve()

        detected = detect_sims4_mods_folder()
        if detected and detected.exists():
            self.config_manager.config["mods_folder"] = str(detected)
            self.config_manager.save()
            return detected.resolve()

        return configured

    def _resolve_backup_dir(self) -> Path:
        backup_rel = self.config_manager.backup_folder
        if backup_rel.is_absolute():
            return backup_rel
        return (self.base_dir / backup_rel).resolve()

    def _resolve_manifest_path(self) -> Path:
        manifest_rel = self.config_manager.manifest_path
        if manifest_rel.is_absolute():
            return manifest_rel
        for candidate in (
            self.base_dir / manifest_rel,
            BUNDLE_DIR / manifest_rel,
        ):
            if candidate.exists():
                return candidate.resolve()
        return (self.base_dir / manifest_rel).resolve()

    def _resolve_scan_target(self, mods_folder: Path) -> Tuple[Path, str]:
        """설정된 하위 폴더(scan_subfolder)가 유효하면 (하위 폴더 Path, 상대 경로)를, 아니면 (전체 Mods, '')를 반환합니다."""
        raw_sub = self.config_manager.scan_subfolder
        if not raw_sub or not str(mods_folder).strip() or not mods_folder.exists():
            return mods_folder, ""
        try:
            mods_resolved = mods_folder.resolve()
            cand = (mods_resolved / raw_sub).resolve()
            if cand == mods_resolved:
                self.config_manager.set_scan_subfolder("")
                return mods_resolved, ""
            if cand.exists() and cand.is_dir() and is_safe_subpath(cand, mods_resolved, allow_equal=False):
                return cand, str(cand.relative_to(mods_resolved))
        except Exception:
            pass
        self.config_manager.set_scan_subfolder("")
        return mods_folder, ""

    def _resolve_scan_cache_path(self) -> Path:
        return (self.base_dir / "scan_cache.json").resolve()

    @classmethod
    def _json_safe(cls, obj: Any) -> Any:
        """Path, set, tuple 등 JSON 비호환 타입을 직렬화 가능한 형태로 안전하게 변환합니다."""
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, dict):
            return {str(k): cls._json_safe(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [cls._json_safe(v) for v in obj]
        return str(obj)

    def _clear_daily_scan_cache(self) -> None:
        """자정 경과 등으로 만료된 일일 스캔 캐시 파일을 삭제(초기화)합니다."""
        cache_path = self._resolve_scan_cache_path()
        try:
            if cache_path.exists():
                cache_path.unlink()
        except Exception:
            pass

    def _save_daily_scan_cache(
        self,
        mods_folder: Path,
        mods_list: List[Dict[str, Any]],
        summary: Dict[str, int],
        mod_cache: Dict[str, Dict[str, Any]],
        scan_subfolder: str = "",
    ) -> None:
        """당일(자정 전까지) 재사용할 모드 스캔 결과를 디스크(scan_cache.json)에 저장합니다."""
        cache_path = self._resolve_scan_cache_path()
        now = datetime.datetime.now()
        payload = {
            "schema_version": self.SCAN_CACHE_SCHEMA_VERSION,
            "scan_date": now.date().isoformat(),
            "scanned_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "mods_folder": str(mods_folder.resolve()),
            "scan_subfolder": str(scan_subfolder or ""),
            "rpo_channel": self.config_manager.rpo_channel,
            "ww_channel": self.config_manager.ww_channel,
            "mods": self._json_safe(mods_list),
            "summary": self._json_safe(summary),
            "mod_cache": self._json_safe(mod_cache),
        }
        tmp_path = cache_path.with_suffix(".json.tmp")
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, cache_path)
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass

    def _load_daily_scan_cache(
        self, mods_folder: Path, scan_subfolder: str = ""
    ) -> Optional[Dict[str, Any]]:
        """당일 스캔 캐시를 불러옵니다. 자정이 지나 날짜가 바뀌었으면 캐시를 초기화하고 None을 반환합니다."""
        cache_path = self._resolve_scan_cache_path()
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            self._clear_daily_scan_cache()
            return None

        if not isinstance(data, dict):
            self._clear_daily_scan_cache()
            return None

        if data.get("schema_version") != self.SCAN_CACHE_SCHEMA_VERSION:
            self._clear_daily_scan_cache()
            return None

        if data.get("rpo_channel") != self.config_manager.rpo_channel:
            self._clear_daily_scan_cache()
            return None

        if data.get("ww_channel", "free") != self.config_manager.ww_channel:
            self._clear_daily_scan_cache()
            return None

        if str(data.get("scan_subfolder") or "") != str(scan_subfolder or ""):
            return None

        today_str = datetime.date.today().isoformat()
        if data.get("scan_date") != today_str:
            # 자정이 지나 날짜가 변경되었으므로 캐시 초기화
            self._clear_daily_scan_cache()
            return None

        cached_folder_raw = str(data.get("mods_folder") or "").strip()
        if not cached_folder_raw:
            return None
        try:
            if Path(cached_folder_raw).resolve() != mods_folder.resolve():
                return None
        except Exception:
            return None

        mods_list = data.get("mods")
        mod_cache = data.get("mod_cache")
        if not isinstance(mods_list, list) or not isinstance(mod_cache, dict):
            self._clear_daily_scan_cache()
            return None

        summary = data.get("summary")
        if not isinstance(summary, dict):
            summary = self._summarize_mods(mods_list)

        with self._cache_lock:
            self._mod_cache = mod_cache

        return {
            "scan_date": today_str,
            "scanned_at": str(data.get("scanned_at") or today_str),
            "mods_folder": str(mods_folder.resolve()),
            "mods": mods_list,
            "summary": summary,
        }

    @staticmethod
    def _resolve_scope_display_label(mods_folder: Path, scan_sub: str = "") -> str:
        """현재 스캔 범위가 특정 하위 폴더이거나 기본 Mods 루트가 아닌 개별 지정 폴더일 때 표시용 폴더명을 반환합니다."""
        sub_clean = str(scan_sub or "").strip().strip("/\\")
        if sub_clean:
            return sub_clean
        folder_name = mods_folder.name.strip() if str(mods_folder).strip() else ""
        if folder_name and folder_name.lower() != "mods":
            return folder_name
        return ""

    def _emit_frontend_progress(
        self,
        completed: int,
        total: int,
        log_message: str,
        mode: str = "update",
        scan_seq: Optional[int] = None,
        scope_label: str = "",
    ) -> None:
        """스캔 또는 업데이트 진행 중 프론트엔드 진행률 바와 한 줄 로그를 실시간으로 갱신합니다."""
        if self._window is None:
            return
        if scan_seq is not None and scan_seq != self._scan_seq:
            return
        now = time.monotonic()
        is_edge = completed <= 1 or completed >= total
        with self._progress_lock:
            if not is_edge and (now - self._last_progress_emit) < 0.08:
                return
            self._last_progress_emit = now
        try:
            pct = int(round((completed / max(total, 1)) * 100))
            payload = json.dumps(
                {
                    "mode": mode,
                    "completed": completed,
                    "total": total,
                    "percent": pct,
                    "message": log_message,
                    "scopeLabel": scope_label,
                },
                ensure_ascii=False,
            )
            self._window.evaluate_js(
                f"window.Sims4UpdaterUI && window.Sims4UpdaterUI.onBackendProgress && "
                f"window.Sims4UpdaterUI.onBackendProgress({payload});"
            )
        except Exception:
            pass

    @staticmethod
    def _is_conflict_check_eligible_file(path: Path) -> bool:
        """충돌/중복 검사 대상인지 판별합니다.
        일반 CC(.package) 오탐지를 막기 위해 스크립트(.ts4script) 또는 카탈로그에 등록된 기능성/게임플레이 모드 파일만 허용합니다.
        """
        ext = path.suffix.lower()
        if ext == ".ts4script":
            return True
        if ext == ".package":
            return bool(check_known_catalog(path.name))
        return False

    @classmethod
    def _detect_duplicate_map_from_units(
        cls,
        units: List[Dict[str, Any]],
    ) -> Dict[str, List[str]]:
        """이미 스캔된 모드 유닛들의 파일 목록에서 중복(.ts4script 또는 카탈로그 등록 .package) 파일명과 경로를 고속 추출합니다."""
        grouped: Dict[str, List[str]] = {}
        for unit in units:
            for f_str in unit.get("unit_files", []):
                p = Path(f_str)
                if not cls._is_conflict_check_eligible_file(p):
                    continue
                key = p.name.lower()
                norm_str = str(p)
                existing = grouped.setdefault(key, [])
                if norm_str not in existing:
                    existing.append(norm_str)

        return {
            fname: paths for fname, paths in grouped.items() if len(paths) > 1
        }

    @staticmethod
    def _unwrap_platform_version(ver_str: str) -> str:
        """플랫폼 라벨 바깥 괄호(예: '디시인사이드 (v2.5.5 (핫픽스))')를 안전하게 벗겨 내부 버전 문자열을 추출합니다."""
        s = (ver_str or "").strip()
        if not s:
            return ""
        if re.match(r"^(?:[vV]\s*\d|\d|[abAB]\d|[vV]\d+(?:\.\d+)?[gGbBpPrR]\d*)", s):
            return s
        paren = re.search(r"\((.+)\)\s*$", s)
        return paren.group(1).strip() if paren else s

    @staticmethod
    def _to_comparable_version_str(tok: str) -> str:
        """'(핫픽스)' 접미사 및 선행 알파/베타 접두사('a0.5', 'b1.0')를 PEP 440 비교 가능 문자열로 변환합니다."""
        s = re.sub(
            r"\s*\(핫픽스(?:\s*(\d+))?\)",
            lambda m: f".post{m.group(1) or '1'}",
            (tok or "").strip(),
        )
        m_ab = re.match(r"^([abAB])(\d+(?:\.\d+)*)(.*)$", s)
        if m_ab:
            s = f"{m_ab.group(2)}{m_ab.group(1).lower()}0{m_ab.group(3)}"
        return s

    @staticmethod
    def _is_hotfix_subversion_of(base_tok: str, cand_tok: str) -> bool:
        """cand_tok가 base_tok의 핫픽스 하위 버전인지 판별합니다."""
        b_low = (base_tok or "").strip().lstrip("vV").lower()
        c_low = (cand_tok or "").strip().lstrip("vV").lower()
        if not b_low or not c_low:
            return False
        return c_low.startswith(f"{b_low}.") or c_low.startswith(f"{b_low} (핫픽스")

    @classmethod
    def _normalize_version_token(cls, ver_str: str) -> str:
        s = (ver_str or "").strip()
        if not s or s in ("확인 불가", "수동 확인 필요", "-"):
            return ""
        s = cls._unwrap_platform_version(s)
        if any(k in s for k in ("최신", "유료", "선배포", "확인", "링크")):
            return ""
        return s.lstrip("vV").strip()

    @classmethod
    def _is_remote_strictly_newer(cls, local_ver: str, remote_ver: str) -> Optional[bool]:
        """원격 버전이 로컬 버전보다 명확히 최신인지 비교합니다."""
        loc_tok = cls._normalize_version_token(local_ver)
        rem_tok = cls._normalize_version_token(remote_ver)
        if not rem_tok:
            return None
        if not loc_tok:
            return True

        if loc_tok.replace(".", "").lower() == rem_tok.replace(".", "").lower():
            return False

        if loc_tok.lower() == rem_tok.lower():
            return False

        is_loc_date = bool(re.match(r"^20\d{2}\.\d{2}\.\d{2}$", loc_tok))
        is_rem_date = bool(re.match(r"^20\d{2}\.\d{2}\.\d{2}$", rem_tok))
        if is_loc_date != is_rem_date:
            return None

        try:
            return version.parse(cls._to_comparable_version_str(rem_tok)) > version.parse(
                cls._to_comparable_version_str(loc_tok)
            )
        except Exception:
            return rem_tok.lower() != loc_tok.lower()

    @classmethod
    def _is_explicit_version_token(cls, ver_str: str) -> bool:
        """날짜('YYYY.MM.DD') 형식이 아닌 명시적 버전 번호(예: v1.38, v1, v1.677, v2.0.12.0, v3.0.3, 2026.6.0, V98G8, a0.5 등)인지 판별합니다."""
        tok = cls._normalize_version_token(ver_str)
        if not tok:
            return False
        if re.match(r"^20\d{2}\.\d{2}\.\d{2}$", tok):
            return False
        return True

    @staticmethod
    def _format_display_version(ver_str: str) -> str:
        """버전 토큰을 UI 표시용 문자열로 포맷합니다 (예: 1.1 -> v1.1, a0.5 -> a0.5, 2026.08.09 -> 2026.08.09)."""
        tok = (ver_str or "").strip()
        if not tok:
            return ""
        if re.match(r"^V\d+(?:\.\d+)?[GBPR]\d*$", tok, flags=re.IGNORECASE):
            return tok.upper()
        if re.match(r"^[abAB]\d", tok):
            return tok[0].lower() + tok[1:]
        if re.match(r"^(?:[vV]|20\d{2}\.)", tok):
            return tok
        return f"v{tok}"

    @staticmethod
    def _build_manifest_version_map(updater: ModUpdater) -> Dict[str, Dict[str, Any]]:
        """mods_manifest.json에서 파일명(소문자) -> {'version', 'size', 'mtime', 'asset_name'} 매핑을 생성합니다."""
        ver_map: Dict[str, Dict[str, Any]] = {}
        try:
            for item in updater.load_manifest():
                pinned_u = str(item.get("pinned_page_url") or item.get("homepage") or "").strip().lower()
                item_fn_low = (
                    str(item.get("local_file") or item.get("name") or "").strip().lower()
                )
                if "xml-injector" in pinned_u and not (
                    "xml" in item_fn_low and "injector" in item_fn_low
                ):
                    continue
                cur_v = str(item.get("current_version") or "").strip()
                asset_n = str(item.get("installed_asset_name") or "").strip()
                raw_size = item.get("local_file_size")
                try:
                    file_size = int(raw_size) if raw_size is not None else 0
                except (TypeError, ValueError):
                    file_size = 0
                raw_mtime = item.get("local_file_mtime")
                try:
                    file_mtime = int(raw_mtime) if raw_mtime is not None else 0
                except (TypeError, ValueError):
                    file_mtime = 0
                if not cur_v and not (file_size > 0 and asset_n):
                    continue
                info = {"version": cur_v, "size": file_size, "mtime": file_mtime, "asset_name": asset_n}
                for key_field in ("local_file", "name"):
                    raw_k = str(item.get(key_field) or "").strip().lower()
                    if not raw_k:
                        continue
                    existing_info = ver_map.get(raw_k)
                    if (
                        existing_info is None
                        or info["size"] > 0
                        or existing_info.get("size", 0) == 0
                    ):
                        ver_map[raw_k] = info
        except Exception:
            pass
        return ver_map

    @staticmethod
    def _summarize_mods(mods_list: List[Dict[str, Any]]) -> Dict[str, int]:
        return {
            "total": len(mods_list),
            "update": sum(
                1 for m in mods_list if m["statusType"] in ("update", "outdated", "manual")
            ),
            "conflict": sum(
                1 for m in mods_list if m["statusType"] in ("error", "conflict")
            ),
            "latest": sum(1 for m in mods_list if m["statusType"] == "latest"),
        }

    def _build_mod_entry(
        self,
        idx: int,
        unit: Dict[str, Any],
        updater: ModUpdater,
        duplicate_map: Dict[str, List[str]],
        check_remote: bool = True,
        manifest_ver_map: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """ModScanner의 개별 모드 유닛(unit)을 프론트엔드 갤러리 카드 스키마로 변환합니다."""
        primary_file = (
            unit.get("primary_file_name")
            or unit.get("primary_file")
            or unit.get("name", "")
        )
        primary_path = unit.get("primary_file_path") or unit.get("file_path") or ""
        folder_name = unit.get("folder_name") or unit.get("install_folder") or ""
        mod_id = re.sub(
            r"[^a-zA-Z0-9_:-]+", "_", f"{idx}_{unit.get('group_key', primary_file)}"
        )

        # 1) 카탈로그 우선 조회 + 필요 시 바이너리 메타데이터 추출 (초기 로딩 속도 최적화)
        # 단, PRIO / MOD 등 다중 모드 공용 폴더인 경우 폴더명으로 카탈로그를 조회하면
        # 폴더 내 모든 파일이 '바람별' 등으로 잘못 매칭되므로 파일명으로만 우선 조회합니다.
        f_low_clean = folder_name.strip().lower()
        allow_folder_cat = f_low_clean not in (
            "prio", "overrides", "override", "mod", "mods", "gsm", "gm", "(mods 루트)"
        )
        rpo_channel = self.config_manager.rpo_channel
        ww_channel = self.config_manager.ww_channel
        folder_cat = (
            check_known_catalog(folder_name, rpo_channel=rpo_channel, ww_channel=ww_channel)
            if allow_folder_cat
            else None
        )
        if folder_cat and _is_library_catalog_mismatch(folder_cat.get("matched_catalog", ""), primary_file):
            folder_cat = None
        catalog_hit = (
            check_known_catalog(primary_file, rpo_channel=rpo_channel, ww_channel=ww_channel)
            or folder_cat
            or {}
        )
        is_rpo_collection = (
            catalog_hit.get("matched_catalog") == "Relationship & Pregnancy Overhaul (RPO Collection)"
        )
        is_wickedwhims_catalog = catalog_hit.get("matched_catalog") == "WickedWhims"
        fn_ver = (
            extract_version_from_filename(primary_file)
            or (extract_version_from_filename(folder_name) if allow_folder_cat else "")
            or ""
        )

        # mods_manifest.json에 저장된 설치 버전(업데이트 완료 후 기록됨) 반영
        # size가 기록되어 있으면 파일 크기/수정 시각 일치 시 채택하고, size 미기재 기존 레코드는 실제 파일 존재 시 채택
        manifest_ver_raw = ""
        manifest_fallback_raw = ""
        manifest_file_verified = False
        manifest_asset_name = ""
        if manifest_ver_map:
            candidate_files: List[Path] = []
            if primary_path:
                candidate_files.append(Path(primary_path))
            for uf in unit.get("unit_files", []):
                uf_p = Path(uf)
                if not primary_path or str(uf_p) != str(primary_path):
                    candidate_files.append(uf_p)
            for cf in candidate_files:
                cf_low = cf.name.lower()
                m_info = manifest_ver_map.get(cf_low)
                if not m_info:
                    continue
                if not manifest_fallback_raw:
                    manifest_fallback_raw = str(m_info.get("version") or "")
                try:
                    if not (cf.exists() and cf.is_file()):
                        continue
                    m_size = int(m_info.get("size") or 0)
                    m_mtime = int(m_info.get("mtime") or 0)
                    if m_size > 0:
                        st = cf.stat()
                        if st.st_size != m_size:
                            continue
                        if m_mtime > 0 and abs(int(st.st_mtime) - m_mtime) > 2:
                            continue
                        manifest_file_verified = True
                    manifest_ver_raw = str(m_info.get("version") or "")
                    manifest_asset_name = str(m_info.get("asset_name") or "")
                    break
                except OSError:
                    continue
        manifest_ver_tok = self._normalize_version_token(manifest_ver_raw)

        meta: Dict[str, Any] = {}
        if (
            not fn_ver
            or not catalog_hit.get("creator")
            or unit.get("is_ww_animation")
            or catalog_hit.get("is_ww_animation")
        ):
            meta = extract_mod_file_metadata(primary_path) if primary_path else {}

        if not catalog_hit and meta.get("is_ww_animation"):
            ww_anim_cat = (
                check_known_catalog(
                    primary_file,
                    rpo_channel=rpo_channel,
                    ww_channel=ww_channel,
                    is_ww_animation_hint=True,
                )
                or (
                    check_known_catalog(
                        meta.get("inferred_creator") or "",
                        rpo_channel=rpo_channel,
                        ww_channel=ww_channel,
                        is_ww_animation_hint=True,
                    )
                    if meta.get("inferred_creator")
                    else None
                )
            )
            if ww_anim_cat and ww_anim_cat.get("is_ww_animation"):
                catalog_hit = ww_anim_cat

        is_ww_animation = bool(
            unit.get("is_ww_animation")
            or catalog_hit.get("is_ww_animation")
            or meta.get("is_ww_animation")
        )

        bin_ver = str(meta.get("binary_version") or "").strip()
        explicit_local_ver = fn_ver or (self._format_display_version(bin_ver) if bin_ver else "")
        local_ver = explicit_local_ver
        manifest_promoted = False
        is_mtime_fallback = False
        if manifest_ver_tok:
            if not explicit_local_ver:
                local_ver = self._format_display_version(manifest_ver_tok)
                manifest_promoted = True
            elif self._is_remote_strictly_newer(explicit_local_ver, manifest_ver_tok) is True:
                bin_clean = bin_ver.lstrip("vV")
                allow_promote = (
                    manifest_file_verified
                    or not bin_clean
                    or self._is_hotfix_subversion_of(bin_clean, manifest_ver_tok)
                    or bool(re.match(r"^20\d{2}\.\d{2}\.\d{2}$", manifest_ver_tok))
                )
                if allow_promote:
                    local_ver = self._format_display_version(manifest_ver_tok)
                    manifest_promoted = True

        # 명시적 버전 번호(예: v1.38, v1, v1.677, v2.0.12.0, v3.0.3)가 존재할 경우 날짜로 대체하지 않음
        if not local_ver:
            ver_cands = (
                (meta.get("version"), manifest_fallback_raw)
                if ((is_rpo_collection and rpo_channel == "free") or (is_wickedwhims_catalog and ww_channel == "paid"))
                else (catalog_hit.get("version"), meta.get("version"), manifest_fallback_raw)
            )
            for cand_ver in ver_cands:
                if cand_ver and self._is_explicit_version_token(str(cand_ver)):
                    unwrapped_cand = self._unwrap_platform_version(str(cand_ver).strip())
                    if unwrapped_cand:
                        local_ver = self._format_display_version(unwrapped_cand)
                        break

        # 오직 명시적 버전 문자열이 비어 있거나 날짜 형식만 있는 버전 미표기 대상인 경우에만 파일 수정 날짜(mtime) 기준 적용
        cat_ver_tok = self._normalize_version_token(str(catalog_hit.get("version") or ""))
        cat_date_tok = cat_ver_tok if re.match(r"^20\d{2}\.\d{2}\.\d{2}$", cat_ver_tok) else ""
        raw_mtime_date = ""
        is_created_today = False
        today_str = datetime.date.today().strftime("%Y.%m.%d")
        if not local_ver:
            mtime_candidates: List[Path] = []
            if primary_path:
                mtime_candidates.append(Path(primary_path))
            for uf in unit.get("unit_files", []):
                uf_p = Path(uf)
                if not primary_path or str(uf_p) != str(primary_path):
                    mtime_candidates.append(uf_p)
            for mc in mtime_candidates:
                try:
                    if mc.exists() and mc.is_file():
                        st_mc = mc.stat()
                        raw_mtime_date = datetime.datetime.fromtimestamp(st_mc.st_mtime).strftime("%Y.%m.%d")
                        is_created_today = (
                            raw_mtime_date == today_str
                            and abs(st_mc.st_ctime - st_mc.st_mtime) <= 120
                        )
                        if cat_date_tok and raw_mtime_date > cat_date_tok:
                            local_ver = cat_date_tok
                        elif is_created_today and not cat_date_tok:
                            local_ver = ""
                        else:
                            local_ver = raw_mtime_date
                        is_mtime_fallback = True
                        break
                except OSError:
                    continue

        bracket_m = re.search(r"\[([^\]]+)\]", primary_file or "")
        bracket_creator = bracket_m.group(1).strip() if bracket_m else ""

        author = (
            catalog_hit.get("creator")
            or meta.get("inferred_creator")
            or bracket_creator
            or (
                "Deaderpool"
                if "mc_" in primary_file.lower() or "mccc" in folder_name.lower()
                else ""
            )
            or ("TURBODRIVER" if ("wicked" in primary_file.lower() and not is_ww_animation) else "")
            or "심즈4 크리에이터"
        )

        # 깔끔한 카드 타이틀 생성 (WW 애니메이션은 개별 팩 표시명/파일명을 우선 유지하여 다중 팩 구분 지원)
        anim_display_name = (
            meta["display_names"][0]
            if (is_ww_animation and meta.get("display_names"))
            else ""
        )
        if is_ww_animation:
            anim_stem = Path(primary_file).stem if primary_file else ""
            norm_anim_stem = re.sub(
                r"(?:^|[_\-\s]+)(?:ww|wickedwhims|wicked|animations?|anims?)(?:$|[_\-\s]+)",
                " ",
                anim_stem,
                flags=re.IGNORECASE,
            )
            norm_anim_stem = re.sub(r"[\[\]\(\)_\-\s]+", " ", norm_anim_stem).strip()
            creator_low = (author or "").strip().lower()
            has_specific_pack_stem = bool(
                anim_stem
                and norm_anim_stem
                and norm_anim_stem.lower() != creator_low
            )
            if catalog_hit.get("override_mod_title") and catalog_hit.get("mod_title"):
                clean_title = str(catalog_hit["mod_title"])
            else:
                clean_title = (
                    meta.get("manifest_name")
                    or anim_display_name
                    or (anim_stem if has_specific_pack_stem else "")
                    or catalog_hit.get("mod_title")
                    or catalog_hit.get("name")
                    or (anim_stem or folder_name)
                )
        else:
            clean_title = (
                catalog_hit.get("mod_title")
                or catalog_hit.get("name")
                or meta.get("manifest_name")
                or (Path(primary_file).stem if primary_file else folder_name)
            )
        if "mc_cmd_center" in clean_title.lower():
            clean_title = "MC Command Center (MCCC)"
        elif "wickedwhims" in clean_title.lower() and not is_ww_animation:
            clean_title = "WickedWhims"

        is_unreleased_mod = bool(catalog_hit.get("is_unreleased")) or bool(
            re.search(
                r"sulsul[\s_-]*ai",
                f"{primary_file} {folder_name} {clean_title}",
                flags=re.IGNORECASE,
            )
        )
        if is_unreleased_mod and "sulsul" in f"{primary_file} {folder_name} {clean_title}".lower():
            clean_title = "SulSul AI Mod"

        # 중복/충돌 경로 점검 (스크립트 또는 카탈로그 등록 기능성 모드 파일만 대상)
        conflict_paths: List[str] = []
        for uf in unit.get("unit_files", []):
            uf_path = Path(uf)
            if not self._is_conflict_check_eligible_file(uf_path):
                continue
            fname_low = uf_path.name.lower()
            if fname_low in duplicate_map:
                for p in duplicate_map[fname_low]:
                    if p not in conflict_paths:
                        conflict_paths.append(p)

        mod_cfg = ModUpdater.infer_mod_config(folder_name or primary_file)
        if primary_file:
            p_low = primary_file.lower()
            is_core_special = (
                (mod_cfg.get("source_type") == "mccc" and "mc_" in p_low)
                or (mod_cfg.get("source_type") == "wickedwhims" and "turbodriver_wickedwhims" in p_low)
                or (mod_cfg.get("source_type") == "barambyul" and "wamtik" in p_low)
            )
            if not is_core_special:
                mod_cfg["source_type"] = "generic_web"
                mod_cfg["download_url"] = ""
                mod_cfg["homepage"] = ""
        mod_cfg["name"] = primary_file or folder_name
        mod_cfg["file_path"] = primary_path
        mod_cfg["install_folder"] = unit.get("install_folder") or ""
        mod_cfg["current_version"] = local_ver.lstrip("vV") if local_ver else ""
        is_wickedwhims = is_wickedwhims_catalog or mod_cfg.get("source_type") == "wickedwhims"
        if is_rpo_collection:
            mod_cfg["rpo_channel"] = rpo_channel
        if is_wickedwhims:
            mod_cfg["ww_channel"] = ww_channel

        display_local_ver = local_ver or "버전 미표기"
        catalog_url = str(catalog_hit.get("primary_url") or "").strip()
        if catalog_url and not is_valid_https_url(catalog_url):
            catalog_url = ""

        # Phase 1: 로컬 빠른 스캔 (0.3초 내 즉시 반환)
        if not check_remote:
            if conflict_paths:
                status_type = "conflict"
                status_text = "충돌 / 중복"
                latest_label = "중복 감지"
            elif is_unreleased_mod:
                status_type = "latest"
                status_text = "미출시"
                latest_label = "미출시"
            else:
                status_type = "checking"
                status_text = "버전 확인 중"
                latest_label = "조회 대기..."

            cat_requires_modal = bool(catalog_hit.get("requires_option_modal"))
            cat_modal_mode = str(catalog_hit.get("option_modal_mode") or "")
            cat_modal_prompt = str(catalog_hit.get("option_modal_prompt") or "")
            p1_names_low = {Path(uf).name.lower() for uf in unit.get("unit_files", [])}
            if primary_file:
                p1_names_low.add(Path(primary_file).name.lower())
            cat_option_choices = [
                {
                    "file_name": str(vc.get("file_name") or ""),
                    "label": str(vc.get("label") or vc.get("file_name") or ""),
                    "description": str(vc.get("description") or ""),
                    "channel": str(vc.get("channel") or ""),
                    "match_tokens": list(vc.get("match_tokens") or []),
                    "installed": (
                        str(vc.get("channel") or "") == rpo_channel
                        if cat_modal_mode == "rpo_channel"
                        else (
                            str(vc.get("channel") or "") == ww_channel
                            if cat_modal_mode == "ww_channel"
                            else self._is_variant_installed(vc, p1_names_low)
                        )
                    ),
                }
                for vc in (catalog_hit.get("option_presets") or [])
                if isinstance(vc, dict) and vc.get("file_name")
            ]
            cat_selected_variant = ""
            if cat_modal_mode == "rpo_channel":
                cat_selected_variant = f"rpo_channel:{rpo_channel}"
            elif cat_modal_mode == "ww_channel":
                cat_selected_variant = f"ww_channel:{ww_channel}"
            elif cat_modal_mode == "multi_file_select":
                cat_selected_variant = "download_mode:all"
            elif cat_option_choices:
                p1_matched_vc = next(
                    (vc["file_name"] for vc in cat_option_choices if vc.get("installed")),
                    "",
                )
                cat_selected_variant = p1_matched_vc or cat_option_choices[0]["file_name"]

            cat_optional_addons = [
                {
                    "file_name": str(oa.get("file_name") or ""),
                    "label": str(oa.get("label") or oa.get("file_name") or ""),
                    "installed": str(oa.get("file_name") or "").strip().lower() in p1_names_low,
                }
                for oa in (catalog_hit.get("optional_addons") or [])
                if isinstance(oa, dict) and oa.get("file_name")
            ]
            cat_selected_addons = [oa["file_name"] for oa in cat_optional_addons if oa["installed"]]
            if cat_modal_mode == "multi_file_select" and not cat_selected_addons:
                cat_selected_addons = [oa["file_name"] for oa in cat_optional_addons]

            entry = {
                "id": mod_id,
                "name": clean_title,
                "author": author,
                "currentVersion": display_local_ver,
                "latestVersion": latest_label,
                "statusText": status_text,
                "statusType": status_type,
                "checked": False,
                "disabled": True,
                "pageUrl": catalog_url,
                "conflictPaths": conflict_paths,
                "folderName": folder_name,
                "primaryFile": primary_file,
                "variantChoices": cat_option_choices,
                "selectedVariant": cat_selected_variant,
                "optionalAddons": cat_optional_addons,
                "selectedAddons": cat_selected_addons,
                "requiresOptionModal": cat_requires_modal,
                "optionModalMode": cat_modal_mode,
                "optionModalPrompt": cat_modal_prompt,
                "rpoChannel": rpo_channel if is_rpo_collection else "",
                "wwChannel": ww_channel if is_wickedwhims else "",
                "isWwAnimation": is_ww_animation,
            }
            return mod_id, {
                "entry": entry,
                "unit": unit,
                "mod_cfg": mod_cfg,
                "update_info": {},
            }

        # Phase 2: 원격 최신 버전 조회 (병렬 워커에서 호출됨)
        try:
            update_info = updater.check_mod_update(mod_cfg)
        except Exception as exc:
            update_info = {"error": str(exc)}

        if (update_info.get("extracted_meta") or {}).get("is_ww_animation"):
            is_ww_animation = True

        if update_info.get("matched_creator"):
            author = str(update_info["matched_creator"])

        raw_latest = str(update_info.get("latest_version") or "").strip()
        latest_ver_clean = self._unwrap_platform_version(raw_latest)

        dl_url = str(update_info.get("download_url") or "").strip()
        is_free_member_gate = "#free_member_file=" in dl_url

        page_url = str(
            update_info.get("page_url")
            or update_info.get("post_link")
            or update_info.get("patreon_url")
            or update_info.get("postype_url")
            or update_info.get("itch_url")
            or (dl_url.split("#")[0] if is_free_member_gate else "")
            or (dl_url if update_info.get("requires_browser") else "")
            or catalog_url
            or ""
        ).strip()
        if page_url and not is_valid_https_url(page_url):
            page_url = ""

        requires_browser = bool(
            update_info.get("requires_browser")
            or update_info.get("is_early_access")
            or update_info.get("is_paid")
            or is_free_member_gate
        )
        direct_file = bool(
            update_info.get("direct_file_detected", not requires_browser)
            and dl_url
            and not requires_browser
            and not is_free_member_gate
        )
        remote_file_size = int(update_info.get("remote_file_size") or 0)
        asset_name = str(update_info.get("asset_name") or "").strip()
        binary_hotfix_mismatch = False
        local_fsize = 0
        if primary_path:
            try:
                loc_p = Path(primary_path)
                if loc_p.exists() and loc_p.is_file():
                    local_fsize = loc_p.stat().st_size
            except OSError:
                local_fsize = 0
        if (
            direct_file
            and remote_file_size > 0
            and asset_name.lower().endswith((".ts4script", ".package"))
            and not update_info.get("is_multi_file_bundle")
            and primary_path
        ):
            try:
                loc_p = Path(primary_path)
                if loc_p.exists() and loc_p.is_file() and loc_p.name.lower() == asset_name.lower():
                    loc_tok = self._normalize_version_token(local_ver)
                    rem_tok = self._normalize_version_token(latest_ver_clean)
                    if local_fsize == remote_file_size and rem_tok and (not loc_tok or is_mtime_fallback or self._is_hotfix_subversion_of(loc_tok, rem_tok)):
                        local_ver = self._format_display_version(rem_tok)
                        display_local_ver = local_ver
                    elif local_fsize != remote_file_size and manifest_promoted and bin_ver:
                        local_ver = self._format_display_version(bin_ver)
                        display_local_ver = local_ver
                    elif local_fsize != remote_file_size and loc_tok and rem_tok and loc_tok.lower() == rem_tok.lower() and "(핫픽스" in rem_tok:
                        binary_hotfix_mismatch = True
            except OSError:
                pass
        if is_mtime_fallback and raw_mtime_date:
            rem_date_tok = self._normalize_version_token(latest_ver_clean)
            if re.match(r"^20\d{2}\.\d{2}\.\d{2}$", rem_date_tok):
                if raw_mtime_date >= rem_date_tok:
                    local_ver = rem_date_tok
                elif cat_date_tok and cat_date_tok < rem_date_tok and raw_mtime_date > cat_date_tok:
                    local_ver = cat_date_tok
                else:
                    local_ver = raw_mtime_date
                display_local_ver = local_ver or "버전 미표기"
                mod_cfg["current_version"] = local_ver.lstrip("vV") if local_ver else ""
            elif is_created_today and not cat_date_tok:
                local_ver = ""
                display_local_ver = "버전 미표기"
                mod_cfg["current_version"] = ""
        newer_cmp = True if binary_hotfix_mismatch else self._is_remote_strictly_newer(local_ver, latest_ver_clean)

        if conflict_paths:
            status_type = "conflict"
            status_text = "충돌 / 중복"
            display_latest_ver = latest_ver_clean or "중복 감지"
            checked = False
            disabled = True
        elif is_unreleased_mod:
            status_type = "latest"
            status_text = "미출시"
            display_latest_ver = "미출시"
            checked = False
            disabled = True
            page_url = ""
        elif update_info.get("error") or update_info.get("link_not_found"):
            status_type = "error"
            status_text = "링크 오류"
            display_latest_ver = "확인 불가"
            checked = False
            disabled = True
        elif is_rpo_collection and rpo_channel == "early_access":
            if newer_cmp is False and local_ver:
                status_type = "latest"
                status_text = "최신버전"
                display_latest_ver = latest_ver_clean or display_local_ver
                checked = False
                disabled = False
            else:
                status_type = "manual"
                status_text = "수동 확인"
                display_latest_ver = latest_ver_clean or "v3"
                checked = False
                disabled = True
        elif is_wickedwhims and ww_channel == "paid":
            if newer_cmp is False and local_ver:
                status_type = "latest"
                status_text = "최신버전"
                display_latest_ver = latest_ver_clean or display_local_ver
                checked = False
                disabled = False
            else:
                status_type = "manual"
                status_text = "수동 확인"
                display_latest_ver = latest_ver_clean or "v187.18"
                checked = False
                disabled = True
        elif requires_browser:
            if newer_cmp is False and local_ver:
                status_type = "latest"
                status_text = "최신버전"
                display_latest_ver = latest_ver_clean or display_local_ver
                checked = False
                disabled = False
            else:
                status_type = "manual"
                status_text = "수동 확인"
                display_latest_ver = latest_ver_clean or "공식 페이지 확인"
                checked = False
                disabled = True
        elif direct_file:
            if newer_cmp is not None:
                is_updatable = bool(newer_cmp)
            else:
                same_verified_asset = (
                    manifest_file_verified
                    and (
                        not asset_name
                        or not manifest_asset_name
                        or manifest_asset_name.lower() == asset_name.lower()
                    )
                    and (remote_file_size <= 0 or local_fsize == remote_file_size)
                )
                is_updatable = False if same_verified_asset else bool(update_info.get("has_update"))
            if is_updatable:
                status_type = "update"
                status_text = "업데이트 가능"
                display_latest_ver = latest_ver_clean or "최신 배포본"
                checked = True
                disabled = False
            else:
                status_type = "latest"
                status_text = "최신버전"
                display_latest_ver = latest_ver_clean or display_local_ver
                checked = False
                disabled = False
        else:
            status_type = "latest"
            status_text = "최신버전"
            display_latest_ver = latest_ver_clean or display_local_ver
            checked = False
            disabled = False

        unit_names_low = {Path(uf).name.lower() for uf in unit.get("unit_files", [])}
        if primary_file:
            unit_names_low.add(Path(primary_file).name.lower())

        option_modal_mode = str(
            update_info.get("option_modal_mode") or catalog_hit.get("option_modal_mode") or ""
        )
        raw_variant_choices = update_info.get("variant_choices") or catalog_hit.get("option_presets") or []
        variant_choices = [
            {
                "file_name": str(vc.get("file_name") or ""),
                "label": str(vc.get("label") or vc.get("file_name") or ""),
                "description": str(vc.get("description") or ""),
                "channel": str(vc.get("channel") or ""),
                "match_tokens": list(vc.get("match_tokens") or []),
                "installed": (
                    str(vc.get("channel") or "") == rpo_channel
                    if option_modal_mode == "rpo_channel"
                    else (
                        str(vc.get("channel") or "") == ww_channel
                        if option_modal_mode == "ww_channel"
                        else self._is_variant_installed(vc, unit_names_low)
                    )
                ),
            }
            for vc in raw_variant_choices
            if isinstance(vc, dict) and vc.get("file_name")
        ]
        selected_variant = ""
        if option_modal_mode == "rpo_channel":
            selected_variant = f"rpo_channel:{rpo_channel}"
            update_info["selected_variant"] = selected_variant
        elif option_modal_mode == "ww_channel":
            selected_variant = f"ww_channel:{ww_channel}"
            update_info["selected_variant"] = selected_variant
        elif option_modal_mode == "multi_file_select":
            selected_variant = str(update_info.get("selected_variant") or "download_mode:all")
            update_info["selected_variant"] = selected_variant
        elif variant_choices:
            matched_vc = next(
                (vc["file_name"] for vc in variant_choices if vc.get("installed")),
                "",
            )
            selected_variant = matched_vc or variant_choices[0]["file_name"]
            update_info["selected_variant"] = selected_variant

        raw_optional_addons = update_info.get("optional_addons") or catalog_hit.get("optional_addons") or []
        optional_addons_entries = [
            {
                "file_name": str(oa.get("file_name") or ""),
                "label": str(oa.get("label") or oa.get("file_name") or ""),
                "installed": str(oa.get("file_name") or "").strip().lower() in unit_names_low,
            }
            for oa in raw_optional_addons
            if isinstance(oa, dict) and oa.get("file_name")
        ]
        selected_addons = [oa["file_name"] for oa in optional_addons_entries if oa["installed"]]
        if option_modal_mode == "multi_file_select" and not selected_addons:
            selected_addons = [oa["file_name"] for oa in optional_addons_entries]
        if optional_addons_entries:
            update_info["optional_addons"] = raw_optional_addons
            update_info["selected_addons"] = list(selected_addons)

        requires_option_modal = bool(
            update_info.get("requires_option_modal") or catalog_hit.get("requires_option_modal")
        )
        option_modal_prompt = str(
            update_info.get("option_modal_prompt") or catalog_hit.get("option_modal_prompt") or ""
        )

        entry = {
            "id": mod_id,
            "name": clean_title,
            "author": author,
            "currentVersion": display_local_ver,
            "latestVersion": display_latest_ver,
            "statusText": status_text,
            "statusType": status_type,
            "checked": checked,
            "disabled": disabled,
            "pageUrl": page_url,
            "conflictPaths": conflict_paths,
            "folderName": folder_name,
            "primaryFile": primary_file,
            "variantChoices": variant_choices,
            "selectedVariant": selected_variant,
            "optionalAddons": optional_addons_entries,
            "selectedAddons": selected_addons,
            "requiresOptionModal": requires_option_modal,
            "optionModalMode": option_modal_mode,
            "optionModalPrompt": option_modal_prompt,
            "rpoChannel": rpo_channel if is_rpo_collection else "",
            "wwChannel": ww_channel if is_wickedwhims else "",
            "isWwAnimation": is_ww_animation,
        }

        return mod_id, {
            "entry": entry,
            "unit": unit,
            "mod_cfg": mod_cfg,
            "update_info": update_info,
        }

    # ------------------------------------------------------------------
    # 프론트엔드 노출 엔드포인트 (pywebview JS API)
    # ------------------------------------------------------------------
    def get_initial_state(self) -> Dict[str, Any]:
        """[Endpoint 1] 당일 스캔 캐시가 유효하면 즉시 복원하고, 자정이 지났거나 캐시가 없으면 로컬 선스캔을 반환합니다."""
        mods_folder = self._resolve_mods_folder()
        scan_target, scan_sub = self._resolve_scan_target(mods_folder)
        scope_display = self._resolve_scope_display_label(mods_folder, scan_sub)
        if str(mods_folder).strip() and mods_folder.exists():
            cached = self._load_daily_scan_cache(mods_folder, scan_subfolder=scan_sub)
            if cached is not None:
                total_cnt = cached["summary"].get("total", len(cached["mods"]))
                update_cnt = cached["summary"].get("update", 0)
                scanned_time = cached["scanned_at"].split(" ")[-1][:5]
                scope_label = f" [지정 폴더: {scope_display}]" if scope_display else ""
                return {
                    "ok": True,
                    "cached": True,
                    "mods_folder": str(mods_folder),
                    "scan_subfolder": scan_sub,
                    "scan_target_path": str(scan_target),
                    "mods": cached["mods"],
                    "summary": cached["summary"],
                    "needs_remote_scan": False,
                    "message": (
                        f"오늘({scanned_time}) 스캔된 {total_cnt}개 데이터를 유지 중{scope_label} "
                        f"(업데이트/수동확인 {update_cnt}개 · 자정 이후 자동 초기화)"
                    ),
                }

        local_scan = self.scan_mods(check_remote=False)
        default_init_msg = (
            f"[{scope_display}] 지정 폴더 로컬 확인 완료! 원격 최신 버전을 조회합니다..."
            if scope_display
            else "로컬 모드 폴더 확인 완료! 원격 최신 버전을 조회합니다..."
        )
        return {
            "ok": local_scan.get("ok", True),
            "cached": False,
            "mods_folder": str(mods_folder),
            "scan_subfolder": local_scan.get("scan_subfolder", scan_sub),
            "scan_target_path": local_scan.get("scan_target_path", str(scan_target)),
            "mods": local_scan.get("mods", []),
            "summary": local_scan.get("summary", {}),
            "needs_remote_scan": len(local_scan.get("mods", [])) > 0,
            "message": local_scan.get("message", default_init_msg),
        }

    @staticmethod
    def _detect_mods_root_and_subfolder(
        selected_folder: Path, current_mods_folder: Optional[Path] = None
    ) -> Tuple[Path, str]:
        """선택한 경로가 심즈 4 'Mods' 폴더 내부의 하위 폴더(예: Mods/MOD WickedWhims/Animations)인 경우,
        상위 'Mods' 루트를 유지하면서 상대 하위 폴더 경로(scan_subfolder)로 자동 분리합니다.
        """
        sel_resolved = selected_folder.resolve()
        if sel_resolved.name.strip().lower() == "mods":
            return sel_resolved, ""

        if (
            current_mods_folder is not None
            and str(current_mods_folder).strip()
            and current_mods_folder.exists()
            and current_mods_folder.resolve().name.strip().lower() == "mods"
        ):
            cur_mods_res = current_mods_folder.resolve()
            if is_safe_subpath(sel_resolved, cur_mods_res, allow_equal=False):
                return cur_mods_res, str(sel_resolved.relative_to(cur_mods_res))

        for parent in sel_resolved.parents:
            if parent.name.strip().lower() == "mods":
                try:
                    return parent, str(sel_resolved.relative_to(parent))
                except ValueError:
                    break

        return sel_resolved, ""

    def select_mods_folder(self) -> Dict[str, Any]:
        """[Endpoint 2] 네이티브 폴더 선택 대화상자를 열어 Mods 폴더(또는 내부 특정 하위 폴더) 경로를 변경하고 로컬 선스캔을 반환합니다."""
        if self._window is None:
            return {"ok": False, "error": "윈도우가 아직 초기화되지 않았습니다."}

        try:
            import webview

            start_dir = self._resolve_mods_folder()
            scan_target_cur, _ = self._resolve_scan_target(start_dir)
            dialog_start = scan_target_cur if scan_target_cur.exists() else start_dir
            selected = self._window.create_file_dialog(
                webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG,
                directory=str(dialog_start) if dialog_start.exists() else str(Path.home()),
            )
            if not selected or len(selected) == 0:
                return {
                    "ok": False,
                    "cancelled": True,
                    "mods_folder": str(start_dir),
                }

            new_folder = Path(selected[0]).resolve()
            if not new_folder.exists() or not new_folder.is_dir():
                return {"ok": False, "error": "유효하지 않은 폴더 경로입니다."}

            # 진행 중이던 이전 전체 스캔을 즉시 무효화
            with self._cache_lock:
                self._scan_seq += 1

            resolved_mods_root, auto_sub = self._detect_mods_root_and_subfolder(new_folder, start_dir)
            self.config_manager.config["mods_folder"] = str(resolved_mods_root)
            self.config_manager.set_scan_subfolder(auto_sub)
            target_path = (resolved_mods_root / auto_sub).resolve() if auto_sub else resolved_mods_root
            scope_display = self._resolve_scope_display_label(resolved_mods_root, auto_sub)

            cached = self._load_daily_scan_cache(resolved_mods_root, scan_subfolder=auto_sub)
            if cached is not None:
                msg_cached = (
                    f"[{scope_display}] 지정 폴더 스캔 캐시 불러오기 완료: {target_path}"
                    if scope_display
                    else f"모드 폴더 변경 완료 (오늘 스캔 캐시 유지): {resolved_mods_root}"
                )
                return {
                    "ok": True,
                    "cached": True,
                    "mods_folder": str(resolved_mods_root),
                    "scan_subfolder": auto_sub,
                    "scan_target_path": str(target_path),
                    "mods": cached["mods"],
                    "summary": cached["summary"],
                    "needs_remote_scan": False,
                    "message": msg_cached,
                }

            local_scan = self.scan_mods(check_remote=False)
            msg_changed = (
                f"[{scope_display}] 지정 폴더로 스캔 범위가 설정되었습니다: {target_path}"
                if scope_display
                else f"모드 폴더가 변경되었습니다: {resolved_mods_root}"
            )
            return {
                "ok": True,
                "cached": False,
                "mods_folder": str(resolved_mods_root),
                "scan_subfolder": auto_sub,
                "scan_target_path": str(target_path),
                "mods": local_scan.get("mods", []),
                "summary": local_scan.get("summary", {}),
                "needs_remote_scan": len(local_scan.get("mods", [])) > 0,
                "message": msg_changed,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def set_scan_subfolder(self, subfolder_rel: str = "") -> Dict[str, Any]:
        """[Endpoint 2-1] Mods 폴더 내 특정 하위 폴더(또는 빈 문자열 지정 시 전체 Mods)를 스캔/업데이트 대상으로 설정합니다."""
        mods_folder = self._resolve_mods_folder()
        if not str(mods_folder).strip() or not mods_folder.exists():
            return {"ok": False, "error": "유효한 Mods 폴더 경로가 없습니다."}

        mods_resolved = mods_folder.resolve()
        raw_sub = str(subfolder_rel or "").strip().strip("/\\")
        if not raw_sub or raw_sub == ".":
            rel_clean = ""
            target_path = mods_resolved
        else:
            cand = (mods_resolved / raw_sub).resolve()
            if not cand.exists() or not cand.is_dir():
                return {"ok": False, "error": "유효하지 않은 하위 폴더 경로입니다."}
            if cand == mods_resolved:
                rel_clean = ""
                target_path = mods_resolved
            elif not is_safe_subpath(cand, mods_resolved, allow_equal=False):
                return {
                    "ok": False,
                    "error": "선택한 폴더가 현재 Mods 폴더 하위 경로가 아닙니다. 다른 폴더를 사용하려면 [폴더 변경]을 이용해 주세요.",
                }
            else:
                rel_clean = str(cand.relative_to(mods_resolved))
                target_path = cand

        # 진행 중이던 이전 스캔을 즉시 무효화
        with self._cache_lock:
            self._scan_seq += 1

        self.config_manager.set_scan_subfolder(rel_clean)

        cached = self._load_daily_scan_cache(mods_resolved, scan_subfolder=rel_clean)
        if cached is not None:
            scope_msg = f"하위 폴더 지정 완료 ({rel_clean} · 오늘 스캔 캐시 유지)" if rel_clean else f"전체 Mods 폴더로 복귀 완료 (오늘 스캔 캐시 유지)"
            return {
                "ok": True,
                "cached": True,
                "mods_folder": str(mods_resolved),
                "scan_subfolder": rel_clean,
                "scan_target_path": str(target_path),
                "mods": cached["mods"],
                "summary": cached["summary"],
                "needs_remote_scan": False,
                "message": scope_msg,
            }

        local_scan = self.scan_mods(check_remote=False)
        scope_msg = (
            f"하위 폴더 스캔 대상으로 지정됨: {rel_clean}"
            if rel_clean
            else f"전체 Mods 폴더 스캔으로 복귀됨: {mods_resolved}"
        )
        return {
            "ok": local_scan.get("ok", True),
            "cached": False,
            "mods_folder": str(mods_resolved),
            "scan_subfolder": rel_clean,
            "scan_target_path": str(target_path),
            "mods": local_scan.get("mods", []),
            "summary": local_scan.get("summary", {}),
            "needs_remote_scan": len(local_scan.get("mods", [])) > 0,
            "message": f"{scope_msg} · {local_scan.get('message', '')}".strip(" ·"),
        }

    def select_scan_subfolder(self) -> Dict[str, Any]:
        """[Endpoint 2-2] 네이티브 폴더 선택 대화상자로 Mods 폴더 내 스캔할 특정 하위 폴더를 선택합니다."""
        if self._window is None:
            return {"ok": False, "error": "윈도우가 아직 초기화되지 않았습니다."}

        mods_folder = self._resolve_mods_folder()
        if not str(mods_folder).strip() or not mods_folder.exists():
            return {"ok": False, "error": "먼저 [폴더 변경]으로 Mods 폴더를 설정해 주세요."}

        try:
            import webview

            scan_target, _ = self._resolve_scan_target(mods_folder)
            start_dir = scan_target if scan_target.exists() else mods_folder
            selected = self._window.create_file_dialog(
                webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG,
                directory=str(start_dir),
            )
            if not selected or len(selected) == 0:
                return {"ok": False, "cancelled": True}

            selected_dir = Path(selected[0]).resolve()
            mods_resolved = mods_folder.resolve()
            if not selected_dir.exists() or not selected_dir.is_dir():
                return {"ok": False, "error": "유효하지 않은 폴더 경로입니다."}
            if not is_safe_subpath(selected_dir, mods_resolved, allow_equal=True):
                return {
                    "ok": False,
                    "error": "선택한 폴더가 현재 Mods 폴더 하위 경로가 아닙니다. 다른 폴더를 사용하려면 [폴더 변경]을 이용해 주세요.",
                }

            rel = "" if selected_dir == mods_resolved else str(selected_dir.relative_to(mods_resolved))
            return self.set_scan_subfolder(rel)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def scan_mods(self, check_remote: bool = True) -> Dict[str, Any]:
        """[Endpoint 3] 로컬 'Mods' 폴더(또는 지정된 하위 폴더) 스캔 및 ThreadPoolExecutor 병렬 원격 최신 버전 조회를 수행합니다."""
        with self._cache_lock:
            self._scan_seq += 1
            current_seq = self._scan_seq

        mods_folder = self._resolve_mods_folder()
        if not str(mods_folder).strip() or not mods_folder.exists():
            with self._cache_lock:
                self._mod_cache.clear()
            return {
                "ok": False,
                "mods": [],
                "summary": {"total": 0, "update": 0, "conflict": 0, "latest": 0},
                "message": "Mods 폴더를 찾을 수 없습니다. [폴더 변경] 버튼으로 폴더를 지정해 주세요.",
            }

        try:
            scan_target, scan_sub = self._resolve_scan_target(mods_folder)
            scope_display = self._resolve_scope_display_label(mods_folder, scan_sub)
            scanner = ModScanner(mods_folder)
            backup_mgr = BackupManager(self._resolve_backup_dir())
            updater = ModUpdater(
                mods_folder=mods_folder,
                manifest_path=self._resolve_manifest_path(),
                backup_manager=backup_mgr,
            )

            units = scanner.scan_updatable_mod_units(
                target_subfolder=(scan_target if scan_sub else None)
            )
            duplicate_map = self._detect_duplicate_map_from_units(units)
            manifest_ver_map = self._build_manifest_version_map(updater)
            total_units = len(units)

            if total_units == 0:
                empty_summary = {"total": 0, "update": 0, "conflict": 0, "latest": 0}
                with self._cache_lock:
                    if current_seq == self._scan_seq:
                        self._mod_cache.clear()
                if check_remote and current_seq == self._scan_seq:
                    self._save_daily_scan_cache(
                        mods_folder, [], empty_summary, {}, scan_subfolder=scan_sub
                    )
                empty_msg = (
                    f"[{scope_display}] 지정 폴더에 설치된 스크립트/게임플레이 모드 및 WW 애니메이션이 없습니다."
                    if scope_display
                    else "설치된 스크립트/게임플레이 모드가 없습니다."
                )
                return {
                    "ok": True,
                    "mods_folder": str(mods_folder),
                    "scan_subfolder": scan_sub,
                    "scan_target_path": str(scan_target),
                    "mods": [],
                    "summary": empty_summary,
                    "message": empty_msg,
                }

            ordered_bundles: List[Optional[Tuple[str, Dict[str, Any]]]] = [None] * total_units
            ordered_entries: List[Optional[Dict[str, Any]]] = [None] * total_units

            if not check_remote:
                for i, unit in enumerate(units):
                    if current_seq != self._scan_seq:
                        return {"ok": True, "superseded": True, "mods": []}
                    mod_id, bundle = self._build_mod_entry(
                        idx=i + 1,
                        unit=unit,
                        updater=updater,
                        duplicate_map=duplicate_map,
                        check_remote=False,
                        manifest_ver_map=manifest_ver_map,
                    )
                    ordered_bundles[i] = (mod_id, bundle)
                    ordered_entries[i] = bundle["entry"]
            else:
                completed_count = 0
                max_workers = min(6, max(1, total_units))
                prefix_log = f"[{scope_display}] " if scope_display else ""
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    future_to_idx = {
                        pool.submit(
                            self._build_mod_entry,
                            i + 1,
                            unit,
                            updater,
                            duplicate_map,
                            True,
                            manifest_ver_map,
                        ): i
                        for i, unit in enumerate(units)
                    }
                    for fut in as_completed(future_to_idx):
                        if current_seq != self._scan_seq:
                            for pending_fut in future_to_idx:
                                pending_fut.cancel()
                            return {"ok": True, "superseded": True, "mods": []}
                        i = future_to_idx[fut]
                        mod_id, bundle = fut.result()
                        ordered_bundles[i] = (mod_id, bundle)
                        ordered_entries[i] = bundle["entry"]
                        completed_count += 1
                        self._emit_frontend_progress(
                            completed=completed_count,
                            total=total_units,
                            log_message=(
                                f"{prefix_log}원격 버전 확인 중 ({completed_count}/{total_units}): "
                                f"{bundle['entry']['name']}"
                            ),
                            mode="scan",
                            scan_seq=current_seq,
                            scope_label=scope_display,
                        )

            if current_seq != self._scan_seq:
                return {"ok": True, "superseded": True, "mods": []}

            new_cache: Dict[str, Dict[str, Any]] = {
                mid: bdl for item in ordered_bundles if item is not None for mid, bdl in (item,)
            }
            mods_list = [e for e in ordered_entries if e is not None]
            summary = self._summarize_mods(mods_list)

            with self._cache_lock:
                if current_seq == self._scan_seq:
                    self._mod_cache = new_cache

            if check_remote and current_seq == self._scan_seq:
                self._save_daily_scan_cache(
                    mods_folder, mods_list, summary, new_cache, scan_subfolder=scan_sub
                )

            scope_tag = f"[{scope_display}] " if scope_display else ""
            item_noun = "항목" if scope_display else "모드"
            msg = (
                f"{scope_tag}지정 폴더 내 {summary['total']}개 {item_noun} 감지됨. 원격 최신 버전을 확인 중..."
                if (not check_remote and scope_display)
                else (
                    f"로컬 모드 {summary['total']}개 감지됨. 원격 최신 버전을 확인 중..."
                    if not check_remote
                    else f"{scope_tag}총 {summary['total']}개 {item_noun} 스캔 완료 (업데이트/수동확인 {summary['update']}개)"
                )
            )
            return {
                "ok": True,
                "mods_folder": str(mods_folder),
                "scan_subfolder": scan_sub,
                "scan_target_path": str(scan_target),
                "mods": mods_list,
                "summary": summary,
                "message": msg,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "mods": []}

    def backup_mods_folder(self) -> Dict[str, Any]:
        """[Endpoint 4] 대용량 CC 전용 폴더는 제외하고, 관리 대상 핵심 모드 파일들만 상대 경로를 유지해 빠르게 백업합니다."""
        mods_folder = self._resolve_mods_folder()
        if not str(mods_folder).strip() or not mods_folder.exists():
            return {"ok": False, "error": "백업할 Mods 폴더 경로가 존재하지 않습니다."}

        try:
            scan_target, scan_sub = self._resolve_scan_target(mods_folder)
            scanner = ModScanner(mods_folder)
            units = scanner.scan_updatable_mod_units(
                target_subfolder=(scan_target if scan_sub else None)
            )
            if not units:
                return {"ok": False, "error": "백업할 스크립트/게임플레이 모드 파일이 없습니다."}

            backup_mgr = BackupManager(self._resolve_backup_dir())
            session_dir = backup_mgr.create_backup_session(label="mods_core")

            copied_files: set = set()
            for unit in units:
                for f_str in unit.get("unit_files", []):
                    src = Path(f_str)
                    if not src.exists() or not src.is_file() or src.is_symlink():
                        continue
                    src_resolved = src.resolve()
                    if src_resolved in copied_files:
                        continue
                    if not is_safe_subpath(src_resolved, mods_folder):
                        continue

                    rel_path = src_resolved.relative_to(mods_folder)
                    dest = (session_dir / rel_path).resolve()
                    if not is_safe_subpath(dest, session_dir):
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_resolved, dest)
                    copied_files.add(src_resolved)

            return {
                "ok": True,
                "backup_path": str(session_dir),
                "backed_up_count": len(copied_files),
                "message": (
                    f"핵심 모드 빠른 백업 완료! ({session_dir.name} · CC 제외 총 {len(copied_files)}개 파일)"
                ),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_mod_page(self, mod_id: str) -> Dict[str, Any]:
        """[Endpoint 5] 수동 확인(requires_browser) 모드의 공식 배포 페이지를 기본 웹 브라우저로 엽니다."""
        with self._cache_lock:
            cached = self._mod_cache.get(mod_id)
        if not cached:
            return {"ok": False, "error": "모드 정보를 찾을 수 없습니다."}

        page_url = str(cached["entry"].get("pageUrl") or "").strip()
        if not page_url or not is_valid_https_url(page_url):
            return {"ok": False, "error": "열 수 있는 안전한 HTTPS 공식 페이지 주소가 없습니다."}

        try:
            webbrowser.open(page_url)
            return {
                "ok": True,
                "page_url": page_url,
                "message": f"[{cached['entry']['name']}] 공식 배포 페이지를 브라우저에서 열었습니다.",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_mod_folder(self, mod_id: str) -> Dict[str, Any]:
        """[Endpoint 6] 충돌/중복 모드의 파일 위치를 Windows 탐색기에서 바로 선택해 열고 중복 경로를 안내합니다."""
        with self._cache_lock:
            cached = self._mod_cache.get(mod_id)
        if not cached:
            return {"ok": False, "error": "모드 정보를 찾을 수 없습니다."}

        unit = cached["unit"]
        entry = cached["entry"]
        configured_mods = self.config_manager.mods_folder
        mods_folder = self._resolve_mods_folder()

        base_candidates: List[Path] = []
        for b in (configured_mods, mods_folder):
            if b is not None and str(b).strip():
                base_candidates.append(b)

        def _is_within_mods_logical_or_real(cand: Path) -> bool:
            try:
                cand_norm_case = os.path.normcase(os.path.normpath(os.path.abspath(str(cand))))
            except Exception:
                return False
            for base_p in base_candidates:
                try:
                    if is_safe_subpath(cand, base_p, allow_equal=True):
                        return True
                except Exception:
                    pass
                try:
                    base_norm_case = os.path.normcase(os.path.normpath(os.path.abspath(str(base_p))))
                    if base_norm_case and os.path.commonpath([base_norm_case, cand_norm_case]) == base_norm_case:
                        return True
                except Exception:
                    continue
            return False

        # 실제 존재하는 대상 파일 우선 선택 (대표 파일 -> 충돌 목록 -> 유닛 파일 -> Mods 폴더 폴백)
        candidate_raws: List[str] = []
        for raw_p in [unit.get("primary_file_path"), unit.get("file_path")]:
            if raw_p:
                candidate_raws.append(str(raw_p))
        for cp in entry.get("conflictPaths") or []:
            if cp:
                candidate_raws.append(str(cp))
        for uf in unit.get("unit_files") or []:
            if uf:
                candidate_raws.append(str(uf))

        target_path: Optional[Path] = None
        seen_invalid = False
        for raw_c in candidate_raws:
            norm_c = os.path.normpath(os.path.abspath(raw_c))
            p_cand = Path(norm_c)
            if not _is_within_mods_logical_or_real(p_cand):
                seen_invalid = True
                continue
            if p_cand.exists() and p_cand.is_file():
                target_path = p_cand
                break

        if target_path is None:
            if seen_invalid:
                return {"ok": False, "error": "허용되지 않은 폴더 경로입니다."}
            fallback_dir = configured_mods if str(configured_mods).strip() and configured_mods.exists() else mods_folder
            if not fallback_dir.exists() or not _is_within_mods_logical_or_real(fallback_dir):
                return {"ok": False, "error": "허용되지 않은 폴더 경로입니다."}
            target_path = Path(os.path.normpath(os.path.abspath(str(fallback_dir))))

        norm_target = os.path.normpath(os.path.abspath(str(target_path))).replace('"', "")
        try:
            if sys.platform == "win32":
                if target_path.is_file():
                    subprocess.Popen(f'explorer /select,"{norm_target}"')
                else:
                    os.startfile(norm_target)
            conflict_paths = entry.get("conflictPaths") or []
            if conflict_paths:
                norm_base = os.path.normpath(os.path.abspath(str(configured_mods if str(configured_mods).strip() and configured_mods.exists() else mods_folder)))
                rel_list = []
                for cp in conflict_paths:
                    try:
                        norm_cp = os.path.normpath(os.path.abspath(str(cp)))
                        if os.path.commonpath([os.path.normcase(norm_base), os.path.normcase(norm_cp)]) == os.path.normcase(norm_base):
                            rel_list.append(os.path.relpath(norm_cp, norm_base))
                        else:
                            rel_list.append(str(Path(cp).resolve().relative_to(mods_folder)))
                    except Exception:
                        rel_list.append(cp)
                msg = f"중복 파일 위치({len(rel_list)}곳): {' | '.join(rel_list)}"
            else:
                msg = f"[{entry['name']}] 폴더를 탐색기에서 열었습니다."
            return {"ok": True, "message": msg, "conflict_paths": conflict_paths}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def set_mod_variant(
        self,
        mod_id: str,
        variant_file_name: str,
        selected_addons: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """[Endpoint 6-1] 택1 본체 옵션, 세부 선택 파일 및 RPO 배포 채널(선배포/무료)을 변경합니다."""
        chosen_name = (variant_file_name or "").strip()
        if not chosen_name:
            return {"ok": False, "error": "선택된 옵션 파일명이 비어 있습니다."}

        with self._cache_lock:
            cached = self._mod_cache.get(mod_id)
            if not cached:
                return {"ok": False, "error": "모드 정보를 찾을 수 없습니다."}
            update_info = cached.get("update_info") or {}
            entry = cached.get("entry") or {}
            unit = cached.get("unit") or {}
            is_rpo_channel_mode = (
                entry.get("optionModalMode") == "rpo_channel"
                or chosen_name.lower().startswith("rpo_channel:")
            )
            is_ww_channel_mode = (
                entry.get("optionModalMode") == "ww_channel"
                or chosen_name.lower().startswith("ww_channel:")
            )
            is_channel_switch = is_rpo_channel_mode or is_ww_channel_mode
            channel_unit_copy = dict(unit) if is_channel_switch else {}
            channel_conflicts = list(entry.get("conflictPaths") or []) if is_channel_switch else []

        if is_channel_switch:
            if is_ww_channel_mode:
                next_channel = "paid" if "paid" in chosen_name.lower() else "free"
                self.config_manager.set_ww_channel(next_channel)
            else:
                next_channel = "free" if "free" in chosen_name.lower() else "early_access"
                self.config_manager.set_rpo_channel(next_channel)
            mods_folder = self._resolve_mods_folder()
            updater = ModUpdater(
                mods_folder=mods_folder,
                manifest_path=self._resolve_manifest_path(),
            )
            dup_map: Dict[str, List[str]] = {}
            if channel_conflicts:
                p_name_low = Path(str(channel_unit_copy.get("primary_file_name") or channel_unit_copy.get("primary_file") or "")).name.lower()
                if p_name_low:
                    dup_map[p_name_low] = channel_conflicts
            try:
                idx_val = int(str(mod_id).split("_", 1)[0])
            except Exception:
                idx_val = 1
            _, rebuilt = self._build_mod_entry(
                idx=idx_val,
                unit=channel_unit_copy,
                updater=updater,
                duplicate_map=dup_map,
                check_remote=True,
                manifest_ver_map=self._build_manifest_version_map(updater),
            )
            rebuilt["entry"]["id"] = mod_id
            with self._cache_lock:
                if mod_id in self._mod_cache:
                    self._mod_cache[mod_id] = rebuilt
                mods_list = [b["entry"] for b in self._mod_cache.values()]
                cache_snapshot = dict(self._mod_cache)
            summary = self._summarize_mods(mods_list)
            if str(mods_folder).strip() and mods_folder.exists():
                _, cur_scan_sub = self._resolve_scan_target(mods_folder)
                self._save_daily_scan_cache(
                    mods_folder, mods_list, summary, cache_snapshot, scan_subfolder=cur_scan_sub
                )
            if is_ww_channel_mode:
                channel_label = (
                    "선배포 버전 (Patreon v187.18 · 수동 다운로드)"
                    if next_channel == "paid"
                    else "무료 버전 (Wicked.cc v185k · 자동 업데이트)"
                )
            else:
                channel_label = "무료 버전 (자동 업데이트)" if next_channel == "free" else "선배포 버전 (수동 확인)"
            res_payload: Dict[str, Any] = {
                "ok": True,
                "entry": dict(rebuilt["entry"]),
                "mods": mods_list,
                "summary": summary,
                "message": f"[{rebuilt['entry'].get('name', mod_id)}] 배포 옵션이 '{channel_label}'(으)로 저장되었습니다.",
            }
            if is_ww_channel_mode:
                res_payload["ww_channel"] = next_channel
            else:
                res_payload["rpo_channel"] = next_channel
            return res_payload

        with self._cache_lock:
            cached = self._mod_cache.get(mod_id)
            if not cached:
                return {"ok": False, "error": "모드 정보를 찾을 수 없습니다."}
            update_info = cached.get("update_info") or {}
            entry = cached.get("entry") or {}
            unit = cached.get("unit") or {}
            variant_choices = update_info.get("variant_choices") or entry.get("variantChoices") or []
            matched = next(
                (vc for vc in variant_choices if str(vc.get("file_name") or "").lower() == chosen_name.lower()),
                None,
            )
            if not matched:
                return {"ok": False, "error": "유효하지 않은 설치 옵션입니다."}

            update_info["selected_variant"] = matched["file_name"]
            entry["selectedVariant"] = matched["file_name"]

            unit_names_low = {Path(uf).name.lower() for uf in unit.get("unit_files", [])}
            if entry.get("primaryFile"):
                unit_names_low.add(Path(str(entry["primaryFile"])).name.lower())

            addon_changed = False
            available_addons = update_info.get("optional_addons") or entry.get("optionalAddons") or []
            if selected_addons is not None and available_addons:
                allowed_map = {
                    str(oa.get("file_name") or "").strip().lower(): str(oa.get("file_name") or "").strip()
                    for oa in available_addons
                    if isinstance(oa, dict) and oa.get("file_name")
                }
                clean_addons: List[str] = []
                for req_fn in selected_addons:
                    req_low = str(req_fn or "").strip().lower()
                    if req_low in allowed_map and allowed_map[req_low] not in clean_addons:
                        clean_addons.append(allowed_map[req_low])
                update_info["selected_addons"] = list(clean_addons)
                entry["selectedAddons"] = list(clean_addons)
                installed_addons_low = {k for k in allowed_map if k in unit_names_low}
                chosen_addons_low = {fn.lower() for fn in clean_addons}
                addon_changed = chosen_addons_low != installed_addons_low

            is_multi_file_select = (
                entry.get("optionModalMode") == "multi_file_select"
                or str(matched.get("file_name") or "").lower() in ("download_mode:all", "download_mode:select")
            )
            if is_multi_file_select:
                is_all_mode = str(matched.get("file_name") or "").lower() == "download_mode:all"
                allowed_all_low = {
                    str(oa.get("file_name") or "").strip().lower()
                    for oa in available_addons
                    if isinstance(oa, dict) and oa.get("file_name")
                }
                installed_all_low = {k for k in allowed_all_low if k in unit_names_low}
                target_low_set = (
                    allowed_all_low
                    if is_all_mode
                    else {str(fn).strip().lower() for fn in (update_info.get("selected_addons") or [])}
                )
                variant_changed = bool(target_low_set - installed_all_low)
                if is_all_mode:
                    addon_changed = False
            else:
                variant_changed = not self._is_variant_installed(matched, unit_names_low)
            if (variant_changed or addon_changed) and entry.get("statusType") == "latest":
                entry["statusType"] = "update"
                entry["statusText"] = "옵션 변경"
                entry["checked"] = True
                entry["disabled"] = False

            entry_copy = dict(entry)

        return {
            "ok": True,
            "entry": entry_copy,
            "message": f"[{entry_copy.get('name', mod_id)}] 설치 옵션 선택: {matched.get('label') or matched['file_name']}",
        }

    def update_single_mod(self, mod_id: str) -> Dict[str, Any]:
        """[Endpoint 7] 갤러리 카드의 개별 [업데이트] 버튼 클릭 시 단일 모드를 업데이트합니다."""
        return self.update_selected_mods([mod_id], launch_game=False)

    def update_selected_mods(
        self, selected_ids: List[str], launch_game: bool = False
    ) -> Dict[str, Any]:
        """[Endpoint 8] 선택된 모드들을 순차적으로 백업 및 업데이트하고 선택 시 심즈4를 실행합니다."""
        mods_folder = self._resolve_mods_folder()
        if not str(mods_folder).strip() or not mods_folder.exists():
            return {"ok": False, "error": "유효한 Mods 폴더 경로가 없습니다."}

        if not selected_ids:
            return {"ok": False, "error": "선택된 업데이트 대상 모드가 없습니다."}

        try:
            backup_mgr = BackupManager(self._resolve_backup_dir())
            updater = ModUpdater(
                mods_folder=mods_folder,
                manifest_path=self._resolve_manifest_path(),
                backup_manager=backup_mgr,
            )

            session_dir = backup_mgr.create_backup_session(label="pre_update")
            total = len(selected_ids)
            updated_names: List[str] = []
            failed_names: List[str] = []

            for idx, mod_id in enumerate(selected_ids, start=1):
                with self._cache_lock:
                    cached = self._mod_cache.get(mod_id)
                if not cached:
                    continue

                entry = cached["entry"]
                if entry.get("optionModalMode") == "rpo_channel" and self.config_manager.rpo_channel == "early_access":
                    failed_names.append(f"{entry['name']}(수동확인)")
                    self._emit_frontend_progress(
                        completed=idx,
                        total=total,
                        log_message=f"[{entry['name']}] 선배포 버전 선택 상태여서 자동 다운로드를 건너뛰었습니다.",
                        mode="update",
                    )
                    continue
                if entry.get("optionModalMode") == "ww_channel" and self.config_manager.ww_channel == "paid":
                    failed_names.append(f"{entry['name']}(수동확인)")
                    self._emit_frontend_progress(
                        completed=idx,
                        total=total,
                        log_message=f"[{entry['name']}] 유료 버전 선택 상태여서 자동 다운로드를 건너뛰었습니다.",
                        mode="update",
                    )
                    continue
                mod_cfg = cached["mod_cfg"]
                mod_cfg["unit_files"] = list(cached["unit"].get("unit_files", []))
                update_info = cached["update_info"]

                self._emit_frontend_progress(
                    completed=idx - 1,
                    total=total,
                    log_message=f"[{entry['name']}] 최신 버전 다운로드 및 설치 중...",
                    mode="update",
                )

                try:
                    for unit_file in cached["unit"].get("unit_files", []):
                        backup_mgr.backup_item(Path(unit_file), session_dir)

                    prev_selected_variant = str(
                        (update_info or {}).get("selected_variant")
                        or entry.get("selectedVariant")
                        or ""
                    ).strip()
                    has_prev_addons = (
                        bool(update_info) and ("selected_addons" in update_info) and (update_info.get("selected_addons") is not None)
                    ) or bool(entry.get("optionalAddons"))
                    prev_selected_addons = list(
                        (update_info or {}).get("selected_addons")
                        if (update_info and "selected_addons" in update_info and update_info.get("selected_addons") is not None)
                        else (entry.get("selectedAddons") or [])
                    )
                    if not update_info or not update_info.get("download_url"):
                        update_info = updater.check_mod_update(mod_cfg)
                        if prev_selected_variant:
                            update_info["selected_variant"] = prev_selected_variant
                        if has_prev_addons and (update_info.get("optional_addons") or entry.get("optionalAddons")):
                            update_info["selected_addons"] = prev_selected_addons

                    if update_info.get("requires_browser"):
                        failed_names.append(f"{entry['name']}(수동확인)")
                    else:
                        installed_names = updater.update_mod(
                            mod=mod_cfg,
                            update_info=update_info,
                            overwrite_mode="all",
                            skip_backup=True,
                        )
                        updated_names.append(entry["name"])

                        # 최신 버전 문자열 확정 (업데이트 성공 시 이전 버전 -> 최신 버전으로 즉시 갱신)
                        raw_latest = str(
                            update_info.get("latest_version")
                            or entry.get("latestVersion")
                            or ""
                        ).strip()
                        latest_tok = self._normalize_version_token(raw_latest)
                        if latest_tok:
                            resolved_latest = self._format_display_version(latest_tok)
                        else:
                            cand_latest = str(entry.get("latestVersion") or "").strip()
                            resolved_latest = (
                                cand_latest
                                if cand_latest and cand_latest not in ("최신 배포본", "확인 불가", "조회 대기...", "-")
                                else str(entry.get("currentVersion") or "최신버전")
                            )

                        # page_url 유무와 무관하게 업데이트 완료된 모드 파일들을 mods_manifest.json에 최신 버전·파일명 기준으로 확실히 기록
                        pin_asset_name = str(update_info.get("asset_name") or "").strip()
                        if not update_info.get("page_url") and (raw_latest or pin_asset_name):
                            fallback_page = str(
                                entry.get("pageUrl")
                                or mod_cfg.get("homepage")
                                or update_info.get("download_url")
                                or ""
                            ).strip()
                            if fallback_page and is_valid_https_url(fallback_page):
                                pin_targets: List[str] = []
                                for cand_pin in list(installed_names or []) + [
                                    str(mod_cfg.get("name") or ""),
                                    str(entry.get("primaryFile") or ""),
                                ]:
                                    c_clean = (cand_pin or "").strip()
                                    if (
                                        c_clean
                                        and c_clean.lower().endswith((".package", ".ts4script"))
                                        and all(c_clean.lower() != ex.lower() for ex in pin_targets)
                                    ):
                                        pin_targets.append(c_clean)
                                for pin_target in pin_targets:
                                    try:
                                        updater.pin_verified_url(
                                            mod_cfg,
                                            fallback_page,
                                            raw_latest,
                                            local_file_name=pin_target,
                                            asset_name=pin_asset_name,
                                        )
                                    except Exception:
                                        pass

                        # 메모리 캐시 즉시 최신 상태로 전환 (업데이트 필요 -> 최신버전 이동, 스캔 목록에서 제외)
                        with self._cache_lock:
                            entry["currentVersion"] = resolved_latest
                            entry["latestVersion"] = resolved_latest
                            entry["statusType"] = "latest"
                            entry["statusText"] = "최신버전"
                            entry["checked"] = False
                            entry["disabled"] = False
                            entry["conflictPaths"] = []
                            mod_cfg["current_version"] = latest_tok or resolved_latest.lstrip("vV")
                            if mod_cfg.get("file_path"):
                                new_fp = Path(str(mod_cfg["file_path"]))
                                cached["unit"]["primary_file_path"] = str(new_fp)
                                cached["unit"]["primary_file_name"] = new_fp.name
                                entry["primaryFile"] = new_fp.name
                                if any(
                                    str(vc.get("file_name") or "").lower() == new_fp.name.lower()
                                    for vc in (entry.get("variantChoices") or [])
                                ):
                                    entry["selectedVariant"] = new_fp.name
                                    update_info["selected_variant"] = new_fp.name
                            # 업데이트 완료된 파일 경로들을 unit_files에 최신 반영하고 삭제된 구버전 파일 제거
                            updated_unit_files: List[str] = []
                            for old_uf in cached["unit"].get("unit_files", []):
                                if Path(old_uf).exists() and old_uf not in updated_unit_files:
                                    updated_unit_files.append(old_uf)
                            for new_ip in mod_cfg.get("installed_paths") or []:
                                if Path(new_ip).exists() and new_ip not in updated_unit_files:
                                    updated_unit_files.append(new_ip)
                            if updated_unit_files:
                                cached["unit"]["unit_files"] = updated_unit_files
                            post_names_low = {Path(uf).name.lower() for uf in cached["unit"].get("unit_files", [])}
                            if entry.get("primaryFile"):
                                post_names_low.add(Path(str(entry["primaryFile"])).name.lower())
                            for vc in (entry.get("variantChoices") or []):
                                if isinstance(vc, dict):
                                    vc["installed"] = self._is_variant_installed(vc, post_names_low)
                                    if vc["installed"] and not entry.get("selectedVariant"):
                                        entry["selectedVariant"] = vc.get("file_name", "")
                            if entry.get("optionalAddons"):
                                for oa in entry["optionalAddons"]:
                                    if isinstance(oa, dict):
                                        oa["installed"] = str(oa.get("file_name") or "").strip().lower() in post_names_low
                                entry["selectedAddons"] = [
                                    oa["file_name"] for oa in entry["optionalAddons"] if oa.get("installed")
                                ]
                                update_info["selected_addons"] = list(entry["selectedAddons"])
                            cached["update_info"] = dict(update_info, has_update=False)
                except Exception:
                    failed_names.append(entry["name"])

                self._emit_frontend_progress(
                    completed=idx,
                    total=total,
                    log_message=f"[{entry['name']}] 업데이트 처리 완료 ({idx}/{total})",
                    mode="update",
                )

            launched = False
            if launch_game:
                launch_res = self.launch_sims4()
                launched = bool(launch_res.get("ok"))

            # 갱신된 캐시 기준으로 즉시 목록/요약 생성 및 오늘자 일일 캐시(scan_cache.json) 저장
            with self._cache_lock:
                mods_list = [b["entry"] for b in self._mod_cache.values()]
                cache_snapshot = dict(self._mod_cache)
            summary = self._summarize_mods(mods_list)
            _, cur_scan_sub = self._resolve_scan_target(mods_folder)
            self._save_daily_scan_cache(
                mods_folder, mods_list, summary, cache_snapshot, scan_subfolder=cur_scan_sub
            )

            suffix = " 심즈4를 실행합니다!" if launched else ""
            if failed_names:
                msg = (
                    f"{len(updated_names)}개 업데이트 완료, "
                    f"{len(failed_names)}개 확인 필요 ({', '.join(failed_names)}){suffix}"
                )
            else:
                msg = f"선택한 {len(updated_names)}개 모드 업데이트가 모두 완료되었습니다!{suffix}"

            return {
                "ok": True,
                "updated_count": len(updated_names),
                "failed_count": len(failed_names),
                "launched": launched,
                "mods": mods_list,
                "summary": summary,
                "message": msg,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _collect_steam_library_roots() -> List[Path]:
        """Windows 레지스트리와 libraryfolders.vdf에서 모든 Steam 라이브러리 루트 경로를 수집합니다."""
        steam_roots: List[Path] = []
        seen: set = set()

        def _add_root(p: Path) -> None:
            try:
                resolved = p.resolve()
                key = str(resolved).lower()
                if key not in seen and resolved.exists():
                    seen.add(key)
                    steam_roots.append(resolved)
            except Exception:
                pass

        if sys.platform == "win32":
            try:
                import winreg

                reg_targets = [
                    (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
                ]
                for root_key, subkey, val_name in reg_targets:
                    try:
                        with winreg.OpenKey(root_key, subkey) as key:
                            val, _ = winreg.QueryValueEx(key, val_name)
                            if val:
                                _add_root(Path(str(val)))
                    except OSError:
                        pass
            except Exception:
                pass

        # 기본 드라이브별 Steam 경로 후보 추가
        for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive_root = Path(f"{drive}:\\")
            if not drive_root.exists():
                continue
            for rel in (
                r"Program Files (x86)\Steam",
                r"Program Files\Steam",
                r"SteamLibrary",
                r"Steam",
            ):
                _add_root(drive_root / rel)

        # libraryfolders.vdf 파싱으로 사용자 지정 Steam 라이브러리 폴더 추가
        for root in list(steam_roots):
            vdf_path = root / "steamapps" / "libraryfolders.vdf"
            if not vdf_path.exists():
                continue
            try:
                content = vdf_path.read_text(encoding="utf-8", errors="ignore")
                for match in re.finditer(r'"path"\s+"([^"]+)"', content):
                    raw_path = match.group(1).replace("\\\\", "\\")
                    _add_root(Path(raw_path))
            except Exception:
                pass

        return steam_roots

    @classmethod
    def _detect_sims4_install(cls) -> Tuple[Optional[str], Optional[Path]]:
        """심즈4 설치 경로를 탐색하여 ('ea' | 'steam', install_dir)을 반환합니다."""
        def _has_sims4_files(folder: Path) -> bool:
            if not folder.exists() or not folder.is_dir():
                return False
            return (
                (folder / "Game" / "Bin" / "TS4_x64.exe").exists()
                or (folder / "Game" / "Bin" / "TS4_DX9_x64.exe").exists()
                or (folder / "Game" / "Bin").is_dir()
            )

        # 1) Windows 레지스트리의 Maxis\The Sims 4 Install Dir 우선 확인
        if sys.platform == "win32":
            try:
                import winreg

                for subkey in (
                    r"SOFTWARE\Maxis\The Sims 4",
                    r"SOFTWARE\WOW6432Node\Maxis\The Sims 4",
                ):
                    try:
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey) as key:
                            install_dir, _ = winreg.QueryValueEx(key, "Install Dir")
                            if install_dir:
                                p = Path(str(install_dir)).resolve()
                                if _has_sims4_files(p):
                                    p_low = str(p).lower().replace("/", "\\")
                                    if "steamapps\\common" in p_low:
                                        return "steam", p
                                    if "ea games" in p_low or "origin games" in p_low:
                                        return "ea", p
                    except OSError:
                        pass
            except Exception:
                pass

        # 2) EA Games / Origin Games 경로 탐색
        for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive_root = Path(f"{drive}:\\")
            if not drive_root.exists():
                continue
            for rel in (
                r"Program Files\EA Games\The Sims 4",
                r"Program Files (x86)\EA Games\The Sims 4",
                r"EA Games\The Sims 4",
                r"Program Files (x86)\Origin Games\The Sims 4",
                r"Origin Games\The Sims 4",
            ):
                candidate = drive_root / rel
                if _has_sims4_files(candidate):
                    return "ea", candidate.resolve()

        # 3) Steam (steamapps\common\The Sims 4) 경로 탐색
        for steam_root in cls._collect_steam_library_roots():
            candidate = steam_root / "steamapps" / "common" / "The Sims 4"
            if _has_sims4_files(candidate):
                return "steam", candidate.resolve()

        return None, None

    def launch_sims4(self) -> Dict[str, Any]:
        """[Endpoint 9] EA Games 설치 시 EA 클라이언트로, steamapps\\common 설치 시 Steam 클라이언트로 심즈4를 실행합니다."""
        EA_LAUNCH_URI = "origin2://game/launch?offerIds=SIMS4.OFF.SOLP.0x0000000000012711"
        STEAM_LAUNCH_URI = "steam://rungameid/1222670"

        platform, install_dir = self._detect_sims4_install()

        def _try_exe_fallback(base_dir: Optional[Path]) -> Optional[Path]:
            if not base_dir:
                return None
            for exe_name in ("TS4_x64.exe", "TS4_DX9_x64.exe"):
                exe_path = base_dir / "Game" / "Bin" / exe_name
                if exe_path.exists():
                    try:
                        os.startfile(str(exe_path))
                        return exe_path
                    except Exception:
                        pass
            return None

        if platform == "ea":
            try:
                os.startfile(EA_LAUNCH_URI)
                return {
                    "ok": True,
                    "platform": "ea",
                    "launched_via": EA_LAUNCH_URI,
                    "install_dir": str(install_dir),
                    "message": "EA 클라이언트를 통해 심즈4를 실행합니다! 즐거운 플레이 되세요!",
                }
            except Exception:
                exe = _try_exe_fallback(install_dir)
                if exe:
                    return {
                        "ok": True,
                        "platform": "ea",
                        "launched_via": str(exe),
                        "install_dir": str(install_dir),
                        "message": "심즈4(EA Games)를 실행합니다! 즐거운 플레이 되세요!",
                    }

        if platform == "steam":
            try:
                os.startfile(STEAM_LAUNCH_URI)
                return {
                    "ok": True,
                    "platform": "steam",
                    "launched_via": STEAM_LAUNCH_URI,
                    "install_dir": str(install_dir),
                    "message": "Steam 클라이언트를 통해 심즈4를 실행합니다! 즐거운 플레이 되세요!",
                }
            except Exception:
                exe = _try_exe_fallback(install_dir)
                if exe:
                    return {
                        "ok": True,
                        "platform": "steam",
                        "launched_via": str(exe),
                        "install_dir": str(install_dir),
                        "message": "심즈4(Steam)를 실행합니다! 즐거운 플레이 되세요!",
                    }

        # 설치 경로를 자동 감지하지 못한 경우 프로토콜 폴백 시도
        for plat_name, uri, label in (
            ("ea", EA_LAUNCH_URI, "EA 클라이언트"),
            ("steam", STEAM_LAUNCH_URI, "Steam 클라이언트"),
        ):
            try:
                os.startfile(uri)
                return {
                    "ok": True,
                    "platform": plat_name,
                    "launched_via": uri,
                    "message": f"{label}를 통해 심즈4를 실행합니다!",
                }
            except Exception:
                continue

        return {"ok": False, "error": "심즈4 설치 경로(EA Games / Steam)를 찾을 수 없습니다."}


def resolve_app_icon() -> Optional[Path]:
    """소스 실행 및 PyInstaller 번들 환경 모두에서 전용 앱 아이콘(.ico) 경로를 탐색합니다."""
    candidates = [
        BASE_DIR / "ui" / "app_icon.ico",
        BUNDLE_DIR / "ui" / "app_icon.ico",
        BASE_DIR / "_internal" / "ui" / "app_icon.ico",
        BASE_DIR / "app_icon.ico",
        BUNDLE_DIR / "app_icon.ico",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None


def _apply_windows_window_icon(window: Any, icon_path: Path) -> None:
    """Windows 실행 창의 타이틀바 및 작업표시줄에 전용 .ico 아이콘을 적용합니다."""
    if sys.platform != "win32" or not icon_path.exists():
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        icon_str = str(icon_path.resolve())
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        LR_DEFAULTSIZE = 0x0040
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1

        hicon_big = user32.LoadImageW(None, icon_str, IMAGE_ICON, 48, 48, LR_LOADFROMFILE | LR_DEFAULTSIZE)
        hicon_small = user32.LoadImageW(None, icon_str, IMAGE_ICON, 16, 16, LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if not hicon_big and not hicon_small:
            return

        hwnd = None
        native_win = getattr(window, "native", None)
        if native_win is not None:
            handle_obj = getattr(native_win, "Handle", None)
            if handle_obj is not None:
                try:
                    hwnd = int(handle_obj.ToInt64())
                except Exception:
                    try:
                        hwnd = int(handle_obj)
                    except Exception:
                        hwnd = None
        if not hwnd:
            title_str = str(getattr(window, "title", "") or "")
            if title_str:
                hwnd = user32.FindWindowW(None, title_str)

        if hwnd:
            if hicon_small:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
            if hicon_big:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
    except Exception:
        pass


def create_app_window() -> None:
    """pywebview 기반 심즈4 모드 자동 업데이터 데스크톱 창을 생성하고 실행합니다."""
    import inspect
    import webview

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Sims4ModAutoUpdater.Desktop.App")
        except Exception:
            pass

    ui_entry = resolve_ui_entry()
    icon_path = resolve_app_icon()
    api = Sims4ModUpdaterAPI(BASE_DIR)

    window = webview.create_window(
        title="심즈4 모드 자동 업데이터 v0.1.6",
        url=str(ui_entry),
        js_api=api,
        width=760,
        height=780,
        min_size=(650, 700),
        resizable=True,
        background_color="#EBF5FA",
    )
    api.set_window(window)

    if icon_path is not None and sys.platform == "win32":
        try:
            window.events.shown += lambda: _apply_windows_window_icon(window, icon_path)
        except Exception:
            pass

    start_kwargs: Dict[str, Any] = {"debug": False}
    if icon_path is not None:
        try:
            if "icon" in inspect.signature(webview.start).parameters:
                start_kwargs["icon"] = str(icon_path)
        except Exception:
            pass
    webview.start(**start_kwargs)


def main() -> None:
    """GUI 전용 메인 진입점."""
    create_app_window()


if __name__ == "__main__":
    main()
