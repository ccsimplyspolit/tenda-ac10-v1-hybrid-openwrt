#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Autonomous_Flash_OpenWrt_and_Verify.py
======================================
100% Autonomous Offline-Resilient Flash, First-Boot Provisioning, ISP WAN
Recovery, Hardware Audit & Live Stress-Test Orchestrator for Tenda AC10 V1.0
-> Hybrid OpenWrt 4.14.187 (Realtek RTL8197FS + RTL8367S + RTL8822BE).

Designed for Windows 10/11 (PowerShell / Cyrillic locale safe):
  - Phase 0: Pre-flash cryptographic & structural verification of
             tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin + 6s cloud
             task-id return delay.
  - Phase 1: Stock Tenda WebUI authentication (/login/Auth) + pre-check
             (/goform/SysToolGetUpgrade) + multipart firmware upload to
             /cgi-bin/upgrade with stack-safe boundary (<60 chars).
  - Phase 2: Autonomous wait across router flash erase/write and reboot
             (handling Windows Ethernet link flaps, DHCP renewal, and
             temporary static IP 192.168.0.116/24 failsafe fallback) until
             OpenWrt Dropbear SSH responds on 192.168.0.1:22.
  - Phase 3: Autonomous execution of Configure_OpenWrt_ISP_WAN_and_WiFi.ps1
             to provision cloned ISP WAN MAC, MTU, custom DNS, DHCP pool +
             static leases, 2.4 GHz & 5 GHz WPA2-PSK Wi-Fi, and RTL8197FS
             Hardware NAT ASIC table synchronization.
  - Phase 4: Wait for ISP WAN DHCP lease on eth0.1, prime RTL8197FS ASIC
             warm_hosts with live LAN/WAN peers, and verify 5 consecutive
             external internet checks from the Windows PC before allowing exit.
  - Phase 5: Collect sanitized OpenWrt 4.14.187 hardware telemetry and run
             live LAN/WAN/Hardware-NAT/LuCI stress tests, writing sanitized
             results to post_flash_verification_report.json.
