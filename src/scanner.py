import re
from pathlib import Path
from typing import Dict, List, Any

# CC(외형/건축/포즈 등) 전용 폴더 판별용 키워드
CC_FOLDER_TOKEN_PATTERN = re.compile(
    r"(?:^|[\s_\-\[\(0-9\.])"
    r"(CAS|BUILD|PRESETS?|SLIDERS?|POSES?|DEFAULTS?|CC|WW\s*CC|HAIR|CLOTH(?:ES|ING)?|"
    r"MAKEUP|SKIN(?:DETAILS?)?|SHOES|ACC(?:ESSORIES)?|FURNITURE|BUY|TATTOOS?|EYES?|"
    r"EYEBROWS?|LASH(?:ES)?|NAILS?)"
    r"(?:$|[\s_\-\]\)])",
    flags=re.IGNORECASE,
)
CC_FOLDER_KOREAN_KEYWORDS = (
    "헤어", "의상", "메이크업", "스킨", "포즈", "슬라이더", "건축", "가구",
    "신발", "악세", "프리셋", "디폴트", "눈썹", "렌즈", "타투", "네일",
    "속눈썹", "화장", "모자", "상의", "하의", "전신", "벽지", "바닥재",
)

# 한글화 / 우선순위 폴더 판별용 키워드
TRANSLATION_FOLDER_KEYWORDS = (
    "PRIO", "한글", "번역", "한패", "KOR", "KOREAN", "TRANSLAT", "OVERRIDE", "오버라이드",
)

# 단일 모드 폴더 내부의 보조/옵션/CC 하위폴더 명칭 (별도 모드로 쪼개지 않고 본체에 귀속하거나 CC로 건너뜀)
AUX_SUBFOLDER_NAMES = {
    "ww cc", "cc", "optional", "options", "addons", "add-ons", "addon",
    "extras", "extras & overrides", "cum layer sets", "presets",
    "core", "merged", "modules", "backup", "backups", "old",
    "옵션", "선택", "선택사항", "추가", "백업", "구버전",
}

# 여러 모드를 담아두는 대표 통합/카테고리 폴더 명칭
CONTAINER_FOLDER_NAMES = {
    "mod", "mods", "gsm", "gsm 1", "gsm 2", "gsm 3", "5 gsm 1", "5 gsm 2", "5 gsm 3",
    "gm", "prio", "3 high priority mods", "high priority mods", "overrides", "override",
    "스크립트", "스크립트 모드", "스크립트모드",
    "패키지", "패키지 모드", "패키지모드", "모드", "게임플레이", "게임플레이 모드",
    "일반 모드", "일반모드", "한글", "한글화", "한글패치", "번역", "한패", "오버라이드",
}


