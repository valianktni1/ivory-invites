# Ivory Invites pilot

The pilot includes two interactive public demos and a password-protected organiser workspace. The organiser can edit the invitation, set a photo and accent colour, create household links, and collect individual RSVPs, optional meal choices and a song request. Real replies and uploaded photos are stored in SQLite.

## Run on TrueNAS

1. Extract the archive into your apps dataset, for example `/mnt/apps/ivory-invites`. Open the TrueNAS shell as a user with permission to run Docker and set ownership on the data directory.
2. From the extracted folder, create the data directory and copy the example settings.

   ```sh
   cd /mnt/apps/ivory-invites
   install -d -m 0750 -o 10001 -g 10001 data
   cp -n .env.example .env
   chmod 600 .env
   ```

3. Edit `.env`. Set a strong, unique password of at least 16 characters. Use a password manager or generate a random value with `openssl rand -hex 24`. Port `30112` is the proposed host port. If it is occupied, choose a free port and use the same one in the proxy settings. To store data on a separate dataset, set `INVITES_DATA_PATH` to its absolute path and give UID/GID `10001:10001` write access there.
4. Start the app and check its status.

   ```sh
   docker compose up -d --build
   docker compose ps
   ```

5. In DNS, point `invites.ivorydigital.uk` at the same public proxy as the other Ivory apps. In Nginx Proxy Manager, add a proxy host for that name with scheme HTTP, forwarding to the TrueNAS LAN address and the host port from `.env`. Use an HTTPS certificate for the public address and enable Force SSL. Keep that address in `PUBLIC_ORIGIN`.
6. Open the public address to try the demos. Open `/editor` to sign in and create a test event. Use made-up guest details for the pilot. After a guest replies, reopen the event or refresh and select it to see the reply.

The app currently uses a single organiser password. Each generated household link can be opened and used to RSVP by whoever holds the link. Send each link to the intended household. Demo replies are discarded. Payment, the wedding planner connection and the occasion landing pages are separate milestones.

To back up, stop the app with `docker compose stop`, copy the data directory to your backup location, then run `docker compose start`. Uploaded photos are inside the same database. The database and data directory should have the same permissions after a restore.

## Run locally for development

Use Python 3.11 or newer with the system's time-zone database installed. For example, on Linux:

```sh
INVITES_PASSWORD="$(openssl rand -hex 24)" python3 app.py
```

For manual sign-in, generate and keep a password in your shell first, then start the app with that value. Open `http://localhost:30112`.
