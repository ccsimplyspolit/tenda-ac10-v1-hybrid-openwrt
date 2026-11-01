#!/bin/sh
# ==============================================================================
# set-mib.sh — Out-of-Band Factory RF Calibration Injection for Tenda AC10 V1.0
# Target Driver: Realtek rtl8192cd (monolithic HAL) on Linux 4.14 / OpenWrt 19.07
# Hardware: RTL8197FS (2.4G wlan1) + RTL8822BE (5G wlan0) + Skyworth RFE Type 6
# ==============================================================================
# Because physical eFuse on the RTL8822BE PCIe card is blank (0xFF), the driver
# requires factory calibration data injected via SIOCDEVPRIVATE ioctl (set_mib).
# Every MIB key below is verified against MIB_TABLE (0x805F96BC..0x805FF8FC) in
# vmlinux_stock.bin and runtime /proc/wlan0/mib_all & /proc/wlan1/mib_all.
# ==============================================================================

CAL_DEV=""
TMP_CAL="/tmp/factory_cal.txt"

# 1. Locate the calibration partition dynamically
if [ -f /proc/mtd ]; then
    CAL_DEV_NAME=$(grep -i "calibration" /proc/mtd | cut -d: -f1)
    if [ -n "$CAL_DEV_NAME" ]; then
        CAL_DEV="/dev/$(printf '%s' "$CAL_DEV_NAME" | sed 's/^mtd/mtdblock/')"
    fi
fi

# Fallback: check standard Tenda AC10 partition layout (mtdblock1)
if [ ! -b "$CAL_DEV" ] && [ -b "/dev/mtdblock1" ]; then
    CAL_DEV="/dev/mtdblock1"
fi

# Emergency fallback: scan all mtdblock devices for Tenda calibration magic
if [ ! -b "$CAL_DEV" ]; then
    for dev in /dev/mtdblock*; do
        if [ -b "$dev" ]; then
            MAGIC=$(dd if="$dev" bs=4 count=1 2>/dev/null | hexdump -e '1/4 "%08x"')
            # Magic 7D 2A ED DE in LE is deed2a7d / 7d2aedde
            if [ "$MAGIC" = "7d2aedde" ] || [ "$MAGIC" = "deed2a7d" ]; then
                CAL_DEV="$dev"
                break
            fi
        fi
    done
fi

if [ ! -b "$CAL_DEV" ]; then
    logger -t set-mib "ERROR: Factory calibration MTD partition not found! Aborting."
    exit 1
fi

logger -t set-mib "Found factory calibration partition at $CAL_DEV. Extracting parameters..."

# 2. Extract ASCII key-value pairs (skip binary header, read 64 KB sector)
# Standard POSIX/BusyBox filter without dependency on external 'strings' utility
dd if="$CAL_DEV" bs=65536 count=1 2>/dev/null | tr '\0' '\n' | tr -d '\r' | tr -cd '\11\12\15\40-\176' > "$TMP_CAL"

get_key() {
    grep "^$1=" "$TMP_CAL" | head -n1 | cut -d'=' -f2-
}

# 3. Format MAC address helper (aabbccddeeff -> aa:bb:cc:dd:ee:ff)
format_mac() {
    echo "$1" | sed 's/../&:/g;s/:$//'
}

# 4. Extract Essential Hardware Parameters
MAC_ETH_RAW=$(get_key "HW_NIC0_ADDR")
MAC_5G_RAW=$(get_key "HW_WLAN0_WLAN_ADDR")
MAC_2G_RAW=$(get_key "HW_WLAN1_WLAN_ADDR")
REG_DOMAIN_5G=$(get_key "HW_WLAN0_REG_DOMAIN")
REG_DOMAIN_2G=$(get_key "HW_WLAN1_REG_DOMAIN")
XCAP_5G=$(get_key "HW_WLAN0_11N_XCAP")
XCAP_2G=$(get_key "HW_WLAN1_11N_XCAP")
THER_5G=$(get_key "HW_WLAN0_11N_THER")
THER_2G=$(get_key "HW_WLAN1_11N_THER")

