/**
 * Pry MCP Worker — Cloudflare Worker for the Model Context Protocol.
 *
 * This worker exposes Pry's scrape/automate/extract capabilities over the
 * official MCP HTTP+SSE transport. It is stateless per session (Durable Objects
 * would be needed for multi-region persistence) and proxies all tool execution
 * to the Pry REST API.
 *
 * Environment:
 *   PRY_API_URL   — base URL of the Pry backend (default: https://pry.dev)
 *   PRY_API_KEY   — optional API key for private Pry instances
 *
 * Endpoints:
 *   GET    /sse            — SSE stream; receive `endpoint` event first
 *   POST   /messages/:sid  — post JSON-RPC messages
 *   GET    /health         — worker health + capability summary
 */

const DEFAULT_PRY_API_URL = "https://pry.dev";

const TOOLS = [
  {
    name: "pry_scrape",
    description: "Scrape a URL to clean markdown. Bypasses Cloudflare automatically.",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", format: "uri" },
        bypass_cloudflare: { type: "boolean", default: true },
        js_render: { type: "boolean", default: false },
      },
      required: ["url"],
    },
  },
  {
    name: "pry_crawl",
    description: "Crawl a website starting from a URL.",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", format: "uri" },
        max_pages: { type: "integer", default: 10, minimum: 1, maximum: 10000 },
        max_depth: { type: "integer", default: 2, minimum: 0, maximum: 20 },
      },
      required: ["url"],
    },
  },
  {
    name: "pry_extract",
    description: "Extract structured data from a URL using CSS selectors.",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", format: "uri" },
        schema: { type: "object" },
      },
      required: ["url", "schema"],
    },
  },
  {
    name: "pry_template",
    description: "Execute one of 110+ pre-built scraper templates.",
    inputSchema: {
      type: "object",
      properties: {
        template_id: { type: "string" },
        url: { type: "string", format: "uri" },
      },
      required: ["template_id", "url"],
    },
  },
  {
    name: "pry_search_templates",
    description: "Search across all 110+ available scraper templates.",
    inputSchema: {
      type: "object",
      properties: { q: { type: "string" }, category: { type: "string" } },
      required: ["q"],
    },
  },
  {
    name: "pry_enrich",
    description: "Enrich a URL with company info, tech stack, and social profiles.",
    inputSchema: {
      type: "object",
      properties: { url: { type: "string", format: "uri" } },
      required: ["url"],
    },
  },
  {
    name: "pry_x402_pricing",
    description: "Get current x402 pay-per-call pricing for all Pry operations.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "pry_referrals",
    description: "Get Pry's referral catalog.",
    inputSchema: {
      type: "object",
      properties: { category: { type: "string" } },
    },
  },
];

const RESOURCES = [
  {
    uri: "pry://catalog",
    name: "Scraper Template Catalog",
    description: "All 110+ available scraper templates organized by category.",
    mimeType: "application/json",
    annotations: { audience: ["user", "assistant"], priority: 0.9 },
  },
  {
    uri: "pry://stats",
    name: "Pry Usage Statistics",
    description: "Current Pry server statistics.",
    mimeType: "application/json",
    annotations: { audience: ["assistant"], priority: 0.5 },
  },
  {
    uri: "pry://x402/pricing",
    name: "x402 Pay-per-call Pricing",
    description: "x402 pricing for all paid operations.",
    mimeType: "application/json",
    annotations: { audience: ["user", "assistant"], priority: 0.8 },
  },
  {
    uri: "pry://referrals",
    name: "Referral Catalog",
    description: "Pry's referral program catalog.",
    mimeType: "application/json",
    annotations: { audience: ["assistant"], priority: 0.3 },
  },
];

const PROMPTS = [
  {
    name: "research_company",
    title: "Research a Company",
    description: "Scrape and analyze a company website for competitive intelligence.",
    arguments: [
      { name: "company_name", description: "Company name", required: true },
      { name: "website", description: "Company website URL", required: true },
    ],
  },
  {
    name: "compare_products",
    title: "Compare Products",
    description: "Compare product pages across e-commerce sites.",
    arguments: [
      { name: "product_query", description: "What to search for", required: true },
      { name: "sites", description: "Sites to compare", required: true },
    ],
  },
  {
    name: "extract_contacts",
    title: "Extract Contacts",
    description: "Crawl a website and extract contact information.",
    arguments: [
      { name: "url", description: "Starting URL", required: true },
      { name: "max_pages", description: "Max pages", required: false },
    ],
  },
];

const TOOL_MAP = {
  pry_scrape: ["POST", "/v1/scrape"],
  pry_crawl: ["POST", "/v1/crawl"],
  pry_extract: ["POST", "/v1/extract/css"],
  pry_template: ["POST", "/v1/templates/execute"],
  pry_search_templates: ["GET", "/v1/templates"],
  pry_enrich: ["POST", "/v1/enrich"],
  pry_x402_pricing: ["GET", "/v1/x402/pricing"],
  pry_referrals: ["GET", "/v1/referrals/catalog"],
};

function newSessionId() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function sseEvent(event, data) {
  return `event: ${event}\ndata: ${data}\n\n`;
}

