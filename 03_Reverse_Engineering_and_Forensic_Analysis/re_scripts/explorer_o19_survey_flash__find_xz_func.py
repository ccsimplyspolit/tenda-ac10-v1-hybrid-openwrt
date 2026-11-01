FLASH_PATH = r"C:\Users\sshunko\.gemini\antigravity\brain\21647d8e-3d9c-493f-900f-f13429d32667\scratch\vmlinux_stock.bin"

with open(FLASH_PATH, "rb") as f:
    kdata = f.read()

import struct

# Find function start before 0x8015CD04
target_va = 0x8015CD04
for va in range(target_va, target_va - 0x1000, -4):
    file_off = va - 0x80000000
    instr, = struct.unpack("<I", kdata[file_off:file_off+4])
    # check for standard MIPS prologue: addiu sp, sp, -imm
    if (instr >> 16) == 0x27BD and (instr & 0x8000):
        print(f"Function starts at 0x{va:08X} (offset 0x{file_off:08X}) with frame size {- (instr & 0xFFFF - 0x10000)} bytes!")
        start_va = va
        break

# Let's inspect the entire function logic
print(f"\n--- Disassembling function from 0x{start_va:08X} to 0x{target_va+0x100:08X} ---")
from disasm_tenda_decomp import disasm_range
disasm_range(start_va, (target_va + 0x100 - start_va) // 4)
