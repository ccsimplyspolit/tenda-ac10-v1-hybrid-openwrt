#!/usr/bin/env python3
"""
Challenger 1 Empirical Verification Suite for Milestone 1
Targets:
  1. Flash_Hybrid_OpenWrt_4.14_TFTP.bat (Path resolution, fallbacks, failure codes)
  2. tftp_recovery_engine.py & verify_firmware.py (TRX2 U-Boot headers, valid/corrupted headers)
  3. test_suite_offline.py (Execution and line 346 legitimacy audit)

Safety: 100% offline local loopback/filesystem execution only. No network/router interference.
"""

import os
import sys
import unittest
import struct
import zlib
import hashlib
import tempfile
import shutil
import subprocess

SUITE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SUITE_DIR)
if not os.path.exists(os.path.join(REPO_ROOT, "offline_autonomous_tools")):
    REPO_ROOT = r"C:\Users\user\AppData\Local\Temp\tenda_ac10_public_repo"
    SUITE_DIR = os.path.join(REPO_ROOT, "Tenda_AC10_V1_Autonomous_Recovery_Suite")
FIRMWARE_DIR = os.path.join(REPO_ROOT, "02_Compiled_Hybrid_OpenWrt_4.14_Firmware")
BAT_PATH = os.path.join(SUITE_DIR, "Flash_Hybrid_OpenWrt_4.14_TFTP.bat")

if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

# Also ensure offline_autonomous_tools is in sys.path
OFFLINE_TOOLS_DIR = os.path.join(REPO_ROOT, "offline_autonomous_tools")
if OFFLINE_TOOLS_DIR not in sys.path:
    sys.path.insert(0, OFFLINE_TOOLS_DIR)

import verify_firmware
import tftp_recovery_engine


def make_valid_cs6c_payload(payload_size=1024, load_addr=0x80A00000, burn_addr=0x00030000):
    """
    Creates a valid Realtek cs6c single-segment payload with 16-bit BE additive checksum == 0x0000.
    Header: 16 bytes (magic b'cs6c', load_addr, burn_addr, seg1_len)
    Payload: seg1_len bytes, padded and adjusted so sum16_be == 0x0000.
    """
    if payload_size % 2 != 0:
        payload_size += 1
    # Generate arbitrary body bytes
    body = bytearray((i * 37 + 11) % 256 for i in range(payload_size - 2))
    # Compute current sum of the first payload_size - 2 bytes
    acc = 0
    for i in range(0, len(body), 2):
        acc = (acc + ((body[i] << 8) | body[i + 1])) & 0xFFFF
    # The last 2 bytes compensate to make total sum == 0x0000
    comp = (-acc) & 0xFFFF
    body.append((comp >> 8) & 0xFF)
    body.append(comp & 0xFF)

    header = struct.pack(">4sIII", b"cs6c", load_addr, burn_addr, len(body))
    return bytes(header + body)


def wrap_tenda_webupgrade(cs6c_data, ih_hcrc=0, ih_os=2, ih_ver=0x00030028, ih_magic=0x27051956, calc_hcrc=False):
    """
    Wraps cs6c_data into a 64-byte Tenda U-Boot webupgrade container.
    """
    ih_time = 0x61000000
    ih_size = len(cs6c_data)
    ih_load = 0x80A00000
    ih_ep = 0x80A00000
    ih_dcrc = zlib.crc32(cs6c_data) & 0xFFFFFFFF

    # 64 bytes total
    # 0x00: ih_magic (4)
    # 0x04: ih_hcrc (4)
    # 0x08: ih_time (4)
    # 0x0C: ih_size (4)
    # 0x10: ih_load (4)
    # 0x14: ih_ep (4)
    # 0x18: ih_dcrc (4)
    # 0x1C: 4 bytes (e.g. 0)
    # 0x20: ih_os (1 byte at 0x20, 3 bytes padding/flags)
    # 0x24: ih_ver (4 bytes)
    # 0x28..0x40: ih_name (24 bytes)

    name_bytes = b"Tenda_AC10_V1_Hybrid\x00".ljust(24, b"\x00")
    hdr = bytearray(64)
    struct.pack_into(">7I", hdr, 0, ih_magic, 0 if calc_hcrc else ih_hcrc, ih_time, ih_size, ih_load, ih_ep, ih_dcrc)
    hdr[0x20] = ih_os & 0xFF
    struct.pack_into(">I", hdr, 0x24, ih_ver)
    hdr[0x28:0x40] = name_bytes

    if calc_hcrc:
        hdr[4:8] = b"\x00\x00\x00\x00"
        computed_hcrc = zlib.crc32(bytes(hdr)) & 0xFFFFFFFF
        struct.pack_into(">I", hdr, 4, computed_hcrc)

    return bytes(hdr) + cs6c_data


