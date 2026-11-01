FLASH_PATH = r"/workspace/analysis\21647d8e-3d9c-493f-900f-f13429d32667\scratch\Tenda_AC10_V1_FullFlash_8MB.bin"

with open(FLASH_PATH, "rb") as f:
    data = f.read()

# Break into 64KB erase blocks (128 blocks for 8MB flash)
print("=== 64KB ERASE BLOCK MAP (0x000000 to 0x800000) ===")
print("Block  Offset Range           Status / Description")
print("-" * 65)

for b_idx in range(128):
    start = b_idx * 0x10000
    end = start + 0x10000
    chunk = data[start:end]
    all_ff = (chunk == b"\xff" * 0x10000)
    all_00 = (chunk == b"\x00" * 0x10000)
    
    desc = ""
    if start == 0x000000:
        desc = "Booter (RTL8197F Realtek Bootloader)"
    elif start == 0x010000:
        desc = "Booter (cont.)"
    elif start == 0x020000:
        desc = "mtd1: Factory RF Calibration / HW_SETTING"
    elif start == 0x030000:
        desc = "mtd2: Linux Kernel (cr6c header)"
    elif 0x040000 <= start < 0x230000:
        desc = "mtd2: Linux Kernel payload (compressed)"
    elif start == 0x230000:
        desc = "mtd2 Kernel end (0x23BC12) / mtd3 SquashFS start (0x23BC12)"
    elif 0x240000 <= start < 0x760000:
        desc = "mtd3: SquashFS Rootfs payload"
    elif start == 0x760000:
        desc = "mtd3: SquashFS metadata tables & end (0x76BD76)"
    elif start == 0x7E0000:
        desc = "mtd4: CFM Primary NVRAM (sys_config)"
    elif start == 0x7F0000:
        desc = "mtd5: CFM Backup NVRAM (sys_config)"
    
    if all_ff:
        status = "EMPTY (0xFF)"
    elif all_00:
        status = "ZERO PADDING (0x00)"
    else:
        non_pad = sum(1 for b in chunk if b != 0xff and b != 0x00)
        status = f"DATA ({non_pad} bytes)"
        
    if desc or not all_ff and not all_00:
        print(f"#{b_idx:03d}   0x{start:06X} - 0x{end:06X}   {status:<24} | {desc}")
