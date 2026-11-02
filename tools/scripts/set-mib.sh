#!/bin/sh
# ==============================================================================
# set-mib.sh — Out-of-Band Factory RF Calibration Injection for Tenda AC10 V1.0
# Supports Both:
#   - Hybrid OpenWrt 4.14: rtw88 (5 GHz PCIe RTL8822BE, Skyworth SE5003L1 RFE 6)
#                        + rtl8192cd (2.4 GHz SoC RTL8197FS, Skyworth SKY85303-11 RFE 5)
#   - Monolithic rtl8192cd: Dual-band vendor HAL (wlan0 5 GHz + wlan1 2.4 GHz)
# ==============================================================================
# Reads per-unit ASCII calibration keys from /dev/mtd1 (0x020000..0x030000),
# injects 5 GHz crystal cap (HW_WLAN0_11N_XCAP) + factory MAC into rtw88_core /
# rtw88_8822be, and injects 2.4 GHz power tables + crystal cap + thermal baseline
# + vladisslav0 UDP/uTP torrent stability fixes (manual_edca=1, disable_txsc=1)
# into rtl8192cd.
# ==============================================================================

CAL_DEV=""
TMP_CAL="/tmp/factory_cal.$$"

# 1. Locate the calibration partition dynamically by MTD label
if [ -f /proc/mtd ]; then
    CAL_DEV_NAME=$(grep -i -E '"(calibration|caldata)"' /proc/mtd | head -n1 | cut -d: -f1)
    if [ -n "$CAL_DEV_NAME" ]; then
        CAL_BLK="/dev/$(printf '%s' "$CAL_DEV_NAME" | sed 's/^mtd/mtdblock/')"
        if [ -b "$CAL_BLK" ]; then
            CAL_DEV="$CAL_BLK"
        elif [ -c "/dev/$CAL_DEV_NAME" ]; then
            CAL_DEV="/dev/$CAL_DEV_NAME"
        fi
    fi
fi

# Fallback: standard Tenda AC10 V1.0 partition index 1 (0x020000, 64 KB)
if [ -z "$CAL_DEV" ]; then
    if [ -b "/dev/mtdblock1" ]; then
        CAL_DEV="/dev/mtdblock1"
    elif [ -c "/dev/mtd1" ]; then
        CAL_DEV="/dev/mtd1"
    fi
fi

# Universal emergency fallback: scan all mtdblock devices for ASCII HW_NIC0_ADDR=
# (Note: bytes [0..3] of mtd1 are per-unit uint32_le CRC32(mtd1[8:65536]), NOT a fixed magic!)
if [ -z "$CAL_DEV" ]; then
    for dev in /dev/mtdblock*; do
        if [ -b "$dev" ]; then
            if dd if="$dev" bs=65536 count=1 2>/dev/null | tr '\0' '\n' | grep -q '^HW_NIC0_ADDR='; then
                CAL_DEV="$dev"
                break
            fi
        fi
    done
fi

if [ -z "$CAL_DEV" ] || { [ ! -b "$CAL_DEV" ] && [ ! -c "$CAL_DEV" ] && [ ! -f "$CAL_DEV" ]; }; then
    logger -t set-mib "ERROR: Factory calibration MTD partition not found! Aborting."
    exit 1
fi

logger -t set-mib "Found factory calibration partition at $CAL_DEV. Extracting parameters..."

# 2. Extract ASCII key-value pairs (read 64 KB sector, strip NUL/CR)
dd if="$CAL_DEV" bs=65536 count=1 2>/dev/null | tr '\0' '\n' | tr -d '\r' | tr -cd '\11\12\40-\176' > "$TMP_CAL"

get_key() {
    grep "^$1=" "$TMP_CAL" | head -n1 | cut -d'=' -f2-
}

# 3. Format MAC address helper (aabbccddeeff -> aa:bb:cc:dd:ee:ff)
format_mac() {
    printf '%s' "$1" | tr -d '\r\n ' | tr 'A-F' 'a-f' | sed 's/../&:/g;s/:$//'
}

valid_mac() {
    case "$1" in
        [0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f])
            [ "$1" != "00:00:00:00:00:00" ] && [ "$1" != "ff:ff:ff:ff:ff:ff" ] && return 0
            ;;
    esac
    return 1
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

