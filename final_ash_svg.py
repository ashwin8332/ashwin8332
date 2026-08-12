"""
final_ash_svg.py
================

Generates `final_ash.svg` — an animated, neofetch-style GitHub profile card.

The left panel renders your photo as a **vector halftone dot matrix**: the image
is sampled on a square grid and each cell becomes a round dot whose diameter and
opacity track that cell's brightness. The dots are stroked with the animated
cyan -> violet gradient, layered with scanlines and glitch bars, faded at the
edges by a radial mask, and revealed by a top-down wipe. No raster data is
embedded — the whole portrait is geometry, so it stays crisp at any zoom.

`--style ascii` switches the same portrait to classic ASCII-art characters.

Usage
-----
    python final_ash_svg.py                       # uses SOURCE below
    python final_ash_svg.py --source photo.png    # different portrait
    python final_ash_svg.py --style ascii         # character portrait instead
    python final_ash_svg.py --dump-preview        # PNG of the sampled portrait

Requires Pillow: pip install pillow
"""

from __future__ import annotations

import argparse
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "SCREEN.png"             # portrait photo
OUTPUT = ROOT / "final_ash.svg"

# --------------------------------------------------------------------------- #
# 1. CONTENT  — the only block you normally need to edit
# --------------------------------------------------------------------------- #

USER = "ashwin"
HOST = "devos"

# A section is (section_title | None, [(key, value), ...]).
# `None` title -> rows only.  An empty key -> plain text line.
# A dot inside a key ("Core.Lang") renders as two highlighted words joined by a
# dim dot, exactly like dark.svg.
SECTIONS: list[tuple[str | None, list[tuple[str, str]]]] = [
    (None, [
        ("Subject",   "Ashwin Vincent Koonissery"),
        ("Role",      "AI Engineer · Software Developer"),
        ("Focus",     "AI/ML · Generative AI · Agentic AI · Full-Stack"),
        ("Origin",    "Mumbai, India"),
        ("Status",    "B.E. IT — AI & ML Honours · 2023–2027"),
        ("Toolchain", "Python · PyTorch · Hugging Face · Transformers · RAG"),
    ]),
    (None, [
        ("Core.Lang",     "Python · JavaScript · TypeScript · SQL · C · C++"),
        ("Core.Python",   "PyTorch · Scikit-learn · XGBoost · Transformers"),
        ("Core.Frontend", "React.js · Next.js · Tailwind CSS · HTML5 · CSS3"),
        ("Core.Backend",  "FastAPI · Flask · Node.js · REST APIs"),
        ("Core.Data",     "MongoDB · MySQL · SQLite · Microsoft Fabric"),
        ("Core.Cloud",    "Docker · Microsoft Fabric · GitHub · Prometheus"),
    ]),
    ("Contact", [
        ("Grid.Mail",      "anshilashwin80@gmail.com"),
        ("Grid.Portfolio", "avkdev.vercel.app"),
        ("Grid.LinkedIn",  "/in/ashwin-vincent-koonissery-a2662a2b7"),
        ("Grid.Github",    "github.com/ashwin8332"),
    ]),
]

# --------------------------------------------------------------------------- #
# 2. PORTRAIT
# --------------------------------------------------------------------------- #

STYLE = "dots"                           # "dots" (halftone) or "ascii"

# Crop taken from the source, as fractions (left, top, right, bottom).
# Tuned so the head sits in the upper third and the shoulders fill the base.
CROP = (0.24, 0.00, 0.79, 0.72)

AUTO_CUTOFF = 0                          # percent clipped off each end of the histogram
CONTRAST = 1.05                          # >1 hardens tonal separation
GAMMA = 0.82                             # <1 lifts midtones
PRE_BLUR = 0.4                           # softens busy backgrounds before sampling
INVERT = False                           # True for light-on-dark sources

# Baked-in vignette: fades the background away from the face so the foliage
# behind you doesn't compete with the subject. 0 disables it.
VIGNETTE = 0.70
VIGNETTE_CENTER = (0.50, 0.40)           # where the face sits in the crop
VIGNETTE_INNER = 0.46                    # radius held at full brightness

# Drawing box for the portrait, inside the left panel (local coords).
BOX_X, BOX_Y, BOX_W, BOX_H = 34, 48, 448, 424