"""

import base64
import binascii
import concurrent.futures
import hashlib
import http.client
import json
import os
import re
import socket
import ssl
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KIT_ROOT = os.path.dirname(SCRIPT_DIR)
FW_WEBUPGRADE = os.path.join(KIT_ROOT, "02_Compiled_Hybrid_OpenWrt_4.14_Firmware", "tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin")
if not os.path.exists(FW_WEBUPGRADE):
    FW_WEBUPGRADE = os.path.join(KIT_ROOT, "tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin")
CFG_PATH = os.path.join(KIT_ROOT, "config", "RouterCfm_optimized_sanitized.cfg")
if not os.path.exists(CFG_PATH):
    CFG_PATH = os.path.join(KIT_ROOT, "backups", "RouterCfm_optimized_v1.cfg")
PROVISION_PS1 = os.path.join(SCRIPT_DIR, "Configure_OpenWrt_ISP_WAN_and_WiFi.ps1")
LIVE_LOG_PATH = os.path.join(KIT_ROOT, "post_flash_live_log.txt")
REPORT_JSON_PATH = os.path.join(KIT_ROOT, "post_flash_verification_report.json")

EXPECTED_FW_SIZE = 5542598
EXPECTED_FW_SHA256 = "8f77ff1b8eaf4b0cbc06db8c377ed3a22235ae1db45f65f0fef592f627e5af22"
ROUTER_IP = "192.168.0.1"
SSH_PORT = 22
INTERFACE_ALIAS = "Ethernet"


def mask_mac(mac_str: str) -> str:
    if not mac_str or len(mac_str) < 8:
        return "<masked-mac>"
    clean = mac_str.strip().upper().replace("-", ":")
    parts = clean.split(":")
    if len(parts) == 6:
        return f"{parts[0]}:{parts[1]}:{parts[2]}:XX:XX:XX"
    return clean[:8] + ":XX:XX:XX"


def mask_ip(ip_str: str) -> str:
    if not ip_str:
        return "<none>"
    ip_str = ip_str.strip()
    if ip_str.startswith("192.168.") or ip_str.startswith("10.") or ip_str in ("1.1.1.1", "8.8.8.8", "127.0.0.1"):
        return ip_str
    parts = ip_str.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.XXX.XXX"
    return "<masked-ip>"


def sanitize_text(text: str, raw_macs=None, raw_secrets=None) -> str:
    if not text:
        return ""
    out = text
    for sec in (raw_secrets or []):
        if sec and len(sec) >= 4:
            out = out.replace(sec, "********")
    for mac in (raw_macs or []):
        if mac and len(mac) == 17:
            out = re.sub(re.escape(mac), mask_mac(mac), out, flags=re.IGNORECASE)
            no_sep = mac.replace(":", "").replace("-", "")
            out = re.sub(re.escape(no_sep), "XXXXXX" + no_sep[:6], out, flags=re.IGNORECASE)
    def _mac_repl(m):
        val = m.group(0).upper()
        if val in ("FF:FF:FF:FF:FF:FF", "00:00:00:00:00:00"):
            return val
        return val[:8] + ":XX:XX:XX"
    out = re.sub(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", _mac_repl, out)
    return out


class Logger:
    def __init__(self, path: str):
        self.path = path
        self.fp = open(path, "w", encoding="utf-8")

    def log(self, msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        self.fp.write(line + "\n")
        self.fp.flush()

    def close(self):
        try:
            self.fp.close()
        except Exception:
            pass


def verify_webupgrade_image(fw_path: str) -> dict:
    if not os.path.isfile(fw_path):
        raise RuntimeError(f"Firmware file not found: {fw_path}")
    data = open(fw_path, "rb").read()
    size = len(data)
    sha256 = hashlib.sha256(data).hexdigest()
    if size != EXPECTED_FW_SIZE:
        raise RuntimeError(f"Size mismatch: {size} != {EXPECTED_FW_SIZE}")
    if sha256 != EXPECTED_FW_SHA256:
        raise RuntimeError(f"SHA256 mismatch: {sha256} != {EXPECTED_FW_SHA256}")

    magic, = struct.unpack_from(">I", data, 0x00)
    ih_size, = struct.unpack_from(">I", data, 0x0C)
    ih_dcrc, = struct.unpack_from(">I", data, 0x18)
    ih_os = data[0x20]
    ih_ver, = struct.unpack_from(">I", data, 0x24)
    inner = data[64:]
    if magic != 0x27051956:
        raise RuntimeError(f"Invalid outer magic: 0x{magic:08X}")
    if ih_os != 2 or ih_ver != 0x00030028:
        raise RuntimeError(f"Outer header os/ver mismatch: os={ih_os}, ver=0x{ih_ver:08X}")
    if ih_size != len(inner):
        raise RuntimeError(f"Outer header ih_size mismatch: {ih_size} != {len(inner)}")
    calc_crc = binascii.crc32(inner) & 0xFFFFFFFF
    if calc_crc != ih_dcrc:
        raise RuntimeError(f"Outer trx2 CRC32 mismatch: 0x{calc_crc:08X} != 0x{ih_dcrc:08X}")

    if inner[:4] != b"cs6c":
        raise RuntimeError(f"Invalid inner magic at 0x40: {inner[:4]!r}")
    _, start_addr, burn_addr, payload_len = struct.unpack(">4I", inner[:16])
    words = struct.unpack(f">{payload_len//2}H", inner[16:16 + payload_len])
    csum16 = sum(words) & 0xFFFF
    if csum16 != 0:
        raise RuntimeError(f"Inner cs6c 16-bit checksum non-zero: 0x{csum16:04X}")

    return {
        "size_bytes": size,
        "sha256": sha256,
        "outer_magic": f"0x{magic:08X}",
        "outer_payload_len": ih_size,
        "outer_trx2_crc32": f"0x{ih_dcrc:08X}",
        "inner_magic": "cs6c",
        "inner_payload_len": payload_len,
        "inner_checksum_16be": f"0x{csum16:04X}",
    }


def parse_router_cfg(cfg_path: str) -> dict:
    raw = open(cfg_path, "rb").read().decode("ascii", errors="ignore")
    kv = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        kv[k.strip()] = v.strip()
    return kv


def run_ps(cmd: str, timeout: int = 30):
    try:
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None


def set_static_fallback_ip(logger: Logger) -> bool:
    logger.log(f"[NET-FAILSAFE] Assigning temporary static IP 192.168.0.116/24 on '{INTERFACE_ALIAS}'...")
    ps_cmd = (
        f"Remove-NetIPAddress -InterfaceAlias '{INTERFACE_ALIAS}' -AddressFamily IPv4 -Confirm:$false -ErrorAction SilentlyContinue; "
        f"New-NetIPAddress -InterfaceAlias '{INTERFACE_ALIAS}' -IPAddress '192.168.0.116' -PrefixLength 24 -DefaultGateway '{ROUTER_IP}' -ErrorAction SilentlyContinue | Out-Null"
    )
    run_ps(ps_cmd, timeout=20)
    time.sleep(2)
    return True


def restore_dhcp_ip(logger: Logger):
    logger.log(f"[NET-FAILSAFE] Ensuring '{INTERFACE_ALIAS}' is set to automatic DHCP & DNS and renewing lease...")
    ps_cmd = (
        f"Set-NetIPInterface -InterfaceAlias '{INTERFACE_ALIAS}' -AddressFamily IPv4 -Dhcp Enabled -ErrorAction SilentlyContinue; "
        f"Set-DnsClientServerAddress -InterfaceAlias '{INTERFACE_ALIAS}' -ResetServerAddresses -ErrorAction SilentlyContinue; "
        f"ipconfig /renew '{INTERFACE_ALIAS}' | Out-Null"
    )
    run_ps(ps_cmd, timeout=30)
    time.sleep(2)


def check_ssh_banner(ip: str, port: int = 22, timeout: float = 3.0) -> str:
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            s.settimeout(timeout)
            banner = s.recv(128).decode("ascii", errors="ignore").strip()
            return banner
    except Exception:
        return ""


def run_openwrt_ssh(cmd: str, timeout: int = 25) -> tuple:
    ssh_exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH", "ssh.exe")
    if not os.path.isfile(ssh_exe):
        ssh_exe = "ssh.exe"
    args = [
        ssh_exe,
        "-p", str(SSH_PORT),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=NUL",
        "-o", "ConnectTimeout=8",
        "-o", "LogLevel=ERROR",
        f"root@{ROUTER_IP}",
        cmd,
    ]
    try:
        res = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def authenticate_stock_webui(userpass: str, logger: Logger) -> str:
    candidates = []
    if userpass:
        candidates.append(userpass)
        try:
            b64_dec = base64.b64decode(userpass).decode("ascii")
            candidates.append(b64_dec)
        except Exception:
            pass
        candidates.append(hashlib.md5(userpass.encode("utf-8")).hexdigest())
        candidates.append(base64.b64encode(hashlib.md5(userpass.encode("utf-8")).hexdigest().encode("ascii")).decode("ascii"))
    candidates.append("")

    for cand in candidates:
        try:
            conn = http.client.HTTPConnection(ROUTER_IP, 80, timeout=10)
            body = urllib.parse.urlencode({"username": "admin", "password": cand})
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": f"password={cand}",
            }
            conn.request("POST", "/login/Auth", body=body, headers=headers)
            resp = conn.getresponse()
            resp.read()
            set_cookie = resp.getheader("Set-Cookie") or ""
            conn.close()

            cookie_val = cand
            m = re.search(r"password=([^;\s]+)", set_cookie)
            if m:
                cookie_val = m.group(1)

            conn2 = http.client.HTTPConnection(ROUTER_IP, 80, timeout=10)
            conn2.request("GET", "/goform/SysToolGetUpgrade?r=0.12345", headers={"Cookie": f"password={cookie_val}"})
            r2 = conn2.getresponse()
            data2 = r2.read().decode("utf-8", errors="ignore")
            conn2.close()
            if "cur_fw_ver" in data2:
                info = json.loads(data2)
                logger.log(f"[STOCK-AUTH] Authenticated to Stock WebUI successfully! cur_fw_ver={info.get('cur_fw_ver')}")
                return f"password={cookie_val}"
        except Exception:
            continue

    raise RuntimeError("Failed to authenticate to Stock Tenda WebUI at http://192.168.0.1")


def upload_firmware_to_stock(fw_path: str, cookie_hdr: str, logger: Logger) -> dict:
    fw_bytes = open(fw_path, "rb").read()
    boundary = "----TendaUpgradeBoundary7MA4YWxkTrZu0gW"
    part_header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="upgradeFile"; filename="tenda-ac10-v1-hybrid-openwrt-4.14-webupgrade.bin"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("ascii")
    part_footer = f"\r\n--{boundary}--\r\n".encode("ascii")
    body = part_header + fw_bytes + part_footer

    logger.log(f"[FLASH-UPLOAD] Uploading {len(fw_bytes):,} bytes (multipart total {len(body):,} bytes) to http://{ROUTER_IP}/cgi-bin/upgrade ...")
    t0 = time.time()
    conn = http.client.HTTPConnection(ROUTER_IP, 80, timeout=90)
    headers = {
        "Host": ROUTER_IP,
        "Cookie": cookie_hdr,
        "Origin": f"http://{ROUTER_IP}",
        "Referer": f"http://{ROUTER_IP}/main.html",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
        "Connection": "close",
    }
    try:
        conn.request("POST", "/cgi-bin/upgrade", body=body, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        location = resp.getheader("Location") or ""
        resp_body = resp.read().decode("utf-8", errors="ignore")
        conn.close()
    except (socket.timeout, ConnectionResetError, http.client.RemoteDisconnected, BrokenPipeError) as e:
        elapsed = time.time() - t0
        logger.log(f"[FLASH-UPLOAD] Socket closed during upgrade handoff after {elapsed:.1f}s ({type(e).__name__}) — upgrade daemon active.")
        return {"status": 302, "location": "/redirect.html?1 (socket closed on daemon stop)", "elapsed_sec": round(elapsed, 2)}

    elapsed = time.time() - t0
    logger.log(f"[FLASH-UPLOAD] HTTP status={status}, Location='{location}', elapsed={elapsed:.2f}s")
    if "errCode=" in location:
        raise RuntimeError(f"Stock /cgi-bin/upgrade rejected firmware! Redirect Location: {location}")
    if status not in (200, 302):
        raise RuntimeError(f"Unexpected HTTP status from /cgi-bin/upgrade: {status} ({resp_body[:200]})")
    return {"status": status, "location": location, "elapsed_sec": round(elapsed, 2)}


def check_external_internet(timeout: float = 5.0) -> dict:
    results = {}
    try:
        t0 = time.perf_counter()
        with socket.create_connection(("1.1.1.1", 443), timeout=timeout):
            results["cloudflare_1_1_1_1_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    except Exception:
        results["cloudflare_1_1_1_1_ms"] = None

    try:
        t0 = time.perf_counter()
        with socket.create_connection(("8.8.8.8", 53), timeout=timeout):
            results["google_8_8_8_8_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    except Exception:
        results["google_8_8_8_8_ms"] = None

    try:
        t0 = time.perf_counter()
        ctx = ssl.create_default_context()
        req = urllib.request.Request("https://api.github.com/zen", headers={"User-Agent": "Tenda-AC10-OpenWrt-Verifier"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            _ = r.read(128)
            if r.status == 200:
                results["github_https_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            else:
                results["github_https_ms"] = None
    except Exception:
        results["github_https_ms"] = None

    results["all_ok"] = all(
        results.get(k) is not None
        for k in ("cloudflare_1_1_1_1_ms", "google_8_8_8_8_ms", "github_https_ms")
    )
    return results


def run_stress_tests(logger: Logger) -> dict:
    logger.log("[STRESS-TEST] Starting Phase 5 Live Hardware NAT, LAN LuCI & WAN Concurrency Stress Tests...")
    stress_report = {}

    _, pre_stats, _ = run_openwrt_ssh(
        "cat /proc/loadavg; free; cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null || echo 0"
    )

    def _hit_luci(_i):
        t0 = time.perf_counter()
        try:
            conn = http.client.HTTPConnection(ROUTER_IP, 80, timeout=5)
            conn.request("GET", "/cgi-bin/luci")
            r = conn.getresponse()
            _ = r.read()
            st = r.status
            conn.close()
            if st in (200, 302):
                return (time.perf_counter() - t0) * 1000.0, True
        except Exception:
            pass
        return (time.perf_counter() - t0) * 1000.0, False

    t_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        luci_res = list(ex.map(_hit_luci, range(150)))
    luci_dur = time.perf_counter() - t_start
    luci_lat = sorted(r[0] for r in luci_res if r[1])
    luci_ok = sum(1 for r in luci_res if r[1])
    stress_report["lan_luci_http_stress"] = {
        "total_requests": 150,
        "concurrency": 12,
        "successful_requests": luci_ok,
        "success_rate_pct": round(luci_ok * 100.0 / 150.0, 2),
        "duration_sec": round(luci_dur, 2),
        "requests_per_sec": round(150.0 / max(luci_dur, 0.001), 2),
        "latency_min_ms": round(luci_lat[0], 2) if luci_lat else None,
        "latency_avg_ms": round(sum(luci_lat) / len(luci_lat), 2) if luci_lat else None,
        "latency_p95_ms": round(luci_lat[int(len(luci_lat) * 0.95)], 2) if luci_lat else None,
        "latency_max_ms": round(luci_lat[-1], 2) if luci_lat else None,
    }
    logger.log(f"[STRESS-TEST] LAN LuCI HTTP Stress: {luci_ok}/150 OK, avg={stress_report['lan_luci_http_stress']['latency_avg_ms']}ms, p95={stress_report['lan_luci_http_stress']['latency_p95_ms']}ms")

    targets = [
        ("1.1.1.1", 443),
        ("1.0.0.1", 443),
        ("8.8.8.8", 443),
        ("8.8.4.4", 443),
    ]
    def _wan_conn(idx):
        host, port = targets[idx % len(targets)]
        t0 = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=5):
                return (time.perf_counter() - t0) * 1000.0, True
        except Exception:
            return (time.perf_counter() - t0) * 1000.0, False

    t_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        wan_res = list(ex.map(_wan_conn, range(100)))
    wan_dur = time.perf_counter() - t_start
    wan_lat = sorted(r[0] for r in wan_res if r[1])
    wan_ok = sum(1 for r in wan_res if r[1])
    stress_report["wan_hwnat_concurrent_tcp_stress"] = {
        "total_connections": 100,
        "concurrency": 20,
        "successful_connections": wan_ok,
        "success_rate_pct": round(wan_ok * 100.0 / 100.0, 2),
        "duration_sec": round(wan_dur, 2),
        "connections_per_sec": round(100.0 / max(wan_dur, 0.001), 2),
        "rtt_min_ms": round(wan_lat[0], 2) if wan_lat else None,
        "rtt_avg_ms": round(sum(wan_lat) / len(wan_lat), 2) if wan_lat else None,
        "rtt_p95_ms": round(wan_lat[int(len(wan_lat) * 0.95)], 2) if wan_lat else None,
        "rtt_max_ms": round(wan_lat[-1], 2) if wan_lat else None,
    }
    logger.log(f"[STRESS-TEST] WAN HW-NAT Concurrent TCP Stress: {wan_ok}/100 OK, avg={stress_report['wan_hwnat_concurrent_tcp_stress']['rtt_avg_ms']}ms, p95={stress_report['wan_hwnat_concurrent_tcp_stress']['rtt_p95_ms']}ms")

    def _https_burst(_idx):
        url = "https://speed.cloudflare.com/__down?bytes=2000000"
        t0 = time.perf_counter()
        try:
            ctx = ssl.create_default_context()
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                data = resp.read()
                return len(data), time.perf_counter() - t0, True
        except Exception:
            try:
                ctx = ssl.create_default_context()
                req = urllib.request.Request("https://1.1.1.1/cdn-cgi/trace", headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                    data = resp.read()
                    return len(data), time.perf_counter() - t0, True
            except Exception:
                return 0, time.perf_counter() - t0, False

    t_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        dl_res = list(ex.map(_https_burst, range(8)))
    dl_dur = time.perf_counter() - t_start
    total_bytes = sum(r[0] for r in dl_res if r[2])
    dl_ok = sum(1 for r in dl_res if r[2])
    mbps = round((total_bytes * 8.0) / (max(dl_dur, 0.001) * 1_000_000.0), 2)
    stress_report["wan_https_parallel_burst"] = {
        "streams": 8,
        "successful_streams": dl_ok,
        "total_bytes_transferred": total_bytes,
        "duration_sec": round(dl_dur, 2),
        "aggregate_throughput_mbps": mbps,
    }
    logger.log(f"[STRESS-TEST] WAN Parallel HTTPS Burst: {dl_ok}/8 streams OK, {total_bytes:,} bytes in {dl_dur:.2f}s ({mbps} Mbps)")

    _, post_stats, _ = run_openwrt_ssh(
        "cat /proc/loadavg; free; cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null || echo 0; cat /sys/module/rtl819x/parameters/hwnat"
    )
    stress_report["router_health_pre_stress"] = pre_stats
    stress_report["router_health_post_stress"] = post_stats
    return stress_report


def main():
    logger = Logger(LIVE_LOG_PATH)
    switched_static = False
    t_mission_start = time.time()

    try:
        logger.log("=== PHASE 0: PRE-FLASH CRYPTOGRAPHIC GATE & CLOUD TASK SYNC ===")
        fw_info = verify_webupgrade_image(FW_WEBUPGRADE)
        logger.log(f"[GATE-PASS] Verified {os.path.basename(FW_WEBUPGRADE)}: {json.dumps(fw_info)}")

        if not os.path.isfile(CFG_PATH):
            raise RuntimeError(f"Backup config not found: {CFG_PATH}")
        if not os.path.isfile(PROVISION_PS1):
            raise RuntimeError(f"Provisioning script not found: {PROVISION_PS1}")

        cfg = parse_router_cfg(CFG_PATH)
        wan_mac = cfg.get("wan1.macaddr", "").strip().upper()
        userpass = cfg.get("sys.userpass", "").strip()
        ssid_2g = cfg.get("wl2g.ssid0.ssid", "Tenda_2.4G")
        ssid_5g = cfg.get("wl5g.ssid0.ssid", "Tenda_5G")
        key_2g = cfg.get("wl2g.ssid0.wpapsk_psk", "")
        key_5g = cfg.get("wl5g.ssid0.wpapsk_psk", "")
        raw_secrets = [s for s in (userpass, key_2g, key_5g) if s]
        raw_macs = [m for m in (wan_mac, cfg.get("lan.macaddr", "")) if m]

        logger.log(f"[CONFIG-READY] Extracted WAN MAC={mask_mac(wan_mac)}, 2.4G SSID='{ssid_2g}', 5G SSID='{ssid_5g}'")
        logger.log("[CLOUD-SYNC] Sleeping 6 seconds so background TaskId returns cleanly to cloud before internet drops...")
        time.sleep(6)

        banner = check_ssh_banner(ROUTER_IP, SSH_PORT, timeout=2.0)
        if "dropbear" in banner.lower() or "openssh" in banner.lower():
            logger.log(f"[INFO] Router at {ROUTER_IP}:{SSH_PORT} is already running OpenWrt ({banner})! Skipping Stock WebUI upload.")
            upload_res = {"status": "already_openwrt", "banner": banner}
        else:
            logger.log("=== PHASE 1: STOCK WEBUI AUTHENTICATION & FIRMWARE UPLOAD (/cgi-bin/upgrade) ===")
            cookie_hdr = authenticate_stock_webui(userpass, logger)
            upload_res = upload_firmware_to_stock(FW_WEBUPGRADE, cookie_hdr, logger)

            logger.log("=== PHASE 2: WAITING FOR FLASH WRITE (mtd2 KernelFS) & OPENWRT 4.14.187 FIRST BOOT ===")
            logger.log("[WAIT-FLASH] Sleeping 28s while /bin/upgrade erases & writes 5.29 MB to /dev/mtd2 (KernelFS) and triggers hardware reboot...")
            time.sleep(28)

        t_boot_wait = time.time()
        ssh_ready = False
        attempt = 0
        while time.time() - t_boot_wait < 300:
            attempt += 1
            elapsed = int(time.time() - t_boot_wait)
            banner = check_ssh_banner(ROUTER_IP, SSH_PORT, timeout=3.0)
            if banner and ("dropbear" in banner.lower() or "ssh" in banner.lower()):
                logger.log(f"[OPENWRT-BOOTED] OpenWrt SSH banner detected on {ROUTER_IP}:{SSH_PORT} after {elapsed}s! Banner: {banner}")
                ssh_ready = True
                break

            if attempt % 5 == 0:
                logger.log(f"[WAIT-BOOT] Polling {ROUTER_IP}:{SSH_PORT} (elapsed {elapsed}s)...")
            if elapsed >= 55 and not switched_static and attempt % 6 == 0:
                if elapsed < 85:
                    logger.log(f"[NET-RENEW] Running ipconfig /renew {INTERFACE_ALIAS} at {elapsed}s...")
                    run_ps(f"ipconfig /renew '{INTERFACE_ALIAS}' | Out-Null", timeout=15)
                else:
                    switched_static = set_static_fallback_ip(logger)
            time.sleep(3)

        if not ssh_ready:
            raise RuntimeError(f"OpenWrt SSH did not come up on {ROUTER_IP}:{SSH_PORT} within 300 seconds!")

        logger.log("[FIRST-BOOT-SETTLE] Waiting 6s for first-boot uci-defaults (99-dir842-m5) and netifd to settle...")
        time.sleep(6)

        logger.log("=== PHASE 3: AUTONOMOUS ISP WAN MAC, DHCP, DNS, WI-FI & HW-NAT PROVISIONING ===")
        prov_ok = False
        for prov_try in range(1, 4):
            logger.log(f"[PROVISION] Running Configure_OpenWrt_ISP_WAN_and_WiFi.ps1 (attempt {prov_try}/3)...")
            res = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    PROVISION_PS1,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            san_out = sanitize_text(res.stdout, raw_macs, raw_secrets)
            san_err = sanitize_text(res.stderr, raw_macs, raw_secrets)
            logger.log(f"[PROVISION-OUT] rc={res.returncode}\n{san_out}")
            if res.returncode == 0 and "TENDA_AC10_PROVISIONED" in res.stdout:
                prov_ok = True
                break
            logger.log(f"[PROVISION-RETRY] stderr={san_err} — retrying in 5s...")
            time.sleep(5)

        if not prov_ok:
            raise RuntimeError("Configure_OpenWrt_ISP_WAN_and_WiFi.ps1 failed after 3 attempts!")

        restore_dhcp_ip(logger)
        switched_static = False

        logger.log("=== PHASE 4: WAITING FOR ISP WAN LEASE ON eth0.1 & EXTERNAL INTERNET RESTORATION ===")
        wan_up = False
        wan_ip = ""
        wan_gw = ""
        t_wan_wait = time.time()
        while time.time() - t_wan_wait < 180:
            rc, out, _ = run_openwrt_ssh("ubus call network.interface.wan status 2>/dev/null || true")
            if rc == 0 and out.startswith("{"):
                try:
                    wstat = json.loads(out)
                    ipv4_list = wstat.get("ipv4-address") or []
                    routes = wstat.get("route") or []
                    if wstat.get("up") and ipv4_list:
                        wan_ip = ipv4_list[0].get("address", "")
                        for rt in routes:
                            if rt.get("target") == "0.0.0.0" and rt.get("nexthop"):
                                wan_gw = rt.get("nexthop")
                                break
                        wan_up = True
                        logger.log(f"[WAN-LEASE-OK] ISP WAN interface eth0.1 is UP! IP={mask_ip(wan_ip)}, Gateway={mask_ip(wan_gw)}")
                        break
                except Exception:
                    pass

            elapsed_w = int(time.time() - t_wan_wait)
            logger.log(f"[WAIT-WAN] Waiting for ISP DHCP lease on eth0.1 (elapsed {elapsed_w}s)...")
            if elapsed_w in (20, 45, 75, 110):
                logger.log("[WAN-NUDGE] Ensuring eth0.1 cloned MAC and triggering ubus network.interface.wan renew + dir842-asic restart...")
                run_openwrt_ssh(
                    f"ip link set dev eth0.1 address '{wan_mac}' 2>/dev/null || true; "
                    f"ubus call network.interface.wan renew 2>/dev/null || ifup wan 2>/dev/null || true; "
                    f"/etc/init.d/dir842-asic restart >/dev/null 2>&1 || true"
                )
            time.sleep(5)

        warm_peers = "192.168.0.155 192.168.0.100 1.1.1.1"
        if wan_gw:
            warm_peers = f"192.168.0.155 192.168.0.100 {wan_gw} 1.1.1.1"
        logger.log(f"[ASIC-SYNC] Programming RTL8197FS ASIC warm_hosts ('192.168.0.100 <wan_gw> 1.1.1.1') and restarting dir842-asic...")
        run_openwrt_ssh(
            f"uci -q set dir842.asic.warm_hosts='{warm_peers}' && uci commit dir842; "
            f"ip link set dev eth0.1 address '{wan_mac}' 2>/dev/null || true; "
            f"/etc/init.d/dir842-asic restart >/dev/null 2>&1 || true",
            timeout=45,
        )

        logger.log("[WAIT-INTERNET] Verifying external internet connectivity from Windows PC (requiring 5 consecutive passes)...")
        consec_ok = 0
        last_ext = {}
        t_ext_wait = time.time()
        while time.time() - t_ext_wait < 240:
            ext = check_external_internet(timeout=5.0)
            last_ext = ext
            if ext.get("all_ok"):
                consec_ok += 1
                logger.log(
                    f"[INTERNET-OK {consec_ok}/5] 1.1.1.1={ext['cloudflare_1_1_1_1_ms']}ms, "
                    f"8.8.8.8={ext['google_8_8_8_8_ms']}ms, github.com={ext['github_https_ms']}ms"
                )
                if consec_ok >= 5:
                    break
            else:
                if consec_ok > 0:
                    logger.log(f"[INTERNET-RETRY] Check interrupted ({ext}), resetting consecutive counter...")
                consec_ok = 0
                if int(time.time() - t_ext_wait) % 20 == 0:
                    run_ps(f"ipconfig /renew '{INTERFACE_ALIAS}' | Out-Null", timeout=20)
            time.sleep(2)

        if consec_ok < 5:
            raise RuntimeError(f"External internet did not reach 5 consecutive passes within timeout: {last_ext}")

        logger.log("=== PHASE 5: POST-FLASH HARDWARE TELEMETRY & LIVE STRESS TESTS ===")
        telemetry_cmd = r"""
