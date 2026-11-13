# Schnellstart

Dieses Paket enthält den getesteten RV1106-QEMU für **Linux x86_64** sowie deine aus `uboot.img` extrahierte U-Boot-Datei mit dem unveränderten Control-DTB. Für Windows/macOS/ARM-Hosts oder ältere Linux-Systeme bitte den Quellcode-Build aus README.md verwenden. Getestet wurde Debian 13; der fertige Linux-Build benötigt mindestens glibc 2.38. Die Laufzeitbibliotheken sind in README.md beschrieben.

Im entpackten Ordner starten:

```sh
python3 tools/run_console.py firmware/u-boot.bin --qemu ./bin/qemu-system-arm --enable-console-debug
```

Nach der Debug-Bestätigung gegebenenfalls Strg-C und Enter drücken. Dann funktionieren beispielsweise:

```text
version
printenv
help
```

Deine Firmware schaltet ihre Konsole intern ab. Deshalb ist `--enable-console-debug` ausdrücklich erforderlich: Es löscht ausschließlich das Console-Disable-Flag im flüchtigen Gastspeicher. **Die Firmwaredatei und ihr DTB bleiben unverändert.** Ohne diese Option läuft dieselbe Firmware, liefert aber keine serielle Ausgabe. Diese Freigabe ist für die SHA256 deiner konkreten Datei gesperrt und wird nicht blind auf andere Images angewandt.

Beenden: Prozess mit SIGTERM aus einem zweiten Terminal beenden oder den Aufruf für einen zeitlich begrenzten Test mit `timeout 60s` starten. Die reine UART-Konsole hat keinen QEMU-Monitor-Hotkey.

## USB-Autoupdate

Deine laufende Firmware bietet den Befehl `usb_update`. Das gelesene Default-Environment enthält jedoch:

```text
bootcmd=boot_fit;boot_android ${devtype} ${devnum};
bootdelay=0
```

Kein `preboot`-Eintrag ruft das Update auf. Beim beobachteten Normalstart wurden Breakpoints auf dem `usb_update`-Handler nicht getroffen. Das gilt für diesen Start ohne USB-Stick und ohne gespeichertes Geräte-Environment.

**Dieses Paket hat noch keinen funktionsfähigen USB-Host oder USB-Stick.** Es kann daher keinen vollständigen USB-Update-Test ersetzen. Auch SD/eMMC melden bewusst „keine Karte“. Keine echte Hardware und keine Datenträger werden beschrieben. Für genaue Testgrenzen und Protokolle siehe TESTED.md und test-results/.

## Andere U-Boot-Versionen

FIT zuerst mit tools/rv1106_image.py untersuchen und extrahieren (tools/README.md). Bereits normalisierte Raw-Dateien starten bei 0x00200000; ARM-ELF verwendet seinen Entry Point. Nicht jede Board-/U-Boot-Konfiguration ist abgedeckt. Details und Eigenbau: README.md und MODEL.md.
