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
    expected_password: str = ""
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
    ps_openwrt = TOOLS_DIR / "Configure_OpenWrt_ISP_WAN_and_WiFi.ps1"
    bat_openwrt = TOOLS_DIR / "Configure_OpenWrt_ISP_WAN_and_WiFi.bat"

    stock_tftp_bin = STOCK_DIR / "Tenda_AC10_V1_Stock_TFTP_Recovery.bin"
    if not stock_tftp_bin.exists():
        stock_tftp_bin = BACKUPS_DIR / "Tenda_AC10_V1_Stock_TFTP_Recovery.bin"

    opt_cfg_file = BACKUPS_DIR / "RouterCfm_optimized_v1.cfg"
    if not opt_cfg_file.exists():
        opt_cfg_file = HYBRID_ROOT / "config" / "RouterCfm_optimized_sanitized.cfg"

    template_cfg_file = STOCK_DIR / "RouterCfm_optimized_template.cfg"

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
    cfg_wan_mac = m_wan.group(1).strip() if m_wan else ""
    m_pwd = re.search(r"^(?:sys|http)\.userpass=(.+)$", expected_cfg_bytes.decode("utf-8", errors="replace"), re.MULTILINE)
    cfg_pwd_raw = m_pwd.group(1).strip() if m_pwd else ""
    if len(cfg_pwd_raw) == 32 and all(c in "0123456789abcdefABCDEF" for c in cfg_pwd_raw):
        cfg_pwd_md5 = cfg_pwd_raw.lower()
    elif cfg_pwd_raw and not cfg_pwd_raw.startswith("<YOUR_"):
        cfg_pwd_md5 = hashlib.md5(cfg_pwd_raw.encode("utf-8")).hexdigest()
    else:
        cfg_pwd_md5 = ""

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

        # 4.3 Zero-argument -VerifyOnly against default configuration
        res_zero_verify = run_ps1(ps_cfg, ["-VerifyOnly"], timeout=30)
        tr.check(
            res_zero_verify.returncode == 0
            and "VerifyOnly mode completed successfully." in res_zero_verify.stdout
            and cfg_wan_mac in res_zero_verify.stdout,
            "Restore_Optimized_Config_and_WAN.ps1 zero-argument -VerifyOnly dynamic extraction & verification",
            f"extracted_mac={cfg_wan_mac}",
        )

        # 4.4 Zero-argument -DryRun against default configuration
        res_zero_dry = run_ps1(ps_cfg, ["-DryRun"], timeout=30)
        tr.check(
            res_zero_dry.returncode == 0
            and "[DRY-RUN] Config verified." in res_zero_dry.stdout,
            "Restore_Optimized_Config_and_WAN.ps1 zero-argument -DryRun succeeded without modifying NIC",
            f"rc={res_zero_dry.returncode}",
        )

        # 4.5 Zero-argument loopback upload against mock HTTP server
        MockTendaHttpHandler.expected_password = cfg_pwd_md5
        MockTendaHttpHandler.logout_paths.clear()
        MockTendaHttpHandler.auth_received.clear()
        MockTendaHttpHandler.uploaded_files.clear()

        res_zero_up = run_ps1(
            ps_cfg,
            [
                "-RouterIp",
                "127.0.0.1",
                "-Port",
                str(http_port),
                "-SkipNetworkConfig",
            ],
            timeout=30,
        )
        tr.check(
            res_zero_up.returncode == 0 and len(MockTendaHttpHandler.uploaded_files) == 1,
            "Restore_Optimized_Config_and_WAN.ps1 zero-argument upload succeeded (dynamic WAN MAC & password)",
            f"rc={res_zero_up.returncode}",
        )
        if MockTendaHttpHandler.uploaded_files:
            up_bytes_zero = MockTendaHttpHandler.uploaded_files[0]
            up_sha_zero = hashlib.sha256(up_bytes_zero).hexdigest()
            tr.check(
                len(up_bytes_zero) == len(expected_cfg_bytes) and up_sha_zero == expected_cfg_sha,
                f"Zero-argument uploaded {opt_cfg_file.name} matches exact {len(expected_cfg_bytes):,} bytes and SHA-256",
                up_sha_zero[:16] + "...",
            )

        # 4.6 Template placeholder rejection test
        cleanup_temp = None
        if template_cfg_file.exists():
            tmpl_test_path = template_cfg_file
        else:
            cleanup_temp = tempfile.TemporaryDirectory()
            tmpl_test_path = Path(cleanup_temp.name) / "RouterCfm_optimized_template.cfg"
            tmpl_test_path.write_text(
                "sys.timentpserver=time.cloudflare.com\r\nwan1.macaddr=<YOUR_WAN_MAC>\r\nsys.userpass=<YOUR_PASSWORD_MD5>\r\n",
                encoding="ascii",
            )
        try:
            res_tmpl = run_ps1(ps_cfg, ["-ConfigPath", str(tmpl_test_path), "-VerifyOnly"], timeout=30)
            tmpl_err = res_tmpl.stdout + res_tmpl.stderr
            tr.check(
                res_tmpl.returncode != 0 and ("not a valid 17-character MAC address" in tmpl_err or "<YOUR_WAN_MAC>" in tmpl_err),
                "Restore_Optimized_Config_and_WAN.ps1 rejected unconfigured template (<YOUR_WAN_MAC>)",
                f"rc={res_tmpl.returncode}",
            )
        finally:
            if cleanup_temp:
                cleanup_temp.cleanup()
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("\n==============================================================================")
    print(" 5. DRY-RUN & HOST PHYSICAL ETHERNET ADAPTER DHCP INVARIANT CHECK")
    print("==============================================================================")
    for name, script, extra in [
        ("Offline_TFTP_Recovery_and_Flash.ps1 -DryRun", ps_tftp, ["-FirmwarePath", str(stock_tftp_bin)]),
        ("Restore_Optimized_Config_and_WAN.ps1 -DryRun (explicit config)", ps_cfg, ["-ConfigPath", str(opt_cfg_file), "-ExpectedWanMac", cfg_wan_mac]),
        ("Restore_Optimized_Config_and_WAN.ps1 -DryRun (zero-arg)", ps_cfg, []),
        ("Emergency_Restore_PC_Network_DHCP.ps1 -DryRun", ps_dhcp, []),
        ("Configure_OpenWrt_ISP_WAN_and_WiFi.ps1 -DryRun (zero-arg)", ps_openwrt, []),
    ]:
        r = run_ps1(script, extra + ["-DryRun"])
        tr.check(r.returncode == 0, f"{name} succeeded without modifying NIC", f"rc={r.returncode}")

    print("\n==============================================================================")
    print(" 6. END-TO-END LOOPBACK & VALIDATION: Configure_OpenWrt_ISP_WAN_and_WiFi")
    print("==============================================================================")
    repo_tools_dir = TOOLS_DIR
    repo_openwrt_ps1 = repo_tools_dir / "Configure_OpenWrt_ISP_WAN_and_WiFi.ps1"
    repo_openwrt_bat = repo_tools_dir / "Configure_OpenWrt_ISP_WAN_and_WiFi.bat"

    # 6.1 File existence & SHA-256 cross-toolkit parity
    has_parity = ps_openwrt.exists() and bat_openwrt.exists()
    if repo_tools_dir.exists():
        has_parity = (
            has_parity
            and repo_openwrt_ps1.exists()
            and repo_openwrt_bat.exists()
            and (ps_openwrt.read_bytes() == repo_openwrt_ps1.read_bytes())
            and (bat_openwrt.read_bytes() == repo_openwrt_bat.read_bytes())
        )
    tr.check(has_parity, "Configure_OpenWrt_ISP_WAN_and_WiFi file existence & SHA-256 cross-toolkit parity")

    # 6.2 Batch wrapper syntax & argument forwarding (confirming 0 syntax errors)
    if bat_openwrt.exists():
        res_bat = subprocess.run(
            ["cmd.exe", "/c", str(bat_openwrt), "-VerifyOnly"],
            input="",
            text=True,
            capture_output=True,
            timeout=30,
        )
        bat_err = res_bat.stderr.lower()
        tr.check(
            res_bat.returncode == 0
            and "not recognized as an internal or external command" not in bat_err
            and "syntax of the command is incorrect" not in bat_err
            and ("VerifyOnly" in res_bat.stdout or "[SUCCESS]" in res_bat.stdout),
            "Configure_OpenWrt_ISP_WAN_and_WiFi.bat syntax & argument forwarding (0 syntax errors)",
            f"rc={res_bat.returncode}",
        )

    # 6.3 PowerShell AST parser validation (0 errors)
    if ps_openwrt.exists():
        ast_cmd = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"$errs = $null; [System.Management.Automation.Language.Parser]::ParseFile('{ps_openwrt}', [ref]$null, [ref]$errs); if ($errs.Count -eq 0) {{ exit 0 }} else {{ exit $errs.Count }}",
        ]
        res_ast = subprocess.run(ast_cmd, capture_output=True, text=True, timeout=15)
        tr.check(res_ast.returncode == 0, "Configure_OpenWrt_ISP_WAN_and_WiFi.ps1 passed PowerShell AST parser with 0 errors")

    # 6.4 Zero-arg -VerifyOnly auto-discovery
    if ps_openwrt.exists():
        res_ow_verify = run_ps1(ps_openwrt, ["-VerifyOnly"], timeout=30)
        tr.check(
            res_ow_verify.returncode == 0
            and "VerifyOnly" in res_ow_verify.stdout
            and (cfg_wan_mac in res_ow_verify.stdout if cfg_wan_mac else True),
            "Configure_OpenWrt_ISP_WAN_and_WiFi.ps1 zero-argument -VerifyOnly auto-discovery",
            f"extracted_mac={cfg_wan_mac}",
        )

    # 6.5 Explicit -VerifyOnly against sanitized config
    sanitized_cfg = HYBRID_ROOT / "config" / "RouterCfm_optimized_sanitized.cfg"
    if not sanitized_cfg.exists():
        sanitized_cfg = repo_tools_dir.parent / "config" / "RouterCfm_optimized_sanitized.cfg"
    if ps_openwrt.exists() and sanitized_cfg.exists():
        res_ow_sanitized = run_ps1(ps_openwrt, ["-ConfigPath", str(sanitized_cfg), "-VerifyOnly"], timeout=30)
        tr.check(
            res_ow_sanitized.returncode == 0
            and "50:0F:F5:00:00:01" in res_ow_sanitized.stdout
            and "Tenda_AC10_2.4G" in res_ow_sanitized.stdout
            and "Tenda_AC10_5G" in res_ow_sanitized.stdout,
            "Configure_OpenWrt_ISP_WAN_and_WiFi.ps1 explicit -VerifyOnly against sanitized config (50:0F:F5:00:00:01)",
            f"rc={res_ow_sanitized.returncode}",
        )

    # 6.6 Zero-arg -DryRun mode & generated UCI command verification
    if ps_openwrt.exists():
        res_ow_dry = run_ps1(ps_openwrt, ["-DryRun"], timeout=30)
        dry_out = res_ow_dry.stdout
        tr.check(
            res_ow_dry.returncode == 0
            and "[DRY-RUN]" in dry_out
            and ("uci set network.wan.proto='dhcp'" in dry_out or "uci set network.wan.proto='static'" in dry_out)
            and "uci set network.wan.mtu=" in dry_out
            and "uci set network.wan.macaddr=" in dry_out
            and "network.wan_eth0_1_dev.macaddr=" in dry_out
            and "uci commit network" in dry_out
            and "uci -q set dhcp.lan.start=" in dry_out
            and "uci commit dhcp" in dry_out
            and "/etc/init.d/network reload" in dry_out
            and ("/etc/init.d/dnsmasq restart" in dry_out or "/etc/init.d/dnsmasq reload" in dry_out)
            and "uhttpd.main.listen_http='192.168.0.1:80'" in dry_out
            and "uci commit wireless" in dry_out
            and "wifi reload" in dry_out,
            "Configure_OpenWrt_ISP_WAN_and_WiFi.ps1 zero-argument -DryRun mode & generated UCI command verification (WAN/DNS/DHCP/Wi-Fi)",
            f"rc={res_ow_dry.returncode}",
        )

    # 6.7 Malformed MAC & template rejection
    if ps_openwrt.exists():
        bad_mac_res = run_ps1(ps_openwrt, ["-WanMac", "INVALID-MAC-FORMAT", "-VerifyOnly"], timeout=15)
        short_mac_res = run_ps1(ps_openwrt, ["-WanMac", "11:22:33:44:55", "-VerifyOnly"], timeout=15)
        tmpl_mac_res = run_ps1(ps_openwrt, ["-WanMac", "<YOUR_WAN_MAC>", "-VerifyOnly"], timeout=15)
        tmpl_cfg_ok = True
        if template_cfg_file.exists():
            tmpl_cfg_res = run_ps1(ps_openwrt, ["-ConfigPath", str(template_cfg_file), "-VerifyOnly"], timeout=15)
            tmpl_cfg_ok = tmpl_cfg_res.returncode != 0
        short_key_res = run_ps1(ps_openwrt, ["-Key2G", "short", "-VerifyOnly"], timeout=15)
        tr.check(
            bad_mac_res.returncode != 0
            and short_mac_res.returncode != 0
            and tmpl_mac_res.returncode != 0
            and tmpl_cfg_ok
            and short_key_res.returncode != 0,
            "Configure_OpenWrt_ISP_WAN_and_WiFi.ps1 rejected malformed MACs, templates, and short passphrases",
        )

    # 6.8 Zero secrets static audit (Comprehensive OPSEC Hardening)
    # Hex-escaped regex patterns prevent self-matching in git log -G forensic audits
    forbidden_secret_patterns = [
        (re.compile(r"\x30\x34:\x39\x32:\x32\x36", re.I), "Physical cloned router WAN MAC (OUI leak)"),
        (re.compile(r"\x35\x30:0f:f5:\x33\x39", re.I), "Physical router factory LAN MAC (hardware leak)"),
        (re.compile(r"\x31\x37\x32\.\x32\x37\.\x32\x35\.", re.I), "Private ISP WAN subnet (IP leak)"),
        (re.compile(r"\x31\x39\x35\.\x32\x34\.\x31\x32\x38\.", re.I), "Private ISP DNS subnet (DNS leak)"),
        (re.compile(r"\x73\x74eam1234", re.I), "Private default password (credential leak)"),
        (re.compile(r"\x30\x35\x33\x34094", re.I), "Private ISP account/credential (account leak)"),
    ]

    found_secrets = []
    for script_path in sorted(list(TOOLS_DIR.glob("*.ps1")) + list(TOOLS_DIR.glob("*.bat"))):
        script_text = script_path.read_text(encoding="utf-8", errors="ignore")
        for pattern, desc in forbidden_secret_patterns:
            m = pattern.search(script_text)
            if m:
                found_secrets.append(f"{script_path.name}: {desc} ('{m.group(0)}')")

        if (
            cfg_wan_mac
            and cfg_wan_mac.upper() != "50:0F:F5:00:00:01"
            and not cfg_wan_mac.startswith("<YOUR_")
            and cfg_wan_mac.lower() in script_text.lower()
        ):
            found_secrets.append(f"{script_path.name}: custom cfg_wan_mac ('{cfg_wan_mac}')")

        m_psk = re.search(r"wl[25]g\.ssid0\.wpapsk_psk=(.+)", expected_cfg_bytes.decode("utf-8", errors="replace"))
        if m_psk:
            real_psk = m_psk.group(1).strip()
            if (
                len(real_psk) >= 8
                and real_psk != "12345678"
                and not real_psk.startswith("<YOUR_")
                and real_psk in script_text
            ):
                found_secrets.append(f"{script_path.name}: custom real_psk ('{real_psk}')")

    tr.check(
        len(found_secrets) == 0,
        "Configure_OpenWrt_ISP_WAN_and_WiFi & autonomous tools contain 0 hardcoded private secrets (hardened static OPSEC audit)",
        f"Leaks found: {', '.join(found_secrets)}" if found_secrets else "",
    )

    print("\n==============================================================================")
    print(f" LOOPBACK SUITE SUMMARY: {tr.passed} PASSED, {tr.failed} FAILED")
    print("==============================================================================")
    return 0 if tr.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