# Factory baseline fallback defaults if mtd1 keys are empty/blank
case "$XCAP_5G" in ''|*[!0-9]*) XCAP_5G="27" ;; esac
case "$XCAP_2G" in ''|*[!0-9]*) XCAP_2G="46" ;; esac
case "$THER_5G" in ''|*[!0-9]*) THER_5G="25" ;; esac
case "$THER_2G" in ''|*[!0-9]*) THER_2G="32" ;; esac
case "$REG_DOMAIN_5G" in ''|*[!0-9]*) REG_DOMAIN_5G="13" ;; esac
case "$REG_DOMAIN_2G" in ''|*[!0-9]*) REG_DOMAIN_2G="13" ;; esac

[ -z "$PWR_5G_HT40_A" ] && PWR_5G_HT40_A="00000000000000000000000000000000000000000000000000000000000000000000001B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B1B19191919191919191918181818181818181818181818181818181818181818181800000000000000000000000000000000000000"
[ -z "$PWR_5G_HT40_B" ] && PWR_5G_HT40_B="00000000000000000000000000000000000000000000000000000000000000000000001E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1E1B1B1B1B1B1B1B1B1B19191919191919191919191919191919191919191919191900000000000000000000000000000000000000"
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

ETH_MAC=$(format_mac "$MAC_ETH_RAW")
valid_mac "$ETH_MAC" || ETH_MAC="50:0f:f5:00:00:00"
MAC_5G=$(format_mac "$MAC_5G_RAW")
valid_mac "$MAC_5G" || MAC_5G="50:0f:f5:00:00:05"
MAC_2G=$(format_mac "$MAC_2G_RAW")
valid_mac "$MAC_2G" || MAC_2G="50:0f:f5:00:00:01"

# Read UCI 2.4 GHz channel width & noscan policy (default HT20 = use40M 0)
UCI_2G_HTMODE=$(uci -q get wireless.radio1.htmode 2>/dev/null)
case "$UCI_2G_HTMODE" in
    HT40*|VHT40*) USE40M_2G="1" ;;
    *)            USE40M_2G="0" ;;
esac
UCI_2G_NOSCAN=$(uci -q get wireless.radio1.noscan 2>/dev/null)

# ==============================================================================
# 5. Program Base Ethernet MAC (eth0 / gmac0) when interface is not yet up
# ==============================================================================
if [ -d /sys/class/net/eth0 ]; then
    ifconfig eth0 hw ether "$ETH_MAC" 2>/dev/null || ip link set dev eth0 address "$ETH_MAC" 2>/dev/null || true
    logger -t set-mib "eth0 base Ethernet MAC set to $ETH_MAC"
fi

