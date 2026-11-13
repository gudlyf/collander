# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub's **Report a vulnerability** button (Security → Advisories) rather than in a public issue. Include steps to reproduce and the version or commit you tested. You should hear back within a week.

## Deployment notes

Collander is designed for a single household on a private network.

- Put it behind HTTPS (a reverse proxy such as Caddy, Traefik or nginx) if it's reachable from the internet, and set `COLLANDER_SECURE_COOKIES=true`.
- Use a strong password. Failed sign-ins are rate-limited, but that is not a substitute for a good password.
- API keys entered on the Settings page are stored in the database inside your data volume. To keep them out of the database, set them as environment variables instead.
- The link importer fetches pages your server can reach (LAN addresses included, link-local/metadata addresses excluded). Only signed-in users can trigger it.
