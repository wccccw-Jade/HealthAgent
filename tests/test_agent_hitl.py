from app.agent.review import needs_human_review, normalize_decision, review_reason_for


def test_normalize_decision() -> None:
    assert normalize_decision("确认") == "confirm"
    assert normalize_decision("取消") == "cancel"
    assert normalize_decision("继续") is None


def test_delete_medication_requires_review() -> None:
    assert needs_human_review("delete_medication", {"medication_id": 1}) is True
    assert review_reason_for("delete_medication", {"medication_id": 1}) == "delete_medication"


def test_update_dose_requires_review() -> None:
    args = {"medication_id": 1, "dose": "2 片"}

    assert needs_human_review("update_medication", args) is True
    assert review_reason_for("update_medication", args) == "dose_change"


def test_update_times_requires_review() -> None:
    args = {"medication_id": 1, "times": ["09:00"]}

    assert needs_human_review("update_medication", args) is True
    assert review_reason_for("update_medication", args) == "time_change"


def test_update_instructions_does_not_require_review() -> None:
    assert needs_human_review("update_medication", {"instructions": "饭后"}) is False


def test_add_medication_does_not_require_review() -> None:
    assert needs_human_review("add_medication", {"name": "二甲双胍"}) is False
