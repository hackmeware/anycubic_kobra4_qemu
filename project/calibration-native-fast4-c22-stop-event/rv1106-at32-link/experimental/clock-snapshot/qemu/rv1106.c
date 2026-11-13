/* SPDX-License-Identifier: GPL-2.0-or-later */
/* RV1106 U-Boot bring-up machine. Not a complete silicon model. */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qapi/visitor.h"
#include "qemu/error-report.h"
#include "qemu/log.h"
#include "qemu/units.h"
#include "qemu/timer.h"
#include "qemu/main-loop.h"
#include "qemu/bswap.h"
#include "qemu/host-utils.h"
#include "qemu/guest-random.h"
#include "exec/address-spaces.h"
#include "hw/boards.h"
#include "hw/sd/sd.h"
#include "sysemu/blockdev.h"
#include "hw/irq.h"
#include "hw/loader.h"
#include "hw/qdev-properties.h"
#include "hw/char/serial-mm.h"
#include "hw/intc/arm_gic.h"
#include "hw/usb/hcd-dwc3.h"
#include "sysemu/reset.h"
#include "sysemu/runstate.h"
#include "sysemu/sysemu.h"
#include "target/arm/cpu.h"
#include "elf.h"
#include "migration/blocker.h"

#define TYPE_RV1106_MACHINE MACHINE_TYPE_NAME("rv1106")
OBJECT_DECLARE_SIMPLE_TYPE(RV1106State, RV1106_MACHINE)
#define CRU_SIZE 0x20000
#define GRF_SIZE 0x90000
#define N_SPI 128

typedef struct RV1106Regs {
    MemoryRegion mr;
    uint32_t *data;
    const char *name;
    bool cru;
} RV1106Regs;

typedef struct RV1106Timer {
    MemoryRegion mr;
    uint64_t load[6], started[6];
    uint32_t control[6];
} RV1106Timer;

struct RV1106State {
    MachineState parent_obj;
    ARMCPU *cpu;
    MemoryRegion sram;
    MemoryRegion gic_aiar, gic_aeoir;
    MemoryRegion uart_ext[6];
    RV1106Regs cru, grf, ioc, pmuioc, gpio[5], pwm;
    RV1106Timer timers;
    MemoryRegion vop;
    uint32_t vop_regs[0x200 / 4];
    QEMUTimer *vop_timer;
    qemu_irq vop_irq;
    MemoryRegion adc;
    uint32_t adc_regs[0x200 / 4];
    MemoryRegion rng;
    uint32_t rng_regs[0x200 / 4];
    uint64_t entry;
    Error *migration_blocker;
    /* Opt-in host instrumentation; never changes guest clock frequency. */
    QEMUTimer *virtual_deadline_timer;
    bool virtual_deadline_enabled;
    bool virtual_clock_initialized;
    bool virtual_deadline_armed;
    bool virtual_deadline_fired;
    int64_t virtual_deadline_ns;
    int64_t virtual_deadline_stop_ns;
    int64_t virtual_deadline_fired_ns;
    int64_t virtual_clock_epoch;
};

/* This timer requests an event-loop pause, not an exact CPU execution budget.
 * Non-icount host scheduling can delay dispatch. Controllers must independently
 * validate actual stop time against their unchanged virtual-time lead limit. */
static void rv1106_deadline_clear(RV1106State *s)
{
    if (s->virtual_deadline_timer) {
        timer_del(s->virtual_deadline_timer);
    }
    s->virtual_deadline_armed = false;
    s->virtual_deadline_fired = false;
    s->virtual_deadline_ns = 0;
    s->virtual_deadline_stop_ns = -1;
    s->virtual_deadline_fired_ns = -1;
}

static void rv1106_deadline_vm_state(void *opaque, bool running, RunState state)
{
    RV1106State *s = opaque;
    if (!running && s->virtual_deadline_fired &&
        s->virtual_deadline_stop_ns < 0) {
        s->virtual_deadline_stop_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
        timer_del(s->virtual_deadline_timer);
    }
}

/* While the native stop request is pending, keep a real event immediately
 * ahead of actual virtual time. Otherwise icount's idle-warp path can jump to
 * a much later device event after the vCPU has stopped but before runstate is
 * updated. timerlist_run_timers snapshots current_time once, so a strictly
 * future rearm cannot spin within that same dispatch. No clock is rewritten. */
static void rv1106_deadline_stop_barrier(RV1106State *s)
{
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    if (now < INT64_MAX) {
        timer_mod(s->virtual_deadline_timer, now + 1);
    }
}

static void rv1106_deadline_expired(void *opaque)
{
    RV1106State *s = opaque;
    if (!s->virtual_deadline_enabled) {
        return;
    }
    if (!s->virtual_deadline_armed) {
        if (s->virtual_deadline_fired && s->virtual_deadline_stop_ns < 0) {
            rv1106_deadline_stop_barrier(s);
        }
        return;
    }
    s->virtual_deadline_armed = false;
    s->virtual_deadline_fired = true;
    s->virtual_deadline_fired_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    /* Stop this machine's sole vCPU immediately, without disabling the clock
     * from its own callback. This closes the instruction-execution gap before
     * the main loop consumes the asynchronous VM-stop request. */
    cpu_pause(CPU(s->cpu));
    /* Never disable a clock from one of its timer callbacks: vm_stop() calls
     * pause_all_vcpus(), which waits for this timer list to finish. Queue the
     * native stop request for main_loop_should_exit() after callback return. */
    qemu_system_vmstop_request_prepare();
    qemu_system_vmstop_request(RUN_STATE_PAUSED);
    rv1106_deadline_stop_barrier(s);
}

