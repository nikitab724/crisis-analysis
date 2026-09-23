"""Explicit, versioned label definitions for the opt-in semantic classifier."""

import os

TAXONOMY_VERSION = "crisis-v1"
DISASTER_DEFINITIONS = {
    "Earthquake": "Seismic shaking or an earthquake, including aftershocks.",
    "Tsunami": "A destructive tsunami or seismic sea wave; ordinary coastal flooding is Flood.",
    "Volcanic Eruption": "An erupting volcano, volcanic ash fall, or lava flow.",
    "Landslide": "A landslide, mudslide, rockslide, avalanche, sinkhole, or ground collapse.",
    "Hurricane": "A tropical cyclone, hurricane, or typhoon. A tornado alone is Tornado, not Hurricane.",
    "Tornado": "A tornado, twister, or rotating funnel reaching the ground; ordinary high wind alone is insufficient.",
    "Flood": "Water inundating normally dry land, streets, or buildings, including flash floods and storm surge.",
    "Heatwave": "A sustained period of dangerous extreme heat; an ordinary warm day is insufficient.",
    "Wildfire": "An uncontrolled vegetation, forest, or brush fire; an ordinary building fire alone is insufficient.",
    "Cold Snap": "A period of dangerous extreme cold or a severe freeze.",
    "Pandemic": "A claimed widespread infectious-disease outbreak; an isolated illness or metaphor is insufficient.",
    "Solar Flare": "A solar flare or geomagnetic storm with claimed hazardous effects; ordinary aurora viewing is insufficient.",
    "Transportation Accident": "A serious vehicle, train, aircraft, or ship accident; routine congestion is insufficient.",
}


def classification_mode():
    mode = os.environ.get("CRISIS_CLASSIFICATION_MODE", "rules")
    if mode not in ("rules", "jev"):
        raise ValueError("CRISIS_CLASSIFICATION_MODE must be rules or jev.")
    if mode == "jev" and os.environ.get("CRISIS_RELEVANCE_MODE", "off") != "jev":
        raise ValueError("Jev classification requires CRISIS_RELEVANCE_MODE=jev and its API key.")
    return mode
