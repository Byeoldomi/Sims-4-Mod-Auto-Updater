"""WickedWhims 애니메이션 카탈로그 및 다양한 폴더 구조 호환 기능 테스트."""

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main as app_main
from src.finder import (
    check_known_catalog,
    extract_mod_file_metadata,
    find_direct_mod_page,
    is_ww_animation_package,
)
from src.scanner import ModScanner
from src.updater import ModUpdater


def _build_minimal_dbpf_package(
    dest_path: Path,
    xml_texts: list[str],
    raw_typed_chunks: list[tuple[int, bytes]] | None = None,
) -> Path:
    """테스트용 최소 DBPF 2.1 .package 파일을 생성합니다."""
    header = bytearray(96)
    header[0:4] = b"DBPF"
    struct.pack_into("<I", header, 4, 2)
    struct.pack_into("<I", header, 8, 1)

    records: list[tuple[int, int, int]] = []
    body = bytearray()
    cur_offset = 96
    for txt in xml_texts:
        raw = txt.encode("utf-8")
        records.append((0x03B33DDF, cur_offset, len(raw)))
        body.extend(raw)
        cur_offset += len(raw)
    for r_type, raw_bytes in (raw_typed_chunks or []):
        records.append((r_type, cur_offset, len(raw_bytes)))
        body.extend(raw_bytes)
        cur_offset += len(raw_bytes)

    idx_offset = cur_offset
    struct.pack_into("<I", header, 36, len(records))
    struct.pack_into("<I", header, 64, idx_offset)

    idx_buf = bytearray(4)
    for idx_i, (r_type, off, sz) in enumerate(records):
        entry = bytearray(32)
        struct.pack_into("<I", entry, 0, r_type)
        struct.pack_into("<5I", entry, 12, idx_i + 1, off, sz, sz, 0)
        idx_buf.extend(entry)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(bytes(header) + bytes(body) + bytes(idx_buf))
    return dest_path


def _ww_anim_xml(author: str, display_name: str, extra_url: str = "") -> str:
    url_tag = f'<T n="url">{extra_url}</T>' if extra_url else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<I c="WickedWhimsAnimationPackage" i="snippet" m="wickedwhims_animations" n="WW:AnimPack">'
        f'<T n="animation_author">{author}</T>'
        f'<T n="animation_raw_display_name">{display_name}</T>'
        f"{url_tag}"
        "</I>"
    )


