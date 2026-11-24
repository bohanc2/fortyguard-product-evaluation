"""
FortyGuard API and MCP Evaluation Test Suite
===========================================
Systematically test FortyGuard REST API (Part A) and Model Context Protocol (Part B).
Saves detailed logs, request/response payloads, HTTP status codes, and latency to test_logs/.
"""

import os
import json
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
LOG_DIR = BASE_DIR / "test_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

def load_env():
    env_vars = {}
    if ENV_PATH.exists():
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip()
    return env_vars

ENV = load_env()
API_KEY = ENV.get("FORTYGUARD_API_KEY", "")

REST_BASE_URL = "https://api.fortyguard.com/v1"
MCP_ENDPOINT = "https://tos-mcp.app.fortyguard.com/mcp"

# Shared state across tests
execution_results = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "test_cases": [],
    "credits_usage": {},
    "shared_activity_ids": {}
}

def log_test_result(test_id, category, name, method, url, req_headers, req_body, resp_status, resp_headers, resp_body, latency_ms, notes=""):
    # Sanitize API key in logged headers
    sanitized_req_headers = dict(req_headers) if req_headers else {}
    if "api-key" in sanitized_req_headers:
        sanitized_req_headers["api-key"] = sanitized_req_headers["api-key"][:6] + "..."
    if "Authorization" in sanitized_req_headers:
        sanitized_req_headers["Authorization"] = "Bearer " + sanitized_req_headers["Authorization"].split()[-1][:6] + "..."

    entry = {
        "test_id": test_id,
        "category": category,
        "name": name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method": method,
        "url": url,
        "request_headers": sanitized_req_headers,
        "request_body": req_body,
        "response_status": resp_status,
        "latency_ms": round(latency_ms, 2),
        "response_body": resp_body,
        "notes": notes
    }
    execution_results["test_cases"].append(entry)
    
    file_name = f"{test_id.lower().replace(' ', '_')}.json"
    with open(LOG_DIR / file_name, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)
        
    print(f"[{test_id}] {name} -> Status: {resp_status} ({round(latency_ms, 2)} ms)")
    return entry

# ==========================================
# PART A: Temperature API (REST)
# ==========================================

def get_rest_headers(api_key=None):
    key = api_key if api_key is not None else API_KEY
    headers = {"Content-Type": "application/json"}
    if key:
        headers["api-key"] = key
    return headers

def parse_remaining_credits(body):
    """Attempt to extract remaining credit count from various possible schema structures"""
    if not isinstance(body, dict):
        return None
    # Check common direct fields
    for k in ["remaining_credits", "remaining", "balance", "credits_remaining", "available_credits"]:
        if k in body and isinstance(body[k], (int, float)):
            return body[k]
    # Check data/result nested object
    nested = body.get("data") or body.get("result") or body.get("usage")
    if isinstance(nested, dict):
        for k in ["remaining_credits", "remaining", "balance", "credits_remaining", "available_credits"]:
            if k in nested and isinstance(nested[k], (int, float)):
                return nested[k]
        if "total_credits" in nested and "used_credits" in nested:
            return nested["total_credits"] - nested["used_credits"]
    if "total_credits" in body and "used_credits" in body:
        return body["total_credits"] - body["used_credits"]
    return None

def check_credits(label="initial"):
    """Check API Credits Usage baseline"""
    url = f"{REST_BASE_URL}/system/fetch-api-key-usage"
    headers = get_rest_headers()
    
    t0 = time.perf_counter()
    resp = requests.get(url, headers=headers)
    lat = (time.perf_counter() - t0) * 1000
    
    if resp.status_code == 405:
        t0 = time.perf_counter()
        resp = requests.post(url, headers=headers, json={})
        lat = (time.perf_counter() - t0) * 1000

    try:
        body = resp.json()
    except Exception:
        body = resp.text

    rem = parse_remaining_credits(body)
    notes = f"Credit check ({label}). Remaining parsed: {rem}"
    log_test_result(
        test_id=f"A1_Credits_{label.capitalize()}",
        category="Auth & Quota",
        name=f"Check API Credits Usage ({label})",
        method=resp.request.method,
        url=url,
        req_headers=headers,
        req_body={},
        resp_status=resp.status_code,
        resp_headers=dict(resp.headers),
        resp_body=body,
        latency_ms=lat,
        notes=notes
    )
    execution_results["credits_usage"][label] = {"raw": body, "remaining_parsed": rem}
    return rem, body

