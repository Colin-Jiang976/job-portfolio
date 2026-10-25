#!/usr/bin/env bash
# 由本人在 AWS CloudShell 执行。只为已有 cj-photo-api 的执行角色授予指定表/相册的 Query。
set -euo pipefail
region='ap-northeast-1'
function_name='cj-photo-api'
account_id=$(aws sts get-caller-identity --query Account --output text --no-cli-pager)
info=$(aws lambda get-function-configuration --function-name "$function_name" --region "$region" --query '[Runtime,Role]' --output text --no-cli-pager)
read -r runtime role_arn <<< "$info"
if [[ "$runtime" != 'python3.12' ]]; then
  echo '请先在原函数中换成 Python 3.12，并上传新 ZIP、设置处理程序。' >&2
  exit 1
fi
if [[ ! "$account_id" =~ ^[0-9]{12}$ ]] || [[ "$role_arn" != "arn:aws:iam::${account_id}:role/"* ]]; then
  echo '未确认当前账号内的执行角色，停止授权。' >&2
  exit 1
fi
role_name=${role_arn##*/}
work_dir=$(mktemp -d)
trap 'rm -f "$work_dir/policy.json"; rmdir "$work_dir"' EXIT
cat > "$work_dir/policy.json" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow", "Action": "dynamodb:Query",
    "Resource": "arn:aws:dynamodb:${region}:${account_id}:table/cj-photo-catalog",
    "Condition": {"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": ["ALBUM#main"]}}
  }]
}
EOF
aws iam put-role-policy --role-name "$role_name" --policy-name PhotoCatalogMainRead --policy-document "file://$work_dir/policy.json" --no-cli-pager
echo '已给 cj-photo-api 的当前执行角色添加 main 相册的 Query 权限。未运行函数，未修改表或 S3。'
