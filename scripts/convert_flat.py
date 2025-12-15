import argparse
import csv
from pathlib import Path
import re


DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "providers"
SOURCE_FILE = DATA_DIR / "providers2.csv"
OUTPUT_FILE = DATA_DIR / "providers_flat.csv"

def make_zone_code(country, city, provider, idx):
    # Make a short code: CountryCode-CityCode-idx
    country_code = country[:2].upper()
    city_code = re.sub(r'\W+', '', city.split()[0][:4].upper())
    prov_code = re.sub(r'\W+', '', provider.split()[0][:4].upper())
    return f"{country_code}-{city_code}-{prov_code}-{idx+1}"

def convert_provider_sheet(source: Path = SOURCE_FILE, destination: Path = OUTPUT_FILE):
    with source.open(newline='', encoding='utf-8') as infile, \
         destination.open('w', newline='', encoding='utf-8') as outfile:

        reader = csv.DictReader(infile)
        # Output fields
        fieldnames = [
            'Country', 'Region/City', 'Zone_Code', 'Provider', 'Endpoint',
            'S3_Compatible', 'Object_Lock', 'Versioning', 'ISO_27001_GDPR',
            'Veeam_Ready', 'Notes'
        ]
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            if row['S3_Compatible'].strip().lower() != 'yes':
                continue

            locations = [loc.strip() for loc in row['Locations'].split(',')]
            # Format: Country (City)
            locs_parsed = []
            for loc in locations:
                # Handle location like "France (Paris)"
                m = re.match(r'([\w\s\.-]+)\s*\(([\w\s\.-]+)\)', loc)
                if m:
                    locs_parsed.append((m.group(1).strip(), m.group(2).strip()))
                else:
                    # e.g., just "EU" or "Geneva"
                    parts = loc.split()
                    if len(parts) > 1:
                        locs_parsed.append((parts[0].strip(), ' '.join(parts[1:]).strip()))
                    else:
                        locs_parsed.append(('', loc.strip()))

            for idx, (country, city) in enumerate(locs_parsed):
                # Ignore locations not in EU or UK/CH (optional)
                if country == '' or city == '':
                    continue

                zone_code = make_zone_code(country, city, row['Provider'], idx)
                endpoint = ''  # Could be filled if you have endpoint info per location

                writer.writerow({
                    'Country': country,
                    'Region/City': city,
                    'Zone_Code': zone_code,
                    'Provider': row['Provider'],
                    'Endpoint': endpoint,  # Not available per location in original
                    'S3_Compatible': row['S3_Compatible'],
                    'Object_Lock': row['Object_Lock'],
                    'Versioning': row['Versioning'],
                    'ISO_27001_GDPR': row['ISO_27001_GDPR'],
                    'Veeam_Ready': row['Veeam_Ready'],
                    'Notes': row['Notes'],
                })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flatten provider CSV data.")
    parser.add_argument(
        "--source",
        type=Path,
        default=SOURCE_FILE,
        help="Path to providers2.csv (defaults to data/providers/providers2.csv)",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=OUTPUT_FILE,
        help="Where to write providers_flat.csv",
    )
    args = parser.parse_args()
    convert_provider_sheet(args.source, args.destination)