static bool rv1106_deadline_enabled_get(Object *obj, Error **errp)
{
    return RV1106_MACHINE(obj)->virtual_deadline_enabled;
}

static void rv1106_deadline_enabled_set(Object *obj, bool value, Error **errp)
{
    RV1106State *s = RV1106_MACHINE(obj);
    if (s->virtual_clock_initialized) {
        error_setg(errp, "virtual-deadline-enabled is a launch-only opt-in");
        return;
    }
    s->virtual_deadline_enabled = value;
}

static bool rv1106_deadline_armed_get(Object *obj, Error **errp)
{
    return RV1106_MACHINE(obj)->virtual_deadline_armed;
}

static bool rv1106_deadline_fired_get(Object *obj, Error **errp)
{
    return RV1106_MACHINE(obj)->virtual_deadline_fired;
}

static void rv1106_virtual_clock_get(Object *obj, Visitor *v, const char *name,
                                     void *opaque, Error **errp)
{
    RV1106State *s = RV1106_MACHINE(obj);
    int64_t value;
    if (!strcmp(name, "virtual-time-ns")) {
        value = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    } else if (!strcmp(name, "virtual-deadline-ns")) {
        value = s->virtual_deadline_ns;
    } else if (!strcmp(name, "virtual-deadline-fired-ns")) {
        value = s->virtual_deadline_fired_ns;
    } else if (!strcmp(name, "virtual-deadline-stop-ns")) {
        value = s->virtual_deadline_stop_ns;
    } else {
        g_assert(!strcmp(name, "virtual-clock-epoch"));
        value = s->virtual_clock_epoch;
    }
    visit_type_int64(v, name, &value, errp);
}

/* Read-only diagnostic snapshot. BQL serializes runstate and deadline metadata.
 * The actual virtual clock is sampled once. While running it remains a live
 * sample; clients must require running=false before relying on frozen time.
 * This getter never pauses, rearms, clears, or changes any emulated state.
 */
static void rv1106_virtual_clock_state_get(Object *obj, Visitor *v,
                                           const char *name, void *opaque,
                                           Error **errp)
{
    RV1106State *s = RV1106_MACHINE(obj);
    int64_t schema = 1;
    char source_text[] = "rv1106-virtual-clock-state";
    char *source = source_text;
    bool enabled, initialized, running, armed, fired;
    int64_t epoch, now, deadline, fired_ns, stop_ns;

    if (!bql_locked()) {
        error_setg(errp, "Clock snapshot requires the Big QEMU Lock");
        return;
    }
    enabled = s->virtual_deadline_enabled;
    initialized = s->virtual_clock_initialized;
    running = runstate_is_running();
    epoch = s->virtual_clock_epoch;
    now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    deadline = s->virtual_deadline_ns;
    armed = s->virtual_deadline_armed;
    fired = s->virtual_deadline_fired;
    fired_ns = s->virtual_deadline_fired_ns;
    stop_ns = s->virtual_deadline_stop_ns;

    if (!visit_start_struct(v, name, NULL, 0, errp)) {
        return;
    }
    if (!visit_type_int64(v, "schema", &schema, errp) ||
        !visit_type_str(v, "source", &source, errp) ||
        !visit_type_bool(v, "enabled", &enabled, errp) ||
        !visit_type_bool(v, "initialized", &initialized, errp) ||
        !visit_type_bool(v, "running", &running, errp) ||
        !visit_type_int64(v, "epoch", &epoch, errp) ||
        !visit_type_int64(v, "virtual_time_ns", &now, errp) ||
        !visit_type_int64(v, "deadline_ns", &deadline, errp) ||
        !visit_type_bool(v, "armed", &armed, errp) ||
        !visit_type_bool(v, "fired", &fired, errp) ||
        !visit_type_int64(v, "fired_ns", &fired_ns, errp) ||
        !visit_type_int64(v, "stop_ns", &stop_ns, errp)) {
        goto out;
    }
    visit_check_struct(v, errp);
out:
    visit_end_struct(v, NULL);
}

static void rv1106_virtual_deadline_set(Object *obj, Visitor *v,
                                      const char *name, void *opaque,
                                      Error **errp)
{
    RV1106State *s = RV1106_MACHINE(obj);
    int64_t value;
    if (!visit_type_int64(v, name, &value, errp)) {
        return;
    }
    if (!s->virtual_deadline_enabled || !s->virtual_clock_initialized) {
        error_setg(errp, "virtual deadline requires launch opt-in and initialized machine");
        return;
    }
    if (!runstate_check(RUN_STATE_PAUSED) &&
        !runstate_check(RUN_STATE_PRELAUNCH)) {
        error_setg(errp, "VM must be paused/prelaunch to arm or clear virtual deadline");
        return;
    }
    if (value < 0 || (value && value <= qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL))) {
        error_setg(errp, "virtual deadline must be zero (clear) or strictly in the future");
        return;
    }
    rv1106_deadline_clear(s);
    if (value) {
        s->virtual_deadline_ns = value;
        s->virtual_deadline_armed = true;
        timer_mod(s->virtual_deadline_timer, value);
    }
}

