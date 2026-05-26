# Instagram MCP Server

MCP server para publicar en Instagram desde Claude Desktop.

## Herramientas disponibles

| Herramienta | Descripción |
|---|---|
| `scrape_website` | Extrae contenido de una URL |
| `publish_instagram_post` | Publica un post de texto en Instagram |
| `publish_instagram_post_with_image` | Publica un post con imagen (URL pública) |
| `publish_instagram_reel` | Publica un Reel desde una URL pública de vídeo MP4 |
| `get_instagram_account_info` | Info de la cuenta: seguidores, bio, etc. |
| `get_recent_posts` | Últimos posts publicados |

## Deploy seguro

El deploy usa Secret Manager. No pasa `IG_ACCESS_TOKEN` ni `MCP_API_KEY` con `--set-env-vars`.

Primera configuración o rotación de secretos:

```bash
export PROJECT_ID="tu-gcp-project"
export IG_USER_ID="17841470871082749"
read -rsp "IG_ACCESS_TOKEN: " IG_ACCESS_TOKEN; export IG_ACCESS_TOKEN; echo
read -rsp "MCP_API_KEY: " MCP_API_KEY; export MCP_API_KEY; echo

bash deploy.sh --setup-secrets
```

Usar `read -rsp` evita escribir secretos reales en el historial de shell.

Deploys posteriores:

```bash
export PROJECT_ID="tu-gcp-project"
export IG_USER_ID="17841470871082749"

bash deploy.sh
```

El servicio Cloud Run recibe:

- `IG_ACCESS_TOKEN` desde Secret Manager: `instagram-mcp-ig-access-token`
- `MCP_API_KEY` desde Secret Manager: `instagram-mcp-api-key`
- `IG_USER_ID` como variable no secreta

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

Actualiza Secret Manager y fuerza una nueva revisión de Cloud Run:

```bash
export PROJECT_ID="instagram-mcp-prod"
export REGION="europe-west1"
./scripts/update_ig_token.sh
```

El script usa `read -rsp`, añade una nueva versión del secreto `IG_ACCESS_TOKEN` y ejecuta `gcloud run services update --update-secrets` para que Cloud Run cargue `latest`. No pegues tokens en el chat ni uses `--update-env-vars IG_ACCESS_TOKEN=...`.


## Publicar Reels

El vídeo debe estar disponible mediante una URL pública accesible por Instagram Graph API.

Herramienta MCP:

```json
{
  "caption": "Texto del reel + hashtags",
  "video_url": "https://storage.googleapis.com/.../reel.mp4",
  "share_to_feed": true
}
```

La herramienta crea el contenedor `media_type=REELS`, espera a que el procesamiento termine y llama a `media_publish`.
