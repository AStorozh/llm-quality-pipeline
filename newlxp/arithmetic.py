"""Recompute the arithmetic in a finished work.

A language model writes a number the way it writes a word: usually right,
sometimes off by one, and it never re-adds its own column. Everything here is
plain Python over the work's text, so checking costs nothing extra.

Three kinds of figure are verified:

- inline expressions: "18 / 26 = 69,2%", "300 000 / 340 ≈ 882";
- Markdown tables: a total row ("Итого", "Всего") must equal the sum (or the
  mean) of the rows above it; a column computed from two others must hold in
  every row once it holds in most; the standard marketing ones (leads =
  budget / cost per lead, clicks = budget / CPC) are known by their headers
  and checked even in a three-row table; a "days since" column must count
  from one and the same date.

Each finding is a short Russian sentence naming the place and the right
value, ready to show the student.
"""
from __future__ import annotations

import datetime as dt
import re
from itertools import permutations

from . import export, polish

# "1 234", "1 234,5", "69.2", "0,8". A space only groups thousands.
_NUMBER = r"\d{1,3}(?:[  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
# "a / b × 100% = c": the "× 100%" only turns a share into a percentage.
_EXPRESSION_RE = re.compile(
    r"(?<![\d.,])(%s)\s*([/×*:]|\s[+−-]\s)\s*(%s)(\s*[×*]\s*100\s*%%)?"
    r"\s*(=|≈)\s*(%s)\s*(%%)?"
    % (_NUMBER, _NUMBER, _NUMBER))
# The same shape at the end of a table cell, with its result in the next one:
# "CAC = 42 690 / 63" | "677,62 руб.". A trailing "%" on the right operand
# ("82 × 13,415%") is a share of one.
_CELL_EXPRESSION_RE = re.compile(
    r"(?<![\d.,])(%s)\s*([/×*:]|\s[+−-]\s)\s*(%s)\s*(%%)?(\s*[×*]\s*100\s*%%)?\s*$"
    % (_NUMBER, _NUMBER))
# A longer expression of three numbers or more: "0,3 × 10,4 + 0,5 × 9,4 = 8,6",
# "29,91 + 0,33 - 1,88 = 28,36". Checked as a whole, because its last pair
# alone ("0,5 × 9,4 = 8,6") is not what the sentence claims.
_CHAIN_OPERATOR = r"(?:[×*/:+]|\s[−-]\s)"
_CHAIN_RE = re.compile(
    r"(?<![\d.,])((?:%s)(?:\s*%s\s*(?:%s)){2,})\s*(=|≈)\s*(%s)(?!\d|[.,]\d)"
    r"\s*(%%)?(?!\s*(?:[×*/:+]|\s[−-]\s)\s*\d)"
    % (_NUMBER, _CHAIN_OPERATOR, _NUMBER, _NUMBER))
# A number and an operator right before a match: it is the tail of a longer
# expression and cannot be judged on its own.
_OPERATOR_BEFORE_RE = re.compile(r"[\d)]\s*(?:[×*/:+]|\s[−-])\s*$")
# ...and right after: "a × b = c + d = e" has c as a middle step, not a result.
_OPERATOR_AFTER_RE = re.compile(r"\s*(?:[×*/:+]|\s[−-]\s)\s*\d")
_DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_TOTAL_RE = re.compile(r"^(итого|всего|сумма|total)\b", re.I)
# Rates and averages: their total is not the sum of the column.
_RATE_HEADER_RE = re.compile(
    r"%|ctr|cr\b|cpa|cpc|cpm|cpl|cpi|roi|ltv|arpu|средн|стоимость\s+(заявки|клика|лида)|"
    r"цена|конверс|удержан|доля|чек|коэфф", re.I)

# A relation is trusted once it holds in this share of rows, and in at least
# MIN_ROWS of them; rows that break it are then reported.
MIN_SHARE = 0.75
MIN_ROWS = 3


def parse_number(text: str):
    """``"1 234,5 руб."`` → ``1234.5``; ``None`` when the cell is not a number."""
    cleaned = re.sub(r"[\s ]", "", text or "")
    cleaned = re.sub(r"(руб\.?|₽|у\.?е\.?|%|шт\.?)$", "", cleaned, flags=re.I)
    if not re.fullmatch(r"-?\d+(?:[.,]\d+)?", cleaned):
        return None
    return float(cleaned.replace(",", "."))


