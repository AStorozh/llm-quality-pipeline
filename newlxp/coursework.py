"""Assemble study materials for a checkpoint and write them to disk.

The context rule mirrors how a student would prepare: to produce the work for
a given checkpoint the AI receives, in order, every study topic and every
earlier checkpoint that precedes it — including any previously generated work
for those earlier checkpoints — followed by the target checkpoint itself.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

from . import api, attachments, content, polish

# Everything the AI produces is written under ``ai_output/`` in the CWD.
OUTPUT_ROOT = os.path.join(os.getcwd(), "ai_output")

# Default system prompt. Universal for any assignment type and sent on every
# request (a few per cent of it — the materials block dominates). It asks for
# substance, bounds the length so works differ in size instead of all running
# to the same six pages, and closes the holes seen in practice: invented
# dates and events, visible references to "материалы", and chat leftovers.
SYSTEM_PROMPT = (
    "Ты студент, выполняющий учебное задание на основе предоставленных "
    "материалов.\n\n"
    "Изучение материалов. Сначала внимательно изучи задание и источники. "
    "Определи основные вопросы, требования и критерии выполнения. Опирайся "
    "прежде всего на предоставленные материалы, сохраняя их терминологию, "
    "смысл и уровень детализации. Не пересказывай источники подряд. Используй "
    "внешние источники, только если это разрешено заданием; если в задании об "
    "этом ничего не сказано, опирайся на материалы и общеизвестные факты.\n\n"
    "Достоверность. Не выдавай выдуманное за факт: статистику, финансовые "
    "показатели, даты событий, названия и цитаты приводи только из "
    "материалов или общеизвестные. Если таких данных нет, не подставляй "
    "правдоподобные - конкретность достигается точными формулировками и "
    "разбором ситуаций, а не цифрами ради цифр. Это не мешает предлагать "
    "собственные плановые величины там, где этого просит задание: сроки "
    "этапов, целевые значения показателей, состав команды - давай их "
    "конкретно, как своё предложение. Реквизиты документа - дату "
    "утверждения, номер, титульный лист - проставляй, только если задание "
    "их просит. Не описывай как состоявшееся то, "
    "чего не было: если задание требует провести опрос, интервью или "
    "эксперимент, оформи это как смоделированный сценарий и прямо укажи, "
    "что он условный. Если задание практическое и требует данных для "
    "расчёта (база клиентов, заказы, посещения, бюджет), а их не дали, "
    "создай небольшой учебный набор данных, прямо назови его условным и "
    "проведи на нём все расчёты до конца: исходные данные, промежуточные и "
    "итоговые значения. Рассуждение о том, что показали бы данные, вместо "
    "самого расчёта - это невыполненное задание.\n\n"
    "Содержание. Раскрывай тему через конкретные объяснения и аргументы. "
    "Анализируй причины, последствия и взаимосвязи, сравнивай подходы, "
    "рассматривай примеры и обосновывай выводы. Не ограничивайся "
    "перечислением понятий и общепринятых утверждений. Каждый основной тезис "
    "должен быть раскрыт по существу. Если информации недостаточно, не "
    "заполняй пробелы догадками.\n\n"
    "Самостоятельность рассуждений. Показывай понимание темы через анализ "
    "материала, а не через декларации личного мнения. Учитывай противоречия "
    "и ограничения, если они существенны. Не повторяй одну мысль разными "
    "словами. Выводы должны логически следовать из рассмотренных "
    "аргументов.\n\n"
    "Связь с предыдущими работами. Если задание продолжает линию прошлых "
    "контрольных точек, опирайся на принятые там решения и развивай их, "
    "коротко напомнив суть своими словами. Не копируй формулировки и целые "
    "абзацы из предыдущих работ дословно.\n\n"
    "Язык. Пиши ясно и естественно, в соответствии с уровнем студенческой "
    "работы. Используй точные формулировки, избегай канцелярита, избитых "
    "выражений, пустых обобщений, излишне сложных конструкций и терминов без "
    "объяснения. Не добавляй формальные фразы ради объёма. Не усложняй "
    "простые мысли ради академичности. Не используй длинное и среднее "
    "тире (символы — и –): вместо них ставь обычный дефис с пробелами "
    "(«цель - это рост продаж»), двоеточие или скобки. Не заменяй тире "
    "запятой: «цель, это рост» - ошибка. Не ссылайся на источники "
    "оборотами "
    "«в материалах», «из материалов», «согласно материалам», «из учебной темы» - излагай "
    "содержание напрямую или называй конкретный источник.\n\n"
    "Структура. Выстраивай текст в соответствии с логикой конкретного "
    "задания. Не используй одинаковую схему рассуждения для всех абзацев и "
    "без необходимости не повторяй один и тот же тип блока после каждого "
    "раздела - но если задание прямо требует такой блок (например, "
    "пояснение после каждого пункта), делай его везде, где сказано. Каждый абзац "
    "должен развивать тему или добавлять новую мысль. Не дублируй "
    "аргументы.\n\n"
    "Дробление. Если задание не предписывает иного, основной объём работы - "
    "связный текст абзацами, а не каркас из заголовков и списков. Заголовки "
    "ставь только там, где меняется крупная часть работы: обычно их не "
    "больше шести-восьми на всю работу, и под каждым идёт несколько абзацев. "
    "Не выноси в отдельный раздел то, что укладывается в один абзац, и не "
    "превращай рассуждение в маркированный список. Списком оформляй только "
    "то, что действительно является перечнем. Схемы описывай словами, а не "
    "символами псевдографики и не блоками кода. Таблицы оформляй в "
    "Markdown (| столбец | столбец |): в документе они становятся "
    "настоящими таблицами. Где задание просит таблицу, расчёт, план по "
    "каналам или неделям, давай таблицу, а не описание словами.\n\n"
    "Полнота. Пройди по заданию по пунктам и убедись, что раскрыт каждый: "
    "пропущенный пункт стоит баллов. Если задание или материалы вводят свои "
    "термины, классификацию или метод анализа (SWOT, матрица, модель), "
    "применяй именно их и называй своими именами, а не пересказывай.\n\n"
    "Объём. Если задание называет объём - соблюдай ровно его, это важнее "
    "всех ориентиров ниже. Иначе: обычная контрольная "
    "точка - 700-1200 слов. Короткий разбор, расчёт или ответ на конкретный "
    "вопрос - 300-600 слов. Задание с длинным перечнем разделов и "
    "приложений - до 1800 слов. Не превышай 1800 слов: чтобы уложиться, "
    "делай каждый пункт короче, но не выбрасывай требуемое заданием. Работы "
    "по разным темам не должны получаться одинакового размера - объём "
    "диктует задание. Лучше короче и по делу, чем длиннее ради полноты.\n\n"
    "Проверка. Перед ответом проверь соответствие заданию, точность фактов, "
    "качество аргументации, обоснованность выводов и отсутствие повторов. "
    "Исправь обнаруженные недостатки.\n\n"
    "Названия разделов выше - указания для тебя, а не план работы: не "
    "переноси их в текст. Выдавай только саму работу на русском языке: без "
    "обращений к читателю, без пояснений о том, что и почему ты сделал, без "
    "предложений доработать или переоформить её и без подписи в конце."
)


# Repeated at the very end of every request, right after the task. The same
# limits are in the system prompt, but a model follows what stands next to
# the task far more reliably — without this the works came out twice as long
# as asked and split into dozens of one-paragraph sections.
def output_rules(task_text: str = "") -> str:
    """The formatting checklist appended after the task.

    A size stated in the task replaces our own guidance; everything else is
    phrased so the task always wins, since disciplines differ in what they
    demand (a title page with a date, an explanation after every clause, a
    particular method of analysis).
    """
    stated = required_volume(task_text)
    volume = ("- Объём задан в задании: %s. Это требование преподавателя, "
              "соблюдай его. Если задан диапазон, целься в верхнюю половину: "
              "недобор объёма считается невыполнением.\n" % stated if stated else
              "- Объём: столько, сколько требует задание. Обычная КТ - "
              "700-1200 слов; короткий разбор, расчёт или ответ на один "
              "вопрос - 300-600 слов. Если задание перечисляет больше пяти "
              "пунктов или требует приложений и образцов - 1400-1800 слов. "
              "Больше 1800 слов не пиши: укладывайся, делая каждый пункт "
              "короче, а не выбрасывая его.\n")
    return _OUTPUT_RULES_TEMPLATE % volume


_OUTPUT_RULES_TEMPLATE = (
    "# ТРЕБОВАНИЯ К ЭТОЙ РАБОТЕ\n\n"
    "- Сначала выпиши для себя всё, что требует задание: разделы, пункты, "
    "приложения, образцы, методы анализа, объём, оформление. Каждый такой "
    "пункт должен оказаться в работе - пропущенный стоит баллов.\n"
    "- Требования задания важнее правил ниже. Если задание просит титульный "
    "лист с датой, пояснение после каждого пункта, нумерованные списки, "
    "конкретный метод анализа (SWOT, PEST, матрица и т. п.) или иной "
    "объём - делай так, как сказано в задании, даже если ниже написано "
    "обратное.\n"
    "- Если тема опирается на метод или классификацию из материалов курса, "
    "применяй именно их и называй своими именами, а не пересказывай.\n"
    "%s"
    "- Если задание просит разработать варианты, альтернативы, сценарии "
    "или подходы, а затем выбрать лучший - опиши каждый вариант отдельно, "
    "сравни их и обоснуй выбор. Назвать сразу один вариант недостаточно.\n"
    "- Там, где задание просит план, этапы или дорожную карту, у каждого "
    "этапа укажи ориентировочный срок и ответственного. Там, где просит "
    "приложения, образцы или шаблоны, вынеси их отдельным разделом "
    "«Приложения» в конце.\n"
    "- Если задание практическое (расчёт, анализ данных, медиаплан, "
    "контент-план, программа с параметрами, выполнение по шагам): раздели "
    "работу на разделы по шагам задания с заголовками «## », даже если "
    "выше сказано обходиться без заголовков. Каждое значение, которое "
    "требует шаг, посчитай и покажи в таблице Markdown; нет исходных данных "
    "- создай учебные, назови их условными и доведи расчёт до итога. Цели "
    "и KPI давай с числом и сроком.\n"
    "- В расчётных заданиях считай каждый показатель один раз: формула, "
    "подстановка, результат. Округляй одинаково везде, не повторяй шаг и не "
    "давай одной величине два разных значения. Итоговый ответ должен "
    "совпадать с последним шагом расчёта и со сводной таблицей.\n"
    "- Формулы и расчёты пиши обычным текстом: «CAC = 42 690 / 63 = 677,62 "
    "руб.», без LaTeX, без знаков доллара вокруг формул и без команд с "
    "обратной косой чертой.\n"
    "- Иначе, если задание не требует иного, основа работы - связный текст "
    "абзацами: заголовков не больше шести-восьми на всю работу, под каждым "
    "несколько абзацев, и списком оформлены только настоящие перечни. Не "
    "дроби текст на разделы из одного абзаца.\n"
    "- Не выдавай выдуманное за факт: статистику, финансовые показатели и "
    "результаты компаний приводи только из материалов или общеизвестные. Но "
    "там, где задание просит предложить план, сроки, этапы, целевые "
    "значения или реквизиты документа, давай конкретику от своего имени - "
    "это твоё предложение, а не факт.\n"
    "- Каждый пронумерованный шаг задания выполняй буквально, как он "
    "сформулирован: если шаг велит выделить первую группу и разделить её, "
    "работай именно с ней, а не с другой выборкой; если просит среднее, "
    "посчитай среднее, а не сумму. Название таблицы или раздела должно "
    "совпадать с тем, что в нём показано.\n"
    "- Цели, лимиты и плановые значения, которые ты назвал в начале, "
    "должны выполняться в твоих же расчётах: если расчёт даёт другое, "
    "поправь цель или расчёт. Группы разного размера сравнивай по средним "
    "или долям, а не по суммам.\n"
    "- Перед ответом сверь текст с таблицами и со сроками плана: числа и "
    "названия совпадают, и ни одно действие не опирается на то, что по "
    "плану ещё не началось.\n"
    "- Без штампов: не пиши «это и есть», «важно отметить», «играет "
    "ключевую роль», «удобный инструмент», «позволяет не только», «в итоге "
    "моя…», «становится не… а…». Конструкцию «не X, а Y» используй не "
    "больше двух-трёх раз на всю работу.\n"
    "- Не используй длинное и среднее тире (— и –): ставь обычный дефис с "
    "пробелами («цель - это рост»), а не запятую («цель, это рост» - "
    "ошибка).\n"
    "- Выдай только текст работы: без подписи в конце, без пояснений о том, "
    "что ты сделал, и без предложений доработать её."
)


# Appended when the work is also exported as a presentation: the deck is split
# into slides by headings, so without them the slides are cut by paragraph.
SLIDES_INSTRUCTION = (
    "\n\nРаботу также нужно оформить презентацией, поэтому раздели её на "
    "смысловые части и дай каждой короткий заголовок отдельной строкой, "
    "начав строку с «## »."
)

# Appended last: the work is handed in under the student's own name.
_AUTHOR_INSTRUCTION = (
    " Работа сдаётся от имени студента %s, пиши от первого лица как этот "
    "человек."
)


def prompt_version() -> str:
    """A short fingerprint of the instructions the model is given.

    Recorded with every eval result, so a score can be attributed to the
    prompt that produced it. A hash rather than a number because nobody
    remembers to bump a number, and a stale version label is worse than
    none at all.
    """
    material = SYSTEM_PROMPT + _OUTPUT_RULES_TEMPLATE + SLIDES_INSTRUCTION
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:8]


def system_prompt(student_name: str = "", base: str = "", slides: bool = False) -> str:
    """Return the system prompt, personalised with the student's name.

    ``base`` overrides the built-in :data:`SYSTEM_PROMPT` when provided (a
    user-edited prompt). With ``slides`` the model is asked for headings, so
    the presentation export can split the work into slides.
    """
    text = base.strip() or SYSTEM_PROMPT
    if slides:
        text += SLIDES_INSTRUCTION
    if student_name:
        text += _AUTHOR_INSTRUCTION % student_name
    return text


def flatten_topics(discipline: dict) -> list[dict]:
    """Return the discipline's topics as a single ordered list."""
    topics: list[dict] = []
    for chapter in discipline.get("chapters") or []:
        for topic in chapter.get("topics") or []:
            topics.append(
                {
                    "id": topic.get("id"),
                    "name": (topic.get("name") or "").strip(),
                    "is_checkpoint": bool(topic.get("isCheckPoint")),
                    "max_score": topic.get("maxScore"),
                    "chapter": chapter.get("name"),
                }
            )
    return topics


