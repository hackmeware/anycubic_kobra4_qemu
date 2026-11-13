"""Opt-in actual-time bootstrap; cancellation is observed only while paused.

Segmenting RunFor is NOT yet established equivalent to the legacy single call.
A stalled step is a failure, not a cancellation boundary. An outer supervisor
is still required for process stalls, setup and final diagnostics.
"""
import json
import os
import select
import sys
import time

SLICE_NS = 1_000_000
TOTAL_NS = 1_000_000_000
BOOTSTRAP_WRITE_TIMEOUT = 1
BOOTSTRAP_ACK_TIMEOUT = 2


def bounded_send(process, lock, data, timeout=10):
    """Bound lock acquisition and pipe writes; never leave a writer thread alive."""
    deadline = time.monotonic() + timeout
    if not lock.acquire(timeout=timeout):
        raise RuntimeError('Renode monitor write lock timed out')
    fd = None
    try:
        if process.poll() is not None:
            raise RuntimeError('Renode process exited before monitor write')
        candidate = process.stdin.fileno()
        blocking = os.get_blocking(candidate)
        os.set_blocking(candidate, False)
        fd = candidate
        view = memoryview(data)
        while view:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('Renode monitor write timed out; command may be partial')
            if not select.select([], [fd], [], remaining)[1]:
                raise RuntimeError('Renode monitor write timed out; command may be partial')
            try:
                count = os.write(fd, view)
            except BlockingIOError:
                continue
            if count <= 0:
                raise RuntimeError('Renode monitor write made no progress')
            view = view[count:]
    finally:
        original_error = sys.exc_info()[1]
        try:
            if fd is not None:
                os.set_blocking(fd, blocking)
        except OSError as restore_error:
            if original_error is None:
                raise
            original_error.add_note('Monitor blocking-mode restore failed: ' + str(restore_error))
        finally:
            lock.release()


def bootstrap(stepper, check_boundary, output):
    """Return the SAME stepper after exactly 1000 acknowledged 1ms advances.

    Persist an in-flight marker before each command, clearing it only after
    validation. A timeout/epoch/time mismatch therefore never claims a pause.
    """
    initial = stepper.time_ns
    epoch = stepper.epoch
    state = {'schema': 1, 'mode': 'segmented', 'equivalence_established': False,
             'slice_ns': SLICE_NS, 'target_delta_ns': TOTAL_NS,
             'initial_time_ns': initial, 'epoch': epoch, 'completed_steps': 0,
             'last_confirmed_step_id': stepper.step_id,
             'last_confirmed_time_ns': initial, 'actual_delta_ns': 0,
             'uncertain_in_flight_step_id': None, 'status': 'active'}
    def save():
        temp = output.with_suffix('.tmp')
        temp.write_text(json.dumps(state, indent=2) + '\n')
        temp.replace(output)
    try:
        save()
        if stepper.step_id != 0 or stepper.failed:
            raise RuntimeError('Segmented bootstrap requires fresh acknowledged step zero')
        for index in range(TOTAL_NS // SLICE_NS):
            check_boundary()
            state['uncertain_in_flight_step_id'] = stepper.step_id + 1
            save()
            now = stepper.step(SLICE_NS)
            if (stepper.epoch != epoch or stepper.step_id != index + 1
                    or now != initial + (index + 1) * SLICE_NS):
                raise RuntimeError('Segmented bootstrap acknowledgement mismatch')
            state.update(completed_steps=index + 1,
                         last_confirmed_step_id=stepper.step_id,
                         last_confirmed_time_ns=now, actual_delta_ns=now-initial,
                         uncertain_in_flight_step_id=None)
            save()
            check_boundary()
        state['status'] = 'complete'
        save()
        return stepper
    except Exception as error:
        state.update(status='incomplete', reason=str(error),
                     error_notes=list(getattr(error, '__notes__', [])))
        try:
            save()
        except OSError as report_error:
            error.add_note('Bootstrap evidence write failed: ' + str(report_error))
        raise
