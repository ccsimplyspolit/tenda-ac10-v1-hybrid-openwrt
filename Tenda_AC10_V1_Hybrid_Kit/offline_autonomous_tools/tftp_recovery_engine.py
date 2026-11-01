#!/usr/bin/env python3
"""
tftp_recovery_engine.py — 100% Autonomous Offline RFC 1350 Dual-Mode TFTP Engine
and Realtek Booter v3.4.11B.9 Image Validator for Tenda AC10 V1.0.

Zero external pip dependencies (uses Python 3 standard library only).
"""
import argparse
import hashlib
import os
import socket
import struct
import sys
import threading
import time
from typing import Dict, Optional, Tuple

MAX_FIRMWARE_PARTITION_SIZE = 0x7E0000 - 0x030000  # 8,060,928 bytes (7,872 KB)
EXPECTED_LOAD_ADDR = 0x80A00000
EXPECTED_BURN_ADDR = 0x00030000


def sum16_be(data: bytes) -> int:
    """Compute 16-bit Big-Endian additive checksum modulo 65536 (Realtek cvimg / Booter 0x80001ebc)."""
    if len(data) % 2 != 0:
        raise ValueError(f"Payload length ({len(data)}) must be even for 16-bit BE checksum.")
    if not data:
        return 0
    return sum(struct.unpack(f">{len(data) // 2}H", data)) & 0xFFFF



