"""Local previews and downloads for the Ivory Invites stationery collection."""

import io
import math
import re
import threading
from datetime import date
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont as WebFont
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

STATIC = Path(__file__).parent / "static"
MM = 72 / 25.4
RENDER_SLOTS = threading.BoundedSemaphore(2)
FONT_LOCK = threading.Lock()
FONT_FILES = {
    "StationerySerif": "cormorantgaramond.woff2",
    "StationerySans": "dmsans.woff2",
}
SIZES = {
    "5x7": (127, 177.8), "A5": (148, 210), "A6": (105, 148), "A3": (297, 420),
    "A2": (420, 594), "A1": (594, 841), "DL": (99, 210),
    "flat": (90, 50), "folded": (90, 100),
}
SIZE_LABELS = {
    "5x7": "5 × 7 in", "flat": "90 × 50 mm (flat)", "folded": "90 × 100 mm (folded)",
    "DL": "DL (99 × 210 mm)",
}
KINDS = {
    "save-date": ("Save the date", ("A6", "5x7"), ("title", "date", "venue", "message")),
    "day": ("Day invitation", ("5x7", "A5"), ("title", "intro", "date", "time", "venue", "message", "reply")),
    "evening": ("Evening invitation", ("5x7", "A5"), ("title", "intro", "date", "time", "venue", "message", "reply")),
    "welcome": ("Welcome sign", ("A2", "A1", "A3"), ("title", "date", "message")),
    "menu": ("Menu", ("DL", "A5"), ("title", "lines")),
    "place": ("Place cards", ("flat", "folded"), ("lines",)),
    "table": ("Table names or numbers", ("A6", "A5"), ("lines",)),
    "seating": ("Seating chart", ("A2", "A1", "A3"), ("title", "lines")),
    "thanks": ("Thank-you card", ("A6", "5x7"), ("title", "message")),
}
LABELS = {
    "title": "Names or event title", "intro": "Opening line", "date": "Date", "time": "Arrival time (UK)",
    "venue": "Venue or address", "message": "Wording", "reply": "How and when to reply",
}
LISTS = {
    "menu": ("Menu", "Put each course heading on its own line, followed by its dishes. Leave a blank line between courses."),
    "place": ("Guest names", "Enter one name per line."),
    "table": ("Table names or numbers", "Enter one table per line."),
    "seating": ("Table assignments", "Put the table name first, then one guest per line. Leave a blank line between tables."),
}
LIMITS = {"title": 90, "intro": 120, "date": 10, "time": 5, "venue": 180,
          "message": 1200, "reply": 240, "lines": 12000}
ARTWORK = {"wedding", "birthday", "botanical", "something-blue", "silver"}
PHOTO_KINDS = {"day", "evening", "save-date", "welcome", "thanks"}
PARTY_DESIGNS = {"birthday", "disco"}