# ==============================================================================
# 6 & 7. Program Wireless Interfaces (Monolithic Dual-rtl8192cd vs Hybrid rtw88+rtl8192cd)
# ==============================================================================
if [ -e /proc/wlan0/mib_all ] && [ -e /proc/wlan1/mib_all ]; then
    # --- Monolithic Dual-rtl8192cd Mode: wlan0 = 5 GHz (RTL8822BE), wlan1 = 2.4 GHz (RTL8197FS) ---
    if ifconfig wlan0 down 2>/dev/null; then
        logger -t set-mib "Configuring wlan0 (5 GHz 802.11ac, monolithic rtl8192cd)..."
        ifconfig wlan0 hw ether "$MAC_5G" 2>/dev/null || true
        iwpriv wlan0 set_mib xcap="$XCAP_5G"
        iwpriv wlan0 set_mib share_xcap=0
        iwpriv wlan0 set_mib ther="$THER_5G"
        iwpriv wlan0 set_mib rfe_type=6
        iwpriv wlan0 set_mib pwrlevel5GHT40_1S_A="$PWR_5G_HT40_A"
        iwpriv wlan0 set_mib pwrlevel5GHT40_1S_B="$PWR_5G_HT40_B"
        iwpriv wlan0 set_mib pwrdiff_5G_40BW2S_20BW2S_A="$DIFF_5G_40_20_A"
        iwpriv wlan0 set_mib pwrdiff_5G_40BW2S_20BW2S_B="$DIFF_5G_40_20_B"
        iwpriv wlan0 set_mib pwrdiff_5G_20BW1S_OFDM1T_A="$DIFF_5G_20_OFDM_A"
        iwpriv wlan0 set_mib pwrdiff_5G_20BW1S_OFDM1T_B="$DIFF_5G_20_OFDM_B"
        iwpriv wlan0 set_mib pwrdiff_5G_80BW1S_160BW1S_A="$DIFF_5G_80_1S_A"
        iwpriv wlan0 set_mib pwrdiff_5G_80BW2S_160BW2S_A="$DIFF_5G_80_2S_A"
        iwpriv wlan0 set_mib pwrdiff_5G_80BW1S_160BW1S_B="$DIFF_5G_80_1S_B"
        iwpriv wlan0 set_mib pwrdiff_5G_80BW2S_160BW2S_B="$DIFF_5G_80_2S_B"
        iwpriv wlan0 set_mib band=76
        iwpriv wlan0 set_mib use40M=2
        iwpriv wlan0 set_mib shortGI20M=1
        iwpriv wlan0 set_mib shortGI40M=1
        iwpriv wlan0 set_mib shortGI80M=1
        iwpriv wlan0 set_mib ampdu=1
        iwpriv wlan0 set_mib amsdu=1
        iwpriv wlan0 set_mib manual_edca=1
        iwpriv wlan0 set_mib disable_txsc=1
        iwpriv wlan0 set_mib txbf=1
        iwpriv wlan0 set_mib txbfer=1
        iwpriv wlan0 set_mib txbfee=1
        iwpriv wlan0 set_mib txbf_mu=1
        iwpriv wlan0 set_mib regdomain="$REG_DOMAIN_5G"
        iwpriv wlan0 set_mib led_type=3
        ifconfig wlan0 up
        logger -t set-mib "wlan0 (5 GHz) initialized with MAC $MAC_5G, xcap=$XCAP_5G, RFE=6."
    fi

    if ifconfig wlan1 down 2>/dev/null; then
        logger -t set-mib "Configuring wlan1 (2.4 GHz 802.11b/g/n, monolithic rtl8192cd)..."
        ifconfig wlan1 hw ether "$MAC_2G" 2>/dev/null || true
        iwpriv wlan1 set_mib xcap="$XCAP_2G"
        iwpriv wlan1 set_mib ther="$THER_2G"
        iwpriv wlan1 set_mib rfe_type=5
        iwpriv wlan1 set_mib pwrlevelCCK_A="$PWR_2G_CCK_A"
        iwpriv wlan1 set_mib pwrlevelCCK_B="$PWR_2G_CCK_B"
        iwpriv wlan1 set_mib pwrlevelHT40_1S_A="$PWR_2G_HT40_A"
        iwpriv wlan1 set_mib pwrlevelHT40_1S_B="$PWR_2G_HT40_B"
        iwpriv wlan1 set_mib pwrdiffHT20="$DIFF_2G_HT20"
        iwpriv wlan1 set_mib pwrdiffOFDM="$DIFF_2G_OFDM"
        iwpriv wlan1 set_mib pwrdiffHT40_2S="$DIFF_2G_HT40_2S"
        iwpriv wlan1 set_mib band=11
        iwpriv wlan1 set_mib use40M="$USE40M_2G"
        iwpriv wlan1 set_mib shortGI20M=1
        iwpriv wlan1 set_mib shortGI40M=1
        iwpriv wlan1 set_mib ampdu=1
        iwpriv wlan1 set_mib amsdu=1
        iwpriv wlan1 set_mib manual_edca=1
        iwpriv wlan1 set_mib disable_txsc=1
        [ "$UCI_2G_NOSCAN" = "1" ] && iwpriv wlan1 set_mib coexist=0
        iwpriv wlan1 set_mib regdomain="$REG_DOMAIN_2G"
        ifconfig wlan1 up
        logger -t set-mib "wlan1 (2.4 GHz) initialized with MAC $MAC_2G, xcap=$XCAP_2G, RFE=5."
    fi
