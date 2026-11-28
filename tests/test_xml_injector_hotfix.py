"""0.1.6 핫픽스 회귀 테스트: XML Injector 오인식 및 타 모드(텔레포트 석상·괴롭히기 모드 등) 덮어쓰기 방지 검증."""

import json
import shutil
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import main as app_main
from src.backup import BackupManager
from src.finder import (
    check_known_catalog,
    extract_mod_file_metadata,
    find_direct_mod_page,
    is_safe_remote_file_match,
)
from src.scanner import ModScanner
from src.updater import ModUpdater
from src.utils import find_superseded_mod_files


def _build_minimal_dbpf_package(dest_path: Path, xml_texts: list[str]) -> Path:
    """테스트용 최소 DBPF 2.1 .package 파일을 생성합니다."""
    header = bytearray(96)
    header[0:4] = b"DBPF"
    struct.pack_into("<I", header, 4, 2)  # major
    struct.pack_into("<I", header, 8, 1)  # minor

    records: list[tuple[int, int]] = []
    body = bytearray()
    cur_offset = 96
    for txt in xml_texts:
        raw = txt.encode("utf-8")
        records.append((cur_offset, len(raw)))
        body.extend(raw)
        cur_offset += len(raw)

    idx_offset = cur_offset
    struct.pack_into("<I", header, 36, len(records))
    struct.pack_into("<I", header, 64, idx_offset)

    idx_buf = bytearray(4)  # flags = 0
    for idx_i, (off, sz) in enumerate(records):
        entry = bytearray(32)
        struct.pack_into("<5I", entry, 12, idx_i + 1, off, sz, sz, 0)
        idx_buf.extend(entry)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(bytes(header) + bytes(body) + bytes(idx_buf))
    return dest_path


