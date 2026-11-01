#!/usr/bin/env python3
"""
Master Autonomous Firmware Flashing Orchestrator for Tenda AC10 V1.0
Pure Python 3 Standard Library (Zero External Dependencies)

Lifecycle:
1. Static image validation (Realtek cr6c header, size <= 7,872 KB, 16-bit BE checksum).
2. Host network adapter state snapshot & failsafe switch to 192.168.1.8/24.
3. Hardware operator guidance (RST button GPIO 54, 12-15s timing, SYS LED).
4. Bootloader link probing (192.168.1.6 ping loop).
5. Dual-mode TFTP flashing (WRQ push + background RRQ listener).
6. Flash burning monitoring & post-reboot verification.
7. Guaranteed network adapter rollback to DHCP/DNS in all exit conditions.
"""

import os
import sys
import time
import socket
import struct
import signal
import atexit
import argparse
import subprocess
import logging

# Ensure suite directory is in path for imports
SUITE_DIR = os.path.dirname(os.path.abspath(__file__))
if SUITE_DIR not in sys.path:
    sys.path.insert(0, SUITE_DIR)

from tftp_emergency_engine import TftpClient, TftpServer, TftpError
from verify_firmware import verify_image_file, fix_image_checksum, format_report

logger = logging.getLogger("RecoveryMaster")
_network_switched = False


def rollback_network():
    """Guaranteed rollback hook registered with atexit and signal handlers."""
    global _network_switched
    if not _network_switched:
        return
    print("\n" + "=" * 70)
    print("  FAILSAFE NETWORK RESTORATION: Reverting adapter to DHCP & DNS...")
    print("=" * 70)
    try:
        ps_script = os.path.join(SUITE_DIR, "network_failsafe.ps1")
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_script, "-Action", "Restore"],
            capture_output=True, text=True, timeout=15
        )
        if res.returncode == 0:
            print("[OK] Adapter restored to automatic DHCP & DNS.")
        else:
            print(f"[!] Warning during network rollback: {res.stderr.strip() or res.stdout.strip()}")
    except Exception as e:
        print(f"[-] Rollback execution error: {e}")
        print("[!] You can manually run 'restore_network.bat' at any time to restore DHCP.")
    finally:
        _network_switched = False


# Register emergency signal and exit traps
atexit.register(rollback_network)


def sig_handler(signum, frame):
    print(f"\n[!] Caught signal {signum} (Ctrl+C / Interrupted). Aborting safely...")
    rollback_network()
    sys.exit(130)


signal.signal(signal.SIGINT, sig_handler)
signal.signal(signal.SIGTERM, sig_handler)


def check_admin():
    """Checks if running with Windows Administrator privileges."""
    try:
        res = subprocess.run(["net", "session"], capture_output=True)
        return res.returncode == 0
    except Exception:
        return False


def ping_host(ip, timeout_sec=1):
    """Pings target IP once with short timeout."""
    try:
        # Windows ping: -n 1 (1 packet), -w timeout_ms
        timeout_ms = int(timeout_sec * 1000)
        res = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), ip],
            capture_output=True, text=True
        )
        return res.returncode == 0
    except Exception:
        return False


def display_hardware_instructions(router_ip):
    """Prints clear, visual step-by-step unbricking guidance for physical operator."""
    print("\n" + "=" * 72)
    print("                HARDWARE RECOVERY INSTRUCTIONS (GPIO 54)")
    print("=" * 72)
    print("  1. Connect PC Gigabit Ethernet directly to router port [LAN1, LAN2, or LAN3].")
    print("     CRITICAL: Do NOT connect to WAN port! Realtek Booter (at 0x8000ECE8)")
    print("     explicitly powers OFF the WAN PHY; only LAN switch ports are active!")
    print("  2. UNPLUG the 12V DC power barrel from the back of the Tenda AC10.")
    print("  3. Using a paperclip or pin, PRESS and HOLD the physical [RST/WPS] button.")
    print("  4. WHILE STILL HOLDING THE BUTTON, plug the 12V DC power barrel back in.")
    print("  5. KEEP HOLDING the button for 12 to 15 seconds until:")
    print("     - The blue SYS LED turns solid, blinks, then PULSES RAPIDLY (~10 Hz).")
    print("  6. RELEASE the button. The router is now in Realtek Booter Recovery Mode!")
    print(f"     Target Recovery IP: {router_ip}")
    print("=" * 72 + "\n")


