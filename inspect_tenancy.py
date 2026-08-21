"""
inspect_tenancy.py — Read-only check of OCI tenancy state before the "war".

Verifies:
  1. API credentials work (user / fingerprint / key_file)
  2. Home region + available Availability Domains
  3. Existing VCNs (Free tier is limited to 2 VCNs!)
  4. Existing compute instances (anything already claimed?)
  5. Boot/block volume usage vs the 200 GB Always Free quota

This script NEVER creates or modifies anything.
"""

import oci


def main():
    config = oci.config.from_file()
    tenancy = config["tenancy"]
    region = config["region"]

    print(f"Region (from config) : {region}")
    print(f"Tenancy OCID         : {tenancy}")
    print(f"User OCID            : {config['user']}")

    # --- 1. Tenancy info ---------------------------------------------------
    identity = oci.identity.IdentityClient(config)
    try:
        t = identity.get_tenancy(tenancy).data
        print(f"Home region            : {t.home_region_key}")
        print(f"Tenancy name           : {t.name}")
    except oci.exceptions.ServiceError as e:
        print(f"get_tenancy error      : {e.status} {e.code} — {e.message}")

    # --- 2. Availability domains --------------------------------------------
    ads = identity.list_availability_domains(tenancy).data
    print(f"\nAvailability domains   : {len(ads)}")
    for ad in ads:
        print(f"  - {ad.name}")

    # --- 3. VCNs (free tier limit = 2) ---------------------------------------
    network = oci.core.VirtualNetworkClient(config)
    vcns = network.list_vcns(tenancy).data
    print(f"\nVCNs in {region}       : {len(vcns)} (free tier limit = 2)")
    for v in vcns:
        print(f"  - {v.display_name or '(no name)'} | {v.cidr_block} | {v.lifecycle_state} | {v.id}")

    subnets = network.list_subnets(tenancy).data
    for s in subnets:
        print(f"    subnet: {s.display_name or '(no name)'} | {s.cidr_block} | AD={s.availability_domain} | {s.id}")

    # --- 4. Compute instances --------------------------------------------------
    compute = oci.core.ComputeClient(config)
    instances = compute.list_instances(tenancy).data
    print(f"\nCompute instances      : {len(instances)}")
    for i in instances:
        print(f"  - {i.display_name or '(no name)'} | {i.shape} | {i.lifecycle_state} | AD={i.availability_domain}")
        if i.shape_config:
            print(f"      OCPU={i.shape_config.ocpus} RAM={i.shape_config.memory_in_gbs}GB")

    # --- 5. Block volumes (boot + block count toward 200 GB) -------------------
    bv = oci.core.BlockstorageClient(config)
    boot_vols = []
    for ad in ads:
        boot_vols += bv.list_boot_volumes(
            compartment_id=tenancy, availability_domain=ad.name
        ).data
    volumes = boot_vols + bv.list_volumes(compartment_id=tenancy).data
    total_gb = sum(v.size_in_gbs or 0 for v in volumes)
    print(f"\nBlock storage used     : {total_gb} GB of 200 GB Always Free quota")
    for v in volumes:
        kind = "boot" if v.__class__.__name__ == "BootVolume" else "block"
        print(f"  - [{kind}] {v.display_name or '(no name)'} | {v.size_in_gbs} GB | {v.lifecycle_state}")

    print("\nInspection done. No resources were created or changed.")


if __name__ == "__main__":
    main()
