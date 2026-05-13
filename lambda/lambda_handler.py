#!/usr/bin/env python3
"""
AWS Lambda Handler - Cloud Cost Optimizer
This Lambda function is triggered by CloudWatch Events (weekly schedule)
and runs all cost optimization checks, then sends an SNS alert.

Author: Anish Tiwari
Project: AWS Cloud Cost Optimizer
"""

import boto3
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List

# Add parent dir to path for local dev
sys.path.insert(0, '/var/task')

# Environment variables (set by Terraform)
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', '')
REPORTS_BUCKET = os.environ.get('REPORTS_BUCKET', '')
CPU_THRESHOLD = float(os.environ.get('CPU_THRESHOLD', '5.0'))
ALERT_THRESHOLD = float(os.environ.get('ALERT_THRESHOLD', '100'))


def get_all_regions() -> List[str]:
    ec2 = boto3.client('ec2', region_name='us-east-1')
    response = ec2.describe_regions(
        Filters=[{'Name': 'opt-in-status', 'Values': ['opt-in-not-required', 'opted-in']}]
    )
    return [r['RegionName'] for r in response['Regions']]


def check_idle_ec2(region: str) -> List[Dict]:
    """Detect EC2 instances with < CPU_THRESHOLD% avg CPU over 7 days."""
    ec2 = boto3.client('ec2', region_name=region)
    cloudwatch = boto3.client('cloudwatch', region_name=region)
    idle = []

    try:
        pages = ec2.get_paginator('describe_instances').paginate(
            Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]
        )
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=7)

        for page in pages:
            for reservation in page['Reservations']:
                for instance in reservation['Instances']:
                    instance_id = instance['InstanceId']
                    launch_time = instance['LaunchTime']

                    if (datetime.now(timezone.utc) - launch_time).days < 7:
                        continue

                    response = cloudwatch.get_metric_statistics(
                        Namespace='AWS/EC2',
                        MetricName='CPUUtilization',
                        Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
                        StartTime=start_time, EndTime=end_time,
                        Period=86400, Statistics=['Average']
                    )
                    datapoints = response.get('Datapoints', [])
                    avg_cpu = sum(dp['Average'] for dp in datapoints) / len(datapoints) if datapoints else 0.0

                    if avg_cpu < CPU_THRESHOLD:
                        name = next(
                            (t['Value'] for t in instance.get('Tags', []) if t['Key'] == 'Name'), 'N/A'
                        )
                        # Hourly costs lookup
                        HOURLY = {'t3.micro': 0.0104, 't3.small': 0.0208, 't3.medium': 0.0416,
                                  't3.large': 0.0832, 'm5.large': 0.096, 'm5.xlarge': 0.192}
                        hourly = HOURLY.get(instance['InstanceType'], 0.05)
                        idle.append({
                            'type': 'idle_ec2',
                            'region': region,
                            'resource_id': instance_id,
                            'name': name,
                            'instance_type': instance['InstanceType'],
                            'avg_cpu_percent': round(avg_cpu, 2),
                            'monthly_waste_usd': round(hourly * 730, 2),
                            'action': 'STOP or RIGHTSIZE'
                        })
    except Exception as e:
        print(f"[EC2] Error in {region}: {e}")

    return idle


def check_unused_ebs(region: str) -> List[Dict]:
    """Find unattached EBS volumes."""
    ec2 = boto3.client('ec2', region_name=region)
    EBS_PRICE = {'gp2': 0.10, 'gp3': 0.08, 'io1': 0.125, 'io2': 0.125,
                 'st1': 0.045, 'sc1': 0.025, 'standard': 0.05}
    unused = []

    try:
        pages = ec2.get_paginator('describe_volumes').paginate(
            Filters=[{'Name': 'status', 'Values': ['available']}]
        )
        for page in pages:
            for vol in page['Volumes']:
                price = EBS_PRICE.get(vol['VolumeType'], 0.10)
                monthly_cost = round(vol['Size'] * price, 2)
                unused.append({
                    'type': 'unused_ebs',
                    'region': region,
                    'resource_id': vol['VolumeId'],
                    'size_gb': vol['Size'],
                    'volume_type': vol['VolumeType'],
                    'monthly_waste_usd': monthly_cost,
                    'action': 'DELETE or SNAPSHOT'
                })
    except Exception as e:
        print(f"[EBS] Error in {region}: {e}")

    return unused


