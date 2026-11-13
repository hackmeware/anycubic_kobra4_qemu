# Gebündelte QEMU-Zustandsabfrage: isolierter Versuch

6. November 2026. Kein produktiver Launcher wurde geändert. Kein nativer
Heiz-, Kalibrierungs- oder Drucklauf wurde gestartet.

## Ergebnis

Der neue nur lesende Snapshot ist implementiert, getrennt gebaut und mit
dem gleich gebauten unveränderten Vergleich getestet. Im synthetischen
1-ms-QEMU-Test steigt der mittlere Durchsatz von **101,85 auf 125,27 Schritte/s**,
also ungefähr **23 %**. Die Wall-Zeit pro Schritt sinkt von 9,821 auf 7,990 ms
(18,6 %). Alle verglichenen virtuellen Zeitspuren bleiben identisch.

Die vier Kandidatenmessungen lagen bei 120,39–130,39 Schritten/s, die vier
Vergleichsmessungen bei 99,71–103,92. Zwei unterschiedliche, ausgeglichene
Reihenfolgen wurden verwendet. Der Gewinn ist in diesen kurzen synthetischen
Reihen reproduzierbar. Das ist **kein Nachweis für 23 % schnellere native
Kalibrierung oder Bett-Heizung**. Renode, UART und native Programme haben
eigene Kosten und benötigen einen gesonderten begrenzten Integrationslauf.

| 1-ms-Test, je 1.000 gemessene Schritte | Schritte/s | Wall-ms/Schritt | QEMU-CPU-ms/Schritt | Anfragen/Schritt |
|---|---:|---:|---:|---:|
| Neu gebauter Vergleich, bisherige Einzelwerte | 101,85 | 9,821 | 9,609 | 16 |
| Neuer QEMU-Build, weiterhin Einzelwerte | 100,87 | 9,925 | 9,711 | 16 |
| Neuer QEMU-Build, gebündelter Snapshot | 125,27 | 7,990 | 7,754 | 6 |

Alle Modi benutzen denselben STOP-Event-Client-Unterbau. Die zweite Zeile
kontrolliert den Build-Effekt: Allein das Vorhandensein der neuen Eigenschaft
beschleunigt den bisherigen Pfad nicht. Erst ihre Verwendung spart Anfragen.
Die Anzahl der Schreibvorgänge bleibt bei sechs, die Anzahl der QMP-Anfragen
sinkt um 62,5 %. QEMU-CPU sinkt im Vergleich um 19,3 %, Client-CPU von 0,440
auf 0,323 ms/Schritt. Summierte Thread-CPU und Wall-Zeit sind unterschiedliche
Messgrößen, keine exakt voneinander abziehbaren Zeitanteile.

Ein zusätzlicher 1-µs-QEMU-Test mit je 500 Schritten ergibt 276,55 gegenüber
655,06 Schritten/s. Er charakterisiert den höheren relativen Protokollaufwand
bei sehr kurzen QEMU-Intervallen. Er ändert **nicht** die regulären 1-ms-
Koordinatorschritte und ist keine Hochrechnung auf den Druckerbetrieb.

## Änderung und Timingsemantik

Die neue QOM-Eigenschaft `/machine:virtual-clock-state` ist ausschließlich
lesbar. Sie liefert in einer strukturierten Antwort:

- Schema und Herkunft, aktiviert/initialisiert, tatsächlichen Laufzustand;
- Epoche und einmal abgelesene tatsächliche virtuelle Zeit;
- angeforderte Deadline, armed/fired;
- tatsächliche Callback-Zeit und eingefrorene Stoppzeit.

Der Getter verlangt den bestehenden Big QEMU Lock und kopiert die Felder
lokal. Er setzt keine Zeit, Register, Pause oder Deadline und hat keinen
Setter. Im laufenden Zustand ist die Uhr weiterhin eine Live-Beobachtung;
erst `running=false` erlaubt dem Client, sich auf eingefrorene Zeit zu
verlassen. Lesen einer laufenden VM hält sie nicht an.

Der neue Python-Client ersetzt nur die Einzelabfragen. Die bestehenden
begrenzten Pipe-Zugriffe, exklusiven Verbindungsbesitzer, Antwort-IDs,
RESUME/STOP-Reihenfolge und Lifecycle-Fehler bleiben erhalten. Unsupported,
unvollständige, falsch typisierte oder inkonsistente Antworten führen zum
Abbruch. Es gibt keinen automatischen Rückfall auf ungeprüfte Werte.

Weiter geprüft werden echter Pausezustand, Epoche, tatsächliche Uhr,
armed/fired, Callback-Grenzen und `stop_ns == virtual_time_ns`. Zusätzlich
werden angeforderte Deadline, geleerte Stopp-/Callback-Zeitstempel nach dem
Armen und die unveränderte pausierte Zeit zwischen Vorbereitung und Armen
verglichen. STOP bleibt ein Aufwecksignal, kein Erfolgsnachweis.

Nicht geändert: icount shift=0, 1-ms-Schritte, 5-ms-Lead-Grenze, höchstens
1 ms zwischenzeitlicher Rückstand und kein negativer Endversatz. Die
exact24-Architekturkorrektur, +1-ns-Stoppbarriere, Timer, Frequenzen, MCU-
Quellen, thermischen Modelle und Hersteller-Firmware bleiben unverändert.

Der Client richtet sich an den exklusiven Koordinator. Epoche null und
bereits vorbereitete Deadlines werden zurückgewiesen. Er ist daher kein
allgemeiner Ersatz für beliebige manuelle Stop/Rearm-Abläufe.

## Nachweise