def checkpoints(topics: list[dict]) -> list[tuple[int, dict]]:
    """Return ``(index, topic)`` pairs for every checkpoint, in order."""
    return [(i, t) for i, t in enumerate(topics) if t["is_checkpoint"]]


# Checkpoint names on the platform look like «КТ №4. Тема», «КТ 2 - "Тема"»,
# «Checkpoint 2. Topic» or just «Итоговая работа». This matches the prefix.
_CHECKPOINT_PREFIX_RE = re.compile(
    r"^\s*(?:КТ|KT|Checkpoint|Контрольная\s+точка)(?![^\W\d_])"
    r"\s*№?\s*(\d+)?\s*[.:\-–—]?\s*",
    re.IGNORECASE,
)
_QUOTES = {'"': '"', "«": "»", "“": "”"}


def checkpoint_label(name: str, ordinal: int) -> tuple[int, str]:
    """Split a checkpoint name into ``(number, title)``.

    The number is taken from the name («КТ №4…») or, when absent, is the
    checkpoint's ordinal; the title loses the prefix, wrapping quotes and a
    trailing dot: ``КТ № 3 - "План"`` → ``(3, "План")``.
    """
    name = (name or "").strip()
    number, title = ordinal, name
    match = _CHECKPOINT_PREFIX_RE.match(name)
    if match:
        if match.group(1):
            number = int(match.group(1))
        title = name[match.end():]
    title = title.strip().rstrip(".").strip()
    closing = _QUOTES.get(title[:1])
    if closing and title.endswith(closing) and title.count(title[0]) <= 2:
        title = title[1:-1].strip()
    title = title[:1].upper() + title[1:]
    return number, title or name