# Each entry gives paper, ink and trim colours shared by all nine pieces.
PALETTES = {
    "letterpress": {
        "Warm ivory": ("#f7eee1", "#553e30", "#9a755c"),
        "Champagne": ("#fff8ed", "#534132", "#a38354"),
        "Soft rose": ("#faefed", "#573d42", "#a8757a"),
    },
    "botanical": {
        "Garden sage": ("#f8f5e8", "#334737", "#62765c"),
        "Olive and cream": ("#faf4de", "#3b4530", "#74794b"),
        "Deep forest": ("#edf1e7", "#233e32", "#4b6c58"),
    },
    "deco": {
        "Antique gold": ("#29231f", "#f3dbac", "#d4ae69"),
        "Emerald": ("#203d36", "#f2dfb3", "#caaa68"),
        "Midnight": ("#203039", "#f4e3be", "#c4a56d"),
    },
    "something-blue": {
        "Wedgwood": ("#f7f2e9", "#294760", "#698ca9"),
        "Cornflower": ("#eef2f8", "#293b64", "#687fb2"),
        "Navy and cream": ("#fcf7ed", "#213653", "#57779b"),
    },
    "silver": {
        "Silver": ("#f1efeb", "#242322", "#5e5b59"),
        "Warm linen": ("#f7f0e4", "#332c27", "#81715f"),
        "Chalk and ink": ("#f9f8f4", "#202626", "#5c6b6b"),
    },
    "winter": {
        "Mulberry": ("#472c38", "#f9e4cc", "#dbb491"),
        "Evergreen": ("#263c35", "#f6ebd0", "#ccaf78"),
        "Winter berry": ("#542a31", "#f9e7d0", "#ddaf8e"),
    },
    "wedding": {
        "Country olive": ("#f5ede0", "#404b30", "#7b825c"),
        "Taupe and ivory": ("#f7efe7", "#503d37", "#967a68"),
        "Rosewood": ("#faeeea", "#603f43", "#9e7777"),
    },
    "black-tie": {
        "Black and gold": ("#25251f", "#f5e5bd", "#b89455"),
        "Midnight blue": ("#202b40", "#f5e9d1", "#c4a072"),
        "Oxblood": ("#412628", "#f5e2c3", "#c59672"),
    },
    "birthday": {
        "Fern": ("#fbf5d9", "#315238", "#667e49"),
        "Amber": ("#fff0d9", "#5d3a27", "#9d684e"),
        "Jungle blue": ("#eaf1ec", "#28434b", "#588288"),
    },
    "disco": {
        "Plum": ("#3c2158", "#fff0ea", "#fcbf93"),
        "Rose disco": ("#602c50", "#fff0ea", "#f5b7c9"),
        "Midnight disco": ("#252d56", "#faecfb", "#c4b0e7"),
    },
}


class StationeryError(ValueError):
    pass


@lru_cache(maxsize=2)
def font_bytes(name):
    buffer = io.BytesIO()
    with WebFont(STATIC / FONT_FILES[name]) as font:
        font.flavor = None
        font.save(buffer)
    return buffer.getvalue()


def register_fonts():
    with FONT_LOCK:
        for name in FONT_FILES:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, io.BytesIO(font_bytes(name))))


def choice(value, allowed, message):
    if not isinstance(value, str) or value not in allowed:
        raise StationeryError(message)
    return value


def defaults(event, kind):
    result = {field: "" for field in KINDS[kind][2]}
    result["size"] = KINDS[kind][1][0]
    for field in result.keys() & {"title", "date", "venue"}:
        result[field] = event.get(field, "")
    party = event["template"] in PARTY_DESIGNS
    if kind == "day":
        result.update(intro=event["intro"], time=event["time"], message=event["message"])
    if kind == "evening":
        result["message"] = "Please join us for the evening celebration."
    if kind == "welcome":
        result["message"] = "Welcome to our celebration" if party else "Welcome to our wedding"
    if kind == "thanks":
        result["message"] = "Thank you for celebrating with us."
    if kind in PHOTO_KINDS:
        result.update(photo_x=50, photo_y=50, photo_zoom=1)
    return result


def example(event, kind):
    result = defaults(event, kind)
    if kind == "evening":
        result["time"] = "19:30"
    if kind == "day":
        result["time"] = result["time"] or "14:00"
    if kind in {"evening", "day"}:
        result["reply"] = "Please reply by 1 May"
    if kind in LISTS:
        result["lines"] = {
            "menu": "Starter\nGarden pea and mint soup\n\nMain\nRoast chicken with spring vegetables\n\nDessert\nLemon posset",
            "place": "Jamie Taylor\nSam Parker",
            "table": "The Orangery\nThe Garden",
            "seating": "The Orangery\nJamie Taylor\nSam Parker\n\nThe Garden\nAlex Quinn\nMorgan Lee",
        }[kind]
    return result


