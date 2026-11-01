#!/usr/bin/env python3
"""
mtd1_mac_cal_tool.py — Tenda AC10 V1.0 Factory Calibration (mtd1 @ 0x020000)
MAC Address Editor, Sanitizer & IEEE 802.3 CRC32 Checksum Recomputer.

Answers 4PDA community questions (#3016, #3583 by dimoхa) when cloning an
8 MB CH341A SPI NOR flash dump (`0x000000..0x800000`) or 64 KB `mtd1` dump
(`0x020000..0x030000`) onto a donor Tenda AC10 V1.0 board:

Binary Format of `mtd1` (`0x020000..0x030000`, 65,536 bytes):
  - Offset 0x0000..0x0003 (4B): Little-Endian IEEE 802.3 CRC32 over `mtd1[8:65536]`
                                (`zlib.crc32(mtd1[8:65536]) & 0xFFFFFFFF`).
  - Offset 0x0004..0x0007 (4B): Little-Endian uint32 sequence/header word (`0x00000000` on mtd1).
  - Offset 0x0008..0xFFFF:      Newline-delimited ASCII `KEY=VALUE\\n` entries padded
                                to 65,536 bytes with `0x00`.

WARNING: Editing MAC addresses in a hex editor WITHOUT recomputing the 4-byte
Little-Endian CRC32 at `0x020000` causes stock Tenda `libcfm.so` / `flash` to
reject the entire factory RF calibration partition (losing 2.4G/5G XCAP, THER,
and per-channel TX power tables)! This tool edits keys safely and recomputes
`mtd1[0:4]` automatically.

Zero external pip dependencies (Python 3 standard library only).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import zlib
from typing import Dict, List, Optional, Tuple

MTD1_SIZE = 0x10000       # 65,536 bytes (64 KB)
FULL_FLASH_SIZE = 0x800000  # 8,388,608 bytes (8 MB Winbond W25Q64FV / GigaDevice GD25Q64C)
MTD1_FLASH_OFFSET = 0x020000


def normalize_mac12(mac_str: str) -> str:
    """Normalize '50:0F:F5:12:34:50' or '50-0f-f5-12-34-50' or '500FF5123450' -> '500FF5123450'."""
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", mac_str).upper()
    if len(cleaned) != 12:
        raise ValueError(f"Invalid MAC address '{mac_str}' (expected 12 hex digits, got '{cleaned}').")
    int_val = int(cleaned, 16)
    if (int_val >> 40) & 0x01:
        raise ValueError(f"Invalid unicast MAC address '{mac_str}': multicast bit (bit 0 of first octet) is set.")
    return cleaned


def format_mac_colon(mac12: str) -> str:
    m = normalize_mac12(mac12)
    return ":".join(m[i : i + 2] for i in range(0, 12, 2))


def mac_add(mac12: str, delta: int) -> str:
    """Increment the 24-bit NIC suffix (or full 48-bit MAC on carry) matching Tenda factory derivation."""
    m = normalize_mac12(mac12)
    oui = m[:6]
    nic = (int(m[6:], 16) + delta) & 0xFFFFFF
    return f"{oui}{nic:06X}"


def extract_mtd1_slice(raw: bytes) -> Tuple[bytes, int]:
    """Return `(mtd1_64kb, base_offset_in_file)` from either a 64 KB mtd1 file or an 8 MB full flash dump."""
    if len(raw) == MTD1_SIZE:
        return raw, 0
    if len(raw) == FULL_FLASH_SIZE:
        return raw[MTD1_FLASH_OFFSET : MTD1_FLASH_OFFSET + MTD1_SIZE], MTD1_FLASH_OFFSET
    raise ValueError(
        f"Unsupported dump size {len(raw):,} bytes. Expected 65,536 B (64 KB mtd1) "
        f"or 8,388,608 B (8 MB full SPI NOR flash dump)."
    )


def parse_mtd1(mtd1: bytes) -> Dict[str, object]:
    """Parse 64 KB mtd1 partition, verify IEEE 802.3 CRC32, and return ordered key-value list + metadata."""
    if len(mtd1) != MTD1_SIZE:
        raise ValueError(f"mtd1 slice must be exactly {MTD1_SIZE} bytes, got {len(mtd1)}.")

    stored_crc, seq = struct.unpack_from("<II", mtd1, 0)
    calc_crc = zlib.crc32(mtd1[8:]) & 0xFFFFFFFF

    payload_region = mtd1[8:]
    # Identify padding byte (0x00 on stock Tenda mtd1)
    pad_byte = payload_region[-1]
    if pad_byte not in (0x00, 0xFF):
        pad_byte = 0x00
    stripped = payload_region.rstrip(bytes([pad_byte]))

    # Tenda mtd1 uses '\n'-delimited ASCII KEY=VALUE lines (or '\x00'-delimited on some Realtek SDK variants)
    delimiter = b"\n" if b"\n" in stripped else b"\x00"
    trailing_delim = stripped.endswith(delimiter)

    entries: List[Tuple[str, str, int]] = []
    pos = 8
    for raw_item in stripped.split(delimiter):
        if not raw_item:
            pos += len(delimiter)
            continue
        item_str = raw_item.decode("ascii", errors="strict")
        if "=" not in item_str:
            raise ValueError(f"Malformed mtd1 entry at offset 0x{pos:04X}: {item_str!r}")
        k, v = item_str.split("=", 1)
        entries.append((k, v, pos))
        pos += len(raw_item) + len(delimiter)

    return {
        "stored_crc": stored_crc,
        "calc_crc": calc_crc,
        "crc_valid": stored_crc == calc_crc,
        "seq": seq,
        "pad_byte": pad_byte,
        "delimiter": delimiter,
        "trailing_delim": trailing_delim,
        "entries": entries,
        "dict": {k: v for k, v, _ in entries},
    }


def build_mtd1(
    entries: List[Tuple[str, str]],
    seq: int = 0,
    delimiter: bytes = b"\n",
    trailing_delim: bool = True,
    pad_byte: int = 0x00,
) -> bytes:
    """Serialize ordered `(key, value)` entries into a 65,536-byte mtd1 image with fresh LE IEEE CRC32."""
    chunks = [f"{k}={v}".encode("ascii") for k, v in entries]
    body = delimiter.join(chunks)
    if trailing_delim and chunks:
        body += delimiter
    max_body = MTD1_SIZE - 8
    if len(body) > max_body:
        raise ValueError(f"Serialized mtd1 body ({len(body)} B) exceeds {max_body} B capacity.")
    padded_body = body + bytes([pad_byte]) * (max_body - len(body))
    crc = zlib.crc32(padded_body) & 0xFFFFFFFF
    header = struct.pack("<II", crc, seq)
    return header + padded_body


def update_mtd1_keys(raw_dump: bytes, updates: Dict[str, str]) -> bytes:
    """
    Apply `updates` (`{key: new_value}`) to a 64 KB mtd1 dump or 8 MB full flash dump,
    preserving key order and recomputing `mtd1[0:4]` Little-Endian CRC32.
    """
    mtd1, base_off = extract_mtd1_slice(raw_dump)
    parsed = parse_mtd1(mtd1)
    existing_keys = {k for k, _, _ in parsed["entries"]}

    new_entries: List[Tuple[str, str]] = []
    for k, v, _ in parsed["entries"]:
        new_entries.append((k, updates[k] if k in updates else v))
    for k, v in updates.items():
        if k not in existing_keys:
            new_entries.append((k, v))

    new_mtd1 = build_mtd1(
        new_entries,
        seq=int(parsed["seq"]),
        delimiter=bytes(parsed["delimiter"]),
        trailing_delim=bool(parsed["trailing_delim"]),
        pad_byte=int(parsed["pad_byte"]),
    )

    if len(raw_dump) == MTD1_SIZE:
        return new_mtd1
    out = bytearray(raw_dump)
    out[base_off : base_off + MTD1_SIZE] = new_mtd1
    return bytes(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tenda AC10 V1.0 mtd1 (0x020000) MAC Editor & IEEE CRC32 Checksum Tool (64KB mtd1 or 8MB full dump)"
    )
    parser.add_argument("input", help="Path to 64 KB mtd1 dump or 8 MB CH341A full flash dump")
    parser.add_argument("-o", "--output", help="Output path for modified dump (required when editing keys)")
    parser.add_argument("--verify", action="store_true", help="Verify IEEE 802.3 CRC32 and print MAC/RF summary")
    parser.add_argument(
        "--set-base-mac",
        help="Set base LAN MAC (HW_NIC0_ADDR) and auto-derive 2.4G (+1: HW_WLAN1_WLAN_ADDR) and 5G (+5: HW_WLAN0_WLAN_ADDR)",
    )
    parser.add_argument("--set-lan-mac", help="Explicitly set HW_NIC0_ADDR (12 hex digits or AA:BB:CC:DD:EE:FF)")
    parser.add_argument("--set-2g-mac", help="Explicitly set HW_WLAN1_WLAN_ADDR (2.4 GHz MAC)")
    parser.add_argument("--set-5g-mac", help="Explicitly set HW_WLAN0_WLAN_ADDR (5 GHz MAC)")
    parser.add_argument(
        "--set-key",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Set arbitrary mtd1 calibration/config key (repeatable)",
    )
    parser.add_argument(
        "--sanitize",
        action="store_true",
        help="Sanitize personal identifiers (MACs -> 500FF5000000/01/05, WSC PIN -> 00000000, ucloud_serialnum -> 0000000, Wi-Fi passwords -> 12345678)",
    )
    parser.add_argument("--export-json", help="Export all parsed mtd1 keys to JSON file")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"[ERROR] Input file not found: {args.input}", file=sys.stderr)
        return 1

    with open(args.input, "rb") as f:
        raw = f.read()

    mtd1, base_off = extract_mtd1_slice(raw)
    info = parse_mtd1(mtd1)
    kv: Dict[str, str] = info["dict"]  # type: ignore[assignment]

    crc_status = "VALID" if info["crc_valid"] else "INVALID (MISMATCH!)"
    print("=" * 76)
    print(f"Tenda AC10 V1.0 mtd1 Calibration Inspector ({os.path.basename(args.input)})")
    print("=" * 76)
    print(f"  Container Size : {len(raw):,} B (mtd1 base offset: 0x{base_off:06X})")
    print(
        f"  Header CRC32   : stored=0x{info['stored_crc']:08X} | computed=0x{info['calc_crc']:08X} -> [{crc_status}]"
    )
    print(f"  Header Seq     : {info['seq']} | Total Keys: {len(info['entries'])}")

    for label, key in [
        ("LAN Base MAC  ", "HW_NIC0_ADDR"),
        ("2.4 GHz MAC   ", "HW_WLAN1_WLAN_ADDR"),
        ("5 GHz MAC     ", "HW_WLAN0_WLAN_ADDR"),
        ("NIC1 Default  ", "HW_NIC1_ADDR"),
        ("5G XCAP / THER", "HW_WLAN0_11N_XCAP"),
        ("2G XCAP / THER", "HW_WLAN1_11N_XCAP"),
    ]:
        for e_k, e_v, e_off in info["entries"]:  # type: ignore[union-attr]
            if e_k == key:
                flash_off = base_off + e_off
                val_off = flash_off + len(e_k) + 1
                if "ADDR" in key and len(e_v) == 12:
                    print(
                        f"  {label} : {format_mac_colon(e_v)} ({e_v}) @ mtd1+0x{e_off:04X} (flash val @ 0x{val_off:06X})"
                    )
                elif key == "HW_WLAN0_11N_XCAP":
                    print(f"  {label} : XCAP={e_v}, THER={kv.get('HW_WLAN0_11N_THER', '?')} (RegDomain={kv.get('HW_WLAN0_REG_DOMAIN', '?')})")
                elif key == "HW_WLAN1_11N_XCAP":
                    print(f"  {label} : XCAP={e_v}, THER={kv.get('HW_WLAN1_11N_THER', '?')} (RegDomain={kv.get('HW_WLAN1_REG_DOMAIN', '?')})")

    updates: Dict[str, str] = {}
    if args.sanitize:
        updates["HW_NIC0_ADDR"] = "500FF5000000"
        updates["HW_WLAN1_WLAN_ADDR"] = "500FF5000001"
        updates["HW_WLAN0_WLAN_ADDR"] = "500FF5000005"
        if "HW_WLAN0_WSC_PIN" in kv:
            updates["HW_WLAN0_WSC_PIN"] = "00000000"
        if "HW_WLAN1_WSC_PIN" in kv:
            updates["HW_WLAN1_WSC_PIN"] = "00000000"
        if "ucloud_serialnum" in kv:
            updates["ucloud_serialnum"] = "0000000"
        if "TD_WLAN0_SSID0_PWD" in kv:
            updates["TD_WLAN0_SSID0_PWD"] = "12345678"
        if "TD_WLAN1_SSID0_PWD" in kv:
            updates["TD_WLAN1_SSID0_PWD"] = "12345678"
        if "TD_ATE_SN" in kv:
            updates["TD_ATE_SN"] = ""

    if args.set_base_mac:
        base_mac = normalize_mac12(args.set_base_mac)
        updates["HW_NIC0_ADDR"] = base_mac
        updates["HW_WLAN1_WLAN_ADDR"] = mac_add(base_mac, 1)
        updates["HW_WLAN0_WLAN_ADDR"] = mac_add(base_mac, 5)

    if args.set_lan_mac:
        updates["HW_NIC0_ADDR"] = normalize_mac12(args.set_lan_mac)
    if args.set_2g_mac:
        updates["HW_WLAN1_WLAN_ADDR"] = normalize_mac12(args.set_2g_mac)
    if args.set_5g_mac:
        updates["HW_WLAN0_WLAN_ADDR"] = normalize_mac12(args.set_5g_mac)

    for item in args.set_key:
        if "=" not in item:
            print(f"[ERROR] Invalid --set-key '{item}' (expected KEY=VALUE).", file=sys.stderr)
            return 1
        k, v = item.split("=", 1)
        updates[k] = v

    if updates:
        if not args.output:
            print("[ERROR] -o / --output is required when modifying mtd1 keys.", file=sys.stderr)
            return 1
        updated_raw = update_mtd1_keys(raw, updates)
        new_mtd1, _ = extract_mtd1_slice(updated_raw)
        new_info = parse_mtd1(new_mtd1)
        assert new_info["crc_valid"], "Internal error: recomputed mtd1 CRC32 failed validation!"
        with open(args.output, "wb") as out_f:
            out_f.write(updated_raw)
        sha = hashlib.sha256(updated_raw).hexdigest()
        print("-" * 76)
        print(f"  [UPDATED] Wrote {len(updated_raw):,} B to {args.output}")
        print(f"  [UPDATED] New mtd1 CRC32 = 0x{new_info['stored_crc']:08X} (LE bytes: {new_mtd1[:4].hex(' ')})")
        print(f"  [UPDATED] Output SHA-256 = {sha}")
        kv = new_info["dict"]  # type: ignore[assignment]

    if args.export_json:
        export_dict = dict(sorted(kv.items()))
        for pwd_key in ("TD_WLAN0_SSID0_PWD", "TD_WLAN1_SSID0_PWD"):
            if pwd_key in export_dict and export_dict[pwd_key] == "12345678" and args.sanitize:
                export_dict[pwd_key] = "<YOUR_WIFI_PASSWORD>"
        with open(args.export_json, "w", encoding="utf-8", newline="\n") as jf:
            json.dump(export_dict, jf, indent=2)
            jf.write("\n")
        print(f"  [EXPORT]  Wrote {len(export_dict)} keys to {args.export_json}")

    if args.verify and not updates and not info["crc_valid"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