else
    # --- Hybrid OpenWrt 4.14 Mode: rtw88 (5 GHz mac80211) + rtl8192cd (2.4 GHz SoC) ---
    # A. Dynamic per-unit 5 GHz crystal cap (HW_WLAN0_11N_XCAP) for blank-eFuse RTL8822BE:
    #    rtw88_core latches xtal_cap_override into rtwdev->efuse.crystal_cap during PCIe probe
    #    (rtw88_8822be init) and programs BB regs 0x24/0x28 in rtw8822b_phy_set_param().
    if [ -w /sys/module/rtw88_core/parameters/xtal_cap_override ]; then
        CUR_XCAP=$(cat /sys/module/rtw88_core/parameters/xtal_cap_override 2>/dev/null)
        if [ "$CUR_XCAP" != "$XCAP_5G" ]; then
            echo "$XCAP_5G" > /sys/module/rtw88_core/parameters/xtal_cap_override 2>/dev/null || true
            # Persist per-unit xtal_cap_override into /etc/modules.d/rtw88 on writable JFFS2 overlay
            if [ -f /etc/modules.d/rtw88 ] && [ -w /etc/modules.d/rtw88 ]; then
                sed -i "s|^rtw88_core.*|rtw88_core xtal_cap_override=$XCAP_5G|" /etc/modules.d/rtw88 2>/dev/null || true
            fi
            # Pre-bind radio0 to its invariant PCIe path before re-probing so hotplug 10-wifi-detect sees found=1 on phy1
            _PRE_PHY=$(ls /sys/bus/pci/drivers/rtw_8822be/*/ieee80211 2>/dev/null | head -n1)
            if [ -n "$_PRE_PHY" ] && [ -f /lib/netifd/mac80211.sh ] && command -v uci >/dev/null 2>&1 && [ "$(uci -q get wireless.radio0.type 2>/dev/null)" = "mac80211" ]; then
                _PRE_PATH=$(. /lib/netifd/mac80211.sh; mac80211_phy_to_path "$_PRE_PHY" 2>/dev/null)
                if [ -n "$_PRE_PATH" ]; then
                    uci -q set wireless.radio0.path="$_PRE_PATH"
                    uci -q delete wireless.radio0.phy
                    uci -q delete wireless.radio0.macaddr
                    uci -q commit wireless
                fi
            fi
            # Re-probe rtw88_8822be at early boot (START=18, before S20network/hostapd) so efuse.crystal_cap latches $XCAP_5G
            if ! pidof hostapd >/dev/null 2>&1; then
                rmmod rtw88_8822be 2>/dev/null && modprobe rtw88_8822be 2>/dev/null || true
            fi
            logger -t set-mib "rtw88 5 GHz dynamic xtal_cap_override latched to $XCAP_5G (was $CUR_XCAP)"
        fi
    fi

    # B. Guard against phy0 -> phy1 index shift after rmmod/modprobe rtw88_8822be
    #    and ensure 5 GHz mac80211 interface & UCI carry factory HW_WLAN0_WLAN_ADDR MAC:
    ACTUAL_PHY=$(ls /sys/bus/pci/drivers/rtw_8822be/*/ieee80211 2>/dev/null | head -n1)
    [ -z "$ACTUAL_PHY" ] && ACTUAL_PHY=$(ls /sys/class/ieee80211 2>/dev/null | head -n1)
    for _net in /sys/class/net/wlan*; do
        [ -e "$_net" ] || continue
        _if="${_net##*/}"
        case "$_if" in *-*) continue ;; esac
        if [ ! -e "/proc/$_if/mib_all" ]; then
            ifconfig "$_if" hw ether "$MAC_5G" 2>/dev/null || ip link set dev "$_if" address "$MAC_5G" 2>/dev/null || true
            logger -t set-mib "5 GHz rtw88 interface $_if factory MAC set to $MAC_5G (phy=${ACTUAL_PHY:-unknown})"
        fi
    done
    if command -v uci >/dev/null 2>&1 && [ "$(uci -q get wireless.radio0.type 2>/dev/null)" = "mac80211" ]; then
        ACTUAL_PATH=""
        if [ -n "$ACTUAL_PHY" ] && [ -f /lib/netifd/mac80211.sh ]; then
            ACTUAL_PATH=$(. /lib/netifd/mac80211.sh; mac80211_phy_to_path "$ACTUAL_PHY" 2>/dev/null)
        fi
        if [ -n "$ACTUAL_PATH" ]; then
            uci -q set wireless.radio0.path="$ACTUAL_PATH"
            uci -q delete wireless.radio0.phy
        elif [ -n "$ACTUAL_PHY" ]; then
            uci -q set wireless.radio0.phy="$ACTUAL_PHY"
        fi
        # Remove any stale random blank-eFuse wiphy macaddr on wifi-device so find_phy() uses PCIe path/phy
        uci -q delete wireless.radio0.macaddr
        # Remove any duplicate disabled radio2 created if hotplug 10-wifi-detect fired on phy1
        if [ "$(uci -q get wireless.radio2.type 2>/dev/null)" = "mac80211" ] && [ "$(uci -q get wireless.radio2.disabled 2>/dev/null)" = "1" ]; then
            uci -q delete wireless.default_radio2
            uci -q delete wireless.radio2
        fi
        if uci -q get wireless.default_radio0 >/dev/null 2>&1; then
            [ -z "$(uci -q get wireless.default_radio0.ifname 2>/dev/null)" ] && uci -q set wireless.default_radio0.ifname='wlan1'
            CUR_UCI_5G_MAC=$(uci -q get wireless.default_radio0.macaddr 2>/dev/null)
            if [ -z "$CUR_UCI_5G_MAC" ] || [ "$CUR_UCI_5G_MAC" = "02:11:22:33:44:56" ]; then
                uci -q set wireless.default_radio0.macaddr="$MAC_5G"
            fi
        fi
        uci -q commit wireless
    fi

    # C. Identify 2.4 GHz vendor rtl8192cd root interface by /proc/<ifname>/mib_all and inject calibration + UDP/uTP fixes
    VENDOR_2G_IF=""
    for _net in /sys/class/net/wlan*; do
        [ -e "$_net" ] || continue
        _if="${_net##*/}"
        case "$_if" in *-*) continue ;; esac
        if [ -e "/proc/$_if/mib_all" ]; then
            VENDOR_2G_IF="$_if"
            break
        fi
    done

    if [ -n "$VENDOR_2G_IF" ]; then
        ifconfig "$VENDOR_2G_IF" hw ether "$MAC_2G" 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib xcap="$XCAP_2G" 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib ther="$THER_2G" 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib rfe_type=5 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib pwrlevelCCK_A="$PWR_2G_CCK_A" 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib pwrlevelCCK_B="$PWR_2G_CCK_B" 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib pwrlevelHT40_1S_A="$PWR_2G_HT40_A" 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib pwrlevelHT40_1S_B="$PWR_2G_HT40_B" 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib pwrdiffHT20="$DIFF_2G_HT20" 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib pwrdiffOFDM="$DIFF_2G_OFDM" 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib pwrdiffHT40_2S="$DIFF_2G_HT40_2S" 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib band=11 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib use40M="$USE40M_2G" 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib shortGI20M=1 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib shortGI40M=1 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib ampdu=1 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib amsdu=1 2>/dev/null || true
        # vladisslav0 4PDA #97815216 & #98016337 fixes for UDP/uTP torrent stalls & TX shortcut corruption:
        iwpriv "$VENDOR_2G_IF" set_mib manual_edca=1 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib disable_txsc=1 2>/dev/null || true
        [ "$UCI_2G_NOSCAN" = "1" ] && iwpriv "$VENDOR_2G_IF" set_mib coexist=0 2>/dev/null || true
        iwpriv "$VENDOR_2G_IF" set_mib regdomain="$REG_DOMAIN_2G" 2>/dev/null || true
        logger -t set-mib "Hybrid mode: $VENDOR_2G_IF (2.4 GHz rtl8192cd, RFE=5, xcap=$XCAP_2G, manual_edca=1, disable_txsc=1) calibrated."
    fi
fi

rm -f "$TMP_CAL"
logger -t set-mib "Calibration injection complete for all interfaces."
exit 0
