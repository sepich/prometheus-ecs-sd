# Prometheus file discovery for AWS ECS

This adds ability to dynamically discover targets to scrape in AWS ECS cluster. Prometheus integration via static [file_sd_config](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#file_sd_config) is used for that.

### Why yet another implementation?
There are at least 2 other great implementations of same idea:
 - [teralytics/prometheus-ecs-discovery](https://github.com/teralytics/prometheus-ecs-discovery) in Go
 - [signal-ai/prometheus-ecs-sd](https://github.com/signal-ai/prometheus-ecs-sd) in Python

Unfortunately both of them do not support scraping the same single container on multiple ports (and /urls).

### Usage

Set [dockerLabels](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html#container_definition_labels) of Containers in your Tasks:
```json
"dockerLabels": {
    "PROMETHEUS_SCRAPES": "8080/internal/metrics,9106",
    "PROMETHEUS_LABELS": "__scheme__=https,skip_15s=true"
},
```
- `PROMETHEUS_SCRAPES` is comma delimited list of `port/metric_path` to scrape. Note that `metric_path=/metric` by default, so usually you only need to provide `port` only. This could be single value, for one port to scrape on container
- `PROMETHEUS_LABELS` (optional) comma delimited list of `key=value` labels to add to your container in Prometheus. This is the way to have some containers scraped 15s or 1m via multiple targets with [relabel_configs](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#relabel_config) and `action: keep`

Start discoverer:
```bash
docker run -it --rm -v /tmp:/tmp -e AWS_ACCESS_KEY_ID=AKIAXXX -e AWS_SECRET_ACCESS_KEY=xxx -e AWS_DEFAULT_REGION=eu-west-1 sepa/ecs-sd -h
usage: prometheus-ecs-sd [-h] [-f FILE] [-i INTERVAL] [-l {debug,info,warn}]

Prometheus file discovery for AWS ECS

optional arguments:
  -h, --help            show this help message and exit
  -f FILE, --file FILE  File to write tasks (default: /tmp/ecs_file_sd.yml)
  -i INTERVAL, --interval INTERVAL
                        Interval to discover ECS tasks, seconds (default: 60)
  -l {debug,info,warn}, --log {debug,info,warn}
                        Logging level (default: info)
  -p PORT, --port PORT  Port to serve /metrics (default: 8080)
```
Verify that you get valid `/tmp/ecs_file_sd.yml`:
```yaml
- labels:
    container_arn: arn:aws:ecs:eu-west-1:111:container/064c4ef7-6bb2-4ec3-b619-e0d6896f52c4
    container_name: backend-dev
    task_name: backend
    task_revision: 52
    __metrics_path__: /internal/metrics
  targets:
  - 10.0.0.3:32342
- labels:
    container_arn: arn:aws:ecs:eu-west-1:111:container/064c4ef7-6bb2-4ec3-b619-e0d6896f52c4
    container_name: backend-dev
    task_name: backend
    task_revision: 52
  targets:
  - 10.0.0.3:32799
- labels:
    container_arn: arn:aws:ecs:eu-west-1:111:container/978972c8-646d-49cc-9933-4bb3daa2eeea
    container_name: node-exporter
    task_name: node-exporter
    task_revision: 13
  targets:
  - 10.0.0.3:9100
- labels:
    container_arn: arn:aws:ecs:eu-west-1:111:container/7abd91d2-091d-4f12-80a7-14c279260aac
    container_name: cadvisor
    task_name: cadvisor
    task_revision: 8
  targets:
  - 10.0.0.3:32798
```
By default this file would be updated each 60s. Script caches API responses to not hit AWS API limits, but anyway it have to list all Tasks each time, so do not set `--interval` too low.

Integrate to Prometheus:
```yaml
scrape_configs:
# you only need this part
  - job_name: ecs
    file_sd_configs:
      - files:
        - /prometheus/sd/ecs_file_sd.yml
        refresh_interval: 1m

# optional relabel example 
    relabel_configs:
      # fix instance from host:mapped_port to containername-rev-hash
      - source_labels: [container_name, task_revision, container_arn]
        action: replace
        regex: (.*);(.*);.*-(.*)
        replacement: $1-$2-$3
        target_label: instance
      # leave as ip for node-exporter and cadvisor
      - source_labels: [container_name, __address__]
        regex: (node-exporter|cadvisor);([^:]+)([\.:].*)?
        replacement: $2
        target_label: instance
      # not needed anymore
      - regex: container_arn
        action: labeldrop
```

Minimal IAM policy for discoverer:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": [
        "ECS:ListClusters",
        "ECS:ListTasks",
        "ECS:DescribeTask",
        "ECS:DescribeClusters",
        "ECS:DescribeContainerInstances",
        "ECS:DescribeTasks",
        "ECS:DescribeTaskDefinition",
        "EC2:DescribeInstances"
      ],
      "Effect": "Allow",
      "Resource": "*"
    }
  ]
}
```

### ECS Metrics
This container also could expose ECS metrics (which are not available in CloudWatch) in Prometheus format on port `8080` and path `/metrics`:
```
ecs_service_desired_tasks{service="node-exporter"} 1
ecs_service_running_tasks{service="node-exporter"} 1
ecs_service_pending_tasks{service="node-exporter"} 0
```
These metrics are not cached, so each scrape would lead to `describe_service` API call. 

### TODO
 - No FARGATE support yet, as I have only EC2 ECS clusters
