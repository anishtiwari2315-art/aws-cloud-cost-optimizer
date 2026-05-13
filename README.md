# AWS Cloud Cost Optimization

![GitHub Actions](https://github.com/anishtiwari2315-art/aws-cloud-cost-optimizer/actions/workflows/cost-scan.yml/badge.svg)
![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![Terraform](https://img.shields.io/badge/Terraform-1.7-purple?logo=terraform)
![AWS](https://img.shields.io/badge/AWS-Cloud-orange?logo=amazon-aws)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)

> **Real-world DevOps project** that automatically detects and reports AWS cloud cost waste — idle EC2 instances, unused EBS volumes, unattached Elastic IPs, and S3 storage inefficiencies — saving companies hundreds to thousands of dollars per month.

---

## Problem Statement

Cloud waste is a real problem. According to industry reports, organizations waste **30-35% of their cloud spend** on:
- EC2 instances running 24/7 with <5% CPU usage
- EBS volumes sitting unattached after EC2 termination ($0.10/GB/month)
- Elastic IPs not assigned to any instance ($3.65/month each)
- S3 buckets with no lifecycle policies (data accumulates forever)
- Old snapshots never cleaned up

This project automates the detection and alerting process using AWS-native tools.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              GitHub Actions (CI/CD)                  │
│  Push/PR → Lint → Test → Terraform → Deploy          │
│  Schedule → Weekly Cost Scan → Reports               │
└─────────────────┬───────────────────────────────────┘
                  │ Deploy
                  ▼
┌─────────────────────────────────────────────────────┐
│                   AWS Account                        │
│                                                      │
│  CloudWatch Events (cron: Monday 9AM UTC)            │
│           │                                          │
│           ▼                                          │
│     Lambda Function (Python 3.11)                    │
│           │                                          │
│    ┌──────┴──────┐                                   │
│    ▼             ▼                                   │
│  EC2 API    CloudWatch Metrics                       │
│  EBS API    Cost Explorer API                        │
│  S3  API                                             │
│    │                                                 │
│    ├──→ S3 Bucket (Reports JSON)                     │
│    └──→ SNS Topic → Email Alert                      │
└─────────────────────────────────────────────────────┘
```

---

## Features

| Feature | Description | Savings Potential |
|---|---|---|
| **EC2 Idle Detection** | Finds instances with <5% avg CPU over 7 days | $7-$140+/mo per instance |
| **EBS Unused Volumes** | Finds unattached volumes (status: available) | $0.08-$0.125/GB/mo |
| **Stale Snapshots** | Flags snapshots >90 days not linked to AMI | $0.05/GB/mo |
| **EIP Waste** | Finds Elastic IPs not assigned to any instance | $3.65/mo per EIP |
| **S3 Lifecycle Check** | Detects buckets without lifecycle policies | Varies |
| **SNS Alerting** | Email alert when savings exceed threshold | - |
| **Multi-Region** | Scans all active AWS regions automatically | - |
| **Weekly Automation** | CloudWatch Events triggers Lambda every Monday | - |

---

## Tech Stack

- **Python 3.11** + **Boto3** — AWS SDK for EC2, EBS, S3, CloudWatch, SNS
- **Terraform** — Infrastructure as Code (Lambda, IAM, SNS, CloudWatch, S3)
- **AWS Lambda** — Serverless execution (no EC2 needed)
- **GitHub Actions** — CI/CD pipeline with weekly scheduled scans
- **AWS CloudWatch** — Metrics + Events scheduling
- **AWS SNS** — Email alerting
- **AWS Cost Explorer** — Billing data access

---

## Project Structure

```
aws-cloud-cost-optimizer/
├── .github/
│   └── workflows/
│       └── cost-scan.yml          # CI/CD pipeline (lint, test, deploy, scan)
├── scripts/
│   ├── ec2_idle_detector.py       # Detect idle EC2 with CloudWatch CPU metrics
│   ├── ebs_unused_volumes.py      # Find unattached EBS + stale snapshots
│   └── s3_cost_optimizer.py       # S3 lifecycle, versioning, public access check
├── lambda/
│   └── lambda_handler.py          # AWS Lambda entry point (all checks + SNS)
├── terraform/
│   ├── main.tf                    # Lambda, IAM, SNS, S3, CloudWatch resources
│   └── variables.tf               # Configurable variables with validation
├── reports/                       # Generated JSON cost reports (gitignored)
├── .gitignore
├── LICENSE
└── README.md
```

---

## Quick Start

### Prerequisites
- AWS account with IAM credentials
- Python 3.11+
- Terraform 1.5+
- AWS CLI configured

### 1. Clone the repository
```bash
git clone https://github.com/anishtiwari2315-art/aws-cloud-cost-optimizer.git
cd aws-cloud-cost-optimizer
```

### 2. Install Python dependencies
```bash
pip install boto3
```

### 3. Run scripts locally
```bash
# Detect idle EC2 instances
python scripts/ec2_idle_detector.py

# Find unused EBS volumes
python scripts/ebs_unused_volumes.py

# Analyze S3 costs
python scripts/s3_cost_optimizer.py
```

### 4. Deploy infrastructure with Terraform
```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars  # edit with your values
terraform init
terraform plan
terraform apply
```

### 5. GitHub Actions Setup
Add these secrets to your GitHub repository (`Settings > Secrets`):

| Secret | Description |
|---|---|
| `AWS_ACCESS_KEY_ID` | IAM user access key |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret key |
| `ALERT_EMAIL` | Email to receive cost alerts |

---

## Sample Report Output

```json
{
  "scan_timestamp": "2026-05-13T09:00:00+00:00",
  "total_idle_instances": 3,
  "estimated_monthly_savings_usd": 245.76,
  "idle_instances": [
    {
      "region": "us-east-1",
      "instance_id": "i-0abc123def456",
      "instance_type": "m5.large",
      "name": "old-staging-server",
      "avg_cpu_percent": 0.8,
      "monthly_waste_usd": 70.08,
      "recommendation": "STOP or RIGHT-SIZE"
    }
  ]
}
```

---

## IAM Permissions Required

Minimum IAM policy (read-only, safe to run):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["ec2:Describe*", "cloudwatch:GetMetricStatistics", "s3:List*", "s3:GetBucket*", "ce:GetCostAndUsage", "sns:Publish"], "Resource": "*" }
  ]
}
```

---

## CI/CD Pipeline

The GitHub Actions pipeline has 5 jobs:

1. **Lint & Security** — flake8, Black formatter, Bandit security scan, safety CVE check
2. **Unit Tests** — pytest with moto (AWS mocking), coverage report
3. **Terraform Validate** — fmt check + validate
4. **Deploy** — Terraform apply (main branch only, requires AWS secrets)
5. **Cost Scan** — Weekly automated scan + artifact upload

---

## Real-World Impact

This type of project is used at scale by:
- **Startups** — Avoid burning runway on idle cloud resources
- **Enterprise FinOps teams** — Automated weekly cost governance
- **DevOps Engineers** — Proactive cost alerting as part of the release pipeline

---

## Author

**Anish Tiwari** — DevOps Engineer

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-blue?logo=linkedin)](https://linkedin.com/in/anishtiwari2315)
[![GitHub](https://img.shields.io/badge/GitHub-Follow-black?logo=github)](https://github.com/anishtiwari2315-art)

---

## License

MIT License — see [LICENSE](LICENSE) for details.
