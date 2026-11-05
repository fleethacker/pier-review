"""Regenerate the seed berths from surveyed pier positions.

Each FACE below is a real pier face. Its position, direction and length come from OpenStreetMap (ODbL, (c) OpenStreetMap
contributors) and were checked by drawing the face on Mapbox satellite imagery (Maxar), where it lies along the pier
edge with ships moored alongside. A face is the berth frame of mooring/core/schemas/refdata.py: the origin is the end of
the face at the -x side, +x runs along the face to the right of someone standing on the pier facing the water, and
`bearing` is the true bearing of +x. Piers mapped as polygons use their long edge; piers mapped as centrelines use the
longest segment offset by half the pier width (an estimate, shown in `notes`).

What is NOT surveyed: the fittings, fenders and depth profile are the notional Pier 12 layout stretched to the face
length, and the weather is synthetic. Run `python scripts/build_berths.py` and commit the result.
"""

import math
from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parent.parent / "modeling" / "mooring" / "refdata" / "berths"
OSM = "OpenStreetMap contributors (ODbL), way {way}; checked on Mapbox/Maxar satellite imagery"

FACES = [
    dict(id="NAVSTA-NORFOLK-P12-N", file="navsta-norfolk-p12-n.yaml", prefix="P12N", way=623235098,
         name="Pier 12 North face (NAVSTA Norfolk)", lat=36.957533, lon=-76.331655, bearing=99.5, length_m=424.4,
         clear_m=(0, 160), clear_note="A ship is moored about 165-370 m along the face; the west 160 m is clear, just enough for a 155 m destroyer.",
         note="Polygon long edge facing north."),
    dict(id="NAVSTA-NORFOLK-P12-S", file="navsta-norfolk-p12-s.yaml", prefix="P12S", way=623235098,
         name="Pier 12 South face (NAVSTA Norfolk)", lat=36.956497, lon=-76.327035, bearing=279.5, length_m=424.4,
         clear_m=(285, 424.4), clear_note="A ship is moored about 60-280 m along the face; about 140 m is clear at the west end, a little short of a destroyer.",
         note="Polygon long edge facing south."),
    dict(id="NAVBASE-SAN-DIEGO-P7", file="sandiego-pier7.yaml", prefix="SD7", way=477061102,
         name="Pier 7, northwest face (Naval Base San Diego)", lat=32.673967, lon=-117.125825, bearing=54.5, length_m=446.7,
         clear_m=(180, 440), clear_note="A ship is moored over the first 165 m; the rest of the face is clear.",
         note="Mapped as a centreline; pier half width estimated at 14 m from the imagery."),
    dict(id="PEARL-HARBOR-HOTEL-PIER", file="pearl-harbor-hotel-pier.yaml", prefix="HP", way=1262816731,
         name="Hotel Pier, northwest face (Joint Base Pearl Harbor-Hickam)", lat=21.364023, lon=-157.944251, bearing=67.0,
         length_m=404.6, clear_m=(220, 400), clear_note="A tanker is moored about 35-212 m along the face; the inner end is clear.",
         note="Polygon long edge facing northwest."),
    dict(id="YOKOSUKA-FLEET-ACTIVITIES-1", file="yokosuka-pier-1.yaml", prefix="YK1", way=1503791481,
         name="Pier, northeast face (Fleet Activities Yokosuka)", lat=35.292378, lon=139.661501, bearing=138.4, length_m=244.5,
         clear_note="Two warships are moored along the whole face; no clear stretch.",
         note="Longest straight run of an irregular polygon edge facing northeast. Unnamed in OSM."),
    dict(id="ROTA-PIER-1", file="rota-pier-1.yaml", prefix="RT1", way=478953761,
         name="Pier, southwest face (Naval Station Rota)", lat=36.618824, lon=-6.321448, bearing=320.5, length_m=246.3,
         clear_note="A large ship is moored along the whole face; no clear stretch.",
         note="Mapped as a centreline; pier half width estimated at 6 m. Unnamed in OSM."),
    # Commercial ports, added for lesser-known harbours. Same method: OSM face, water side from the way's geometry.
    dict(id="ADEN-MAALLA-JETTY", file="aden-maalla-jetty.yaml", prefix="ADN", way=485538999,
         name="Ma'alla Jetty, northeast face (Port of Aden, Yemen)", lat=12.79955, lon=45.001593, bearing=126.8,
         length_m=260.1, clear_m=(0, 260.1), clear_note="No ship alongside this face.",
         note="Polygon long edge facing northeast, away from the pier area. Commercial wharf."),
    dict(id="DJIBOUTI-DORALEH-MP-E", file="djibouti-doraleh-mp-e.yaml", prefix="DJI", way=235934450,
         name="Doraleh Multipurpose Port, north quay, east berth (Port of Djibouti)", lat=11.600402, lon=43.063122,
         bearing=82.9, section_start_m=800, length_m=405.6, clear_m=(240, 400),
         clear_note="Bulk and container ships are moored along most of the quay; its east end (about 1040-1200 m) is clear.",
         note="East 406 m of the 1206 m straight north quay edge, where the OSM coastline and the port boundary "
              "(way 480879281) coincide; water is on the coastline's right. The split into a berth is ours, not the port's."),
    dict(id="CARTAGENA-MANGA-MUELLE-2", file="cartagena-manga-muelle-2.yaml", prefix="CTG", way=166292803,
         name="Muelle 2, east face (Port of Cartagena, Colombia)", lat=10.404956, lon=-75.531215, bearing=211.5,
         length_m=203.8,
         clear_m=(0, 203.8), clear_note="No ship alongside this face (a cruise ship is on the other face of the pier).",
         note="Mapped as a line; Muelle 3 (way 166292804), 42 m to the west, is the other face of the same finger pier."),
    dict(id="CURACAO-TULA-PIER", file="curacao-tula-pier.yaml", prefix="CUR", way=563308681,
         name="Tula pier, south face (Willemstad, Curacao)", lat=12.105333, lon=-68.9445, bearing=287.1,
         length_m=189.6, clear_m=(0, 189.6), clear_note="No ship alongside.",
         note="Polygon long edge facing south (seamark berth 'Tulapier')."),
    dict(id="PITUFFIK-PIER-S", file="pituffik-pier-s.yaml", prefix="PTF", way=591394303,
         name="Pier, south face (Pituffik Space Base, Greenland)", lat=76.540366, lon=-68.836867, bearing=None,
         end=(76.539389, -68.843749), offset_m=10,
         note="Mapped as a centreline; pier half width assumed to be 10 m. NOT checked on imagery: Mapbox/Maxar has no "
              "high-resolution coverage this far north, so the face, its water side and occupancy are unverified."),
    # Large commercial ports for emergency diverts. Long container quays: the berth is a section of the quay.
    dict(id="JEBEL-ALI-QUAY-NE", file="jebel-ali-quay-ne.yaml", prefix="JBA", way=693749843,
         name="Container quay, northeast end (Jebel Ali Port, UAE)", lat=24.992115, lon=55.072590, bearing=226.2,
         length_m=400.0, clear_m=(0, 150),
         clear_note="Car carriers are moored along most of the 1654 m quay; about 150 m is clear at the northeast end, "
                    "a few metres short of a destroyer.",
         note="Northeast 400 m of a 1654 m straight quay edge mapped as coastline (water on its right). The split into a "
              "berth is ours, not the port's."),
    dict(id="SINGAPORE-PASIR-PANJANG-Q", file="singapore-pasir-panjang-q.yaml", prefix="SGP", way=557975391,
         name="Pasir Panjang container quay (Port of Singapore)", lat=1.272790, lon=103.786558, bearing=301.2,
         section_start_m=700, length_m=400.0, clear_m=(130, 275),
         clear_note="Container ships fill most of the quay; about 145 m is clear between two of them, a little short of a destroyer.",
         note="400 m section (700-1100 m from the southeast end) of a 1263 m straight quay edge mapped as coastline "
              "(water on its right). The split into a berth is ours, not the port's."),
]

