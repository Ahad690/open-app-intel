"""AppScope — self-hosted, federated open app-intelligence stack.

See PRD (open-app-intel-PRD-v1.1.md). There is no central server: each user
runs the collectors, estimator, REST API and MCP server locally with their own
keys. Only public app-store calibration anchors are ever federated.
"""

__version__ = "1.1.0"
