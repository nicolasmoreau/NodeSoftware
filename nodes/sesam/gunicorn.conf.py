import os
def numCPUs():
    if not hasattr(os, "sysconf"):
        raise RuntimeError("No sysconf detected.")
    return os.sysconf("SC_NPROCESSORS_ONLN")
workers = numCPUs() * 2 + 1

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
pidfile = "/tmp/gunicorn.pid"
timeout = 60
daemon = False