class TestBatPathResolution(unittest.TestCase):
    """
    Empirical tests of Flash_Hybrid_OpenWrt_4.14_TFTP.bat path resolution:
    - Pass valid firmware file via %1
    - Fallback to ..\02_Compiled_Hybrid_OpenWrt_4.14_Firmware\tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin
    - Fallback to current directory
    - Fallback to parent directory
    - Fallback to ..\firmware\
    - Failure with code 1 when no firmware found
    - Argument forwarding to flasher script
    """

    @classmethod
    def setUpClass(cls):
        # Pre-compile a standalone mock net.exe using csc.exe so net session passes without UAC
        cls.shared_bin = tempfile.mkdtemp(prefix="mock_net_bin_")
        cs_src = os.path.join(cls.shared_bin, "net.cs")
        with open(cs_src, "w", encoding="utf-8") as f:
            f.write("public class P { public static int Main() { return 0; } }")
        cls.mock_net_exe = os.path.join(cls.shared_bin, "net.exe")
        csc = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
        subprocess.run([csc, "/nologo", f"/out:{cls.mock_net_exe}", cs_src], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.shared_bin, ignore_errors=True)

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="bat_test_")

        # Create suite directory where the .bat lives
        self.test_suite_dir = os.path.join(self.tmp_dir, "Tenda_AC10_V1_Autonomous_Recovery_Suite")
        os.makedirs(self.test_suite_dir, exist_ok=True)
        self.test_bat = os.path.join(self.test_suite_dir, "Flash_Hybrid_OpenWrt_4.14_TFTP.bat")
        shutil.copy2(BAT_PATH, self.test_bat)

        # Create a mock Offline_TFTP_Recovery_and_Flash.ps1 that logs arguments and exits 0
        self.ps1_log = os.path.join(self.tmp_dir, "flasher_invoked.log")
        mock_ps1 = (
            f"param([string]$FirmwarePath)\n"
            f"$out = 'FirmwarePath=' + $FirmwarePath + ' Args=' + ($args -join ' ')\n"
            f"Set-Content -Path '{self.ps1_log.replace(chr(92), '/')}' -Value $out\n"
            f"Write-Host '[MOCK_FLASHER] Running with FirmwarePath=' $FirmwarePath\n"
            f"exit 0\n"
        )
        with open(os.path.join(self.test_suite_dir, "Offline_TFTP_Recovery_and_Flash.ps1"), "w", encoding="utf-8") as f:
            f.write(mock_ps1)

        self.env = dict(os.environ)
        self.env["PATH"] = self.shared_bin + os.pathsep + self.env["PATH"]

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def run_bat(self, args=None):
        cmd = ["cmd.exe", "/c", self.test_bat]
        if args:
            cmd.extend(args)
        proc = subprocess.run(
            cmd,
            cwd=self.test_suite_dir,
            env=self.env,
            input="\n\n",
            capture_output=True,
            text=True
        )
        return proc

    def test_01_explicit_fw_path_via_arg1(self):
        """Test passing a valid firmware file via %1."""
        custom_fw = os.path.join(self.tmp_dir, "custom_target_firmware.bin")
        with open(custom_fw, "wb") as f:
            f.write(b"cs6c_dummy_data")

        res = self.run_bat([custom_fw])
        self.assertEqual(res.returncode, 0, f"BAT failed: {res.stdout}\n{res.stderr}")
        self.assertIn(f"Target Image: {custom_fw}", res.stdout)
        self.assertTrue(os.path.exists(self.ps1_log))
        with open(self.ps1_log, "r", encoding="utf-8") as f:
            log_content = f.read().strip()
        self.assertIn(f"FirmwarePath={custom_fw}", log_content)

    def test_02_fallback_to_compiled_hybrid_dir(self):
        """Test fallback to ..\\02_Compiled_Hybrid_OpenWrt_4.14_Firmware\\tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin."""
        compiled_dir = os.path.join(self.tmp_dir, "02_Compiled_Hybrid_OpenWrt_4.14_Firmware")
        os.makedirs(compiled_dir, exist_ok=True)
        expected_fw = os.path.join(compiled_dir, "tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin")
        with open(expected_fw, "wb") as f:
            f.write(b"cs6c_factory_compiled")

        res = self.run_bat([])
        self.assertEqual(res.returncode, 0, f"BAT failed: {res.stdout}\n{res.stderr}")
        self.assertIn("Target Image:", res.stdout)
        self.assertIn("02_Compiled_Hybrid_OpenWrt_4.14_Firmware", res.stdout)
        with open(self.ps1_log, "r", encoding="utf-8") as f:
            log_content = f.read().strip()
        logged_fw = log_content.split("FirmwarePath=")[1].split(" Args=")[0]
        self.assertEqual(os.path.normpath(expected_fw), os.path.normpath(logged_fw))

    def test_03_fallback_to_current_directory(self):
        """Test fallback to current directory tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin."""
        expected_fw = os.path.join(self.test_suite_dir, "tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin")
        with open(expected_fw, "wb") as f:
            f.write(b"cs6c_local_factory")

        res = self.run_bat([])
        self.assertEqual(res.returncode, 0, f"BAT failed: {res.stdout}\n{res.stderr}")
        self.assertIn(f"Target Image: {expected_fw}", res.stdout)
        with open(self.ps1_log, "r", encoding="utf-8") as f:
            log_content = f.read().strip()
        logged_fw = log_content.split("FirmwarePath=")[1].split(" Args=")[0]
        self.assertEqual(os.path.normpath(expected_fw), os.path.normpath(logged_fw))

    def test_04_fallback_to_parent_directory(self):
        """Test fallback to ..\\tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin."""
        expected_fw = os.path.join(self.tmp_dir, "tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin")
        with open(expected_fw, "wb") as f:
            f.write(b"cs6c_parent_factory")

        res = self.run_bat([])
        self.assertEqual(res.returncode, 0, f"BAT failed: {res.stdout}\n{res.stderr}")
        self.assertIn("Target Image:", res.stdout)
        with open(self.ps1_log, "r", encoding="utf-8") as f:
            log_content = f.read().strip()
        logged_fw = log_content.split("FirmwarePath=")[1].split(" Args=")[0]
        self.assertEqual(os.path.normpath(expected_fw), os.path.normpath(logged_fw))

    def test_05_fallback_to_parent_firmware_dir(self):
        """Test fallback to ..\\firmware\\tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin."""
        fw_dir = os.path.join(self.tmp_dir, "firmware")
        os.makedirs(fw_dir, exist_ok=True)
        expected_fw = os.path.join(fw_dir, "tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin")
        with open(expected_fw, "wb") as f:
            f.write(b"cs6c_firmware_subfolder")

        res = self.run_bat([])
        self.assertEqual(res.returncode, 0, f"BAT failed: {res.stdout}\n{res.stderr}")
        self.assertIn("Target Image:", res.stdout)
        with open(self.ps1_log, "r", encoding="utf-8") as f:
            log_content = f.read().strip()
        logged_fw = log_content.split("FirmwarePath=")[1].split(" Args=")[0]
        self.assertEqual(os.path.normpath(expected_fw), os.path.normpath(logged_fw))

    def test_06_no_firmware_found_fails_with_code_1(self):
        """Test behavior when no firmware is found: must fail gracefully with code 1 and show searched paths."""
        res = self.run_bat([])
        self.assertEqual(res.returncode, 1, f"Expected returncode 1, got {res.returncode}\nOUT: {res.stdout}")
        self.assertIn("[ERROR] Firmware binary 'tenda-ac10-v1-hybrid-openwrt-4.14-factory.bin' not found", res.stdout)
        self.assertIn("Searched locations:", res.stdout)
        self.assertIn("02_Compiled_Hybrid_OpenWrt_4.14_Firmware", res.stdout)
        self.assertIn("Command-line argument:", res.stdout)
        # Verify flasher was NEVER invoked
        self.assertFalse(os.path.exists(self.ps1_log))

    def test_07_argument_forwarding(self):
        """Test forwarding additional flags to flasher script."""
        custom_fw = os.path.join(self.tmp_dir, "fw.bin")
        with open(custom_fw, "wb") as f:
            f.write(b"data")

        res = self.run_bat([custom_fw, "-VerifyOnly", "-SkipNetworkConfig"])
        self.assertEqual(res.returncode, 0)
        with open(self.ps1_log, "r", encoding="utf-8") as f:
            log_content = f.read().strip()
        self.assertIn(f"FirmwarePath={custom_fw}", log_content)
        self.assertIn("-VerifyOnly", log_content)
        self.assertIn("-SkipNetworkConfig", log_content)


