import sys
sys.path.insert(0, r"K:\aoe4_dlc\.agents\teamwork\explorer_driver_hwnat_re")
from re_disasm import load_environment, resolve_symbol, disassemble_range

data, symbols, sym_list = load_environment()

def find_sym(name):
    for a, n in sym_list:
        if n == name:
            return a
    return None

for name in [
    "rtk_port_macForceLinkExt0_get",
    "rtk_port_macForceLinkExt0_set",
    "rtl8367b_getAsicPortStatus",
    "RTL8367R_init_switch_mode",
    "display_8367r_port_stat"
]:
    addr = find_sym(name)
    if addr:
        print(f"\n=== Disassembly of {name} at 0x{addr:08x} ===")
        print(disassemble_range(data, sym_list, addr, max_instructions=50))
    else:
        print(f"[-] {name} not found in symbols")
