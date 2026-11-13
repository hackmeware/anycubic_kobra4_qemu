R5: Getrennte Integration des Runtime-Manifests

Basis: vollständiger verfügbarer Offline-Prüfbaum libfile_db5b514fd8f881a4aaa87692d3cc3d3b. Neue lokale Instanz: /workspace/scratch/ca95ca5f55d9/c22_stop_event_instance_r5_20261111. Original R3 bleibt bytegleich gemäß seiner Pins. Kein alter Prozess wurde angefasst. Keine Emulation in R5 gestartet.

In der bestehenden Produktionsfunktion runner.verify_manifest integriert:
- Runtime-Manifest enthält weiterhin 5489 reguläre Dateien und die unveränderten Regeln für Symlinks und fehlende Symlinkziele.
- Exakt zwei explizite historische RESC-Ausnahmen einschließlich Originalhashes, fest in Runner und Manifest abgeglichen.
- Historisches vollständiges Manifest außerhalb des Runtime-Baums unverändert archiviert; historische Vollständigkeit ausdrücklich false.
- Beide exakt rekonstruierten historischen REPL-Dateien physisch in der neuen Instanz vorhanden und gepinnt.
- Exakte Mitgliedschaft der neun direkten Generator-Eingabeverzeichnisse für .cs/.repl/.resc. Zusätzliche passende Eingaben scheitern vor dem Start. Bestehende kanonische Pfad- und Inhaltsprüfungen unverändert erhalten.
- Abhängige Hash-Pins in Runner, Wrappern, Vertragsdateien und Kontrollen aktualisiert; kein weiterer Admission-Mechanismus eingeführt.

Nachweise: tatsächliche Produktionsfunktion erfolgreich auf allen 5489 Dateien; negative Tests mit Zusatzdateien aller drei Endungen, fehlenden/geänderten Dateien, internen Symlink-Vorfahren, verfälschter Mitgliedschaft und geänderten Ausnahmen. Drei Auswahlketten-Testgruppen und vier Isolationstestgruppen bestanden. Reale Offline-Modellvorbereitung mit execution_args und shared_mcu.prepare für scalar und stop-event erfolgreich; nur der abschließende Emulatoraufruf wurde durch Offline-Vorbereitung ersetzt. Keine QEMU-/Renode-Ausführung. Beide Auswahlvarianten behalten icount=0 und 1-ms-Kopplung bei.

Default scalar unverändert. Stop-Event ausschließlich explizit per C22_STOP_EVENT_OPT_IN=1. Widersprüche werden abgelehnt. launch_c22.sh bleibt gesperrt (Exit 78), unabhängige Begutachtung steht aus. Keine Aussage, dass komplette Kalibrierung nun schneller oder erfolgreich ist.

Delta anwenden: In eine NEUE Instanz am oben angegebenen R5-Pfad aus dem Basisarchiv profile/ als calibration-native-fast4-c22-stop-event/ und controls/ als sensor_run_check/native-fast4-c22-stop-event/ kopieren; dann ausschließlich dort die Delta-Dateien darüberlegen. Historische Daten nicht in bestehende Läufe hinein entpacken. Die konkreten absoluten Pfade im Profil sind gepinnt; andere Zielpfade benötigen erneute Relokation und Repinning. R5-DELTA-MANIFEST.json nennt jede geänderte Quelldatei und alle Paket-Hashes. Testprogramme liegen auf Wurzelebene.

Rücknahme: Die neue R5-Instanz nicht benutzen; Original R3 wurde nicht verändert. Kein alter Lauf wird beendet oder wiederaufgenommen. Offline-Testausgaben sind kein fortsetzbarer Kalibrierungssnapshot.
