# Publishing: Forgejo, GitHub and Home Assistant

Forgejo (`Homelab/monster-rgbic-ha`) is the source of truth. GitHub
(`Aareon/monster-rgbic-ha`) is a read-only public copy that HACS installs from.

```
PR merged to main on Forgejo
  -> lint workflow: yaml, eol, python, secrets, trailers, actionlint, tests
  -> release job: tags v<manifest version> if that tag is missing
  -> mirror job: filtered main + v* tags pushed to GitHub (SSH deploy key)
  -> GitHub release workflow: publishes the release for the tag
  -> HACS sees the release, Home Assistant's update entity turns on
```

Nothing is pushed to GitHub by hand, and nothing is merged on GitHub: a commit that exists only
there makes the next mirror push fail (it never forces).

## Releasing

- **Version in the PR:** change `version` in
  `custom_components/monster_rgbic/manifest.json` in the PR that should ship. When it merges and
  the checks pass, the release job tags `v<version>`.
- **Bump from CI:** run the `lint` workflow by hand on `main` (Actions, Run workflow) and pick
  `patch`, `minor` or `major`. After the checks pass it commits `release: X.Y.Z` to `main`
  (`scripts/release.py`), tags it and mirrors it.
- A merge that does not change the version publishes nothing to HACS: the mirror still copies
  `main`, but no release exists for it.
- The release job refuses a version that is not higher than the newest existing tag.

## What the mirror leaves out

`scripts/mirror-exclude.txt` lists the paths removed from the GitHub copy, in its whole history:
`.forgejo` (workflows that name the LAN runner and `ci/actions`) and `renovate.json`. Add a path
there to keep it off GitHub. A Forgejo push mirror cannot do this (it copies every path and ref),
which is why the mirror is a job. `scripts/mirror-to-github.sh` rewrites a throwaway clone with
git-filter-repo, so the GitHub commit ids differ from Forgejo's for commits that touched an
excluded path and are the same for the rest. The rewrite is deterministic, so every run is a
fast-forward.

GitHub runs `.github/workflows/`. Forgejo reads `.forgejo/workflows/` first and ignores
`.github/`, so the two sets do not run in each other's place.

## One-time setup (Aareon)

1. Make a key pair for this repo only, with no passphrase (a job cannot type one). In Windows
   PowerShell 5.1 the empty passphrase must be written `'""'`: a bare `""` is dropped and
   ssh-keygen answers "Too many arguments".
   `ssh-keygen -t ed25519 -N '""' -C monster-rgbic-ha-forgejo-mirror -f C:\Users\Aareon\monster-rgbic-ha-github-deploy-key`
2. GitHub, `Aareon/monster-rgbic-ha`, Settings, Deploy keys, Add: paste
   `C:\Users\Aareon\monster-rgbic-ha-github-deploy-key.pub`, tick **Allow write access**.
3. Forgejo, `Homelab/monster-rgbic-ha`, Settings, Actions, Secrets: add `MIRROR_DEPLOY_KEY` with
   the content of `C:\Users\Aareon\monster-rgbic-ha-github-deploy-key` (the private key; paste it
   in the page).
4. Delete both files:
   `Remove-Item C:\Users\Aareon\monster-rgbic-ha-github-deploy-key, C:\Users\Aareon\monster-rgbic-ha-github-deploy-key.pub`
5. Forgejo, Settings, Actions: the job token must be allowed to push to the repo (the release
   job pushes the tag and the bump commit).
6. GitHub repo settings: a description and topics (the HACS validation checks both), and
   Dependabot alerts on.

Until step 3 is done the mirror job only prints a warning.

## Rollback

- **Stop the mirror:** delete the `MIRROR_DEPLOY_KEY` secret (the job then only warns), and the
  deploy key on GitHub.
- **Bad release:** delete the GitHub release and its tag on GitHub, delete the tag on Forgejo,
  and publish a higher version. Home Assistant can go back to an earlier release from its update
  entity (`update.install` with `version:` set to the earlier tag).
- **GitHub copy diverged:** the mirror push fails and nothing is overwritten. Compare
  `git log` on both before deciding; never force it.
