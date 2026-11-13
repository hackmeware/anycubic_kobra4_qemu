# Abdeckung und Fidelity

„Funktional“ bedeutet getestete Register-/Daten-/IRQ-Operationen, nicht alle Hardware-Modi. Die Tests sind gezielt, kein vollständiger Hersteller-Konformitätstest.

| Block | Status | Wesentliche Grenzen |
|---|---|---|
| Cortex-M4 / NVIC / SysTick | Renode-Core, Firmwareausführung getestet | Nicht zyklengenau, CPU-IPC nicht mit realem Takt gleichsetzen |
| Flash 1 MiB / SRAM 96/224 KiB | Exakte Speicherfenster, Boot-Flash-Alias, Bitbanding | Bootpins/BTOPT/ROM und Option-Byte-Umschaltung fehlen |
| CRM | Custom, Ready/PLL/Divider/IRQ/Reset/Clock-Propagation | Clock-Gating, Reset-Cause-Erfassung, Clock-Failure/NMI und Sleep unvollständig; HEXT=8MHz Boardannahme |
| Flashcontroller | Register-/Unlock-/Fehlerpfade für Startup | Keine echte Programmierung, kein Erase, kein Sicherheitsschutz; direkte RAM-artige Flashwrites technisch möglich |
| GPIO A–E | Custom, Config/IDT/ODT/Set/Clear/Lock/Pulls/Open-drain | Kein analoges Padmodell; LQFP64 nur A–C und D0–2 gebondet |
| IOMUX / EXINT | Portzuordnung, Flanken, Softwaretrigger, W1C, IRQ-Gruppen | Kein vollständiges Alternate-Function-Netz; Event kein vollständiges Cortex-Sleep-Eventmodell |
| UART/USART 1–8 | TX/RX/IRQ/Fehlerstatus/DMA-Anforderung | Synchronous byte transport, keine bitgenaue Baud/Framing/Flow-Control/LIN/IRDA/Smartcard |
| SPI 1–4 | Echte Child-Transfers, IRQ, 8/16Bit, Status/CRC/DMA-Anforderung | Master-Funktionspfad; kein Slave/I²S/CRC-next/elektrisches NSS-Timing |
| I²C 1–3 | Echte Child-Transfers, 7/10Bit, Start/RepeatedStart/Stop, IRQ | Kein Slave/SMBus, Busarbitration/ClockStretching/bitgenaues ACK-Timing |
| DMA 1–2 ×7 | Elementbreite/Zahl/Inkrement/IRQ/Fehler/Circular/M2M, Fixed/Flex-Request-Routing | Synchronous transfer, keine Prioritätsarbitrierung; Timer/DAC/SDIO-Requests nicht automatisch vollständig integriert |
| Timer 1–14 | Renode-Timer plus AT32-PR-Reset/PMEN32-Adapter | TMR2/5 mit32Bit, sonst16Bit; Motorsteuerungs-/Break-/Deadtime-Details, DMA/PWM-Pinrouting nicht vollständig |
| ADC 1–3 | Injizierbare Werte, Sequences, Softwaretrigger, Calibration, Watchdog/IRQ | Keine Analogsimulation; sofortige Conversion, kein fortlaufender Continuous-/Multi-ADC-Zeitablauf, externe Trigger nicht verdrahtet |
| DAC 1–2 | Datenlatches, Alignment, Trigger und sichtbare Ausgänge | Keine Analogwellenform, kein Noise/Triangle/DMA |
| RTC / BPR / PWC | Virtuelle Zeit, Divider/Counter/Alarm/IRQ, Backup-Retention/Writegate | Keine echte Stromdomäne, Tamper/Low-power nur Teilumfang |
| WDT / WWDT | Geschützte Konfiguration, Refresh, EarlyIRQ und tatsächlicher Reset | Kein automatischer Option-Byte-Start; Debug-Freeze/Reset-Cause unvollständig |
| CRC | Programmierbare Polynomial/Seed/Breite/Reflection | Gegen Standardvektoren getestet |
| DWT | Clock-synchronisierter CYCCNT | Keine Trace-/Watchpoint-/Profiling-Funktion |
| USBFS, CAN1/2, SDIO1/2, XMC, SPIM, ACC, I²S extensions | Nicht modelliert | MMIO bleibt ungemappt und wird von Renode sichtbar gemeldet |

## Bedeutende Abweichungen bewusst vermeiden

- Keine riesigen STM32-Flash-/SRAM-Fenster, die ungültige Firmwareadressen verstecken.
- Kein Cortex-M3 statt des M4-Kerns.
- Keine STM32F4-GPIO-/DMA-/RCC-Layouts an den AT32-Adressen.
- DMA2 IRQ59 und75 werden korrekt OR-verknüpft; Timer-/ADC-Shared-IRQs ebenfalls.
- Peripherie-unabhängige DMA-Transfers verwenden **Elementzahlen**, nicht fälschlich Bytezahlen.
- Bei nicht implementierten Flash-Operationen wird kein erfolgreiches Update vorgetäuscht.

## Startup-/Boardgrenzen

Voreingestellt ist Boot aus Flashbank1; BOOT-Pins werden nicht simuliert. UID ist synthetisch. Das echte Board kann externe Pull-ups, Taster, Sensoren, Motoren, Display, Leistungstreiber oder eine zweite CPU verlangen. Ohne solche modellierten Gegenstellen ist eine wartende Firmware kein Beweis für einen fehlerhaften CPU-Emulator und ein laufender CPU-Loop kein Beweis für ein funktionierendes Gesamtgerät.
