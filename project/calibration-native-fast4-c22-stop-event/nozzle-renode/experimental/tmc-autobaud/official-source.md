# Official source

Analog Devices, TMC2209 Datasheet Rev.1.09 (2023-Feb-16), sections4.1.1–4.1.2 and NODECONF register table, page24.
https://www.analog.com/media/en/technical-documentation/data-sheets/TMC2209_datasheet_rev1.09.pdf

Short exact excerpt:
“The TMC2209 responds with the same baud rate as the master uses for the read request.”

Source acquisition: the official-domain indexed text was retrievable. Direct full PDF fetch timed out. The adjacent evidence/nozzle-uart-timing/datasheet-semantics.md records the source comparison and its limitations. The candidate follows the sync-edge measurement and paired SENDDELAY encoding, without claiming the current native failure is caused by their absence.