class TestHeaderValidation(unittest.TestCase):
    """
    Empirical tests of tftp_recovery_engine.py & verify_firmware.py:
    - Valid Tenda webupgrade header with ih_hcrc == 0, model 0x00030028, OS type 2 -> must succeed!
    - Valid Tenda webupgrade header with calculated ih_hcrc -> must succeed!
    - Real Run 41311238013 webupgrade.bin -> must succeed!
    - Corrupted magic or truncated payload -> must reject gracefully.
    - Corrupted checksum, dcrc, hcrc, model, os -> must reject gracefully.
    """

    def setUp(self):
        self.valid_cs6c = make_valid_cs6c_payload(2048)

    def test_01_valid_webupgrade_hcrc_zero_succeeds(self):
        """Valid Tenda webupgrade header with ih_hcrc == 0, model 0x00030028, OS type 2 -> must succeed!"""
        fw = wrap_tenda_webupgrade(self.valid_cs6c, ih_hcrc=0, ih_os=2, ih_ver=0x00030028)

        # 1. tftp_recovery_engine
        inner, meta = tftp_recovery_engine.unwrap_tenda_webupgrade(fw)
        self.assertEqual(meta["ih_hcrc"], 0)
        self.assertEqual(meta["ih_ver"], 0x00030028)
        self.assertEqual(meta["ih_os"], 2)
        val_res = tftp_recovery_engine.validate_realtek_booter_image(fw)
        self.assertEqual(val_res["magic"], "cs6c")
        self.assertEqual(val_res["start_addr"], 0x80A00000)
        self.assertEqual(val_res["burn_addr"], 0x00030000)
        self.assertEqual(val_res["is_webupgrade_wrapped"], True)

        # 2. verify_firmware
        unwrapped, v_meta, errs = verify_firmware.unwrap_booter_payload(fw)
        self.assertEqual(errs, [])
        self.assertIsNotNone(v_meta)
        is_valid, results = verify_firmware.verify_image_bytes(fw)
        self.assertTrue(is_valid)
        self.assertEqual(results["details"]["checksum_val"], 0x0000)

    def test_02_valid_webupgrade_hcrc_calculated_succeeds(self):
        """Valid Tenda webupgrade header with calculated non-zero ih_hcrc -> must succeed!"""
        fw = wrap_tenda_webupgrade(self.valid_cs6c, calc_hcrc=True, ih_os=2, ih_ver=0x00030028)
        inner, meta = tftp_recovery_engine.unwrap_tenda_webupgrade(fw)
        self.assertNotEqual(meta["ih_hcrc"], 0)
        val_res = tftp_recovery_engine.validate_realtek_booter_image(fw)
        self.assertEqual(val_res["magic"], "cs6c")

        is_valid, results = verify_firmware.verify_image_bytes(fw)
        self.assertTrue(is_valid)

    def test_03_real_compiled_webupgrade_file(self):
        """Empirically test the real Run 41311238013 webupgrade binary."""
        real_webupgrade_path = os.path.join(FIRMWARE_DIR, "tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin")
        if not os.path.exists(real_webupgrade_path):
            real_webupgrade_path = os.path.join(r"K:\aoe4_dlc\02_Compiled_Hybrid_OpenWrt_4.14_Firmware", "tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin")
        self.assertTrue(os.path.exists(real_webupgrade_path), f"File not found: {real_webupgrade_path}")

        with open(real_webupgrade_path, "rb") as f:
            real_fw = f.read()

        # Check in tftp_recovery_engine
        inner, meta = tftp_recovery_engine.unwrap_tenda_webupgrade(real_fw)
        self.assertEqual(meta["ih_hcrc"], 0)
        self.assertEqual(meta["ih_ver"], 0x00030028)
        self.assertEqual(meta["ih_os"], 2)
        booter_res = tftp_recovery_engine.validate_realtek_booter_image(real_fw)
        self.assertEqual(booter_res["magic"], "cs6c")
        self.assertEqual(booter_res["start_addr"], 0x80A00000)
        self.assertEqual(booter_res["burn_addr"], 0x00030000)
        self.assertEqual(booter_res["is_webupgrade_wrapped"], True)

        # Check in verify_firmware
        is_valid, results = verify_firmware.verify_image_bytes(real_fw)
        self.assertTrue(is_valid, f"verify_firmware failed on real webupgrade: {results.get('errors')}")

    def test_04_corrupted_magic_webupgrade(self):
        """Corrupted U-Boot magic must reject gracefully."""
        fw = bytearray(wrap_tenda_webupgrade(self.valid_cs6c))
        fw[0:4] = b"\x12\x34\x56\x78"  # corrupt magic

        # tftp_recovery_engine treats non-webupgrade as raw booter, which expects cs6c/cr6c
        with self.assertRaises(ValueError) as ctx:
            tftp_recovery_engine.validate_realtek_booter_image(bytes(fw))
        self.assertIn("Invalid header magic", str(ctx.exception))

        # verify_firmware unwrap_booter_payload returns data as raw, verify_image_bytes rejects magic
        is_valid, res = verify_firmware.verify_image_bytes(bytes(fw))
        self.assertFalse(is_valid)

    def test_05_corrupted_magic_inner_payload(self):
        """Valid 0x27051956 wrapper, but inner payload magic is corrupt -> must reject."""
        corrupt_inner = bytearray(self.valid_cs6c)
        corrupt_inner[0:4] = b"BAD!"
        fw = wrap_tenda_webupgrade(bytes(corrupt_inner))

        with self.assertRaises(ValueError) as ctx:
            tftp_recovery_engine.validate_realtek_booter_image(fw)
        self.assertIn("Invalid header magic", str(ctx.exception))

        is_valid, res = verify_firmware.verify_image_bytes(fw)
        self.assertFalse(is_valid)

    def test_06_truncated_payload_below_header(self):
        """File truncated below 64 bytes -> must reject gracefully."""
        short_data = b"\x27\x05\x19\x56" + b"\x00" * 20

        with self.assertRaises(ValueError) as ctx:
            tftp_recovery_engine.validate_realtek_booter_image(short_data)
        self.assertIn("too small", str(ctx.exception).lower())

        is_valid, res = verify_firmware.verify_image_bytes(short_data)
        self.assertFalse(is_valid)

    def test_07_truncated_inner_payload_size_mismatch(self):
        """Wrapper claims 2048 bytes, but file truncated to 100 bytes -> must reject."""
        fw = wrap_tenda_webupgrade(self.valid_cs6c)
        truncated = fw[:100]

        with self.assertRaises(ValueError) as ctx:
            tftp_recovery_engine.validate_realtek_booter_image(truncated)
        self.assertIn("ih_size mismatch", str(ctx.exception))

        unwrapped, meta, errs = verify_firmware.unwrap_booter_payload(truncated)
        self.assertTrue(any("ih_size mismatch" in e for e in errs))

    def test_08_corrupted_dcrc(self):
        """Data CRC mismatch -> must reject gracefully."""
        fw = bytearray(wrap_tenda_webupgrade(self.valid_cs6c))
        fw[70] ^= 0xFF  # corrupt byte in inner payload

        with self.assertRaises(ValueError) as ctx:
            tftp_recovery_engine.validate_realtek_booter_image(bytes(fw))
        self.assertIn("ih_dcrc mismatch", str(ctx.exception))

        unwrapped, meta, errs = verify_firmware.unwrap_booter_payload(bytes(fw))
        self.assertTrue(any("ih_dcrc mismatch" in e for e in errs))

    def test_09_corrupted_nonzero_hcrc(self):
        """Non-zero corrupted header CRC -> must reject gracefully."""
        fw = bytearray(wrap_tenda_webupgrade(self.valid_cs6c, ih_hcrc=0x12345678))

        with self.assertRaises(ValueError) as ctx:
            tftp_recovery_engine.validate_realtek_booter_image(bytes(fw))
        self.assertIn("ih_hcrc mismatch", str(ctx.exception))

        unwrapped, meta, errs = verify_firmware.unwrap_booter_payload(bytes(fw))
        self.assertTrue(any("ih_hcrc mismatch" in e for e in errs))

    def test_10_invalid_os_type(self):
        """Invalid OS type (e.g. NetBSD or 255) -> must reject gracefully."""
        fw = wrap_tenda_webupgrade(self.valid_cs6c, ih_os=255)

        with self.assertRaises(ValueError) as ctx:
            tftp_recovery_engine.validate_realtek_booter_image(fw)
        self.assertIn("rejected by check_fw_valid", str(ctx.exception))
        self.assertIn("expected 2 = Linux", str(ctx.exception))

        unwrapped, meta, errs = verify_firmware.unwrap_booter_payload(fw)
        self.assertTrue(any("ih_os" in e and "invalid" in e for e in errs))

    def test_11_invalid_model_version(self):
        """Invalid model version (e.g. 0x00020000) -> must reject gracefully."""
        fw = wrap_tenda_webupgrade(self.valid_cs6c, ih_ver=0x00020000)

        with self.assertRaises(ValueError) as ctx:
            tftp_recovery_engine.validate_realtek_booter_image(fw)
        self.assertIn("rejected by check_fw_valid", str(ctx.exception))
        self.assertIn("0x00030028", str(ctx.exception))

        unwrapped, meta, errs = verify_firmware.unwrap_booter_payload(fw)
        self.assertTrue(any("ih_ver" in e and "rejected" in e for e in errs))

    def test_12_corrupted_16bit_be_checksum(self):
        """Inner payload with bad 16-bit additive sum -> must reject gracefully."""
        corrupt_cs6c = bytearray(self.valid_cs6c)
        corrupt_cs6c[-1] ^= 0x01  # break sum16
        # Re-wrap with correct outer CRC so it passes U-Boot wrapper check
        fw = wrap_tenda_webupgrade(bytes(corrupt_cs6c))

        with self.assertRaises(ValueError) as ctx:
            tftp_recovery_engine.validate_realtek_booter_image(fw)
        self.assertIn("16-bit BE checksum failed", str(ctx.exception))

        is_valid, res = verify_firmware.verify_image_bytes(fw)
        self.assertFalse(is_valid)
        self.assertIn("Segment 1 checksum failure", "\n".join(res.get("errors", [])))


