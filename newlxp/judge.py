"""Rate a finished work with a model, against a written rubric.

The mechanical checks in :mod:`newlxp.checks` answer "is the required section
there". They cannot answer "is the reasoning any good", and that is what most
marks are actually for. This module asks a model, which is a weaker kind of
evidence and is treated as such:

* the rubric is explicit, so two runs judge the same thing;
* the reply is JSON, validated against a schema, with no silent fallback;
* the judge is calibrated (``evals/judge_cases/``) and its agreement with
  known-quality work is reported, because a judge nobody checked is just the
  model agreeing with itself.

Judging costs a request of its own, so nothing calls it automatically.
"""
from __future__ import annotations

import json
import re

from . import ai, schema

# Each criterion is scored 1-5. The descriptions are what the model is given,
# so changing them changes the measurement: treat them as versioned.
RUBRIC = {
    "compliance": "Выполнены ли требования задания: все пункты раскрыты, "
                  "нужные разделы и приложения на месте, заданные термины "
                  "использованы. 1 - половина пунктов пропущена, "
                  "5 - выполнено всё.",
    "depth": "Глубина разбора: есть ли объяснение причин и следствий, "
             "сравнение подходов, обоснованные выводы. 1 - перечисление "
             "общих мест, 5 - предметный анализ.",
    "concreteness": "Конкретность: привязка к ситуации, примеры, названные "
                    "механизмы вместо общих слов. 1 - сплошные общие фразы, "
                    "5 - каждый тезис подкреплён.",
    "coherence": "Связность: текст развивается, мысли не повторяются разными "
                 "словами, структура следует логике задания. 1 - набор "
                 "абзацев, 5 - цельный текст.",
}

SCORE_SCHEMA = {
    "type": "object",
    "required": list(RUBRIC) + ["comment"],
    "properties": dict(
        {name: {"type": "integer"} for name in RUBRIC},
        comment={"type": "string"},
    ),
}

SYSTEM = (
    "Ты строгий преподаватель. Ты оцениваешь студенческую работу по рубрике "
    "и возвращаешь только JSON.\n\n"
    "Оценивай по шкале от 1 до 5 целыми числами:\n"
    + "\n".join("  %s - %s" % (name, text) for name, text in RUBRIC.items())
    + "\n\nВерни объект JSON с полями "
    + ", ".join('"%s"' % name for name in RUBRIC)
    + ' и "comment" - одна фраза о главном недостатке работы.\n'
      "Оценивай только то, что видишь в тексте. Не придумывай недостатков "
      "и не делай скидок за объём: короткая, но содержательная работа может "
      "получить 5."
)


class Verdict:
    """What the judge said: a score per criterion plus one sentence."""

    __slots__ = tuple(RUBRIC) + ("comment",)

    def __init__(self, comment: str = "", **scores):
        for name in RUBRIC:
            setattr(self, name, int(scores.get(name, 0)))
        self.comment = comment

    @property
    def scores(self) -> dict:
        return {name: getattr(self, name) for name in RUBRIC}

    @property
    def average(self) -> float:
        return sum(self.scores.values()) / len(RUBRIC)

    def __repr__(self) -> str:
        return "<Verdict %s avg=%.2f>" % (self.scores, self.average)


def rate(config: dict, work: str, task_text: str = "") -> Verdict:
    """Ask the model to score ``work``; raises :class:`ai.AIError` on failure.

    No fallback on purpose: a made-up score is worse than no score, because
    it would quietly pollute the eval history.
    """
    user = (("# ЗАДАНИЕ\n\n%s\n\n" % task_text) if task_text else "") + \
        "# РАБОТА\n\n" + work
    answer = ai.complete(config, SYSTEM, user, json_mode=True)
    try:
        payload = _parse(answer.text)
    except ValueError as exc:
        raise ai.AIError("the judge did not return JSON (%s)" % exc)
    try:
        schema.validate(payload, SCORE_SCHEMA)
    except schema.SchemaError as exc:
        raise ai.AIError("the judge's answer does not match the rubric (%s)" % exc)
    for name in RUBRIC:
        if not 1 <= payload[name] <= 5:
            raise ai.AIError("%s scored %r, outside 1-5" % (name, payload[name]))
    return Verdict(payload["comment"],
                   **{name: payload[name] for name in RUBRIC})


def agreement(verdicts, expected) -> dict:
    """How well the judge matches known-quality work.

    ``expected`` holds a ``(low, high)`` band per criterion. A judge that
    lands inside the bands is usable; one that does not is reported as such
    rather than quietly trusted.
    """
    inside = total = 0
    distance = 0.0
    for verdict, bands in zip(verdicts, expected):
        for name, (low, high) in bands.items():
            value = getattr(verdict, name)
            total += 1
            if low <= value <= high:
                inside += 1
            else:
                distance += min(abs(value - low), abs(value - high))
    return {
        "criteria": total,
        "inside_band": inside,
        "rate": inside / total if total else 1.0,
        "mean_miss": distance / total if total else 0.0,
    }


def _parse(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n|\n```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the answer")
    return json.loads(text[start:end + 1])
