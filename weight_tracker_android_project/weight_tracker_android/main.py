"""Buildozer entrypoint, instrumented to separate imports from app startup."""
from services.performance import mark

_process_entry = mark("python_entry")
_import_started = mark("app_import_start")
from app import WeightApp  # noqa: E402

mark("app_import_complete", _import_started)

if __name__ == "__main__":
    _run_started = mark("kivy_run_start", _process_entry)
    WeightApp().run()
    mark("kivy_run_returned", _run_started)