def _decimals(text: str) -> int:
    match = re.search(r"[.,](\d+)\s*%?\s*$", text.strip())
    return len(match.group(1)) if match else 0


def _close(shown: float, exact: float, decimals: int, loose: bool = False) -> bool:
    """Equal up to the rounding the shown figure implies."""
    tolerance = 0.5 * 10 ** -decimals + 1e-9
    if loose:  # "≈" allows a little more than rounding
        tolerance = max(tolerance, abs(exact) * 0.01)
    return abs(shown - exact) <= tolerance


def _show(value: float, decimals=None) -> str:
    """A figure as the work would print it, rounded like the shown one."""
    if decimals is not None:
        value = round(value, decimals)
    if abs(value - round(value)) < 1e-9:
        return "{:,}".format(int(round(value))).replace(",", " ")
    places = 2 if decimals is None else decimals
    text = "%.*f" % (places, value)
    return (text.rstrip("0").rstrip(".") if decimals is None else text).replace(".", ",")


def _evaluate(expression: str):
    """Value of "a × b + c / d - e" with the usual precedence, or ``None``."""
    values, signs = [], []
    pending = None  # the operator waiting for its right operand
    for token in re.finditer(r"(%s)|([×*/:+])|\s([−-])\s" % _NUMBER, expression):
        number, high_or_plus, minus = token.groups()
        if number is not None:
            value = parse_number(number)
            if value is None:
                return None
            if pending in ("×", "*"):
                values[-1] *= value
            elif pending in ("/", ":"):
                if value == 0:
                    return None
                values[-1] /= value
            else:
                values.append(value)
                signs.append(-1 if pending in ("−", "-") else 1)
            pending = None
        else:
            pending = high_or_plus or minus
    return sum(sign * value for sign, value in zip(signs, values))


def _check_chains(text: str):
    """Findings for long expressions, and the spans they cover."""
    findings, spans = [], []
    for match in _CHAIN_RE.finditer(text):
        expression, sign, result, percent = match.groups()
        exact, shown = _evaluate(expression), parse_number(result)
        spans.append(match.span())
        if exact is None or shown is None:
            continue
        # The inputs are usually rounded already; allow for that.
        tolerance = max(0.5 * 10 ** -_decimals(result) + 1e-9, 0.0075 * abs(exact))
        if sign == "≈":
            tolerance = max(tolerance, 0.01 * abs(exact))
        if abs(shown - exact) > tolerance:
            findings.append("«%s %s %s»: должно быть %s%s"
                            % (expression.strip(), sign, result.strip() + (percent or ""),
                               _show(exact, _decimals(result)), "%" if percent else ""))
    return findings, spans


def check_expressions(text: str) -> list:
    """Findings for inline expressions whose result is wrong."""
    findings, spans = _check_chains(text)
    for match in _EXPRESSION_RE.finditer(text):
        if any(start <= match.start() < end for start, end in spans):
            continue  # inside a longer expression, judged as a whole
        if _OPERATOR_BEFORE_RE.search(text[:match.start()]):
            continue  # the tail of an expression this check cannot read
        if _OPERATOR_AFTER_RE.match(text, match.end()):
            continue  # a middle step of a longer line, not its result
        left, op, right, scale, sign, result, percent = match.groups()
        a, b, shown = parse_number(left), parse_number(right), parse_number(result)
        op = op.strip()
        if a is None or b is None or shown is None:
            continue
        if op in "/:":
            if b == 0:
                continue
            exact = a / b * (100 if (percent or scale) else 1)
        elif op in "×*":
            exact = a * b * (100 if scale else 1)
        elif op == "+":
            exact = a + b
        else:
            exact = a - b
        accepted = [exact]
        if op in "/:" and percent and not scale:
            # "21 / 12 = 1,75%" is also right when 21 and 12 are already
            # percentages: the mean of twelve monthly returns.
            accepted.append(a / b)
        if not any(_close(shown, value, _decimals(result), loose=sign == "≈")
                   for value in accepted):
            findings.append("«%s»: должно быть %s%s"
                            % (match.group(0).strip(), _show(exact, _decimals(result)),
                               "%" if percent else ""))
    return findings


