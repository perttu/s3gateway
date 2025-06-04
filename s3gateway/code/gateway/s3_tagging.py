#!/usr/bin/env python3
"""
S3 Tagging Support
Implements S3-compatible tagging API endpoints and tag-based replica count management.
"""

import json
import logging
import xml.etree.ElementTree as ET
from typing import Dict, Optional, List, Tuple
from urllib.parse import unquote
import re

logger = logging.getLogger(__name__)


class S3TaggingError(Exception):
    """S3 tagging related errors"""
    pass


class S3TagManager:
    """Manages S3 object and bucket tagging operations"""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def validate_tag_key(self, key: str) -> Tuple[bool, str]:
        """Validate S3 tag key according to AWS rules"""
        if not key:
            return False, "Tag key cannot be empty"
        
        if len(key) > 128:
            return False, "Tag key cannot exceed 128 characters"
        
        # S3 tag keys can contain unicode characters, spaces, and most symbols
        # But cannot start/end with spaces and cannot contain certain control characters
        if key.startswith(' ') or key.endswith(' '):
            return False, "Tag key cannot start or end with spaces"
        
        # Check for control characters
        if any(ord(c) < 32 and c not in '\t\n\r' for c in key):
            return False, "Tag key cannot contain control characters"
        
        return True, ""
    
    def validate_tag_value(self, value: str) -> Tuple[bool, str]:
        """Validate S3 tag value according to AWS rules"""
        if len(value) > 256:
            return False, "Tag value cannot exceed 256 characters"
        
        # Check for control characters
        if any(ord(c) < 32 and c not in '\t\n\r' for c in value):
            return False, "Tag value cannot contain control characters"
        
        return True, ""
    
    def validate_tag_set(self, tags: Dict[str, str]) -> Tuple[bool, str]:
        """Validate a complete tag set"""
        if len(tags) > 10:
            return False, "Cannot have more than 10 tags per object/bucket"
        
        for key, value in tags.items():
            # Validate key
            key_valid, key_error = self.validate_tag_key(key)
            if not key_valid:
                return False, f"Invalid tag key '{key}': {key_error}"
            
            # Validate value
            value_valid, value_error = self.validate_tag_value(value)
            if not value_valid:
                return False, f"Invalid tag value for key '{key}': {value_error}"
        
        # Check for duplicate keys (case-sensitive in S3)
        if len(set(tags.keys())) != len(tags.keys()):
            return False, "Duplicate tag keys are not allowed"
        
        return True, ""
    
    def parse_tag_xml(self, xml_content: str) -> Dict[str, str]:
        """Parse S3 tagging XML into a dictionary"""
        try:
            root = ET.fromstring(xml_content)
            tags = {}
            
            # Handle both TagSet and Tagging root elements
            tag_set = root.find('TagSet') or root.find('.//TagSet') or root
            
            for tag_elem in tag_set.findall('Tag'):
                key_elem = tag_elem.find('Key')
                value_elem = tag_elem.find('Value')
                
                if key_elem is not None and value_elem is not None:
                    key = unquote(key_elem.text or "")
                    value = unquote(value_elem.text or "")
                    tags[key] = value
            
            return tags
            
        except ET.ParseError as e:
            raise S3TaggingError(f"Invalid XML format: {e}")
        except Exception as e:
            raise S3TaggingError(f"Failed to parse tag XML: {e}")
    
    def generate_tag_xml(self, tags: Dict[str, str]) -> str:
        """Generate S3-compatible tagging XML"""
        root = ET.Element("Tagging")
        tag_set = ET.SubElement(root, "TagSet")
        
        for key, value in tags.items():
            tag_elem = ET.SubElement(tag_set, "Tag")
            key_elem = ET.SubElement(tag_elem, "Key")
            key_elem.text = key
            value_elem = ET.SubElement(tag_elem, "Value")
            value_elem.text = value
        
        # Format with proper XML declaration
        xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml_str += ET.tostring(root, encoding='unicode')
        return xml_str
    
    def set_object_tags(self, customer_id: str, bucket_name: str, object_key: str, tags: Dict[str, str]) -> bool:
        """Set tags for an S3 object"""
        try:
            from sqlalchemy import text
            
            # Validate tags
            valid, error_msg = self.validate_tag_set(tags)
            if not valid:
                raise S3TaggingError(error_msg)
            
            # Update object tags in database
            query = text("""
                UPDATE object_metadata 
                SET tags = :tags, updated_at = CURRENT_TIMESTAMP
                WHERE customer_id = :customer_id 
                  AND bucket_name = :bucket_name 
                  AND object_key = :object_key
            """)
            
            result = self.db.execute(query, {
                'customer_id': customer_id,
                'bucket_name': bucket_name,
                'object_key': object_key,
                'tags': json.dumps(tags)
            })
            
            if result.rowcount == 0:
                raise S3TaggingError("Object not found")
            
            self.db.commit()
            logger.info(f"Set tags for object {customer_id}:{bucket_name}/{object_key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set object tags: {e}")
            self.db.rollback()
            raise S3TaggingError(str(e))
    
    def get_object_tags(self, customer_id: str, bucket_name: str, object_key: str) -> Dict[str, str]:
        """Get tags for an S3 object"""
        try:
            from sqlalchemy import text
            
            query = text("""
                SELECT tags
                FROM object_metadata 
                WHERE customer_id = :customer_id 
                  AND bucket_name = :bucket_name 
                  AND object_key = :object_key
            """)
            
            result = self.db.execute(query, {
                'customer_id': customer_id,
                'bucket_name': bucket_name,
                'object_key': object_key
            }).fetchone()
            
            if not result:
                raise S3TaggingError("Object not found")
            
            tags_json = result[0] or "{}"
            return json.loads(tags_json)
            
        except Exception as e:
            logger.error(f"Failed to get object tags: {e}")
            raise S3TaggingError(str(e))
    
    def delete_object_tags(self, customer_id: str, bucket_name: str, object_key: str) -> bool:
        """Delete all tags for an S3 object"""
        try:
            from sqlalchemy import text
            
            query = text("""
                UPDATE object_metadata 
                SET tags = '{}', updated_at = CURRENT_TIMESTAMP
                WHERE customer_id = :customer_id 
                  AND bucket_name = :bucket_name 
                  AND object_key = :object_key
            """)
            
            result = self.db.execute(query, {
                'customer_id': customer_id,
                'bucket_name': bucket_name,
                'object_key': object_key
            })
            
            if result.rowcount == 0:
                raise S3TaggingError("Object not found")
            
            self.db.commit()
            logger.info(f"Deleted tags for object {customer_id}:{bucket_name}/{object_key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete object tags: {e}")
            self.db.rollback()
            raise S3TaggingError(str(e))
    
    def set_bucket_tags(self, customer_id: str, bucket_name: str, tags: Dict[str, str]) -> bool:
        """Set tags for an S3 bucket"""
        try:
            from sqlalchemy import text
            
            # Validate tags
            valid, error_msg = self.validate_tag_set(tags)
            if not valid:
                raise S3TaggingError(error_msg)
            
            # Update bucket tags in database
            query = text("""
                UPDATE buckets 
                SET tags = :tags, updated_at = CURRENT_TIMESTAMP
                WHERE customer_id = :customer_id 
                  AND bucket_name = :bucket_name
            """)
            
            result = self.db.execute(query, {
                'customer_id': customer_id,
                'bucket_name': bucket_name,
                'tags': json.dumps(tags)
            })
            
            if result.rowcount == 0:
                raise S3TaggingError("Bucket not found")
            
            self.db.commit()
            logger.info(f"Set tags for bucket {customer_id}:{bucket_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set bucket tags: {e}")
            self.db.rollback()
            raise S3TaggingError(str(e))
    
    def get_bucket_tags(self, customer_id: str, bucket_name: str) -> Dict[str, str]:
        """Get tags for an S3 bucket"""
        try:
            from sqlalchemy import text
            
            query = text("""
                SELECT tags
                FROM buckets 
                WHERE customer_id = :customer_id 
                  AND bucket_name = :bucket_name
            """)
            
            result = self.db.execute(query, {
                'customer_id': customer_id,
                'bucket_name': bucket_name
            }).fetchone()
            
            if not result:
                raise S3TaggingError("Bucket not found")
            
            tags_json = result[0] or "{}"
            return json.loads(tags_json)
            
        except Exception as e:
            logger.error(f"Failed to get bucket tags: {e}")
            raise S3TaggingError(str(e))
    
    def delete_bucket_tags(self, customer_id: str, bucket_name: str) -> bool:
        """Delete all tags for an S3 bucket"""
        try:
            from sqlalchemy import text
            
            query = text("""
                UPDATE buckets 
                SET tags = '{}', updated_at = CURRENT_TIMESTAMP
                WHERE customer_id = :customer_id 
                  AND bucket_name = :bucket_name
            """)
            
            result = self.db.execute(query, {
                'customer_id': customer_id,
                'bucket_name': bucket_name
            })
            
            if result.rowcount == 0:
                raise S3TaggingError("Bucket not found")
            
            self.db.commit()
            logger.info(f"Deleted tags for bucket {customer_id}:{bucket_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete bucket tags: {e}")
            self.db.rollback()
            raise S3TaggingError(str(e))


