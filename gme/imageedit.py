"""Built-in image editor (Pillow): crop, rotate / flip, transparent background,
auto-trim, resize and format conversion of a game's image media.

POST /api/image-edit/<index>/<field>/preview  {"ops": {...}}   writes nothing
POST /api/image-edit/<index>/<field>          {"ops": {...}, "mode": "overwrite" | "new"}
POST /api/image-edit/batch/preview            {"paths": [...], "field": "wheel", "ops": {...}}
POST /api/image-edit/batch                    same body
POST /api/image-edit/undo                     {"id": "<edit id>"}

``ops`` (every key optional; they run in this order):

- ``crop``: ``{"x", "y", "w", "h"}`` in pixels of the source image;
- ``rotate``: 0, 90, 180 or 270 (degrees clockwise); ``flip_h`` / ``flip_v``;
- ``bg``: ``{"mode": "flood" | "key", "color": "#rrggbb" | null, "tolerance": 0-100}``
  makes the background transparent: ``flood`` the area of that colour touching
  the edges (logos), ``key`` that colour everywhere. No colour = the most
  common corner colour;
- ``trim``: ``{"tolerance": 0-100}`` removes transparent or uniform borders;
- ``resize``: ``{"max_w": px, "max_h": px, "upscale": false}`` fits the image
  in that box, keeping its proportions;
- ``format``: ``keep`` | ``png`` | ``jpg`` | ``webp``, ``quality`` 1-100
  (JPG / WebP), ``matte`` ``#rrggbb``: background of transparent pixels in a JPG.

Saving: ``overwrite`` replaces the file (a copy of the original is kept) and,
when the format changes, writes ``name.<new ext>`` and points the tag at it
(the old file goes to the Recycle Bin, as for a replaced media). ``new`` writes
``name-edit.<ext>`` next to it and points the tag at the copy; the original
stays. A file another tag also uses is never overwritten: the edit goes to a
new file. Every save returns an edit id: ``/api/image-edit/undo`` puts the
original files back and restores the gamelist snapshot taken before (when the
gamelist changed). Originals live in ``.gme-backups/<gamelist>/media/<id>/``;
the last ``MAX_EDITS`` edits are kept.

Batch apply only takes ``trim``, ``resize`` and ``format`` / ``quality`` /
``matte``, and skips images it would not change.
"""
import base64
import io
import json
import os
import re
import shutil
import uuid
import warnings
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from gme import fsutil, history, xml_store
from gme.backups import backup_dir, restore_snapshot
from gme.http import api_err
from gme.i18n import st
from gme.log import log
from gme.media import discard_old_media, file_in_use
from gme.xml_store import MEDIA_DIRS, get_game_elem, load_xml, require_gamelist, resolve_under_base, save_xml

bp = Blueprint("imageedit", __name__)

NOT_IMAGE_FIELDS = {"video", "manual", "music"}
IMAGE_FIELDS = tuple(f for f in MEDIA_DIRS if f not in NOT_IMAGE_FIELDS)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
PREVIEW_SIDE = 1024          # px: the live preview works on a copy this large at most
MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_EDITS = 20               # edits whose originals are kept for undo
BATCH_PREVIEW_ROWS = 40      # images computed for a batch preview
_EDIT_ID = re.compile(r"^\d{8}T\d{12}Z-[0-9a-f]{8}$")
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
_FORMATS = {"png": ("PNG", ".png", "image/png"), "jpg": ("JPEG", ".jpg", "image/jpeg"),
            "webp": ("WEBP", ".webp", "image/webp"), "gif": ("GIF", ".gif", "image/gif"),
            "bmp": ("BMP", ".bmp", "image/bmp")}
_EXT_FORMAT = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".webp": "webp", ".gif": "gif", ".bmp": "bmp"}


class EditError(ValueError):
    def __init__(self, key, status=400, **params):
        super().__init__(key)
        self.key, self.status, self.params = key, status, params


def _error(e):
    return api_err(st(e.key, **e.params), e.status, code=e.key.replace(".", "_"))


