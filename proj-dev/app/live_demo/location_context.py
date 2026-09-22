"""Small, conservative context rules for the existing US gazetteer lookup."""

import re

import pycountry

from gazetteer import US_STATE_NAMES

STATE_CODES = {name.casefold(): code for code, name in US_STATE_NAMES.items()}
STATE_PATTERN = (
    "(?i:" + "|".join(re.escape(name) for name in sorted(STATE_CODES, key=len, reverse=True))
    + ")|" + "|".join(US_STATE_NAMES)
)
STATE_SUFFIX = re.compile(rf"(?P<city>.+?)(?:,\s*|\s+)(?P<state>{STATE_PATTERN})$")

# Country data only: this does not add or replace an NLP component.
FOREIGN_NAMES = {
    value.casefold()
    for country in pycountry.countries if country.alpha_2 != "US"
    for key, value in dict(country).items() if key in {"name", "common_name", "official_name"}
}
FOREIGN_NAMES.update({
    "uk", "england", "scotland", "wales", "russia", "south korea", "north korea",
    "iran", "syria", "vietnam", "laos", "taiwan", "palestine",
})
FOREIGN_NAMES.update(place.name.casefold() for place in pycountry.subdivisions.get(country_code="CA"))
# Georgia remains a supported US state; the country/state ambiguity is unresolved.
FOREIGN_NAMES.difference_update(STATE_CODES)
BROAD_REGIONS = {
    "north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest",
    "midwest", "pacific", "atlantic", "pacific coast", "atlantic coast", "gulf coast",
    "pacific ocean", "atlantic ocean", "united states", "the united states", "usa", "us",
}


def state_code(value):
    value = value.strip()
    if value.casefold() in STATE_CODES:
        return STATE_CODES[value.casefold()]
    # Lowercase ordinary words must not become Indiana, Oregon, or Maine.
    if value.upper() in US_STATE_NAMES and (value.isupper() or value.casefold() not in {"in", "or", "me"}):
        return value.upper()
    return None


def split_place(value):
    """Accept a city/state pair emitted as one entity as well as separate entities."""
    value = " ".join(value.strip("# ,").split())
    if state_code(value):
        return value, None
    match = STATE_SUFFIX.fullmatch(value)
    return (match["city"], state_code(match["state"])) if match else (value, None)


def adjacent_states(place, text):
    """Use only state names/codes immediately following this particular place."""
    pattern = rf"(?<!\w)(?i:{re.escape(place)})(?!\w)(?:,\s*|\s+(?:in\s+)?)(?P<state>{STATE_PATTERN})(?!\w)"
    return {state_code(match["state"]) for match in re.finditer(pattern, text)}


def location_candidates(locations, text):
    """Yield unique (entity, place, state hint) triples without guessing foreign cities."""
    places = [split_place(location) for location in locations]
    foreign_context = any(
        place.casefold() in FOREIGN_NAMES and not hint and not adjacent_states(place, text)
        for place, hint in places
    )
    states = {hint or state_code(place) for place, hint in places} - {None}
    sole_state = next(iter(states)) if len(states) == 1 and not foreign_context else None
    seen = set()
    for location, (place, embedded_hint) in zip(locations, places):
        if not place:
            continue
        hints = {embedded_hint} if embedded_hint else adjacent_states(place, text)
        is_state = state_code(place)
        # International context and broad regions need an explicit local US qualifier.
        if not is_state and not hints and (
            foreign_context or place.casefold() in FOREIGN_NAMES | BROAD_REGIONS
        ):
            continue
        for hint in sorted(hints) if hints else [None if is_state else sole_state]:
            identity = (place.casefold(), hint)
            if identity not in seen:
                seen.add(identity)
                yield location, place, hint
