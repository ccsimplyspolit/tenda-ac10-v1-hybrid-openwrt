import os
import struct

SYMBOLS_TXT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "01_Stock_Firmware_and_Partitions", "kallsyms_stock_31434.txt"))

def main():
    syms = []
    with open(SYMBOLS_TXT, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(maxsplit=2)
            addr = int(parts[0], 16)
            syms.append((addr, parts[1], parts[2]))

    print(f"Total symbols: {len(syms)}")

    # 1. Look for fastpath / fwdEngine / hwnat symbols
    print("\n--- fastpath / fwdEngine / hwnat symbols ---")
    for addr, stype, name in syms:
        nl = name.lower()
        if any(k in nl for k in ["fastpath", "fwdengine", "hwnat", "asic_napt", "rtl_nat", "rtl865x_nat"]):
            print(f"  0x{addr:08x} {stype} {name}")

    # 2. Look for netfilter / conntrack hook symbols
    print("\n--- Netfilter / Conntrack Hook symbols ---")
    for addr, stype, name in syms:
        nl = name.lower()
        if any(k in nl for k in ["conntrack", "nf_conn", "netfilter", "ip_conntrack"]) and any(k in nl for k in ["rtl", "hook", "fast", "nat", "ext", "event"]):
            print(f"  0x{addr:08x} {stype} {name}")

    # 3. Look for ASIC table configuration functions
    print("\n--- ASIC Table / Register configuration functions ---")
    for addr, stype, name in syms:
        nl = name.lower()
        if ("rtl8651_" in nl or "rtl865x_" in nl) and any(k in nl for k in ["napt", "table", "asic", "reg", "route", "flow", "entry"]):
            print(f"  0x{addr:08x} {stype} {name}")

if __name__ == "__main__":
    main()
