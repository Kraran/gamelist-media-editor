#!/usr/bin/env python3
"""Gamelist Media Editor — entry point (source runs, Lancer.bat, PyInstaller).

The application lives in the ``gme`` package; see ``gme/__init__.py``.
"""
from gme.main import main
from gme.server import app

__all__ = ["app", "main"]  # app.app: the Flask (WSGI) application

if __name__ == "__main__":
    main()
