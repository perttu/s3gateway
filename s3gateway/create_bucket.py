import boto3
from botocore.exceptions import ClientError
import os

# --- Configuration (for demo only, use env vars in production) ---
aws_access_key_id = "WG0SHVF6VS7072T4LVBW"
aws_secret_access_key = "CdAzsodxxFA3lnLJuyt7mTpaIMK7EcpyBpvUhy0W"
region = "default"  # Change as needed
bucket_name = "2025-datatransfer"
S3_ENDPOINT = "https://s3c.tns.cx"  # Your custom endpoint

def create_bucket():
    s3 = boto3.client(
        "s3",
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        endpoint_url=S3_ENDPOINT,
        region_name=region,
    )
    try:
        s3.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={"LocationConstraint": region}
        )
        print(f"Bucket '{bucket_name}' created successfully at {S3_ENDPOINT}.")
    except ClientError as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    create_bucket()
