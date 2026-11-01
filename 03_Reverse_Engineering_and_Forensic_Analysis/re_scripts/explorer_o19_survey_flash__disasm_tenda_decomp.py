from explorer_driver_hwnat_re__re_disasm import load_kernel_bytes as _load_vmlinux_stock

    kdata = _load_vmlinux_stock()

import struct

def disasm_range(start_va, count=64):
    file_off = start_va - 0x80000000
    for i in range(0, count * 4, 4):
        va = start_va + i
        instr, = struct.unpack("<I", kdata[file_off+i:file_off+i+4])
        op = (instr >> 26) & 0x3F
        rs = (instr >> 21) & 0x1F
        rt = (instr >> 16) & 0x1F
        rd = (instr >> 11) & 0x1F
        imm = instr & 0xFFFF
        simm = imm - 0x10000 if imm >= 0x8000 else imm
        
        reg_names = [
            "zero", "at", "v0", "v1", "a0", "a1", "a2", "a3",
            "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
            "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7",
            "t8", "t9", "k0", "k1", "gp", "sp", "fp", "ra"
        ]
        r_rs = reg_names[rs]
        r_rt = reg_names[rt]
        r_rd = reg_names[rd]
        
        name = f"0x{op:02X}"
        args = f"{r_rs}, {r_rt}, {simm}"
        
        if op == 0x00: # SPECIAL
            f_code = instr & 0x3F
            shamt = (instr >> 6) & 0x1F
            if f_code == 0x00:
                if instr == 0: name = "nop"; args = ""
                else: name = "sll"; args = f"{r_rd}, {r_rt}, {shamt}"
            elif f_code == 0x02: name = "srl"; args = f"{r_rd}, {r_rt}, {shamt}"
            elif f_code == 0x03: name = "sra"; args = f"{r_rd}, {r_rt}, {shamt}"
            elif f_code == 0x08: name = "jr"; args = f"{r_rs}"
            elif f_code == 0x09: name = "jalr"; args = f"{r_rd}, {r_rs}"
            elif f_code == 0x20: name = "add"; args = f"{r_rd}, {r_rs}, {r_rt}"
            elif f_code == 0x21: name = "addu"; args = f"{r_rd}, {r_rs}, {r_rt}"
            elif f_code == 0x23: name = "subu"; args = f"{r_rd}, {r_rs}, {r_rt}"
            elif f_code == 0x24: name = "and"; args = f"{r_rd}, {r_rs}, {r_rt}"
            elif f_code == 0x25: name = "or"; args = f"{r_rd}, {r_rs}, {r_rt}"
            elif f_code == 0x26: name = "xor"; args = f"{r_rd}, {r_rs}, {r_rt}"
            elif f_code == 0x2A: name = "slt"; args = f"{r_rd}, {r_rs}, {r_rt}"
            elif f_code == 0x2B: name = "sltu"; args = f"{r_rd}, {r_rs}, {r_rt}"
            else: name = f"spec_{f_code:02X}"
        elif op == 0x02: name = "j"; args = f"0x{(instr & 0x3FFFFFF) << 2:08X}"
        elif op == 0x03: name = "jal"; args = f"0x{0x80000000 | ((instr & 0x3FFFFFF) << 2):08X}"
        elif op == 0x04: name = "beq"; args = f"{r_rs}, {r_rt}, 0x{va + 4 + (simm << 2):08X}"
        elif op == 0x05: name = "bne"; args = f"{r_rs}, {r_rt}, 0x{va + 4 + (simm << 2):08X}"
        elif op == 0x09: name = "addiu"; args = f"{r_rt}, {r_rs}, {simm}"
        elif op == 0x0C: name = "andi"; args = f"{r_rt}, {r_rs}, 0x{imm:04X}"
        elif op == 0x0D: name = "ori"; args = f"{r_rt}, {r_rs}, 0x{imm:04X}"
        elif op == 0x0F: name = "lui"; args = f"{r_rt}, 0x{imm:04X}"
        elif op == 0x20: name = "lb"; args = f"{r_rt}, {simm}({r_rs})"
        elif op == 0x21: name = "lh"; args = f"{r_rt}, {simm}({r_rs})"
        elif op == 0x23: name = "lw"; args = f"{r_rt}, {simm}({r_rs})"
        elif op == 0x24: name = "lbu"; args = f"{r_rt}, {simm}({r_rs})"
        elif op == 0x25: name = "lhu"; args = f"{r_rt}, {simm}({r_rs})"
        elif op == 0x28: name = "sb"; args = f"{r_rt}, {simm}({r_rs})"
        elif op == 0x29: name = "sh"; args = f"{r_rt}, {simm}({r_rs})"
        elif op == 0x2B: name = "sw"; args = f"{r_rt}, {simm}({r_rs})"
        
        print(f"  0x{va:08X}: {instr:08X}  {name:<8} {args}")

print("--- Function around 0x8015CD04 ---")
disasm_range(0x8015CCD0, 50)
