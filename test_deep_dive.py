"""
FortyGuard Deep-Dive Evaluation Suite (Round 2)
==============================================
1. Core Endpoints:
   - Heatmap 100m vs 60m (latency, credit deduction, return schema)
   - Heat Intelligence Report via MCP (report -> report_read)
   - Monitoring & Alerts exploration (Webhook vs polling vs notification channels)
2. Robustness & Validation Edge Cases:
   - Self-intersecting Polygon (bowtie)
   - Granularity = 0 and Granularity = -10
   - Empty/invalid string origin/destination in routing
   - Rate limiting stress test (8 rapid-fire env_params requests)
3. MCP Schema Static Audit Analysis
"""

import json
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
LOG_DIR = BASE_DIR / "test_logs" / "deep_dive"
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

def get_rest_headers():
    return {
        "Content-Type": "application/json",
        "api-key": API_KEY
    }

def get_mcp_headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }

def log_result(test_id, name, endpoint_type, status_code, latency_ms, req_payload, resp_payload, notes=""):
    entry = {
        "test_id": test_id,
        "name": name,
        "endpoint_type": endpoint_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
        "request_payload": req_payload,
        "response_payload": resp_payload,
        "notes": notes
    }
    filename = f"{test_id.lower()}.json"
    with open(LOG_DIR / filename, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)
    print(f"[{test_id}] {name} -> Status: {status_code} ({round(latency_ms, 2)} ms) | {notes}")
    return entry

def get_credit_balance():
    """Query current credits via MCP credit_balance tool"""
    payload = {
        "jsonrpc": "2.0",
        "id": 999,
        "method": "tools/call",
        "params": {"name": "credit_balance", "arguments": {}}
    }
    try:
        r = requests.post(MCP_ENDPOINT, headers=get_mcp_headers(), json=payload, timeout=15)
        # Parse SSE
        lines = r.text.strip().split("\n")
        for line in lines:
            if line.startswith("data: "):
                data = json.loads(line[6:])
                available = data.get("result", {}).get("structuredContent", {}).get("available_credits")
                if available is not None:
                    return available
    except Exception as e:
        print(f"Failed to fetch credit balance: {e}")
    return None

# =========================================================================
# PART 1: CORE ENDPOINTS DEEP DIVE
# =========================================================================

def run_heatmap_comparison():
    """Run Heatmap 100m vs 60m on Seattle AOI, poll to completion"""
    print("\n" + "="*50)
    print("1. HEATMAP COMPARISON (100m vs 60m)")
    print("="*50)

    aoi = {
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
    }
    date_time = {
        "start_date": "2024-07-15",
        "start_time": "14:00",
        "filter_type": 1
    }

    results = {}

    for gran in [100, 60]:
        print(f"\n---> Submitting Heatmap (Granularity: {gran}m)...")
        credits_before = get_credit_balance()
        payload = {
            "polygon_aoi": aoi,
            "date_time": date_time,
            "granularity": gran
        }

        t0 = time.perf_counter()
        resp = requests.post(f"{REST_BASE_URL}/heatmap", headers=get_rest_headers(), json=payload)
        submit_lat = (time.perf_counter() - t0) * 1000

        try:
            body = resp.json()
        except Exception:
            body = resp.text

        log_result(f"core_heatmap_{gran}m_submit", f"Heatmap {gran}m Submit", "REST", resp.status_code, submit_lat, payload, body)

        activity_id = None
        if isinstance(body, dict):
            activity_id = body.get("activity_id") or body.get("data", {}).get("activity_id")

        if not activity_id:
            print(f"[-] Could not capture activity_id for {gran}m. Response: {body}")
            continue

        print(f"[+] Activity ID: {activity_id}. Polling status (max 120s)...")
        status_url = f"{REST_BASE_URL}/status/{activity_id}"
        poll_count = 0
        poll_start = time.perf_counter()
        completed = False

        while poll_count < 24:
            poll_count += 1
            time.sleep(5)
            t_poll = time.perf_counter()
            r_poll = requests.get(status_url, headers=get_rest_headers())
            p_lat = (time.perf_counter() - t_poll) * 1000

            try:
                p_body = r_poll.json()
            except Exception:
                p_body = r_poll.text

            status_str = "Unknown"
            if isinstance(p_body, dict):
                status_str = p_body.get("data", {}).get("status") or p_body.get("message")

            print(f"    Poll #{poll_count} ({poll_count*5}s): status={status_str}")

            if status_str in ["Completed", "Failed", "Error"]:
                total_duration_s = time.perf_counter() - poll_start
                credits_after = get_credit_balance()
                deducted = (credits_before - credits_after) if (credits_before and credits_after) else "Unknown"

                summary_notes = f"Completed in {round(total_duration_s, 1)}s ({poll_count} polls). Credits deducted: {deducted}"
                log_result(f"core_heatmap_{gran}m_complete", f"Heatmap {gran}m Result", "REST", r_poll.status_code, total_duration_s*1000, {}, p_body, notes=summary_notes)
                results[gran] = {
                    "duration_s": round(total_duration_s, 2),
                    "poll_count": poll_count,
                    "credits_deducted": deducted,
                    "status": status_str,
                    "payload_size": len(r_poll.text)
                }
                completed = True
                break

        if not completed:
            print(f"[-] Heatmap {gran}m timed out after 120s.")

    return results

