from cua.agent.loop_runner import AgentLoopRunner


def test_defer_premature_done_when_ui_actions_are_present() -> None:
    actions = [
        {"action": "CLICK", "x": 300, "y": 45},
        {"action": "INPUT", "text": "刘海俊"},
        {"action": "PRESS", "key": "enter"},
        {"action": "REPLY", "text": "已成功向刘海俊发送消息「hello」，任务完成。"},
        {"action": "DONE"},
    ]

    filtered, deferred = AgentLoopRunner._defer_premature_completion(actions)

    assert deferred is True
    assert filtered == [
        {"action": "CLICK", "x": 300, "y": 45},
        {"action": "INPUT", "text": "刘海俊"},
        {"action": "PRESS", "key": "enter"},
    ]


def test_keep_done_when_no_ui_actions_are_present() -> None:
    actions = [
        {"action": "REPLY", "text": "已确认消息发送完成。"},
        {"action": "DONE"},
    ]

    filtered, deferred = AgentLoopRunner._defer_premature_completion(actions)

    assert deferred is False
    assert filtered == actions