def check_row_expressions(rows: list) -> list:
    """A cell that ends in "a / b" must be followed by the right result.

    Step-by-step solutions are often laid out as a table, the working in
    one cell and the answer in the next, which the inline check cannot see.
    A cell with no "=" is only trusted for division and multiplication:
    "1 - 3" in a period column is not a subtraction.
    """
    findings = []
    for row in rows:
        for cell, result in zip(row, row[1:]):
            match = _CELL_EXPRESSION_RE.search(cell.strip())
            shown = parse_number(result)
            if not match or shown is None:
                continue
            left, op, right, right_percent, scale = match.groups()
            op = op.strip()
            a, b = parse_number(left), parse_number(right)
            if a is None or b is None or (op in "+−-" and "=" not in cell):
                continue
            if right_percent:  # "82 × 13,415%": a share of one
                if op not in "×*":
                    continue
                b = b / 100
            if op in "/:":
                if b == 0:
                    continue
                exact = a / b
            elif op in "×*":
                exact = a * b
            elif op == "+":
                exact = a + b
            else:
                exact = a - b
            if scale:
                exact *= 100
            # "677,14 руб.": the unit must not hide the decimals from the check
            decimals = _decimals(re.sub(r"\s*(?:руб\.?|₽|у\.?\s?е\.?|шт\.?)\s*$", "",
                                       result.strip(), flags=re.I))
            candidates = [exact]
            if op in "/:" and not scale:
                # a share written as "75" or as "75%"
                candidates.append(exact * 100)
            if not any(_close(shown, value, decimals) for value in candidates):
                findings.append("«%s = %s»: должно быть %s"
                                % (cell.strip().split("=")[-1].strip(), result.strip(),
                                   _show(candidates[-1] if result.strip().endswith("%")
                                         and len(candidates) > 1 else exact, decimals)))
    return findings


def _tables(text: str) -> list:
    return [rows for kind, rows in export.parse_blocks(text) if kind == "table"]


def _label(row: list) -> str:
    return row[0] if row and row[0] else "строка"


def check_totals(rows: list) -> list:
    """A total row must be the sum (or the mean) of the rows above it."""
    header, findings = rows[0], []
    body = []
    for row in rows[1:]:
        if not _TOTAL_RE.match(row[0] or ""):
            body.append(row)
            continue
        for col in range(1, len(header)):
            shown = parse_number(row[col])
            values = [parse_number(r[col]) for r in body]
            if shown is None or not values or None in values:
                continue
            if _RATE_HEADER_RE.search(header[col]):
                continue
            total, decimals = sum(values), _decimals(row[col])
            if not (_close(shown, total, decimals)
                    or _close(shown, total / len(values), decimals, loose=True)):
                findings.append("таблица «%s», строка «%s»: %s, а сумма строк выше - %s"
                                % (header[col], row[0], row[col], _show(total)))
        body = []  # a second block may follow with its own total
    return findings


_OPERATIONS = (
    ("/", lambda a, b: a / b if b else None),
    ("×", lambda a, b: a * b),
    ("+", lambda a, b: a + b),
    ("-", lambda a, b: a - b),
    ("/ ×100", lambda a, b: a / b * 100 if b else None),
)


def check_derived_columns(rows: list) -> list:
    """A column computed from two others must agree in every row.

    The relation is not declared anywhere, so it is inferred: it counts only
    when it holds in most rows, and then the rows that break it are wrong.
    """
    header = rows[0]
    body = [r for r in rows[1:] if not _TOTAL_RE.match(r[0] or "")]
    columns = range(len(header))
    numeric = [c for c in columns
               if sum(parse_number(r[c]) is not None for r in body) >= MIN_ROWS]
    findings, explained = [], set()
    # Rightmost first: a computed column usually follows its inputs, and once
    # "Сумма = Цена × Кол-во" is found, "Цена = Сумма / Кол-во" is the same
    # relation and must not report the same row again.
    for target in reversed(numeric):
        if target in explained:
            continue
        for a, b in permutations([c for c in numeric if c != target], 2):
            for name, op in _OPERATIONS:
                held, broken = 0, []
                for row in body:
                    x, y, shown = (parse_number(row[a]), parse_number(row[b]),
                                   parse_number(row[target]))
                    if None in (x, y, shown):
                        continue
                    exact = op(x, y)
                    if exact is None:
                        continue
                    if _close(shown, exact, _decimals(row[target]), loose=True):
                        held += 1
                    else:
                        broken.append((row, exact))
                checked = held + len(broken)
                # Trivial matches (all zeros, a column equal to itself) and
                # coincidences in two rows prove nothing.
                if held < MIN_ROWS or held < MIN_SHARE * checked or target in explained:
                    continue
                explained.update((target, a, b))
                for row, exact in broken:
                    findings.append("таблица, «%s», %s: %s, а %s %s %s = %s"
                                    % (_label(row), header[target], row[target],
                                       header[a], name.split()[0], header[b], _show(exact)))
    return findings


