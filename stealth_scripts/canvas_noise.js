
        (() => {
            const noise = 0.00017348278297823374;
            const toDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function(type, quality) {
                const canvas = this;
                const ctx = canvas.getContext('2d');
                if (ctx) {
                    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                    for (let i = 0; i < imageData.data.length; i += 4) {
                        imageData.data[i] = Math.min(255, Math.max(0, imageData.data[i] + (Math.random() > 0.5 ? 1 : -1) * noise * 255));
                    }
                    ctx.putImageData(imageData, 0, 0);
                }
                return toDataURL.call(this, type, quality);
            };
        })();
        