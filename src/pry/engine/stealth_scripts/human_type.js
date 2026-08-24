// SPDX-License-Identifier: BSL-1.1
// Copyright (c) 2026 Rug Munch Media LLC
//
// Part of Pry — Stealth Script.
// Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.

        (() => {
            window.__pry_humanType = async (selector, text) => {
                const el = document.querySelector(selector);
                if (!el) return;
                el.focus();
                el.value = '';
                for (const char of text) {
                    el.value += char;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('keydown', { bubbles: true }));
                    el.dispatchEvent(new Event('keyup', { bubbles: true }));
                    const delay = char === ' ' ? Math.random() * 200 + 100 : Math.random() * 80 + 40;
                    await new Promise(r => setTimeout(r, delay));
                }
                el.dispatchEvent(new Event('change', { bubbles: true }));
            };
        })();
        