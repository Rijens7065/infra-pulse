"""Shared constants for the CloudSentro ML pipeline."""

FAILURE_MODES = [
    "NORMAL",
    "OOM_LEAK",
    "CPU_THROTTLE",
    "NETWORK_DEGRADATION",
    "COST_SPIKE",
    "SECURITY_DRIFT",
]

METRIC_CHANNELS = [
    "cpu_usage_percent",
    "memory_rss_bytes",
    "pod_restart_count",
    "http_p99_latency_ms",
    "network_bytes_in",
    "network_bytes_out",
    "azure_cost_per_hour_usd",
]

WINDOW_SIZE = 60
N_CHANNELS = len(METRIC_CHANNELS)
N_CLASSES = len(FAILURE_MODES)

MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