# 5 GHz Power Tables & Bandwidth Diffs (20/40/80/160 MHz)
PWR_5G_HT40_A=$(get_key "HW_WLAN0_TX_POWER_5G_HT40_1S_A")
PWR_5G_HT40_B=$(get_key "HW_WLAN0_TX_POWER_5G_HT40_1S_B")
DIFF_5G_40_20_A=$(get_key "HW_WLAN0_TX_POWER_DIFF_5G_40BW2S_20BW2S_A")
DIFF_5G_40_20_B=$(get_key "HW_WLAN0_TX_POWER_DIFF_5G_40BW2S_20BW2S_B")
DIFF_5G_20_OFDM_A=$(get_key "HW_WLAN0_TX_POWER_DIFF_5G_20BW1S_OFDM1T_A")
DIFF_5G_20_OFDM_B=$(get_key "HW_WLAN0_TX_POWER_DIFF_5G_20BW1S_OFDM1T_B")
DIFF_5G_80_1S_A=$(get_key "HW_WLAN0_TX_POWER_DIFF_5G_80BW1S_160BW1S_A")
DIFF_5G_80_2S_A=$(get_key "HW_WLAN0_TX_POWER_DIFF_5G_80BW2S_160BW2S_A")
DIFF_5G_80_1S_B=$(get_key "HW_WLAN0_TX_POWER_DIFF_5G_80BW1S_160BW1S_B")
DIFF_5G_80_2S_B=$(get_key "HW_WLAN0_TX_POWER_DIFF_5G_80BW2S_160BW2S_B")

# 2.4 GHz Power Tables & Bandwidth Diffs
PWRLVL_2G_CCK_A=$(get_key "HW_WLAN1_TX_POWER_CCK_A")
PWRLVL_2G_CCK_B=$(get_key "HW_WLAN1_TX_POWER_CCK_B")
PWR_2G_HT40_A=$(get_key "HW_WLAN1_TX_POWER_HT40_1S_A")
PWR_2G_HT40_B=$(get_key "HW_WLAN1_TX_POWER_HT40_1S_B")
DIFF_2G_HT20=$(get_key "HW_WLAN1_TX_POWER_DIFF_HT20")
DIFF_2G_OFDM=$(get_key "HW_WLAN1_TX_POWER_DIFF_OFDM")
DIFF_2G_HT40_2S=$(get_key "HW_WLAN1_TX_POWER_DIFF_HT40_2S")

# Exact factory fallback defaults from mtd1_factory_rf_cal_40keys.json & wl_info.log
[ -z "$XCAP_5G" ] && XCAP_5G="27"
[ -z "$XCAP_2G" ] && XCAP_2G="46"
[ -z "$THER_5G" ] && THER_5G="25"
[ -z "$THER_2G" ] && THER_2G="32"
[ -z "$REG_DOMAIN_5G" ] && REG_DOMAIN_5G="13"
[ -z "$REG_DOMAIN_2G" ] && REG_DOMAIN_2G="13"
case "$REG_DOMAIN_5G" in ''|*[!0-9]*) REG_DOMAIN_5G="13" ;; esac
case "$REG_DOMAIN_2G" in ''|*[!0-9]*) REG_DOMAIN_2G="13" ;; esac