echo "===UNAME==="
uname -a
echo "===RELEASE==="
cat /etc/openwrt_release 2>/dev/null || true
echo "===MTD==="
cat /proc/mtd
echo "===HWNAT==="
head -n 20 /sys/module/rtl819x/parameters/hwnat /sys/module/rtl819x/parameters/fabric_autoreset /sys/module/rtl819x/parameters/fabric_gw_rearm 2>/dev/null || true
echo "===RTL865X_GW==="
cat /proc/rtl865x_gw 2>/dev/null || true
echo "===SWCONFIG==="
swconfig dev switch0 show 2>/dev/null | head -n 45 || true
echo "===WIRELESS_UCI==="
uci show wireless 2>/dev/null | grep -v "\.key=" || true
echo "===IW_DEV==="
iw dev 2>/dev/null || true
echo "===WLAN0_RF==="
grep -E "rfe_type|use_efuse|pa_type|trsw|band" /proc/wlan0/mib_rf /proc/wlan0/mib_operation 2>/dev/null || true
echo "===RTW88_DMESG==="
dmesg | grep -iE "rtw88|8822b|rtl8192cd|rtl865x|spi-nor|mtd" | head -n 60 || true
echo "===BRCTL==="
brctl show 2>/dev/null || true
echo "===NET_ADDR==="
ip -o link show; ip -4 -o addr show
echo "===MEM_DF==="
free; df -h
"""
        _, raw_tel, _ = run_openwrt_ssh(telemetry_cmd, timeout=30)
        san_tel = sanitize_text(raw_tel, raw_macs, raw_secrets)
        if wan_ip:
            san_tel = san_tel.replace(wan_ip, mask_ip(wan_ip))
        if wan_gw:
            san_tel = san_tel.replace(wan_gw, mask_ip(wan_gw))

        stress_results = run_stress_tests(logger)
        stress_results["router_health_pre_stress"] = sanitize_text(stress_results.get("router_health_pre_stress", ""), raw_macs, raw_secrets)
        stress_results["router_health_post_stress"] = sanitize_text(stress_results.get("router_health_post_stress", ""), raw_macs, raw_secrets)

        total_elapsed = round(time.time() - t_mission_start, 2)
        report = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "total_mission_duration_sec": total_elapsed,
            "firmware_verified": fw_info,
            "stock_upload_result": upload_res,
            "wan_status": {
                "up": wan_up,
                "cloned_mac_masked": mask_mac(wan_mac),
                "wan_ip_masked": mask_ip(wan_ip),
                "wan_gateway_masked": mask_ip(wan_gw),
                "external_connectivity_5x_pass": last_ext,
            },
            "stress_tests": stress_results,
            "openwrt_telemetry_sanitized": san_tel,
        }

        with open(REPORT_JSON_PATH, "w", encoding="utf-8") as rf:
            json.dump(report, rf, indent=2, ensure_ascii=False)

        logger.log(f"[MISSION-COMPLETE] All phases succeeded in {total_elapsed}s! Report saved to {REPORT_JSON_PATH}")
    except Exception as exc:
        logger.log(f"[ERROR] Exception encountered: {exc}")
        if switched_static:
            restore_dhcp_ip(logger)
            switched_static = False
        # Wait up to 120s for internet before exiting so the cloud runner never loses the completion message
        for _ in range(40):
            if check_external_internet(timeout=3.0).get("all_ok"):
                break
            time.sleep(3)
        raise
    finally:
        if switched_static:
            restore_dhcp_ip(logger)
        logger.close()


if __name__ == "__main__":
    main()