# A stated size in the task text: "объёмом примерно 1500-2000 слов", "не
# менее 5 страниц", "до 10 000 знаков". Parsed in code rather than left to
# the model, because a stated size outranks our own guidance and the wording
# differs from discipline to discipline.
#
# One parser, one answer: three separate ones used to disagree about the
# same sentence, so the prompt, the retry and the checks each demanded
# something different.
_VOLUME_RE = re.compile(
    r"(?:(не\s+менее|не\s+более|минимум|максимум|от|до|примерно|около)\s+)?"
    r"(\d[\d\s\u00a0]{0,8})"
    r"(?:\s*(?:[-\u2013\u2014]|до)\s*(\d[\d\s\u00a0]{0,8}))?\s*"
    r"(слов|слова|слов[аеу]х?|страниц\w*|стр\.|знак\w*|символ\w*|листов|листа|листах)"
    r"(?![а-яё])",
    re.IGNORECASE,
)
# Plausible ranges per unit, to reject "10 человек" style false positives.
# The upper bounds also keep out sizes no single request could produce.
_VOLUME_LIMITS = {"слов": (100, 5000), "знак": (1000, 35000),
                  "символ": (1000, 35000), "страниц": (1, 40),
                  "стр": (1, 40), "лист": (1, 40)}
# A number and a unit are only a size requirement when something nearby
# says so. Without this, "разместите схему на 2 страницах приложения"
# was read as the length of the whole work.
_VOLUME_CUE = re.compile(
    r"объ[её]м|размер|напиш|эссе|работ|текст|реферат|доклад|сочинен|"
    r"статья|отч[её]т|аннотац|конспект|издож|излож", re.IGNORECASE)
