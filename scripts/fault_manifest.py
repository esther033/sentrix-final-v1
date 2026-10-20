"""Chaos manifest rendering and the filter targets recorded in fault-record.json.

Edge NetworkChaos templates (SETUP-REVIEW 7.15, method A) keep the pod-IP
target and add the destination Service ClusterIP as an externalTarget: the
app dials Service names, and kube-proxy (iptables) DNATs ClusterIP -> pod IP
in the host netns, after the source pod's egress tc filter. The ClusterIP is
looked up right before injection, never stored in a profile.
"""
import re

import yaml

CLUSTER_IP_KEY = "TARGET_SERVICE_CLUSTER_IP"
PLACEHOLDER = re.compile(r"{{\s*([A-Z0-9_]+)\s*}}")


def render(template, fault, name, duration_seconds, cluster_ip_of=None):
    """-> (manifest text, substitutions). cluster_ip_of(service) is only called
    when the template asks for the destination ClusterIP."""
    edge = fault.get("target_kind") == "dependency_edge"
    if edge and not (fault.get("source_service") and fault.get("destination_service")):
        raise ValueError("dependency_edge fault requires source_service and destination_service")
    substitutions = {
        "NAME": name,
        "SOURCE_SERVICE": fault["source_service"] if edge else fault["root_cause_service"],
        "TARGET_SERVICE": fault["destination_service"] if edge else fault["root_cause_service"],
        "DURATION": f"{duration_seconds}s",
        **fault.get("params", {}),
    }
    if "{{" + CLUSTER_IP_KEY + "}}" in template:
        if cluster_ip_of is None:
            raise ValueError("template needs the destination ClusterIP but no lookup was given")
        ip = cluster_ip_of(substitutions["TARGET_SERVICE"])
        if not ip or not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip):
            raise ValueError(f"destination Service {substitutions['TARGET_SERVICE']} has no ClusterIP ({ip!r})")
        substitutions[CLUSTER_IP_KEY] = ip
    for key, value in substitutions.items():
        template = template.replace("{{" + key + "}}", str(value))
    left = PLACEHOLDER.findall(template)
    if left:
        raise ValueError("unsubstituted placeholders: " + ", ".join(sorted(set(left))))
    return template, substitutions


def filter_targets(manifest):
    """What the injector filters on, read back from the rendered manifest."""
    doc = yaml.safe_load(manifest)
    spec = doc["spec"]
    if doc["kind"] != "NetworkChaos":
        return None
    labels = lambda sel: (sel or {}).get("selector", {}).get("labelSelectors") or {}
    return {
        "direction": spec.get("direction"),
        "injected_selector": spec.get("selector", {}).get("labelSelectors") or {},
        "target_selector": labels(spec.get("target")),
        "external_targets": list(spec.get("externalTargets") or []),
    }


def observed_targets(container_records, source_pods, destination_pods):
    """Pods Chaos Mesh actually selected (selectorKey '.' = injected, '.Target'
    = filter target) joined with the pod objects, plus a consistency verdict
    against the manifest's intent (injected pods are source pods, the target
    pod IPs are the destination's)."""
    def pick(key, pods):
        names = {r["id"].split("/", 1)[-1] for r in container_records if r.get("selectorKey", ".") == key}
        return [{"name": p["metadata"]["name"], "uid": p["metadata"]["uid"], "ip": p.get("status", {}).get("podIP")}
                for p in pods if p["metadata"]["name"] in names]
    injected, target = pick(".", source_pods), pick(".Target", destination_pods)
    n_injected = sum(1 for r in container_records if r.get("selectorKey", ".") == ".")
    n_target = sum(1 for r in container_records if r.get("selectorKey") == ".Target")
    return {"injected_source_pods": injected, "target_destination_pods": target,
            "destination_pod_ips": sorted(p.get("status", {}).get("podIP") for p in destination_pods
                                          if p.get("status", {}).get("podIP")),
            "selection_consistent": bool(injected) and len(injected) == n_injected
                                    and len(target) == n_target}
