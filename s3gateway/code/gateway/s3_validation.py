#!/usr/bin/env python3
"""
S3 Naming Validation Module
Validates bucket names and object keys according to AWS S3 naming conventions
to prevent backend creation failures.
"""

import re
import urllib.parse
from typing import Dict, List, Optional, Tuple


class S3ValidationError(Exception):
    """Custom exception for S3 naming validation errors"""
    def __init__(self, message: str, error_code: str = "InvalidRequest"):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


class S3NameValidator:
    """S3 naming validation according to AWS S3 naming conventions"""
    
    # Bucket name constraints
    MIN_BUCKET_LENGTH = 3
    MAX_BUCKET_LENGTH = 63
    
    # Object key constraints  
    MAX_OBJECT_KEY_LENGTH = 1024
    
    # Forbidden bucket name patterns
    FORBIDDEN_BUCKET_PREFIXES = ['xn--']
    FORBIDDEN_BUCKET_SUFFIXES = ['-s3alias', '--ol-s3']
    
    # IP address pattern
    IP_ADDRESS_PATTERN = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    
    # Valid bucket name pattern (lowercase letters, numbers, dots, hyphens)
    BUCKET_NAME_PATTERN = re.compile(r'^[a-z0-9.-]+$')
    
    # Invalid sequences in bucket names
    CONSECUTIVE_PERIODS_PATTERN = re.compile(r'\.\.')
    PERIOD_HYPHEN_PATTERN = re.compile(r'\.-|-\.')
    
    # Characters that can cause issues in object keys
    PROBLEMATIC_OBJECT_CHARS = {
        '&': 'ampersand',
        '$': 'dollar sign', 
        '@': 'at symbol',
        '=': 'equals sign',
        ';': 'semicolon',
        ':': 'colon',
        '+': 'plus sign',
        ' ': 'space',
        ',': 'comma',
        '?': 'question mark',
        '\\': 'backslash',
        '{': 'left brace',
        '}': 'right brace',
        '^': 'caret',
        '`': 'backtick',
        ']': 'right bracket',
        '[': 'left bracket',
        '"': 'quotation mark',
        '>': 'greater than',
        '<': 'less than',
        '~': 'tilde',
        '#': 'hash',
        '|': 'pipe'
    }

    @classmethod
    def validate_bucket_name(cls, bucket_name: str) -> Tuple[bool, List[str]]:
        """
        Validate S3 bucket name according to AWS naming rules.
        
        Returns:
            Tuple[bool, List[str]]: (is_valid, list_of_errors)
        """
        errors = []
        
        if not bucket_name:
            errors.append("Bucket name cannot be empty")
            return False, errors
        
        # Length validation
        if len(bucket_name) < cls.MIN_BUCKET_LENGTH:
            errors.append(f"Bucket name must be at least {cls.MIN_BUCKET_LENGTH} characters long")
        
        if len(bucket_name) > cls.MAX_BUCKET_LENGTH:
            errors.append(f"Bucket name must not exceed {cls.MAX_BUCKET_LENGTH} characters")
        
        # Character validation
        if not cls.BUCKET_NAME_PATTERN.match(bucket_name):
            errors.append("Bucket name can only contain lowercase letters, numbers, periods, and hyphens")
        
        # Start/end validation
        if bucket_name[0] in '.-' or bucket_name[-1] in '.-':
            errors.append("Bucket name must start and end with a letter or number")
        
        # Consecutive periods
        if cls.CONSECUTIVE_PERIODS_PATTERN.search(bucket_name):
            errors.append("Bucket name must not contain consecutive periods")
        
        # Period-hyphen combinations
        if cls.PERIOD_HYPHEN_PATTERN.search(bucket_name):
            errors.append("Bucket name must not contain period-hyphen or hyphen-period combinations")
        
        # IP address format
        if cls.IP_ADDRESS_PATTERN.match(bucket_name):
            errors.append("Bucket name must not be formatted as an IP address")
        
        # Forbidden prefixes
        for prefix in cls.FORBIDDEN_BUCKET_PREFIXES:
            if bucket_name.startswith(prefix):
                errors.append(f"Bucket name must not start with '{prefix}'")
        
        # Forbidden suffixes
        for suffix in cls.FORBIDDEN_BUCKET_SUFFIXES:
            if bucket_name.endswith(suffix):
                errors.append(f"Bucket name must not end with '{suffix}'")
        
        return len(errors) == 0, errors

    @classmethod
    def validate_object_key(cls, object_key: str, strict: bool = False) -> Tuple[bool, List[str]]:
        """
        Validate S3 object key according to AWS naming rules.
        
        Args:
            object_key: The object key to validate
            strict: If True, reject characters that might cause issues
            
        Returns:
            Tuple[bool, List[str]]: (is_valid, list_of_errors)
        """
        errors = []
        warnings = []
        
        if not object_key:
            errors.append("Object key cannot be empty")
            return False, errors
        
        # Length validation
        if len(object_key.encode('utf-8')) > cls.MAX_OBJECT_KEY_LENGTH:
            errors.append(f"Object key must not exceed {cls.MAX_OBJECT_KEY_LENGTH} bytes when UTF-8 encoded")
        
        # Leading slash warning
        if object_key.startswith('/'):
            warnings.append("Object key starts with '/' which is allowed but not recommended")
        
        # Trailing slash warning
        if object_key.endswith('/'):
            warnings.append("Object key ends with '/' - this will be treated as a folder")
        
        # Check for problematic characters
        problematic_chars = []
        for char in object_key:
            if char in cls.PROBLEMATIC_OBJECT_CHARS:
                problematic_chars.append(f"'{char}' ({cls.PROBLEMATIC_OBJECT_CHARS[char]})")
        
        if problematic_chars:
            message = f"Object key contains characters that may cause issues: {', '.join(problematic_chars)}"
            if strict:
                errors.append(message)
            else:
                warnings.append(message)
        
        # Check for control characters
        control_chars = [char for char in object_key if ord(char) < 32 and char not in '\t\n\r']
        if control_chars:
            errors.append(f"Object key contains control characters: {control_chars}")
        
        # URL encoding check
        try:
            urllib.parse.quote(object_key, safe='/')
        except Exception as e:
            errors.append(f"Object key contains characters that cannot be URL encoded: {e}")
        
        # Add warnings to errors if any (for reporting)
        all_issues = errors + warnings
        
        return len(errors) == 0, all_issues

    @classmethod
    def sanitize_bucket_name(cls, bucket_name: str) -> str:
        """
        Attempt to sanitize a bucket name to make it S3-compliant.
        
        Returns:
            str: Sanitized bucket name (may still need validation)
        """
        if not bucket_name:
            return bucket_name
        
        # Convert to lowercase
        sanitized = bucket_name.lower()
        
        # Replace invalid characters with hyphens
        sanitized = re.sub(r'[^a-z0-9.-]', '-', sanitized)
        
        # Remove consecutive periods
        sanitized = re.sub(r'\.{2,}', '.', sanitized)
        
        # Remove period-hyphen combinations
        sanitized = re.sub(r'\.-|-\.', '-', sanitized)
        
        # Ensure starts and ends with alphanumeric
        sanitized = re.sub(r'^[.-]+', '', sanitized)
        sanitized = re.sub(r'[.-]+$', '', sanitized)
        
        # Ensure minimum length
        if len(sanitized) < cls.MIN_BUCKET_LENGTH:
            sanitized = sanitized + 'a' * (cls.MIN_BUCKET_LENGTH - len(sanitized))
        
        # Ensure maximum length
        if len(sanitized) > cls.MAX_BUCKET_LENGTH:
            sanitized = sanitized[:cls.MAX_BUCKET_LENGTH]
            # Ensure doesn't end with period or hyphen
            sanitized = re.sub(r'[.-]+$', '', sanitized)
        
        return sanitized

    @classmethod
    def sanitize_object_key(cls, object_key: str, strict: bool = False) -> str:
        """
        Attempt to sanitize an object key to make it S3-compliant.
        
        Args:
            object_key: Original object key
            strict: If True, remove problematic characters
            
        Returns:
            str: Sanitized object key
        """
        if not object_key:
            return object_key
        
        sanitized = object_key
        
        # Remove control characters (except tab, newline, carriage return)
        sanitized = ''.join(char for char in sanitized if ord(char) >= 32 or char in '\t\n\r')
        
        # If strict mode, remove problematic characters
        if strict:
            for char in cls.PROBLEMATIC_OBJECT_CHARS:
                sanitized = sanitized.replace(char, '_')
        
        # Ensure doesn't exceed length limit
        if len(sanitized.encode('utf-8')) > cls.MAX_OBJECT_KEY_LENGTH:
            # Truncate while preserving UTF-8 character boundaries
            encoded = sanitized.encode('utf-8')[:cls.MAX_OBJECT_KEY_LENGTH]
            # Find last valid UTF-8 character boundary
            while encoded and encoded[-1] >= 0x80:
                encoded = encoded[:-1]
            sanitized = encoded.decode('utf-8', errors='ignore')
        
        return sanitized

    @classmethod
    def get_validation_report(cls, bucket_name: str = None, object_key: str = None, strict: bool = False) -> Dict:
        """
        Generate a comprehensive validation report.
        
        Returns:
            Dict: Validation report with details and suggestions
        """
        report = {
            'timestamp': str(datetime.utcnow()),
            'validation_mode': 'strict' if strict else 'standard',
            'overall_valid': True,
            'bucket_validation': None,
            'object_validation': None,
            'suggestions': []
        }
        
        if bucket_name is not None:
            bucket_valid, bucket_errors = cls.validate_bucket_name(bucket_name)
            report['bucket_validation'] = {
                'name': bucket_name,
                'valid': bucket_valid,
                'errors': bucket_errors,
                'sanitized': cls.sanitize_bucket_name(bucket_name) if not bucket_valid else bucket_name
            }
            if not bucket_valid:
                report['overall_valid'] = False
                report['suggestions'].append(f"Use sanitized bucket name: {report['bucket_validation']['sanitized']}")
        
        if object_key is not None:
            object_valid, object_errors = cls.validate_object_key(object_key, strict)
            report['object_validation'] = {
                'key': object_key,
                'valid': object_valid,
                'issues': object_errors,
                'sanitized': cls.sanitize_object_key(object_key, strict) if object_errors else object_key
            }
            if not object_valid:
                report['overall_valid'] = False
                report['suggestions'].append(f"Use sanitized object key: {report['object_validation']['sanitized']}")
        
        return report