_CUE_WINDOW = 80  # characters before the number to look in
# "лонгриды на 5000 знаков, посты на 500": the size of the items the work is
# about, not of the work. Plural or item-only forms, so "напишите пост на 300
# слов", where the post is the work, still counts.
_ITEM_SIZE = re.compile(
    r"(?:лонгрид\w*|пост(?:ы|ов|ах)|публикаци(?:и|й|ях)|подписи|заголовк\w*|"
    r"ролик\w*|сообщени(?:я|й|ях))\s*(?:[-\u2013\u2014:,]\s*)?"
    r"(?:на|до|в|по|около|примерно)?\s*$", re.IGNORECASE)
# Below this, an upper bound is read as applying to a section rather
# than to the whole work.
MIN_CEILING_WORDS = 300
# Russian academic prose averages roughly this many characters per word,
# including the following space.
CHARS_PER_WORD = 6.5
# A page of student prose. Used only to bound a page count, never to turn
# one into a hard floor: pagination depends on formatting.
WORDS_PER_PAGE = 300
# A shortfall smaller than this is not worth a second request.
VOLUME_TOLERANCE = 0.95

_AT_LEAST = ("не менее", "минимум", "от")
_AT_MOST = ("не более", "максимум", "до")


class Volume:
    """A size requirement read out of an assignment.

    ``floor`` and ``ceiling`` are in words and are ``0`` when the task
    gives no usable bound. ``as_written`` is the task's own phrasing, for
    quoting back to the model.
    """

    __slots__ = ("floor", "ceiling", "as_written")

    def __init__(self, floor: int = 0, ceiling: int = 0, as_written: str = ""):
        self.floor = floor
        self.ceiling = ceiling
        self.as_written = as_written

    def __bool__(self) -> bool:
        return bool(self.as_written)

    def __repr__(self) -> str:
        return "<Volume %r floor=%d ceiling=%d>" % (
            self.as_written, self.floor, self.ceiling)


