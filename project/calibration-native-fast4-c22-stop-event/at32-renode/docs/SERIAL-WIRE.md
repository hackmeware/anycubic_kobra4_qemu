# External virtual serial wire

`AT32VirtualSerialWire` is an explicit **external testbench adapter**, not an AT32 peripheral and not a larger MCU UART FIFO. It accepts host bursts into its own queue and injects one completed frame at a time into an existing `AT32UART`. CPU execution and virtual time advance between frames. The first byte is delivered after a complete frame interval; remaining bytes arrive at `bitsPerFrame / baud` virtual seconds per frame. At 576000 baud and 10 bits/frame this is approximately 17.361111 microseconds, subject to Renode clock quantization.

Load after `AT32F403A_IO.cs`:

```
include @peripherals/AT32F403A_VirtualSerialWire.cs
```

Add an addressless testbench component to the platform, referring to the actual UART name:

```
serialWire: AT32.AT32VirtualSerialWire @ sysbus
    uart: usart1
    baud: 576000
    bitsPerFrame: 10
```

Connect the host PTY/UART terminal to `sysbus.serialWire`, **not directly to `sysbus.usart1`**. The serial wire's outgoing UART event forwards MCU transmissions immediately. This paces only host-to-MCU delivery. Host wall time and MCU virtual time are not shared or synchronized. The adapter does not sample a physical waveform or compare its configured baud/framing with firmware UART settings, so wrong-baud/framing faults are not reproduced. TX line serialization, modem signals, parity checking, framing errors and electrical levels are not modeled. `bitsPerFrame` controls total RX timing only; the byte transport advertises 8N1-style stop/parity metadata. UART receiver enable, FIFO1 overrun and interrupt behavior are unchanged. No firmware safety check is bypassed.

The optional `capacity` constructor argument defaults to 1048576 host bytes. Overflow increments `RejectedBytes` and logs an ERROR; it is not silently absorbed. Monitor properties `PendingBytes`, `DeliveredBytes`, `RejectedBytes`, `BaudRate` and `BitsPerFrame` are available. `DeliveredBytes` counts injection attempts, not proof that firmware consumed bytes: the actual UART can still drop bytes when disabled or raise overrun when firmware fails to service it.

`Reset` discards pending host bytes, resets counters and stops/rephases the frame timer. It does not reset the underlying UART. The next incoming byte starts a fresh full-frame delay. Normal machine reset also resets its UART separately. Addressless registration is tested; the optional read-only 16-byte diagnostic MMIO interface exists solely for test registration and is not part of the AT32 hardware map.

## Tests

Run:

```
python3 tests/run-serial-wire.py --renode /path/to/renode
```

The self-contained test generates an auditable Thumb firmware image, runs it on the actual Renode Cortex-M core, queues an ABC burst and checks that the firmware consumes and echoes ABC without overrun. Virtual-time boundary checks at 17/18, 34/35 and 52/53 microseconds bracket each expected frame completion at 576000 baud. Reset discards a partially pending Z frame, and a later D requires a new full-frame interval. Tests also verify TX event forwarding, finite-queue overflow reporting and reset counters. These are functional timing checks, not a hardware timing certification.