async function handleJsonRpc(request, env) {
  const body = await request.json();
  const method = body.method;
  const id = body.id ?? null;

  if (method === "initialize") {
    return {
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: "2024-11-05",
        serverInfo: { name: "pry", version: "3.0.0" },
        capabilities: {
          tools: { listChanged: false },
          resources: { subscribe: false, listChanged: false },
          prompts: { listChanged: false },
          logging: {},
        },
      },
    };
  }

  if (method === "ping") {
    return { jsonrpc: "2.0", id, result: {} };
  }

  if (method === "tools/list") {
    return { jsonrpc: "2.0", id, result: { tools: TOOLS } };
  }

  if (method === "tools/call") {
    return await callTool(body.params?.name, body.params?.arguments || {}, env);
  }

  if (method === "resources/list") {
    return { jsonrpc: "2.0", id, result: { resources: RESOURCES } };
  }

  if (method === "resources/read") {
    return await readResource(body.params?.uri, env);
  }

  if (method === "prompts/list") {
    return { jsonrpc: "2.0", id, result: { prompts: PROMPTS } };
  }

  if (method === "prompts/get") {
    return getPrompt(body.params?.name, body.params?.arguments || {});
  }

  if (method === "logging/setLevel") {
    return { jsonrpc: "2.0", id, result: {} };
  }

  return {
    jsonrpc: "2.0",
    id,
    error: { code: -32601, message: `Method not found: ${method}` },
  };
}

async function callTool(name, args, env) {
  const mapping = TOOL_MAP[name];
  if (!mapping) {
    return {
      content: [{ type: "text", text: `Tool ${name} not available in worker` }],
      isError: false,
    };
  }
  const [httpMethod, path] = mapping;
  const base = (env.PRY_API_URL || DEFAULT_PRY_API_URL).replace(/\/$/, "");
  const url = httpMethod === "GET" ? `${base}${path}?${new URLSearchParams(args)}` : `${base}${path}`;
  const headers = { "Content-Type": "application/json" };
  if (env.PRY_API_KEY) headers["Authorization"] = `Bearer ${env.PRY_API_KEY}`;

  try {
    const resp = await fetch(url, {
      method: httpMethod,
      headers,
      body: httpMethod === "GET" ? undefined : JSON.stringify(args),
    });
    const data = await resp.json();
    return {
      content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
      isError: false,
    };
  } catch (e) {
    return {
      content: [{ type: "text", text: `Pry API call failed: ${e.message}` }],
      isError: true,
    };
  }
}

async function readResource(uri, env) {
  const base = (env.PRY_API_URL || DEFAULT_PRY_API_URL).replace(/\/$/, "");
  let text = "";
  try {
    if (uri === "pry://catalog") {
      const resp = await fetch(`${base}/v1/templates`);
      const data = await resp.json();
      text = JSON.stringify(data, null, 2);
    } else if (uri === "pry://x402/pricing") {
      const resp = await fetch(`${base}/v1/x402/pricing`);
      const data = await resp.json();
      text = JSON.stringify(data, null, 2);
    } else if (uri === "pry://referrals") {
      const resp = await fetch(`${base}/v1/referrals/catalog`);
      const data = await resp.json();
      text = JSON.stringify(data, null, 2);
    } else {
      text = JSON.stringify({ uri, note: "Resource placeholder" });
    }
  } catch (e) {
    text = JSON.stringify({ error: e.message });
  }
  return {
    contents: [{ uri, mimeType: "application/json", text }],
  };
}

function getPrompt(name, args) {
  const prompt = PROMPTS.find((p) => p.name === name);
  if (!prompt) {
    return { error: { code: -32602, message: `Prompt not found: ${name}` } };
  }
  const argText = Object.entries(args)
    .map(([k, v]) => `${k}=${v}`)
    .join(", ");
  return {
    description: prompt.description,
    messages: [
      {
        role: "user",
        content: {
          type: "text",
          text: `Execute the ${prompt.title} prompt with arguments: ${argText}`,
        },
      },
    ],
  };
}

const sessions = new Map(); // sid -> controller

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return new Response(
        JSON.stringify({
          status: "ok",
          server: "pry-mcp-worker",
          version: "3.0.0",
          protocol_version: "2024-11-05",
          tools_count: TOOLS.length,
          resources_count: RESOURCES.length,
          prompts_count: PROMPTS.length,
        }),
        { headers: { "Content-Type": "application/json" } }
      );
    }

    if (url.pathname === "/sse") {
      const sid = newSessionId();
      const postUrl = `${url.origin}/messages/${sid}`;
      const stream = new ReadableStream({
        start(controller) {
          sessions.set(sid, controller);
          controller.enqueue(new TextEncoder().encode(sseEvent("endpoint", postUrl)));
          const keepalive = setInterval(() => {
            controller.enqueue(new TextEncoder().encode(": ping\n\n"));
          }, 30000);
          ctx.waitUntil(
            new Promise((resolve) => {
              const check = setInterval(() => {
                if (!sessions.has(sid)) {
                  clearInterval(keepalive);
                  clearInterval(check);
                  resolve();
                }
              }, 5000);
            })
          );
        },
        cancel() {
          sessions.delete(sid);
        },
      });
      return new Response(stream, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache, no-transform",
          Connection: "keep-alive",
          "X-Accel-Buffering": "no",
        },
      });
    }

    const messagesMatch = url.pathname.match(/^\/messages\/([a-zA-Z0-9]+)$/);
    if (messagesMatch && request.method === "POST") {
      const sid = messagesMatch[1];
      const response = await handleJsonRpc(request, env);
      if (response !== null) {
        const controller = sessions.get(sid);
        if (controller) {
          controller.enqueue(
            new TextEncoder().encode(sseEvent("message", JSON.stringify(response)))
          );
        }
      }
      return new Response(null, { status: 202 });
    }

    return new Response("Not found", { status: 404 });
  },
};
