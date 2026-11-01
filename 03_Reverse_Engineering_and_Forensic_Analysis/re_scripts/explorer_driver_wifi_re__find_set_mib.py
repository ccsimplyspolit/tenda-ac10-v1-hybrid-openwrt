import sys
import re_tool

target = 0x80316914
target_bytes = target.to_bytes(4, 'little')
target_jal = (0x0c000000 | ((target & 0x0fffffff) >> 2)).to_bytes(4, 'little')

re_tool.f_bin.seek(0)
data = re_tool.f_bin.read()

print('Searching for pointer to set_mib_default_tbl:')
idx = 0
while True:
    idx = data.find(target_bytes, idx)
    if idx == -1: break
    va = re_tool.LOAD_BASE + idx
    sym = re_tool.addr2sym.get(va, 'unknown')
    print(f'  Found pointer at 0x{va:08x} ({sym})')
    idx += 4

print('Searching for JAL to set_mib_default_tbl:')
idx = 0
while True:
    idx = data.find(target_jal, idx)
    if idx == -1: break
    va = re_tool.LOAD_BASE + idx
    sym = re_tool.addr2sym.get(va, 'unknown')
    print(f'  Found JAL at 0x{va:08x} ({sym})')
    idx += 4

print('Searching for string set_mib:')
idx = 0
while True:
    idx = data.find(b'set_mib', idx)
    if idx == -1: break
    va = re_tool.LOAD_BASE + idx
    sym = re_tool.addr2sym.get(va, 'unknown')
    print(f'  Found set_mib at 0x{va:08x} ({sym})')
    idx += 7