FT_PER_M = 3.28084
EARTH_R = 6371000.0


def _dest(lat: float, lon: float, bearing: float, d: float) -> tuple[float, float]:
    la, lo, b, dr = math.radians(lat), math.radians(lon), math.radians(bearing), d / EARTH_R
    la2 = math.asin(math.sin(la) * math.cos(dr) + math.cos(la) * math.sin(dr) * math.cos(b))
    lo2 = lo + math.atan2(math.sin(b) * math.sin(dr) * math.cos(la), math.cos(dr) - math.sin(la) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(h))


def resolve(face: dict) -> dict:
    """Turn a face spec into origin, bearing and length: centrelines get their bearing from `end` and are moved
    `offset_m` toward the water (the +y side); quay sections start `section_start_m` along the quay."""
    face = dict(face)
    if face.get("bearing") is None:
        face["bearing"] = round(_bearing((face["lat"], face["lon"]), face["end"]), 1)
        face["length_m"] = round(_distance((face["lat"], face["lon"]), face["end"]), 1)
    if face.get("offset_m"):
        face["lat"], face["lon"] = _dest(face["lat"], face["lon"], (face["bearing"] - 90) % 360, face["offset_m"])
    if face.get("section_start_m"):
        face["lat"], face["lon"] = _dest(face["lat"], face["lon"], face["bearing"], face["section_start_m"])
    face["lat"], face["lon"] = round(face["lat"], 6), round(face["lon"], 6)
    return face

