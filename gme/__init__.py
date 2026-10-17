"""
Gamelist Media Editor — local Flask app for EmulationStation / RetroBat gamelist.xml.

Architecture
------------
* Bound to 127.0.0.1 only (local tool, not exposed on the LAN).
* Starts **without** a gamelist; the user opens one via /api/open-gamelist
  (or passes a path on the CLI / drops a file onto the .exe).
* Media files live under the gamelist folder (images/, videos/, manuals/).
* XML is cached by mtime; writes are serialized with a process lock.
* ScreenScraper, Arcade Database and Steam scrapers share the same apply contract.
* PyInstaller: templates/static from sys._MEIPASS; writable config next to the .exe.

Modules
-------
==================  ===========================================================
``main``            entry point (CLI gamelist, window, server)
``server``          Flask app: request guards + blueprints
``security``        local-only guard (CSRF / DNS rebinding), game identity guard
``editor``          editor routes: list, open gamelist, media, metadata, tools
``scrapers.ss``     ScreenScraper client, parsing, routes
``scrapers.adb``    Arcade Database client, parsing, routes
``scrapers.steam``  Steam trailers, routes
``scrapers.common`` throttling, name matching, ROM hashes
``xml_store``       open gamelist.xml: path, cache, writes, game lookup
``media``           media files: extensions, downloads, placeholders, Pad2Key
``systems``         ScreenScraper system id from the RetroBat folder name
``arcade``          arcade hardware names from MAME drivers
``i18n``            server messages in the UI language
``window``          Chromium app-mode window / default browser
``paths``, ``version``, ``http``, ``log``: small shared pieces
==================  ===========================================================

Dependencies only go downwards (routes → scrapers → media / xml_store →
paths, i18n, http). ``xml_store.XML_PATH`` and ``xml_store.BASE_DIR`` change
when another gamelist is opened: always read them through the module.
"""
