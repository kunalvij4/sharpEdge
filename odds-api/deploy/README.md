# GitHub image builds and production deployment

GitHub Actions builds the Linux/amd64 odds API image on changes to `main`, runs
the SQLite/PostgreSQL tests and container smoke test, and pushes the tested image
to `ghcr.io/kunalvij4/sharpedge-odds-api:sha-<full-commit-SHA>`. Pull requests run
the same checks without publishing. Changing the GitHub owner/repository changes
the image name automatically.

Deployment is separate and manual: **Actions → Deploy odds API → Run workflow**.
Choose `main` and enter the version from the successful build's summary. The
workflow resolves that tag to a digest, verifies its source revision, transfers
the matching commit's Compose configuration, and deploys that digest. The server
never checks out application source or builds an image.

The default target is **root@45.76.8.244:22**. The existing server's directory and
Compose project must be configured before the first deployment.

## One-time server setup

Use the server's existing SSH access to inspect the running deployment:

```sh
ssh root@45.76.8.244
docker compose ls --format json
```

Find the odds API's project name and the directory containing its Compose file.
Use that directory as `DEPLOY_DIR` and the **same project name** as
`DEPLOY_PROJECT`. The current repository's default project is `in-house-odds`;
its volumes are `in-house-odds_odds-data` and
`in-house-odds_collection-artifacts`. A different project name selects different
volumes, so do not guess when adopting an existing deployment.

The server needs Docker Engine, the Docker Compose v2 plugin with `up --wait`
and `--wait-timeout`, Bash, `tar`, and `flock` (from `util-linux`). The SSH user
must be able to run Docker and write in `DEPLOY_DIR`.

Keep the existing production `.env` at `DEPLOY_DIR/.env` and restrict its
permissions to the deployment user (`chmod 600 /actual/deploy/directory/.env`).
This is the file already used by the API; preserve its database name, username,
password, API keys, provider keys, league configuration, and existing `API_PORT`.
For a fresh installation only, copy `odds-api/.env.example` there and supply the
real values. The workflow does not copy or overwrite this file.

Use the existing root password through `DEPLOY_SSH_PASSWORD`, or authorize the
public half of a dedicated SSH deployment key for `root` and save its private
half as `DEPLOY_SSH_KEY`. GitHub-hosted runners must be able to reach the
configured SSH port. If both credentials are configured, the key takes priority.

## GitHub settings

Create an environment named **production** under **Settings → Environments**.
Add these environment secrets:

| Secret | Value |
| --- | --- |
| `DEPLOY_SSH_PASSWORD` | Existing root SSH password; required when no SSH key is configured |
| `DEPLOY_SSH_KEY` | Optional alternative: private SSH deployment key in OpenSSH format, without a passphrase |
| `DEPLOY_KNOWN_HOSTS` | Verified SSH known-hosts entry for `45.76.8.244` |

Use a trusted existing `known_hosts` entry, or collect the public host key with
`ssh-keyscan -H 45.76.8.244` and verify its fingerprint against the server console
before saving it. For a non-default port, use `ssh-keyscan -p PORT -H HOST`.
Deployment enforces host-key verification.

Some Windows OpenSSH versions fail with
`choose_kex: unsupported KEX method sntrup761x25519-sha512@openssh.com`
when running `ssh-keyscan`. Use a Linux container to collect the public key:

```powershell
docker run --rm alpine:3.22 sh -c 'apk add --no-cache openssh-client >/dev/null && ssh-keyscan -T 10 -t ed25519 45.76.8.244'
```

Copy the entire output line beginning `45.76.8.244 ssh-ed25519` into
`DEPLOY_KNOWN_HOSTS` after verification. From the hosting provider's trusted
server console, display the server's public-key fingerprint with:

```sh
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

This works with password login and does not require a user SSH key pair.
The Windows issue is tracked in
[Win32-OpenSSH #2140](https://github.com/PowerShell/Win32-OpenSSH/issues/2140).

Password authentication uses OpenSSH's `SSH_ASKPASS` helper. The helper reads
the masked GitHub secret from its environment; the password is not written to
the helper or passed as a command-line argument. SSH stdin stays available for
the release archive and short-lived registry token.

Add these environment variables:

| Variable | Value |
| --- | --- |
| `DEPLOY_DIR` | **Required:** absolute existing deployment directory, e.g. `/root/sharpEdge/odds-api`; no trailing slash or spaces |
| `DEPLOY_PROJECT` | Existing Compose project name; defaults to `in-house-odds` |
| `DEPLOY_HOST` | Optional; defaults to `45.76.8.244` |
| `DEPLOY_USER` | Optional; defaults to `root` |
| `DEPLOY_PORT` | Optional; defaults to `22` |

`DEPLOY_DIR` can also be stored as an environment or repository secret. The
workflow accepts either; a nonempty variable takes precedence over the secret.

The workflow uses the automatically supplied `GITHUB_TOKEN` to publish and pull
the private GHCR package. No registry personal access token or stored server
registry password is needed. The server receives the short-lived token over
SSH stdin, uses a temporary Docker configuration, and removes it on exit. Keep
the package connected to this repository and grant it Actions access if a
package with the same name already exists.

The existing Lambda deployment in `.github/workflows/main.yml` is independent
and remains active.

## Build and deploy

1. Push these workflow changes to `main`. GitHub only discovers workflows under
   the repository's top-level `.github/workflows` directory.
2. Wait for **Build odds API image** to pass. Its summary contains the deploy
   version and image digest. You can also run this build manually on `main`.
3. Open **Deploy odds API**, choose **Run workflow**, select `main`, and enter
   `sha-<full-40-character-commit-SHA>` (the full SHA alone also works).
4. Review the deployment run's result. It succeeds only after the API passes
   the Compose health check against `/health/ready`.

Each deployment creates `DEPLOY_DIR/releases/RUN_ID-RUN_ATTEMPT`, containing the
selected commit's `compose.yaml`, deployment script, and, after success, an
`image` file with the deployed digest. `current` points to the last successful
release; `previous` points to the prior successful release. Neither pointer
changes if migrations or readiness fail. Releases are retained for inspection.

Before replacing the running API, the Redis deployment validates configuration,
pulls the image, and runs a one-off container from that image to authenticate
and PING the configured Redis endpoint. A failed connection leaves the running
API untouched. It then recreates the API and waits for readiness. A brief API
interruption is expected. Existing data and collection-artifact volumes are
preserved. Deployments are serialized in GitHub and by a server-side lock.

## Redeploy an earlier version or recover a failure

Run **Deploy odds API** again with a previously published version. Source,
configuration, and image all come from that version. Image replacement does
not undo schema migrations; older application versions must support the
database's current schema. There is no automatic database downgrade or
automatic rollback after a failed migration.

If migration or readiness fails after the API was stopped, the job fails and
the API may remain stopped or unhealthy. Inspect the failed release on the
server, fix the cause, and retry the same version or deploy a compatible one:

```sh
# Replace these values with the configured directory, failed release, and project.
deploy_dir=/actual/deploy/directory
release_dir="$deploy_dir/releases/RUN_ID-RUN_ATTEMPT"
project=in-house-odds
docker compose --project-name "$project" --env-file "$deploy_dir/.env" \
  --file "$release_dir/compose.yaml" ps --all
```

The `current` pointer records release success; it does not roll back the running
container after a readiness failure. Use **Inspect odds API collector** to view
the container image, exit status, restart count, and startup logs, including
when the container is restarting. A Redis TLS handshake failure occurs before
authentication; verify the database is running and Quick Connect still shows
the configured host and port. Changing `ODDS_REDIS_URL` alone does not update an
existing server `.env` entry (see Redis secret injection below).

Keep previous images in GHCR if you want to redeploy them. Deleting the package
version removes the workflow's ability to pull it again. Normal Docker restarts
use the already downloaded image and its restart policy.

GitHub references: [publishing Docker images](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images),
[manual workflow runs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow),
and [GHCR authentication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

## Redis secret injection

Set the repository or production-environment Actions secret `ODDS_REDIS_URL` to
the complete Redis connection URL. The deployment workflow passes it over SSH
stdin and adds a single-quoted `REDIS_URL` entry to `DEPLOY_DIR/.env` only if that
key is absent. Existing entries are preserved, including explicit empty entries
(which Compose rejects). The URL is never placed in command arguments or logs.
Other API/provider credentials must already be in the server's `.env`.

The Redis deployment pulls only the API image and removes obsolete PostgreSQL
and migration containers without deleting their volumes. SQL migration steps in
the older instructions above apply only to older releases.