def _unit_limits(unit: str):
    """Plausible bounds for a unit word, matched by its stem."""
    unit = unit.lower().rstrip(".")
    for stem, bounds in _VOLUME_LIMITS.items():
        if unit.startswith(stem):
            return bounds
    return None


def _to_words(amount: int, unit: str) -> int:
    """A size in its own unit, expressed in words."""
    unit = unit.lower()
    if unit.startswith("слов"):
        return amount
    if unit.startswith(("знак", "символ")):
        return int(amount / CHARS_PER_WORD)
    return amount * WORDS_PER_PAGE  # pages or sheets


def read_volume(task_text: str) -> Volume:
    """The size the task asks for, as a single answer.

    The first plausible statement wins for the wording, but a later
    sentence can still supply a bound the first one lacked - tasks write
    "Работа на 5 страниц, не менее 1200 слов."
    """
    result = Volume()
    for match in _VOLUME_RE.finditer(task_text or ""):
        qualifier, low, high, unit = match.groups()
        qualifier = (qualifier or "").lower()
        bounds = _unit_limits(unit)
        if bounds is None:
            continue
        if _ITEM_SIZE.search(task_text[max(0, match.start() - 40):match.start()]):
            continue
        cue = _VOLUME_CUE.search(task_text, max(0, match.start() - _CUE_WINDOW),
                                 match.start())
        if not cue and qualifier not in _AT_LEAST + _AT_MOST:
            continue  # a number and a unit, but nothing says it is the size
        low_n = _as_int(low)
        high_n = _as_int(high) if high else None
        if not bounds[0] <= low_n <= bounds[1]:
            continue
        if high_n is not None and not bounds[0] <= high_n <= bounds[1]:
            continue

        floor = ceiling = 0
        if high_n is not None:                     # an explicit range
            floor, ceiling = _to_words(low_n, unit), _to_words(high_n, unit)
        elif qualifier in _AT_MOST:
            ceiling = _to_words(low_n, unit)
        else:                                      # bare or "не менее"
            floor = _to_words(low_n, unit)
            if qualifier not in _AT_LEAST:
                ceiling = floor                    # "эссе на 500 слов"
        # A page count bounds the answer but is too formatting-dependent to
        # enforce as a floor.
        if unit.lower().startswith(("страниц", "стр", "лист")):
            floor = 0

        if not result.as_written:
            size = ("%s-%s" % (_group(low_n), _group(high_n)) if high_n
                    else _group(low_n))
            # A range already says both bounds; "от 800-1 200" reads wrong.
            prefix = ("" if high_n else
                      (qualifier + " ") if qualifier in _AT_LEAST + _AT_MOST else "")
            result.as_written = "%s%s %s" % (prefix, size, unit.lower())
        result.floor = result.floor or floor
        result.ceiling = result.ceiling or ceiling

    if result.floor and result.ceiling and result.floor > result.ceiling:
        result.ceiling = 0  # contradictory statements: keep the demand
    # A tiny ceiling with no floor is almost always scoped to one part of
    # the work ("сократите введение до 200 слов"), and enforcing it would
    # fail every real answer.
    if result.ceiling and not result.floor and result.ceiling < MIN_CEILING_WORDS:
        result.ceiling = 0
        result.as_written = ""
    return result