def test_auth_baseline():
    """Test invalid API key and missing headers"""
    url = f"{REST_BASE_URL}/env_params"
    sample_payload = {"latitude": 47.6062, "longitude": -122.3321}

    # Case 1: Invalid API Key
    headers_invalid = {"Content-Type": "application/json", "api-key": "invalid_fortyguard_key_xyz123"}
    t0 = time.perf_counter()
    resp_invalid = requests.post(url, headers=headers_invalid, json=sample_payload)
    lat_invalid = (time.perf_counter() - t0) * 1000
    try:
        b_invalid = resp_invalid.json()
    except Exception:
        b_invalid = resp_invalid.text
    log_test_result("A1_Auth_InvalidKey", "Auth & Quota", "Invalid API Key Test", "POST", url, headers_invalid, sample_payload, resp_invalid.status_code, dict(resp_invalid.headers), b_invalid, lat_invalid)

    # Case 2: Missing API Key Header
    headers_missing = {"Content-Type": "application/json"}
    t0 = time.perf_counter()
    resp_missing = requests.post(url, headers=headers_missing, json=sample_payload)
    lat_missing = (time.perf_counter() - t0) * 1000
    try:
        b_missing = resp_missing.json()
    except Exception:
        b_missing = resp_missing.text
    log_test_result("A1_Auth_MissingHeader", "Auth & Quota", "Missing Header Test", "POST", url, headers_missing, sample_payload, resp_missing.status_code, dict(resp_missing.headers), b_missing, lat_missing)

def test_env_params_sync(skip_phoenix=False):
    """Test sync Environmental Parameters endpoint for Phoenix and Seattle"""
    url = f"{REST_BASE_URL}/env_params"
    headers = get_rest_headers()

    if skip_phoenix:
        print("[*] Credit protection active: Skipping Phoenix point query to conserve credits.")
        log_test_result("A2_Sync_Phoenix", "Sync Endpoint", "Environmental Parameters (Phoenix) [SKIPPED]", "POST", url, headers, {}, 0, {}, {"status": "skipped", "reason": "credits < 15,000 threshold"}, 0.0, notes="Skipped for credit conservation")
    else:
        phx_payload = {"latitude": 33.4484, "longitude": -112.074}
        t0 = time.perf_counter()
        resp_phx = requests.post(url, headers=headers, json=phx_payload)
        lat_phx = (time.perf_counter() - t0) * 1000
        try:
            b_phx = resp_phx.json()
        except Exception:
            b_phx = resp_phx.text
        log_test_result("A2_Sync_Phoenix", "Sync Endpoint", "Environmental Parameters (Phoenix)", "POST", url, headers, phx_payload, resp_phx.status_code, dict(resp_phx.headers), b_phx, lat_phx)

    # Seattle (common anchor)
    sea_payload = {"latitude": 47.6062, "longitude": -122.3321}
    t0 = time.perf_counter()
    resp_sea = requests.post(url, headers=headers, json=sea_payload)
    lat_sea = (time.perf_counter() - t0) * 1000
    try:
        b_sea = resp_sea.json()
    except Exception:
        b_sea = resp_sea.text
    log_test_result("A2_Sync_Seattle", "Sync Endpoint", "Environmental Parameters (Seattle)", "POST", url, headers, sea_payload, resp_sea.status_code, dict(resp_sea.headers), b_sea, lat_sea)

