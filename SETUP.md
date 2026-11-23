# foxtrot profile setup

The profile files belong at the root of the public `RedstoneLord/RedstoneLord` repository. GitHub displays the root `README.md` on the profile. Keep the GIF in `assets/foxtrot.gif` so the relative link works.

## Refresh the console

The workflow runs on Mondays at 07:23 Moscow time (04:23 UTC). Choose **Actions → Refresh foxtrot profile → Run workflow** to refresh on demand from the default branch. The workflow regenerates `assets/terminal.gif` with the latest snapshot and keeps the existing animation if GitHub returns an error.

- **Commits** covers the past 365 days. The console labels the source as the contribution graph or, if the built-in Actions token lacks access, GitHub’s public commit search. The fallback counts indexed commits on default branches, so the two sources can report different counts.
- **Stars earned** sums the current stars on your public repositories.
- **Top languages** ranks code bytes across your public non-fork repositories.
- **Activity** shows the latest three events from your public GitHub activity feed.

To request the exact contribution graph in the workflow, set `PROFILE_STATS_TOKEN` as a repository Actions secret using a fine-grained read-only personal access token restricted to the public profile repository. The workflow uses that token for the GraphQL query and the built-in Actions token for its commit. Limit the token to public data, since the generated README is public.

The animation uses `sv.ping`, `sd.calch`, and `clr` as described in the game’s [console reference](https://voicesofthevoid.wiki.gg/wiki/Commands). `github.status` is the foxtrot terminal’s custom stats command.

With Pillow and DejaVu Sans Mono installed, run this command from the repository root to preview the current public stats as text.

```sh
python3 scripts/refresh_stats.py --dry-run
```

Run the command without `--dry-run` to regenerate the terminal GIF.

## Regenerate the artwork

With Python 3, NumPy, Pillow, and DejaVu Sans Mono installed, run this command from the repository root.

```sh
python3 scripts/render_scene.py assets/foxtrot.gif
```

Pass a `.png` output path for a still or `--font /path/to/monospace.ttf` to choose a different font. The weekly refresh updates the separate terminal GIF.
