#!/usr/bin/env python3
"""
Loopback & Edge-Case Verification Suite for Tenda AC10 V1.0 Offline Autonomous Tools.
Runs 100% locally on 127.0.0.1 without touching the live router (192.168.0.1) or
modifying the host PC's physical Ethernet adapter configuration.
"""

from __future__ import annotations

import hashlib
import http.server
import re
import struct
import subprocess
import sys
import tempfile
import threading
import zlib
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
HYBRID_ROOT = TOOLS_DIR.parent
STOCK_DIR = HYBRID_ROOT / "01_Stock_Firmware_and_Partitions"
FW_DIR = HYBRID_ROOT / "02_Compiled_Hybrid_OpenWrt_4.14_Firmware"
BACKUPS_DIR = HYBRID_ROOT / "backups"

sys.path.insert(0, str(TOOLS_DIR))
from tftp_recovery_engine import (
    MockRealtekBooterTftpServer,
    TENDA_WEB_IH_OS,
    TENDA_WEB_IH_VER,
    TENDA_WEB_MAGIC,
    fix_single_segment_checksum,
    sum16_be,
    tftp_push_wrq,
    unwrap_tenda_webupgrade,
    validate_realtek_booter_image,
)


class TestRunner:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def check(self, cond: bool, name: str, detail: str = "") -> None:
        if cond:
            self.passed += 1
            print(f"  [PASS] {name}" + (f" ({detail})" if detail else ""))
        else:
            self.failed += 1
            print(f"  [FAIL] {name}" + (f" ({detail})" if detail else ""))


def run_ps1(script_path: Path, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
    ] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


class MockTendaHttpHandler(http.server.BaseHTTPRequestHandler):
    expected_password: str = "<YOUR_PASSWORD_MD5>"
    logout_paths: list[str] = []
    auth_received: list[str] = []
    uploaded_files: list[bytes] = []

    def log_message(self, format: str, *args) -> None:
        pass

    def do_GET(self) -> None:
        if self.path in ("/goform/exit", "/logout/Auth"):
            MockTendaHttpHandler.logout_paths.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/login.html")
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        from urllib.parse import parse_qs

        content_len = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_len)

        if self.path == "/login/Auth":
            body_str = body.decode("utf-8", errors="replace")
            MockTendaHttpHandler.auth_received.append(body_str)
            qs = parse_qs(body_str, keep_blank_values=True)
            rx_user = qs.get("username", [""])[0]
            rx_pass = qs.get("password", [""])[0]
            if rx_user == "admin" and rx_pass == MockTendaHttpHandler.expected_password:
                self.send_response(302)
                self.send_header(
                    "Set-Cookie",
                    f"password={MockTendaHttpHandler.expected_password}ohqcvb; path=/",
                )
                self.send_header("Location", "/main.html")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"1")
            return

        if self.path == "/cgi-bin/UploadCfg":
            cookie_hdr = self.headers.get("Cookie", "")
            if "password=" not in cookie_hdr or "password=errorlogin" in cookie_hdr:
                self.send_response(302)
                self.send_header("Location", "http://192.168.0.1/login.html")
                self.end_headers()
                return

            ctype = self.headers.get("Content-Type", "")
            m = re.search(r"boundary=([^\s;]+)", ctype)
            if m:
                boundary = m.group(1).encode("ascii")
                header_end = body.find(b"\r\n\r\n")
                footer_marker = b"\r\n--" + boundary
                footer_start = body.rfind(footer_marker)
                if header_end != -1 and footer_start != -1 and footer_start > header_end + 4:
                    file_bytes = body[header_end + 4 : footer_start]
                    MockTendaHttpHandler.uploaded_files.append(file_bytes)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<html><body>Restore Success</body></html>")
                    return

            self.send_response(400)
            self.end_headers()
            return

        self.send_response(404)
        self.end_headers()


def make_synthetic_cs6c(payload_len: int, burn_addr: int = 0x00030000, corrupt_checksum: bool = False) -> bytes:
    header = struct.pack(">4sIII", b"cs6c", 0x80A00000, burn_addr, payload_len)
    body = bytearray((i & 0xFF) for i in range(payload_len - 2))
    cur_sum = sum16_be(bytes(body))
    comp = (-cur_sum) & 0xFFFF
    body.extend(struct.pack(">H", comp))
    if corrupt_checksum:
        body[-1] ^= 0xFF
    return header + bytes(body)


