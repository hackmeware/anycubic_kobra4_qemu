# Main-to-motor synchronization signal

The UART-only link is incomplete. Original main firmware reads DWT CYCCNT at `0x08004a0e`, toggles GPIOA output bit8 (PA8) at `0x08004a14–1a`, and sends command `0x10` with that four-byte timestamp at `0x08004a28`. This is a real firmware-produced edge, not a proposed periodic synthetic stimulus.

The original motor registers command0x10 to handler `0x0800ef88`. That handler passes the received timestamp to `0x080125bc`, then to `0x08012920` with its synchronization record at `0x20003b94`. Motor TMR2 channel1 capture interrupt calls `0x080128a8`, which reads capture register0x34. The received timestamp path reads the live TMR2 counter0x24 and compares capture/arrival intervals. Repeated invalid observations call status accumulator `0x08011724` with bit0x0800 (axis0 at0x08012a24 and axis1 at0x08012ab8).

Therefore the observed native-session status0x0800 is consistent with missing synchronization capture input. It must not be cleared or relabeled as harmless simply because the host UI reaches ready. The exact motor package pin and remap are still being checked; the timer channel role is established by executed instruction paths. A causal main-PA8-to-motor-TMR2-channel1 connection requires a common virtual timebase or a carefully timestamped cross-process event transport. Generating unrelated pulses from a host clock would not validate the real synchronization path.

Separately, bit0x0010 is set by original calibrated phase-current checks at0x0800a4c2–4ec when signed current samples leave the inclusive interval[-1945,1945]. It is not the current-calibration offset error0x0008. The standalone generic RL test had zero status, but native driver configuration changes its current requests; investigation of the full-session transient remains open.

Instruction evidence is in `firmware-evidence/main-motor-sync.asm`. These findings do not establish motor silicon identity, encoder wiring, rotor dynamics, or successful printing.

## Capture setup

Motor initializer0x0801bf2c configures PA15 as input and PB3/PB10/PB11 as alternate-function outputs. It writes IOMUX0x40010024 bits4–5 to3 via remap helper0x08017e08, then programs TMR2 channel1 input capture with selection1, both-edge polarity3 and filter5. The exact FCES package mux is not documented publicly; PA15 is the strongly supported firmware-side input candidate, while the actual TMR2 channel1 capture endpoint is directly established. Renode's inherited timer capture endpoint is `tmr2.OnGPIO(0, level)`; a virtual board overlay must carry the real mainPA8 edge into that endpoint, not merely change motor GPIO input state without alternate-function routing.
