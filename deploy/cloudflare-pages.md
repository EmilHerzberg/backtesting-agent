# Cloudflare Pages Deployment (Frontend only)

Alternative zu Docker: Frontend direkt auf Cloudflare Pages deployen.

## Setup in Cloudflare Dashboard

1. Gehe zu dash.cloudflare.com → Workers & Pages → Create
2. Connect to Git → Waehle dein GitHub Repo
3. Build Settings:
   - Framework preset: Next.js
   - Root directory: `frontend`
   - Build command: `npm run build`
   - Build output directory: `.next`
4. Environment Variables (im Dashboard setzen):
   - `NEXT_PUBLIC_API_URL` = `https://api.deine-domain.com`
   - `NODE_VERSION` = `22`

## Bei jedem Push wird automatisch deployed.