def run_heat_intelligence_report():
    """Test Heat Intelligence Report via MCP tool call, measure token footprint"""
    print("\n" + "="*50)
    print("2. HEAT INTELLIGENCE REPORT (MCP report -> report_read)")
    print("="*50)

    credits_before = get_credit_balance()
    report_args = {
        "latitude": 47.6062,
        "longitude": -122.3321,
        "temperature": 75.0,  # Prompt specifies Fahrenheit
        "date": "2024-07-15",
        "analysis": ["geographic", "environmental"]
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 201,
        "method": "tools/call",
        "params": {
            "name": "report",
            "arguments": report_args
        }
    }

    t0 = time.perf_counter()
    r = requests.post(MCP_ENDPOINT, headers=get_mcp_headers(), json=payload, timeout=30)
    lat = (time.perf_counter() - t0) * 1000

    raw_text = r.text
    log_result("core_report_submit", "Heat Intelligence Report Submit (MCP)", "MCP", r.status_code, lat, payload, raw_text, notes=f"Size: {len(raw_text)} bytes")

    # Extract analytics_id or activity_id from SSE
    activity_id = None
    for line in raw_text.split("\n"):
        if line.startswith("data: "):
            try:
                data = json.loads(line[6:])
                res_content = data.get("result", {}).get("content", [])
                if res_content and "text" in res_content[0]:
                    inner = json.loads(res_content[0]["text"])
                    activity_id = inner.get("activity_id") or inner.get("analytics_id") or inner.get("result", {}).get("activity_id")
            except Exception:
                pass

    if activity_id:
        print(f"[+] Captured Report activity_id: {activity_id}. Polling report_read...")
        poll_count = 0
        while poll_count < 15:
            poll_count += 1
            time.sleep(5)
            read_payload = {
                "jsonrpc": "2.0",
                "id": 202,
                "method": "tools/call",
                "params": {"name": "report_read", "arguments": {"analytics_id": activity_id}}
            }
            t_read = time.perf_counter()
            r_read = requests.post(MCP_ENDPOINT, headers=get_mcp_headers(), json=read_payload, timeout=30)
            read_lat = (time.perf_counter() - t_read) * 1000
            read_text = r_read.text

            print(f"    Report Poll #{poll_count} ({poll_count*5}s): len={len(read_text)}")
            if "completed" in read_text.lower():
                credits_after = get_credit_balance()
                cost = (credits_before - credits_after) if (credits_before and credits_after) else "Unknown"
                est_tokens = len(read_text) // 4
                log_result("core_report_complete", "Heat Intelligence Report Complete (MCP)", "MCP", r_read.status_code, read_lat, read_payload, read_text[:1000], notes=f"Finished. Size: {len(read_text)} bytes (~{est_tokens} tokens). Cost: {cost}")
                break
    else:
        print(f"[-] Could not parse report activity_id from: {raw_text[:300]}")

def run_monitoring_alerts_probe():
    """Probe Monitors and Alerts via MCP to verify webhook vs polling vs notification channels"""
    print("\n" + "="*50)
    print("3. MONITORS & ALERTS ENDPOINT PROBING")
    print("="*50)

    # list_monitors (free)
    payload_monitors = {
        "jsonrpc": "2.0",
        "id": 301,
        "method": "tools/call",
        "params": {"name": "monitoring", "arguments": {"operation": "list_monitors"}}
    }
    t0 = time.perf_counter()
    r_mon = requests.post(MCP_ENDPOINT, headers=get_mcp_headers(), json=payload_monitors, timeout=15)
    lat_mon = (time.perf_counter() - t0) * 1000
    log_result("core_monitoring_list_monitors", "List Monitors Operation", "MCP", r_mon.status_code, lat_mon, payload_monitors, r_mon.text)

    # list_alerts (free)
    payload_alerts = {
        "jsonrpc": "2.0",
        "id": 302,
        "method": "tools/call",
        "params": {"name": "monitoring", "arguments": {"operation": "list_alerts"}}
    }
    t0 = time.perf_counter()
    r_alt = requests.post(MCP_ENDPOINT, headers=get_mcp_headers(), json=payload_alerts, timeout=15)
    lat_alt = (time.perf_counter() - t0) * 1000
    log_result("core_monitoring_list_alerts", "List Alerts Operation", "MCP", r_alt.status_code, lat_alt, payload_alerts, r_alt.text)

# =========================================================================
# PART 2: VALIDATION LAYER & ROBUSTNESS STRESS TESTING (0 CREDITS)
# =========================================================================

