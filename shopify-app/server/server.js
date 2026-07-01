// Pry Shopify App — Express backend for Shopify integration
// Handles OAuth, product import, and webhook registration

const express = require('express');
const app = express();
const PORT = process.env.PORT || 3000;

// In production, use a proper Shopify app framework like @shopify/express
// This is the scaffold showing the integration pattern

app.use(express.json());

// ── OAuth route (simplified — use @shopify/koa-shopify-auth in production) ──
app.get('/auth', (req, res) => {
  const { shop } = req.query;
  if (!shop) {
    return res.status(400).json({error: 'Missing shop parameter'});
  }
  // Redirect to Shopify OAuth
  const redirectUri = `${process.env.HOST}/auth/callback`;
  const installUrl = `https://${shop}/admin/oauth/authorize?client_id=${process.env.SHOPIFY_API_KEY}&scope=write_products,read_products&redirect_uri=${redirectUri}`;
  res.redirect(installUrl);
});

// ── Import product from Pry API → Shopify ──
app.post('/import-product', async (req, res) => {
  const { shop, accessToken, productUrl, pryApiUrl } = req.body;
  
  if (!shop || !accessToken || !productUrl) {
    return res.status(400).json({error: 'Missing required fields'});
  }

  try {
    // 1. Scrape the competitor product via Pry
    const pryResponse = await fetch(pryApiUrl || 'http://localhost:8002/v1/scrape', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: productUrl, bypassCloudflare: true})
    });
    const pryData = await pryResponse.json();
    
    if (!pryData.success) {
      return res.status(502).json({error: 'Pry scrape failed', details: pryData.error});
    }

    const content = pryData.data.content || '';
    const title = pryData.data.title || 'Imported Product';
    
    // 2. Create product in Shopify
    const shopifyProduct = {
      product: {
        title: title.substring(0, 255),
        body_html: `<div>${content.substring(0, 5000)}</div>`,
        vendor: 'Competitor Import',
        product_type: 'Reference',
        status: 'draft',
        metafields_global: [
          {
            key: 'original_source',
            value: productUrl,
            type: 'single_line_text_field',
            namespace: 'pry'
          },
          {
            key: 'imported_at',
            value: new Date().toISOString(),
            type: 'single_line_text_field',
            namespace: 'pry'
          }
        ]
      }
    };

    const shopifyResponse = await fetch(`https://${shop}/admin/api/2024-01/products.json`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Shopify-Access-Token': accessToken
      },
      body: JSON.stringify(shopifyProduct)
    });
    
    const shopifyData = await shopifyResponse.json();
    
    if (shopifyResponse.ok) {
      res.json({
        success: true,
        shopify_product_id: shopifyData.product.id,
        product_url: `https://${shop}/admin/products/${shopifyData.product.id}`,
        title: shopifyData.product.title
      });
    } else {
      res.status(502).json({error: 'Shopify API error', details: shopifyData});
    }
  } catch (err) {
    res.status(500).json({error: err.message});
  }
});

// ── Bulk import multiple products ──
app.post('/bulk-import', async (req, res) => {
  const { shop, accessToken, urls, pryApiUrl } = req.body;
  
  if (!shop || !accessToken || !urls || !Array.isArray(urls)) {
    return res.status(400).json({error: 'Missing required fields'});
  }

  const results = [];
  for (const url of urls) {
    try {
      const importResult = await fetch(`http://localhost:${PORT}/import-product`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({shop, accessToken, productUrl: url, pryApiUrl})
      });
      const data = await importResult.json();
      results.push({url, success: data.success, product_id: data.shopify_product_id});
    } catch (err) {
      results.push({url, success: false, error: err.message});
    }
  }

  res.json({success: true, imported: results.filter(r => r.success).length, failed: results.filter(r => !r.success).length, results});
});

// ── Webhook: product update notifications from Pry monitors ──
app.post('/webhook/pry-monitor', async (req, res) => {
  const { shop, accessToken, productId, newData } = req.body;
  
  // Update the Shopify product with new competitor data
  try {
    const updatePayload = {
      product: {
        metafields_global: [
          {
            key: 'last_monitor_update',
            value: new Date().toISOString(),
            type: 'single_line_text_field',
            namespace: 'pry'
          }
        ]
      }
    };
    
    await fetch(`https://${shop}/admin/api/2024-01/products/${productId}.json`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'X-Shopify-Access-Token': accessToken
      },
      body: JSON.stringify(updatePayload)
    });
    
    res.json({success: true});
  } catch (err) {
    res.status(500).json({error: err.message});
  }
});

app.listen(PORT, () => {
  console.log(`Pry Shopify app running on port ${PORT}`);
});
