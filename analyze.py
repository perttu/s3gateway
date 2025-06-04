import csv
from collections import defaultdict
import re

def parse_location(location_str):
    """Parse location string in format 'Country (City1, City2)' into country and cities."""
    if not location_str or location_str == "Unknown":
        return None, []
    
    # Handle special case for Cloudflare R2
    if "no country-specific granularity" in location_str:
        return "EU", ["EU-wide"]
    
    # Handle multiple locations format
    if "Multiple EU regions" in location_str:
        return "Multiple", ["Multiple EU regions"]
    
    # Extract country and cities
    match = re.match(r'([^(]+)\s*\(([^)]+)\)', location_str)
    if match:
        country = match.group(1).strip()
        cities = [city.strip() for city in match.group(2).split(',')]
        return country, cities
    
    return None, []

def analyze_providers():
    # Initialize data structures
    providers_per_country = defaultdict(set)  # Country -> set of providers
    cities_per_country = defaultdict(set)     # Country -> set of cities
    provider_features = defaultdict(dict)     # Provider -> features dict
    
    # Read the CSV file
    with open('providers.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            provider = row['Provider']
            location_str = row['Locations']
            country, cities = parse_location(location_str)
            
            if country:
                providers_per_country[country].add(provider)
                for city in cities:
                    cities_per_country[country].add(city)
            
            # Store provider features
            provider_features[provider] = {
                's3_compatible': row['S3_Compatible'],
                'object_lock': row['Object_Lock'],
                'versioning': row['Versioning'],
                'iso27001': row['ISO_27001_GDPR'],
                'veeam_ready': row['Veeam_Ready'],
                'homepage': row['Homepage'],
                'notes': row['Notes']
            }

    # Print results
    print("\n=== European S3 Storage Provider Analysis ===\n")
    
    # Print summary of provider and city counts
    print("Country Coverage Summary:")
    print("-" * 50)
    print(f"{'Country':<15} {'Providers':<10} {'Cities':<10} {'S3 Compatible':<15}")
    print("-" * 50)
    
    for country in sorted(providers_per_country.keys()):
        if country in ["Multiple", "EU"]:
            continue
        
        s3_compatible_count = sum(1 for p in providers_per_country[country] 
                                if provider_features[p]['s3_compatible'] == "Yes")
        
        print(f"{country:<15} {len(providers_per_country[country]):<10} "
              f"{len(cities_per_country[country]):<10} {s3_compatible_count:<15}")
    
    print("\nDetailed Provider Coverage by Country:")
    print("-" * 50)
    for country in sorted(providers_per_country.keys()):
        if country in ["Multiple", "EU"]:
            continue
            
        print(f"\n{country}:")
        print(f"  Cities ({len(cities_per_country[country])}): {', '.join(sorted(cities_per_country[country]))}")
        print(f"  Providers ({len(providers_per_country[country])}):")
        
        # Group providers by S3 compatibility status
        s3_compatible = []
        s3_unknown = []
        s3_via_3rd_party = []
        
        for provider in sorted(providers_per_country[country]):
            compat = provider_features[provider]['s3_compatible']
            if compat == "Yes":
                s3_compatible.append(provider)
            elif compat == "Via 3rd party":
                s3_via_3rd_party.append(provider)
            else:
                s3_unknown.append(provider)
        
        if s3_compatible:
            print("    S3 Compatible:")
            for provider in s3_compatible:
                print(f"      - {provider}")
        
        if s3_via_3rd_party:
            print("    S3 Compatible via 3rd party:")
            for provider in s3_via_3rd_party:
                print(f"      - {provider}")
        
        if s3_unknown:
            print("    S3 Compatibility Unknown:")
            for provider in s3_unknown:
                print(f"      - {provider}")

    print("\nCountries with Most Provider Presence:")
    print("-" * 50)
    sorted_countries = sorted(
        [(country, len(providers)) for country, providers in providers_per_country.items() if country not in ["Multiple", "EU"]],
        key=lambda x: x[1],
        reverse=True
    )
    for country, count in sorted_countries:
        print(f"{country}: {count} providers")

    print("\nProvider Features Summary:")
    print("-" * 50)
    feature_counts = defaultdict(int)
    for provider, features in provider_features.items():
        if features['s3_compatible'] == "Yes":
            feature_counts['s3_compatible'] += 1
        if features['object_lock'] == "Yes":
            feature_counts['object_lock'] += 1
        if features['versioning'] == "Yes":
            feature_counts['versioning'] += 1
        if features['iso27001'] == "Yes":
            feature_counts['iso27001'] += 1
        if features['veeam_ready'] == "Yes":
            feature_counts['veeam_ready'] += 1
    
    print(f"S3 Compatible: {feature_counts['s3_compatible']} providers")
    print(f"Object Lock: {feature_counts['object_lock']} providers")
    print(f"Versioning: {feature_counts['versioning']} providers")
    print(f"ISO 27001/GDPR: {feature_counts['iso27001']} providers")
    print(f"Veeam Ready: {feature_counts['veeam_ready']} providers")

if __name__ == "__main__":
    analyze_providers() 