# Halftone -------------------------------------------------------------------
DOT_CELL = 3                             # grid pitch in px; smaller = finer, bigger file
DOT_LEVELS = 7                           # brightness buckets; bucket 0 is left blank
DOT_SIZES = [0.0, 1.0, 1.6, 2.2, 2.8, 3.4, 3.9]      # dot diameter per bucket
DOT_OPACITY = [0.0, 0.42, 0.58, 0.72, 0.85, 0.94, 1.0]
GLITCH_ROWS = 9                         # bright horizontal glitch bars
GLITCH_SEED = 53

# ASCII (only used with --style ascii) ---------------------------------------
ASCII_COLS, ASCII_ROWS = 93, 53
ASCII_Y0 = 79.98
ASCII_LINE_H = 7.548
ASCII_FONT_SIZE = 7.4
ASCII_TRACKING = -0.2
ASCII_RAMP = " .:-=+*#%@"

CHAR_W = ASCII_FONT_SIZE * 0.6 + ASCII_TRACKING   # Courier advances 0.6em per glyph
ASCII_BLOCK_W = ASCII_COLS * CHAR_W
ASCII_X = round(14 + (488 - ASCII_BLOCK_W) / 2)   # centre the block in the panel

# --------------------------------------------------------------------------- #
# 3. LAYOUT — mirrors dark.svg; change only if you resize the canvas
# --------------------------------------------------------------------------- #

CANVAS_W, CANVAS_H = 1180, 610

INFO_X = 520
INFO_Y_HEAD = 42                         # baseline of the "user@host" line
INFO_GAP_AFTER_HEAD = 24
INFO_LINE_H = 22
INFO_MAX_LINES = 22                      # what fits inside the right panel
INFO_LINE_WIDTH = 66                     # right edge, in characters
MIN_LEADER_DOTS = 4
MAX_LEADER_DOTS = 34                     # stops short values getting a 50-dot leader
RULE_CHAR = "—"
RULE_WIDTH = 46

TYPE_START = 0.75                        # when line 0 starts drawing, seconds
TYPE_STAGGER = 0.115                     # delay between consecutive lines
TYPE_DUR = 0.38                          # sweep duration of one line
MASK_DUR = 2.6                           # portrait reveal duration


# --------------------------------------------------------------------------- #
# 4. IMAGE SAMPLING
# --------------------------------------------------------------------------- #

