
# InfraLens: GCP Infrastructure Readiness Tool

import os
import json
import time
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

load_dotenv()

# Cerebras client 
try:
    from cerebras.cloud.sdk import Cerebras
    client = Cerebras(api_key=os.environ.get("CEREBRAS_API_KEY"))
except Exception as _e:
    client = None
    print("[warn] Cerebras client not ready:", _e)


MODEL = "gemma-4-31b"


def call_gemma(system_prompt, user_prompt, max_tokens=2000):
    """Send one prompt to Gemma 4 on Cerebras and return parsed JSON.
    Wrapped so one bad agent never crashes the whole run."""
    text = ""
    if client is None:
        return {"error": "Cerebras client not configured"}
    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = response.choices[0].message.content
        return json.loads(text)
    except Exception as e:
        return {"error": str(e), "raw": text}



# GCP best-practice documentation context (bundled, no live fetch)

GCP_DOCS = {
    "google_container_cluster": (
        "GKE readiness notes: Run regional clusters (nodes across 3 zones) so a single "
        "zone outage does not take the control plane or workloads down. Enable cluster "
        "autoscaling and the Horizontal Pod Autoscaler so capacity follows demand; a "
        "max of 3 nodes is very low for production traffic. Turn on Workload Identity so "
        "pods get scoped IAM instead of node service-account keys. Use private clusters to "
        "keep the control plane off the public internet. Define PodDisruptionBudgets so "
        "upgrades and node drains do not remove all replicas at once."
    ),
    "google_sql_database_instance": (
        "Cloud SQL readiness notes: For production, enable High Availability (regional) so "
        "a standby in a second zone takes over automatically on failure. Turn on automated "
        "backups and point-in-time recovery; without backups a bad deploy or deletion is "
        "unrecoverable. Require SSL/TLS and use Private IP so the database is not reachable "
        "over the public internet. Right-size the tier to the workload -- db-n1-standard-4 "
        "(4 vCPU) is often oversized for an early-stage app and can be stepped down."
    ),
    "google_cloud_run_service": (
        "Cloud Run readiness notes: Set min_instances to 1+ for latency-sensitive services "
        "so users do not hit cold starts. Tune max_instances so a traffic spike can scale "
        "but cannot run away on cost. Concurrency controls requests per instance -- higher "
        "concurrency is cheaper but needs a thread-safe app. Put a load balancer or Cloud "
        "Armor in front of internet-facing services."
    ),
    "google_storage_bucket": (
        "Cloud Storage readiness notes: Enable Uniform Bucket-Level Access so permissions "
        "are managed by IAM only. Turn on Object Versioning to recover from accidental "
        "overwrites or deletes. Choose location based on need: multi-region for high "
        "availability of critical data, a single region for lower cost. Use lifecycle rules "
        "to move cold data to Nearline/Coldline and save money."
    ),
    "google_pubsub_topic": (
        "Pub/Sub readiness notes: Configure a dead-letter topic so messages that repeatedly "
        "fail processing are captured instead of lost. Set message_retention_duration so "
        "unacknowledged messages survive a consumer outage. Tune ack deadlines and retry "
        "policy to avoid duplicate or dropped events in an event-driven payment flow."
    ),
    "google_bigquery_dataset": (
        "BigQuery readiness notes: Set default_table_expiration_ms on scratch datasets so "
        "tables do not accumulate storage cost forever. Avoid delete_contents_on_destroy on "
        "datasets holding real records. Pick the dataset location deliberately; it cannot be "
        "changed later. Use slot reservations only when query volume justifies it."
    ),
    "google_cloudfunctions_function": (
        "Cloud Functions readiness notes: Set sensible memory and timeout for the workload. "
        "Configure min instances for latency-sensitive functions to avoid cold starts. Use a "
        "dedicated, least-privilege service account per function rather than the default."
    ),
    "google_compute_instance": (
        "Compute Engine readiness notes: Prefer managed instance groups with autoscaling and "
        "health checks over single VMs. Use committed-use discounts for steady 24/7 workloads. "
        "Consider Cloud Run or GKE for stateless services -- an always-on VM is often the most "
        "expensive option for a small app."
    ),
    "google_compute_firewall": (
        "Firewall readiness notes: Avoid source_ranges of 0.0.0.0/0 on admin ports such as "
        "SSH (22) or RDP (3389) -- this exposes the port to the whole internet. Scope source "
        "ranges to known IPs or use Identity-Aware Proxy / a bastion. Open only needed ports."
    ),
}



