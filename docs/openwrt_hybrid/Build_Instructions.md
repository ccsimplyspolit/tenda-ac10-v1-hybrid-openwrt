# Hybrid OpenWrt 4.14 Reproducible Build & Packaging Guide

## 1. Build Environment & Prerequisites

Compiling the Hybrid OpenWrt 4.14 firmware requires a Linux x86_64 host environment (Ubuntu 20.04 LTS or 22.04 LTS recommended).

### Required Host Packages:
```bash
sudo apt update
sudo apt install -y build-essential libncurses5-dev gawk git subversion \
    libssl-dev gettext zlib1g-dev file python3 python3-distutils unzip \
    bzip2 wget ccache ecj fastjar libelf-dev flex bison
```

---

## 2. Source Tree Preparation & Feed Ingestion

Clone the stable OpenWrt 19.07 branch and initialize the package feeds:

```bash
# 1. Clone OpenWrt 19.07 Source Repository
git clone -b openwrt-19.07 https://git.openwrt.org/openwrt/openwrt.git openwrt-hybrid-ac10
cd openwrt-hybrid-ac10

# 2. Update and Install Package Feeds
./scripts/feeds update -a
./scripts/feeds install -a
```

---

## 3. Integrating the Tenda AC10 V1 Hybrid Kit Artifacts

Transfer the hardware definitions, kernel configuration patches, and calibration daemon from the Hybrid Kit into the build tree:

### 3.1 Device Tree Integration
Copy the hardware device tree into the Realtek DTS target directory:
```bash
cp config/tenda-ac10-v1.dts target/linux/realtek/dts/
```

### 3.2 OpenWrt Configuration Patching
Apply the configuration patch to OpenWrt's top-level `.config` enabling the Realtek target, HW NAT, and the monolithic wireless driver:
```bash
patch -p1 < config/kernel-4.14.config.diff
```

### 3.3 Rootfs Calibration Script & Startup Hooks
Integrate the out-of-band calibration injection daemon directly into the filesystem overlay:
```bash
mkdir -p files/bin files/etc
cp tools/scripts/set-mib.sh files/bin/set-mib.sh
chmod +x files/bin/set-mib.sh

# Create automated startup hook in /etc/rc.local
cat << 'EOF' > files/etc/rc.local
# Put your custom commands here that should be executed once
# the system init finished. By default this file does nothing.

# Inject Realtek RF Calibration Parameters from MTD1
/bin/set-mib.sh

exit 0
EOF
chmod +x files/etc/rc.local
```

---

## 4. Menuconfig Configuration

Generate the target profile:
```bash
make menuconfig
```
Select the following core options:
- **Target System**: `Realtek RTL8197F`
- **Subtarget**: `RTL8197FS Gateway`
- **Target Profile**: `Tenda AC10 V1.0`
- **Target Images**:
  - `[*] squashfs`
  - `[ ] jffs2`
- **LuCI Configuration**:
  - `LuCI -> Collections -> <*> luci`
  - `LuCI -> Protocols -> <*> luci-proto-wireguard`
- **Network -> VPN**:
  - `<*> wireguard-tools`

---

## 5. Compilation & Image Generation

Compile the toolchain, kernel, and rootfs packages:

```bash
# Download package tarballs
make download -j8

# Compile firmware image (adjust -j for CPU core count)
make -j$(nproc) V=s
```

Upon successful completion, the compiled raw kernel and SquashFS binaries reside in:
`bin/targets/realtek/rtl8197f/`

---

## 6. Crucial Packaging Protocol: Avoiding the Booter AutoBurn Traps

As proven in our reverse engineering analysis of `booter_stage2_v3.4.11B.9`:
1. **The `$s7` Zeroing Bug**: Never output a dual-header `cs6c` + `hsqs` image, which resets the destination burn address to `0x00030000` and overwrites the kernel.
2. **The Padding Loop Stall**: Never append trailing padding bytes beyond the declared payload length. The length field in bytes 12..15 of the 16-byte header must exactly match `image_file_size - 16`.

### Automated Header Generator Script:
```python
import struct, os, sys

def package_hybrid_image(kernel_bin, rootfs_bin, output_bin):
    with open(kernel_bin, "rb") as fk:
        k_data = fk.read()
    with open(rootfs_bin, "rb") as fr:
        r_data = fr.read()
        
    payload = k_data + r_data
    payload_len = len(payload)
    
    # Target address for KernelFS slot is 0x00030000
    burn_addr = 0x00030000
    magic = b"cr6c" # Use unified cr6c magic
    flags = 0x0000
    
    # Compute 16-bit big-endian additive checksum
    csum = 0
    # Add payload words
    for i in range(0, payload_len - (payload_len % 2), 2):
        w = (payload[i] << 8) | payload[i+1]
        csum = (csum + w) & 0xFFFF
    if payload_len % 2 != 0:
        csum = (csum + (payload[-1] << 8)) & 0xFFFF
        
    # Calculate required header checksum field such that total sum == 0
    # Header format: magic (4s), load_addr (I), checksum (H), flags (H), payload_len (I) -> 16 bytes
    header_partial = struct.pack(">4sIHHI", magic, burn_addr, 0, flags, payload_len)
    for i in range(0, len(header_partial), 2):
        w = (header_partial[i] << 8) | header_partial[i+1]
        csum = (csum + w) & 0xFFFF
        
    final_csum_field = (0x10000 - csum) & 0xFFFF
    
    # Assemble final 16-byte header
    header = struct.pack(">4sIHHI", magic, burn_addr, final_csum_field, flags, payload_len)
    
    final_image = header + payload
    with open(output_bin, "wb") as fo:
        fo.write(final_image)
        
    print(f"[OK] Packaged {output_bin}: {len(final_image)} bytes, payload {payload_len} bytes.")

package_hybrid_image("vmlinux.lzma", "root.squashfs", "openwrt-hybrid-tenda-ac10-v1.bin")
```

---

## 7. Flashing the Hybrid Firmware

Once packaged:
1. Connect client PC Ethernet to router **LAN Port 1** (Do not use WAN port).
2. Configure PC static IP: `192.168.1.100`, subnet `255.255.255.0`.
3. Power-cycle the router with Reset button depressed for 5 seconds to enter Realtek Booter disaster mode.
4. Execute `run_emergency_recovery.bat` or `tftp_emergency_engine.py` to transmit `openwrt-hybrid-tenda-ac10-v1.bin` to `192.168.1.6:69`.
5. The booter burns the image and automatically reboots into Hybrid OpenWrt 4.14!
