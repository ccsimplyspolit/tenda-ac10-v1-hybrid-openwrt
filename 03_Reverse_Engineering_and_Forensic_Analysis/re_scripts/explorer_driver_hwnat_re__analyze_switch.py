import sys
sys.path.insert(0, r"K:\aoe4_dlc\.agents\teamwork\explorer_driver_hwnat_re")
import capstone
from re_disasm import load_environment, resolve_symbol, disassemble_range

data, symbols, sym_list = load_environment()
md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
md.detail = True

def disassemble_func(addr, count=60):
    sym = resolve_symbol(addr, sym_list)
    print(f"\n=======================================================")
    print(f"Disassembly of {sym} at 0x{addr:08x} ({count} instructions):")
    print(f"=======================================================")
    start_off = addr - 0x80000000
    code = data[start_off:start_off + count * 4]
    c = 0
    for insn in md.disasm(code, addr):
        extra = ""
        for op in insn.operands:
            if op.type == capstone.mips.MIPS_OP_IMM:
                target = op.imm
                if target >= 0x80000000:
                    extra += f" ; {resolve_symbol(target, sym_list)}"
                elif target > 0x1000:
                    extra += f" ; 0x{target:x}"
        line = f"0x{insn.address:08x}:  {insn.bytes.hex()}   {insn.mnemonic:<8} {insn.op_str:<30} {extra}"
        print(line)
        c += 1
        if c >= count:
            break

# Disassemble plat_spi_init
disassemble_func(0x806c0024, 70)

# Disassemble smi_init
disassemble_func(0x801d7bbc, 60)

# Disassemble rtl819x_8367r_i2c_pin_probe
disassemble_func(0x801df8ec, 70)

# Disassemble RTL83XX_vlan_init
disassemble_func(0x80208b50, 80)
