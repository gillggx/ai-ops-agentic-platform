# AIOps Pipeline-Builder — remote MCP server

Lets an external Claude (Claude Desktop / cowork) build analysis pipelines via MCP
tools that proxy the in-cluster builder API. Runs on EC2; pure Python (no build).

Tools: `list_blocks`, `explain_block`, `validate`, `preview`, `execute`, `save_pipeline`.
The skill/workflow is baked into the server `instructions` + tool docstrings.

## Deploy (EC2, no build)
    python3 -m venv /opt/aiops/venv_mcp
    /opt/aiops/venv_mcp/bin/pip install -r requirements.txt
    # /opt/aiops/mcp_pipeline_builder/.env :
    #   SIDECAR_SERVICE_TOKEN=...   JAVA_INTERNAL_TOKEN=...   SHARED_SECRET_TOKEN=...
    #   MCP_HOST=127.0.0.1  MCP_PORT=8060  PUBLIC_BASE=https://aiops-gill.com
    sudo cp deploy/aiops-mcp.service /etc/systemd/system/
    sudo systemctl enable --now aiops-mcp

Bind localhost:8060; expose via nginx /mcp with a bearer-token gate. The internal
service tokens stay server-side; only the MCP bearer is public.
