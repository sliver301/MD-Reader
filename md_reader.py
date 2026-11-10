#!/usr/bin/env python3
"""
MD Reader - a modern Markdown reader / editor for Windows.

Preview and Raw tabs, read-only by default with an Edit switch, copy buttons on
every table cell, dark / light themes, settings, find, export.

Run:  python md_reader.py [file.md]
"""

APP_NAME = "MD Reader"
APP_VERSION = "1.1"

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import html as htmlmod
from pathlib import Path


def _fatal(msg):
    """Show an error even when started with pythonw (no console)."""
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, APP_NAME, 0x10)
            return
    except Exception:
        pass
    print(msg, file=sys.stderr)


try:
    from PySide6.QtCore import (Qt, QUrl, QObject, Slot, Signal, QTimer, QFile, QIODevice,
                                QFileSystemWatcher, QSize, QByteArray, QPropertyAnimation,
                                QEasingCurve, Property, QRectF, QEvent)
    from PySide6.QtGui import (QIcon, QPixmap, QPainter, QColor, QFont, QKeySequence, QAction,
                               QSyntaxHighlighter, QTextCharFormat, QFontDatabase, QDesktopServices,
                               QPalette, QTextCursor, QTextDocument, QGuiApplication, QImage,
                               QFontMetrics)  # noqa: F401
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel, QHBoxLayout,
                                   QVBoxLayout, QToolButton, QPushButton, QButtonGroup, QStackedWidget,
                                   QSplitter, QPlainTextEdit, QStatusBar, QMenu, QFileDialog,
                                   QMessageBox, QDialog, QComboBox, QSpinBox, QFontComboBox,
                                   QLineEdit, QScrollArea, QAbstractButton, QStyle, QTabBar,
                                   QPlainTextDocumentLayout, QSizePolicy)
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PySide6.QtWebChannel import QWebChannel
    import markdown
except ImportError as exc:  # pragma: no cover
    _fatal("MD Reader is missing a required package:\n\n"
           f"{exc}\n\nDouble-click 'Run MD Reader.bat' (it installs everything), or run:\n"
           "python -m pip install -r requirements.txt")
    sys.exit(1)

try:
    import pymdownx  # noqa: F401
    HAVE_PYMDOWNX = True
except ImportError:
    HAVE_PYMDOWNX = False

try:
    from pygments.formatters import HtmlFormatter
    HAVE_PYGMENTS = True
except ImportError:
    HAVE_PYGMENTS = False


# --------------------------------------------------------------------------------------
# Paths & settings
# --------------------------------------------------------------------------------------

def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


MD_EXTS = {".md", ".markdown", ".mdown", ".mkd", ".mkdn", ".mdwn", ".txt"}

DEFAULTS = {
    "theme": "system",            # system | light | dark
    "accent": "Blue",
    "preview_font_size": 16,
    "reading_font": "sans",       # sans | serif | mono
    "reading_width": "comfortable",  # narrow | comfortable | wide | full
    "cell_copy": True,
    "edit_by_default": False,
    "split_when_editing": True,
    "sync_scroll": True,
    "word_wrap": True,
    "editor_font": "",
    "editor_font_size": 11,
    "reopen_last": True,
    "startup": "home",            # home | last
    "open_files": [],
    "active_file": "",
    "auto_reload": True,
    "recent": [],
    "last_file": "",
    "last_tab": "preview",
    "geometry": "",
    "splitter": [],
}


class Settings(dict):
    def __init__(self):
        super().__init__(json.loads(json.dumps(DEFAULTS)))
        self.path = self._pick_path()
        self.load()

    @staticmethod
    def _pick_path() -> Path:
        if install_scope():           # installed copies keep settings in %APPDATA%\MD Reader
            d = appdata_dir()
            d.mkdir(parents=True, exist_ok=True)
            return d / "settings.json"
        p = app_dir() / "settings.json"
        try:
            with open(p, "a", encoding="utf-8"):
                pass
            return p
        except OSError:
            d = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
            d.mkdir(parents=True, exist_ok=True)
            return d / "settings.json"

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            for k in DEFAULTS:
                if k in data:
                    self[k] = data[k]
        except Exception:
            pass

    def save(self):
        try:
            self.path.write_text(json.dumps(self, indent=2), encoding="utf-8")
        except OSError:
            pass


# --------------------------------------------------------------------------------------
# Theme palettes
# --------------------------------------------------------------------------------------

BASE_PALETTES = {
    "dark": dict(
        chrome="#17181b", bg="#1c1d20", surface="#212226", th="#27282c", border="#2f3136",
        fg="#e4e5e9", muted="#8f929b", code_bg="#232428", quote_bg="#202125",
        row_hover="#24252a", hover="#2a2c31", pressed="#33353b", seg_bg="#202125",
        seg_active="#34363c", scroll="#3a3c42", input="#232428", ok="#3fb950",
        icon="#c9cbd1", switch_off="#45474e", shadow="rgba(0,0,0,.45)",
        code_fg="#e3b778", quote_fg="#9da1aa",
    ),
    "light": dict(
        chrome="#f5f6f8", bg="#ffffff", surface="#ffffff", th="#f4f5f7", border="#e3e5ea",
        fg="#1f2328", muted="#6b7180", code_bg="#f5f6f8", quote_bg="#f7f8fa",
        row_hover="#f8f9fb", hover="#e8eaee", pressed="#dde0e6", seg_bg="#eceef2",
        seg_active="#ffffff", scroll="#c9cdd4", input="#ffffff", ok="#1a7f37",
        icon="#3d424b", switch_off="#c7ccd4", shadow="rgba(16,24,40,.08)",
        code_fg="#b4541a", quote_fg="#5b6270",
    ),
}

ACCENTS = {  # name: (dark theme, light theme)
    "Blue": ("#6aa9ff", "#1f6feb"),
    "Indigo": ("#8f90ff", "#5b5bd6"),
    "Teal": ("#2ec4b0", "#0f8a7a"),
    "Green": ("#4cc76a", "#1a7f37"),
    "Orange": ("#ff9f5a", "#c4561a"),
    "Rose": ("#ff7aa8", "#c22d6b"),
}

READING_FONTS = {
    "sans": ("Sans-serif (Segoe UI)",
             '"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif'),
    "serif": ("Serif (Georgia)", 'Charter,"Bitstream Charter",Georgia,Cambria,"Times New Roman",serif'),
    "mono": ("Monospace", '"Cascadia Code","Cascadia Mono",Consolas,"Courier New",monospace'),
}
READING_WIDTHS = {
    "narrow": ("Narrow", "720px"),
    "comfortable": ("Comfortable", "900px"),
    "wide": ("Wide", "1150px"),
    "full": ("Full window", "100%"),
}
MONO_STACK = '"Cascadia Code","Cascadia Mono",Consolas,"JetBrains Mono","Courier New",monospace'


def rgba(hex_color, alpha):
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


def make_palette(theme, accent_name):
    P = dict(BASE_PALETTES[theme])
    pair = ACCENTS.get(accent_name, ACCENTS["Blue"])
    acc = pair[0] if theme == "dark" else pair[1]
    P["accent"] = acc
    P["link"] = acc
    P["accent_soft"] = rgba(acc, 0.16)
    P["sel"] = rgba(acc, 0.32)
    c = QColor(acc)
    P["accent_hover"] = (c.lighter(112) if theme == "dark" else c.darker(112)).name()
    P["on_accent"] = "#0d1117" if theme == "dark" else "#ffffff"
    P["theme"] = theme
    return P


def resolve_theme(settings):
    t = settings.get("theme", "system")
    if t in ("dark", "light"):
        return t
    try:
        if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Light:
            return "light"
        return "dark"
    except Exception:
        return "dark"


# --------------------------------------------------------------------------------------
# Icons (Lucide-style line icons, drawn from SVG so they stay crisp and recolourable)
# --------------------------------------------------------------------------------------

ICON_PATHS = {
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "code": '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
    "pencil": '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "folder-open": '<path d="m6 14 1.45-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.55 6a2 2 0 0 1-1.94 1.5H4a2 2 0 0 1-2-2V5c0-1.1.9-2 2-2h3.93a2 2 0 0 1 1.66.9l.82 1.2a2 2 0 0 0 1.66.9H18a2 2 0 0 1 2 2v2"/>',
    "folder": '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "settings": '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    "file-plus": '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "more": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "chevron-up": '<path d="m18 15-6-6-6 6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    "printer": '<polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "keyboard": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M6 12h.01M10 12h.01M14 12h.01M18 12h.01M7 16h10"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5"/>',
    "file": '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><path d="M8 13h8M8 17h5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "user": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "save-as": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v4"/><polyline points="7 3 7 8 15 8"/><path d="M14 19h7M17.5 15.5v7"/>',
}

APP_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#5fa2ff"/><stop offset="1" stop-color="#7a5cff"/></linearGradient></defs>
<rect x="3" y="3" width="58" height="58" rx="15" fill="url(#g)"/>
<path d="M15 43V21l8.5 10L32 21v22" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M45 21v20M38 34.5l7 7 7-7" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""


def svg_icon_markup(name, color, stroke=1.9):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
            f'stroke-linejoin="round">{ICON_PATHS[name]}</svg>')


def svg_pixmap(svg, size, dpr=2.0):
    r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p)
    p.end()
    px.setDevicePixelRatio(dpr)
    return px


def make_icon(name, color, size=20, on_color=None):
    ic = QIcon()
    ic.addPixmap(svg_pixmap(svg_icon_markup(name, color), size), QIcon.Mode.Normal, QIcon.State.Off)
    if on_color:
        ic.addPixmap(svg_pixmap(svg_icon_markup(name, on_color), size), QIcon.Mode.Normal, QIcon.State.On)
    return ic


def app_icon():
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(svg_pixmap(APP_ICON_SVG, s, 1.0))
    return ic


_ARROW_CACHE = {}


def arrow_file(name, color):
    """QSS needs image files for combo/spin arrows; write tiny SVGs to the temp folder."""
    key = (name, color)
    if key not in _ARROW_CACHE:
        d = Path(tempfile.gettempdir()) / "md_reader_icons"
        d.mkdir(exist_ok=True)
        f = d / f"{name}_{color.strip('#')}.svg"
        f.write_text(svg_icon_markup(name, color, 2.2), encoding="utf-8")
        _ARROW_CACHE[key] = f.as_posix()
    return _ARROW_CACHE[key]


# --------------------------------------------------------------------------------------
# Windows niceties
# --------------------------------------------------------------------------------------

def style_titlebar(widget, P):
    """Dark/light native title bar, tinted to match the app on Windows 11."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        val = ctypes.c_int(1 if P["theme"] == "dark" else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, old)
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break

        def colorref(hexc):
            c = QColor(hexc)
            return ctypes.c_int(c.red() | (c.green() << 8) | (c.blue() << 16))
        cap = colorref(P["chrome"])
        txt = colorref(P["fg"])
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(cap), ctypes.sizeof(cap))  # caption colour
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(txt), ctypes.sizeof(txt))  # text colour
    except Exception:
        pass


# --------------------------------------------------------------------------------------
# Markdown -> HTML
# --------------------------------------------------------------------------------------

LIST_RE = re.compile(r"^(?P<ind>[ \t]*)(?P<mark>[-*+]|\d{1,9}[.)])(?P<sp>[ \t]+|$)")
HR_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
FENCE_RE = re.compile(r"^(?P<ind>[ \t]*)(?P<f>`{3,}|~{3,})")


def _ind(s):
    return len(s) - len(s.lstrip(" \t")), len(s[: len(s) - len(s.lstrip(" \t"))].expandtabs(4))


def normalize_markdown(text):
    """Make GitHub-style Markdown render correctly with Python-Markdown.

    * adds the blank line Python-Markdown needs before a list / table / code fence
      that directly follows a paragraph line;
    * re-indents nested lists written with 2-space indentation (GitHub style) to the
      4 spaces Python-Markdown requires, keeping relative indentation of code inside.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = []
    fence = None          # current fence marker string
    stack = []            # open list items: [orig_indent, orig_content_col, new_indent]
    in_list = False
    prev_blank = True
    prev_kind = "blank"   # blank | para | list | table | other
    last_kind = "blank"   # kind of the last non-blank top-level line
    after_fence = False

    def reindent_cont(line):
        nchars, width = _ind(line)
        owner = None
        for item in stack:
            if item[0] < width:
                owner = item
        if owner is None:
            return line
        new_content = owner[2] + 4
        rel = max(width - owner[1], 0)
        return " " * (new_content + rel) + line[nchars:]

    for line in lines:
        stripped = line.strip()

        # ---- inside a fenced code block
        if fence is not None:
            m = FENCE_RE.match(line)
            closing = bool(m and m.group("f")[0] == fence[0] and len(m.group("f")) >= len(fence)
                           and stripped == m.group("f"))
            out.append(reindent_cont(line) if (in_list and stack and line[:1] in " \t") or
                       (in_list and stack and closing and line[:1] in " \t") else line)
            if closing:
                fence = None
                after_fence = True
            prev_blank = False
            continue

        if after_fence:
            after_fence = False
            if stripped:
                out.append("")   # Python-Markdown needs a blank line after a fence

        if not stripped:
            out.append("")
            prev_blank = True
            prev_kind = "blank"
            continue

        nchars, width = _ind(line)
        fm = FENCE_RE.match(line)
        lm = LIST_RE.match(line) if not HR_RE.match(line) else None

        # ---- does a list end here?
        if in_list and width == 0 and not lm:
            if prev_blank or stripped.startswith(("#", "|", "```", "~~~", ">")):
                in_list = False
                stack.clear()

        if lm and (in_list or width <= 3):
            mark = lm.group("mark")
            sp = lm.group("sp") or " "
            if not in_list and prev_kind in ("para", "table", "other") and not prev_blank:
                out.append("")
            while stack and width < stack[-1][0]:
                stack.pop()
            if stack and width <= stack[-1][0] + 1:
                stack.pop()
            level = len(stack)
            new_indent = 4 * level
            stack.append([width, width + len(mark) + len(sp.expandtabs(4)), new_indent])
            in_list = True
            out.append(" " * new_indent + line[nchars:])
            prev_kind = "list"
            prev_blank = False
            continue

        if in_list and stack:
            if fm:
                fence = fm.group("f")
            out.append(reindent_cont(line) if width > 0 else line)
            prev_kind = "list"
            prev_blank = False
            continue

        # ---- top level (not in a list)
        if fm:
            if not prev_blank:
                out.append("")
            fence = fm.group("f")
            out.append(line)
            prev_kind = "other"
            prev_blank = False
            continue
        if stripped.startswith(">"):
            if prev_blank and last_kind == "quote":
                out.append("<!-- -->")
                out.append("")
            out.append(line)
            prev_kind = last_kind = "quote"
            prev_blank = False
            continue
        if stripped.startswith("|"):
            if not prev_blank and prev_kind != "table":
                out.append("")
            out.append(line)
            prev_kind = "table"
            prev_blank = False
            continue
        out.append(line)
        if prev_kind == "quote" and not prev_blank:
            prev_kind = "quote"   # lazy continuation of a quote
        elif stripped.startswith("#"):
            prev_kind = "other"
        elif prev_kind == "table" and "|" in stripped:
            prev_kind = "table"
        else:
            prev_kind = "para"
        last_kind = prev_kind
        prev_blank = False
    return "\n".join(out)


class Renderer:
    def __init__(self):
        if HAVE_PYMDOWNX:
            exts = ["abbr", "attr_list", "def_list", "footnotes", "md_in_html", "tables",
                    "admonition", "sane_lists", "toc",
                    "pymdownx.superfences", "pymdownx.highlight", "pymdownx.inlinehilite",
                    "pymdownx.tasklist", "pymdownx.tilde", "pymdownx.mark",
                    "pymdownx.magiclink", "pymdownx.betterem", "pymdownx.keys"]
            cfg = {
                "pymdownx.highlight": {"css_class": "highlight", "guess_lang": False,
                                       "use_pygments": HAVE_PYGMENTS, "pygments_lang_class": True},
                "pymdownx.tasklist": {"custom_checkbox": True},
                "toc": {"permalink": False},
            }
        else:
            exts = ["extra", "admonition", "sane_lists", "toc", "codehilite"]
            cfg = {"codehilite": {"css_class": "highlight", "guess_lang": False}}
        try:
            self.md = markdown.Markdown(extensions=exts, extension_configs=cfg)
        except Exception:
            self.md = markdown.Markdown(extensions=["extra", "sane_lists", "toc"])

    def render(self, text):
        self.md.reset()
        try:
            return self.md.convert(normalize_markdown(text))
        except Exception as exc:  # never crash on odd input
            return f"<pre>{htmlmod.escape(text)}</pre><p><b>Render error:</b> {htmlmod.escape(str(exc))}</p>"


def pygments_css():
    if not HAVE_PYGMENTS:
        return ""
    from pygments.styles import get_all_styles
    styles = set(get_all_styles())
    dark = "github-dark" if "github-dark" in styles else "monokai"
    light = "default"
    css = HtmlFormatter(style=dark).get_style_defs('html[data-theme="dark"] .highlight')
    css += "\n" + HtmlFormatter(style=light).get_style_defs('html[data-theme="light"] .highlight')
    css += "\nhtml .highlight, html .highlight pre { background: transparent !important; }"
    return css


# --------------------------------------------------------------------------------------
# Preview page (HTML / CSS / JS)
# --------------------------------------------------------------------------------------

