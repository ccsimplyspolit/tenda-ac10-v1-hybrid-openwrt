import sys
sys.path.insert(0, r"K:\aoe4_dlc\.agents\teamwork\explorer_driver_hwnat_re")
from re_disasm import load_environment, resolve_symbol
import capstone
import struct

data, symbols, sym_list = load_environment()
md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)

print("Scanning for ASIC registers at base 0xbb800000...")
reg_targets = {
    0x4000: "MACCR",
    0x4004: "MACCR1 / PORT0_ROUTER_MODE",
    0x4008: "SWTCR0",
    0x400c: "SWTCR1 (EnL4WayH, L4EnHash1)",
    0x4010: "FFCR (Flooding Control)",
    0x4050: "TEACR (L2 Aging)",
    0x4200: "MEMCR",
    0x4418: "TLU_CTRL",
    0x4428: "TLU_STATUS",
    0x4d00: "TABLE_ACCESS_CTRL",
    0x4d04: "TABLE_STATUS",
    0x4d08: "TABLE_ADDR",
    0x4d20: "TABLE_DATA0",
    0x5138: "PAD_CTRL (GPIO 18/19 pinmux)",
}

for off in range(0, len(data)-8, 4):
    va = 0x80000000 + off
    w = struct.unpack('<I', data[off:off+4])[0]
    if (w >> 16) & 0xffff in [0x3c01, 0x3c02, 0x3c03, 0x3c04, 0x3c05, 0x3c06, 0x3c07] and (w & 0xffff) == 0xbb80:
        code = data[off:off+28]
        for insn in md.disasm(code, va):
            for reg, rname in reg_targets.items():
                if f"0x{reg:x}" in insn.op_str:
                    sym = resolve_symbol(insn.address, sym_list)
                    print(f"  0x{insn.address:08x}: {insn.mnemonic:<6} {insn.op_str:<25} ({rname} 0xbb80{reg:04x}) in {sym}")
