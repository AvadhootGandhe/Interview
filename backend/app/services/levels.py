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
