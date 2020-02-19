#!/usr/bin/env python
import argparse
import signal
import boto3
import logging
import time
import yaml
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(prog='prometheus-ecs-sd', description='Prometheus file discovery for AWS ECS')
    parser.add_argument('-f', '--file', type=str, default='/tmp/ecs_file_sd.yml', help='File to write tasks (default: /tmp/ecs_file_sd.yml)')
    parser.add_argument('-i', '--interval', type=int, default=60, help='Interval to discover ECS tasks, seconds (default: 60)')
    parser.add_argument('-l', '--log', choices=['debug', 'info', 'warn'], default='info', help='Logging level (default: info)')
    args = parser.parse_args()
    logger.setLevel(getattr(logging, args.log.upper()))
    return args


class Discoverer:
    def __init__(self, file):
        self.file = file
        self.tasks = {}      # ecs tasks cache
        self.hosts = {}      # ec2 container instances cache
        try:
            self.ecs = boto3.client('ecs')
            self.ec2 = boto3.client('ec2')
            self.ecs.list_clusters()  # check creds
        except Exception as e:
            sys.exit(e)

    def loop(self, interval):
        signal.signal(signal.SIGINT, self.signal_handler)
        i = 0
        while True:
            self.discover()
            time.sleep(interval)
            i += 1
            # drop caches
            if i > 1440:
                i = 0
                self.tasks = {}

    def discover(self):
        targets = []
        tasks = 0
        for cluster in self.ecs.list_clusters().get('clusterArns', []):
            for page in self.ecs.get_paginator('list_tasks').paginate(cluster=cluster, launchType='EC2'):
                for arn in page.get('taskArns', []):
                    targets += self.check_task(cluster=cluster, arn=arn)
                    tasks += 1
        logger.info(f"Discovered {len(targets)} targets from {tasks} tasks")
        with open(self.file, 'w') as f:
            yaml.dump(targets, f)

    def check_task(self, cluster, arn):
        if arn not in self.tasks:
            task = self.ecs.describe_tasks(cluster=cluster, tasks=[arn])['tasks'][0]
            td = self.ecs.describe_task_definition(taskDefinition=task['taskDefinitionArn'])['taskDefinition']
            host = self.get_host_ip(cluster, task['containerInstanceArn'])
            sd = []
            for container in td['containerDefinitions']:
                labels = self.get_labels(container.get('dockerLabels', {}).get('PROMETHEUS_LABELS'))
                labels['container_name'] = container['name']
                labels['task_name'] = td['family']
                labels['task_revision'] = td['revision']
                labels['container_arn'] = [x for x in task['containers'] if x['name']==container['name']][0]['containerArn']
                scrapes = container.get('dockerLabels', {}).get('PROMETHEUS_SCRAPES')
                if scrapes:
                    for port in scrapes.split(','):
                        tmp = labels.copy()
                        if '/' in port:
                            port, path = port.split('/', maxsplit=1)
                            tmp['__metrics_path__'] = f'/{path}'
                        port = self.get_mapped_port(int(port), container, task['containers'])
                        if port is None:  # not yet mapped, skip caching
                            return []
                        sd.append({
                            'targets': [f'{host}:{port}'],
                            'labels': tmp
                        })
            self.tasks[arn] = sd
            logger.debug(f'Got task {arn} obj: {self.tasks[arn]}')
        return self.tasks[arn]

    def get_host_ip(self, cluster, arn):
        if arn not in self.hosts:
            id = self.ecs.describe_container_instances(cluster=cluster, containerInstances=[arn])['containerInstances'][0]['ec2InstanceId']
            self.hosts[arn] = self.ec2.describe_instances(InstanceIds=[id])['Reservations'][0]['Instances'][0]['PrivateIpAddress']
            logger.debug(f'Got host {arn} IP: {self.hosts[arn]}')
        return self.hosts[arn]

    # "__scheme__=https,skip_15s=true" => {"__scheme__": "https", "skip_15s": "true"}
    @staticmethod
    def get_labels(str):
        if not str:
            return {}
        try:
            return  dict(x.split('=', maxsplit=1) for x in str.split(','))
        except:
            logger.warning(f'Unable to parse Labels: {str}')

    # find host 'port' mapping of container 'definition' in running 'containers'
    @staticmethod
    def get_mapped_port(port, definition, containers):
        portmap = [x for x in definition.get('portMappings', {}) if x['containerPort']==port]
        if not portmap:
            return port  # hostNet
        if portmap[0]['hostPort'] == 0:  # dynamic host ports
            for container in containers:
                if container['name'] == definition['name']:
                    if 'networkBindings' not in container:
                        logger.info(f'Container {container["name"]} is not yet mapped to host port, skipping')
                        return None
                    for bind in container['networkBindings']:
                        if bind['containerPort'] == port:
                            return bind['hostPort']
        else:
            return portmap[0]['hostPort']  # mapped port

    @staticmethod
    def signal_handler(num, frame):
        sys.exit(0)


if __name__ == "__main__":
    args = parse_args()
    logger.debug(f"Starting with args: {args}")
    Discoverer(args.file).loop(args.interval)
