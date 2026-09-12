// SPDX-License-Identifier: BSL-1.1
// Copyright (c) 2026 Rug Munch Media LLC
//
// Part of Pry — Stealth Script.
// Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.

(() => {
	const noise = 0.00017348278297823374;
	const toDataURL = HTMLCanvasElement.prototype.toDataURL;
	HTMLCanvasElement.prototype.toDataURL = function (type, quality) {
		const ctx = this.getContext("2d");
		if (ctx) {
			const imageData = ctx.getImageData(0, 0, this.width, this.height);
			for (let i = 0; i < imageData.data.length; i += 4) {
				imageData.data[i] = Math.min(
					255,
					Math.max(
						0,
						imageData.data[i] + (Math.random() > 0.5 ? 1 : -1) * noise * 255,
					),
				);
			}
			ctx.putImageData(imageData, 0, 0);
		}
		return toDataURL.call(this, type, quality);
	};
})();