BASE_CSS = r"""
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:var(--bg);color:var(--fg)}
body{font-family:var(--font);font-size:var(--fs);line-height:1.68;-webkit-font-smoothing:antialiased;
  text-rendering:optimizeLegibility;overflow-wrap:break-word}
::selection{background:var(--sel)}
#content{max-width:var(--width);margin:0 auto;padding:44px 48px 140px}
#content>:first-child{margin-top:0!important}
h1,h2,h3,h4,h5,h6{font-weight:650;line-height:1.28;margin:1.7em 0 .6em;letter-spacing:-.012em;color:var(--fg)}
h1{font-size:2em;padding-bottom:.3em;border-bottom:1px solid var(--border)}
h2{font-size:1.5em;padding-bottom:.28em;border-bottom:1px solid var(--border)}
h3{font-size:1.25em}h4{font-size:1.06em}h5{font-size:.95em}h6{font-size:.9em;color:var(--muted)}
p{margin:0 0 1em}
a{color:var(--link);text-decoration:underline;text-decoration-color:color-mix(in srgb,var(--link) 40%,transparent);
  text-underline-offset:3px;transition:text-decoration-color .15s}
a:hover{text-decoration-color:var(--link)}
strong{font-weight:650}
code,kbd{font-family:var(--mono);font-size:.86em}
:not(pre)>code{background:var(--code-bg);border:1px solid var(--border);border-radius:6px;padding:.12em .42em;white-space:break-spaces}
kbd{background:var(--surface);border:1px solid var(--border);border-bottom-width:2px;border-radius:5px;padding:.08em .4em}
mark{background:color-mix(in srgb,#f5c542 40%,transparent);color:inherit;border-radius:3px;padding:0 .15em}
del{color:var(--muted)}
pre{margin:0;padding:16px 18px;overflow:auto;line-height:1.55;font-size:.95em}
pre code{background:none;border:0;padding:0;font-size:.86em}
.code-block{position:relative;margin:0 0 1.2em;background:var(--code-bg);border:1px solid var(--border);border-radius:12px}
.code-block>.highlight,.code-block>pre{margin:0}
.code-tools{position:absolute;top:8px;right:8px;display:flex;gap:6px;align-items:center;opacity:0;transition:opacity .15s}
.code-block:hover .code-tools{opacity:1}
.code-lang{font:600 11px/1 var(--font);color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
blockquote{margin:0 0 1em;padding:.7em 1.1em;border-left:3px solid var(--accent);background:var(--quote-bg);
  border-radius:0 10px 10px 0;color:var(--quote)}
blockquote>:last-child{margin-bottom:0}
hr{border:0;height:1px;background:var(--border);margin:2.2em 0}
img{max-width:100%;border-radius:8px}
ul,ol{padding-left:1.7em;margin:0 0 1em}
li{margin:.28em 0}li>ul,li>ol{margin:.2em 0}li>p{margin:.3em 0}
li::marker{color:var(--muted)}
.task-list-item{list-style:none;margin-left:-1.4em}
.task-list-control{display:inline-block;margin-right:.5em;vertical-align:middle}
.task-list-control input{display:none}
.task-list-indicator{display:inline-block;width:1em;height:1em;border:1.5px solid var(--muted);border-radius:4px;vertical-align:-.12em}
.task-list-control input:checked+.task-list-indicator{background:var(--accent);border-color:var(--accent);
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='white' stroke-width='3.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='20 6 9 17 4 12'/%3E%3C/svg%3E");
  background-size:80%;background-position:center;background-repeat:no-repeat}
li>input[type=checkbox]{margin-right:.5em}
dt{font-weight:650;margin-top:.6em}dd{margin:0 0 .6em 1.4em;color:var(--quote)}
.footnote{font-size:.9em;color:var(--muted)}
.footnote hr{margin:2em 0 1em}

/* tables */
.table-block{position:relative;margin:2.1em 0 1.3em}
.table-scroll{overflow:auto;border:1px solid var(--border);border-radius:12px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:.94em}
.table-block table{margin:0}
th,td{position:relative;text-align:left;padding:10px 38px 10px 14px;border-bottom:1px solid var(--border);vertical-align:top}
th{background:var(--th);font-weight:620;white-space:nowrap}
tbody tr:last-child td{border-bottom:0}
tbody tr{transition:background .12s}
tbody tr:hover{background:var(--row-hover)}
#content>table{border:1px solid var(--border)}

.cell-copy,.code-copy,.table-copy{display:inline-flex;align-items:center;justify-content:center;gap:5px;
  border:1px solid var(--border);background:var(--surface);color:var(--muted);cursor:pointer;
  font:600 11.5px/1 var(--font);border-radius:7px;transition:opacity .14s,transform .14s,color .14s,border-color .14s,background .14s;
  box-shadow:0 2px 8px var(--shadow)}
.cell-copy{position:absolute;top:50%;right:7px;width:24px;height:24px;padding:0;opacity:0;transform:translateY(-50%) scale(.85)}
td:hover>.cell-copy,th:hover>.cell-copy{opacity:1;transform:translateY(-50%) scale(1)}
.cell-copy svg{width:13px;height:13px}
.code-copy{padding:5px 9px}
.code-copy svg,.table-copy svg{width:13px;height:13px}
.table-copy{position:absolute;right:2px;bottom:calc(100% + 6px);padding:5px 9px;opacity:0;transform:translateY(3px)}
.table-block:hover .table-copy{opacity:1;transform:none}
.cell-copy:hover,.code-copy:hover,.table-copy:hover{color:var(--accent);border-color:var(--accent)}
.cell-copy.done,.code-copy.done,.table-copy.done{color:var(--ok);border-color:var(--ok)}
body.no-cell-copy .cell-copy{display:none}
body.no-cell-copy th,body.no-cell-copy td{padding-right:14px}

/* GitHub alerts + admonitions */
.alert,.admonition{border-left:3px solid var(--alert);background:color-mix(in srgb,var(--alert) 8%,transparent);
  color:var(--fg);border-radius:0 10px 10px 0;padding:.75em 1.1em;margin:0 0 1em}
.alert-title,.admonition-title{font-weight:650;color:var(--alert);margin:0 0 .3em!important}
.alert-note,.admonition.note,.admonition.info{--alert:#4c8dff}
.alert-tip,.admonition.tip,.admonition.hint{--alert:#3fb950}
.alert-important,.admonition.important{--alert:#a371f7}
.alert-warning,.admonition.warning,.admonition.attention{--alert:#d29922}
.alert-caution,.admonition.danger,.admonition.caution,.admonition.error{--alert:#f85149}
.admonition{--alert:var(--accent)}

/* welcome screen */
.welcome{min-height:72vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
.welcome .logo svg{width:76px;height:76px;filter:drop-shadow(0 10px 24px rgba(90,110,255,.35))}
.welcome h1{border:0;font-size:1.9em;margin:.6em 0 .2em}
.welcome p{color:var(--muted);margin:.2em 0}
.welcome .actions{display:flex;gap:10px;margin:1.6em 0 1.2em}
.btn{font:600 14px/1 var(--font);padding:11px 18px;border-radius:10px;border:1px solid var(--border);
  background:var(--surface);color:var(--fg);cursor:pointer;transition:all .15s}
.btn:hover{border-color:var(--accent);color:var(--accent)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.btn.primary:hover{filter:brightness(1.08);color:var(--on-accent)}
.recent{margin-top:1.4em;width:min(520px,100%);text-align:left}
.recent h4{margin:0 0 .5em;font-size:.78em;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.recent a{display:block;padding:8px 12px;border-radius:8px;text-decoration:none;color:var(--fg);font-size:.92em}
.recent a span{display:block;color:var(--muted);font-size:.82em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.recent a:hover{background:var(--row-hover)}
.hint{font-size:.85em}

body.at-home #content{max-width:760px}
.home{padding:7vh 0 40px;display:flex;flex-direction:column;align-items:center}
.home .hero{text-align:center}
.home .logo svg{width:72px;height:72px;filter:drop-shadow(0 10px 24px rgba(90,110,255,.35))}
.home h1{border:0;font-size:1.9em;margin:.45em 0 .15em;padding:0}
.home .hero p{color:var(--muted);margin:0}
.home .actions{display:flex;gap:10px;margin:28px 0 20px}
.btn{display:inline-flex;align-items:center;gap:8px}
.btn svg{width:16px;height:16px}
.restore{display:flex;align-items:center;gap:10px;width:100%;max-width:520px;padding:12px 16px;
  border:1px dashed var(--border);border-radius:12px;background:transparent;color:var(--fg);
  font:600 14px/1.2 var(--font);cursor:pointer;transition:border-color .15s,background .15s}
.restore svg{width:16px;height:16px;color:var(--accent)}
.restore em{margin-left:auto;font-style:normal;color:var(--muted);font-weight:500}
.restore:hover{border-color:var(--accent);background:var(--row-hover)}
.home .recent{width:100%;max-width:520px;margin-top:22px}
.home .recent h4{margin:0 0 8px 12px;font-size:.72em;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.home .recent a{display:flex;align-items:center;gap:12px;padding:9px 12px;border-radius:10px;text-decoration:none;color:var(--fg)}
.home .recent a:hover{background:var(--row-hover)}
.home .recent .fi svg{width:18px;height:18px;color:var(--muted);display:block}
.home .recent .ft{display:flex;flex-direction:column;min-width:0;flex:1;line-height:1.35}
.home .recent .ft b{font-weight:600;font-size:.93em}
.home .recent .ft small{color:var(--muted);font-size:.78em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.home .recent i{font-style:normal;font-size:.72em;font-weight:600;color:var(--accent);
  background:color-mix(in srgb,var(--accent) 14%,transparent);padding:2px 8px;border-radius:999px}
.home .hint{color:var(--muted);font-size:.82em;margin-top:26px}
.empty-doc{color:var(--muted);text-align:center;margin-top:18vh}
.empty-doc p{margin:.3em 0}
#toast{position:fixed;left:50%;bottom:26px;transform:translate(-50%,16px);opacity:0;pointer-events:none;
  background:var(--fg);color:var(--bg);font:600 13px/1 var(--font);padding:10px 16px;border-radius:999px;
  box-shadow:0 8px 24px var(--shadow);transition:all .2s}
#toast.show{opacity:.95;transform:translate(-50%,0)}

::-webkit-scrollbar{width:12px;height:12px}
::-webkit-scrollbar-thumb{background:var(--scroll);border-radius:8px;border:3px solid transparent;background-clip:content-box}
::-webkit-scrollbar-thumb:hover{background:var(--muted);background-clip:content-box;border:3px solid transparent}
::-webkit-scrollbar-track,::-webkit-scrollbar-corner{background:transparent}

@media (max-width:700px){#content{padding:28px 20px 100px}}
@media print{.cell-copy,.code-tools,.table-copy,#toast{display:none!important}#content{max-width:none;padding:0}
  .code-block,.table-scroll{break-inside:avoid}}
"""

APP_JS = r"""
(function(){
const C=document.getElementById('content');
let bridge=null;
try{ new QWebChannel(qt.webChannelTransport,function(ch){ bridge=ch.objects.bridge; }); }catch(e){}
const SV='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">';
const I_COPY=SV+'<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
const I_CHECK=SV+'<polyline points="20 6 9 17 4 12"/></svg>';
const I_TABLE=SV+'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M12 3v18"/></svg>';
let toastTimer=null;
function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');
  clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.classList.remove('show'),1300);}
function copy(text,label){
  if(bridge){bridge.copy(text);}else if(navigator.clipboard){navigator.clipboard.writeText(text);}
  toast(label||'Copied');}
function flash(btn){const orig=btn.dataset.orig||btn.innerHTML;btn.dataset.orig=orig;
  btn.innerHTML=I_CHECK+(btn.querySelector('span')?'<span>Copied</span>':'');btn.classList.add('done');
  clearTimeout(btn._t);btn._t=setTimeout(()=>{btn.innerHTML=orig;btn.classList.remove('done');},1200);}
function mkBtn(cls,html,title){const b=document.createElement('button');b.type='button';b.className=cls;
  b.innerHTML=html;b.title=title;b.addEventListener('mousedown',e=>e.preventDefault());return b;}
function cellText(cell){return cell.innerText.replace(/\u00a0/g,' ').replace(/[ \t]+\n/g,'\n').trim();}
function tableTSV(tbl){return Array.from(tbl.rows).map(r=>Array.from(r.cells).map(c=>cellText(c).replace(/[\t\r\n]+/g,' ')).join('\t')).join('\n');}

function enhance(){
  C.querySelectorAll('blockquote').forEach(bq=>{
    const p=bq.firstElementChild; if(!p||p.tagName!=='P')return;
    const m=p.innerHTML.match(/^\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(<br\s*\/?>)?/i); if(!m)return;
    const kind=m[1].toLowerCase(); p.innerHTML=p.innerHTML.slice(m[0].length);
    if(!p.innerHTML.trim())p.remove();
    bq.classList.add('alert','alert-'+kind);
    const h=document.createElement('p');h.className='alert-title';h.textContent=kind[0].toUpperCase()+kind.slice(1);bq.prepend(h);
  });
  C.querySelectorAll('table').forEach(tbl=>{
    if(tbl.closest('.table-block'))return;
    const block=document.createElement('div');block.className='table-block';
    const scroll=document.createElement('div');scroll.className='table-scroll';
    tbl.parentNode.insertBefore(block,tbl);scroll.appendChild(tbl);block.appendChild(scroll);
    const tb=mkBtn('table-copy',I_TABLE+'<span>Copy table</span>','Copy the whole table (pastes into Excel)');
    tb.addEventListener('click',e=>{e.preventDefault();copy(tableTSV(tbl),'Table copied');flash(tb);});
    block.appendChild(tb);
    tbl.querySelectorAll('th,td').forEach(cell=>{
      const b=mkBtn('cell-copy',I_COPY,'Copy cell');
      b.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();copy(cellText(cell),'Cell copied');flash(b);});
      cell.appendChild(b);});
  });
  C.querySelectorAll('pre').forEach(pre=>{
    const host=(pre.parentElement&&pre.parentElement.classList.contains('highlight'))?pre.parentElement:pre;
    if(host.parentElement&&host.parentElement.classList.contains('code-block'))return;
    const w=document.createElement('div');w.className='code-block';
    host.parentNode.insertBefore(w,host);w.appendChild(host);
    const tools=document.createElement('div');tools.className='code-tools';
    const code=pre.querySelector('code');
    const lm=((code&&code.className)||'').match(/language-([\w+#-]+)/)||(host.className||'').match(/language-([\w+#-]+)/);
    if(lm){const l=document.createElement('span');l.className='code-lang';l.textContent=lm[1];tools.appendChild(l);}
    const b=mkBtn('code-copy',I_COPY+'<span>Copy</span>','Copy code');
    b.addEventListener('click',e=>{e.preventDefault();copy((code||pre).innerText.replace(/\n$/,''),'Code copied');flash(b);});
    tools.appendChild(b);w.appendChild(tools);
  });
}
window.mdRender=function(html,reset){C.innerHTML=html;enhance();if(reset)window.scrollTo(0,0);};
window.mdSetTheme=function(theme,vars){document.documentElement.setAttribute('data-theme',theme);
  document.getElementById('vars').textContent=vars;};
window.mdSetOptions=function(o){document.body.classList.toggle('no-cell-copy',!o.cellCopy);};
window.mdScrollToY=function(y){window.scrollTo(0,y);};
let scrollT=null;
window.addEventListener('scroll',()=>{clearTimeout(scrollT);scrollT=setTimeout(()=>{if(bridge)bridge.scroll(window.scrollY);},150);});
window.mdScrollTo=function(r){const max=document.documentElement.scrollHeight-window.innerHeight;window.scrollTo(0,Math.max(0,r*max));};
window.mdExport=function(){const c=C.cloneNode(true);
  c.querySelectorAll('.cell-copy,.table-copy,.code-tools').forEach(e=>e.remove());return c.innerHTML;};
document.addEventListener('click',e=>{
  const act=e.target.closest('[data-action]');
  if(act){e.preventDefault();if(bridge)bridge.action(act.dataset.action);return;}
  const a=e.target.closest('a[href^="#"]');
  if(a){e.preventDefault();const id=decodeURIComponent(a.getAttribute('href').slice(1));
    const t=document.getElementById(id)||document.getElementsByName(id)[0];
    if(t)t.scrollIntoView({behavior:'smooth',block:'start'});}
});
})();
"""


def css_vars(P, s):
    width = READING_WIDTHS.get(s["reading_width"], READING_WIDTHS["comfortable"])[1]
    font = READING_FONTS.get(s["reading_font"], READING_FONTS["sans"])[1]
    v = {
        "bg": P["bg"], "surface": P["surface"], "th": P["th"], "border": P["border"],
        "fg": P["fg"], "muted": P["muted"], "accent": P["accent"], "link": P["link"],
        "code-bg": P["code_bg"], "quote-bg": P["quote_bg"], "quote": P["quote_fg"],
        "row-hover": P["row_hover"], "ok": P["ok"], "shadow": P["shadow"], "sel": P["sel"],
        "scroll": P["scroll"], "on-accent": P["on_accent"],
        "fs": f'{int(s["preview_font_size"])}px', "width": width, "font": font, "mono": MONO_STACK,
    }
    return ":root{" + ";".join(f"--{k}:{val}" for k, val in v.items()) + "}"


def qwebchannel_js():
    f = QFile(":/qtwebchannel/qwebchannel.js")
    if f.open(QIODevice.OpenModeFlag.ReadOnly):
        data = bytes(f.readAll()).decode("utf-8")
        f.close()
        return data
    return ""


def shell_html(P, s, pyg):
    return ("<!doctype html><html data-theme=\"" + P["theme"] + "\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<style id=\"vars\">" + css_vars(P, s) + "</style>"
            "<style>" + BASE_CSS + "</style><style>" + pyg + "</style>"
            "<script>" + qwebchannel_js() + "</script></head>"
            "<body><main id=\"content\"></main><div id=\"toast\"></div>"
            "<script>" + APP_JS + "</script></body></html>")


# --------------------------------------------------------------------------------------
# Web view plumbing
# --------------------------------------------------------------------------------------

class Bridge(QObject):
    copied = Signal(str)
    actionRequested = Signal(str)
    scrolled = Signal(float)

    @Slot(float)
    def scroll(self, y):
        self.scrolled.emit(y)

    @Slot(str)
    def copy(self, text):
        QGuiApplication.clipboard().setText(text)
        self.copied.emit(text)

    @Slot(str)
    def action(self, name):
        self.actionRequested.emit(name)


