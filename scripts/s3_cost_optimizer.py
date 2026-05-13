#!/usr/bin/env python3
"""
S3 Cost Optimizer
Real-world use case:
- Detect buckets without lifecycle policies (objects never expire = infinite cost)
- Find buckets using expensive storage classes when cheaper ones would work
- Detect buckets with versioning enabled but no lifecycle to clean old versions
- Identify public access buckets (security + cost risk)

Author: Anish Tiwari
Project: AWS Cloud Cost Optimizer
"""

import boto3
import json
from datetime import datetime, timezone
from typing import List, Dict


# S3 storage class pricing per GB-month (approximate)
S3_PRICING = {
    'STANDARD': 0.023,
    'STANDARD_IA': 0.0125,
    'ONEZONE_IA': 0.01,
    'INTELLIGENT_TIERING': 0.023,
    'GLACIER': 0.004,
    'DEEP_ARCHIVE': 0.00099,
    'GLACIER_IR': 0.004,
}


def get_bucket_size_and_cost(bucket_name: str, region: str) -> Dict:
    """Get total bucket size and estimated monthly cost via CloudWatch metrics."""
    cloudwatch = boto3.client('cloudwatch', region_name=region)
    from datetime import timedelta
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=2)

    # BucketSizeBytes metric
    response = cloudwatch.get_metric_statistics(
        Namespace='AWS/S3',
        MetricName='BucketSizeBytes',
        Dimensions=[
            {'Name': 'BucketName', 'Value': bucket_name},
            {'Name': 'StorageType', 'Value': 'StandardStorage'}
        ],
        StartTime=start_time,
        EndTime=end_time,
        Period=86400,
        Statistics=['Average']
    )

    datapoints = response.get('Datapoints', [])
    size_bytes = datapoints[-1]['Average'] if datapoints else 0
    size_gb = size_bytes / (1024 ** 3)
    monthly_cost = round(size_gb * S3_PRICING['STANDARD'], 4)

    return {
        'size_bytes': size_bytes,
        'size_gb': round(size_gb, 4),
        'estimated_monthly_cost_usd': monthly_cost
    }


def check_lifecycle_policy(s3_client, bucket_name: str) -> bool:
    """Check if bucket has a lifecycle policy."""
    try:
        s3_client.get_bucket_lifecycle_configuration(Bucket=bucket_name)
        return True
    except s3_client.exceptions.ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchLifecycleConfiguration':
            return False
        raise


def check_versioning(s3_client, bucket_name: str) -> str:
    """Check versioning status: Enabled, Suspended, or Disabled."""
    try:
        response = s3_client.get_bucket_versioning(Bucket=bucket_name)
        return response.get('Status', 'Disabled')
    except Exception:
        return 'Unknown'


def check_public_access(s3_client, bucket_name: str) -> bool:
    """Check if bucket has public access block disabled (potential security/cost risk)."""
    try:
        response = s3_client.get_public_access_block(Bucket=bucket_name)
        config = response['PublicAccessBlockConfiguration']
        # If ALL four settings are True, it's fully blocked (safe)
        all_blocked = all([
            config.get('BlockPublicAcls', False),
            config.get('IgnorePublicAcls', False),
            config.get('BlockPublicPolicy', False),
            config.get('RestrictPublicBuckets', False)
        ])
        return not all_blocked
    except Exception:
        return True  # Assume public if can't check


def analyze_all_buckets() -> List[Dict]:
    """Analyze all S3 buckets for cost optimization opportunities."""
    s3 = boto3.client('s3', region_name='us-east-1')
    buckets = s3.list_buckets()['Buckets']

    print(f"[*] Found {len(buckets)} S3 buckets to analyze")
    results = []

    for bucket in buckets:
        bucket_name = bucket['Name']
        print(f"  Analyzing: {bucket_name}")

        # Get bucket region
        try:
            loc = s3.get_bucket_location(Bucket=bucket_name)
            region = loc['LocationConstraint'] or 'us-east-1'
        except Exception:
            region = 'us-east-1'

        try:
            has_lifecycle = check_lifecycle_policy(s3, bucket_name)
            versioning = check_versioning(s3, bucket_name)
            is_public_risk = check_public_access(s3, bucket_name)
            size_info = get_bucket_size_and_cost(bucket_name, region)

            issues = []
            recommendations = []

            if not has_lifecycle:
                issues.append('No lifecycle policy')
                recommendations.append('Add S3 lifecycle policy to transition old objects to Glacier')

            if versioning == 'Enabled' and not has_lifecycle:
                issues.append('Versioning ON but no lifecycle for old versions')
                recommendations.append('Add lifecycle rule to expire non-current versions after 30 days')

            if is_public_risk:
                issues.append('Public access not fully blocked')
                recommendations.append('Enable S3 Block Public Access on this bucket')

            if size_info['size_gb'] > 100:
                issues.append(f'Large bucket ({size_info["size_gb"]:.1f} GB) - review storage class')
                recommendations.append('Consider S3 Intelligent-Tiering for large buckets')

            results.append({
                'bucket_name': bucket_name,
                'region': region,
                'size_gb': size_info['size_gb'],
                'estimated_monthly_cost_usd': size_info['estimated_monthly_cost_usd'],
                'has_lifecycle_policy': has_lifecycle,
                'versioning_status': versioning,
                'public_access_risk': is_public_risk,
                'issues': issues,
                'recommendations': recommendations
            })

        except Exception as e:
            print(f"  [ERROR] {bucket_name}: {e}")

    return results


def generate_s3_report(results: List[Dict]):
    """Generate S3 optimization report."""
    import os
    os.makedirs('reports', exist_ok=True)

    buckets_with_issues = [r for r in results if r['issues']]
    total_cost = sum(r['estimated_monthly_cost_usd'] for r in results)

    report = {
        'scan_timestamp': str(datetime.now(timezone.utc)),
        'summary': {
            'total_buckets_scanned': len(results),
            'buckets_with_issues': len(buckets_with_issues),
            'total_estimated_s3_cost_usd': round(total_cost, 2)
        },
        'buckets': results
    }

    with open('reports/s3_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\n{'='*60}")
    print(f"S3 COST OPTIMIZATION REPORT")
    print(f"{'='*60}")
    print(f"Total Buckets Scanned    : {len(results)}")
    print(f"Buckets With Issues      : {len(buckets_with_issues)}")
    print(f"Total S3 Monthly Cost    : ${round(total_cost, 2)}")
    print(f"Report: reports/s3_report.json")
    print(f"{'='*60}")
    return report


if __name__ == '__main__':
    print("Starting S3 Cost Optimization Analysis...\n")
    results = analyze_all_buckets()
    generate_s3_report(results)
