import ComponentCreator from "@docusaurus/ComponentCreator";
import React from "react";

export default [
	{
		path: "/blog",
		component: ComponentCreator("/blog", "a5e"),
		exact: true,
	},
	{
		path: "/blog/announcing-pry-3",
		component: ComponentCreator("/blog/announcing-pry-3", "de4"),
		exact: true,
	},
	{
		path: "/blog/archive",
		component: ComponentCreator("/blog/archive", "182"),
		exact: true,
	},
	{
		path: "/blog/authors",
		component: ComponentCreator("/blog/authors", "0b7"),
		exact: true,
	},
	{
		path: "/blog/tags",
		component: ComponentCreator("/blog/tags", "287"),
		exact: true,
	},
	{
		path: "/blog/tags/crypto",
		component: ComponentCreator("/blog/tags/crypto", "51c"),
		exact: true,
	},
	{
		path: "/blog/tags/mcp",
		component: ComponentCreator("/blog/tags/mcp", "bd7"),
		exact: true,
	},
	{
		path: "/blog/tags/release",
		component: ComponentCreator("/blog/tags/release", "951"),
		exact: true,
	},
	{
		path: "/blog/tags/x-402",
		component: ComponentCreator("/blog/tags/x-402", "72a"),
		exact: true,
	},
	{
		path: "/docs",
		component: ComponentCreator("/docs", "53c"),
		routes: [
			{
				path: "/docs",
				component: ComponentCreator("/docs", "5d9"),
				routes: [
					{
						path: "/docs",
						component: ComponentCreator("/docs", "e27"),
						routes: [
							{
								path: "/docs/advanced/15-tier-fallback",
								component: ComponentCreator(
									"/docs/advanced/15-tier-fallback",
									"478",
								),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/advanced/captcha",
								component: ComponentCreator("/docs/advanced/captcha", "90c"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/advanced/signup",
								component: ComponentCreator("/docs/advanced/signup", "4a5"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/advanced/stealth",
								component: ComponentCreator("/docs/advanced/stealth", "de7"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/api/crawl",
								component: ComponentCreator("/docs/api/crawl", "d21"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/api/extract",
								component: ComponentCreator("/docs/api/extract", "703"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/api/scrape",
								component: ComponentCreator("/docs/api/scrape", "9d9"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/api/templates",
								component: ComponentCreator("/docs/api/templates", "894"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/changelog",
								component: ComponentCreator("/docs/changelog", "c45"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/configuration",
								component: ComponentCreator("/docs/configuration", "4e9"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/installation",
								component: ComponentCreator("/docs/installation", "057"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/intro",
								component: ComponentCreator("/docs/intro", "a6e"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/mcp/discovery",
								component: ComponentCreator("/docs/mcp/discovery", "f8a"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/mcp/overview",
								component: ComponentCreator("/docs/mcp/overview", "4e1"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/mcp/tools",
								component: ComponentCreator("/docs/mcp/tools", "20b"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/mcp/transports",
								component: ComponentCreator("/docs/mcp/transports", "210"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/quickstart",
								component: ComponentCreator("/docs/quickstart", "5e3"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/templates/ecommerce",
								component: ComponentCreator("/docs/templates/ecommerce", "128"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/templates/jobs",
								component: ComponentCreator("/docs/templates/jobs", "fdf"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/templates/legal",
								component: ComponentCreator("/docs/templates/legal", "8f6"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/templates/overview",
								component: ComponentCreator("/docs/templates/overview", "2cf"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/x402/networks",
								component: ComponentCreator("/docs/x402/networks", "9d1"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/x402/overview",
								component: ComponentCreator("/docs/x402/overview", "4fe"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/x402/pricing",
								component: ComponentCreator("/docs/x402/pricing", "a0c"),
								exact: true,
								sidebar: "docs",
							},
							{
								path: "/docs/x402/verification",
								component: ComponentCreator("/docs/x402/verification", "153"),
								exact: true,
								sidebar: "docs",
							},
						],
					},
				],
			},
		],
	},
	{
		path: "*",
		component: ComponentCreator("*"),
	},
];
