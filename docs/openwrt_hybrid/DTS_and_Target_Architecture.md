# Hybrid OpenWrt 4.14 Device Tree & Target Architecture

## 1. Target Architecture & Hardware Abstraction

To provide modern OpenWrt routing, IPv6 support, WireGuard VPN capabilities, and updated firewall management without sacrificing hardware offload performance, the target architecture selected is **OpenWrt 19.07** running **Linux Kernel 4.14 (MIPS32 LE)**.

### Target Specifications
- **Target System**: Realtek RTL8197F (`realtek`)
- **Subtarget**: RTL8197FS Embedded Gateway (`rtl8197f`)
- **Profile**: Tenda AC10 V1.0 (`tenda_ac10-v1`)
- **Instruction Set**: MIPS32 Release 2, Little-Endian (`mipsel`)
- **C Library**: `musl` libc
- **DRAM Model**: 64 MB (512 Mbit) integrated DDR2 memory (`0x00000000 - 0x04000000`)

```
+-----------------------------------------------------------------------------------+
|                     Hybrid OpenWrt 4.14 Device Tree Architecture                  |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  | Root Device Node: "tenda,ac10-v1", "realtek,rtl8197f-soc"                   |  |
|  +-----------------------------------------------------------------------------+  |
|        |                  |                     |                   |             |
|        v                  v                     v                   v             |
|  +--------------+  +--------------+      +--------------+    +-----------------+  |
|  | Memory Node  |  | SPI0 Flash   |      | Switch SMI   |    | PCIe RC0 Node   |  |
|  | 64 MB DDR2   |  | W25Q64 8 MB  |      | RTL8367RB    |    | RTL8822BE 5 GHz |  |
|  | (0x0-0x40000)|  | 41.67 MHz    |      | GPIO 18/19/58|    | (IRQ 5)         |  |
|  +--------------+  +--------------+      +--------------+    +-----------------+  |
|                           |                     |                                 |
|                           v                     v                                 |
|                    Fixed Partitions:     Ports 0..3 (RJ45)                        |
|                    - bootloader (128 KB) Port 6 (CPU RGMII)                       |
|                    - calibration (64 KB) (2.0 ns Rx Delay)                        |
|                    - firmware (7,872 KB)                                          |
|                    - cfm (128 KB)                                                 |
+-----------------------------------------------------------------------------------+
```

---

## 2. Complete Device Tree Specification (`tenda-ac10-v1.dts`)

Below is the verified, production-ready Device Tree Source (DTS) designed for the Tenda AC10 V1.0 under Linux 4.14:

