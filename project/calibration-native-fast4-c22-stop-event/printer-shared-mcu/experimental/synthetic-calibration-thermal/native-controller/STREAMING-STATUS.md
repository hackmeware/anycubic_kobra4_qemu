# Revision3: correct GetStatus streaming cardinality

## Mistake and preserved native outcome

The initial static recovery verified message fields and heater temperature semantics but omitted RPC cardinality. The controller incorrectly required unary END_STREAM/trailers for GetStatus. This was a controller mistake, not native printer failure.

Preserved native r2 reached PrinterState ready, then captured five GetStatus messages while its legacy stream-end client waited until the5guest-second timeout. Original exits143 remain failures. No target or target-zero request was sent. All raw r1/r2 files and prior checkpoints are preserved, not reclassified as passing runs.

`streaming-status-review/` contains original r2 frames, each exact protobuf, capture hashes, and original cardinality proof. The first message's omitted current scalars decode to native default0; subsequent four messages report25°C/target0 for both heaters. No0→25 substitution is permitted.

Native registration0x107ee6c..0x107ef38 sets method kind2. Dispatcher0x106b7a4 reads service slot0x1d8 at0x1395430, pointing to handler0x1176800. The handler writes responses at0x11768b4..0x11768d8, schedules the next cycle approximately1s later, and checks ServerContextBase::IsCancelled at0x1176920. The typed ServerStreamingHandler and ServerWriter RTTI independently confirm streaming.

## Isolated replacement for status snapshots only

`status_snapshot.py` is a separate ARM builder and strict host validator restricted to the exact empty GetStatus request on guest127.0.0.1:50051. The proven unary stream-end generator/default, PrinterState route and normal nozzle/bed setter transports are unchanged. Readiness ELF bytes are compared against actual r2 bytes in regression tests.

Each snapshot:

1. Receives initial HTTP/2 response headers and exactly TWO complete uncompressed gRPC messages, across arbitrary read and DATA-frame fragmentation. It keeps raw frames and both payloads. Extra full/partial message bytes within the final captured frame fail closed; later unread network frames are outside the finite snapshot and are not represented as observed.
2. Sends an explicit RST_STREAM(CANCEL=8), then calls local shutdown(SHUT_RDWR) and close. Exit20 is available only when the framed pair was captured and the cancellation send/shutdown/close calls succeeded. Partial/error outcomes never produce exit20. Guest timeout remains5s; no uncertain retry.
3. Independently validates captured HTTP/2 framing, complete header blocks, exactly one HTTP200 and application/grpc content type, no error trailers, and both complete protobuf schemas before using either sample. The emitted ARM client checks framing/envelopes; HPACK, HTTP semantics and temperature schemas are checked by the host validator. Exit20 alone is never accepted as valid temperature data.
4. Always selects message2 by sequence, regardless of its values. Both decoded messages and protobufs are retained. This avoids relying on an unproven assumption that the first0/0 is startup-only rather than a per-subscription initial/default response. R2 provides a real positive pair: message1=0/0, message2=25/0 on both heaters.
5. Reports `two_stream_messages_validated`, `selected_native_message_index=2`, `local_cancel_frame_sent`, and `local_socket_shutdown_and_close`. It explicitly reports `transport_complete=false`, `unary_rpc_completion=false`, `grpc_trailers_observed=false`, and `remote_cancellation_acknowledged=false`. Local syscall success does not prove that the remote handler has already observed cancellation, and the snapshot makes no terminal gRPC-status claim.

Baseline collection remains unheated and requires actual native/model/ADC ambient agreement and both targets0. It is capped at3 successfully canceled snapshots or10virtual seconds after ready. A correctly decoded but not-yet-ready0°C sample can lead only to another bounded fresh observation, never invented readiness. Any transport uncertainty ends the virtual run rather than retrying.

All original physical, native fault, stable-band, target-zero, heater-off, cooling, source, clock and hard-time limits remain in place. No native firmware, PID, safety setting, physical clock, model, central launcher, console TTY or source-of-temperature route was altered.

## Validation and limits

- Actual r2 first-two frames (568bytes) decode both native temperatures25°C and targets0 in message2, with message1 retained as default0.
- The emitted ARM ELF is executed by the existing ARM instruction interpreter with Linux syscalls mocked. Tests check every-byte fragmentation, split envelopes and message bodies, both messages coalesced in a DATA frame, first-only blocking, premature EOF/truncation, oversized/compressed messages, server errors/reset/END_STREAM, padding/continuations, control frames, EINTR and partial sends/writes, exact CANCEL bytes and syscall order, and cancel/shutdown/close failures.
- Host tests reject duplicate/bad HTTP headers, non200 responses, terminal error trailers, missing/extra messages, invalid protobufs in either message, and original r2 timeout143. Selection of sequence2 is tested even when it has a lower/default temperature than sequence1.
- Full mocked controller tests cover stable nozzle and separate bed flows, faults, no-rise/time caps, target/zero uncertainty, exact startup exceptions, baseline0 then real ambient, and permanently-zero baseline stopping without heat.
- Existing unary transport and diagnostic heater regressions run unchanged. The original diagnostic0..35°C bound is preserved.

No qemu-arm or qemu-arm-static Linux-user runtime was found in PATH or the inspected installed/runtime/build locations. Therefore no actual Linux ARM process or local TCP mock-server execution is claimed. These are emitted-instruction/syscall-mocked tests plus actual captured native DATA fixtures, not live validation of the new client. No native three-MCU run was launched during revision3 preparation.