# Count = money / price per unit, recognised by the column headers.
# Word starts only: "отклик" is a response rate, not a number of clicks.
_COUNT_HEADER_RE = re.compile(
    r"(?<![а-яё])(?:заяв|лид|клик|продаж|покуп|установ|конверси[йи]\b)", re.I)
_MONEY_HEADER_RE = re.compile(r"бюджет|расход|затрат", re.I)
_PRICE_HEADER_RE = re.compile(r"стоимост|\bcp[acli]\b|\bcpc\b|цена", re.I)


def check_known_formulas(rows: list) -> list:
    """Leads = budget / cost per lead, and the like, in every row."""
    header, findings = rows[0], []
    body = [r for r in rows[1:] if not _TOTAL_RE.match(r[0] or "")]
    for target, title in enumerate(header):
        if not _COUNT_HEADER_RE.search(title) or _PRICE_HEADER_RE.search(title):
            continue
        money = [c for c, h in enumerate(header) if _MONEY_HEADER_RE.search(h)]
        price = [c for c, h in enumerate(header)
                 if _PRICE_HEADER_RE.search(h) and _COUNT_HEADER_RE.search(h)]
        if len(money) != 1 or len(price) != 1:
            continue
        a, b = money[0], price[0]
        for row in body:
            x, y, shown = (parse_number(row[a]), parse_number(row[b]),
                           parse_number(row[target]))
            if None in (x, y, shown) or not y:
                continue
            if not _close(shown, x / y, _decimals(row[target]), loose=True):
                findings.append("таблица, «%s», %s: %s, а %s / %s = %s"
                                % (_label(row), title, row[target], header[a],
                                   header[b], _show(x / y, 0)))
    return findings


def check_day_counts(rows: list) -> list:
    """"Days since the last purchase" must count from one date in every row."""
    header = rows[0]
    body = [r for r in rows[1:] if not _TOTAL_RE.match(r[0] or "")]
    findings = []
    for d in range(len(header)):
        dates = [_date(r[d]) for r in body]
        if sum(x is not None for x in dates) < MIN_ROWS:
            continue
        for n in range(len(header)):
            if n == d or not re.search(r"дн", header[n], re.I):
                continue
            pairs = [(row, date, parse_number(row[n])) for row, date in zip(body, dates)]
            pairs = [(row, date, days) for row, date, days in pairs
                     if date is not None and days is not None]
            refs = [date + dt.timedelta(days=int(days)) for _, date, days in pairs]
            if len(refs) < MIN_ROWS:
                continue
            reference = max(set(refs), key=refs.count)
            if refs.count(reference) < MIN_SHARE * len(refs):
                continue
            for (row, date, _days), ref in zip(pairs, refs):
                if ref != reference:
                    findings.append("таблица, «%s», %s: %s, а от %s до %s - %d"
                                    % (_label(row), header[n], row[n],
                                       row[d], reference.strftime("%d.%m.%Y"),
                                       (reference - date).days))
    return findings


def _date(text: str):
    match = _DATE_RE.match((text or "").strip())
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def find_errors(text: str) -> list:
    """Every arithmetic finding in the work, inline and in its tables."""
    text = polish.replace_latex(text)
    findings = check_expressions(text)
    for rows in _tables(text):
        if len(rows) < 2:
            continue
        findings += check_totals(rows)
        findings += check_row_expressions(rows)
        known = check_known_formulas(rows)
        findings += known or check_derived_columns(rows)
        findings += check_day_counts(rows)
    return findings
