import struct

KERNEL_BIN = r"/workspace/analysis\21647d8e-3d9c-493f-900f-f13429d32667\scratch\vmlinux_stock.bin"
SYMBOLS_TXT = r"k:\aoe4_dlc\.agents\teamwork\explorer_o19_survey_kernel\vmlinux_symbols.txt"

def main():
    syms = []
    with open(SYMBOLS_TXT, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(maxsplit=2)
            addr = int(parts[0], 16)
            syms.append((addr, parts[1], parts[2]))

    print("\n--- rtl8367 symbols ---")
    for addr, stype, name in syms:
        nl = name.lower()
        if "8367" in nl:
            print(f"  0x{addr:08x} {stype} {name}")

    print("\n--- SMI / MDIO / Switch GPIO symbols ---")
    for addr, stype, name in syms:
        nl = name.lower()
        if any(k in nl for k in ["smi", "sck", "sda", "switch_init", "switch_probe", "rtl_switch", "rtk_switch", "sw_init"]):
            print(f"  0x{addr:08x} {stype} {name}")

if __name__ == "__main__":
    main()
