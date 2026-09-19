"""nasos-task-run: invoked by generated systemd timers/services to run a
scheduled task via `tasks.run` on the agent socket, so "Run now", timers and
history all share one job path (PLAN.md §8). Implemented in Milestone 7.
"""

from __future__ import annotations


def main() -> None:
    raise SystemExit("nasos-task-run is not implemented yet (arrives in Milestone 7)")


if __name__ == "__main__":
    main()