class TestTestSuiteOfflineAudit(unittest.TestCase):
    """
    Empirical audit of test_suite_offline.py:
    - Execute test_suite_offline.py and verify all tests pass
    - Audit line 346: verify assertion '192.168.0.100' legitimately tests line 328
    """

    def test_01_execute_test_suite_offline(self):
        """Execute test_suite_offline.py in Tenda_AC10_V1_Autonomous_Recovery_Suite."""
        test_script = os.path.join(SUITE_DIR, "test_suite_offline.py")
        proc = subprocess.run(
            [sys.executable, test_script],
            cwd=SUITE_DIR,
            capture_output=True,
            text=True
        )
        self.assertEqual(proc.returncode, 0, f"test_suite_offline.py failed:\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("Ran 9 tests in", proc.stderr)
        self.assertIn("OK", proc.stderr)
        self.assertIn("TEST SUITE PASSED (100%): ALL VERIFICATIONS SUCCESSFUL", proc.stdout)

    def test_02_line_346_code_audit(self):
        """Audit line 346 in test_suite_offline.py for fixture consistency."""
        test_script = os.path.join(SUITE_DIR, "test_suite_offline.py")
        with open(test_script, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Line 328 (1-indexed, so index 327)
        line_328 = lines[327].strip()
        # Line 346 (1-indexed, so index 345)
        line_346 = lines[345].strip()

        print(f"\n[AUDIT] Line 328: {line_328}")
        print(f"[AUDIT] Line 346: {line_346}")

        self.assertIn('"192.168.0.100"', line_328)
        self.assertIn('"192.168.0.100"', line_346)
        self.assertNotIn("192.168.0.176", line_346, "Stale fixture assertion 192.168.0.176 still present!")


if __name__ == "__main__":
    unittest.main(verbosity=2)
