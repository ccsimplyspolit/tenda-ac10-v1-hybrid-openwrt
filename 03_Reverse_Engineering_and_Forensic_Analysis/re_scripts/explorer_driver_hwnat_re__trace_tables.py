import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from explorer_driver_hwnat_re__re_disasm import load_environment, resolve_symbol
import capstone

data, symbols, sym_list = load_environment()
md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
md.detail = True

funcs = [
    ("rtl8651_setAsicNaptTcpUdpTable", 0x801e5620),
    ("rtl8651_setAsicRouting", 0x801e3e8c),
    ("rtl8651_setAsicNextHopTable", 0x801e40bc),
    ("rtl8651_setAsicArp", 0x801e3ae8),
    ("rtl8651_setAsicExtIntIpTable", 0x801e4274),
    ("rtl8651_setAsicPppoe", 0x801e4154),
    ("rtl8651_setAsicVlan", 0x801dad24),
    ("rtl8651_setAsicNetInterface", 0x801db224),
    ("rtl8651_setAsicL2Table", 0x801e0d1c),
]

for name, va in funcs:
    code = data[va - 0x80000000 : va - 0x80000000 + 400]
    table_types = []
    calls = []
    for insn in md.disasm(code, va):
        if insn.mnemonic == 'jal':
            t = insn.operands[0].imm
            sym = resolve_symbol(t, sym_list)
            calls.append((insn.address, sym))
        if insn.mnemonic == 'addiu' and insn.op_str.startswith('$a0, $zero, '):
            val = int(insn.op_str.split()[-1], 0)
            table_types.append((insn.address, val))
    print(f"{name} (0x{va:08x}):")
    print("  Table types:", [(hex(a), f"0x{v:02x}") for a, v in table_types])
    print("  JAL calls:", [(hex(a), s) for a, s in calls[:6]])
