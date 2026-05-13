#!/usr/bin/env python3
"""
EBS Unused Volume Detector
Real-world use case: Find EBS volumes not attached to any EC2 instance.
EBS gp2 costs ~$0.10/GB/month. A 500GB unattached volume wastes $50/month.

Author: Anish Tiwari
Project: AWS Cloud Cost Optimizer
"""

import boto3
import json
from datetime import datetime, timezone
from typing import List, Dict


# EBS volume pricing per GB-month (approximate, us-east-1)
EBS_PRICING = {
    'gp2': 0.10,
    'gp3': 0.08,
    'io1': 0.125,
    'io2': 0.125,
    'st1': 0.045,
    'sc1': 0.025,
    'standard': 0.05,
}


def get_all_regions() -> List[str]:
    ec2 = boto3.client('ec2', region_name='us-east-1')
    response = ec2.describe_regions(
        Filters=[{'Name': 'opt-in-status', 'Values': ['opt-in-not-required', 'opted-in']}]
    )
    return [r['RegionName'] for r in response['Regions']]


def find_unused_volumes(region: str) -> List[Dict]:
    """Find all unattached EBS volumes in a region."""
    ec2 = boto3.client('ec2', region_name=region)
    unused = []

    paginator = ec2.get_paginator('describe_volumes')
    pages = paginator.paginate(
        Filters=[{'Name': 'status', 'Values': ['available']}]  # 'available' = not attached
    )

    for page in pages:
        for volume in page['Volumes']:
            vol_id = volume['VolumeId']
            size_gb = volume['Size']
            vol_type = volume['VolumeType']
            create_time = volume['CreateTime']
            state = volume['State']

            # Get volume name tag
            name = next(
                (tag['Value'] for tag in volume.get('Tags', []) if tag['Key'] == 'Name'),
                'N/A'
            )

            # Calculate monthly cost
            price_per_gb = EBS_PRICING.get(vol_type, 0.10)
            monthly_cost = round(size_gb * price_per_gb, 2)

            # Calculate how long it's been unattached
            age_days = (datetime.now(timezone.utc) - create_time).days

            unused.append({
                'region': region,
                'volume_id': vol_id,
                'name': name,
                'size_gb': size_gb,
                'volume_type': vol_type,
                'state': state,
                'create_time': str(create_time),
                'age_days': age_days,
                'monthly_cost_usd': monthly_cost,
                'recommendation': 'DELETE or SNAPSHOT then DELETE'
            })

    return unused


def find_unused_snapshots(region: str) -> List[Dict]:
    """Find old snapshots not associated with any AMI."""
    ec2 = boto3.client('ec2', region_name=region)
    account_id = boto3.client('sts').get_caller_identity()['Account']

    # Get all AMI snapshot IDs
    images = ec2.describe_images(Owners=['self'])['Images']
    ami_snapshot_ids = set()
    for img in images:
        for bdm in img.get('BlockDeviceMappings', []):
            if 'Ebs' in bdm:
                ami_snapshot_ids.add(bdm['Ebs'].get('SnapshotId', ''))

    old_snapshots = []
    paginator = ec2.get_paginator('describe_snapshots')
    pages = paginator.paginate(OwnerIds=[account_id])

    for page in pages:
        for snap in page['Snapshots']:
            snap_id = snap['SnapshotId']
            # Skip snapshots used by AMIs
            if snap_id in ami_snapshot_ids:
                continue

            size_gb = snap['VolumeSize']
            start_time = snap['StartTime']
            age_days = (datetime.now(timezone.utc) - start_time).days

            # Only flag snapshots older than 90 days
            if age_days < 90:
                continue

            # Snapshots cost ~$0.05/GB-month
            monthly_cost = round(size_gb * 0.05, 2)

            old_snapshots.append({
                'region': region,
                'snapshot_id': snap_id,
                'description': snap.get('Description', ''),
                'size_gb': size_gb,
                'age_days': age_days,
                'monthly_cost_usd': monthly_cost,
                'recommendation': 'REVIEW and DELETE if not needed'
            })

    return old_snapshots


def scan_all_regions():
    """Main scanner for all regions."""
    all_unused_volumes = []
    all_old_snapshots = []
    regions = get_all_regions()

    for region in regions:
        print(f"[*] Scanning EBS in region: {region}")
        try:
            volumes = find_unused_volumes(region)
            all_unused_volumes.extend(volumes)
            if volumes:
                print(f"  [!] Found {len(volumes)} unused volumes")

            snapshots = find_unused_snapshots(region)
            all_old_snapshots.extend(snapshots)
            if snapshots:
                print(f"  [!] Found {len(snapshots)} old snapshots")

        except Exception as e:
            print(f"  [ERROR] {region}: {e}")

    # Calculate totals
    vol_savings = sum(v['monthly_cost_usd'] for v in all_unused_volumes)
    snap_savings = sum(s['monthly_cost_usd'] for s in all_old_snapshots)
    total_savings = round(vol_savings + snap_savings, 2)

    report = {
        'scan_timestamp': str(datetime.now(timezone.utc)),
        'summary': {
            'unused_volumes_count': len(all_unused_volumes),
            'old_snapshots_count': len(all_old_snapshots),
            'volumes_monthly_savings_usd': round(vol_savings, 2),
            'snapshots_monthly_savings_usd': round(snap_savings, 2),
            'total_monthly_savings_usd': total_savings
        },
        'unused_volumes': all_unused_volumes,
        'old_snapshots': all_old_snapshots
    }

    import os
    os.makedirs('reports', exist_ok=True)
    with open('reports/ebs_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\n{'='*60}")
    print(f"EBS COST OPTIMIZATION REPORT")
    print(f"{'='*60}")
    print(f"Unused Volumes        : {len(all_unused_volumes)} (saves ${vol_savings:.2f}/mo)")
    print(f"Old Snapshots         : {len(all_old_snapshots)} (saves ${snap_savings:.2f}/mo)")
    print(f"Total Monthly Savings : ${total_savings}")
    print(f"Report: reports/ebs_report.json")
    print(f"{'='*60}")

    return report


if __name__ == '__main__':
    print("Scanning for unused EBS volumes and old snapshots...\n")
    scan_all_regions()
