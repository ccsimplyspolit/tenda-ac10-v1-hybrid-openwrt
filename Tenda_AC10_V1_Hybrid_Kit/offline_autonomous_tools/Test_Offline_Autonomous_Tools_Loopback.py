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
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
HYBRID_ROOT = TOOLS_DIR.parent
BACKUPS_DIR = HYBRID_ROOT / "backups"

sys.path.insert(0, str(TOOLS_DIR))
from tftp_recovery_engine import (
    MockRealtekBooterTftpServer,
    fix_single_segment_checksum,
    sum16_be,
    tftp_push_wrq,
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
        pass  # Suppress noisy HTTP logs

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
        content_len = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_len)

        if self.path == "/login/Auth":
            body_str = body.decode("utf-8", errors="replace")
            MockTendaHttpHandler.auth_received.append(body_str)
            expected_form = f"username=admin&password={MockTendaHttpHandler.expected_password}"
            if body_str == expected_form:
                self.send_response(302)
                self.send_header(
                    "Set-Cookie",
                    f"password={MockTendaHttpHandler.expected_password}ohqcvb; path=/",
                )
                self.send_header("Location", "/main.html")
                self.end_headers()
            else:
                # Real Tenda bin/httpd (VA 0x436918) returns HTTP 200 OK with body '1' on wrong password
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"1")
            return

        if self.path == "/cgi-bin/UploadCfg":
            cookie_hdr = self.headers.get("Cookie", "")
            if "password=" not in cookie_hdr or "password=errorlogin" in cookie_hdr:
                # Real Tenda bin/httpd (VA 0x436230) redirects unauthenticated /cgi-bin/UploadCfg to /login.html
                self.send_response(302)
                self.send_header("Location", "http://192.168.0.1/login.html")
                self.end_headers()
                return

            ctype = self.headers.get("Content-Type", "")
            m = re.search(r"boundary=([^\s;]+)", ctype)
            if m:
                boundary = m.group(1).encode("ascii")
                # Extract payload between double CRLF and CRLF--boundary
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


