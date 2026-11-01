import sys
sys.path.insert(0, r"K:\aoe4_dlc\.agents\teamwork\explorer_driver_hwnat_re")
from re_disasm import load_environment, resolve_symbol, disassemble_range

data, symbols, sym_list = load_environment()
print("=== smi_init (0x801d7bbc) ===")
print(disassemble_range(data, sym_list, 0x801d7bbc, max_instructions=50))

print("\n=== rtl819x_8367r_i2c_pin_probe (0x801df8ec) ===")
print(disassemble_range(data, sym_list, 0x801df8ec, max_instructions=60))