def check_unattached_eips(region: str) -> List[Dict]:
    """Find unassociated Elastic IPs ($3.65/month each)."""
    ec2 = boto3.client('ec2', region_name=region)
    eips = []

    try:
        addresses = ec2.describe_addresses()['Addresses']
        for addr in addresses:
            if 'AssociationId' not in addr:
                eips.append({
                    'type': 'unattached_eip',
                    'region': region,
                    'resource_id': addr.get('AllocationId', addr.get('PublicIp', 'N/A')),
                    'public_ip': addr.get('PublicIp', 'N/A'),
                    'monthly_waste_usd': 3.65,
                    'action': 'RELEASE'
                })
    except Exception as e:
        print(f"[EIP] Error in {region}: {e}")

    return eips


def build_alert_message(findings: List[Dict], total_savings: float) -> str:
    """Build a human-readable alert message for SNS."""
    ec2_count = sum(1 for f in findings if f['type'] == 'idle_ec2')
    ebs_count = sum(1 for f in findings if f['type'] == 'unused_ebs')
    eip_count = sum(1 for f in findings if f['type'] == 'unattached_eip')

    msg = f"""
=== AWS Cloud Cost Optimizer Report ===
Scan Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

SUMMARY OF WASTE DETECTED:
  - Idle EC2 Instances     : {ec2_count}
  - Unused EBS Volumes     : {ebs_count}
  - Unattached Elastic IPs : {eip_count}
  - Total Resources Flagged: {len(findings)}

ESTIMATED MONTHLY SAVINGS: ${total_savings:.2f} USD

TOP FINDINGS:
"""
    for f in findings[:10]:  # Show top 10
        msg += f"  [{f['type']}] {f['region']} | {f['resource_id']} | Waste: ${f['monthly_waste_usd']}/mo | Action: {f['action']}\n"

    msg += f"""
---
Full report saved to S3: s3://{REPORTS_BUCKET}/reports/
Review and take action to reduce your AWS bill.
"""
    return msg


def handler(event, context):
    """Main Lambda entry point."""
    print("[*] Starting AWS Cloud Cost Optimization scan...")
    regions = get_all_regions()
    all_findings = []

    for region in regions:
        print(f"[*] Scanning region: {region}")
        all_findings.extend(check_idle_ec2(region))
        all_findings.extend(check_unused_ebs(region))
        all_findings.extend(check_unattached_eips(region))

    total_savings = sum(f['monthly_waste_usd'] for f in all_findings)
    print(f"[*] Total findings: {len(all_findings)} | Potential savings: ${total_savings:.2f}/mo")

    # Sort by highest waste first
    all_findings.sort(key=lambda x: x['monthly_waste_usd'], reverse=True)

    report = {
        'scan_timestamp': str(datetime.now(timezone.utc)),
        'total_findings': len(all_findings),
        'estimated_monthly_savings_usd': round(total_savings, 2),
        'findings': all_findings
    }

    # Save report to S3
    if REPORTS_BUCKET:
        s3 = boto3.client('s3')
        key = f"reports/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/cost_report.json"
        s3.put_object(
            Bucket=REPORTS_BUCKET,
            Key=key,
            Body=json.dumps(report, indent=2),
            ContentType='application/json'
        )
        print(f"[*] Report saved to s3://{REPORTS_BUCKET}/{key}")

    # Send SNS alert if savings exceed threshold
    if SNS_TOPIC_ARN and total_savings >= ALERT_THRESHOLD:
        sns = boto3.client('sns')
        message = build_alert_message(all_findings, total_savings)
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"[AWS Cost Alert] ${total_savings:.2f}/mo in potential savings identified!",
            Message=message
        )
        print(f"[*] SNS alert sent to {SNS_TOPIC_ARN}")

    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Cost scan complete',
            'total_findings': len(all_findings),
            'monthly_savings_usd': round(total_savings, 2)
        })
    }


if __name__ == '__main__':
    # For local testing
    result = handler({}, None)
    print(json.dumps(json.loads(result['body']), indent=2))