def main() -> int:
    tr = TestRunner()
    ps_tftp = TOOLS_DIR / "Offline_TFTP_Recovery_and_Flash.ps1"
    ps_cfg = TOOLS_DIR / "Restore_Optimized_Config_and_WAN.ps1"
    ps_dhcp = TOOLS_DIR / "Emergency_Restore_PC_Network_DHCP.ps1"
    stock_tftp_bin = BACKUPS_DIR / "Tenda_AC10_V1_Stock_TFTP_Recovery.bin"
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
    print(" 2. EXACT 512-BYTE MULTIPLE & ZERO-BYTE TERMINATION TEST (Python Engine)")
    print("==============================================================================")
    # Total image size = 1024 bytes (16-byte cs6c header + 1008-byte payload) -> exact 2 * 512 blocks + 1 zero-length block
    exact_1024_img = make_synthetic_cs6c(payload_len=1008, burn_addr=0x00030000)
    info_1024 = validate_realtek_booter_image(exact_1024_img)
    tr.check(info_1024["size"] == 1024, "Synthetic 1024-byte cs6c checksum == 0x0000")

    mock_booter2 = MockRealtekBooterTftpServer(bind_ip="127.0.0.1", bind_port=0, drop_Every_n_blocks=2)
    mock_booter2.start()
    try:
        tftp_push_wrq(
            payload=exact_1024_img,
            server_ip="127.0.0.1",
            server_port=mock_booter2.port,
            probe_timeout=5.0,
            block_timeout=0.3,
            quiet=True,
        )
        mock_booter2.completed.wait(timeout=5.0)
        tr.check(
            bytes(mock_booter2.received_data) == exact_1024_img,
            "Python TFTP engine delivered exact 1024-byte payload",
        )
        tr.check(
            mock_booter2.total_blocks_acked == 3,
            "Exact 512-byte multiple sent trailing 0-byte termination packet (3 blocks total)",
            f"blocks_acked={mock_booter2.total_blocks_acked}",
        )
    finally:
        mock_booter2.stop()

    print("\n==============================================================================")
    print(" 3. PRE-FLIGHT SAFETY GATE REJECTION TESTS (Edge & Lethal Cases)")
    print("==============================================================================")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Case A: Bad magic
        bad_magic_path = tmp / "bad_magic.bin"
        bad_magic_path.write_bytes(b"BAD!" + exact_1024_img[4:])

        # Case B: Unsafe burnAddr 0x00000000 (would overwrite bootloader)
        bad_burn_path = tmp / "bad_burn.bin"
        bad_burn_path.write_bytes(make_synthetic_cs6c(payload_len=1008, burn_addr=0x00000000))

        # Case C: Corrupted checksum
        bad_csum_path = tmp / "bad_csum.bin"
        bad_csum_path.write_bytes(make_synthetic_cs6c(payload_len=1008, burn_addr=0x00030000, corrupt_checksum=True))

        # Case D: Lethal multi-segment cs6c + hsqs (triggers Realtek Booter 0x80001c2c $s7=0 erase bug)
        lethal_2seg_cs6c = tmp / "lethal_2seg_cs6c.bin"
        lethal_2seg_cs6c.write_bytes(exact_1024_img + b"hsqs" + b"\x00" * 64)

        for label, bad_path in [
            ("Invalid header magic ('BAD!')", bad_magic_path),
            ("Unsafe burnAddr 0x00000000", bad_burn_path),
            ("Corrupted 16-bit BE checksum", bad_csum_path),
            ("Lethal 2-segment cs6c+hsqs image (0x80001c2c bug)", lethal_2seg_cs6c),
        ]:
            # Test Python validator
            py_rejected = False
            try:
                validate_realtek_booter_image(bad_path.read_bytes())
            except ValueError:
                py_rejected = True
            tr.check(py_rejected, f"Python validator rejected: {label}")

            # Test PowerShell validator
            ps_res = run_ps1(ps_tftp, ["-FirmwarePath", str(bad_path), "-VerifyOnly"])
            tr.check(ps_res.returncode != 0, f"PowerShell validator rejected: {label}", f"rc={ps_res.returncode}")

    print("\n==============================================================================")
    print(" 4. END-TO-END LOOPBACK TEST: Restore_Optimized_Config_and_WAN.ps1")
    print("==============================================================================")
    httpd = http.server.HTTPServer(("127.0.0.1", 0), MockTendaHttpHandler)
    http_port = httpd.server_port
    http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    http_thread.start()
    try:
        # Case 4A: Configured router with MD5("<YOUR_WIFI_PASSWORD>") = <YOUR_PASSWORD_MD5>
        MockTendaHttpHandler.expected_password = "<YOUR_PASSWORD_MD5>"
        MockTendaHttpHandler.logout_paths.clear()
        MockTendaHttpHandler.auth_received.clear()
        MockTendaHttpHandler.uploaded_files.clear()

        res_cfg = run_ps1(
            ps_cfg,
            [
                "-ConfigPath",
                str(opt_cfg_file),
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
            and MockTendaHttpHandler.auth_received[0] == "username=admin&password=<YOUR_PASSWORD_MD5>"
            and "/goform/exit" in MockTendaHttpHandler.logout_paths
            and "/logout/Auth" in MockTendaHttpHandler.logout_paths,
            "Cleared stale session (/goform/exit + /logout/Auth) and authenticated with MD5 password hash",
        )
        tr.check(len(MockTendaHttpHandler.uploaded_files) == 1, "Uploaded 1 file to /cgi-bin/UploadCfg")
        if MockTendaHttpHandler.uploaded_files:
            up_bytes = MockTendaHttpHandler.uploaded_files[0]
            up_sha256 = hashlib.sha256(up_bytes).hexdigest()
            tr.check(
                len(up_bytes) == 25369
                and up_sha256 == "078243bc81190d7012c6d3b1f9dd8d00c70ea6c4e7b23dc1bbbe373e0d02b9bd",
                "Uploaded RouterCfm_optimized_v1.cfg matches exact 25,369 bytes and SHA-256",
                up_sha256,
            )

        # Case 4B: Factory-reset router with blank password ("") where first attempt (MD5) returns HTTP 200 OK body "1"
        MockTendaHttpHandler.expected_password = ""
        MockTendaHttpHandler.logout_paths.clear()
        MockTendaHttpHandler.auth_received.clear()
        MockTendaHttpHandler.uploaded_files.clear()

        res_blank = run_ps1(
            ps_cfg,
            [
                "-ConfigPath",
                str(opt_cfg_file),
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
            and MockTendaHttpHandler.auth_received
            == [
                "username=admin&password=<YOUR_PASSWORD_MD5>",
                "username=admin&password=",
            ]
            and len(MockTendaHttpHandler.uploaded_files) == 1,
            "Factory-reset fallback: rejected HTTP 200 OK '1' on MD5 attempt and succeeded with blank password",
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("\n==============================================================================")
    print(" 5. DRY-RUN & HOST PHYSICAL ETHERNET (Intel I225-V) DHCP INVARIANT CHECK")
    print("==============================================================================")
    for name, script in [
        ("Offline_TFTP_Recovery_and_Flash.ps1 -DryRun", ps_tftp),
        ("Restore_Optimized_Config_and_WAN.ps1 -DryRun", ps_cfg),
        ("Emergency_Restore_PC_Network_DHCP.ps1 -DryRun", ps_dhcp),
    ]:
        r = run_ps1(script, ["-DryRun"])
        tr.check(r.returncode == 0, f"{name} succeeded without modifying NIC", f"rc={r.returncode}")

    nic_check = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "(Get-NetIPInterface -InterfaceAlias 'Ethernet' -AddressFamily IPv4).Dhcp",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    dhcp_state = nic_check.stdout.strip()
    tr.check(dhcp_state == "Enabled", "Host physical 'Ethernet' (Intel I225-V) remains Dhcp=Enabled", f"Dhcp={dhcp_state}")

    print("\n==============================================================================")
    print(f" LOOPBACK SUITE SUMMARY: {tr.passed} PASSED, {tr.failed} FAILED")
    print("==============================================================================")
    return 0 if tr.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