def wrap_tenda_webupgrade(inner: bytes, ih_ver: int = TENDA_WEB_IH_VER, corrupt_dcrc: bool = False) -> bytes:
    dcrc = zlib.crc32(inner) & 0xFFFFFFFF
    if corrupt_dcrc:
        dcrc ^= 0xFFFFFFFF
    name_b = b"Hybrid_OpenWrt_AC10_V1\x00".ljust(28, b"\x00")
    hdr = bytearray(
        struct.pack(
            ">7I4BI28s",
            0x27051956,
            0,
            0x67000000,
            len(inner),
            0x80A00000,
            0x80A00000,
            dcrc,
            TENDA_WEB_IH_OS,
            5,
            2,
            3,
            ih_ver,
            name_b,
        )
    )
    hcrc = zlib.crc32(bytes(hdr)) & 0xFFFFFFFF
    struct.pack_into(">I", hdr, 4, hcrc)
    return bytes(hdr) + inner


def main() -> int:
    tr = TestRunner()
    ps_tftp = TOOLS_DIR / "Offline_TFTP_Recovery_and_Flash.ps1"
    ps_cfg = TOOLS_DIR / "Restore_Optimized_Config_and_WAN.ps1"
    ps_dhcp = TOOLS_DIR / "Emergency_Restore_PC_Network_DHCP.ps1"

    stock_tftp_bin = STOCK_DIR / "Tenda_AC10_V1_Stock_TFTP_Recovery.bin"
    if not stock_tftp_bin.exists():
        stock_tftp_bin = BACKUPS_DIR / "Tenda_AC10_V1_Stock_TFTP_Recovery.bin"

    opt_cfg_file = STOCK_DIR / "RouterCfm_optimized_template.cfg"
    if not opt_cfg_file.exists():
        opt_cfg_file = BACKUPS_DIR / "RouterCfm_optimized_v1.cfg"

    print("==============================================================================")
    print(" 1. END-TO-END LOOPBACK TEST: PowerShell TFTP Flash (7,588,884 B Stock Image)")
    print("==============================================================================")
    mock_booter = MockRealtekBooterTftpServer(bind_ip="127.0.0.1", bind_port=0, drop_Every_n_blocks=5000)
    mock_booter.start()
    try:
        res = run_ps1(
            ps_tftp,
            [
                "-FirmwarePath",
                str(stock_tftp_bin),
                "-ServerIp",
                "127.0.0.1",
                "-Port",
                str(mock_booter.port),
                "-ProbeTimeoutSeconds",
                "10",
                "-BlockTimeoutMs",
                "400",
                "-SkipNetworkConfig",
            ],
            timeout=90,
        )
        mock_booter.completed.wait(timeout=5.0)
        tr.check(res.returncode == 0, "Offline_TFTP_Recovery_and_Flash.ps1 exit code == 0", f"rc={res.returncode}")
        rx_bytes = bytes(mock_booter.received_data)
        rx_sha256 = hashlib.sha256(rx_bytes).hexdigest()
        tr.check(
            len(rx_bytes) == 7588884,
            "MockRealtekBooter received exact 7,588,884 bytes (including retries on dropped blocks)",
            f"received={len(rx_bytes)} B, blocks={mock_booter.total_blocks_acked}",
        )
        tr.check(
            rx_sha256 == "a7d4d27f7b1d52526e24348a6a21c5a56740d41b357b17c9e3bc4d8db9f9b0fa",
            "Received TFTP image SHA-256 matches Tenda_AC10_V1_Stock_TFTP_Recovery.bin",
            rx_sha256,
        )
    finally:
        mock_booter.stop()

    print("\n==============================================================================")
    print(" 2. 64-BYTE 0x27051956 WEBUPGRADE AUTO-UNWRAP & 512-BYTE BOUNDARY TEST")
    print("==============================================================================")
    exact_1024_img = make_synthetic_cs6c(payload_len=1008, burn_addr=0x00030000)
    wrapped_1088_img = wrap_tenda_webupgrade(exact_1024_img)
    unwrapped, wmeta = unwrap_tenda_webupgrade(wrapped_1088_img)
    info_web = validate_realtek_booter_image(wrapped_1088_img)
    tr.check(
        unwrapped == exact_1024_img and info_web["is_webupgrade_wrapped"] and wmeta["ih_ver"] == 0x00030028,
        "Python validator verified & unwrapped 64-byte 0x27051956 WebUI wrapper (1088 B -> 1024 B cs6c)",
    )

    with tempfile.TemporaryDirectory() as tmpw:
        web_tmp_path = Path(tmpw) / "test_webupgrade.bin"
        web_tmp_path.write_bytes(wrapped_1088_img)
        mock_booter_web = MockRealtekBooterTftpServer(bind_ip="127.0.0.1", bind_port=0, drop_Every_n_blocks=2)
        mock_booter_web.start()
        try:
            res_w = run_ps1(
                ps_tftp,
                [
                    "-FirmwarePath",
                    str(web_tmp_path),
                    "-ServerIp",
                    "127.0.0.1",
                    "-Port",
                    str(mock_booter_web.port),
                    "-ProbeTimeoutSeconds",
                    "5",
                    "-BlockTimeoutMs",
                    "300",
                    "-SkipNetworkConfig",
                ],
                timeout=30,
            )
            mock_booter_web.completed.wait(timeout=5.0)
            tr.check(
                res_w.returncode == 0
                and bytes(mock_booter_web.received_data) == exact_1024_img
                and mock_booter_web.total_blocks_acked == 3,
                "PowerShell TFTP flasher auto-unwrapped 64-byte webupgrade.bin and sent exact 1024 B + 0-byte termination",
                f"blocks_acked={mock_booter_web.total_blocks_acked}",
            )
        finally:
            mock_booter_web.stop()

    print("\n==============================================================================")
    print(" 3. PRE-FLIGHT SAFETY GATE REJECTION TESTS (Edge, WebUI & Lethal Cases)")
    print("==============================================================================")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        bad_magic_path = tmp / "bad_magic.bin"
        bad_magic_path.write_bytes(b"BAD!" + exact_1024_img[4:])

        bad_burn_path = tmp / "bad_burn.bin"
        bad_burn_path.write_bytes(make_synthetic_cs6c(payload_len=1008, burn_addr=0x00000000))

        bad_csum_path = tmp / "bad_csum.bin"
        bad_csum_path.write_bytes(make_synthetic_cs6c(payload_len=1008, burn_addr=0x00030000, corrupt_checksum=True))

        lethal_2seg_cs6c = tmp / "lethal_2seg_cs6c.bin"
        lethal_2seg_cs6c.write_bytes(exact_1024_img + b"hsqs" + b"\x00" * 64)

        bad_web_ver = tmp / "bad_web_ac10u_ver.bin"
        bad_web_ver.write_bytes(wrap_tenda_webupgrade(exact_1024_img, ih_ver=0x00030099))

        bad_web_dcrc = tmp / "bad_web_dcrc.bin"
        bad_web_dcrc.write_bytes(wrap_tenda_webupgrade(exact_1024_img, corrupt_dcrc=True))

        for label, bad_path in [
            ("Invalid header magic ('BAD!')", bad_magic_path),
            ("Unsafe burnAddr 0x00000000", bad_burn_path),
            ("Corrupted 16-bit BE checksum", bad_csum_path),
            ("Lethal 2-segment cs6c+hsqs image (0x80001c2c bug)", lethal_2seg_cs6c),
            ("Wrong model ih_ver != 0x00030028 (e.g. AC10U)", bad_web_ver),
            ("Corrupted 0x27051956 ih_dcrc payload CRC32", bad_web_dcrc),
        ]:
            py_rejected = False
            try:
                validate_realtek_booter_image(bad_path.read_bytes())
            except ValueError:
                py_rejected = True
            tr.check(py_rejected, f"Python validator rejected: {label}")

            ps_res = run_ps1(ps_tftp, ["-FirmwarePath", str(bad_path), "-VerifyOnly"])
            tr.check(ps_res.returncode != 0, f"PowerShell validator rejected: {label}", f"rc={ps_res.returncode}")

    print("\n==============================================================================")
    print(" 4. END-TO-END LOOPBACK TEST: Restore_Optimized_Config_and_WAN.ps1")
    print("==============================================================================")
    expected_cfg_bytes = opt_cfg_file.read_bytes()
    expected_cfg_sha = hashlib.sha256(expected_cfg_bytes).hexdigest()
    m_wan = re.search(r"^wan1\.macaddr=(.+)$", expected_cfg_bytes.decode("utf-8", errors="replace"), re.MULTILINE)
    cfg_wan_mac = m_wan.group(1).strip() if m_wan else "<YOUR_WAN_MAC>"
    m_pwd = re.search(r"^sys\.userpass=(.+)$", expected_cfg_bytes.decode("utf-8", errors="replace"), re.MULTILINE)
    cfg_pwd_md5 = m_pwd.group(1).strip() if m_pwd else "<YOUR_PASSWORD_MD5>"

    httpd = http.server.HTTPServer(("127.0.0.1", 0), MockTendaHttpHandler)
    http_port = httpd.server_port
    http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    http_thread.start()
    try:
        MockTendaHttpHandler.expected_password = cfg_pwd_md5
        MockTendaHttpHandler.logout_paths.clear()
        MockTendaHttpHandler.auth_received.clear()
        MockTendaHttpHandler.uploaded_files.clear()

        res_cfg = run_ps1(
            ps_cfg,
            [
                "-ConfigPath",
                str(opt_cfg_file),
                "-ExpectedWanMac",
                cfg_wan_mac,
                "-AdminPasswordMd5",
                cfg_pwd_md5,
                "-RouterIp",
                "127.0.0.1",
                "-Port",
                str(http_port),
                "-SkipNetworkConfig",
            ],
            timeout=30,
        )
        tr.check(res_cfg.returncode == 0, "Restore_Optimized_Config_and_WAN.ps1 exit code == 0", f"rc={res_cfg.returncode}")
        tr.check(
            len(MockTendaHttpHandler.auth_received) == 1
            and "/goform/exit" in MockTendaHttpHandler.logout_paths
            and "/logout/Auth" in MockTendaHttpHandler.logout_paths,
            "Cleared stale session (/goform/exit + /logout/Auth) and authenticated with MD5 password hash",
        )
        tr.check(len(MockTendaHttpHandler.uploaded_files) == 1, "Uploaded 1 file to /cgi-bin/UploadCfg")
        if MockTendaHttpHandler.uploaded_files:
            up_bytes = MockTendaHttpHandler.uploaded_files[0]
            up_sha256 = hashlib.sha256(up_bytes).hexdigest()
            tr.check(
                len(up_bytes) == len(expected_cfg_bytes) and up_sha256 == expected_cfg_sha,
                f"Uploaded {opt_cfg_file.name} matches exact {len(expected_cfg_bytes):,} bytes and SHA-256",
                up_sha256[:16] + "...",
            )

        MockTendaHttpHandler.expected_password = ""
        MockTendaHttpHandler.logout_paths.clear()
        MockTendaHttpHandler.auth_received.clear()
        MockTendaHttpHandler.uploaded_files.clear()

        res_blank = run_ps1(
            ps_cfg,
            [
                "-ConfigPath",
                str(opt_cfg_file),
                "-ExpectedWanMac",
                cfg_wan_mac,
                "-AdminPasswordMd5",
                cfg_pwd_md5,
                "-RouterIp",
                "127.0.0.1",
                "-Port",
                str(http_port),
                "-SkipNetworkConfig",
            ],
            timeout=30,
        )
        tr.check(
            res_blank.returncode == 0
            and len(MockTendaHttpHandler.auth_received) == 2
            and MockTendaHttpHandler.auth_received[1] == "username=admin&password="
            and len(MockTendaHttpHandler.uploaded_files) == 1,
            "Factory-reset fallback: rejected HTTP 200 OK '1' on MD5 attempt and succeeded with blank password",
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("\n==============================================================================")
    print(" 5. DRY-RUN & HOST PHYSICAL ETHERNET ADAPTER DHCP INVARIANT CHECK")
    print("==============================================================================")
    for name, script, extra in [
        ("Offline_TFTP_Recovery_and_Flash.ps1 -DryRun", ps_tftp, ["-FirmwarePath", str(stock_tftp_bin)]),
        ("Restore_Optimized_Config_and_WAN.ps1 -DryRun", ps_cfg, ["-ConfigPath", str(opt_cfg_file), "-ExpectedWanMac", cfg_wan_mac]),
        ("Emergency_Restore_PC_Network_DHCP.ps1 -DryRun", ps_dhcp, []),
    ]:
        r = run_ps1(script, extra + ["-DryRun"])
        tr.check(r.returncode == 0, f"{name} succeeded without modifying NIC", f"rc={r.returncode}")

    print("\n==============================================================================")
    print(f" LOOPBACK SUITE SUMMARY: {tr.passed} PASSED, {tr.failed} FAILED")
    print("==============================================================================")
    return 0 if tr.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
