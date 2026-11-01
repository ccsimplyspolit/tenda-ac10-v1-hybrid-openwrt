import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from explorer_driver_hwnat_re__re_disasm import load_environment, resolve_symbol, disassemble_range

data, symbols, sym_list = load_environment()
# 0x8047e4a8 - 0x8047e040 = 0x468 = 1128 bytes = 282 instructions
print(disassemble_range(data, sym_list, 0x8047e040, max_instructions=285))