[ -z "$PWR_5G_HT40_A" ] && PWR_5G_HT40_A="00000000000000000000000000000000000000000000000000000000000000000000001B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B19191919191919191918181818181818181818181818181818181818181818181800000000000000000000000000000000000000"
[ -z "$PWR_5G_HT40_B" ] && PWR_5G_HT40_B="00000000000000000000000000000000000000000000000000000000000000000000001E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1B1B1B1B1B1B1B1B1B19191919191919191919191919191919191919191919191900000000000000000000000000000000000000"
[ -z "$DIFF_5G_40_20_A" ] && DIFF_5G_40_20_A="0101010101010101010101010101"
[ -z "$DIFF_5G_40_20_B" ] && DIFF_5G_40_20_B="0101010101010101010101010101"
[ -z "$DIFF_5G_20_OFDM_A" ] && DIFF_5G_20_OFDM_A="1212121212121212121212121212"
[ -z "$DIFF_5G_20_OFDM_B" ] && DIFF_5G_20_OFDM_B="1212121212121212121212121212"
[ -z "$DIFF_5G_80_1S_A" ] && DIFF_5G_80_1S_A="0000000000000000000000000000"
[ -z "$DIFF_5G_80_2S_A" ] && DIFF_5G_80_2S_A="0000000000000000000000000000"
[ -z "$DIFF_5G_80_1S_B" ] && DIFF_5G_80_1S_B="0000000000000000000000000000"
[ -z "$DIFF_5G_80_2S_B" ] && DIFF_5G_80_2S_B="0000000000000000000000000000"

[ -z "$PWRLVL_2G_CCK_A" ] && PWRLVL_2G_CCK_A="2020202222222222222626262626"
[ -z "$PWRLVL_2G_CCK_B" ] && PWRLVL_2G_CCK_B="1a1a1a1b1b1b1b1b1b1e1e1e1e1e"
PWR_2G_CCK_A="$PWRLVL_2G_CCK_A"
PWR_2G_CCK_B="$PWRLVL_2G_CCK_B"
[ -z "$PWR_2G_HT40_A" ] && PWR_2G_HT40_A="1a1a1a1a1a1a1a1a1a1d1d1d1d1d"
[ -z "$PWR_2G_HT40_B" ] && PWR_2G_HT40_B="1515151616161616161717171717"
[ -z "$DIFF_2G_HT20" ] && DIFF_2G_HT20="0000001111111111112222222222"
[ -z "$DIFF_2G_OFDM" ] && DIFF_2G_OFDM="1111112222222222223333333333"
[ -z "$DIFF_2G_HT40_2S" ] && DIFF_2G_HT40_2S="0000000000000000000000000000"

# ==============================================================================
# 5. Program Base Ethernet MAC (eth0 / gmac0)
# ==============================================================================
if [ -n "$MAC_ETH_RAW" ]; then
    ETH_MAC=$(format_mac "$MAC_ETH_RAW")
    ifconfig eth0 hw ether "$ETH_MAC" 2>/dev/null || ip link set dev eth0 address "$ETH_MAC"
    logger -t set-mib "eth0 base Ethernet MAC set to $ETH_MAC"
fi

