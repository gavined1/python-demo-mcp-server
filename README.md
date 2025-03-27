# Python Demo MCP Server

## Introduction
This is a demonstration server implementing the Model Context Protocol (MCP) with Server-Sent Events (SSE). It provides a practical example of how to build a server that can handle streaming content production and management.

## Getting Started

1. Set up your Python environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install the required packages

```bash
uv pip install -r requirements.txt
```

## Run the server

### Development Environment

```bash
python server.py
```

The server will start on http://localhost:8080 by default.

### Production Environment

For deployment on Sevalla, make sure to select Dockerfile based build environment!

## Usage in Cursor

To use this server in Cursor, paste the following in your `mcp.json` file:

```json
"demo-mcp": {
  "url": "https://<your-mcp-server-domain>/sse"
}
```

Make sure to replace `<your-mcp-server-domain>` with the actual domain of your server.