def validate_draft(kind, value):
    if not isinstance(value, dict):
        raise StationeryError("Enter the stationery details.")
    result = {"size": choice(value.get("size"), KINDS[kind][1], "Choose a paper size for this piece.")}
    for field in KINDS[kind][2]:
        text = value.get(field, "")
        if not isinstance(text, str) or len(text) > LIMITS[field] or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]", text):
            raise StationeryError("Check the wording and length of each field.")
        result[field] = text.strip()
    day, clock = result.get("date"), result.get("time")
    if day:
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError()
        except ValueError as error:
            raise StationeryError("Enter a valid date.") from error
    if clock and not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", clock):
        raise StationeryError("Enter a valid arrival time.")
    if kind in PHOTO_KINDS:
        for field, default, low, high in (("photo_x", 50, 0, 100), ("photo_y", 50, 0, 100), ("photo_zoom", 1, 1, 3)):
            number = value.get(field, default)
            if type(number) not in (int, float) or not low <= number <= high:
                raise StationeryError("Check the photo position and zoom.")
            result[field] = number
    return result


def metadata(event, sheets, palette):
    template = event["template"]
    kinds = {}
    for kind, (name, sizes, fields) in KINDS.items():
        label, hint = LISTS[kind] if kind in LISTS else ("", "")
        kinds[kind] = {
            "name": "Party invitation" if kind == "day" and template in PARTY_DESIGNS else name,
            "sizes": {size: SIZE_LABELS.get(size, size) for size in sizes},
            "fields": {field: label if field == "lines" else LABELS[field] for field in fields},
            "hint": hint, "photo": kind in PHOTO_KINDS,
            "draft": sheets.get(kind, defaults(event, kind)), "hasDraft": kind in sheets,
            "defaults": defaults(event, kind),
        }
    return dict(kinds=kinds, palettes=PALETTES[template], palette=palette or next(iter(PALETTES[template])))


@lru_cache(maxsize=5)
def template_art(template):
    return Image.open(STATIC / f"{template}.webp").convert("RGB")


def photo_crop(photo, width, height, draft):
    target = (max(1, round(width * 3)), max(1, round(height * 3)))
    # Match the requested focus and aspect ratio without upscaling originals for print.
    ratio = target[0] / target[1]
    crop_w = min(photo.width, photo.height * ratio) / draft.get("photo_zoom", 1)
    crop_h = crop_w / ratio
    left = (photo.width - crop_w) * draft.get("photo_x", 50) / 100
    top = (photo.height - crop_h) * draft.get("photo_y", 50) / 100
    return photo.crop((round(left), round(top), max(round(left) + 1, round(left + crop_w)),
                       max(round(top) + 1, round(top + crop_h))))