def test_async_heatmap():
    """Submit a small GeoJSON polygon in Seattle to Create Heatmap, poll Check Status up to 120s"""
    url = f"{REST_BASE_URL}/heatmap"
    headers = get_rest_headers()

    small_polygon_payload = {
        "polygon_aoi": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [-122.335, 47.608],
                            [-122.330, 47.608],
                            [-122.330, 47.612],
                            [-122.335, 47.612],
                            [-122.335, 47.608]
                        ]]
                    }
                }
            ]
        },
        "granularity": 100
    }

    t0 = time.perf_counter()
    resp = requests.post(url, headers=headers, json=small_polygon_payload)
    lat = (time.perf_counter() - t0) * 1000
    try:
        data = resp.json()
    except Exception:
        data = resp.text

    entry = log_test_result("A3_Heatmap_Submit", "Async Lifecycle", "Create Heatmap (Seattle)", "POST", url, headers, small_polygon_payload, resp.status_code, dict(resp.headers), data, lat)

    activity_id = None
    if isinstance(data, dict):
        activity_id = data.get("activity_id") or data.get("id") or (data.get("data", {}).get("activity_id") if isinstance(data.get("data"), dict) else None)

    if not activity_id:
        print(f"[-] No activity_id returned from Heatmap submission (status {resp.status_code}). Skipping polling.")
        return None

    execution_results["shared_activity_ids"]["heatmap"] = activity_id
    print(f"[+] Captured Heatmap activity_id: {activity_id}")

    # Polling status: Max 24 polls, 5s interval (120s total)
    status_url = f"{REST_BASE_URL}/status/{activity_id}"
    print(f"[*] Polling Heatmap status for activity_id={activity_id} (max 120s)...")
    poll_count = 0
    max_polls = 24
    poll_start = time.perf_counter()
    final_status = "Unknown"

    while poll_count < max_polls:
        poll_count += 1
        time.sleep(5)
        t_poll = time.perf_counter()
        resp_poll = requests.get(status_url, headers=headers)
        poll_lat = (time.perf_counter() - t_poll) * 1000
        try:
            poll_data = resp_poll.json()
        except Exception:
            poll_data = resp_poll.text

        final_status = poll_data.get("status") if isinstance(poll_data, dict) else str(resp_poll.status_code)
        print(f"    Heatmap Poll #{poll_count} ({poll_count*5}s): status={final_status} ({round(poll_lat, 1)}ms)")

        if final_status in ["Completed", "Failed", "Error"] or resp_poll.status_code != 200:
            total_lat = (time.perf_counter() - poll_start) * 1000
            log_test_result("A3_Heatmap_Status_Complete", "Async Lifecycle", f"Heatmap Status ({final_status})", "GET", status_url, headers, {}, resp_poll.status_code, dict(resp_poll.headers), poll_data, total_lat, notes=f"Finished after {poll_count} polls ({round(total_lat/1000, 1)}s).")
            break
    else:
        total_lat = (time.perf_counter() - poll_start) * 1000
        log_test_result("A3_Heatmap_Status_Timeout", "Async Lifecycle", "Heatmap Polling Timeout", "GET", status_url, headers, {}, 200, {}, {"status": "Timeout", "polls": poll_count}, total_lat, notes=f"Exceeded 120s timeout limit ({poll_count} polls)")

    return activity_id

