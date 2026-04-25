# Tailscale iPhone Setup Guide for Elijah

This guide fixes the connection problem between your Linux Mint live USB (Madam‑Mary) and your iPhone.

## 1. Prepare the Linux side
1. Open a terminal on Madam‑Mary.
2. **Reset any cached Tailscale auth data** so the next login generates a fresh URL.

```bash
# Stop the Tailscale service
sudo systemctl stop tailscaled

# Remove the local auth cache (keys, auth URL, and state)
sudo rm -rf /var/lib/tailscale/*

# Start the service again
sudo systemctl start tailscaled
```

3. **Generate a new auth URL** (you’ll copy this to the iPhone):

```bash
sudo tailscale up --login-server="https://login.tailscale.com"
```

   The command will output a URL like `https://login.tailscale.com/a/<token>`. Keep this handy.

## 2. Prepare the iPhone
1. **Install the Tailscale app** from the App Store if it isn’t already installed.
2. **Log out of any existing Tailscale session**:
   - Open the Tailscale app.
   - Tap the profile icon (top‑right).
   - Choose **Log out**.
3. **Clear any cached auth URLs**:
   - In iOS Settings → Tailscale → Reset Network Settings (if present), or simply uninstall and reinstall the app to guarantee a clean slate.

## 3. Connect the iPhone
1. Open the Tailscale app on the iPhone.
2. Tap **Log in**.
3. When prompted to paste an auth URL, **paste the URL you copied from step 1‑3** on the Linux side.
4. Accept the permission prompts. The iPhone should now appear in your Tailscale network alongside Madam‑Mary.

## 4. Verify the connection
Back on Linux, run:

```bash
tailscale status
```

You should see the iPhone listed with its device name and an “online” state.

## 5. Optional: Make the login URL reusable
If you want a permanent shortcut, create a small script that generates the URL and copies it to the clipboard:

```bash
#!/usr/bin/env bash
# tailscale-login-url.sh – generate a fresh auth URL and copy to clipboard

# Ensure tailscaled is running
sudo systemctl start tailscaled

# Generate URL
URL=$(sudo tailscale up --login-server="https://login.tailscale.com" 2>&1 | grep -o 'https://[^ ]*')
echo "Auth URL: $URL"

# Copy to clipboard (requires xclip)
echo -n "$URL" | xclip -selection clipboard
echo "URL copied to clipboard."
```

Make it executable:

```bash
chmod +x ~/scripts/tailscale-login-url.sh
```

Run it whenever you need a fresh login link.

---  
**Why this fix?**  
- Clears stale auth data that can prevent a new device from joining.  
- Gives you a fresh, single‑use URL that the iPhone can accept.  
- Provides a repeatable script for future device additions.  

Follow the steps above, and your iPhone should connect to the same Tailscale network as your Linux Mint machine.  
---  

**Next actions you might want**  
- Run the reset commands now (you’ll need a separate terminal for `sudo`).  
- Install the app on the iPhone and follow the login steps.  
- Use the script to generate future login URLs quickly.

Feel free to ask for any part of this to be executed or refined.  