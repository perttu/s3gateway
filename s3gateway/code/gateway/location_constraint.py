#!/usr/bin/env python3
"""
LocationConstraint Parser and Manager
Handles S3 LocationConstraint with comma-separated regions/zones for bucket placement and replication control.
"""

import json
import logging
import re
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class LocationType(Enum):
    REGION = "region"
    ZONE = "zone"


@dataclass
class Location:
    """Represents a geographic location (region or zone)"""
    name: str
    type: LocationType
    country: str
    region: str  # Parent region for zones
    zones: List[str] = None  # Available zones for regions
    
    def __post_init__(self):
        if self.zones is None:
            self.zones = []


class LocationConstraintParser:
    """
    Parses and validates S3 LocationConstraint with support for:
    - Comma-separated regions/zones: "fi,de-fra,fr" 
    - Order-based priority: First is primary, others for replication
    - Cross-border replication control based on specified countries
    """
    
    def __init__(self):
        # Available regions and zones (could be loaded from config)
        self.available_locations = {
            # Finland
            'fi': Location('fi', LocationType.REGION, 'Finland', 'fi', ['fi-hel-st-1', 'fi-hel-uc-1', 'fi-hel-hz-1']),
            'fi-hel': Location('fi-hel', LocationType.REGION, 'Finland', 'fi-hel', ['fi-hel-st-1', 'fi-hel-uc-1', 'fi-hel-hz-1']),
            'fi-hel-st-1': Location('fi-hel-st-1', LocationType.ZONE, 'Finland', 'fi-hel'),
            'fi-hel-uc-1': Location('fi-hel-uc-1', LocationType.ZONE, 'Finland', 'fi-hel'),
            'fi-hel-hz-1': Location('fi-hel-hz-1', LocationType.ZONE, 'Finland', 'fi-hel'),
            
            # Germany
            'de': Location('de', LocationType.REGION, 'Germany', 'de', ['de-fra-st-1', 'de-fra-uc-1', 'de-fra-hz-1']),
            'de-fra': Location('de-fra', LocationType.REGION, 'Germany', 'de-fra', ['de-fra-st-1', 'de-fra-uc-1', 'de-fra-hz-1']),
            'de-fra-st-1': Location('de-fra-st-1', LocationType.ZONE, 'Germany', 'de-fra'),
            'de-fra-uc-1': Location('de-fra-uc-1', LocationType.ZONE, 'Germany', 'de-fra'),
            'de-fra-hz-1': Location('de-fra-hz-1', LocationType.ZONE, 'Germany', 'de-fra'),
            
            # France
            'fr': Location('fr', LocationType.REGION, 'France', 'fr', ['fr-par-st-1', 'fr-par-uc-1', 'fr-par-hz-1']),
            'fr-par': Location('fr-par', LocationType.REGION, 'France', 'fr-par', ['fr-par-st-1', 'fr-par-uc-1', 'fr-par-hz-1']),
            'fr-par-st-1': Location('fr-par-st-1', LocationType.ZONE, 'France', 'fr-par'),
            'fr-par-uc-1': Location('fr-par-uc-1', LocationType.ZONE, 'France', 'fr-par'),
            'fr-par-hz-1': Location('fr-par-hz-1', LocationType.ZONE, 'France', 'fr-par'),
        }
    
    def parse_location_constraint(self, constraint_str: str) -> Tuple[bool, List[Location], List[str]]:
        """
        Parse LocationConstraint string into validated locations.
        
        Args:
            constraint_str: Comma-separated list like "fi,de-fra,fr-par-st-1"
            
        Returns:
            Tuple[bool, List[Location], List[str]]: (success, locations, errors)
        """
        if not constraint_str or constraint_str.strip() == "":
            # Default to Finland if no constraint specified
            return True, [self.available_locations['fi']], []
        
        errors = []
        locations = []
        constraint_str = constraint_str.strip().lower()
        
        # Split by comma and clean up
        location_names = [name.strip() for name in constraint_str.split(',') if name.strip()]
        
        if not location_names:
            errors.append("Empty location constraint")
            return False, [], errors
        
        # Validate each location
        for name in location_names:
            if name not in self.available_locations:
                errors.append(f"Unknown location: {name}")
                continue
            
            location = self.available_locations[name]
            
            # Check for duplicates
            if any(loc.name == name for loc in locations):
                errors.append(f"Duplicate location: {name}")
                continue
            
            locations.append(location)
        
        if errors:
            return False, [], errors
        
        return True, locations, []
    
    def get_countries_from_locations(self, locations: List[Location]) -> Set[str]:
        """Get unique countries from location list"""
        return {loc.country for loc in locations}
    
    def allows_cross_border_replication(self, locations: List[Location]) -> bool:
        """Check if cross-border replication is allowed based on specified locations"""
        countries = self.get_countries_from_locations(locations)
        return len(countries) > 1
    
    def get_primary_location(self, locations: List[Location]) -> Location:
        """Get primary location (first in list)"""
        if not locations:
            return self.available_locations['fi']  # Default
        return locations[0]
    
    def resolve_location_to_zone(self, location: Location) -> str:
        """
        Resolve location to a specific zone.
        If location is a region, pick first available zone.
        If location is a zone, return as-is.
        """
        if location.type == LocationType.ZONE:
            return location.name
        elif location.type == LocationType.REGION and location.zones:
            # Pick first zone for deterministic behavior
            # Could be made random or load-balanced in production
            return location.zones[0]
        else:
            # Fallback to region name if no zones defined
            return location.name
    
    def get_replication_zones(self, locations: List[Location], replica_count: int) -> List[str]:
        """
        Get list of zones for replication based on replica count.
        
        Args:
            locations: Available locations in priority order
            replica_count: Number of replicas desired
            
        Returns:
            List[str]: Zone names for replication (primary first)
        """
        if replica_count <= 0:
            return []
        
        # Limit replica count to available locations
        actual_count = min(replica_count, len(locations))
        
        # Take first N locations based on replica count
        selected_locations = locations[:actual_count]
        
        # Resolve each location to a specific zone
        zones = []
        for location in selected_locations:
            zone = self.resolve_location_to_zone(location)
            zones.append(zone)
        
        return zones
    
    def create_location_policy(self, locations: List[Location], replica_count: int = 1) -> Dict:
        """
        Create replication policy from locations and replica count.
        
        Args:
            locations: Available locations in priority order
            replica_count: Number of replicas
            
        Returns:
            Dict: Policy configuration
        """
        countries = self.get_countries_from_locations(locations)
        primary_location = self.get_primary_location(locations)
        replication_zones = self.get_replication_zones(locations, replica_count)
        
        return {
            "location_constraint": [loc.name for loc in locations],
            "primary_location": primary_location.name,
            "primary_zone": self.resolve_location_to_zone(primary_location),
            "replica_count": replica_count,
            "replication_zones": replication_zones,
            "allowed_countries": list(countries),
            "cross_border_replication": self.allows_cross_border_replication(locations),
            "policy_version": "1.0"
        }
    
    def validate_replication_request(self, locations: List[Location], replica_count: int) -> Tuple[bool, List[str]]:
        """
        Validate a replication request.
        
        Args:
            locations: Available locations
            replica_count: Requested replica count
            
        Returns:
            Tuple[bool, List[str]]: (success, errors)
        """
        errors = []
        
        if replica_count <= 0:
            errors.append("Replica count must be positive")
        
        if replica_count > len(locations):
            errors.append(f"Replica count ({replica_count}) exceeds available locations ({len(locations)})")
        
        # Check for conflicting constraints
        countries = self.get_countries_from_locations(locations)
        if len(countries) > 1:
            # Cross-border replication - additional validation could be added
            logger.info(f"Cross-border replication requested across: {countries}")
        
        return len(errors) == 0, errors


