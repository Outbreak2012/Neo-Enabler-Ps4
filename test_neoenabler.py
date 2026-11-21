"""
Unit and end-to-end tests for NEOENABLER v2.0:
- SFO binary parsing, in-place patching, full table rebuilding
- Bit 23 (0x00800000) Neo Mode activation & deactivation
- Old SDK (< 0x04000000) automatic upgrade in both param.sfo (SYSTEM_VER) and eboot.bin (OrbisProcParam 'ORBI')
- Backup creation & full restoration of both param.sfo and eboot.bin
"""

from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from eboot_patcher import (
    NEO_COMPAT_SDK_VERSION,
    analyze_eboot_bytes,
    create_sample_fself_eboot,
    patch_eboot_sdk_version,
)
from ps4_ftp import BackupManager, GoldHenFtpClient, InstalledGame
from resolution_patcher import (
    build_goldhen_xml,
    generate_resolution_patch_entries,
    patch_eboot_resolution_inplace,
    scan_eboot_for_resolutions,
)
from sfo_parser import NEO_MODE_BIT, SfoFile, create_sample_sfo


class TestNeoEnabler(unittest.TestCase):
    def test_sfo_create_and_toggle_neo_bit(self) -> None:
        sfo = create_sample_sfo(
            title_id="CUSA00900",
            title="Bloodborne",
            app_ver="01.09",
            attribute=0x00000002,
            system_ver=0x03500000,
        )
        self.assertEqual(sfo.title_id, "CUSA00900")
        self.assertTrue(sfo.is_old_sdk)
        self.assertFalse(sfo.is_neo_enabled)

        new_attr = sfo.set_neo_mode(True)
        self.assertEqual(new_attr, 0x00800002)
        self.assertTrue(sfo.is_neo_enabled)

        patched_bytes = sfo.to_bytes(prefer_inplace=True)
        reparsed = SfoFile.from_bytes(patched_bytes)
        self.assertTrue(reparsed.is_neo_enabled)
        self.assertEqual(reparsed.attribute, 0x00800002)

    def test_eboot_fself_orbi_sdk_upgrade(self) -> None:
        # Create an old-SDK (2.00 = 0x02000001) FSELF eboot.bin
        raw_eboot = create_sample_fself_eboot(sdk_version=0x02000001)
        analysis = analyze_eboot_bytes(raw_eboot)
        self.assertTrue(analysis.is_patchable)
        self.assertTrue(analysis.is_old_sdk)
        self.assertEqual(analysis.primary_sdk_version, 0x02000001)
        self.assertEqual(analysis.container_type, "FSELF (Fake Signed SELF)")

        # Upgrade sdk_version in OrbisProcParam ('ORBI') to 0x04500001 (SDK 4.50)
        patched_eboot, new_analysis = patch_eboot_sdk_version(raw_eboot, NEO_COMPAT_SDK_VERSION)
        self.assertTrue(new_analysis.is_patchable)
        self.assertFalse(new_analysis.is_old_sdk)
        self.assertEqual(new_analysis.primary_sdk_version, NEO_COMPAT_SDK_VERSION)

    def test_old_sdk_game_injection_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sfo_path = tmp_path / "param.sfo"
            eboot_path = tmp_path / "eboot.bin"
            bkp_dir = tmp_path / "backups"

            # Driveclub compiled with old SDK 2.00 (0x02000000)
            sfo = create_sample_sfo(
                title_id="CUSA00552",
                title="Driveclub",
                attribute=0x00008002,
                system_ver=0x02000000,
            )
            sfo.save(str(sfo_path))

            raw_eboot = create_sample_fself_eboot(sdk_version=0x02000001)
            eboot_path.write_bytes(raw_eboot)

            bkp_mgr = BackupManager(backups_root=bkp_dir)
            client = GoldHenFtpClient(backup_manager=bkp_mgr)

            game = InstalledGame(
                title_id="CUSA00552",
                title="Driveclub",
                app_ver="01.28",
                category="gd",
                system_ver=sfo.system_ver_hex,
                system_ver_int=sfo.system_ver,
                attribute=sfo.attribute,
                sfo_locations={str(sfo_path): sfo},
                local_source_path=str(sfo_path),
                local_eboot_path=str(eboot_path),
                eboot_analysis=analyze_eboot_bytes(raw_eboot),
            )
            self.assertTrue(game.is_old_sdk)

            # Inject Neo Mode + Old-SDK Patch
            ok, _msg = client.apply_neo_mode(game, enable=True, patch_old_sdk=True, sync_app_db=False)
            self.assertTrue(ok)
            self.assertTrue(game.is_neo_enabled)
            self.assertFalse(game.is_old_sdk)

            # Verify disk param.sfo has both Neo bit (0x00800000) and upgraded SYSTEM_VER (0x04500000)
            disk_sfo = SfoFile.from_file(str(sfo_path))
            self.assertTrue(disk_sfo.is_neo_enabled)
            self.assertEqual(disk_sfo.attribute, 0x00808002)
            self.assertEqual(disk_sfo.system_ver, 0x04500000)

            # Verify disk eboot.bin has upgraded OrbisProcParam ('ORBI') sdk_version (0x04500001)
            disk_eboot_analysis = analyze_eboot_bytes(eboot_path.read_bytes())
            self.assertEqual(disk_eboot_analysis.primary_sdk_version, NEO_COMPAT_SDK_VERSION)

            # Restore original backup and verify both param.sfo and eboot.bin return to SDK 2.00
            ok_rest, _msg_rest = client.restore_original_backup(game, sync_app_db=False)
            self.assertTrue(ok_rest)
            self.assertFalse(game.is_neo_enabled)
            self.assertTrue(game.is_old_sdk)

            restored_sfo = SfoFile.from_file(str(sfo_path))
            self.assertFalse(restored_sfo.is_neo_enabled)
            self.assertEqual(restored_sfo.system_ver, 0x02000000)

            restored_eboot_analysis = analyze_eboot_bytes(eboot_path.read_bytes())
            self.assertEqual(restored_eboot_analysis.primary_sdk_version, 0x02000001)

    def test_resolution_scanner_and_goldhen_xml_generator(self) -> None:
        # Create a mock 900p (1600x900) FSELF eboot.bin
        raw_eboot = create_sample_fself_eboot(sdk_version=0x02500001, res_width=1600, res_height=900)
        matches = scan_eboot_for_resolutions(raw_eboot, source_width=1600, source_height=900)
        self.assertGreaterEqual(len(matches), 1)
        self.assertEqual(matches[0].original_width, 1600)
        self.assertEqual(matches[0].original_height, 900)

        # Generate GoldHEN XML upgrading 1600x900 -> 2560x1440 (1440p) + curated patches
        entries = generate_resolution_patch_entries(
            title_id="CUSA00129",
            title="Assassin's Creed Unity",
            app_ver="01.05",
            matches=matches,
            target_width=2560,
            target_height=1440,
            include_curated=True,
        )
        xml_text = build_goldhen_xml("CUSA00129", entries)
        self.assertIn("<ID>CUSA00129</ID>", xml_text)
        self.assertIn("0x00000a00", xml_text)  # 2560 in hex
        self.assertIn("0x000005a0", xml_text)  # 1440 in hex

        # Verify direct in-place eboot resolution patching
        patched_eb = patch_eboot_resolution_inplace(raw_eboot, matches, 2560, 1440)
        new_matches = scan_eboot_for_resolutions(patched_eb, source_width=2560, source_height=1440)
        self.assertEqual(len(new_matches), len(matches))


if __name__ == "__main__":
    unittest.main()
