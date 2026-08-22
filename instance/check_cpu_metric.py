"""
check_cpu_metric.py — query the OCI Monitoring metric that Oracle itself uses
for idle-reclaim decisions (CpuUtilization, namespace oci_computeagent).

Run locally:  .venv/bin/python instance/check_cpu_metric.py [hours]
  [hours] = lookback window (default 6)

Purpose: empirically verify the anti-idle warmer keeps CPU utilization above
the 20% idle threshold, as measured by Oracle (not by top inside the VM).
"""

import os
import sys
import datetime
import oci

# No OCIDs in this public repo: instances are auto-discovered from the tenancy
# (all running Always Free Micros). Override with env INSTANCE_OCID to check one.


def find_micro_instances():
    """Return list of (display_name, ocid) for running Micro instances."""
    if os.environ.get("INSTANCE_OCID"):
        return [("override", os.environ["INSTANCE_OCID"])]
    config = oci.config.from_file()
    compute = oci.core.ComputeClient(config)
    found = []
    for inst in compute.list_instances(compartment_id=config["tenancy"]).data:
        if inst.shape == "VM.Standard.E2.1.Micro" and inst.lifecycle_state == "RUNNING":
            found.append((inst.display_name, inst.id))
    if not found:
        raise SystemExit("No running VM.Standard.E2.1.Micro instance found in tenancy.")
    return found


def query(statistic, start, end, resolution, instance_ocid):
    config = oci.config.from_file()
    monitoring = oci.monitoring.MonitoringClient(config)
    tenancy = config["tenancy"]
    resp = monitoring.summarize_metrics_data(
        compartment_id=tenancy,
        summarize_metrics_data_details=oci.monitoring.models.SummarizeMetricsDataDetails(
            namespace="oci_computeagent",
            query=f"CpuUtilization[{resolution}].{statistic}",
            start_time=start,
            end_time=end,
        ),
    )
    points = []
    for item in resp.data:
        dims = item.dimensions or {}
        if dims.get("resourceId") and dims["resourceId"] != instance_ocid:
            continue  # only our instance
        for dp in item.aggregated_datapoints or []:
            points.append((dp.timestamp, dp.value))
    return sorted(points)


def main():
    hours = float(sys.argv[1]) if len(sys.argv) > 1 else 6
    instances = find_micro_instances()
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(hours=hours)
    resolution = "5m" if hours <= 6 else "1h"

    print(f"Window : last {hours} h  ({start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} UTC), res {resolution}")
    print(f"Target : percentile(0.95) > 20% (reclaim if p95 < 20% over 7 days)\n")

    for name, instance_ocid in instances:
        print(f"=== {name} ===")
        print(f"    {instance_ocid}")
        for stat in ("mean()", "max()", "percentile(0.95)"):
            pts = query(stat, start, end, resolution, instance_ocid)
            if not pts:
                print(f"    {stat:20s}: no datapoints")
                continue
            vals = [v for _, v in pts]
            print(f"    {stat:20s}: min={min(vals):.1f}%  avg={sum(vals)/len(vals):.1f}%  max={max(vals):.1f}%  ({len(vals)} points)")
        print()


if __name__ == "__main__":
    main()
