# =============================================================
# Terraform Variables - AWS Cloud Cost Optimizer
# =============================================================

variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name prefix for all resources"
  type        = string
  default     = "aws-cost-optimizer"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be: dev, staging, or prod."
  }
}

variable "owner" {
  description = "Owner name for tagging resources"
  type        = string
  default     = "anish-tiwari"
}

variable "alert_email" {
  description = "Email address to receive cost optimization alerts"
  type        = string
  # No default - must be provided. Set in terraform.tfvars
}

variable "cpu_threshold" {
  description = "CPU utilization threshold (%) below which EC2 is considered idle"
  type        = number
  default     = 5.0
  validation {
    condition     = var.cpu_threshold > 0 && var.cpu_threshold <= 100
    error_message = "CPU threshold must be between 0 and 100."
  }
}

variable "monthly_savings_alert_threshold" {
  description = "Monthly AWS bill threshold (USD) - alert when exceeded"
  type        = number
  default     = 100
}

variable "scan_schedule" {
  description = "CloudWatch Events cron schedule for cost scan (default: every Monday 9AM UTC)"
  type        = string
  default     = "cron(0 9 ? * MON *)"
}

variable "ebs_volume_age_threshold_days" {
  description = "Days unattached before EBS volume is flagged"
  type        = number
  default     = 7
}

variable "snapshot_age_threshold_days" {
  description = "Days old before a snapshot is flagged as stale"
  type        = number
  default     = 90
}
