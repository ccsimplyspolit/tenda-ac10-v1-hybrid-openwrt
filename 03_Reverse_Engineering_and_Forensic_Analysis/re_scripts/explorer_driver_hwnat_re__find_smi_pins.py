import sys
sys.path.insert(0, r"K:\aoe4_dlc\.agents\teamwork\explorer_driver_hwnat_re")
from re_disasm import load_environment, resolve_symbol
import struct
import capstone

data, symbols, sym_list = load_environment()
md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)

print("Searching for accesses to smi_SCK (0x80c22984), smi_SDA (0x80c22988), smi_RST (0x80c22990)...")
for off in range(0, len(data)-8, 4):
    va = 0x80000000 + off
    w = struct.unpack('<I', data[off:off+4])[0]
    if (w >> 16) & 0xffff in [0x3c01, 0x3c02, 0x3c03, 0x3c04, 0x3c05, 0x3c06, 0x3c07, 0x3c08] and (w & 0xffff) == 0x80c2:
        code = data[off:off+36]
        for insn in md.disasm(code, va):
            for target_addr, name in [(0x80c22984, "smi_SCK"), (0x80c22988, "smi_SDA"), (0x80c22990, "smi_RST")]:
                offset = target_addr - 0x80c20000
                if f"0x{offset:x}" in insn.op_str:
                    sym = resolve_symbol(insn.address, sym_list)
                    print(f"  0x{insn.address:08x}: {insn.mnemonic:<6} {insn.op_str:<25} ({name}) in {sym}")
