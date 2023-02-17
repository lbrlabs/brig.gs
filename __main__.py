import pulumi
import json
import pulumi_aws as aws
import pulumi_random as random
import components.database as database
import components.elasticache as elasticache
import components.fargateapp as fargate

config = pulumi.Config()
recaptcha_site_key = config.require_secret("recaptcha_site_key")
recaptcha_secret_key = config.require_secret("recaptcha_secret_key")
google_safe_browsing_api_key = config.require_secret("google_safe_browsing_api_key")

stack = pulumi.get_stack()

vpc = pulumi.StackReference(f"jaxxstorm/vpc/{stack}")
vpc_id = vpc.require_output("vpc_id")
subnet_ids = vpc.require_output("private_subnet_ids")

cluster = pulumi.StackReference(f"jaxxstorm/ecs/{stack}")
cluster_arn = cluster.get_output("cluster_arn")

loadbalancer = pulumi.StackReference(f"jaxxstorm/loadbalancer/{stack}")
target_group_arn = loadbalancer.require_output("target_group_arn")
address = loadbalancer.require_output("lb_dns_name")


db = database.PrivateDatabase(
    "kutt",
    args=database.PrivateDatabaseArgs(
        vpc_id=vpc_id,
        subnet_ids=subnet_ids,
        production=True,
        db_name="kutt",
        tags={
            "Name": "kutt",
            "repo": "jaxxstorm/brig.gs",
            "environment": "production",
            "project": "kutt",
        },
    ),
)

cache = elasticache.PrivateRedis(
    "kutt",
    args=elasticache.PrivateRedisArgs(
        vpc_id=vpc_id,
        subnet_ids=subnet_ids,
        tags={
            "Name": "kutt",
            "repo": "jaxxstorm/brig.gs",
            "environment": "production",
            "project": "kutt",
        },
    ),
)

jwt_secret = random.RandomPassword(
    "kutt-jwt-secret",
    length=32,
)

mail_user = aws.iam.User(
    "kutt",
)

aws.iam.UserPolicyAttachment(
    "kutt-mail-policy-attchment",
    user=mail_user.name,
    policy_arn=aws.iam.ManagedPolicy.AMAZON_SES_FULL_ACCESS,
    opts=pulumi.ResourceOptions(parent=mail_user),
)

access_key = aws.iam.AccessKey(
    "kutt",
    user=mail_user.name,
    opts=pulumi.ResourceOptions(parent=mail_user),
)

secret = aws.secretsmanager.Secret("kutt")

secrets = aws.secretsmanager.SecretVersion(
    "kutt",
    secret_id=secret.id,
    secret_string=pulumi.Output.secret(
        pulumi.Output.json_dumps(
            {
                "RECAPTCHA_SECRET_KEY": recaptcha_secret_key,
                "RECAPTCHA_SITE_KEY": recaptcha_site_key,
                "DB_PASSWORD": db.database.password,
                "MAIL_USER": access_key.id,
                "MAIL_PASSWORD": access_key.ses_smtp_password_v4,
                "JWT_SECRET": jwt_secret.result,
                "GOOGLE_SAFE_BROWSING_KEY": google_safe_browsing_api_key,
            }
        )
    ),
    opts=pulumi.ResourceOptions(parent=secret),
)

task_role = aws.iam.Role(
    "kutt-task-role",
    assume_role_policy=json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "sts:AssumeRole",
                    "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                    "Effect": "Allow",
                    "Sid": "",
                }
            ],
        }
    ),
)

aws.iam.RolePolicyAttachment(
    "kutt-iam-policy-attchment",
    role=task_role.name,
    policy_arn=aws.iam.ManagedPolicy.AMAZON_ECS_FULL_ACCESS,
    opts=pulumi.ResourceOptions(parent=task_role),
)

kutt = fargate.WebApp(
    "kutt",
    args=fargate.WebAppArgs(
        vpc_id=vpc_id,
        subnet_ids=subnet_ids,
        image="jaxxstorm/kutt:latest",
        container_name="kutt",
        port=3000,
        command=["npm", "start"],
        secrets=[
            {
                "name": "RECAPTCHA_SECRET_KEY",
                "valueFrom": pulumi.Output.concat(
                    secret.arn, ":RECAPTCHA_SECRET_KEY::"
                ),
            },
            {
                "name": "RECAPTCHA_SITE_KEY",
                "valueFrom": pulumi.Output.concat(secret.arn, ":RECAPTCHA_SITE_KEY::"),
            },
            {
                "name": "DB_PASSWORD",
                "valueFrom": pulumi.Output.concat(secret.arn, ":DB_PASSWORD::"),
            },
            {
                "name": "JWT_SECRET",
                "valueFrom": pulumi.Output.concat(secret.arn, ":JWT_SECRET::"),
            },
            {
                "name": "MAIL_PASSWORD",
                "valueFrom": pulumi.Output.concat(secret.arn, ":MAIL_PASSWORD::"),
            },
            {
                "name": "MAIL_USER",
                "valueFrom": pulumi.Output.concat(secret.arn, ":MAIL_USER::"),
            },
            {
                "name": "GOOGLE_SAFE_BROWSING_KEY",
                "valueFrom": pulumi.Output.concat(
                    secret.arn, ":GOOGLE_SAFE_BROWSING_KEY::"
                ),
            },
        ],
        environment=[
            {
                "name": "DB_HOST",
                "value": db.database.address,
            },
            {
                "name": "DB_NAME",
                "value": db.database.db_name,
            },
            {
                "name": "DB_USER",
                "value": db.database.username,
            },
            {
                "name": "REDIS_HOST",
                "value": cache.cluster.cache_nodes[0].address,
            },
            {"name": "SITE_NAME", "value": "brig.gs"},
            {"name": "DEFAULT_DOMAIN", "value": "brig.gs"},
            {"name": " DISALLOW_ANONYMOUS_LINKS", "value": "true"},
            {
                "name": "MAIL_HOST",
                "value": "email-smtp.us-west-2.amazonaws.com",
            },
            {
                "name": "MAIL_PORT",
                "value": "587",
            },
            {
                "name": "MAIL_DEBUG",
                "value": "true",
            },
            {
                "name": "MAIL_FROM",
                "value": "urls@mail.brig.gs",
            },
            {
                "name": "MAIL_LOG",
                "value": "true",
            },
            {"name": "ADMIN_EMAILS", "value": "lee@leebriggs.co.uk"},
        ],
        target_group_arn=target_group_arn,
        task_role_arn=task_role.arn,
        cluster_arn=cluster_arn,
        register_with_loadbalancer=True,
        tags={
            "Name": "kutt",
            "repo": "jaxxstorm/brig.gs",
            "environment": "production",
            "project": "kutt",
        },
    ),
)

"""
Allow the task to access the secrets
in secrets manager
"""

secret_policy_document = aws.iam.get_policy_document_output(
    version="2012-10-17",
    statements=[
        aws.iam.GetPolicyDocumentStatementArgs(
            effect="Allow",
            actions=[
                "secretsmanager:GetSecretValue",
            ],
            resources=[secret.arn],
        )
    ],
)

secret_policy = aws.iam.Policy(
    "kutt-secret-access-policy",
    policy=secret_policy_document.json,
    opts=pulumi.ResourceOptions(parent=kutt.task_execution_role),
)

aws.iam.RolePolicyAttachment(
    "kutt-secret-policy-attchment",
    role=kutt.task_execution_role.name,
    policy_arn=secret_policy.arn,
    opts=pulumi.ResourceOptions(parent=kutt.task_execution_role),
)
