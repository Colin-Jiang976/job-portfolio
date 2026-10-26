#!/usr/bin/env bash
# 本人 CloudShell 执行：让现有 CloudFront 分配调用现有 Lambda URL，绝不授予匿名访问。
set -euo pipefail
region='ap-northeast-1'
function_name='cj-photo-api'
distribution_id='E1EXJ282JJY07Q'
auth_type=$(aws lambda get-function-url-config --function-name "$function_name" --region "$region" --query AuthType --output text --no-cli-pager)
if [[ "$auth_type" != 'AWS_IAM' ]]; then
  echo '请先创建授权类型为 AWS_IAM 的函数 URL；本脚本不会将接口设为公开。' >&2
  exit 1
fi
source_arn=$(aws cloudfront get-distribution --id "$distribution_id" --query Distribution.ARN --output text --no-cli-pager)
if [[ ! "$source_arn" =~ ^arn:aws:cloudfront::[0-9]{12}:distribution/E1EXJ282JJY07Q$ ]]; then
  echo '未核对到指定 CloudFront 分配，停止授权。' >&2
  exit 1
fi
aws lambda add-permission --function-name "$function_name" --region "$region" \
  --statement-id PortfolioCloudFrontUrl --action lambda:InvokeFunctionUrl \
  --principal cloudfront.amazonaws.com --source-arn "$source_arn" \
  --function-url-auth-type AWS_IAM --no-cli-pager >/dev/null
aws lambda add-permission --function-name "$function_name" --region "$region" \
  --statement-id PortfolioCloudFrontInvoke --action lambda:InvokeFunction \
  --principal cloudfront.amazonaws.com --source-arn "$source_arn" \
  --invoked-via-function-url --no-cli-pager >/dev/null
echo '已允许指定 CloudFront 分配通过函数 URL 调用 cj-photo-api。未开放匿名访问，未修改执行角色或表数据。'
