import pandas as pd
import locationtagger

#load gazetteer

US_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia"
}

columns = [
    "geonameid",
    "name",
    "asciiname",
    "alternatenames",
    "latitude",
    "longitude",
    "featureClass",
    "featureCode",
    "countryCode",
    "cc2",
    "stateCode",
    "admin2Code",
    "admin3Code",
    "admin4Code",
    "population",
    "elevation",
    "dem",
    "timezone",
    "modificationDate"
]

dtypes = {
    "geonameid": "int64",
    "name": "string",
    "asciiname": "string",
    "alternatenames": "string",
    "latitude": "float64",
    "longitude": "float64",
    "featureClass": "string",
    "featureCode": "string",
    "countryCode": "string",
    "cc2": "string",
    "stateCode": "string",
    "admin2Code": "string",
    "admin3Code": "string",
    "admin4Code": "string",
    "population": "int64",
    "elevation": "float64",      # or "Int64" if you want nullable integer
    "dem": "int64",
    "timezone": "string",
    "modificationDate": "string" # Could parse as date later doesn't matter too much though
}

def load_gazetteer(filename): #"../data/US.txt"
    gazetteer_df = pd.read_csv(filename, 
                            sep="\t",
                            names=columns,
                            dtype=dtypes,
                            header=None,
                            low_memory=False)

    gazetteer_df["alternate_list"] = gazetteer_df["alternatenames"] \
        .fillna("") \
        .apply(lambda x: x.split(","))

    gazetteer_df = gazetteer_df[[
        "geonameid",
        "name",
        "alternate_list",
        "countryCode",
        "stateCode",
        "latitude",
        "longitude",
        "featureCode",
        "population"
    ]]

    return gazetteer_df

def build_location_dict(gazetteer_df):
    #building dictionary once

    location_dict = {}
    for i, row in gazetteer_df.iterrows():
        if pd.notna(row["name"]):
            main = row["name"].lower()
            location_dict.setdefault(main, []).append(i)

        alt_list = row["alternate_list"]
        if alt_list is not None and isinstance(alt_list, list):
            for alt in alt_list:
                alt_lower = alt.strip().lower()
                if alt_lower:
                    location_dict.setdefault(alt_lower, []).append(i)
    return location_dict

def lookup_city_state_country(loc_text, gaz_df, loc_dict):
    if not loc_text:
        return None

    normed = loc_text.lower().strip()
    if normed not in loc_dict:
        return None

    row_indices = loc_dict[normed]
    if not row_indices:
        return None

    matches = gaz_df.loc[row_indices]
    if matches.empty:
        return None

    best = matches.sort_values("population", ascending=False).iloc[0]
    feature_code = best["featureCode"]
    place_name   = best["name"]
    country_code = best["countryCode"]
    admin1_code  = best["stateCode"]

    city_name = None
    state_name = None
    region = None

    if pd.isna(feature_code):
        city_name = place_name
    else:
        feature_code = str(feature_code)  # Ensure it's a string
        if feature_code == "ADM1":
            # State-level record: no city, state from admin1_code.
            city_name = None
            if admin1_code in US_STATE_NAMES:
                state_name = US_STATE_NAMES[admin1_code]
            else:
                state_name = admin1_code
        elif feature_code.startswith("PPL"):
            # Populated place: assign the place name as city,
            # and try to get state from admin1_code.
            city_name = place_name
            if admin1_code in US_STATE_NAMES:
                state_name = US_STATE_NAMES[admin1_code]
            else:
                state_name = None
        elif feature_code.startswith("ADM"):
            # Other administrative levels (e.g., ADM2: county-level)
            city_name = place_name
            if admin1_code in US_STATE_NAMES:
                state_name = US_STATE_NAMES[admin1_code]
            else:
                state_name = None
        else:
            city_name = place_name

    # If no state is found, clear the city so it doesn't duplicate the region,
    # and set region to the returned place_name (unless it's US California).
    all_us_states = [s.lower() for s in US_STATE_NAMES.values()] + [code.lower() for code in US_STATE_NAMES.keys()]

    # Simple region rule: if the entire normalized text is exactly a US state name/abbreviation, don't set a region.
    if not state_name:
        city_name = None
        if normed in all_us_states:
            region = None
        else:
            region = normed.title()  # convert to title-case for display

    if region:
        for state in US_STATE_NAMES.values():
            if state.lower() in region.lower():
                state_name = state  # override or set state to the one found in region
                break
    
    return {
        "city": city_name,
        "state": state_name,
        "region": region,
        "country": country_code
    }

def standardize_row(row, gazetteer_df=None, location_dict=None):
    """
    Process all locations in the row and return location information.
    Returns a dictionary with city, state, region, country for each location.
    """
    # Get the locations list
    locs = row["locations"]
    print("locs before processing in gazetteer: ", locs)


    # If no locations or gazetteer data, return empty values
    if not isinstance(locs, list) or len(locs) == 0 or gazetteer_df is None or location_dict is None:
        return pd.Series({"city": None, "state": None, "region": None, "country": None})
    
    # Process each location
    location_info = []
    for loc_text in locs:
        if not loc_text:
            continue
            
        # Lookup the location
        match_result = lookup_city_state_country(loc_text, gazetteer_df, location_dict)
        
        if match_result and match_result.get("state"):
            location_info.append({
                "location": loc_text,
                "city": match_result["city"],
                "state": match_result["state"],
                "region": match_result["region"],
                "country": match_result["country"]
            })
    
    # If no valid locations found with states, return empty values
    if not location_info:
        return pd.Series({"city": None, "state": None, "region": None, "country": None})
    
    # For backwards compatibility, return the first location's details at the top level
    # and include the full list as a new field
    first_loc = location_info[0]
    
    # Copy the location info list but exclude the first item which is already at the top level
    remaining_locations = location_info[1:] if len(location_info) > 1 else []
    
    result = {
        "city": first_loc["city"],
        "state": first_loc["state"],
        "region": first_loc["region"],
        "country": first_loc["country"],
        "all_locations": remaining_locations  # Only include additional locations beyond the first
    }
    
    #print("result from gazetteer: ", result)
    return pd.Series(result)