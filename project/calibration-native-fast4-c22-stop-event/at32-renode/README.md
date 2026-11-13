# AT32F403ARGT7 für Renode

Ausführbares, quelloffenes **Funktionsmodell**, kein vollständiger oder zyklengenauer Silizium-Digitalzwilling. Ziel: unveränderte Cortex-M-Firmware starten, Register-/Interrupt-Verhalten testen und simulierte Geräte anschließen. Getestete Laufzeit: **Renode 1.17.0 portable (.NET)**.

## Schnellstart

Aus diesem Verzeichnis:

```sh
renode scripts/load.resc
```

Im Renode-Monitor für eine ELF-Datei:

```text
sysbus LoadELF @/pfad/firmware.elf
showAnalyzer sysbus.usart1
start
```

Für eine rohe Binärdatei müssen **Ladeadresse und Vektortabelle zur Firmware passen**. Für die untersuchte `mcu_firmware_v1.3.3_20260311.bin`:

```text
sysbus LoadBinary @/pfad/mcu_firmware_v1.3.3_20260311.bin 0x08004000
sysbus.cpu VectorTableOffset 0x08004000
sysbus.cpu SP 0x20008000
sysbus.cpu PC 0x08008099
showAnalyzer sysbus.usart1
start
```

Diese Datei ist eine Anwendung hinter einem 16-KiB-Bootloader, kein vollständiges Flash-Abbild. Der Bootloader ist nicht enthalten. Das Modell startet die Anwendung direkt; dadurch werden eventuell vom echten Bootloader vorbereitete Zustände nicht rekonstruiert. Siehe `docs/VALIDATION.md` für die tatsächlich erreichte Ausführung, nicht für einen unbelegten vollständigen Funktionstest des Geräts.

## Enthalten

- Cortex-M4, NVIC, SysTick, 1 MiB Flash mit Boot-Alias, standardmäßig 96 KiB SRAM, SRAM-/Peripherie-Bitbanding.
- CRM mit Oszillator-Ready-Flags, PLL/Bus-Dividern, Clock-Status, Interruptflags, Peripherie-Reset und dynamischen Timer-/UART-/DWT-Takten.
- GPIO A–E, IOMUX/EXINT und acht UART/USART-Instanzen.
- Vier SPI, drei I²C mit echten Renode-Geräteverbindungen, programmierbare CRC.
- Zwei DMA-Controller mit je sieben Kanälen und korrekt zusammengefassten Interrupts.
- Timer 1–14, drei ADC, zwei DAC-Kanäle, RTC/Backup-Register sowie unabhängiger und Fenster-Watchdog.
- DWT-CYCCNT für Firmware-Warteschleifen, synthetische UID, korrekte Chip-ID und Flashgrößenkennung.
- Quellcode, reproduzierbare Tests, selbst erzeugte Minimal-Firmware und dokumentierte Grenzen.

**Nicht enthalten:** USBFS-Stack/Controller, CAN, SDIO, XMC, SPIM-Flash, Boot-ROM, ACC, physikalische I²S-Signale. Nicht implementierte Adressen bleiben sichtbar ungemappt; es gibt keine universelle RAM-Attrappe, die Erfolg vortäuscht.

## Hardwarekonfiguration

Der RGT7 ist LQFP64: PA0–15, PB0–15, PC0–15 und PD0–2 sind die 51 herausgeführten GPIOs. Die GPIO-D/E-Register existieren als Registerblöcke, aber zusätzliche Pins sind an diesem Gehäuse nicht nutzbar. Remap-Register sind kein vollständiges elektrisches Pin-Multiplexermodell.

HEXT ist eine **Boardannahme von 8 MHz**, kein Bestandteil der Chipbezeichnung. Ändere `hextFrequency` in der Plattform passend zur Platine. Die Reset-Systemfrequenz beträgt 8 MHz; CRM berechnet die später von Firmware eingestellten Taktraten. CPU-Ausführungsleistung in Renode ist trotzdem nicht zyklengenau.

Der Chip kann über Option Bytes 224 KiB statt 96 KiB SRAM bereitstellen. Die Standardplattform bildet den **96-KiB-Resetmodus** ab. Eine separate 224-KiB-Variante befindet sich unter `platforms/at32f403argt7-224k.repl`. Sie ist eine Hostkonfiguration; Option-Byte-Programmierung ist nicht implementiert.

## Analoge Eingänge und externe Geräte

ADC-Werte sind bewusst explizit injizierbare 12-Bit-Rohwerte:

```text
sysbus.adc1 SetChannelValue 0 2048
sysbus.adc1 SetChannelValue 1 4095
sysbus.gpioA OnGPIO 0 true
sysbus.usart1 WriteChar 65
```

GPIO-Eingang freigeben: `sysbus.gpioA ReleasePin 0`. UART-Idle-Ereignis explizit injizieren: `sysbus.usart1 SignalIdle`.

SPI-Geräte werden als `ISPIPeripheral` unter dem gewünschten SPI-Controller registriert; I²C-Geräte als `II2CPeripheral` an der jeweiligen Adresse. Reproduzierbare Beispiele mit simulierten Gegenstellen stehen in `tests/BusPeripheralTests.cs` und `tests/bus.repl`. Es wird kein reales angeschlossenes Board-Gerät erfunden.

