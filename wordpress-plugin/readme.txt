=== Pry Monitor ===
Contributors: rugmunchmedia
Tags: competitor monitoring, price tracking, woocommerce, scraping, pry
Requires at least: 6.0
Tested up to: 6.6
Requires PHP: 8.0
Stable tag: 1.0.0
License: MIT
License URI: https://opensource.org/licenses/MIT

Track competitor prices and content changes from your WordPress dashboard, and sync imported products to WooCommerce.

== Description ==

Pry Monitor connects your WordPress site to a self-hosted Pry server. Add competitor
URLs, schedule recurring checks, receive change notifications by email, and import
competitor products into WooCommerce as draft products.

The plugin talks to the Pry API endpoint configured under **Pry Monitor → Settings**
(default `http://localhost:8002`). Nothing is sent to a third-party service.

== Installation ==

1. Upload the `pry-monitor` folder to `/wp-content/plugins/`.
2. Activate the plugin through the **Plugins** screen.
3. Open **Pry Monitor → Settings** and set the Pry Server URL (and API key if your
   Pry instance requires one).
4. Add competitors under **Pry Monitor → Competitors**.

== Frequently Asked Questions ==

= Does this plugin require a Pry server? =

Yes. Pry Monitor is a client for a Pry instance you run yourself.

= How often are competitors checked? =

The check interval is configurable in minutes (15–1440) under Settings. Changing the
value reschedules the background check immediately.

= Does it work without WooCommerce? =

Yes. Competitor tracking works on its own; WooCommerce is only used for product sync.

== Changelog ==

= 1.0.0 =
* Initial release.
