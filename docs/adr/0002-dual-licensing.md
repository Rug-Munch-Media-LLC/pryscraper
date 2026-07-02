[//]: # (SPDX-License-Identifier: MIT)
[//]: # (Copyright (c) 2026 Rug Munch Media LLC)
# ADR-0002: Dual Licensing (MIT + BSL 1.1)

## Status
Accepted

## Date
2026-07-03

## Context

The Pry (munchcrawl) project was initially released under a full proprietary license. This licensing model resulted in zero community engagement, zero external contributors, and zero GitHub stars. In the competitive web scraping and data extraction market, open source projects such as Firecrawl and Crawl4AI have achieved dominant positions by leveraging MIT licensing to build strong community moats, attract contributors, and establish trust with users.

The existing LICENSING_PRICING_STRATEGY.md document previously listed Pry as PROPRIETARY. This approach proved incompatible with the project's goal of achieving widespread adoption, particularly for the Model Context Protocol (MCP) server and template marketplace components that benefit from community contributions and third-party integrations.

The core challenge is that a fully proprietary license prevents the project from competing on community moat. Without open source licensing, potential users cannot inspect the codebase for security vulnerabilities, cannot contribute improvements, and cannot build trust in the scraping engine's reliability. The project requires a licensing strategy that balances community growth with protection of proprietary anti-detection techniques that constitute the project's competitive advantage.

## Decision

Pry will adopt a dual licensing model consisting of MIT for the core scraping engine and Business Source License 1.1 (BSL 1.1) for the anti-detection and stealth components.

The MIT license will apply to the core scraping engine, comprising over 100 files including: the scraper module, extractor module, parser module, all 80+ templates, MCP server, x402 protocol implementation, command-line interface, software development kit, browser extension, WordPress plugin, Shopify app, and all LLM provider integrations. The MIT license permits free use, modification, and redistribution of these files by any party.

The BSL 1.1 license will apply to 15 anti-detection and stealth files: ultimate_scraper.py, stealth_engine.py, all stealth_scripts/*.js files, camoufox_integration.py, tls_fingerprint.py, cookie_warmer.py, behavioral_biometrics.py, adaptive.py, browser_pool.py, network.py, captcha_solver.py, shadow_dom.py, lazy_load.py, signup_automator.py, and auth_connector.py. The BSL 1.1 includes an Additional Use Grant that permits personal use, non-production testing, academic research, non-commercial open source software development, and 90-day evaluation. The BSL Change License is MIT, not GPLv2. The Change Date is set to 2029-01-01, after which all BSL-licensed files automatically convert to MIT.

## Consequences

Positive: The MIT-licensed core engine will enable community growth, attract GitHub stars, build user trust through code transparency, and drive adoption of the MCP server and template marketplace. External contributors can submit improvements to the scraping engine, parser, and integrations.

Positive: Users and auditors can inspect the core scraping engine for security vulnerabilities, data handling practices, and code quality. This transparency is essential for enterprise adoption and regulatory compliance.

Positive: The BSL 1.1 protection on anti-detection files preserves the project's competitive moat. Competitors can see and copy the core engine code under MIT, but cannot legally copy the anti-detection techniques that differentiate Pry from other scraping tools.

Negative: Competitors can freely use, modify, and redistribute the core scraping engine code. This may lead to derivative projects that compete with Pry's commercial offerings, though they will lack the protected anti-detection capabilities.

Negative: The dual licensing model introduces complexity in license compliance. Contributors and users must understand which files are under MIT versus BSL 1.1, and the BSL 1.1 Additional Use Grant limitations must be clearly communicated.

## Alternatives

Full MIT license: Rejected because it would expose all anti-detection techniques to competitors, eliminating the project's primary competitive advantage. Without protection of these techniques, the project would have no sustainable differentiation in the market.

Full proprietary license: Rejected because it resulted in zero community engagement, zero contributors, and zero adoption. This model proved incompatible with building the community moat necessary to compete with Firecrawl and Crawl4AI.

AGPL version 3 plus commercial license: Rejected because the AGPL's viral copyleft nature would deter many potential users and contributors who prefer permissive licensing. The AGPL also creates compatibility issues with the MIT-licensed ecosystem that the project depends upon.

BSL 1.1 on all files: Rejected because applying BSL to the entire codebase would prevent the community adoption and trust-building that only a permissive license can provide. Users would be unable to freely use the core engine without evaluating the BSL's Additional Use Grant limitations.

## References

- LICENSE (MIT) - Core scraping engine license file
- LICENSE-BSL-STEALTH (BSL 1.1) - Anti-detection components license file
- https://mariadb.com/bsl11/ - Business Source License 1.1 official documentation
- ADR-0000-template.md - Architecture Decision Record template used for this document
- LICENSING_PRICING_STRATEGY.md - Previous licensing strategy document (superseded by this ADR)
