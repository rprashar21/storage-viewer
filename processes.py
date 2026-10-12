"""Read-only process sampler. CPU is per-core scale (100% = one core)."""
import time
import psutil


class ProcessSampler:
    def __init__(self):
        self._seen = set()
        psutil.cpu_percent(None)

    def sample(self):
        rows, alive = [], set()
        for proc in psutil.process_iter():
            try:
                key = (proc.pid, proc.create_time())
                alive.add(key)
                if key in self._seen:
                    cpu = proc.cpu_percent(None)
                else:
                    proc.cpu_percent(None)
                    cpu = None
                rows.append({'pid': proc.pid, 'name': proc.name(), 'cpu': cpu,
                             'rss': proc.memory_info().rss, 'state': 'ok'})
            except psutil.AccessDenied:
                rows.append({'pid': proc.pid, 'name': proc.name() if proc.is_running() else '?',
                             'cpu': None, 'rss': None, 'state': 'denied'})
            except psutil.Error:
                continue
        self._seen = alive
        mem = psutil.virtual_memory()
        return {'at': time.time(), 'cpu_total': psutil.cpu_percent(None), 'cores': psutil.cpu_count(),
                'mem_total': mem.total, 'mem_used': mem.total - mem.available, 'procs': rows}