class LocationConstraintManager:
    """
    Manages bucket location constraints and replication policies in database.
    """
    
    def __init__(self, db_session):
        self.db = db_session
        self.parser = LocationConstraintParser()
    
    def store_location_constraint(self, customer_id: str, logical_name: str, 
                                 locations: List[Location], replica_count: int = 1) -> bool:
        """
        Store location constraint in database.
        
        Args:
            customer_id: Customer identifier
            logical_name: Logical bucket name
            locations: Available locations
            replica_count: Number of replicas
            
        Returns:
            bool: Success status
        """
        try:
            from sqlalchemy import text
            
            policy = self.parser.create_location_policy(locations, replica_count)
            
            query = text("""
                INSERT INTO bucket_location_constraints 
                (customer_id, logical_name, location_constraint, replication_policy, created_at)
                VALUES (:customer_id, :logical_name, :location_constraint, :replication_policy, CURRENT_TIMESTAMP)
                ON CONFLICT (customer_id, logical_name)
                DO UPDATE SET 
                    location_constraint = :location_constraint,
                    replication_policy = :replication_policy,
                    updated_at = CURRENT_TIMESTAMP
            """)
            
            self.db.execute(query, {
                'customer_id': customer_id,
                'logical_name': logical_name,
                'location_constraint': ','.join([loc.name for loc in locations]),
                'replication_policy': json.dumps(policy)
            })
            
            self.db.commit()
            logger.info(f"Stored location constraint for {customer_id}:{logical_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store location constraint: {e}")
            self.db.rollback()
            return False
    
    def get_location_constraint(self, customer_id: str, logical_name: str) -> Optional[Dict]:
        """
        Get location constraint for a bucket.
        
        Args:
            customer_id: Customer identifier
            logical_name: Logical bucket name
            
        Returns:
            Optional[Dict]: Location policy or None
        """
        try:
            from sqlalchemy import text
            
            query = text("""
                SELECT replication_policy
                FROM bucket_location_constraints 
                WHERE customer_id = :customer_id AND logical_name = :logical_name
            """)
            
            result = self.db.execute(query, {
                'customer_id': customer_id,
                'logical_name': logical_name
            }).fetchone()
            
            if result:
                return json.loads(result[0])
            return None
            
        except Exception as e:
            logger.error(f"Failed to get location constraint: {e}")
            return None
    
    def update_replica_count(self, customer_id: str, logical_name: str, new_replica_count: int) -> bool:
        """
        Update replica count for existing bucket.
        
        Args:
            customer_id: Customer identifier
            logical_name: Logical bucket name
            new_replica_count: New replica count
            
        Returns:
            bool: Success status
        """
        try:
            # Get current policy
            current_policy = self.get_location_constraint(customer_id, logical_name)
            if not current_policy:
                logger.error(f"No location constraint found for {customer_id}:{logical_name}")
                return False
            
            # Parse current locations
            constraint_str = ','.join(current_policy['location_constraint'])
            success, locations, errors = self.parser.parse_location_constraint(constraint_str)
            
            if not success:
                logger.error(f"Failed to parse current constraint: {errors}")
                return False
            
            # Validate new replica count
            valid, validation_errors = self.parser.validate_replication_request(locations, new_replica_count)
            if not valid:
                logger.error(f"Invalid replica count: {validation_errors}")
                return False
            
            # Create updated policy
            updated_policy = self.parser.create_location_policy(locations, new_replica_count)
            
            # Store updated policy
            from sqlalchemy import text
            
            query = text("""
                UPDATE bucket_location_constraints 
                SET replication_policy = :replication_policy, 
                    updated_at = CURRENT_TIMESTAMP
                WHERE customer_id = :customer_id AND logical_name = :logical_name
            """)
            
            self.db.execute(query, {
                'customer_id': customer_id,
                'logical_name': logical_name,
                'replication_policy': json.dumps(updated_policy)
            })
            
            self.db.commit()
            logger.info(f"Updated replica count to {new_replica_count} for {customer_id}:{logical_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update replica count: {e}")
            self.db.rollback()
            return False