class ModScanner:
    """심즈 4 Mods 폴더 스캔 및 검사기"""

    def __init__(self, mods_folder: Path):
        self.mods_folder = mods_folder

    @staticmethod
    def _is_cc_folder_name(folder_name: str) -> bool:
        """폴더 이름이 외형/건축/슬라이더 CC 전용 폴더인지 판별합니다.
        - 응애 스타터팩 제외 대상: 4 High Priority CC, 6 Slider, 7 CC
        - 바람별 폴더 구조 제외 대상: AA Defaults, AA Packs, AA Prototype, BB Interiors, BB Functional,
          CC FeaturedCreators, CC ETC, DD Sliders, DD Preset
        - 우선 스캔 대상(GSM, GM, MOD, Overrides, MCCC 등)은 항상 False(모드 폴더)로 판별합니다.
        """
        name_strip = folder_name.strip()
        name_upper = name_strip.upper()

        # 1) 명시적 모드 폴더 접두어(GSM, GM, MOD 및 GSM-1, GSM_1, GSM1 등) 또는 MCCC, Overrides 폴더는 CC 폴더에서 제외
        if (
            re.match(r"^(?:[\d\-]+[\.\s_\-]*)?(?:MOD|GSM|GM)(?:[\s_\-]*\[?\d+\]?)?(?:[\s_\-]|$)", name_upper)
            or "MCCC" in name_upper
            or "COMMAND CENTER" in name_upper
            or "OVERRIDE" in name_upper
        ):
            return False

        # 2) 바람별님 CC 폴더 체계 접두어 (AA ..., BB ..., CC ..., DD ...) 제외
        if re.match(r"^(?:AA|BB|CC|DD)(?:[\s_\-]|$)", name_upper):
            return True

        if CC_FOLDER_TOKEN_PATTERN.search(name_upper):
            return True
        if any(kw in name_strip for kw in CC_FOLDER_KOREAN_KEYWORDS):
            return True
        return False

    @staticmethod
    def _is_translation_folder_or_files(folder_name: str, packages: List[Path]) -> bool:
        """폴더 이름 또는 내부 파일명이 한글화/우선순위 모드인지 판별합니다."""
        name_upper = folder_name.upper()
        if any(kw in name_upper for kw in TRANSLATION_FOLDER_KEYWORDS):
            return True
        for pkg in packages[:10]:
            p_low = pkg.name.lower()
            if any(k in p_low for k in ("!wamtik", "_wamtik", "한글", "번역", "한패", "korean", "_kor")):
                return True
        return False

    @staticmethod
    def _is_cc_or_aux_subfolder(sub_dir: Path, parent_has_root_mods: bool = False) -> bool:
        """하위 폴더가 CC/옵션/백업 보조 폴더인지 판별합니다.
        (카테고리 1차 분류 -> 제작자별 2차 분류 -> 모드별 3차 분류 등 다단계 폴더 구조는 통과시킴)
        """
        name_low = sub_dir.name.lower().strip()
        if name_low in AUX_SUBFOLDER_NAMES:
            return True
        if any(
            k in name_low
            for k in (
                "ww cc", "layer set", "preset", "slider", "pose",
                "optional", "addon", "add-on", "backup", "옵션", "구버전", "백업",
            )
        ):
            return True
        return False

    @staticmethod
    def _get_file_group_key(f: Path, all_stems_in_dir: List[str]) -> str:
        """동일 폴더 내 파일들을 개별 모드 단위로 묶기 위한 그룹 키를 생성합니다."""
        f_low = f.name.lower()
        if f_low.startswith("mc_woohoo"):
            return "mccc:mc_woohoo"
        if f_low.startswith("mc_"):
            return "mccc:mc_cmd_center"

        try:
            from src.finder import check_known_catalog
            cat = check_known_catalog(f.name)
            if cat and cat.get("matched_catalog"):
                return f"cat:{cat['matched_catalog']}"
        except Exception:
            pass

        stem = re.sub(r"^[!_~\-\s]+", "", f.stem)
        clean_stem = re.sub(r"[\s_-]*\((?:required|optional|[^\)]*)\)", "", stem, flags=re.IGNORECASE)
        clean_stem = re.sub(r"[\s_-]+(?:v|ver|version)?[0-9]+(?:\.[0-9]+)*[a-z]?\b", "", clean_stem, flags=re.IGNORECASE)
        clean_stem = re.sub(
            r"[_\-\s]+(scripts?|tuning|package|core|main|base|required|optional|addon|add-on|test_users)$",
            "",
            clean_stem,
            flags=re.IGNORECASE,
        )
        clean_low = clean_stem.lower().strip(" _-")

        parts = [p for p in clean_low.split("_") if p]
        if len(parts) >= 2:
            p0, p1 = parts[0], parts[1]
            if p0 == "littlemssam" and p1 == "rsm" and len(parts) >= 4:
                return f"lms_rsm:{p0}_{p1}_{parts[2]}_{parts[3]}"
            if p0 in (
                "littlemssam", "lumpinou", "natethel0ser", "polarbearsims",
                "pandasama", "spinningplumbobs", "turbodriver", "weerbesu", "roburky", "lotharihoe",
                "simmattically", "simkatu", "simplyanjuta", "sims4me",
                "chingyu", "kiarasims", "adeepindigo", "lot51",
            ):
                return f"creator_mod:{p0}_{p1}"

        # 같은 폴더 내 더 짧은 기본 파일명(본체)의 하위 애드온/옵션 파일이 존재하는 경우 동일 그룹으로 묶음
        for base_cand in sorted(all_stems_in_dir, key=len):
            if (
                len(base_cand) >= 8
                and (clean_low == base_cand or clean_low.startswith(base_cand + "_"))
                and any(other != base_cand and other.startswith(base_cand + "_") for other in all_stems_in_dir)
            ):
                return f"base:{base_cand}"

        return f"stem:{clean_low}"

    @staticmethod
    def _select_primary_file(g_files: List[Path]) -> Path:
        """그룹에 속한 파일들 중 버전/메타데이터 추출에 가장 적합한 대표 본체 파일을 선택합니다."""
        if len(g_files) == 1:
            return g_files[0]

        def _norm_base_stem(p: Path) -> str:
            s = re.sub(r"^[!_~\-\s]+", "", p.stem)
            s = re.sub(r"[_\-\s]+(scripts?|package|core|main|base|required)$", "", s, flags=re.IGNORECASE)
            return s

        min_stem_len = min(len(_norm_base_stem(f)) for f in g_files)

        def _priority_key(f: Path):
            f_low = f.name.lower()
            stem_clean = _norm_base_stem(f)
            score = 0

            # 1) 핵심 코어 파일 최우선
            if any(
                k in f_low
                for k in (
                    "mc_cmd_center.ts4script",
                    "wickedwhims_scripts.ts4script",
                    "wonderfulwhims_scripts.ts4script",
                    "!wamtik",
                    "_wamtik",
                    "m00_corelibrary_required",
                )
            ) or f_low == "sims4_ai_chat.ts4script":
                score += 250

            # 2) Required / Core / Base 표기 파일 우선
            if any(k in f_low for k in ("required", "core", "base")):
                score += 80

            # 3) Optional / Addon / 보조 파일 후순위
            if any(
                k in f_low
                for k in (
                    "optional", "addon", "add-on", "updater", "ringer",
                    "sounds", "test_users", "nocooking", "cannotdie",
                    "costfix", "gotosleep", "hiremore", "lockedstats",
                    "noautocooking", "noautoputaway", "nogardening",
                    "secondnanny",
                )
            ):
                score -= 90

            # 4) 가장 짧은 기본 파일명(본체 파일, 예: LittleMsSam_BetterButler.package) 가산점
            if len(stem_clean) <= min_stem_len + 2:
                score += 65

            # 5) 본체 스크립트 파일(.ts4script) 가산점
            if f.suffix.lower() == ".ts4script":
                score += 40

            return (-score, len(stem_clean), f_low)

        return sorted(g_files, key=_priority_key)[0]

    def _group_directory_into_units(
        self,
        target_dir: Path,
        d_files: List[Path],
        is_standalone_root: bool = False,
    ) -> List[Dict[str, Any]]:
        """단일 디렉터리 내의 모드 파일들을 개별 모드 단위(unit) 리스트로 그룹화합니다."""
        if not d_files:
            return []

        base_stems: List[str] = []
        for f in d_files:
            s = re.sub(r"^[!_~\-\s]+", "", f.stem).lower()
            s = re.sub(r"[\s_-]*\((?:required|optional|[^\)]*)\)", "", s, flags=re.IGNORECASE)
            s = re.sub(r"[\s_-]+(?:v|ver|version)?[0-9]+(?:\.[0-9]+)*[a-z]?\b", "", s, flags=re.IGNORECASE)
            s = re.sub(
                r"[_\-\s]+(scripts?|tuning|package|core|main|base|required|optional)$",
                "",
                s,
                flags=re.IGNORECASE,
            ).strip(" _-")
            if s:
                base_stems.append(s)

        groups: Dict[str, List[Path]] = {}
        for f in d_files:
            gk = self._get_file_group_key(f, base_stems)
            groups.setdefault(gk, []).append(f)

        rel_dir_str = (
            ""
            if is_standalone_root or target_dir.resolve() == self.mods_folder.resolve()
            else str(target_dir.relative_to(self.mods_folder))
        )
        folder_display = "(Mods 루트)" if not rel_dir_str else rel_dir_str

        units: List[Dict[str, Any]] = []
        multi_group_in_dir = len(groups) > 1 or is_standalone_root or ("\\" in rel_dir_str or "/" in rel_dir_str)

        for gk, g_files in groups.items():
            pkgs = [x for x in g_files if x.suffix.lower() == ".package"]
            scrs = [x for x in g_files if x.suffix.lower() == ".ts4script"]
            primary = self._select_primary_file(g_files)

            if scrs:
                u_type = "스크립트 모드"
            elif self._is_translation_folder_or_files(target_dir.name, pkgs):
                u_type = "한글화 / 우선순위"
            else:
                u_type = "패키지 모드"

            display_name = (
                f"{folder_display} › {primary.name}"
                if multi_group_in_dir
                else folder_display
            )

            units.append({
                "name": display_name,
                "display_name": display_name,
                "folder_name": folder_display,
                "install_folder": rel_dir_str,
                "path": str(target_dir),
                "primary_file": primary.name,
                "primary_file_name": primary.name,
                "file_path": str(primary),
                "primary_file_path": str(primary),
                "unit_files": [str(x) for x in g_files],
                "package_count": len(pkgs),
                "script_count": len(scrs),
                "subdir_count": 0,
                "mod_type": u_type,
                "is_standalone": is_standalone_root,
                "group_key": gk,
            })

        return units

    @staticmethod
    def _folder_scan_sort_key(p: Path):
        """스캔 시 GSM, GM, MOD, Overrides, PRIO 등 핵심 모드 폴더를 우선 정렬합니다."""
        name_up = p.name.strip().upper()
        if re.match(r"^(?:[\d\-]+[\.\s_\-]*)?(?:GSM|GM)(?:[\s_\-]*\[?\d+\]?)?(?:[\s_\-]|$)", name_up):
            prio = 0
        elif re.match(r"^(?:[\d\-]+[\.\s_\-]*)?MOD(?:[\s_\-]*\[?\d+\]?)?(?:[\s_\-]|$)", name_up) or "MCCC" in name_up or "WICKED" in name_up:
            prio = 1
        elif "OVERRIDE" in name_up or "PRIO" in name_up or "한글" in name_up:
            prio = 2
        elif ModScanner._is_cc_folder_name(p.name):
            prio = 9
        else:
            prio = 3
        return (prio, p.name.lower())

    def scan_updatable_mod_units(self) -> List[Dict[str, Any]]:
        """Mods 폴더 전체(1단계 폴더, 통합 폴더 내 하위 폴더, Mods 루트 직속 단일 파일, .package 전용 모드 포함)를
        스캔하여 실제 업데이트 점검 대상인 '개별 모드 단위(Mod Unit)' 목록을 반환합니다.
        """
        if not self.mods_folder.exists():
            return []

        all_units: List[Dict[str, Any]] = []

        # 1. 1단계 폴더 및 내부 비-CC 하위 폴더 스캔 (GSM, GM, MOD 등 핵심 모드 폴더 우선)
        for top_dir in sorted(self.mods_folder.iterdir(), key=self._folder_scan_sort_key):
            if not top_dir.is_dir():
                continue

            all_scripts_in_top = [f for f in top_dir.rglob("*") if f.is_file() and f.suffix.lower() == ".ts4script"]
            all_pkgs_in_top = [f for f in top_dir.rglob("*") if f.is_file() and f.suffix.lower() == ".package"]
            if not all_scripts_in_top and not all_pkgs_in_top:
                continue

            # CC 전용 폴더명(예: 4 High Priority CC, 6 Slider, 7 CC, CAS, BUILD, POSE 등)은 절대 건드리지 않음
            if self._is_cc_folder_name(top_dir.name):
                continue

            root_files = [
                f for f in top_dir.iterdir()
                if f.is_file() and f.suffix.lower() in (".package", ".ts4script")
            ]
            has_root_mods = len(root_files) > 0

            dirs_to_scan: List[Path] = [top_dir]
            for sub in sorted(top_dir.rglob("*"), key=lambda p: str(p).lower()):
                if not sub.is_dir():
                    continue
                rel_parts = sub.relative_to(top_dir).parts
                if any(
                    pt.lower() in AUX_SUBFOLDER_NAMES or self._is_cc_folder_name(pt)
                    for pt in rel_parts
                ):
                    continue
                if self._is_cc_or_aux_subfolder(sub, has_root_mods):
                    continue
                dirs_to_scan.append(sub)

            for d in dirs_to_scan:
                d_files = sorted(
                    [f for f in d.iterdir() if f.is_file() and f.suffix.lower() in (".package", ".ts4script")],
                    key=lambda p: p.name.lower(),
                )
                if not d_files:
                    continue
                all_units.extend(self._group_directory_into_units(d, d_files, is_standalone_root=False))

        # 2. Mods 루트 직속 단일 파일(standalone_files) 스캔 및 그룹화
        root_standalone = sorted(
            [
                f for f in self.mods_folder.iterdir()
                if f.is_file()
                and f.name.lower() != "resource.cfg"
                and f.suffix.lower() in (".package", ".ts4script")
            ],
            key=lambda p: p.name.lower(),
        )
        if root_standalone:
            all_units.extend(self._group_directory_into_units(self.mods_folder, root_standalone, is_standalone_root=True))

        return all_units

    def scan(self) -> Dict[str, Any]:
        """Mods 폴더 내 모드 현황 및 구조를 분석합니다."""
        if not self.mods_folder.exists():
            return {
                "exists": False,
                "package_count": 0,
                "script_count": 0,
                "warnings": ["Mods 폴더가 존재하지 않습니다."]
            }

        package_files: List[Path] = []
        script_files: List[Path] = []
        warnings: List[str] = []

        for item in self.mods_folder.rglob("*"):
            if not item.is_file():
                continue

            suffix = item.suffix.lower()
            if suffix == ".package":
                package_files.append(item)
            elif suffix == ".ts4script":
                script_files.append(item)
                # 심즈 4 제한: .ts4script는 Mods 바로 아래 또는 1단계 서브폴더까지만 인식됨
                try:
                    rel_path = item.relative_to(self.mods_folder)
                    # 부모 디렉터리 depth 체크: Mods 기준 1단계 초과 서브폴더면 경고
                    if len(rel_path.parts) > 2:
                        warnings.append(
                            f"[주의] 스크립트 모드 깊이 초과: {rel_path} "
                            "(심즈 4는 .ts4script 파일을 최대 1단계 하위 폴더까지만 지원합니다)"
                        )
                except ValueError:
                    pass

        return {
            "exists": True,
            "mods_folder": str(self.mods_folder),
            "package_count": len(package_files),
            "script_count": len(script_files),
            "total_count": len(package_files) + len(script_files),
            "warnings": warnings,
        }

    def scan_user_mods(self) -> Dict[str, Any]:
        """사용자의 Mods 폴더를 스캔하여 1단계 폴더 단위 모드 및 루트 직속 단일 파일 목록을 수집합니다.
        각 1단계 모드 폴더의 파일 개수는 하위 폴더 내부 파일까지 모두 포함한 전체 개수로 집계합니다.
        """
        if not self.mods_folder.exists():
            return {"folder_mods": [], "standalone_files": [], "mod_units": []}

        folder_mods = []
        standalone_files = []
        all_units = self.scan_updatable_mod_units()

        for item in sorted(self.mods_folder.iterdir(), key=self._folder_scan_sort_key):
            if item.is_dir():
                # 1단계 폴더 및 내부 모든 하위 폴더에 있는 package와 ts4script 전체 수집
                all_packages = [f for f in item.rglob("*") if f.is_file() and f.suffix.lower() == ".package"]
                all_scripts = [f for f in item.rglob("*") if f.is_file() and f.suffix.lower() == ".ts4script"]
                subdirs = [d for d in item.iterdir() if d.is_dir()]

                # 모드 판별 및 분류 (CC 전용 폴더는 최우선으로 제외하고, 나머지 스크립트/패키지/번역 모드를 분류)
                if self._is_cc_folder_name(item.name):
                    mod_type = "CC / 외형·건축"
                elif all_scripts:
                    mod_type = "스크립트 모드"
                elif self._is_translation_folder_or_files(item.name, all_packages):
                    mod_type = "한글화 / 우선순위"
                elif all_packages:
                    mod_type = "패키지 모드"
                else:
                    mod_type = "폴더 / 기타"

                is_updatable = mod_type in ("스크립트 모드", "패키지 모드", "한글화 / 우선순위")
                unit_cnt = sum(
                    1 for u in all_units
                    if not u.get("is_standalone")
                    and (u["folder_name"] == item.name or u["folder_name"].startswith(item.name + "\\") or u["folder_name"].startswith(item.name + "/"))
                )

                folder_mods.append({
                    "name": item.name,
                    "path": str(item),
                    "package_count": len(all_packages),
                    "script_count": len(all_scripts),
                    "subdir_count": len(subdirs),
                    "mod_type": mod_type,
                    "is_updatable": is_updatable,
                    "unit_count": unit_cnt,
                })
            elif item.is_file():
                # Resource.cfg 제외
                if item.name.lower() != "resource.cfg" and item.suffix.lower() in [".package", ".ts4script"]:
                    standalone_files.append({
                        "name": item.name,
                        "suffix": item.suffix.lower(),
                        "type": item.suffix.lower(),
                        "path": str(item)
                    })

        return {
            "folder_mods": folder_mods,
            "standalone_files": standalone_files,
            "mod_units": all_units,
        }

    def collect_scan_diagnostics(self) -> Dict[str, Any]:
        """모드 누락 및 제외 원인을 100% 추적하기 위한 상세 스캔 진단 데이터를 수집합니다."""
        if not self.mods_folder.exists():
            return {
                "exists": False,
                "excluded_top_folders": [],
                "excluded_subfolders": [],
                "package_only_folders": [],
                "multi_script_folders": [],
                "merged_unit_files": [],
                "root_files_diagnostics": [],
                "unaccounted_files": [],
            }

        user_mods_res = self.scan_user_mods()
        folder_mods = user_mods_res["folder_mods"]
        mod_units = user_mods_res["mod_units"]

        excluded_top_folders: List[Dict[str, Any]] = []
        excluded_subfolders: List[Dict[str, Any]] = []
        package_only_folders: List[Dict[str, Any]] = []
        multi_script_folders: List[Dict[str, Any]] = []
        merged_unit_files: List[Dict[str, Any]] = []
        root_files_diagnostics: List[Dict[str, Any]] = []

        accounted_file_paths: set[str] = set()

        # 1) 1단계 폴더 및 내부 하위폴더 전수 분석
        for top_dir in sorted(self.mods_folder.iterdir(), key=self._folder_scan_sort_key):
            if not top_dir.is_dir():
                continue

            all_scripts = [f for f in top_dir.rglob("*") if f.is_file() and f.suffix.lower() == ".ts4script"]
            all_pkgs = [f for f in top_dir.rglob("*") if f.is_file() and f.suffix.lower() == ".package"]

            if not all_scripts and not all_pkgs:
                other_files = [f.name for f in top_dir.rglob("*") if f.is_file()]
                excluded_top_folders.append({
                    "folder_name": top_dir.name,
                    "path": str(top_dir),
                    "package_count": 0,
                    "script_count": 0,
                    "reason": (
                        f"내부에 .package 또는 .ts4script 모드 파일이 존재하지 않아 업데이트 목록에서 제외됨 "
                        f"(기타 파일 {len(other_files)}개)"
                    ),
                    "sample_files": other_files[:10],
                })
                continue

            if self._is_cc_folder_name(top_dir.name):
                name_up = top_dir.name.strip().upper()
                if re.match(r"^(?:AA|BB|CC|DD)(?:[\s_\-]|$)", name_up):
                    rule_desc = "바람별 폴더 구조 CC 제외 규칙(AA/BB/CC/DD 접두어)"
                elif name_up in ("4 HIGH PRIORITY CC", "6 SLIDER", "7 CC"):
                    rule_desc = "응애 스타터팩 CC/슬라이더 제외 폴더 규칙(4, 6, 7번)"
                else:
                    rule_desc = "외형/건축/포즈/슬라이더 CC 전용 키워드 규칙"

                reason_str = (
                    f".package 전용(CC/외형·건축) 폴더로 분류되어 업데이트 목록에서 제외됨 "
                    f"[{rule_desc}] (.package {len(all_pkgs)}개, .ts4script {len(all_scripts)}개)"
                )
                if all_scripts:
                    reason_str += f" ⚠️ [주의: CC 폴더 내에 .ts4script {len(all_scripts)}개({', '.join(s.name for s in all_scripts)})가 포함되어 있습니다]"

                excluded_top_folders.append({
                    "folder_name": top_dir.name,
                    "path": str(top_dir),
                    "package_count": len(all_pkgs),
                    "script_count": len(all_scripts),
                    "reason": reason_str,
                    "sample_files": [f.name for f in (all_scripts + all_pkgs)[:10]],
                })
                package_only_folders.append({
                    "folder_name": top_dir.name,
                    "status": "업데이트 목록에서 제외됨 (CC 전용 폴더)",
                    "package_count": len(all_pkgs),
                    "script_count": len(all_scripts),
                    "unit_count": 0,
                    "reason": reason_str,
                })
                for f in all_scripts + all_pkgs:
                    accounted_file_paths.add(str(f.resolve()).lower())
                continue

            # 비-CC 상위 폴더 중 .package 전용 폴더(.ts4script == 0) 기록
            top_units = [
                u for u in mod_units
                if not u.get("is_standalone")
                and (
                    u["folder_name"] == top_dir.name
                    or u["folder_name"].startswith(top_dir.name + "\\")
                    or u["folder_name"].startswith(top_dir.name + "/")
                )
            ]
            if len(all_scripts) == 0 and len(all_pkgs) > 0:
                mod_kind = "한글화 / 우선순위" if self._is_translation_folder_or_files(top_dir.name, all_pkgs) else "패키지 모드"
                omitted_pkg_cnt = max(0, len(all_pkgs) - len(top_units))
                pkg_note = (
                    f".package 전용 폴더(.ts4script 0개, .package {len(all_pkgs)}개)로 분류됨 — "
                    f"구버전(.ts4script 전용 스캔)에서는 업데이트 목록에서 제외되었으나, "
                    f"현재 v0.1.4에서는 [{mod_kind}]로 스캔에 포함되어 {len(top_units)}개 개별 모드로 감지됨."
                )
                if omitted_pkg_cnt > 0:
                    pkg_note += (
                        f" (단, 폴더 내 .package {len(all_pkgs)}개 중 대표 파일 {len(top_units)}개 외 "
                        f"[{omitted_pkg_cnt}]개는 동일 모드 부속/번들 패키지로 병합되어 개별 목록에서 생략됨)"
                    )
                package_only_folders.append({
                    "folder_name": top_dir.name,
                    "status": f"스캔 포함 ({mod_kind}, {len(top_units)}개 모드)",
                    "package_count": len(all_pkgs),
                    "script_count": 0,
                    "unit_count": len(top_units),
                    "reason": pkg_note,
                })

            # 상위 폴더 내부의 하위 폴더들 중 보조/옵션/CC 규칙으로 제외된 하위폴더 추적
            root_files = [
                f for f in top_dir.iterdir()
                if f.is_file() and f.suffix.lower() in (".package", ".ts4script")
            ]
            has_root_mods = len(root_files) > 0

            dirs_to_scan: List[Path] = [top_dir]
            for sub in sorted(top_dir.rglob("*"), key=lambda p: str(p).lower()):
                if not sub.is_dir():
                    continue
                rel_path = sub.relative_to(self.mods_folder)
                rel_parts = sub.relative_to(top_dir).parts
                sub_Files_direct = [
                    f for f in sub.iterdir()
                    if f.is_file() and f.suffix.lower() in (".package", ".ts4script")
                ]
                sub_pkgs = [f for f in sub_Files_direct if f.suffix.lower() == ".package"]
                sub_scrs = [f for f in sub_Files_direct if f.suffix.lower() == ".ts4script"]

                matched_aux = [pt for pt in rel_parts if pt.lower() in AUX_SUBFOLDER_NAMES or self._is_cc_folder_name(pt)]
                is_aux = bool(matched_aux) or self._is_cc_or_aux_subfolder(sub, has_root_mods)

                if is_aux:
                    if sub_Files_direct:
                        excluded_subfolders.append({
                            "folder_name": str(rel_path),
                            "path": str(sub),
                            "package_count": len(sub_pkgs),
                            "script_count": len(sub_scrs),
                            "files": [f.name for f in sub_Files_direct],
                            "reason": (
                                f"모드 폴더 내부의 보조/옵션/백업/CC 전용 하위폴더('{sub.name}')로 분류되어 "
                                f"업데이트 스캔에서 제외됨 (.package {len(sub_pkgs)}개, .ts4script {len(sub_scrs)}개)"
                            ),
                        })
                        for f in sub_Files_direct:
                            accounted_file_paths.add(str(f.resolve()).lower())
                    continue
                dirs_to_scan.append(sub)

            # 각 스캔 대상 디렉터리별 다중 .ts4script 보유 여부 확인
            for d in dirs_to_scan:
                d_scrs = sorted(
                    [f for f in d.iterdir() if f.is_file() and f.suffix.lower() == ".ts4script"],
                    key=lambda p: p.name.lower(),
                )
                if len(d_scrs) >= 2:
                    rel_d_str = str(d.relative_to(self.mods_folder))
                    rep_scr = self._select_primary_file(d_scrs)
                    other_scrs = [s.name for s in d_scrs if s.name != rep_scr.name]
                    d_units = [u for u in mod_units if u["folder_name"] == rel_d_str and u["script_count"] > 0]
                    unit_primary_scrs = [u["primary_file_name"] for u in d_units]
                    still_omitted_scrs = [s.name for s in d_scrs if s.name not in unit_primary_scrs]
                    if still_omitted_scrs:
                        unit_detail = (
                            f"개별 모드 유닛 스캔에서도 동일 모드 그룹으로 묶여 대표 {len(unit_primary_scrs)}개 외 "
                            f".ts4script [{len(still_omitted_scrs)}]개({', '.join(still_omitted_scrs)})가 부속 파일로 병합·생략됨"
                        )
                    else:
                        unit_detail = (
                            f"폴더 단위 보기에서는 대표 1개('{rep_scr.name}') 외 [{len(other_scrs)}]개가 가려지나, "
                            f"개별 모드 유닛(mod_units) 스캔에서는 {len(d_units)}개 모드로 모두 개별 분리됨"
                        )
                    multi_script_folders.append({
                        "folder_name": rel_d_str,
                        "total_scripts": len(d_scrs),
                        "representative_script": rep_scr.name,
                        "other_scripts": other_scrs,
                        "omitted_in_folder_view_count": len(other_scrs),
                        "omitted_in_unit_view": still_omitted_scrs,
                        "reason": (
                            f"한 폴더('{rel_d_str}') 안에 {len(d_scrs)}개의 .ts4script가 들어있어 "
                            f"폴더 대표 1개('{rep_scr.name}') 외 [{len(other_scrs)}]개가 폴더 대표 뒤에 병합됨 ({unit_detail})"
                        ),
                    })

        # 2) 개별 모드 그룹(mod_units) 내부에서 대표 1개 외 병합/생략된 부속 파일 기록
        for u in mod_units:
            u_files = [Path(p) for p in u.get("unit_files", [])]
            for uf in u_files:
                if uf.exists():
                    accounted_file_paths.add(str(uf.resolve()).lower())

            if len(u_files) > 1:
                primary_name = u["primary_file_name"]
                omitted_all = [p.name for p in u_files if p.name != primary_name]
                omitted_scrs = [p.name for p in u_files if p.name != primary_name and p.suffix.lower() == ".ts4script"]
                omitted_pkgs = [p.name for p in u_files if p.name != primary_name and p.suffix.lower() == ".package"]

                if omitted_scrs:
                    reason_text = (
                        f"한 폴더/모드 그룹('{u['folder_name']}') 안에 총 {u['script_count']}개의 .ts4script가 들어있어 "
                        f"대표 1개('{primary_name}') 외 .ts4script [{len(omitted_scrs)}]개({', '.join(omitted_scrs)})"
                        + (f" 및 부속 .package [{len(omitted_pkgs)}]개" if omitted_pkgs else "")
                        + "가 동일 모드로 묶여 개별 검색 목록에서 제외됨"
                    )
                else:
                    reason_text = (
                        f"모드 그룹('{u['folder_name']}') 내 대표 파일 1개('{primary_name}') 외 "
                        f"부속 .package [{len(omitted_pkgs)}]개가 동일 모드 구성 파일로 병합되어 개별 검색 목록에서 제외됨"
                    )

                merged_unit_files.append({
                    "folder_name": u["folder_name"],
                    "primary_file": primary_name,
                    "total_unit_files": len(u_files),
                    "omitted_count": len(omitted_all),
                    "omitted_scripts": omitted_scrs,
                    "omitted_packages": omitted_pkgs,
                    "reason": reason_text,
                })

        # 3) Mods 루트 직속 단일 파일 진단
        standalone_units = [u for u in mod_units if u.get("is_standalone")]
        for item in sorted(self.mods_folder.iterdir(), key=lambda p: p.name.lower()):
            if not item.is_file():
                continue
            f_low = item.name.lower()
            suffix = item.suffix.lower()
            if f_low == "resource.cfg" or suffix not in (".package", ".ts4script"):
                root_files_diagnostics.append({
                    "file_name": item.name,
                    "status": "스캔 제외 (비모드/시스템 파일)",
                    "reason": "Mods 루트 폴더의 단일 설정/캐시/비모드 파일이라서 스캔에서 제외됨",
                })
                if suffix in (".package", ".ts4script"):
                    accounted_file_paths.add(str(item.resolve()).lower())
                continue

            matched_u = next(
                (
                    u for u in standalone_units
                    if any(Path(up).name.lower() == f_low for up in u.get("unit_files", []))
                ),
                None,
            )
            if matched_u:
                if matched_u["primary_file_name"].lower() == f_low:
                    root_files_diagnostics.append({
                        "file_name": item.name,
                        "status": "개별 모드 유닛 스캔 포함 (폴더 목록에서는 제외)",
                        "reason": (
                            "루트 폴더(Mods/)의 단일 파일이라서 1단계 하위폴더 목록(folder_mods)에서는 제외됨 "
                            "→ 개별 모드 유닛(mod_units) 스캔에서는 '(Mods 루트)' 소속 대표 모드로 정상 포함됨"
                        ),
                    })
                else:
                    other_cnt = len(matched_u.get("unit_files", [])) - 1
                    root_files_diagnostics.append({
                        "file_name": item.name,
                        "status": f"루트 대표 파일('{matched_u['primary_file_name']}')에 병합됨",
                        "reason": (
                            f"루트 폴더(Mods/)의 단일 파일이며, 동일 모드 대표 파일 1개('{matched_u['primary_file_name']}') 외 "
                            f"[{other_cnt}]개 부속 파일로 묶여 개별 검색에서 제외됨"
                        ),
                    })
            else:
                root_files_diagnostics.append({
                    "file_name": item.name,
                    "status": "누락됨",
                    "reason": "루트 폴더의 단일 파일이나 스캔 유닛에 매핑되지 않음 (점검 필요)",
                })

        # 4) Mods 폴더 내 전체 .package / .ts4script 전수 대조 (미분류 사각지대 파일 0% 검증)
        unaccounted_files: List[Dict[str, str]] = []
        for f in sorted(self.mods_folder.rglob("*"), key=lambda p: str(p).lower()):
            if not f.is_file():
                continue
            if f.name.lower() == "resource.cfg" or f.suffix.lower() not in (".package", ".ts4script"):
                continue
            resolved_key = str(f.resolve()).lower()
            if resolved_key not in accounted_file_paths:
                rel_f = str(f.relative_to(self.mods_folder))
                unaccounted_files.append({
                    "relative_path": rel_f,
                    "full_path": str(f),
                    "reason": "스캔 포함 목록 및 제외 규칙 목록 어디에도 매핑되지 않은 미분류 파일",
                })

        return {
            "exists": True,
            "folder_mods": folder_mods,
            "mod_units": mod_units,
            "excluded_top_folders": excluded_top_folders,
            "excluded_subfolders": excluded_subfolders,
            "package_only_folders": package_only_folders,
            "multi_script_folders": multi_script_folders,
            "merged_unit_files": merged_unit_files,
            "root_files_diagnostics": root_files_diagnostics,
            "unaccounted_files": unaccounted_files,
        }

    def detect_mod_installed(self, mod: Dict[str, Any]) -> Dict[str, Any]:
        """폴더 이름 또는 개별 모드 파일 정보를 기준으로 지정된 모드의 package와 ts4script 파일이
        Mods 폴더에 존재하는지 감지합니다. (.ts4script 단독 모드 및 .package 단독 모드도 모두 정상 감지)
        """
        if not self.mods_folder.exists():
            return {
                "installed": False,
                "has_package": False,
                "has_script": False,
                "packages": [],
                "scripts": [],
                "locations": [],
                "target_dirs": []
            }

        # 0. Mods 루트 직속 단일 파일이거나 unit_files가 명시된 경우 우선 처리
        unit_files_raw = mod.get("unit_files") or []
        if mod.get("is_standalone") or (unit_files_raw and mod.get("folder_name") == "(Mods 루트)"):
            unit_paths = [Path(p) for p in unit_files_raw if Path(p).exists()]
            if not unit_paths and mod.get("file_path") and Path(mod["file_path"]).exists():
                unit_paths = [Path(mod["file_path"])]
            if not unit_paths:
                unit_paths = [
                    f for f in self.mods_folder.iterdir()
                    if f.is_file() and f.suffix.lower() in (".package", ".ts4script")
                ]
            matched_packages = [p for p in unit_paths if p.suffix.lower() == ".package"]
            matched_scripts = [p for p in unit_paths if p.suffix.lower() == ".ts4script"]
            has_package = len(matched_packages) > 0
            has_script = len(matched_scripts) > 0

            duplicates: List[Dict[str, Any]] = []
            target_file_map = {f.name.lower(): f for f in matched_packages + matched_scripts}
            if target_file_map:
                for item in self.mods_folder.rglob("*"):
                    if not item.is_file() or item.suffix.lower() not in (".package", ".ts4script"):
                        continue
                    item_name_lower = item.name.lower()
                    if item_name_lower in target_file_map:
                        original_file = target_file_map[item_name_lower]
                        if item.resolve() != original_file.resolve():
                            duplicates.append({
                                "file_name": item.name,
                                "suffix": item.suffix.lower(),
                                "original_path": str(original_file),
                                "duplicate_path": str(item),
                            })

            return {
                "installed": has_package or has_script,
                "has_package": has_package,
                "has_script": has_script,
                "packages": matched_packages,
                "scripts": matched_scripts,
                "locations": [str(self.mods_folder)],
                "target_dirs": [self.mods_folder],
                "duplicates": duplicates,
                "has_duplicates": len(duplicates) > 0,
            }

        mod_name = mod.get("name", "")
        folder_keywords = mod.get("folder_keywords", [])

        if not folder_keywords:
            mod_name_lower = mod_name.lower()
            if "command center" in mod_name_lower or "mccc" in mod_name_lower:
                folder_keywords = ["MOD MC Command Center", "MOD MCCC"]
            elif "wonderful" in mod_name_lower:
                folder_keywords = ["MOD WonderfulWhims", "WonderfulWhims"]
            elif "wicked" in mod_name_lower or "whims" in mod_name_lower:
                folder_keywords = ["MOD WickedWhims", "MOD WW"]
            elif "한글" in mod_name_lower or "바람별" in mod_name_lower:
                folder_keywords = ["PRIO"]
            else:
                folder_keywords = [mod_name]

        file_keywords = mod.get("file_keywords", [])
        clean_file_keywords = [fkw.lower() for fkw in file_keywords if fkw]
        clean_keywords = [re.sub(r'[^a-zA-Z0-9가-힣]', '', kw.lower()) for kw in folder_keywords if kw]

        # 1. 특정 폴더명(하위 폴더 상대경로 포함) 우선 검색 또는 키워드와 일치하는 대상 모드 폴더 탐색
        target_mod_dirs: List[Path] = []
        specific_folder = mod.get("install_folder") or mod.get("folder_name")
        if specific_folder and specific_folder != "(Mods 루트)" and (self.mods_folder / specific_folder).is_dir():
            target_mod_dirs.append(self.mods_folder / specific_folder)
        elif mod.get("path") and Path(mod["path"]).is_dir():
            target_mod_dirs.append(Path(mod["path"]))
        else:
            for d in self.mods_folder.rglob("*"):
                if not d.is_dir():
                    continue
                clean_dir_name = re.sub(r'[^a-zA-Z0-9가-힣]', '', d.name.lower())
                if clean_dir_name in clean_keywords:
                    target_mod_dirs.append(d)

        matched_packages: List[Path] = []
        matched_scripts: List[Path] = []
        locations = []

        # 2. 감지된 대상 모드 폴더 내 전체(.package, .ts4script) 파일 수집 (루트 파일 우선 정렬)
        for target_dir in target_mod_dirs:
            locations.append(str(target_dir))
            sorted_items = sorted(
                target_dir.rglob("*"),
                key=lambda p: (len(p.relative_to(target_dir).parts), p.name.lower()),
            )
            for item in sorted_items:
                if not item.is_file():
                    continue
                suffix = item.suffix.lower()
                if suffix not in [".package", ".ts4script"]:
                    continue

                if clean_file_keywords:
                    item_name_lower = item.name.lower()
                    if not any(item_name_lower.startswith(fkw) or fkw in item_name_lower for fkw in clean_file_keywords):
                        continue

                if suffix == ".package":
                    matched_packages.append(item)
                elif suffix == ".ts4script":
                    matched_scripts.append(item)

        has_package = len(matched_packages) > 0
        has_script = len(matched_scripts) > 0

        # 3. package / ts4script 단위 중복 모드 파일 감지
        duplicates = []
        target_file_map = {f.name.lower(): f for f in matched_packages + matched_scripts}

        if target_file_map:
            for item in self.mods_folder.rglob("*"):
                if not item.is_file():
                    continue
                suffix = item.suffix.lower()
                if suffix not in [".package", ".ts4script"]:
                    continue
                item_name_lower = item.name.lower()
                if item_name_lower in target_file_map:
                    original_file = target_file_map[item_name_lower]
                    if item.resolve() != original_file.resolve():
                        duplicates.append({
                            "file_name": item.name,
                            "suffix": suffix,
                            "original_path": str(original_file),
                            "duplicate_path": str(item)
                        })

        # .ts4script 단독 모드 또는 .package 단독 모드도 정상 설치된 것으로 인식
        if mod.get("require_both_package_and_script") is True:
            is_installed = has_package and has_script
        else:
            is_installed = has_package or has_script

        return {
            "installed": is_installed,
            "has_package": has_package,
            "has_script": has_script,
            "packages": matched_packages,
            "scripts": matched_scripts,
            "locations": locations,
            "target_dirs": target_mod_dirs,
            "duplicates": duplicates,
            "has_duplicates": len(duplicates) > 0
        }

    def scan_all_mod_files(self, target_folder: Path, root_only: bool = False) -> Dict[str, Any]:
        """지정된 모드 폴더(또는 root_only=True일 때 루트 직속 파일만)에 있는 .package와 .ts4script 파일 목록을 수집합니다."""
        if not target_folder.exists() or not target_folder.is_dir():
            return {
                "folder_name": target_folder.name,
                "folder_path": str(target_folder),
                "packages": [],
                "scripts": [],
                "all_files": [],
                "warnings": []
            }

        packages = []
        scripts = []
        all_files = []
        warnings = []

        iterator = sorted(target_folder.iterdir()) if root_only else sorted(target_folder.rglob("*"))
        for item in iterator:
            if not item.is_file():
                continue
            if item.name.lower() == "resource.cfg":
                continue
            suffix = item.suffix.lower()
            if suffix not in [".package", ".ts4script"]:
                continue

            rel_path = item.relative_to(target_folder)
            parent_rel = rel_path.parent
            location_str = "." if str(parent_rel) == "." else str(parent_rel)

            file_info = {
                "name": item.name,
                "type": suffix,
                "location": location_str,
                "relative_path": str(rel_path),
                "full_path": str(item),
                "size": item.stat().st_size
            }

            all_files.append(file_info)
            if suffix == ".package":
                packages.append(file_info)
            elif suffix == ".ts4script":
                scripts.append(file_info)
                if location_str != ".":
                    warnings.append(
                        f"스크립트 파일 '{item.name}'이(가) 하위 폴더({location_str})에 있습니다. "
                        "심즈 4는 서브폴더 깊이가 1단계를 초과하면 스크립트를 인식하지 못할 수 있습니다."
                    )

        return {
            "folder_name": target_folder.name,
            "folder_path": str(target_folder),
            "packages": packages,
            "scripts": scripts,
            "all_files": all_files,
            "warnings": warnings
        }

    def scan_subfolders(self, target_folder: Path) -> List[Dict[str, Any]]:
        """지정된 모드 폴더 내부의 하위 폴더들과 포함된 파일 목록을 스캔합니다."""
        if not target_folder.exists() or not target_folder.is_dir():
            return []

        results = []
        root_files = [f.name for f in target_folder.iterdir() if f.is_file()]
        results.append({
            "folder_name": target_folder.name + " (루트)",
            "relative_path": ".",
            "full_path": str(target_folder),
            "files": sorted(root_files)
        })

        for sub_dir in sorted(target_folder.rglob("*")):
            if not sub_dir.is_dir():
                continue
            sub_files = [f.name for f in sub_dir.iterdir() if f.is_file()]
            rel = sub_dir.relative_to(target_folder)
            results.append({
                "folder_name": sub_dir.name,
                "relative_path": str(rel),
                "full_path": str(sub_dir),
                "files": sorted(sub_files)
            })

        return results

    def detect_mccc_installed(self) -> Dict[str, Any]:
        """Mods 폴더 내에서 MC Command Center의 package 및 ts4script 파일을 감지합니다."""
        return self.detect_mod_installed({
            "name": "MC Command Center",
            "install_folder": "MOD MC Command Center",
            "folder_keywords": ["MOD MC Command Center", "MOD MCCC"]
        })
