"""Flask application: request guards and blueprints."""

from flask import Flask

from gme import history, security
from gme.backups import bp as backups_bp
from gme.batch_jobs import bp as batch_bp
from gme.bulk import bp as bulk_bp
from gme.dattool import bp as dattool_bp
from gme.editor import bp as editor_bp
from gme.gamedelete import bp as gamedelete_bp
from gme.history import bp as history_bp
from gme.jobs import bp as jobs_bp
from gme.paths import resource_path
from gme.mediacheck import bp as mediacheck_bp
from gme.newgamelist import bp as newgamelist_bp
from gme.overview import bp as overview_bp
from gme.multibatch import bp as multibatch_bp
from gme.network import bp as network_bp
from gme.imageedit import bp as imageedit_bp
from gme.solidimages import bp as solidimages_bp
from gme.recent import bp as recent_bp
from gme.romcheck import bp as romcheck_bp
from gme.settings import bp as settings_bp
from gme.stats import bp as stats_bp
from gme.remote_cache import bp as remote_cache_bp
from gme.scrapers.adb import bp as adb_bp
from gme.scrapers.fallback import bp as sources_bp
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
app.before_request(security.begin_gamelist_request)
app.before_request(security.check_game_identity)
app.after_request(security.flag_reindexed)
app.after_request(history.add_revision_header)
app.teardown_request(security.end_gamelist_request)
app.teardown_request(history.finish)   # the request's writes become one undo step

for blueprint in (editor_bp, gamedelete_bp, ss_bp, adb_bp, steam_bp, thumbs_bp, remote_cache_bp, recent_bp, romcheck_bp, mediacheck_bp, settings_bp, backups_bp, batch_bp, bulk_bp, stats_bp, dattool_bp, newgamelist_bp, imageedit_bp, solidimages_bp, overview_bp, multibatch_bp, sources_bp, network_bp, history_bp, jobs_bp):
    app.register_blueprint(blueprint)