/* Minimal RV1106 VOP register/IRQ transport. Register layout follows the
 * vendor Linux rv1106_vop/rk3366_lit_win1 definitions, not a full pixel pipe.
 * Fixed 60 Hz completion is diagnostic, not MCU-panel electrical timing. */
static void vop_update_irq(RV1106State *s)
{
    qemu_set_irq(s->vop_irq, !!(s->vop_regs[0x3c / 4] &
                             s->vop_regs[0x34 / 4]));
}
static void vop_tick(void *opaque)
{
    RV1106State *s = opaque;
    uint32_t events = 0x300; /* display hold valid and DMA completion */
    if (!(s->vop_regs[0x18 / 4] & 2)) {
        events |= 0x1b; /* frame start/new and two line flags */
    }
    s->vop_regs[0x3c / 4] |= events & s->vop_regs[0x34 / 4];
    s->vop_regs[0x0c / 4] &= ~(1U << 28);
    vop_update_irq(s);
    timer_mod(s->vop_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 16666667);
}
static uint64_t vop_read(void *opaque, hwaddr addr, unsigned size)
{
    RV1106State *s = opaque;
    return s->vop_regs[addr / 4];
}
static void vop_write(void *opaque, hwaddr addr, uint64_t value, unsigned size)
{
    RV1106State *s = opaque;
    uint32_t v = value, mask = v >> 16;
    if (addr == 0x38) {
        s->vop_regs[0x3c / 4] &= ~(v & mask);
    } else if (addr == 0x34) {
        s->vop_regs[addr / 4] = (s->vop_regs[addr / 4] & ~mask) | (v & mask);
    } else if (addr != 4 && addr != 0x3c) {
        s->vop_regs[addr / 4] = v;
    }
    vop_update_irq(s);
    qemu_log_mask(LOG_UNIMP, "rv1106.vop +0x%03" HWADDR_PRIx " = 0x%08x\n", addr, v);
}
static const MemoryRegionOps vop_ops = {
    .read = vop_read, .write = vop_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
};

static uint64_t regs_read(void *opaque, hwaddr addr, unsigned size)
{
    RV1106Regs *r = opaque;
    uint32_t v = r->data[addr / 4];
    if (!strcmp(r->name, "rv1106.gpio")) {
        if (addr == 0x70) {
            return 0xffffffff; /* unconnected input pins pulled high */
        }
        if (addr == 0x78) {
            return 0x01000c2b; /* Rockchip GPIO v2 */
        }
    }
    /* PLL lock is synthesized: no analog oscillator/lock delay model. */
    if (r->cru && addr >= 0x10000 && addr < 0x10080 &&
        (addr & 0x1f) == 4) {
        v |= 1 << 10;
    }
    return v;
}

static void regs_write(void *opaque, hwaddr addr, uint64_t val, unsigned size)
{
    RV1106Regs *r = opaque;
    uint32_t mask = val >> 16;
    /* GRF OS registers are full-width persistent scratch registers. */
    if (!strcmp(r->name, "rv1106.pwm") ||
        (!strcmp(r->name, "rv1106.grf") && addr >= 0x500 && addr < 0x520)) {
        r->data[addr / 4] = val;
    } else if (r->cru && addr >= 0x10318 && addr <= 0x10340 &&
               !((addr - 0x10318) % 8)) {
        /* Clock fractional dividers use a full 16:16 numerator/denominator. */
        r->data[addr / 4] = val;
    } else {
        r->data[addr / 4] = (r->data[addr / 4] & ~mask) | (val & mask);
    }
    qemu_log_mask(LOG_UNIMP, "%s: approximate register write +0x%" HWADDR_PRIx
                  " = 0x%08" PRIx64 "\n", r->name, addr, val);
}

static const MemoryRegionOps regs_ops = {
    .read = regs_read, .write = regs_write, .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
};

static void add_regs(RV1106State *s, RV1106Regs *r, const char *name,
                     hwaddr base, size_t size, bool cru)
{
    r->name = name;
    r->cru = cru;
    r->data = g_new0(uint32_t, size / 4);
    memory_region_init_io(&r->mr, OBJECT(s), &regs_ops, r, name, size);
    memory_region_add_subregion_overlap(get_system_memory(), base, &r->mr,
                                        !strcmp(name, "rv1106.gpio") ? 1 : 0);
}

static uint64_t uart_ext_read(void *opaque, hwaddr addr, unsigned size)
{
    switch (addr) {
    case 0x7c: return 6; /* DW USR: TX FIFO not full, TX FIFO empty */
    case 0x80: case 0x84: return 0; /* FIFO levels */
    default: return 0;
    }
}

static void uart_ext_write(void *opaque, hwaddr addr, uint64_t value,
                           unsigned size)
{
    qemu_log_mask(LOG_UNIMP, "rv1106.uart: unmodeled DW register +0x%"
                  HWADDR_PRIx " write 0x%" PRIx64 "\n", addr, value);
}

static const MemoryRegionOps uart_ext_ops = {
    .read = uart_ext_read, .write = uart_ext_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

static uint64_t ticks_now(void)
{
    return muldiv64(qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL), 24000000,
                    NANOSECONDS_PER_SECOND);
}

