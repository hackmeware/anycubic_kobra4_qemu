# Virtuelle Druckerumgebung: experimentelle Bausteine

Diese Erweiterung simuliert ausschließlich Softwareobjekte. Sie spricht keine realen Heizer, Motoren, GPIO-Geräte oder Drucker an. Sie ist **noch kein vollständiges Modell der konkreten Druckerplatine**.

## Belegter Ausgangszustand der MCU-Firmware

Die bereitgestellte `mcu_firmware_v1.3.3_20260311.bin` (SHA-256 siehe VALIDATION.md) läuft ohne Sensorergänzungen eine virtuelle Sekunde ohne CPU-Fault. Der dabei oft beobachtete PC `0x08004F2C` liegt unmittelbar hinter WFI `0x08004F2A`: ein absichtlicher Interrupt-Wartezustand, kein bewiesener MMIO-Hänger.

Im read-only Register-Probe nach einer Sekunde ohne Hostbefehle:

- ADC1 CTRL1 `0x40012404` = 0, CTRL2 `0x40012408` = 0.
- ADC1 OSQ1/OSQ2/OSQ3 `0x4001242C/30/34` = 0.
- GPIOA CFGLR/CFGHR = `0x44448944` / `0x44444891`.
- GPIOB CFGLR/CFGHR = `0x14444444` / `0x44444444`.
- GPIOC CFGLR/CFGHR = `0x44444444` / `0x44444444`.

ADC1 ist damit in diesem beobachteten Startzustand deaktiviert. Fehlende ADC-Temperaturen erklären das Warten nicht. Es ist möglich, dass der Host Peripherie und Kanäle erst über sein Protokoll konfiguriert; die konkrete Bedeutung der GPIOs lässt sich aus diesen Werten allein nicht herleiten.

Die aus dem Original-Update extrahierten `sensors.cfg` und `avata_main.cfg` tragen einen binären `ACCFG1.0`-Header. Eine verifizierte Zuordnung von Thermistorkanälen, Heizpins, Endschaltern und Kennlinien liegt bislang nicht vor. Es werden daher **keine ADC-Kanäle pauschal auf plausible Werte gesetzt**, die in Wirklichkeit beispielsweise Strom-/Versorgungseingänge sein könnten.

## Isolierte Demonstration

Vom Paketverzeichnis:

```sh
renode scripts/virtual-printer-sandbox.resc
```

Im Monitor:

```text
sysbus.virtualHotend SetDutyCycle 0.5
emulation RunFor "10"
sysbus.virtualHotend TemperatureCelsius
sysbus.virtualHotend ADCValue
sysbus.virtualHotend SetDutyCycle 0
emulation RunFor "10"
sysbus.virtualHotend SetSensorFault "open"
sysbus.virtualHotend ADCValue
sysbus.virtualHotend SetSensorFault "none"
```

Die Beispiel-Heizung beginnt bei 25 °C. **40 W, 100-kΩ-NTC, B=3950 K, 4,7-kΩ-Pull-up und sämtliche Abmessungen sind illustrative Parameter**, nicht aus dieser Platine ausgelesene Werte. Das Beispiel enthält einen getrennten `sandboxADC`; reale MCU-ADC-Kanäle und GPIOs bleiben unangetastet. Die Demonstration beweist deshalb keine vollständige Druckerfunktion.

Thermisches Modell und Fault-API: siehe THERMAL.md.

## Virtuelle Mechanik und digitale Sensoren

`VirtualPrinterAxis` übersetzt steigende STEP-Flanken in eine Position. DIR wählt das Vorzeichen, ENABLE schaltet den Antrieb frei. Schrittweite, Verfahrbereich, Startposition und Polaritäten sind konfigurierbar. Es gibt keinen Motorstrom-, Drehmoment-, Beschleunigungs-, CoreXY- oder mechanischen Trägheits-Simulator.

