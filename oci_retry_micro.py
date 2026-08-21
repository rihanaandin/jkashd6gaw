import oci
import time
import random
import datetime

# ╔══════════════════════════════════════════════════════╗
# ║  Target : VM.Standard.E2.1.Micro (x86 AMD)           ║
# ║  Spec   : 1 OCPU / 1 GB RAM / 50 GB boot (default)   ║
# ║  Tier   : Oracle Always Free (max 2 per tenancy)     ║
# ║  Region : ap-singapore-1 (single AD)                 ║
# ║  OS     : Canonical Ubuntu 22.04                     ║
# ╚══════════════════════════════════════════════════════╝

# ─── Configuration ───────────────────────────────────────
# Leave COMPARTMENT_ID empty to use the tenancy OCID from ~/.oci/config
# (GitHub Actions writes that config from repository secrets).
# NEVER commit real OCIDs/IPs/keys to this public repo.
COMPARTMENT_ID = ""
SSH_PUBLIC_KEY = "ssh-ed25519 AAAA... your-key-comment"  # your SSH public key (.pub file content)
INSTANCE_NAME = "free-micro"     # change to "free-micro-2" when claiming the second one
BOOT_VOLUME_SIZE_IN_GBS = 50
# NOTE: Micro is the PRIMARY front - easier to claim than ARM, and once won it
# can host the ARM retry bot itself. ARM fires slower (300s+) so both fronts
# stay under the per-user LaunchInstance rate limit (~1 call / 75-90s).
RETRY_INTERVAL = 90              # base seconds between attempts
JITTER_MAX = 30                  # random + jitter to avoid sync with other bots
TARGET_SHAPE = "VM.Standard.E2.1.Micro"
MAX_MICRO_INSTANCES = 2          # Always Free entitlement
WANTED_INGRESS_PORTS = [22, 80, 443, 8501]

# Reuse an EXISTING public subnet BY NAME (avoids creating extra VCNs; free tier
# is capped at 2 VCNs). Leave empty to always create the shared fallback VCN.
EXISTING_SUBNET_NAME = ""
# ────────────────────────────────────────────────────────

config = oci.config.from_file()
if not COMPARTMENT_ID:
    COMPARTMENT_ID = config["tenancy"]
compute = oci.core.ComputeClient(config)
network = oci.core.VirtualNetworkClient(config)
identity = oci.identity.IdentityClient(config)


def get_availability_domain():
    ads = identity.list_availability_domains(COMPARTMENT_ID).data
    return ads[0].name


def get_ubuntu_x86_image():
    images = compute.list_images(
        COMPARTMENT_ID,
        operating_system="Canonical Ubuntu",
        operating_system_version="22.04",
        shape=TARGET_SHAPE,
        sort_by="TIMECREATED",
        sort_order="DESC",
    ).data
    if not images:
        raise Exception("Ubuntu 22.04 x86 image not found")
    return images[0].id


def resolve_subnet_id():
    """Prefer an existing subnet (looked up by name); fall back to a shared VCN."""
    if EXISTING_SUBNET_NAME:
        subs = network.list_subnets(
            compartment_id=COMPARTMENT_ID, display_name=EXISTING_SUBNET_NAME
        ).data
        if subs:
            subnet = subs[0]
            print(f"Using existing subnet: {subnet.id}")
            return subnet.id
        print(f"Subnet '{EXISTING_SUBNET_NAME}' not found; creating fallback VCN/subnet.")
    return create_shared_vcn_and_subnet()


def create_shared_vcn_and_subnet():
    """Fallback path: reuses the SAME shared VCN as oci_retry.py (keeps VCN count low)."""
    vcns = network.list_vcns(COMPARTMENT_ID, display_name="retry-vcn-shared").data
    if vcns:
        vcn = vcns[0]
        print(f"Using existing shared VCN: {vcn.id}")
    else:
        vcn = network.create_vcn(
            oci.core.models.CreateVcnDetails(
                compartment_id=COMPARTMENT_ID,
                display_name="retry-vcn-shared",
                cidr_block="10.2.0.0/16",
            )
        ).data
        print(f"Created shared VCN: {vcn.id}")

        ig = network.create_internet_gateway(
            oci.core.models.CreateInternetGatewayDetails(
                compartment_id=COMPARTMENT_ID,
                vcn_id=vcn.id,
                display_name="retry-ig-shared",
                is_enabled=True,
            )
        ).data

        network.update_route_table(
            vcn.default_route_table_id,
            oci.core.models.UpdateRouteTableDetails(
                route_rules=[
                    oci.core.models.RouteRule(
                        destination="0.0.0.0/0",
                        network_entity_id=ig.id,
                    )
                ]
            ),
        )

    subnets = network.list_subnets(
        COMPARTMENT_ID, vcn_id=vcn.id, display_name="retry-subnet-shared"
    ).data
    if subnets:
        subnet = subnets[0]
        print(f"Using existing shared subnet: {subnet.id}")
    else:
        subnet = network.create_subnet(
            oci.core.models.CreateSubnetDetails(
                compartment_id=COMPARTMENT_ID,
                vcn_id=vcn.id,
                display_name="retry-subnet-shared",
                cidr_block="10.2.1.0/24",
                prohibit_public_ip_on_vnic=False,
            )
        ).data
        print(f"Created shared subnet: {subnet.id}")

    return subnet.id