## Tests

`tests/setup-runtime.sh` lädt die offizielle, festgelegte Renode-Version und installiert die Python-Testabhängigkeiten in ein lokales Verzeichnis. Alternativ vorhandenes Renode über die in den Runnern beschriebenen Umgebungsvariablen nutzen.

```sh
./tests/setup-runtime.sh
./tests/run.sh
./tests/run-bus.sh
python3 tests/run-io.py
```

Weitere Suites und genaue Kommandos: `docs/VALIDATION.md`. Die mitgelieferte `firmware/smoke.bin` lässt sich allein mit Python über `firmware/make_smoke.py` regenerieren; kein ARM-Compiler erforderlich.

## Wesentliche Grenzen

- Flash ist ausführbarer Speicher für geladene Firmware. Hardware-Schreibschutz und echte Flashprogrammierung sind **nicht** modelliert. Der Flashcontroller unterstützt Start-/Unlock-/Statuspfade; Erase-/Program-Befehle werden ausdrücklich mit Fehlerflag abgelehnt. Direkte Speicherwrites sind in Renode technisch weiterhin möglich. Nicht zur Validierung eines Flash-Updaters oder von Schutzmechanismen einsetzen.
- Peripherie-Clocks werden berechnet, aber Clock-Gating und Spannungs-/Sleep-Modi sind nicht vollständig umgesetzt.
- UART/SPI/I²C/DMA-Konvertierungen erfolgen funktional, nicht als bitgenaue Leitungssimulation. DMA-Arbitrierung, Buslatenzen und elektrische Fehler sind keine Modellgarantie.
- ADC liefert deterministische Samples, keine analogen Spannungs-/Rausch-/Temperaturkurven. Trigger-, Continuous-/Multi-ADC-Modi sind nur im dokumentierten Umfang abgebildet.
- Timer verwenden Renodes STM32-Funktionsmodell mit AT32-Anpassungen. Fortgeschrittene Motorsteuerung, komplementäre Ausgänge, Deadtime und automatische Pinzuordnung sind keine Vollabdeckung.
- UID-Werte sind synthetisch. Sie stellen kein reales Gerät und keine Sicherheitsidentität dar.

Detailumfang: `docs/COVERAGE.md`, `docs/BUS-PERIPHERALS.md`, `docs/EXTRAS.md`, `docs/IO.md` und `docs/SOURCES.md`.

## Zusammen mit einer RV1106-Emulation

Die UART-Modelle sind Renode-UART-Endpunkte und können an einen Host-Socket/PTY und darüber an einen QEMU-Chardev angeschlossen werden. Das verbindet Bytes, synchronisiert aber nicht automatisch die virtuellen Uhren beider Emulatoren. Welche MCU-UART, RV1106-UART und Protokollvariante das reale Board verwendet, muss aus der Platine/Firmware bestätigt werden. Der Hardware-RX-Puffer ist standardmäßig ein Byte; bei ungetakteten Hostbursts sind Overruns möglich. Größere `receiveFifoDepth`-Werte sind eine explizite Hosttransport-Erweiterung und kein Hardwaremerkmal.

## Neu: virtuelle Druckerumgebung

`scripts/virtual-printer-sandbox.resc` startet eine isolierte Heizung/NTC-/Lüfter- und Step/Dir-/Endschalter-Demonstration. Temperatur beginnt bei25°C, reagiert auf die virtuelle Leistung und wird über eine konfigurierbare NTC-Kennlinie in ADC-Werte übersetzt. Open/Short-Fehler sind injizierbar. Mechanische Position und thermische Fehler überleben einen MCU-Reset.

**Keine bestätigte K4-Pinbelegung:** Nach1s Originalfirmware sind die ADC-Kanalregister noch deaktiviert. Die Sandbox weist daher keine erfundenen Thermistorkanäle oder Heizpins zu und ersetzt das Hostprotokoll nicht. Details, Schnittstellen und offene Punkte: `docs/VIRTUAL-PRINTER.md` und `docs/THERMAL.md`.

## Nachtrag: direkte Firmware-Pinanalyse

`docs/FIRMWARE-PINS.md` unterscheidet belegte feste Pin-/ADC-Tabellen, feste Startpins und über Konfigurationsargumente ausgewählte Pins/Grenzwerte. Die Behauptung „beim Start kein ADC, also keine festen Pins“ wäre zu weitgehend; die zusätzliche statische Analyse ist mit Bytes/Adressen und lokalem Verifikationsscript reproduzierbar. Bislang keine belegte Hotend-/Bett-Zuordnung, daher keine automatische Heizerverdrahtung.

### Kobra-Taktprofil

Für die bereitgestellte Kobra-Main-Firmware steht `scripts/load-kobra4.resc` bereit: HEXT 24 MHz ergibt den vom Originalhost erwarteten 120-MHz-Kerntakt. Das generische Chipmodell behält 8 MHz. Die PCB-Quarzfrequenz ist aus Firmware/Host-Verhalten abgeleitet, nicht physisch verifiziert. Details und Grenzen unabhängiger Simulationsuhren: [KOBRA-CLOCKS.md](docs/KOBRA-CLOCKS.md).
