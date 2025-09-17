# ElevenLabs + Google Calendar MCP Setup

## Deployment to Railway

### 1. GitHub Repository
- Repository: `MCP-Google-Calendar-Elevenlabs`
- Description: Google Calendar MCP Server for ElevenLabs voice integration

### 2. Railway Deployment
1. Go to [Railway.app](https://railway.app)
2. Sign in with GitHub
3. Click "New Project" → "Deploy from GitHub repo"
4. Select `MCP-Google-Calendar-Elevenlabs`
5. Railway will auto-detect Node.js

### 3. Environment Variables in Railway
Add these in Railway dashboard:

```
GOOGLE_OAUTH_CREDENTIALS={"installed":{"client_id":"YOUR_CLIENT_ID","client_secret":"YOUR_CLIENT_SECRET","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","redirect_uris":["http://localhost"]}}
GOOGLE_CALENDAR_ID=roelof@elvison.com
MCP_SERVER_NAME=dental-calendar
DEBUG=false
```

### 4. ElevenLabs Configuration
- **Server type:** Streamable HTTP
- **Server URL:** `https://your-railway-url.up.railway.app`
- **Headers:** 
  - Accept: application/json
  - Accept: text/event-stream
- **Tools:** Enable all 6 MCP tools

### 5. Test
- Health check: `https://your-railway-url.up.railway.app/health`
- Should return: `{"status":"healthy","server":"google-calendar-mcp"}`
