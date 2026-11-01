def parse_hex_array(s):
    # s is a string of hex pairs like "1A1A1A..."
    return [int(s[i:i+2], 16) for i in range(0, len(s), 2)]

# Load parsed entries from parse_mtd1.py
entries = {}
with open("mtd1_factory_calibration.bin", "rb") as f:
    raw = f.read()

lines = raw[8:].split(b"\n")
for l in lines:
    if b"=" in l:
        k, v = l.decode("ascii", errors="ignore").split("=", 1)
        entries[k] = v

print("=== RF CALIBRATION DETAILED DISSECTION ===")

# 1. 2.4 GHz (WLAN1 - RTL8197F SoC integrated)
print("\n--- 2.4 GHz (WLAN1 - RTL8197F) ---")
# Channels in 2.4 GHz: 1 to 14 (14 channels total)
cck_a = parse_hex_array(entries['HW_WLAN1_TX_POWER_CCK_A'])
cck_b = parse_hex_array(entries['HW_WLAN1_TX_POWER_CCK_B'])
ht40_a = parse_hex_array(entries['HW_WLAN1_TX_POWER_HT40_1S_A'])
ht40_b = parse_hex_array(entries['HW_WLAN1_TX_POWER_HT40_1S_B'])

print(f"CCK Path A (len={len(cck_a)}):  {[hex(x) for x in cck_a]} -> Decimal: {cck_a}")
print(f"CCK Path B (len={len(cck_b)}):  {[hex(x) for x in cck_b]} -> Decimal: {cck_b}")
print(f"HT40 1S Path A (len={len(ht40_a)}): {[hex(x) for x in ht40_a]} -> Decimal: {ht40_a}")
print(f"HT40 1S Path B (len={len(ht40_b)}): {[hex(x) for x in ht40_b]} -> Decimal: {ht40_b}")

# Notice len(cck_a) = 14! Exactly 14 channels (Ch 1 to 14)!
# Notice len(ht40_a) = 14! Exactly 14 channels (Ch 1 to 14)!
for ch in range(1, 15):
    print(f"  Ch {ch:02d}: CCK_A={cck_a[ch-1]:2d} (0x{cck_a[ch-1]:02X}), CCK_B={cck_b[ch-1]:2d} (0x{cck_b[ch-1]:02X}) | HT40_A={ht40_a[ch-1]:2d} (0x{ht40_a[ch-1]:02X}), HT40_B={ht40_b[ch-1]:2d} (0x{ht40_b[ch-1]:02X})")

# TX Power differences:
diff_ht20 = parse_hex_array(entries['HW_WLAN1_TX_POWER_DIFF_HT20'])
diff_ofdm = parse_hex_array(entries['HW_WLAN1_TX_POWER_DIFF_OFDM'])
diff_ht40_2s = parse_hex_array(entries['HW_WLAN1_TX_POWER_DIFF_HT40_2S'])
print(f"DIFF_HT20 (len={len(diff_ht20)}): {diff_ht20}")
print(f"DIFF_OFDM (len={len(diff_ofdm)}): {diff_ofdm}")
print(f"DIFF_HT40_2S (len={len(diff_ht40_2s)}): {diff_ht40_2s}")

# Crystal cap & Thermal sensor:
print(f"XCAP: {entries['HW_WLAN1_11N_XCAP']} (0x{int(entries['HW_WLAN1_11N_XCAP']):02X} = 46)")
print(f"THER (Thermal sensor meter): {entries['HW_WLAN1_11N_THER']} (0x{int(entries['HW_WLAN1_11N_THER']):02X} = 32)")

# 2. 5 GHz (WLAN0 - RTL8822BE PCIe)
print("\n--- 5 GHz (WLAN0 - RTL8822BE) ---")
ht40_5g_a = parse_hex_array(entries['HW_WLAN0_TX_POWER_5G_HT40_1S_A'])
ht40_5g_b = parse_hex_array(entries['HW_WLAN0_TX_POWER_5G_HT40_1S_B'])
print(f"5G HT40 Path A total bytes: {len(ht40_5g_a)}")
print(f"5G HT40 Path B total bytes: {len(ht40_5g_b)}")

# Let's inspect where non-zero power values occur in 5GHz table
non_zero_a = [(idx, val) for idx, val in enumerate(ht40_5g_a) if val != 0]
non_zero_b = [(idx, val) for idx, val in enumerate(ht40_5g_b) if val != 0]
print(f"Non-zero power entries in Path A: {len(non_zero_a)} entries (range idx {non_zero_a[0][0]} to {non_zero_a[-1][0]})")
print(f"Non-zero power entries in Path B: {len(non_zero_b)} entries (range idx {non_zero_b[0][0]} to {non_zero_b[-1][0]})")

# Print unique values and ranges
from itertools import groupby
print("Path A power segments:")
for k, g in groupby(enumerate(ht40_5g_a), key=lambda x: x[1]):
    items = list(g)
    print(f"  Indices {items[0][0]:3d}..{items[-1][0]:3d} ({len(items):3d} entries): value = 0x{k:02X} ({k} dBm/step)")

print("Path B power segments:")
for k, g in groupby(enumerate(ht40_5g_b), key=lambda x: x[1]):
    items = list(g)
    print(f"  Indices {items[0][0]:3d}..{items[-1][0]:3d} ({len(items):3d} entries): value = 0x{k:02X} ({k} dBm/step)")

# Differences for 5G
diff_5g_40_20_a = parse_hex_array(entries['HW_WLAN0_TX_POWER_DIFF_5G_40BW2S_20BW2S_A'])
diff_5g_40_20_b = parse_hex_array(entries['HW_WLAN0_TX_POWER_DIFF_5G_40BW2S_20BW2S_B'])
diff_5g_ofdm_a = parse_hex_array(entries['HW_WLAN0_TX_POWER_DIFF_5G_20BW1S_OFDM1T_A'])
diff_5g_ofdm_b = parse_hex_array(entries['HW_WLAN0_TX_POWER_DIFF_5G_20BW1S_OFDM1T_B'])
print(f"DIFF_5G_40BW2S_20BW2S_A (len={len(diff_5g_40_20_a)}): {diff_5g_40_20_a}")
print(f"DIFF_5G_40BW2S_20BW2S_B (len={len(diff_5g_40_20_b)}): {diff_5g_40_20_b}")
print(f"DIFF_5G_20BW1S_OFDM1T_A (len={len(diff_5g_ofdm_a)}): {diff_5g_ofdm_a}")
print(f"DIFF_5G_20BW1S_OFDM1T_B (len={len(diff_5g_ofdm_b)}): {diff_5g_ofdm_b}")

print(f"5G XCAP: {entries['HW_WLAN0_11N_XCAP']} (0x{int(entries['HW_WLAN0_11N_XCAP']):02X} = 27)")
print(f"5G THER: {entries['HW_WLAN0_11N_THER']} (0x{int(entries['HW_WLAN0_11N_THER']):02X} = 25)")
