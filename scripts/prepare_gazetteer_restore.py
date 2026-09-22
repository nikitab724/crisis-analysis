#!/usr/bin/env python3
"""Extract application gazetteer data from a plain PostgreSQL cluster backup.

Only COPY data for the expected public.gazetteer columns is read. Other SQL,
roles, authentication data, and secrets in the backup are never copied/executed.
"""

import argparse
import hashlib
import json
from pathlib import Path

COLUMNS = 'geonameid, name, alternate_list, "countryCode", "stateCode", latitude, longitude, "featureCode", population'
COPY_HEADER = f"COPY public.gazetteer ({COLUMNS}) FROM stdin;"
SCHEMA = """\\set ON_ERROR_STOP on
BEGIN;
-- Intentionally fails if the destination table already exists. No data is replaced.
CREATE TABLE public.gazetteer (
    geonameid bigint NOT NULL,
    name character varying,
    alternate_list character varying,
    "countryCode" character varying,
    "stateCode" character varying,
    latitude double precision,
    longitude double precision,
    "featureCode" character varying,
    population bigint
);
"""
FOOTER = """ALTER TABLE public.gazetteer ADD PRIMARY KEY (geonameid);
CREATE INDEX gazetteer_name_population_idx
    ON public.gazetteer (name, population DESC NULLS LAST, geonameid);
CREATE INDEX gazetteer_state_idx ON public.gazetteer ("stateCode")
    WHERE "featureCode" = 'ADM1';
ALTER TABLE public.gazetteer ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.gazetteer FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.gazetteer TO service_role;
NOTIFY pgrst, 'reload schema';
COMMIT;
ANALYZE public.gazetteer;
"""


def prepare_restore(backup, output, *, all_features=False):
    backup, output = Path(backup), Path(output)
    if backup.resolve() == output.resolve():
        raise ValueError("Output must not replace the source backup.")
    output.parent.mkdir(parents=True, exist_ok=True)
    source_rows = restored_rows = 0
    data_digest = hashlib.sha256()
    found = finished = False
    demo_places = []
    created = False
    try:
        with backup.open(encoding="utf-8", newline="") as source, output.open("x", encoding="utf-8", newline="") as target:
            created = True
            target.write(SCHEMA + COPY_HEADER + "\n")
            for raw_line in source:
                line = raw_line.rstrip("\r\n")
                if not found:
                    if line.startswith("COPY public.gazetteer "):
                        if line != COPY_HEADER:
                            raise ValueError("Unexpected gazetteer COPY columns; inspect the schema before restoring.")
                        found = True
                    continue
                if line == r"\.":
                    finished = True
                    break
                fields = line.split("\t")
                if len(fields) != 9:
                    raise ValueError(f"Invalid gazetteer row {source_rows + 1}: expected nine fields.")
                try:
                    int(fields[0])
                except ValueError:
                    raise ValueError(f"Invalid gazetteer row {source_rows + 1}: expected a numeric ID.") from None
                source_rows += 1
                feature = fields[7]
                if not all_features and not (feature.upper().startswith("PPL") or feature == "ADM1"):
                    continue
                # Preserve PostgreSQL COPY escaping exactly; never interpret rows as SQL.
                encoded = (line + "\n").encode("utf-8")
                target.write(line + "\n")
                data_digest.update(encoded)
                restored_rows += 1
                if fields[1] in ("Austin", "Texas") and fields[4] == "TX":
                    demo_places.append({"id": int(fields[0]), "name": fields[1], "state": fields[4],
                                        "feature": feature, "population": fields[8]})
            if not found or not finished or not restored_rows:
                raise ValueError("Backup has no complete, nonempty gazetteer COPY section.")
            target.write("\\.\n" + FOOTER)
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise
    return {"source_rows": source_rows, "restore_rows": restored_rows,
            "scope": "all_features" if all_features else "app_lookups_PPL_and_ADM1",
            "data_sha256": data_digest.hexdigest(), "output_bytes": output.stat().st_size,
            "demo_places": demo_places, "output": str(output.resolve())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="Read-only source .backup/plain SQL dump")
    parser.add_argument("--output", type=Path, default=Path(".restore/gazetteer.sql"))
    parser.add_argument("--all-features", action="store_true", help="Include even feature types the app never queries")
    args = parser.parse_args()
    try:
        report = prepare_restore(args.backup, args.output, all_features=args.all_features)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Preparation failed: {exc}\n")
    print(json.dumps(report, indent=2))
    print("Prepared only; no database connection or restore has been performed.")


if __name__ == "__main__":
    main()
