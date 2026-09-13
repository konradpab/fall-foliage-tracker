"""Regenerate batch/data/landmask.json (dev-only; needs `pip install global-land-mask`).

Produces a 0.25-degree land/water bitmask over a generous Europe bounding box.
The bitmask is resolution-independent input: grid.py samples it by nearest cell,
so changing the forecast grid step does NOT require regenerating this file.
"""
import base64, json, pathlib

LAT0, LAT1, LON0, LON1, STEP = 34.0, 72.0, -12.0, 34.0, 0.25
OUT = pathlib.Path(__file__).resolve().parents[1] / "data" / "landmask.json"


def main() -> None:
    from global_land_mask import globe

    rows = round((LAT1 - LAT0) / STEP)
    cols = round((LON1 - LON0) / STEP)
    bits = bytearray((rows * cols + 7) // 8)
    for r in range(rows):
        lat = LAT0 + (r + 0.5) * STEP
        for c in range(cols):
            lon = LON0 + (c + 0.5) * STEP
            if bool(globe.is_land(lat, lon)):
                i = r * cols + c
                bits[i >> 3] |= 1 << (i & 7)
    OUT.write_text(json.dumps({
        "lat0": LAT0, "lat1": LAT1, "lon0": LON0, "lon1": LON1,
        "step": STEP, "rows": rows, "cols": cols,
        "bits_b64": base64.b64encode(bytes(bits)).decode("ascii"),
    }))
    land = sum(bin(b).count("1") for b in bits)
    print(f"{OUT}: {rows}x{cols} cells, {land} land ({land / (rows * cols):.1%})")


if __name__ == "__main__":
    main()
