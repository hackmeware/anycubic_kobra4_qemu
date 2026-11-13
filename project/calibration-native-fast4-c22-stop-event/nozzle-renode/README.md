# Nozzle MCU: vorläufiges Cortex-M3/F1-kompatibles Modell

**Kein identifizierter physischer SoC.** Diese Plattform bildet den aus der bereitgestellten Nozzle-Anwendung beobachteten Cortex-M-/STM32F1-kompatiblen Softwarepfad nach. Sie darf weder als Beweis für STM32F103 noch für AT32 oder einen anderen Hersteller ausgegeben werden. Kompatible Klone und andere Cortex-M-Kerne sind durch die vorliegende Binärdatei nicht sicher ausgeschlossen.

## Belegte Image-Eigenschaften

- `nozzle_firmware_v1.2.9_20260120.bin`,37469Bytes.
- SHA-256 `ae09264667ff4a72905706026b1591bdede91e1f250755319fec531328e54e2f`.
- **Ladebasis0x08004000**. Resetvector0x08008565 entspricht Datei-Offset0x4564 mit `cpsid i`, Laden von SP und Entry und `bx` zum Entry0x08009411.
- Initial-SP0x20005000. Modelliert sind20KiB SRAM; der SP allein beweist nicht die vollständige physische SRAM-Kapazität.
- GPIO0x40010800, RCC0x40021000, FLASH0x40022000, USART1 0x40013800; NVIC/SysTick/DWT unter Cortex-M-Systemadressen.
- Read-only Startbeobachtung liest Gerätekonfiguration0x0801F800/804. Flashfenster deshalb128KiB, nicht nur die Dateigröße. Vollständige physische Flash-Kapazität bleibt unbestätigt.
- USART1 wird mit Divisor63 und CTRL1=0x202C initialisiert, RX/TX PA10/PA9. Host erwartet576000Baud.

## Gewählte Kompatibilitätsannahmen

Renodes Cortex-M3 führt den beobachteten Code aus; das ist kein alleiniger Nachweis für den echten Kern. HEXT24MHz ist eine aus der Firmware-/Host-Konstellation plausible, unbestätigte Boardannahme. Damit führen RCC-CFG0x0005E40A zu72MHz Systemtakt/36MHz APB2 und571428Baud mit Divisor63. Der serielle Hosttransport arbeitet byteweise und bildet die Baudabweichung nicht elektrisch ab.

Die F1-kompatiblen UART/GPIO/EXINT/I²C/SPI/ADC/Watchdog/DWT-Funktionsmodelle werden aus dem AT32-Projekt wiederverwendet. Deshalb tragen die Implementierungstypen den Namespace AT32, **ohne dass hierdurch der Nozzle-Chip als AT32 identifiziert wäre**. Es wird ein separates F1-Startup-Flashregistermodell mit Access-Control-Register verwendet. AT32-spezifische Chip-ID-/UID-Tags werden nicht gesetzt.

## Start

Aus diesem Verzeichnis:

```sh
renode scripts/load.resc
```

Im Monitor:

```text
sysbus LoadBinary @/pfad/nozzle_firmware_v1.2.9_20260120.bin 0x08004000
cpu VectorTableOffset 0x08004000
showAnalyzer sysbus.usart1
start
```

Der fehlende Bootloader wird umgangen. Für eine Verbindung mit der Hostemulation ist `sysbus.usart1` der getestete UART-Endpunkt. Die gemeinsame Verwendung mit dem Haupt-MCU-Paket sollte über separate Renode-Prozesse erfolgen, um doppelte dynamische Typdefinitionen zu vermeiden. Virtuelle Uhren sind dabei nicht automatisch synchronisiert.

## Bootnachweis und Grenzen

Ein1s-Lauf erreicht PC0x08005088 unmittelbar hinter WFI0x08005086, CFSR/HFSR=0. USART1 sendet `06 10 5c e2 92 7e`. Dies belegt bounded boot und Kommunikationsbereitschaft, nicht die vollständige Nozzle-Funktion oder exakte Hardware.

Die Anwendung liest eine **nicht mitgelieferte** Gerätekonfiguration bei0x0801F800. Nicht geladener MappedMemory ist standardmäßig0; das ist synthetischer Emulatorzustand, kein echter Gerätespeicherinhalt. Ein zweiter Test setzt den ersten Konfigurationsbereich auf0xFF: Die Anwendung versucht Initialisierung/Flashwrites, das Modell meldet ausdrücklich nicht unterstützte Flashprogrammierung; die MCU erreicht dennoch denselben WFI-Zustand. Beide Zustände sind keine rekonstruierte reale Konfiguration. Ein vollständiger Flashdump wäre hierfür nötig.

Flashprogrammierung, Erase, Schutzmechanismen, echter Bootloader, USB/CAN/SDIO, genaue Pin-Multiplexierung und Nozzle-Sensoren/Aktoren sind nicht vollständig modelliert. Keine realen Ausgänge werden angesprochen und keine konkrete Heater-Pinbelegung erfunden.

## Tests

Mit der daneben vorbereiteten Renode1.17-Laufzeit:

```sh
./tests/run.sh /pfad/nozzle_firmware_v1.2.9_20260120.bin
```

Die originale Firmware wird nicht im Paket mitgeliefert. `docs/*.asm` enthält fokussierte statische Belege, `docs/mmio-refs.json` PC-relative MMIO-Kandidaten. Die JSON-Liste enthält auch Daten, die beim Halfwordscan wie Instruktionen aussehen; nur die separat analysierten Routinen sind als Belege zu behandeln.

## Zeitbasis im gekoppelten Betrieb

Der DWT-Zähler wurde zusätzlich deterministisch geprüft: exakt 7.200.000 Zyklen pro 0,1 Sekunden Renode-Zeit bei 72 MHz. Zwei unabhängige Renode-Prozesse und QEMU/native Host teilen jedoch keine gemeinsame Simulationsuhr. UART-Pacing in Echtzeit kann die hostseitige Taktschätzung verzerren. Ein erfolgreicher Identify-Handshake beweist keine Echtzeit-Synchronität; den Nozzle-Takt deshalb nicht künstlich erhöhen und Sicherheitsprüfungen nicht unterdrücken.
