// SPDX-License-Identifier: BSL-1.1
// Copyright (c) 2026 Rug Munch Media LLC
//
// Part of Pry — Stealth Script.
// Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.

        (() => {
            const getChannelData = AudioBuffer.prototype.getChannelData;
            AudioBuffer.prototype.getChannelData = function(channel) {
                const data = getChannelData.call(this, channel);
                for (let i = 0; i < data.length; i += 100) {
                    data[i] += (Math.random() - 0.5) * 0.0001;
                }
                return data;
            };
        })();
        