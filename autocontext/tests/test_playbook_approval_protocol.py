from __future__ import annotations


def test_start_run_protocol_accepts_playbook_approval_flag() -> None:
    from autocontext.server.protocol import StartRunCmd, parse_client_message

    cmd = parse_client_message({"type": "start_run", "scenario": "grid_ctf", "generations": 1, "require_playbook_approval": True})

    assert isinstance(cmd, StartRunCmd)
    assert cmd.effective_require_playbook_approval is True


def test_start_run_protocol_accepts_deprecated_lesson_approval_alias() -> None:
    from autocontext.server.protocol import StartRunCmd, parse_client_message

    cmd = parse_client_message({"type": "start_run", "scenario": "grid_ctf", "generations": 1, "require_lesson_approval": True})

    assert isinstance(cmd, StartRunCmd)
    assert cmd.require_playbook_approval is False
    assert cmd.effective_require_playbook_approval is True
