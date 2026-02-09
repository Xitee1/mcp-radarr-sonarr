FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml MANIFEST.in README.md LICENSE ./
COPY radarr_sonarr_mcp/ radarr_sonarr_mcp/

RUN pip install --no-cache-dir .

ENV MCP_TRANSPORT=sse
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8080

EXPOSE 8080

CMD ["python", "-m", "radarr_sonarr_mcp.server"]
