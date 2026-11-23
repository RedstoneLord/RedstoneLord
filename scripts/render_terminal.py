"""Render the foxtrot console's typed commands and responses as a GIF."""

from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image, ImageDraw, ImageFont


SIZE = (1000, 486)
LEFT = 47
TOP = 75
ROW_HEIGHT = 29
VISIBLE_ROWS = 13
PROMPT = "> "
INK = {
    "command": "#e1f1ca",
    "reply": "#abcc8a",
    "heading": "#8f8dc6",
    "muted": "#86947d",
}
KEY_DELAYS = (100, 80, 130, 90, 150, 90, 100, 80)


def terminal_background():
    image = Image.new("RGB", SIZE, "#0b0d16")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((9, 8, 990, 477), radius=19, fill="#191a28", outline="#3d3d54", width=2)
    draw.rounded_rectangle((23, 22, 976, 464), radius=12, fill="#101913", outline="#313b31", width=2)
    for y in range(70, 451, 4):
        draw.line((30, y, 969, y), fill="#121d15")
    draw.line((41, 64, 958, 64), fill="#354332")
    label_font = ImageFont.truetype("DejaVuSansMono.ttf", 18)
    draw.text((LEFT, 39), "FOXTROT / ARRAY CONSOLE", font=label_font, fill=INK["heading"], anchor="lt")
    draw.ellipse((868, 42, 875, 49), fill="#77a964")
    draw.text((886, 39), "ONLINE", font=label_font, fill=INK["reply"], anchor="lt")
    return image


def draw_screen(background, font, history, input_text=None, cursor=False):
    image = background.copy()
    draw = ImageDraw.Draw(image)
    lines = list(history)
    if input_text is not None:
        lines.append(("command", PROMPT + input_text))
    visible = lines[-VISIBLE_ROWS:]
    for index, (kind, line) in enumerate(visible):
        y = TOP + index * ROW_HEIGHT
        draw.text((LEFT, y), line, font=font, fill=INK[kind], anchor="lt")
    if cursor and input_text is not None:
        x = round(LEFT + font.getlength(PROMPT + input_text))
        y = TOP + (len(visible) - 1) * ROW_HEIGHT + 20
        draw.rectangle((x, y, x + 11, y + 2), fill=INK["command"])
    return image


def terminal_frames(stats):
    base = terminal_background()
    font = ImageFont.truetype("DejaVuSansMono.ttf", 24)
    history = []

    def screen(delay, input_text=None, cursor=False):
        return draw_screen(base, font, history, input_text, cursor), delay

    yield screen(590, "", True)
    steps = (
        ("sv.ping", (("reply", "foxtrot .......... 4/4 packets"),
                     ("reply", "relay-west ....... 4/4 packets")), 610),
        ("sd.calch", (("reply", "foxtrot .......... 99.6%"),
                      ("reply", "relay-west ....... 98.3%")), 620),
        ("github.status", stats, 5100),
        ("clr", (), 0),
    )
    for command, replies, hold in steps:
        for index in range(1, len(command) + 1):
            yield screen(KEY_DELAYS[(index - 1) % len(KEY_DELAYS)], command[:index], True)
        if command == "clr":
            yield screen(330, command, True)
            history.clear()
            yield screen(650, "", True)
            continue

        history.append(("command", PROMPT + command))
        yield screen(220)
        for reply in replies:
            history.append(reply)
            yield screen(110)
        while hold:
            delay = min(hold, 490)
            yield screen(delay, "", (hold // 490) % 2 == 0)
            hold -= delay


def write_terminal_gif(path: Path, stats):
    frames, delays = zip(*terminal_frames(stats))
    # The screen just before the clear contains all of the terminal's text colors.
    sampled = frames[-2]
    colors = sampled.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    palette = Image.new("P", (1, 1))
    palette.putpalette(colors.getpalette()[:255 * 3])
    indexed = (frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames)
    global_palette = bytes(palette.getpalette()) + bytes((0, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, suffix=".gif", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        first = next(indexed)
        first.save(temporary, append_images=indexed, save_all=True, duration=delays,
                   loop=0, disposal=1, transparency=255, palette=global_palette, optimize=True)
        if path.exists() and temporary.read_bytes() == path.read_bytes():
            return False
        temporary.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o644)
        temporary.replace(path)
        return True
    finally:
        temporary.unlink(missing_ok=True)
