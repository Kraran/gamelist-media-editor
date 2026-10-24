"""Flask application: request guards and blueprints."""

from flask import Flask

from gme import security
from gme.editor import bp as editor_bp
from gme.paths import resource_path
from gme.recent import bp as recent_bp
from gme.remote_cache import bp as remote_cache_bp
from gme.scrapers.adb import bp as adb_bp
from gme.scrapers.ss import bp as ss_bp
from gme.scrapers.steam import bp as steam_bp
from gme.thumbs import bp as thumbs_bp


app = Flask(
    __name__,
    template_folder=resource_path("templates"),
    static_folder=resource_path("static"),
)

# Large game lists: no key sorting, no indentation (≈4x faster to encode).
app.json.sort_keys = False
app.json.compact = True

# Order matters: reject foreign requests first, then check the game identity.
app.before_request(security.guard_local_requests)
app.before_request(security.check_game_identity)
app.after_request(security.flag_reindexed)

for blueprint in (editor_bp, ss_bp, adb_bp, steam_bp, thumbs_bp, remote_cache_bp, recent_bp):
    app.register_blueprint(blueprint)