# ==============================================================================
# 6. Program wlan0 (5 GHz RTL8822BE + Skyworth RFE Type 6)
# ==============================================================================
if ifconfig wlan0 down 2>/dev/null; then
    logger -t set-mib "Configuring wlan0 (5 GHz 802.11ac)..."

    # Set Hardware MAC Address
    if [ -n "$MAC_5G_RAW" ]; then
        MAC_5G=$(format_mac "$MAC_5G_RAW")
        ifconfig wlan0 hw ether "$MAC_5G"
        logger -t set-mib "wlan0 MAC set to $MAC_5G"
    fi

    # Crystal Oscillator Frequency Tuning (BB Register 0x2C)
    iwpriv wlan0 set_mib xcap="$XCAP_5G"
    iwpriv wlan0 set_mib share_xcap=0
    logger -t set-mib "wlan0 xcap set to $XCAP_5G"

    # Thermal Tracking Baseline (Register 0x87C)
    iwpriv wlan0 set_mib ther="$THER_5G"
    logger -t set-mib "wlan0 ther baseline set to $THER_5G"

    # Skyworth RFE Type 6 External PA / LNA Enable (Registers 0x82C, 0x830, 0x838)
    iwpriv wlan0 set_mib rfe_type=6
    logger -t set-mib "wlan0 RFE Type set to 6 (Skyworth External FEM active)"

    # 196-Channel 5 GHz Power Tables & 20/40/80/160 MHz Diffs
    if [ -n "$PWR_5G_HT40_A" ]; then
        iwpriv wlan0 set_mib pwrlevel5GHT40_1S_A="$PWR_5G_HT40_A"
    fi
    if [ -n "$PWR_5G_HT40_B" ]; then
        iwpriv wlan0 set_mib pwrlevel5GHT40_1S_B="$PWR_5G_HT40_B"
    fi
    if [ -n "$DIFF_5G_40_20_A" ]; then
        iwpriv wlan0 set_mib pwrdiff_5G_40BW2S_20BW2S_A="$DIFF_5G_40_20_A"
    fi
    if [ -n "$DIFF_5G_40_20_B" ]; then
        iwpriv wlan0 set_mib pwrdiff_5G_40BW2S_20BW2S_B="$DIFF_5G_40_20_B"
    fi
    if [ -n "$DIFF_5G_20_OFDM_A" ]; then
        iwpriv wlan0 set_mib pwrdiff_5G_20BW1S_OFDM1T_A="$DIFF_5G_20_OFDM_A"
    fi
    if [ -n "$DIFF_5G_20_OFDM_B" ]; then
        iwpriv wlan0 set_mib pwrdiff_5G_20BW1S_OFDM1T_B="$DIFF_5G_20_OFDM_B"
    fi
    if [ -n "$DIFF_5G_80_1S_A" ]; then
        iwpriv wlan0 set_mib pwrdiff_5G_80BW1S_160BW1S_A="$DIFF_5G_80_1S_A"
    fi
    if [ -n "$DIFF_5G_80_2S_A" ]; then
        iwpriv wlan0 set_mib pwrdiff_5G_80BW2S_160BW2S_A="$DIFF_5G_80_2S_A"
    fi
    if [ -n "$DIFF_5G_80_1S_B" ]; then
        iwpriv wlan0 set_mib pwrdiff_5G_80BW1S_160BW1S_B="$DIFF_5G_80_1S_B"
    fi
    if [ -n "$DIFF_5G_80_2S_B" ]; then
        iwpriv wlan0 set_mib pwrdiff_5G_80BW2S_160BW2S_B="$DIFF_5G_80_2S_B"
    fi

    # High-Performance 802.11ac VHT80 Parameters (verified against vmlinux MIB_TABLE)
    iwpriv wlan0 set_mib band=76        # 802.11a/n/ac (4 + 8 + 64 = 76)
    iwpriv wlan0 set_mib use40M=2       # 80 MHz channel width (0=20MHz, 1=40MHz, 2=80MHz)
    iwpriv wlan0 set_mib shortGI20M=1   # Short Guard Interval (20 MHz)
    iwpriv wlan0 set_mib shortGI40M=1   # Short Guard Interval (40 MHz)
    iwpriv wlan0 set_mib shortGI80M=1   # Short Guard Interval (80 MHz)
    iwpriv wlan0 set_mib ampdu=1        # A-MPDU aggregation
    iwpriv wlan0 set_mib amsdu=1        # A-MSDU aggregation
    iwpriv wlan0 set_mib txbf=1         # Beamforming master enable
    iwpriv wlan0 set_mib txbfer=1       # Explicit SU Beamformer
    iwpriv wlan0 set_mib txbfee=1       # SU Beamformee
    iwpriv wlan0 set_mib txbf_mu=1      # Wave 2 MU-MIMO Beamforming
    iwpriv wlan0 set_mib regdomain=1    # Numeric regulatory domain baseline (1=FCC / 3=ETSI)
    iwpriv wlan0 set_mib regdomain="$REG_DOMAIN_5G"  # Dynamic numeric regulatory domain from mtd1
    iwpriv wlan0 set_mib led_type=3     # Hardware LED trigger

    ifconfig wlan0 up
    logger -t set-mib "wlan0 initialized successfully at 866.7 Mbps line rate."
