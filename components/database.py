import pulumi
import pulumi_aws as aws
import pulumi_random as random
from typing import Sequence, Optional, Mapping


class PrivateDatabaseArgs:
    def __init__(
        self,
        vpc_id: pulumi.Input[str],
        subnet_ids: pulumi.Input[Sequence[pulumi.Input[str]]],
        db_name: pulumi.Input[str],
        production: bool = False,
        disk_size: pulumi.Input[int] = 10,
        engine: pulumi.Input[str] = "postgres",
        port: pulumi.Input[int] = 5432,
        engine_version: pulumi.Input[str] = "13.7",
        instance_class: pulumi.Input[str] = "db.t3.micro",
        username: pulumi.Input[str] = "administrator",
        password: Optional[pulumi.Input[str]] = None,
        tags: Optional[pulumi.Input[Mapping[str, pulumi.Input[str]]]] = None,
    ):
        self.production = production
        self.vpc_id = vpc_id
        self.subnet_ids = subnet_ids
        self.db_name = db_name
        self.disk_size = disk_size
        self.engine = engine
        self.engine_version = engine_version
        self.instance_class = instance_class
        self.username = username
        self.password = password
        self.tags = tags
        self.port = port


class PrivateDatabase(pulumi.ComponentResource):

    subnet_group: aws.rds.SubnetGroup
    security_group: aws.ec2.SecurityGroup
    database: aws.rds.Instance
    admin_password: aws.ssm.Parameter

    def __init__(
        self,
        name: str,
        args: PrivateDatabaseArgs,
        opts: pulumi.ResourceOptions = None,
    ):
        super().__init__("jaxxstorm:index:Database", name, {}, opts)

        self.subnet_group = aws.rds.SubnetGroup(
            name,
            description=f"Subnet group for {name}",
            subnet_ids=args.subnet_ids,
            tags=args.tags,
            opts=pulumi.ResourceOptions(parent=self),
        )
        """ 
        we retrieve the VPC to get the CIDR block
        """
        vpc = aws.ec2.get_vpc(
            id=args.vpc_id,
            opts=pulumi.InvokeOptions(parent=self),
        )
        """
        we allow access to the entire vpc
        to the database
        """
        self.security_group = aws.ec2.SecurityGroup(
            name,
            description=f"Security group for PrivateDatabase {name}",
            vpc_id=args.vpc_id,
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

        """
        check if there's a password set in args
        if not, generate a random password using the random provider
        """
        if args.password is None:
            password_result = random.RandomPassword(
                name, length=16, special=True, override_special="@"
            )
            password = password_result.result
        else:
            password = args.password

        """
        we need some randomness in the snapshot so that we don't run into
        deletion issues
        """
        snapshot_identifier = random.RandomString(
            name,
            length=4,
            opts=pulumi.ResourceOptions(parent=self),
        )

        self.database = aws.rds.Instance(
            name,
            db_subnet_group_name=self.subnet_group.name,
            allocated_storage=args.disk_size,
            copy_tags_to_snapshot=True,
            db_name=args.db_name,
            engine=args.engine,
            instance_class=args.instance_class,
            engine_version=args.engine_version,
            vpc_security_group_ids=[self.security_group.id],
            username=args.username,
            password=password,
            tags=args.tags,
            skip_final_snapshot=False if args.production else True,
            final_snapshot_identifier=pulumi.Output.format(
                "name-{0}-deleted", snapshot_identifier.result
            ),
            opts=pulumi.ResourceOptions(parent=self.subnet_group),
        )

        """
        store the admin password in aws ssm parameterstore
        """
        self.admin_password = aws.ssm.Parameter(
            name,
            type="SecureString",
            value=self.database.password,
            tags=args.tags,
            opts=pulumi.ResourceOptions(parent=self),
        )