class WebPage(QWebEnginePage):
    linkClicked = Signal(QUrl)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            self.linkClicked.emit(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class WebView(QWebEngineView):
    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        drop = {QWebEnginePage.WebAction.Back, QWebEnginePage.WebAction.Forward,
                QWebEnginePage.WebAction.Reload, QWebEnginePage.WebAction.ViewSource,
                QWebEnginePage.WebAction.SavePage, QWebEnginePage.WebAction.OpenLinkInNewWindow,
                QWebEnginePage.WebAction.OpenLinkInNewTab, QWebEnginePage.WebAction.OpenLinkInThisWindow,
                QWebEnginePage.WebAction.DownloadLinkToDisk, QWebEnginePage.WebAction.DownloadImageToDisk}
        for wa in drop:
            try:
                menu.removeAction(self.page().action(wa))
            except Exception:
                pass
        acts = menu.actions()
        while acts and acts[0].isSeparator():
            menu.removeAction(acts.pop(0))
        if menu.actions():
            menu.exec(event.globalPos())


# --------------------------------------------------------------------------------------
# Widgets
# --------------------------------------------------------------------------------------

class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(38, 22)
        self._p = 0.0
        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)
        self.colors = {"off": "#45474e", "on": "#6aa9ff", "knob": "#ffffff"}

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._p)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def set_now(self, on):
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._p = 1.0 if on else 0.0
        self.update()

    def _get(self):
        return self._p

    def _set(self, v):
        self._p = v
        self.update()

    progress = Property(float, _get, _set)

    def sizeHint(self):
        return QSize(38, 22)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.4)
        off, on, t = QColor(self.colors["off"]), QColor(self.colors["on"]), self._p
        track = QColor.fromRgbF(off.redF() + (on.redF() - off.redF()) * t,
                                off.greenF() + (on.greenF() - off.greenF()) * t,
                                off.blueF() + (on.blueF() - off.blueF()) * t)
        w, h = self.width(), self.height()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        d = h - 6
        x = 3 + (w - 6 - d) * t
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QRectF(x, 3.6, d, d))
        p.setBrush(QColor(self.colors["knob"]))
        p.drawEllipse(QRectF(x, 3, d, d))
        p.end()


