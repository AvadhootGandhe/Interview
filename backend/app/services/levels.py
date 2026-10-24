LEVEL_RANK = {"Fresher": 1, "SDE-1": 2, "SDE-1/2": 3, "SDE-2/3": 4, "Architect/Principal": 5}

LEVEL_EXPECTATIONS = {
    "Fresher": "Solid fundamentals and clear explanations. Does not need production experience; reward curiosity and correct core concepts.",
    "SDE-1": "Applies fundamentals to small real tasks. Knows common tools, can reason about simple trade-offs and debug basic issues.",
    "SDE-1/2": "Owns features end to end. Explains trade-offs, failure modes and testing; some awareness of scale and operations.",
    "SDE-2/3": "Designs components and systems. Reasons about scale, reliability, cost and trade-offs; mentors others and justifies decisions with experience.",
    "Architect/Principal": "Shapes architecture across teams. Weighs long-term trade-offs, risk, org impact and evolution; challenges requirements and sees second-order effects.",
}
DEFAULT_EXPECTATION = "Reason from first principles and explain trade-offs clearly."


def level_expectations(level: str | None) -> str:
    return LEVEL_EXPECTATIONS.get(level or "", DEFAULT_EXPECTATION)


LEVEL_RUBRICS = {
    "Fresher": "Reward correct fundamentals and clear explanations. Do not penalise missing production experience.",
    "SDE-1": "Expect correct fundamentals applied to practical tasks, with basic trade-offs and debugging awareness.",
    "SDE-1/2": "Expect trade-offs, failure modes and testing awareness, with a concrete example from experience.",
    "SDE-2/3": "Expect scale, reliability and cost trade-offs, justified decisions and concrete production experience.",
    "Architect/Principal": "Expect long-term trade-offs, risk, organisational impact and second-order effects; penalise shallow or one-size-fits-all answers.",
}
DEFAULT_RUBRIC = "Judge correctness, depth, clarity and communication."


def level_rubric(level: str | None) -> str:
    return LEVEL_RUBRICS.get(level or "", DEFAULT_RUBRIC)