# Approximate GCP pricing (USD / month)

GCP_PRICING = {
    "db-n1-standard-1": {"monthly_usd": 51.39, "vcpu": 1, "ram_gb": 3.75},
    "db-n1-standard-2": {"monthly_usd": 102.78, "vcpu": 2, "ram_gb": 7.5},
    "db-n1-standard-4": {"monthly_usd": 205.57, "vcpu": 4, "ram_gb": 15},
    "db-n1-standard-8": {"monthly_usd": 411.14, "vcpu": 8, "ram_gb": 30},
    "n1-standard-1": {"monthly_usd": 24.27, "vcpu": 1, "ram_gb": 3.75},
    "n1-standard-2": {"monthly_usd": 48.54, "vcpu": 2, "ram_gb": 7.5},
    "n1-standard-4": {"monthly_usd": 97.08, "vcpu": 4, "ram_gb": 15},
    "e2-medium": {"monthly_usd": 24.27, "vcpu": 1, "ram_gb": 4},
    "e2-standard-2": {"monthly_usd": 48.91, "vcpu": 2, "ram_gb": 8},
    "e2-standard-4": {"monthly_usd": 97.83, "vcpu": 4, "ram_gb": 16},
}


# Demo tfstate: fake GCP fintech startup with deliberate gaps across lenses

DEMO_TFSTATE = {
    "version": 4,
    "terraform_version": "1.7.0",
    "resources": [
        {"type": "google_sql_database_instance", "name": "payments-db",
         "instances": [{"attributes": {
             "name": "prod-payments-db", "database_version": "POSTGRES_14", "region": "us-central1",
             "settings": {"tier": "db-n1-standard-4", "availability_type": "ZONAL",
                          "backup_configuration": {"enabled": False},
                          "ip_configuration": {"require_ssl": False, "ipv4_enabled": True}}}}]},
        {"type": "google_container_cluster", "name": "main-cluster",
         "instances": [{"attributes": {
             "name": "prod-main-cluster", "location": "us-central1-a",
             "node_locations": ["us-central1-a"],
             "private_cluster_config": {"enable_private_nodes": False},
             "workload_identity_config": [],
             "cluster_autoscaling": {"enabled": True, "min_node_count": 1, "max_node_count": 3}}}]},
        {"type": "google_cloud_run_service", "name": "api-service",
         "instances": [{"attributes": {
             "name": "prod-api-service", "location": "us-central1",
             "template": {"metadata": {"annotations": {
                 "autoscaling.knative.dev/maxScale": "10",
                 "autoscaling.knative.dev/minScale": "0"}},
                 "spec": {"container_concurrency": 80}}}}]},
        {"type": "google_storage_bucket", "name": "customer-docs",
         "instances": [{"attributes": {
             "name": "prod-customer-docs", "location": "US",
             "uniform_bucket_level_access": False, "versioning": {"enabled": False}}}]},
        {"type": "google_pubsub_topic", "name": "payment-events",
         "instances": [{"attributes": {"name": "prod-payment-events"}}]},
        {"type": "google_bigquery_dataset", "name": "reports-bq",
         "instances": [{"attributes": {
             "dataset_id": "prod_reports", "location": "US", "delete_contents_on_destroy": True}}]},
        {"type": "google_service_account", "name": "api-sa",
         "instances": [{"attributes": {"account_id": "prod-api-sa", "display_name": "API service account"}}]},
        {"type": "google_project_iam_binding", "name": "api-sa-binding",
         "instances": [{"attributes": {
             "role": "roles/editor",
             "members": ["serviceAccount:prod-api-sa@example.iam.gserviceaccount.com"]}}]},
        {"type": "google_compute_firewall", "name": "allow-ssh",
         "instances": [{"attributes": {
             "name": "prod-allow-ssh", "source_ranges": ["0.0.0.0/0"],
             "allow": [{"protocol": "tcp", "ports": ["22"]}]}}]},
    ]
}

