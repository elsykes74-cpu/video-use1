from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path


@dataclass
class ApprovalState:
    run_id: str
    topic: str
    weak_scenes: list[int]
    status: str
    approved: bool


def _state_path(run_id: str, root: Path) -> Path:
    return root / "_runs" / run_id / "approval_state.json"


def save_approval_state(state: ApprovalState, root: Path) -> Path:
    path = _state_path(state.run_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    return path


def load_approval_state(run_id: str, root: Path) -> ApprovalState | None:
    path = _state_path(run_id, root)
    if not path.exists():
        return None
    return ApprovalState(**json.loads(path.read_text(encoding="utf-8")))
