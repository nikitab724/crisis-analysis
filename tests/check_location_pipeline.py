"""Opt-in checks against a running real model API and its configured gazetteer.

Sends synthetic texts for extraction only; does not inject posts into the dashboard.
Usage: python tests/check_location_pipeline.py --url http://127.0.0.1:5002
"""

import argparse

import requests

CASES = [
    ("Flood in Austin Texas.", "Austin", "Texas"),
    ("An earthquake struck 48 km southeast of Perryville, Alaska. #perryville #alaska", "Perryville", "Alaska"),
    ("Flood in Portland, Maine.", "Portland", "Maine"),
    ("Flood in Portland, Oregon.", "Portland", "Oregon"),
    ("Flood in Paris, Texas.", "Paris", "Texas"),
    ("Flood in Mexico, Missouri.", "Mexico", "Missouri"),
    ("Flood in McAllen, Texas.", "McAllen", "Texas"),
    ("Typhoon Dujuan kills six in Japan, with landslides in Chiba and Kanagawa.", None, None),
    ("Hurricane Polo moves up Mexico's Pacific coast.", None, None),
    ("Flood in Hamilton, Ontario, Canada.", None, None),
    ("Flood in New Mexico.", None, "New Mexico"),
    ("Flood in West Virginia.", None, "West Virginia"),
    ("Flood in Portland.", None, None),
    ("Flood in Springfield.", None, None),
    ("Flood in Austin.", None, None),
    ("Flood in Georgia.", None, None),
    ("Flood in Georgia, USA.", None, "Georgia"),
    ("Flood in Atlanta, Georgia.", "Atlanta", "Georgia"),
    ("Flood in Texas.", None, "Texas"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Running model API URL, not the dashboard URL")
    base = parser.parse_args().url.rstrip("/")
    ready = requests.get(base + "/ready", timeout=15)
    ready.raise_for_status()
    assert ready.json()["status"] == "healthy"
    for text, city, state in CASES:
        response = requests.post(base + "/extract_entities", json={"text": text}, timeout=30)
        response.raise_for_status()
        data = response.json()
        matches = [data, *data.get("all_locations", [])]
        actual = [(match.get("city"), match.get("state")) for match in matches]
        assert data["disasters"], (text, "no disaster detected")
        assert (city, state) in actual, (text, actual)
        assert all(match.get("state") == state for match in matches), (text, actual)
        assert len(actual) == len(set(actual)), (text, "duplicate location", actual)
        assert len(actual) == 1, (text, "city and state counted separately", actual)
        if text in {"Flood in Portland.", "Flood in Springfield.", "Flood in Austin.", "Flood in Georgia."}:
            assert data["location_status"] == "ambiguous", (text, data)
        print(f"PASS: {text} → {actual}; {data['location_detail']}")
    print(f"PASS: {len(CASES)} real NLP + gazetteer location checks.")


if __name__ == "__main__":
    main()
