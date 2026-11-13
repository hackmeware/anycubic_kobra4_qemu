# Kobra 4: neuer diagnostischer Starter

Arbeitsstand, noch keine vollständige startfertige Firmware-Import-Lieferung.
Dieser Starter verwendet getrennte, vom Nutzer lokal bereitgestellte Firmware-Eingaben und passende Emulator-Laufzeiten. Er verändert keine Original-Firmwaredatei und startet keine physische Hardware.

## Nachgewiesen

- Ein neuer isolierter Offline-Lauf des zugrunde liegenden R9-Starters erreicht die Linux-Shell `RV1106_OFFLINE_USERSPACE_READY` und BusyBox 1.27.2.
- Main- und Nozzle-MCU initialisieren; UART-Ausgabe und Abschlussdaten liegen vor. 30 Sekunden Beobachtung, 48,25 Sekunden Hostlaufzeit, Exit 0.
- `prepare_diagnostic.py` erzeugt aus den bekannten privaten Kernel-/DT-Eingaben die vorhandenen 128-MiB-Diagnose-DTB- und ELF-Dateien bytegenau erneut.
- Drei Schutztests prüfen bereits vorhandene Ausgabeverzeichnisse, Symlink-Ausgabeziele und unbekannte Vorlagen.
- Der portable Starter selbst hat einen bestandenen Plan- und Ausführungstest: 47,03 Sekunden, Exit 0, neuer DT/ELF, abgeschaltetes Netzwerk, unveränderte Eingaben und bestätigte eigene Prozessbereinigung. Insgesamt sieben Schutztests bestanden.

## Voraussetzungen

- Linux x86-64, Python 3.11 oder neuer.
- `unshare` mit zugelassenen unprivilegierten Benutzer-, PID- und Mount-Namespaces. Bei abgeschalteter Netzwerkfunktion zusätzlich Netzwerk-Namespaces. Der Starter bricht ab, wenn diese Isolation nicht möglich ist; er ändert keine Systemeinstellungen.
- Mindestens ungefähr 2 GiB freier Arbeitsspeicher für den nachgewiesenen Zwei-MCU-Test; der neue Überwacher setzt ein gesampeltes 4-GiB-Limit für den gesamten privaten Prozessraum. Das ist kein kernelbasierter cgroup-Hardlimit.
- Passender privater R9-Scalar-QEMU samt zugehörigem Loader/Bibliotheken und Renode 1.17.0 portable einschließlich Abhängigkeiten. Ein normales QEMU-Paket ist kein austauschbarer Ersatz für das RV1106-Modell.
- Vollständiger Modell- und Quellbaum; separate private Eingaben `offline-emmc.img`, `mcu.bin`, `nozzle.bin`, `kernel-zImage`, `kernel-board-dtb.dtb`, `disk-layout.json`.
- Das Systemabbild benötigt den dokumentierten diagnostischen `/emulation-init.sh`-Hook. Eine unveränderte Hersteller-SWU allein erfüllt diese Voraussetzung noch nicht.

## Bedienung

`python3 start_diagnostic.py --help` beschreibt die expliziten Pfade. Ohne `--execute` wird lediglich ein neuer Startplan einschließlich vorbereiteter privater Boot-Dateien erzeugt. Jede Ausführung benötigt ein neues Ausgabeverzeichnis.

Der Plan hat standardmäßig `--network off`. Ein tatsächlicher Start benötigt zusätzlich `--execute`. Kein alter Lauf wird gesucht, beendet oder übernommen.

Neue Ausgaben enthalten:
- `RUN-PLAN.json`: tatsächliche Argumente und Eingabe-Hashes.
- `boot/PREPARATION.json`: Ableitung und Hashes der Bootdateien.
- `launcher.log` und `logs/`: Starter- und Emulatorbelege.
- `SUPERVISOR.json`, `EXIT.json`: Zeit-/Speichergrenzen, Status und Nachprüfung unveränderter Originale.

Die Bootdateien und Laufdaten enthalten Firmware oder daraus abgeleitete Inhalte. Sie sind privat zu halten und gehören nicht in GitHub oder Quellpakete.

## SLIRP

Die geplanten Modi heißen `off`, `isolated` und `internet`. Die aktivierten Modi nutzen QEMU-Benutzernetzwerk und USB-Ethernet, kein TUN/TAP und keine Host-Firewalländerung. `isolated` setzt `restrict=on`, `internet` setzt ausdrücklich `restrict=off`. Optionale HTTP-/MQTT-Weiterleitungen binden ausschließlich an `127.0.0.1`.

Dies ist USB-Ethernet, kein echter WLAN-Chip. Im tatsächlichen isolierten Gasttest registriert Kernel 5.10.160 über cdc_ether die Schnittstelle eth0, DHCP vergibt 10.0.2.15/24 und Pakete werden ausgetauscht. Der Test endet normal mit Exit 0 und unveränderten Eingaben. Die vorhandene DHCP-Hilfe scheitert noch am Schreiben der schreibgeschützten resolv.conf; DNS-Korrektur ist in Arbeit. Drei USB-Control-Warnungen wurden protokolliert. Internet, Hostweiterleitungen, Hersteller-Cloud, WLAN und App-Anmeldung sind damit nicht nachgewiesen. Der Starter aktiviert keine TFTP-Freigabe und liefert keine Zugangsdaten.

## Grenzen

Der neue Diagnoseplan startet zwei MCUs ohne gekoppelten Kalibrierungstakt. Motor-MCU, UI, originale Hersteller-Daemons, Druck, vollständige Kalibrierung und persistente Gaständerungen sind damit nicht nachgewiesen. QEMU nutzt `snapshot=on`; Gastschreibzugriffe werden beim Ende verworfen.

Der Zeitwächter bittet zunächst über eine neue Stop-Datei um Ende, danach beendet er ausschließlich seine eigenen Prozesse im privaten PID-Raum. Ein erzwungenes Ende ist kein erfolgreicher Test.

## Fehlerbehebung

- **Namespace nicht erlaubt:** Hostvoraussetzung fehlt. Keine Sicherheitsoption automatisch lockern; auf einer geeigneten Linux-Installation testen.
- **Scalar baseline hash mismatch:** Falsches QEMU-Binary, auch wenn Versionsnummer oder Dateiname ähnlich ist.
- **Diagnostic recipe mismatch:** Quellvorlage geändert. Nicht den Hash blind ersetzen; die Änderung prüfen.
- **Kein Userspace-Marker:** Kernel/DTB, Partitionslayout und diagnostischen PID1-Hook prüfen. Ein vorhandener ELF ist kein Bootnachweis.
- **Kein `eth0`:** Gerätebaum, USB-Modell und Gasttreiber prüfen. WLAN-Dateien nicht als Ersatz für den USB-Ethernet-Treiber behandeln.
- **Zeit- oder Speichergrenze:** Belege behalten, Ursache prüfen. Nicht ohne Begründung unbegrenzte Läufe starten.

## Veröffentlichung

Dieses Dokument ist eine technische Arbeitsdokumentation, keine Lizenz für Firmware. Ein separates GitHub-Paket benötigt noch den zugesagten Audit auf private Pfade/Metadaten, Gerätezustand, Zugangsdaten und konkrete Quell-/Binärlizenzen. Es wurde nichts veröffentlicht. Anonymität wird nicht zugesichert.