def _build_minimal_ts4script(dest_path: Path, module_name: str = "dummy_mod/__init__.pyc") -> Path:
    """테스트용 최소 유효 .ts4script(ZIP) 파일을 생성합니다."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_path, "w") as zf:
        zf.writestr(module_name, b"\x00\x00\x00\x00")
    return dest_path


class XmlInjectorHotfixRegressionTest(unittest.TestCase):
    def test_teleport_any_sim_is_not_matched_as_xml_injector(self) -> None:
        for fname in (
            "MTS_Scumbumbo_TeleportAnySim_Script.ts4script",
            "MTS_Scumbumbo_TeleportAnySim.package",
            "Scumbumbo_TeleportAnySim.package",
        ):
            self.assertIsNone(check_known_catalog(fname), f"오매칭 발생: {fname}")
            res = find_direct_mod_page(fname)
            self.assertNotEqual(
                res.get("diagnostics", {}).get("matched_catalog"),
                "XML Injector",
                f"find_direct_mod_page 오매칭: {fname}",
            )

        xml_res = check_known_catalog("XmlInjector_Script_v4.ts4script")
        self.assertIsNotNone(xml_res)
        self.assertEqual(xml_res["matched_catalog"], "XML Injector")

    def test_scanner_separates_xml_injector_and_teleport_any_sim_in_same_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mods_dir = Path(tmp) / "Mods"
            shared_dir = mods_dir / "5 GSM 1"
            xml_scr = _build_minimal_ts4script(
                shared_dir / "XmlInjector_Script_v4.ts4script",
                "xml_injector/__init__.pyc",
            )
            tp_scr = _build_minimal_ts4script(
                shared_dir / "MTS_Scumbumbo_TeleportAnySim_Script.ts4script",
                "teleport_any_sim/__init__.pyc",
            )
            tp_pkg = _build_minimal_dbpf_package(
                shared_dir / "MTS_Scumbumbo_TeleportAnySim.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="Object" i="object" m="objects.game_object" n="Scumbumbo:TeleportStatue"/>'],
            )
            self.assertTrue(xml_scr.exists() and tp_scr.exists() and tp_pkg.exists())

            scanner = ModScanner(mods_dir)
            units = scanner.scan_updatable_mod_units()
            primaries = {u["primary_file_name"] for u in units}
            self.assertIn("XmlInjector_Script_v4.ts4script", primaries)
            self.assertIn("MTS_Scumbumbo_TeleportAnySim_Script.ts4script", primaries)
            xml_unit = next(u for u in units if u["primary_file_name"] == "XmlInjector_Script_v4.ts4script")
            self.assertEqual(len(xml_unit["unit_files"]), 1)

    def test_package_with_xml_injector_snippet_and_folder_name_not_mismatched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod_dir = Path(tmp) / "괴롭히기 모드 (XML Injector 필수)"
            torment_pkg = _build_minimal_dbpf_package(
                mod_dir / "SAC_SimTorments.package",
                [
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<I c="XmlInjector" i="snippet" m="xml_injector.snippet" n="Scumbumbo:Torment_XmlInjector_Snippet"/>',
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<I c="Interaction" i="interaction" m="interactions.base.super_interaction" n="SAC:SimTorments_BullySim"/>',
                ],
            )
            meta = extract_mod_file_metadata(str(torment_pkg))
            self.assertFalse(
                any("xmlinjector" in rt.lower().replace("_", "") for rt in meta.get("root_tunings", []))
            )
            self.assertNotIn("xml injector", meta.get("inferred_mod", "").lower())

            with patch("src.finder.search_and_rank_distribution_links", return_value=[]):
                res = find_direct_mod_page(
                    "SAC_SimTorments.package",
                    file_path=str(torment_pkg),
                    folder_name="괴롭히기 모드 (XML Injector 필수)",
                )
            self.assertNotEqual(res.get("diagnostics", {}).get("matched_catalog"), "XML Injector")
            self.assertNotIn("scumbumbomods.com/xml-injector", res.get("primary_url", ""))

            safe, _, _ = is_safe_remote_file_match(
                target_name="SAC_SimTorments.package",
                folder_name="괴롭히기 모드 (XML Injector 필수)",
                extracted_meta=meta,
                remote_info={
                    "status": "free_direct",
                    "file_name": "XmlInjector_Script_v42.zip",
                    "title": "XML Injector v4.2",
                    "page_url": "https://scumbumbomods.com/xml-injector",
                },
                checked_url="https://scumbumbomods.com/xml-injector",
            )
            self.assertFalse(safe)

    def test_updating_xml_injector_does_not_overwrite_teleport_or_torment_mods(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods_dir = root / "Mods"
            shared_dir = mods_dir / "5 GSM 1"
            sub_dir = shared_dir / "TeleportMod"

            xml_old = _build_minimal_ts4script(
                shared_dir / "XmlInjector_Script_v4.ts4script",
                "xml_injector/__init__.pyc",
            )
            tp_scr = _build_minimal_ts4script(
                shared_dir / "Scumbumbo_TeleportAnySim.ts4script",
                "teleport_any_sim/__init__.pyc",
            )
            tp_pkg = _build_minimal_dbpf_package(
                shared_dir / "Scumbumbo_TeleportAnySim.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="Object" i="object" m="objects.game_object" n="TeleportStatue"/>'],
            )
            torment_pkg = _build_minimal_dbpf_package(
                shared_dir / "SAC_SimTorments.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="XmlInjector" i="snippet" m="xml_injector.snippet" n="Torment_Snippet"/>'],
            )
            sub_tp = _build_minimal_dbpf_package(
                sub_dir / "MTS_Scumbumbo_TeleportAnySim.package",
                ['<?xml version="1.0" encoding="utf-8"?><I c="Object" i="object" m="objects.game_object" n="TeleportStatue"/>'],
            )

            # find_superseded_mod_files 단위 검증
            superseded, _ = find_superseded_mod_files(
                incoming_names=["XmlInjector_Script_v4.2.ts4script"],
                target_dir_resolved=shared_dir.resolve(),
                mods_root_resolved=mods_dir.resolve(),
                known_existing_files=[xml_old],
                selected_file_path=xml_old,
                include_subdirs=True,
                expected_catalog_id="XML Injector",
            )
            superseded_names = {p.name for p in superseded}
            self.assertEqual(superseded_names, {"XmlInjector_Script_v4.ts4script"})

            # 실제 XmlInjector_Script_v42.zip 준비 후 ModUpdater.update_mod 실행
            zip_src = root / "XmlInjector_Script_v42.zip"
            inner_scr = root / "XmlInjector_Script_v4.2.ts4script"
            _build_minimal_ts4script(inner_scr, "xml_injector/__init__.pyc")
            with zipfile.ZipFile(zip_src, "w") as zf:
                zf.write(inner_scr, arcname="XmlInjector_Script_v4.2.ts4script")

            updater = ModUpdater(
                mods_folder=mods_dir,
                manifest_path=root / "mods_manifest.json",
                backup_manager=BackupManager(root / "backups"),
            )
            mod_cfg = {
                "name": "XmlInjector_Script_v4.ts4script",
                "file_path": str(xml_old),
                "install_folder": "5 GSM 1",
                "unit_files": [str(xml_old)],
                "source_type": "generic_web",
            }
            update_info = {
                "latest_version": "Scumbumbo (v4.2)",
                "download_url": "https://scumbumbomods.com/xml-injector/XmlInjector_Script_v42.zip",
                "asset_name": "XmlInjector_Script_v42.zip",
                "page_url": "https://scumbumbomods.com/xml-injector",
            }

            def _fake_download(url, dest_path, **kwargs):
                shutil.copy2(zip_src, dest_path)
                return dest_path

            with patch("src.updater.download_file", side_effect=_fake_download):
                installed = updater.update_mod(mod_cfg, update_info, overwrite_mode="all")

            self.assertEqual(installed, ["XmlInjector_Script_v4.2.ts4script"])
            self.assertFalse(xml_old.exists())
            self.assertTrue((shared_dir / "XmlInjector_Script_v4.2.ts4script").exists())
            self.assertTrue(tp_scr.exists())
            self.assertTrue(tp_pkg.exists())
            self.assertTrue(torment_pkg.exists())
            self.assertTrue(sub_tp.exists())

    def test_polluted_manifest_and_scan_cache_schema_invalidation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "mods_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "mods": [
                            {
                                "name": "Scumbumbo_TeleportAnySim.ts4script",
                                "local_file": "Scumbumbo_TeleportAnySim.ts4script",
                                "pinned_page_url": "https://scumbumbomods.com/xml-injector",
                                "current_version": "v4.2",
                            },
                            {
                                "name": "XmlInjector_Script_v4.ts4script",
                                "local_file": "XmlInjector_Script_v4.ts4script",
                                "pinned_page_url": "https://scumbumbomods.com/xml-injector",
                                "current_version": "v4.2",
                            },
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            updater = ModUpdater(mods_folder=root / "Mods", manifest_path=manifest_path)
            self.assertEqual(updater.get_pinned_url("Scumbumbo_TeleportAnySim.ts4script"), "")
            self.assertEqual(
                updater.get_pinned_url("XmlInjector_Script_v4.ts4script"),
                "https://scumbumbomods.com/xml-injector",
            )

            ver_map = app_main.Sims4ModUpdaterAPI._build_manifest_version_map(updater)
            self.assertNotIn("scumbumbo_teleportanysim.ts4script", ver_map)
            self.assertIn("xmlinjector_script_v4.ts4script", ver_map)

            # 구버전(10) 일일 스캔 캐시 무효화 확인
            self.assertGreaterEqual(app_main.Sims4ModUpdaterAPI.SCAN_CACHE_SCHEMA_VERSION, 11)
            mods_dir = root / "Mods"
            mods_dir.mkdir(parents=True, exist_ok=True)
            api = app_main.Sims4ModUpdaterAPI(base_dir=root)
            (root / "scan_cache.json").write_text(
                json.dumps(
                    {
                        "schema_version": 10,
                        "scan_date": "2026-11-27",
                        "mods_folder": str(mods_dir.resolve()),
                        "scan_subfolder": "",
                        "rpo_channel": api.config_manager.rpo_channel,
                        "ww_channel": api.config_manager.ww_channel,
                        "mods": [],
                        "summary": {},
                        "mod_cache": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.assertIsNone(api._load_daily_scan_cache(mods_dir))
            self.assertFalse((root / "scan_cache.json").exists())


if __name__ == "__main__":
    unittest.main()
