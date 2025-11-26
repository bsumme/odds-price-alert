# Mobile Testing Guide

This guide explains how to test the mobile version of the Arbitrage Bet Finder using BlueStacks emulator or a physical mobile device.

## Prerequisites

- BlueStacks emulator installed on your PC, OR
- A physical mobile device on the same network as your PC
- The FastAPI server running

## Quick Start

### Method 1: Use the Testing Script (Recommended)

1. Run the testing script:
   ```powershell
   .\start_server_for_mobile_test.ps1
   ```

2. The script will:
   - Find your PC's local IP address automatically
   - Start the server accessible from BlueStacks/network
   - Display the exact URL to use in BlueStacks

3. In BlueStacks, open a browser and navigate to the URL shown (e.g., `http://192.168.1.100:8000/ArbritrageBetFinder.html`)

### Method 2: Manual Setup

1. **Find your PC's local IP address:**
   ```powershell
   ipconfig | findstr IPv4
   ```
   Look for an address like `192.168.x.x` or `10.x.x.x` (not `127.0.0.1`)

2. **Start the server with network access:**
   
   **Option A:** Modify `restart_server.ps1` line 120 to use `0.0.0.0`:
   ```powershell
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
   
   **Option B:** Run manually:
   ```powershell
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

3. **Access from BlueStacks:**
   - Open a browser in BlueStacks (Chrome, Firefox, etc.)
   - Navigate to: `http://YOUR_PC_IP:8000/ArbritrageBetFinder.html`
   - Replace `YOUR_PC_IP` with your PC's local IP (e.g., `http://192.168.1.100:8000/ArbritrageBetFinder.html`)

## What to Test

### ✅ Mobile Detection & Redirect
- Visiting the main page (`ArbritrageBetFinder.html`) should automatically redirect to the mobile version (`ArbritrageBetFinder-mobile.html`)
- The redirect happens based on:
  - User agent detection (mobile device strings)
  - Screen width (< 768px)
  - Touch capability detection

### ✅ Filter Panel
- Tap "Filters & Settings" button to expand/collapse the filter panel
- Verify all form controls are easily tappable
- Check that checkboxes, selects, and inputs work properly

### ✅ Card-Based Layout
- Results should display as cards instead of a table
- Each card should show:
  - Header with sport badge and arbitrage margin badge
  - Recommended bet section with team logo, description, odds
  - Compare price section
  - Hedge bet section (when available)
  - Footer with start time

### ✅ Touch Optimization
- All buttons should be at least 44x44px (easy to tap)
- Inputs should be large enough (16px font to prevent iOS zoom)
- Checkboxes should be easily tappable
- Adequate spacing between interactive elements

### ✅ Watcher Panel (Bottom Sheet)
- Tap the 🔔 bell icon in the header to open the watcher panel
- Panel should slide up from the bottom
- Swipe down on the panel to close it
- Tap the overlay or close button (✕) to close
- Verify all watcher functionality works (start/stop, SMS test, etc.)

### ✅ Pull-to-Refresh
- Pull down on the results section to refresh
- Should trigger a new search for arbitrage opportunities

### ✅ Form Inputs
- Inputs should not cause page zoom on focus (iOS)
- All inputs should be easily tappable
- Form selections should persist (localStorage)

### ✅ Navigation
- Test all buttons and interactions
- Verify smooth navigation between pages
- Check that the "Bet Watcher" link works

### ✅ Responsive Design
- Test in both portrait and landscape orientations
- Verify safe area support (notches, home indicators)
- Check that content doesn't overflow

## Troubleshooting

### Can't Connect from BlueStacks

**Problem:** BlueStacks browser can't reach the server

**Solutions:**
1. **Ensure both devices are on the same Wi-Fi network**
   - PC and BlueStacks must be on the same network

2. **Check Windows Firewall**
   - Windows Firewall may be blocking port 8000
   - Run this PowerShell command to allow it:
     ```powershell
     New-NetFirewallRule -DisplayName "Allow FastAPI Port 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
     ```

3. **Verify server is running on 0.0.0.0**
   - Server must bind to `0.0.0.0`, not `127.0.0.1`
   - `127.0.0.1` only accepts local connections
   - `0.0.0.0` accepts connections from the network

4. **Check server is actually running**
   - Look for the server output showing it's listening
   - Try accessing `http://127.0.0.1:8000` from your PC's browser first

### Mobile Detection Not Working

**Problem:** Not redirecting to mobile version

**Solutions:**
1. **Clear browser cache** in BlueStacks
2. **Check user agent** - Mobile detection uses user agent strings
3. **Manually navigate** to `/ArbritrageBetFinder-mobile.html` to test the mobile UI directly

### Firewall Issues

**Problem:** Windows Firewall blocking connections

**Solution:** Allow port 8000 through firewall:
```powershell
# Allow inbound connections on port 8000
New-NetFirewallRule -DisplayName "Allow FastAPI Port 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow

# To remove the rule later (if needed):
# Remove-NetFirewallRule -DisplayName "Allow FastAPI Port 8000"
```

## Testing on Physical Mobile Device

The same process works for physical mobile devices:

1. Ensure your phone/tablet is on the same Wi-Fi network as your PC
2. Start the server with `--host 0.0.0.0`
3. Find your PC's IP address
4. Open a browser on your mobile device
5. Navigate to `http://YOUR_PC_IP:8000/ArbritrageBetFinder.html`

## Server Configuration

### Default Configuration
- **Host:** `127.0.0.1` (localhost only)
- **Port:** `8000`
- **Access:** Only from the same machine

### Network-Accessible Configuration
- **Host:** `0.0.0.0` (all network interfaces)
- **Port:** `8000`
- **Access:** From any device on the same network

### Security Note
⚠️ **Warning:** Running the server on `0.0.0.0` makes it accessible to anyone on your local network. Only use this for testing on a trusted network. For production, use proper authentication and security measures.

## Files Reference

- **Desktop version:** `frontend/ArbritrageBetFinder.html`
- **Mobile version:** `frontend/ArbritrageBetFinder-mobile.html`
- **Testing script:** `start_server_for_mobile_test.ps1`
- **Server script:** `restart_server.ps1`

## Quick Commands Reference

```powershell
# Find your IP address
ipconfig | findstr IPv4

# Start server for mobile testing
.\start_server_for_mobile_test.ps1

# Start server manually with network access
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Allow firewall port (run as Administrator)
New-NetFirewallRule -DisplayName "Allow FastAPI Port 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```