def required_volume(task_text: str) -> str:
    """The size the task demands, in its own words ("1 500-2 000 слов")."""
    return read_volume(task_text).as_written


def volume_floor(task_text: str) -> int:
    """Minimum length in words the task demands, or ``0`` if it states none."""
    return read_volume(task_text).floor


def _as_int(value: str) -> int:
    return int(re.sub(r"[\s\u00a0]", "", value))


def _group(number: int) -> str:
    """Thousands separated by a space, as Russian texts write them."""
    return "{:,}".format(number).replace(",", " ")


def expansion_prompt(answer: str, task_text: str) -> str:
    """Ask the model to grow a work that came out below the required size."""
    return (
        "Эта работа короче, чем требует задание: в ней %d слов, а нужно "
        "%s.\n\nРаскрой подробнее то, что уже написано: добавь объяснений, "
        "разбор причин и следствий, примеры и аргументы. Не добавляй новых "
        "разделов ради объёма, не повторяй уже сказанное другими словами и "
        "не пиши вступлений о том, что ты дополняешь текст. Верни работу "
        "целиком одним текстом.\n\n# ТЕКУЩАЯ РАБОТА\n\n%s"
        % (len(answer.split()), required_volume(task_text) or "больше", answer)
    )


def work_heading(discipline: str, number: int, title: str, student: str) -> list[str]:
    """The lines a work is signed with: discipline, «КТ1: title», student.

    Long dashes are replaced here too, so a checkpoint whose official name
    contains one ("Матрица «Сопротивление - Изменение»") matches the body.
    """
    return [polish.replace_dashes(line) for line in
            (discipline, "КТ%d: %s" % (number, title), student)]