def run_robustness_tests():
    print("\n" + "="*50)
    print("4. ROBUSTNESS & VALIDATION STRESS TESTING")
    print("="*50)

    date_time = {"start_date": "2024-07-15", "start_time": "14:00", "filter_type": 1}

    # 1. Self-intersecting polygon (Bowtie / Butterfly)
    bowtie_polygon = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-122.335, 47.608],
                    [-122.330, 47.612],
                    [-122.335, 47.612],
                    [-122.330, 47.608],
                    [-122.335, 47.608]
                ]]
            }
        }]
    }
    p_bowtie = {"polygon_aoi": bowtie_polygon, "date_time": date_time, "granularity": 100}
    t0 = time.perf_counter()
    r_bowtie = requests.post(f"{REST_BASE_URL}/heatmap", headers=get_rest_headers(), json=p_bowtie)
    lat_bowtie = (time.perf_counter() - t0) * 1000
    try:
        b_bowtie = r_bowtie.json()
    except Exception:
        b_bowtie = r_bowtie.text
    log_result("stress_bowtie_polygon", "Self-intersecting Polygon Validation", "REST", r_bowtie.status_code, lat_bowtie, p_bowtie, b_bowtie, notes="Expect 422/400 validation error; check for 500 crash")

    # 2. Granularity = 0 and Granularity = -10
    for g_val in [0, -10]:
        aoi_valid = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[-122.335, 47.608], [-122.330, 47.608], [-122.330, 47.612], [-122.335, 47.612], [-122.335, 47.608]]]
                }
            }]
        }
        p_gran = {"polygon_aoi": aoi_valid, "date_time": date_time, "granularity": g_val}
        t0 = time.perf_counter()
        r_gran = requests.post(f"{REST_BASE_URL}/heatmap", headers=get_rest_headers(), json=p_gran)
        lat_gran = (time.perf_counter() - t0) * 1000
        try:
            b_gran = r_gran.json()
        except Exception:
            b_gran = r_gran.text
        log_result(f"stress_granularity_{g_val}", f"Invalid Granularity ({g_val})", "REST", r_gran.status_code, lat_gran, p_gran, b_gran, notes=f"Expect 422 validation error on granularity={g_val}")

    # 3. Routing with empty/invalid strings
    p_route_empty = {
        "origin": {"lat": "", "lon": ""},
        "destination": {"lat": 47.6805, "lon": -122.3305},
        "departure_time": "2026-11-24T00:00:00Z"
    }
    t0 = time.perf_counter()
    r_route_empty = requests.post(f"{REST_BASE_URL}/routing", headers=get_rest_headers(), json=p_route_empty)
    lat_route_empty = (time.perf_counter() - t0) * 1000
    try:
        b_route_empty = r_route_empty.json()
    except Exception:
        b_route_empty = r_route_empty.text
    log_result("stress_routing_empty_origin", "Empty String Route Origin", "REST", r_route_empty.status_code, lat_route_empty, p_route_empty, b_route_empty, notes="Check for clean 422 vs 500 crash")

    # 4. Rate Limiting burst test: 8 rapid env_params queries
    print("\n---> Firing 8 rapid-fire env_params requests...")
    burst_results = []
    p_env = {"latitude": 47.6062, "longitude": -122.3321, "temperature": 20.0, "date_time": {"start_date": "2024-07-15", "filter_type": 1}}
    for i in range(1, 9):
        t_req = time.perf_counter()
        resp = requests.post(f"{REST_BASE_URL}/env_params", headers=get_rest_headers(), json=p_env)
        req_lat = (time.perf_counter() - t_req) * 1000
        headers_dict = dict(resp.headers)
        rate_headers = {k: v for k, v in headers_dict.items() if "rate" in k.lower() or "retry" in k.lower() or "limit" in k.lower()}
        burst_results.append({
            "request_num": i,
            "status_code": resp.status_code,
            "latency_ms": round(req_lat, 2),
            "rate_headers": rate_headers
        })
        print(f"    Burst #{i}: Status {resp.status_code} ({round(req_lat, 1)}ms) RateHeaders: {rate_headers}")
    
    log_result("stress_rate_limit_burst", "Rate Limiting Burst (8x env_params)", "REST", 200, sum(b['latency_ms'] for b in burst_results), p_env, burst_results, notes="Evaluated 429 threshold and rate headers")

# =========================================================================
# MASTER RUNNER
# =========================================================================

if __name__ == "__main__":
    print("=" * 65)
    print("STARTING FORTYGUARD DEEP DIVE TEST SUITE (ROUND 2)")
    print(f"Initial Credits: {get_credit_balance()}")
    print("=" * 65)

    # 1. Heatmap 100m vs 60m
    run_heatmap_comparison()

    # 2. Heat Intelligence Report
    run_heat_intelligence_report()

    # 3. Monitors & Alerts
    run_monitoring_alerts_probe()

    # 4. Robustness & Validation
    run_robustness_tests()

    print("\n" + "=" * 65)
    print(f"Final Credits: {get_credit_balance()}")
    print(f"Logs persisted to: {LOG_DIR.resolve()}")
    print("=" * 65)
