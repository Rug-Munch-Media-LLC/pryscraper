module.exports = {
	docs: [
		"intro",
		{
			type: "category",
			label: "Getting Started",
			items: ["quickstart", "installation", "configuration"],
		},
		{
			type: "category",
			label: "API Reference",
			items: [
				"api/scrape",
				"api/crawl",
				"api/extract",
				"api/templates",
				"api/data",
			],
		},
		{
			type: "category",
			label: "x402 Payments",
			items: [
				"x402/overview",
				"x402/networks",
				"x402/pricing",
				"x402/verification",
			],
		},
		{
			type: "category",
			label: "MCP Server",
			items: ["mcp/overview", "mcp/tools", "mcp/transports", "mcp/discovery"],
		},
		{
			type: "category",
			label: "Advanced",
			items: [
				"advanced/15-tier-fallback",
				"advanced/stealth",
				"advanced/signup",
				"advanced/captcha",
			],
		},
		{
			type: "category",
			label: "Templates",
			items: [
				"templates/overview",
				"templates/ecommerce",
				"templates/jobs",
				"templates/legal",
			],
		},
		"changelog",
	],
};