static uint64_t timer_read(void *opaque, hwaddr addr, unsigned size)
{
    RV1106Timer *t = opaque;
    unsigned n = addr / 0x20, reg = addr % 0x20;
    uint64_t current = t->load[n];
    if (t->control[n] & 1) {
        current -= ticks_now() - t->started[n];
    }
    switch (reg) {
    case 0: return (uint32_t)t->load[n];
    case 4: return t->load[n] >> 32;
    case 8: return (uint32_t)current;
    case 12: return current >> 32;
    case 16: return t->control[n];
    default: return 0;
    }
}

static void timer_write(void *opaque, hwaddr addr, uint64_t val, unsigned size)
{
    RV1106Timer *t = opaque;
    unsigned n = addr / 0x20, reg = addr % 0x20;
    switch (reg) {
    case 0: t->load[n] = (t->load[n] & 0xffffffff00000000ULL) | val; break;
    case 4: t->load[n] = (t->load[n] & 0xffffffffULL) | (val << 32); break;
    case 16: t->control[n] = val; t->started[n] = ticks_now(); break;
    default: break;
    }
}

static const MemoryRegionOps timer_ops = {
    .read = timer_read, .write = timer_write, .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
};

/* Two unconnected SARADC inputs return full scale, not a pressed boot key. */
static uint64_t adc_read(void *opaque, hwaddr addr, unsigned size)
{
    RV1106State *s = opaque;
    if (addr == 0x120 || addr == 0x124) {
        return 1023;
    }
    return s->adc_regs[addr / 4];
}

static void adc_write(void *opaque, hwaddr addr, uint64_t val, unsigned size)
{
    RV1106State *s = opaque;
    if (addr == 0x110) {
        s->adc_regs[addr / 4] &= ~val;
    } else if (addr == 0 || addr == 0x104) {
        uint32_t mask = val >> 16;
        s->adc_regs[addr / 4] = (s->adc_regs[addr / 4] & ~mask) | (val & mask);
        if (addr == 0 && (val & (1 << 4))) {
            s->adc_regs[0x110 / 4] |= 1;
        }
    } else {
        s->adc_regs[addr / 4] = val;
    }
}

static const MemoryRegionOps adc_ops = {
    .read = adc_read, .write = adc_write, .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
};

/* TRNGv1 request/status protocol, backed by QEMU's host entropy API. */
static uint64_t rng_read(void *opaque, hwaddr addr, unsigned size)
{
    RV1106State *s = opaque;
    return addr == 0xf0 ? 0x46bc : s->rng_regs[addr / 4];
}

static void rng_write(void *opaque, hwaddr addr, uint64_t val, unsigned size)
{
    RV1106State *s = opaque;
    if (addr == 0x14) {
        s->rng_regs[addr / 4] &= ~val;
    } else {
        s->rng_regs[addr / 4] = val;
        if (addr == 0 && (val & 3)) {
            qemu_guest_getrandom_nofail(&s->rng_regs[0x20 / 4], 32);
            s->rng_regs[0x14 / 4] |= val & 3;
        }
    }
}

static const MemoryRegionOps rng_ops = {
    .read = rng_read, .write = rng_write, .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
};

/* Experimental DW-MSHC host with upstream QEMU eMMC card protocol.
 * Implements 32-bit chained IDMAC and PIO, not timing/tuning/DDR signalling. */
#define TYPE_RV1106_MMC "rv1106-dwmmc"
OBJECT_DECLARE_SIMPLE_TYPE(RV1106MMC, RV1106_MMC)
struct RV1106MMC {
    SysBusDevice parent_obj;
    MemoryRegion mr;
    SDBus bus;
    qemu_irq irq;
    uint32_t r[0x1000 / 4];
    uint32_t remaining;
    bool writing;
    QEMUTimer *command_timer;
    uint32_t pending_command;
};

static void mmc_irq(RV1106MMC *s)
{
    qemu_set_irq(s->irq, (s->r[0] & 0x10) &&
                 ((s->r[0x44/4] & s->r[0x24/4]) ||
                  (s->r[0x8c/4] & s->r[0x90/4])));
}

static void mmc_data_done(RV1106MMC *s)
{
    s->r[0x44/4] &= ~((1 << 4) | (1 << 5));
    s->r[0x44/4] |= 1 << 3;
    if (s->r[0x2c/4] & (1 << 12)) {
        SDRequest stop = { .cmd = 12 };
        uint8_t resp[16];
        sdbus_do_command(&s->bus, &stop, resp);
        s->r[0x44/4] |= 1 << 14;
    }
}

static void mmc_dma(RV1106MMC *s)
{
    uint32_t addr = s->r[0x88/4];
    unsigned guard = 0;
    while (s->remaining && guard++ < 65536) {
        uint8_t desc[16], buf[8192];
        uint32_t flags, len, ptr, next;
        cpu_physical_memory_read(addr, desc, sizeof(desc));
        flags = ldl_le_p(desc);
        len = MIN(ldl_le_p(desc + 4) & 0x1fff, s->remaining);
        ptr = ldl_le_p(desc + 8);
        next = ldl_le_p(desc + 12);
        if (!(flags & (1U << 31)) || !len) {
            s->r[0x8c/4] |= (1 << 4) | (1 << 9);
            break;
        }
        if (s->writing) {
            cpu_physical_memory_read(ptr, buf, len);
            sdbus_write_data(&s->bus, buf, len);
        } else {
            sdbus_read_data(&s->bus, buf, len);
            cpu_physical_memory_write(ptr, buf, len);
        }
        s->remaining -= len;
        s->r[0x5c/4] += len;
        s->r[0x60/4] += len;
        stl_le_p(desc, flags & ~(1U << 31));
        cpu_physical_memory_write(addr, desc, sizeof(desc));
        addr = flags & (1 << 4) ? next : addr + 16;
    }
    if (!s->remaining) {
        s->r[0x8c/4] |= (1 << 8) | (s->writing ? 1 : 2);
        mmc_data_done(s);
    }
}