if __name__ == "__main__":
    # Test the location constraint parser
    print("🌍 Location Constraint Parser Tests")
    print("==================================")
    
    parser = LocationConstraintParser()
    
    # Test cases
    test_cases = [
        ("fi", "Single region"),
        ("fi,de", "Two regions (cross-border)"),
        ("fi-hel,de-fra", "Two specific regions"),
        ("fi-hel-st-1,de-fra-uc-1", "Two specific zones"),
        ("fi,de,fr", "Three regions"),
        ("fi-hel-st-1", "Single zone"),
        ("invalid-region", "Invalid region"),
        ("fi,fi", "Duplicate region"),
        ("", "Empty constraint"),
    ]
    
    for constraint, description in test_cases:
        print(f"\nTest: {description}")
        print(f"Constraint: '{constraint}'")
        
        success, locations, errors = parser.parse_location_constraint(constraint)
        
        if success:
            print(f"✅ Success: {len(locations)} location(s)")
            for i, loc in enumerate(locations):
                zone = parser.resolve_location_to_zone(loc)
                print(f"  {i+1}. {loc.name} ({loc.type.value}) -> {zone} [{loc.country}]")
            
            # Test replication policies
            for replica_count in [1, 2, len(locations), len(locations) + 1]:
                policy = parser.create_location_policy(locations, replica_count)
                zones = policy['replication_zones']
                print(f"    Replica count {replica_count}: {zones}")
                
                if policy['cross_border_replication']:
                    print(f"    Cross-border: {policy['allowed_countries']}")
        else:
            print(f"❌ Failed: {errors}")
    
    print("\n✅ Location constraint parsing ensures:")
    print("• Order-based priority (first = primary)")
    print("• Flexible region/zone specification")
    print("• Cross-border replication control")
    print("• Replica count validation")
    print("• Deterministic zone selection") 