import unittest

from newlxp import grades


def item(**fields):
    base = {
        "discipline": {"id": "d1", "name": "Математика", "maxScore": 100},
        "studyPeriod": [{"name": "1 семестр", "endDate": "2025-01-01", "status": "FINISHED"}],
        "learningGroup": {"id": "g1"},
    }
    base.update(fields)
    return base


class GradesTest(unittest.TestCase):
    def test_format_number(self):
        self.assertEqual(grades.format_number(50.0), "50")
        self.assertEqual(grades.format_number(12.5), "12.5")
        self.assertEqual(grades.format_number(None), "0")

    def test_to_grade(self):
        self.assertEqual(grades.to_grade("FOUR"), 4)
        self.assertEqual(grades.to_grade(5), 5)
        self.assertIsNone(grades.to_grade(""))

    def test_regular_discipline(self):
        row = grades.parse_discipline(item(scoreForAnsweredTasks=87, disciplineGrade="FIVE"))
        self.assertEqual((row["score"], row["max"], row["grade"]), (87, 100, 5))
        self.assertEqual(row["period"], "1 семестр")
        self.assertEqual(row["group_id"], "g1")

    def test_retake_uses_main_attempt_and_v2_grade(self):
        row = grades.parse_discipline(item(
            hasRetake=True, mainStudentAttempt={"scoreForAttempt": 61},
            retakeDisciplineGradeV2="THREE", disciplineGrade="TWO"))
        self.assertEqual((row["score"], row["grade"]), (61, 3))

    def test_retake_score_uses_retake_grade(self):
        row = grades.parse_discipline(item(
            hasRetakeV1=True, retakeScore=70, retakeDisciplineGrade="FOUR"))
        self.assertEqual((row["score"], row["grade"]), (70, 4))

    def test_ongoing_period_has_no_grade(self):
        row = grades.parse_discipline(item(
            studyPeriod=[{"name": "2 семестр", "status": "ACTIVE"}],
            scoreForAnsweredTasks=10, disciplineGrade="FIVE"))
        self.assertIsNone(row["grade"])