def build(face: dict, base: dict) -> dict:
    length_ft = round(face["length_m"] * FT_PER_M)
    by_kind = {f["kind"]: f for f in base["fittings"]}
    xs = []  # (x, row, kind)
    for x in range(30, length_ft - 29, 60):
        xs.append((x, "B", "bollard_horn" if (x - 270) % 300 == 0 else "bollard_special_b"))
    for x in range(90, length_ft - 29, 120):
        xs.append((x, "M", "bollard_special_a"))
    xs.append((120, "C", "cleat_42"))
    xs.append((round((length_ft - 120) / 60) * 60, "C", "cleat_42"))
    counts = {"B": 0, "M": 0, "C": 0}
    fits = []
    for x, row, kind in sorted(xs, key=lambda t: (t[0], t[1])):
        counts[row] += 1
        proto = by_kind[kind]
        f = {k: v for k, v in proto.items() if k not in ("fitting_id", "x_ft", "condition")}
        fits.append({"fitting_id": f"{face['prefix']}-{row}{counts[row]:02d}", "kind": kind, "x_ft": x, **{k: v for k, v in f.items() if k != "kind"}})
    # keep the suspect bollard of the demo layout (a fitting the safety checks flag) at the same place
    for f in fits:
        if f["kind"] == "bollard_special_b" and f["x_ft"] == 630:
            f["condition"] = "suspect"
    fenders = []
    for i, frac in enumerate((0.333, 0.48, 0.63), start=1):
        proto = dict(base["fenders"][i - 1])
        proto.update(fender_id=f"{face['prefix']}-CAMEL-{i}", x_ft=round(frac * length_ft / 10) * 10)
        fenders.append(proto)
    return {
        "berth_id": face["id"],
        "name": face["name"],
        "face_bearing_true_deg": face["bearing"],
        "origin_lat": face["lat"],
        "origin_lon": face["lon"],
        "face_length_ft": length_ft,
        "deck_height_mllw_ft": base["deck_height_mllw_ft"],
        "depth_profile": [{"x_ft": 0, "depth_mllw_ft": 42}, {"x_ft": length_ft // 2, "depth_mllw_ft": 45},
                          {"x_ft": length_ft, "depth_mllw_ft": 47}],
        "fittings": fits,
        "fenders": fenders,
        "structure": base["structure"],
        "env_station_ids": ({"wind": "8638614", "current": "cb0402", "water_level": "8638610"}
                            if face["id"].startswith("NAVSTA") else
                            {"wind": f"MOCK-{face['prefix']}-WIND", "current": f"MOCK-{face['prefix']}-CURRENT",
                             "water_level": f"MOCK-{face['prefix']}-LEVEL"}),
        "provenance": {
            "source": OSM.format(way=face["way"]),
            "url": f"https://www.openstreetmap.org/way/{face['way']}",
            "confidence": "mock",
            "notes": f"Position, direction and length of the face are surveyed ({face['note']}). Fittings, fenders and "
                     "depths are the notional Pier 12 layout stretched to the face length; weather is synthetic. "
                     f"{('Occupancy in the imagery: ' + face['clear_note'] + ' ') if face.get('clear_note') else ''}"
                     "Not for operational use.",
        },
        **({"clear_stretch": {"start_ft": round(face["clear_m"][0] * FT_PER_M),
                              "end_ft": min(round(face["clear_m"][1] * FT_PER_M), length_ft),
                              "note": face["clear_note"]}} if face.get("clear_m") else {}),
    }


def main() -> None:
    base = yaml.safe_load((OUT / "navsta-norfolk-p12-s.yaml").read_text())
    for face in map(resolve, FACES):
        text = "# Berth with a surveyed face position (see scripts/build_berths.py); layout and depths are notional.\n"
        text += yaml.safe_dump(build(face, base), sort_keys=False)
        (OUT / face["file"]).write_text(text)
        print("wrote", face["file"])


if __name__ == "__main__":
    main()
