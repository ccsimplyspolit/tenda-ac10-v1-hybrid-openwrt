#!/usr/bin/env python3
"""
Firmware Verification & Checksum Engine for Tenda AC10 V1.0
Pure Python 3 Standard Library (Zero External Dependencies)

Reverse-engineered from Realtek Booter v3.4.11B.9:
- Validates maximum image size <= 8,060,928 bytes (7,872 KB, flash partition 0x030000-0x7E0000).
- Validates 16-byte header:
    Offset 0..3:   Magic (b'cr6c', b'cs6c', etc.)
    Offset 4..7:   Load address (0x80A00000 / 0x80000000)
    Offset 8..11:  Burn flash offset (0x00030000)
    Offset 12..15: Payload length (uint32_BE)
- Validates 16-bit Big-Endian additive checksum modulo 65536 == 0x0000 over payload.
- Provides --fix-checksum option to repair custom OpenWrt or test images.
"""

import os
import sys
import struct
import argparse
import hashlib

# Realtek Booter Limits
MAX_FLASH_IMAGE_SIZE = 8060928  # 0x7B0000 (7,872 KB)
BURN_DESTINATION_SAFE = 0x00030000
EXPECTED_LOAD_ADDR   = 0x80A00000

VALID_MAGICS = {
    b"cr6c": "Linux kernel + rootfs (Standard Tenda / OpenWrt)",
    b"cs6c": "Linux kernel (SquashFS)",
    b"w6cg": "Webpages partition",
    b"r6cr": "Root filesystem",
    b"boot": "Boot code / Bootloader",
    b"ALL1": "Total Flash Image (Checksummed)",
    b"ALL2": "Total Flash Image (No Checksum)",
    b"hsqs": "SquashFS filesystem",
}


def compute_16bit_be_checksum(data: bytes) -> int:
    """
    Computes 16-bit Big-Endian additive checksum modulo 65536.
    Matches Realtek Booter stage2 checksum loop at PC 0x80001E64-0x80001E90.
    """
    length = len(data)
    # Pad to even length if odd
    if length % 2 != 0:
        data = data + b"\x00"
        length += 1

    acc = 0
    for i in range(0, length, 2):
        word = (data[i] << 8) | data[i + 1]
        acc = (acc + word) & 0xFFFF
    return acc


def parse_header(header_bytes: bytes):
    """
    Parses 16-byte Realtek cr6c/cs6c header.
    Returns dict with magic, load_addr, burn_offset, payload_len.
    """
    if len(header_bytes) < 16:
        raise ValueError(f"Header too short: {len(header_bytes)} bytes (expected 16)")

    magic = header_bytes[0:4]
    load_addr, burn_offset, payload_len = struct.unpack(">III", header_bytes[4:16])
    return {
        "magic": magic,
        "magic_str": magic.decode("ascii", "replace"),
        "load_addr": load_addr,
        "burn_offset": burn_offset,
        "payload_len": payload_len,
    }


