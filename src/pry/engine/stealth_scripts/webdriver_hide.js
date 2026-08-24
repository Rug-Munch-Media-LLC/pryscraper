// SPDX-License-Identifier: BSL-1.1
// Copyright (c) 2026 Rug Munch Media LLC
//
// Part of Pry — Stealth Script.
// Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.

        (() => {
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => Math.floor(Math.random() * 4) + 2 });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => Math.floor(Math.random() * 4) + 2 });
            window.chrome = { runtime: {} };
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (p) => (
                p.name === 'notifications' ? Promise.resolve({state: 'denied'}) : originalQuery(p)
            );
        })();
        