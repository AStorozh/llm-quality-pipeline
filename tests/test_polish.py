import unittest

from newlxp import polish

NAME = "Петров Пётр Петрович"


class CleanAnswerTest(unittest.TestCase):
    def clean(self, text):
        return polish.clean_answer(text, NAME)

    def test_trailing_offer_is_removed(self):
        text = ("Основной текст работы.\n\n"
                "Если нужно, я могу сразу оформить это же в виде более "
                "«официального» контрольного документа с нумерацией.")
        self.assertEqual(self.clean(text), "Основной текст работы.")

    def test_other_offer_wordings(self):
        for tail in ("Если хотите, могу дополнить разбор примерами.",
                     "При необходимости могу оформить таблицей.",
                     "Готов оформить это приложением.",
                     "Могу также подготовить презентацию."):
            self.assertEqual(self.clean("Текст.\n\n" + tail), "Текст.", tail)

    def test_several_trailing_offers(self):
        text = "Текст.\n\nЕсли нужно, могу расширить.\n\nГотов дополнить таблицей."
        self.assertEqual(self.clean(text), "Текст.")

    def test_trailing_signature_is_removed(self):
        for tail in (NAME, "**%s**" % NAME, "Петров П.П.", "Петров П. П."):
            self.assertEqual(self.clean("Вывод работы.\n\n" + tail), "Вывод работы.",
                             tail)

    def test_self_introduction_loses_the_name(self):
        text = "Я, %s, рассматриваю ситуацию компании." % NAME
        self.assertEqual(self.clean(text), "Я рассматриваю ситуацию компании.")

    def test_normal_text_is_untouched(self):
        for text in (
            "Если нужно изменить структуру, компания проводит реорганизацию.",
            "Петров как фамилия здесь ни при чём, это обычное предложение "
            "в конце работы.",
            "Могут возникнуть сложности с координацией подразделений.",
            "Я рассматриваю задачу как управленческую.",
        ):
            self.assertEqual(self.clean(text), text)

    def test_conclusion_is_not_mistaken_for_an_offer(self):
        text = ("Текст.\n\nЕсли компания не управляет изменениями, она теряет "
                "управляемость и в итоге проигрывает более гибким конкурентам.")
        self.assertEqual(self.clean(text), text)

    def test_works_without_a_name(self):
        text = "Я, Иванов Иван, пишу.\n\nЕсли нужно, могу дополнить."
        self.assertEqual(polish.clean_answer(text), "Я, Иванов Иван, пишу.")

    def test_empty_and_whitespace(self):
        self.assertEqual(self.clean(""), "")
        self.assertEqual(self.clean("   \n\n  "), "")


class DashTest(unittest.TestCase):
    def test_long_dashes_become_hyphens(self):
        cases = {
            "мысль \u2014 продолжение": "мысль - продолжение",
            "1500\u20132000 слов": "1500-2000 слов",
            "это \u2012 так, а то \u2212 иначе": "это - так, а то - иначе",
            "\u2014 Да, \u2014 сказал он.": "- Да, - сказал он.",
        }
        for text, expected in cases.items():
            self.assertEqual(polish.replace_dashes(text), expected, text)

    def test_hyphens_and_text_survive(self):
        for text in ("кое-что, что-то, из-за", "список:\n- пункт\n- пункт", ""):
            self.assertEqual(polish.replace_dashes(text), text)

    def test_clean_answer_applies_it(self):
        self.assertEqual(polish.clean_answer("Вывод \u2014 он важен."),
                         "Вывод - он важен.")


class PromptHasNoLongDashesTest(unittest.TestCase):
    def test_prompt_does_not_use_the_dashes_it_forbids(self):
        # A model copies punctuation from its instructions, so the prompt
        # itself must be clean apart from the two it quotes as examples.
        from newlxp import coursework

        for text in (coursework.SYSTEM_PROMPT, coursework.output_rules(),
                     coursework.output_rules("эссе объёмом 1500 слов"),
                     coursework.SLIDES_INSTRUCTION, coursework._AUTHOR_INSTRUCTION):
            without_examples = text.replace("\u2014 и \u2013", "")
            self.assertEqual(polish.replace_dashes(without_examples), without_examples)
