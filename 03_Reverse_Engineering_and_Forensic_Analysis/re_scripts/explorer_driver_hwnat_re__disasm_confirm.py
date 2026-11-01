import sys
sys.path.insert(0, r"K:\aoe4_dlc\.agents\teamwork\explorer_driver_hwnat_re")
from re_disasm import load_environment, resolve_symbol, disassemble_range

data, symbols, sym_list = load_environment()
print("=== Disassembly of rtl_nf_conntrack_confirm_hooks (0x8047e7b0) ===")
print(disassemble_range(data, sym_list, 0x8047e7b0, max_instructions=35))

print("\n=== Disassembly of __nf_conntrack_confirm (0x803d8f08) ===")
print(disassemble_range(data, sym_list, 0x803d8f08, max_instructions=50))
