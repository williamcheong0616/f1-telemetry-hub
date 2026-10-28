"""Render assets/app.ico (the same mark as the dashboard favicon) with the stdlib only."""
import struct
import zlib
from pathlib import Path

RED = (0xE1, 0x06, 0x00)
# favicon path on a 32x32 grid: M7 21l6-10h12l-2 3h-8l-1 2h7l-2 3h-7l-2 2z
POLY = [(7, 21), (13, 11), (25, 11), (23, 14), (15, 14), (14, 16), (21, 16), (19, 19), (12, 19), (10, 21)]
RADIUS = 7
SS = 4  # supersamples per axis


def inside_poly(x, y):
    hit = False
    for (x1, y1), (x2, y2) in zip(POLY, POLY[1:] + POLY[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def inside_rect(x, y):
    cx = min(max(x, RADIUS), 32 - RADIUS)
    cy = min(max(y, RADIUS), 32 - RADIUS)
    return (x - cx) ** 2 + (y - cy) ** 2 <= RADIUS ** 2


def render(size):
    rows = []
    for py in range(size):
        row = bytearray([0])  # PNG filter: none
        for px in range(size):
            bg = fg = 0
            for sy in range(SS):
                for sx in range(SS):
                    x = (px + (sx + 0.5) / SS) * 32 / size
                    y = (py + (sy + 0.5) / SS) * 32 / size
                    if inside_rect(x, y):
                        bg += 1
                        fg += inside_poly(x, y)
            n = SS * SS
            a = bg / n
            w = fg / bg if bg else 0
            row += bytes([round(c + (255 - c) * w) for c in RED]) + bytes([round(a * 255)])
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [render(s) for s in sizes]
    out = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    offset = 6 + 16 * len(images)
    for s, img in zip(sizes, images):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
    for img in images:
        out += img
    path = Path(__file__).resolve().parent.parent / "assets" / "app.ico"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(out)
    print(f"wrote {path} ({len(out)} bytes)")


if __name__ == "__main__":
    main()
