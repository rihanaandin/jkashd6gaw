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

# No OCIDs in this public repo: the instance is auto-discovered from the tenancy
# (a running Always Free Micro). Override with env INSTANCE_OCID if needed.


def find_instance_ocid():
    if os.environ.get("INSTANCE_OCID"):
        return os.environ["INSTANCE_OCID"]
    config = oci.config.from_file()
    compute = oci.core.ComputeClient(config)
    for inst in compute.list_instances(compartment_id=config["tenancy"]).data:
        if inst.shape == "VM.Standard.E2.1.Micro" and inst.lifecycle_state == "RUNNING":
            return inst.id
    raise SystemExit("No running VM.Standard.E2.1.Micro instance found in tenancy.")


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
    instance_ocid = find_instance_ocid()
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(hours=hours)
    resolution = "5m" if hours <= 6 else "1h"

    print(f"Instance : {instance_ocid}")
    print(f"Window   : last {hours} h  ({start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} UTC), res {resolution}\n")

    for stat in ("mean()", "max()", "percentile(0.95)"):
        pts = query(stat, start, end, resolution, instance_ocid)
        if not pts:
            print(f"{stat:20s}: no datapoints")
            continue
        vals = [v for _, v in pts]
        print(f"{stat:20s}: min={min(vals):.1f}%  avg={sum(vals)/len(vals):.1f}%  max={max(vals):.1f}%  ({len(vals)} points)")
        # show last few points
        for ts, v in pts[-6:]:
            print(f"    {ts:%m-%d %H:%M} UTC → {v:.1f}%")

    print("\nInterpretation: reclaim happens if p95 < 20% over 7 days.")
    print("Target: keep percentile(0.95) comfortably > 20%.")


if __name__ == "__main__":
    main()