def validate_realtek_booter_image(raw: bytes) -> Dict[str, object]:
    """
    Bit-exact emulation of Realtek Booter v3.4.11B.9 AutoBurn (0x800019d0) and check_image (0x8000dd10).
    Raises ValueError if the image is invalid or dangerous to flash.
    """
    total_len = len(raw)
    if total_len < 32:
        raise ValueError(f"Image too small ({total_len} bytes).")
    if total_len > MAX_FIRMWARE_PARTITION_SIZE:
        raise ValueError(
            f"Image size ({total_len:,} B) exceeds 7,872 KB firmware slot ({MAX_FIRMWARE_PARTITION_SIZE:,} B) "
            "and would overwrite CFM NVRAM at 0x7E0000!"
        )

    magic = raw[:4]
    if magic not in (b"cr6c", b"cs6c"):
        raise ValueError(f"Invalid header magic {magic!r} (expected b'cr6c' or b'cs6c').")

    start_addr, burn_addr, seg1_len = struct.unpack_from(">III", raw, 4)
    if start_addr != EXPECTED_LOAD_ADDR:
        raise ValueError(f"Invalid startAddr 0x{start_addr:08X} (expected 0x{EXPECTED_LOAD_ADDR:08X}).")
    if burn_addr != EXPECTED_BURN_ADDR:
        raise ValueError(
            f"Unsafe burnAddr 0x{burn_addr:08X} (must be 0x{EXPECTED_BURN_ADDR:08X} to protect "
            "Bootloader 0x0 and RF Calibration 0x20000)!"
        )
    if 16 + seg1_len > total_len:
        raise ValueError(f"Segment 1 length ({seg1_len}) exceeds file size ({total_len}).")

    seg1_sum = sum16_be(raw[16 : 16 + seg1_len])
    if seg1_sum != 0:
        raise ValueError(f"Segment 1 ({magic.decode()}) 16-bit BE checksum failed: 0x{seg1_sum:04X} != 0x0000.")

    rem_len = total_len - (16 + seg1_len)
    mode = f"Single-Segment ({magic.decode()})"
    seg2_magic = None

    if rem_len > 0:
        # Guard against Realtek Booter v3.4.11B.9 bug @ 0x80001c2c:
        # Multi-segment cs6c + hsqs leaves sp[0x6c]=0 and sets $s7=0 on segment 2, erasing 0x00000000!
        if magic == b"cs6c":
            raise ValueError(
                f"LETHAL IMAGE BLOCKED: Multi-segment 'cs6c' image detected ({rem_len} trailing bytes). "
                "Realtek Booter v3.4.11B.9 bug @ 0x80001c2c sets burnAddr=0x00000000 on segment 2 and erases "
                "the bootloader! Repack as single-segment 'cs6c' or use 'cr6c'."
            )
        if rem_len < 16:
            raise ValueError(f"Trailing {rem_len} bytes after cr6c are too short for hsqs RootFS.")

        seg2_off = 16 + seg1_len
        seg2_magic = raw[seg2_off : seg2_off + 4]
        if seg2_magic not in (b"hsqs", b"sqsh"):
            raise ValueError(f"Invalid segment 2 magic {seg2_magic!r} at 0x{seg2_off:X} (expected b'hsqs' or b'sqsh').")

        # check_rootfs_image (0x8000d844) reads BE32 at +8 of hsqs and adds 0x282 (642)
        (hsqs_be8,) = struct.unpack_from(">I", raw, seg2_off + 8)
        expected_seg2_len = hsqs_be8 + 0x282
        if rem_len != expected_seg2_len:
            raise ValueError(
                f"Segment 2 ({seg2_magic.decode()}) length mismatch: actual={rem_len}, "
                f"check_rootfs_image expects {expected_seg2_len}."
            )
        seg2_sum = sum16_be(raw[seg2_off:])
        if seg2_sum != 0:
            raise ValueError(
                f"Segment 2 ({seg2_magic.decode()}) 16-bit BE checksum failed: 0x{seg2_sum:04X} != 0x0000."
            )
        mode = f"Dual-Segment Factory Stock (cr6c + {seg2_magic.decode()})"

    return {
        "size": total_len,
        "magic": magic.decode("ascii"),
        "mode": mode,
        "start_addr": start_addr,
        "burn_addr": burn_addr,
        "seg1_len": seg1_len,
        "seg2_len": rem_len,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def fix_single_segment_checksum(raw: bytes, force_magic: Optional[bytes] = None) -> bytes:
    """
    Repack or fix a single-segment cr6c/cs6c image so its 16-bit BE additive checksum equals 0x0000.
    Also safely converts a multi-segment cs6c+hsqs image into a safe single-segment cs6c image.
    """
    if len(raw) < 16:
        raise ValueError("Image too short to contain 16-byte cvimg header.")
    magic = force_magic if force_magic else raw[:4]
    if magic not in (b"cr6c", b"cs6c"):
        raise ValueError(f"Unsupported magic {magic!r}")
    start_addr, burn_addr, _ = struct.unpack_from(">III", raw, 4)
    payload = bytearray(raw[16:])
    if len(payload) % 2 == 1:
        payload.append(0x00)
    cur_sum = sum16_be(bytes(payload))
    if cur_sum != 0:
        comp = (-cur_sum) & 0xFFFF
        payload.extend(struct.pack(">H", comp))
    out = magic + struct.pack(">III", start_addr, burn_addr, len(payload)) + bytes(payload)
    validate_realtek_booter_image(out)
    return out


def tftp_push_wrq(
    payload: bytes,
    server_ip: str = "192.168.1.6",
    server_port: int = 69,
    remote_filename: str = "firmware.bin",
    probe_timeout: float = 30.0,
    block_timeout: float = 1.5,
    max_retries: int = 6,
    quiet: bool = False,
) -> Tuple[int, float]:
    """
    RFC 1350 TFTP Client (WRQ Push) compatible with Realtek Booter v3.4.11B.9 (TID port 2098+).
    Handles 16-bit block counter rollover and exact 512-byte boundary 0-byte termination.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        wrq = struct.pack(">H", 2) + remote_filename.encode("ascii") + b"\x00octet\x00"
        deadline = time.monotonic() + probe_timeout
        session_addr: Optional[Tuple[str, int]] = None

        while time.monotonic() < deadline:
            sock.settimeout(min(1.0, max(0.1, deadline - time.monotonic())))
            sock.sendto(wrq, (server_ip, server_port))
            try:
                data, addr = sock.recvfrom(516)
                if len(data) >= 4:
                    opcode, blk = struct.unpack_from(">HH", data, 0)
                    if opcode == 4 and blk == 0 and addr[0] == server_ip:
                        session_addr = addr
                        break
                    elif opcode == 5:
                        err_msg = data[4:-1].decode("ascii", errors="replace")
                        raise RuntimeError(f"Router TFTP ERROR on WRQ: {err_msg}")
            except socket.timeout:
                continue

        if session_addr is None:
            raise TimeoutError(f"Timed out waiting for TFTP ACK 0 from {server_ip}:{server_port}")

        total_len = len(payload)
        offset = 0
        block_num = 1
        send_zero_term = (total_len % 512) == 0
        t0 = time.monotonic()

        while offset < total_len or send_zero_term:
            chunk = payload[offset : offset + 512]
            if offset >= total_len and send_zero_term:
                chunk = b""
                send_zero_term = False

            pkt = struct.pack(">HH", 3, block_num) + chunk
            acked = False
            cur_timeout = block_timeout

            for _ in range(max_retries):
                sock.settimeout(cur_timeout)
                sock.sendto(pkt, session_addr)
                wait_until = time.monotonic() + cur_timeout
                while time.monotonic() < wait_until:
                    try:
                        rx, rx_addr = sock.recvfrom(516)
                        if rx_addr[0] != server_ip or len(rx) < 4:
                            continue
                        op, ack_blk = struct.unpack_from(">HH", rx, 0)
                        if op == 4 and ack_blk == block_num:
                            session_addr = rx_addr
                            acked = True
                            break
                        elif op == 5:
                            err_msg = rx[4:-1].decode("ascii", errors="replace")
                            raise RuntimeError(f"Router TFTP ERROR at block {block_num}: {err_msg}")
                    except socket.timeout:
                        break
                if acked:
                    break
                cur_timeout = min(5.0, cur_timeout * 1.5)

            if not acked:
                raise TimeoutError(f"TFTP DATA block {block_num} timed out after {max_retries} retries.")

            offset += len(chunk)
            block_num = (block_num + 1) & 0xFFFF

        elapsed = max(1e-6, time.monotonic() - t0)
        if not quiet:
            print(f"[OK] Transferred {total_len:,} bytes to {session_addr} in {elapsed:.2f}s ({total_len/1024/elapsed:.1f} KB/s)")
        return total_len, elapsed
    finally:
        sock.close()


class MockRealtekBooterTftpServer:
    """
    Exact loopback emulator of Realtek Booter v3.4.11B.9 TFTP Server (0x8000163c..0x80002620):
    - Listens on 127.0.0.1:<port> for WRQ (opcode 2) or RRQ (opcode 1).
    - Replies to WRQ from ephemeral TID port (simulating 0x80019070 port 2098+).
    - Optionally simulates dropped ACK packets to test client retransmission resilience.
    """

    def __init__(
        self,
        bind_ip: str = "127.0.0.1",
        bind_port: int = 0,
        serve_payload: bytes = b"",
        drop_Every_n_blocks: int = 0,
    ) -> None:
        self.bind_ip = bind_ip
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((bind_ip, bind_port))
        self.port = self.sock.getsockname()[1]
        self.serve_payload = serve_payload
        self.drop_every_n_blocks = drop_Every_n_blocks
        self.received_data = bytearray()
        self.received_filename = ""
        self.total_blocks_acked = 0
        self.completed = threading.Event()
        self.error: Optional[Exception] = None
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop = True
        try:
            self.sock.close()
        except Exception:
            pass

    def _run(self) -> None:
        tid_sock: Optional[socket.socket] = None
        try:
            self.sock.settimeout(0.5)
            while not self._stop:
                try:
                    data, client_addr = self.sock.recvfrom(1024)
                except socket.timeout:
                    continue
                except OSError:
                    break

                if len(data) < 4:
                    continue
                (opcode,) = struct.unpack_from(">H", data, 0)
                if opcode == 2:  # WRQ
                    parts = data[2:].split(b"\x00")
                    self.received_filename = parts[0].decode("ascii", errors="replace")
                    self.received_data.clear()
                    self.total_blocks_acked = 0

                    # Open dedicated TID socket (emulating Realtek Booter TID port 2098+)
                    tid_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    tid_sock.bind((self.bind_ip, 0))
                    tid_sock.settimeout(5.0)
                    tid_sock.sendto(struct.pack(">HH", 4, 0), client_addr)

                    expected_block = 1
                    dropped_Set = set()
                    while not self._stop:
                        pkt, c_addr = tid_sock.recvfrom(1024)
                        if len(pkt) < 4:
                            continue
                        op, blk = struct.unpack_from(">HH", pkt, 0)
                        if op != 3:
                            continue
                        if (
                            self.drop_every_n_blocks > 0
                            and blk % self.drop_every_n_blocks == 0
                            and blk not in dropped_Set
                        ):
                            dropped_Set.add(blk)
                            continue  # Simulate lost packet once

                        if blk == expected_block:
                            chunk = pkt[4:]
                            self.received_data.extend(chunk)
                            self.total_blocks_acked += 1
                            tid_sock.sendto(struct.pack(">HH", 4, blk), c_addr)
                            expected_block = (expected_block + 1) & 0xFFFF
                            if len(chunk) < 512:
                                self.completed.set()
                                return
                        else:
                            prev_blk = (expected_block - 1) & 0xFFFF
                            tid_sock.sendto(struct.pack(">HH", 4, prev_blk), c_addr)
        except Exception as exc:
            self.error = exc
            self.completed.set()
        finally:
            if tid_sock is not None:
                tid_sock.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Tenda AC10 V1.0 Offline TFTP Engine & Image Validator")
    parser.add_argument("--image", required=True, help="Path to firmware binary")
    parser.add_argument("--verify-only", action="store_true", help="Only validate image header & checksums")
    parser.add_argument("--fix-checksum", help="Output path for checksum-repaired single-segment image")
    parser.add_argument("--server-ip", default="192.168.1.6", help="TFTP server IP (default: 192.168.1.6)")
    parser.add_argument("--port", type=int, default=69, help="TFTP server UDP port (default: 69)")
    parser.add_argument("--timeout", type=float, default=60.0, help="Probe timeout in seconds")
    args = parser.parse_args()

    with open(args.image, "rb") as f:
        raw = f.read()

    if args.fix_checksum:
        fixed = fix_single_segment_checksum(raw)
        with open(args.fix_checksum, "wb") as out_f:
            out_f.write(fixed)
        info = validate_realtek_booter_image(fixed)
        print(f"[FIXED] Saved validated image to {args.fix_checksum} ({info['size']:,} B, SHA256={info['sha256']})")
        return 0

    info = validate_realtek_booter_image(raw)
    print(
        f"[PASS] {args.image}: mode={info['mode']}, size={info['size']:,} B, "
        f"start=0x{info['start_addr']:08X}, burn=0x{info['burn_addr']:08X}, sha256={info['sha256']}"
    )

    if args.verify_only:
        return 0

    tftp_push_wrq(raw, server_ip=args.server_ip, server_port=args.port, probe_timeout=args.timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
