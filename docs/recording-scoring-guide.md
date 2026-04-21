# Recording Scoring

This is the eval workflow for COW recordings.

- `run_recordings`: run the agent against one or more saved recordings and create `CowAgentSession` rows.
- `eval_recordings`: score existing `(recording, agent session)` pairs.

Use `run_recordings` first when you need fresh runs. Use `eval_recordings` when the pairs already exist and you just want scores.

All management commands run inside the `api` Docker container:

```bash
docker compose -f docker-compose-local.yml exec api python manage.py <command>
```

## Commands

### 1. Run agent sessions

This creates agent sessions from recordings. It does not score them.

```bash
docker compose -f docker-compose-local.yml exec api python manage.py run_recordings
```

Common examples:

```bash
# one recording across the default models
docker compose -f docker-compose-local.yml exec api python manage.py run_recordings \
  --recording-session-id 2b8a...

# only recordings tagged issue-triage
docker compose -f docker-compose-local.yml exec api python manage.py run_recordings \
  --tag issue-triage

# custom models
docker compose -f docker-compose-local.yml exec api python manage.py run_recordings \
  --models gpt-4o claude-sonnet-4-5 gemini-2.5-pro
```

Useful flags:

- `--models ...`
- `--workspace-id <uuid>`
- `--recording-session-id <uuid>`
- `--tag <label>`
- `--limit-recordings N`
- `--agent-url <url>`
- `--timeout <seconds>`
- `--commit`: commit staged ops to base tables (makes changes permanent)
- `--discard`: delete staged ops after the run (use only if you are NOT scoring)

Agent sessions are written to the DB. Score them with `eval_recordings`.

### 2. Score existing pairs

This scores any `CowAgentSession` that is linked to a recording.

```bash
docker compose -f docker-compose-local.yml exec api python manage.py eval_recordings
```

Common examples:

```bash
# score one recording's runs
docker compose -f docker-compose-local.yml exec api python manage.py eval_recordings \
  --recording-session-id 2b8a...

# score one specific agent session
docker compose -f docker-compose-local.yml exec api python manage.py eval_recordings \
  --agent-session-id 7f13...

# score a subset
docker compose -f docker-compose-local.yml exec api python manage.py eval_recordings \
  --workspace-id 3fa8... \
  --limit 10
```

Useful flags:

- `--workspace-id <uuid>`
- `--recording-session-id <uuid>`
- `--agent-session-id <uuid>`
- `--limit N`
- `--output-dir <path>`
- `--name <label>`

Outputs:

- `<name>.csv`
- `<name>.jsonl`

The CSV is the summary view. The JSONL includes the feedback report and other detailed scoring data.

## Normal workflow

```bash
# 1) create fresh agent runs — staged ops are kept so scoring can read them
docker compose -f docker-compose-local.yml exec api python manage.py run_recordings

# 2) score the resulting pairs
docker compose -f docker-compose-local.yml exec api python manage.py eval_recordings
```

## If something is missing

- `run_recordings` needs saved recordings with prompts.
- `eval_recordings` needs `CowAgentSession` rows with `recording_id` set.
- If you ran `run_recordings --discard`, the staged ops are gone and `eval_recordings` will score everything as zero. Re-run without `--discard`.
- If `run_recordings` fails with 404, the agent container may not be running. Check with `docker compose ps`.
- If `eval_recordings` finds nothing, you probably have not created any linked agent sessions yet.
