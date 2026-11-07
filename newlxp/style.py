"""Style variation for AI output.

To keep works written for many students from looking alike, a small, neutral
"style profile" is appended to the system prompt. The nudges only affect form
(structure, tone, emphasis) — never the content or the assignment's
requirements — so quality is unaffected. Picking one nudge per axis yields
hundreds of combinations.

A profile is a mapping ``{axis: index}``. It is generated once per user and
kept stable across assignments (see :mod:`newlxp.config`); the user may
re-roll it on purpose.
"""
from __future__ import annotations

import random

# The nudges below are appended to the prompt, so they are written in
# Russian like the rest of it; only AXIS_LABELS is interface text.
AXES = {
    "structure": [
        "Начни сразу с сути, без общего вступления.",
        "Выстрой изложение от конкретного примера к общему выводу.",
        "Веди мысль от общего принципа к частным деталям.",
        "Сделай упор на причинно-следственные связи между понятиями.",
        "Где уместно, сравни разные подходы и поясни выбор.",
        "Заверши ясным выводом, обобщающим твоё понимание темы.",
        "Подавай материал последовательными логическими шагами.",
        "Свяжи ключевые понятия между собой в единую картину.",
        "Начни с короткой постановки проблемы, затем разбери её.",
        "Чередуй объяснение и короткие пояснения по ходу текста.",
    ],
    "tone": [
        "Пиши сдержанно и по-деловому.",
        "Пиши чуть живее, допускается лёгкая разговорность.",
        "Пиши уверенно, от первого лица, как разобравшийся студент.",
        "Держи нейтральный академический тон без лишних эмоций.",
        "Пиши лаконично, короткими ясными фразами.",
        "Допусти более развёрнутые предложения там, где это помогает мысли.",
        "Допусти пару естественных оговорок, как в живом тексте.",
        "Пиши спокойно и рассудительно, с аккуратными формулировками.",
        "Пиши просто и доступно, объясняя как будто для себя.",
        "Пиши собранно и по существу, без отступлений.",
    ],
    "accent": [
        "Сделай акцент на определениях ключевых понятий.",
        "Сделай акцент на том, зачем это нужно и где применяется.",
        "Удели больше внимания типичным ошибкам и тому, как их избежать.",
        "Добавь короткий практический пример из реальной работы.",
        "Подчеркни последовательность шагов или логику процесса.",
        "Останови внимание на одном нетривиальном аспекте темы.",
        "Сделай акцент на связи теории с практикой.",
        "Обрати внимание на сильные и слабые стороны рассматриваемого.",
        "Выдели главное и отдели его от второстепенного.",
        "Покажи, как тема решает конкретную задачу специалиста.",
    ],
}

# Fixed display order and human labels for the axes.
AXIS_ORDER = ["structure", "tone", "accent"]
AXIS_LABELS = {"structure": "Structure", "tone": "Tone", "accent": "Focus"}


def random_profile() -> dict:
    """Pick one nudge index per axis at random."""
    return {axis: random.randrange(len(AXES[axis])) for axis in AXIS_ORDER}


def normalise(profile) -> dict:
    """Return a valid profile, filling/fixing any missing or bad indices."""
    result = {}
    for axis in AXIS_ORDER:
        index = (profile or {}).get(axis)
        if not isinstance(index, int) or not (0 <= index < len(AXES[axis])):
            index = random.randrange(len(AXES[axis]))
        result[axis] = index
    return result


def describe(profile) -> list:
    """Return ``[(label, text), ...]`` for display."""
    profile = normalise(profile)
    return [(AXIS_LABELS[axis], AXES[axis][profile[axis]]) for axis in AXIS_ORDER]


def suffix(profile) -> str:
    """The style instructions to append to the system prompt."""
    profile = normalise(profile)
    parts = [AXES[axis][profile[axis]] for axis in AXIS_ORDER]
    return " " + " ".join(parts)