def lines_of(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def sections(text):
    return [lines_of(group) for group in re.split(r"\n\s*\n", text.strip()) if group.strip()]


def date_label(day):
    if not day:
        return ""
    parsed = date.fromisoformat(day)
    return f"{parsed:%A} {parsed.day} {parsed:%B %Y}"


class Layout:
    """One set of drawing commands for preview, PDF and PNG."""

    def __init__(self, width, height, config, kind):
        self.w, self.h = width, height
        self.config = config
        self.bg, self.ink, self.accent = PALETTES[config["template"]][config["palette"]]
        self.offset = height / 2 if kind == "place" and config["size"] == "folded" else 0
        self.area = self.h - self.offset
        self.ops = [("rect", 0, 0, width, height, self.bg, None, .5)]

    def line(self, x, y, x2, y2, colour, width=.55):
        self.ops.append(("line", x, y, x2, y2, colour, width))

    def frame(self, inset, width=.55):
        self.ops.append(("rect", inset, self.offset + inset, self.w - 2 * inset,
                         self.area - 2 * inset, None, self.accent, width))

    def shape(self, points, width=.55):
        self.ops.append(("path", points, self.accent, width))

    def text(self, text, box, size, *, minimum=9, sans=False, align="centre", top_aligned=False):
        if not text:
            return
        x, y, width, height = box
        font = "StationerySans" if sans else "StationerySerif"
        glyphs = pdfmetrics.getFont(font).face.charToGlyph
        if any(not char.isspace() and ord(char) not in glyphs for char in text):
            raise StationeryError("One of the characters cannot be printed in this font. Check the wording.")
        minimum = min(minimum, size)
        while True:
            lines = wrap(text, font, size, width)
            if lines is not None and len(lines) * size * 1.25 <= height:
                break
            if size <= minimum:
                raise StationeryError("Some wording is too long for this layout. Shorten it or choose a larger size.")
            size = max(minimum, size * .91)
        line_height = size * 1.25
        top = y if top_aligned else y + (height - len(lines) * line_height) / 2
        for index, line in enumerate(lines):
            advance = pdfmetrics.stringWidth(line, font, size)
            left = x if align == "left" else x + (width - advance) / 2
            self.ops.append(("text", line, left, top + size + index * line_height,
                             size, font, self.ink))


def wrap(text, font, size, width):
    lines = []
    for paragraph in text.splitlines():
        line = ""
        for word in paragraph.split():
            if pdfmetrics.stringWidth(word, font, size) > width:
                return None
            candidate = f"{line} {word}" if line else word
            if line and pdfmetrics.stringWidth(candidate, font, size) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


def decorate(layout, kind, uploaded, sample):
    cfg = layout.config
    key = cfg["template"]
    w, h, y = layout.w, layout.area, layout.offset
    inset = min(w, h) * .045
    art = uploaded if kind in PHOTO_KINDS else None
    if art is None and key in ARTWORK and (key != "silver" or sample):
        art = template_art(key)
    art_height = 0
    if art is not None:
        compact = kind in {"place", "table", "seating", "menu"}
        art_height = h * (.15 if compact else .29)
        # Small pieces carry an accent strip instead of cropping a portrait.
        strip = (inset * 1.55, y + inset * 1.55, w - inset * 3.1, art_height)
        crop = cfg if art is uploaded else {}
        if key == "silver":
            art = ImageOps.grayscale(art).convert("RGB")
        layout.ops.append(("image", photo_crop(art, strip[2], strip[3], crop), *strip))
    if key in {"deco", "black-tie"}:
        for margin in (inset, inset * 1.38):
            cut = inset * 1.25
            right, bottom = w - margin, y + h - margin
            upper = y + margin
            layout.shape([(margin + cut, upper), (right - cut, upper), (right, upper + cut),
                          (right, bottom - cut), (right - cut, bottom), (margin + cut, bottom),
                          (margin, bottom - cut), (margin, upper + cut)])
    elif key == "winter":
        for margin in (inset, inset * 1.38):
            cap = min(w * .22, h * .28)
            points = [(w - margin, y + h - margin), (margin, y + h - margin)]
            points += [(w / 2 - (w / 2 - margin) * math.cos(a * math.pi / 24),
                        y + margin + cap * (1 - math.sin(a * math.pi / 24))) for a in range(25)]
            layout.shape(points)
    elif key == "disco":
        layout.frame(inset)
        for centre in (.11, .89):
            for depth in (.14, .86):
                x, yy = centre * w, y + depth * h
                layout.shape([(x - inset, yy), (x, yy - inset), (x + inset, yy), (x, yy + inset)])
    elif key == "silver":
        layout.line(w * .12, y + h * .92, w * .88, y + h * .92, layout.accent)
    else:
        layout.frame(inset)
        if key in {"letterpress", "something-blue"}:
            layout.frame(inset * 1.38, .35)
    if layout.offset:
        layout.line(0, y, w, y, "#999086", .35)
    return art_height / h


def make_layout(config, kind, photo, sample, *, name=None, groups=()):
    width, height = (value * MM for value in SIZES[config["size"]])
    layout = Layout(width, height, config, kind)
    art = decorate(layout, kind, photo, sample)
    w, h, y = width, layout.area, layout.offset
    left = w * .13
    usable = w - 2 * left
    accent = layout.accent
    title = config.get("title", "")
    message = config.get("message", "")
    venue = config.get("venue", "")
    day = date_label(config.get("date"))
    time = config.get("time")
    align = "left" if config["template"] == "silver" and kind not in {"place", "table", "seating"} else "centre"

    def text(value, top, depth, size, **options):
        layout.text(value, (left, y + h * top, usable, h * depth), size, align=align, **options)

    def rule(top):
        start = left if align == "left" else w * .43
        layout.line(start, y + h * top, start + w * .14, y + h * top, accent)

    top = max(.135, art + .118)
    large = min(w * .16, h * .19)
    small = max(11, w * .048)
    if kind in {"day", "evening", "save-date"}:
        heading = {"day": "Party invitation" if config["template"] in PARTY_DESIGNS else "Day invitation",
                   "evening": "Evening invitation", "save-date": "Save the date"}[kind]
        text(heading.upper(), top, .055, small * .68, sans=True)
        text(title, top + .06, .143, large)
        rule(top + .216)
        if not art:
            text(config.get("intro"), top + .24, .058, small)
            text(message, top + .306, .15, small)
        else:
            text(config.get("intro"), top - .053, .038, small * .82)
            text(message, top + .22, .09, small * .90)
        details = "\n".join(filter(None, [day + (f" at {time}" if time else "") if day else "", venue]))
        text(details, .735 if art else .645, .12, small)
        text(config.get("reply"), .865 if art else .79, .06, small * .85, sans=True)
    elif kind == "welcome":
        text(message, top, .10, small * 1.12, sans=True)
        text(title, top + .12, .20, large * 1.3)
        rule(top + .35)
        text(day, top + .37, .09, small)
    elif kind == "thanks":
        text("Thank you", top, .18, large * 1.13)
        rule(top + .19)
        text(message, top + .22, .14, small)
        text(title, top + .38, .10, small * 1.18)
    elif kind in {"place", "table"}:
        label = "Table" if kind == "table" and not name.lower().startswith("table") else ""
        text(label.upper(), top + .04, .10, small * .85, sans=True)
        text(name, top + .16, .34, min(w * .17, h * .28), minimum=10)
        rule(top + .54)
    elif kind == "menu":
        text("Menu", top, .115, large)
        text(title, top + .118, .072, small)
        rule(top + .20)
        menu_top = top + .23
        cell = (.91 - menu_top) / len(groups)
        for index, (heading, *items) in enumerate(groups):
            offset = menu_top + index * cell
            text(heading, offset, cell * .30, small, sans=True)
            text("\n".join(items), offset + cell * .31, cell * .65, small * 1.10)
    elif kind == "seating":
        text("Find your table", top, .094, large * .68)
        text(title, top + .099, .055, small)
        rule(top + .17)
        columns = 2 if len(groups) <= 8 else 3
        rows = math.ceil(len(groups) / columns)
        cell_top = top + .19
        cell_height = (.91 - cell_top) / rows
        cell_width = usable / columns
        row_height = h * cell_height
        header_height = min(row_height * .29, h * .054)
        gap = h * .009
        for index, (table, *guests) in enumerate(groups):
            x = left + index % columns * cell_width + cell_width * .06
            yy = y + h * cell_top + index // columns * row_height
            layout.text(table, (x, yy, cell_width * .88, header_height), small * .94,
                        minimum=12, sans=True, top_aligned=True)
            minimum = {"A1": 18, "A2": 14, "A3": 11}[config["size"]]
            layout.text("\n".join(guests), (x, yy + header_height + gap, cell_width * .88,
                                             row_height - header_height - gap * 2),
                        small * .87, minimum=minimum, top_aligned=True)
    return layout


def content_for(kind, config, preview):
    if not preview:
        needed = {"day": ("title", "date", "time", "venue"), "evening": ("title", "date", "time", "venue"),
                  "save-date": ("title", "date"), "welcome": ("title", "date"), "thanks": ("title",)}
        for field in needed.get(kind, ()):
            if not config[field]:
                raise StationeryError(f"Add the {LABELS[field].lower()} before downloading.")
    if kind not in LISTS:
        return [], []
    wording = config["lines"]
    if not wording and preview:
        wording = {"menu": "Starter\nAdd your menu", "place": "Guest name",
                   "table": "Table 1", "seating": "Table 1\nGuest names"}[kind]
    if not wording:
        raise StationeryError(f"Enter {LISTS[kind][0].lower()} before downloading.")
    if kind in {"place", "table"}:
        names = lines_of(wording)
        if not names or len(names) > (250 if kind == "place" else 40) or any(len(name) > 100 for name in names):
            raise StationeryError("Check the number and length of the names.")
        return names, []
    groups = sections(wording)
    if kind == "seating":
        if not groups or len(groups) > 18 or any(len(group) < 2 for group in groups):
            raise StationeryError("Add up to 18 tables. Put at least one guest under each table name.")
    elif not groups or len(groups) > 5:
        raise StationeryError("Use up to five menu sections, separated by blank lines.")
    return [], groups


def render(event, kind, draft, palette, action, photo=None, *, sample=False, bleed=0):
    config = dict(draft, template=event["template"], palette=palette)
    names, groups = content_for(kind, config, action == "preview")
    if not RENDER_SLOTS.acquire(timeout=3):
        raise StationeryError("The preview and download service is busy. Try again in a moment.")
    try:
        register_fonts()
        uploaded = None
        if photo and kind in PHOTO_KINDS:
            try:
                with Image.open(io.BytesIO(photo)) as image:
                    if image.width * image.height > 20_000_000:
                        raise StationeryError("Use a smaller photo for stationery.")
                    uploaded = ImageOps.exif_transpose(image).convert("RGB")
            except (UnidentifiedImageError, OSError) as error:
                raise StationeryError("The saved photo could not be opened. Upload it again.") from error
        # The preview represents the individual piece. PDF batches lay out every entered name.
        entries = names if action == "pdf" else names[:1]
        layouts = [make_layout(config, kind, uploaded, sample, name=name, groups=groups)
                   for name in entries or (None,)]
        if action == "pdf":
            pages = placecard_sheets(layouts) if kind == "place" and len(layouts) > 1 else layouts
            return draw_pdf(pages, 0 if len(layouts) > 1 else bleed)
        return draw_png(layouts[0], 760 if action == "preview" else 1800)
    finally:
        RENDER_SLOTS.release()


def moved(op, dx, dy):
    kind, *values = op
    if kind == "line":
        x, y, x2, y2, *style = values
        return kind, x + dx, y + dy, x2 + dx, y2 + dy, *style
    if kind == "path":
        points, *style = values
        return kind, [(x + dx, y + dy) for x, y in points], *style
    if kind == "rect":
        x, y, *style = values
        return kind, x + dx, y + dy, *style
    content, x, y, *style = values
    return kind, content, x + dx, y + dy, *style


def placecard_sheets(cards):
    """Preserve each card's dimensions on A4, with cutting and fold marks."""
    w, h = 210 * MM, 297 * MM
    cw, ch = cards[0].w, cards[0].h
    gap = 6 * MM
    rows = int((h - 20 * MM + gap) // (ch + gap))
    per_page = 2 * rows
    x0 = (w - 2 * cw - gap) / 2
    y0 = (h - rows * ch - gap * (rows - 1)) / 2
    pages = []
    for start in range(0, len(cards), per_page):
        sheet = Layout(w, h, cards[0].config, "sheet")
        sheet.bg = "#ffffff"
        sheet.ops = []
        for index, card in enumerate(cards[start:start + per_page]):
            dx = x0 + (index % 2) * (cw + gap)
            dy = y0 + (index // 2) * (ch + gap)
            sheet.ops.extend(moved(op, dx, dy) for op in card.ops)
            for x, sx in ((dx, -1), (dx + cw, 1)):
                for y, sy in ((dy, -1), (dy + ch, 1)):
                    sheet.line(x + sx * MM, y, x + sx * 2.5 * MM, y, "#777777", .25)
                    sheet.line(x, y + sy * MM, x, y + sy * 2.5 * MM, "#777777", .25)
        pages.append(sheet)
    return pages


def draw_pdf(layouts, bleed=0):
    out = io.BytesIO()
    margin = bleed * MM
    pdf = canvas.Canvas(out, pageCompression=1, initialFontName="StationerySerif")
    pdf.setTitle("Event stationery")
    pdf.setAuthor("Ivory Digital")
    for page in layouts:
        outer_w, outer_h = page.w + 2 * margin, page.h + 2 * margin
        pdf.setPageSize((outer_w, outer_h))
        pdf.setTrimBox((margin, margin, page.w + margin, page.h + margin))
        pdf.setBleedBox((0, 0, outer_w, outer_h))
        pdf.setFillColor(HexColor(page.bg))
        pdf.rect(0, 0, outer_w, outer_h, fill=1, stroke=0)
        pdf.saveState()
        pdf.translate(margin, margin)
        for op in page.ops:
            kind, *values = op
            if kind == "rect":
                x, y, w, h, fill, stroke, width = values
                pdf.setLineWidth(width)
                if fill:
                    pdf.setFillColor(HexColor(fill))
                if stroke:
                    pdf.setStrokeColor(HexColor(stroke))
                pdf.rect(x, page.h - y - h, w, h, fill=bool(fill), stroke=bool(stroke))
            elif kind == "line":
                x, y, x2, y2, colour, width = values
                pdf.setStrokeColor(HexColor(colour))
                pdf.setLineWidth(width)
                pdf.line(x, page.h - y, x2, page.h - y2)
            elif kind == "path":
                points, colour, width = values
                outline = pdf.beginPath()
                x, y = points[0]
                outline.moveTo(x, page.h - y)
                for x, y in points[1:]:
                    outline.lineTo(x, page.h - y)
                outline.close()
                pdf.setStrokeColor(HexColor(colour))
                pdf.setLineWidth(width)
                pdf.setLineJoin(1)
                pdf.drawPath(outline)
            elif kind == "text":
                text, x, y, size, font, colour = values
                pdf.setFont(font, size)
                pdf.setFillColor(HexColor(colour))
                pdf.drawString(x, page.h - y, text)
            else:
                photo, x, y, w, h = values
                pdf.drawImage(ImageReader(photo), x, page.h - y - h, w, h)
        pdf.restoreState()
        pdf.showPage()
    pdf.save()
    return out.getvalue()


def draw_png(page, long_edge):
    scale = long_edge / max(page.w, page.h)
    image = Image.new("RGB", (round(page.w * scale), round(page.h * scale)), page.bg)
    draw = ImageDraw.Draw(image)

    def pixels(*values):
        return tuple(round(value * scale) for value in values)

    for op in page.ops:
        kind, *values = op
        if kind == "rect":
            x, y, w, h, fill, stroke, width = values
            draw.rectangle(pixels(x, y, x + w, y + h), fill=fill, outline=stroke,
                           width=max(1, round(width * scale)))
        elif kind == "line":
            x, y, x2, y2, colour, width = values
            draw.line(pixels(x, y, x2, y2), fill=colour, width=max(1, round(width * scale)))
        elif kind == "path":
            points, colour, width = values
            outline = [pixels(x, y) for x, y in points]
            draw.line(outline + outline[:1], fill=colour, width=max(1, round(width * scale)), joint="curve")
        elif kind == "text":
            text, x, y, size, font_name, colour = values
            font = ImageFont.truetype(io.BytesIO(font_bytes(font_name)), max(1, round(size * scale)))
            draw.text(pixels(x, y), text, font=font, fill=colour, anchor="ls")
        else:
            photo, x, y, w, h = values
            scaled = photo.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)
            image.paste(scaled, pixels(x, y))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()
