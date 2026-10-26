-- rugdex.pairs repair - UP / DOWN. Source of truth: pry.datasources.dextools_repair.
-- The writer of rugdex.pairs is outside every repo; this is the documented fix.
CREATE TABLE rugdex.pairs_v2 (
    chain String, pair_address String, token_address String, token_name String,
    token_symbol String, quote_token String, dex String, created_at DateTime,
    liquidity_usd Float64, fdv_usd Float64, price_usd Nullable(Float64), source_url String
) ENGINE = ReplacingMergeTree ORDER BY (chain, pair_address)
TTL created_at + toIntervalDay(180) SETTINGS index_granularity = 8192;

INSERT INTO rugdex.pairs_v2
SELECT chain, pair_address, token_address, token_name,
    multiIf(position(token_name, ' / ') > 0
            AND trimBoth(splitByString(' / ', token_name)[1]) != '',
            trimBoth(splitByString(' / ', token_name)[1]),
            match(token_symbol, '^[0-9]'), '', token_symbol) AS token_symbol,
    quote_token, dex, created_at, liquidity_usd, fdv_usd,
    toFloat64OrNull(replaceAll(token_symbol, ',', '')) AS price_usd,
    concat('https://www.dextools.io/app/', chain, '/pair-explorer/',
        if(startsWith(pair_address, concat(chain, '_')),
           substring(pair_address, length(chain) + 2), pair_address)) AS source_url
FROM (
    SELECT *, row_number() OVER (
        PARTITION BY chain, token_address ORDER BY created_at DESC, pair_address DESC
    ) AS rn FROM rugdex.pairs FINAL
) WHERE rn = 1;

EXCHANGE TABLES rugdex.pairs AND rugdex.pairs_v2;
RENAME TABLE rugdex.pairs_v2 TO rugdex.pairs_unrepaired_20261026;
-- DOWN: EXCHANGE TABLES rugdex.pairs AND rugdex.pairs_unrepaired_20261026;