def ensure_ingress_open(subnet_id):
    """Additively ensure WANTED_INGRESS_PORTS are open on the subnet's security lists."""
    subnet = network.get_subnet(subnet_id).data
    seclist_ids = subnet.security_list_ids or []
    if not seclist_ids:
        print("No security lists attached to subnet; skipping ingress setup.")
        return

    for sl_id in seclist_ids:
        sl = network.get_security_list(sl_id).data
        open_ports = set()
        for r in sl.ingress_security_rules or []:
            if r.protocol == "6" and r.tcp_options and r.tcp_options.destination_port_range:
                pr = r.tcp_options.destination_port_range
                open_ports.update(range(pr.min, pr.max + 1))

        missing = [p for p in WANTED_INGRESS_PORTS if p not in open_ports]
        if not missing:
            print(f"Security list {sl.display_name}: all wanted ports already open.")
            continue

        new_ingress = list(sl.ingress_security_rules or [])
        for port in missing:
            new_ingress.append(
                oci.core.models.IngressSecurityRule(
                    protocol="6",
                    source="0.0.0.0/0",
                    tcp_options=oci.core.models.TcpOptions(
                        destination_port_range=oci.core.models.PortRange(
                            min=port, max=port
                        )
                    ),
                )
            )
            print(f"  + opening port {port} on {sl.display_name}")

        network.update_security_list(
            sl_id,
            oci.core.models.UpdateSecurityListDetails(
                ingress_security_rules=new_ingress,
                egress_security_rules=sl.egress_security_rules,
            ),
        )


def used_micro_count():
    """Number of non-terminated Micro instances in the tenancy."""
    n = 0
    for inst in compute.list_instances(COMPARTMENT_ID).data:
        if inst.shape == TARGET_SHAPE and inst.lifecycle_state not in ("TERMINATED", "TERMINATING"):
            n += 1
    return n


def try_create_instance(subnet_id, ad_name, image_id):
    instance = compute.launch_instance(
        oci.core.models.LaunchInstanceDetails(
            compartment_id=COMPARTMENT_ID,
            display_name=INSTANCE_NAME,
            availability_domain=ad_name,
            shape=TARGET_SHAPE,
            source_details=oci.core.models.InstanceSourceViaImageDetails(
                image_id=image_id,
                boot_volume_size_in_gbs=BOOT_VOLUME_SIZE_IN_GBS,
            ),
            create_vnic_details=oci.core.models.CreateVnicDetails(
                subnet_id=subnet_id,
                assign_public_ip=True,
            ),
            metadata={"ssh_authorized_keys": SSH_PUBLIC_KEY},
        )
    ).data
    return instance


def main():
    # Pre-flight: entitlement is 2 Micro instances.
    already = used_micro_count()
    if already >= MAX_MICRO_INSTANCES:
        print(f"[done] Micro entitlement already used ({already}/{MAX_MICRO_INSTANCES}). Nothing to claim.")
        return

    print("Initializing network configuration...")
    subnet_id = resolve_subnet_id()
    ensure_ingress_open(subnet_id)

    print("Fetching availability domain...")
    ad_name = get_availability_domain()
    print(f"AD: {ad_name}")

    print("Fetching Ubuntu 22.04 x86 image...")
    image_id = get_ubuntu_x86_image()
    print(f"Image ID: {image_id}")

    attempt = 0
    throttle_streak = 0
    while True:
        attempt += 1
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now}] Attempt #{attempt} to create instance...")

        try:
            instance = try_create_instance(subnet_id, ad_name, image_id)
            throttle_streak = 0
            print(f"\n[SUCCESS] Instance created")
            print(f"   ID: {instance.id}")
            print(f"   State: {instance.lifecycle_state}")
            print(f"   Check Oracle Cloud Console for the public IP")
            break
        except oci.exceptions.ServiceError as e:
            status = getattr(e, "status", None)
            code = getattr(e, "code", "") or ""
            msg = (getattr(e, "message", "") or "").lower()

            # Rate-limit: back off progressively instead of hammering harder.
            if status == 429 or code == "TooManyRequests" or "too many requests" in msg:
                throttle_streak += 1
                backoff = min(60 * (2 ** throttle_streak), 900)
                print(f"[throttle] 429 rate-limited - backing off {backoff}s (streak {throttle_streak})")
                time.sleep(backoff + random.randint(0, JITTER_MAX))
                continue
            throttle_streak = 0

            if status in (401, 403, 404) or code in ("NotAuthenticated", "NotAuthorizedOrNotFound"):
                print(f"[FATAL] Auth/config error {status} {code}: {e.message}")
                raise SystemExit(2)

            if code in ("LimitExceeded", "QuotaExceeded") or "quota" in msg or "limit exceeded" in msg:
                held = used_micro_count()
                if held >= MAX_MICRO_INSTANCES:
                    print(f"[SUCCESS] Micro entitlement now filled ({held}/{MAX_MICRO_INSTANCES}) - likely claimed concurrently. Stopping.")
                    break
                print(f"[warn] Quota/limit response but entitlement not full ({held}/{MAX_MICRO_INSTANCES}); retrying.")
            elif "out of host capacity" in msg or "capacity" in msg:
                print("[retry] Out of capacity.")
            else:
                print(f"[retry] API error {status} {code}: {e.message}")
        except SystemExit:
            raise
        except Exception as e:
            print(f"[retry] Transient/network error ({type(e).__name__})")

        time.sleep(RETRY_INTERVAL + random.randint(0, JITTER_MAX))


if __name__ == "__main__":
    main()
