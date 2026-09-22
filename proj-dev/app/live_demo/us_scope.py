"""Shared US coverage rule for saved reports, aggregates, and dashboard views."""

from gazetteer import US_STATE_NAMES

US_STATES = {name.casefold() for name in US_STATE_NAMES.values()} | {
    code.casefold() for code in US_STATE_NAMES
}


def is_us_location(record):
    """Require explicit US country data and a supported state (50 states or DC)."""
    country = record.get("country")
    state = record.get("state")
    status = record.get("location_status")
    # Older exports and the deterministic fixture have no match-status field.
    status = status.strip().casefold() if isinstance(status, str) else ""
    return (
        isinstance(country, str) and country.strip().upper() == "US"
        and isinstance(state, str) and state.strip().casefold() in US_STATES
        and status in {"", "matched"}
    )


def us_records(frame):
    """Also filter older CSVs on read so excluded records cannot reappear."""
    return frame.loc[[is_us_location(row) for row in frame.to_dict("records")]].copy()
