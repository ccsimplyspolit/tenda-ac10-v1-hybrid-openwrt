import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from explorer_driver_hwnat_re__re_disasm import load_environment, resolve_symbol, disassemble_range

data, symbols, sym_list = load_environment()
# 0x8046e9a0 - 0x8046e7c0 = 0x1e0 = 480 bytes = 120 instructions
print(disassemble_range(data, sym_list, 0x8046e7c0, max_instructions=125))
