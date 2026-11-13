Kobra 4: firmwarefreie lokale Diagnose-Input-Vorbereitung

Getestet am 12.11.2026: Die echte K4_1.2.1.3.swu wurde lokal entschlüsselt;
alle drei MCU-Dateien, FIT-Kernel/DTB und vier OTA-Images wurden anhand der
bekannten Projekt-Hashes geprüft. Aus dem enthaltenen app-Verzeichnis wurden
app.ext4 sowie leere userdata.ext4/data.ext4 gebaut. Alle Nutzdateien,
Symlinks, Typen, Modi und UID/GID wurden gegen R9 verglichen; e2fsck -fn war
für alle drei Dateisysteme sauber. Das System enthält die zwei ausdrücklich
benannten Diagnoseänderungen des früheren R9, keine zusätzlichen Binärpatches.

NICHT behauptet: identische alte ext4/SquashFS-Metadaten, identischer alter
Disk-Hash, Hersteller-Signaturauthentizität, vollständige Kalibrierung oder
Live-Boot. ACTUAL-PREPARATION-TEST.json hält die tatsächlichen neuen Hashes
fest. Neue Aufbauten können neue Metadatenhashes erhalten. Der Starter muss
die frisch erzeugten Hashes als neues Profil verwenden, nicht alte Pins
überschreiben oder Prüfungen blind abschalten.

Linux x86_64, Python 3.11+, vertrauenswürdige Hostprogramme e2fsprogs und
squashfs-tools nötig. --tools-root / verwendet vorhandene /usr/sbin/mke2fs,
/usr/sbin/debugfs, /usr/sbin/e2fsck und /usr/bin/mksquashfs. Isolierte offizielle
Debian-Pakete wurden im Test verwendet; Versionen: e2fsprogs 1.47.2-3+b12,
squashfs-tools 1:4.6.1-1. Paketdatei-Hashes siehe HOST-TOOLS-SHA256.txt.
Die Programme/Pakete selbst sind NICHT mitgeliefert. Kein sudo, Mounten oder
Systeminstallieren im Importer. Bei isolierten Bibliotheken muss deren
LD_LIBRARY_PATH vor dem Aufruf gesetzt werden.

Lokal (neues, noch nicht vorhandenes Ausgabe-Verzeichnis):
  python3 prepare_swu.py --swu /pfad/K4_1.2.1.3.swu --output /pfad/kobra-import --tools-root /

Optionaler Download ausschließlich von einer selbst geprüften HTTPS-URL:
  python3 prepare_swu.py --url 'https://HERSTELLER/EXAKTE-DATEI.swu' --sha256 ba1938de6241e6918f4ab19450e2a5aa876ceb71a35fc038080026839a975c19 --output /pfad/kobra-import --tools-root /

Die URL oben ist bewusst ein Platzhalter, keine behauptete Herstellerquelle.
Der Download ist begrenzt, prüft öffentliche Zieladressen/TLS und akzeptiert
nur den bekannten SWU-Hash. Kein Netztest des echten Downloadpfads durchgeführt;
der lokale reale Import wurde getestet. Passwort nur interaktiv am Terminal,
kein Standardpasswort, keine Speicherung. Bei abweichendem Hash/Layout Abbruch.
Keine automatische Suche, keine Firmware- oder Update-Skriptausführung.

Ergebnis: output/prepared/inputs sowie PREPARED-INPUTS.json.
Die Disk ist eine synthetische 512-MiB-GPT-Emulator-Disk. env/idblock/misc
bleiben wie im Referenzprofil leer. NIEMALS auf physische Hardware flashen.
Das zusätzliche /emulation-init.sh öffnet lediglich eine Offline-Diagnoseshell;
es startet NICHT selbst die Herstellerdienste. S80_wifi_connect wird durch
einen Offline-Hinweis ersetzt. In app/start.sh werden ausschließlich die
bekannten wpa_supplicant/udhcpc-Zeilen im Speicher ersetzt, Vor-/Nachhash
geprüft. Netzwerkfreigabe/SLIRP gehört in den getrennten Starter.

Sicherheit: Nur exakt gepinnte Archive/Bilder werden geparst. Keine generische
Tar-Extraktion; Dateien/Verzeichnisse zuerst, geprüfte Symlinks zuletzt.
Absolute Gastsymlinks im System werden nicht auf dem Host verfolgt.
Ausgaben privat halten: Sie enthalten nach dem Import Firmware, Hersteller-
Konfigurationen und mögliche Herstellerkennungen. Keine Weitergabe der
Ausgaben empfohlen. Dieses Quellpaket enthält keine Firmware, Bibliotheks-
Binärdateien, Original-Herstellerskripte, Firmwarepasswörter oder private Keys.
Hashes beweisen hier Kontinuität mit dem gesicherten Projekt, nicht allein
Herstellerauthentizität. Firmware-Lizenzen müssen aus der selbst beschafften
Quelle geklärt werden; keinerlei Weiterverbreitungsrecht wird behauptet.

Eigene kleine Diagnosehooks stammen aus dem gesicherten Emulatorprojekt.
Profile enthalten nur Metadaten/Hashes/Pfade, keine Herstellerdateiinhalte.

Vertrauensgrenze: Die mitgelieferten JSON-Profile, Diagnosehooks und Hosttools
sind vertrauenswürdiger Programmcode/Konfiguration, keine beliebigen Eingaben.
Das Disklayout ist zusätzlich per SHA256 fest gebunden; andere Layouts werden
vor dem Erstellen einer Disk abgelehnt. Profile nicht ungeprüft ersetzen.
