#!/usr/bin/env python3
"""
Tenda AC10 V1.0 SquashFS Decompressor & Extractor
Reverse-engineered for Tenda proprietary SquashFS 4.0 XZ compression format.
"""

import os
import sys
import struct
import lzma

FLASH_PATH = r"/workspace/analysis\21647d8e-3d9c-493f-900f-f13429d32667\scratch\Tenda_AC10_V1_FullFlash_8MB.bin"

def parse_vli(b, offset):
    res = 0
    shift = 0
    while True:
        byte = b[offset]
        offset += 1
        res |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return res, offset

def extract_and_verify(flash_path, output_dir=None):
    if not os.path.exists(flash_path):
        print(f"Error: Flash file not found at {flash_path}")
        return False

    with open(flash_path, "rb") as f:
        data = f.read()

    sq_start = 0x23BC12
    sq_hdr = data[sq_start:sq_start+96]
    magic, inodes, mkfs_time, block_size, fragments, compression, block_log, flags, no_ids, s_major, s_minor = struct.unpack("<IIIIIHHHHHH", sq_hdr[:32])
    root_inode, bytes_used = struct.unpack("<QQ", sq_hdr[32:48])

    print("=" * 70)
    print("TENDA SQUASHFS 4.0 METADATA")
    print("=" * 70)
    print(f"Superblock Offset:  0x{sq_start:06X}")
    print(f"Magic:              0x{magic:08X} ({chr(magic&0xff)}{chr((magic>>8)&0xff)}{chr((magic>>16)&0xff)}{chr((magic>>24)&0xff)})")
    print(f"Inodes:             {inodes}")
    print(f"Block Size:         {block_size} bytes (log2: {block_log})")
    print(f"Fragments:          {fragments}")
    print(f"Compression:        {compression} (XZ/LZMA2 with custom Tenda container)")
    print(f"Total Bytes Used:   {bytes_used} (0x{bytes_used:X} bytes, {bytes_used/(1024*1024):.2f} MB)")
    print(f"SquashFS Span:      0x{sq_start:06X} - 0x{sq_start+bytes_used:06X}")
    print("=" * 70)

    # Scan blocks
    pos = sq_start
    sq_end = sq_start + bytes_used
    blocks = []

    while True:
        idx = data.find(b"Tenda\x00", pos)
        if idx == -1 or idx >= sq_end:
            break
        
        # Block Header
        bh_offset = idx + 12
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
            "flash_offset": idx,
            "rel_offset": idx - sq_start,
            "bh_size": bh_size,
            "payload_start": payload_start,
            "comp_size": comp_size,
            "uncomp_size": uncomp_size
        })
        pos = payload_start + comp_size

    print(f"Identified {len(blocks)} custom Tenda compressed blocks.")

    # Decompress all blocks in memory to verify 100% integrity
    total_uncompressed = 0
    corrupt_count = 0
    for b in blocks:
        payload = data[b["payload_start"] : b["payload_start"] + b["comp_size"]]
        decomp = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA2, "dict_size": 131072}])
        try:
            out = decomp.decompress(payload)
            if len(out) != b["uncomp_size"]:
                print(f"Size mismatch in block #{b['idx']}: got {len(out)}, expected {b['uncomp_size']}")
                corrupt_count += 1
            total_uncompressed += len(out)
        except Exception as e:
            print(f"Decompression error in block #{b['idx']}: {e}")
            corrupt_count += 1

    print(f"Decompression Verification Complete:")
    print(f"  Valid blocks:      {len(blocks) - corrupt_count} / {len(blocks)} ({100.0 * (len(blocks) - corrupt_count) / len(blocks):.1f}%)")
    print(f"  Total Uncompressed Data: {total_uncompressed:,} bytes ({total_uncompressed/(1024*1024):.2f} MB)")
    print(f"  Compression Ratio: {bytes_used / total_uncompressed:.2f}x ({100.0 * bytes_used / total_uncompressed:.1f}%)")
    return corrupt_count == 0

if __name__ == "__main__":
    extract_and_verify(FLASH_PATH)
