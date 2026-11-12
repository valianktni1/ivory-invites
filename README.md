# Ivory Invites pilot

The pilot includes two interactive public demos and a password-protected organiser workspace. The organiser can edit the invitation, set a photo and accent colour, create household links, and collect individual RSVPs, optional meal choices and a song request. Real replies and uploaded photos are stored in SQLite.

## Run on TrueNAS

| Purpose | TrueNAS path |
| --- | --- |
| Git checkout and local deployment settings | `/mnt/apps/invites-ivorydigital` |
| SQLite database, uploaded photos and RSVP replies | `/mnt/photographers_data/invites-ivoryclient` |

1. In the TrueNAS shell, clone the private repository into the existing app dataset. This command expects the app dataset to be empty. If it already contains this checkout, run `git pull --ff-only` from that directory.

   ```sh
   git clone https://github.com/valianktni1/ivory-invites.git /mnt/apps/invites-ivorydigital
   cd /mnt/apps/invites-ivorydigital
   ```

2. Give the container's UID and GID `10001:10001` write access to the client-data dataset. For a new, empty dataset with standard Unix permissions, run the following as root.

   ```sh
   test -d /mnt/photographers_data/invites-ivoryclient &&
     chown 10001:10001 /mnt/photographers_data/invites-ivoryclient
   ```

3. Copy the example settings if this is a fresh install. The example contains the public URL, port `30012` and the separate client-data path.

   ```sh
   cp -n .env.example .env
   chmod 600 .env
   ```

   Edit `.env` and set a strong, unique `INVITES_PASSWORD` of at least 16 characters. On an existing checkout, check that `INVITES_PORT=30012`, `PUBLIC_ORIGIN=https://invites.ivorydigital.uk` and `INVITES_DATA_PATH=/mnt/photographers_data/invites-ivoryclient` are set in `.env`. If an earlier pilot already has data, stop it and copy its database files into the new dataset before switching the mount. Keep the original copy until you verify the data in the app.

4. Validate the configuration, build the app and check that the container starts.

   ```sh
   docker compose config --quiet &&
     docker compose up -d --build &&
     docker compose ps
   ```

5. The existing Nginx Proxy Manager host for `invites.ivorydigital.uk` should forward HTTP to the TrueNAS LAN address on port `30012` and serve HTTPS to visitors. Check `https://invites.ivorydigital.uk/health` for a successful response, then visit `/editor` to create a test event. After a guest replies, reopen the event or refresh and select it to see the reply.

The app currently uses a single organiser password. Each generated household link can be opened and used to RSVP by whoever holds the link. Send each link to the intended household. Demo replies are discarded. Payment, the wedding planner connection and the occasion landing pages are separate milestones.

To back up, stop the app with `docker compose stop`, copy `/mnt/photographers_data/invites-ivoryclient` to your backup location, then run `docker compose start`. Uploaded photos are inside the same database. The database and data directory should have the same permissions after a restore.

## Run locally for development

Use Python 3.11 or newer with the system's time-zone database installed. For example, on Linux:

```sh
INVITES_PASSWORD="$(openssl rand -hex 24)" python3 app.py
```

For manual sign-in, generate and keep a password in your shell first, then start the app with that value. Open `http://localhost:30112`.
