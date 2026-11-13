# Statische Pin- und ADC-Analyse der Original-MCU-Firmware

Untersuchte Datei: `mcu_firmware_v1.3.3_20260311.bin`,39.681Bytes, Ladebasis`0x08004000`, SHA-256`9bd702c8a076f29c0ac019cc7c8ea6c7afa52d13580fea04e977e3dce0a5d517`. Die nachfolgenden absoluten Adressen gelten nur für diese Datei. Analysiert wurde die Datei direkt, nicht nur das bisher beobachtete Startverhalten.

## Ergebnis

**Es gibt fest codierte Pin-Tabellen und Initialisierung.** Die fest codierte ADC-Tabelle beschreibt jedoch erlaubte Pin/Kanal-Kombinationen. Die konkret gewünschte Pin-ID wird einer Konfigurationsroutine als Argument übergeben. Der Binärcode belegt bisher keine Zuordnung „dieser Kanal ist Hotend“ oder „dieser Ausgang ist Bett-Heizung“.

Deshalb werden nur die unten belegten Fähigkeiten dokumentiert. Keine tatsächliche Thermistor-/Heizungs-Verbindung wird automatisch angelegt. Das ist keine Behauptung, dass die gesamte Firmware frei von weiteren festen Board-Defaults sei.

## ADC1: feste Fähigkeitstabelle, variable Auswahl

`0x08006520` ist eine Konfigurationsroutine:

- `0x0800652A`: `ldr r0,[r0,#4]` lädt die gewünschte Pin-ID aus dem zweiten Konfigurationsargument.
- `0x08006524` referenziert über Literal`0x080065EC` die Tabelle`0x0800CD14`.
- Die Schleife`0x0800652E–0x0800653A` sucht die Pin-ID in17Einträgen; der gefundene Index wird der ADC-Kanal.
- `0x0800654E` konfiguriert gewöhnliche Pins analog; Sonderwert`0xFE` umgeht die GPIO-Konfiguration.
- `0x08006560/66` speichert ADC1-Basis`0x40012400` und den ausgewählten Kanal im Objekt.
- Bei nicht gefundener Pin-ID ruft`0x0800656E–70` den Fehlerpfad mit Code`0x2E` auf.

Tabelle:

| ADC1-Kanal | Firmware-Pin-ID | Physischer Pin |
|---|---|---|
|0–7|0x00–0x07|PA0–PA7|
|8–9|0x10–0x11|PB0–PB1|
|10–15|0x20–0x25|PC0–PC5|
|16|0xFE|interner Temperatursensor, kein externer Thermistorpin|

Das Pin-Encoding wird durch die GPIO-Helfer bestätigt: Portindex=`pin>>4`, Bitnummer=`pin&15`; GPIO-Portbasen stehen in Tabelle`0x0800CD70`. Der allgemeine Output-Helfer`0x0800A018` lehnt ungültige Portindizes/-basen ab. Diese familienweite Tabelle ersetzt nicht die Einschränkungen des LQFP64-Gehäuses.

## ADC-Sicherheitsgrenzen sind Konfigurationsdaten

Routine`0x08005D10` findet ein bereits angelegtes ADC-Objekt. Im Bereich`0x08005D4C–74` übernimmt sie folgende Argumente:

| Argumentoffset | Beobachtete Verwendung |
|---|---|
|+0x04|Start-/Planungszeit|
|+0x08|Abstand zwischen Einzelmessungen|
|+0x0C|8-Bit-Samplezahl|
|+0x10|Wiederholungsintervall|
|+0x14|untere16-Bit-Grenze, Objekt+0x1A|
|+0x18|obere16-Bit-Grenze, Objekt+0x1C|
|+0x1C|8-Bit-Grenze für aufeinanderfolgende Bereichsfehler, Objekt+0x29|

Die Messroutine`0x08005E5C` startet/liest ADC1 und akkumuliert Samples. `0x08005EAA–B4` vergleicht den Messwert/Sample-Summenwert gegen die konfigurierten Grenzen. Bei Verletzung zählt`0x08005EFA–0x08005F0C` aufeinanderfolgende Fehler. Nach Erreichen der konfigurierten Anzahl wird, sofern nicht bereits im Fehlerzustand, bei`0x08005F16–18` der zentrale Fehlerpfad`0x08004210` mit Code`0x19` aufgerufen.

