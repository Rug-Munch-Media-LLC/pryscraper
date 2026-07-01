
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
        