def validate_s3_name(bucket_name: str = None, object_key: str = None, strict: bool = False) -> Dict:
    """
    Convenience function for S3 name validation.
    
    Args:
        bucket_name: Bucket name to validate (optional)
        object_key: Object key to validate (optional)  
        strict: Use strict validation for object keys
        
    Returns:
        Dict: Validation results
        
    Raises:
        S3ValidationError: If validation fails
    """
    validator = S3NameValidator()
    
    if bucket_name and object_key:
        return validator.get_validation_report(bucket_name, object_key, strict)
    elif bucket_name:
        bucket_valid, bucket_errors = validator.validate_bucket_name(bucket_name)
        if not bucket_valid:
            raise S3ValidationError(f"Invalid bucket name: {'; '.join(bucket_errors)}", "InvalidBucketName")
        return {"bucket_name": bucket_name, "valid": True, "errors": []}
    elif object_key:
        object_valid, object_errors = validator.validate_object_key(object_key, strict)
        error_messages = [msg for msg in object_errors if 'warning' not in msg.lower()]
        if not object_valid:
            raise S3ValidationError(f"Invalid object key: {'; '.join(error_messages)}", "InvalidObjectKey")
        return {"object_key": object_key, "valid": True, "errors": object_errors}
    else:
        raise S3ValidationError("Either bucket_name or object_key must be provided", "InvalidRequest")


