"""Dashboard live server with refresh endpoint.

Serves the unified dashboard HTML and provides a /refresh endpoint
that regenerates the dashboard data without restarting the server.
"""

import os
import threading
from flask import Flask, send_file, jsonify

from shared.utils import logger

app = Flask(__name__)

# Will be set by serve()
_output_dir = None
_tickers = None
_refresh_lock = threading.Lock()
_is_refreshing = False


@app.route("/")
def index():
    path = os.path.join(_output_dir, "unified_dashboard.html")
    if not os.path.exists(path):
        return "Dashboard not generated yet. Hit /refresh first.", 404
    return send_file(path)


@app.route("/refresh", methods=["POST"])
def refresh():
    global _is_refreshing
    if _is_refreshing:
        return jsonify({"status": "already_running"}), 409

    def _run():
        global _is_refreshing
        try:
            _is_refreshing = True
            logger.info("Dashboard refresh triggered from browser")
            from dashboard.unified import generate_unified_dashboard
            generate_unified_dashboard(output_dir=_output_dir, tickers=_tickers)
            logger.info("Dashboard refresh complete")
        except Exception as e:
            logger.error(f"Dashboard refresh failed: {e}")
        finally:
            _is_refreshing = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/refresh/status")
def refresh_status():
    return jsonify({"refreshing": _is_refreshing})


def serve(output_dir, tickers=None, port=8050):
    """Start the dashboard server."""
    global _output_dir, _tickers
    _output_dir = output_dir
    _tickers = tickers

    # Generate dashboard on first launch if it doesn't exist
    path = os.path.join(_output_dir, "unified_dashboard.html")
    if not os.path.exists(path):
        logger.info("No dashboard found, generating on first launch...")
        from dashboard.unified import generate_unified_dashboard
        generate_unified_dashboard(output_dir=_output_dir, tickers=_tickers)

    print(f"\n  Dashboard server running at http://localhost:{port}")
    print(f"  Press Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=port, debug=False)
