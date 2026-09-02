module.exports = {
	title: "Pry Scraping API",
	tagline: "Pay-per-request HTTP for the multi-chain economy",
	url: "https://docs.pryscraper.com",
	baseUrl: "/",
	onBrokenLinks: "throw",
	favicon: "img/favicon.ico",
	organizationName: "RugMunchMedia",
	projectName: "pryscraper",
	themeConfig: {
		navbar: {
			title: "Pry",
			logo: { alt: "Pry Logo", src: "img/logo.svg", href: "/docs/intro" },
			items: [
				{ to: "/docs/intro", label: "Docs", position: "left" },
				{ to: "/docs/api/scrape", label: "API", position: "left" },
				{ to: "/docs/x402/overview", label: "x402", position: "left" },
				{ to: "/docs/mcp/overview", label: "MCP", position: "left" },
				{
					to: "/docs/templates/overview",
					label: "Templates",
					position: "left",
				},
				{
					href: "https://codeberg.org/RugMunchMedia/pryscraper",
					label: "GitHub",
					position: "right",
				},
			],
		},
		footer: {
			style: "dark",
			links: [
				{
					title: "Docs",
					items: [
						{ label: "Quickstart", to: "docs/intro" },
						{ label: "API Reference", to: "docs/api/scrape" },
						{ label: "x402 Payments", to: "docs/x402/overview" },
						{ label: "MCP Server", to: "docs/mcp/overview" },
					],
				},
				{
					title: "Community",
					items: [
						{
							label: "GitHub",
							href: "https://codeberg.org/RugMunchMedia/pryscraper",
						},
					],
				},
				{
					title: "More",
					items: [
						{ label: "Blog", to: "blog" },
						{ label: "Changelog", to: "docs/changelog" },
					],
				},
			],
			copyright: `Copyright © ${new Date().getFullYear()} Rug Munch Media LLC.`,
		},
		prism: {
			theme: {
				plain: { color: "#393A34", backgroundColor: "#f6f8fa" },
				styles: [],
			},
			additionalLanguages: ["bash", "json", "yaml", "toml"],
		},
	},
	presets: [
		[
			"classic",
			{
				docs: {
					sidebarPath: require.resolve("./sidebars.js"),
					editUrl:
						"https://codeberg.org/RugMunchMedia/pryscraper/tree/main/docs/",
				},
				blog: { showReadingTime: true },
				theme: { customCss: require.resolve("./src/css/custom.css") },
			},
		],
	],
};
