"""Entry point: optional gamelist from the command line, window, server."""

import sys
import threading

from gme.server import app
from gme.thumbs import prune_cache
from gme.version import APP_VERSION
from gme.window import open_browser
from gme.xml_store import close_gamelist, set_gamelist_path


def main():
    """Entry point for source runs and the frozen Windows .exe."""
    if getattr(sys, "frozen", False):
        try:
            import multiprocessing
            multiprocessing.freeze_support()
        except Exception:
            pass

    print("=" * 60)
    print(f"  Gamelist Media Editor v{APP_VERSION}")
    print("=" * 60)
    print()

    # Optional CLI path still supported (drag-drop onto .exe / Lancer.bat)
    # --no-browser: server only (CI smoke test, headless use)
    args = [a for a in sys.argv[1:] if a != "--no-browser"]
    no_browser = len(args) != len(sys.argv) - 1
    xml_arg = None
    if args:
        xml_arg = args[0].strip().strip('"').strip("'")
    if xml_arg:
        try:
            info = set_gamelist_path(xml_arg)
            print(f"  XML            : {info['xml_path']}")
            print(f"  Dossier medias : {info['base_dir']}")
        except Exception as e:
            print(f"  [WARN] Impossible d'ouvrir le gamelist fourni : {e}")
            print("  Demarre sans gamelist — utilise le menu « Gamelist… ».")
            close_gamelist()
    else:
        print("  Aucun gamelist charge.")
        print("  Ouvre un fichier via le bouton « Gamelist… » dans l'interface.")

    url = "http://127.0.0.1:5050"
    print()
    print(f"  Interface : {url}")
    print("  Fenetre application (sans barre d'adresse) si Edge/Chrome/Brave est dispo")
    print("  (Fermer la fenetre, Ctrl+C ou bouton Quitter pour arreter)")
    print("=" * 60)

    # Open the browser shortly after the server starts (exe-friendly)
    if not no_browser:
        threading.Timer(0.9, lambda: open_browser(url)).start()
    threading.Thread(target=prune_cache, daemon=True).start()

    # use_reloader=False required for PyInstaller / single process
    app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False, threaded=True)