# Import datetime for timestamps
from datetime import datetime

if __name__ == "__main__":
    # Test examples
    validator = S3NameValidator()
    
    # Test bucket names
    test_buckets = [
        "valid-bucket-name",
        "Invalid-Bucket-Name",  # Invalid: uppercase
        "my..bucket",  # Invalid: consecutive periods  
        "192.168.1.1",  # Invalid: IP address
        "xn--bucket",  # Invalid: forbidden prefix
        "ab",  # Invalid: too short
        "bucket-s3alias",  # Invalid: forbidden suffix
    ]
    
    print("🪣 Bucket Name Validation Tests:")
    for bucket in test_buckets:
        valid, errors = validator.validate_bucket_name(bucket)
        status = "✅ VALID" if valid else "❌ INVALID"
        print(f"  {status}: '{bucket}'")
        if errors:
            for error in errors:
                print(f"    - {error}")
        if not valid:
            sanitized = validator.sanitize_bucket_name(bucket)
            print(f"    💡 Suggested: '{sanitized}'")
        print()
    
    # Test object keys
    test_objects = [
        "valid/object/key.txt",
        "object with spaces.txt",  # Warning: spaces
        "object&with$special@chars.txt",  # Warning: special chars
        "/leading-slash.txt",  # Warning: leading slash
        "folder/",  # Warning: trailing slash
        "very" * 300 + ".txt",  # Invalid: too long
        "object\x00with\x01control.txt",  # Invalid: control chars
    ]
    
    print("📄 Object Key Validation Tests:")
    for obj_key in test_objects:
        valid, issues = validator.validate_object_key(obj_key)
        status = "✅ VALID" if valid else "❌ INVALID"
        print(f"  {status}: '{obj_key[:50]}{'...' if len(obj_key) > 50 else ''}'")
        if issues:
            for issue in issues:
                print(f"    - {issue}")
        print() 