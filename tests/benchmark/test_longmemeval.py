from jevmem.benchmark.datasets.longmemeval import parse_date, to_case
from jevmem.benchmark.grading import anscheck_prompt, response_text
from jevmem.benchmark.scoring import AgentAnswer


def _instance(qtype: str = "knowledge-update", qid: str = "q1") -> dict[str, object]:
    return {
        "question_id": qid,
        "question_type": qtype,
        "question": "What is my 5K personal best?",
        "question_date": "2023/06/25 (Sun) 13:22",
        "answer": "25:50",
        "answer_session_ids": ["a1", "a2"],
        "haystack_session_ids": ["x", "a1", "a2"],
        "haystack_dates": [
            "2023/05/01 (Mon) 10:00",
            "2023/05/23 (Tue) 13:01",
            "2023/05/30 (Tue) 13:53",
        ],
        "haystack_sessions": [
            [
                {"role": "user", "content": "Tell me about knitting."},
                {"role": "assistant", "content": "Sure."},
            ],
            [{"role": "user", "content": "I ran a 5K in 26:30!", "has_answer": True}],
            [
                {"role": "user", "content": "New PB: 25:50.", "has_answer": True},
                {"role": "user", "content": "  "},
            ],
        ],
    }


def test_knowledge_update_labels_latest_evidence_required_and_older_stale() -> None:
    case = to_case(_instance())
    labels = {m.content: m.label for m in case.memories}
    assert labels == {
        "Tell me about knitting.": "neutral",
        "I ran a 5K in 26:30!": "forbidden",
        "New PB: 25:50.": "required",
    }
    assert case.now == parse_date("2023/06/25 (Sun) 13:22")
    assert case.expected.mode == "llm_judge"
    assert case.expected.reference == "25:50"
    assert not case.background_eligible
    assert [m.sequence for m in case.memories] == sorted(m.sequence for m in case.memories)


def test_single_session_user_and_abstention_mapping() -> None:
    case = to_case(_instance("single-session-user", "q2_abs"))
    assert case.category == "single-session-user_abs"
    assert case.expected.abstention
    assert sum(m.label == "forbidden" for m in case.memories) == 0


def test_official_prompts_are_selected_by_task() -> None:
    ku = anscheck_prompt("knowledge-update", "Q", "A", "R", abstention=False)
    assert "updated answer is the required answer" in ku
    assert "unanswerable" in anscheck_prompt("single-session-user", "Q", "A", "R", abstention=True)
    assert response_text(AgentAnswer(final_answer="", abstain=True)).startswith("(The memories")
