"""
dry_run_check.py — Read-only pre-war verification for ap-singapore-1.

Checks (no resources created):
  1. A1.Flex and E2.1.Micro shapes are listed in the home region AD
  2. Which Ubuntu images exist for each shape (and their versions)
  3. Current Always Free compute usage via Limits/Quotas API
"""

import oci

config = oci.config.from_file()
tenancy = config["tenancy"]
region = config["region"]

identity = oci.identity.IdentityClient(config)
compute = oci.core.ComputeClient(config)

ads = identity.list_availability_domains(compartment_id=tenancy).data
ad = ads[0].name
print(f"Region: {region} | AD: {ad}\n")

# --- 1. Shapes ---------------------------------------------------------------
shapes = compute.list_shapes(compartment_id=tenancy, availability_domain=ad).data
wanted = {"VM.Standard.A1.Flex": None, "VM.Standard.E2.1.Micro": None}
for s in shapes:
    if s.shape in wanted:
        wanted[s.shape] = s

for name, s in wanted.items():
    if s is None:
        print(f"[!] shape {name}: NOT LISTED in {ad}")
    else:
        mem = getattr(s, "memory_options", None)
        oc = getattr(s, "ocpu_options", None)
        print(f"[ok] shape {name}: listed (ocpu_options={oc}, memory_options={mem})")

# --- 2. Images ----------------------------------------------------------------
for shape in ("VM.Standard.A1.Flex", "VM.Standard.E2.1.Micro"):
    print(f"\nLatest Ubuntu images for {shape}:")
    imgs = compute.list_images(
        compartment_id=tenancy,
        operating_system="Canonical Ubuntu",
        shape=shape,
        sort_by="TIMECREATED",
        sort_order="DESC",
    ).data
    if not imgs:
        print("  (none found!)")
    for i in imgs[:4]:
        print(f"  - {i.display_name} | v{i.operating_system_version} | created {i.time_created} | {i.id}")

# --- 3. Always Free usage via Quotas API ----------------------------------------
try:
    limits = oci.limits.LimitsClient(config)
    quota = limits.get_resource_availability(
        compartment_id=tenancy,
        service_name="compute",
        limit_name="a1-flex-ocpus-count",
        availability_domain=ad,
    ).data
    print(f"\nA1 OCPU availability: used={quota.used} available={quota.available}")
except Exception as e:
    print(f"\nQuotas API check skipped: {e}")

print("\nDry run complete — nothing was created.")