static void mmc_command(RV1106MMC *s, uint32_t val)
{
    SDRequest req = { .cmd = val & 63, .arg = s->r[0x28/4] };
    uint8_t resp[16] = {0};
    int len;
    s->r[0x2c/4] = val & ~(1U << 31);
    if (val & (1 << 21)) {
        return;
    }
    len = sdbus_do_command(&s->bus, &req, resp);
    qemu_log_mask(LOG_UNIMP, "rv1106.mmc CMD%u arg=%08x response=%d dma=%08x bytes=%u\n",
                  req.cmd, req.arg, len, s->r[0], s->r[0x20/4]);
    if (len == 4) {
        s->r[0x30/4] = ldl_be_p(resp);
        /* No eMMC power-ramp timing is modeled. The vendor driver polls
         * CMD1(0) without yielding; report ready for this OCR inquiry while
         * keeping upstream card state idle until voltage selection CMD1. */
        if (req.cmd == 1) {
            /* This vendor kernel requires its soldered eMMC's exact OCR
             * voltage window (including dual-voltage bit7), not QEMU's
             * generic all-voltage SD window. */
            s->r[0x30/4] = (s->r[0x30/4] & 0x7f000000) | 0x80ff8080;
        }
    } else if (len == 16) {
        for (int i = 0; i < 4; i++) {
            s->r[0x30/4 + i] = ldl_be_p(resp + 12 - i * 4);
        }
    }
    s->r[0x44/4] |= 1 << 2;
    if ((val & (1 << 6)) && !len) {
        s->r[0x44/4] |= 1 << 8;
    } else if (val & (1 << 9)) {
        s->remaining = s->r[0x20/4];
        s->writing = val & (1 << 10);
        s->r[0x5c/4] = s->r[0x60/4] = 0;
        if (s->r[0] & (1 << 25)) {
            mmc_dma(s);
        } else {
            s->r[0x44/4] |= s->writing ? (1 << 4) : (1 << 5);
        }
    }
    mmc_irq(s);
}

static void mmc_command_timer(void *opaque)
{
    RV1106MMC *s = opaque;
    mmc_command(s, s->pending_command);
}

static uint64_t mmc_read(void *opaque, hwaddr addr, unsigned size)
{
    RV1106MMC *s = opaque;
    uint32_t val = 0;
    qemu_log_mask(LOG_UNIMP, "rv1106.mmc read +%03" HWADDR_PRIx " reg=%08x\n", addr, s->r[addr/4]);
    switch (addr) {
    case 0x40: return s->r[0x44/4] & s->r[0x24/4];
    case 0x48:
        return s->remaining && !s->writing ?
               (MIN((s->remaining + 3) / 4, 32) << 17) | 8 : 4;
    case 0x50: return !sdbus_get_inserted(&s->bus);
    case 0x54: return sdbus_get_readonly(&s->bus);
    case 0x6c: return 0x240a;
    case 0x70: return 1 << 7; /* 32-bit data width; 32-bit internal IDMAC */
    case 0x200:
        if (s->remaining && !s->writing) {
            unsigned n = MIN(s->remaining, 4);
            uint8_t b[4] = {0};
            sdbus_read_data(&s->bus, b, n);
            val = ldl_le_p(b);
            s->remaining -= n;
            if (!s->remaining) { mmc_data_done(s); }
            mmc_irq(s);
        }
        return val;
    default: return s->r[addr / 4];
    }
}

static void mmc_write(void *opaque, hwaddr addr, uint64_t val, unsigned size)
{
    RV1106MMC *s = opaque;
    qemu_log_mask(LOG_UNIMP, "rv1106.mmc write +%03" HWADDR_PRIx " = %08" PRIx64 "\n", addr, val);
    switch (addr) {
    case 0:
        s->r[0] = val & ~7U;
        if (val & 3) {
            timer_del(s->command_timer);
            s->remaining = 0;
            s->r[0x44/4] &= ~((1 << 4) | (1 << 5));
        }
        break;
    case 0x44: case 0x8c: s->r[addr/4] &= ~val; break;
    case 0x80: s->r[addr/4] = val & ~1U; break;
    case 0x2c:
        if ((val & (1 << 21)) || !sdbus_get_inserted(&s->bus)) {
            mmc_command(s, val);
        } else {
            s->pending_command = val;
            s->r[0x2c/4] = val & ~(1U << 31);
            timer_mod(s->command_timer,
                      qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 10000);
        }
        break;
    case 0x84: if (s->remaining) { mmc_dma(s); } break;
    case 0x200:
        if (s->remaining && s->writing) {
            uint8_t b[4];
            unsigned n = MIN(s->remaining, 4);
            stl_le_p(b, val);
            sdbus_write_data(&s->bus, b, n);
            s->remaining -= n;
            if (!s->remaining) { mmc_data_done(s); }
        }
        break;
    default: s->r[addr/4] = val; break;
    }
    mmc_irq(s);
}

