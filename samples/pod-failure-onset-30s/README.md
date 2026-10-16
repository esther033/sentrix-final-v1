# Pod failure telemetry sample

This package is a 30-second slice around the start of the accepted
`m2-pod-failure-checkoutservice-005` incident. The Parquet files were filtered
from the run's canonical view without changing their column schemas or data
types.

Window: `[2026-09-26T08:27:21.505381Z, 2026-09-26T08:27:51.505381Z)`

| File | Rows | Purpose |
|---|---:|---|
| `metrics.parquet` | 4,395 | CPU, memory, call-rate, error, and latency metric observations |
| `logs.parquet` | 3,744 | Kubernetes container logs with resolved service identity |
| `traces.parquet` | 6,723 | OTel spans with trace hierarchy, timing, status, resource, and span attributes |
| `incident-label.yaml` | 1 incident | Fault target, injection/removal times, impact, recovery, control pairing, and validity |

The canonical schema intentionally stores the full original OTel/label payloads
in columns such as `labels_json`, `raw_span_json`, and
`resource_attributes_json`. Those columns remain strings exactly as in the
working dataset; the surrounding table is Parquet with typed timestamps,
numeric values, booleans, and IDs.

The three telemetry files contain all services observed in the window, not only
`checkoutservice`. This preserves the cross-service evidence needed for RCA.
