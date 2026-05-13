import boto3
from datetime import datetime, timedelta, timezone

CLOUDWATCH_NAMESPACE = "AWS/RDS"


def get_all_regions():
    ec2 = boto3.client("ec2")
    regions = ec2.describe_regions(AllRegions=False)
    return [r["RegionName"] for r in regions["Regions"]]


def get_rds_client(region):
    return boto3.client("rds", region_name=region)


def get_cloudwatch_client(region):
    return boto3.client("cloudwatch", region_name=region)


def get_metric_average(cw, db_id, metric_name, start_time, end_time, period=3600):
    resp = cw.get_metric_statistics(
        Namespace=CLOUDWATCH_NAMESPACE,
        MetricName=metric_name,
        Dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
        StartTime=start_time,
        EndTime=end_time,
        Period=period,
        Statistics=["Average"],
    )
    datapoints = resp.get("Datapoints", [])
    if not datapoints:
        return 0.0
    avg = sum(dp["Average"] for dp in datapoints) / len(datapoints)
    return round(avg, 2)


def estimate_instance_monthly_cost(instance_class):
    # Rough example mapping (not exact AWS pricing)
    rough_monthly = {
        "db.t3.micro": 15,
        "db.t3.small": 30,
        "db.t3.medium": 60,
        "db.m5.large": 150,
        "db.m5.xlarge": 300,
    }
    for key, value in rough_monthly.items():
        if key in instance_class:
            return value
    return 100  # default rough estimate


def list_idle_rds_instances(idle_cpu_threshold=5.0, idle_conn_threshold=5.0, days=7):
    results = []
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    for region in get_all_regions():
        rds = get_rds_client(region)
        cw = get_cloudwatch_client(region)

        paginator = rds.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for db in page.get("DBInstances", []):
                if db["DBInstanceStatus"] != "available":
                    continue

                db_id = db["DBInstanceIdentifier"]
                instance_class = db["DBInstanceClass"]
                engine = db["Engine"]

                avg_cpu = get_metric_average(
                    cw, db_id, "CPUUtilization", start, now
                )
                avg_conn = get_metric_average(
                    cw, db_id, "DatabaseConnections", start, now
                )

                if avg_cpu < idle_cpu_threshold and avg_conn < idle_conn_threshold:
                    est_monthly = estimate_instance_monthly_cost(instance_class)
                    results.append(
                        {
                            "region": region,
                            "db_identifier": db_id,
                            "engine": engine,
                            "instance_class": instance_class,
                            "avg_cpu_percent": avg_cpu,
                            "avg_connections": avg_conn,
                            "estimated_monthly_waste_usd": est_monthly,
                            "recommendation": "STOP or DOWNSIZE (non-prod / low usage)",
                        }
                    )

    return results


def list_old_rds_snapshots(days_old=90):
    results = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days_old)

    for region in get_all_regions():
        rds = get_rds_client(region)

        paginator = rds.get_paginator("describe_db_snapshots")
        for page in paginator.paginate(SnapshotType="manual"):
            for snap in page.get("DBSnapshots", []):
                create_time = snap["SnapshotCreateTime"]
                if create_time < cutoff:
                    results.append(
                        {
                            "region": region,
                            "snapshot_id": snap["DBSnapshotIdentifier"],
                            "db_identifier": snap["DBInstanceIdentifier"],
                            "engine": snap["Engine"],
                            "snapshot_create_time": create_time.isoformat(),
                            "recommendation": "REVIEW and DELETE if no longer needed",
                        }
                    )

    return results


def run_rds_checks():
    idle_instances = list_idle_rds_instances()
    old_snapshots = list_old_rds_snapshots()

    total_monthly_savings = sum(
        item["estimated_monthly_waste_usd"] for item in idle_instances
    )

    return {
        "total_idle_rds_instances": len(idle_instances),
        "total_old_rds_snapshots": len(old_snapshots),
        "estimated_monthly_savings_usd": round(total_monthly_savings, 2),
        "idle_rds_instances": idle_instances,
        "old_rds_snapshots": old_snapshots,
    }


if __name__ == "__main__":
    report = run_rds_checks()
    print(report)