class ClickFrame(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class MdHighlighter(QSyntaxHighlighter):
    """Light-weight Markdown syntax colouring for the Raw editor."""
    IN_FENCE = 1

    def __init__(self, doc):
        super().__init__(doc)
        self.f = {}
        self.inline = []

    def set_palette(self, P):
        def fmt(color, bold=False, italic=False, bg=None, strike=False, size=None):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            if italic:
                f.setFontItalic(True)
            if strike:
                f.setFontStrikeOut(True)
            if bg:
                f.setBackground(QColor(bg))
            return f
        acc, muted = P["accent"], P["muted"]
        self.f = {
            "heading": fmt(acc, bold=True),
            "hmark": fmt(muted, bold=True),
            "code": fmt(P["code_fg"]),
            "fence": fmt(muted),
            "quote": fmt(P["quote_fg"], italic=True),
            "list": fmt(acc, bold=True),
            "pipe": fmt(muted),
            "hr": fmt(muted, bold=True),
        }
        self.inline = [
            (re.compile(r"`[^`\n]+`"), fmt(P["code_fg"])),
            (re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1"), fmt(P["fg"], bold=True)),
            (re.compile(r"(?<![*\w])\*(?=[^\s*])([^*\n]+?)(?<=\S)\*(?!\*)|(?<![_\w])_(?=\S)([^_\n]+?)(?<=\S)_(?![_\w])"),
             fmt(P["fg"], italic=True)),
            (re.compile(r"~~(?=\S).+?(?<=\S)~~"), fmt(muted, strike=True)),
            (re.compile(r"!?\[[^\]\n]*\]\([^)\n]*\)"), fmt(acc)),
            (re.compile(r"<https?://[^>\s]+>|https?://[^\s)>\]]+"), fmt(acc)),
            (re.compile(r"</?[A-Za-z][^>\n]*>"), fmt(muted)),
        ]
        doc = self.document()
        was = doc.isModified() if doc else False
        self.rehighlight()
        if doc and doc.isModified() != was:
            doc.setModified(was)

    def _set(self, text, start, length, f):
        if any(ord(ch) > 0xFFFF for ch in text):  # convert to UTF-16 offsets
            u = lambda i: len(text[:i].encode("utf-16-le")) // 2  # noqa: E731
            start, length = u(start), u(start + length) - u(start)
        self.setFormat(start, length, f)

    def highlightBlock(self, text):
        if not self.f:
            return
        stripped = text.strip()
        if self.previousBlockState() == self.IN_FENCE:
            self._set(text, 0, len(text), self.f["code"])
            if stripped.startswith(("```", "~~~")):
                self._set(text, 0, len(text), self.f["fence"])
                self.setCurrentBlockState(0)
            else:
                self.setCurrentBlockState(self.IN_FENCE)
            return
        if stripped.startswith(("```", "~~~")):
            self._set(text, 0, len(text), self.f["fence"])
            self.setCurrentBlockState(self.IN_FENCE)
            return
        self.setCurrentBlockState(0)
        m = re.match(r"^(\s{0,3}#{1,6})(\s.*|$)", text)
        if m:
            self._set(text, 0, len(text), self.f["heading"])
            self._set(text, 0, len(m.group(1)), self.f["hmark"])
            return
        if HR_RE.match(text):
            self._set(text, 0, len(text), self.f["hr"])
            return
        if re.match(r"^\s*>", text):
            self._set(text, 0, len(text), self.f["quote"])
        m = LIST_RE.match(text)
        if m:
            self._set(text, len(m.group("ind")), len(m.group("mark")), self.f["list"])
            t = re.match(r"\s*\[[ xX]\]", text[m.end():])
            if t:
                self._set(text, m.end(), t.end(), self.f["list"])
        for rx, f in self.inline:
            for mm in rx.finditer(text):
                self._set(text, mm.start(), mm.end() - mm.start(), f)
        if stripped.startswith("|"):
            if re.match(r"^\s*\|?[\s:\-|]+\|?\s*$", text):
                self._set(text, 0, len(text), self.f["pipe"])
            else:
                for mm in re.finditer(r"\|", text):
                    self._set(text, mm.start(), 1, self.f["pipe"])


class Editor(QPlainTextEdit):
    """Plain-text Markdown editor with list auto-continue and soft tabs."""

    def __init__(self):
        super().__init__()
        self.setObjectName("editor")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.document().setDocumentMargin(22)
        self.setTabChangesFocus(False)

    def keyPressEvent(self, e):
        if self.isReadOnly():
            return super().keyPressEvent(e)
        key = e.key()
        if key == Qt.Key.Key_Tab and not e.modifiers():
            self.insertPlainText("    ")
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not e.modifiers():
            cur = self.textCursor()
            line = cur.block().text()[: cur.positionInBlock()]
            m = re.match(r"^(\s*)([-*+]|(\d+)([.)]))(\s+)(\[[ xX]\]\s+)?", line)
            if m and cur.positionInBlock() == len(cur.block().text()):
                if line.strip() == m.group(0).strip():  # empty item -> end the list
                    cur.movePosition(QTextCursor.MoveOperation.StartOfBlock,
                                     QTextCursor.MoveMode.KeepAnchor)
                    cur.removeSelectedText()
                    return
                if m.group(3):
                    marker = f"{int(m.group(3)) + 1}{m.group(4)}"
                else:
                    marker = m.group(2)
                task = "[ ] " if m.group(6) else ""
                self.insertPlainText("\n" + m.group(1) + marker + m.group(5) + task)
                return
            indent = re.match(r"^\s*", cur.block().text()).group(0)
            self.insertPlainText("\n" + indent)
            return
        super().keyPressEvent(e)


class FindBar(QFrame):
    search = Signal(str, bool)   # text, backward
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("findbar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 7, 10, 7)
        lay.setSpacing(6)
        self.icon = QLabel()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Find in document")
        self.edit.setClearButtonEnabled(True)
        self.edit.setMaximumWidth(380)
        self.count = QLabel("")
        self.count.setObjectName("muted")
        self.prev = QToolButton(objectName="tb")
        self.next = QToolButton(objectName="tb")
        self.close_btn = QToolButton(objectName="tb")
        self.prev.setToolTip("Previous (Shift+Enter)")
        self.next.setToolTip("Next (Enter)")
        self.close_btn.setToolTip("Close (Esc)")
        for w in (self.icon, self.edit, self.count, self.prev, self.next):
            lay.addWidget(w)
        lay.addStretch(1)
        lay.addWidget(self.close_btn)
        self.edit.textChanged.connect(lambda t: self.search.emit(t, False))
        self.edit.installEventFilter(self)
        self.prev.clicked.connect(lambda: self.search.emit(self.edit.text(), True))
        self.next.clicked.connect(lambda: self.search.emit(self.edit.text(), False))
        self.close_btn.clicked.connect(self.closed.emit)

    def set_icons(self, P):
        self.icon.setPixmap(svg_pixmap(svg_icon_markup("search", P["muted"]), 16))
        self.prev.setIcon(make_icon("chevron-up", P["icon"]))
        self.next.setIcon(make_icon("chevron-down", P["icon"]))
        self.close_btn.setIcon(make_icon("x", P["icon"]))

    def eventFilter(self, obj, ev):
        if obj is self.edit and ev.type() == QEvent.Type.KeyPress:
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                back = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                self.search.emit(self.edit.text(), back)
                return True
            if ev.key() == Qt.Key.Key_Escape:
                self.closed.emit()
                return True
        return super().eventFilter(obj, ev)


# --------------------------------------------------------------------------------------
# Settings dialog
# --------------------------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, s, P, parent=None):
        super().__init__(parent)
        self.s, self.P = s, P
        self.setWindowTitle("Settings")
        self.setMinimumSize(600, 640)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QFrame(objectName="dlgHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(26, 22, 26, 14)
        t = QLabel("Settings", objectName="dlgTitle")
        sub = QLabel("Make MD Reader look and behave the way you like.", objectName="muted")
        hl.addWidget(t)
        hl.addWidget(sub)
        outer.addWidget(head)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget(objectName="dlgBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(22, 6, 22, 18)
        bl.setSpacing(16)
        area.setWidget(body)
        outer.addWidget(area, 1)

        self.w = {}

        # Windows: default app + install / uninstall
        c = self._card(bl, "WINDOWS")
        self.btn_default = QPushButton("Make default")
        self.btn_default.clicked.connect(self._make_default)
        _, self.desc_default = self._row(c, "Default .md reader / editor", " ", self.btn_default, None)
        self.btn_install = QPushButton("Install…")
        self.btn_install.clicked.connect(self._install_clicked)
        _, self.desc_install = self._row(c, "Installation", " ", self.btn_install, None)
        self.next_action = None
        self._refresh_system()


        # Appearance
        c = self._card(bl, "APPEARANCE")
        cb = QComboBox()
        for key, label in (("system", "Match Windows"), ("light", "Light"), ("dark", "Dark")):
            cb.addItem(label, key)
        cb.setCurrentIndex(max(0, cb.findData(s["theme"])))
        self._row(c, "Theme", "Light, dark, or follow the Windows setting.", cb, "theme")
        cb = QComboBox()
        for name, pair in ACCENTS.items():
            px = QPixmap(28, 28)
            px.fill(Qt.GlobalColor.transparent)
            p = QPainter(px)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(pair[0] if P["theme"] == "dark" else pair[1]))
            p.drawEllipse(4, 4, 20, 20)
            p.end()
            px.setDevicePixelRatio(2)
            cb.addItem(QIcon(px), name, name)
        cb.setCurrentIndex(max(0, cb.findData(s["accent"])))
        self._row(c, "Accent colour", "Used for links, headings in the editor and highlights.", cb, "accent")

        # Reading
        c = self._card(bl, "READING")
        sp = QSpinBox()
        sp.setRange(11, 28)
        sp.setSuffix(" px")
        sp.setValue(int(s["preview_font_size"]))
        self._row(c, "Text size", "Font size of the Preview.", sp, "preview_font_size")
        cb = QComboBox()
        for key, (label, _) in READING_FONTS.items():
            cb.addItem(label, key)
        cb.setCurrentIndex(max(0, cb.findData(s["reading_font"])))
        self._row(c, "Reading font", "Typeface used in the Preview.", cb, "reading_font")
        cb = QComboBox()
        for key, (label, _) in READING_WIDTHS.items():
            cb.addItem(label, key)
        cb.setCurrentIndex(max(0, cb.findData(s["reading_width"])))
        self._row(c, "Page width", "How wide the text column can get.", cb, "reading_width")
        self._row(c, "Table copy buttons", "Show a copy button when you hover a table cell.",
                  self._switch(s["cell_copy"]), "cell_copy")

        # Editing
        c = self._card(bl, "EDITING")
        self._row(c, "Start in Edit mode", "Off = files open read-only until you switch Edit on.",
                  self._switch(s["edit_by_default"]), "edit_by_default")
        self._row(c, "Live preview while editing", "In the Preview tab, editing shows the editor beside the preview.",
                  self._switch(s["split_when_editing"]), "split_when_editing")
        self._row(c, "Sync scrolling", "Scroll the preview along with the editor.",
                  self._switch(s["sync_scroll"]), "sync_scroll")
        self._row(c, "Word wrap", "Wrap long lines in the Raw editor.",
                  self._switch(s["word_wrap"]), "word_wrap")
        fc = QFontComboBox()
        fc.setFontFilters(QFontComboBox.FontFilter.MonospacedFonts)
        fc.setCurrentFont(QFont(s["editor_font"] or default_mono_family()))
        self._row(c, "Editor font", "Monospaced font for the Raw editor.", fc, "editor_font")
        sp = QSpinBox()
        sp.setRange(8, 28)
        sp.setSuffix(" pt")
        sp.setValue(int(s["editor_font_size"]))
        self._row(c, "Editor text size", "Font size of the Raw editor.", sp, "editor_font_size")

        # Files
        c = self._card(bl, "FILES")
        cb = QComboBox()
        cb.addItem("Show the home screen", "home")
        cb.addItem("Reopen last files", "last")
        cb.setCurrentIndex(max(0, cb.findData(s.get("startup", "home"))))
        self._row(c, "When MD Reader opens", "Files you double-click always open, either way.", cb, "startup")
        self._row(c, "Reload when changed on disk", "Pick up changes made by other programs automatically.",
                  self._switch(s["auto_reload"]), "auto_reload")
        c = self._card(bl, "ABOUT")
        where = {"machine": "Installed for all users.", "user": "Installed for you."}.get(
            install_scope(), "Portable copy." if is_frozen() else "Running as a Python script.")
        kb = QPushButton("Keyboard shortcuts")
        kb.clicked.connect(lambda: self._go("shortcuts"))
        self._row(c, f"{APP_NAME} {APP_VERSION}", where, kb, None)

        loc = QLabel(f"Settings are saved in: {s.path}", objectName="muted")
        loc.setWordWrap(True)
        loc.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bl.addWidget(loc)
        bl.addStretch(1)

        foot = QFrame(objectName="dlgFoot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(22, 12, 22, 14)
        reset = QPushButton("Reset to defaults")
        cancel = QPushButton("Cancel")
        save = QPushButton("Save", objectName="primary")
        save.setDefault(True)
        fl.addWidget(reset)
        fl.addStretch(1)
        fl.addWidget(cancel)
        fl.addWidget(save)
        outer.addWidget(foot)
        reset.clicked.connect(self._reset)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)

    def showEvent(self, e):
        super().showEvent(e)
        style_titlebar(self, self.P)

    def _switch(self, on):
        sw = ToggleSwitch()
        sw.colors = {"off": self.P["switch_off"], "on": self.P["accent"], "knob": "#ffffff"}
        sw.set_now(bool(on))
        return sw

    def _card(self, parent_layout, title):
        lbl = QLabel(title, objectName="sectionTitle")
        parent_layout.addWidget(lbl)
        card = QFrame(objectName="card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(0)
        parent_layout.addWidget(card)
        return lay

    def _row(self, card_layout, title, desc, widget, key):
        if card_layout.count():
            line = QFrame(objectName="rowLine")
            line.setFixedHeight(1)
            card_layout.addWidget(line)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(16, 11, 16, 11)
        txt = QVBoxLayout()
        txt.setSpacing(2)
        a = QLabel(title, objectName="rowTitle")
        txt.addWidget(a)
        if desc:
            b = QLabel(desc, objectName="muted")
            b.setWordWrap(True)
            txt.addWidget(b)
        rl.addLayout(txt, 1)
        rl.addSpacing(16)
        if isinstance(widget, (QComboBox, QSpinBox, QPushButton)):
            # every control sits in the same 190 px column, whatever its own size hint
            box = QWidget()
            box.setFixedWidth(190)
            bl_ = QHBoxLayout(box)
            bl_.setContentsMargins(0, 0, 0, 0)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            bl_.addWidget(widget)
            rl.addWidget(box, 0, Qt.AlignmentFlag.AlignVCenter)
        else:
            rl.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        card_layout.addWidget(row)
        if key:
            self.w[key] = widget
        return row, (b if desc else None)

    def _refresh_system(self):
        if not IS_WIN:
            self.btn_default.setEnabled(False)
            self.desc_default.setText("Only available on Windows.")
        elif is_default():
            self.btn_default.setText("Default ✓")
            self.btn_default.setEnabled(False)
            self.desc_default.setText("Double-clicking a .md file opens it in MD Reader.")
        else:
            self.btn_default.setText("Make default")
            self.btn_default.setEnabled(True)
            self.desc_default.setText("Open .md files in MD Reader when you double-click them.")
        scope = install_scope()
        self.btn_install.setObjectName("danger" if scope else "")
        self.btn_install.style().unpolish(self.btn_install)
        self.btn_install.style().polish(self.btn_install)
        if scope:
            who = "all users" if scope == "machine" else "you"
            self.desc_install.setText(f"Installed for {who}. Also listed in Windows Settings > Apps.")
            self.btn_install.setText("Uninstall…")
            self.btn_install.setIcon(shield_icon() if scope == "machine" and not is_admin() else QIcon())
        elif IS_WIN and is_frozen():
            self.desc_install.setText("Portable copy (not installed).")
            self.btn_install.setText("Update…" if existing_install() else "Install…")
        else:
            self.desc_install.setText("Running as a Python script. Build the EXE (Build EXE.bat) to install it.")
            self.btn_install.setVisible(False)

    def _make_default(self):
        parent = self.parent()
        if parent is not None and hasattr(parent, "make_default_flow"):
            parent.make_default_flow()
        self._refresh_system()

    def _go(self, action):
        self.next_action = action
        self.reject()

    def _install_clicked(self):
        self.next_action = "uninstall" if install_scope() else "install"
        self.reject()

    def _reset(self):
        for key, w in self.w.items():
            v = DEFAULTS[key]
            if isinstance(w, ToggleSwitch):
                w.setChecked(bool(v))
            elif isinstance(w, QFontComboBox):
                w.setCurrentFont(QFont(default_mono_family()))
            elif isinstance(w, QComboBox):
                w.setCurrentIndex(max(0, w.findData(v)))
            elif isinstance(w, QSpinBox):
                w.setValue(int(v))

    def values(self):
        out = {}
        for key, w in self.w.items():
            if isinstance(w, ToggleSwitch):
                out[key] = w.isChecked()
            elif isinstance(w, QFontComboBox):
                out[key] = w.currentFont().family()
            elif isinstance(w, QComboBox):
                out[key] = w.currentData()
            elif isinstance(w, QSpinBox):
                out[key] = w.value()
        return out


def default_mono_family():
    fams = set(QFontDatabase.families())
    for f in ("Cascadia Code", "Cascadia Mono", "JetBrains Mono", "Consolas", "DejaVu Sans Mono",
              "Courier New"):
        if f in fams:
            return f
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()


# --------------------------------------------------------------------------------------
# Qt stylesheet
# --------------------------------------------------------------------------------------

def build_qss(P):
    down = arrow_file("chevron-down", P["muted"])
    up = arrow_file("chevron-up", P["muted"])
    return f"""
QMainWindow, QDialog {{ background: {P['bg']}; }}
QWidget {{ color: {P['fg']}; font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif; font-size: 10pt; }}
#topbar {{ background: {P['chrome']}; }}
#tabstrip {{ background: {P['chrome']}; }}
#brand {{ font-size: 11pt; font-weight: 700; }}
QToolButton#menuBtn {{ background: transparent; border: none; border-radius: 8px; padding: 0 10px 0 12px;
    font-weight: 600; color: {P['fg']}; }}
QToolButton#menuBtn:hover, QToolButton#menuBtn:pressed {{ background: {P['hover']}; }}
QToolButton#menuBtn::menu-indicator {{ image: none; width: 0px; }}
QToolButton#tb:disabled {{ background: transparent; }}
QToolButton#homeTab {{ background: transparent; border: 1px solid transparent; border-bottom: none;
    border-top-left-radius: 8px; border-top-right-radius: 8px; }}
QToolButton#homeTab:hover {{ background: {P['hover']}; }}
QToolButton#homeTab:checked {{ background: {P['bg']}; border-color: {P['border']}; }}
QTabBar#docTabs {{ background: transparent; border: none; font-size: 9.5pt; }}
QTabBar#docTabs::tab {{ background: transparent; color: {P['muted']}; height: 30px; padding: 0 0 0 12px;
    margin: 0 2px 0 0; border: 1px solid transparent; border-bottom: none;
    border-top-left-radius: 8px; border-top-right-radius: 8px; min-width: 64px; max-width: 220px; }}
QTabBar#docTabs::tab:selected {{ background: {P['bg']}; color: {P['fg']}; border-color: {P['border']}; }}
QTabBar#docTabs::tab:hover:!selected {{ background: {P['hover']}; color: {P['fg']}; }}
QTabBar#docTabs[home="true"]::tab:selected {{ background: transparent; color: {P['muted']}; border-color: transparent; }}
QTabBar#docTabs[home="true"]::tab:selected:hover {{ background: {P['hover']}; color: {P['fg']}; }}
QTabBar QToolButton {{ background: {P['chrome']}; border: none; border-radius: 6px; }}
QToolButton#tabClose {{ background: transparent; border: none; border-radius: 5px; padding: 0; }}
QToolButton#tabClose:hover {{ background: {P['pressed']}; }}
QPushButton#segbtn:disabled {{ color: {P['scroll']}; }}
#editPill:disabled {{ border-color: {P['border']}; background: {P['seg_bg']}; }}
#editLabel:disabled {{ color: {P['scroll']}; }}
#optCard {{ background: {P['surface']}; border: 1px solid {P['border']}; border-radius: 12px; }}
#optCard:hover {{ border-color: {P['muted']}; }}
#optCard[selected="true"] {{ border-color: {P['accent']}; background: {P['accent_soft']}; }}
#optCard QLabel {{ background: transparent; }}
QPushButton#danger {{ color: #f85149; }}
QPushButton#danger:hover {{ border-color: #f85149; }}
QLabel:disabled {{ color: {P['muted']}; }}
#docTitle {{ font-size: 10.5pt; font-weight: 600; }}
#docSub, #muted {{ color: {P['muted']}; font-size: 8.5pt; }}
QToolButton#tb {{ background: transparent; border: none; border-radius: 8px; padding: 6px; }}
QToolButton#tb:hover {{ background: {P['hover']}; }}
QToolButton#tb:pressed, QToolButton#tb:checked {{ background: {P['pressed']}; }}
QToolButton#tb::menu-indicator {{ image: none; width: 0px; }}
#segment {{ background: {P['seg_bg']}; border: 1px solid {P['border']}; border-radius: 11px; }}
QPushButton#segbtn {{ background: transparent; border: none; border-radius: 8px; padding: 0 16px;
    color: {P['muted']}; font-weight: 600; min-width: 64px; }}
QPushButton#segbtn:hover {{ color: {P['fg']}; }}
QPushButton#segbtn:checked {{ background: {P['seg_active']}; color: {P['fg']}; }}
#editPill {{ background: {P['seg_bg']}; border: 1px solid {P['border']}; border-radius: 11px; }}
#editPill:hover {{ border-color: {P['muted']}; }}
#editPill[on="true"] {{ border-color: {P['accent']}; background: {P['accent_soft']}; }}
#editLabel {{ font-weight: 600; color: {P['muted']}; background: transparent; }}
#editPill[on="true"] #editLabel {{ color: {P['accent']}; }}
#sep {{ background: {P['border']}; }}
QPlainTextEdit#editor {{ background: {P['bg']}; color: {P['fg']}; border: none;
    selection-background-color: {P['sel']}; selection-color: {P['fg']}; }}
QSplitter::handle {{ background: {P['border']}; }}
QStatusBar {{ background: {P['chrome']}; border-top: 1px solid {P['border']}; min-height: 26px; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {P['muted']}; font-size: 8.5pt; padding: 0 8px; }}
QStatusBar QLabel#badge {{ color: {P['muted']}; background: {P['hover']}; border-radius: 8px; padding: 1px 9px; font-weight: 600; }}
QStatusBar QLabel#badge[editing="true"] {{ color: {P['accent']}; background: {P['accent_soft']}; }}
QMenu {{ background: {P['surface']}; border: 1px solid {P['border']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 30px 7px 10px; border-radius: 6px; background: transparent; }}
QMenu::item:selected {{ background: {P['hover']}; }}
QMenu::item:disabled {{ color: {P['muted']}; }}
QMenu::icon {{ padding-left: 8px; }}
QMenu::separator {{ height: 1px; background: {P['border']}; margin: 5px 8px; }}
QToolTip {{ background: {P['surface']}; color: {P['fg']}; border: 1px solid {P['border']}; padding: 5px 8px; border-radius: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {P['scroll']}; border-radius: 4px; min-height: 36px; margin: 2px 3px; }}
QScrollBar::handle:vertical:hover {{ background: {P['muted']}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {P['scroll']}; border-radius: 4px; min-width: 36px; margin: 3px 2px; }}
QScrollBar::handle:horizontal:hover {{ background: {P['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
#findbar {{ background: {P['chrome']}; border-top: 1px solid {P['border']}; }}
QLineEdit {{ background: {P['input']}; border: 1px solid {P['border']}; border-radius: 8px; padding: 6px 10px;
    selection-background-color: {P['sel']}; selection-color: {P['fg']}; }}
QLineEdit:focus {{ border-color: {P['accent']}; }}
QComboBox, QSpinBox, QFontComboBox {{ background: {P['input']}; border: 1px solid {P['border']}; border-radius: 8px;
    padding: 5px 10px; min-height: 20px; min-width: 150px; }}
QComboBox:hover, QSpinBox:hover {{ border-color: {P['muted']}; }}
QComboBox:focus, QSpinBox:focus {{ border-color: {P['accent']}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{down}"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {P['surface']}; border: 1px solid {P['border']}; border-radius: 8px;
    selection-background-color: {P['hover']}; selection-color: {P['fg']}; outline: 0; padding: 4px; }}
QSpinBox {{ min-width: 0px; }}
QSpinBox::up-button, QSpinBox::down-button {{ border: none; background: transparent; width: 20px; }}
QSpinBox::up-arrow {{ image: url("{up}"); width: 12px; height: 12px; }}
QSpinBox::down-arrow {{ image: url("{down}"); width: 12px; height: 12px; }}
QPushButton {{ background: {P['input']}; border: 1px solid {P['border']}; border-radius: 9px; padding: 8px 18px; font-weight: 600; }}
QPushButton:hover {{ background: {P['hover']}; }}
QPushButton#primary {{ background: {P['accent']}; border-color: {P['accent']}; color: {P['on_accent']}; }}
QPushButton#primary:hover {{ background: {P['accent_hover']}; }}
#dlgHead, #dlgBody, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {P['bg']}; }}
#dlgFoot {{ background: {P['chrome']}; border-top: 1px solid {P['border']}; }}
#dlgTitle {{ font-size: 16pt; font-weight: 700; }}
#sectionTitle {{ color: {P['muted']}; font-size: 8pt; font-weight: 700; padding: 8px 4px 0 4px; }}
#card {{ background: {P['surface']}; border: 1px solid {P['border']}; border-radius: 12px; }}
#card QWidget {{ background: transparent; }}
#card QComboBox, #card QSpinBox, #card QFontComboBox {{ background: {P['input']}; }}
#rowLine {{ background: {P['border']}; margin: 0 16px; }}
#rowTitle {{ font-weight: 600; }}
QMessageBox {{ background: {P['bg']}; }}
QMessageBox QLabel {{ color: {P['fg']}; }}
"""


def qt_palette(P):
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: P["bg"], QPalette.ColorRole.WindowText: P["fg"],
        QPalette.ColorRole.Base: P["input"], QPalette.ColorRole.AlternateBase: P["surface"],
        QPalette.ColorRole.Text: P["fg"], QPalette.ColorRole.Button: P["surface"],
        QPalette.ColorRole.ButtonText: P["fg"], QPalette.ColorRole.Highlight: P["accent"],
        QPalette.ColorRole.HighlightedText: P["on_accent"], QPalette.ColorRole.ToolTipBase: P["surface"],
        QPalette.ColorRole.ToolTipText: P["fg"], QPalette.ColorRole.PlaceholderText: P["muted"],
        QPalette.ColorRole.Link: P["link"],
    }
    for role, col in roles.items():
        pal.setColor(role, QColor(col))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(P["muted"]))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(P["muted"]))
    return pal


# --------------------------------------------------------------------------------------
# File helpers
# --------------------------------------------------------------------------------------

def read_text_file(path):
    data = Path(path).read_bytes()
    bom = data.startswith(b"\xef\xbb\xbf")
    text = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    nl = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n").replace("\r", "\n"), nl, bom


def is_md_path(p):
    return Path(p).suffix.lower() in MD_EXTS


# --------------------------------------------------------------------------------------
# Windows integration: install / portable, Windows "Apps" entry, default .md app
# --------------------------------------------------------------------------------------

IS_WIN = sys.platform == "win32"
PROGID = "MDReader.md"
EXE_NAME = APP_NAME + ".exe"
ASSOC_EXTS = (".md", ".markdown")
REG_APP_KEY = r"Software\MD Reader"
UNINSTALL_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\MDReader"
APP_PATHS_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\App Paths\MD Reader.exe"
CLASSES = r"Software\Classes"

if IS_WIN:
    import winreg
    import ctypes
    from ctypes import wintypes
    _k32 = ctypes.windll.kernel32
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]

DETACHED = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
NO_WINDOW = 0x08000000


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def same_path(a, b):
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def install_dir_for(scope):
    if scope == "machine":
        base = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files"
    else:
        base = os.path.join(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")), "Programs")
    return Path(base) / APP_NAME


def install_scope():
    """'machine' / 'user' when this exe is the installed copy, else None (portable or script)."""
    if not (IS_WIN and is_frozen()):
        return None
    for sc in ("machine", "user"):
        if same_path(app_dir(), install_dir_for(sc)):
            return sc
    return None


def existing_install():
    if not IS_WIN:
        return None
    for sc in ("user", "machine"):
        if (install_dir_for(sc) / EXE_NAME).is_file():
            return sc
    return None


def appdata_dir():
    return Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def open_command(exe_path=None):
    if exe_path:
        return f'"{exe_path}"'
    if is_frozen():
        return f'"{sys.executable}"'
    pyw = Path(sys.executable).with_name("pythonw.exe")
    interp = pyw if pyw.is_file() else Path(sys.executable)
    return f'"{interp}" "{Path(__file__).resolve()}"'


def icon_ref(exe_path=None):
    if exe_path:
        return f'"{exe_path}",0'
    if is_frozen():
        return f'"{sys.executable}",0'
    ico = app_dir() / "app_icon.ico"
    return f'"{ico}"' if ico.is_file() else f'"{sys.executable}",0'


def known_folder(csidl):
    buf = ctypes.create_unicode_buffer(520)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return Path(buf.value)


CSIDL_DESKTOP, CSIDL_PROGRAMS, CSIDL_COMMON_PROGRAMS = 0x10, 0x02, 0x17


def start_menu_dir(scope):
    return known_folder(CSIDL_COMMON_PROGRAMS if scope == "machine" else CSIDL_PROGRAMS)


def _hk(scope):
    return winreg.HKEY_LOCAL_MACHINE if scope == "machine" else winreg.HKEY_CURRENT_USER


def reg_set(root, key, name, value, kind=None):
    if kind is None:
        kind = winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ
    with winreg.CreateKeyEx(root, key, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, name, 0, kind, value)


def reg_get(root, key, name=""):
    try:
        with winreg.OpenKey(root, key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def reg_del_value(root, key, name):
    try:
        with winreg.OpenKey(root, key, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def reg_del_tree(root, key):
    try:
        with winreg.OpenKey(root, key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            subs = []
            i = 0
            while True:
                try:
                    subs.append(winreg.EnumKey(k, i))
                    i += 1
                except OSError:
                    break
        for s in subs:
            reg_del_tree(root, key + "\\" + s)
        winreg.DeleteKeyEx(root, key, winreg.KEY_WOW64_64KEY, 0)
    except OSError:
        pass


def shell_notify():
    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except Exception:
        pass


def register_app(scope, exe_path=None):
    """Registers the 'Markdown document' file type and the app's capabilities (Open with, Default apps)."""
    root = _hk(scope)
    cmd = open_command(exe_path)
    icon = icon_ref(exe_path)
    reg_set(root, rf"{CLASSES}\{PROGID}", "", "Markdown document")
    reg_set(root, rf"{CLASSES}\{PROGID}", "FriendlyTypeName", "Markdown document")
    reg_set(root, rf"{CLASSES}\{PROGID}\DefaultIcon", "", icon)
    reg_set(root, rf"{CLASSES}\{PROGID}\shell\open\command", "", f'{cmd} "%1"')
    for ext in ASSOC_EXTS:
        reg_set(root, rf"{CLASSES}\{ext}\OpenWithProgids", PROGID, b"", winreg.REG_NONE)
    if exe_path or is_frozen():
        exe = Path(exe_path or sys.executable).name
        reg_set(root, rf"{CLASSES}\Applications\{exe}", "FriendlyAppName", APP_NAME)
        reg_set(root, rf"{CLASSES}\Applications\{exe}\shell\open\command", "", f'{cmd} "%1"')
        for ext in ASSOC_EXTS:
            reg_set(root, rf"{CLASSES}\Applications\{exe}\SupportedTypes", ext, "")
    cap = REG_APP_KEY + r"\Capabilities"
    reg_set(root, cap, "ApplicationName", APP_NAME)
    reg_set(root, cap, "ApplicationDescription", "Read and edit Markdown files.")
    reg_set(root, cap, "ApplicationIcon", icon)
    for ext in ASSOC_EXTS:
        reg_set(root, cap + r"\FileAssociations", ext, PROGID)
    reg_set(root, r"Software\RegisteredApplications", APP_NAME, cap)


def register_uninstall(scope, dest):
    root = _hk(scope)
    exe = dest / EXE_NAME
    try:
        size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file()) // 1024
    except OSError:
        size = 0
    k = UNINSTALL_SUBKEY
    reg_set(root, k, "DisplayName", APP_NAME)
    reg_set(root, k, "DisplayVersion", APP_VERSION)
    reg_set(root, k, "Publisher", APP_NAME)
    reg_set(root, k, "DisplayIcon", f'"{exe}",0')
    reg_set(root, k, "InstallLocation", str(dest))
    reg_set(root, k, "UninstallString", f'"{exe}" --uninstall')
    reg_set(root, k, "InstallDate", time.strftime("%Y%m%d"))
    reg_set(root, k, "EstimatedSize", int(size))
    reg_set(root, k, "NoModify", 1)
    reg_set(root, k, "NoRepair", 1)
    reg_set(root, APP_PATHS_SUBKEY, "", str(exe))
    reg_set(root, APP_PATHS_SUBKEY, "Path", str(dest))


def unregister(scope):
    root = _hk(scope)
    reg_del_tree(root, UNINSTALL_SUBKEY)
    reg_del_tree(root, APP_PATHS_SUBKEY)
    reg_del_tree(root, rf"{CLASSES}\{PROGID}")
    for ext in ASSOC_EXTS:
        reg_del_value(root, rf"{CLASSES}\{ext}\OpenWithProgids", PROGID)
        if reg_get(root, rf"{CLASSES}\{ext}") == PROGID:
            reg_del_value(root, rf"{CLASSES}\{ext}", "")
    reg_del_tree(root, rf"{CLASSES}\Applications\{EXE_NAME}")
    reg_del_tree(root, REG_APP_KEY)
    reg_del_value(root, r"Software\RegisteredApplications", APP_NAME)


def user_choice(ext=".md"):
    return reg_get(winreg.HKEY_CURRENT_USER,
                   rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{ext}\UserChoice", "ProgId")


def is_default():
    if not IS_WIN:
        return False
    uc = user_choice()
    if uc:
        return uc == PROGID
    try:
        return winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, ".md") == PROGID
    except OSError:
        return False


def make_default():
    """Points .md / .markdown at this copy. Returns True when done, False when Windows
    still has another app chosen by the user (Windows then needs one confirmation click)."""
    register_app("user")
    for ext in ASSOC_EXTS:
        reg_set(winreg.HKEY_CURRENT_USER, rf"{CLASSES}\{ext}", "", PROGID)
    shell_notify()
    return is_default()


def confirm_default_with_windows(hwnd=0):
    """Shows Windows' own 'How do you want to open .md files?' picker."""
    class OPENASINFO(ctypes.Structure):
        _fields_ = [("pcszFile", wintypes.LPCWSTR), ("pcszClass", wintypes.LPCWSTR),
                    ("oaifInFlags", ctypes.c_int)]
    tmp = Path(tempfile.gettempdir()) / "Markdown file.md"
    if not tmp.exists():
        tmp.write_text("# Markdown file\n", encoding="utf-8")
    info = OPENASINFO(str(tmp), None, 0x1 | 0x2 | 0x20)  # ALLOW_REGISTRATION | REGISTER_EXT | FORCE_REGISTRATION
    try:
        ctypes.windll.shell32.SHOpenWithDialog(wintypes.HWND(hwnd), ctypes.byref(info))
    except Exception:
        pass
    shell_notify()
    return is_default()


def pids_for_exe(exe, exclude=()):
    out = []
    if not IS_WIN:
        return out
    arr = (wintypes.DWORD * 8192)()
    needed = wintypes.DWORD()
    if not ctypes.windll.psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed)):
        return out
    skip = {0, os.getpid(), *exclude}
    for pid in arr[: needed.value // 4]:
        if pid in skip:
            continue
        h = _k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) and same_path(buf.value, exe):
                out.append(int(pid))
        finally:
            _k32.CloseHandle(h)
    return out


def terminate_pid(pid):
    h = _k32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
    if h:
        _k32.TerminateProcess(h, 0)
        _k32.CloseHandle(h)


def _psq(s):
    return str(s).replace("'", "''")


def run_powershell(script, wait=True):
    args = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden", "-Command", script]
    if wait:
        subprocess.run(args, creationflags=NO_WINDOW, timeout=30, capture_output=True)
    else:
        subprocess.Popen(args, creationflags=DETACHED, cwd=tempfile.gettempdir(), close_fds=True)


def make_shortcut(lnk, target, workdir):
    try:
        lnk.parent.mkdir(parents=True, exist_ok=True)
        run_powershell(f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{_psq(lnk)}');"
                       f"$s.TargetPath='{_psq(target)}';$s.WorkingDirectory='{_psq(workdir)}';"
                       f"$s.IconLocation='{_psq(target)},0';$s.Description='{APP_NAME}';$s.Save()")
    except Exception:
        pass


def run_elevated(args):
    """Runs this exe again as administrator (UAC prompt) and waits. Returns its exit code,
    or None when the UAC prompt was cancelled."""
    class SEI(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    sei = SEI()
    sei.cbSize = ctypes.sizeof(SEI)
    sei.fMask = 0x40 | 0x100  # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    sei.lpVerb = "runas"
    sei.lpFile = sys.executable
    sei.lpParameters = " ".join(f'"{a}"' for a in args)
    sei.lpDirectory = tempfile.gettempdir()
    sei.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)) or not sei.hProcess:
        return None
    app = QApplication.instance()
    while _k32.WaitForSingleObject(sei.hProcess, 100) == 0x102:  # WAIT_TIMEOUT
        if app:
            app.processEvents()
    code = wintypes.DWORD()
    _k32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    _k32.CloseHandle(sei.hProcess)
    return code.value


def do_install(scope):
    """Copies this app folder to the install folder and registers it. Returns an error text or ''."""
    src, dest = app_dir(), install_dir_for(scope)
    if same_path(src, dest):
        return ""
    exe = dest / EXE_NAME
    others = pids_for_exe(exe)
    for pid in others:
        terminate_pid(pid)
    if others:
        time.sleep(0.5)
    last = None
    for _ in range(10):
        try:
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns("settings.json", "__pycache__"))
            last = None
            break
        except OSError as exc:
            last = exc
            time.sleep(0.4)
    if last is not None:
        return f"Could not copy {APP_NAME} to:\n{dest}\n\n{last}"
    try:
        register_app(scope, exe)
        register_uninstall(scope, dest)
    except OSError as exc:
        return f"Could not register {APP_NAME} with Windows:\n{exc}"
    make_shortcut(start_menu_dir(scope) / f"{APP_NAME}.lnk", exe, dest)
    shell_notify()
    return ""


