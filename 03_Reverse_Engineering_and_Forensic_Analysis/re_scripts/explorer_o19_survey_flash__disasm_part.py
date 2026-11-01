from explorer_driver_hwnat_re__re_disasm import load_kernel_bytes as _load_vmlinux_stock

    kdata = _load_vmlinux_stock()

# Offset 0x0049E28C in binary is virtual address 0x8049E28C
# Let's inspect the code around 0x0049E100 to 0x0049E600
code_chunk = kdata[0x0049E100:0x0049E600]

# Simple MIPS disassembler helper or raw instructions
import struct

def disasm_mips(data, base_va):
    for i in range(0, len(data), 4):
        instr, = struct.unpack("<I", data[i:i+4])
        va = base_va + i
        op = (instr >> 26) & 0x3F
        rs = (instr >> 21) & 0x1F
        rt = (instr >> 16) & 0x1F
        rd = (instr >> 11) & 0x1F
        imm = instr & 0xFFFF
        if imm >= 0x8000:
            simm = imm - 0x10000
        else:
            simm = imm
        
        # Identify common instructions
        name = f"0x{op:02X}"
        args = f"r{rs}, r{rt}, {simm}"
        if op == 0x00: # SPECIAL
            funct = instr & 0x3F
            if funct == 0x08: name = "jr"; args = f"r{rs}"
            elif funct == 0x09: name = "jalr"; args = f"r{rd}, r{rs}"
            elif funct == 0x21: name = "addu"; args = f"r{rd}, r{rs}, r{rt}"
            elif funct == 0x23: name = "subu"; args = f"r{rd}, r{rs}, r{rt}"
            else: name = f"spec_{funct:02X}"
        elif op == 0x02: name = "j"; args = f"0x{(instr & 0x3FFFFFF) << 2:08X}"
        elif op == 0x03: name = "jal"; args = f"0x{0x80000000 | ((instr & 0x3FFFFFF) << 2):08X}"
        elif op == 0x04: name = "beq"; args = f"r{rs}, r{rt}, 0x{va + 4 + (simm << 2):08X}"
        elif op == 0x05: name = "bne"; args = f"r{rs}, r{rt}, 0x{va + 4 + (simm << 2):08X}"
        elif op == 0x08: name = "addi"; args = f"r{rt}, r{rs}, {simm}"
        elif op == 0x09: name = "addiu"; args = f"r{rt}, r{rs}, {simm}"
        elif op == 0x0F: name = "lui"; args = f"r{rt}, 0x{imm:04X}"
        elif op == 0x23: name = "lw"; args = f"r{rt}, {simm}(r{rs})"
        elif op == 0x2B: name = "sw"; args = f"r{rt}, {simm}(r{rs})"

        print(f"  0x{va:08X}: {instr:08X}  {name:<8} {args}")

print("Disassembly around rtkxxpart registration:")
disasm_mips(code_chunk[:256], 0x8049E100)