def verify_image_bytes(data: bytes):
    """
    Verifies firmware binary data in-memory.
    Returns (is_valid: bool, results: dict).
    """
    results = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "details": {}
    }

    size = len(data)
    results["details"]["file_size"] = size

    # 1. Size Check
    if size > MAX_FLASH_IMAGE_SIZE:
        results["valid"] = False
        results["errors"].append(
            f"Image size {size:,} B exceeds maximum allowable flash boundary "
            f"of {MAX_FLASH_IMAGE_SIZE:,} B (7,872 KB). Burning this would destroy NVRAM!"
        )
    elif size < 18:
        results["valid"] = False
        results["errors"].append(f"Image too small ({size} bytes). Minimum size is 18 bytes.")
        return results["valid"], results

    # 2. Header Parse
    try:
        hdr = parse_header(data[:16])
        results["details"].update(hdr)
    except Exception as e:
        results["valid"] = False
        results["errors"].append(f"Header parse failed: {e}")
        return results["valid"], results

    # 3. Magic Verification
    if hdr["magic"] not in VALID_MAGICS:
        results["valid"] = False
        results["errors"].append(
            f"Unknown magic header signature: {hdr['magic_str']!r} ({hdr['magic'].hex()}). "
            f"Expected one of: {list(k.decode('ascii') for k in VALID_MAGICS.keys())}"
        )

    # 4. Burn Offset Verification
    if hdr["burn_offset"] < BURN_DESTINATION_SAFE:
        results["valid"] = False
        results["errors"].append(
            f"Burn destination offset 0x{hdr['burn_offset']:08X} is dangerous! "
            f"Minimum safe offset is 0x{BURN_DESTINATION_SAFE:08X} (192 KB). "
            f"Lower offsets will overwrite the Bootloader (0x0..0x20000) or RF Calibrations (0x20000..0x30000)!"
        )

    # 5. Load Address Verification
    if hdr["load_addr"] != EXPECTED_LOAD_ADDR and hdr["magic"] != b"boot":
        results["warnings"].append(
            f"Load address 0x{hdr['load_addr']:08X} differs from standard RAM buffer 0x{EXPECTED_LOAD_ADDR:08X}."
        )

    # 6. Segment 1 Payload Length & Checksum Check
    actual_payload_len = size - 16
    hdr_payload_len = hdr["payload_len"]
    results["details"]["actual_payload_len"] = actual_payload_len

    if hdr_payload_len > actual_payload_len:
        results["valid"] = False
        results["errors"].append(
            f"Header specifies payload length {hdr_payload_len:,} B, but file only has {actual_payload_len:,} B."
        )
        return results["valid"], results

    # Checksum is computed over the payload range defined by header length
    checked_payload = data[16 : 16 + hdr_payload_len]
    csum = compute_16bit_be_checksum(checked_payload)
    results["details"]["checksum_val"] = csum

    if csum != 0x0000:
        results["valid"] = False
        results["errors"].append(
            f"Segment 1 checksum failure: 0x{csum:04X} (Expected 0x0000). "
            f"The Realtek Booter will reject this image with 'imgage checksum error at %X!'."
        )

    # 7. Multi-Segment Validation & Security Exploit Prevention
    seg2_offset = 16 + hdr_payload_len
    remaining_bytes = size - seg2_offset
    results["details"]["remaining_bytes"] = remaining_bytes

    if remaining_bytes > 0:
        results["details"]["is_multi_segment"] = True
        if remaining_bytes < 4:
            results["valid"] = False
            results["errors"].append(
                f"Image has {remaining_bytes} unparsed trailing bytes (too short to form a valid secondary segment)."
            )
            return results["valid"], results

        seg2_magic = data[seg2_offset : seg2_offset + 4]
        results["details"]["seg2_magic"] = seg2_magic

        # CRITICAL AUTO-BURN EXPLOIT GUARD:
        # In AutoBurn (0x80001C28), cs6c zeros register $s7, causing 2-segment cs6c + hsqs
        # to write segment 2 to flash offset 0x00000000 (overwriting the bootloader).
        if seg2_magic == b"hsqs":
            if hdr["magic"] == b"cs6c":
                results["valid"] = False
                results["errors"].append(
                    "CRITICAL SECURITY VETO: 2-segment 'cs6c + hsqs' image detected! "
                    "In Realtek AutoBurn (0x80001C28), cs6c zeros register $s7, causing "
                    "segment 2 (SquashFS) to overwrite flash at 0x00000000 and permanently "
                    "destroy the bootloader! Multi-segment images MUST use 'cr6c' for segment 1."
                )
                return False, results

            # Validate segment 2 (hsqs) checksum and ensure remaining_bytes == 0 after segment 2
            seg2_data = data[seg2_offset :]
            csum_seg2 = compute_16bit_be_checksum(seg2_data)
            results["details"]["seg2_checksum_val"] = csum_seg2

            if csum_seg2 != 0x0000:
                results["valid"] = False
                results["errors"].append(
                    f"Segment 2 (hsqs) checksum failure: 0x{csum_seg2:04X} (Expected 0x0000). "
                    f"AutoBurn will reject secondary segment or fail reboot."
                )
        elif seg2_magic in (b"cr6c", b"cs6c"):
            if remaining_bytes < 16:
                results["valid"] = False
                results["errors"].append(f"Segment 2 header truncated ({remaining_bytes} bytes < 16).")
                return False, results
            hdr2 = parse_header(data[seg2_offset : seg2_offset + 16])
            results["details"]["seg2_header"] = hdr2
            if hdr2["burn_offset"] < BURN_DESTINATION_SAFE:
                results["valid"] = False
                results["errors"].append(
                    f"Segment 2 burn offset 0x{hdr2['burn_offset']:08X} is dangerous! "
                    f"Minimum safe offset is 0x{BURN_DESTINATION_SAFE:08X}."
                )
            seg2_payload_len = hdr2["payload_len"]
            if seg2_offset + 16 + seg2_payload_len > size:
                results["valid"] = False
                results["errors"].append(
                    f"Segment 2 specifies {seg2_payload_len} B payload, but only {size - (seg2_offset + 16)} B remain."
                )
                return False, results
            seg2_payload = data[seg2_offset + 16 : seg2_offset + 16 + seg2_payload_len]
            csum_seg2 = compute_16bit_be_checksum(seg2_payload)
            results["details"]["seg2_checksum_val"] = csum_seg2
            if csum_seg2 != 0x0000:
                results["valid"] = False
                results["errors"].append(f"Segment 2 checksum failure: 0x{csum_seg2:04X} (Expected 0x0000).")
            
            rem_after_seg2 = size - (seg2_offset + 16 + seg2_payload_len)
            if rem_after_seg2 != 0:
                results["valid"] = False
                results["errors"].append(
                    f"Image has {rem_after_seg2} unparsed trailing bytes after segment 2. "
                    f"AutoBurn will fail on 3rd iteration with 'unknown image type'."
                )
        else:
            results["valid"] = False
            results["errors"].append(
                f"Unknown secondary segment magic: {seg2_magic!r}. AutoBurn will fail with 'unknown image type'."
            )
    else:
        results["details"]["is_multi_segment"] = False

    # Compute SHA-256 for integrity reference
    results["details"]["sha256"] = hashlib.sha256(data).hexdigest()
    return results["valid"], results


