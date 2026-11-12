# Ivory Invites pilot

The pilot includes two interactive public demos and a workspace for each organiser account. Organisers can edit their invitations, create household links and collect RSVPs, meal choices and song requests. Invitations, uploaded photos and replies are stored in SQLite.

## Run on TrueNAS

| Purpose | TrueNAS path |
| --- | --- |
| Git checkout and local deployment settings | `/mnt/apps/invites-ivorydigital` |
| SQLite database, uploaded photos and RSVP replies | `/mnt/photographers_data/invites-ivoryclient` |

1. In the TrueNAS shell, clone the repository into the existing app dataset. This command expects the app dataset to be empty. If it already contains this checkout, run `git pull --ff-only` from that directory.

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

   On an existing checkout, keep the current `.env` with your public URL, port and client-data path. You can remove the old `INVITES_PASSWORD` line. Existing pilot invitations will be linked to the verified `INVITES_OWNER_EMAIL` account when it is created. The default is `admin@ivorydigital.uk`. Existing guest links and replies are carried over.

4. Create the app's private settings directory and start the container as root.

   ```sh
   install -d -m 0700 -o 10001 -g 10001 .settings
   docker compose config --quiet &&
     docker compose up -d --build &&
     docker compose ps
   ```

5. The existing Nginx Proxy Manager host for `invites.ivorydigital.uk` should forward HTTP to the TrueNAS LAN address on port `30012` and serve HTTPS to visitors. If you already have an owner login, sign in and open **Admin → SMTP settings**. For first-time setup or mail recovery, generate a one-time code on TrueNAS:

   ```sh
   docker compose exec -T invites python app.py mail-setup-code
   ```

   Open [SMTP setup](https://invites.ivorydigital.uk/admin/mail-setup), paste the code and enter your mailbox details. The code expires after 20 minutes or after a successful save. The form starts with the Hostinger SMTP server, SSL/TLS and port 465. Select **Verify and save**. SMTP settings are stored in the app dataset under `.settings`; the older `.smtp-password` file is no longer used.

6. At `/editor`, choose **Set up the owner account** if you have yet to create the owner login. Open the email link, enter the same email address and choose a password with at least eight characters and one special character.

## Invite and manage customers

Sign in as the configured owner and open **Admin**. Enter a customer's email address, select their access and choose **Send setup link**. The customer opens the email and sets their own password. Only the owner can send new customer setup links.

- **Free** gives wedding couples full invitation access.
- **Trial** lets customers design, save and privately preview drafts.
- **Paid** gives full access after you confirm their payment.

Use **Change access** to upgrade a Trial account. Their drafts are already in their dashboard. Payment is recorded manually by choosing Paid. Existing non-owner accounts from the earlier pilot start at Trial until the owner changes their access. Existing owner invitations are carried over.

If the sign-up email does not arrive, check your junk folder and run `docker compose logs --tail=50 invites` for mail delivery errors. Each generated household link can be opened and used to RSVP by whoever holds the link. Send each link to the intended household. Demo replies are discarded. Payment, the wedding planner connection and the occasion landing pages are separate milestones.

To back up, stop the app with `docker compose stop`, copy `/mnt/photographers_data/invites-ivoryclient` to your backup location, then run `docker compose start`. Uploaded photos are inside the same database. The database and data directory should have the same permissions after a restore.

## Run locally for development

Use Python 3.11 or newer with the system's time-zone database installed.

```sh
python3 app.py
```

Open `http://localhost:30112`. For local mail setup, use `python3 app.py mail-setup-code` and open `/admin/mail-setup`.
