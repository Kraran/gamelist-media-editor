"""Game fields shared by the editor and the scrapers: validation and XML setters."""

from lxml import etree

from gme.xml_store import BOOL_META_FIELDS, META_FIELDS


class FieldError(ValueError):
    """A submitted value is invalid: (message key, error code)."""

    def __init__(self, key, code):
        super().__init__(key)
        self.key, self.code = key, code


def clean_meta(data):
    """Validate and normalize metadata fields; raises FieldError. Unknown keys ignored."""
    out = {}
    for field, value in data.items():
        if field not in META_FIELDS:
            continue
        value = (value or "").strip()
        if field == "rating" and value:
            try:
                fval = float(value)
            except ValueError:
                raise FieldError("server.rating_invalid", "rating_invalid")
            if not (0.0 <= fval <= 1.0):
                raise FieldError("server.rating_range", "rating_range")
            value = f"{fval:.2f}".rstrip("0").rstrip(".") if fval != 0 else "0"
        if field == "lang" and value:
            value = value.lower()
        if field in BOOL_META_FIELDS:
            value = "true" if value.lower() in ("true", "1", "yes", "on") else ""
        out[field] = value
    return out


def set_name(game, name):
    elem = game.find("name")
    if elem is None:
        elem = etree.Element("name")
        game.insert(0, elem)
    elem.text = name


def set_desc(game, desc):
    elem = game.find("desc")
    if elem is None:
        name_elem = game.find("name")
        if name_elem is not None:
            elem = etree.Element("desc")
            name_elem.addnext(elem)
        else:
            elem = etree.SubElement(game, "desc")
    elem.text = desc


def set_meta(game, cleaned):
    for field, value in cleaned.items():
        elem = game.find(field)
        if value == "":
            if elem is not None:
                game.remove(elem)
        else:
            if elem is None:
                elem = etree.SubElement(game, field)
            elem.text = value
