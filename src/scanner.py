from pathlib import Path
from typing import Dict, List, Any

class ModScanner:
    """심즈 4 Mods 폴더 스캔 및 검사기"""

    def __init__(self, mods_folder: Path):
        self.mods_folder = mods_folder

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
            return {"folder_mods": [], "standalone_files": []}

        folder_mods = []
        standalone_files = []

        for item in sorted(self.mods_folder.iterdir(), key=lambda p: p.name.lower()):
            if item.is_dir():
                # 1단계 폴더 및 내부 모든 하위 폴더에 있는 package와 ts4script 전체 수집
                all_packages = [f for f in item.rglob("*") if f.is_file() and f.suffix.lower() == ".package"]
                all_scripts = [f for f in item.rglob("*") if f.is_file() and f.suffix.lower() == ".ts4script"]
                subdirs = [d for d in item.iterdir() if d.is_dir()]

                # 모드 판별 및 분류
                item_upper = item.name.upper()
                if all_scripts:
                    mod_type = "스크립트 모드"
                elif any(cc_kw in item_upper for cc_kw in ["CAS", "BUILD", "PRESET", "SLIDER", "POSE", "DEFAULT"]):
                    mod_type = "CC / 외형·건축"
                elif "PRIO" in item_upper or "한글" in item.name:
                    mod_type = "한글화 / 우선순위"
                elif all_packages:
                    mod_type = "패키지 모드"
                else:
                    # 파일이 없는 빈 폴더/기타 폴더인 경우
                    mod_type = "폴더 / 기타"

                folder_mods.append({
                    "name": item.name,
                    "path": str(item),
                    "package_count": len(all_packages),
                    "script_count": len(all_scripts),
                    "subdir_count": len(subdirs),
                    "mod_type": mod_type
                })
            elif item.is_file():
                # Resource.cfg 제외
                if item.name.lower() != "resource.cfg" and item.suffix.lower() in [".package", ".ts4script"]:
                    standalone_files.append({
                        "name": item.name,
                        "suffix": item.suffix.lower(),
                        "path": str(item)
                    })

        return {
            "folder_mods": folder_mods,
            "standalone_files": standalone_files
        }

    def detect_mod_installed(self, mod: Dict[str, Any]) -> Dict[str, Any]:
        """폴더 이름을 기준으로 지정된 모드의 package와 ts4script 파일이 Mods 폴더에 존재하는지 감지합니다.
        하위 폴더는 제외하고 키워드와 일치하는 대상 모드 폴더 자체만 감지합니다.
        """
        import re

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

        mod_name = mod.get("name", "")
        # 매니페스트에 지정된 폴더 키워드 우선 사용
        folder_keywords = mod.get("folder_keywords", [])

        # 기본 키워드 매핑 (매니페스트에 없는 경우)
        if not folder_keywords:
            mod_name_lower = mod_name.lower()
            if "command center" in mod_name_lower or "mccc" in mod_name_lower:
                folder_keywords = ["MOD MC Command Center", "MOD MCCC"]
            elif "wicked" in mod_name_lower or "whims" in mod_name_lower:
                folder_keywords = ["MOD WickedWhims", "MOD WW"]
            elif "한글" in mod_name_lower or "바람별" in mod_name_lower:
                folder_keywords = ["PRIO"]
            else:
                folder_keywords = [mod_name]

        # 파일명 키워드 (매니페스트에 명시적으로 file_keywords가 지정된 경우에만 필터링하여 폴더 내 전체 개수와 일치 유지)
        file_keywords = mod.get("file_keywords", [])
        clean_file_keywords = [fkw.lower() for fkw in file_keywords if fkw]

        # 비교를 위해 키워드 정규화 (소문자, 영숫자만 남긴 형태)
        clean_keywords = [re.sub(r'[^a-zA-Z0-9가-힣]', '', kw.lower()) for kw in folder_keywords if kw]

        # 1. 특정 폴더명 우선 검색 또는 키워드와 일치하는 대상 모드 폴더 탐색
        target_mod_dirs: List[Path] = []
        specific_folder = mod.get("folder_name") or mod.get("install_folder")
        if specific_folder and (self.mods_folder / specific_folder).is_dir():
            target_mod_dirs.append(self.mods_folder / specific_folder)
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

                # 파일 키워드가 지정되어 있으면 파일명 필터링
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
        # 대상 폴더에서 감지된 파일들과 동일한 파일명이 Mods 폴더 내 다른 위치(다른 폴더/하위폴더 등)에도 존재하는지 확인
        duplicates: List[Dict[str, Any]] = []
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

        # 한글화 모드 등 ts4script가 불필요한 모드 처리
        require_script = mod.get("require_script", True)
        if "한글" in mod_name or "korean" in mod_name.lower():
            require_script = False

        if require_script:
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

    def scan_all_mod_files(self, target_folder: Path) -> Dict[str, Any]:
        """지정된 모드 폴더 및 모든 하위 폴더에 있는 모든 .package와 .ts4script 파일 목록을 수집합니다."""
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

        # target_folder 내부의 모든 파일 탐색 (루트 및 모든 하위 폴더)
        for item in sorted(target_folder.rglob("*")):
            if not item.is_file():
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
                # ts4script 파일이 루트가 아닌 하위 서브폴더에 있는 경우 경고
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
        # 루트 폴더 파일 목록
        root_files = [f.name for f in target_folder.iterdir() if f.is_file()]
        results.append({
            "folder_name": target_folder.name + " (루트)",
            "relative_path": ".",
            "full_path": str(target_folder),
            "files": sorted(root_files)
        })

        # 하위 폴더들 순회
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
