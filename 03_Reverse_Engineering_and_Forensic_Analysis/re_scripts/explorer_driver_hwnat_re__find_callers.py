import capstone
from re_disasm import load_environment, resolve_symbol

data, symbols, sym_list = load_environment()
md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)
md.detail = True

def find_callers_of(func_va):
    callers = []
    for off in range(0, len(data), 4):
        va = 0x80000000 + off
        w = int.from_bytes(data[off:off+4], 'little')
        op = w >> 26
        if op == 0x03: # jal
            target = (0x80000000 & 0xf0000000) | ((w & 0x03ffffff) << 2)
            if target == func_va:
                sym = resolve_symbol(va, sym_list)
                callers.append((va, sym))
    return callers

funcs = [
    ("rtl8651_setAsicNaptTcpUdpTable", 0x8046aa74),
    ("rtl8651_setAsicRouting", 0x804689b8),
    ("rtl8651_setAsicNextHopTable", 0x8046a364),
    ("rtl8651_setAsicArp", 0x804692dc),
    ("rtl8651_setAsicExtIntIpTable", 0x80467c9c),
    ("rtl865x_handle_nat", 0x8047e040),
]

for name, va in funcs:
    callers = find_callers_of(va)
    print(f"\nCallers of {name} (0x{va:08x}): {len(callers)}")
    for c_va, c_sym in callers:
        print(f"  0x{c_va:08x} in {c_sym}")