class ReplicaCountManager:
    """Manages replica count based on S3 tags and LocationConstraint"""
    
    def __init__(self, db_session, replication_manager):
        self.db = db_session
        self.replication_manager = replication_manager
    
    def extract_replica_count_from_tags(self, tags: Dict[str, str]) -> Optional[int]:
        """Extract replica count from object/bucket tags"""
        # Check various tag names that might specify replica count
        replica_tag_names = [
            'replica-count',
            'replica_count', 
            'replication-count',
            'replication_count',
            'replicas',
            'x-replica-count'
        ]
        
        for tag_name in replica_tag_names:
            if tag_name in tags:
                try:
                    replica_count = int(tags[tag_name])
                    if replica_count >= 1:
                        return replica_count
                    else:
                        logger.warning(f"Invalid replica count in tag {tag_name}: {replica_count} (must be >= 1)")
                except ValueError:
                    logger.warning(f"Invalid replica count value in tag {tag_name}: {tags[tag_name]}")
        
        return None
    
    def get_current_replica_zones(self, customer_id: str, bucket_name: str, object_key: str) -> List[str]:
        """Get current replica zones for an object"""
        try:
            from sqlalchemy import text
            
            query = text("""
                SELECT replicas
                FROM object_metadata 
                WHERE customer_id = :customer_id 
                  AND bucket_name = :bucket_name 
                  AND object_key = :object_key
            """)
            
            result = self.db.execute(query, {
                'customer_id': customer_id,
                'bucket_name': bucket_name,
                'object_key': object_key
            }).fetchone()
            
            if not result:
                return []
            
            replicas = json.loads(result[0] or "[]")
            return [replica.get('provider_id') for replica in replicas if replica.get('status') == 'active']
            
        except Exception as e:
            logger.error(f"Failed to get current replica zones: {e}")
            return []
    
    def get_allowed_zones_from_location_constraint(self, customer_id: str, bucket_name: str) -> List[str]:
        """Get allowed zones from LocationConstraint in priority order"""
        try:
            from location_constraint import LocationConstraintManager, LocationConstraintParser
            
            location_manager = LocationConstraintManager(self.db)
            policy = location_manager.get_location_constraint(customer_id, bucket_name)
            
            if not policy:
                # Default to FI-HEL if no constraint
                return ['fi-hel-st-1']
            
            # Get the location constraint string and parse it
            constraint_str = ','.join(policy.get('location_constraint', ['fi']))
            parser = LocationConstraintParser()
            
            success, locations, errors = parser.parse_location_constraint(constraint_str)
            if not success:
                logger.error(f"Failed to parse location constraint: {errors}")
                return ['fi-hel-st-1']
            
            # Resolve each location to zones in order
            zones = []
            for location in locations:
                zone = parser.resolve_location_to_zone(location)
                zones.append(zone)
            
            return zones
            
        except Exception as e:
            logger.error(f"Failed to get allowed zones from location constraint: {e}")
            return ['fi-hel-st-1']
    
    def process_tag_based_replica_count_change(self, customer_id: str, bucket_name: str, 
                                             object_key: str, new_tags: Dict[str, str]) -> List[str]:
        """Process replica count change based on new tags"""
        
        # Extract replica count from tags
        new_replica_count = self.extract_replica_count_from_tags(new_tags)
        
        if new_replica_count is None:
            logger.info(f"No replica count specified in tags for {customer_id}:{bucket_name}/{object_key}")
            return []
        
        logger.info(f"Processing replica count change to {new_replica_count} for {customer_id}:{bucket_name}/{object_key}")
        
        # Get current replica zones
        current_zones = self.get_current_replica_zones(customer_id, bucket_name, object_key)
        
        # Get allowed zones from LocationConstraint (in priority order)
        allowed_zones = self.get_allowed_zones_from_location_constraint(customer_id, bucket_name)
        
        if not allowed_zones:
            logger.error(f"No allowed zones found for {customer_id}:{bucket_name}")
            return []
        
        # Validate replica count doesn't exceed allowed zones
        if new_replica_count > len(allowed_zones):
            logger.warning(f"Replica count {new_replica_count} exceeds allowed zones {len(allowed_zones)}, capping to {len(allowed_zones)}")
            new_replica_count = len(allowed_zones)
        
        # Calculate target zones based on replica count and allowed zones
        # Primary region = first in list, additional replicas filled left-to-right
        target_zones = allowed_zones[:new_replica_count]
        
        logger.info(f"Target zones for replica count {new_replica_count}: {target_zones}")
        logger.info(f"Current zones: {current_zones}")
        
        # Process the change using replication manager
        job_ids = self.replication_manager.process_replica_count_change(
            customer_id, bucket_name, object_key, current_zones, target_zones
        )
        
        if job_ids:
            logger.info(f"Scheduled {len(job_ids)} replication jobs: {job_ids}")
        else:
            logger.info("No replication changes needed")
        
        return job_ids
    
    def process_bucket_tag_replica_count_change(self, customer_id: str, bucket_name: str, 
                                               new_tags: Dict[str, str]) -> Dict[str, List[str]]:
        """Process replica count change for all objects in a bucket based on bucket tags"""
        
        # Extract replica count from bucket tags
        new_replica_count = self.extract_replica_count_from_tags(new_tags)
        
        if new_replica_count is None:
            logger.info(f"No replica count specified in bucket tags for {customer_id}:{bucket_name}")
            return {}
        
        logger.info(f"Processing bucket-level replica count change to {new_replica_count} for {customer_id}:{bucket_name}")
        
        # Get allowed zones from LocationConstraint (in priority order)
        allowed_zones = self.get_allowed_zones_from_location_constraint(customer_id, bucket_name)
        
        if not allowed_zones:
            logger.error(f"No allowed zones found for {customer_id}:{bucket_name}")
            return {}
        
        # Validate replica count doesn't exceed allowed zones
        if new_replica_count > len(allowed_zones):
            logger.warning(f"Replica count {new_replica_count} exceeds allowed zones {len(allowed_zones)}, capping to {len(allowed_zones)}")
            new_replica_count = len(allowed_zones)
        
        # Calculate target zones
        target_zones = allowed_zones[:new_replica_count]
        
        # Get current zones from first object (assuming all objects have same zones)
        current_zones = []
        try:
            from sqlalchemy import text
            
            # Get a sample object to determine current replica zones
            query = text("""
                SELECT object_key, replicas
                FROM object_metadata 
                WHERE customer_id = :customer_id 
                  AND bucket_name = :bucket_name
                ORDER BY created_at ASC
                LIMIT 1
            """)
            
            result = self.db.execute(query, {
                'customer_id': customer_id,
                'bucket_name': bucket_name
            }).fetchone()
            
            if result:
                sample_object_key = result[0]
                replicas = json.loads(result[1] or "[]")
                current_zones = [replica.get('provider_id') for replica in replicas if replica.get('status') == 'active']
                logger.info(f"Sample object {sample_object_key} has current zones: {current_zones}")
            
        except Exception as e:
            logger.error(f"Failed to get current zones for bucket: {e}")
            return {}
        
        # Determine if this is a large operation that benefits from bulk processing
        object_count = self.replication_manager.get_object_count_in_bucket(customer_id, bucket_name)
        use_bulk_operations = object_count > 10  # Use bulk operations for buckets with many objects
        
        logger.info(f"Bucket has {object_count} objects, using {'bulk' if use_bulk_operations else 'individual'} operations")
        
        # For bulk operations, use enhanced bucket-level deletion
        if use_bulk_operations:
            # Use bucket-level replica count change which supports bulk deletion
            job_ids = self.replication_manager.process_bucket_replica_count_change(
                customer_id, bucket_name, current_zones, target_zones, bulk_operations=True
            )
            
            if job_ids:
                logger.info(f"Scheduled {len(job_ids)} bulk replication jobs for bucket")
                return {"bulk_operations": job_ids}
            else:
                logger.info("No bulk replication changes needed")
                return {}
        
        # For smaller buckets, process each object individually
        else:
            try:
                query = text("""
                    SELECT object_key
                    FROM object_metadata 
                    WHERE customer_id = :customer_id 
                      AND bucket_name = :bucket_name
                """)
                
                result = self.db.execute(query, {
                    'customer_id': customer_id,
                    'bucket_name': bucket_name
                })
                
                object_keys = [row[0] for row in result]
                
                # Process each object individually
                all_job_ids = {}
                for object_key in object_keys:
                    # For bucket-level changes, we create a synthetic tag set with the replica count
                    synthetic_tags = {'replica-count': str(new_replica_count)}
                    job_ids = self.process_tag_based_replica_count_change(
                        customer_id, bucket_name, object_key, synthetic_tags
                    )
                    if job_ids:
                        all_job_ids[object_key] = job_ids
                
                logger.info(f"Processed bucket-level replica count change for {len(object_keys)} objects individually")
                return all_job_ids
                
            except Exception as e:
                logger.error(f"Failed to process bucket tag replica count change: {e}")
                return {}


