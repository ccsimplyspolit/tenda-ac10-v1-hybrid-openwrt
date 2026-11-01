#!/usr/bin/env python3
"""
Tenda AC10 V1.0 Proprietary SquashFS 4.0 XZ Extractor & Decompressor
===================================================================

Reverse-Engineered Specification:
- Stock SquashFS Superblock magic: 0x73717368 ("hsqs", SquashFS 4.0 LE).
- Custom Stream Container:
  Each data block begins with a proprietary 12-byte header:
  54 65 6E 64 61 00 00 01 FD 69 95 C6 ("Tenda\x00\x00\x01" replacing standard "\xFD7zXZ\x00").
- Block Header:
  Declares variable-length integers (VLI) for compressed and uncompressed block sizes.
- Filter Specification:
  Standard raw LZMA2 filter (ID 0x21) with 128 KB dictionary (0x0A / 131,072 bytes).
- Standard SquashFS Superblock location:
  * In carved RootFS: Offset 0x000000
  * In full 8MB SPI NOR dump: Offset 0x23BC12

Usage:
    python extract_tenda_xz.py --input <path_to_binary> [--verify-only] [--output <dir>]
"""

import os
import sys
import struct
import lzma
import argparse

def parse_vli(buffer, offset):
    """Parse Variable-Length Integer (VLI) used in LZMA/XZ headers."""
    result = 0
    shift = 0
    while True:
        byte = buffer[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return result, offset

def locate_squashfs_superblock(data):
    """Locate SquashFS superblock ('hsqs') in buffer."""
    # Check at offset 0
    if len(data) >= 96 and data[:4] == b"hsqs":
        return 0
    # Check known stock offset
    stock_offset = 0x23BC12
    if len(data) > stock_offset + 96 and data[stock_offset:stock_offset+4] == b"hsqs":
        return stock_offset
    # Search entire buffer
    idx = data.find(b"hsqs")
    if idx != -1:
        return idx
    return None

def extract_and_verify(input_path, output_dir=None, verify_only=False):
    if not os.path.exists(input_path):
        print(f"[-] Error: Input file not found: {input_path}")
        return False

    file_size = os.path.getsize(input_path)
    print("=" * 72)
    print(f"TENDA AC10 V1.0 SQUASHFS 4.0 XZ EXTRACTOR")
    print("=" * 72)
    print(f"Input file:  {input_path}")
    print(f"File size:   {file_size:,} bytes ({file_size / (1024 * 1024):.2f} MB)")

    with open(input_path, "rb") as f:
        data = f.read()

    sq_start = locate_squashfs_superblock(data)
    if sq_start is None:
        print("[-] Error: No valid SquashFS superblock ('hsqs') found in input file.")
        return False

    sq_hdr = data[sq_start:sq_start+96]
    magic, inodes, mkfs_time, block_size, fragments, compression, block_log, flags, no_ids, s_major, s_minor = struct.unpack("<IIIIIHHHHHH", sq_hdr[:32])
    root_inode, bytes_used = struct.unpack("<QQ", sq_hdr[32:48])

    print(f"Superblock Offset:  0x{sq_start:06X}")
    print(f"Magic:              0x{magic:08X} ({chr(magic&0xff)}{chr((magic>>8)&0xff)}{chr((magic>>16)&0xff)}{chr((magic>>24)&0xff)})")
    print(f"Inodes:             {inodes:,}")
    print(f"Block Size:         {block_size:,} bytes (log2: {block_log})")
    print(f"Compression ID:     {compression} (Tenda Custom LZMA2 / XZ)")
    print(f"Total Bytes Used:   {bytes_used:,} bytes (0x{bytes_used:X}, {bytes_used / (1024 * 1024):.2f} MB)")
    print(f"Filesystem Span:    0x{sq_start:06X} - 0x{sq_start + bytes_used:06X}")
    print("-" * 72)

    # Scan custom Tenda XZ compressed blocks
    pos = sq_start
    sq_end = sq_start + bytes_used
    blocks = []

    while True:
        idx = data.find(b"Tenda\x00", pos)
        if idx == -1 or idx >= sq_end:
            break

        bh_offset = idx + 12
        if bh_offset + 2 >= len(data):
            break

        bh_size = (data[bh_offset] + 1) * 4
        bflags = data[bh_offset + 1]
        has_comp_size = bool(bflags & 0x40)
        has_uncomp_size = bool(bflags & 0x80)

        curr = bh_offset + 2
        comp_size = None
        uncomp_size = None
        if has_comp_size:
            comp_size, curr = parse_vli(data, curr)
        if has_uncomp_size:
            uncomp_size, curr = parse_vli(data, curr)

        payload_start = idx + 12 + bh_size
        blocks.append({
            "idx": len(blocks),
            "offset": idx,
            "rel_offset": idx - sq_start,
            "bh_size": bh_size,
            "payload_start": payload_start,
            "comp_size": comp_size,
            "uncomp_size": uncomp_size
        })
        pos = payload_start + (comp_size if comp_size else 0)

    print(f"[+] Identified {len(blocks)} custom Tenda compressed blocks.")

    # Decompress blocks
    total_uncompressed = 0
    corrupt_count = 0
    decompressed_data = []

    for b in blocks:
        payload = data[b["payload_start"] : b["payload_start"] + b["comp_size"]]
        decomp = lzma.LZMADecompressor(
            format=lzma.FORMAT_RAW,
            filters=[{"id": lzma.FILTER_LZMA2, "dict_size": 131072}]
        )
        try:
            out = decomp.decompress(payload)
            if b["uncomp_size"] is not None and len(out) != b["uncomp_size"]:
                print(f"[-] Size mismatch in block #{b['idx']}: got {len(out)}, expected {b['uncomp_size']}")
                corrupt_count += 1
            total_uncompressed += len(out)
            if not verify_only:
                decompressed_data.append(out)
        except Exception as e:
            print(f"[-] Decompression error in block #{b['idx']}: {e}")
            corrupt_count += 1

    print("-" * 72)
    print(f"Decompression Results:")
    print(f"  Valid blocks:        {len(blocks) - corrupt_count} / {len(blocks)} ({100.0 * (len(blocks) - corrupt_count) / max(len(blocks), 1):.1f}%)")
    print(f"  Total Uncompressed:  {total_uncompressed:,} bytes ({total_uncompressed / (1024 * 1024):.2f} MB)")
    if total_uncompressed > 0:
        print(f"  Compression Ratio:   {bytes_used / total_uncompressed:.2f}x ({100.0 * bytes_used / total_uncompressed:.1f}%)")

    if corrupt_count == 0:
        print(f"[+] STATUS: 100% INTEGRITY VERIFIED - ALL BLOCKS DECOMPRESSED SUCCESSFULLY")
    else:
        print(f"[-] STATUS: INTEGRITY FAILURE - {corrupt_count} CORRUPT BLOCKS DETECTED")
        return False

    # Optional extraction output
    if output_dir and not verify_only:
        os.makedirs(output_dir, exist_ok=True)
        raw_out_path = os.path.join(output_dir, "tenda_rootfs_decompressed.bin")
        with open(raw_out_path, "wb") as f_out:
            for chunk in decompressed_data:
                f_out.write(chunk)
        print(f"[+] Exported decompressed payload to: {raw_out_path}")

    return corrupt_count == 0

def main():
    parser = argparse.ArgumentParser(
        description="Tenda AC10 V1.0 Proprietary SquashFS 4.0 XZ Extractor & Decompressor"
    )
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Path to full flash dump or carved SquashFS rootfs binary"
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Directory to export decompressed payload"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Validate 100%% block decompression without writing to disk"
    )

    args = parser.parse_args()
    success = extract_and_verify(args.input, args.output, args.verify_only)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
