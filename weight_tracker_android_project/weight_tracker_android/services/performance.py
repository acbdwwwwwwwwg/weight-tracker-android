"""Low-overhead startup and UI performance marks visible in Android logcat."""
from time import perf_counter

_PROCESS_START = perf_counter()


def mark(name, started_at=None, **details):
    """Emit one parseable timing line and return the current monotonic timestamp."""
    now = perf_counter()
    elapsed = (now - started_at) * 1000.0 if started_at is not None else None
    since_start = (now - _PROCESS_START) * 1000.0
    fields = [f"phase={name}", f"since_start_ms={since_start:.1f}"]
    if elapsed is not None:
        fields.append(f"elapsed_ms={elapsed:.1f}")
    for key, value in details.items():
        safe = str(value).replace("\n", " ").replace("\r", " ")
        fields.append(f"{key}={safe}")
    print("[PERF] " + " ".join(fields), flush=True)
    return now
