import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from explorer_driver_hwnat_re__re_disasm import load_environment, resolve_symbol, disassemble_range
import capstone

data, symbols, sym_list = load_environment()
md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)

print("=== RTL8367R_init_switch_mode (0x80208574 - 0x802087dc) ===")
print(disassemble_range(data, sym_list, 0x80208574, max_instructions=110))
