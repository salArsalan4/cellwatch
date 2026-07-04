from aws_lambda_powertools import Logger, Metrics, Tracer

_METRICS_NAMESPACE = "CellWatch"


def get_logger(service: str) -> Logger:
    return Logger(service=service)


def get_metrics(service: str) -> Metrics:
    return Metrics(namespace=_METRICS_NAMESPACE, service=service)


def get_tracer() -> Tracer:
    return Tracer()
