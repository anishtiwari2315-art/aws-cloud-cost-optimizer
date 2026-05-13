# =============================================================
# AWS Cloud Cost Optimizer - Terraform Infrastructure
# Provisions: Lambda + SNS + CloudWatch Events for automated
# cost scanning and alerting
# Author: Anish Tiwari
# =============================================================

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  # Uncomment to use S3 backend for team use
  # backend "s3" {
  #   bucket = "your-terraform-state-bucket"
  #   key    = "cost-optimizer/terraform.tfstate"
  #   region = "us-east-1"
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "aws-cloud-cost-optimizer"
      ManagedBy   = "Terraform"
      Owner       = var.owner
      Environment = var.environment
    }
  }
}

# ---------------------------------------------------------------
# Data Sources
# ---------------------------------------------------------------
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ---------------------------------------------------------------
# SNS Topic for Cost Alerts
# ---------------------------------------------------------------
resource "aws_sns_topic" "cost_alerts" {
  name = "${var.project_name}-cost-alerts"

  tags = {
    Name = "${var.project_name}-cost-alerts"
  }
}

resource "aws_sns_topic_subscription" "email_alert" {
  topic_arn = aws_sns_topic.cost_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ---------------------------------------------------------------
# IAM Role for Lambda
# ---------------------------------------------------------------
resource "aws_iam_role" "lambda_role" {
  name = "${var.project_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_cost_optimizer_policy" {
  name = "${var.project_name}-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EC2ReadAccess"
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:DescribeRegions",
          "ec2:DescribeVolumes",
          "ec2:DescribeSnapshots",
          "ec2:DescribeAddresses"
        ]
        Resource = "*"
      },
      {
        Sid    = "CloudWatchReadAccess"
        Effect = "Allow"
        Action = [
          "cloudwatch:GetMetricStatistics",
          "cloudwatch:ListMetrics"
        ]
        Resource = "*"
      },
      {
        Sid    = "S3ReadAccess"
        Effect = "Allow"
        Action = [
          "s3:ListAllMyBuckets",
          "s3:GetBucketLocation",
          "s3:GetBucketLifecycleConfiguration",
          "s3:GetBucketVersioning",
          "s3:GetPublicAccessBlock"
        ]
        Resource = "*"
      },
      {
        Sid    = "CostExplorerAccess"
        Effect = "Allow"
        Action = [
          "ce:GetCostAndUsage",
          "ce:GetCostForecast",
          "ce:GetRecommendations"
        ]
        Resource = "*"
      },
      {
        Sid    = "SNSPublish"
        Effect = "Allow"
        Action = ["sns:Publish"]
        Resource = aws_sns_topic.cost_alerts.arn
      },
      {
        Sid    = "S3ReportsWrite"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject"
        ]
        Resource = "${aws_s3_bucket.reports_bucket.arn}/*"
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# ---------------------------------------------------------------
# S3 Bucket for Reports
# ---------------------------------------------------------------
resource "aws_s3_bucket" "reports_bucket" {
  bucket = "${var.project_name}-reports-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "${var.project_name}-reports"
  }
}

resource "aws_s3_bucket_versioning" "reports_versioning" {
  bucket = aws_s3_bucket.reports_bucket.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "reports_block" {
  bucket                  = aws_s3_bucket.reports_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "reports_lifecycle" {
  bucket = aws_s3_bucket.reports_bucket.id

  rule {
    id     = "expire-old-reports"
    status = "Enabled"

    expiration {
      days = 90
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# ---------------------------------------------------------------
# Lambda Function - Cost Scanner
# ---------------------------------------------------------------
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/lambda_function.zip"
}

resource "aws_lambda_function" "cost_scanner" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "${var.project_name}-scanner"
  role             = aws_iam_role.lambda_role.arn
  handler          = "lambda_handler.handler"
  runtime          = "python3.11"
  timeout          = 900  # 15 minutes
  memory_size      = 256
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  environment {
    variables = {
      SNS_TOPIC_ARN     = aws_sns_topic.cost_alerts.arn
      REPORTS_BUCKET    = aws_s3_bucket.reports_bucket.bucket
      CPU_THRESHOLD     = tostring(var.cpu_threshold)
      ALERT_THRESHOLD   = tostring(var.monthly_savings_alert_threshold)
    }
  }

  tags = {
    Name = "${var.project_name}-scanner"
  }
}

resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.cost_scanner.function_name}"
  retention_in_days = 14
}

# ---------------------------------------------------------------
# CloudWatch Event Rule - Weekly Schedule (Monday 9AM UTC)
# ---------------------------------------------------------------
resource "aws_cloudwatch_event_rule" "weekly_scan" {
  name                = "${var.project_name}-weekly-scan"
  description         = "Triggers cost optimization scan every Monday at 9AM UTC"
  schedule_expression = var.scan_schedule

  tags = {
    Name = "${var.project_name}-weekly-scan"
  }
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.weekly_scan.name
  target_id = "cost-scanner-lambda"
  arn       = aws_lambda_function.cost_scanner.arn
}

resource "aws_lambda_permission" "allow_cloudwatch" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cost_scanner.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.weekly_scan.arn
}

# ---------------------------------------------------------------
# CloudWatch Alarms - Budget Alert (if cost > threshold)
# ---------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "high_ec2_cost" {
  alarm_name          = "${var.project_name}-high-ec2-spend"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "EstimatedCharges"
  namespace           = "AWS/Billing"
  period              = 86400
  statistic           = "Maximum"
  threshold           = var.monthly_savings_alert_threshold
  alarm_description   = "Monthly AWS estimated charges exceed threshold"
  alarm_actions       = [aws_sns_topic.cost_alerts.arn]

  dimensions = {
    Currency = "USD"
  }

  tags = {
    Name = "${var.project_name}-billing-alarm"
  }
}
