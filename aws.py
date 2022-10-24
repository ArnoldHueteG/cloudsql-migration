import json
import logging
import subprocess as sp
import sys
import time
import uuid


class AwsError(Exception):
    pass


class AwsApi:

    def get_sec_group(self, instance, logger=None):
        """
        :param instance: db instance identifier
        :return: the security group object for given database instance
        """
        self._logger = logger if logger is not None else logging.getLogger(__name__)
        instances_info = json.loads(
            sp.check_output(
                f"aws-okta exec okta -- aws rds describe-db-instances --db-instance-identifier {instance}".split()
            ).decode(sys.stdout.encoding))
        instance_info = instances_info['DBInstances'][0]
        sgs = instance_info['VpcSecurityGroups']
        if not sgs:
            raise AwsError(f"expected at least one security group for {instance} but none were found")
        if len(sgs) > 1:
            raise AwsError(f"expected at most one security group for {instance} but many were found")
        group_id = sgs[0]['VpcSecurityGroupId']
        sg_info = json.loads(
            sp.check_output(
                f"aws-okta exec okta -- aws ec2 describe-security-groups --group-ids={group_id}".split()
            ).decode(sys.stdout.encoding)
        )
        return sg_info['SecurityGroups'][0]

    def allow_sec_group_ip_ingress(self, instance, cidr_blocks):
        group = self.get_sec_group(instance)
        actual_cidrs = set(map(lambda x: x['CidrIp'], group['IpPermissions'][0]['IpRanges']))
        required_ips = []
        for cidr_block in cidr_blocks:
            if cidr_block not in actual_cidrs:
                required_ips.append(cidr_block)
        for required_ip in required_ips:
            sp.check_output([*'aws-okta exec okta -- aws ec2 authorize-security-group-ingress --group-id'.split(),
                             group["GroupId"], "--ip-permissions",
                             f'IpProtocol=tcp,FromPort=5432,ToPort=5432,IpRanges=[{{CidrIp={required_ip},Description="Added by cloudsql migration team for GCP access"}}]'])
        return required_ips

    def reset_rds_master_password(self, instance):
        """
        :param instance:
        :return: new master password
        """
        new_password = str(uuid.uuid4())
        command = f'aws-okta exec okta -- aws rds modify-db-instance --db-instance-identifier {instance} --master-user-password={new_password}'.split()
        sp.check_output(command)
        time.sleep(12)  # takes some time to transition to a modifying state

        # wait until password is updated
        status = 'await'
        while status != "available":
            time.sleep(1)
            instances_info = json.loads(
                sp.check_output(
                    f"aws-okta exec okta -- aws rds describe-db-instances --db-instance-identifier {instance}".split()
                ).decode(sys.stdout.encoding))
            status = instances_info["DBInstances"][0]["DBInstanceStatus"]
            self._logger.debug(f"{instance} status = '{status}' => 'available'")
        self._logger.info("reset password")
        return new_password

    def create_replication_user(self, host, database, root_username, root_password):
        """
        :param host:
        :param root_username:
        :param root_password:
        :return:
        """
        replication_password = str(uuid.uuid4())
        command = f'source psql-commands.sh; _create_replication_user {host} 5432 {database} {root_username} {root_password} {replication_password}'
        output = sp.check_output(['bash', '-c', command]).decode(sys.stdout.encoding)
        self._logger.debug(f"result of create_replication_user on {host}:\n{output}")
        return "gcp_replication", replication_password