- **31 Offline-Tests**, auch mit optimiertem Python: Schema, Typen, fehlende
  Daten, inkonsistente Zustände, Epoch-/Zeitfehler, Deadline, STOP-Rennen,
  Timeout, volle Pipe, Verbindungsfehler, konkurrierende Besitzer, Cleanup.
- **11 echte QEMU-Zustandsfälle**: Snapshot entspricht pausiert sämtlichen
  bisherigen Einzelwerten bei initialem, vorbereitetem, ausgelöstem,
  abgebrochenem, manuell gestopptem und zurückgesetztem Zustand. Mehrfaches
  Lesen verändert nichts. Schreiben wird abgelehnt. Lesen hält eine
  laufende VM nicht an. Der unveränderte Vergleich kennt die neue Property
  erwartungsgemäß nicht.
- Beide Builds bestehen die bestehenden ARM/UART-, Register- und
  eMMC-Regressionen sowie die physischen und virtuellen 24-MHz-Counter-/
  CVAL-Prüfungen. Die exakte C-Arithmetik besteht 50.000 Zufallstests plus
  Grenzfälle.
- Beide Builds bestehen die bestehenden Deadline-Regressionen mit jeweils
  50 × 1 ms und 50 × 1 µs einschließlich Reset, Abbruch, Read-only und
  Mutationsverweigerung im laufenden Zustand.
- **4.500 gemessene QEMU-Benchmark-Schritte**, zusätzlich 90 Warmups:
  Callback genau auf Ziel, Stopp genau Ziel +1 ns, identische Trace-Hashes
  zwischen allen Modi je Intervall.
- **Kurzer gemeinsamer QEMU/Renode-Uhrentest**: tatsächliches Renode-Quantum
  1 µs; drei separat bestätigte 1-µs-Mikroschritte; anschließend 101
  1-ms-Koordinatorzyklen. Maximaler tatsächlicher QEMU-Lead 1 ns,
  zwischenzeitlicher Rückstand 1 ms. Originaler Koordinator unverändert.
  Renode war ein CPU-/Firmware-freies Uhrmodell, QEMU führte nur `B .` aus.

Das ist kein Nachweis elektrischer, physikalischer oder nativer Druckertreue.
Die 1-µs-Uhrkonfiguration ist geprüft; ein nativer Drei-MCU/UART-Lauf ist es
nicht. Der neue Kandidat wurde deshalb **nicht in Startprofile integriert**.

## Provenienz und Schutz des bisherigen Stands

Die passende exact24-Architekturquelle wurde aus ihrem gesicherten
Quellcheckpoint wiederhergestellt. Archiv- und Patch-Hashes stimmen mit der
Dokumentation der bisherigen Runtime überein. Auch der ursprüngliche
Board-Code stimmt exakt überein. Das passende DTC wurde vom offiziellen
QEMU-Repository unter dessen fest gepinntem Commit bezogen und mitgesichert.

Beide neuen Binärdateien wurden mit demselben Compiler, denselben Optionen
und denselben Abhängigkeiten gebaut. Sie sind **nicht bitidentisch** mit der
historischen Runtime. Nur der zweite Build enthält den neuen Getter.
Deshalb erfolgt der Leistungstest gegen den neu gebauten Vergleich und
zusätzlich gegen den Einzelwertpfad im neuen Build.

Details: `evidence/build-provenance.json`, beide Build-Protokolle,
`qemu/clock-snapshot.patch`, `source-inputs/` und `BUILD.de.md`.
Alle 1.108 Dateien des ursprünglichen V8-Quellmanifests blieben unverändert.
Zusätzlich wurde der vollständige wiederhergestellte Gesamtsnapshot gegen
seine 5.609 gespeicherten Datei-Hashes geprüft.

## Paket verwenden

In ein neues leeres Verzeichnis entpacken. Das Paket enthält beide neuen
QEMU-Runtimes, die getesteten Clients, unterstützende Quellen, synthetische
Fixtures, Rohmessungen und die Quelländerung. Es enthält keine Hersteller-
Firmware. Es ersetzt keinen Netzwerk-/VNC-/Kalibrierungsstart.

Vom Paketwurzelverzeichnis aus:

    P=rv1106-at32-link/experimental/clock-snapshot
    python -B "$P/client/test_snapshot_clock.py" -v
    timeout --signal=TERM --kill-after=5s 30s python -B "$P/test_runtime_snapshot.py" \
      --candidate "$P/runtime/run-snapshot" --baseline "$P/runtime/run-baseline" \
      --fixture "$P/fixtures/branch-self.bin" --output /new/result.json

Für den Leistungsvergleich:

    timeout --signal=TERM --kill-after=5s 45s python -B "$P/benchmark_snapshot.py" \
      --candidate "$P/runtime/run-snapshot" --baseline "$P/runtime/run-baseline" \
      --fixture "$P/fixtures/branch-self.bin" --slice-ns 1000000 --steps 250 \
      --output /new/empty/benchmark-directory

Ein zweiter Lauf mit `--reverse` kehrt die Modus-Reihenfolge um. Für die
separate kurze QEMU-Intervallprüfung `--slice-ns 1000` verwenden. Keine dieser
Optionen ändert einen bestehenden Drucker-Launcher.

`joint_clock_smoke.py` benötigt zusätzlich den unveränderten Renode-1.17-
Launcher aus dem bestehenden Gesamtsnapshot als `--renode`-Argument.

## Grenzen und nächster Schritt

Vor einer produktiven Integration wäre ein kurzer begrenzter nativer
Boot-/Bereitschaftsvergleich bei denselben 1-ms-/1-µs-Einstellungen sinnvoll,
mit UART-Annahmefehlern, Clock-Skew, Thread-CPU und Phasenzeiten als Kriterien.
Ein langer Heizlauf ist dafür weder nötig noch durch dieses Paket gestartet.
