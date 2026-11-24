# Temperature Dashboard Real-World Test Findings

Manual testing observations from `https://dashboard.fortyguard.com/map`. Integrate these findings into `FINAL_REPORT.md` and cross-reference them with API/MCP test results.

## Highlights
- Custom heatmaps support Polygon, Circle, and GeoJSON uploads with selectable spatial granularity (60m / 80m / 100m).
- Clicking map coordinates seamlessly triggers Satellite View and Street View Segmentation, providing high value for urban cooling and property assessment.
- Selesious AI Agent uses structured slot-filling UI cards (`Leave now` / `Depart at`) for routing parameters and gracefully separates valid domain questions from profane/frustrated user phrasing.

## P0 - Critical Usability & Performance Issues
1. **Severe Routing Latency**: A short ~2.76-mile Seattle route (`558 NE 100th St` -> `East Green Lake Way N`) stalled at 35% and 80% for an extended duration, making the `Leave now` real-time routing use case practically unusable. Likely caused by on-the-fly LTM inference along route waypoints instead of pre-computed road-network thermal weights, compounded by blocking full-panel loading states rather than progressive rendering.
2. **Broken Bottom Sheet on Narrow Desktop Viewports (RWD Bug)**: When a desktop browser window triggers the tablet/mobile responsive breakpoint, the post-calculation route results drawer cannot be dragged up via mouse or clicked to expand (likely bound exclusively to touch events), cutting off route metrics completely.

## P1 - Architecture, State Sync & Agent Bugs
1. **Async Job State Desynchronization**: Routing tasks initiated via either the `Route` drawer or Selesious Chatbot never appear in `Task Progress`. Furthermore, after Selesious outputs the complete route metrics in chat, a stale `*Route is still being generated.*` status label remains visible at the bottom of the same message.
2. **Selesious Agent Context Pollution**: While the underlying routing tool accurately computed the 8-mile Northgate-to-Seattle route, the final LLM synthesis step was polluted by an earlier `from taipei to seattle` turn in conversation history, falsely claiming it could not route across the ocean and fell back to a local route.
3. **Weak Local NLU & Low Debug Transparency**: Fails to resolve common local aliases (e.g., `uvillage`), loses conversational context upon geocoding failure (returning a Heatmap error during a routing flow), and `Show details` only renders static tool descriptions rather than actual input coordinates and raw tool outputs.
4. **Rigid Off-Topic Guardrails**: Prompts combining a valid product question with an off-topic query (e.g., LeetCode Two Sum) are blocked entirely by an upstream classifier instead of answering the valid portion.

## P2 - UX, Information Architecture & Copywriting
1. **Missing Thermal Color Legend**: The main heatmap view lacks a persistent temperature scale bar, preventing users from interpreting absolute temperatures or thermal deltas at a glance.
2. **Core Workflow Gaps**: `Walking` mode in `Route` is still marked `Coming soon` (despite pedestrians being the primary beneficiaries of heat-aware routing); `Search` pans to an address without displaying point environmental data or quick actions (`Set as origin` / `Create heatmap`), and leaves a dimming overlay blocking the map until manually closed.
3. **Redundant Entry Points & UI Occlusion**: The floating blue `G` button duplicates `Selesious AI Agent` inside `More`, persists on top of open menus, and overlaps/occludes the `Size Estimate` readout in the custom heatmap creation drawer.
4. **Copywriting & Mental Model Mismatches**:
   - Route result card displays static copy (`Higher heat exposure along parts of the route.`) even when the temperature delta between routes is explicitly `0.00°C`.
   - The generic `+` upload icon in chat only accepts GeoJSON (revealed solely on hover tooltip), causing confusion when standard images or PDFs are rejected.
   - Internal terminology leaks (`Search Activity...` inside the `Heatmaps` list), high-risk red styling on `Clear map` (which only hides the active layer), `Clear All Filters` label on a form with no filters, and minor typo `Feedbacks` under `More`.
