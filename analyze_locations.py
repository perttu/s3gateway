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

def is_eu_country(country):
    eu_countries = {
        'Austria', 'Belgium', 'Bulgaria', 'Croatia', 'Cyprus', 'Czech Republic',
        'Denmark', 'Estonia', 'Finland', 'France', 'Germany', 'Greece', 'Hungary',
        'Ireland', 'Italy', 'Latvia', 'Lithuania', 'Luxembourg', 'Malta',
        'Netherlands', 'Poland', 'Portugal', 'Romania', 'Slovakia', 'Slovenia',
        'Spain', 'Sweden'
    }
    return country in eu_countries

def analyze_locations():
    # Initialize counters and data structures
    unique_cities = defaultdict(set)  # Country -> set of unique cities
    providers_per_country = defaultdict(set)  # Country -> set of providers
    eu_cities = set()
    swiss_cities = set()
    uk_cities = set()
    
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
                    unique_cities[country].add(city)
                    
                    if is_eu_country(country):
                        eu_cities.add(f"{city}, {country}")
                    elif country == 'Switzerland':
                        swiss_cities.add(f"{city}, {country}")
                    elif country == 'UK':
                        uk_cities.add(f"{city}, {country}")

    # Print results
    print("\n=== European S3 Storage Location Analysis ===\n")
    
    print("Total Coverage:")
    print(f"Total European Cities: {sum(len(cities) for cities in unique_cities.values())}")
    print(f"EU Cities (excluding UK and Switzerland): {len(eu_cities)}")
    print(f"Swiss Cities: {len(swiss_cities)}")
    print(f"UK Cities: {len(uk_cities)}")
    
    print("\nCities and Providers by Country:")
    print("-" * 50)
    for country, cities in sorted(unique_cities.items()):
        print(f"\n{country}:")
        print(f"  Cities ({len(cities)}): {', '.join(sorted(cities))}")
        print(f"  Providers ({len(providers_per_country[country])}):")
        for provider in sorted(providers_per_country[country]):
            print(f"    - {provider}")

    print("\nCountries with Most Provider Presence:")
    print("-" * 50)
    sorted_countries = sorted(providers_per_country.items(), key=lambda x: len(x[1]), reverse=True)
    for country, providers in sorted_countries:
        print(f"{country}: {len(providers)} providers")

if __name__ == "__main__":
    analyze_locations() 