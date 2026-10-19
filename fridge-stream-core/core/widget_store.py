"""
Chat widgets: StreamElements / Streamlabs custom code widgets (HTML + CSS + JS + fields),
run by Core.

A widget is imported once (the zip StreamElements exports, or the four boxes pasted in) and
kept in ``data/widgets/<name>/``:

    widget.json   platform ("streamelements" / "streamlabs"), when it was added, version
    html.txt  css.txt  js.txt
    fields.json   the widget's settings list ({key: {type, label, value, ...}})
    data.json     the values chosen for them (StreamElements' "data.txt")

The overlay page ``/overlay/widget.html?name=<name>`` shows it: Core's own page talks to
``/ws`` and passes chat and alerts, translated into the platform's event format
(``overlay/widget-bridge.js``), into a sandboxed frame ``/widget-frame/<name>`` that holds
the widget's code. The frame has no access to Core's origin (no dashboard token, no admin
API): the widget's code is someone else's and often obfuscated.

``compose`` builds that frame: settings filled into the code the way the platform does it
(``{{key}}`` and ``{key}`` on StreamElements, ``{{key}}`` on Streamlabs), the common chat
placeholders filled by ``css_templates``, jQuery and Core's shim loaded first.
"""

from __future__ import annotations

import configparser
import io
import json
import logging
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Optional

from core.css_templates import fill_placeholders
from core.media_library import clean_name, decode_base64, name_from_filename

log = logging.getLogger("core.widget_store")

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "widgets"
PLATFORMS = ("streamelements", "streamlabs")
PARTS = ("html", "css", "js", "fields", "data")
PART_FILES = {"html": "html.txt", "css": "css.txt", "js": "js.txt", "fields": "fields.json", "data": "data.json"}
# Size limits in bytes (one imported zip, one part), and the most widgets kept.
# JQUERY: StreamElements widgets expect jQuery, so the frame loads Core's local copy first.
MAX_ZIP_BYTES = 20 * 1024 * 1024
MAX_PART_BYTES = 5 * 1024 * 1024
MAX_WIDGETS = 100
JQUERY = "/overlay/vendor/jquery-3.7.1.min.js"
# the frame runs in its own blank origin: scripts yes, Core's origin (token, admin API) no
FRAME_CSP = "sandbox allow-scripts"


def _read_json(raw: str, what: str) -> dict[str, Any]:
    """Parse a fields / data box as a JSON object ({} when empty); ValueError with a readable reason."""
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ValueError(f"The {what} aren't valid JSON ({e.msg}, line {e.lineno}).") from e
    if not isinstance(data, dict):
        raise ValueError(f"The {what} should be a JSON object ({{ ... }}).")
    return data


def guess_platform(parts: dict[str, str]) -> str:
    """StreamElements unless the code looks like a Streamlabs chat box / widget."""
    html, js = parts.get("html") or "", parts.get("js") or ""
    if re.search(r"onWidgetLoad|SE_API|\"listener\"|\.listener\b", js):
        return "streamelements"
    if "chatlist_item" in html or re.search(r"addEventListener\(\s*['\"]onLoad['\"]", js):
        return "streamlabs"
    return "streamelements"


