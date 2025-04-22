import pandas as pd

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

gazetteer_df = load_gazetteer("US.txt")
gazetteer_df.to_csv("US_gazetteer.csv", index=False)