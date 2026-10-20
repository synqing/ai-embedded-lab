"""Bounded ownership of a deployment gateway and its programmer descendants."""
import os
import signal
import subprocess
import threading
import time


def _group_exists(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    return True


def run_deployment(argv, *, stdout, timeout, deadline, process):
    """Keep cleanup inside the caller's deadline; never recover over a live group."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("No deployment cleanup budget remains")
    # Reserve part of the existing authority, never extend its deadline.
    reserve = min(10.0, remaining / 3)
    execution_timeout = min(timeout, remaining - reserve)
    process.update(process_group_complete=False, recovery_safe=False,
                   cleanup_forced=False, execution_timeout_seconds=execution_timeout)
    proc = None
    previous_term = previous_int = None
    cancellation = []
    handles_term = threading.current_thread() is threading.main_thread()

    def cancelled(signum, frame):
        cancellation.append(signum)

    def wait_group(until):
        while time.monotonic() < until:
            proc.poll()  # Reap the gateway before checking for remaining children.
            if not _group_exists(proc.pid):
                process.update(process_group_complete=True, returncode=proc.returncode)
                return True
            time.sleep(min(.02, max(0, until - time.monotonic())))
        proc.poll()
        complete = not _group_exists(proc.pid)
        process.update(process_group_complete=complete, returncode=proc.returncode)
        return complete

    try:
        if handles_term:
            previous_term = signal.signal(signal.SIGTERM, cancelled)
            previous_int = signal.signal(signal.SIGINT, cancelled)
        proc = subprocess.Popen(argv, stdout=stdout, stderr=subprocess.STDOUT,
                                start_new_session=True)
        process["process_group_id"] = proc.pid
        try:
            execution_deadline = min(deadline - reserve, time.monotonic() + execution_timeout)
            while True:
                if cancellation:
                    raise KeyboardInterrupt("Deployment cancelled by signal " + str(cancellation[0]))
                wait_seconds = execution_deadline - time.monotonic()
                if wait_seconds <= 0:
                    raise subprocess.TimeoutExpired(argv, execution_timeout)
                try:
                    proc.wait(timeout=min(.05, wait_seconds))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if not wait_group(min(deadline - reserve, time.monotonic() + .2)):
                raise RuntimeError("Gateway exited while deployment descendants remained")
            if cancellation:
                raise KeyboardInterrupt("Deployment cancelled by signal " + str(cancellation[0]))
            process["recovery_safe"] = True
            return subprocess.CompletedProcess(argv, proc.returncode)
        except BaseException as exc:
            process["termination_reason"] = type(exc).__name__
            # Ignore repeated cancellation only during bounded owned cleanup.
            old_int = signal.signal(signal.SIGINT, signal.SIG_IGN) if handles_term else None
            if handles_term:
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
            try:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    process["term_sent"] = True
                except ProcessLookupError:
                    pass
                kill_reserve = min(.5, max(0, deadline - time.monotonic()) / 4)
                if wait_group(deadline - kill_reserve):
                    process["recovery_safe"] = True
                else:
                    process["cleanup_forced"] = True
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    wait_group(deadline)
                    exc.add_note("Deployment cleanup did not finish within its deadline; recovery forbidden")
            finally:
                if handles_term:
                    signal.signal(signal.SIGINT, old_int)
            raise
    finally:
        if handles_term:
            signal.signal(signal.SIGTERM, previous_term)
            signal.signal(signal.SIGINT, previous_int)
        if proc is None:
            # Failure to spawn cannot leave a programmer child behind.
            process.update(process_group_complete=True, recovery_safe=True)
