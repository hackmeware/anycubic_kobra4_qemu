# Explicit 1us learned-baud candidate, not a default replacement

This isolated copy of VirtualNozzleTmc2209Autobaud uses the official four-bit sync edge span for each request and transmits its reply at that learned baud. It corrects odd SENDDELAY pairs according to the official table. It does not modify turnaround reference, GPIO SyncTime, firmware, frequencies, CRC checks, address checks or fault behavior. Production remains fixed40kbaud. No native launcher selection is installed here.

Official source and excerpts are retained in ../tmc-autobaud/official-source.md. Observed SENDDELAY2 was already correct in baseline. Candidate is restricted to explicit1us experiments: prior10us CPU phase failures remain blocking for broader promotion.

Run run_replay.py with external100s timeout, then analyze_replay.py. It replays original native-xy-quantum1 request edge timestamps with one constant origin translation, no scaling. Original source hash is saved. Both models accepted29 requests (10 writes,19reads,rejected0). All38 replies passed byte identity/CRC/framing; fixed reply period25us versus learned reply period24.75–25.25us; edge timing checked within1ns timer rounding.

Important fixture limitation: native passive observer only records GPIO edges, not every mode transition. Replay therefore releases input at last-byte-start plus ten learned bit periods. This assumption is explicit in metadata, not claimed observed. The isolated native return-to-output edge following transaction20 is not replayed as part of a request. Original receiving firmware is not executed, so these results prove model baud semantics, not repaired native CRC reception.

Run run_protocol_tests.py under external90s timeout:1us quantum,72 positive waveforms across20/40/50/80kbaud and SENDDELAY0/1/2/3/14/15;60 bad CRC/address/stop/disconnect/sync negatives. All passed. No tolerance changed.

Before native integration, arrange an explicit generated-source override with the launcher owner so shared namespace rewriting remains valid and default fixed-baud selection stays unchanged. Do not include an unrewritten standalone Nozzle class into the shared PrinterNozzle model. Preserve baseline runtime/source and record selected candidate/hash/1us assumption. A subsequent native comparison must re-export actual edges and both transports and must not infer success from ready alone.
