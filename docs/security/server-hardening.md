# Server Hardening — HealthCore VPS

**Scope:** the single VPS used for HealthCore operations (Ubuntu 22.04.5 LTS).
**Date:** 2026-10-18
**Method:** baseline snapshot → changes → verification from outside the server.

---

## 1. Baseline (before)

| Control             | Finding                                                                                                                                          | Evidence                    |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------- |
| Root SSH login      | **Allowed** (`PermitRootLogin yes`)                                                                                                              | `sshd -T`                   |
| SSH passwords       | **Allowed** — two config files contradicted each other (`50-cloud-init.conf` = yes, `60-cloudimg-settings.conf` = no); effective value was `yes` | `sshd -T`                   |
| Non-root users      | **None** (`/home` empty, everything ran as root)                                                                                                 | `ls -la /home`              |
| Firewall            | **Inactive** (`ufw` inactive, iptables `INPUT ACCEPT`)                                                                                           | `ufw status`, `iptables -S` |
| Exposed ports       | 22 (SSH), 5173 (Vite dev server), 5678 (debugpy), 8000 (API) published on `0.0.0.0` and `[::]`                                                   | `ss -tulpn`                 |
| Pending maintenance | Reboot required, 19 package updates pending                                                                                                      | login banner                |
| Disk                | `/` at 95%                                                                                                                                       | `df -h /`                   |

Critical items: root SSH with password allowed, no firewall, a debugger port (5678) published to the internet, development servers exposed.

## 2. Changes applied

1. **Dedicated non-root user** `deploy`, member of `sudo`, key-only login (ed25519).
2. **SSH hardening** in `/etc/ssh/sshd_config.d/00-hardening.conf` (the `00-` prefix makes sshd read it first, so it wins over the conflicting files):

```
   PermitRootLogin no
   PasswordAuthentication no
   PubkeyAuthentication yes
   AllowUsers deploy
```

Validated with `sshd -t` before `systemctl reload ssh`. 3. **Unused containers stopped** (legacy financial-dashboard project) and auto-restart disabled:
`docker update --restart=no <containers>` then `docker stop <containers>`. Stopped, not deleted, so it is reversible. 4. **Firewall (ufw)**: default deny incoming, allow outgoing, SSH rate-limited:

```
   ufw default deny incoming
   ufw default allow outgoing
   ufw limit 22/tcp
   ufw --force enable
```

## 3. Folder permission model

| Path                                | Owner           | Mode            | Purpose                               |
| ----------------------------------- | --------------- | --------------- | ------------------------------------- |
| `/home/deploy`                      | `deploy:deploy` | `755` (default) | Operational user home                 |
| `/home/deploy/.ssh`                 | `deploy:deploy` | `700`           | SSH keys                              |
| `/home/deploy/.ssh/authorized_keys` | `deploy:deploy` | `600`           | Public key only                       |
| `/root`                             | `root:root`     | `700`           | Legacy files, not used for operations |

Rule going forward: application code is read-only for the app user, logs are the only writable directory, and secrets live in `.env` files that are git-ignored and never world-readable.

## 4. Verification (after)

Run from a machine **outside** the server:

```bash
# deploy still works (key login)
ssh -i ~/.ssh/healthcore_vps deploy@<VPS_IP> 'echo deploy login OK'

# root is rejected
ssh -o ConnectTimeout=5 root@<VPS_IP> true

# only the SSH port is reachable
for p in 22 5173 5678 8000 18789; do
  timeout 3 bash -c "</dev/tcp/<VPS_IP>/$p" 2>/dev/null && echo "port $p OPEN" || echo "port $p closed"
done
```

| Check                            | Before                          | After                           |
| -------------------------------- | ------------------------------- | ------------------------------- |
| `ssh root@<VPS_IP>`              | accepted (password)             | `Permission denied (publickey)` |
| `sshd -T` permitrootlogin        | `yes`                           | `no`                            |
| `sshd -T` passwordauthentication | `yes`                           | `no`                            |
| `sshd -T` allowusers             | not set                         | `deploy`                        |
| `ufw status`                     | inactive                        | active, `22/tcp LIMIT IN`       |
| Open ports from outside          | 22, 5173, 8000 (5678 published) | 22 only                         |

## 5. Residual risks and notes

- **Docker bypasses ufw.** Docker publishes ports through its own iptables chains, ahead of ufw rules. If any container with `ports:` is started again, it is reachable even with ufw active. Mitigation: bind published ports to loopback (`127.0.0.1:8000:8000`) or enforce rules in the `DOCKER-USER` chain.
- **Pending OS updates and reboot** (A06). Not applied yet: the disk is at 95%, so the update needs free space first.
- **Legacy data in `/root`** (old project folders, shell history, editor server data) should be reviewed and cleaned.
- **Remote editors** that connected as root (Cursor/VS Code server) must now connect as `deploy` with the key.

## 6. Rollback

Console access from the hosting provider's panel is the recovery path if SSH is lost. To undo SSH changes: remove `/etc/ssh/sshd_config.d/00-hardening.conf`, then `sshd -t && systemctl reload ssh`. To undo the firewall: `ufw disable`.