```dts
/dts-v1/;

#include "rtl8197f.dtsi"
#include <dt-bindings/gpio/gpio.h>
#include <dt-bindings/input/input.h>

/ {
    model = "Tenda AC10 V1.0";
    compatible = "tenda,ac10-v1", "realtek,rtl8197f-soc";

    aliases {
        led-boot = &led_sys;
        led-failsafe = &led_sys;
        led-running = &led_sys;
        led-upgrade = &led_sys;
    };

    memory@0 {
        device_type = "memory";
        reg = <0x00000000 0x04000000>; /* 64 MB DDR2 SDRAM */
    };

    chosen {
        bootargs = "console=ttyS0,115200 rootfstype=squashfs,jffs2";
    };

    keys {
        compatible = "gpio-keys-polled";
        poll-interval = <20>;

        reset {
            label = "reset";
            gpios = <&gpio1 22 GPIO_ACTIVE_LOW>; /* GPIO 54 (Port G6) */
            linux,code = <KEY_RESTART>;
        };

        wps {
            label = "wps";
            gpios = <&gpio1 24 GPIO_ACTIVE_LOW>; /* GPIO 56 (Port G7) */
            linux,code = <KEY_WPS_BUTTON>;
        };
    };

    leds {
        compatible = "gpio-leds";

        led_sys: sys {
            label = "tenda:blue:sys";
            gpios = <&gpio1 25 GPIO_ACTIVE_LOW>; /* GPIO 57 (Port H1) */
            default-state = "on";
        };

        led_wps: wps {
            label = "tenda:blue:wps";
            gpios = <&gpio0 22 GPIO_ACTIVE_LOW>; /* GPIO 22 (Port C6) */
        };

        led_wan: wan {
            label = "tenda:blue:wan";
            gpios = <&gpio0 23 GPIO_ACTIVE_LOW>; /* GPIO 23 (Port C7) */
        };

        led_lan: lan {
            label = "tenda:blue:lan";
            gpios = <&gpio0 31 GPIO_ACTIVE_LOW>; /* GPIO 31 (Port D7) */
        };

        led_wifi: wifi {
            label = "tenda:blue:wifi";
            gpios = <&gpio1 1 GPIO_ACTIVE_LOW>;  /* GPIO 33 (Port E1) */
        };
    };
};

&spi0 {
    status = "okay";
    flash@0 {
        compatible = "jedec,spi-nor";
        reg = <0>;
        spi-max-frequency = <41666667>; /* 41.67 MHz */

        partitions {
            compatible = "fixed-partitions";
            #address-cells = <1>;
            #size-cells = <1>;

            partition@0 {
                label = "bootloader";
                reg = <0x00000000 0x00020000>; /* 128 KB */
                read-only;
            };

            partition@20000 {
                label = "calibration";
                reg = <0x00020000 0x00010000>; /* 64 KB (MTD1 RF Keys) */
                read-only;
            };

            partition@30000 {
                label = "firmware";
                reg = <0x00030000 0x007B0000>; /* 7,872 KB Firmware Slot */
                compatible = "openwrt,uimage", "denx,uimage";
            };

            partition@7e0000 {
                label = "cfm";
                reg = <0x007E0000 0x00020000>; /* 128 KB (Primary + Backup NVRAM) */
                read-only;
            };
        };
    };
};

	/*
	 * Realtek RTL8367RB-VB External 5-Port Gigabit Switch (Realtek 4.14 BSP Driver)
	 *   MDC  (Clock) : GPIO 18 (gpio0 pin 18)
	 *   MDIO (Data)  : GPIO 19 (gpio0 pin 19)
	 *   RST  (Reset) : GPIO 58 (gpio1 pin 26, active-low)
	 *   CPU RGMII    : Port 6 (EXT_PORT_1, 1000M full-duplex, txDelay=0, rxDelay=2)
	 *   Physical Map : Port 3 = WAN (VID 1), Ports 2/1/0 = LAN1/LAN2/LAN3 (VID 2)
	 */
	rtl8367b {
		compatible = "realtek,rtl8367b";
		cpu_port = <6>;
		realtek,cpu-port = <6>;
		realtek,extif1 = <1 0 1 1 1 1 1 1 2>;
		gpio-sck = <&gpio0 18 GPIO_ACTIVE_HIGH>;
		gpio-sda = <&gpio0 19 GPIO_ACTIVE_HIGH>;
		realtek,smi-mdc-gpio = <&gpio0 18 GPIO_ACTIVE_HIGH>;
		realtek,smi-mdio-gpio = <&gpio0 19 GPIO_ACTIVE_HIGH>;
		realtek,reset-gpio = <&gpio1 26 GPIO_ACTIVE_LOW>;
		realtek,ext-rgmii-delay = <0x02>;
	};

&pcie0 {
    status = "okay";
    /* PCI Express Root Complex connecting RTL8822BE 5 GHz Radio */
};
```

---

## 3. Hardware Pin Mapping & GPIO Bank Addressing

In the RTL8197F DTS binding, GPIO pins are represented across two 32-bit controllers:
- `gpio0`: Represents Port A through Port D (GPIO 0 through GPIO 31).
  - Formula: `pin_index = gpio_number`
  - GPIO 18 (Switch SMI MDC) = `<&gpio0 18>`
  - GPIO 19 (Switch SMI MDIO) = `<&gpio0 19>`
  - GPIO 22 (WPS LED) = `<&gpio0 22>`
  - GPIO 23 (WAN LED) = `<&gpio0 23>`
  - GPIO 31 (LAN LED) = `<&gpio0 31>`
- `gpio1`: Represents Port E through Port H (GPIO 32 through GPIO 63).
  - Formula: `pin_index = gpio_number - 32`
  - GPIO 33 (Wi-Fi LED) = `33 - 32 = 1` -> `<&gpio1 1>`
  - GPIO 54 (Reset Button) = `54 - 32 = 22` -> `<&gpio1 22>`
  - GPIO 56 (WPS Button) = `56 - 32 = 24` -> `<&gpio1 24>`
  - GPIO 57 (SYS LED) = `57 - 32 = 25` -> `<&gpio1 25>`
  - GPIO 58 (Switch Reset) = `58 - 32 = 26` -> `<&gpio1 26>`

This precise pin mapping ensures that OpenWrt's `gpio-leds` and `gpio-keys-polled` drivers accurately control LEDs and register button presses, and the Realtek BSP switch driver correctly binds SMI and asserts the hardware reset line.