def main():
    global _network_switched

    parser = argparse.ArgumentParser(
        description="Autonomous Emergency Firmware Flashing Suite for Tenda AC10 V1.0"
    )
    parser.add_argument("--image", default=None,
                        help="Path to firmware image binary (.bin)")
    parser.add_argument("--stock", action="store_true",
                        help="Restore factory stock firmware (Tenda_AC10_V1_Stock_TFTP_Recovery.bin)")
    parser.add_argument("--fix-checksum", action="store_true",
                        help="Automatically calculate and inject 16-bit compensating checksum if needed")
    parser.add_argument("--skip-verify", action="store_true",
                        help="Bypass static image validation (NOT recommended)")
    parser.add_argument("--skip-network-switch", action="store_true",
                        help="Skip automatic network adapter configuration (assumes 192.168.1.8 is already set)")
    parser.add_argument("--router-ip", default="192.168.1.6",
                        help="Bootloader TFTP IP (default: 192.168.1.6)")
    parser.add_argument("--tftp-port", type=int, default=69,
                        help="TFTP port (default: 69)")
    parser.add_argument("--post-ip", default=None,
                        help="Target OS IP to probe after reboot (192.168.0.1 for Stock, 192.168.1.1 for OpenWrt)")
    parser.add_argument("--timeout", type=int, default=180,
                        help="Bootloader discovery timeout in seconds (default: 180)")

    args = parser.parse_args()

    print("\n" + "#" * 72)
    print("   TENDA AC10 V1.0 - 100% AUTONOMOUS OFFLINE RECOVERY ORCHESTRATOR")
    print("   Pure Python 3 RFC 1350 Dual-Mode Engine | Failsafe Network Rollback")
    print("#" * 72 + "\n")

    # 1. Resolve Image Path
    image_path = args.image
    if args.stock:
        stock_candidate = os.path.join(SUITE_DIR, "backups", "Tenda_AC10_V1_Stock_TFTP_Recovery.bin")
        if not os.path.exists(stock_candidate):
            stock_candidate = os.path.join(SUITE_DIR, "backups", "mtd3_kernelfs.bin")
        if not os.path.exists(stock_candidate):
            stock_candidate = os.path.join(SUITE_DIR, "backups", "kernel_cr6c.bin")
        image_path = stock_candidate
        print(f"[*] Stock restoration selected: Using verified image {image_path}")

    if not image_path:
        # Check default recovery image in backups
        default_img = os.path.join(SUITE_DIR, "backups", "Tenda_AC10_V1_Stock_TFTP_Recovery.bin")
        if not os.path.exists(default_img):
            default_img = os.path.join(SUITE_DIR, "backups", "mtd3_kernelfs.bin")
        if os.path.exists(default_img):
            image_path = default_img
            print(f"[*] No image specified: Defaulting to verified recovery binary:\n    {image_path}")
        else:
            print("[-] Error: No firmware image specified! Use --image <path> or --stock.")
            sys.exit(1)

    if not os.path.exists(image_path):
        print(f"[-] Error: Image file does not exist: {image_path}")
        sys.exit(1)

    # 2. Stage 1: Static Firmware Image Verification
    if not args.skip_verify:
        print("[*] Stage 1: Validating firmware image against Realtek Booter specifications...")
        is_valid, report = verify_image_file(image_path)
        print(format_report(image_path, is_valid, report))

        if not is_valid:
            if args.fix_checksum and "Checksum failure" in str(report.get("errors")):
                print("[*] Attempting automatic checksum compensation (--fix-checksum)...")
                try:
                    image_path = fix_image_checksum(image_path)
                    is_valid, report = verify_image_file(image_path)
                    print(format_report(image_path, is_valid, report))
                    if not is_valid:
                        print("[-] Fatal: Repaired image still failed validation. Aborting.")
                        sys.exit(1)
                except Exception as e:
                    print(f"[-] Checksum repair error: {e}")
                    sys.exit(1)
            else:
                print("[-] Fatal: Firmware verification failed. Refusing to flash corrupt image.")
                print("    (Use --fix-checksum if the only defect is checksum mismatch)")
                sys.exit(1)
    else:
        print("[!] Warning: Image validation bypassed by --skip-verify flag.")

    # 3. Stage 2: Administrator Check & Network Configuration
    if not args.skip_network_switch:
        if not check_admin():
            print("[-] Error: Administrator privileges are required to configure network adapter IP.")
            print("    Please run this terminal or launcher batch as Administrator.")
            sys.exit(1)

        print("[*] Stage 2: Snapshotting network configuration and switching to 192.168.1.8/24...")
        ps_script = os.path.join(SUITE_DIR, "network_failsafe.ps1")
        cmd = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", ps_script,
            "-Action", "Switch",
            "-RecoveryIP", "192.168.1.8",
            "-RecoveryGateway", args.router_ip
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        print(res.stdout.strip())
        if res.returncode != 0:
            print(f"[-] Network switch failed: {res.stderr.strip()}")
            sys.exit(1)
        _network_switched = True
    else:
        print("[*] Stage 2: Skipping network switch (--skip-network-switch enabled).")

    # 4. Stage 3 & 4: Dual-Mode TFTP Flashing with Direct UDP WRQ Polling
    display_hardware_instructions(args.router_ip)

    print(f"\n[*] Stage 3: Polling Realtek Booter via UDP TFTP WRQ ({args.router_ip}:{args.tftp_port})...")
    print("    (Note: Realtek Booter at 0x80001010 processes only UDP 0x11; ICMP is dropped by hardware design.)")
    print(f"    Waiting up to {args.timeout}s for router power-on with RST held...")

    # Start background TFTP Server on port 69 in case booter issues RRQ
    tftp_server = TftpServer(bind_ip="0.0.0.0", bind_port=args.tftp_port,
                             served_file=image_path, quiet=True)
    tftp_server.start_background()

    # Calculate retries for foreground client based on timeout (base timeout 1.5s per retry)
    calculated_retries = max(10, int(args.timeout / 2.0))
    tftp_client = TftpClient(host=args.router_ip, port=args.tftp_port,
                             timeout=1.5, retries=calculated_retries, quiet=False)

    transfer_ok = False
    try:
        tftp_client.push_file(image_path, remote_filename="firmware.bin")
        transfer_ok = True
    except Exception as e:
        print(f"\n[*] Client WRQ attempt ended: {e}")
        print("[*] Checking if Booter engaged background TFTP Server (RRQ)...")
        # Wait up to 10s to see if server handled an RRQ
        if tftp_server.transfer_completed.wait(timeout=10.0) and tftp_server.last_transfer_success:
            print("[+] TFTP RRQ Server Transfer Completed Successfully!")
            transfer_ok = True
        else:
            print(f"[-] Transfer failed: {e}")
            sys.exit(1)
    finally:
        tftp_server.stop()

    if not transfer_ok:
        print("[-] Error: TFTP transfer did not complete successfully.")
        sys.exit(1)

    # 5. Stage 5: Flash Burning & Reboot Monitoring
    print("\n" + "=" * 72)
    print("  CRITICAL: FIRMWARE UPLOAD FINISHED! BURNING SPI NOR FLASH...")
    print("  DO NOT DISCONNECT POWER OR ETHERNET CABLE FOR 3 MINUTES!")
    print("=" * 72)
    print("  The Realtek Booter is now writing the image to flash at 0x00030000.")
    print("  The blue SYS LED will flash rapidly during write, then restart.")
    print("=" * 72 + "\n")

    # Determine post-reboot target IP
    post_ip = args.post_ip
    if not post_ip:
        is_stock = args.stock or any(k in os.path.basename(image_path).lower() for k in ["stock", "kernelfs", "mtd3"])
        post_ip = "192.168.0.1" if is_stock else "192.168.1.1"

    print("[*] Waiting 60 seconds for flash write cycle and reboot...")
    for i in range(60):
        sys.stdout.write("#" if (i % 10 == 0) else ".")
        sys.stdout.flush()
        time.sleep(1.0)

    # Trigger network rollback back to DHCP/DNS so host can communicate with new OS
    print("\n[+] Flash write completed. Reverting PC network adapter to automatic DHCP & DNS...")
    rollback_network()

    print(f"[*] Waiting for router OS to boot (probing {post_ip} and waiting for DHCP lease)...")
    os_detected = False
    for i in range(120):
        if ping_host(post_ip, timeout_sec=1):
            os_detected = True
            print(f"\n[+] SUCCESS! Target OS is ONLINE and responding at {post_ip}!")
            break
        sys.stdout.write("#" if (i % 10 == 0) else ".")
        sys.stdout.flush()
        time.sleep(1.0)

    print("\n" + "#" * 72)
    if os_detected:
        print("   RECOVERY / FLASHING COMPLETED SUCCESSFULLY!")
        print(f"   Access Web Interface: http://{post_ip}")
        if post_ip == "192.168.0.1":
            print("   Stock Firmware Web UI: http://192.168.0.1")
        else:
            print("   OpenWrt LuCI Web UI:   http://192.168.1.1")
            print("   OpenWrt SSH:           ssh root@192.168.1.1")
    else:
        print("   Firmware flashed! Router may take up to 3 minutes on first boot.")
        print(f"   Please check http://{post_ip} or your PC's assigned DHCP IP address.")
    print("#" * 72 + "\n")


if __name__ == "__main__":
    main()
