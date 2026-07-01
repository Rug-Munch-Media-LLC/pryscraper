
        (() => {
            const noise = 0.0008210699841618288;
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(p) {
                if (p === 37445) return 'Intel Inc.';
                if (p === 37446) return 'Intel Iris OpenGL Engine';
                const result = getParameter.call(this, p);
                if (typeof result === 'number' && !Number.isInteger(result)) return result + noise;
                return result;
            };
            const getExtension = WebGLRenderingContext.prototype.getExtension;
            WebGLRenderingContext.prototype.getExtension = function(name) {
                if (name === 'WEBGL_debug_renderer_info') return null;
                return getExtension.call(this, name);
            };
        })();
        