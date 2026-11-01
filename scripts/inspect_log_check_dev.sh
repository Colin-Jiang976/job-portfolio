#!/usr/bin/env bash
# 由本人在已登录的AWS CloudShell执行。仅查询，不创建/更新/删除资源。
set -euo pipefail
TASK_REGION="${AWS_REGION:-ap-northeast-1}"
if [[ $# -eq 0 ]]; then
  aws lambda list-functions --region "$TASK_REGION" \
    --query 'Functions[].{Name:FunctionName,Runtime:Runtime,Handler:Handler}' --output table --no-cli-pager
  exit 0
fi
if [[ $# -ne 1 || ! "$1" =~ ^[A-Za-z0-9_-]{1,64}$ ]]; then
  echo 'Usage: bash inspect_log_check_dev.sh [exact-existing-function-name]' >&2
  exit 1
fi
TASK_FUNCTION="$1"
# 不输出全部环境变量，只查看旧源码中明确使用的三个资源配置。
aws lambda get-function-configuration --region "$TASK_REGION" --function-name "$TASK_FUNCTION" \
  --query '{Function:FunctionName,Runtime:Runtime,Handler:Handler,State:State,LastUpdate:LastUpdateStatus,Role:Role,Input:Environment.Variables.INPUT_BUCKET,Results:Environment.Variables.RESULTS_BUCKET,Topic:Environment.Variables.ALERT_TOPIC_ARN,Logging:LoggingConfig}' \
  --output json --no-cli-pager
TASK_INPUT="$(aws lambda get-function-configuration --region "$TASK_REGION" --function-name "$TASK_FUNCTION" --query 'Environment.Variables.INPUT_BUCKET' --output text --no-cli-pager)"
TASK_RESULTS="$(aws lambda get-function-configuration --region "$TASK_REGION" --function-name "$TASK_FUNCTION" --query 'Environment.Variables.RESULTS_BUCKET' --output text --no-cli-pager)"
TASK_TOPIC="$(aws lambda get-function-configuration --region "$TASK_REGION" --function-name "$TASK_FUNCTION" --query 'Environment.Variables.ALERT_TOPIC_ARN' --output text --no-cli-pager)"
if [[ "$TASK_INPUT" == None || "$TASK_RESULTS" == None || "$TASK_TOPIC" == None ]]; then
  echo 'Expected existing Log Check variables missing; stop and verify the selected function.' >&2
  exit 1
fi
aws s3api head-bucket --bucket "$TASK_INPUT" --region "$TASK_REGION" --no-cli-pager
aws s3api head-bucket --bucket "$TASK_RESULTS" --region "$TASK_REGION" --no-cli-pager
aws s3api get-bucket-notification-configuration --bucket "$TASK_INPUT" --region "$TASK_REGION" --output json --no-cli-pager
aws lambda get-policy --function-name "$TASK_FUNCTION" --region "$TASK_REGION" --output json --no-cli-pager
# 只看订阅协议和确认状态，不输出邮箱地址。
aws sns list-subscriptions-by-topic --topic-arn "$TASK_TOPIC" --region "$TASK_REGION" \
  --query 'Subscriptions[].{Protocol:Protocol,Confirmed:starts_with(SubscriptionArn, `arn:`)}' --output json --no-cli-pager
# 照片API本轮只核对日志格式/级别，不改其资源。
aws lambda get-function-configuration --function-name cj-photo-api --region "$TASK_REGION" \
  --query '{Function:FunctionName,Runtime:Runtime,Handler:Handler,Logging:LoggingConfig}' --output json --no-cli-pager