static const MemoryRegionOps mmc_ops = {
    .read = mmc_read, .write = mmc_write, .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
};

static void mmc_init(Object *obj)
{
    RV1106MMC *s = RV1106_MMC(obj);
    s->command_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, mmc_command_timer, s);
    qbus_init(&s->bus, sizeof(s->bus), TYPE_SD_BUS, DEVICE(s), "sd-bus");
    memory_region_init_io(&s->mr, obj, &mmc_ops, s, TYPE_RV1106_MMC, 0x1000);
    sysbus_init_mmio(SYS_BUS_DEVICE(s), &s->mr);
    sysbus_init_irq(SYS_BUS_DEVICE(s), &s->irq);
    s->r[0x4c/4] = 31 << 16;
}

static void mmc_reset(DeviceState *dev)
{
    RV1106MMC *s = RV1106_MMC(dev);
    timer_del(s->command_timer);
    memset(s->r, 0, sizeof(s->r));
    s->r[0x4c/4] = 31 << 16;
    s->remaining = 0;
    s->writing = false;
    mmc_irq(s);
}

static void mmc_class_init(ObjectClass *klass, void *data)
{
    device_class_set_legacy_reset(DEVICE_CLASS(klass), mmc_reset);
}

static const TypeInfo mmc_type = {
    .name = TYPE_RV1106_MMC, .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(RV1106MMC), .instance_init = mmc_init,
    .class_init = mmc_class_init,
};

static void rv1106_reset(void *opaque)
{
    RV1106State *s = opaque;
    rv1106_deadline_clear(s);
    s->virtual_clock_epoch++;
    memset(s->vop_regs, 0, sizeof(s->vop_regs));
    s->vop_regs[4 / 4] = 0x0002000c;
    if (s->vop_timer) {
        timer_mod(s->vop_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 16666667);
        vop_update_irq(s);
    }
    cpu_reset(CPU(s->cpu));
    cpu_set_pc(CPU(s->cpu), s->entry);
    /* Cold startup is unchanged. Subsequent resets in explicitly enabled
     * diagnostic mode must not silently resume without an armed deadline. */
    if (s->virtual_deadline_enabled && s->virtual_clock_epoch > 1) {
        vm_stop(RUN_STATE_PAUSED);
    }
}

