"""Deploy and operate the AWS test environment. Needs AWS credentials (aws configure) and Terraform.

  python scripts/aws_deploy.py all             # everything below, in order
  python scripts/aws_deploy.py state           # 1. Terraform state bucket + lock table, backend.hcl
  python scripts/aws_deploy.py base            # 2. network, database, registry, CodeBuild (no services yet)
  python scripts/aws_deploy.py images          # 3. build + push the five images with CodeBuild
  python scripts/aws_deploy.py database        # 4. one database and login per service (one-off ECS task)
  python scripts/aws_deploy.py infra           # 5. everything else, services start on the new images
  python scripts/aws_deploy.py users           # 6. demo users in Cognito (DEMO_PASSWORD)
  python scripts/aws_deploy.py web             # 7. build the web app and publish it to S3/CloudFront
  python scripts/aws_deploy.py env             # write .local/aws.env for the test scripts
  python scripts/aws_deploy.py scale --tasks 0 # stop all services to save cost (--tasks 2 to resume)
  python scripts/aws_deploy.py release booking # build the current commit and roll it out to one service

Environment: TERRAFORM (path to terraform), AWS_REGION (default ap-southeast-1), DEMO_PASSWORD.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import boto3

REPO = Path(__file__).resolve().parents[1]
TF_DIR = REPO / "infra" / "terraform" / "envs" / "test"
REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
TERRAFORM = os.environ.get("TERRAFORM", "terraform")
SERVICES = ["merchant", "catalogue", "availability", "booking", "notification"]
DEMO_USERS = {"admin": "platform_admin", **{u: "customer" for u in ["alice", "bob", "owner1", "owner2", "partner", "loadtester"]}}
BASE_TARGETS = [
    "aws_route_table_association.private", "aws_route_table_association.public", "aws_vpc_endpoint.s3",
    "aws_db_instance.main", "aws_secretsmanager_secret_version.database_url",
    "aws_secretsmanager_secret_version.db_bootstrap", "aws_ecr_lifecycle_policy.service",
    "aws_ecs_cluster_capacity_providers.main", "aws_ecs_task_definition.db_bootstrap",
    "aws_vpc_security_group_ingress_rule.db_from_bootstrap", "aws_codebuild_project.images",
    "aws_s3_bucket_lifecycle_configuration.build_source", "aws_s3_bucket_public_access_block.build_source",
    # role policies are not dependencies of the resources above, so -target must name them
    "aws_iam_role_policy.build", "aws_iam_role_policy_attachment.bootstrap_execution", "aws_iam_role_policy.bootstrap_secrets",
]


def session():
    return boto3.session.Session(region_name=REGION)


def account_id() -> str:
    return session().client("sts").get_caller_identity()["Account"]


def git_sha() -> str:
    """Image tag: the commit, plus a hash of uncommitted changes to anything baked into the images
    (ECR tags are immutable, so a changed image must never reuse a tag)."""
    def git(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=REPO, check=True, capture_output=True, text=True).stdout
    tag = git("rev-parse", "--short=12", "HEAD").strip()
    diff = git("diff", "HEAD", "--", "libs", "services", "docker")
    if diff:
        import hashlib
        tag += "-d" + hashlib.sha256(diff.encode()).hexdigest()[:8]
    return tag


def tf(*args: str, capture: bool = False) -> str:
    cmd = [TERRAFORM, f"-chdir={TF_DIR}", *args]
    print("$", " ".join(cmd[:4]), "..." if len(cmd) > 4 else "")
    result = subprocess.run(cmd, check=True, text=True, capture_output=capture)
    return result.stdout if capture else ""


def tf_outputs() -> dict:
    return {k: v["value"] for k, v in json.loads(tf("output", "-json", capture=True)).items()}


def tfvars(tag: str) -> list[str]:
    repo = os.environ.get("GITHUB_REPOSITORY", "LiTL0529/team9-booking-platform")
    args = ["-var", f"image_tag={tag}", "-var", f"github_repository={repo}", "-var", f"region={REGION}"]
    # Newer GitHub OIDC subjects carry numeric ids: owner@<id>/repo@<id> (see infra cicd.tf)
    for var, env in (("github_owner_id", "GITHUB_OWNER_ID"), ("github_repository_id", "GITHUB_REPOSITORY_ID")):
        if os.environ.get(env):
            args += ["-var", f"{var}={os.environ[env]}"]
    return args


# --- steps --------------------------------------------------------------------------------------

def step_state(_args) -> None:
    acct = account_id()
    bucket, table = f"booking-platform-tfstate-{acct}", "booking-platform-tflock"
    s3 = session().client("s3")
    try:
        s3.head_bucket(Bucket=bucket)
    except s3.exceptions.ClientError:
        s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION})
    s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    ddb = session().client("dynamodb")
    try:
        ddb.create_table(TableName=table, BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "LockID", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "LockID", "KeyType": "HASH"}])
        ddb.get_waiter("table_exists").wait(TableName=table)
    except ddb.exceptions.ResourceInUseException:
        pass
    (TF_DIR / "backend.hcl").write_text(
        f'bucket         = "{bucket}"\nkey            = "envs/test/terraform.tfstate"\n'
        f'region         = "{REGION}"\ndynamodb_table = "{table}"\nencrypt        = true\n', encoding="utf-8")
    tf("init", "-input=false", "-reconfigure", "-backend-config=backend.hcl")
    print(f"state in s3://{bucket}")


def step_base(args) -> None:
    targets = [f"-target={t}" for t in BASE_TARGETS]
    tf("apply", "-input=false", "-auto-approve", *tfvars(args.tag), *targets)


def build_images(tag: str) -> None:
    out = tf_outputs()
    buf = io.BytesIO()
    files = subprocess.run(["git", "ls-files"], cwd=REPO, check=True, capture_output=True, text=True).stdout.split()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            if name.startswith(("libs/", "services/", "docker/")):
                zf.write(REPO / name, name)
    session().client("s3").put_object(Bucket=out["build_source_bucket"], Key="source.zip", Body=buf.getvalue())
    cb = session().client("codebuild")
    build = cb.start_build(projectName=out["build_project"],
                           environmentVariablesOverride=[{"name": "IMAGE_TAG", "value": tag, "type": "PLAINTEXT"}])["build"]
    print(f"CodeBuild {build['id']} building tag {tag} ...")
    while True:
        time.sleep(15)
        build = cb.batch_get_builds(ids=[build["id"]])["builds"][0]
        print(f"  {build['currentPhase']:<16} {build['buildStatus']}")
        if build["buildComplete"]:
            break
    if build["buildStatus"] != "SUCCEEDED":
        for phase in build.get("phases", []):
            for ctx in phase.get("contexts", []):
                if ctx.get("message"):
                    print(f"  {phase['phaseType']}: {ctx['message']}")
        logs = build.get("logs", {})
        if logs.get("groupName") and logs.get("streamName"):
            events = session().client("logs").get_log_events(
                logGroupName=logs["groupName"], logStreamName=logs["streamName"], limit=40)["events"]
            print("\n".join(e["message"].rstrip() for e in events))
        sys.exit("image build failed")


def step_images(args) -> None:
    build_images(args.tag)


def step_database(_args) -> None:
    out = tf_outputs()
    ecs = session().client("ecs")
    task = ecs.run_task(
        cluster=out["ecs_cluster"], launchType="FARGATE", taskDefinition="booking-test-db-bootstrap",
        networkConfiguration={"awsvpcConfiguration": {
            "subnets": out["private_subnet_ids"], "securityGroups": [out["db_bootstrap_security_group"]],
            "assignPublicIp": "DISABLED"}},
    )["tasks"][0]["taskArn"]
    print(f"bootstrap task {task.split('/')[-1]} running ...")
    ecs.get_waiter("tasks_stopped").wait(cluster=out["ecs_cluster"], tasks=[task], WaiterConfig={"Delay": 10, "MaxAttempts": 60})
    detail = ecs.describe_tasks(cluster=out["ecs_cluster"], tasks=[task])["tasks"][0]
    code = detail["containers"][0].get("exitCode")
    if code != 0:
        sys.exit(f"bootstrap failed (exit {code}, {detail.get('stoppedReason')}); see /ecs/booking-test-db-bootstrap")
    print("databases and logins created")


def step_infra(args) -> None:
    tf("apply", "-input=false", "-auto-approve", *tfvars(args.tag))
    out = tf_outputs()
    ecs = session().client("ecs")
    # The services ignore task definition changes in Terraform (pipelines own deployments), so roll
    # each one onto the revision Terraform just registered for this image tag.
    for s in SERVICES:
        latest = ecs.describe_task_definition(taskDefinition=f"test-{s}")["taskDefinition"]["taskDefinitionArn"]
        current = ecs.describe_services(cluster=out["ecs_cluster"], services=[s])["services"][0]["taskDefinition"]
        if latest != current:
            ecs.update_service(cluster=out["ecs_cluster"], service=s, taskDefinition=latest)
            print(f"{s}: rolling out {latest.split('/')[-1]}")
    print("waiting for the services to become stable ...")
    ecs.get_waiter("services_stable").wait(cluster=out["ecs_cluster"], services=SERVICES,
                                           WaiterConfig={"Delay": 15, "MaxAttempts": 60})
    print("all services stable")


def step_users(_args) -> None:
    password = os.environ.get("DEMO_PASSWORD") or sys.exit("set DEMO_PASSWORD (8+ chars, upper, lower, digit)")
    pool = tf_outputs()["cognito_user_pool_id"]
    idp = session().client("cognito-idp")
    for user, group in DEMO_USERS.items():
        try:
            idp.admin_create_user(UserPoolId=pool, Username=user, MessageAction="SUPPRESS",
                                  UserAttributes=[{"Name": "email", "Value": f"{user}@example.com"},
                                                  {"Name": "email_verified", "Value": "true"}])
        except idp.exceptions.UsernameExistsException:
            pass
        idp.admin_set_user_password(UserPoolId=pool, Username=user, Password=password, Permanent=True)
        idp.admin_add_user_to_group(UserPoolId=pool, Username=user, GroupName=group)
        print(f"user {user} ({group})")


def api_key_value(key_id: str) -> str:
    return session().client("apigateway").get_api_key(apiKey=key_id, includeValue=True)["value"]


def step_web(_args) -> None:
    out = tf_outputs()
    npm = shutil.which("npm") or sys.exit("npm not found")
    if not (REPO / "web" / "node_modules").exists():  # reuse an existing install (Windows locks files on reinstall)
        subprocess.run([npm, "--prefix", str(REPO / "web"), "ci"], check=True)
    subprocess.run([npm, "--prefix", str(REPO / "web"), "run", "build"], check=True)
    dist = REPO / "web" / "dist"
    (dist / "config.json").write_text(json.dumps({
        "apiBaseUrl": "", "apiKey": api_key_value(out["api_key_ids"]["web"]), "authMode": "cognito",
        "cognitoRegion": REGION, "cognitoClientId": out["cognito_client_ids"]["web"]}), encoding="utf-8")
    s3 = session().client("s3")
    types = {".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".json": "application/json",
             ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}
    for path in dist.rglob("*"):
        if path.is_file():
            key = path.relative_to(dist).as_posix()
            cache = "no-cache" if key in ("index.html", "config.json") else "public,max-age=31536000,immutable"
            s3.upload_file(str(path), out["web_bucket"], key,
                           ExtraArgs={"ContentType": types.get(path.suffix, "application/octet-stream"), "CacheControl": cache})
    session().client("cloudfront").create_invalidation(
        DistributionId=out["cloudfront_distribution_id"],
        InvalidationBatch={"Paths": {"Quantity": 2, "Items": ["/index.html", "/config.json"]}, "CallerReference": str(time.time())})
    print(f"web app published: {out['web_url']}")


def step_env(_args) -> None:
    out = tf_outputs()
    keys = {name: api_key_value(key_id) for name, key_id in out["api_key_ids"].items()}
    env = {
        "PLATFORM_GATEWAY": out["web_url"],
        "PLATFORM_API_KEY": keys["web"],
        "LOADTEST_API_KEY": keys["loadtest"],
        "PARTNER_GATEWAY": out["web_url"],
        "PARTNER_API_KEY": keys["partner"],
        "COGNITO_CLIENT_ID": out["cognito_client_ids"]["web"],
        "PARTNER_COGNITO_CLIENT_ID": out["cognito_client_ids"]["partner"],
        "BOOKING_TOPIC_ARN": out["booking_topic_arn"],
        "NOTIFICATION_QUEUE_URL": out["notification_queue_url"],
        "AWS_REGION": REGION,
    }
    target = REPO / ".local" / "aws.env"
    target.parent.mkdir(exist_ok=True)
    target.write_text("".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8")
    print(f"wrote {target} (contains API keys; .local/ is git-ignored)")
    print(f"web: {out['web_url']}\ndashboard: {out['dashboard_url']}")


def step_scale(args) -> None:
    out = tf_outputs()
    ecs, aas = session().client("ecs"), session().client("application-autoscaling")
    for s in SERVICES:
        resource = f"service/{out['ecs_cluster']}/{s}"
        if args.tasks == 0:
            aas.register_scalable_target(ServiceNamespace="ecs", ResourceId=resource,
                                         ScalableDimension="ecs:service:DesiredCount", MinCapacity=0, MaxCapacity=0)
        else:
            limits = {"availability": 6, "booking": 5, "notification": 5}  # keep in sync with service_scaling
            aas.register_scalable_target(ServiceNamespace="ecs", ResourceId=resource,
                                         ScalableDimension="ecs:service:DesiredCount",
                                         MinCapacity=args.tasks, MaxCapacity=max(args.tasks, limits.get(s, 2)))
        ecs.update_service(cluster=out["ecs_cluster"], service=s, desiredCount=args.tasks)
        print(f"{s}: {args.tasks} tasks")


def step_release(args) -> None:
    tag = args.tag
    build_images(tag)
    out = tf_outputs()
    ecs = session().client("ecs")
    image = f"{out['ecr_repositories'][args.service]}:{tag}"
    current = ecs.describe_task_definition(taskDefinition=f"test-{args.service}")["taskDefinition"]
    for c in current["containerDefinitions"]:
        if c["name"] == "app":
            c["image"] = image
    keep = ["family", "taskRoleArn", "executionRoleArn", "networkMode", "containerDefinitions", "volumes",
            "requiresCompatibilities", "cpu", "memory", "runtimePlatform"]
    new = ecs.register_task_definition(**{k: current[k] for k in keep if k in current})["taskDefinition"]["taskDefinitionArn"]
    ecs.update_service(cluster=out["ecs_cluster"], service=args.service, taskDefinition=new)
    print(f"rolling out {image} to {args.service} ...")
    ecs.get_waiter("services_stable").wait(cluster=out["ecs_cluster"], services=[args.service],
                                           WaiterConfig={"Delay": 15, "MaxAttempts": 60})
    print("deployment complete")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["all", "state", "base", "images", "database", "infra", "users", "web",
                                         "env", "scale", "release"])
    parser.add_argument("service", nargs="?", choices=SERVICES)
    parser.add_argument("--tag", default=None, help="image tag (default: current commit)")
    parser.add_argument("--tasks", type=int, default=2)
    args = parser.parse_args()
    args.tag = args.tag or git_sha()
    steps = {"state": step_state, "base": step_base, "images": step_images, "database": step_database,
             "infra": step_infra, "users": step_users, "web": step_web, "env": step_env, "scale": step_scale,
             "release": step_release}
    if args.step == "all":
        for name in ["state", "base", "images", "database", "infra", "users", "web", "env"]:
            print(f"\n=== {name} ===")
            steps[name](args)
    elif args.step == "release":
        if not args.service:
            sys.exit("usage: aws_deploy.py release <service>")
        step_release(args)
    else:
        steps[args.step](args)


if __name__ == "__main__":
    main()