def load_gray(source: Path, cols: int, rows: int):
    """Crop, tone-map and downsample `source` onto a cols x rows grid."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    except ImportError:  # pragma: no cover
        sys.exit("Pillow is required: pip install pillow")

    if not source.exists():
        sys.exit(f"Portrait not found: {source}\nPass --source PATH")

    img = Image.open(source).convert("L")
    w, h = img.size
    left, top, right, bottom = CROP
    img = img.crop((int(w * left), int(h * top), int(w * right), int(h * bottom)))

    if PRE_BLUR:
        img = img.filter(ImageFilter.GaussianBlur(PRE_BLUR))
    img = ImageOps.autocontrast(img, cutoff=AUTO_CUTOFF)
    img = ImageEnhance.Contrast(img).enhance(CONTRAST)
    if GAMMA != 1.0:
        img = img.point([min(255, int(255 * (i / 255) ** GAMMA)) for i in range(256)])
    if INVERT:
        img = ImageOps.invert(img)

    img = img.resize((cols, rows), Image.Resampling.LANCZOS)

    if VIGNETTE:
        cx, cy = VIGNETTE_CENTER
        px = img.load()
        for y in range(rows):
            dy = (y / rows - cy) / 0.55
            for x in range(cols):
                dx = (x / cols - cx) / 0.50
                dist = (dx * dx + dy * dy) ** 0.5
                if dist <= VIGNETTE_INNER:
                    continue
                falloff = min(1.0, (dist - VIGNETTE_INNER) / (1 - VIGNETTE_INNER))
                px[x, y] = int(px[x, y] * (1 - VIGNETTE * falloff))

    return img


def build_halftone(source: Path, preview: Path | None = None) -> str:
    """Sample the photo into a grid of gradient-stroked dots."""
    import random

    cols = BOX_W // DOT_CELL
    rows = BOX_H // DOT_CELL
    img = load_gray(source, cols, rows)
    if preview:
        img.resize((cols * 4, rows * 4)).save(preview)

    # Centre the dot block inside the drawing box.
    x0 = BOX_X + (BOX_W - cols * DOT_CELL) // 2
    y0 = BOX_Y + (BOX_H - rows * DOT_CELL) // 2

    px = img.load()
    buckets: dict[int, list[str]] = {level: [] for level in range(1, DOT_LEVELS)}
    for row in range(rows):
        for col in range(cols):
            level = px[col, row] * DOT_LEVELS // 256
            if level < 1:
                continue                                  # darkest bucket stays empty
            # Coordinates are emitted in *grid units* and scaled up by the group
            # transform below — two-digit numbers instead of four-digit ones cut
            # the path data by roughly a quarter.
            buckets[level].append(f"M{col} {row}h.01")    # zero-length round-capped dash

    # One <path> per brightness bucket keeps the file an order of magnitude
    # smaller than emitting one <circle> per dot.
    # The mask lives on the OUTER group: a mask on a transformed element is
    # resolved in that element's own (scaled) user space, which would shift the
    # fade off the portrait. Only the inner group carries the transform.
    half = DOT_CELL / 2
    parts = [
        '<g mask="url(#portraitFade)">',
        f'<g fill="none" stroke="url(#asciiGrad)" stroke-linecap="round" '
        f'transform="translate({x0 + half} {y0 + half}) scale({DOT_CELL})">'
    ]
    for level in range(1, DOT_LEVELS):
        if not buckets[level]:
            continue
        parts.append(
            f'<path stroke-width="{DOT_SIZES[level] / DOT_CELL:.3f}" '
            f'opacity="{DOT_OPACITY[level]}" d="{"".join(buckets[level])}"/>'
        )
    parts.append("</g>")

    # Structure: fine scanlines, then a few bright glitch bars, in page units.
    w, h = cols * DOT_CELL, rows * DOT_CELL
    parts.append('<g fill="none">')
    lines = "".join(f"M{x0} {y}H{x0 + w}" for y in range(y0, y0 + h, DOT_CELL + 1))
    parts.append(f'<path stroke="#9BE7FF" stroke-width="0.5" opacity="0.10" d="{lines}"/>')

    rng = random.Random(GLITCH_SEED)
    bars = []
    for _ in range(GLITCH_ROWS):
        gy = rng.randrange(y0, y0 + h, DOT_CELL)
        gx = rng.randint(x0 + 10, x0 + w - 90)
        bars.append(f"M{gx} {gy}h{rng.randint(24, 78)}")
    parts.append(
        f'<path stroke="#A5F3FC" stroke-width="1.5" opacity="0.22" d="{"".join(bars)}">'
        '<animate attributeName="opacity" values="0.22;0.05;0.26;0.09;0.22" '
        'dur="5.5s" repeatCount="indefinite"/></path>'
    )
    parts.append("</g></g>")

    dots = sum(len(v) for v in buckets.values())
    print(f"  halftone: {cols}x{rows} grid, {dots} dots")
    return "\n  ".join(parts)


def build_ascii(source: Path, preview: Path | None = None) -> str:
    """Sample the photo into ASCII-art <tspan> lines."""
    img = load_gray(source, ASCII_COLS, ASCII_ROWS)
    if preview:
        img.resize((ASCII_COLS * 6, ASCII_ROWS * 6)).save(preview)

    px = img.load()
    last = len(ASCII_RAMP) - 1
    rows = [
        "".join(ASCII_RAMP[px[x, y] * last // 255] for x in range(ASCII_COLS))
        for y in range(ASCII_ROWS)
    ]
    tspans = "\n".join(
        f'<tspan x="{ASCII_X}" y="{ASCII_Y0 + i * ASCII_LINE_H:.2f}" '
        f'xml:space="preserve">{escape(line)}</tspan>'
        for i, line in enumerate(rows)
    )
    return f'<text x="{ASCII_X}" y="0" class="ascii">\n{tspans}\n  </text>'


# --------------------------------------------------------------------------- #
# 5. INFO PANEL
# --------------------------------------------------------------------------- #

def key_tspans(key: str) -> str:
    """'Core.Lang' -> highlighted 'Core', dim '.', highlighted 'Lang'."""
    parts = key.split(".")
    chunks = [f'<tspan class="key">{escape(parts[0])}</tspan>']
    for part in parts[1:]:
        chunks.append('<tspan class="cc">.</tspan>')
        chunks.append(f'<tspan class="key">{escape(part)}</tspan>')
    return "".join(chunks)


def build_lines() -> list[str]:
    """Flatten SECTIONS into a list of tspan strings, one per rendered line."""
    rule = RULE_CHAR * RULE_WIDTH
    lines: list[str] = [
        f'<tspan class="head">{escape(USER)}@{escape(HOST)}</tspan>'
        f'<tspan class="cc"> -{rule}-—-</tspan>'
    ]

    for index, (title, rows) in enumerate(SECTIONS):
        if index > 0:
            lines.append('<tspan class="cc">. </tspan>')            # spacer
        if title:
            lines.append(
                f'<tspan class="accent">- {escape(title)}</tspan>'
                f'<tspan class="cc"> -{rule}-—-</tspan>'
            )
        for key, value in rows:
            if not key:
                lines.append(
                    f'<tspan class="cc">. </tspan><tspan class="value">{escape(value)}</tspan>'
                )
                continue
            prefix = 2 + len(key) + 2                                # ". " + key + ": "
            dots = INFO_LINE_WIDTH - len(value) - prefix - 1         # -1 for the space
            if dots < MIN_LEADER_DOTS:
                print(f"  note: '{key}' row runs past column {INFO_LINE_WIDTH}", file=sys.stderr)
                dots = MIN_LEADER_DOTS
            dots = min(dots, MAX_LEADER_DOTS)
            lines.append(
                f'<tspan class="cc">. </tspan>{key_tspans(key)}'
                f'<tspan class="cc">: {"." * dots} </tspan>'
                f'<tspan class="value">{escape(value)}</tspan>'
            )

    if len(lines) > INFO_MAX_LINES:
        print(
            f"  warning: {len(lines)} info lines, panel holds {INFO_MAX_LINES}; "
            "extras will overflow the frame",
            file=sys.stderr,
        )
    return lines


def line_y(i: int) -> float:
    """Baseline of info line i. Line 0 is the header, with a wider gap below."""
    if i == 0:
        return float(INFO_Y_HEAD)
    return INFO_Y_HEAD + INFO_GAP_AFTER_HEAD + (i - 1) * INFO_LINE_H


def build_info(lines: list[str]) -> tuple[str, str, float]:
    """Return (clipPath defs, rendered rows, time the last line finishes)."""
    clips, rows = [], []
    for i, content in enumerate(lines):
        y = line_y(i)
        begin = TYPE_START + i * TYPE_STAGGER
        clips.append(
            f'<clipPath id="lc{i}"><rect x="500" y="{y - 16:.2f}" width="0" height="24">'
            f'<animate attributeName="width" from="0" to="690" dur="{TYPE_DUR}s" '
            f'begin="{begin:.2f}s" fill="freeze"/></rect></clipPath>'
        )
        rows.append(
            f'<g clip-path="url(#lc{i})"><text x="{INFO_X}" y="0" fill="#dbeafe">'
            f'<tspan x="{INFO_X}" y="{y:.2f}">{content}</tspan></text></g>'
        )
    done = TYPE_START + (len(lines) - 1) * TYPE_STAGGER + TYPE_DUR
    return "\n  ".join(clips), "\n  ".join(rows), done


# --------------------------------------------------------------------------- #
# 6. SVG
# --------------------------------------------------------------------------- #

def build_svg(portrait: str) -> str:
    lines = build_lines()
    clip_defs, info_rows, done = build_info(lines)
    cursor_y = line_y(len(lines) - 1) - 15

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_W}" height="{CANVAS_H}" viewBox="0 0 {CANVAS_W} {CANVAS_H}">
<defs>
  <linearGradient id="asciiGrad" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#22D3EE">
      <animate attributeName="stop-color" values="#22D3EE;#7C3AED;#38BDF8;#22D3EE" dur="9s" repeatCount="indefinite"/>
    </stop>
    <stop offset="100%" stop-color="#7C3AED">
      <animate attributeName="stop-color" values="#7C3AED;#38BDF8;#22D3EE;#7C3AED" dur="9s" repeatCount="indefinite"/>
    </stop>
  </linearGradient>
  <linearGradient id="borderGrad" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#7C3AED"/>
    <stop offset="50%" stop-color="#22D3EE"/>
    <stop offset="100%" stop-color="#10B981"/>
  </linearGradient>
  <radialGradient id="bgGlow" cx="30%" cy="20%" r="80%">
    <stop offset="0%" stop-color="#0B1120"/>
    <stop offset="100%" stop-color="#050816"/>
  </radialGradient>
  <linearGradient id="scanGrad" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" stop-color="#22D3EE" stop-opacity="0"/>
    <stop offset="45%" stop-color="#22D3EE" stop-opacity="0.05"/>
    <stop offset="50%" stop-color="#A5F3FC" stop-opacity="0.65"/>
    <stop offset="55%" stop-color="#22D3EE" stop-opacity="0.05"/>
    <stop offset="100%" stop-color="#7C3AED" stop-opacity="0"/>
  </linearGradient>
  <pattern id="scanlines" width="4" height="4" patternUnits="userSpaceOnUse">
    <rect width="4" height="1" fill="#7DD3FC" opacity="0.05"/>
  </pattern>
  <radialGradient id="fadeGrad" cx="50%" cy="40%" r="72%">
    <stop offset="0%" stop-color="#fff"/>
    <stop offset="75%" stop-color="#fff" stop-opacity="0.95"/>
    <stop offset="100%" stop-color="#000"/>
  </radialGradient>
  <mask id="portraitFade" maskUnits="userSpaceOnUse" x="{BOX_X}" y="{BOX_Y}" width="{BOX_W}" height="{BOX_H}">
    <rect x="{BOX_X}" y="{BOX_Y}" width="{BOX_W}" height="{BOX_H}" fill="url(#fadeGrad)"/>
  </mask>
  <mask id="revealMask" maskUnits="userSpaceOnUse" x="0" y="0" width="{CANVAS_W}" height="620">
    <rect x="0" y="0" width="{CANVAS_W}" height="0" fill="#fff">
      <animate attributeName="height" from="0" to="560" dur="{MASK_DUR}s" begin="0.2s" fill="freeze" calcMode="spline" keySplines="0.25 0.1 0.25 1"/>
    </rect>
  </mask>
  {clip_defs}
  <style>
    .ascii  {{ font-family: 'Courier New', Consolas, monospace; font-size: {ASCII_FONT_SIZE}px; fill: url(#asciiGrad); letter-spacing: {ASCII_TRACKING}px; }}
    .key    {{ font-family: 'Courier New', Consolas, monospace; font-size: 15px; fill: #22D3EE; font-weight: bold; }}
    .value  {{ font-family: 'Courier New', Consolas, monospace; font-size: 15px; fill: #E5E7EB; }}
    .cc     {{ font-family: 'Courier New', Consolas, monospace; font-size: 15px; fill: #475569; }}
    .head   {{ font-family: 'Courier New', Consolas, monospace; font-size: 17px; fill: #7C3AED; font-weight: bold; }}
    .accent {{ font-family: 'Courier New', Consolas, monospace; font-size: 15px; fill: #10B981; font-weight: bold; }}
    text, tspan {{ white-space: pre; }}
    .term-label  {{ font-family: 'Courier New', Consolas, monospace; font-size: 12px; fill: #64748B; letter-spacing: 0.5px; }}
    .scan-label  {{ font-family: 'Courier New', Consolas, monospace; font-size: 10px; fill: #F87171; letter-spacing: 1px; }}
    .panel-title {{ font-family: 'Courier New', Consolas, monospace; font-size: 11px; fill: #38BDF8; letter-spacing: 2px; opacity: 0.7; }}
    .cursor-blink {{ fill: #22D3EE; }}
  </style>
</defs>

<rect width="{CANVAS_W}" height="{CANVAS_H}" rx="18" fill="url(#bgGlow)"/>
<rect width="{CANVAS_W}" height="{CANVAS_H}" rx="18" fill="url(#scanlines)"/>

<g id="titlebar">
  <rect x="3" y="3" width="1174" height="34" rx="16" fill="#0B1120" fill-opacity="0.85"/>
  <circle cx="24" cy="20" r="5" fill="#EF4444"><animate attributeName="opacity" values="1;0.55;1" dur="4s" repeatCount="indefinite"/></circle>
  <circle cx="42" cy="20" r="5" fill="#F59E0B"><animate attributeName="opacity" values="1;0.55;1" dur="4s" begin="0.3s" repeatCount="indefinite"/></circle>
  <circle cx="60" cy="20" r="5" fill="#10B981"><animate attributeName="opacity" values="1;0.55;1" dur="4s" begin="0.6s" repeatCount="indefinite"/></circle>
  <text x="590" y="25" text-anchor="middle" class="term-label">{USER}@{HOST} ~ % ./profile.sh --live</text>
  <circle cx="1104" cy="20" r="4" fill="#F87171">
    <animate attributeName="opacity" values="1;0.15;1" dur="1.1s" repeatCount="indefinite"/>
  </circle>
  <text x="1168" y="24" text-anchor="end" class="scan-label">SCANNING</text>
</g>

<g transform="translate(0,38)">
  <rect x="14" y="26" width="488" height="468" rx="14" fill="#0B1120" fill-opacity="0.35" stroke="url(#borderGrad)" stroke-width="1" opacity="0.35"/>
  <rect x="508" y="10" width="655" height="500" rx="14" fill="#0B1120" fill-opacity="0.35" stroke="url(#borderGrad)" stroke-width="1" opacity="0.35"/>
  <text x="30" y="24" class="panel-title">VISUAL.MAP</text>
  <text x="524" y="24" class="panel-title">SYSTEM.INFO</text>

  <g mask="url(#revealMask)">
  {portrait}
  </g>

  <g stroke="#38BDF8" stroke-width="1" opacity="0.35" fill="none">
    <path d="M{BOX_X} {BOX_Y + 18}V{BOX_Y}H{BOX_X + 18}"/>
    <path d="M{BOX_X + BOX_W - 18} {BOX_Y}H{BOX_X + BOX_W}V{BOX_Y + 18}"/>
    <path d="M{BOX_X + BOX_W} {BOX_Y + BOX_H - 18}V{BOX_Y + BOX_H}H{BOX_X + BOX_W - 18}"/>
    <path d="M{BOX_X + 18} {BOX_Y + BOX_H}H{BOX_X}V{BOX_Y + BOX_H - 18}"/>
  </g>

  {info_rows}

  <rect x="522" y="{cursor_y:.1f}" width="9" height="16" class="cursor-blink" opacity="0">
    <animate attributeName="opacity" values="0;0;1;0;1;0;1;0" keyTimes="0;0.01;0.02;0.3;0.5;0.7;0.85;1" dur="1.4s" begin="{done:.2f}s" repeatCount="indefinite"/>
  </rect>
</g>

<rect x="0" y="-70" width="{CANVAS_W}" height="70" fill="url(#scanGrad)" opacity="0.7" style="mix-blend-mode:screen">
  <animateTransform attributeName="transform" type="translate" from="0 -70" to="0 680" dur="4.2s" repeatCount="indefinite"/>
</rect>

<rect x="3" y="3" width="1174" height="604" rx="16" fill="none" stroke="url(#borderGrad)" stroke-width="2" opacity="0.8">
  <animate attributeName="opacity" values="0.5;0.95;0.5" dur="3.2s" repeatCount="indefinite"/>
</rect>
</svg>
'''


# --------------------------------------------------------------------------- #
# 7. CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    parser = argparse.ArgumentParser(description="Build the animated profile card.")
    parser.add_argument("--source", type=Path, default=SOURCE, help="portrait image")
    parser.add_argument("--style", choices=("dots", "ascii"), default=STYLE)
    parser.add_argument("--output", type=Path, default=OUTPUT, help="SVG to write")
    parser.add_argument("--dump-preview", action="store_true",
                        help="write sampled_portrait.png to check the crop and tone")
    args = parser.parse_args()

    preview = ROOT / "sampled_portrait.png" if args.dump_preview else None
    if args.style == "ascii":
        portrait = build_ascii(args.source, preview)
    else:
        portrait = build_halftone(args.source, preview)

    args.output.write_text(build_svg(portrait), encoding="utf-8")
    size_kb = args.output.stat().st_size / 1024
    print(f"Generated {args.output}  ({size_kb:.1f} KB, style={args.style})")


if __name__ == "__main__":
    main()