static void rv1106_init(MachineState *machine)
{
    RV1106State *s = RV1106_MACHINE(machine);
    MemoryRegion *mem = get_system_memory();
    DeviceState *gic;
    const char *image = machine->kernel_filename ?: machine->firmware;
    static const int ppi[] = { 14, 11, 10, 13 };
    static const hwaddr uart[] = {
        0xff4a0000, 0xff4b0000, 0xff4c0000,
        0xff4d0000, 0xff4e0000, 0xff4f0000,
    };
    int i;
    if (machine->ram_size < 32 * MiB || machine->ram_size > 256 * MiB ||
        !is_power_of_2(machine->ram_size)) {
        error_report("rv1106 requires 32, 64, 128 or 256 MiB RAM");
        exit(1);
    }
    if (machine->kernel_filename && machine->firmware) {
        error_report("Use only one of -kernel and -bios");
        exit(1);
    }
    memory_region_add_subregion(mem, 0, machine->ram);
    memory_region_init_ram_nomigrate(&s->sram, OBJECT(s), "rv1106.sram", 64 * KiB,
                           &error_fatal);
    memory_region_add_subregion(mem, 0xff700000, &s->sram);
    s->cpu = ARM_CPU(object_new(machine->cpu_type));
    object_property_add_child(OBJECT(s), "cpu", OBJECT(s->cpu));
    object_property_set_int(OBJECT(s->cpu), "cntfrq", 24000000, &error_fatal);
    qdev_realize(DEVICE(s->cpu), NULL, &error_fatal);
    gic = qdev_new(TYPE_ARM_GIC);
    qdev_prop_set_uint32(gic, "num-cpu", 1);
    qdev_prop_set_uint32(gic, "num-irq", N_SPI + 32);
    qdev_prop_set_uint32(gic, "revision", 2);
    qdev_prop_set_bit(gic, "has-security-extensions",
                      arm_feature(&s->cpu->env, ARM_FEATURE_EL3));
    sysbus_realize_and_unref(SYS_BUS_DEVICE(gic), &error_fatal);
    sysbus_mmio_map(SYS_BUS_DEVICE(gic), 0, 0xff1f1000);
    sysbus_mmio_map(SYS_BUS_DEVICE(gic), 1, 0xff1f2000);
    /* Vendor Linux uses GICC_AIAR/AEOIR. Upstream GIC lacks these aliases.
     * In the EL3-disabled diagnostic mode there is only one IRQ view. */
    if (!arm_feature(&s->cpu->env, ARM_FEATURE_EL3)) {
        MemoryRegion *cpuif = sysbus_mmio_get_region(SYS_BUS_DEVICE(gic), 1);
        memory_region_init_alias(&s->gic_aiar, OBJECT(s), "rv1106.gic-aiar",
                                 cpuif, 0x0c, 4);
        memory_region_init_alias(&s->gic_aeoir, OBJECT(s), "rv1106.gic-aeoir",
                                 cpuif, 0x10, 4);
        memory_region_add_subregion_overlap(mem, 0xff1f2020, &s->gic_aiar, 1);
        memory_region_add_subregion_overlap(mem, 0xff1f2024, &s->gic_aeoir, 1);
    }
    sysbus_connect_irq(SYS_BUS_DEVICE(gic), 0,
                       qdev_get_gpio_in(DEVICE(s->cpu), ARM_CPU_IRQ));
    sysbus_connect_irq(SYS_BUS_DEVICE(gic), 1,
                       qdev_get_gpio_in(DEVICE(s->cpu), ARM_CPU_FIQ));
    for (i = 0; i < ARRAY_SIZE(ppi); i++) {
        qdev_connect_gpio_out(DEVICE(s->cpu), i,
                              qdev_get_gpio_in(gic, N_SPI + 16 + ppi[i]));
    }
    /* Serial0 is board debug UART2; subsequent backends map UART0,1,3,4,5. */
    for (i = 0; i < ARRAY_SIZE(uart); i++) {
        int backend = i == 2 ? 0 : (i < 2 ? i + 1 : i);
        memory_region_init_io(&s->uart_ext[i], OBJECT(s), &uart_ext_ops, s,
                              "rv1106.uart-dw", 0x100);
        memory_region_add_subregion_overlap(mem, uart[i], &s->uart_ext[i], -1);
        serial_mm_init(mem, uart[i], 2, qdev_get_gpio_in(gic, 25 + i),
                       24000000 / 16, serial_hd(backend), DEVICE_LITTLE_ENDIAN);
    }
    add_regs(s, &s->grf, "rv1106.grf", 0xff000000, GRF_SIZE, false);
    add_regs(s, &s->cru, "rv1106.cru", 0xff3a0000, CRU_SIZE, true);
    add_regs(s, &s->ioc, "rv1106.ioc", 0xff538000, 0x40000, false);
    add_regs(s, &s->pmuioc, "rv1106.pmuioc", 0xff388000, 0x1000, false);
    for (i = 0; i < 5; i++) {
        hwaddr base = i ? 0xff520000 + i * 0x10000 : 0xff380000;
        add_regs(s, &s->gpio[i], "rv1106.gpio", base, 0x100, false);
    }
    /* Diagnostic USB host: upstream DWC3/xHCI, RV1106 MMIO and IRQ. */
    {
        DeviceState *usb = qdev_new(TYPE_USB_DWC3);
        sysbus_realize_and_unref(SYS_BUS_DEVICE(usb), &error_fatal);
        sysbus_mmio_map(SYS_BUS_DEVICE(usb), 0, 0xffb00000);
        sysbus_connect_irq(SYS_BUS_DEVICE(&USB_DWC3(usb)->sysbus_xhci), 0,
                           qdev_get_gpio_in(gic, 54));
    }
    add_regs(s, &s->pwm, "rv1106.pwm", 0xff350000, 0x40, false);
    /* Bootloader clock defaults, not hardware power-on reset values. */
    s->cru.data[0x10000 / 4] = (2 << 12) | 68;
    s->cru.data[0x10004 / 4] = (1 << 12) | (1 << 6) | 1;
    s->cru.data[0x10020 / 4] = (2 << 12) | 250;
    s->cru.data[0x10024 / 4] = (1 << 12) | (1 << 6) | 3;
    s->cru.data[0x10040 / 4] = (2 << 12) | 50;
    s->cru.data[0x10044 / 4] = (1 << 12) | (1 << 6) | 1;
    s->cru.data[0x10060 / 4] = (2 << 12) | 99;
    s->cru.data[0x10064 / 4] = (1 << 12) | (1 << 6) | 1;
    s->cru.data[0x10280 / 4] = 0x15;
    s->cru.data[0x1f280 / 4] = 1;
    memory_region_init_io(&s->timers.mr, OBJECT(s), &timer_ops, &s->timers,
                          "rv1106.secure-timers", 6 * 0x20);
    memory_region_add_subregion(mem, 0xff590000, &s->timers.mr);
    /* Rockchip preloader handoff: CORE + DDR_MEM + SERIAL + NONE, hash=0 is valid.
     * U-Boot proper can skip SPL/DDR training using this DRAM bank record.
     */
    {
        uint8_t tags[268] = { 0 };
        stl_le_p(tags, 5);
        stl_le_p(tags + 4, 0x54410001);
        stl_le_p(tags + 20, 48);
        stl_le_p(tags + 24, 0x54410052);
        stl_le_p(tags + 28, 1);
        stq_le_p(tags + 44, machine->ram_size);
        stl_le_p(tags + 212, 12);
        stl_le_p(tags + 216, 0x54410050);
        stl_le_p(tags + 224, 1);
        stq_le_p(tags + 228, 0xff4c0000);
        stl_le_p(tags + 236, 115200);
        stl_le_p(tags + 240, 1);
        stl_le_p(tags + 244, 2);
        rom_add_blob_fixed("rv1106.preloader-atags", tags, sizeof(tags),
                           0x1fe000);
    }
    for (i = 0; i < 2; i++) {
        DeviceState *host = qdev_new(TYPE_RV1106_MMC);
        DriveInfo *dinfo = drive_get(IF_SD, 0, i);
        sysbus_realize_and_unref(SYS_BUS_DEVICE(host), &error_fatal);
        sysbus_mmio_map(SYS_BUS_DEVICE(host), 0, 0xffa90000 + i * 0x10000);
        sysbus_connect_irq(SYS_BUS_DEVICE(host), 0, qdev_get_gpio_in(gic, 48 + i));
        if (dinfo) {
            DeviceState *card = qdev_new(TYPE_EMMC);
            qdev_prop_set_drive_err(card, "drive", blk_by_legacy_dinfo(dinfo), &error_fatal);
            qdev_realize_and_unref(card, BUS(&RV1106_MMC(host)->bus), &error_fatal);
        }
    }
    memory_region_init_io(&s->vop, OBJECT(s), &vop_ops, s,
                          "rv1106.vop", 0x200);
    memory_region_add_subregion(mem, 0xff990000, &s->vop);
    s->vop_irq = qdev_get_gpio_in(gic, 89);
    s->vop_regs[4 / 4] = 0x0002000c;
    s->vop_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, vop_tick, s);
    timer_mod(s->vop_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 16666667);

    memory_region_init_io(&s->rng, OBJECT(s), &rng_ops, s,
                          "rv1106.trng", 0x200);
    memory_region_add_subregion(mem, 0xff448000, &s->rng);
    s->rng_regs[0x14 / 4] = 1;
    memory_region_init_io(&s->adc, OBJECT(s), &adc_ops, s,
                          "rv1106.saradc", 0x200);
    memory_region_add_subregion(mem, 0xff3c0000, &s->adc);
    s->entry = 0x200000;
    if (image) {
        g_autofree char *buf = NULL;
        gsize len;
        if (!g_file_get_contents(image, &buf, &len, NULL)) {
            error_report("Cannot read firmware '%s'", image);
            exit(1);
        }
        if (len >= 4 && !memcmp(buf, ELFMAG, SELFMAG)) {
            uint64_t low, high;
            if (load_elf(image, NULL, NULL, NULL, &s->entry, &low, &high,
                         NULL, 0, EM_ARM, 0, 0) < 0 ||
                high > machine->ram_size || s->entry >= machine->ram_size) {
                error_report("Firmware must be an ARM ELF linked in DRAM");
                exit(1);
            }
        } else if (len == 0 || len > machine->ram_size - s->entry ||
                   load_image_targphys(image, s->entry,
                                        machine->ram_size - s->entry) < 0) {
            error_report("Raw firmware empty, too large or unreadable");
            exit(1);
        }
    }
    error_setg(&s->migration_blocker,
               "RV1106 experimental register banks do not support migration");
    migrate_add_blocker(&s->migration_blocker, &error_fatal);
    s->virtual_deadline_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL,
                                           rv1106_deadline_expired, s);
    rv1106_deadline_clear(s);
    qemu_add_vm_change_state_handler(rv1106_deadline_vm_state, s);
    s->virtual_clock_initialized = true;
    qemu_register_reset(rv1106_reset, s);
}

