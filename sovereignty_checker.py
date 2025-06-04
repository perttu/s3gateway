import csv
from collections import defaultdict
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass
from enum import Enum

class ProviderType(Enum):
    CLOUD = "cloud"
    HOSTING = "hosting"
    TELECOM = "telecom"
    STORAGE = "storage"

@dataclass
class Location:
    city: str
    country: str
    provider: str
    provider_type: ProviderType
    has_object_lock: bool
    has_versioning: bool
    is_iso27001: bool
    is_veeam_ready: bool

class SovereigntyChecker:
    def __init__(self, csv_file: str):
        self.locations: Dict[str, List[Location]] = defaultdict(list)
        self.load_data(csv_file)

    def load_data(self, csv_file: str):
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                country = row['Country']
                if country == "Multiple":  # Skip the Multiple category
                    continue
                
                provider = row['Provider']
                locations = [loc.strip() for loc in row['City/Data Center'].split(',')]
                
                # Determine provider type
                provider_type = ProviderType.CLOUD
                if any(x in provider.lower() for x in ['host', 'server']):
                    provider_type = ProviderType.HOSTING
                elif any(x in provider.lower() for x in ['telecom', 'telco']):
                    provider_type = ProviderType.TELECOM
                elif 'storage' in provider.lower():
                    provider_type = ProviderType.STORAGE
                
                for location in locations:
                    loc = Location(
                        city=location,
                        country=country,
                        provider=provider,
                        provider_type=provider_type,
                        has_object_lock=row['Object Lock'] == 'Yes',
                        has_versioning=row['Versioning'] == 'Yes',
                        is_iso27001=row['ISO 27001/GDPR'] == 'Yes',
                        is_veeam_ready=row['Veeam Ready'] == 'Yes'
                    )
                    self.locations[country].append(loc)

    def check_replica_requirements(self, country: str, required_replicas: int) -> Tuple[bool, List[Location]]:
        """Check if a country has enough locations for the required number of replicas."""
        available_locations = sorted(self.locations[country], key=lambda x: x.city)
        if len(available_locations) >= required_replicas:
            return True, available_locations[:required_replicas]
        return False, available_locations

    def suggest_primary_locations(self, country: str, required_replicas: int) -> Dict[str, List[Location]]:
        """Suggest primary locations for replicas based on provider distribution and features."""
        suggestions = {}
        available_locations = sorted(self.locations[country], key=lambda x: x.city)
        
        if len(available_locations) >= required_replicas:
            # Group locations by provider
            provider_locations = defaultdict(list)
            for location in available_locations:
                provider_locations[location.provider].append(location)
            
            # Score locations based on features
            scored_locations = []
            for location in available_locations:
                score = 0
                if location.has_object_lock:
                    score += 2
                if location.has_versioning:
                    score += 2
                if location.is_iso27001:
                    score += 1
                if location.is_veeam_ready:
                    score += 1
                scored_locations.append((location, score))
            
            # Sort by score and provider diversity
            scored_locations.sort(key=lambda x: (-x[1], x[0].provider))
            
            # Select locations trying to maximize provider diversity
            selected_locations = []
            used_providers = set()
            
            for location, _ in scored_locations:
                if len(selected_locations) < required_replicas:
                    if location.provider not in used_providers:
                        selected_locations.append(location)
                        used_providers.add(location.provider)
            
            suggestions['primary'] = selected_locations[:required_replicas]
            suggestions['alternative'] = [loc for loc in available_locations if loc not in selected_locations]
        else:
            suggestions['error'] = f"Not enough locations in {country}. Required: {required_replicas}, Available: {len(available_locations)}"
        
        return suggestions

def format_location(location: Location) -> str:
    """Format location information for display."""
    features = []
    if location.has_object_lock:
        features.append("🔒")
    if location.has_versioning:
        features.append("📝")
    if location.is_iso27001:
        features.append("📋")
    if location.is_veeam_ready:
        features.append("💾")
    
    return f"{location.city} ({location.provider}) {' '.join(features)}"

def main():
    checker = SovereigntyChecker('providers.csv')
    
    print("\n=== Data Sovereignty and Replica Placement Checker ===\n")
    
    # Example checks for different countries
    test_cases = [
        ("Finland", 3),
        ("Germany", 3),
        ("Switzerland", 2),
        ("UK", 3),
        ("France", 3),
        ("Netherlands", 3)
    ]
    
    for country, replicas in test_cases:
        print(f"\nChecking {country} for {replicas} replicas:")
        print("-" * 50)
        
        # Check if country has enough locations
        has_enough, locations = checker.check_replica_requirements(country, replicas)
        
        if has_enough:
            print(f"✓ {country} has enough locations for {replicas} replicas")
            print(f"Available locations: {', '.join(format_location(loc) for loc in locations)}")
            
            # Get primary location suggestions
            suggestions = checker.suggest_primary_locations(country, replicas)
            if 'primary' in suggestions:
                print("\nSuggested primary locations:")
                for i, loc in enumerate(suggestions['primary'], 1):
                    print(f"  {i}. {format_location(loc)}")
                if suggestions['alternative']:
                    print("\nAlternative locations:")
                    print(f"  {', '.join(format_location(loc) for loc in suggestions['alternative'])}")
        else:
            print(f"✗ {country} does not have enough locations for {replicas} replicas")
            print(f"Available locations: {', '.join(format_location(loc) for loc in locations)}")
            print(f"Required: {replicas}, Available: {len(locations)}")

if __name__ == "__main__":
    main() 