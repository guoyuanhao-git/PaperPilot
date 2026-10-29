"""Cooperative cancellation for paper Q&A and reading report tasks."""
import contextvars
import os
from contextlib import contextmanager
import queue
import subprocess
import threading
import time

CURRENT = contextvars.ContextVar('paperpilot_cancel', default=None)


class Cancelled(ValueError):
    pass


class Control:
    def __init__(self):
        self.event = threading.Event()
        self.committed = False  # Protected by service.SAVE_LOCK.
        self.lock = threading.Lock()
        self.closers = set()

    def check(self):
        if self.event.is_set():
            raise Cancelled('已停止回答')

    def cancel(self):
        self.event.set()
        with self.lock:
            for close in self.closers:
                threading.Thread(target=_close, args=(close,), daemon=True).start()


def _close(close):
    try:
        close()
    except Exception:
        pass


def check():
    control = CURRENT.get()
    if control:
        control.check()


@contextmanager
def response_connection(response):
    control = CURRENT.get()
    if not control:
        yield
        return
    close = response.close
    with control.lock:
        control.check()
        control.closers.add(close)
    try:
        yield
    finally:
        with control.lock:
            control.closers.discard(close)


def http_call(call):
    control = CURRENT.get()
    if not control:
        return call()
    control.check()
    # urllib cannot cancel DNS/connect synchronously. Free the task worker at
    # once; close the response when available and discard any late result.
    results = queue.Queue(maxsize=1)
    context = contextvars.copy_context()
    def run():
        try:
            results.put((True, context.run(call)))
        except Exception as exc:
            results.put((False, exc))
    threading.Thread(target=run, daemon=True).start()
    while True:
        control.check()
        try:
            ok, value = results.get(timeout=.1)
        except queue.Empty:
            continue
        control.check()
        if ok:
            return value
        raise value


def run_process(command, *, env, input, timeout):
    control = CURRENT.get()
    if not control:
        return subprocess.run(command, env=env, input=input, text=True, capture_output=True, timeout=timeout)
    if control:
        control.check()
    process = subprocess.Popen(command, env=env, text=True, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8' if os.name == 'nt' else None)
    close_job = None
    deadline = time.monotonic() + timeout
    first = True
    try:
        from .codex_runtime import process_job
        close_job = process_job(process)
        while True:
            if control:
                control.check()
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(input=input if first else None, timeout=.1)
                if control:
                    control.check()
                return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                first = False
    finally:
        if close_job:
            close_job()
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
