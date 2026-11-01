import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from explorer_driver_hwnat_re__re_disasm import load_environment, resolve_symbol, disassemble_range

data, symbols, sym_list = load_environment()
print("=== _vlan_setting / RTL83XX_vlan_init (0x80207520 - 0x80207750) ===")
print(disassemble_range(data, sym_list, 0x80207520, max_instructions=130))