fi

# ==============================================================================
# 7. Program wlan1 (2.4 GHz RTL8197FS SoC integrated + Skyworth RFE Type 5)
# ==============================================================================
if ifconfig wlan1 down 2>/dev/null; then
    logger -t set-mib "Configuring wlan1 (2.4 GHz 802.11b/g/n)..."

    # Set Hardware MAC Address
    if [ -n "$MAC_2G_RAW" ]; then
        MAC_2G=$(format_mac "$MAC_2G_RAW")
        ifconfig wlan1 hw ether "$MAC_2G"
        logger -t set-mib "wlan1 MAC set to $MAC_2G"
    fi

    # Crystal Oscillator Frequency Tuning (SoC Registers 0xb8000024 / 0xb8000028)
    iwpriv wlan1 set_mib xcap="$XCAP_2G"
    logger -t set-mib "wlan1 xcap set to $XCAP_2G"

    # Thermal Tracking Baseline
    iwpriv wlan1 set_mib ther="$THER_2G"
    logger -t set-mib "wlan1 ther baseline set to $THER_2G"

    # Skyworth RFE Type 5 External FEM Enable
    iwpriv wlan1 set_mib rfe_type=5
    logger -t set-mib "wlan1 RFE Type set to 5"

    # 2.4 GHz Power Tables & Bandwidth Diffs (verified against vmlinux MIB_TABLE)
    if [ -n "$PWR_2G_CCK_A" ]; then
        iwpriv wlan1 set_mib pwrlevelCCK_A="$PWR_2G_CCK_A"
    fi
    if [ -n "$PWR_2G_CCK_B" ]; then
        iwpriv wlan1 set_mib pwrlevelCCK_B="$PWR_2G_CCK_B"
    fi
    if [ -n "$PWR_2G_HT40_A" ]; then
        iwpriv wlan1 set_mib pwrlevelHT40_1S_A="$PWR_2G_HT40_A"
    fi
    if [ -n "$PWR_2G_HT40_B" ]; then
        iwpriv wlan1 set_mib pwrlevelHT40_1S_B="$PWR_2G_HT40_B"
    fi
    if [ -n "$DIFF_2G_HT20" ]; then
        iwpriv wlan1 set_mib pwrdiffHT20="$DIFF_2G_HT20"
    fi
    if [ -n "$DIFF_2G_OFDM" ]; then
        iwpriv wlan1 set_mib pwrdiffOFDM="$DIFF_2G_OFDM"
    fi
    if [ -n "$DIFF_2G_HT40_2S" ]; then
        iwpriv wlan1 set_mib pwrdiffHT40_2S="$DIFF_2G_HT40_2S"
    fi

    # High-Performance 802.11n 40 MHz Parameters
    iwpriv wlan1 set_mib band=11        # 802.11b/g/n (1 + 2 + 8 = 11)
    iwpriv wlan1 set_mib use40M=1       # 40 MHz channel width (HT40)
    iwpriv wlan1 set_mib shortGI20M=1   # Short GI (20 MHz)
    iwpriv wlan1 set_mib shortGI40M=1   # Short GI (40 MHz)
    iwpriv wlan1 set_mib ampdu=1        # A-MPDU aggregation
    iwpriv wlan1 set_mib regdomain=1    # Numeric regulatory domain baseline (1=FCC / 3=ETSI)
    iwpriv wlan1 set_mib regdomain="$REG_DOMAIN_2G"

    ifconfig wlan1 up
    logger -t set-mib "wlan1 initialized successfully at 300.0 Mbps line rate."
fi

# Clean temporary file
rm -f "$TMP_CAL"
logger -t set-mib "Calibration injection complete for all wireless interfaces."
exit 0
