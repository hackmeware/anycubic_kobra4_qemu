# Main firmware shutdown code 3: static evidence

Applies only to SHA256 9bd702c8a076f29c0ac019cc7c8ea6c7afa52d13580fea04e977e3dce0a5d517, loaded at 0x08004000.

The routine at 0x08004228 inserts an event into a deadline-ordered linked structure. It loads the requested deadline from argument object + 8. If that event precedes the current head, 0x08004256–0x0800425E reads DWT CYCCNT and branches when signed (deadline - now) is negative. At 0x08004284 it checks a global state byte at 0x2000000A. When this byte is zero, 0x0800428A loads error ID 3 and 0x0800428C calls the central error path at 0x08004210.

This establishes a scheduled-deadline-already-past cause for this path. It does not assign an unverified vendor string to the code, identify the specific host command that triggered it, or justify disabling the check.

The coupled run also used 5 ms wall-clock pacing per byte, equivalent to 200 bytes/s, rather than the nominal 576000 baud (~57600 bytes/s at 8N1). A 20-byte command then takes 100 ms. This can itself turn a future scheduled event into a past event. Independently running simulator clocks remain another potential contributor. Both must be measured, not masked by changing safety logic.