if __name__ == "__main__":
    # Test the S3 tagging functionality
    print("🏷️  Testing S3 Tagging System")
    print("=============================")
    
    # Test tag validation
    tag_manager = S3TagManager(None)
    
    # Test valid tags
    valid_tags = {
        'Environment': 'production',
        'Team': 'data-engineering',
        'replica-count': '3',
        'backup-schedule': 'daily'
    }
    
    valid, error = tag_manager.validate_tag_set(valid_tags)
    print(f"Valid tag set: {valid} ({error if error else 'OK'})")
    
    # Test invalid tags
    invalid_tags = {
        'Environment': 'production',
        ' BadKey ': 'value',  # Key with leading/trailing spaces
        'TooLongValue': 'x' * 300,  # Value too long
    }
    
    valid, error = tag_manager.validate_tag_set(invalid_tags)
    print(f"Invalid tag set: {valid} ({error})")
    
    # Test XML generation
    xml_output = tag_manager.generate_tag_xml(valid_tags)
    print(f"Generated XML:\n{xml_output}")
    
    # Test XML parsing
    parsed_tags = tag_manager.parse_tag_xml(xml_output)
    print(f"Parsed tags: {parsed_tags}")
    
    # Test replica count extraction
    replica_manager = ReplicaCountManager(None, None)
    
    replica_count = replica_manager.extract_replica_count_from_tags(valid_tags)
    print(f"Extracted replica count: {replica_count}")
    
    print("✅ S3 tagging test completed") 