def webp_supported():
    try:
        from PIL import features
        return bool(features.check("webp"))
    except Exception:
        return False


# --- Options -------------------------------------------------------------------

def _int(value, lo, hi, default):
    try:
        value = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _color(value):
    if value in (None, ""):
        return None
    m = _HEX.match(str(value).strip())
    if not m:
        raise EditError("imgedit.bad_ops")
    h = m.group(1)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def clean_ops(raw, batch=False):
    """Validated operations, with defaults; raises EditError."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise EditError("imgedit.bad_ops")
    ops = {"crop": None, "rotate": 0, "flip_h": False, "flip_v": False, "bg": None, "trim": None,
           "resize": None, "format": "keep", "quality": 90, "matte": (255, 255, 255)}
    if not batch:
        crop = raw.get("crop")
        if isinstance(crop, dict):
            box = [_int(crop.get(k), 0, 1 << 16, -1) for k in ("x", "y", "w", "h")]
            if min(box) < 0:
                raise EditError("imgedit.bad_ops")
            if box[2] >= 1 and box[3] >= 1:
                ops["crop"] = tuple(box)
        rotate = _int(raw.get("rotate"), -3600, 3600, 0) % 360
        if rotate % 90:
            raise EditError("imgedit.bad_ops")
        ops["rotate"] = rotate
        ops["flip_h"] = bool(raw.get("flip_h"))
        ops["flip_v"] = bool(raw.get("flip_v"))
        bg = raw.get("bg")
        if isinstance(bg, dict) and bg.get("mode") in ("flood", "key"):
            ops["bg"] = {"mode": bg["mode"], "color": _color(bg.get("color")),
                         "tolerance": _int(bg.get("tolerance"), 0, 100, 10)}
    trim = raw.get("trim")
    if isinstance(trim, dict):
        ops["trim"] = {"tolerance": _int(trim.get("tolerance"), 0, 100, 5)}
    resize = raw.get("resize")
    if isinstance(resize, dict):
        mw = _int(resize.get("max_w"), 0, 16384, 0)
        mh = _int(resize.get("max_h"), 0, 16384, 0)
        if mw or mh:
            ops["resize"] = {"max_w": mw, "max_h": mh, "upscale": bool(resize.get("upscale"))}
    fmt = raw.get("format") or "keep"
    if fmt not in ("keep", "png", "jpg", "webp"):
        raise EditError("imgedit.bad_ops")
    if fmt == "webp" and not webp_supported():
        raise EditError("imgedit.webp_unsupported")
    ops["format"] = fmt
    ops["quality"] = _int(raw.get("quality"), 1, 100, 90)
    ops["matte"] = _color(raw.get("matte")) or (255, 255, 255)
    return ops


# --- Pixels ----------------------------------------------------------------------

def open_image(data):
    """RGBA copy of the first frame, upright (EXIF orientation), and its format key."""
    from PIL import Image, ImageOps
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                fmt = (im.format or "").upper()
                im.seek(0)
                im.load()
                im = ImageOps.exif_transpose(im)
                rgba = im.convert("RGBA")
    except Exception as e:
        raise EditError("imgedit.unreadable") from e
    key = {"PNG": "png", "JPEG": "jpg", "MPO": "jpg", "WEBP": "webp", "GIF": "gif", "BMP": "bmp"}.get(fmt, "png")
    return rgba, key


def _distance_mask(img, color):
    """L image: largest channel difference between each pixel and ``color``."""
    from PIL import Image, ImageChops
    diff = ImageChops.difference(img.convert("RGB"), Image.new("RGB", img.size, color))
    r, g, b = diff.split()
    return ImageChops.lighter(ImageChops.lighter(r, g), b)


def corner_color(img):
    """Most common of the four corner colours (ties: top-left)."""
    w, h = img.size
    rgb = img.convert("RGB")
    corners = [rgb.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    return max(corners, key=corners.count)


def _threshold(tolerance):
    return int(round(tolerance * 2.55))


def make_transparent(img, mode, color, tolerance):
    from PIL import ImageChops, ImageDraw
    color = color or corner_color(img)
    thr = _threshold(tolerance)
    near = _distance_mask(img, color).point(lambda v: 255 if v <= thr else 0)
    if mode == "flood":
        # Only the area of that colour connected to an edge: the inside of a
        # logo of the same colour stays opaque.
        w, h = near.size
        edge = [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] + \
               [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]
        px = near.load()
        for p in edge:
            if px[p] == 255:
                ImageDraw.floodfill(near, p, 128, thresh=0)
        near = near.point(lambda v: 255 if v == 128 else 0)
    out = img.copy()
    alpha = ImageChops.multiply(out.getchannel("A"), near.point(lambda v: 255 - v))
    out.putalpha(alpha)
    return out


def trim_box(img, tolerance):
    """Bounding box of the content: without transparent borders when the
    corners are transparent, else without borders of the top-left colour."""
    thr = _threshold(tolerance)
    alpha = img.getchannel("A")
    w, h = img.size
    corners = [alpha.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    if max(corners) <= thr:
        return alpha.point(lambda v: 255 if v > thr else 0).getbbox()
    ref = img.convert("RGB").getpixel((0, 0))
    mask = _distance_mask(img, ref).point(lambda v: 255 if v > thr else 0)
    # A transparent pixel of another colour is still border
    from PIL import ImageChops
    mask = ImageChops.multiply(mask, alpha.point(lambda v: 255 if v > thr else 0))
    return mask.getbbox()


def fit_size(w, h, max_w, max_h, upscale=False):
    scale = min(max_w / w if max_w else float("inf"), max_h / h if max_h else float("inf"))
    if scale == float("inf") or (scale >= 1 and not upscale):
        return w, h
    return max(1, int(round(w * scale))), max(1, int(round(h * scale)))


def apply_ops(img, ops, scale=1.0):
    """The edited RGBA image. ``scale`` < 1: ``img`` is a reduced copy of the
    source (live preview); crop and resize sizes are scaled to match."""
    from PIL import Image
    if ops.get("crop"):
        x, y, w, h = (v * scale for v in ops["crop"])
        x0, y0 = max(0, int(round(x))), max(0, int(round(y)))
        x1, y1 = min(img.width, int(round(x + w))), min(img.height, int(round(y + h)))
        if x1 - x0 >= 1 and y1 - y0 >= 1:
            img = img.crop((x0, y0, x1, y1))
    rotate = ops.get("rotate") or 0
    if rotate:
        img = img.transpose({90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180,
                             270: Image.Transpose.ROTATE_90}[rotate])
    if ops.get("flip_h"):
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if ops.get("flip_v"):
        img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    if ops.get("bg"):
        bg = ops["bg"]
        img = make_transparent(img, bg["mode"], bg["color"], bg["tolerance"])
    if ops.get("trim"):
        box = trim_box(img, ops["trim"]["tolerance"])
        if box and box != (0, 0, img.width, img.height):
            img = img.crop(box)
    if ops.get("resize"):
        r = ops["resize"]
        size = fit_size(img.width, img.height, r["max_w"] * scale, r["max_h"] * scale, r["upscale"])
        if size != img.size:
            img = img.resize(size, Image.Resampling.LANCZOS)
    return img


def output_format(ops, source_fmt):
    return source_fmt if ops["format"] == "keep" else ops["format"]


def encode(img, fmt, quality=90, matte=(255, 255, 255)):
    """Bytes of ``img`` in ``fmt`` (png, jpg, webp, gif, bmp)."""
    from PIL import Image
    pil_fmt = _FORMATS[fmt][0]
    opaque = img.getchannel("A").getextrema()[0] == 255
    out = io.BytesIO()
    if fmt == "jpg" or (fmt == "bmp" and not opaque):
        flat = Image.new("RGB", img.size, matte)
        flat.paste(img, mask=img.getchannel("A"))
        if fmt == "jpg":
            flat.save(out, "JPEG", quality=quality, optimize=True)
        else:
            flat.save(out, "BMP")
    elif fmt == "png":
        _png_smallest(img, opaque).save(out, "PNG", optimize=True)
    elif fmt == "webp":
        img.save(out, "WEBP", quality=quality, method=4, lossless=quality >= 100)
    elif fmt == "gif":
        img.save(out, "GIF")
    else:
        img.convert("RGB").save(out, pil_fmt)
    return out.getvalue()


def _png_smallest(img, opaque):
    """A palette copy when the image has at most 256 colours (a crop or a
    rotation of a palette PNG stays as small as the original), else RGB / RGBA."""
    from PIL import Image
    colors = img.getcolors(256) if img.width * img.height <= 4_000_000 else None
    if colors:
        palette = [c for _n, c in colors]
        index = {bytes(c): i for i, c in enumerate(palette)}
        raw = img.tobytes()
        pal = Image.frombytes("P", img.size, bytes(index[raw[i:i + 4]] for i in range(0, len(raw), 4)))
        flat = [v for c in palette for v in c]
        if opaque:
            pal.putpalette([v for i, v in enumerate(flat) if i % 4 != 3], "RGB")
        else:
            pal.putpalette(flat, "RGBA")
        return pal
    return img.convert("RGB") if opaque else img


def is_empty(img):
    """Every pixel transparent (a background colour also used by the art)."""
    return img.getchannel("A").getextrema()[1] == 0


def has_alpha(img):
    return img.getchannel("A").getextrema()[0] < 255


# --- Files -------------------------------------------------------------------------

def _media_full(game, field):
    if field not in IMAGE_FIELDS:
        raise EditError("imgedit.not_image_field")
    rel = (game.findtext(field, "") or "").strip()
    full = resolve_under_base(rel) if rel else None
    if not full or not os.path.isfile(full):
        raise EditError("imgedit.no_media", 404)
    if os.path.splitext(full)[1].lower() not in IMAGE_EXTS:
        raise EditError("imgedit.not_image_file")
    if os.path.getsize(full) > MAX_SOURCE_BYTES:
        raise EditError("imgedit.too_large", n=MAX_SOURCE_BYTES // (1024 * 1024))
    return rel, full


def _read(full):
    with open(full, "rb") as f:
        return f.read()


def _rel(full):
    return xml_store.gamelist_value(full)


def _free_name(folder, stem, ext, taken=()):
    """``stem.ext``, else ``stem-2.ext``… a name no file has yet."""
    n = 1
    while True:
        name = f"{stem}{ext}" if n == 1 else f"{stem}-{n}{ext}"
        full = os.path.join(folder, name)
        if not os.path.exists(full) and os.path.normcase(full) not in taken:
            return full
        n += 1


def _edits_root():
    return os.path.join(backup_dir(), "media")


class EditLog:
    """Originals and new files of one save (single or batch), for undo."""

    def __init__(self):
        now = datetime.now(timezone.utc)
        self.id = now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
        self.dir = os.path.join(_edits_root(), self.id)
        self.restore, self.created, self.xml_snapshot = [], [], None
        self.started = False

    def keep_original(self, full):
        if not self.started:
            os.makedirs(self.dir, exist_ok=True)
            self.started = True
        name = "%04d%s" % (len(self.restore) + 1, os.path.splitext(full)[1].lower())
        shutil.copy2(full, os.path.join(self.dir, name))
        self.restore.append({"path": _rel(full), "backup": name})

    def wrote_new(self, full):
        self.created.append(_rel(full))

    def save(self):
        if not self.started:
            os.makedirs(self.dir, exist_ok=True)
        data = {"version": 1, "created": datetime.now(timezone.utc).isoformat(),
                "xml_snapshot": self.xml_snapshot, "restore": self.restore, "created_files": self.created}
        fsutil.atomic_write(os.path.join(self.dir, "manifest.json"), json.dumps(data, indent=1).encode("utf-8"))
        _prune_edits()


def _prune_edits():
    root = _edits_root()
    try:
        names = sorted((n for n in os.listdir(root) if _EDIT_ID.fullmatch(n)), reverse=True)
    except OSError:
        return
    for old in names[MAX_EDITS:]:
        shutil.rmtree(os.path.join(root, old), ignore_errors=True)


def save_edit(game, field, ops, mode, edit, img=None, source_fmt=None):
    """Write the edited image of ``game``'s ``field``; returns a result dict.

    Called with the operation lock held. The caller saves the XML when
    ``result["path_changed"]`` (after one snapshot for the whole operation).
    """
    rel, full = _media_full(game, field)
    if img is None:
        source, source_fmt = open_image(_read(full))
        img = apply_ops(source, ops)
    if is_empty(img):
        raise EditError("imgedit.empty_result")
    fmt = output_format(ops, source_fmt)
    data = encode(img, fmt, ops["quality"], ops["matte"])
    ext = _FORMATS[fmt][1]
    folder, name = os.path.split(full)
    stem, old_ext = os.path.splitext(name)
    same_ext = _EXT_FORMAT.get(old_ext.lower()) == fmt
    shared = file_in_use(game, rel, skip_tag=field)
    if xml_store.is_esde():
        # ES-DE finds a media by its name: the edit always takes the media's place
        mode, shared = "overwrite", False
        dest = full if same_ext else os.path.join(folder, stem + ext)
    elif mode == "new":
        dest = _free_name(folder, stem + "-edit", ext)
    elif same_ext and not shared:
        dest = full
    elif shared:
        dest = _free_name(folder, stem + "-edit", ext)
    else:
        dest = _free_name(folder, stem, ext)
    in_place = os.path.normcase(dest) == os.path.normcase(full)
    if in_place:
        edit.keep_original(full)
    fsutil.atomic_write(dest, data)
    if not in_place:
        edit.wrote_new(dest)
    new_rel = rel if in_place else _rel(dest)
    trashed = False
    if not in_place and mode == "overwrite" and not shared:
        # Format change: the original goes where a replaced media goes (Recycle
        # Bin), after a copy for undo.
        edit.keep_original(full)
        trashed = discard_old_media(game, field, rel, new_rel)
    return {"path": new_rel, "old_path": rel, "path_changed": new_rel != rel, "shared": shared,
            "width": img.width, "height": img.height, "bytes": len(data), "format": fmt,
            "trashed": trashed}


def _set_tag(game, field, value):
    elem = game.find(field)
    elem.text = value


# --- Routes ---------------------------------------------------------------------------

def _body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _game(index):
    try:
        return get_game_elem(index)
    except IndexError:
        raise EditError("imgedit.no_game", 404)


@bp.route("/api/image-edit/<int:index>/<field>/preview", methods=["POST"])
def api_preview(index, field):
    err = require_gamelist()
    if err:
        return err
    try:
        ops = clean_ops(_body().get("ops"))
        _tree, game = _game(index)
        _rel_path, full = _media_full(game, field)
        data = _read(full)
        source, source_fmt = open_image(data)
        sw, sh = source.size
        scale = 1.0
        work = source
        if max(sw, sh) > PREVIEW_SIDE:
            from PIL import Image
            scale = PREVIEW_SIDE / max(sw, sh)
            work = source.resize((max(1, round(sw * scale)), max(1, round(sh * scale))), Image.Resampling.BILINEAR)
        out = apply_ops(work, ops, scale)
        fmt = output_format(ops, source_fmt)
        shown = encode(out, fmt if fmt in ("jpg", "webp") else "png", ops["quality"], ops["matte"])
        mime = _FORMATS[fmt if fmt in ("jpg", "webp") else "png"][2]
        exact = scale == 1.0
        width = out.width if exact else max(1, round(out.width / scale))
        height = out.height if exact else max(1, round(out.height / scale))
        if ops["resize"] and not exact:
            r = ops["resize"]
            # The resize box is exact: snap to it
            if r["max_w"] and abs(width - r["max_w"]) <= 2:
                width = r["max_w"]
            if r["max_h"] and abs(height - r["max_h"]) <= 2:
                height = r["max_h"]
        return jsonify({
            "data": "data:%s;base64,%s" % (mime, base64.b64encode(shown).decode("ascii")),
            "width": width, "height": height, "exact": exact, "format": fmt,
            "bytes": len(encode(out, fmt, ops["quality"], ops["matte"])) if exact else None,
            "alpha": has_alpha(out), "empty": is_empty(out), "alpha_lost": fmt in ("jpg", "bmp") and has_alpha(out),
            "source": {"width": sw, "height": sh, "format": source_fmt, "bytes": len(data)},
            "webp": webp_supported(),
        })
    except EditError as e:
        return _error(e)


@bp.route("/api/image-edit/<int:index>/<field>", methods=["POST"])
def api_save(index, field):
    err = require_gamelist()
    if err:
        return err
    body = _body()
    mode = body.get("mode") or "overwrite"
    try:
        if mode not in ("overwrite", "new"):
            raise EditError("imgedit.bad_ops")
        ops = clean_ops(body.get("ops"))
        tree, game = _game(index)
        _media_full(game, field)
        edit = EditLog()
        try:
            res = save_edit(game, field, ops, mode, edit)
        except OSError as e:
            log.warning("Image edit failed: %s", e)
            raise EditError("imgedit.write_failed", 500, detail=str(e))
        history.label("image_edit", game=history.game_name(game), field=field)
        if res["path_changed"]:
            _bak, edit.xml_snapshot = xml_store.backup_xml_snapshot()
            _set_tag(game, field, res["path"])
            save_xml(tree)
        edit.save()
        history.note_image_edit(edit.id)
        res.update({"success": True, "field": field, "undo": edit.id})
        return jsonify(res)
    except EditError as e:
        return _error(e)


def _batch_plan(body):
    field = body.get("field")
    if field not in IMAGE_FIELDS:
        raise EditError("imgedit.not_image_field")
    paths = body.get("paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
        raise EditError("imgedit.no_games")
    ops = clean_ops(body.get("ops"), batch=True)
    if not (ops["trim"] or ops["resize"] or ops["format"] != "keep"):
        raise EditError("imgedit.batch_nothing")
    wanted = set(paths)
    tree = load_xml()
    targets, missing = [], 0
    for game in tree.getroot().findall("game"):
        if (game.findtext("path", "") or "") not in wanted:
            continue
        try:
            _media_full(game, field)
            targets.append(game)
        except EditError:
            missing += 1
    return tree, field, ops, targets, missing


def _batch_one(game, field, ops):
    """(source info, edited image, source format, changed) for one game."""
    _rel_path, full = _media_full(game, field)
    data = _read(full)
    source, source_fmt = open_image(data)
    out = apply_ops(source, ops)
    changed = out.size != source.size or ops["format"] != "keep"
    return {"width": source.width, "height": source.height, "bytes": len(data), "format": source_fmt}, \
        out, source_fmt, changed


def _row(game, field):
    return {"path": game.findtext("path", "") or "", "name": game.findtext("name", "") or "",
            "file": game.findtext(field, "") or ""}


@bp.route("/api/image-edit/batch/preview", methods=["POST"])
def api_batch_preview():
    err = require_gamelist()
    if err:
        return err
    try:
        _tree, field, ops, targets, missing = _batch_plan(_body())
        rows, unchanged, failed = [], 0, 0
        for game in targets[:BATCH_PREVIEW_ROWS]:
            row = _row(game, field)
            try:
                before, out, source_fmt, changed = _batch_one(game, field, ops)
            except EditError:
                failed += 1
                continue
            if not changed:
                unchanged += 1
                continue
            fmt = output_format(ops, source_fmt)
            row.update({"before": before, "after": {
                "width": out.width, "height": out.height, "format": fmt,
                "bytes": len(encode(out, fmt, ops["quality"], ops["matte"]))}})
            rows.append(row)
        return jsonify({"total": len(targets), "missing": missing, "rows": rows,
                        "checked": min(len(targets), BATCH_PREVIEW_ROWS),
                        "unchanged": unchanged, "failed": failed})
    except EditError as e:
        return _error(e)


@bp.route("/api/image-edit/batch", methods=["POST"])
def api_batch_apply():
    err = require_gamelist()
    if err:
        return err
    try:
        tree, field, ops, targets, _missing = _batch_plan(_body())
    except EditError as e:
        return _error(e)
    edit = EditLog()
    changed, unchanged, failed, renamed = [], 0, [], []
    for game in targets:
        try:
            _before, out, source_fmt, is_changed = _batch_one(game, field, ops)
            if not is_changed:
                unchanged += 1
                continue
            res = save_edit(game, field, ops, "overwrite", edit, img=out, source_fmt=source_fmt)
            changed.append(res["path"])
            if res["path_changed"]:
                renamed.append((game, res["path"]))
        except (EditError, OSError) as e:
            log.warning("Batch image edit: %s skipped (%s)", game.findtext("path", ""), e)
            failed.append(game.findtext("path", "") or "")
    if changed:
        history.label("image_batch", n=len(changed), field=field)
    try:
        if renamed:
            _bak, edit.xml_snapshot = xml_store.backup_xml_snapshot()
            for game, value in renamed:
                _set_tag(game, field, value)
            save_xml(tree)
        if changed:
            edit.save()
            history.note_image_edit(edit.id)
    except OSError as e:
        return api_err(str(e), 500, code="write_failed")
    return jsonify({"success": True, "changed": len(changed), "unchanged": unchanged, "failed": failed,
                    "renamed": len(renamed), "paths": changed, "undo": edit.id if changed else None})


class UndoMissing(EditError):
    def __init__(self):
        super().__init__("imgedit.undo_missing", 404)


def _manifest(edit_id):
    if not isinstance(edit_id, str) or not _EDIT_ID.fullmatch(edit_id):
        raise UndoMissing()
    folder = os.path.join(_edits_root(), edit_id)
    try:
        with open(os.path.join(folder, "manifest.json"), "rb") as f:
            return folder, json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError):
        raise UndoMissing()


def restore_files(edit_id, forget=True):
    """Put the originals of edit ``edit_id`` back and remove the files it
    created; the gamelist is left alone. Returns ``(restored, paths)``.
    Raises ``EditError`` when the edit is unknown (pruned)."""
    folder, manifest = _manifest(edit_id)
    restored, paths = 0, []
    put_back = set()
    for item in manifest.get("restore", []):
        full = resolve_under_base(item.get("path"))
        name = os.path.basename(str(item.get("backup", "")))
        src = os.path.join(folder, name)
        if not full or not name or not os.path.isfile(src):
            continue
        os.makedirs(os.path.dirname(full), exist_ok=True)
        fsutil.atomic_write(full, _read(src))
        put_back.add(os.path.normcase(full))
        restored += 1
        paths.append(item["path"])
    for rel in manifest.get("created_files", []):
        full = resolve_under_base(rel)
        if full and os.path.isfile(full) and os.path.normcase(full) not in put_back:
            os.remove(full)
    if forget:
        shutil.rmtree(folder, ignore_errors=True)
    return restored, paths


@bp.route("/api/image-edit/undo", methods=["POST"])
def api_undo():
    err = require_gamelist()
    if err:
        return err
    edit_id = _body().get("id")
    try:
        folder, manifest = _manifest(edit_id)
    except EditError as e:
        return _error(e)
    try:
        restored, paths = restore_files(edit_id, forget=False)
        session = None
        snapshot = manifest.get("xml_snapshot")
        if snapshot:
            if restore_snapshot(snapshot) is None:
                return _error(EditError("imgedit.undo_missing", 404))
            session = xml_store.SESSION_ID
        shutil.rmtree(folder, ignore_errors=True)
    except EditError as e:
        return _error(e)
    except (OSError, ValueError) as e:
        return api_err(str(e), 500, code="undo_failed")
    history.label("image_undo")
    return jsonify({"success": True, "restored": restored, "paths": paths, "session_id": session})