def work_filename(number: int, discipline: str, initials: str) -> str:
    """File name (without extension) like ``КТ5_Дисциплина_И.И.И``.

    A user whose profile carries no name contributes nothing rather than a
    trailing separator.
    """
    parts = ["КТ%d" % number, content.safe_filename(discipline), initials.strip()]
    return "_".join(part for part in parts if part)


# Generated works are remembered here (outside the output folder) so later
# checkpoints can build on earlier ones, while the output folder stays clean —
# it contains only the finished work files.
CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".newlxp_cache")


def discipline_dir(discipline_name: str) -> str:
    """Return (creating if needed) the output directory for a discipline."""
    path = os.path.join(OUTPUT_ROOT, content.safe_filename(discipline_name))
    os.makedirs(path, exist_ok=True)
    return path


def _works_path(discipline_name: str) -> str:
    os.makedirs(CACHE_ROOT, exist_ok=True)
    return os.path.join(CACHE_ROOT, content.safe_filename(discipline_name) + ".json")


def load_works_index(discipline_name: str) -> dict:
    """Load previously generated works keyed by checkpoint id."""
    try:
        with open(_works_path(discipline_name), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_works_index(discipline_name: str, index: dict) -> None:
    """Persist the generated-works index (best effort).

    Written to a temporary file and renamed, so an interrupted write cannot
    truncate the index of works generated so far.
    """
    path = _works_path(discipline_name)
    temporary = path + ".part"
    try:
        with open(temporary, "w", encoding="utf-8") as fh:
            json.dump(index, fh, ensure_ascii=False)
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError):
        try:
            os.remove(temporary)
        except OSError:
            pass


# Context caps in characters (Russian text is roughly 3 characters per
# token). They bound the cost of a request while keeping the materials
# complete enough for a full-length work.
MAX_TOPIC_CHARS = 6000        # a study topic quoted as background material
MAX_TASK_CHARS = 30000        # the checkpoint being written: never cut its
                              # requirements, they are the whole assignment
MAX_ATTACHMENT_CHARS = 8000   # text extracted from one attached file
MAX_PRIOR_WORK_CHARS = 4000   # one previously generated work
MAX_MATERIALS_CHARS = 80000   # the whole "materials" block


def _clip(text: str, limit: int) -> str:
    """Trim text to ``limit`` characters, marking that it was shortened."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " …[сокращено]"


# What stands between the start of a long assignment and its own steps.
_TASK_GAP = "\n\n…[середина пропущена]…\n\n"


def _clip_task(text: str, limit: int) -> str:
    """Trim a long assignment without losing its steps.

    A checkpoint's topic is a long article followed by the assignment, which
    is the last block. Cutting from the end, as :func:`_clip` does, kept the
    article and dropped exactly the part the work is graded against; here
    the last block is kept whole and the cut is made in the middle.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text.rfind("\n## ")
    tail = text[cut:].strip() if cut > 0 else ""
    room = limit - len(tail) - len(_TASK_GAP)
    if not tail or room < limit // 4:
        return _clip(text, limit)
    return text[:room].rstrip() + _TASK_GAP + tail


def _attachment_text(name: str, url: str) -> str:
    """One attached file rendered as a prompt section."""
    try:
        text = attachments.extract_text(name, url)
    except attachments.AttachmentError as exc:
        return "### Вложение «%s»\n\n(не удалось прочитать: %s)" % (name, exc)
    return "### Вложение «%s»\n\n%s" % (
        name, _clip(text, MAX_ATTACHMENT_CHARS) or "(текста нет)")