def do_uninstall(scope, wait_pids=()):
    """Removes the registration, Start menu shortcut and (after the app has closed) the folder."""
    dest = install_dir_for(scope)
    unregister(scope)
    try:
        (start_menu_dir(scope) / f"{APP_NAME}.lnk").unlink()
    except OSError:
        pass
    keep = set(wait_pids) | {os.getpid()}
    for pid in pids_for_exe(dest / EXE_NAME, exclude=keep):
        terminate_pid(pid)
    ids = ",".join(str(p) for p in sorted(keep))
    run_powershell(f"Wait-Process -Id {ids} -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 800;"
                   f"Remove-Item -LiteralPath '{_psq(dest)}' -Recurse -Force -ErrorAction SilentlyContinue",
                   wait=False)
    shell_notify()


# ---- one window: a second launch hands its files to the running window

def instance_name(folder=None):
    import hashlib
    import getpass
    key = os.path.normcase(os.path.abspath(str(folder or app_dir()))) + "|" + getpass.getuser()
    return "MDReader-" + hashlib.md5(key.encode("utf-8")).hexdigest()[:12]


def send_to_running(msg, name, timeout=500):
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(timeout):
        return False
    if IS_WIN:
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except Exception:
            pass
    sock.write((json.dumps(msg) + "\n").encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1500)
    sock.disconnectFromServer()
    return True


def ask_installed_copy_to_quit(dest, timeout=12.0):
    """Politely closes a running installed copy (it may ask to save), so it can be replaced/removed."""
    exe = dest / EXE_NAME
    if not pids_for_exe(exe):
        return
    send_to_running({"quit": True}, instance_name(dest))
    end = time.time() + timeout
    app = QApplication.instance()
    while time.time() < end and pids_for_exe(exe):
        if app:
            app.processEvents()
        time.sleep(0.1)


