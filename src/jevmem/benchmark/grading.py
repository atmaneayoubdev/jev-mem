"""LLM-judged answer grading for external benchmarks.

The templates below are LongMemEval's official answer-check prompts, reproduced verbatim
from `src/evaluation/evaluate_qa.py` (https://github.com/xiaowu0162/LongMemEval, MIT
license). The official evaluation uses GPT-4o as the judge; JevMem runs the same prompts on
the configured Qwen model, so absolute numbers are not comparable to published results.
"""

from __future__ import annotations

from jevmem.benchmark.scoring import AgentAnswer, AnswerScore
from jevmem.providers.qwen import GenerationProvider

_DEFAULT = (
    "I will give you a question, a correct answer, and a response from a model. Please answer "
    "yes if the response contains the correct answer. Otherwise, answer no. If the response is "
    "equivalent to the correct answer or contains all the intermediate steps to get the correct "
    "answer, you should also answer yes. If the response only contains a subset of the "
    "information required by the answer, answer no. \n\nQuestion: {}\n\nCorrect Answer: {}\n\n"
    "Model Response: {}\n\nIs the model response correct? Answer yes or no only."
)
_KNOWLEDGE_UPDATE = (
    "I will give you a question, a correct answer, and a response from a model. Please answer "
    "yes if the response contains the correct answer. Otherwise, answer no. If the response "
    "contains some previous information along with an updated answer, the response should be "
    "considered as correct as long as the updated answer is the required answer.\n\nQuestion: "
    "{}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes "
    "or no only."
)
_ABSTENTION = (
    "I will give you an unanswerable question, an explanation, and a response from a model. "
    "Please answer yes if the model correctly identifies the question as unanswerable. The model "
    "could say that the information is incomplete, or some other information is given but the "
    "asked information is not.\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}\n\nDoes "
    "the model correctly identify the question as unanswerable? Answer yes or no only."
)

GRADER_VERSION = "lme-official-v1"


def anscheck_prompt(task: str, question: str, answer: str, response: str, abstention: bool) -> str:
    if abstention:
        return _ABSTENTION.format(question, answer, response)
    if task == "knowledge-update":
        return _KNOWLEDGE_UPDATE.format(question, answer, response)
    if task in ("single-session-user", "single-session-assistant", "multi-session"):
        return _DEFAULT.format(question, answer, response)
    raise NotImplementedError(f"no official prompt wired for task {task!r}")


def response_text(answer: AgentAnswer) -> str:
    text = answer.final_answer.strip()
    if answer.abstain:
        text = (text + " " if text else "") + "(The memories do not contain this information.)"
    return text or "(no answer)"


async def grade(
    grader: GenerationProvider,
    *,
    task: str,
    question: str,
    reference: str,
    answer: AgentAnswer,
    abstention: bool,
) -> AnswerScore:
    prompt = anscheck_prompt(task, question, reference, response_text(answer), abstention)
    result = await grader.complete(
        [{"role": "user", "content": prompt}], max_tokens=8, enable_thinking=False
    )
    verdict = result.text.strip().lower()
    return AnswerScore(
        correct=verdict.startswith("yes"),
        forbidden_used=False,
        matched=[],
        reason=f"{GRADER_VERSION}: {verdict[:10]}",
    )
