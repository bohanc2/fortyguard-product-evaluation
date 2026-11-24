# FortyGuard Product Evaluation (Senior SWE Perspective)

## Context
This is a product evaluation task for the FortyGuard Software Development Internship. From a Senior Software Engineer's perspective, the goal is to systematically test the **Temperature API** and **Temperature MCP**, combine those findings with the manual observations recorded in `dashboard_findings.md`, and produce an interview-ready technical report (`FINAL_REPORT.md`) covering test results, DX/UX analysis, and architectural recommendations.

## Reference URLs
- API Docs: https://docs-api.fortyguard.com/docs/introduction
- MCP Docs: https://docs-api.fortyguard.com/docs/mcp-overview
- MCP Endpoint: https://tos-mcp.app.fortyguard.com/mcp

## Environment & Constraints
- Load the API key from `FORTYGUARD_API_KEY` in `.env`.
- The products currently support US locations only. Use Seattle, WA and Phoenix, AZ as primary test locations.
- Preserve Free tier credits: query `Check API Credits Usage` before and after running tests, and avoid infinite polling loops or duplicate high-cost requests.

## Test Matrix
Write and execute an automated Python test script to run all cases below, logging full request/response payloads, HTTP status codes, and end-to-end latency into `test_logs/`.

### Part A: Temperature API (REST)
Header: `api-key: $FORTYGUARD_API_KEY`
1. **Auth & Quota Baseline**:
   - Call `Check API Credits Usage` (GET) to record the initial credit balance.
   - Test invalid API keys and missing headers to evaluate 401/403 error clarity.
2. **Sync Endpoint (`Environmental Parameters`)**:
   - Happy path: Query Phoenix `(33.4484, -112.074)` and Seattle `(47.6062, -122.3321)`.
   - Evaluate JSON schema cleanliness, field naming consistency, and explicit unit definitions.
3. **Async Lifecycle (`Create Heatmap` & `Temperature-Aware Routing`)**:
   - Submit a small GeoJSON Polygon in Seattle to `Create Heatmap`, capture `activity_id`, poll `Check Status` until completion, and record total latency and poll count.
   - Submit a short-distance route (`558 NE 100th St, Seattle` to `East Green Lake Way N, Seattle`), measure API-level latency, and cross-reference against the severe latency observed in the Dashboard.
   - Verify credit deduction post-completion against documentation claims.
4. **Edge Cases & Error Handling**:
   - Non-US coordinates (e.g., Taipei `25.0330, 121.5654`).
   - Oversized GeoJSON Polygon or route exceeding the 124-mile limit.
   - Call a `PREMIUM`-only endpoint (e.g., `Satellite View Segmentation`) using the Free API key to check status codes and upgrade/error messaging.
   - Malformed GeoJSON payload.

### Part B: Temperature MCP
Header: `Authorization: Bearer $FORTYGUARD_API_KEY`
1. **Tool Discovery**:
   - Connect to `https://tos-mcp.app.fortyguard.com/mcp` and dump all exposed tools, including their JSON schemas and descriptions.
   - Evaluate whether tool descriptions provide sufficient guidance for LLMs to handle two-step async workflows (`heatmap` -> `heatmap_read`, `temperature_routing` -> `temperature_routing_read`) without leaking raw activity IDs to users or triggering duplicate calls.
2. **Payload & Context Efficiency**:
   - Execute `env_params` and at least one async tool pair via MCP. Measure response payload size and estimated token footprint to assess context window efficiency and hallucination risk.
3. **Cross-Product Consistency**:
   - Document DX friction across surfaces, such as the authentication header mismatch between REST API (`api-key`) and MCP (`Authorization: Bearer`).

## Deliverable (`FINAL_REPORT.md`)
Generate a clear, structured, engineering-focused report in English containing:
1. **Executive Summary**: Key product strengths and overall platform maturity assessment.
2. **Test Execution Summary**: Markdown table summarizing all tested endpoints/tools (Status Code, Latency, Credits Used, Doc Alignment).
3. **Prioritized Findings (P0 / P1 / P2)**: Consolidate API/MCP findings with `dashboard_findings.md`. Each item must include: Symptom, Repro Steps, Suspected Root Cause, and Concrete Engineering/UX Fix.
4. **Future Roadmap & Integration Ideas**: Actionable proposals to unify the Dashboard, API, and MCP developer experience.