SHIELD_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<path d="M12 1.6 3.6 4.7V11H12Z" fill="#2f6fde"/><path d="M12 1.6 20.4 4.7V11H12Z" fill="#f2b705"/>
<path d="M3.6 11c0 5.3 3.5 9.7 8.4 11.4V11Z" fill="#f2b705"/><path d="M20.4 11c0 5.3-3.5 9.7-8.4 11.4V11Z" fill="#2f6fde"/>
<path d="M12 1.6 3.6 4.7V11c0 5.3 3.5 9.7 8.4 11.4 4.9-1.7 8.4-6.1 8.4-11.4V4.7Z" fill="none" stroke="#1d3f86" stroke-width=".9"/>
</svg>"""


def shield_icon():
    """The Windows UAC shield (the same one installers show)."""
    if IS_WIN:
        try:
            ic = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_VistaShield)
            if not ic.isNull() and ic.availableSizes():
                return ic
        except Exception:
            pass
        try:
            class SHSTOCKICONINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("hIcon", wintypes.HICON), ("iSysImageIndex", ctypes.c_int),
                            ("iIcon", ctypes.c_int), ("szPath", wintypes.WCHAR * 260)]
            info = SHSTOCKICONINFO()
            info.cbSize = ctypes.sizeof(info)
            if ctypes.windll.shell32.SHGetStockIconInfo(77, 0x100, ctypes.byref(info)) == 0 and info.hIcon:
                img = QImage.fromHICON(int(info.hIcon))
                ctypes.windll.user32.DestroyIcon(info.hIcon)
                if not img.isNull():
                    return QIcon(QPixmap.fromImage(img))
        except Exception:
            pass
    ic = QIcon()
    for s in (16, 20, 24, 32):
        ic.addPixmap(svg_pixmap(SHIELD_SVG, s))
    return ic


class HoverButton(QPushButton):
    hovered = Signal(bool)

    def enterEvent(self, e):
        self.hovered.emit(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.hovered.emit(False)
        super().leaveEvent(e)


class OptionCard(ClickFrame):
    def __init__(self, icon, title, desc):
        super().__init__(objectName="optCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)
        ic = QLabel()
        ic.setPixmap(icon.pixmap(QSize(26, 26)))
        ic.setFixedSize(30, 30)
        txt = QVBoxLayout()
        txt.setSpacing(1)
        t = QLabel(title, objectName="rowTitle")
        d = QLabel(desc, objectName="muted")
        d.setWordWrap(True)
        txt.addWidget(t)
        txt.addWidget(d)
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(txt, 1)
        self.dot = QLabel()
        self.dot.setFixedSize(18, 18)
        lay.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        for w in (ic, t, d, self.dot):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_selected(self, on, P):
        self.setProperty("selected", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        col = P["accent"] if on else P["border"]
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 18"><circle cx="9" cy="9" r="7.5" '
               f'fill="none" stroke="{col}" stroke-width="1.6"/>' +
               (f'<circle cx="9" cy="9" r="4" fill="{col}"/>' if on else "") + "</svg>")
        self.dot.setPixmap(svg_pixmap(svg, 18))


class InstallDialog(QDialog):
    """The Install / Portable question (same idea as HK-Master)."""

    def __init__(self, P, existing=None, from_settings=False, parent=None):
        super().__init__(parent)
        self.P = P
        self.choice = None          # "install" | "portable" | None (closed)
        self.scope = existing or "user"
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setFixedWidth(500)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 24, 26, 22)
        lay.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(svg_pixmap(APP_ICON_SVG, 48))
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        ht = QVBoxLayout()
        ht.setSpacing(3)
        title = QLabel(f"Update the installed {APP_NAME}?" if existing else f"Install {APP_NAME}?",
                       objectName="dlgTitle")
        sub = QLabel("Choose who can use it. You can uninstall it any time from Settings "
                     "or from Windows Settings > Apps.", objectName="muted")
        sub.setWordWrap(True)
        ht.addWidget(title)
        ht.addWidget(sub)
        head.addLayout(ht, 1)
        lay.addLayout(head)

        self.card_me = OptionCard(make_icon("user", P["icon"], 26), "Just for me",
                                  "Installs in your user folder.")
        self.card_all = OptionCard(shield_icon(), "All users",
                                   "Installs in Program Files for everyone on this PC.")
        self.card_me.clicked.connect(lambda: self._select("user"))
        self.card_all.clicked.connect(lambda: self._select("machine"))
        lay.addWidget(self.card_me)
        lay.addWidget(self.card_all)

        opts = QFrame(objectName="card")
        ol = QVBoxLayout(opts)
        ol.setContentsMargins(14, 6, 14, 6)
        ol.setSpacing(0)
        self.sw_default, self.lbl_default = self._switch_row(
            ol, "Set as default .md reader / editor", is_default() if existing else True)
        self.sw_desktop, self.lbl_desktop = self._switch_row(
            ol, "Add a desktop shortcut",
            (known_folder(CSIDL_DESKTOP) / f"{APP_NAME}.lnk").exists() if (existing and IS_WIN) else True)
        lay.addWidget(opts)

        note = QLabel("Not now: keep using this portable copy." if from_settings else
                      "Portable: run this copy without installing.", objectName="muted")
        lay.addWidget(note)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_portable = HoverButton("Not now" if from_settings else "Portable")
        self.btn_install = QPushButton("Update" if existing else "Install", objectName="primary")
        self.btn_install.setDefault(True)
        self.btn_install.setIconSize(QSize(16, 16))
        btns.addWidget(self.btn_portable)
        btns.addWidget(self.btn_install)
        lay.addLayout(btns)

        self.btn_install.clicked.connect(self._install)
        self.btn_portable.clicked.connect(self._portable)
        self.btn_portable.hovered.connect(self._portable_hover)
        self._saved = None
        self._select(self.scope)

    def _switch_row(self, layout, text, on):
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 8, 0, 8)
        lbl = QLabel(text, objectName="rowTitle")
        sw = ToggleSwitch()
        sw.colors = {"off": self.P["switch_off"], "on": self.P["accent"], "knob": "#ffffff"}
        sw.set_now(bool(on))
        rl.addWidget(lbl, 1)
        rl.addWidget(sw)
        layout.addWidget(row)
        return sw, lbl

    def _select(self, scope):
        self.scope = scope
        self.card_me.set_selected(scope == "user", self.P)
        self.card_all.set_selected(scope == "machine", self.P)
        need_admin = scope == "machine" and not (IS_WIN and is_admin())
        self.btn_install.setIcon(shield_icon() if need_admin else QIcon())

    def _portable_hover(self, over):
        # a portable copy is neither installed nor the default app: show it while hovering
        if over:
            self._saved = (self.sw_default.isChecked(), self.sw_desktop.isChecked())
            for sw, lbl in ((self.sw_default, self.lbl_default), (self.sw_desktop, self.lbl_desktop)):
                sw.set_now(False)
                sw.setEnabled(False)
                lbl.setEnabled(False)
        elif self._saved is not None:
            for sw, lbl, val in ((self.sw_default, self.lbl_default, self._saved[0]),
                                 (self.sw_desktop, self.lbl_desktop, self._saved[1])):
                sw.setEnabled(True)
                lbl.setEnabled(True)
                sw.set_now(val)
            self._saved = None

    def _install(self):
        self.choice = "install"
        self.make_default = self.sw_default.isChecked()
        self.desktop = self.sw_desktop.isChecked()
        self.accept()

    def _portable(self):
        self.choice = "portable"
        self.accept()

    def showEvent(self, e):
        super().showEvent(e)
        style_titlebar(self, self.P)


def run_install(parent, scope, make_def, desktop, settings=None):
    """Installs (or updates) from this portable exe, then starts the installed copy.
    Returns True when the installed copy was started (the caller should exit)."""
    dest = install_dir_for(scope)
    exe = dest / EXE_NAME
    ask_installed_copy_to_quit(dest)
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        if scope == "machine" and not is_admin():
            rc = run_elevated(["--do-install", "machine"])
            if rc is None:
                return False            # UAC prompt cancelled
            err = "" if rc == 0 else "__shown__"
        else:
            err = do_install(scope)
    finally:
        QApplication.restoreOverrideCursor()
    if err:
        if err != "__shown__":
            QMessageBox.critical(parent, APP_NAME, err)
        return False
    # carry the portable settings over the first time
    try:
        if settings is not None:
            settings.save()
        src = app_dir() / "settings.json"
        dst = appdata_dir() / "settings.json"
        if src.is_file() and src.stat().st_size > 2 and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    except OSError:
        pass
    if desktop:
        make_shortcut(known_folder(CSIDL_DESKTOP) / f"{APP_NAME}.lnk", exe, dest)
    subprocess.Popen([str(exe)] + (["--make-default"] if make_def else []), cwd=str(dest), close_fds=True)
    return True


def uninstall_flow(parent, from_windows=False):
    """Uninstalls the installed copy this exe belongs to. Returns True when removed."""
    scope = install_scope()
    if not scope:
        QMessageBox.information(parent, APP_NAME, "This copy of MD Reader isn't installed.")
        return False
    if not from_windows:
        r = QMessageBox.question(parent, APP_NAME, f"Uninstall {APP_NAME}?")
        if r != QMessageBox.StandardButton.Yes:
            return False
    wipe = QMessageBox.question(parent, APP_NAME, "Also delete your settings?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
    dest = install_dir_for(scope)
    if from_windows:
        ask_installed_copy_to_quit(dest)
    cmd = reg_get(winreg.HKEY_CURRENT_USER, rf"{CLASSES}\{PROGID}\shell\open\command") or ""
    if str(dest).lower() in cmd.lower():
        unregister("user")      # the per-user "default app" entries pointed at this copy
    try:
        (known_folder(CSIDL_DESKTOP) / f"{APP_NAME}.lnk").unlink()
    except OSError:
        pass
    if scope == "machine" and not is_admin():
        rc = run_elevated(["--uninstall-elevated", str(os.getpid())])
        if rc is None:
            return False
    else:
        do_uninstall(scope)
    if wipe:
        shutil.rmtree(appdata_dir(), ignore_errors=True)
    shell_notify()
    QMessageBox.information(parent, APP_NAME, f"{APP_NAME} was uninstalled.")
    return True


# --------------------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------------------

SHORTCUTS_HELP = [
    ("Ctrl+O", "Open files"), ("Ctrl+T / Ctrl+N", "New tab"), ("Ctrl+W", "Close tab"),
    ("Ctrl+Tab / Ctrl+Shift+Tab", "Next / previous tab"), ("Ctrl+S", "Save"),
    ("Ctrl+Shift+S", "Save as"), ("Ctrl+E", "Turn editing on / off"),
    ("Ctrl+1 / Ctrl+2", "Preview / Raw"), ("Ctrl+F", "Find"),
    ("Ctrl+Shift+D", "Dark / light theme"), ("Ctrl+,", "Settings"),
    ("Ctrl + / - / 0", "Zoom in / out / reset"), ("F5", "Reload from disk"),
]


class TabClose(QWidget):
    """Close button for a file tab, with room around it. Shows a dot while the file has unsaved changes."""
    clicked = Signal()

    def __init__(self, P):
        super().__init__()
        self.setFixedSize(28, 22)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 6, 0)
        lay.setSpacing(0)
        self.btn = QToolButton(objectName="tabClose")
        self.btn.setFixedSize(18, 18)
        self.btn.setIconSize(QSize(12, 12))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setToolTip("Close  (Ctrl+W)")
        self.btn.clicked.connect(self.clicked.emit)
        self.btn.installEventFilter(self)
        lay.addWidget(self.btn)
        self.modified = False
        self.hover = False
        self.set_palette(P)

    def set_palette(self, P):
        self._x = make_icon("x", P["muted"], 12)
        self._dot = QIcon(svg_pixmap('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12">'
                                     f'<circle cx="6" cy="6" r="3.4" fill="{P["accent"]}"/></svg>', 12))
        self._refresh()

    def set_modified(self, m):
        self.modified = bool(m)
        self.btn.setToolTip("Unsaved changes. Close  (Ctrl+W)" if m else "Close  (Ctrl+W)")
        self._refresh()

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Enter:
            self.hover = True
            self._refresh()
        elif ev.type() == QEvent.Type.Leave:
            self.hover = False
            self._refresh()
        return super().eventFilter(obj, ev)

    def _refresh(self):
        self.btn.setIcon(self._dot if self.modified and not self.hover else self._x)


class Doc:
    """One open file (one tab). Each has its own text document, so undo history is per tab."""

    def __init__(self, P):
        self.document = QTextDocument()
        self.document.setDocumentLayout(QPlainTextDocumentLayout(self.document))
        self.document.setDocumentMargin(22)
        self.highlighter = MdHighlighter(self.document)
        self.highlighter.set_palette(P)
        self.path = None
        self.newline = "\n"
        self.bom = False
        self.cursor_pos = 0
        self.editor_scroll = 0
        self.preview_scroll = 0.0
        self.document.setModified(False)

    def title(self):
        return self.path.name if self.path else "Untitled"

    def is_pristine(self):
        return self.path is None and not self.document.isModified() and self.document.isEmpty()


class MainWindow(QMainWindow):
    def __init__(self, settings, initial=None, make_default_on_start=False):
        super().__init__()
        self.s = settings
        self.renderer = Renderer()
        self.pyg_css = pygments_css()
        self.docs = []
        self.cur = None
        self.mode = "preview" if self.s.get("last_tab") != "raw" else "raw"
        self.edit = bool(self.s["edit_by_default"])
        self.P = make_palette(resolve_theme(self.s), self.s["accent"])
        self._shell_ready = False
        self._shell_base = None
        self._pending_render = False
        self._restore_y = None
        self._preview_dirty = True
        self._ignore_disk_until = 0.0
        self._loading = False
        self._zoom = 1.0
        self._icon_buttons = []
        self._drop_targets = []
        self._skip_close = False
        self._ipc_buf = {}
        self.home_active = False
        self._suppress_switch = False

        self.setWindowIcon(app_icon())
        self.resize(1240, 820)
        self.setMinimumSize(760, 480)
        self.setAcceptDrops(True)

        self.bridge = Bridge()
        self.bridge.copied.connect(self._on_copied)
        self.bridge.actionRequested.connect(self._on_page_action)
        self.bridge.scrolled.connect(self._on_preview_scrolled)

        self._build_ui()
        self._build_actions()
        self._install_drop_filters()

        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._on_disk_changed)
        self.render_timer = QTimer(self, singleShot=True, interval=180)
        self.render_timer.timeout.connect(self._render_now)
        self.stats_timer = QTimer(self, singleShot=True, interval=300)
        self.stats_timer.timeout.connect(self._update_stats)
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme)
        except Exception:
            pass

        self.server = QLocalServer(self)
        QLocalServer.removeServer(instance_name())
        self.server.listen(instance_name())
        self.server.newConnection.connect(self._on_ipc)

        self.apply_theme()
        self._restore_geometry()
        self._arrange()
        self._open_startup_files(initial or [])
        if make_default_on_start:
            QTimer.singleShot(700, self.make_default_flow)

    # ---------------------------------------------------------------- current-doc shortcuts
    @property
    def path(self):
        return self.cur.path if self.cur else None

    def _tool(self, icon, tip, slot=None):
        b = QToolButton(objectName="tb")
        b.setToolTip(tip)
        b.setIconSize(QSize(18, 18))
        b.setFixedSize(34, 34)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if slot:
            b.clicked.connect(slot)
        self._icon_buttons.append((b, icon))
        return b

    @staticmethod
    def _vsep(h=20):
        s = QFrame(objectName="sep")
        s.setFixedSize(1, h)
        return s

    def _build_ui(self):
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ---- top bar:  brand | File  open  save   ·   Preview / Raw   ·   Edit | find theme settings
        self.topbar = QFrame(objectName="topbar")
        self.topbar.setFixedHeight(54)
        tb = QHBoxLayout(self.topbar)
        tb.setContentsMargins(16, 0, 14, 0)
        tb.setSpacing(0)

        left = QWidget()
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)
        self.logo = QLabel()
        self.logo.setPixmap(svg_pixmap(APP_ICON_SVG, 24))
        self.logo.setFixedSize(24, 24)
        brand = QLabel(APP_NAME, objectName="brand")
        self.btn_file = QToolButton(objectName="menuBtn")
        self.btn_file.setText("File")
        self.btn_file.setToolTip("File menu")
        self.btn_file.setFixedHeight(34)
        self.btn_file.setIconSize(QSize(14, 14))
        self.btn_file.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_file.setLayoutDirection(Qt.LayoutDirection.RightToLeft)   # chevron after the text
        self.btn_file.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_file.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open = self._tool("folder-open", "Open  (Ctrl+O)", lambda: self.open_dialog())
        self.btn_save = self._tool("save", "Save  (Ctrl+S)", lambda: self.save())
        ll.addWidget(self.logo)
        ll.addSpacing(6)
        ll.addWidget(brand)
        ll.addSpacing(14)
        ll.addWidget(self._vsep(), 0, Qt.AlignmentFlag.AlignVCenter)
        ll.addSpacing(10)
        ll.addWidget(self.btn_file)
        ll.addWidget(self.btn_open)
        ll.addWidget(self.btn_save)
        ll.addStretch(1)

        self.segment = QFrame(objectName="segment")
        self.segment.setFixedHeight(36)
        sl = QHBoxLayout(self.segment)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.seg_preview = QPushButton(" Preview", objectName="segbtn")
        self.seg_raw = QPushButton(" Raw", objectName="segbtn")
        self.seg_group = QButtonGroup(self)
        for b, mode, tip in ((self.seg_preview, "preview", "Preview  (Ctrl+1)"),
                             (self.seg_raw, "raw", "Raw Markdown  (Ctrl+2)")):
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIconSize(QSize(16, 16))
            b.setFixedHeight(30)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
            self.seg_group.addButton(b)
            sl.addWidget(b)

        right = QWidget()
        rl = QHBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        rl.addStretch(1)
        self.edit_pill = ClickFrame(objectName="editPill")
        self.edit_pill.setFixedHeight(36)
        self.edit_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_pill.setToolTip("Turn editing on / off  (Ctrl+E)")
        for w_ in (self.segment, self.edit_pill):       # keep their space when hidden at home
            sp_ = w_.sizePolicy(); sp_.setRetainSizeWhenHidden(True); w_.setSizePolicy(sp_)
        el = QHBoxLayout(self.edit_pill)
        el.setContentsMargins(12, 0, 8, 0)
        el.setSpacing(8)
        self.edit_icon = QLabel()
        self.edit_icon.setStyleSheet("background: transparent;")
        self.edit_label = QLabel("Edit", objectName="editLabel")
        self.edit_switch = ToggleSwitch()
        self.edit_switch.set_now(self.edit)
        self.edit_switch.toggled.connect(self.set_edit)
        self.edit_pill.clicked.connect(self.edit_switch.toggle)
        el.addWidget(self.edit_icon)
        el.addWidget(self.edit_label)
        el.addWidget(self.edit_switch)
        self.btn_find = self._tool("search", "Find  (Ctrl+F)", lambda: self.show_find())
        self.btn_theme = self._tool("moon", "Dark / light  (Ctrl+Shift+D)", lambda: self.toggle_theme())
        self.btn_settings = self._tool("settings", "Settings  (Ctrl+,)", lambda: self.open_settings())
        rl.addWidget(self.edit_pill)
        rl.addSpacing(10)
        rl.addWidget(self._vsep(), 0, Qt.AlignmentFlag.AlignVCenter)
        rl.addSpacing(10)
        for b in (self.btn_find, self.btn_theme, self.btn_settings):
            rl.addWidget(b)

        tb.addWidget(left, 1)
        tb.addWidget(self.segment, 0, Qt.AlignmentFlag.AlignVCenter)
        tb.addWidget(right, 1)
        v.addWidget(self.topbar)

        # ---- tab strip:  [Home] [file tabs…] [+]
        self.tabstrip = QFrame(objectName="tabstrip")
        self.tabstrip.setFixedHeight(40)
        tsl = QHBoxLayout(self.tabstrip)
        tsl.setContentsMargins(12, 0, 12, 0)
        tsl.setSpacing(4)
        self.btn_home = QToolButton(objectName="homeTab")
        self.btn_home.setCheckable(True)
        self.btn_home.setFixedSize(40, 32)
        self.btn_home.setIconSize(QSize(17, 17))
        self.btn_home.setToolTip("Home  (Alt+Home)")
        self.btn_home.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_home.clicked.connect(lambda: self.show_home())
        self.tabs = QTabBar(objectName="docTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(False)          # own close buttons (spacing + unsaved dot)
        self.tabs.setMovable(True)
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(self._switch_to)
        self.tabs.tabBarClicked.connect(self._on_tab_clicked)
        self.tabs.tabMoved.connect(self._on_tab_moved)
        self.tabs.tabBarDoubleClicked.connect(lambda i: self.new_doc() if i < 0 else None)
        self.tabs.installEventFilter(self)
        self.btn_newtab = self._tool("plus", "New tab  (Ctrl+T)", lambda: self.new_doc())
        self.btn_newtab.setFixedSize(30, 30)
        self.btn_newtab.setIconSize(QSize(16, 16))
        tsl.addWidget(self.btn_home, 0, Qt.AlignmentFlag.AlignBottom)
        tsl.addWidget(self._vsep(18), 0, Qt.AlignmentFlag.AlignVCenter)
        tsl.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignBottom)
        tsl.addWidget(self.btn_newtab, 0, Qt.AlignmentFlag.AlignVCenter)
        tsl.addStretch(1)
        v.addWidget(self.tabstrip)

        # ---- content
        self.stack = QStackedWidget()
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.setChildrenCollapsible(False)
        self.web = WebView()
        self.page = WebPage(self.web)
        self.web.setPage(self.page)
        st = self.page.settings()
        st.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        st.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        st.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject("bridge", self.bridge)
        self.page.setWebChannel(self.channel)
        self.page.loadFinished.connect(self._on_shell_loaded)
        self.page.linkClicked.connect(self._on_link)
        self.page.findTextFinished.connect(self._on_find_result)
        self.web.setMinimumWidth(260)
        self.splitter.addWidget(self.web)

        self.raw_page = QWidget()
        self.raw_layout = QVBoxLayout(self.raw_page)
        self.raw_layout.setContentsMargins(0, 0, 0, 0)
        self.editor = Editor()
        self.editor.setMinimumWidth(260)
        self._blank = QTextDocument(self)           # shown in the editor when no file is open
        self._blank.setDocumentLayout(QPlainTextDocumentLayout(self._blank))
        self.editor.setDocument(self._blank)
        self.raw_layout.addWidget(self.editor)
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.verticalScrollBar().valueChanged.connect(self._on_editor_scroll)
        self.editor.cursorPositionChanged.connect(self._update_cursor_pos)

        self.stack.addWidget(self.splitter)
        self.stack.addWidget(self.raw_page)
        v.addWidget(self.stack, 1)

        self.findbar = FindBar()
        self.findbar.hide()
        self.findbar.search.connect(self.do_find)
        self.findbar.closed.connect(self.hide_find)
        v.addWidget(self.findbar)
        self.setCentralWidget(central)

        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        self.setStatusBar(sb)
        self.st_path = QLabel("")
        self.st_msg = QLabel("")
        self.st_pos = QLabel("")
        self.st_stats = QLabel("")
        self.st_badge = QLabel("Read-only", objectName="badge")
        sb.addWidget(self.st_path, 1)
        sb.addPermanentWidget(self.st_msg)
        sb.addPermanentWidget(self.st_pos)
        sb.addPermanentWidget(self.st_stats)
        sb.addPermanentWidget(self.st_badge)
        self.msg_timer = QTimer(self, singleShot=True, interval=2500)
        self.msg_timer.timeout.connect(lambda: self.st_msg.setText(""))

    def _build_actions(self):
        def act(text, shortcuts, slot, icon=None):
            a = QAction(text, self)
            if shortcuts:
                if isinstance(shortcuts, str):
                    shortcuts = [shortcuts]
                a.setShortcuts([QKeySequence(x) for x in shortcuts])
                a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            a.triggered.connect(slot)
            a._icon_name = icon
            self.addAction(a)
            return a

        self.a_new = act("New document", ["Ctrl+T", "Ctrl+N"], lambda: self.new_doc(), "file-plus")
        self.a_open = act("Open…", "Ctrl+O", lambda: self.open_dialog(), "folder-open")
        self.a_save = act("Save", "Ctrl+S", lambda: self.save(), "save")
        self.a_saveas = act("Save as…", "Ctrl+Shift+S", lambda: self.save_as(), "save-as")
        self.a_reload = act("Reload from disk", "F5", lambda: self.reload_from_disk(), "refresh")
        self.a_html = act("Export as HTML…", None, lambda: self.export_html(), "download")
        self.a_pdf = act("Export as PDF…", None, lambda: self.export_pdf(), "printer")
        self.a_folder = act("Show in folder", None, lambda: self.open_folder(), "folder")
        self.a_close = act("Close tab", ["Ctrl+W", "Ctrl+F4"], lambda: self.close_tab(self.tabs.currentIndex()), "x")
        self.a_close_all = act("Close all tabs", "Ctrl+Shift+W", lambda: self.close_all_tabs(), None)
        self.a_home = act("Home", "Alt+Home", lambda: self.show_home(), "home")
        act("Edit", "Ctrl+E", lambda: self.edit_switch.toggle() if not self._at_home() else None)
        act("Preview", "Ctrl+1", lambda: self.set_mode("preview"))
        act("Raw", "Ctrl+2", lambda: self.set_mode("raw"))
        act("Next tab", ["Ctrl+Tab", "Ctrl+PgDown"], lambda: self._cycle_tab(1))
        act("Previous tab", ["Ctrl+Shift+Tab", "Ctrl+PgUp"], lambda: self._cycle_tab(-1))
        act("Find", "Ctrl+F", lambda: self.show_find())
        act("Theme", "Ctrl+Shift+D", lambda: self.toggle_theme())
        act("Settings", "Ctrl+,", lambda: self.open_settings())
        act("Zoom in", ["Ctrl+=", "Ctrl++"], lambda: self.zoom(1))
        act("Zoom out", "Ctrl+-", lambda: self.zoom(-1))
        act("Zoom reset", "Ctrl+0", lambda: self.zoom(0))
        act("Close find", "Esc", lambda: self.hide_find() if self.findbar.isVisible() else None)

        self.file_menu = QMenu(self)
        self.recent_menu = QMenu("Open recent", self)
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        self.file_menu.aboutToShow.connect(self._update_actions)
        for a in (self.a_new, self.a_open):
            self.file_menu.addAction(a)
        self.file_menu.addMenu(self.recent_menu)
        self.file_menu.addSeparator()
        for a in (self.a_save, self.a_saveas, self.a_reload):
            self.file_menu.addAction(a)
        self.file_menu.addSeparator()
        for a in (self.a_html, self.a_pdf, self.a_folder):
            self.file_menu.addAction(a)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.a_close)
        self.file_menu.addAction(self.a_close_all)
        self.btn_file.setMenu(self.file_menu)

    def _update_actions(self):
        has_doc = not self._at_home()
        has_path = has_doc and self.path is not None
        for a in (self.a_save, self.a_saveas, self.a_html, self.a_pdf):
            a.setEnabled(has_doc)
        for a in (self.a_reload, self.a_folder):
            a.setEnabled(has_path)
        self.a_close.setEnabled(bool(self.docs))
        self.a_close_all.setEnabled(bool(self.docs))
        self.btn_save.setEnabled(has_doc)

    def apply_theme(self):
        self.P = P = make_palette(resolve_theme(self.s), self.s["accent"])
        app = QApplication.instance()
        app.setPalette(qt_palette(P))
        app.setStyleSheet(build_qss(P))
        for b, name in self._icon_buttons:
            ic = QIcon()
            ic.addPixmap(svg_pixmap(svg_icon_markup(name, P["icon"]), 18), QIcon.Mode.Normal)
            ic.addPixmap(svg_pixmap(svg_icon_markup(name, P["scroll"]), 18), QIcon.Mode.Disabled)
            b.setIcon(ic)
        self.btn_theme.setIcon(make_icon("sun" if P["theme"] == "dark" else "moon", P["icon"]))
        self.btn_file.setIcon(make_icon("chevron-down", P["muted"]))
        self.btn_home.setIcon(make_icon("home", P["muted"], on_color=P["fg"]))
        for b, mode in ((self.seg_preview, "eye"), (self.seg_raw, "code")):
            ic = make_icon(mode, P["muted"], on_color=P["fg"])
            ic.addPixmap(svg_pixmap(svg_icon_markup(mode, P["scroll"]), 20), QIcon.Mode.Disabled, QIcon.State.Off)
            ic.addPixmap(svg_pixmap(svg_icon_markup(mode, P["scroll"]), 20), QIcon.Mode.Disabled, QIcon.State.On)
            b.setIcon(ic)
        for a in self.actions():
            name = getattr(a, "_icon_name", None)
            if name:
                a.setIcon(make_icon(name, P["icon"]))
        self.recent_menu.setIcon(make_icon("clock", P["icon"]))
        self.edit_switch.colors = {"off": P["switch_off"], "on": P["accent"], "knob": "#ffffff"}
        self.edit_switch.update()
        self._style_edit_pill()
        self.findbar.set_icons(P)
        for d in self.docs:
            d.highlighter.set_palette(P)
        for i in range(self.tabs.count()):
            w = self.tabs.tabButton(i, QTabBar.ButtonPosition.RightSide)
            if isinstance(w, TabClose):
                w.set_palette(P)
        self._apply_editor_prefs()
        self.page.setBackgroundColor(QColor(P["bg"]))
        if self._shell_ready:
            self._js(self._theme_js(P))
        style_titlebar(self, P)

    def _style_edit_pill(self):
        on = self.edit and not self._at_home()
        col = self.P["accent"] if on else (self.P["scroll"] if self._at_home() else self.P["muted"])
        self.edit_icon.setPixmap(svg_pixmap(svg_icon_markup("pencil", col), 15))
        for w, prop, val in ((self.edit_pill, "on", on), (self.st_badge, "editing", on)):
            w.setProperty(prop, "true" if val else "false")
            w.style().unpolish(w)
            w.style().polish(w)
        self.edit_label.style().unpolish(self.edit_label)
        self.edit_label.style().polish(self.edit_label)
        self.st_badge.setText("Editing" if on else "Read-only")

    # ---------------------------------------------------------------- home
    def _at_home(self):
        return self.home_active or self.cur is None

    def show_home(self):
        if self.cur is not None and not self.home_active and self.editor.document() is self.cur.document:
            self.cur.cursor_pos = self.editor.textCursor().position()
            self.cur.editor_scroll = self.editor.verticalScrollBar().value()
        self.home_active = True
        self._set_tabs_home_look(True)
        self._arrange()
        self._restore_y = 0.0
        self._preview_dirty = True
        if self._shell_base is None:
            self._load_shell(str(Path.home()))
        else:
            self._render_now()
        self._update_title()
        self._update_stats()

    def _set_tabs_home_look(self, home):
        self.btn_home.setChecked(home)
        self.tabs.setProperty("home", "true" if home else "false")
        self.tabs.style().unpolish(self.tabs)
        self.tabs.style().polish(self.tabs)
        self.tabs.update()

    def _home_html(self):
        ic_open = svg_icon_markup("folder-open", "currentColor", 2)
        ic_new = svg_icon_markup("file-plus", "currentColor", 2)
        ic_file = svg_icon_markup("file", "currentColor", 1.8)
        ic_restore = svg_icon_markup("refresh", "currentColor", 2)
        open_paths = {os.path.normcase(str(d.path)) for d in self.docs if d.path}
        session = [f for f in self.s.get("open_files") or [] if Path(f).is_file()
                   and os.path.normcase(f) not in open_paths]
        restore = ""
        if session and not self.docs:
            n = len(session)
            restore = (f'<button class="restore" data-action="restore">{ic_restore}'
                       f'<span>Continue where you left off</span><em>{n} file{"s" if n != 1 else ""}</em></button>')
        items = [p for p in self.s["recent"] if Path(p).is_file()][:8]
        rec = ""
        if items:
            rows = []
            for i, p in enumerate(items):
                badge = '<i>open</i>' if os.path.normcase(p) in open_paths else ""
                rows.append(f'<a href="#" data-action="recent:{i}"><span class="fi">{ic_file}</span>'
                            f'<span class="ft"><b>{htmlmod.escape(Path(p).name)}</b>'
                            f'<small>{htmlmod.escape(str(Path(p).parent))}</small></span>{badge}</a>')
            rec = f'<section class="recent"><h4>Recent files</h4>{"".join(rows)}</section>'
        return ('<div class="home">'
                f'<div class="hero"><div class="logo">{APP_ICON_SVG}</div><h1>{APP_NAME}</h1>'
                '<p>Read and edit Markdown files.</p></div>'
                f'<div class="actions"><button class="btn primary" data-action="open">{ic_open}Open file</button>'
                f'<button class="btn" data-action="new">{ic_new}New document</button></div>'
                f'{restore}{rec}'
                '<p class="hint">Drag .md files anywhere in this window to open them</p></div>')

    def _restore_session(self):
        files = [f for f in self.s.get("open_files") or [] if Path(f).is_file()]
        for f in files:
            self.open_file(f, activate=False, quiet=True)
        active = self.s.get("active_file")
        target = active if active and Path(active).is_file() else (files[-1] if files else None)
        if target:
            self.open_file(target, quiet=True)

    # ---------------------------------------------------------------- tabs
    def _add_doc(self, doc, activate=True):
        self.docs.append(doc)
        doc.document.modificationChanged.connect(lambda _=None, d=doc: self._on_doc_modified(d))
        self._suppress_switch = True
        i = self.tabs.addTab(doc.title())
        self._suppress_switch = False
        close = TabClose(self.P)
        close.clicked.connect(lambda c=close: self._close_from_button(c))
        self.tabs.setTabButton(i, QTabBar.ButtonPosition.RightSide, close)
        self._update_tab(doc)
        if activate:
            self._activate_tab(i)
        return doc

    def _activate_tab(self, i):
        if self.tabs.currentIndex() == i:
            self._switch_to(i, force=True)
        else:
            self.tabs.setCurrentIndex(i)

    def _close_from_button(self, btn):
        for i in range(self.tabs.count()):
            if self.tabs.tabButton(i, QTabBar.ButtonPosition.RightSide) is btn:
                self.close_tab(i)
                return

    def _update_tab(self, doc):
        if doc not in self.docs:
            return
        i = self.docs.index(doc)
        self.tabs.setTabText(i, doc.title())
        self.tabs.setTabToolTip(i, str(doc.path) if doc.path else "Not saved yet")
        w = self.tabs.tabButton(i, QTabBar.ButtonPosition.RightSide)
        if isinstance(w, TabClose):
            w.set_modified(doc.document.isModified())

    def _on_doc_modified(self, doc):
        self._update_tab(doc)
        if doc is self.cur:
            self._update_title()

    def _on_tab_moved(self, frm, to):
        d = self.docs.pop(frm)
        self.docs.insert(to, d)

    def _on_tab_clicked(self, i):
        if i >= 0 and self.home_active and i == self.tabs.currentIndex():
            self._switch_to(i, force=True)

    def _cycle_tab(self, step):
        n = self.tabs.count()
        if not n:
            return
        if self.home_active:
            self._activate_tab(0 if step > 0 else n - 1)
        elif n > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % n)

    def _switch_to(self, i, force=False):
        if self._suppress_switch or i < 0 or i >= len(self.docs):
            return
        new = self.docs[i]
        if self.home_active:
            self.home_active = False
            self._set_tabs_home_look(False)
            force = True
        elif new is self.cur and not force and self.editor.document() is new.document:
            return
        old = self.cur
        if old is not None and old is not new and old in self.docs and self.editor.document() is old.document:
            old.cursor_pos = self.editor.textCursor().position()
            old.editor_scroll = self.editor.verticalScrollBar().value()
        self.cur = new
        if self.editor.document() is not new.document:
            self._loading = True
            self.editor.setDocument(new.document)
            self._loading = False
            self._sync_doc_prefs()
            c = self.editor.textCursor()
            c.setPosition(min(new.cursor_pos, max(0, new.document.characterCount() - 1)))
            self.editor.setTextCursor(c)
            QTimer.singleShot(0, lambda d=new: self.editor.verticalScrollBar().setValue(d.editor_scroll)
                              if d is self.cur else None)
        self._restore_y = new.preview_scroll
        self._arrange()
        base = str(new.path.parent) if new.path else (self._shell_base or str(Path.home()))
        if base != self._shell_base:
            self._load_shell(base)
        else:
            self._preview_dirty = True
            if self._preview_visible():
                self._render_now()
        self._update_title()
        self._update_stats()
        self._update_cursor_pos()
        if self.findbar.isVisible() and self.findbar.edit.text():
            self.do_find(self.findbar.edit.text(), False)

    def close_tab(self, i):
        if i < 0 or i >= len(self.docs):
            return
        doc = self.docs[i]
        if doc.document.isModified():
            if not self.home_active:
                self._activate_tab(i)
            if not self.maybe_save(doc):
                return
        if doc.path and not any(d is not doc and d.path == doc.path for d in self.docs):
            self.watcher.removePath(str(doc.path))
        if self.editor.document() is doc.document:
            self._loading = True
            self.editor.setDocument(self._blank)     # never leave the editor on a document being dropped
            self._loading = False
        was_current = self.cur is doc
        self._suppress_switch = True
        self.docs.pop(i)
        self.tabs.removeTab(i)
        self._suppress_switch = False
        if not self.docs:
            self.cur = None
            self.show_home()                          # closing the last tab goes back home
        elif self.home_active:
            if was_current:
                self.cur = self.docs[max(0, self.tabs.currentIndex())]
            self._render_now()                        # refresh the "open" badges on home
        elif was_current:
            self._switch_to(self.tabs.currentIndex(), force=True)

    def close_all_tabs(self):
        if not self.maybe_save_all():
            return
        for d in self.docs:
            d.document.setModified(False)
        while self.docs:
            self.close_tab(len(self.docs) - 1)

    def _render_now(self):
        if not self._shell_ready:
            self._pending_render = True
            return
        self._pending_render = False
        if self._at_home():
            body = self._home_html()
        else:
            text = self.editor.toPlainText()
            body = self.renderer.render(text) if text.strip() else (
                '<div class="empty-doc"><p>This document is empty.</p>'
                '<p>Turn on <b>Edit</b> to start writing.</p></div>')
        js = f"document.body.classList.toggle('at-home',{'true' if self._at_home() else 'false'});"
        js += f"mdRender({json.dumps(body)},false);"
        if self._restore_y is not None:
            js += f"mdScrollToY({float(self._restore_y):.1f});"
            self._restore_y = None
        self._js(js)
        self._preview_dirty = False

    def _on_page_action(self, name):
        if name == "open":
            self.open_dialog()
        elif name == "new":
            self.new_doc()
        elif name == "restore":
            self._restore_session()
        elif name.startswith("recent:"):
            items = [p for p in self.s["recent"] if Path(p).is_file()]
            i = int(name.split(":", 1)[1])
            if i < len(items):
                self.open_file(items[i])

    def set_mode(self, mode):
        self.mode = mode
        self.s["last_tab"] = mode
        self._arrange()

    def set_edit(self, on):
        if self._at_home():
            self.edit_switch.set_now(self.edit)
            return
        self.edit = bool(on)
        if self.edit_switch.isChecked() != self.edit:
            self.edit_switch.set_now(self.edit)
        if self.edit and self.mode == "preview" and not self.s["split_when_editing"]:
            self.mode = "raw"
        self._style_edit_pill()
        self._arrange()

    def _arrange(self):
        home = self._at_home()
        # Preview/Raw and Edit only mean something for a document: hide them at home
        # (their space is kept, so nothing in the top bar jumps around)
        self.segment.setVisible(not home)
        self.edit_pill.setVisible(not home)
        self.tabs.setVisible(self.tabs.count() > 0)
        self.edit_switch.setEnabled(not home)
        self._style_edit_pill()
        self._update_actions()
        self.seg_preview.setChecked(self.mode == "preview")
        self.seg_raw.setChecked(self.mode == "raw")
        in_split = self.splitter.indexOf(self.editor) >= 0
        split = (not home) and self.mode == "preview" and self.edit and self.s["split_when_editing"]
        if split and not in_split:
            self.splitter.insertWidget(0, self.editor)
            sizes = self.s.get("splitter") or []
            if len(sizes) == 2 and all(isinstance(x, int) and x > 100 for x in sizes):
                self.splitter.setSizes(sizes)
            else:
                w = max(self.splitter.width(), 800)
                self.splitter.setSizes([w // 2, w - w // 2])
        elif not split and in_split:
            self.s["splitter"] = self.splitter.sizes()
            self.raw_layout.addWidget(self.editor)
        self.editor.show()
        self.stack.setCurrentIndex(0 if (home or self.mode == "preview") else 1)
        self.editor.setReadOnly(home or not self.edit)
        self.editor.viewport().setCursor(Qt.CursorShape.IBeamCursor if (self.edit and not home)
                                         else Qt.CursorShape.ArrowCursor)
        if not home and self.mode == "preview" and self._preview_dirty:
            self._render_now()
        if not home and self.edit and (self.mode == "raw" or split):
            self.editor.setFocus()
        elif home or self.mode == "preview":
            self.web.setFocus()
        self.st_pos.setVisible(not home and (self.mode == "raw" or split))
        self.st_badge.setVisible(not home)
        if self.findbar.isVisible() and self.findbar.edit.text():
            self.do_find(self.findbar.edit.text(), False)

    def _open_startup_files(self, files):
        if self.s.get("startup") == "last" and not files:
            self._restore_session()
        for f in files:
            self.open_file(f, quiet=True)
        if not self.docs or (not files and self.s.get("startup") != "last"):
            self.show_home()
        self._update_title()

    def new_doc(self):
        self._add_doc(Doc(self.P))
        if not self.edit:
            self.set_edit(True)

    def _update_title(self):
        portable = " (portable)" if (IS_WIN and is_frozen() and not install_scope()) else ""
        if self._at_home():
            self.setWindowTitle(f"{APP_NAME}{portable}")
            self.st_path.setText("Home")
            return
        doc = self.cur
        mod = doc.document.isModified()
        self.setWindowTitle(f"{'• ' if mod else ''}{doc.title()} — {APP_NAME}{portable}")
        self.st_path.setText(str(doc.path) if doc.path else "Not saved yet")

    def _update_stats(self):
        if self._at_home():
            n = len(self.docs)
            self.st_stats.setText(f"{n} open file{'s' if n != 1 else ''}" if n else "")
            return
        text = self.editor.toPlainText()
        words = len(re.findall(r"\S+", text))
        lines = text.count("\n") + 1 if text else 0
        mins = max(1, round(words / 220)) if words else 0
        self.st_stats.setText(f"{words:,} words  ·  {lines:,} lines  ·  {mins} min read")

    # ---------------------------------------------------------------- UI
    # ---------------------------------------------------------------- theme
    def _theme_js(self, P):
        return (f"mdSetTheme({json.dumps(P['theme'])},{json.dumps(css_vars(P, self.s))});"
                f"mdSetOptions({{cellCopy:{'true' if self.s['cell_copy'] else 'false'}}});")

    def _apply_editor_prefs(self):
        fam = self.s["editor_font"] or default_mono_family()
        f = QFont(fam)
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPointSizeF(float(self.s["editor_font_size"]) * self._zoom)
        self.editor.setFont(f)
        self.editor.setStyleSheet('QPlainTextEdit#editor {{ font-family: "{}"; font-size: {:.1f}pt; }}'
                                  .format(fam, f.pointSizeF()))
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth if self.s["word_wrap"]
                                    else QPlainTextEdit.LineWrapMode.NoWrap)
        self._sync_doc_prefs()

    def _sync_doc_prefs(self):
        doc = self.editor.document()
        was = doc.isModified()          # changing fonts / tab stops must not mark the file as edited
        f = self.editor.font()
        doc.setDefaultFont(f)
        self.editor.setTabStopDistance(QFontMetrics(f).horizontalAdvance(" ") * 4)
        if doc.isModified() != was:
            doc.setModified(was)

    def toggle_theme(self):
        self.s["theme"] = "light" if self.P["theme"] == "dark" else "dark"
        self.s.save()
        self.apply_theme()

    def _on_system_scheme(self, *_):
        if self.s["theme"] == "system":
            self.apply_theme()

    def showEvent(self, e):
        super().showEvent(e)
        style_titlebar(self, self.P)

    # ---------------------------------------------------------------- tabs
    # ---------------------------------------------------------------- preview
    def _js(self, code):
        self.page.runJavaScript(code)

    def _load_shell(self, base_dir):
        self._shell_ready = False
        self._shell_base = base_dir
        self._pending_render = True
        self.page.setHtml(shell_html(self.P, self.s, self.pyg_css),
                          QUrl.fromLocalFile(os.path.join(base_dir, "")))

    def _on_shell_loaded(self, ok):
        if not ok:
            return
        self._shell_ready = True
        self._install_drop_filters()
        self._js(self._theme_js(self.P))
        if self._pending_render:
            self._render_now()

    def _preview_visible(self):
        return self.mode == "preview"

    def _on_text_changed(self):
        if self._loading:
            return
        if self._preview_visible():
            self.render_timer.start()
        else:
            self._preview_dirty = True
        self.stats_timer.start()

    def _on_editor_scroll(self, value):
        if not (self.s["sync_scroll"] and self._shell_ready and self.mode == "preview" and self.edit
                and self.splitter.indexOf(self.editor) >= 0):
            return
        sb = self.editor.verticalScrollBar()
        ratio = value / sb.maximum() if sb.maximum() > 0 else 0
        self._js(f"mdScrollTo({ratio:.4f});")

    def _on_preview_scrolled(self, y):
        if self.cur is not None and self._restore_y is None:
            self.cur.preview_scroll = y

    def _on_copied(self, text):
        short = text.replace("\n", " ")
        self.flash_msg(f"Copied: {short[:40]}{'…' if len(short) > 40 else ''}")

    def _on_link(self, url):
        if url.isLocalFile():
            local = url.toLocalFile()
            if is_md_path(local) and Path(local).is_file():
                self.open_file(local)
                return
            if Path(local).exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(local))
                return
            self.flash_msg("Link target not found")
            return
        QDesktopServices.openUrl(url)

    # ---------------------------------------------------------------- modes
    # ---------------------------------------------------------------- files
    def maybe_save(self, doc=None):
        doc = doc or self.cur
        if doc is None or not doc.document.isModified():
            return True
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"Save changes to “{doc.title()}”?")
        box.setInformativeText("Your changes will be lost if you don't save them.")
        box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                               QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        r = box.exec()
        if r == QMessageBox.StandardButton.Save:
            return self.save(doc)
        return r == QMessageBox.StandardButton.Discard

    def maybe_save_all(self):
        for i, d in enumerate(list(self.docs)):
            if d.document.isModified():
                self._activate_tab(self.docs.index(d))
                if not self.maybe_save(d):
                    return False
        return True

    def open_dialog(self):
        start = str(self.path.parent) if self.path else (
            str(Path(self.s["recent"][0]).parent) if self.s["recent"] else str(Path.home()))
        files, _ = QFileDialog.getOpenFileNames(
            self, "Open Markdown files", start,
            "Markdown (*.md *.markdown *.mdown *.mkd *.mkdn *.txt);;All files (*)")
        for fn in files:
            self.open_file(fn)

    def open_file(self, fn, activate=True, quiet=False):
        path = Path(fn).resolve()
        for i, d in enumerate(self.docs):
            if d.path and same_path(d.path, path):
                if activate:
                    self._activate_tab(i)
                return
        try:
            text, nl, bom = read_text_file(path)
        except OSError as exc:
            if not quiet:
                QMessageBox.critical(self, APP_NAME, f"Could not open the file:\n{fn}\n\n{exc}")
            return
        reuse = self.cur if (self.cur is not None and not self.home_active and self.cur.is_pristine()
                             and activate) else None
        doc = reuse or Doc(self.P)
        doc.path, doc.newline, doc.bom = path, nl, bom
        doc.cursor_pos = doc.editor_scroll = 0
        doc.preview_scroll = 0.0
        self._loading = True
        doc.document.setPlainText(text)
        doc.document.setModified(False)
        self._loading = False
        self.watcher.addPath(str(path))
        self._add_recent(str(path))
        self.s["last_file"] = str(path)
        if reuse:
            self._update_tab(doc)
            self._switch_to(self.docs.index(doc), force=True)
        else:
            self._add_doc(doc, activate=activate)
        if not quiet:
            self.flash_msg(f"Opened {path.name}")

    def save(self, doc=None):
        doc = doc or self.cur
        if doc is None:
            return False
        if doc.path is None:
            return self.save_as(doc)
        return self._write(doc, doc.path)

    def save_as(self, doc=None):
        doc = doc or self.cur
        if doc is None:
            return False
        start = str(doc.path) if doc.path else str(Path.home() / "Untitled.md")
        fn, _ = QFileDialog.getSaveFileName(self, "Save Markdown file", start,
                                            "Markdown (*.md);;Text (*.txt);;All files (*)")
        if not fn:
            return False
        if not Path(fn).suffix:
            fn += ".md"
        if not self._write(doc, Path(fn)):
            return False
        if doc.path and not any(d is not doc and d.path == doc.path for d in self.docs):
            self.watcher.removePath(str(doc.path))
        doc.path = Path(fn).resolve()
        self.watcher.addPath(str(doc.path))
        self._add_recent(str(doc.path))
        self._update_tab(doc)
        if doc is self.cur:
            self.s["last_file"] = str(doc.path)
            if str(doc.path.parent) != self._shell_base:
                self._load_shell(str(doc.path.parent))
            self._update_title()
        return True

    def _write(self, doc, path):
        text = doc.document.toPlainText()
        if doc.newline == "\r\n":
            text = text.replace("\n", "\r\n")
        try:
            self._ignore_disk_until = time.time() + 1.5
            Path(path).write_bytes(text.encode("utf-8-sig" if doc.bom else "utf-8"))
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not save the file:\n{path}\n\n{exc}")
            return False
        doc.document.setModified(False)
        self.flash_msg(f"Saved {Path(path).name}")
        return True

    def reload_from_disk(self, doc=None, ask=True):
        doc = doc or self.cur
        if doc is None or not doc.path or not doc.path.is_file():
            return
        if ask and doc.document.isModified():
            r = QMessageBox.question(self, APP_NAME, f"Reload “{doc.title()}” from disk and lose your unsaved changes?")
            if r != QMessageBox.StandardButton.Yes:
                return
        try:
            text, nl, bom = read_text_file(doc.path)
        except OSError:
            return
        if text == doc.document.toPlainText():
            doc.document.setModified(False)
            return
        is_cur = doc is self.cur
        if is_cur:
            pos = self.editor.textCursor().position()
            scroll = self.editor.verticalScrollBar().value()
        doc.newline, doc.bom = nl, bom
        self._loading = True
        doc.document.setPlainText(text)
        self._loading = False
        doc.document.setModified(False)
        if is_cur:
            c = self.editor.textCursor()
            c.setPosition(min(pos, len(text)))
            self.editor.setTextCursor(c)
            self.editor.verticalScrollBar().setValue(scroll)
            self._preview_dirty = True
            if self._preview_visible():
                self._render_now()
            self._update_stats()
        self.flash_msg(f"Reloaded {doc.title()}")

    def _on_disk_changed(self, p):
        QTimer.singleShot(200, lambda: self._handle_disk_change(p))

    def _handle_disk_change(self, p):
        docs = [d for d in self.docs if d.path and same_path(d.path, p)]
        if not docs:
            return
        if Path(p).is_file() and p not in self.watcher.files():
            self.watcher.addPath(p)
        if time.time() < self._ignore_disk_until:
            return
        for doc in docs:
            if not doc.path.is_file():
                self.flash_msg(f"{doc.title()} was moved or deleted on disk")
                continue
            if not self.s["auto_reload"]:
                self.flash_msg(f"{doc.title()} changed on disk (F5 to reload)")
                continue
            if doc.document.isModified():
                self.tabs.setCurrentIndex(self.docs.index(doc))
                r = QMessageBox.question(self, APP_NAME,
                                         f"“{doc.title()}” was changed by another program.\n\n"
                                         "Reload it and lose your unsaved changes?")
                if r != QMessageBox.StandardButton.Yes:
                    continue
            self.reload_from_disk(doc, ask=False)

    def _add_recent(self, p):
        rec = [x for x in self.s["recent"] if os.path.normcase(x) != os.path.normcase(p)]
        self.s["recent"] = [p] + rec[:11]

    def _fill_recent(self):
        self.recent_menu.clear()
        items = [p for p in self.s["recent"] if Path(p).is_file()]
        if not items:
            a = self.recent_menu.addAction("No recent files")
            a.setEnabled(False)
            return
        for p in items[:12]:
            a = self.recent_menu.addAction(f"{Path(p).name}    —    {Path(p).parent}")
            a.triggered.connect(lambda _=False, x=p: self.open_file(x))
        self.recent_menu.addSeparator()
        clear = self.recent_menu.addAction("Clear list")
        clear.triggered.connect(lambda: (self.s.__setitem__("recent", []), self.s.save()))

    def open_folder(self):
        if not self.path:
            return
        if IS_WIN:
            subprocess.Popen(["explorer", "/select,", str(self.path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent)))

    def export_html(self):
        start = str(self.path.with_suffix(".html")) if self.path else str(Path.home() / "document.html")
        fn, _ = QFileDialog.getSaveFileName(self, "Export as HTML", start, "HTML (*.html)")
        if not fn:
            return
        if self.mode != "preview" or self._preview_dirty:
            self._render_now()
        title = htmlmod.escape(self.path.stem if self.path else "Document")

        def write(body):
            doc = ("<!doctype html><html data-theme=\"" + self.P["theme"] + "\"><head><meta charset=\"utf-8\">"
                   f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{title}</title>"
                   "<style>" + css_vars(self.P, self.s) + "</style><style>" + BASE_CSS + "</style><style>" +
                   self.pyg_css + "</style></head><body><main id=\"content\">" + (body or "") +
                   "</main></body></html>")
            try:
                Path(fn).write_text(doc, encoding="utf-8")
                self.flash_msg(f"Exported {Path(fn).name}")
            except OSError as exc:
                QMessageBox.critical(self, APP_NAME, f"Could not write the file:\n{exc}")
        self.page.runJavaScript("mdExport()", 0, write)

    def export_pdf(self):
        start = str(self.path.with_suffix(".pdf")) if self.path else str(Path.home() / "document.pdf")
        fn, _ = QFileDialog.getSaveFileName(self, "Export as PDF", start, "PDF (*.pdf)")
        if not fn:
            return
        if self._preview_dirty:
            self._render_now()
        light = make_palette("light", self.s["accent"])
        self._js(f"mdSetTheme('light',{json.dumps(css_vars(light, self.s))});")

        def done(path, ok):
            try:
                self.page.pdfPrintingFinished.disconnect(done)
            except Exception:
                pass
            self.apply_theme()
            self.flash_msg(f"Exported {Path(path).name}" if ok else "PDF export failed")
        self.page.pdfPrintingFinished.connect(done)
        QTimer.singleShot(150, lambda: self.page.printToPdf(fn))

    # ---------------------------------------------------------------- find
    def show_find(self):
        self.findbar.show()
        self.findbar.edit.setFocus()
        self.findbar.edit.selectAll()
        if self.findbar.edit.text():
            self.do_find(self.findbar.edit.text(), False)

    def hide_find(self):
        self.findbar.hide()
        self.page.findText("")
        self.findbar.count.setText("")
        (self.editor if self.mode == "raw" else self.web).setFocus()

    def do_find(self, text, backward):
        if self.mode == "preview":
            if backward:
                self.page.findText(text, QWebEnginePage.FindFlag.FindBackward)
            else:
                self.page.findText(text)
            if not text:
                self.findbar.count.setText("")
            return
        if not text:
            self.findbar.count.setText("")
            return
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        found = self.editor.find(text, flags)
        if not found:
            c = self.editor.textCursor()
            c.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
            self.editor.setTextCursor(c)
            found = self.editor.find(text, flags)
        n = self.editor.toPlainText().lower().count(text.lower())
        self.findbar.count.setText(f"{n} match{'es' if n != 1 else ''}" if found else "No matches")

    def _on_find_result(self, res):
        if not self.findbar.edit.text():
            self.findbar.count.setText("")
        elif res.numberOfMatches() == 0:
            self.findbar.count.setText("No matches")
        else:
            self.findbar.count.setText(f"{res.activeMatch()} of {res.numberOfMatches()}")

    # ---------------------------------------------------------------- Windows: default app / install
    def make_default_flow(self):
        if not IS_WIN:
            QMessageBox.information(self, APP_NAME, "Setting the default app only works on Windows.")
            return False
        try:
            done = make_default()
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not register {APP_NAME}:\n{exc}")
            return False
        if not done:
            QMessageBox.information(
                self, APP_NAME,
                "Windows needs you to confirm this once.\n\n"
                f"In the next window, pick “{APP_NAME}” and click “Always”.")
            done = confirm_default_with_windows(int(self.winId()))
        self.flash_msg(f"{APP_NAME} is now the default for .md files" if done else "Default app not changed")
        return done

    def install_flow(self):
        if not (IS_WIN and is_frozen()):
            QMessageBox.information(self, APP_NAME,
                                    "To install, first build the app with “Build EXE.bat”, "
                                    "then run “MD Reader.exe” from the dist folder.")
            return
        dlg = InstallDialog(self.P, existing_install(), from_settings=True, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.choice != "install":
            return
        if not self.maybe_save_all():
            return
        self._save_state()
        if run_install(self, dlg.scope, dlg.make_default, dlg.desktop, self.s):
            self._skip_close = True
            QApplication.quit()

    def uninstall_from_app(self):
        if not self.maybe_save_all():
            return
        if uninstall_flow(self, from_windows=False):
            self._skip_close = True
            QApplication.quit()

    # ---------------------------------------------------------------- single window (IPC)
    def _on_ipc(self):
        while self.server.hasPendingConnections():
            c = self.server.nextPendingConnection()
            self._ipc_buf[id(c)] = b""
            c.readyRead.connect(lambda c=c: self._read_ipc(c))
            c.disconnected.connect(lambda c=c: (self._ipc_buf.pop(id(c), None), c.deleteLater()))

    def _read_ipc(self, c):
        buf = self._ipc_buf.get(id(c), b"") + bytes(c.readAll())
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            try:
                msg = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            if msg.get("quit"):
                QTimer.singleShot(0, self.close)
                continue
            for f in msg.get("files", []):
                if Path(f).is_file():
                    self.open_file(f)
            if msg.get("make_default"):
                QTimer.singleShot(300, self.make_default_flow)
            self.bring_to_front()
        self._ipc_buf[id(c)] = buf

    def bring_to_front(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    # ---------------------------------------------------------------- misc
    def zoom(self, step):
        self._zoom = 1.0 if step == 0 else max(0.5, min(2.5, self._zoom + 0.1 * step))
        self.web.setZoomFactor(self._zoom)
        self._apply_editor_prefs()
        self.flash_msg(f"Zoom {int(round(self._zoom * 100))}%")

    def open_settings(self):
        dlg = SettingsDialog(self.s, self.P, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.s.update(dlg.values())
            self.s.save()
            self.apply_theme()
            if not self.s["split_when_editing"] and self.edit and self.mode == "preview":
                self.mode = "raw"
            self._arrange()
        if dlg.next_action == "install":
            QTimer.singleShot(0, self.install_flow)
        elif dlg.next_action == "uninstall":
            QTimer.singleShot(0, self.uninstall_from_app)
        elif dlg.next_action == "shortcuts":
            QTimer.singleShot(0, self.show_shortcuts)

    def show_shortcuts(self):
        rows = "".join(f"<tr><td style='padding:3px 18px 3px 0'><b>{k}</b></td><td>{v}</td></tr>"
                       for k, v in SHORTCUTS_HELP)
        QMessageBox.information(self, "Keyboard shortcuts", f"<table>{rows}</table>")

    def show_about(self):
        where = {"machine": "Installed for all users", "user": "Installed for you"}.get(
            install_scope(), "Portable copy" if is_frozen() else "Running as a Python script")
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<h3>{APP_NAME} {APP_VERSION}</h3><p>A clean Markdown reader and editor.</p>"
                          f"<p>{where}.</p>")

    def flash_msg(self, text):
        self.st_msg.setText(text)
        self.msg_timer.start()

    def _update_cursor_pos(self):
        c = self.editor.textCursor()
        self.st_pos.setText(f"Ln {c.blockNumber() + 1}, Col {c.positionInBlock() + 1}")

    def _restore_geometry(self):
        g = self.s.get("geometry")
        if g:
            try:
                self.restoreGeometry(QByteArray.fromBase64(g.encode("ascii")))
            except Exception:
                pass

    def _save_state(self):
        self.s["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        if self.splitter.indexOf(self.editor) >= 0:
            self.s["splitter"] = self.splitter.sizes()
        self.s["last_tab"] = self.mode
        self.s["open_files"] = [str(d.path) for d in self.docs if d.path]
        self.s["active_file"] = str(self.cur.path) if self.cur and self.cur.path else ""
        self.s.save()

    def closeEvent(self, e):
        if self._skip_close:
            e.accept()
            return
        if not self.maybe_save_all():
            e.ignore()
            return
        self._save_state()
        self.server.close()
        e.accept()

    # drag & drop: the window, the editor and the preview all accept .md files
    def _install_drop_filters(self):
        targets = [self.editor.viewport(), self.web]
        fp = self.web.focusProxy()
        if fp is not None:
            targets.append(fp)
        for t in targets:
            if t is not None and t not in self._drop_targets:
                t.setAcceptDrops(True)
                t.installEventFilter(self)
                self._drop_targets.append(t)

    def dragEnterEvent(self, ev):
        if not self._handle_drop_event(ev):
            super().dragEnterEvent(ev)

    def dropEvent(self, ev):
        if not self._handle_drop_event(ev):
            super().dropEvent(ev)

    def eventFilter(self, obj, ev):
        if obj is self.tabs and ev.type() == QEvent.Type.MouseButtonRelease \
                and ev.button() == Qt.MouseButton.MiddleButton:
            i = self.tabs.tabAt(ev.position().toPoint())
            if i >= 0:
                self.close_tab(i)
                return True
        if obj in self._drop_targets and self._handle_drop_event(ev):
            return True
        return super().eventFilter(obj, ev)

    def _handle_drop_event(self, ev):
        t = ev.type()
        if t in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            md = ev.mimeData()
            if md and md.hasUrls():
                files = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
                files = [f for f in files if is_md_path(f) or Path(f).suffix == ""]
                if files:
                    ev.acceptProposedAction()
                    if t == QEvent.Type.Drop:
                        QTimer.singleShot(0, lambda fs=files: [self.open_file(f) for f in fs])
                    return True
        return False


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------

def make_ico(dest):
    """Write the app icon as .ico (used by Build EXE.bat)."""
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
    img = svg_pixmap(APP_ICON_SVG, 256, 1.0).toImage()
    png = Path(dest).with_suffix(".png")
    img.save(str(png), "PNG")
    try:
        from PIL import Image
        Image.open(png).save(dest, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    except Exception:
        img.save(str(dest), "ICO")
    try:
        png.unlink()
    except OSError:
        pass


def _message_box(text, error=True):
    if IS_WIN:
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10 if error else 0x40)
    else:
        print(text, file=sys.stderr)


def main():
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--make-icon":
        make_ico(args[1])
        return 0
    # helpers that run elevated (UAC) for "All users"
    if IS_WIN and "--do-install" in args:
        i = args.index("--do-install")
        scope = args[i + 1] if i + 1 < len(args) else "machine"
        err = do_install(scope)
        if err:
            _message_box(err)
        return 1 if err else 0
    if IS_WIN and "--uninstall-elevated" in args:
        i = args.index("--uninstall-elevated")
        keep = [int(args[i + 1])] if i + 1 < len(args) and args[i + 1].isdigit() else []
        scope = install_scope()
        if scope:
            do_uninstall(scope, keep)
        return 0

    if IS_WIN:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("IMM.MDReader")
        except Exception:
            pass
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-logging")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())

    settings = Settings()
    if not settings["editor_font"]:
        settings["editor_font"] = default_mono_family()
    P = make_palette(resolve_theme(settings), settings["accent"])

    def themed():
        app.setPalette(qt_palette(P))
        app.setStyleSheet(build_qss(P))

    # uninstall started from Windows Settings > Apps
    if "--uninstall" in args:
        themed()
        uninstall_flow(None, from_windows=True)
        return 0

    files = [str(Path(a).resolve()) for a in args if not a.startswith("--") and Path(a).is_file()]
    make_def = "--make-default" in args

    # one window: hand files to the copy that's already running
    if send_to_running({"files": files, "make_default": make_def}, instance_name()):
        return 0

    # a portable exe opened by double-click: offer to install it (like HK-Master)
    if IS_WIN and is_frozen() and not install_scope() and not files and "--portable" not in args:
        themed()
        dlg = InstallDialog(P, existing_install())
        dlg.exec()
        if dlg.choice is None:
            return 0
        if dlg.choice == "install":
            if run_install(None, dlg.scope, dlg.make_default, dlg.desktop, settings):
                return 0

    win = MainWindow(settings, files, make_default_on_start=make_def)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
