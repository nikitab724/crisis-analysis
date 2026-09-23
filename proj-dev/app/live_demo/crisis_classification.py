"""Explicit, versioned label definitions for the opt-in semantic classifier."""

import os
import re

TAXONOMY_VERSION = "crisis-v2"
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
    "Drowning": "A reported drowning, near-drowning, or person in distress requiring water rescue. Drowning alone does not establish a flood.",
    "Power Outage": "An actual interruption of electricity service, including repeated brief outages or lights flickering from supply problems. An unplugged device, figurative loss of power, or merely forecast bad weather is insufficient.",
}

# This inexpensive candidate filter only decides which posts need model analysis.
# Jev assigns the labels; a word match never establishes that an event is happening.
SEMANTIC_SIGNALS = re.compile(
    r'\b(?:flood\w*|underwater|inundat\w*|submerg\w*|drown\w*|water\s+rescue|'
    r'outages?|blackouts?|electricity|flicker\w*|power\s+(?:cut|out|off|loss|fail)\w*|'
    r'earthquake\w*|aftershock\w*|seismic|tremors?|tsunami\w*|tidal\s+waves?|'
    r'volcan\w*|erupt\w*|lava|landslide\w*|mudslide\w*|rockslide\w*|avalanche\w*|sinkhole\w*|'
    r'hurricane\w*|cyclone\w*|typhoon\w*|tornado\w*|twisters?|funnel\w*|'
    r'heat\s*wave\w*|extreme\s+(?:heat|cold)|cold\s+snap\w*|freez\w*|'
    r'wildfire\w*|fires?|burn\w*|smoke|flames?|blaz\w*|'
    r'pandemic\w*|epidemic\w*|outbreak\w*|infect\w*|'
    r'solar\s+flare\w*|geomagnetic|crash\w*|colli\w*|derail\w*|capsiz\w*|'
    r'evacuat\w*|trapped|emergency|resc\w*|collapsed?|shaking|shook)\b', re.I)


def semantic_candidate(text):
    """Broad wording filter for live throughput; this cannot guarantee full recall."""
    return bool(SEMANTIC_SIGNALS.search(text))


def classification_mode():
    mode = os.environ.get("CRISIS_CLASSIFICATION_MODE", "rules")
    if mode not in ("rules", "jev"):
        raise ValueError("CRISIS_CLASSIFICATION_MODE must be rules or jev.")
    if mode == "jev" and os.environ.get("CRISIS_RELEVANCE_MODE", "off") != "jev":
        raise ValueError("Jev classification requires CRISIS_RELEVANCE_MODE=jev and its API key.")
    return mode
