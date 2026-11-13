# R9 scalar USB Ethernet integration candidate v1

NEW profile; neither the historical R9 launcher nor existing release was edited.
This provides an executable wrapper integration surface, not a completed guest
network verification. Original input images and manifests remain unchanged.

## Wiring into the fresh starter

1. Use scalar runtime directory
   rv1106-at32-link/experimental/clock-snapshot/runtime.
   Exact bin/qemu-baseline SHA256:
   d295efe337e46357fa6cc9bf28356ba6e0cc0df5c82198aa3bf0a4d1eae7bfb1.
2. During fresh diagnostic DT construction, after original reduced-board edits
   and BEFORE DT/ELF serialization, call `nodes = enable_usb_host(nodes)` when
   network mode is enabled. Import from baseline_network.py. Never rewrite an
   original DT file. This enables a diagnostic simple bus / generic-xhci device
   at 0xffb00000, size0x10000, GIC SPI54, high-speed host. It bypasses the unsupported
   native DWC3 PHY/register probe. This is a disclosed emulation adaptation.
3. Supply run_link's --qemu a new per-run shell wrapper that executes Python:
   `python3 /path/baseline_network.py --runtime /path/runtime --mode isolated
    --http-port 18912 --mqtt-port 9895 --execute -- "$@"`
   Quote all generated shell paths using shlex.quote. Or use `command()` from
   a new runner directly. Internet mode must be explicit. Off emits -nic none.
   No existing args may already contain netdev/nic/device networking. Coupled mode is accepted only as the exact scalar tuple described below;
   independent mode remains the default.
4. After /oem is mounted, before application startup, run the Ethernet commands
   in usb-ethernet.commands, guarded so failed DHCP is reported, not silently
   accepted. Historical original cdc_ether created eth0; a different kernel may
   need appropriate USB/xHCI/usbnet/cdc_ether modules and cannot be assumed supported.
   Confirm eth0, DHCP address, route and resolver before declaring readiness.
5. Preserve each instance's own disk writer lock, run directory and endpoints.
   This wrapper does not manage disk lifetime, stop processes, reserve ports or
   supply console/VNC/MCU logic: retain the fresh starter's lifecycle handling.

This minimal path requires NO hwsim module, OTP identity or fake WLAN interface.
It provides Ethernet IP transport, not WLAN onboarding behavior. Native printer
application can still require wlan0/event semantics; do not silently rename eth0
or claim the GUI/cloud registration is fixed. Existing HTTP and MQTT guest
listeners must exist; forwarding does not create them or bypass authentication.

CLI defaults to printing command JSON. --execute explicitly execs the validated
private runtime loader. Library function validate_runner_args allows only the
R9 runner pair family and restricts machine, display, monitor, serial backend and
shared RAM object. It is not a security sandbox for hostile input: trusted parent
runner still owns validation of paths and disk/PTY provenance. No arbitrary CLI
passthrough, TAP/TUN, firewall, TFTP or credential state is introduced.

## Evidence

Read-only capability commands on recovered scalar runtime returned user SLIRP
backend and usb-net device. They do not prove machine bus realization or guest
network traffic. 5 synthetic tests passed: DT copy semantics, known registers/IRQ,
argument family, rejecting alternate machine/network/icount and port/mode handling.
No guest was launched by this worker. A separate fresh-boot worker subsequently
verified isolated USB enumeration and DHCP; see update below.

Fresh boot owner must test guest enumeration/DHCP/local forwarded HTTP before
calling this working integration. Test network-off remains a separate baseline.
An end-to-end result should record new source/DT/ELF/runtime hashes and effective
args, not relabel historical R9 or OTP TESTED02 evidence. Old network328369... and
OTP0b3d796... profiles cannot replace this pinned scalar runtime automatically.


## Revision: own guest DHCP hook and coupled admission

The fresh-boot worker reported a bounded isolated run with built-in cdc_ether,
USB0525:a4a2, eth0 DHCP10.0.2.15/24. Native udhcpc hook failed to write readonly
/etc/resolv.conf and provided no observed default route. This is evidence of
Ethernet/DHCP transport only, not a successful complete internet stack.