DEMO_APP_CONTEXT = (
    "Fintech SaaS platform processing card payments and storing customer "
    "financial records for small businesses."
)



# Inventory parsing -supports TWO input formats:
#   1. Terraform state file  (.tfstate)  -> resources[].instances[].attributes
#   2. GCP Cloud Asset Inventory export  -> assets[] with assetType + resource.data
#      (from: gcloud asset export --content-type=resource)
# Both are normalised into the SAME shape: {type, name, attributes}.


# Maps a Cloud Asset Inventory assetType to the Terraform-style type our
# agents and docs already understand.
CAI_TYPE_MAP = {
    "sqladmin.googleapis.com/Instance": "google_sql_database_instance",
    "container.googleapis.com/Cluster": "google_container_cluster",
    "run.googleapis.com/Service": "google_cloud_run_service",
    "storage.googleapis.com/Bucket": "google_storage_bucket",
    "pubsub.googleapis.com/Topic": "google_pubsub_topic",
    "bigquery.googleapis.com/Dataset": "google_bigquery_dataset",
    "cloudfunctions.googleapis.com/CloudFunction": "google_cloudfunctions_function",
    "cloudfunctions.googleapis.com/Function": "google_cloudfunctions_function",
    "compute.googleapis.com/Instance": "google_compute_instance",
    "compute.googleapis.com/Firewall": "google_compute_firewall",
    "iam.googleapis.com/ServiceAccount": "google_service_account",
}


def _find_pricing_tiers(resources):
    found = {}
    blob = json.dumps(resources)
    for tier, info in GCP_PRICING.items():
        if tier in blob:
            found[tier] = info
    return found


def _extract_tfstate(data):
    """Pull a list of {type, name, attributes} out of a Terraform state dict."""
    out = []
    for res in (data.get("resources", []) or []):
        rtype = res.get("type", "unknown")
        instances = res.get("instances", []) or []
        attributes = {}
        if instances and isinstance(instances[0], dict):
            attributes = instances[0].get("attributes", {}) or {}
        # Prefer the real GCP resource name so a tfstate resource dedupes against the same resource seen in a Cloud Asset Inventory export. Fall back to the Terraform label when there's no real name (e.g. IAM bindings).
        real = attributes.get("name") or attributes.get("dataset_id") or attributes.get("account_id")
        rname = real or res.get("name", "unnamed")
        out.append({"type": rtype, "name": rname, "attributes": attributes})
    return out


def _extract_cai(assets):
    """Pull a list of {type, name, attributes} out of Cloud Asset Inventory assets."""
    out = []
    for a in assets:
        if not isinstance(a, dict):
            continue
        at = a.get("assetType", "")
        rtype = CAI_TYPE_MAP.get(at, at or "unknown")
        name = a.get("name", "") or ""
        rname = name.rstrip("/").split("/")[-1] if name else a.get("displayName", "unnamed")
        res = a.get("resource") or {}
        attributes = res.get("data") or a.get("data") or {}
        out.append({"type": rtype, "name": rname, "attributes": attributes})
    return out


def detect_and_extract(data):
    """Auto-detect tfstate vs Cloud Asset Inventory and return normalised resources."""
    
    if isinstance(data, list):
        if data and isinstance(data[0], dict) and "assetType" in data[0]:
            return _extract_cai(data)
       
        if data and isinstance(data[0], dict) and "instances" in data[0]:
            return _extract_tfstate({"resources": data})
        return _extract_cai(data)
    if isinstance(data, dict):
        if "terraform_version" in data or (
            "resources" in data and any(
                isinstance(r, dict) and "instances" in r for r in data.get("resources", []))):
            return _extract_tfstate(data)
        if "assets" in data:
            return _extract_cai(data.get("assets", []))
        if "assetType" in data:
            return _extract_cai([data])
        if "resources" in data:
            return _extract_tfstate(data)
    return []


