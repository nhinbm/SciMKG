#!/usr/bin/env bash
# Run every Ex02 (lesson, configuration) in turn; wait and resume when the Codex quota pauses a run (exit 75).
# Lessons go one at a time through all three configurations, so a stop leaves complete lessons behind.
# full on nervous-system is the Ex01 run and is not repeated. A finished folder is skipped.
set -u
cd "$(dirname "$0")/../../.."
PYTHON=${PYTHON:-.venv-ex01/bin/python}
MODEL=${MODEL:-gpt-6-luna}
WAIT_SECONDS=${WAIT_SECONDS:-1800}

for lesson in amphibian-reproduction atmospheric-pressure proteins buoyancy sulfuric-acid-and-sulfate nervous-system; do
  for config in no-verification one-round full; do
    [ "$lesson/$config" = "nervous-system/full" ] && continue
    folder="runs/experiments/ex-02/$MODEL/$config/$lesson"
    [ -f "$folder/augmentation.json" ] && continue
    while true; do
      echo "$(date -u +%FT%TZ) start $lesson $config"
      "$PYTHON" scripts/experiments/ex-02/run.py run --lesson "$lesson" --config "$config" --model "$MODEL"
      code=$?
      [ "$code" -eq 0 ] && break
      if [ "$code" -ne 75 ]; then
        echo "$(date -u +%FT%TZ) failed $lesson $config with exit $code"
        exit "$code"
      fi
      echo "$(date -u +%FT%TZ) paused $lesson $config; waiting ${WAIT_SECONDS}s"
      sleep "$WAIT_SECONDS"
    done
    echo "$(date -u +%FT%TZ) done $lesson $config"
  done
done
"$PYTHON" scripts/experiments/ex-02/run.py summary --model "$MODEL"