def test_async_routing():
    """Submit short route in Seattle (558 NE 100th St -> East Green Lake Way N), poll up to 120s"""
    url = f"{REST_BASE_URL}/routing"
    headers = get_rest_headers()

    routing_payload = {
        "origin": {"lat": 47.7013, "lon": -122.3218},
        "destination": {"lat": 47.6805, "lon": -122.3305},
        "departure_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    }

    t0 = time.perf_counter()
    resp = requests.post(url, headers=headers, json=routing_payload)
    lat = (time.perf_counter() - t0) * 1000
    try:
        data = resp.json()
    except Exception:
        data = resp.text

    log_test_result("A3_Routing_Submit", "Async Lifecycle", "Temperature-Aware Routing (Seattle)", "POST", url, headers, routing_payload, resp.status_code, dict(resp.headers), data, lat)

    activity_id = None
    if isinstance(data, dict):
        activity_id = data.get("activity_id") or data.get("id") or (data.get("data", {}).get("activity_id") if isinstance(data.get("data"), dict) else None)

    if not activity_id:
        print(f"[-] No activity_id returned for Routing (status: {resp.status_code}). Plan restriction or synchronous validation response.")
        return None

    execution_results["shared_activity_ids"]["routing"] = activity_id
    status_url = f"{REST_BASE_URL}/status/{activity_id}"
    print(f"[*] Polling Routing status for activity_id={activity_id} (max 120s)...")
    poll_count = 0
    max_polls = 24
    poll_start = time.perf_counter()

    while poll_count < max_polls:
        poll_count += 1
        time.sleep(5)
        t_poll = time.perf_counter()
        resp_poll = requests.get(status_url, headers=headers)
        poll_lat = (time.perf_counter() - t_poll) * 1000
        try:
            poll_data = resp_poll.json()
        except Exception:
            poll_data = resp_poll.text

        final_status = poll_data.get("status") if isinstance(poll_data, dict) else str(resp_poll.status_code)
        print(f"    Routing Poll #{poll_count} ({poll_count*5}s): status={final_status} ({round(poll_lat, 1)}ms)")

        if final_status in ["Completed", "Failed", "Error"] or resp_poll.status_code != 200:
            total_lat = (time.perf_counter() - poll_start) * 1000
            log_test_result("A3_Routing_Status_Complete", "Async Lifecycle", f"Routing Status ({final_status})", "GET", status_url, headers, {}, resp_poll.status_code, dict(resp_poll.headers), poll_data, total_lat, notes=f"Finished after {poll_count} polls ({round(total_lat/1000, 1)}s).")
            break
    else:
        total_lat = (time.perf_counter() - poll_start) * 1000
        log_test_result("A3_Routing_Status_Timeout", "Async Lifecycle", "Routing Polling Timeout", "GET", status_url, headers, {}, 200, {}, {"status": "Timeout", "polls": poll_count}, total_lat, notes=f"Exceeded 120s limit ({poll_count} polls)")

    return activity_id

def test_edge_cases():
    """Test Non-US coords, oversized route/polygon, Premium-only endpoint, malformed GeoJSON"""
    headers = get_rest_headers()

    # 1. Non-US Coordinates (Taipei 25.0330, 121.5654)
    url_env = f"{REST_BASE_URL}/env_params"
    taipei_payload = {"latitude": 25.0330, "longitude": 121.5654}
    t0 = time.perf_counter()
    resp_taipei = requests.post(url_env, headers=headers, json=taipei_payload)
    lat_taipei = (time.perf_counter() - t0) * 1000
    try:
        b_taipei = resp_taipei.json()
    except Exception:
        b_taipei = resp_taipei.text
    log_test_result("A4_Edge_NonUS", "Edge Cases", "Non-US Coordinates (Taipei)", "POST", url_env, headers, taipei_payload, resp_taipei.status_code, dict(resp_taipei.headers), b_taipei, lat_taipei)

    # 2. Oversized Route Exceeding 124-mile (200km) Limit (Seattle to SF, ~800 miles)
    url_routing = f"{REST_BASE_URL}/routing"
    oversized_payload = {
        "origin": {"lat": 47.6062, "lon": -122.3321},
        "destination": {"lat": 37.7749, "lon": -122.4194},
        "departure_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    t0 = time.perf_counter()
    resp_over = requests.post(url_routing, headers=headers, json=oversized_payload)
    lat_over = (time.perf_counter() - t0) * 1000
    try:
        b_over = resp_over.json()
    except Exception:
        b_over = resp_over.text
    log_test_result("A4_Edge_OversizedRoute", "Edge Cases", "Oversized Route (>124mi)", "POST", url_routing, headers, oversized_payload, resp_over.status_code, dict(resp_over.headers), b_over, lat_over)

    # 3. Call PREMIUM-only endpoint (Satellite View Segmentation) with Free key
    url_sat = f"{REST_BASE_URL}/satellite"
    sat_payload = {"latitude": 33.4484, "longitude": -112.074}
    t0 = time.perf_counter()
    resp_sat = requests.post(url_sat, headers=headers, json=sat_payload)
    lat_sat = (time.perf_counter() - t0) * 1000
    try:
        b_sat = resp_sat.json()
    except Exception:
        b_sat = resp_sat.text
    log_test_result("A4_Edge_PremiumOnly", "Edge Cases", "Premium Endpoint (Satellite Segmentation)", "POST", url_sat, headers, sat_payload, resp_sat.status_code, dict(resp_sat.headers), b_sat, lat_sat)

    # 4. Malformed GeoJSON Payload to Heatmap
    url_heat = f"{REST_BASE_URL}/heatmap"
    malformed_payload = {
        "polygon_aoi": {
            "type": "InvalidCollection",
            "features": [{"geometry": {"type": "BrokenPolygon", "coordinates": [[12, 34]]}}]
        }
    }
    t0 = time.perf_counter()
    resp_mal = requests.post(url_heat, headers=headers, json=malformed_payload)
    lat_mal = (time.perf_counter() - t0) * 1000
    try:
        b_mal = resp_mal.json()
    except Exception:
        b_mal = resp_mal.text
    log_test_result("A4_Edge_MalformedGeoJSON", "Edge Cases", "Malformed GeoJSON Payload", "POST", url_heat, headers, malformed_payload, resp_mal.status_code, dict(resp_mal.headers), b_mal, lat_mal)


# ==========================================
# PART B: Temperature MCP
# ==========================================

def get_mcp_headers(auth_type="bearer", custom_key=None):
    key = custom_key if custom_key is not None else API_KEY
    headers = {"Content-Type": "application/json"}
    if auth_type == "bearer" and key:
        headers["Authorization"] = f"Bearer {key}"
    elif auth_type == "api-key" and key:
        headers["api-key"] = key
    return headers

def test_mcp_tools_discovery():
    """Discover MCP tools via JSON-RPC initialize and tools/list"""
    headers = get_mcp_headers("bearer")

    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "Senior-SWE-Evaluator", "version": "1.0.0"}
        }
    }
    t0 = time.perf_counter()
    resp_init = requests.post(MCP_ENDPOINT, headers=headers, json=init_payload)
    lat_init = (time.perf_counter() - t0) * 1000
    try:
        b_init = resp_init.json()
    except Exception:
        b_init = resp_init.text
    log_test_result("B1_MCP_Initialize", "MCP Tool Discovery", "MCP Initialize Handshake", "POST", MCP_ENDPOINT, headers, init_payload, resp_init.status_code, dict(resp_init.headers), b_init, lat_init)

    tools_payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }
    t0 = time.perf_counter()
    resp_tools = requests.post(MCP_ENDPOINT, headers=headers, json=tools_payload)
    lat_tools = (time.perf_counter() - t0) * 1000
    try:
        b_tools = resp_tools.json()
    except Exception:
        b_tools = resp_tools.text
    log_test_result("B1_MCP_ToolsList", "MCP Tool Discovery", "MCP Tools Discovery (tools/list)", "POST", MCP_ENDPOINT, headers, tools_payload, resp_tools.status_code, dict(resp_tools.headers), b_tools, lat_tools)

    with open(LOG_DIR / "mcp_tools_catalog.json", "w", encoding="utf-8") as f:
        json.dump(b_tools, f, indent=2, ensure_ascii=False)
        
    return b_tools

