# Optional stream-end diagnostic probe candidate

Isolated candidate only. This candidate does not modify production source, RPC
schemas, the current emulator, guest state, or launchers. Nothing in this directory automatically starts
an emulator, connects a socket, or executes the generated ARM program.

## Build, without running

From the snapshot root:

```sh
python3 rv1106-at32-link/experimental/stream-end-probe/make_probe.py \
  --response-mode stream-end --method PrinterState --timeout-seconds 1 \
  --output /tmp/printer-state-stream-end.elf
```

The resulting `.commands` file is a **future guest-console artifact**, not a host
script to run. Do not submit it to the current emulator without coordinating a
separate experiment. Its socket address is fixed to guest `127.0.0.1:50051`;
there is no network-target option. The generator itself performs no networking.

Omitting `--response-mode`, or using `--response-mode timeout`, invokes the
production generator. ELF bytes, command bytes, stdout and existing defaults are
unchanged. The new mode obtains its exact request packet and validation from the
production generator; it does not redefine any RPC or loosen its restrictions.

## Stream-end behavior

- Read exactly one 9-byte frame header and its declared payload at a time.
  Fragmented reads are accumulated correctly; coalesced frames are separated
  by the requested read lengths. Every received byte is written to stdout as
  read, with short-write and EINTR handling. Header/payload prefixes survive EOF
  or external timeout.
- Stop after fully capturing stream 1 DATA or HEADERS with END_STREAM. A HEADERS
  block with END_STREAM but no END_HEADERS must finish its matching CONTINUATION
  sequence first. Stop after a complete stream 1 RST_STREAM as a distinct outcome.
  Other streams, unknown extension frames, SETTINGS, PING, WINDOW_UPDATE, and
  GOAWAY cannot falsely end the capture.
- Capture is the complete wire prefix through the terminal frame/header block.
  Later connection-level bytes are deliberately not read, even when already
  coalesced in the socket receive queue. No text/status is mixed into raw stdout.
- ACK every fully received, valid non-ACK SETTINGS frame. Echo each non-ACK PING
  as a PING ACK only after all 8 opaque bytes arrive. Do not ACK an ACK. Check
  control-frame length/stream constraints and relevant SETTINGS bounds.
- Replenish connection and stream receive windows by each nonterminal DATA
  frame's entire payload size, including padding. Request DATA is already fully
  sent, so valid peer WINDOW_UPDATE values are checked but need no outbound
  accounting. Terminal DATA requires no further socket write. If a control
  send fails, suppress later control sends and keep reading the bounded raw
  response until its terminal frame, EOF, receive failure or external timeout.
  This retains already-queued response bytes; the eventual exit still reports
  I/O code 5, not clean transport completion. Initial request-send and stdout
  failures remain fatal.
- Enforce a 16,384-byte maximum frame payload, matching the unchanged initial
  HTTP/2 default. Resident receive storage is fixed at 16,384 bytes plus a header
  and small control buffers. Limit total raw capture to 1 MiB. No frame-sized or
  response-sized allocation occurs at runtime.
- Malformed/unsupported frames, capture bounds, and I/O failures terminate with
  distinct nonzero transport codes. These are intentional safety exits in
  addition to normal END_STREAM, reset and connection-close termination.
  Oversized frames retain their header only; the unbounded payload is not read.
  A capture-limit failure retains the already-read prefix. Other bounded
  malformed frames are fully captured before their error exit.

The external BusyBox `timeout -t` remains unchanged as the final wall/guest-time
safety bound for an incomplete stream or a stalled peer. The candidate command
file additionally prints `GRPC_PROBE_TRANSPORT_EXIT=<number>` **after** the raw
`od` output. `GRPC_PROBE_DONE` remains a capture workflow marker, not success.

Transport codes from the candidate binary:

| Code | Meaning |
| --- | --- |
| 0 | Complete stream 1 END_STREAM framing/header block captured |
| 2 | Complete stream 1 RST_STREAM captured |
| 3 | Peer EOF before a stream 1 terminal frame/header block |
| 4 | Malformed/unsupported frame or oversized frame |
| 5 | Socket/connect/read/write/send failure; a failed control send is deferred while capture continues |
| 6 | Capture volume bound would be exceeded |

The external timeout can return its own BusyBox-dependent status instead.
Code 0 is **not gRPC success, API acceptance, or physical completion**. A
nonzero gRPC status, absent/malformed HPACK, or an application error still may
have valid END_STREAM framing. This client never decodes HPACK or protobuf,
never invents a status, and never replaces the existing response verifier.
Keep interpreting the raw capture separately.

## Deliberate limits

This is a bounded single-stream diagnostic transport, not a full HTTP/2 client.
It does not implement HPACK, content validation, all stream-state rules, push,
TLS, reconnects, retries of RPCs, or generic endpoints. It ignores unknown
extension frames outside a header-block continuation. Server PUSH_PROMISE is
explicitly unsupported and fails closed. Valid framing on other stream IDs is
captured and cannot claim stream 1 completion. SETTINGS are acknowledged after
validation, but no additional request is sent. The original request is exactly
one RPC. Unknown settings are ignored as HTTP/2 requires. The supported production
generator hash is recorded separately from the initial pre-work hash, so an
independently authorized generator update can be tracked without conflating it
with this transport candidate.

The ARM ELF uses Linux ARM EABI socket/connect/read/write/send/exit syscalls and
MSG_NOSIGNAL for socket writes. It preserves the legacy single writable segment
layout and needs no C runtime or cross-compiler. These syscall assumptions have
only been modeled offline so far, not checked against a running guest kernel.

## Verification

```sh
python3 -m unittest discover \
  -s rv1106-at32-link/experimental/stream-end-probe -p test_probe.py -v
python3 -m unittest discover \
  -s rv1106-at32-link/tests -p test_extruder_preheating_probe.py -v
python3 -m unittest discover \
  -s rv1106-at32-link/tests -p test_native_homing_probe.py -v
python3 -m unittest discover \
  -s rv1106-at32-link/tests -p test_verify_native_error_rpc.py -v
sha256sum -c rv1106-at32-link/experimental/stream-end-probe/production-script.sha256
```

`arm_fixture.py` interprets the actual emitted ARM instruction bytes with mocked
Linux syscalls and checked memory ranges. It never opens a socket, executes the
ELF on the host, or uses the printer emulator. The tests include all split points,
byte-by-byte delivery, 50 seeded fragmentation patterns, 300 malformed-frame
fixtures, raw nonzero gRPC status retention, open/incomplete/EOF streams,
CONTINUATION and reset, settings/ping/window updates, padding/priority,
short writes and EINTR, control-send failure with continued capture, malformed and oversized frames, an over-64-KiB response,
the 1-MiB cap, and byte identity for existing default outputs and request packets.

This verifies a local instruction/syscall model, not native Linux execution,
native gRPC-server interoperability, or a measured virtual-time improvement.
Those remain unverified and require a separately coordinated emulator run.