static void rv1106_class_init(ObjectClass *oc, void *data)
{
    MachineClass *mc = MACHINE_CLASS(oc);
    static const char *const cpus[] = { ARM_CPU_TYPE_NAME("cortex-a7"), NULL };
    mc->desc = "Rockchip RV1106 (experimental U-Boot bring-up, not full SoC)";
    mc->init = rv1106_init;
    mc->default_cpu_type = ARM_CPU_TYPE_NAME("cortex-a7");
    mc->valid_cpu_types = cpus;
    mc->default_ram_size = 64 * MiB;
    mc->default_ram_id = "rv1106.dram";
    mc->max_cpus = 1;
    /* These approximate register banks do not implement migration state. */
    object_class_property_add(oc, "virtual-clock-state", "rv1106 clock state",
                              rv1106_virtual_clock_state_get, NULL, NULL, NULL);
    object_class_property_add(oc, "virtual-time-ns", "int",
                              rv1106_virtual_clock_get, NULL, NULL, NULL);
    object_class_property_add_bool(oc, "virtual-deadline-enabled",
                                  rv1106_deadline_enabled_get,
                                  rv1106_deadline_enabled_set);
    object_class_property_add(oc, "virtual-deadline-ns", "int",
                              rv1106_virtual_clock_get,
                              rv1106_virtual_deadline_set, NULL, NULL);
    object_class_property_add_bool(oc, "virtual-deadline-armed",
                                  rv1106_deadline_armed_get, NULL);
    object_class_property_add_bool(oc, "virtual-deadline-fired",
                                  rv1106_deadline_fired_get, NULL);
    object_class_property_add(oc, "virtual-deadline-fired-ns", "int",
                              rv1106_virtual_clock_get, NULL, NULL, NULL);
    object_class_property_add(oc, "virtual-deadline-stop-ns", "int",
                              rv1106_virtual_clock_get, NULL, NULL, NULL);
    object_class_property_add(oc, "virtual-clock-epoch", "int",
                              rv1106_virtual_clock_get, NULL, NULL, NULL);

}

static const TypeInfo rv1106_type = {
    .name = TYPE_RV1106_MACHINE, .parent = TYPE_MACHINE,
    .instance_size = sizeof(RV1106State), .class_init = rv1106_class_init,
};
static void rv1106_register_types(void) { type_register_static(&mmc_type); type_register_static(&rv1106_type); }
type_init(rv1106_register_types)