Das ist ein belegter Rohwert-Grenzcheck, **keine nachgewiesene fest codierte Celsius-Grenze oder vollständige thermische Sicherheitsfunktion**. Die Thermistorkennlinie, Bedeutung des Kanals und zulässigen Grenzen müssen aus der tatsächlichen Konfiguration stammen. Es wurden weder Fehlergrenzen deaktiviert noch Sicherheitsprüfungen umgangen.

## Weitere fest codierte Startpins

- `0x08004F90–0x08004FA4`: GPIO-Ausgangshilfsroutine erhält Pin-IDs`0x17` und`0x08`, jeweils mit Anfangswert1. Das sind **PB7 und PA8, initial High**. Ihre Boardfunktion bleibt unbekannt; High kann bei aktiver Low-Logik sogar „aus“ bedeuten. Nicht als Heizung deuten oder mit einer virtuellen Heizung verbinden.
- `0x0800500E–0x08005038`: USART1-Basis`0x40013800`; feste Pin-IDs`0x0A/0x09` entsprechen **PA10 RX / PA9 TX**.
- `0x080050D8–0x08005110`: USART2-Basis`0x40004400`; feste Pin-IDs`0x03/0x02` entsprechen **PA3 RX / PA2 TX**.
- Beide UARTs erhalten hier Baud-Divisor`0x68`; die tatsächliche Baudrate hängt von der noch unbestätigten Board-Clock-Konfiguration ab.

Ein weiterer Helfer bei`0x0800A074` verwendet fest PA7 (GPIOA-Maske`0x80`); seine Peripherie-/Boardfunktion ist nicht belegt. Auch dies wird nicht als Heizung verdrahtet. Die konfigurierbare GPIO-Tabelle umfasst familienweite Ports A–G, nicht ausschließlich die am RGT7 tatsächlich gebondeten Pins.

## Datengetriebene digitale Ausgänge

Routine`0x08005A48` liest Pin und Anfangswert aus den Konfigurationsargumenten+4/+8, ruft den GPIO-Output-Helfer`0x0800A018` auf und speichert weitere Parameter im neu erzeugten Objekt. Die anschließenden Output-Handler schreiben über im Objekt gespeicherte GPIO-Basis/Bitmaske. Damit existiert ein generischer, konfigurierbarer Ausgangspfad. Ohne zugehörige Konfigurationsdaten lässt sich nicht entscheiden, welches Objekt eine Heizung, ein Lüfter oder ein anderer Ausgang ist.

## Reproduktion und Belege

`docs/firmware-evidence/*.asm` enthält fokussierte Thumb-Disassembly mit Bytes und aufgelösten PC-Literalen. `verified-pin-capabilities.json` dokumentiert die extrahierte Tabelle und bewusst leere automatische Sensorbindungen.

```sh
python3 tools/inspect_firmware_pins.py /pfad/mcu_firmware_v1.3.3_20260311.bin
```

Das Werkzeug liest ausschließlich lokal, prüft den Firmware-Hash und ausgewählte Instruktions-/Tabellenbytes und verweigert die Anwendung dieser Offsets auf eine andere Datei. Es benötigt nur Python, verändert keine Firmware und verbindet keine Hardware.

Ergänzende Laufzeitbeobachtung: ADC1 ist nach1s ohne Hostkonfiguration noch deaktiviert, siehe VIRTUAL-PRINTER.md. Das allein war kein Beweis gegen feste Pins; die statische Argument-/Tabellenanalyse oben liefert die zusätzliche Unterscheidung.

## Unabhängige Output-Prüfung

Ein zweiter Disassembly-Durchgang bestätigt`0x08005B00`: GPIO-Basis/Bitmaske werden aus dem konfigurierten Objekt+0x18 geladen; bei`0x08005B40` wird GPIO+0x10 (Set/Reset) geschrieben. Der Callback`0x0800580D` wird anhand von DWT-CYCCNT plus einer Laufzeitdauer geplant. Das belegt zeitgesteuerte digitale Ausgänge; es reicht ohne Objektkonfiguration nicht aus, einen konkreten Heizpin oder thermischen Regelkreis zu benennen. Separater Beleg: `firmware-evidence/output-pin-independent-check.asm`.
