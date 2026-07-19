"""Tool registry for the BI Analyst Agent.

The forecast model is provided (see project/tools/forecast/); the other tools wrap it
plus SQL, KB retrieval, web analytics, actions, and anomaly detection. The registry is
the single entry point the agent loop uses.
"""

from project.tools.registry import REGISTRY, dispatch, get_tools, tool_schemas

__all__ = ["REGISTRY", "dispatch", "get_tools", "tool_schemas"]
