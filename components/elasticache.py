import pulumi
import pulumi_aws as aws
from typing import Sequence, Optional, Mapping


class PrivateRedisArgs:
    def __init__(
        self,
        vpc_id: pulumi.Input[str],
        subnet_ids: pulumi.Input[Sequence[pulumi.Input[str]]],
        port: pulumi.Input[int] = 6379,
        instance_class: pulumi.Input[str] = "cache.t2.micro",
        number_of_nodes: pulumi.Input[int] = 1,
        tags: Optional[pulumi.Input[Mapping[str, pulumi.Input[str]]]] = None,
    ):

        self.vpc_id = vpc_id
        self.subnet_ids = subnet_ids
        self.tags = tags
        self.port = port
        self.instance_class = instance_class
        self.number_of_nodes = number_of_nodes


class PrivateRedis(pulumi.ComponentResource):

    subnet_group: aws.elasticache.SubnetGroup
    security_group: aws.ec2.SecurityGroup
    cluster: aws.elasticache.Cluster

    def __init__(
        self,
        name: str,
        args: PrivateRedisArgs,
        opts: pulumi.ResourceOptions = None,
    ):
        super().__init__("jaxxstorm:index:Redis", name, {}, opts)

        self.subnet_group = aws.elasticache.SubnetGroup(
            f"{name}-subnet-group",
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
            description=f"Security group for Private Redis {name}",
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
        
        self.cluster = aws.elasticache.Cluster(
            f"{name}-redis-cluster",
            engine="redis",
            node_type=args.instance_class,
            port=args.port,
            num_cache_nodes=args.number_of_nodes,
            subnet_group_name=self.subnet_group.name,
            security_group_ids=[self.security_group.id],
            final_snapshot_identifier=f"{name}-redis-final-snapshot",
            tags=args.tags,
            opts=pulumi.ResourceOptions(parent=self),
        )
