# Getrennter Offline-Nachbau

Die in diesem Paket enthaltenen Binärdateien wurden mit GCC 14.2.0 gebaut.
Exakte Version, Quellen-Hashes und Konfiguration stehen in
`evidence/build-provenance.json`. Die folgenden Schritte beschreiben den
tatsächlich verwendeten getrennten Ablauf. Neue Pfade und Compiler können
andere Binär-Hashes ergeben; die funktionalen Regressionen sind erneut nötig.

Voraussetzung: vorhandener unveränderter Gesamtsnapshot V8 mit
`sources/qemu-9.2.0.tar.xz`, `rv1106-qemu/`, `build-deps/` und der bekannten
exact24-Runtime. QEMU-Upstream-Archiv SHA-256:
`f859f0bc65e1f533d040bbe8c92bcfecee5af2c921a6687c652fb44d089bd894`.

1. Neues leeres Arbeitsverzeichnis anlegen. Darin `project/`, `upstream/`
   und `runtime/` verwenden. Nicht den bestehenden Snapshot verändern.
2. `build-deps/`, `rv1106-qemu/hw`, `rv1106-qemu/scripts` und
   `rv1106-qemu/tests` aus dem Snapshot nach `project/` kopieren. Das
   Upstream-Archiv unter `project/sources/qemu-9.2.0.tar.xz` bereitstellen.
3. `source-inputs/exact24-source-checkpoint.tar.gz` in `project/` entpacken.
   Hash vorher prüfen: `9b3852fa0d6cec5d6afa6911fc06d1fff2534e9e591d1693baa3ca78d9b765f6`.
4. Upstream-QEMU in `upstream/` entpacken. Das mitgelieferte DTC-Archiv
   `source-inputs/dtc-b6910bec.tar.gz` mit `--strip-components=1` nach
   `upstream/qemu-9.2.0/subprojects/dtc/` entpacken. Hash:
   `e115f987eec23a1ba25150a46ced1675de3716072d3b4905afb3a9cda0f007c7`.
5. Die kopierte `project/build-deps/env.sh` sourcen. Nur ihre abgeleiteten
   pkg-config-Dateien werden an den neuen Pfad angepasst. Mit absoluten
   Pfaden arbeiten und setzen:

       export JOBS=4
       export RV1106_BUILD_ROOT=/absolute/new/work/upstream
       project/rv1106-qemu/experimental/exact-generic-timer/build-candidate.sh \
         --disable-download -Dfdt=internal

   Der vorhandene Builder prüft das Upstream-Archiv und die fünf
   exact24-Architekturdateien vor der Anwendung. Er baut zunächst den
   **Vergleich ohne neue Snapshot-Eigenschaft** und führt die vorhandenen
   ARM/Register/eMMC-Tests aus. Ausgabe ist `upstream/build/qemu-system-arm`.
6. Diese Binärdatei unverändert als `runtime/bin/qemu-baseline` sichern.
   Vor der nächsten Änderung muss `upstream/qemu-9.2.0/hw/arm/rv1106.c`
   SHA-256 `3e93fe0cddb52937db806f844278a216873b29a8be3f54634cb3f63321ff50cd`
   besitzen.
7. `qemu/clock-snapshot.patch` aus diesem Paket mit `patch -p1` im
   `upstream/qemu-9.2.0/`-Verzeichnis anwenden. Der neue Board-Hash muss
   `fd3f75487b4cf412fb0a54f7077026eaa0cad8d8d5606c70a816d08e1f4f0507`
   lauten. Die fünf exact24-Architekturdateien bleiben unverändert.
8. Nur mit `ninja -C upstream/build -j4 qemu-system-arm` neu bauen.
   **Nicht** erneut den Overlay-Builder ausführen, weil dieser den
   ursprünglichen Board-Code zurückkopiert. Die neue Ausgabe als
   `runtime/bin/qemu-snapshot` sichern.
9. Für beide Binärdateien dieselben bereits gesicherten Laufzeitbibliotheken
   und denselben Loader der ursprünglichen exact24-Runtime verwenden. Die
   beiden mitgelieferten `runtime/run-*`-Wrapper zeigen den relativen Aufbau.
10. Offline-Clienttests, echte Snapshot-Zustandstests, 24-MHz-Counter/CVAL,
    ursprüngliche Geräte-/eMMC-/Deadline-Regressionen und die begrenzten
    Benchmark-/Uhrentests wiederholen. Ergebnisse nicht überschreiben.

Der erste getrennte Kandidatenbau enthielt nur eine Const-Qualifier-Warnung
für den Herkunftstext. Sie wurde vor sämtlichen Runtime-Messungen behoben.
`candidate-build-final.log` ist der abschließende warnungsfreie Build.

Der aktuelle Getter nutzt ausschließlich lokale Momentaufnahmen vorhandener
Felder. Sein vollständiger Quelltext ist unter `qemu/rv1106.c` enthalten.
Die Architekturquelle einschließlich alter/neuer Dateien und Patch liegt
im mitgelieferten exact24-Quellcheckpoint; der unveränderte übrige QEMU-
Quelltext ist das oben bezeichnete öffentliche Upstream-Archiv. QEMU und die
gelieferten Laufzeitbibliotheken behalten ihre jeweiligen Lizenzen; siehe
`runtime/COPYING`, `runtime/COPYING.LIB` und die Originalquellen.
