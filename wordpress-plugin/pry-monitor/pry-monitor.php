<?php
/**
 * Plugin Name: Pry Monitor
 * Plugin URI: https://pry.dev
 * Description: Competitor price & content monitoring directly in your WordPress dashboard. Track competitors, get alerts, and sync data to WooCommerce.
 * Version: 1.0.0
 * Author: Rug Munch Media LLC
 * License: GPL v2 or later
 * Text Domain: pry-monitor
 *
 * WC requires at least: 8.0
 * WC tested up to: 9.0
 */

defined('ABSPATH') or die('Direct access not allowed');

define('PRY_MONITOR_VERSION', '1.0.0');
define('PRY_MONITOR_API_URL', get_option('pry_api_url', 'http://localhost:8002'));
define('PRY_MONITOR_API_KEY', get_option('pry_api_key', ''));

// ── Admin Menu ──
add_action('admin_menu', 'pry_monitor_admin_menu');
function pry_monitor_admin_menu() {
    add_menu_page(
        'Pry Monitor',
        'Pry Monitor',
        'manage_options',
        'pry-monitor',
        'pry_monitor_dashboard_page',
        'dashicons-chart-area',
        30
    );
    add_submenu_page(
        'pry-monitor',
        'Competitors',
        'Competitors',
        'manage_options',
        'pry-monitor-competitors',
        'pry_monitor_competitors_page'
    );
    add_submenu_page(
        'pry-monitor',
        'Monitors',
        'Monitors',
        'manage_options',
        'pry-monitor-monitors',
        'pry_monitor_monitors_page'
    );
    add_submenu_page(
        'pry-monitor',
        'Settings',
        'Settings',
        'manage_options',
        'pry-monitor-settings',
        'pry_monitor_settings_page'
    );
    add_submenu_page(
        'pry-monitor',
        'WooCommerce Sync',
        'Woo Sync',
        'manage_options',
        'pry-monitor-woo',
        'pry_monitor_woo_page'
    );
    add_submenu_page(
        'pry-monitor',
        'Proxy Settings',
        'Proxy',
        'manage_options',
        'pry-monitor-proxy',
        'pry_monitor_proxy_page'
    );
}

