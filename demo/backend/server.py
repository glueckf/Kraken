"""Local dev push-pull scoring backend for the Kraken demo.

Implements the one endpoint the frontend already knows how to call
(see demo/web/src/backend.ts): POST /score {scenario_id, placement} ->
{cost, latency, per_placement}. scenario_id is "<topology_id>/<query_id>",
e.g. "medium/seq_abc" — matching the manifest's "file" field convention,
since query ids alone aren't unique across topologies.

Each request shells out to score_one.py in a fresh subprocess (see that
file's docstring for why: topology reconstruction must be isolated the same
way export_scenario.py isolates its own exports, or RNG state from one
topology could leak into another's and silently mismatch what the frontend
is showing). A few hundred ms to ~1s per request is fine here — the UI
already shows a "optimising communication…" pending state while it waits.

Run:  python demo/backend/server.py  (defaults to http://localhost:8787)
"""
import json
import os
import subprocess
import sys

from flask import Flask, jsonify, request

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.dirname(HERE)
WORKER = os.path.join(DEMO, "export", "score_one.py")
PORT = int(os.environ.get("PORT", 8787))

app = Flask(__name__)


@app.after_request
def add_cors_headers(resp):
    # Local dev only: the frontend (esbuild serve, a different port) needs to
    # be allowed to call this cross-origin.
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.route("/score", methods=["POST", "OPTIONS"])
def score():
    if request.method == "OPTIONS":
        return "", 204

    body = request.get_json(silent=True) or {}
    scenario_id = body.get("scenario_id", "")
    placement = body.get("placement")
    if not isinstance(placement, dict):
        return jsonify({"error": "missing or invalid 'placement'"}), 400

    if "/" not in scenario_id:
        return jsonify({"error": "scenario_id must be '<topology_id>/<query_id>'"}), 400
    topology_id, query_id = scenario_id.split("/", 1)

    try:
        result = subprocess.run(
            [sys.executable, WORKER, topology_id, query_id, json.dumps(placement)],
            capture_output=True, text=True, timeout=20,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "scoring timed out"}), 504

    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return jsonify({"error": "worker produced no parseable output", "stderr": result.stderr[-2000:]}), 500

    if "error" in data:
        return jsonify(data), 422
    return jsonify(data)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
