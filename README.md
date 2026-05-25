# Instagram MCP Server

MCP server para publicar en Instagram desde Claude Desktop.

## Herramientas disponibles

| Herramienta | Descripción |
|---|---|
| `scrape_website` | Extrae contenido de una URL |
| `publish_instagram_post` | Publica un post de texto en Instagram |
| `publish_instagram_post_with_image` | Publica un post con imagen (URL pública) |
| `get_instagram_account_info` | Info de la cuenta: seguidores, bio, etc. |
| `get_recent_posts` | Últimos posts publicados |

## Deploy

```bash
export PROJECT_ID="tu-gcp-project"
export IG_ACCESS_TOKEN="tu-token-60-dias"
export IG_USER_ID="17841470871082749"

bash deploy.sh
```

## Configurar en Claude Desktop

Edita `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "instagram-mcp": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://instagram-mcp-XXXX-uc.a.run.app/mcp"
      ]
    }
  }
}
```

Reinicia Claude Desktop. Ya puedes decirle:

> "Mira tangibledata.xyz, genera un post en español con las novedades y publícalo en Instagram"

## Renovar el token (cada 60 días)

```bash
curl "https://graph.facebook.com/v19.0/oauth/access_token?\
grant_type=fb_exchange_token&\
client_id=2404791133365791&\
client_secret=TU_APP_SECRET&\
fb_exchange_token=TU_TOKEN_ACTUAL"
```

Actualiza la variable en Cloud Run:

```bash
gcloud run services update instagram-mcp \
  --region us-central1 \
  --update-env-vars IG_ACCESS_TOKEN=NUEVO_TOKEN \
  --project $PROJECT_ID
```