Eingänge: 0=STEP, 1=DIR, 2=ENABLE. Ausgänge: `MinimumEndstop`, `MaximumEndstop`. Bei Überschreiten eines Endes bleibt die Position dort stehen und `LimitCollisionCount` steigt. `Stalled=true` simuliert ausbleibende Bewegung; `TotalStepPulses` bleibt beobachtbar.

```text
sysbus.virtualX OnGPIO 2 false
sysbus.virtualX OnGPIO 1 true
sysbus.virtualX OnGPIO 0 false
sysbus.virtualX OnGPIO 0 true
sysbus.virtualX PositionMillimeters
sysbus.virtualX SetPosition 0
sysbus.virtualX Stalled true
sysbus.virtualFilamentPresent Asserted false
sysbus.virtualProbe Asserted true
```

MCU-Reset deaktiviert die Achse, setzt die physische Position aber nicht zurück. `RestoreInitialPosition` ist ein ausdrücklicher Szenario-Neustart. `VirtualPrinterSwitch` besitzt eine konfigurierbare Aktivpolarität und einen dauerhaft gespeicherten logischen Zustand; MCU-Reset verändert diesen Zustand nicht.

## Anschluss an bestätigte Platinenpins

Erst nach Bestätigung müssen pro Kanal ADC-Instanz/Nummer, Heizsignalquelle, Aktivpolarität, Thermistorkennlinie und Pull-Widerstand festgelegt werden. Die Heizquelle kann ein GPIO-Ausgang oder ein passender Timerkanal sein. Da das MCU-Modell Alternate-Function-Pinrouting nicht vollständig emuliert, müssen PWM-Ausgänge gegebenenfalls direkt vom Timer verbunden werden.

Beispielsyntax, **keine gültige Pinbelegung dieser Platine**:

```text
myThermal: AT32.VirtualPrinterThermal @ sysbus
    adc: adc1
    channel: 0

gpioA:
    0 -> myThermal@0

myAxis: AT32.VirtualPrinterAxis @ sysbus
    MinimumEndstop -> gpioB@0

gpioC:
    0 -> myAxis@0
    1 -> myAxis@1
    2 -> myAxis@2
```

Für die konkrete Maschine diese Platzhalter durch belegte Verbindungen ersetzen. Die Analog-Kanalnummer ist keine GPIO-Pinnummer; außerdem sind beim LQFP64 nur PA0–15, PB0–15, PC0–15 und PD0–2 verfügbar. Sensoren für Filament, Tür und Probe erhalten ihre Bedeutung durch die bestätigte Boardverdrahtung, nicht durch einen frei gewählten Objektnamen.

## Was noch fehlt

- Authentifizierte/dekodierte Boardkonfiguration und tatsächliche Thermistor-/Heater-/Stepper-/Endstop-Zuordnung.
- Originales Hostprotokoll einschließlich Initialisierung, Status und Fehlerreaktionen.
- Weitere Geräte wie Drucksensor/IMU/Treiber-UART/Lüfter-Tacho/EEPROM, soweit die Firmware sie wirklich erwartet.
- Vergleich des virtuellen Verhaltens mit dem echten Gerät.

Eine erfolgreiche thermische Rechnung und eine wartende MCU ersetzen diese Nachweise nicht. Diese Umgebung darf nicht als Nachweis der Sicherheit realer Heizregelung verwendet werden.

## Laufzeitbeobachter und neu belegte STEP/DIR-Signale

`OBSERVER.md` beschreibt den rein lesenden CSV-Beobachter und die offline nutzbare HTML-Wiedergabe tatsächlicher Komponentenwerte. Das mitgelieferte Beispiel ist ausdrücklich ein synthetischer Komponententest, kein Firmware-Druck.

`STEPPER-BINDINGS.md` dokumentiert aus Firmware und initialisiertem SRAM belegte STEP/DIR-Paare. Die Zuordnung zu X/Y/Z, Schrittweite, Enable-Signal und mechanischer Transformation ist weiterhin offen; es werden keine Verbindungen aus unvollständigen Annahmen automatisch hergestellt.