def field_values(fields: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Each field's default ("value") with the saved values on top (saved keys without a
    field are kept: StreamElements' data.txt often holds more than fields.txt lists)."""
    out: dict[str, Any] = {}
    for key, f in (fields or {}).items():
        if isinstance(f, dict) and "value" in f:
            out[str(key)] = f["value"]
    for key, v in (data or {}).items():
        out[str(key)] = v
    return out


def _as_text(value: Any) -> str:
    """A field value as it is written into widget code (true / false, JSON for lists and objects)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def fill_fields(text: str, values: dict[str, Any], single: bool) -> str:
    """{{key}} (and {key} when ``single``) -> the field's value, for keys the widget has.
    Anything else in braces (CSS rules, JS objects, Streamlabs' {from}) is left alone."""
    if not text or not values:
        return text
    pattern = r"\{\{\s*([A-Za-z_][\w-]*)\s*\}\}"
    if single:
        pattern += r"|\{([A-Za-z_][\w-]*)\}"

    def sub(m: re.Match) -> str:
        """The field's value for one match, or the match unchanged when the key is not a field."""
        key = m.group(1) or (m.group(2) if single else None)
        if key is None or key not in values:
            return m.group(0)
        return _as_text(values[key])

    return re.sub(pattern, sub, text)


def _script_safe(js: str) -> str:
    """Keep widget code inside its <script> (a "</script>" in a string would end it)."""
    return re.sub(r"</(script)", r"<\\/\1", js or "", flags=re.IGNORECASE)


# ── reading an exported zip ────────────────────────────────────────────
def _part_for(filename: str) -> Optional[str]:
    """Which widget part ("html", "css", "js", "fields", "data") a zip entry is, by its name; None to skip."""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base.startswith(".") or base.startswith("__macosx"):
        return None
    stem, _, ext = base.rpartition(".")
    stem = stem or base
    if base in ("html.txt", "index.html") or ext in ("html", "htm"):
        return "html"
    if base == "css.txt" or ext == "css":
        return "css"
    if base in ("js.txt", "script.txt") or ext == "js":
        return "js"
    # StreamElements' GitHub widgets keep the fields in widget.json
    if base in ("fields.txt", "fields.json", "widget.json") or ("field" in stem and ext in ("json", "txt")):
        return "fields"
    if base in ("data.txt", "data.json"):
        return "data"
    return None


def read_zip(raw: bytes) -> dict[str, str]:
    """{part: text} from a widget zip: StreamElements' export (widget.ini + html.txt, css.txt,
    js.txt, fields.txt, data.txt) or any zip with .html / .css / .js / fields .json files."""
    if len(raw) > MAX_ZIP_BYTES:
        raise ValueError("That zip is bigger than 20 MB.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as e:
        raise ValueError("That isn't a zip file.") from e
    infos = [i for i in zf.infolist() if not i.is_dir() and "__MACOSX" not in i.filename]
    by_name = {i.filename.replace("\\", "/"): i for i in infos}

    def text(info: zipfile.ZipInfo) -> str:
        """One zip entry as text (BOM stripped), refusing entries over MAX_PART_BYTES."""
        if info.file_size > MAX_PART_BYTES:
            raise ValueError(f"{info.filename} is bigger than 5 MB.")
        return zf.read(info).decode("utf-8-sig", errors="replace")

    found: dict[str, zipfile.ZipInfo] = {}
    # widget.ini names the files: [HTML] path = "html.txt"
    for ini in (i for i in infos if i.filename.lower().endswith("widget.ini")):
        folder = ini.filename.replace("\\", "/").rpartition("/")[0]
        cp = configparser.ConfigParser()
        try:
            cp.read_string(text(ini))
        except configparser.Error:
            continue
        for section in cp.sections():
            part = section.strip().lower()
            path = cp.get(section, "path", fallback="").strip().strip('"').strip("'")
            target = (folder + "/" + path) if folder else path
            if part in PARTS and target in by_name:
                found.setdefault(part, by_name[target])
        break
    # otherwise by file name; the shallowest file wins
    for info in sorted(infos, key=lambda i: (i.filename.count("/"), i.filename)):
        part = _part_for(info.filename)
        if part and part not in found:
            found[part] = info
    parts = {part: text(info) for part, info in found.items()}
    if not (parts.get("html") or parts.get("js") or parts.get("css")):
        raise ValueError("No widget code in that zip (looked for html.txt / css.txt / js.txt, or .html / .css / .js files).")
    return parts


class WidgetStore:
    """The imported widgets in ``root`` (default data/widgets), one folder each.

    Changes run under one lock (admin requests can overlap). Shared instance: ``default_store()``.
    """
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else DATA_DIR
        self._lock = threading.RLock()

    def _dir(self, name: str) -> Optional[Path]:
        """The folder of an existing widget, or None (no folder, or no widget.json in it)."""
        name = clean_name(name)
        if not name:
            return None
        d = self.root / name
        return d if (d / "widget.json").is_file() else None

    def _meta(self, d: Path) -> dict[str, Any]:
        """widget.json as a dict ({} when missing or broken)."""
        try:
            meta = json.loads((d / "widget.json").read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            meta = {}
        return meta if isinstance(meta, dict) else {}

    def _read_part(self, d: Path, part: str) -> str:
        """One part's saved text ("" when missing)."""
        p = d / PART_FILES[part]
        try:
            return p.read_text(encoding="utf-8") if p.is_file() else ""
        except OSError:
            return ""

    def names(self) -> list[str]:
        """Names of every stored widget, sorted."""
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if (p / "widget.json").is_file())

    def get(self, name: str, with_code: bool = False) -> Optional[dict[str, Any]]:
        """A widget's info for the dashboard (with its code when ``with_code``), or None.

        ``values`` are the field defaults with the saved values on top.
        """
        d = self._dir(name)
        if d is None:
            return None
        meta = self._meta(d)
        try:
            fields = json.loads(self._read_part(d, "fields") or "{}")
        except ValueError:
            fields = {}
        try:
            data = json.loads(self._read_part(d, "data") or "{}")
        except ValueError:
            data = {}
        platform = meta.get("platform") if meta.get("platform") in PLATFORMS else "streamelements"
        out = {
            "name": d.name,
            "platform": platform,
            "title": str(meta.get("title") or ""),
            "added": int(meta.get("added") or 0),
            "version": int(meta.get("version") or 0),
            "fields": fields if isinstance(fields, dict) else {},
            "values": field_values(fields if isinstance(fields, dict) else {}, data if isinstance(data, dict) else {}),
            "url": f"/overlay/widget.html?name={d.name}",
        }
        if with_code:
            out["code"] = {p: self._read_part(d, p) for p in ("html", "css", "js")}
            out["code"]["fields"] = self._read_part(d, "fields")
            out["code"]["data"] = self._read_part(d, "data")
        return out

    def list(self) -> list[dict[str, Any]]:
        """``get()`` for every widget (without code)."""
        return [w for w in (self.get(n) for n in self.names()) if w]

    def _free_name(self, wanted: str) -> str:
        """``wanted`` cleaned, with -2, -3 ... added while a folder of that name exists (max 40 chars)."""
        base = clean_name(wanted) or "widget"
        name, n = base, 2
        while (self.root / name).exists():
            suffix = f"-{n}"
            name = base[: 40 - len(suffix)] + suffix
            n += 1
        return name

    @staticmethod
    def _check(parts: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Size-check every part and parse fields / data. Returns (fields, data) or raises ValueError."""
        for part in PARTS:
            if len((parts.get(part) or "").encode("utf-8")) > MAX_PART_BYTES:
                raise ValueError(f"The {part.upper()} is bigger than 5 MB.")
        return _read_json(parts.get("fields") or "", "fields"), _read_json(parts.get("data") or "", "saved values")

    def _write(self, d: Path, parts: dict[str, str], meta: dict[str, Any]) -> None:
        """Save the given parts and widget.json; ``version`` always goes up so open frames reload."""
        d.mkdir(parents=True, exist_ok=True)
        for part in PARTS:
            if part in parts:
                (d / PART_FILES[part]).write_text(parts[part] or "", encoding="utf-8")
        meta["version"] = max(int(time.time() * 1000), int(meta.get("version") or 0) + 1)
        (d / "widget.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def add(self, parts: dict[str, str], name: str = "", platform: str = "", title: str = "") -> dict[str, Any]:
        """A new widget from its parts (html, css, js, fields, data); a taken name gets -2."""
        parts = {p: str(parts.get(p) or "") for p in PARTS}
        if not (parts["html"].strip() or parts["js"].strip() or parts["css"].strip()):
            raise ValueError("Paste the widget's HTML, CSS or JS first.")
        self._check(parts)
        with self._lock:
            if len(self.names()) >= MAX_WIDGETS:
                raise ValueError(f"Core keeps at most {MAX_WIDGETS} widgets; delete one first.")
            plat = platform if platform in PLATFORMS else guess_platform(parts)
            try:
                data = json.loads(parts["data"] or "{}")
            except ValueError:
                data = {}
            title = title or (str(data.get("widgetName") or "") if isinstance(data, dict) else "")
            d = self.root / self._free_name(name or title or "widget")
            self._write(d, parts, {"platform": plat, "added": int(time.time()), "title": title[:80]})
            log.info("Widget %s added (%s)", d.name, plat)
            return self.get(d.name) or {}

    def add_zip(self, raw: bytes, name: str = "", filename: str = "", platform: str = "") -> dict[str, Any]:
        """Import a widget from an exported zip (name taken from the file name when none is given)."""
        parts = read_zip(raw)
        return self.add(parts, name=name or name_from_filename(filename), platform=platform)

    def add_zip_base64(self, b64: str, name: str = "", filename: str = "", platform: str = "") -> dict[str, Any]:
        """``add_zip`` for a zip sent as base64 text."""
        return self.add_zip(decode_base64(b64), name=name, filename=filename, platform=platform)

    def update(self, name: str, parts: Optional[dict[str, str]] = None, values: Optional[dict[str, Any]] = None,
               platform: str = "") -> dict[str, Any]:
        """New code (any of html / css / js / fields / data) and / or new values for the settings."""
        with self._lock:
            d = self._dir(name)
            if d is None:
                raise KeyError(name)
            meta = self._meta(d)
            new_parts = {p: str(v) for p, v in (parts or {}).items() if p in PARTS and v is not None}
            if values is not None:
                if not isinstance(values, dict):
                    raise ValueError("Values should be an object.")
                new_parts["data"] = json.dumps(values, indent=2, ensure_ascii=False)
            self._check(new_parts)
            if platform in PLATFORMS:
                meta["platform"] = platform
            self._write(d, new_parts, meta)
            return self.get(d.name) or {}

    def rename(self, name: str, new_name: str) -> dict[str, Any]:
        """Rename a widget's folder (a taken name gets -2 ...). KeyError if it does not exist."""
        with self._lock:
            d = self._dir(name)
            if d is None:
                raise KeyError(name)
            target = clean_name(new_name)
            if not target:
                raise ValueError("Use letters, numbers, - or _ for the name.")
            if target != d.name:
                target = self._free_name(target)
                d.rename(self.root / target)
            return self.get(target) or {}

    def delete(self, name: str) -> bool:
        """Delete a widget and all its files. False when there was none."""
        with self._lock:
            d = self._dir(name)
            if d is None:
                return False
            shutil.rmtree(d, ignore_errors=True)
            return True

    # ── the frame ───────────────────────────────────────────────────────
    def compose(self, name: str) -> Optional[str]:
        """The widget's own page (served in a sandbox at /widget-frame/<name>)."""
        w = self.get(name, with_code=True)
        if w is None:
            return None
        return compose_frame(w["platform"], w["code"], w["values"])


def compose_frame(platform: str, code: dict[str, str], values: dict[str, Any]) -> str:
    """The HTML for the sandboxed frame: settings filled in, CSS placeholders filled, and the code
    kept from closing its own <style> / <script> tags early.
    """
    se = platform != "streamlabs"
    html = fill_fields(code.get("html") or "", values, single=se)
    css = fill_fields(code.get("css") or "", values, single=se)
    js = fill_fields(code.get("js") or "", values, single=se)
    css, _ = fill_placeholders(css)
    css = re.sub(r"</(style)", r"<\\/\1", css, flags=re.IGNORECASE)
    return (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<link rel=\"stylesheet\" href=\"/overlay/animate-lite.css\">\n"
        "<style>html,body{background:transparent;margin:0;overflow:hidden}</style>\n"
        f"<script src=\"{JQUERY}\"></script>\n"
        f"<script src=\"/overlay/widget-frame.js\" data-platform=\"{'streamelements' if se else 'streamlabs'}\"></script>\n"
        f"<style>\n{css}\n</style>\n</head><body>\n{html}\n"
        f"<script>\n{_script_safe(js)}\n</script>\n"
        "<script>window.FridgeWidget && window.FridgeWidget.ready();</script>\n"
        "</body></html>\n"
    )


_default: Optional[WidgetStore] = None


def default_store() -> WidgetStore:
    """The WidgetStore in data/widgets (one per Core)."""
    global _default
    if _default is None:
        _default = WidgetStore()
    return _default
