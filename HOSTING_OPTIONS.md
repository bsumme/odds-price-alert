# Hosting Options for Arbitrage Bet Finder

This guide covers options for hosting your FastAPI application online so it can be accessed from anywhere, including your iPhone.

## Quick Comparison

| Platform | Free Tier | Ease of Setup | Best For |
|----------|-----------|---------------|----------|
| **Railway** | ✅ Yes | ⭐⭐⭐⭐⭐ Very Easy | Quick deployment, auto-deploy from GitHub |
| **Render** | ✅ Yes | ⭐⭐⭐⭐ Easy | Simple web services, good free tier |
| **Fly.io** | ✅ Yes | ⭐⭐⭐ Moderate | Global edge deployment, fast |
| **PythonAnywhere** | ✅ Limited | ⭐⭐⭐⭐ Easy | Python-focused, beginner-friendly |
| **Replit** | ✅ Yes | ⭐⭐⭐⭐⭐ Very Easy | In-browser IDE + hosting |
| **Heroku** | ❌ No | ⭐⭐⭐ Moderate | Well-known, but no free tier anymore |

## Recommended: Railway (Easiest)

### Why Railway?
- ✅ Free tier with $5 credit/month
- ✅ Auto-deploys from GitHub
- ✅ Zero configuration needed
- ✅ Automatic HTTPS
- ✅ Works great with FastAPI

### Setup Steps:

1. **Create Railway Account**
   - Go to https://railway.app
   - Sign up with GitHub

2. **Create New Project**
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Connect your repository

3. **Configure Build**
   - Railway auto-detects Python projects
   - It will look for `requirements.txt` or `Pipfile`
   - Create a `requirements.txt` if you don't have one:
     ```
     fastapi
     uvicorn[standard]
     requests
     pydantic
     ```

4. **Set Environment Variables**
   - In Railway dashboard, go to "Variables"
   - Add: `THE_ODDS_API_KEY=your_api_key_here`

5. **Deploy**
   - Railway will automatically deploy
   - You'll get a URL like: `https://your-app.railway.app`

6. **Access from iPhone**
   - Open Safari on iPhone
   - Go to: `https://your-app.railway.app/ArbritrageBetFinder.html`

### Railway Configuration Files

Create these files in your repo root:

**`railway.json`** (optional):
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "uvicorn main:app --host 0.0.0.0 --port $PORT",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

**`Procfile`** (alternative):
```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Alternative: Render

### Setup Steps:

1. **Create Account**
   - Go to https://render.com
   - Sign up with GitHub

2. **Create New Web Service**
   - Click "New +" → "Web Service"
   - Connect your GitHub repository

3. **Configure Service**
   - **Name:** arbitrage-bet-finder
   - **Environment:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`

4. **Set Environment Variables**
   - Add: `THE_ODDS_API_KEY`

5. **Deploy**
   - Render will build and deploy
   - Free tier: spins down after 15 min of inactivity (wakes up on next request)

6. **Access**
   - URL: `https://your-app.onrender.com/ArbritrageBetFinder.html`

## Alternative: Fly.io

### Setup Steps:

1. **Install Fly CLI**
   ```powershell
   # Windows (PowerShell)
   iwr https://fly.io/install.ps1 -useb | iex
   ```

2. **Create Account**
   ```powershell
   fly auth signup
   ```

3. **Initialize App**
   ```powershell
   fly launch
   ```
   - Follow prompts
   - Creates `fly.toml` config file

4. **Configure `fly.toml`**
   ```toml
   app = "your-app-name"
   primary_region = "iad"  # or closest to you
   
   [build]
   
   [http_service]
     internal_port = 8000
     force_https = true
     auto_stop_machines = true
     auto_start_machines = true
     min_machines_running = 0
   
   [[vm]]
     memory_mb = 256
   ```

5. **Set Secrets**
   ```powershell
   fly secrets set THE_ODDS_API_KEY=your_key_here
   ```

6. **Deploy**
   ```powershell
   fly deploy
   ```

7. **Access**
   - URL: `https://your-app.fly.dev/ArbritrageBetFinder.html`

## Alternative: PythonAnywhere

### Setup Steps:

1. **Create Account**
   - Go to https://www.pythonanywhere.com
   - Free tier available (limited)

2. **Upload Files**
   - Use web interface or git clone
   - Upload your project files

3. **Configure Web App**
   - Go to "Web" tab
   - Create new web app
   - Select "Manual configuration" → Python 3.x
   - Set source code path

4. **Set Environment Variables**
   - In "Web" → "Environment variables"
   - Add: `THE_ODDS_API_KEY`

5. **Configure WSGI**
   - Edit WSGI file:
   ```python
   import sys
   path = '/home/yourusername/odds-price-alert'
   if path not in sys.path:
       sys.path.append(path)
   
   from main import app
   application = app
   ```

6. **Reload Web App**
   - Click "Reload" button
   - Access: `https://yourusername.pythonanywhere.com/ArbritrageBetFinder.html`

## Alternative: Replit

### Setup Steps:

1. **Create Repl**
   - Go to https://replit.com
   - Create new Repl → "Python"
   - Import from GitHub or upload files

2. **Configure**
   - Replit auto-detects FastAPI
   - Set environment variables in "Secrets" tab

3. **Run**
   - Click "Run"
   - Replit provides a public URL
   - Access: `https://your-repl-name.your-username.repl.co/ArbritrageBetFinder.html`

## Required Files for Hosting

### `requirements.txt`
Create this file in your repo root:
```
fastapi==0.104.1
uvicorn[standard]==0.24.0
requests==2.31.0
pydantic==2.5.0
python-multipart==0.0.6
```

### Update `main.py` for Production

You may need to update the server startup to use the `PORT` environment variable:

```python
import os

# At the end of main.py, if running directly:
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

Or use the command line (which most platforms do):
```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Security Considerations

⚠️ **Important for Production:**

1. **API Keys**: Never commit API keys to GitHub
   - Use environment variables
   - Add `.env` to `.gitignore`

2. **CORS**: If needed, configure CORS in FastAPI:
   ```python
   from fastapi.middleware.cors import CORSMiddleware
   
   app.add_middleware(
       CORSMiddleware,
       allow_origins=["*"],  # Or specific domains
       allow_credentials=True,
       allow_methods=["*"],
       allow_headers=["*"],
   )
   ```

3. **Rate Limiting**: Consider adding rate limiting for production

4. **HTTPS**: All platforms provide HTTPS automatically

## Quick Start Recommendation

**For fastest setup, use Railway:**
1. Push your code to GitHub
2. Sign up at railway.app
3. Connect GitHub repo
4. Add environment variable
5. Deploy (automatic)
6. Access from iPhone!

## Testing on iPhone

Once deployed, test on iPhone:
1. Open Safari
2. Go to your hosted URL
3. Should automatically redirect to mobile version
4. Add to Home Screen for app-like experience:
   - Tap Share button
   - "Add to Home Screen"

## Troubleshooting

### App not loading on iPhone
- Check HTTPS is enabled (required for some features)
- Verify CORS is configured if needed
- Check server logs in hosting platform dashboard

### Environment variables not working
- Ensure variables are set in hosting platform
- Restart/redeploy after adding variables
- Check variable names match exactly

### Static files not serving
- Verify `StaticFiles` mount in `main.py`
- Check file paths are correct
- Ensure files are in the repository