class WickedWhimsAnimationSupportTest(unittest.TestCase):
    def test_binary_detection_distinguishes_ww_anim_from_pose_and_cas_cc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ww_anim = _build_minimal_dbpf_package(
                root / "CustomCreator_MyPack.package",
                [_ww_anim_xml("CustomCreator", "Cozy Animation Pack")],
            )
            normal_pose = _build_minimal_dbpf_package(
                root / "Andrew_NormalPose.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="PosePack" i="snippet" m="pose_player" n="Andrew:Pose"/>'],
            )
            ww_cas = _build_minimal_dbpf_package(
                root / "Creator_WW_CAS.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="WickedWhimsCASPartsPackage" i="snippet" m="wickedwhims_cas_parts" n="WW:CAS"/>'],
            )

            self.assertTrue(is_ww_animation_package(ww_anim))
            meta = extract_mod_file_metadata(str(ww_anim))
            self.assertTrue(meta["is_ww_animation"])
            self.assertEqual(meta["inferred_creator"], "CustomCreator")
            self.assertIn("Cozy Animation Pack", meta["display_names"])

            self.assertFalse(is_ww_animation_package(normal_pose))
            self.assertFalse(is_ww_animation_package(ww_cas))

    def test_scanner_supports_diverse_ww_animation_folders_and_conditional_pose_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mods_dir = Path(tmp) / "Mods"

            # 1) WW 폴더 하위 Animations
            p1 = _build_minimal_dbpf_package(
                mods_dir / "MOD WickedWhims" / "Animations" / "Anarcis_WW_Animations.package",
                [_ww_anim_xml("Anarcis", "Anarcis Pack")],
            )
            # 2) 독립 WW 애니메이션 폴더
            p2 = _build_minimal_dbpf_package(
                mods_dir / "WW Animations" / "Amra72_Animations.package",
                [_ww_anim_xml("Amra72", "Amra72 Pack")],
            )
            # 3) CLI 공용 폴더 하위 한글 애니메이션 폴더
            p3 = _build_minimal_dbpf_package(
                mods_dir / "5 GSM 1" / "WW 애니" / "GreyNaya_Animations.package",
                [_ww_anim_xml("GreyNaya", "GreyNaya Pack")],
            )
            # 4) 포즈 폴더 내 일반 포즈팩(제외) + WW 애니메이션(예외 포함)
            normal_pose = _build_minimal_dbpf_package(
                mods_dir / "Pose" / "Andrew_NormalPose.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="PosePack" i="snippet" m="pose_player" n="Andrew:Pose"/>'],
            )
            ww_in_pose = _build_minimal_dbpf_package(
                mods_dir / "포즈" / "CustomCreator_MyAnim.package",
                [_ww_anim_xml("CustomCreator", "Pose Folder WW Anim")],
            )
            # 5) 일반 CC 폴더는 계속 제외
            cc_excluded = _build_minimal_dbpf_package(
                mods_dir / "7 CC" / "Hair_CC.package",
                [_ww_anim_xml("Anyone", "Should Not Scan Inside 7 CC")],
            )
            aa_excluded = _build_minimal_dbpf_package(
                mods_dir / "AA Defaults" / "Default_Skin.package",
                [_ww_anim_xml("Anyone", "Should Not Scan Inside AA")],
            )

            self.assertTrue(all(x.exists() for x in (p1, p2, p3, normal_pose, ww_in_pose, cc_excluded, aa_excluded)))

            scanner = ModScanner(mods_dir)
            units = scanner.scan_updatable_mod_units()
            primaries = {u["primary_file_name"]: u for u in units}

            self.assertIn("Anarcis_WW_Animations.package", primaries)
            self.assertIn("Amra72_Animations.package", primaries)
            self.assertIn("GreyNaya_Animations.package", primaries)
            self.assertIn("CustomCreator_MyAnim.package", primaries)
            self.assertNotIn("Andrew_NormalPose.package", primaries)
            self.assertNotIn("Hair_CC.package", primaries)
            self.assertNotIn("Default_Skin.package", primaries)

            for included_fn in (
                "Anarcis_WW_Animations.package",
                "Amra72_Animations.package",
                "GreyNaya_Animations.package",
                "CustomCreator_MyAnim.package",
            ):
                self.assertTrue(primaries[included_fn].get("is_ww_animation"))
                self.assertEqual(primaries[included_fn].get("mod_type"), "WW 애니메이션")

    def test_catalog_matching_embedded_url_priority_and_no_cc_false_positive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cat_hit = check_known_catalog("Anarcis_WW_Animations.package")
            self.assertIsNotNone(cat_hit)
            self.assertTrue(cat_hit["is_ww_animation"])
            self.assertEqual(cat_hit["creator"], "Anarcis")

            # 일반 CC 파일명에 제작자명만 포함되어도 오매칭되지 않아야 함
            self.assertIsNone(check_known_catalog("Anarcis_Hair_CC.package"))

            # 바이너리로 WW 애니메이션이 확인되고 파일 내부에 공식 URL이 있으면 1순위 사용
            embedded_pkg = _build_minimal_dbpf_package(
                root / "Anarcis_Pack_2026.package",
                [_ww_anim_xml("Anarcis", "Anarcis 2026 Pack", "https://www.patreon.com/posts/anarcis-pack-123456")],
            )
            res = find_direct_mod_page("Anarcis_Pack_2026.package", file_path=str(embedded_pkg))
            self.assertTrue(res.get("is_ww_animation"))
            self.assertEqual(res.get("primary_url"), "https://www.patreon.com/posts/anarcis-pack-123456")

    def test_main_build_mod_entry_sets_is_ww_animation_badge_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods_dir = root / "Mods"
            anim_pkg = _build_minimal_dbpf_package(
                mods_dir / "포즈" / "CustomCreator_MyAnim.package",
                [_ww_anim_xml("CustomCreator", "My Sweet WW Pack")],
            )
            units = ModScanner(mods_dir).scan_updatable_mod_units()
            self.assertEqual(len(units), 1)

            api = app_main.Sims4ModUpdaterAPI(base_dir=root)
            updater = ModUpdater(mods_folder=mods_dir, manifest_path=root / "mods_manifest.json")
            _, bundle = api._build_mod_entry(
                idx=1,
                unit=units[0],
                updater=updater,
                duplicate_map={},
                check_remote=False,
                manifest_ver_map={},
            )
            entry = bundle["entry"]
            self.assertTrue(entry["isWwAnimation"])
            self.assertEqual(entry["name"], "My Sweet WW Pack")
            self.assertEqual(entry["author"], "CustomCreator")
            self.assertEqual(app_main.Sims4ModUpdaterAPI.SCAN_CACHE_SCHEMA_VERSION, 34)
            self.assertTrue(anim_pkg.exists())

    def test_ww_subfolders_korean_parent_starterpack_cc_and_unorganized_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods_dir = root / "Mods"

            # 1) 한글 WW 상위 폴더('위키드윔즈') 내 'WW CC' 및 'Optional' 하위 폴더:
            #    실제 WW 애니메이션만 수집하고 동봉된 WW 바디 파츠 CC 및 백업 폴더는 자동 제외
            ww_cc_anim = _build_minimal_dbpf_package(
                mods_dir / "위키드윔즈" / "WW CC" / "Lupobianco_WW_Animations.package",
                [_ww_anim_xml("Lupobianco", "Lupobianco Couch Pack")],
            )
            ww_cc_body = _build_minimal_dbpf_package(
                mods_dir / "위키드윔즈" / "WW CC" / "Creator_WW_BodyTop.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="WickedWhimsCASPartsPackage" i="snippet" m="wickedwhims_cas_parts" n="WW:BodyTop"/>'],
            )
            ww_opt_anim = _build_minimal_dbpf_package(
                mods_dir / "WW모드" / "추가 모션" / "Mike24_Animations.package",
                [_ww_anim_xml("Mike24", "Mike24 Extra Motion")],
            )
            ww_backup_ignored = _build_minimal_dbpf_package(
                mods_dir / "위키드윔즈" / "백업" / "Old_Anim.package",
                [_ww_anim_xml("Anarcis", "Old Backup Pack")],
            )

            # 2) 스타터팩 대분류 CC 폴더('7 CC', 'CC ETC') 하위 포즈/애니 폴더 조건부 감지
            starter_pose_anim = _build_minimal_dbpf_package(
                mods_dir / "7 CC" / "포즈" / "애니" / "WildGuy_Animations.package",
                [_ww_anim_xml("WildGuy", "WildGuy StarterPack Anim")],
            )
            starter_pose_normal = _build_minimal_dbpf_package(
                mods_dir / "7 CC" / "포즈" / "Normal_Selfie_Pose.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="PosePack" i="snippet" m="pose_player" n="Andrew:SelfiePose"/>'],
            )
            baram_cc_anim = _build_minimal_dbpf_package(
                mods_dir / "CC ETC" / "Animations" / "Yrsa_Animations.package",
                [_ww_anim_xml("Yrsa", "Yrsa CC ETC Anim")],
            )

            # 3) 정리 안 된 Mods 루트 직속 파일: 단순 CAS 의상/일반 포즈/WW 바디 파츠 제외, 실제 모드·번역·WW 애니메이션 유지
            root_hair_cc = _build_minimal_dbpf_package(
                mods_dir / "SomeCreator_CuteHair_CC.package",
                [],
                raw_typed_chunks=[(0x034AEECB, b"\x00" * 32)],
            )
            root_pose_cc = _build_minimal_dbpf_package(
                mods_dir / "SomeCreator_CouplePose.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="PosePack" i="snippet" m="pose_player" n="Pose:Couple"/>'],
            )
            root_ww_body_cc = _build_minimal_dbpf_package(
                mods_dir / "SomeCreator_WW_SkinAddon.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="WickedWhimsCASPartsPackage" i="snippet" m="wickedwhims_cas_parts" n="WW:Skin"/>'],
            )
            root_ww_anim = _build_minimal_dbpf_package(
                mods_dir / "Zorak_WW_Animations.package",
                [_ww_anim_xml("Zorak", "Zorak Loose Root Anim")],
            )
            root_gameplay_mod = _build_minimal_dbpf_package(
                mods_dir / "Creator_FasterCooking.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="Interaction" i="interaction" m="interactions.base.super_interaction" n="Creator:FasterCooking"/>'],
            )
            root_stbl_kor = _build_minimal_dbpf_package(
                mods_dir / "SomeMod_KOR_번역.package",
                [],
                raw_typed_chunks=[(0x220557DA, b"\x00" * 32)],
            )

            for p in (
                ww_cc_anim, ww_cc_body, ww_opt_anim, ww_backup_ignored,
                starter_pose_anim, starter_pose_normal, baram_cc_anim,
                root_hair_cc, root_pose_cc, root_ww_body_cc,
                root_ww_anim, root_gameplay_mod, root_stbl_kor,
            ):
                self.assertTrue(p.exists())

            units = ModScanner(mods_dir).scan_updatable_mod_units()
            primaries = {u["primary_file_name"]: u for u in units}

            self.assertIn("Lupobianco_WW_Animations.package", primaries)
            self.assertIn("Mike24_Animations.package", primaries)
            self.assertIn("WildGuy_Animations.package", primaries)
            self.assertIn("Yrsa_Animations.package", primaries)
            self.assertIn("Zorak_WW_Animations.package", primaries)
            self.assertIn("Creator_FasterCooking.package", primaries)
            self.assertIn("SomeMod_KOR_번역.package", primaries)

            self.assertNotIn("Creator_WW_BodyTop.package", primaries)
            self.assertNotIn("Old_Anim.package", primaries)
            self.assertNotIn("Normal_Selfie_Pose.package", primaries)
            self.assertNotIn("SomeCreator_CuteHair_CC.package", primaries)
            self.assertNotIn("SomeCreator_CouplePose.package", primaries)
            self.assertNotIn("SomeCreator_WW_SkinAddon.package", primaries)

    def test_multi_pack_individual_cards_and_no_wickedwhims_parent_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods_dir = root / "Mods"
            anim_dir = mods_dir / "WickedWhims Scripts" / "Anims"

            # 동일 제작자 서로 다른 2개 팩 + 1번 팩의 사운드 부속 파일 + 비카탈로그 제작자 애니메이션
            _build_minimal_dbpf_package(
                anim_dir / "Belo_Bedroom.package",
                [_ww_anim_xml("Belo", "Belo Bedroom Pack")],
            )
            _build_minimal_dbpf_package(
                anim_dir / "Belo_Bedroom_Sound.package",
                [_ww_anim_xml("Belo", "Belo Bedroom Pack")],
            )
            _build_minimal_dbpf_package(
                anim_dir / "Belo_Shower.package",
                [_ww_anim_xml("Belo", "Belo Shower Pack")],
            )
            indie_pkg = _build_minimal_dbpf_package(
                anim_dir / "IndieAnimator_WickedWhims_Animations_Sofa.package",
                [_ww_anim_xml("IndieAnimator", "IndieAnimator WickedWhims Sofa Pack")],
            )

            # 5단계 초과 깊이 경고 검증용 파일 (Mods/1/2/3/4/5/6/TooDeep.package -> parts 길이 7 > 6)
            _build_minimal_dbpf_package(
                mods_dir / "d1" / "d2" / "d3" / "d4" / "d5" / "d6" / "TooDeep_Anim.package",
                [_ww_anim_xml("IndieAnimator", "Too Deep Pack")],
            )

            scanner = ModScanner(mods_dir)
            scan_summary = scanner.scan()
            self.assertTrue(
                any("깊이 초과" in w and "TooDeep_Anim.package" in w for w in scan_summary["warnings"])
            )

            units = [
                u for u in scanner.scan_updatable_mod_units()
                if "TooDeep_Anim.package" not in u["primary_file_name"]
            ]
            self.assertEqual(len(units), 3)

            api = app_main.Sims4ModUpdaterAPI(base_dir=root)
            updater = ModUpdater(mods_folder=mods_dir, manifest_path=root / "mods_manifest.json")
            entries_by_file = {}
            for idx_i, u in enumerate(units, start=1):
                _, bundle = api._build_mod_entry(
                    idx=idx_i,
                    unit=u,
                    updater=updater,
                    duplicate_map={},
                    check_remote=False,
                    manifest_ver_map={},
                )
                entries_by_file[u["primary_file_name"]] = bundle["entry"]

            self.assertEqual(entries_by_file["Belo_Bedroom.package"]["name"], "Belo Bedroom Pack")
            self.assertEqual(entries_by_file["Belo_Shower.package"]["name"], "Belo Shower Pack")
            indie_entry = entries_by_file["IndieAnimator_WickedWhims_Animations_Sofa.package"]
            self.assertEqual(indie_entry["name"], "IndieAnimator WickedWhims Sofa Pack")
            self.assertEqual(indie_entry["author"], "IndieAnimator")
            self.assertTrue(indie_entry["isWwAnimation"])

            with patch("src.finder.search_and_rank_distribution_links", return_value=[]):
                res = find_direct_mod_page(
                    indie_pkg.name,
                    file_path=str(indie_pkg),
                    folder_name="WickedWhims Scripts\\Anims",
                )
            self.assertNotEqual(res.get("diagnostics", {}).get("matched_catalog"), "WickedWhims")

    def test_scoped_ww_folder_selection_auto_subfolder_and_stale_scan_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods_dir = root / "Mods"
            ww_anim_dir = mods_dir / "MOD WickedWhims" / "Animations"
            other_mod_dir = mods_dir / "5 GSM 1"

            _build_minimal_dbpf_package(
                ww_anim_dir / "Anarcis_Bedroom.package",
                [_ww_anim_xml("Anarcis", "Anarcis Bedroom Pack")],
            )
            _build_minimal_dbpf_package(
                other_mod_dir / "OtherCreator_GameplayMod.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="Interaction" i="interaction" m="interactions.base.super_interaction" n="Other:Gameplay"/>'],
            )

            api = app_main.Sims4ModUpdaterAPI(base_dir=root)
            api.config_manager.config["mods_folder"] = str(mods_dir)
            api.config_manager.save()

            # 1) [폴더 변경]으로 Mods 내부의 WW 애니메이션 하위 폴더를 직접 선택해도
            #    상위 Mods 루트를 보존한 채 scan_subfolder로 자동 분리되어야 함
            det_root, det_sub = api._detect_mods_root_and_subfolder(ww_anim_dir, mods_dir)
            self.assertEqual(det_root, mods_dir.resolve())
            self.assertEqual(det_sub, str(Path("MOD WickedWhims") / "Animations"))

            sub_res = api.set_scan_subfolder(det_sub)
            self.assertTrue(sub_res["ok"])
            self.assertEqual(sub_res["scan_subfolder"], det_sub)
            self.assertEqual(len(sub_res["mods"]), 1)
            self.assertEqual(sub_res["mods"][0]["name"], "WW Animation - Anarcis")
            self.assertIn(det_sub, sub_res["message"])

            # 2) 이전 스캔(stale scan_seq)의 진행률 이벤트는 프론트엔드로 전달되지 않고 차단되어야 함
            emitted_js: list[str] = []

            class _DummyWindow:
                def evaluate_js(self, code: str) -> None:
                    emitted_js.append(code)

            api.set_window(_DummyWindow())
            stale_seq = api._scan_seq - 1
            api._emit_frontend_progress(
                completed=1,
                total=50,
                log_message="원격 버전 확인 중 (1/50): OtherCreator_GameplayMod",
                mode="scan",
                scan_seq=stale_seq,
                scope_label="",
            )
            self.assertEqual(emitted_js, [])

            api._emit_frontend_progress(
                completed=1,
                total=1,
                log_message=f"[{det_sub}] 원격 버전 확인 중 (1/1): Anarcis Bedroom Pack",
                mode="scan",
                scan_seq=api._scan_seq,
                scope_label=det_sub,
            )
            self.assertEqual(len(emitted_js), 1)
            self.assertIn("Anarcis Bedroom Pack", emitted_js[0])

            # 3) 기본 'Mods' 외부에 있는 독립 WW 애니메이션 전용 폴더 자체를 지정한 경우에도 정상 스캔 및 범위 라벨 표시
            standalone_anim_dir = root / "내 WW 애니메이션 모음"
            _build_minimal_dbpf_package(
                standalone_anim_dir / "WW CC" / "Amra72_Animations.package",
                [_ww_anim_xml("Amra72", "Amra72 Standalone Folder Pack")],
            )
            api.config_manager.config["mods_folder"] = str(standalone_anim_dir)
            api.config_manager.set_scan_subfolder("")
            standalone_scan = api.scan_mods(check_remote=False)
            self.assertTrue(standalone_scan["ok"])
            self.assertEqual(len(standalone_scan["mods"]), 1)
            self.assertEqual(standalone_scan["mods"][0]["name"], "WW Animation - Amra72")
            self.assertIn("[내 WW 애니메이션 모음]", standalone_scan["message"])

    def test_direct_mods_animation_folder_coexistence_euphemisms_companions_and_updater_safety(self) -> None:
        import shutil
        import zipfile
        from src.backup import BackupManager

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods_dir = root / "Mods"

            # 1) Mods 직속 독립 애니메이션 폴더('8 애니메이션') 및 내부 가구/보조 하위 폴더('침대 가구 포함'),
            #    '포즈 & 애니메이션' 복합 폴더, 우회 폴더('꾸금'), 그리고 오탐 제외 대상인 '성인 여심 의상' 폴더 구성
            anim_main = _build_minimal_dbpf_package(
                mods_dir / "8 애니메이션" / "GreyNaya_Bedroom_Animations.package",
                [_ww_anim_xml("GreyNaya", "GreyNaya Bedroom Pack")],
            )
            anim_props = _build_minimal_dbpf_package(
                mods_dir / "8 애니메이션" / "GreyNaya_Bedroom_Props.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="Object" i="object" m="objects.game_object" n="GreyNaya:BedProp"/>'],
            )
            anim_tongue = _build_minimal_dbpf_package(
                mods_dir / "8 애니메이션" / "GreyNaya_Bedroom_Tongue.package",
                [],
                raw_typed_chunks=[(0x015A1849, b"\x00" * 32)],
            )
            separate_device = _build_minimal_dbpf_package(
                mods_dir / "8 애니메이션" / "침대 가구 포함" / "Azmodan22_Bondage_Devices.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="Object" i="object" m="objects.game_object" n="Azmodan22:CrossDevice"/>'],
            )
            deco_bed_cc = _build_minimal_dbpf_package(
                mods_dir / "8 애니메이션" / "침대 가구 포함" / "PureDeco_BedFrame.package",
                [],
                raw_typed_chunks=[(0xC0DB5AE7, b"\x00" * 32)],
            )
            sub_creator_anim = _build_minimal_dbpf_package(
                mods_dir / "8 애니메이션" / "Anarcis" / "Anarcis_WW_Animations.package",
                [_ww_anim_xml("Anarcis", "Anarcis Subfolder Pack")],
            )

            # '포즈 & 애니메이션' 복합 폴더: WW 애니메이션 + Simkatu 생활 애니메이션 오버라이드 유지, 일반 포즈팩 제외
            pose_and_anim_ww = _build_minimal_dbpf_package(
                mods_dir / "포즈 & 애니메이션" / "Mike24_Animations.package",
                [_ww_anim_xml("Mike24", "Mike24 Pack")],
            )
            simkatu_override = _build_minimal_dbpf_package(
                mods_dir / "포즈 & 애니메이션" / "simkatu_eating_at_table.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="Interaction" i="interaction" m="interactions.base.super_interaction" n="simkatu:eating_override"/>'],
            )
            plain_pose_excluded = _build_minimal_dbpf_package(
                mods_dir / "포즈 & 애니메이션" / "Normal_CouplePose.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="PosePack" i="snippet" m="pose_player" n="Andrew:Couple"/>'],
            )

            # 우회 명칭('꾸금')은 인식하고, 연령대 외형 CC('성인 여심 의상')는 오탐 없이 제외
            euphemism_anim = _build_minimal_dbpf_package(
                mods_dir / "꾸금" / "CC" / "Khlas_Animations.package",
                [_ww_anim_xml("Khlas", "Khlas Secret Pack")],
            )
            adult_age_clothes_cc = _build_minimal_dbpf_package(
                mods_dir / "성인 여심 의상" / "AdultFemale_Dress.package",
                [_ww_anim_xml("Anyone", "Should Not Scan Adult Age Clothes Folder")],
            )

            for p in (
                anim_main, anim_props, anim_tongue, separate_device, deco_bed_cc,
                sub_creator_anim, pose_and_anim_ww, simkatu_override, plain_pose_excluded,
                euphemism_anim, adult_age_clothes_cc,
            ):
                self.assertTrue(p.exists())

            units = ModScanner(mods_dir).scan_updatable_mod_units()
            by_primary = {u["primary_file_name"]: u for u in units}

            # 본체 + _Props + _Tongue 3개 파일이 GreyNaya_Bedroom_Animations.package 카드 1개로 병합되어야 함
            self.assertIn("GreyNaya_Bedroom_Animations.package", by_primary)
            self.assertNotIn("GreyNaya_Bedroom_Props.package", by_primary)
            self.assertNotIn("GreyNaya_Bedroom_Tongue.package", by_primary)
            gn_unit_names = {Path(x).name for x in by_primary["GreyNaya_Bedroom_Animations.package"]["unit_files"]}
            self.assertEqual(
                gn_unit_names,
                {
                    "GreyNaya_Bedroom_Animations.package",
                    "GreyNaya_Bedroom_Props.package",
                    "GreyNaya_Bedroom_Tongue.package",
                },
            )

            # 별개 이름 기구 모드 및 Simkatu 생활 애니메이션 오버라이드, 우회 폴더 내 애니메이션 모두 정상 포함
            self.assertIn("Azmodan22_Bondage_Devices.package", by_primary)
            self.assertFalse(by_primary["Azmodan22_Bondage_Devices.package"]["is_ww_animation"])
            self.assertIn("simkatu_eating_at_table.package", by_primary)
            self.assertIn("Mike24_Animations.package", by_primary)
            self.assertIn("Anarcis_WW_Animations.package", by_primary)
            self.assertIn("Khlas_Animations.package", by_primary)

            # 단순 장식 가구 CC, 일반 포즈팩, '성인 여심 의상' 폴더는 제외
            self.assertNotIn("PureDeco_BedFrame.package", by_primary)
            self.assertNotIn("Normal_CouplePose.package", by_primary)
            self.assertNotIn("AdultFemale_Dress.package", by_primary)

            # 2) '8 애니메이션' 루트의 GreyNaya 팩을 업데이트해도 하위 폴더('8 애니메이션/Anarcis') 파일은 보존되어야 함
            upd_zip = root / "GreyNaya_Update.zip"
            new_gn_pkg = root / "GreyNaya_Bedroom_Animations.package"
            _build_minimal_dbpf_package(new_gn_pkg, [_ww_anim_xml("GreyNaya", "GreyNaya Bedroom Pack v2")])
            with zipfile.ZipFile(upd_zip, "w") as zf:
                zf.write(new_gn_pkg, arcname="GreyNaya_Bedroom_Animations.package")

            updater = ModUpdater(
                mods_folder=mods_dir,
                manifest_path=root / "mods_manifest.json",
                backup_manager=BackupManager(root / "backups"),
            )
            gn_unit = by_primary["GreyNaya_Bedroom_Animations.package"]
            mod_cfg = {
                "name": gn_unit["primary_file_name"],
                "file_path": gn_unit["primary_file_path"],
                "install_folder": gn_unit["install_folder"],
                "unit_files": gn_unit["unit_files"],
                "source_type": "generic_web",
            }
            update_info = {
                "latest_version": "v2",
                "download_url": "https://www.patreon.com/file?h=1&i=2",
                "asset_name": "GreyNaya_Update.zip",
                "page_url": "https://www.patreon.com/greynaya",
            }

            def _fake_dl(url, dest_path, **kwargs):
                shutil.copy2(upd_zip, dest_path)
                return dest_path

            with patch("src.updater.download_file", side_effect=_fake_dl):
                installed = updater.update_mod(mod_cfg, update_info, overwrite_mode="all")

            self.assertIn("GreyNaya_Bedroom_Animations.package", installed)
            self.assertTrue(sub_creator_anim.exists())
            self.assertTrue(separate_device.exists())

    def test_0nizu_catalog_multi_file_all_and_selective_download(self) -> None:
        import shutil
        from src.backup import BackupManager

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods_dir = root / "Mods"
            anim_dir = mods_dir / "MOD WickedWhims" / "Animations"

            # 1) 카탈로그 메타데이터 검증
            cat_hit = check_known_catalog("WW_0nizu_Animations.package")
            self.assertIsNotNone(cat_hit)
            self.assertEqual(cat_hit["matched_catalog"], "WW Animation - 0nizu")
            self.assertEqual(cat_hit["creator"], "0nizu")
            self.assertEqual(cat_hit["mod_title"], "WW Animation - 0nizu")
            self.assertEqual(cat_hit["version"], "2026.10.11")
            self.assertTrue(cat_hit["is_ww_animation"])
            self.assertTrue(cat_hit["requires_option_modal"])
            self.assertEqual(cat_hit["option_modal_mode"], "multi_file_select")
            self.assertEqual(
                [oa["file_name"] for oa in cat_hit["optional_addons"]],
                [
                    "WW_0nizu_Animations.package",
                    "WW_0nizu_Group_Animations.package",
                    "WW_0nizu_SpecialGift_Animations.package",
                ],
            )
            self.assertEqual(
                cat_hit["primary_url"],
                "https://wicked.cc/animations/0nizu/0nizu-animations-for-wickedwhims/",
            )

            # 2) 로컬 스캔 시 0nizu 파일 2개가 단일 'WW Animation - 0nizu' 카드로 그룹화되는지 검증
            p_main = _build_minimal_dbpf_package(
                anim_dir / "WW_0nizu_Animations.package",
                [_ww_anim_xml("0nizu", "0nizu Animations")],
            )
            p_group = _build_minimal_dbpf_package(
                anim_dir / "WW_0nizu_Group_Animations.package",
                [_ww_anim_xml("0nizu", "0nizu Group Animations")],
            )
            self.assertTrue(p_main.exists() and p_group.exists())

            units = ModScanner(mods_dir).scan_updatable_mod_units()
            self.assertEqual(len(units), 1)
            unit = units[0]
            self.assertEqual(unit["group_key"], "cat:WW Animation - 0nizu")

            api = app_main.Sims4ModUpdaterAPI(base_dir=root)
            updater = ModUpdater(
                mods_folder=mods_dir,
                manifest_path=root / "mods_manifest.json",
                backup_manager=BackupManager(root / "backups"),
            )
            manifest_ver_map = {
                "ww_0nizu_animations.package": {"version": "2026.10.11", "size": 0, "mtime": 0, "asset_name": ""},
            }
            _, bundle = api._build_mod_entry(
                idx=1,
                unit=unit,
                updater=updater,
                duplicate_map={},
                check_remote=False,
                manifest_ver_map=manifest_ver_map,
            )
            entry = bundle["entry"]
            self.assertEqual(entry["name"], "WW Animation - 0nizu")
            self.assertEqual(entry["author"], "0nizu")
            self.assertEqual(entry["currentVersion"], "2026.10.11")
            self.assertEqual(entry["optionModalMode"], "multi_file_select")
            self.assertEqual(entry["selectedVariant"], "download_mode:all")
            self.assertTrue(entry["isWwAnimation"])

            # 2-1) 원격 버전 조회 시 로컬 버전 2026.10.11 vs 웹 최신 버전 2026.11.27 분리 및 업데이트 필요 상태 확인
            mocked_remote = {
                "status": "free_direct",
                "title": "0nizu Animations for WickedWhims - WickedCC",
                "version": "",
                "file_name": "WW_0nizu_Animations.package",
                "download_url": "https://files.wicked.cc/file/wickedcc/WW_0nizu_Animations.package",
                "page_url": "https://wicked.cc/animations/0nizu/0nizu-animations-for-wickedwhims/",
                "all_files": [
                    ("WW_0nizu_Animations.package", "https://files.wicked.cc/file/wickedcc/WW_0nizu_Animations.package"),
                    ("WW_0nizu_Group_Animations.package", "https://files.wicked.cc/file/wickedcc/p3X2qKrIn0lU1Trq/WW_0nizu_Group_Animations.package"),
                    ("WW_0nizu_SpecialGift_Animations.package", "https://files.wicked.cc/file/wickedcc/WW_0nizu_SpecialGift_Animations.package"),
                ],
            }
            with patch("src.finder.inspect_remote_mod_page", return_value=mocked_remote):
                _, remote_bundle = api._build_mod_entry(
                    idx=1,
                    unit=unit,
                    updater=updater,
                    duplicate_map={},
                    check_remote=True,
                    manifest_ver_map=manifest_ver_map,
                )
            remote_entry = remote_bundle["entry"]
            self.assertEqual(remote_entry["currentVersion"], "2026.10.11")
            self.assertEqual(remote_entry["latestVersion"], "2026.11.27")
            self.assertEqual(remote_entry["statusType"], "update")

            # 3) 원격 파일 3종 준비 후 '전체 다운로드' vs '선택 다운로드(다중 선택)' 검증
            remote_sources = {}
            for r_fn in (
                "WW_0nizu_Animations.package",
                "WW_0nizu_Group_Animations.package",
                "WW_0nizu_SpecialGift_Animations.package",
            ):
                src_p = root / f"remote_{r_fn}"
                _build_minimal_dbpf_package(src_p, [_ww_anim_xml("0nizu", f"Updated {r_fn}")])
                remote_sources[r_fn] = src_p

            all_remote_files = [
                ("WW_0nizu_Animations.package", "https://files.wicked.cc/file/wickedcc/WW_0nizu_Animations.package"),
                ("WW_0nizu_Group_Animations.package", "https://files.wicked.cc/file/wickedcc/p3X2qKrIn0lU1Trq/WW_0nizu_Group_Animations.package"),
                ("WW_0nizu_SpecialGift_Animations.package", "https://files.wicked.cc/file/wickedcc/WW_0nizu_SpecialGift_Animations.package"),
            ]

            def _fake_download(url, dest_path, **kwargs):
                for fn, _ in all_remote_files:
                    if url.endswith("/" + fn):
                        shutil.copy2(remote_sources[fn], dest_path)
                        return dest_path
                raise AssertionError(f"Unexpected download URL: {url}")

            mod_cfg = {
                "name": unit["primary_file_name"],
                "file_path": unit["primary_file_path"],
                "install_folder": unit["install_folder"],
                "unit_files": unit["unit_files"],
                "source_type": "generic_web",
            }
            base_update_info = {
                "latest_version": "Wicked.cc (2026.11.27)",
                "download_url": all_remote_files[0][1],
                "asset_name": all_remote_files[0][0],
                "page_url": "https://wicked.cc/animations/0nizu/0nizu-animations-for-wickedwhims/",
                "all_remote_files": all_remote_files,
                "option_modal_mode": "multi_file_select",
                "is_multi_file_bundle": True,
            }

            # 3-a) 전체 다운로드: 3개 모두 설치 확인
            all_info = dict(base_update_info, selected_variant="download_mode:all")
            with patch("src.updater.download_file", side_effect=_fake_download):
                installed_all = updater.update_mod(mod_cfg, all_info, overwrite_mode="all")

            self.assertEqual(
                set(installed_all),
                {
                    "WW_0nizu_Animations.package",
                    "WW_0nizu_Group_Animations.package",
                    "WW_0nizu_SpecialGift_Animations.package",
                },
            )
            self.assertTrue((anim_dir / "WW_0nizu_SpecialGift_Animations.package").exists())

            # 3-b) 선택 다운로드 (다중 선택 2개): 선택한 2개만 다운로드·설치되고 기존 1번 파일은 삭제되지 않아야 함
            downloaded_urls: list[str] = []

            def _track_download(url, dest_path, **kwargs):
                downloaded_urls.append(url)
                return _fake_download(url, dest_path, **kwargs)

            sel_info = dict(
                base_update_info,
                selected_variant="download_mode:select",
                selected_addons=[
                    "WW_0nizu_Group_Animations.package",
                    "WW_0nizu_SpecialGift_Animations.package",
                ],
            )
            with patch("src.updater.download_file", side_effect=_track_download):
                installed_sel = updater.update_mod(mod_cfg, sel_info, overwrite_mode="all")

            self.assertEqual(
                set(installed_sel),
                {
                    "WW_0nizu_Group_Animations.package",
                    "WW_0nizu_SpecialGift_Animations.package",
                },
            )
            self.assertEqual(len(downloaded_urls), 2)
            self.assertTrue((anim_dir / "WW_0nizu_Animations.package").exists())

    def test_0zzzy_catalog_and_loverslab_inspector(self) -> None:
        from src.finder import inspect_remote_mod_page

        # 1) 카탈로그 메타데이터 검증
        cat_hit = check_known_catalog("WW_0zzzy_Animation.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - 0zzzy")
        self.assertEqual(cat_hit["creator"], "0zzzy")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - 0zzzy")
        self.assertEqual(cat_hit["version"], "1.0.6")
        self.assertTrue(cat_hit["is_ww_animation"])
        self.assertEqual(
            cat_hit["primary_url"],
            "https://www.loverslab.com/files/file/11365-sims4-0zzzy-animations/",
        )

        # 2) LoversLab 표준 IPS4 do=download 응답 시 WW_0zzzy_Animation 추출 검증
        page_url = "https://www.loverslab.com/files/file/11365-sims4-0zzzy-animations/"
        dl_confirm_url = f"{page_url}?do=download&confirm=1&r=555"

        class _MockResp:
            def __init__(self, status_code: int, text: str, url: str, headers: dict[str, str] | None = None) -> None:
                self.status_code = status_code
                self.text = text
                self.url = url
                self.encoding = "utf-8"
                self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}

            def iter_content(self, chunk_size: int = 16384):
                yield self.text.encode("utf-8")

            def close(self) -> None:
                pass

        main_html = (
            '<html><head><title>[SIMS4] 0zzzy Animations 1.0.6</title></head><body>'
            f'<a href="{page_url}?do=download">Download This File</a></body></html>'
        )
        dl_list_html = (
            '<html><body><ul><li><span>WW_0zzzy_Animation.package</span>'
            f'<a href="{dl_confirm_url}">Download</a></li></ul></body></html>'
        )

        class _MockSess:
            def __init__(self) -> None:
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, target_url: str, **kwargs):
                if "do=download" in target_url:
                    return _MockResp(200, dl_list_html, f"{page_url}?do=download")
                return _MockResp(200, main_html, page_url)

        with patch("src.finder.SafeHttpsSession", return_value=_MockSess()):
            res = inspect_remote_mod_page(page_url, target_mod_name="WW_0zzzy_Animation.package")

        self.assertEqual(res["status"], "free_direct")
        self.assertEqual(res["file_name"], "WW_0zzzy_Animation.package")
        self.assertEqual(res["download_url"], dl_confirm_url)
        self.assertEqual(res["version"], "1.0.6")

        # 3) 네트워크 차단(ConnectionResetError) 발생 시 예외 없이 browser_required 폴백 검증
        class _BlockedSess:
            def __init__(self) -> None:
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, target_url: str, **kwargs):
                raise ConnectionResetError(10054, "Connection reset by peer")

        with patch("src.finder.SafeHttpsSession", return_value=_BlockedSess()):
            fallback_res = inspect_remote_mod_page(page_url, target_mod_name="WW_0zzzy_Animation.package")

        self.assertEqual(fallback_res["status"], "browser_required")
        self.assertEqual(fallback_res["page_url"], page_url)

    def test_adakasay_catalog_multi_file_all_and_selective_download(self) -> None:
        import shutil
        from src.backup import BackupManager
        from src.finder import inspect_remote_mod_page

        # 1) 카탈로그 메타데이터 검증
        cat_hit = check_known_catalog("ADAkASAY_WW_animations_TOT.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - Adakasay")
        self.assertEqual(cat_hit["creator"], "Adakasay")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - Adakasay")
        self.assertEqual(cat_hit["version"], "2026.11.04")
        self.assertEqual(cat_hit["option_modal_mode"], "multi_file_select")
        self.assertTrue(cat_hit["requires_option_modal"])
        self.assertTrue(cat_hit["is_ww_animation"])
        self.assertEqual(
            [a["file_name"] for a in cat_hit["optional_addons"]],
            [
                "ADAkASAY_WW_animations_TOT.package",
                "ADAkASAY_WW_animations_LL_.package",
                "ADAkASAY_WW_animations_LL_p2.package",
                "ADAkASAY_WW_animations_STRAPON.package",
            ],
        )

        page_url = (
            "https://www.loverslab.com/files/file/"
            "34506-adakasays-wickedwhims-animations-%E2%80%8B%E2%80%8B-update-november-4th/"
        )

        # 2) 로컬 스캔 시 다중 파일 2개 설치 -> 단일 카드로 묶이고 2026.11.04 최신 버전 표시
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods_dir = root / "Mods"
            anim_dir = mods_dir / "WickedWhims" / "Animations" / "Adakasay"
            anim_dir.mkdir(parents=True)

            local_tot = anim_dir / "ADAkASAY_WW_animations_TOT.package"
            local_ll = anim_dir / "ADAkASAY_WW_animations_LL_.package"
            _build_minimal_dbpf_package(local_tot, [_ww_anim_xml("Adakasay", "TOT Pack")])
            _build_minimal_dbpf_package(local_ll, [_ww_anim_xml("Adakasay", "LL Pack")])

            units = ModScanner(mods_dir).scan_updatable_mod_units()
            self.assertEqual(len(units), 1)
            unit = units[0]
            self.assertEqual(unit["group_key"], "cat:WW Animation - Adakasay")
            self.assertEqual(len(unit["unit_files"]), 2)

            api = app_main.Sims4ModUpdaterAPI(base_dir=root)
            updater = ModUpdater(
                mods_folder=mods_dir,
                manifest_path=root / "mods_manifest.json",
                backup_manager=BackupManager(root / "backups"),
            )

            _, bundle = api._build_mod_entry(
                idx=1,
                unit=unit,
                updater=updater,
                duplicate_map={},
                check_remote=False,
                manifest_ver_map={},
            )
            entry = bundle["entry"]
            self.assertEqual(entry["name"], "WW Animation - Adakasay")
            self.assertEqual(entry["author"], "Adakasay")
            self.assertEqual(entry["currentVersion"], "2026.11.04")
            self.assertEqual(entry["optionModalMode"], "multi_file_select")
            self.assertEqual(entry["selectedVariant"], "download_mode:all")
            self.assertTrue(entry["isWwAnimation"])

            # 3) LoversLab do=download 4파일 목록 추출 검증 (mock HTML)
            dl_urls = [
                f"{page_url}?do=download&confirm=1&r=101",
                f"{page_url}?do=download&confirm=1&r=102",
                f"{page_url}?do=download&confirm=1&r=103",
                f"{page_url}?do=download&confirm=1&r=104",
            ]
            dl_file_names = [
                "ADAkASAY_WW_animations_TOT.package",
                "ADAkASAY_WW_animations_LL_.package",
                "ADAkASAY_WW_animations_LL_p2.package",
                "ADAkASAY_WW_animations_STRAPON.package",
            ]

            class _MockResp:
                def __init__(self, status_code: int, text: str, url: str, headers: dict[str, str] | None = None) -> None:
                    self.status_code = status_code
                    self.text = text
                    self.url = url
                    self.encoding = "utf-8"
                    self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}

                def iter_content(self, chunk_size: int = 16384):
                    yield self.text.encode("utf-8")

                def close(self) -> None:
                    pass

            main_html = f"""
            <html>
              <head><title>ADAKASAY's WickedWhims Animations - Update November 4th - LoversLab</title></head>
              <body>
                <h1 class="ipsType_pageTitle">ADAKASAY's WickedWhims Animations - Update November 4th</h1>
                <a data-action="download" href="{page_url}?do=download">Download This File</a>
              </body>
            </html>
            """
            rows_html = "".join(
                f"""
                <li class="ipsDataItem">
                  <div class="ipsDataItem_main"><span>{fn}</span></div>
                  <div class="ipsDataItem_generic"><a href="{u}">Download</a></div>
                </li>
                """
                for fn, u in zip(dl_file_names, dl_urls)
            )
            dl_list_html = f"<html><body><ul>{rows_html}</ul></body></html>"

            class _MockSess:
                def __init__(self) -> None:
                    self.headers = {}

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def get(self, target_url: str, **kwargs):
                    if "do=download" in target_url and "confirm=1" not in target_url:
                        return _MockResp(200, dl_list_html, f"{page_url}?do=download")
                    return _MockResp(200, main_html, page_url)

            with patch("src.finder.SafeHttpsSession", return_value=_MockSess()):
                inspected = inspect_remote_mod_page(page_url, target_mod_name="ADAkASAY_WW_animations_TOT.package")

            self.assertEqual(inspected["status"], "free_direct")
            self.assertEqual(inspected["all_files"], list(zip(dl_file_names, dl_urls)))

            # 4) 원격 파일 4종 준비 후 '전체 다운로드' vs '선택 다운로드(다중 선택)' 검증
            remote_sources = {}
            for r_fn in dl_file_names:
                src_p = root / f"remote_{r_fn}"
                _build_minimal_dbpf_package(src_p, [_ww_anim_xml("Adakasay", f"Updated {r_fn}")])
                remote_sources[r_fn] = src_p

            all_remote_files = [
                (fn, f"https://cdn.example.invalid/adakasay/{fn}")
                for fn in dl_file_names
            ]

            def _fake_download(url, dest_path, **kwargs):
                for fn, r_url in all_remote_files:
                    if url == r_url:
                        shutil.copy2(remote_sources[fn], dest_path)
                        return dest_path
                raise AssertionError(f"Unexpected download URL: {url}")

            mod_cfg = {
                "name": unit["primary_file_name"],
                "file_path": unit["primary_file_path"],
                "install_folder": unit["install_folder"],
                "unit_files": unit["unit_files"],
                "source_type": "generic_web",
            }
            base_update_info = {
                "latest_version": "LoversLab (2026.11.04)",
                "download_url": all_remote_files[0][1],
                "asset_name": all_remote_files[0][0],
                "page_url": page_url,
                "all_remote_files": all_remote_files,
                "option_modal_mode": "multi_file_select",
                "is_multi_file_bundle": True,
            }

            # 4-a) 전체 다운로드: 4개 모두 설치 확인
            all_info = dict(base_update_info, selected_variant="download_mode:all")
            with patch("src.updater.download_file", side_effect=_fake_download):
                installed_all = updater.update_mod(mod_cfg, all_info, overwrite_mode="all")

            self.assertEqual(set(installed_all), set(dl_file_names))
            for fn in dl_file_names:
                self.assertTrue((anim_dir / fn).exists(), f"Missing {fn}")

            # 4-b) 선택 다운로드 (다중 선택 2개): LL_와 STRAPON만 다운로드·설치되고 TOT·LL_p2는 삭제되지 않아야 함
            downloaded_urls: list[str] = []

            def _track_download(url, dest_path, **kwargs):
                downloaded_urls.append(url)
                return _fake_download(url, dest_path, **kwargs)

            sel_info = dict(
                base_update_info,
                selected_variant="download_mode:select",
                selected_addons=[
                    "ADAkASAY_WW_animations_LL_.package",
                    "ADAkASAY_WW_animations_STRAPON.package",
                ],
            )
            with patch("src.updater.download_file", side_effect=_track_download):
                installed_sel = updater.update_mod(mod_cfg, sel_info, overwrite_mode="all")

            self.assertEqual(
                set(installed_sel),
                {
                    "ADAkASAY_WW_animations_LL_.package",
                    "ADAkASAY_WW_animations_STRAPON.package",
                },
            )
            self.assertEqual(len(downloaded_urls), 2)
            self.assertTrue((anim_dir / "ADAkASAY_WW_animations_TOT.package").exists())
            self.assertTrue((anim_dir / "ADAkASAY_WW_animations_LL_p2.package").exists())

    def test_aftermathdna_catalog_and_loverslab_inspector(self) -> None:
        from src.finder import inspect_remote_mod_page

        # 1) 카탈로그 메타데이터 검증
        cat_hit = check_known_catalog("WW_AftermathDNA_Animations.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - AftermathDNA")
        self.assertEqual(cat_hit["creator"], "AftermathDNA")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - AftermathDNA")
        self.assertEqual(cat_hit["version"], "1.0.13")
        self.assertTrue(cat_hit["is_ww_animation"])
        page_url = (
            "https://www.loverslab.com/files/file/"
            "35783-the-sims-4-aftermathdnas-animations-for-wicked-whims/"
        )
        self.assertEqual(cat_hit["primary_url"], page_url)

        # 2) LoversLab 표준 IPS4 do=download 응답 시 WW_AftermathDNA_Animations.package 추출 검증
        dl_confirm_url = f"{page_url}?do=download&confirm=1&r=777"

        class _MockResp:
            def __init__(self, status_code: int, text: str, url: str, headers: dict[str, str] | None = None) -> None:
                self.status_code = status_code
                self.text = text
                self.url = url
                self.encoding = "utf-8"
                self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}

            def iter_content(self, chunk_size: int = 16384):
                yield self.text.encode("utf-8")

            def close(self) -> None:
                pass

        main_html = (
            '<html><head><title>The Sims 4: AftermathDNA\'s Animations for Wicked Whims 1.0.13</title></head><body>'
            f'<a href="{page_url}?do=download">Download This File</a></body></html>'
        )
        dl_list_html = (
            '<html><body><ul><li class="ipsDataItem">'
            '<div class="ipsDataItem_main"><span>WW_AftermathDNA_Animations.package</span></div>'
            f'<div class="ipsDataItem_generic"><a href="{dl_confirm_url}">Download</a></div>'
            '</li></ul></body></html>'
        )

        class _MockSess:
            def __init__(self) -> None:
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, target_url: str, **kwargs):
                if "do=download" in target_url:
                    return _MockResp(200, dl_list_html, f"{page_url}?do=download")
                return _MockResp(200, main_html, page_url)

        with patch("src.finder.SafeHttpsSession", return_value=_MockSess()):
            res = inspect_remote_mod_page(page_url, target_mod_name="WW_AftermathDNA_Animations.package")

        self.assertEqual(res["status"], "free_direct")
        self.assertEqual(res["file_name"], "WW_AftermathDNA_Animations.package")
        self.assertEqual(res["download_url"], dl_confirm_url)
        self.assertEqual(res["version"], "1.0.13")

    def test_alchemist_catalog_multi_file_all_and_selective_download(self) -> None:
        import shutil
        from src.backup import BackupManager
        from src.finder import inspect_remote_mod_page

        # 1) 카탈로그 메타데이터 검증
        cat_hit = check_known_catalog("WW_AlchemistAnimations.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - Alchemist")
        self.assertEqual(cat_hit["creator"], "Alchemist")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - Alchemist")
        self.assertEqual(cat_hit["version"], "2026.11.25")
        self.assertEqual(cat_hit["option_modal_mode"], "multi_file_select")
        self.assertTrue(cat_hit["requires_option_modal"])
        self.assertTrue(cat_hit["is_ww_animation"])
        self.assertEqual(
            [a["file_name"] for a in cat_hit["optional_addons"]],
            [
                "WW_AlchemistAnimations.package",
                "WW_AlchemistAnimations_Femdom.package",
                "WW_AlchemistAnimations_Cuckold.package",
            ],
        )

        # 일반 판타지/연금술 모드가 WW Animation - Alchemist로 오매칭되지 않는지 검증
        self.assertIsNone(check_known_catalog("AlchemistCareerMod.package"))

        page_url = (
            "https://www.loverslab.com/files/file/"
            "30558-%E2%9B%A7-alchemists-animations-%E2%9B%A7-with-sound-effects/"
        )
        self.assertEqual(cat_hit["primary_url"], page_url)

        # 2) 로컬 스캔 시 다중 파일 2개 설치 -> 단일 카드로 묶이고 2026.11.25 표시
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods_dir = root / "Mods"
            anim_dir = mods_dir / "WickedWhims" / "Animations" / "Alchemist"
            anim_dir.mkdir(parents=True)

            local_base = anim_dir / "WW_AlchemistAnimations.package"
            local_femdom = anim_dir / "WW_AlchemistAnimations_Femdom.package"
            _build_minimal_dbpf_package(local_base, [_ww_anim_xml("Alchemist", "Base Pack")])
            _build_minimal_dbpf_package(local_femdom, [_ww_anim_xml("Alchemist", "Femdom Pack")])

            units = ModScanner(mods_dir).scan_updatable_mod_units()
            self.assertEqual(len(units), 1)
            unit = units[0]
            self.assertEqual(unit["group_key"], "cat:WW Animation - Alchemist")
            self.assertEqual(len(unit["unit_files"]), 2)

            api = app_main.Sims4ModUpdaterAPI(base_dir=root)
            updater = ModUpdater(
                mods_folder=mods_dir,
                manifest_path=root / "mods_manifest.json",
                backup_manager=BackupManager(root / "backups"),
            )

            _, bundle = api._build_mod_entry(
                idx=1,
                unit=unit,
                updater=updater,
                duplicate_map={},
                check_remote=False,
                manifest_ver_map={},
            )
            entry = bundle["entry"]
            self.assertEqual(entry["name"], "WW Animation - Alchemist")
            self.assertEqual(entry["author"], "Alchemist")
            self.assertEqual(entry["currentVersion"], "2026.11.25")
            self.assertEqual(entry["optionModalMode"], "multi_file_select")
            self.assertEqual(entry["selectedVariant"], "download_mode:all")
            self.assertTrue(entry["isWwAnimation"])

            # 3) LoversLab do=download 3파일 목록 추출 검증 (mock HTML)
            dl_urls = [
                f"{page_url}?do=download&confirm=1&r=201",
                f"{page_url}?do=download&confirm=1&r=202",
                f"{page_url}?do=download&confirm=1&r=203",
            ]
            dl_file_names = [
                "WW_AlchemistAnimations.package",
                "WW_AlchemistAnimations_Femdom.package",
                "WW_AlchemistAnimations_Cuckold.package",
            ]

            class _MockResp:
                def __init__(self, status_code: int, text: str, url: str, headers: dict[str, str] | None = None) -> None:
                    self.status_code = status_code
                    self.text = text
                    self.url = url
                    self.encoding = "utf-8"
                    self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}

                def iter_content(self, chunk_size: int = 16384):
                    yield self.text.encode("utf-8")

                def close(self) -> None:
                    pass

            main_html = f"""
            <html>
              <head><title>⛧ Alchemist's Animations ⛧ (With Sound Effects) - LoversLab</title></head>
              <body>
                <h1 class="ipsType_pageTitle">⛧ Alchemist's Animations ⛧ (With Sound Effects)</h1>
                <a data-action="download" href="{page_url}?do=download">Download This File</a>
              </body>
            </html>
            """
            rows_html = "".join(
                f"""
                <li class="ipsDataItem">
                  <div class="ipsDataItem_main"><span>{fn}</span></div>
                  <div class="ipsDataItem_generic"><a href="{u}">Download</a></div>
                </li>
                """
                for fn, u in zip(dl_file_names, dl_urls)
            )
            dl_list_html = f"<html><body><ul>{rows_html}</ul></body></html>"

            class _MockSess:
                def __init__(self) -> None:
                    self.headers = {}

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def get(self, target_url: str, **kwargs):
                    if "do=download" in target_url and "confirm=1" not in target_url:
                        return _MockResp(200, dl_list_html, f"{page_url}?do=download")
                    return _MockResp(200, main_html, page_url)

            with patch("src.finder.SafeHttpsSession", return_value=_MockSess()):
                inspected = inspect_remote_mod_page(page_url, target_mod_name="WW_AlchemistAnimations.package")

            self.assertEqual(inspected["status"], "free_direct")
            self.assertEqual(inspected["all_files"], list(zip(dl_file_names, dl_urls)))

            # 4) 원격 파일 3종 준비 후 '전체 다운로드' vs '선택 다운로드(다중 선택)' 검증
            remote_sources = {}
            for r_fn in dl_file_names:
                src_p = root / f"remote_{r_fn}"
                _build_minimal_dbpf_package(src_p, [_ww_anim_xml("Alchemist", f"Updated {r_fn}")])
                remote_sources[r_fn] = src_p

            all_remote_files = [
                (fn, f"https://cdn.example.invalid/alchemist/{fn}")
                for fn in dl_file_names
            ]

            def _fake_download(url, dest_path, **kwargs):
                for fn, r_url in all_remote_files:
                    if url == r_url:
                        shutil.copy2(remote_sources[fn], dest_path)
                        return dest_path
                raise AssertionError(f"Unexpected download URL: {url}")

            mod_cfg = {
                "name": unit["primary_file_name"],
                "file_path": unit["primary_file_path"],
                "install_folder": unit["install_folder"],
                "unit_files": unit["unit_files"],
                "source_type": "generic_web",
            }
            base_update_info = {
                "latest_version": "LoversLab (2026.11.25)",
                "download_url": all_remote_files[0][1],
                "asset_name": all_remote_files[0][0],
                "page_url": page_url,
                "all_remote_files": all_remote_files,
                "option_modal_mode": "multi_file_select",
                "is_multi_file_bundle": True,
            }

            # 4-a) 전체 다운로드: 3개 모두 설치 확인
            all_info = dict(base_update_info, selected_variant="download_mode:all")
            with patch("src.updater.download_file", side_effect=_fake_download):
                installed_all = updater.update_mod(mod_cfg, all_info, overwrite_mode="all")

            self.assertEqual(set(installed_all), set(dl_file_names))
            for fn in dl_file_names:
                self.assertTrue((anim_dir / fn).exists(), f"Missing {fn}")

            # 4-b) 선택 다운로드 (다중 선택 2개): Femdom과 Cuckold만 다운로드·설치되고 기본 파일은 삭제되지 않아야 함
            downloaded_urls: list[str] = []

            def _track_download(url, dest_path, **kwargs):
                downloaded_urls.append(url)
                return _fake_download(url, dest_path, **kwargs)

            sel_info = dict(
                base_update_info,
                selected_variant="download_mode:select",
                selected_addons=[
                    "WW_AlchemistAnimations_Femdom.package",
                    "WW_AlchemistAnimations_Cuckold.package",
                ],
            )
            with patch("src.updater.download_file", side_effect=_track_download):
                installed_sel = updater.update_mod(mod_cfg, sel_info, overwrite_mode="all")

            self.assertEqual(
                set(installed_sel),
                {
                    "WW_AlchemistAnimations_Femdom.package",
                    "WW_AlchemistAnimations_Cuckold.package",
                },
            )
            self.assertEqual(len(downloaded_urls), 2)
            self.assertTrue((anim_dir / "WW_AlchemistAnimations.package").exists())

    def test_amateurhour47_catalog_and_loverslab_inspector(self) -> None:
        from src.backup import BackupManager
        from src.finder import inspect_remote_mod_page

        # 1) 카탈로그 메타데이터 검증 (파일명이 제작자명.package 형태인 경우 포함)
        cat_hit = check_known_catalog("AmateurHour47.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - AmateurHour47")
        self.assertEqual(cat_hit["creator"], "AmateurHour47")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - AmateurHour47")
        self.assertEqual(cat_hit["version"], "2024.04.20")
        self.assertTrue(cat_hit["is_ww_animation"])
        page_url = (
            "https://www.loverslab.com/files/file/"
            "31633-amateurhour47s-thighjob-animations-custom-sfx-%E2%A7%96/"
        )
        self.assertEqual(cat_hit["primary_url"], page_url)

        # 2) 로컬 스캔 시 Mods/WickedWhims/Animations/AmateurHour47.package가 CC로 제외되지 않고 정상 수집되는지 검증
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods_dir = root / "Mods"
            anim_dir = mods_dir / "WickedWhims" / "Animations"
            anim_dir.mkdir(parents=True)

            local_pkg = anim_dir / "AmateurHour47.package"
            _build_minimal_dbpf_package(local_pkg, [_ww_anim_xml("AmateurHour47", "Thighjob Pack")])

            units = ModScanner(mods_dir).scan_updatable_mod_units()
            self.assertEqual(len(units), 1)
            unit = units[0]
            self.assertEqual(unit["primary_file_name"], "AmateurHour47.package")

            api = app_main.Sims4ModUpdaterAPI(base_dir=root)
            updater = ModUpdater(
                mods_folder=mods_dir,
                manifest_path=root / "mods_manifest.json",
                backup_manager=BackupManager(root / "backups"),
            )
            _, bundle = api._build_mod_entry(
                idx=1,
                unit=unit,
                updater=updater,
                duplicate_map={},
                check_remote=False,
                manifest_ver_map={},
            )
            entry = bundle["entry"]
            self.assertEqual(entry["name"], "WW Animation - AmateurHour47")
            self.assertEqual(entry["author"], "AmateurHour47")
            self.assertEqual(entry["currentVersion"], "2024.04.20")
            self.assertTrue(entry["isWwAnimation"])

        # 3) LoversLab 표준 IPS4 do=download 응답 시 AmateurHour47.package 추출 검증
        dl_confirm_url = f"{page_url}?do=download&confirm=1&r=888"

        class _MockResp:
            def __init__(self, status_code: int, text: str, url: str, headers: dict[str, str] | None = None) -> None:
                self.status_code = status_code
                self.text = text
                self.url = url
                self.encoding = "utf-8"
                self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}

            def iter_content(self, chunk_size: int = 16384):
                yield self.text.encode("utf-8")

            def close(self) -> None:
                pass

        main_html = (
            "<html><head><title>AmateurHour47's Thighjob Animations (Custom SFX ⧖)</title></head><body>"
            f'<a href="{page_url}?do=download">Download This File</a></body></html>'
        )
        dl_list_html = (
            '<html><body><ul><li class="ipsDataItem">'
            '<div class="ipsDataItem_main"><span>AmateurHour47.package</span></div>'
            f'<div class="ipsDataItem_generic"><a href="{dl_confirm_url}">Download</a></div>'
            '</li></ul></body></html>'
        )

        class _MockSess:
            def __init__(self) -> None:
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, target_url: str, **kwargs):
                if "do=download" in target_url:
                    return _MockResp(200, dl_list_html, f"{page_url}?do=download")
                return _MockResp(200, main_html, page_url)

        with patch("src.finder.SafeHttpsSession", return_value=_MockSess()):
            res = inspect_remote_mod_page(page_url, target_mod_name="AmateurHour47.package")

        self.assertEqual(res["status"], "free_direct")
        self.assertEqual(res["file_name"], "AmateurHour47.package")
        self.assertEqual(res["download_url"], dl_confirm_url)

    def test_amorzinho_catalog_multi_file_all_and_selective_download(self) -> None:
        import shutil
        from src.backup import BackupManager
        from src.finder import inspect_remote_mod_page

        expected_files = [
            "climax_missionario.package",
            "oral_otesouro.package",
            "preliminar_amorzinho.package",
            "vaginal_abraco.package",
            "vaginal_borboleta.package",
            "vaginal_cavalgada.package",
            "Vaginal_CavalgadaSentado.package",
            "Vaginal_DeLadinho.package",
            "Vaginal_DeQuatro.package",
            "Vaginal_DeQuatro2.package",
            "Vaginal_Farao.package",
            "Vaginal_PousoForcado.package",
            "Vaginal_T_Invertido.package",
            "Vaginal_T_Invertido2.package",
        ]

        # 1) 카탈로그 메타데이터 검증
        cat_hit = check_known_catalog("Vaginal_DeQuatro.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - amorzinho")
        self.assertEqual(cat_hit["creator"], "amorzinho")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - amorzinho")
        self.assertEqual(cat_hit["version"], "1.0.0")
        self.assertEqual(cat_hit["option_modal_mode"], "multi_file_select")
        self.assertTrue(cat_hit["requires_option_modal"])
        self.assertTrue(cat_hit["is_ww_animation"])
        self.assertEqual([a["file_name"] for a in cat_hit["optional_addons"]], expected_files)

        page_url = "https://www.loverslab.com/files/file/15118-teste-amorzinho/"
        self.assertEqual(cat_hit["primary_url"], page_url)

        # 2) 로컬 스캔 시 다중 파일 2개 설치 -> 단일 카드로 묶이고 1.0.0 표시
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods_dir = root / "Mods"
            anim_dir = mods_dir / "WickedWhims" / "Animations" / "amorzinho"
            anim_dir.mkdir(parents=True)

            local_f1 = anim_dir / "Vaginal_DeQuatro.package"
            local_f2 = anim_dir / "Vaginal_T_Invertido.package"
            _build_minimal_dbpf_package(local_f1, [_ww_anim_xml("amorzinho", "DeQuatro")])
            _build_minimal_dbpf_package(local_f2, [_ww_anim_xml("amorzinho", "T_Invertido")])

            units = ModScanner(mods_dir).scan_updatable_mod_units()
            self.assertEqual(len(units), 1)
            unit = units[0]
            self.assertEqual(unit["group_key"], "cat:WW Animation - amorzinho")
            self.assertEqual(len(unit["unit_files"]), 2)

            api = app_main.Sims4ModUpdaterAPI(base_dir=root)
            updater = ModUpdater(
                mods_folder=mods_dir,
                manifest_path=root / "mods_manifest.json",
                backup_manager=BackupManager(root / "backups"),
            )

            _, bundle = api._build_mod_entry(
                idx=1,
                unit=unit,
                updater=updater,
                duplicate_map={},
                check_remote=False,
                manifest_ver_map={},
            )
            entry = bundle["entry"]
            self.assertEqual(entry["name"], "WW Animation - amorzinho")
            self.assertEqual(entry["author"], "amorzinho")
            self.assertEqual(entry["currentVersion"], "v1.0.0")
            self.assertEqual(entry["optionModalMode"], "multi_file_select")
            self.assertEqual(entry["selectedVariant"], "download_mode:all")
            self.assertTrue(entry["isWwAnimation"])

            # 3) LoversLab do=download 14파일 목록 추출 검증 (mock HTML)
            dl_urls = [f"{page_url}?do=download&confirm=1&r={300 + i}" for i in range(len(expected_files))]

            class _MockResp:
                def __init__(self, status_code: int, text: str, url: str, headers: dict[str, str] | None = None) -> None:
                    self.status_code = status_code
                    self.text = text
                    self.url = url
                    self.encoding = "utf-8"
                    self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}

                def iter_content(self, chunk_size: int = 16384):
                    yield self.text.encode("utf-8")

                def close(self) -> None:
                    pass

            main_html = f"""
            <html>
              <head><title>Teste Amorzinho 1.0.0 - LoversLab</title></head>
              <body>
                <h1 class="ipsType_pageTitle">Teste Amorzinho</h1>
                <a data-action="download" href="{page_url}?do=download">Download This File</a>
              </body>
            </html>
            """
            rows_html = "".join(
                f"""
                <li class="ipsDataItem">
                  <div class="ipsDataItem_main"><span>{fn}</span></div>
                  <div class="ipsDataItem_generic"><a href="{u}">Download</a></div>
                </li>
                """
                for fn, u in zip(expected_files, dl_urls)
            )
            dl_list_html = f"<html><body><ul>{rows_html}</ul></body></html>"

            class _MockSess:
                def __init__(self) -> None:
                    self.headers = {}

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def get(self, target_url: str, **kwargs):
                    if "do=download" in target_url and "confirm=1" not in target_url:
                        return _MockResp(200, dl_list_html, f"{page_url}?do=download")
                    return _MockResp(200, main_html, page_url)

            with patch("src.finder.SafeHttpsSession", return_value=_MockSess()):
                inspected = inspect_remote_mod_page(page_url, target_mod_name="Vaginal_DeQuatro.package")

            self.assertEqual(inspected["status"], "free_direct")
            self.assertEqual(inspected["all_files"], list(zip(expected_files, dl_urls)))

            # 4) 원격 파일 14종 준비 후 '전체 다운로드' vs '선택 다운로드(다중 선택)' 검증
            remote_sources = {}
            for r_fn in expected_files:
                src_p = root / f"remote_{r_fn}"
                _build_minimal_dbpf_package(src_p, [_ww_anim_xml("amorzinho", f"Updated {r_fn}")])
                remote_sources[r_fn] = src_p

            all_remote_files = [
                (fn, f"https://cdn.example.invalid/amorzinho/{fn}")
                for fn in expected_files
            ]

            def _fake_download(url, dest_path, **kwargs):
                for fn, r_url in all_remote_files:
                    if url == r_url:
                        shutil.copy2(remote_sources[fn], dest_path)
                        return dest_path
                raise AssertionError(f"Unexpected download URL: {url}")

            mod_cfg = {
                "name": unit["primary_file_name"],
                "file_path": unit["primary_file_path"],
                "install_folder": unit["install_folder"],
                "unit_files": unit["unit_files"],
                "source_type": "generic_web",
            }
            base_update_info = {
                "latest_version": "LoversLab (1.0.0)",
                "download_url": all_remote_files[0][1],
                "asset_name": all_remote_files[0][0],
                "page_url": page_url,
                "all_remote_files": all_remote_files,
                "option_modal_mode": "multi_file_select",
                "is_multi_file_bundle": True,
            }

            # 4-a) 전체 다운로드: 14개 모두 설치 확인
            all_info = dict(base_update_info, selected_variant="download_mode:all")
            with patch("src.updater.download_file", side_effect=_fake_download):
                installed_all = updater.update_mod(mod_cfg, all_info, overwrite_mode="all")

            self.assertEqual(set(installed_all), set(expected_files))
            for fn in expected_files:
                self.assertTrue((anim_dir / fn).exists(), f"Missing {fn}")

            # 4-b) 선택 다운로드 (다중 선택 3개): DeQuatro2 / T_Invertido2 포함 3개만 설치되고 기존 파일은 보존되어야 함
            downloaded_urls: list[str] = []

            def _track_download(url, dest_path, **kwargs):
                downloaded_urls.append(url)
                return _fake_download(url, dest_path, **kwargs)

            sel_targets = [
                "climax_missionario.package",
                "Vaginal_DeQuatro2.package",
                "Vaginal_T_Invertido2.package",
            ]
            sel_info = dict(
                base_update_info,
                selected_variant="download_mode:select",
                selected_addons=sel_targets,
            )
            with patch("src.updater.download_file", side_effect=_track_download):
                installed_sel = updater.update_mod(mod_cfg, sel_info, overwrite_mode="all")

            self.assertEqual(set(installed_sel), set(sel_targets))
            self.assertEqual(len(downloaded_urls), 3)
            self.assertTrue((anim_dir / "Vaginal_DeQuatro.package").exists())
            self.assertTrue((anim_dir / "Vaginal_T_Invertido.package").exists())

    def test_amra72_catalog_zip_archive_multi_file_all_and_selective_download(self) -> None:
        import zipfile
        from src.backup import BackupManager
        from src.finder import inspect_remote_mod_page

        expected_inner_files = [
            "WW_Amra72_Animations.package",
            "WW_Amra72_Animations_AP.package",
            "WW_Amra72_Custom_Sounds.package",
        ]
        target_zip_name = "WW_Amra72_Animations_Update_(12.04.2023).zip"
        old_zip_name = "WW_Amra72_Animations_Base_Archive.zip"

        # 1) 카탈로그 메타데이터 검증
        cat_hit = check_known_catalog("WW_Amra72_Animations.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - Amra72")
        self.assertEqual(cat_hit["creator"], "Amra72")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - Amra72")
        self.assertEqual(cat_hit["version"], "2023.04.12")
        self.assertEqual(cat_hit["preferred_archive_name"], target_zip_name)
        self.assertEqual(cat_hit["option_modal_mode"], "multi_file_select")
        self.assertTrue(cat_hit["requires_option_modal"])
        self.assertTrue(cat_hit["is_ww_animation"])
        self.assertEqual([a["file_name"] for a in cat_hit["optional_addons"]], expected_inner_files)

        page_url = "https://www.loverslab.com/files/file/3140-wip-amra72s-sex-animation-for-wickedwhims/"
        self.assertEqual(cat_hit["primary_url"], page_url)

        # 2) LoversLab 2개 ZIP 목록 중 WW_Amra72_Animations_Update_(12.04.2023).zip만 선택 추출되는지 검증
        dl_url_old = f"{page_url}?do=download&confirm=1&r=401"
        dl_url_target = f"{page_url}?do=download&confirm=1&r=402"

        class _MockResp:
            def __init__(self, status_code: int, text: str, url: str, headers: dict[str, str] | None = None) -> None:
                self.status_code = status_code
                self.text = text
                self.url = url
                self.encoding = "utf-8"
                self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}

            def iter_content(self, chunk_size: int = 16384):
                yield self.text.encode("utf-8")

            def close(self) -> None:
                pass

        main_html = f"""
        <html>
          <head><title>[WIP] Amra72's Sex Animation for WickedWhims - LoversLab</title></head>
          <body>
            <a data-action="download" href="{page_url}?do=download">Download This File</a>
          </body>
        </html>
        """
        dl_list_html = f"""
        <html><body><ul>
          <li class="ipsDataItem">
            <div class="ipsDataItem_main"><span>{old_zip_name}</span></div>
            <div class="ipsDataItem_generic"><a href="{dl_url_old}">Download</a></div>
          </li>
          <li class="ipsDataItem">
            <div class="ipsDataItem_main"><span>{target_zip_name}</span></div>
            <div class="ipsDataItem_generic"><a href="{dl_url_target}">Download</a></div>
          </li>
        </ul></body></html>
        """

        class _MockSess:
            def __init__(self) -> None:
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, target_url: str, **kwargs):
                if "do=download" in target_url and "confirm=1" not in target_url:
                    return _MockResp(200, dl_list_html, f"{page_url}?do=download")
                return _MockResp(200, main_html, page_url)

        with patch("src.finder.SafeHttpsSession", return_value=_MockSess()):
            inspected = inspect_remote_mod_page(page_url, target_mod_name="WW_Amra72_Animations.package")

        self.assertEqual(inspected["status"], "free_direct")
        self.assertEqual(inspected["file_name"], target_zip_name)
        self.assertEqual(inspected["download_url"], dl_url_target)
        self.assertEqual(inspected["all_files"], [(target_zip_name, dl_url_target)])

        # 3) 로컬 스캔 및 실제 ZIP 내부 3개 파일에 대한 전체/선택(다중 선택) 다운로드 검증
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods_dir = root / "Mods"
            anim_dir = mods_dir / "WickedWhims" / "Animations" / "Amra72"
            anim_dir.mkdir(parents=True)

            local_base = anim_dir / "WW_Amra72_Animations.package"
            _build_minimal_dbpf_package(local_base, [_ww_anim_xml("Amra72", "Old Base")])

            units = ModScanner(mods_dir).scan_updatable_mod_units()
            self.assertEqual(len(units), 1)
            unit = units[0]
            self.assertEqual(unit["group_key"], "cat:WW Animation - Amra72")

            api = app_main.Sims4ModUpdaterAPI(base_dir=root)
            updater = ModUpdater(
                mods_folder=mods_dir,
                manifest_path=root / "mods_manifest.json",
                backup_manager=BackupManager(root / "backups"),
            )
            _, bundle = api._build_mod_entry(
                idx=1,
                unit=unit,
                updater=updater,
                duplicate_map={},
                check_remote=False,
                manifest_ver_map={},
            )
            entry = bundle["entry"]
            self.assertEqual(entry["name"], "WW Animation - Amra72")
            self.assertEqual(entry["author"], "Amra72")
            self.assertEqual(entry["currentVersion"], "2023.04.12")
            self.assertEqual(entry["optionModalMode"], "multi_file_select")
            self.assertTrue(entry["isWwAnimation"])

            # 3-a) 3개 .package가 담긴 임시 ZIP 생성
            remote_zip = root / target_zip_name
            with zipfile.ZipFile(remote_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for fn in expected_inner_files:
                    src_pkg = root / f"stage_{fn}"
                    _build_minimal_dbpf_package(src_pkg, [_ww_anim_xml("Amra72", f"Updated {fn}")])
                    zf.write(src_pkg, arcname=fn)

            import shutil

            def _fake_zip_download(url, dest_path, **kwargs):
                self.assertEqual(url, dl_url_target)
                shutil.copy2(remote_zip, dest_path)
                return dest_path

            mod_cfg = {
                "name": "WW Animation - Amra72",
                "file_path": unit["primary_file_path"],
                "install_folder": unit["install_folder"],
                "unit_files": unit["unit_files"],
                "source_type": "generic_web",
            }
            base_update_info = {
                "latest_version": "LoversLab (2023.04.12)",
                "download_url": dl_url_target,
                "asset_name": target_zip_name,
                "page_url": page_url,
                "all_remote_files": [(target_zip_name, dl_url_target)],
                "preferred_archive_name": target_zip_name,
                "option_modal_mode": "multi_file_select",
                "is_multi_file_bundle": False,
            }

            # 전체 다운로드: ZIP 내부 3개 모두 설치 확인
            all_info = dict(base_update_info, selected_variant="download_mode:all")
            with patch("src.updater.download_file", side_effect=_fake_zip_download):
                installed_all = updater.update_mod(mod_cfg, all_info, overwrite_mode="all")

            self.assertEqual(set(installed_all), set(expected_inner_files))
            for fn in expected_inner_files:
                self.assertTrue((anim_dir / fn).exists(), f"Missing {fn}")

            # 선택 다운로드 (다중 선택 2개): AP + Custom_Sounds만 새로 설치되고 기존 WW_Amra72_Animations.package는 보존
            (anim_dir / "WW_Amra72_Animations_AP.package").unlink()
            (anim_dir / "WW_Amra72_Custom_Sounds.package").unlink()

            sel_targets = [
                "WW_Amra72_Animations_AP.package",
                "WW_Amra72_Custom_Sounds.package",
            ]
            sel_info = dict(
                base_update_info,
                selected_variant="download_mode:select",
                selected_addons=sel_targets,
            )
            with patch("src.updater.download_file", side_effect=_fake_zip_download):
                installed_sel = updater.update_mod(mod_cfg, sel_info, overwrite_mode="all")

            self.assertEqual(set(installed_sel), set(sel_targets))
            self.assertTrue((anim_dir / "WW_Amra72_Animations.package").exists())
            self.assertTrue((anim_dir / "WW_Amra72_Animations_AP.package").exists())
            self.assertTrue((anim_dir / "WW_Amra72_Custom_Sounds.package").exists())

    def test_anarcis_catalog_and_wickedcc_inspector(self) -> None:
        from src.finder import inspect_remote_mod_page

        # 1) 카탈로그 메타데이터 검증
        cat_hit = check_known_catalog("WW_Anarcis_Animations.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - Anarcis")
        self.assertEqual(cat_hit["creator"], "Anarcis")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - Anarcis")
        self.assertEqual(cat_hit["version"], "2026.11.27")
        self.assertTrue(cat_hit["is_ww_animation"])
        page_url = "https://wicked.cc/animations/anarcis/anarcis-animations-for-wickedwhims/"
        self.assertEqual(cat_hit["primary_url"], page_url)

        # 2) Wicked.cc 페이지에서 직접 다운로드 URL이 free_direct로 추출되는지 검증
        dl_trigger = "https://wicked.cc/download/anarcis-1"
        final_dl = "https://files.wicked.cc/file/wickedcc/WW_Anarcis_Animations.package"

        class _MockResp:
            def __init__(self, status_code: int, text: str, url: str) -> None:
                self.status_code = status_code
                self.text = text
                self.url = url
                self.encoding = "utf-8"

            def close(self) -> None:
                pass

        page_html = f"""
        <html>
          <head><title>Anarcis Animations for WickedWhims - WickedCC</title></head>
          <body>
            <a href="{dl_trigger}">Download</a>
          </body>
        </html>
        """

        class _MockSess:
            def __init__(self) -> None:
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, target_url: str, **kwargs):
                if "/download/" in target_url:
                    return _MockResp(200, "", final_dl)
                return _MockResp(200, page_html, page_url)

        with patch("src.finder.SafeHttpsSession", return_value=_MockSess()):
            res = inspect_remote_mod_page(page_url, target_mod_name="WW_Anarcis_Animations.package")

        self.assertEqual(res["status"], "free_direct")
        self.assertEqual(res["file_name"], "WW_Anarcis_Animations.package")
        self.assertEqual(res["download_url"], final_dl)

    def test_anonny_catalog_and_loverslab_inspector(self) -> None:
        from src.finder import inspect_remote_mod_page

        # 1) 카탈로그 메타데이터 검증
        cat_hit = check_known_catalog("WW_Anonny_Animations.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - Anonny")
        self.assertEqual(cat_hit["creator"], "Anonny")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - Anonny")
        self.assertEqual(cat_hit["version"], "1.7")
        self.assertTrue(cat_hit["is_ww_animation"])
        page_url = "https://www.loverslab.com/files/file/3639-sims-4-anonnys-sex-animations-for-wickedwhims/"
        self.assertEqual(cat_hit["primary_url"], page_url)

        # 2) LoversLab 표준 IPS4 do=download 응답 시 파일 및 버전 1.7이 free_direct로 추출되는지 검증
        dl_confirm_url = f"{page_url}?do=download&confirm=1&r=999"

        class _MockResp:
            def __init__(self, status_code: int, text: str, url: str, headers: dict[str, str] | None = None) -> None:
                self.status_code = status_code
                self.text = text
                self.url = url
                self.encoding = "utf-8"
                self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}

            def iter_content(self, chunk_size: int = 16384):
                yield self.text.encode("utf-8")

            def close(self) -> None:
                pass

        main_html = (
            "<html><head><title>[Sims 4] Anonny's Sex Animations for WickedWhims v1.7</title></head><body>"
            f'<a href="{page_url}?do=download">Download This File</a></body></html>'
        )
        dl_list_html = (
            '<html><body><ul><li class="ipsDataItem">'
            '<div class="ipsDataItem_main"><span>WW_Anonny_Animations_v1.7.package</span></div>'
            f'<div class="ipsDataItem_generic"><a href="{dl_confirm_url}">Download</a></div>'
            '</li></ul></body></html>'
        )

        class _MockSess:
            def __init__(self) -> None:
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, target_url: str, **kwargs):
                if "do=download" in target_url:
                    return _MockResp(200, dl_list_html, f"{page_url}?do=download")
                return _MockResp(200, main_html, page_url)

        with patch("src.finder.SafeHttpsSession", return_value=_MockSess()):
            res = inspect_remote_mod_page(page_url, target_mod_name="WW_Anonny_Animations.package")

        self.assertEqual(res["status"], "free_direct")
        self.assertEqual(res["file_name"], "WW_Anonny_Animations_v1.7.package")
        self.assertEqual(res["download_url"], dl_confirm_url)
        self.assertEqual(res["version"], "1.7")

    def test_artistadebastardo_catalog_metadata(self) -> None:
        from src.finder import label_for_url

        cat_hit = check_known_catalog("WW_ArtistadeBastardo_Animations.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - ArtistadeBastardo")
        self.assertEqual(cat_hit["creator"], "ArtistadeBastardo")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - ArtistadeBastardo")
        self.assertEqual(cat_hit["version"], "1.2.0")
        self.assertTrue(cat_hit["is_ww_animation"])
        page_url = "https://modsfire.com/S4eaS0B7TRa37dP"
        self.assertEqual(cat_hit["primary_url"], page_url)
        self.assertEqual(label_for_url(page_url), "ModsFire")

    def test_artmiel_catalog_metadata(self) -> None:
        cat_hit = check_known_catalog("WW_Artmiel_Animations.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - Artmiel")
        self.assertEqual(cat_hit["creator"], "Artmiel")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - Artmiel")
        self.assertEqual(cat_hit["version"], "5.5")
        self.assertTrue(cat_hit["is_ww_animation"])
        self.assertEqual(cat_hit["primary_url"], "https://modsfire.com/vui05Fs8Cf6jE5J")

    def test_aske_catalog_metadata_and_no_substring_false_positive(self) -> None:
        cat_hit = check_known_catalog("WW_ASKE_Animations.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - ASKE")
        self.assertEqual(cat_hit["creator"], "ASKE")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - ASKE")
        self.assertEqual(cat_hit["version"], "1.4")
        self.assertTrue(cat_hit["is_ww_animation"])
        self.assertEqual(
            cat_hit["primary_url"],
            "https://www.loverslab.com/files/file/8766-aske-sex-animations-070319/",
        )
        # 일반 단어('basket' 등) 내부 부분 문자열 오매칭 방지 검증
        self.assertIsNone(check_known_catalog("PicnicBasketMod.package"))

    def test_asketo_catalog_metadata_and_no_aske_prefix_collision(self) -> None:
        cat_hit = check_known_catalog("WW_asketo_Animations.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - asketo")
        self.assertEqual(cat_hit["creator"], "asketo")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - asketo")
        self.assertEqual(cat_hit["version"], "2020.09.18")
        self.assertTrue(cat_hit["is_ww_animation"])
        self.assertEqual(
            cat_hit["primary_url"],
            "https://www.loverslab.com/files/file/9127-asketos-animations-for-whickedwhims-and-some-objects-for-ts4/",
        )
        # ASKE 항목과의 접두사(ww_aske vs ww_asketo) 충돌 방지 재확인
        aske_hit = check_known_catalog("WW_ASKE_Animations.package")
        self.assertIsNotNone(aske_hit)
        self.assertEqual(aske_hit["matched_catalog"], "WW Animation - ASKE")

    def test_atrois_catalog_and_loverslab_1010_rar_selection(self) -> None:
        from src.finder import inspect_remote_mod_page

        # 1) 카탈로그 메타데이터 검증
        cat_hit = check_known_catalog("WW_ATrois_Animations.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - ATrois")
        self.assertEqual(cat_hit["creator"], "ATrois")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - ATrois")
        self.assertEqual(cat_hit["version"], "2026.08.06")
        self.assertEqual(cat_hit["preferred_archive_name"], "1010.rar")
        self.assertTrue(cat_hit["is_ww_animation"])
        page_url = "https://www.loverslab.com/files/file/4697-sims-4-a-trois-sex-animations-for-ww-0806-ll-and-patreon/"
        self.assertEqual(cat_hit["primary_url"], page_url)

        # 2) LoversLab do=download 응답에 여러 파일이 있을 때 1010.rar만 free_direct로 정확히 추출되는지 검증
        dl_old = f"{page_url}?do=download&confirm=1&r=501"
        dl_1010 = f"{page_url}?do=download&confirm=1&r=502"

        class _MockResp:
            def __init__(self, status_code: int, text: str, url: str, headers: dict[str, str] | None = None) -> None:
                self.status_code = status_code
                self.text = text
                self.url = url
                self.encoding = "utf-8"
                self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}

            def iter_content(self, chunk_size: int = 16384):
                yield self.text.encode("utf-8")

            def close(self) -> None:
                pass

        main_html = (
            "<html><head><title>[Sims 4] A-Trois Sex Animations for WW 08.06 - LoversLab</title></head><body>"
            f'<a href="{page_url}?do=download">Download This File</a></body></html>'
        )
        dl_list_html = (
            '<html><body><ul>'
            '<li class="ipsDataItem"><div class="ipsDataItem_main"><span>old_pack.zip</span></div>'
            f'<div class="ipsDataItem_generic"><a href="{dl_old}">Download</a></div></li>'
            '<li class="ipsDataItem"><div class="ipsDataItem_main"><span>1010.rar</span></div>'
            f'<div class="ipsDataItem_generic"><a href="{dl_1010}">Download</a></div></li>'
            '</ul></body></html>'
        )

        class _MockSess:
            def __init__(self) -> None:
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, target_url: str, **kwargs):
                if "do=download" in target_url:
                    return _MockResp(200, dl_list_html, f"{page_url}?do=download")
                return _MockResp(200, main_html, page_url)

        with patch("src.finder.SafeHttpsSession", return_value=_MockSess()):
            res = inspect_remote_mod_page(page_url, target_mod_name="WW_ATrois_Animations.package")

        self.assertEqual(res["status"], "free_direct")
        self.assertEqual(res["file_name"], "1010.rar")
        self.assertEqual(res["download_url"], dl_1010)
        self.assertEqual(res["all_files"], [("1010.rar", dl_1010)])

    def test_awsome_catalog_metadata(self) -> None:
        cat_hit = check_known_catalog("WW_AWSOME_Animations.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - AWSOME")
        self.assertEqual(cat_hit["creator"], "AWSOME")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - AWSOME")
        self.assertEqual(cat_hit["version"], "2026.11.22")
        self.assertTrue(cat_hit["is_ww_animation"])
        self.assertEqual(
            cat_hit["primary_url"],
            "https://www.patreon.com/awsome1/posts/awsomeanimation-161337996",
        )

    def test_ayone_catalog_and_kemono_inspector(self) -> None:
        from src.finder import inspect_remote_mod_page, label_for_url

        # 1) 카탈로그 메타데이터 검증
        cat_hit = check_known_catalog("WW_AYONE_Animations.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - AYONE")
        self.assertEqual(cat_hit["creator"], "AYONE")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - AYONE")
        self.assertEqual(cat_hit["version"], "2025.01.11")
        self.assertTrue(cat_hit["is_ww_animation"])
        page_url = "https://kemono.cr/patreon/user/64723804/post/114430931"
        self.assertEqual(cat_hit["primary_url"], page_url)
        self.assertEqual(label_for_url(page_url), "Kemono")

        expected_dl = "https://kemono.cr/data/ab/cd/hash1234.package?f=WW_AYONE_Animations.package"

        class _MockResp:
            def __init__(self, status_code: int, text: str, url: str) -> None:
                self.status_code = status_code
                self.text = text
                self.url = url
                self.encoding = "utf-8"

            def json(self):
                import json as _json
                return _json.loads(self.text)

        # 2-a) HTML Downloads 영역의 post__attachment-link에서 추출 검증
        html_with_downloads = f"""
        <html>
          <head><title>AYONE WW Animations | Kemono</title></head>
          <body>
            <h2>Downloads</h2>
            <ul class="post__attachments">
              <li class="post__attachment">
                <a class="post__attachment-link" href="/data/ab/cd/hash1234.package?f=WW_AYONE_Animations.package">
                  Download WW_AYONE_Animations.package
                </a>
              </li>
            </ul>
          </body>
        </html>
        """

        class _MockHtmlSess:
            def __init__(self) -> None:
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, target_url: str, **kwargs):
                return _MockResp(200, html_with_downloads, page_url)

        with patch("src.finder.SafeHttpsSession", return_value=_MockHtmlSess()):
            res_html = inspect_remote_mod_page(page_url, target_mod_name="WW_AYONE_Animations.package")

        self.assertEqual(res_html["status"], "free_direct")
        self.assertEqual(res_html["file_name"], "WW_AYONE_Animations.package")
        self.assertEqual(res_html["download_url"], expected_dl)

        # 2-b) SPA 빈 HTML 응답 시 Kemono /api/v1 폴백 추출 검증
        import json as _json

        spa_html = "<html><head><title>Kemono</title></head><body><div id='root'></div></body></html>"
        api_payload = _json.dumps(
            {
                "post": {
                    "id": "114430931",
                    "title": "AYONE WW Animations",
                    "attachments": [
                        {
                            "name": "WW_AYONE_Animations.package",
                            "path": "/ab/cd/hash1234.package",
                        }
                    ],
                }
            }
        )

        class _MockSpaSess:
            def __init__(self) -> None:
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, target_url: str, **kwargs):
                if "/api/v1/patreon/user/64723804/post/114430931" in target_url:
                    return _MockResp(200, api_payload, target_url)
                return _MockResp(200, spa_html, page_url)

        with patch("src.finder.SafeHttpsSession", return_value=_MockSpaSess()):
            res_api = inspect_remote_mod_page(page_url, target_mod_name="WW_AYONE_Animations.package")

        self.assertEqual(res_api["status"], "free_direct")
        self.assertEqual(res_api["file_name"], "WW_AYONE_Animations.package")
        self.assertEqual(res_api["download_url"], expected_dl)

    def test_azmodan22_catalog_modsfire_inspector_and_two_stage_overlay_update(self) -> None:
        import json
        import shutil
        import zipfile
        from src.backup import BackupManager
        from src.finder import inspect_remote_mod_page, label_for_url

        # 1) 카탈로그 메타데이터 검증
        cat_hit = check_known_catalog("WW_Azmodan22_Animations.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - Azmodan22")
        self.assertEqual(cat_hit["creator"], "Azmodan22")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - Azmodan22")
        self.assertEqual(cat_hit["version"], "2025.02.05")
        self.assertTrue(cat_hit["is_ww_animation"])
        wicked_url = "https://wicked.cc/animations/azmodan22/azmodan22-wickedwhims-sex-animations"
        modsfire_url = "https://modsfire.com/dy5R4F25s834UeD"
        self.assertEqual(cat_hit["primary_url"], wicked_url)
        self.assertEqual([lk[2] for lk in cat_hit["candidate_links"]], [wicked_url, modsfire_url])
        self.assertEqual(len(cat_hit["post_install_overlays"]), 1)
        self.assertEqual(cat_hit["post_install_overlays"][0]["url"], modsfire_url)
        self.assertEqual(cat_hit["post_install_overlays"][0]["version"], "2025.02.05")
        self.assertEqual(label_for_url(modsfire_url), "ModsFire")

        # 2) _inspect_modsfire_page mock 테스트
        mf_dl_trigger = "https://modsfire.com/d/dy5R4F25s834UeD"
        mf_final_dl = "https://cdn.modsfire.com/files/WW_Azmodan22_Gold_Normal.package"

        class _MockResp:
            def __init__(self, status_code: int, text: str, url: str, headers: dict[str, str] | None = None) -> None:
                self.status_code = status_code
                self.text = text
                self.url = url
                self.encoding = "utf-8"
                self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}

            def close(self) -> None:
                pass

        mf_html = f"""
        <html>
          <head><title>WW_Azmodan22_Gold_Normal.package | ModsFire</title></head>
          <body><a class="btn" href="{mf_dl_trigger}">Download File</a></body>
        </html>
        """

        class _MockMfSess:
            def __init__(self) -> None:
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, target_url: str, **kwargs):
                if "/d/" in target_url:
                    return _MockResp(
                        200,
                        "",
                        mf_final_dl,
                        headers={
                            "Content-Type": "application/octet-stream",
                            "Content-Disposition": 'attachment; filename="WW_Azmodan22_Gold_Normal.package"',
                        },
                    )
                return _MockResp(200, mf_html, modsfire_url)

        with patch("src.finder.SafeHttpsSession", return_value=_MockMfSess()):
            mf_res = inspect_remote_mod_page(modsfire_url, target_mod_name="Gold_Normal")

        self.assertEqual(mf_res["status"], "free_direct")
        self.assertEqual(mf_res["file_name"], "WW_Azmodan22_Gold_Normal.package")
        self.assertEqual(mf_res["download_url"], mf_final_dl)

        # 3) 2단계 덮어쓰기 통합 테스트:
        #    Step A: Wicked.cc 2024.12.20 기본팩 ZIP 먼저 다운로드·설치
        #    Step B: Gold_Normal만 ModsFire 2025.02.05 버전으로 한 번 더 덮어쓰고 매니페스트 2025.02.05 기록
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods_dir = root / "Mods"
            anim_dir = mods_dir / "WickedWhims" / "Animations" / "Azmodan22"
            anim_dir.mkdir(parents=True)

            local_base = _build_minimal_dbpf_package(
                anim_dir / "WW_Azmodan22_Base.package",
                [_ww_anim_xml("Azmodan22", "Local Old Base")],
            )
            _build_minimal_dbpf_package(
                anim_dir / "WW_Azmodan22_Gold_Normal.package",
                [_ww_anim_xml("Azmodan22", "Local Old Gold Normal")],
            )

            # 2024.12.20 기본팩 ZIP (Base + 구버전 Gold_Normal 포함)
            base_zip_src = root / "Azmodan22_WickedWhims_2024.12.20.zip"
            with zipfile.ZipFile(base_zip_src, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                p_b = _build_minimal_dbpf_package(
                    root / "stage_base.package",
                    [_ww_anim_xml("Azmodan22", "Base 2024.12.20 Marker")],
                )
                p_g_old = _build_minimal_dbpf_package(
                    root / "stage_gold_old.package",
                    [_ww_anim_xml("Azmodan22", "Gold_Normal 2024.12.20 Marker")],
                )
                zf.write(p_b, arcname="WW_Azmodan22_Base.package")
                zf.write(p_g_old, arcname="WW_Azmodan22_Gold_Normal.package")

            # 2025.02.05 Gold_Normal 패치 파일
            gold_new_src = _build_minimal_dbpf_package(
                root / "WW_Azmodan22_Gold_Normal_20250205.package",
                [_ww_anim_xml("Azmodan22", "Gold_Normal 2025.02.05 Updated Marker")],
            )

            base_dl_url = "https://files.wicked.cc/file/wickedcc/Azmodan22_WickedWhims_2024.12.20.zip"
            dl_history: list[str] = []

            def _two_stage_download(url, dest_path, **kwargs):
                dl_history.append(url)
                if url == base_dl_url:
                    shutil.copy2(base_zip_src, dest_path)
                    return dest_path
                if url == mf_final_dl:
                    shutil.copy2(gold_new_src, dest_path)
                    return dest_path
                raise AssertionError(f"Unexpected download URL: {url}")

            manifest_path = root / "mods_manifest.json"
            updater = ModUpdater(
                mods_folder=mods_dir,
                manifest_path=manifest_path,
                backup_manager=BackupManager(root / "backups"),
            )
            mod_cfg = {
                "name": "WW Animation - Azmodan22",
                "file_path": str(local_base),
                "install_folder": str(Path("WickedWhims") / "Animations" / "Azmodan22"),
                "unit_files": [
                    str(anim_dir / "WW_Azmodan22_Base.package"),
                    str(anim_dir / "WW_Azmodan22_Gold_Normal.package"),
                ],
                "source_type": "generic_web",
            }
            update_info = {
                "latest_version": "Wicked.cc (2024.12.20)",
                "download_url": base_dl_url,
                "asset_name": "Azmodan22_WickedWhims_2024.12.20.zip",
                "page_url": wicked_url,
                "post_install_overlays": cat_hit["post_install_overlays"],
            }

            with patch("src.finder.SafeHttpsSession", return_value=_MockMfSess()), patch(
                "src.updater.download_file", side_effect=_two_stage_download
            ):
                installed = updater.update_mod(mod_cfg, update_info, overwrite_mode="all")

            # 다운로드 순서: Wicked.cc 2024.12.20 먼저 -> ModsFire 2025.02.05 Gold_Normal 두 번째
            self.assertEqual(dl_history, [base_dl_url, mf_final_dl])
            self.assertIn("WW_Azmodan22_Base.package", installed)
            self.assertIn("WW_Azmodan22_Gold_Normal.package", installed)

            # Base는 2024.12.20 내용 유지, Gold_Normal만 2025.02.05 내용으로 덮어써졌는지 바이너리 확인
            base_bytes = (anim_dir / "WW_Azmodan22_Base.package").read_bytes()
            gold_bytes = (anim_dir / "WW_Azmodan22_Gold_Normal.package").read_bytes()
            self.assertIn(b"Base 2024.12.20 Marker", base_bytes)
            self.assertNotIn(b"Gold_Normal 2024.12.20 Marker", gold_bytes)
            self.assertIn(b"Gold_Normal 2025.02.05 Updated Marker", gold_bytes)

            # 매니페스트 최신 버전이 2025.02.05로 갱신되었는지 검증
            self.assertEqual(mod_cfg["current_version"], "2025.02.05")
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            recorded_vers = [
                v.get("current_version")
                for v in (manifest_data.get("mods") or [])
                if isinstance(v, dict)
            ]
            self.assertTrue(any(rv == "2025.02.05" for rv in recorded_vers), recorded_vers)

    def test_404dyma_catalog_and_modsfire_inspector(self) -> None:
        from src.finder import inspect_remote_mod_page, label_for_url

        # 1) 카탈로그 메타데이터 검증
        cat_hit = check_known_catalog("WW_404Dyma_Animations.package")
        self.assertIsNotNone(cat_hit)
        self.assertEqual(cat_hit["matched_catalog"], "WW Animation - 404Dyma")
        self.assertEqual(cat_hit["creator"], "404Dyma")
        self.assertEqual(cat_hit["mod_title"], "WW Animation - 404Dyma")
        self.assertEqual(cat_hit["version"], "1.0.0")
        self.assertTrue(cat_hit["is_ww_animation"])
        page_url = "https://modsfire.com/Bky46TOd7C9vc8L"
        self.assertEqual(cat_hit["primary_url"], page_url)
        self.assertEqual(label_for_url(page_url), "ModsFire")

        # 2) _inspect_modsfire_page 자동 추출 검증
        dl_trigger = "https://modsfire.com/d/Bky46TOd7C9vc8L"
        final_dl = "https://cdn.modsfire.com/files/WW_404Dyma_Animations_v1.0.0.package"

        class _MockResp:
            def __init__(self, status_code: int, text: str, url: str, headers: dict[str, str] | None = None) -> None:
                self.status_code = status_code
                self.text = text
                self.url = url
                self.encoding = "utf-8"
                self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}

            def close(self) -> None:
                pass

        mf_html = f"""
        <html>
          <head><title>WW_404Dyma_Animations_v1.0.0.package | ModsFire</title></head>
          <body><a class="btn" href="{dl_trigger}">Download</a></body>
        </html>
        """

        class _MockMfSess:
            def __init__(self) -> None:
                self.headers = {}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, target_url: str, **kwargs):
                if "/d/" in target_url:
                    return _MockResp(
                        200,
                        "",
                        final_dl,
                        headers={
                            "Content-Type": "application/octet-stream",
                            "Content-Disposition": 'attachment; filename="WW_404Dyma_Animations_v1.0.0.package"',
                        },
                    )
                return _MockResp(200, mf_html, page_url)

        with patch("src.finder.SafeHttpsSession", return_value=_MockMfSess()):
            res = inspect_remote_mod_page(page_url, target_mod_name="WW_404Dyma_Animations.package")

        self.assertEqual(res["status"], "free_direct")
        self.assertEqual(res["file_name"], "WW_404Dyma_Animations_v1.0.0.package")
        self.assertEqual(res["download_url"], final_dl)
        self.assertEqual(res["version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