The new commands explicitly select udhcpc-hook.sh, generated into /tmp/k4-usb-net.
It configures eth0, default gateway from the DHCP router field, and up to three
IPv4 DNS servers in a RAM-backed file. Guest-only mount -o bind overlays the
existing resolver target, without writing original rootfs bytes. No host mount or
network setting is touched. The target must already resolve to an existing file;
otherwise a clear K4_NET_ERROR_RESOLVER_TARGET is emitted. Configuration readiness
is marked only after readback succeeds. Reboot removes this diagnostic overlay.
DHCP is bounded to five attempts with two-second timeout, plus up to20s NIC wait.
No DNS lookup, cloud request or Internet validation is performed by the hook.

Coupled argv admission now accepts only rv1106[,memory-backend=displayram],
virtual-deadline-enabled=on together with exactly one -S, one local absolute
-qmp pipe:path and -icount shift=0,align=off,sleep=off. Missing/partial tuples,
alternate transports and other shifts are rejected. This is argv compatibility,
NOT evidence that coupled mode meets realtime or SLIRP latency requirements.

Latest synthetic test report:12 tests pass, including mocked DHCP hook behavior
(valid lease, missing DNS/router, invalid interface/address) and coupled argv
admission. ifconfig/route/mount were harmless local stubs in these tests. Actual
isolated guest retest of this NEW hook is requested from the fresh-boot worker;
its outcome is not preclaimed here. The allowlist is a compatibility check for a
trusted local runner, not a security sandbox against crafted path/value strings.

## Exact vendor resolver symlink correction

New SWU inventory confirms /etc/resolv.conf is the symlink ../tmp/resolv.conf;
its absent target caused the old diagnostic failure. The hook now checks that
exact symlink, refuses a symlink at /tmp/resolv.conf, and writes the DHCP resolver
content to that RAM-backed target. It never replaces the vendor symlink. The
regular-existing-file bind path remains for the alternate documented layout;
unknown symlink targets fail explicitly. New dangling-symlink synthetic regression
passes and confirms no mount call on this layout. Latest suite:13 tests passed.
Actual isolated guest retest is delegated, not preclaimed.

## Revision 2: readonly /tmp and UART line-length fixes

Actual guest retest exposed readonly /tmp and a >4KiB command truncated by the
TTY canonical-line limit. These are new observed failures, not covered by the
previous mocked-hook tests. generate_guest_commands.py now produces separate
short printf append commands and rejects any line over500UTF-8 bytes. A regression
reconstructs every hook line from the serialized shell words and proves equality.
The fresh diagnostic profile mounts a guest-only16MiB tmpfs on /tmp unless one
is already mounted there, before creating the hook. This intentionally hides
original /tmp contents for this diagnostic boot; it is a startup adaptation, not
an operation to apply to an already running printer app. Original disk bytes and
host mounts remain unchanged. K4_NET_TMP_READY confirms the guest write probe.

16 synthetic tests now pass, including bounds, lossless reconstruction and mount
ordering. These do not replace actual guest retesting. No release-v2 files were
modified; changes are only in network_work/next staging.

## Revision 3: isolated DHCP capabilities

Actual isolated retest proved RAM/tmp and short command fixes work and DHCP
supplies10.0.2.15, but restrict=on omitted the router option. That is not an
Internet configuration failure to repair by inventing a gateway. Hook mode is
now explicit in /tmp/k4-usb-net/mode. Isolated mode accepts missing router/DNS,
emits capability-unavailable markers and K4_NET_LOCAL_ONLY_READY. Provided
addresses still undergo validation; valid provided options are configured.
Internet mode requires gateway and DNS before emitting its configuration-ready
marker, which explicitly says UNTESTED. No connectivity inference is made.

Fresh starter must call generate_guest_commands.generate(hook_text,mode=selected)
for isolated/internet, or omit these commands entirely for off. The checked-in
usb-ethernet.commands is isolated by default. Do not use that static isolated file
for internet mode.19 synthetic tests pass, including mode serialization, missing
isolated options, strict internet requirements and malformed supplied DNS.
No new actual guest verification of this revision has yet been performed.
