#!/usr/bin/env python3
"""
EC2 Idle Instance Detector
Real-world use case: Detect EC2 instances with <5% avg CPU over 7 days.
This script saves companies thousands of dollars per month.

Author: Anish Tiwari
Project: AWS Cloud Cost Optimizer
"""

import boto3
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict


def get_all_regions() -> List[str]:
    """Fetch all active AWS regions."""
    ec2 = boto3.client('ec2', region_name='us-east-1')
    response = ec2.describe_regions(Filters=[{'Name': 'opt-in-status', 'Values': ['opt-in-not-required', 'opted-in']}])
    return [r['RegionName'] for r in response['Regions']]


def get_avg_cpu(instance_id: str, region: str, days: int = 7) -> float:
    """Get average CPU utilization for an EC2 instance over N days."""
    cloudwatch = boto3.client('cloudwatch', region_name=region)
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=days)

    response = cloudwatch.get_metric_statistics(
        Namespace='AWS/EC2',
        MetricName='CPUUtilization',
        Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
        StartTime=start_time,
        EndTime=end_time,
        Period=86400,  # 1 day in seconds
        Statistics=['Average']
    )

    datapoints = response.get('Datapoints', [])
    if not datapoints:
        return 0.0
    return sum(dp['Average'] for dp in datapoints) / len(datapoints)


def detect_idle_instances(cpu_threshold: float = 5.0, days: int = 7) -> List[Dict]:
    """
    Scan all regions for idle EC2 instances.
    Idle = avg CPU < cpu_threshold% over the past N days.
    """
    idle_instances = []
    regions = get_all_regions()

    for region in regions:
        print(f"[*] Scanning region: {region}")
        ec2 = boto3.client('ec2', region_name=region)

        try:
            paginator = ec2.get_paginator('describe_instances')
            pages = paginator.paginate(
                Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]
            )

            for page in pages:
                for reservation in page['Reservations']:
                    for instance in reservation['Instances']:
                        instance_id = instance['InstanceId']
                        instance_type = instance['InstanceType']
                        launch_time = instance['LaunchTime']

                        # Skip if instance is too new (launched < 7 days ago)
                        age = datetime.now(timezone.utc) - launch_time
                        if age.days < days:
                            continue

                        avg_cpu = get_avg_cpu(instance_id, region, days)

                        # Get instance name tag
                        name = next(
                            (tag['Value'] for tag in instance.get('Tags', []) if tag['Key'] == 'Name'),
                            'N/A'
                        )

                        if avg_cpu < cpu_threshold:
                            idle_instances.append({
                                'region': region,
                                'instance_id': instance_id,
                                'instance_type': instance_type,
                                'name': name,
                                'avg_cpu_percent': round(avg_cpu, 2),
                                'launch_time': str(launch_time),
                                'recommendation': 'STOP or RIGHT-SIZE'
                            })
                            print(f"  [!] IDLE: {instance_id} ({name}) - Avg CPU: {avg_cpu:.2f}%")

        except Exception as e:
            print(f"  [ERROR] Region {region}: {str(e)}")

    return idle_instances


def estimate_monthly_savings(idle_instances: List[Dict]) -> float:
    """
    Rough monthly cost estimate based on instance type.
    Prices are approximate On-Demand us-east-1 USD/hour.
    """
    # Approximate hourly costs for common instance types
    hourly_costs = {
        't2.micro': 0.0116, 't2.small': 0.023, 't2.medium': 0.0464,
        't3.micro': 0.0104, 't3.small': 0.0208, 't3.medium': 0.0416,
        't3.large': 0.0832, 't3.xlarge': 0.1664,
        'm5.large': 0.096, 'm5.xlarge': 0.192, 'm5.2xlarge': 0.384,
        'c5.large': 0.085, 'c5.xlarge': 0.17, 'c5.2xlarge': 0.34,
        'r5.large': 0.126, 'r5.xlarge': 0.252,
    }
    HOURS_PER_MONTH = 730
    total_savings = 0.0
    for inst in idle_instances:
        hourly = hourly_costs.get(inst['instance_type'], 0.05)  # default $0.05/hr
        total_savings += hourly * HOURS_PER_MONTH
    return round(total_savings, 2)


def generate_report(idle_instances: List[Dict], output_file: str = 'reports/ec2_idle_report.json'):
    """Generate a JSON report of idle instances."""
    import os
    os.makedirs('reports', exist_ok=True)

    savings = estimate_monthly_savings(idle_instances)
    report = {
        'scan_timestamp': str(datetime.now(timezone.utc)),
        'total_idle_instances': len(idle_instances),
        'estimated_monthly_savings_usd': savings,
        'idle_instances': idle_instances
    }

    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\n{'='*60}")
    print(f"SCAN COMPLETE - EC2 Idle Instance Report")
    print(f"{'='*60}")
    print(f"Total Idle Instances Found : {len(idle_instances)}")
    print(f"Estimated Monthly Savings  : ${savings}")
    print(f"Report saved to            : {output_file}")
    print(f"{'='*60}")
    return report


if __name__ == '__main__':
    print("Starting EC2 Idle Instance Detection...")
    print("Threshold: < 5% avg CPU over 7 days\n")
    idle = detect_idle_instances(cpu_threshold=5.0, days=7)
    generate_report(idle)
