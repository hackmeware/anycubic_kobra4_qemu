Host-JIT-Wiederholung und R7-Opt-in, 11.11.2026

Messung wiederholt
Gleicher nativer 20-ms-Präfix, unveränderte Firmware/Modelle/MCU-Uhren, default scalar. Zwei Paare mit wechselnder Reihenfolge:
1. Referenz → single-tier: Laden+Präfix 52,608 → 44,777 s (14,89 % kürzer), Präfix-CPU 18,58 → 9,85 s.
2. single-tier → Referenz: Referenz 54,486 s, single-tier 47,760 s (12,34 % kürzer), Präfix-CPU 24,48 → 12,89 s.
Beide Endpunkte 20.000.000 ns, alle vier Renode-Abschlüsse nach Pause per quit mit Exit 0. Kein Watchdog ausgelöst, alle eigenen Prozesse reapet. Das stützt einen kleinen kalten Host-Startgewinn, nicht eine allgemeine Beschleunigung der vollständigen Kalibrierung. Es sind zwei Paare, keine statistische Langzeitqualifikation.

Motor-SRAM lokalisiert
Die auffälligen Bytes liegen in den Wörtern 0x20000660 und 0x20000664. Eine vorhandene Analyse wurde gegen dieselbe Motor-Firmware mit SHA256 76b439293ab08207317007f5179243a0684c1b27668442781bcb2e201ff62661 offline erneut ausgeführt; 63 historische Quellen/Captures verifiziert, bytegestützte Thumb-Decodierung über bereits installiertes LLVM. Einzige Änderung am Analysewerkzeug: Default-Profilpfad für seinen neuen Speicherort; das Profil wurde explizit übergeben.

Belegte Operationen: Eintrittsroutine 0x0800d358 erhöht die Verschachtelung in 0x20000668 und speichert beim Übergang 0→1 DWT CYCCNT aus 0xe0001004 nach 0x20000660. Austritt 0x0800d37c verringert die Tiefe und addiert beim Übergang 1→0 die Zyklusdifferenz nach 0x20000664. Eine weitere Routine berechnet daraus Prozentwerte und setzt den Akkumulator zurück. IRQ-Lastauswertung ist eine begründete Funktionsinterpretation, kein wiederhergestellter Symbolname. Spätere Steuerungsrelevanz ist nicht vollständig ausgeschlossen.

Aktuelle unveränderte Referenzen variieren bereits: Eintrittszeitwort 0x00455c1c / 0x00455c40 / 0x00455c5f und Akkumulator 0x0006a88f / 0x0006baf5 / 0x0006ac20. Kandidatenwerte liegen in diesem kleinen beobachteten Referenzbereich. Alle aktuellen Verschachtelungstiefen sind 0. Das beweist weder Harmlosigkeit noch vollständige Äquivalenz; es gibt KEINEN neuen tolerierten Diff-Filter. comparison.json enthält jede konkrete Aufnahme und beide Wörter.

Weitere Zustandsgrenzen
Erstes Paar: alle 33 CSV-Traces gleich, Main-/Nozzle-SRAM-Ausschnitte gleich, drei Motorbytes unterschiedlich. Zweites Paar: 32/33 CSV-Traces gleich; physical-state.csv weicht im Beobachtungszeitpunkt ab. Wenige Main-/Nozzle- und Motor-SRAM-Bytes unterscheiden sich ebenfalls. Die Messung sichert nur die ersten 16 KiB SRAM je MCU und wenige frühe Traces. Kein Gesamtzustandsbeweis, keine Aussage zur späten Bett-PID-Phase. Historische Disassemblierungsberichte beschreiben zusätzliche damalige Stack-Captures; diese wurden nicht als neue aktuelle Captures ausgegeben.

Separate Opt-in-Integration
Neue Instanz: c22_host_jit_optin_r7_20261111. Basis ist R5, nicht der auf 20 s gekürzte R6-Teststarter. Produktions-Beobachtungsdauer, 1-s-Bootstrap und bestehende Launcher-Sperre bleiben erhalten. Kein Langlauf gestartet.
RENODE_HOST_JIT=single-tier wird in runner.environment und observer.fixed_environment geprüft/weitergereicht, im Fixture validiert und als --renode-host-jit single-tier an run_link übergeben. Erst am tatsächlichen Renode-Popen wird eine KOPIE seiner Umgebung um DOTNET_TieredCompilation=0 ergänzt. QEMU und der Elternprozess erhalten keine Änderung. Default ist default und lässt die bisherige Renode-Umgebung unverändert. Ungültige Auswahl und konfliktierende DOTNET-/COMPlus-TieredCompilation-Werte werden abgelehnt. renode-host-runtime.json protokolliert die tatsächlich an Renode gewählte Hostoption.

Aktivierung nach Review: RENODE_HOST_JIT=single-tier für den bestehenden Instanzstarter setzen. Deaktivierung: Variable weglassen oder default. Dies öffnet nicht die vorhandene Langlauf-Sperre. Kein globaler export nötig; kein Ändern der Runtimeconfig-Datei, Firmware oder virtuellen Zeiten.

Offline-Prüfungen: vollständige echte Runner→Observer→Shell→Parser/Transportauswahl für beide Clock-Modi und beide JIT-Auswahlen; ungültige Werte vor Erstellung des Laufverzeichnisses abgelehnt; private Kindumgebung und Konflikte geprüft; tatsächliche Popen-Verdrahtung statisch geprüft. Sieben Auswahl-/Umgebungstestgruppen, zwei Runtime-Manifest-Testgruppen, vier Isolationstestgruppen. Alle 5489 Runtime-Dateien und sämtliche Instanzpins verifiziert. Tests der Integration sind offline; die gemessenen nativen Varianten verwendeten das äquivalente Host-Flag direkt, noch keinen R7-Vollstart.

Kein älterer Lauf/Prozess oder ursprüngliches Profil verändert. R7 ist ein experimenteller Opt-in-Kandidat, kein neuer Standard. Der 180-s-Startupengpass ist damit noch nicht nachweislich beseitigt. Ein begrenzter längerer Präfix bzw. tatsächlicher Bootstrap unter dieser Option ist der nächste praktische Schritt, bevor eine vollständige Kalibrierung zugesagt wird.

Wiederherstellung: Das Paket ist ein Delta, kein vollständiges historisches Archiv. Eine NEUE Kopie des vollständigen Offline-Baums (libfile_db5b514fd8f881a4aaa87692d3cc3d3b) mit dem R5-Delta (libfile_ec05c5a7ab6081a4959434062051c422) am im PACKAGE-MANIFEST genannten R7-Pfad aufbauen; profile/ wird calibration-native-fast4-c22-stop-event/, controls/ wird sensor_run_check/native-fast4-c22-stop-event/. Dann nur in diese neue Instanz die Dateien unter integration/ einspielen. Andere Zielpfade benötigen erneute Relokation/Repinning, da feste Pfade gepinnt sind. evidence/ enthält Wiederholung und Analyse. Bestehende Instanzen nie überschreiben. Rücknahme: R7 nicht verwenden; R5 wurde nicht geändert.
