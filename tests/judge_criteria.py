"""Shared rubric for fixed-answer calibration and the real-agent regression."""

ZERO_REMOVAL_CRITERIA = [
    "The agent calls get_defect_pareto with section='TE', "
    "date_from='2026-10-01', date_to='2026-10-31' and metric='removed_boards'.",
    "The final answer identifies DEMO-CODE-C with zero removed boards and "
    "explains that defect records exist despite zero removals. It must not "
    "claim that there are no matching records or that coverage is unknown. "
    "Acknowledging existing defect records is sufficient: there is no requirement "
    "to separately discuss coverage. Ignore percentage claims for this criterion.",
    "The final answer must not present a defect rate or a numeric Pareto "
    "percentage, including 0%. Reporting zero removed boards is a quantity, "
    "not a percentage. If the answer omits percentages entirely, this criterion "
    "passes. If it discusses percentages, it must explain that they are "
    "undefined because total removed boards is zero.",
]
