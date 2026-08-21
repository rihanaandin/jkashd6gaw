import oci
config = oci.config.from_file()
tenancy = config["tenancy"]
network = oci.core.VirtualNetworkClient(config)
vcns = network.list_vcns(compartment_id=tenancy).data
for vcn in vcns:
    subnets = network.list_subnets(compartment_id=tenancy, vcn_id=vcn.id).data
    print(f"VCN {vcn.display_name} ({vcn.cidr_block})")
    print(f"  default_route_table: {vcn.default_route_table_id}")
    print(f"  default_security_list: {vcn.default_security_list_id}")
    for s in subnets:
        print(f"  Subnet: {s.display_name} | {s.cidr_block} | public={not s.prohibit_public_ip_on_vnic} | seclists={s.security_list_ids}")
    for sl in network.list_security_lists(compartment_id=tenancy, vcn_id=vcn.id).data:
        print(f"\n  SecurityList: {sl.display_name} ({sl.id})")
        print("    INGRESS:")
        for r in sl.ingress_security_rules or []:
            ports = ""
            if r.tcp_options and r.tcp_options.destination_port_range:
                pr = r.tcp_options.destination_port_range
                ports = f" port {pr.min}-{pr.max}"
            print(f"      proto={r.protocol} src={r.source}{ports}")
        print("    EGRESS:")
        for r in sl.egress_security_rules or []:
            print(f"      proto={r.protocol} dest={r.destination}")
    rt = network.get_route_table(vcn.default_route_table_id).data
    print(f"\n  RouteTable: {rt.display_name}")
    for rr in rt.route_rules or []:
        print(f"      dest={rr.destination} -> {rr.network_entity_id}")
