import os
import sys

sym_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "01_Stock_Firmware_and_Partitions", "kallsyms_stock_31434.txt"))
with open(sym_path, 'r') as f:
    lines = [l.strip().split() for l in f if len(l.strip().split()) >= 3]

queries = ['init_sw', 'efuse', 'crystal', 'thermal', 'txpwr', 'tx_pwr', 'txpower', 'tx_power', '8192cd', 'set_mib', 'rfe', 'xcap']
for q in queries:
    matches = [l for l in lines if q in l[2].lower()]
    print(f'=== Query "{q}": {len(matches)} matches ===')
    for m in matches[:15]:
        print(f'  {m[0]} {m[1]} {m[2]}')
