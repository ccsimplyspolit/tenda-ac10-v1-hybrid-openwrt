import sys

sym_path = r'K:\aoe4_dlc\.agents\teamwork\explorer_o19_survey_kernel\vmlinux_symbols.txt'
with open(sym_path, 'r') as f:
    lines = [l.strip().split() for l in f if len(l.strip().split()) >= 3]

queries = ['init_sw', 'efuse', 'crystal', 'thermal', 'txpwr', 'tx_pwr', 'txpower', 'tx_power', '8192cd', 'set_mib', 'rfe', 'xcap']
for q in queries:
    matches = [l for l in lines if q in l[2].lower()]
    print(f'=== Query "{q}": {len(matches)} matches ===')
    for m in matches[:15]:
        print(f'  {m[0]} {m[1]} {m[2]}')
