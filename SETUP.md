# foxtrot profile setup

The profile files belong at the root of the public `RedstoneLord/RedstoneLord` repository. GitHub displays the root `README.md` on the profile. Keep the GIF in `assets/foxtrot.gif` so the relative link works.

## Refresh the console

The workflow runs on Mondays at 07:23 Moscow time (04:23 UTC). Choose **Actions → Refresh foxtrot profile → Run workflow** to refresh on demand from the default branch. The workflow updates the generated block in `README.md` and keeps the last successful snapshot if GitHub returns an error.

- **Commits** covers the past 365 days. The console labels the source as the contribution graph or, if the built-in Actions token lacks access, GitHub’s public commit search. The fallback counts indexed commits on default branches, so the two sources can report different counts.
- **Stars earned** sums the current stars on your public repositories.
- **Top languages** ranks code bytes across your public non-fork repositories.
- **Activity** shows the latest three events from your public GitHub activity feed.

To request the exact contribution graph in the workflow, set `PROFILE_STATS_TOKEN` as a repository Actions secret using a fine-grained read-only personal access token restricted to the public profile repository. The workflow uses that token for the GraphQL query and the built-in Actions token for its commit. Limit the token to public data, since the generated README is public.

To preview the terminal with a local GitHub token that is already set as `GITHUB_TOKEN` or `PROFILE_STATS_TOKEN`, run this command from the repository root. The dry run prints the console.

```sh
python3 scripts/refresh_stats.py --dry-run
```

## Regenerate the artwork

With Python 3, NumPy, Pillow, and DejaVu Sans Mono installed, run this command from the repository root.

```sh
python3 scripts/render_scene.py assets/foxtrot.gif
```

Pass a `.png` output path for a still or `--font /path/to/monospace.ttf` to choose a different font. The weekly refresh uses the committed GIF.
