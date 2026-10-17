#!/usr/bin/env bash
# First-time setup of the AWS test environment. Run from the repository root with AWS
# credentials for the target account. Idempotent where AWS allows it.
#
#   ./scripts/aws_bootstrap.sh state      # 1. Terraform state bucket + lock table
#   ./scripts/aws_bootstrap.sh images     # 2. push a "bootstrap" image of every service to ECR
#   ./scripts/aws_bootstrap.sh database   # 3. create one database and login per service
#   ./scripts/aws_bootstrap.sh users      # 4. demo users in Cognito
set -euo pipefail

REGION=${AWS_REGION:-ap-southeast-1}
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
TF_DIR=infra/terraform/envs/test
tf() { terraform -chdir="$TF_DIR" output -raw "$1"; }

case "${1:-}" in
  state)
    BUCKET="booking-platform-tfstate-$ACCOUNT"
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION" 2>/dev/null || true
    aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
    aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
    aws dynamodb create-table --table-name booking-platform-tflock --billing-mode PAY_PER_REQUEST \
      --attribute-definitions AttributeName=LockID,AttributeType=S \
      --key-schema AttributeName=LockID,KeyType=HASH --region "$REGION" 2>/dev/null || true
    echo "state bucket: $BUCKET  (put it in $TF_DIR/backend.hcl)"
    ;;
  images)
    REGISTRY="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
    aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
    for s in merchant catalogue availability booking notification; do
      docker build -f docker/service.Dockerfile --build-arg SERVICE=$s -t "$REGISTRY/booking/$s:bootstrap" .
      docker push "$REGISTRY/booking/$s:bootstrap"
    done
    ;;
  database)
    aws ecs run-task --region "$REGION" --cluster "$(tf ecs_cluster)" --launch-type FARGATE \
      --task-definition "booking-test-db-bootstrap" \
      --network-configuration "awsvpcConfiguration={subnets=[$(terraform -chdir=$TF_DIR output -json private_subnet_ids | tr -d '[]" ')],securityGroups=[$(tf db_bootstrap_security_group)],assignPublicIp=DISABLED}" \
      --query 'tasks[0].taskArn' --output text
    echo "follow the logs in CloudWatch: /ecs/booking-test-db-bootstrap; then restart the services:"
    echo "  for s in merchant catalogue availability booking notification; do aws ecs update-service --cluster $(tf ecs_cluster) --service \$s --force-new-deployment >/dev/null; done"
    ;;
  users)
    POOL=$(tf cognito_user_pool_id)
    PASSWORD=${DEMO_PASSWORD:?set DEMO_PASSWORD (8+ chars, upper, lower, digit)}
    create() {
      aws cognito-idp admin-create-user --user-pool-id "$POOL" --username "$1" \
        --user-attributes Name=email,Value="$1@example.com" Name=email_verified,Value=true \
        --message-action SUPPRESS >/dev/null 2>&1 || true
      aws cognito-idp admin-set-user-password --user-pool-id "$POOL" --username "$1" --password "$PASSWORD" --permanent
      aws cognito-idp admin-add-user-to-group --user-pool-id "$POOL" --username "$1" --group-name "$2"
      echo "user $1 ($2)"
    }
    create admin platform_admin
    for u in alice bob owner1 owner2 partner loadtester; do create "$u" customer; done
    ;;
  *)
    sed -n '2,10p' "$0"
    exit 1
    ;;
esac
