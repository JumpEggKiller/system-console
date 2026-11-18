"""System Console icon: Catppuccin dark + CPU grid + GPU card + net arrows.

Writes system_console.ico (multi-size) and system_console.png (256px, for Linux/.desktop)
next to this script.
"""
import os
from PIL import Image, ImageDraw

def col(v):
    return (243, 139, 168) if v >= 85 else ((249, 226, 175) if v >= 50 else (166, 227, 161))

def make(size):
    im = Image.new("RGBA", (size, size), (17, 17, 27, 255))
    d = ImageDraw.Draw(im)
    s = size / 100
    d.rounded_rectangle([6*s, 6*s, 94*s, 94*s], radius=10*s, fill=(30, 30, 46), outline=(49, 50, 68))
    # left column: CPU core grid 3x4
    vals = [20, 70, 100, 0, 40, 90, 10, 60, 100, 30, 80, 0]
    gx, gy = 12*s, 14*s
    cw, chh, gap = 10*s, 12*s, 2*s
    for i, v in enumerate(vals):
        r, c = divmod(i, 3)
        x0 = gx + c * (cw + gap)
        y0 = gy + r * (chh + gap)
        d.rectangle([x0, y0, x0 + cw, y0 + chh], fill=(49, 50, 68))
        if v:
            fh = chh * v / 100
            d.rectangle([x0, y0 + chh - fh, x0 + cw, y0 + chh], fill=col(v))
    # right: GPU card
    d.rounded_rectangle([52*s, 14*s, 88*s, 44*s], radius=4*s, fill=(24, 24, 37), outline=(49, 50, 68))
    d.rectangle([56*s, 18*s, 74*s, 22*s], fill=(118, 185, 0))  # NVIDIA green chip
    d.rounded_rectangle([56*s, 26*s, 84*s, 32*s], radius=2*s, fill=(49, 50, 68))
    d.rounded_rectangle([56*s, 26*s, int(56*s + 28*s*0.62), 32*s], radius=2*s, fill=(166, 227, 161))
    d.rounded_rectangle([56*s, 35*s, 84*s, 41*s], radius=2*s, fill=(49, 50, 68))
    d.rounded_rectangle([56*s, 35*s, int(56*s + 28*s*0.83), 41*s], radius=2*s, fill=(137, 180, 250))
    # bottom: network arrows (down teal, up peach)
    d.polygon([(20*s, 90*s), (20*s, 62*s), (26*s, 62*s), (26*s, 90*s)], fill=(148, 226, 213))
    d.polygon([(20*s, 62*s), (32*s, 62*s), (26*s, 52*s)], fill=(148, 226, 213))
    d.polygon([(40*s, 62*s), (40*s, 90*s), (46*s, 90*s), (46*s, 62*s)], fill=(250, 179, 135))
    d.polygon([(40*s, 62*s), (52*s, 62*s), (46*s, 52*s)], fill=(250, 179, 135))
    # net history bars
    hs = [30, 55, 40, 70, 90, 60, 80, 45]
    bx = 60*s
    for v in hs:
        h = 4*s + v/100 * 30*s
        d.rectangle([bx, 90*s - h, bx + 2.5*s, 90*s], fill=col(v))
        bx += 3.6*s
    return im

sizes = [16, 24, 32, 48, 64, 128, 256]
imgs = [make(s) for s in sizes]
HERE = os.path.dirname(os.path.abspath(__file__))
imgs[-1].save(
    os.path.join(HERE, "system_console.ico"),
    format="ICO",
    sizes=[(i.width, i.height) for i in imgs],
    append_images=imgs[:-1],
)
imgs[-1].save(os.path.join(HERE, "system_console.png"), format="PNG")
print("icon written")