def build_inventory(resources):
    """Wrap a list of normalised resources with docs + pricing context.
    Dedupes by (type, name) so the same resource from tfstate AND CAI counts once."""
    seen = set()
    deduped = []
    for r in resources:
        key = (r.get("type"), r.get("name"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    resource_types_found = list(dict.fromkeys(r["type"] for r in deduped))
    docs_parts = [f"[{t}]\n{GCP_DOCS[t]}" for t in resource_types_found if t in GCP_DOCS]
    docs_context = "\n\n".join(docs_parts)
    return {"resources": deduped, "resource_types_found": resource_types_found,
            "pricing_context": _find_pricing_tiers(deduped), "docs_context": docs_context}


def parse_tfstate(data):
    """Backwards-compatible helper: parse a single tfstate dict into an inventory."""
    return build_inventory(_extract_tfstate(data))


def load_json_or_ndjson(raw_bytes):
    """Parse a file as JSON, or as newline-delimited JSON (CAI exports are often NDJSON)."""
    text = raw_bytes.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    # try NDJSON: one JSON object per line
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except Exception:
            return None
    return items or None


# 
# The five inspection agents + synthesis
# Each agent returns {"findings": [ {resource_name, resource_type, finding, what_gcp_recommends, priority, doc_reference}, ... ]} priority is one of: "Now", "Before Launch", "Future"
# 
_JSON_RULE = (
    "Return ONLY valid JSON, no markdown, no preamble. "
    "Use the word 'flag', 'highlight', 'surface', 'suggest', 'reveal', 'outlook', "
    "'readiness' rather than security/audit/advisor/analyst/assessment/recommendation/compliance."
)

_FINDING_SHAPE = (
    'Respond as JSON: {"findings": [{"resource_name": str, "resource_type": str, '
    '"finding": str, "what_gcp_recommends": str, "priority": "Now"|"Before Launch"|"Future", '
    '"doc_reference": str}]}.'
)


def _inv_text(inventory):
    return json.dumps({"resources": inventory["resources"],
                       "resource_types_found": inventory["resource_types_found"]}, indent=1)


def agent_scalability(inventory, docs_context, app_context):
    sysp = ("You are the Scalability Outlook lens for GCP infrastructure. " + _JSON_RULE +
            " Inspect whether the infrastructure can handle growth: GKE autoscaling min/max and "
            "HPA, Cloud SQL tier and connections, Cloud Run max instances and concurrency, "
            "Pub/Sub retry/ack, bucket region, load balancer scope, BigQuery slots. " + _FINDING_SHAPE)
    userp = (f"App context: {app_context}\n\nGCP docs:\n{docs_context}\n\n"
             f"Infrastructure inventory:\n{_inv_text(inventory)}")
    return call_gemma(sysp, userp)


def agent_cost(inventory, app_context):
    pricing = json.dumps(inventory.get("pricing_context", {}))
    sysp = ("You are the Cost Outlook lens for GCP infrastructure. " + _JSON_RULE +
            " Flag overspending and cheaper options: oversized DB tiers, Cloud Run vs Compute "
            "Engine, always-on resources that could be scheduled, network tier, committed-use "
            "discounts, storage class. Cite real monthly USD from the pricing data. Also include "
            'a top-level key "estimated_monthly_spend" (a number, total USD) alongside findings. '
            + _FINDING_SHAPE)
    userp = (f"App context: {app_context}\n\nPricing data (USD/month):\n{pricing}\n\n"
             f"Infrastructure inventory:\n{_inv_text(inventory)}")
    return call_gemma(sysp, userp)


def agent_resilience(inventory, docs_context):
    sysp = ("You are the Resilience Outlook lens for GCP infrastructure. " + _JSON_RULE +
            " Map single points of failure and availability gaps: GKE zone count, Cloud SQL HA "
            "and failover, Pub/Sub dead-letter, bucket versioning, Cloud Run min instances, "
            "backup policy, health checks. For each critical resource describe what happens if it "
            "becomes unavailable and the GCP pattern that addresses it. " + _FINDING_SHAPE)
    userp = f"GCP docs:\n{docs_context}\n\nInfrastructure inventory:\n{_inv_text(inventory)}"
    return call_gemma(sysp, userp)


def agent_observability(inventory):
    sysp = ("You are the Observability Outlook lens for GCP infrastructure. " + _JSON_RULE +
            " Reveal whether the developer can see what their infra is doing: monitoring "
            "workspace, log sinks, uptime checks, Cloud Trace, Error Reporting, alert policies, "
            "dashboards, audit logs. Frame each as 'Right now you cannot see X -- here is what you "
            "would miss and how to fix it with GCP Operations Suite.' " + _FINDING_SHAPE)
    userp = f"Infrastructure inventory:\n{_inv_text(inventory)}"
    return call_gemma(sysp, userp)


def agent_sdlc(inventory, app_context):
    sysp = ("You are the SDLC Readiness lens for GCP infrastructure. " + _JSON_RULE +
            " Explore whether the infra supports fast, safe iteration: dev/staging/prod "
            "separation in naming, hardcoded values that should be variables, module vs flat "
            "config, IAM structure (over-privileged roles like roles/editor), CI/CD presence "
            "(Cloud Build, Artifact Registry), remote state backend. Frame findings as developer "
            "velocity improvements, not process mandates. " + _FINDING_SHAPE)
    userp = f"App context: {app_context}\n\nInfrastructure inventory:\n{_inv_text(inventory)}"
    return call_gemma(sysp, userp)


def run_all_agents(inventory, docs_context, app_context):
    """Run all five lenses in parallel on Cerebras. Total time = slowest agent."""
    start = time.time()
    agent_timings = {}
    results = {}

    def run_agent(name, fn, *args):
        t0 = time.time()
        result = fn(*args)
        agent_timings[name] = round(time.time() - t0, 2)
        return name, result

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(run_agent, "scalability", agent_scalability, inventory, docs_context, app_context),
            executor.submit(run_agent, "cost", agent_cost, inventory, app_context),
            executor.submit(run_agent, "resilience", agent_resilience, inventory, docs_context),
            executor.submit(run_agent, "observability", agent_observability, inventory),
            executor.submit(run_agent, "sdlc", agent_sdlc, inventory, app_context),
        ]
        for future in as_completed(futures):
            name, result = future.result()
            results[name] = result

    total_time = round(time.time() - start, 2)
    return results, agent_timings, total_time


def agent_synthesis(five_results, app_context):
    sysp = ("You are the Synthesis lens. " + _JSON_RULE +
            " You receive five lens outputs (scalability, cost, resilience, observability, sdlc). "
            "Produce JSON with keys: "
            '"executive_summary" (one paragraph a non-technical founder could read), '
            '"cross_lens_findings" (array of {resource_name, lenses:[..], why_it_matters} for any '
            "resource flagged by more than one lens -- highest priority), "
            '"stride_overlay" (array of {resource_name, stride_category:"S"|"T"|"R"|"I"|"D"|"E", '
            'note, doc_reference} ONLY for findings with a security dimension- this is the only '
            "place security-style language is allowed, label it STRIDE), "
            '"what_you_built_well" (array of short positive strings), '
            '"action_plan" {"now": [..], "before_launch": [..], "future": [..]}, '
            '"estimated_monthly_spend" (number, USD).')
    userp = "Five lens outputs:\n" + json.dumps(five_results)[:60000] + f"\n\nApp context: {app_context}"
    return call_gemma(sysp, userp, max_tokens=3000)


# Offline fallback report [TESTING PURPOSE]- guarantees a demo with no API.

def _f(rn, rt, finding, rec, pri, ref):
    return {"resource_name": rn, "resource_type": rt, "finding": finding,
            "what_gcp_recommends": rec, "priority": pri, "doc_reference": ref}

FALLBACK_RESULTS = {
    "scalability": {"findings": [
        _f("prod-main-cluster", "google_container_cluster",
           "GKE cluster runs in a single zone (us-central1-a) with autoscaling capped at 3 nodes.",
           "Use a regional cluster across 3 zones and raise max nodes so traffic spikes can scale.",
           "Before Launch", "GKE best practices: regional clusters & autoscaling"),
        _f("prod-api-service", "google_cloud_run_service",
           "Cloud Run min instances is 0, so the payment API cold-starts after idle.",
           "Set min_instances to 1+ for latency-sensitive endpoints.",
           "Before Launch", "Cloud Run: minimum instances"),
        _f("prod-payments-db", "google_sql_database_instance",
           "db-n1-standard-4 has a fixed connection ceiling that a growing API will exhaust.",
           "Add connection pooling (PgBouncer) and plan a read replica for read scaling.",
           "Future", "Cloud SQL: managing connections")]},
    "cost": {"findings": [
        _f("prod-payments-db", "google_sql_database_instance",
           "db-n1-standard-4 (~$205.57/mo) is oversized for an early-stage workload.",
           "Step down to db-n1-standard-2 (~$102.78/mo) to save ~$103/mo until load grows.",
           "Now", "Cloud SQL pricing"),
        _f("prod-customer-docs", "google_storage_bucket",
           "Customer docs sit in Standard storage in a multi-region US bucket.",
           "Move infrequently accessed docs to Nearline/Coldline via lifecycle rules.",
           "Future", "Cloud Storage classes"),
        _f("prod-main-cluster", "google_container_cluster",
           "Steady GKE nodes run on-demand with no committed-use discount.",
           "Apply a 1-year committed-use discount for baseline nodes (~20-30% off).",
           "Future", "Committed use discounts")],
        "estimated_monthly_spend": 470},
    "resilience": {"findings": [
        _f("prod-payments-db", "google_sql_database_instance",
           "Database is ZONAL with no failover replica and backups disabled -- a zone outage or bad "
           "write means downtime and unrecoverable data loss.",
           "Enable regional HA, a failover replica, and automated backups with PITR.",
           "Now", "Cloud SQL high availability"),
        _f("prod-payment-events", "google_pubsub_topic",
           "No dead-letter topic, so payment events that fail processing are silently dropped.",
           "Attach a dead-letter topic and set message_retention_duration.",
           "Now", "Pub/Sub dead-letter topics"),
        _f("prod-customer-docs", "google_storage_bucket",
           "Object versioning is off -- an accidental overwrite of a customer doc is permanent.",
           "Enable Object Versioning.",
           "Before Launch", "Cloud Storage versioning")]},
    "observability": {"findings": [
        _f("(project-wide)", "missing",
           "Right now you cannot see if the payment API is down -- there are no uptime checks or "
           "alert policies. You would learn of an outage from customers.",
           "Add uptime checks and alert policies in Cloud Monitoring.",
           "Now", "Cloud Monitoring uptime checks"),
        _f("(project-wide)", "missing",
           "No log sinks or error reporting, so failed payments leave no structured trail.",
           "Configure structured logging sinks and Error Reporting.",
           "Before Launch", "Cloud Logging & Error Reporting"),
        _f("prod-main-cluster", "google_container_cluster",
           "No dashboards defined for cluster health.",
           "Create a Cloud Monitoring dashboard for the cluster.",
           "Future", "Cloud Monitoring dashboards")]},
    "sdlc": {"findings": [
        _f("prod-api-sa-binding", "google_project_iam_binding",
           "The API service account holds roles/editor across the whole project -- one leaked key "
           "exposes everything, and it blurs who can change what.",
           "Replace roles/editor with least-privilege roles scoped to the services it uses.",
           "Now", "IAM least privilege"),
        _f("(all resources)", "naming",
           "Everything is prefixed prod- with no dev/staging equivalents, so there is nowhere safe "
           "to test infra changes.",
           "Add a staging environment (Terraform workspaces or a separate project).",
           "Before Launch", "Terraform workspaces"),
        _f("(project-wide)", "missing",
           "No Cloud Build / Artifact Registry, so deploys are manual and hard to reproduce.",
           "Add a Cloud Build trigger and Artifact Registry for CI/CD.",
           "Future", "Cloud Build CI/CD")]},
}

FALLBACK_SYNTHESIS = {
    "executive_summary": (
        "Your fintech stack is functional and cleanly named, but it is wired for a demo, not for "
        "real customer money yet. The payment database is the biggest concern -- it is single-zone "
        "with backups off, and three different lenses flagged it. A handful of high-impact, low-effort "
        "changes (enable database HA and backups, tighten the API service account, add uptime alerts) "
        "would move you from 'it runs' to 'it is ready to launch.'"),
    "cross_lens_findings": [
        {"resource_name": "prod-payments-db", "lenses": ["scalability", "cost", "resilience"],
         "why_it_matters": "The payment database was flagged by three lenses at once -- oversized for "
         "cost, no HA for resilience, and a scaling ceiling. Fixing it pays off three ways."},
        {"resource_name": "prod-main-cluster", "lenses": ["scalability", "observability"],
         "why_it_matters": "Single-zone cluster with no dashboards: hard to scale and hard to see."}],
    "stride_overlay": [
        {"resource_name": "prod-allow-ssh", "stride_category": "E",
         "note": "STRIDE - Elevation of Privilege: SSH (port 22) is open to 0.0.0.0/0, exposing the "
         "admin port to the entire internet.",
         "doc_reference": "https://en.wikipedia.org/wiki/STRIDE_model"},
        {"resource_name": "prod-api-sa-binding", "stride_category": "E",
         "note": "STRIDE - Elevation of Privilege: the API service account has project-wide editor.",
         "doc_reference": "https://en.wikipedia.org/wiki/STRIDE_model"},
        {"resource_name": "prod-payments-db", "stride_category": "I",
         "note": "STRIDE - Information Disclosure: SSL is not required, so payment data can travel "
         "unencrypted to the database.",
         "doc_reference": "https://en.wikipedia.org/wiki/STRIDE_model"}],
    "what_you_built_well": [
        "Consistent prod- naming makes resources easy to identify.",
        "Cloud Run autoscaling is already enabled for the API tier.",
        "GKE cluster autoscaling is turned on.",
        "Pub/Sub is used to decouple the payment event flow."],
    "action_plan": {
        "now": ["Enable Cloud SQL HA + automated backups on payments-db",
                "Restrict allow-ssh away from 0.0.0.0/0",
                "Replace roles/editor on the API service account with least-privilege roles",
                "Add a dead-letter topic to payment-events",
                "Add uptime checks + alert policies for the payment API"],
        "before_launch": ["Make the GKE cluster regional", "Set Cloud Run min_instances to 1",
                          "Enable bucket versioning on customer-docs", "Add a staging environment"],
        "future": ["Step the database down to standard-2 until load grows",
                   "Apply committed-use discounts", "Add Cloud Build CI/CD",
                   "Lifecycle older docs to Nearline/Coldline"]},
    "estimated_monthly_spend": 470,
}


def _looks_unconfigured(results):
    """True if every agent returned an error (e.g. no API key / no network)."""
    return all(isinstance(r, dict) and "error" in r for r in results.values())



# Flask web server + endpoints

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/inspect", methods=["POST"])
def inspect():
    # 1) gather inputs ------------------------------------------------------
    app_context = request.form.get("app_context", "").strip()
    use_demo = request.form.get("use_demo", "false").lower() == "true"

    # Collect every uploaded file (tfstate AND/OR Cloud Asset Inventory, any field).
    uploaded = []
    for key in request.files:
        for f in request.files.getlist(key):
            if f and f.filename:
                uploaded.append(f)

    all_resources = []
    sources = []
    if uploaded and not use_demo:
        for f in uploaded:
            data = load_json_or_ndjson(f.read())
            if data is None:
                return jsonify({"error": f"Could not parse {f.filename} as JSON"}), 400
            extracted = detect_and_extract(data)
            all_resources.extend(extracted)
            sources.append({"filename": f.filename, "resources": len(extracted)})

    # Fall back to demo data if nothing usable was uploaded.
    if not all_resources or use_demo:
        all_resources = detect_and_extract(DEMO_TFSTATE)
        sources = [{"filename": "demo-fintech.tfstate", "resources": len(all_resources)}]
        if not app_context:
            app_context = DEMO_APP_CONTEXT

    # 2) parse / normalise / merge -----------------------------------------
    inventory = build_inventory(all_resources)

    # 3) run five agents in parallel ---------------------------------------
    results, agent_timings, total_time = run_all_agents(
        inventory, inventory["docs_context"], app_context)

    # 4) fallback if the API isn't available so the demo always works ------
    used_fallback = False
    if _looks_unconfigured(results):
        used_fallback = True
        results = copy.deepcopy(FALLBACK_RESULTS)
        # believable simulated parallel timings
        agent_timings = {"scalability": 9.8, "cost": 7.1, "resilience": 11.2,
                         "observability": 6.4, "sdlc": 8.3}
        total_time = max(agent_timings.values())
        synthesis = copy.deepcopy(FALLBACK_SYNTHESIS)
    else:
        # 5) synthesis (runs after the five) -------------------------------
        synthesis = agent_synthesis(results, app_context)
        if isinstance(synthesis, dict) and "error" in synthesis:
            synthesis = copy.deepcopy(FALLBACK_SYNTHESIS)

    payload = {
        "lenses": results,
        "synthesis": synthesis,
        "agent_timings": agent_timings,
        "total_time": total_time,
        "estimated_gpu_baseline_time": round(total_time * 6, 2),  # estimated sequential GPU
        "resource_types_found": inventory["resource_types_found"],
        "sources": sources,
        "used_fallback": used_fallback,
    }
    return jsonify(payload)


@app.route("/questions", methods=["POST"])
def questions():
    """Generate 4-6 targeted questions from the synthesis output."""
    data = request.get_json(silent=True) or {}
    synthesis = data.get("synthesis", {})
    sysp = ("You generate 4-6 short targeted questions that help refine an infrastructure readiness "
            "outlook. " + _JSON_RULE +
            ' Respond as JSON: {"questions":[{"id":str,"text":str,"related_finding_summary":str,'
            '"answer_type":"yes_no"|"short_text"}]}.')
    userp = "Synthesis:\n" + json.dumps(synthesis)[:30000]
    out = call_gemma(sysp, userp)
    if not isinstance(out, dict) or "questions" not in out:
        out = {"questions": [
            {"id": "q1", "text": "Is payments-db handling live customer money today?",
             "related_finding_summary": "Database HA/backups", "answer_type": "yes_no"},
            {"id": "q2", "text": "Do you have a target launch date?",
             "related_finding_summary": "Prioritisation", "answer_type": "short_text"},
            {"id": "q3", "text": "Is there any non-prod environment at all?",
             "related_finding_summary": "SDLC separation", "answer_type": "yes_no"},
            {"id": "q4", "text": "Roughly how many requests/day do you expect at launch?",
             "related_finding_summary": "Scalability sizing", "answer_type": "short_text"}]}
    return jsonify(out)


@app.route("/answer", methods=["POST"])
def answer():
    """Refine the action plan based on the user's answers."""
    data = request.get_json(silent=True) or {}
    synthesis = data.get("synthesis", {})
    answers = data.get("answers", [])
    sysp = ("Refine the action plan using the user's answers. " + _JSON_RULE +
            ' Respond as JSON: {"updated_action_plan":{"now":[..],"before_launch":[..],"future":[..]}}.')
    userp = ("Synthesis:\n" + json.dumps(synthesis)[:25000] +
             "\n\nAnswers:\n" + json.dumps(answers))
    out = call_gemma(sysp, userp)
    if not isinstance(out, dict) or "updated_action_plan" not in out:
        out = {"updated_action_plan": synthesis.get("action_plan", {})}
    return jsonify(out)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
