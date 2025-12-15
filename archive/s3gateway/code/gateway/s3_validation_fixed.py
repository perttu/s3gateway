#!/usr/bin/env python3
"""
S3 XML Response Utilities
Helper functions for S3-compatible XML responses with proper formatting.
"""

import uuid
from fastapi import Response


def create_s3_error_response(error_code: str, message: str, bucket_name: str = None, key: str = None) -> Response:
    """Create S3-compatible XML error response with proper formatting"""
    resource = f"/{bucket_name}" if bucket_name else "/"
    if key:
        resource += f"/{key}"
    
    error_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Error>
    <Code>{error_code}</Code>
    <Message>{message}</Message>
    <Resource>{resource}</Resource>
    <RequestId>{str(uuid.uuid4())}</RequestId>
</Error>"""
    
    return Response(
        content=error_xml,
        status_code=400,
        media_type="application/xml",
        headers={
            "X-S3-Validation-Error": "true",
            "X-Error-Code": error_code
        }
    )


def create_s3_list_response(bucket_name: str, objects: list) -> str:
    """Create S3-compatible list bucket XML response"""
    xml_objects = ""
    for obj in objects:
        xml_objects += f"""
        <Contents>
            <Key>{obj['object_key']}</Key>
            <LastModified>2024-01-01T00:00:00.000Z</LastModified>
            <ETag>"{obj['etag']}"</ETag>
            <Size>{obj['size_bytes']}</Size>
            <StorageClass>STANDARD</StorageClass>
        </Contents>"""
    
    xml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    <Name>{bucket_name}</Name>
    <Prefix></Prefix>
    <Marker></Marker>
    <MaxKeys>1000</MaxKeys>
    <IsTruncated>false</IsTruncated>{xml_objects}
</ListBucketResult>"""
    
    return xml_response 