def _fetch_topic(token: str, topic_id: str) -> tuple[str, str]:
    """A topic's ``(title, full body)``, attachment text included.

    Never clips: everything that clips works from what this returns, and a
    clipped value must never reach the cache.
    """
    topic = api.get_topic_content(token, topic_id)
    title, body = content.topic_to_text(topic)
    parts = [body.strip()]
    parts += [_attachment_text(name, url)
              for name, url in content.topic_attachments(topic)
              if attachments.is_supported(name, url)]
    return title, "\n\n".join(part for part in parts if part)


def _topic_text(token: str, topic_id: str, cache: dict,
                limit: int = MAX_TOPIC_CHARS,
                keep_tail: bool = False) -> tuple[str, str]:
    """Fetch and cache a topic's ``(title, body)``, attachments included.

    The cache holds the full text; ``limit`` clips only the copy returned,
    so the same topic can be quoted briefly as background and in full when
    it is the task being written.
    """
    if topic_id not in cache:
        cache[topic_id] = _fetch_topic(token, topic_id)
    title, body = cache[topic_id]
    return title, (_clip_task(body, limit) if keep_tail else _clip(body, limit))


# Topics (and their attachments) are fetched concurrently: the API answers
# each request slowly, so sequential loading of a long course takes minutes.
PREFETCH_WORKERS = 6


def _prefetch(token: str, topic_ids: list, cache: dict) -> None:
    """Fill ``cache`` for every topic id that is not cached yet."""
    missing = [tid for tid in dict.fromkeys(topic_ids) if tid not in cache]
    if len(missing) < 2:
        return
    with ThreadPoolExecutor(max_workers=PREFETCH_WORKERS) as pool:
        # _fetch_topic, not _topic_text: the latter returns a clipped copy,
        # and storing that would cut the target assignment to the
        # background-material budget. Merging in the main thread keeps the
        # shared cache free of concurrent writes.
        results = pool.map(lambda tid: _fetch_topic(token, tid), missing)
        cache.update(zip(missing, results))


def build_prompt(
    token: str,
    topics: list[dict],
    target_index: int,
    prior_works: dict,
    cache: dict,
) -> tuple[str, str]:
    """Build the user prompt for one checkpoint.

    Returns ``(prompt, task_text)``. The prompt contains every preceding
    topic and checkpoint (plus their generated works) and then the target
    task; ``task_text`` is the task on its own, for checking the size.
    Content is clipped (see the ``MAX_*`` caps) to bound token usage.
    """
    _prefetch(token, [t["id"] for t in topics[:target_index + 1]], cache)
    materials = []
    for i in range(target_index):
        topic = topics[i]
        title, body = _topic_text(token, topic["id"], cache)
        if topic["is_checkpoint"]:
            segment = "## [Контрольная точка] %s\n\n%s" % (title, body or "(нет описания)")
            prior = prior_works.get(topic["id"])
            if prior:
                segment += ("\n\n### Ранее выполненная работа по этой КТ:\n\n"
                            + _clip(prior, MAX_PRIOR_WORK_CHARS))
        else:
            segment = "## [Учебная тема] %s\n\n%s" % (title, body or "(пусто)")
        materials.append(segment)

    target = topics[target_index]
    target_title, target_body = _topic_text(token, target["id"], cache,
                                            limit=MAX_TASK_CHARS, keep_tail=True)

    materials_text = "\n\n---\n\n".join(materials) if materials else \
        "(учебных материалов до этой контрольной точки нет)"
    # Cap the whole materials block; keep the part closest to the target.
    if len(materials_text) > MAX_MATERIALS_CHARS:
        materials_text = ("…[начало сокращено]\n\n"
                          + materials_text[-MAX_MATERIALS_CHARS:])
    return (
        "Ниже приведены учебные материалы и предыдущие контрольные точки "
        "дисциплины по порядку.\n\n"
        "# МАТЕРИАЛЫ\n\n" + materials_text +
        "\n\n# ЗАДАНИЕ: КОНТРОЛЬНАЯ ТОЧКА\n\n## %s\n\n%s\n\n" % (
            target_title, target_body or "(описание отсутствует)") +
        "Напиши самостоятельную работу по этой контрольной точке, опираясь "
        "на материалы выше.\n\n" + output_rules(target_body)
    ), target_body