def test_mcp_payload_efficiency(heatmap_activity_id=None):
    """Execute env_params and real heatmap_read via MCP, measuring byte and token size"""
    headers = get_mcp_headers("bearer")

    # 1. MCP env_params (Seattle)
    env_call_payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "env_params",
            "arguments": {"latitude": 47.6062, "longitude": -122.3321}
        }
    }
    t0 = time.perf_counter()
    resp_env = requests.post(MCP_ENDPOINT, headers=headers, json=env_call_payload)
    lat_env = (time.perf_counter() - t0) * 1000
    try:
        b_env = resp_env.json()
    except Exception:
        b_env = resp_env.text

    raw_bytes_env = len(resp_env.content)
    est_tokens_env = len(resp_env.text) // 4
    notes_env = f"Payload size: {raw_bytes_env} bytes (~{est_tokens_env} tokens)"
    log_test_result("B2_MCP_Call_EnvParams", "MCP Payload Efficiency", "MCP tools/call (env_params)", "POST", MCP_ENDPOINT, headers, env_call_payload, resp_env.status_code, dict(resp_env.headers), b_env, lat_env, notes=notes_env)

    # 2. MCP heatmap_read with real activity_id from A3_Heatmap_Submit
    target_id = heatmap_activity_id or "test-activity-id-0000"
    is_real_id = bool(heatmap_activity_id)
    read_call_payload = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "heatmap_read",
            "arguments": {"activity_id": target_id}
        }
    }
    t0 = time.perf_counter()
    resp_read = requests.post(MCP_ENDPOINT, headers=headers, json=read_call_payload)
    lat_read = (time.perf_counter() - t0) * 1000
    try:
        b_read = resp_read.json()
    except Exception:
        b_read = resp_read.text

    read_bytes = len(resp_read.content)
    read_tokens = len(resp_read.text) // 4
    notes_read = f"Using {'REAL activity_id (' + str(target_id) + ')' if is_real_id else 'fallback ID'}. Payload: {read_bytes} bytes (~{read_tokens} tokens)"
    log_test_result("B2_MCP_Call_AsyncRead", "MCP Payload Efficiency", "MCP tools/call (heatmap_read real ID)", "POST", MCP_ENDPOINT, headers, read_call_payload, resp_read.status_code, dict(resp_read.headers), b_read, lat_read, notes=notes_read)

