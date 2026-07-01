
        (() => {
            window.__pry_mouse = { x: 0, y: 0, clicks: 0 };
            document.addEventListener('mousemove', (e) => {
                window.__pry_mouse.x = e.clientX;
                window.__pry_mouse.y = e.clientY;
            });
            window.__pry_humanClick = async (selector) => {
                const el = document.querySelector(selector);
                if (!el) return;
                const rect = el.getBoundingClientRect();
                const targetX = rect.left + rect.width / 2 + (Math.random() - 0.5) * 10;
                const targetY = rect.top + rect.height / 2 + (Math.random() - 0.5) * 10;
                const steps = Math.floor(Math.random() * 10) + 15;
                for (let i = 0; i <= steps; i++) {
                    const t = i / steps;
                    const x = window.__pry_mouse.x + (targetX - window.__pry_mouse.x) * (1 - Math.pow(1 - t, 3));
                    const y = window.__pry_mouse.y + (targetY - window.__pry_mouse.y) * (1 - Math.pow(1 - t, 3));
                    el.dispatchEvent(new MouseEvent('mousemove', { clientX: x, clientY: y, bubbles: true }));
                    await new Promise(r => setTimeout(r, Math.random() * 30 + 10));
                }
                el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
                await new Promise(r => setTimeout(r, Math.random() * 100 + 50));
                el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                await new Promise(r => setTimeout(r, Math.random() * 50 + 20));
                el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                window.__pry_mouse.clicks++;
            };
        })();
        