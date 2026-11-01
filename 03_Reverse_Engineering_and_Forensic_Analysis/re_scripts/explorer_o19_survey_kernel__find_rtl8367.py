import os
import struct

from explorer_driver_hwnat_re__re_disasm import load_kernel_bytes as _load_vmlinux_stock
SYMBOLS_TXT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "01_Stock_Firmware_and_Partitions", "kallsyms_stock_31434.txt"))

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
