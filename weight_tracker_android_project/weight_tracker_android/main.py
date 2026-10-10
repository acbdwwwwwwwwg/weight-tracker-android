"""Buildozer entrypoint. Application code is split into app, ui and services modules."""

from app import WeightApp

if __name__ == "__main__":
    WeightApp().run()
