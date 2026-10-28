"""Build f1telemetry/circuits.json - circuit outlines for every track in the game - from the
f1-circuits GeoJSON (https://github.com/bacinger/f1-circuits, MIT licence, (c) Tomislav Bacinger).

    python tools/make_circuits.py path/to/f1-circuits.geojson path/to/LICENSE.md

Each outline is projected to local metres (+X east, +Z south, so drawing +Z downwards puts north up),
smoothed, resampled every 10 m and starts where the source line starts (at or near the start/finish line,
in race direction). The app lines these outlines up with the game's own coordinates as you drive.
"""
import json
import math
import sys
from pathlib import Path

# game track id -> f1-circuits id (reverse layouts reuse the forward outline)
GAME_TRACKS = {
    0: "au-1953", 1: "fr-1969", 2: "cn-2004", 3: "bh-2002", 4: "es-1991", 5: "mc-1929", 6: "ca-1978",
    7: "gb-1948", 8: "de-1932", 9: "hu-1986", 10: "be-1925", 11: "it-1922", 12: "sg-2008", 13: "jp-1962",
    14: "ae-2009", 15: "us-2012", 16: "br-1940", 17: "at-1969", 18: "ru-2014", 19: "mx-1962", 20: "az-2016",
    26: "nl-1948", 27: "it-1953", 28: "pt-2008", 29: "sa-2021", 30: "us-2022", 31: "us-2023", 32: "qa-2004",
    42: "es-2026",
}
REVERSE = {39: 7, 40: 17, 41: 26}
STEP = 10.0
R_EARTH = 6371008.8


def project(coords):
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    lon0, lat0 = (min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2
    k = math.pi / 180 * R_EARTH
    return [((lon - lon0) * k * math.cos(math.radians(lat0)), -(lat - lat0) * k) for lon, lat in coords]


def catmull_rom(pts, per_seg=8):
    """Centripetal Catmull-Rom through a closed polyline (keeps every source point)."""
    n, out = len(pts), []
    for i in range(n):
        p0, p1, p2, p3 = pts[(i - 1) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        t0 = 0.0
        t1 = t0 + math.dist(p0, p1) ** 0.5 or 1e-6
        t2 = t1 + math.dist(p1, p2) ** 0.5 or t1 + 1e-6
        t3 = t2 + math.dist(p2, p3) ** 0.5 or t2 + 1e-6
        for s in range(per_seg):
            t = t1 + (t2 - t1) * s / per_seg

            def lerp(a, b, ta, tb):
                w = (t - ta) / (tb - ta) if tb != ta else 0.0
                return (a[0] + (b[0] - a[0]) * w, a[1] + (b[1] - a[1]) * w)
            a1, a2, a3 = lerp(p0, p1, t0, t1), lerp(p1, p2, t1, t2), lerp(p2, p3, t2, t3)
            b1, b2 = lerp(a1, a2, t0, t2), lerp(a2, a3, t1, t3)
            out.append(lerp(b1, b2, t1, t2))
    return out


def resample(pts, step):
    closed = pts + [pts[0]]
    cum = [0.0]
    for a, b in zip(closed, closed[1:]):
        cum.append(cum[-1] + math.dist(a, b))
    total = cum[-1]
    out, j = [], 0
    for i in range(int(total // step)):
        s = i * step
        while cum[j + 1] < s:
            j += 1
        f = (s - cum[j]) / ((cum[j + 1] - cum[j]) or 1)
        a, b = closed[j], closed[j + 1]
        out.append([round(a[0] + (b[0] - a[0]) * f, 1), round(a[1] + (b[1] - a[1]) * f, 1)])
    return out, total


def main(src, licence):
    feats = {f["properties"]["id"]: f for f in json.loads(Path(src).read_text(encoding="utf-8"))["features"]}
    tracks = {}
    for tid, cid in GAME_TRACKS.items():
        f = feats[cid]
        coords = f["geometry"]["coordinates"]
        if coords[0] == coords[-1]:
            coords = coords[:-1]
        pts, total = resample(catmull_rom(project(coords)), STEP)
        tracks[str(tid)] = {"name": f["properties"]["Name"], "source_id": cid,
                            "official_length": f["properties"].get("length"), "length": round(total, 1), "pts": pts}
        print(f"{tid:>3} {cid}  {f['properties']['Name']}: {len(coords)} source points -> {len(pts)}, "
              f"{total:.0f} m (official {f['properties'].get('length')} m)")
    out = {
        "source": "https://github.com/bacinger/f1-circuits",
        "licence": Path(licence).read_text(encoding="utf-8").strip(),  # MIT: the notice travels with the data
        "note": "x east, z south (metres); pts every 10 m from the start of the source line, in race direction",
        "reverse": {str(k): v for k, v in REVERSE.items()},
        "tracks": tracks,
    }
    dest = Path(__file__).resolve().parent.parent / "f1telemetry" / "circuits.json"
    dest.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {dest} ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
