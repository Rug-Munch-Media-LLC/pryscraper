"""Pry MCP Server — expose scrape, crawl, automate as MCP tools.
Enables any MCP-compatible AI agent (Claude, Hermes, Cursor) to use Pry."""

import httpx


class PryMCPServer:
    """MCP server exposing Pry as tools for AI agents.

    Implements the Model Context Protocol (MCP) for tool discovery.
    """

    def __init__(self, base_url: str = "http://localhost:8002"):
        self.base_url = base_url
        self._client = httpx.Client(timeout=60)

    def list_tools(self) -> list[dict]:
        """MCP tool discovery — returns available tools."""
        return [
            {
                "name": "pry_scrape",
                "description": "Scrape a URL to clean markdown. Bypasses Cloudflare automatically.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to scrape"},
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in seconds",
                            "default": 30,
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "pry_crawl",
                "description": "Crawl multiple pages from a starting URL.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Starting URL"},
                        "maxPages": {"type": "integer", "description": "Max pages", "default": 10},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "pry_map",
                "description": "Discover all URLs on a website.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Site URL"},
                        "limit": {"type": "integer", "description": "Max links", "default": 50},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "pry_parse",
                "description": "Parse a document (PDF, DOCX, image) to text.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Document URL"},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "pry_screenshot",
                "description": "Take a screenshot of a URL.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to screenshot"},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "pry_automate",
                "description": "Execute browser automation steps (navigate, click, type, extract). Login automation, form filling.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "steps": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "List of automation steps. Each step: {action, selector?, value?, url?}",
                        }
                    },
                    "required": ["steps"],
                },
            },
        ]

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Execute an MCP tool call."""
        tool_map = {
            "pry_scrape": (
                "/v1/scrape",
                {"url": arguments["url"], "timeout": arguments.get("timeout", 30)},
            ),
            "pry_crawl": (
                "/v1/crawl",
                {"url": arguments["url"], "maxPages": arguments.get("maxPages", 10)},
            ),
            "pry_map": (
                "/v1/map",
                {"url": arguments["url"], "limit": arguments.get("limit", 50)},
            ),
            "pry_parse": ("/v1/parse", {"url": arguments["url"]}),
            "pry_screenshot": ("/v1/screenshot", {"url": arguments["url"]}),
            "pry_automate": ("/v1/automate", {"steps": arguments["steps"]}),
        }

        if name not in tool_map:
            return {"error": f"Unknown tool: {name}"}

        path, payload = tool_map[name]
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{self.base_url}{path}", json=payload)
            return resp.json()