// ── Dashboard Page ──
function pry_monitor_dashboard_page() {
    ?>
    <div class="wrap">
        <h1>Pry Monitor Dashboard</h1>
        <div class="pry-stats-grid">
            <?php
            $stats = pry_monitor_api_get('/v1/costing/dashboard');
            $monitors = pry_monitor_api_get('/v1/monitors');
            ?>
            <div class="pry-stat-card">
                <h3>Active Monitors</h3>
                <p class="pry-stat-number"><?php echo esc_html($monitors['data']['total'] ?? 0); ?></p>
            </div>
            <div class="pry-stat-card">
                <h3>Monthly Cost</h3>
                <p class="pry-stat-number">$<?php echo esc_html(number_format($stats['data']['current_month']['projected_monthly_cost'] ?? 0, 2)); ?></p>
            </div>
            <div class="pry-stat-card">
                <h3>Competitors Tracked</h3>
                <p class="pry-stat-number"><?php echo esc_html(count(get_option('pry_competitors', []))); ?></p>
            </div>
        </div>

        <div class="pry-section">
            <h2>Quick Actions</h2>
            <div class="pry-actions">
                <a href="<?php echo admin_url('admin.php?page=pry-monitor-competitors'); ?>" class="button button-primary">Add Competitor</a>
                <a href="<?php echo admin_url('admin.php?page=pry-monitor-monitors'); ?>" class="button">Create Monitor</a>
                <a href="<?php echo admin_url('admin.php?page=pry-monitor-woo'); ?>" class="button">Sync to WooCommerce</a>
            </div>
        </div>
    </div>
    <style>
        .pry-stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }
        .pry-stat-card { background: #fff; border: 1px solid #ccd0d4; padding: 20px; border-radius: 4px; text-align: center; }
        .pry-stat-number { font-size: 2em; font-weight: bold; margin: 10px 0; color: #2271b1; }
        .pry-section { margin: 30px 0; }
        .pry-actions { display: flex; gap: 10px; flex-wrap: wrap; }
        .pry-monitor-table { width: 100%; border-collapse: collapse; }
        .pry-monitor-table th { background: #f0f0f1; text-align: left; padding: 10px; }
        .pry-monitor-table td { padding: 10px; border-bottom: 1px solid #f0f0f1; }
        .pry-status-active { color: #00a32a; font-weight: bold; }
        .pry-status-error { color: #d63638; font-weight: bold; }
        .pry-form-field { margin: 15px 0; }
        .pry-form-field label { display: block; font-weight: 600; margin-bottom: 5px; }
        .pry-form-field input[type="text"], .pry-form-field input[type="url"] { width: 100%; max-width: 500px; }
    </style>
    <?php
}

// ── Competitors Page ──
function pry_monitor_competitors_page() {
    if (isset($_POST['add_competitor']) && check_admin_referer('pry_add_competitor')) {
        $name = sanitize_text_field($_POST['competitor_name']);
        $url = esc_url_raw($_POST['competitor_url']);
        $competitors = get_option('pry_competitors', []);
        $competitors[] = ['name' => $name, 'url' => $url, 'added' => current_time('mysql')];
        update_option('pry_competitors', $competitors);
        echo '<div class="notice notice-success"><p>Competitor added!</p></div>';
    }
    if (isset($_GET['delete'])) {
        $index = intval($_GET['delete']);
        $competitors = get_option('pry_competitors', []);
        if (isset($competitors[$index])) {
            unset($competitors[$index]);
            update_option('pry_competitors', array_values($competitors));
            echo '<div class="notice notice-success"><p>Competitor removed.</p></div>';
        }
    }

    $competitors = get_option('pry_competitors', []);
    ?>
    <div class="wrap">
        <h1>Competitors</h1>
        <form method="post" style="background:#fff;padding:20px;border:1px solid #ccd0d4;margin-bottom:20px;">
            <?php wp_nonce_field('pry_add_competitor'); ?>
            <h2>Add Competitor</h2>
            <div class="pry-form-field">
                <label for="competitor_name">Competitor Name</label>
                <input type="text" name="competitor_name" id="competitor_name" required placeholder="e.g., Acme Corp" />
            </div>
            <div class="pry-form-field">
                <label for="competitor_url">Competitor URL</label>
                <input type="url" name="competitor_url" id="competitor_url" required placeholder="https://competitor.com/pricing" />
            </div>
            <p><button type="submit" name="add_competitor" class="button button-primary">Add Competitor</button></p>
        </form>

        <h2>Tracked Competitors</h2>
        <?php if (empty($competitors)): ?>
            <p>No competitors added yet. Add your first competitor above.</p>
        <?php else: ?>
            <table class="pry-monitor-table">
                <thead><tr><th>Name</th><th>URL</th><th>Added</th><th>Actions</th></tr></thead>
                <tbody>
                    <?php foreach ($competitors as $i => $comp): ?>
                        <tr>
                            <td><strong><?php echo esc_html($comp['name']); ?></strong></td>
                            <td><a href="<?php echo esc_url($comp['url']); ?>" target="_blank"><?php echo esc_html($comp['url']); ?></a></td>
                            <td><?php echo esc_html($comp['added']); ?></td>
                            <td>
                                <a href="<?php echo admin_url('admin.php?page=pry-monitor-competitors&delete=' . $i); ?>" class="button button-small" onclick="return confirm('Remove this competitor?')">Remove</a>
                            </td>
                        </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
            <form method="post" action="<?php echo admin_url('admin-post.php'); ?>" style="margin-top:20px;">
                <input type="hidden" name="action" value="pry_bulk_scan_competitors">
                <?php wp_nonce_field('pry_bulk_scan'); ?>
                <button type="submit" class="button button-primary">Scan All Competitors Now</button>
            </form>
        <?php endif; ?>
    </div>
    <?php
}

// ── Monitors Page ──
function pry_monitor_monitors_page() {
    $monitors = pry_monitor_api_get('/v1/monitors');
    $data = $monitors['data']['monitors'] ?? [];
    ?>
    <div class="wrap">
        <h1>Content Monitors</h1>
        <?php if (empty($data)): ?>
            <p>No monitors configured. Create one from the API or add competitors first.</p>
        <?php else: ?>
            <table class="pry-monitor-table">
                <thead><tr><th>Name</th><th>URL</th><th>Status</th><th>Checks</th><th>Changes</th><th>Last Run</th></tr></thead>
                <tbody>
                    <?php foreach ($data as $m): ?>
                        <tr>
                            <td><strong><?php echo esc_html($m['name'] ?? 'Unnamed'); ?></strong></td>
                            <td><?php echo esc_html(substr($m['target_url'] ?? '', 0, 50)); ?></td>
                            <td><span class="pry-status-<?php echo esc_attr($m['status'] ?? 'active'); ?>"><?php echo esc_html($m['status'] ?? 'unknown'); ?></span></td>
                            <td><?php echo esc_html($m['total_checks'] ?? 0); ?></td>
                            <td><?php echo esc_html($m['total_changes'] ?? 0); ?></td>
                            <td><?php echo esc_html(substr($m['last_run_at'] ?? 'Never', 0, 16)); ?></td>
                        </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        <?php endif; ?>
    </div>
    <?php
}

// ── Settings Page ──
function pry_monitor_settings_page() {
    if (isset($_POST['save_settings']) && check_admin_referer('pry_save_settings')) {
        update_option('pry_api_url', esc_url_raw($_POST['pry_api_url']));
        update_option('pry_api_key', sanitize_text_field($_POST['pry_api_key']));
        update_option('pry_check_interval', intval($_POST['pry_check_interval']));
        echo '<div class="notice notice-success"><p>Settings saved!</p></div>';
    }
    ?>
    <div class="wrap">
        <h1>Pry Monitor Settings</h1>
        <form method="post" style="background:#fff;padding:20px;border:1px solid #ccd0d4;max-width:600px;">
            <?php wp_nonce_field('pry_save_settings'); ?>
            <div class="pry-form-field">
                <label for="pry_api_url">Pry Server URL</label>
                <input type="url" name="pry_api_url" id="pry_api_url" value="<?php echo esc_attr(get_option('pry_api_url', 'http://localhost:8002')); ?>" />
                <p class="description">Your Pry server instance URL.</p>
            </div>
            <div class="pry-form-field">
                <label for="pry_api_key">API Key</label>
                <input type="text" name="pry_api_key" id="pry_api_key" value="<?php echo esc_attr(get_option('pry_api_key', '')); ?>" />
                <p class="description">Leave empty if authentication is disabled.</p>
            </div>
            <div class="pry-form-field">
                <label for="pry_check_interval">Check Interval (minutes)</label>
                <input type="number" name="pry_check_interval" id="pry_check_interval" value="<?php echo esc_attr(get_option('pry_check_interval', 60)); ?>" min="15" max="1440" />
                <p class="description">How often to check competitors for changes.</p>
            </div>
            <p><button type="submit" name="save_settings" class="button button-primary">Save Settings</button></p>
        </form>

        <!-- Referral Section -->
        <h2 style="margin-top:30px;">Recommended Services</h2>
        <p style="color:#666;">Pry uses these services. Signing up through these links helps support development.</p>
        <table class="pry-monitor-table" style="margin-top:15px;">
            <thead><tr><th>Service</th><th>Category</th><th>Commission</th><th>Action</th></tr></thead>
            <tbody>
                <tr>
                    <td><strong>OpenAI</strong></td>
                    <td>LLM / AI</td>
                    <td>20% first 6 months</td>
                    <td><a href="https://platform.openai.com/signup?via=pry" target="_blank" rel="noopener" class="button button-small">Sign Up →</a></td>
                </tr>
                <tr>
                    <td><strong>Anthropic Claude</strong></td>
                    <td>LLM / AI</td>
                    <td>Enterprise referrals</td>
                    <td><a href="https://console.anthropic.com/?ref=pry" target="_blank" rel="noopener" class="button button-small">Sign Up →</a></td>
                </tr>
                <tr>
                    <td><strong>OpenRouter</strong></td>
                    <td>LLM Aggregator</td>
                    <td>$1/signup + usage share</td>
                    <td><a href="https://openrouter.ai/?ref=pry" target="_blank" rel="noopener" class="button button-small">Sign Up →</a></td>
                </tr>
                <tr>
                    <td><strong>ElevenLabs</strong></td>
                    <td>Voice AI</td>
                    <td>22% recurring</td>
                    <td><a href="https://elevenlabs.io/?ref=pry" target="_blank" rel="noopener" class="button button-small">Sign Up →</a></td>
                </tr>
                <tr>
                    <td><strong>Bright Data</strong></td>
                    <td>Proxies</td>
                    <td>$2-$50/signup</td>
                    <td><a href="https://brightdata.com/?ref=pry" target="_blank" rel="noopener" class="button button-small">Sign Up →</a></td>
                </tr>
                <tr>
                    <td><strong>Capsolver</strong></td>
                    <td>CAPTCHA Solving</td>
                    <td>20% recurring lifetime</td>
                    <td><a href="https://capsolver.com/?ref=pry" target="_blank" rel="noopener" class="button button-small">Sign Up →</a></td>
                </tr>
                <tr>
                    <td><strong>Sentry</strong></td>
                    <td>Error Monitoring</td>
                    <td>$100-$1,000</td>
                    <td><a href="https://sentry.io/?ref=pry" target="_blank" rel="noopener" class="button button-small">Sign Up →</a></td>
                </tr>
                <tr>
                    <td><strong>Resend</strong></td>
                    <td>Transactional Email</td>
                    <td>$20/signup</td>
                    <td><a href="https://resend.com/?ref=pry" target="_blank" rel="noopener" class="button button-small">Sign Up →</a></td>
                </tr>
                <tr>
                    <td><strong>Hetzner</strong></td>
                    <td>Cloud Hosting</td>
                    <td>€25/signup + 10%</td>
                    <td><a href="https://hetzner.com/?ref=pry" target="_blank" rel="noopener" class="button button-small">Sign Up →</a></td>
                </tr>
                <tr>
                    <td><strong>DigitalOcean</strong></td>
                    <td>Cloud Hosting</td>
                    <td>$25/paid referral</td>
                    <td><a href="https://m.do.co/c/pry" target="_blank" rel="noopener" class="button button-small">Sign Up →</a></td>
                </tr>
            </tbody>
        </table>
        <p style="font-size:11px;color:#999;margin-top:10px;">These are affiliate links. Pry earns a commission when you sign up through them.</p>
    </div>
    <?php
}

// ── WooCommerce Sync Page ──
function pry_monitor_woo_page() {
    if (!class_exists('WooCommerce')) {
        echo '<div class="wrap"><h1>WooCommerce Sync</h1><div class="notice notice-warning"><p>WooCommerce is not installed. Install or activate WooCommerce to use product sync features.</p></div></div>';
        return;
    }
    ?>
    <div class="wrap">
        <h1>WooCommerce Product Sync</h1>
        <p>Import competitor products directly into your WooCommerce store. Map fields from competitor data to WooCommerce product fields.</p>
        <form method="post" style="background:#fff;padding:20px;border:1px solid #ccd0d4;max-width:600px;">
            <?php wp_nonce_field('pry_woo_import'); ?>
            <div class="pry-form-field">
                <label for="import_url">Competitor Product URL</label>
                <input type="url" name="import_url" id="import_url" required placeholder="https://competitor.com/product/123" />
            </div>
            <div class="pry-form-field">
                <label>Category</label>
                <?php wp_dropdown_categories(['taxonomy' => 'product_cat', 'name' => 'product_cat', 'hide_empty' => false]); ?>
            </div>
            <p><button type="submit" name="import_product" class="button button-primary">Import Product</button></p>
        </form>
    </div>
    <?php
}

// ── Proxy Page ──
function pry_monitor_proxy_page() {
    $providers = array(
        array('name' => 'Bright Data', 'tag' => 'brightdata', 'url' => 'https://brightdata.com/?ref=pry',
              'commission' => '$2-$50/signup, 10% recurring', 'trial' => '$5 free credit', 'best' => true),
        array('name' => 'Smartproxy', 'tag' => 'smartproxy', 'url' => 'https://smartproxy.com/?ref=pry',
              'commission' => '20% recurring lifetime', 'trial' => '100MB free'),
        array('name' => 'Oxylabs', 'tag' => 'oxylabs', 'url' => 'https://oxylabs.io/?ref=pry',
              'commission' => '10-30% recurring', 'trial' => '5K requests free'),
        array('name' => 'IPRoyal', 'tag' => 'iproyal', 'url' => 'https://iproyal.com/?ref=pry',
              'commission' => '30% recurring lifetime', 'trial' => 'None'),
        array('name' => 'Webshare', 'tag' => 'webshare', 'url' => 'https://www.webshare.io/?ref=pry',
              'commission' => '30% recurring lifetime', 'trial' => '10 free proxies'),
        array('name' => 'Proxy-Seller', 'tag' => 'proxyseller', 'url' => 'https://proxy-seller.com/?ref=pry',
              'commission' => '30% recurring', 'trial' => 'None'),
        array('name' => 'NetNut', 'tag' => 'netnut', 'url' => 'https://netnut.io/?ref=pry',
              'commission' => 'Partner program', 'trial' => '7 days free'),
        array('name' => 'PacketStream', 'tag' => 'packetstream', 'url' => 'https://packetstream.io/?ref=pry',
              'commission' => '20% revenue share', 'trial' => 'Pay-as-you-go'),
    );
    ?>
    <div class="wrap">
        <h1>Proxy Settings</h1>
        <div class="pry-section">
            <h2>Free Proxy (Default)</h2>
            <p>Pry uses Tor and public rotating proxies by default. These work for most sites but may be blocked by aggressive anti-bot systems.</p>
            <p><strong>Status:</strong> Active | <strong>Cost:</strong> Free</p>
        </div>
        <div class="pry-section">
            <h2>Premium Proxies (Recommended for Blocked Sites)</h2>
            <p style="color:#666;">When Pry encounters anti-bot blocks, it can automatically recommend a premium proxy. Sign up through these links to support Pry (affiliate).</p>
            <table class="pry-monitor-table">
                <thead>
                    <tr><th>Provider</th><th>Commission</th><th>Free Trial</th><th>Action</th></tr>
                </thead>
                <tbody>
                    <?php foreach ($providers as $p): ?>
                    <tr <?php echo isset($p['best']) ? 'style="background:#fef9e7;"' : ''; ?>>
                        <td>
                            <strong><?php echo esc_html($p['name']); ?></strong>
                            <?php if (isset($p['best'])) echo ' <span style="background:#f59e0b;color:#000;padding:2px 6px;border-radius:3px;font-size:11px;">RECOMMENDED</span>'; ?>
                        </td>
                        <td><?php echo esc_html($p['commission']); ?></td>
                        <td><?php echo esc_html($p['trial']); ?></td>
                        <td>
                            <a href="<?php echo esc_url($p['url']); ?>" target="_blank" rel="noopener" class="button button-primary">Sign Up &rarr;</a>
                        </td>
                    </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
            <p style="font-size:11px;color:#999;margin-top:10px;">After signing up, enter your proxy credentials in <a href="<?php echo admin_url('admin.php?page=pry-monitor&tab=settings'); ?>">Settings</a>.</p>
        </div>
    </div>
    <?php
}

// ── Bulk Scan Handler ──
add_action('admin_post_pry_bulk_scan_competitors', 'pry_bulk_scan_handler');
function pry_bulk_scan_handler() {
    if (!wp_verify_nonce($_POST['_wpnonce'], 'pry_bulk_scan')) {
        wp_die('Security check failed');
    }
    $competitors = get_option('pry_competitors', []);
    $results = [];
    foreach ($competitors as $comp) {
        $result = pry_monitor_api_post('/v1/compliance/check', ['url' => $comp['url']]);
        $results[] = ['name' => $comp['name'], 'result' => $result];
    }
    set_transient('pry_scan_results', $results, 300);
    wp_redirect(admin_url('admin.php?page=pry-monitor&scan=complete'));
    exit;
}

// ── WooCommerce Import Handler ──
add_action('admin_post_pry_woo_import', 'pry_woo_import_handler');
function pry_woo_import_handler() {
    if (!wp_verify_nonce($_POST['_wpnonce'], 'pry_woo_import') || !class_exists('WooCommerce')) {
        wp_die('Security check failed or WooCommerce not active');
    }
    $url = esc_url_raw($_POST['import_url']);
    $cat = intval($_POST['product_cat'] ?? 0);

    // Scrape the product
    $scrape_result = pry_monitor_api_post('/v1/scrape', ['url' => $url]);
    if (!isset($scrape_result['success']) || !$scrape_result['success']) {
        set_transient('pry_woo_error', 'Failed to scrape URL: ' . ($scrape_result['error'] ?? 'unknown'), 60);
        wp_redirect(admin_url('admin.php?page=pry-monitor-woo'));
        exit;
    }

    $content = $scrape_result['data']['content'] ?? '';
    $title = $scrape_result['data']['title'] ?? 'Imported Product';

    // Create WooCommerce product
    $product = new WC_Product_Simple();
    $product->set_name($title . ' (Competitor)');
    $product->set_description(wp_trim_words($content, 100));
    $product->set_regular_price(0); // Mark as competitor reference
    $product->set_catalog_visibility('hidden'); // Don't show in catalog
    if ($cat) {
        $product->set_category_ids([$cat]);
    }
    $product_id = $product->save();

    if ($product_id) {
        set_transient('pry_woo_success', "Product imported with ID: $product_id", 60);
    }
    wp_redirect(admin_url('admin.php?page=pry-monitor-woo'));
    exit;
}

// ── API Helpers ──
function pry_monitor_api_get($endpoint) {
    $url = PRY_MONITOR_API_URL . $endpoint;
    $args = ['headers' => ['Content-Type' => 'application/json'], 'timeout' => 30];
    if (PRY_MONITOR_API_KEY) {
        $args['headers']['Authorization'] = 'Bearer ' . PRY_MONITOR_API_KEY;
    }
    $response = wp_remote_get($url, $args);
    if (is_wp_error($response)) {
        return ['success' => false, 'error' => $response->get_error_message()];
    }
    return json_decode(wp_remote_retrieve_body($response), true) ?: ['success' => false, 'error' => 'Invalid response'];
}

function pry_monitor_api_post($endpoint, $data) {
    $url = PRY_MONITOR_API_URL . $endpoint;
    $args = [
        'headers' => ['Content-Type' => 'application/json'],
        'body' => json_encode($data),
        'timeout' => 60,
    ];
    if (PRY_MONITOR_API_KEY) {
        $args['headers']['Authorization'] = 'Bearer ' . PRY_MONITOR_API_KEY;
    }
    $response = wp_remote_post($url, $args);
    if (is_wp_error($response)) {
        return ['success' => false, 'error' => $response->get_error_message()];
    }
    return json_decode(wp_remote_retrieve_body($response), true) ?: ['success' => false, 'error' => 'Invalid response'];
}

// ── Cron: Scheduled competitor checks ──
add_action('pry_hourly_check', 'pry_run_scheduled_checks');
function pry_run_scheduled_checks() {
    $competitors = get_option('pry_competitors', []);
    foreach ($competitors as $comp) {
        $result = pry_monitor_api_post('/v1/freshness/check', ['url' => $comp['url'], 'content' => '']);
        if (isset($result['data']['changed']) && $result['data']['changed']) {
            // Content changed — send notification to site admin
            $message = "Competitor {$comp['name']} changed content: {$comp['url']}";
            wp_mail(get_option('admin_email'), 'Pry Monitor: Content Change Detected', $message);
        }
    }
}

register_activation_hook(__FILE__, 'pry_monitor_activate');
function pry_monitor_activate() {
    if (!wp_next_scheduled('pry_hourly_check')) {
        wp_schedule_event(time(), 'hourly', 'pry_hourly_check');
    }
    update_option('pry_api_url', 'http://localhost:8002');
    update_option('pry_check_interval', 60);
}

register_deactivation_hook(__FILE__, 'pry_monitor_deactivate');
function pry_monitor_deactivate() {
    wp_clear_scheduled_hook('pry_hourly_check');
}