def verify_image_file(file_path: str):
    """Verifies a firmware file on disk."""
    if not os.path.exists(file_path):
        return False, {"valid": False, "errors": [f"File not found: {file_path}"], "warnings": [], "details": {}}

    with open(file_path, "rb") as f:
        data = f.read()

    return verify_image_bytes(data)


def fix_image_checksum(input_path: str, output_path: str = None) -> str:
    """
    Appends a 16-bit compensating word to make the payload sum modulo 65536 == 0x0000.
    Updates the 16-byte header payload length field accordingly.
    Returns path to repaired file.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with open(input_path, "rb") as f:
        data = bytearray(f.read())

    if len(data) < 16:
        raise ValueError("File too short to contain a 16-byte header")

    hdr = parse_header(data[:16])
    hdr_payload_len = hdr["payload_len"]
    actual_payload_len = len(data) - 16

    # Determine slice to fix
    target_len = min(hdr_payload_len, actual_payload_len)
    if target_len == 0 or target_len > actual_payload_len:
        target_len = actual_payload_len

    payload_to_check = bytes(data[16 : 16 + target_len])
    current_csum = compute_16bit_be_checksum(payload_to_check)

    if current_csum == 0x0000:
        print("[*] Image checksum is already 0x0000! No repair needed.")
        if output_path and output_path != input_path:
            with open(output_path, "wb") as f:
                f.write(data)
            return output_path
        return input_path

    # Calculate compensating word C such that (current_csum + C) % 65536 == 0
    # Note: if len(payload_to_check) was odd, compute_16bit_be_checksum padded with 0.
    is_odd = (len(payload_to_check) % 2 != 0)
    if is_odd:
        # Append 1 byte 0x00 first
        data.insert(16 + target_len, 0x00)
        target_len += 1
        current_csum = compute_16bit_be_checksum(bytes(data[16 : 16 + target_len]))

    compensating_word = (65536 - current_csum) & 0xFFFF
    comp_bytes = struct.pack(">H", compensating_word)

    # Append compensating word to data at end of checked region
    insert_pos = 16 + target_len
    data[insert_pos:insert_pos] = comp_bytes
    new_payload_len = target_len + 2

    # Update header payload length field
    struct.pack_into(">I", data, 12, new_payload_len)

    # Re-verify
    recheck_csum = compute_16bit_be_checksum(bytes(data[16 : 16 + new_payload_len]))
    if recheck_csum != 0x0000:
        raise RuntimeError(f"Internal error: Checksum recalculation yielded 0x{recheck_csum:04X} instead of 0x0000")

    if not output_path:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_fixed{ext}"

    with open(output_path, "wb") as f:
        f.write(data)

    print(f"[+] Fixed checksum: Injected 0x{compensating_word:04X} at offset {insert_pos}.")
    print(f"[+] Updated header payload length: {new_payload_len:,} bytes.")
    print(f"[+] Saved repaired image to: {output_path}")
    return output_path


def format_report(file_path: str, is_valid: bool, results: dict) -> str:
    """Formats verification findings into a human-readable table."""
    d = results.get("details", {})
    lines = []
    lines.append("=" * 72)
    lines.append(f"  FIRMWARE INTEGRITY REPORT: {os.path.basename(file_path)}")
    lines.append("=" * 72)
    lines.append(f"  File Path:          {file_path}")
    lines.append(f"  Total Size:         {d.get('file_size', 0):,} bytes ({d.get('file_size', 0)/1024:.1f} KB)")
    lines.append(f"  Max Flash Limit:    {MAX_FLASH_IMAGE_SIZE:,} bytes (7,872 KB)")
    size_ok = d.get('file_size', 0) <= MAX_FLASH_IMAGE_SIZE
    lines.append(f"  Size Compliance:    {'[PASS] SAFE' if size_ok else '[FAIL] EXCEEDS PARTITION BOUNDARY'}")
    lines.append("-" * 72)

    magic = d.get("magic", b"")
    magic_str = d.get("magic_str", "")
    magic_desc = VALID_MAGICS.get(magic, "UNKNOWN / INVALID")
    lines.append(f"  Magic Signature:    {magic_str!r} ({magic.hex()}) -> {magic_desc}")

    load_addr = d.get("load_addr", 0)
    lines.append(f"  RAM Load Address:   0x{load_addr:08X} (Expected: 0x{EXPECTED_LOAD_ADDR:08X})")

    burn_offset = d.get("burn_offset", 0)
    burn_ok = burn_offset >= BURN_DESTINATION_SAFE
    lines.append(f"  Flash Burn Offset:  0x{burn_offset:08X} ({burn_offset//1024} KB)")
    lines.append(f"  Burn Safe Check:    {'[PASS] PROTECTED' if burn_ok else '[FAIL] DANGEROUS OVERWRITE'}")

    p_len = d.get("payload_len", 0)
    act_len = d.get("actual_payload_len", 0)
    lines.append(f"  Header Payload Len: {p_len:,} bytes (Actual remaining: {act_len:,} bytes)")

    csum = d.get("checksum_val", 0xFFFF)
    csum_ok = (csum == 0x0000)
    lines.append(f"  16-Bit BE Checksum: 0x{csum:04X} (Expected: 0x0000)")
    lines.append(f"  Checksum Status:    {'[PASS] VALID' if csum_ok else '[FAIL] INVALID CHECKSUM'}")
    lines.append(f"  SHA-256 Digest:     {d.get('sha256', 'N/A')}")
    lines.append("-" * 72)

    if results.get("errors"):
        lines.append("  ERRORS DETECTED:")
        for err in results.get("errors", []):
            lines.append(f"   [-] {err}")

    if results.get("warnings"):
        lines.append("  WARNINGS:")
        for warn in results.get("warnings", []):
            lines.append(f"   [!] {warn}")

    lines.append("=" * 72)
    status_str = ">>> VERIFICATION PASSED: IMAGE IS SAFE FOR TFTP RECOVERY <<<" if is_valid else ">>> VERIFICATION FAILED: DO NOT FLASH THIS IMAGE <<<"
    lines.append(f"  {status_str}")
    lines.append("=" * 72)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Realtek Booter cr6c/cs6c Firmware Image Validator for Tenda AC10 V1.0"
    )
    parser.add_argument("image", help="Path to firmware image binary to verify")
    parser.add_argument("--fix-checksum", action="store_true",
                        help="Repair invalid checksum by injecting compensating 16-bit word")
    parser.add_argument("--output", "-o", default=None,
                        help="Output path for fixed image (used with --fix-checksum)")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Output only PASS or FAIL")

    args = parser.parse_args()

    if getattr(args, 'fix_checksum', False):
        try:
            fixed_path = fix_image_checksum(args.image, args.output)
            # Re-verify fixed file
            is_valid, results = verify_image_file(fixed_path)
            if not args.quiet:
                print(format_report(fixed_path, is_valid, results))
            sys.exit(0 if is_valid else 1)
        except Exception as e:
            print(f"[-] Checksum repair failed: {e}")
            sys.exit(1)

    is_valid, results = verify_image_file(args.image)

    if args.quiet:
        print("PASS" if is_valid else "FAIL")
    else:
        print(format_report(args.image, is_valid, results))

    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