def test_mcp_auth_cross_product():
    """Test header mismatch: Attempting REST header (api-key) against MCP endpoint"""
    headers_rest_style = get_mcp_headers("api-key")
    payload = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/list",
        "params": {}
    }
    t0 = time.perf_counter()
    resp = requests.post(MCP_ENDPOINT, headers=headers_rest_style, json=payload)
    lat = (time.perf_counter() - t0) * 1000
    try:
        body = resp.json()
    except Exception:
        body = resp.text

    log_test_result("B3_MCP_Auth_Mismatch", "Cross-Product Consistency", "MCP with REST 'api-key' Header", "POST", MCP_ENDPOINT, headers_rest_style, payload, resp.status_code, dict(resp.headers), body, lat, notes="Verify failure when using REST api-key header on MCP endpoint")

# ==========================================
# MASTER RUNNER
# ==========================================

def run_all_tests():
    print("=" * 65)
    print("STARTING FORTYGUARD EVALUATION TEST SUITE (SENIOR SWE)")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 65)

    # Step 1: Quota baseline initial & threshold check
    print("\n[Step 1] Checking Initial Credits...")
    rem_credits, _ = check_credits("initial")
    
    skip_phoenix = False
    if rem_credits is not None:
        print(f"[!] Initial Remaining Credits: {rem_credits}")
        if rem_credits < 15000:
            print(f"[!] WARNING: Remaining credits ({rem_credits}) < 15,000 threshold. Enabling credit protection: skipping Phoenix.")
            skip_phoenix = True
    else:
        print("[?] Could not parse numerical remaining credits; will proceed normally with Seattle baseline.")

    # Step 2: Auth baseline
    print("\n[Step 2] Testing Auth Baseline (Invalid Key & Missing Header)...")
    test_auth_baseline()

    # Step 3: Sync Endpoint
    print("\n[Step 3] Testing Sync Environmental Parameters...")
    test_env_params_sync(skip_phoenix=skip_phoenix)

    # Step 4: Async Lifecycle (Heatmap & Routing)
    print("\n[Step 4] Testing Async Lifecycle (Create Heatmap & Routing)...")
    heatmap_activity_id = test_async_heatmap()
    test_async_routing()

    # Step 5: Edge cases
    print("\n[Step 5] Testing Edge Cases & Error Handling...")
    test_edge_cases()

    # Step 6: MCP Tool Discovery
    print("\n[Step 6] Testing MCP Tool Discovery...")
    test_mcp_tools_discovery()

    # Step 7: MCP Efficiency & Async real activity_id read
    print("\n[Step 7] Testing MCP Payload & Context Efficiency (Real Heatmap ID)...")
    test_mcp_payload_efficiency(heatmap_activity_id=heatmap_activity_id)

    # Step 8: MCP Auth Mismatch
    print("\n[Step 8] Testing MCP Cross-Product Auth Mismatch...")
    test_mcp_auth_cross_product()

    # Step 9: Quota baseline final
    print("\n[Step 9] Checking Final Credits...")
    check_credits("final")

    execution_results["completed_at"] = datetime.now(timezone.utc).isoformat()
    with open(LOG_DIR / "execution_summary.json", "w", encoding="utf-8") as f:
        json.dump(execution_results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 65)
    print(f"TEST RUN COMPLETE! Total cases recorded: {len(execution_results['test_cases'])}")
    print(f"Logs persisted to: {LOG_DIR.resolve()}")
    print("=" * 65)

if __name__ == "__main__":
    run_all_tests()
