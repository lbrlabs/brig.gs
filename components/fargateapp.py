import pulumi
import json
import pulumi_aws as aws
from typing import Sequence, Optional, Mapping, TypedDict


class WebAppArgs:
    def __init__(
        self,
        vpc_id: pulumi.Input[str],
        subnet_ids: pulumi.Input[Sequence[pulumi.Input[str]]],
        image: pulumi.Input[str],
        container_name: pulumi.Input[str],
        cluster_arn: pulumi.Input[str],
        register_with_loadbalancer: pulumi.Input[bool] = True,
        port: pulumi.Input[int] = 80,
        memory: pulumi.Input[str] = "512",
        cpu: pulumi.Input[str] = "256",
        desired_container_count: pulumi.Input[int] = 1,
        log_group_retention: pulumi.Input[int] = 3,
        task_role_arn: pulumi.Input[str] = None,
        command: Optional[pulumi.Input[Sequence[pulumi.Input[str]]]] = None,
        tags: Optional[pulumi.Input[Mapping[str, pulumi.Input[str]]]] = None,
        environment: Optional[pulumi.Input[Mapping[str, pulumi.Input[str]]]] = None,
        secrets: Optional[pulumi.Input[Mapping[str, pulumi.Input[str]]]] = None,
        target_group_arn: Optional[pulumi.Input[str]] = None,
    ):
        self.vpc_id = vpc_id
        self.subnet_ids = subnet_ids
        self.port = port
        self.tags = tags
        self.image = image
        self.memory = memory
        self.cluster_arn = cluster_arn
        self.task_role_arn = task_role_arn
        self.cpu = cpu
        self.log_group_retention = log_group_retention
        self.container_name = container_name
        self.environment = environment
        self.command = command
        self.desired_container_count = desired_container_count
        self.register_with_loadbalancer = register_with_loadbalancer
        self.target_group_arn = target_group_arn
        self.secrets = secrets


class WebApp(pulumi.ComponentResource):

    security_group: aws.ec2.SecurityGroup
    task_execution_role: aws.iam.Role
    task_definition: aws.ecs.TaskDefinition
    service: aws.ecs.Service
    svc_discovery_service: Optional[aws.servicediscovery.Service]

    def __init__(
        self,
        name: str,
        args: WebAppArgs,
        opts: pulumi.ResourceOptions = None,
    ):
        super().__init__("jaxxstorm:index:WebApp", name, {}, opts)

        """ 
        we retrieve the VPC to get the CIDR block
        """
        vpc = aws.ec2.get_vpc(
            id=args.vpc_id,
            opts=pulumi.InvokeOptions(parent=self),
        )

        self.security_group = aws.ec2.SecurityGroup(
            name,
            vpc_id=args.vpc_id,
            description=f"Web application security group for {name}",
            ingress=[
                aws.ec2.SecurityGroupIngressArgs(
                    protocol="tcp",
                    from_port=args.port,
                    to_port=args.port,
                    cidr_blocks=[vpc.cidr_block],
                )
            ],
            egress=[
                aws.ec2.SecurityGroupEgressArgs(
                    protocol="-1",
                    from_port=0,
                    to_port=0,
                    cidr_blocks=["0.0.0.0/0"],
                )
            ],
            tags=args.tags,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.log_group = aws.cloudwatch.LogGroup(
            name,
            retention_in_days=args.log_group_retention,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.task_execution_role = aws.iam.Role(
            name,
            assume_role_policy=json.dumps(
                {
                    "Version": "2008-10-17",
                    "Statement": [
                        {
                            "Sid": "",
                            "Effect": "Allow",
                            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                }
            ),
            opts=pulumi.ResourceOptions(parent=self),
        )

        aws.iam.RolePolicyAttachment(
            name,
            role=self.task_execution_role.name,
            policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
            opts=pulumi.ResourceOptions(parent=self.task_execution_role),
        )

        self.task_definition = aws.ecs.TaskDefinition(
            name,
            family=name,
            cpu=args.cpu,
            memory=args.memory,
            network_mode="awsvpc",
            execution_role_arn=self.task_execution_role.arn,
            task_role_arn=args.task_role_arn,
            requires_compatibilities=["FARGATE"],
            container_definitions=pulumi.Output.json_dumps(
                [
                    {
                        "name": args.container_name,
                        "image": args.image,
                        "secrets": args.secrets,
                        "environment": args.environment,
                        "command": args.command,
                        "portMappings": [
                            {
                                "containerPort": args.port,
                                "protocol": "tcp",
                                "name": "http",
                            }
                        ],
                        "logConfiguration": {
                            "logDriver": "awslogs",
                            "options": {
                                "awslogs-group": self.log_group.id,
                                "awslogs-region": aws.get_region().name,
                                "awslogs-stream-prefix": pulumi.Output.concat(
                                    name, "-", args.container_name
                                ),
                            },
                        },
                    }
                ]
            ),
            tags=args.tags,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.service = aws.ecs.Service(
            name,
            cluster=args.cluster_arn,
            desired_count=args.desired_container_count,
            launch_type="FARGATE",
            task_definition=self.task_definition.arn,
            load_balancers=[
                aws.ecs.ServiceLoadBalancerArgs(
                    container_name=args.container_name,
                    container_port=args.port,
                    target_group_arn=args.target_group_arn,
                )
            ] if args.register_with_loadbalancer else None,
            network_configuration=aws.ecs.ServiceNetworkConfigurationArgs(
                security_groups=[self.security_group.id],
                assign_public_ip=False,
                subnets=args.subnet_ids,
            ),
            tags=args.tags,
            opts=pulumi.ResourceOptions(parent=self.task_definition),
        )