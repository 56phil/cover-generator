from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cover_engine.legacy import calculate_geometry
from cover_engine.metadata import load_metadata, save_metadata
from cover_engine.validation import validate_cover


class CoverEngineTests(unittest.TestCase):
    def paperback_data(self) -> dict[str, object]:
        return {
            "binding_type": "pb",
            "interior_type": "black_white",
            "paper_type": "white",
            "reading_direction": "ltr",
            "trim_size": "5x8",
            "page_count": 107,
            "front_cover_image": "cover/assets/base.png",
            "title": "On Proportion",
            "author_name": "Philip Huffman",
        }

    def hardcover_data(self) -> dict[str, object]:
        data = self.paperback_data()
        data.update(
            {
                "binding_type": "hc",
                "trim_size": "6x9",
                "template_full_cover_width": 13.996,
                "template_full_cover_height": 10.417,
                "template_front_cover_width": 6.197,
                "template_front_cover_height": 9.236,
                "template_spine_width": 0.421,
                "template_hinge_width": 0.394,
                "template_wrap_width": 0.591,
            }
        )
        return data

    def test_paperback_5x8_geometry(self) -> None:
        geometry = calculate_geometry(self.paperback_data())
        self.assertEqual(geometry.front_w_inches, 5.0)
        self.assertEqual(geometry.front_h_inches, 8.0)
        self.assertGreater(geometry.spine_inches, 0.0)

    def test_hardcover_uses_template_dimensions(self) -> None:
        geometry = calculate_geometry(self.hardcover_data())
        self.assertEqual(geometry.total_w_inches, 13.996)
        self.assertEqual(geometry.front_w_inches, 6.197)
        self.assertEqual(geometry.spine_inches, 0.421)

    def test_metadata_round_trips_with_schema_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cover.md"
            save_metadata(path, self.paperback_data(), "# Body\n")
            loaded, body = load_metadata(path)
        self.assertEqual(loaded["schema_version"], 1)
        self.assertEqual(loaded["kindle_write_latest"], True)
        self.assertEqual(loaded["custom_trim_width_inches"], 6.0)
        self.assertEqual(loaded["guide_x_offset_inches"], 0.0)
        self.assertEqual(loaded["font_title"], "")
        self.assertEqual(loaded["font_bold"], "")
        self.assertEqual(loaded["font_regular"], "")
        self.assertEqual(loaded["font_italic"], "")
        self.assertEqual(loaded["color_title"], "#daa520")
        self.assertEqual(loaded["color_accent"], "#eec448")
        self.assertEqual(loaded["color_body"], "#efe6d4")
        self.assertEqual(loaded["color_soft"], "#c6bca9")
        self.assertIn("# Body", body)

    def test_validation_reports_missing_image(self) -> None:
        data = self.paperback_data()
        data["front_cover_image"] = "cover/assets/not-real.png"
        issues = validate_cover(data)
        self.assertTrue(any(issue.severity == "error" and issue.field == "front_cover_image" for issue in issues))

    def test_custom_paperback_geometry(self) -> None:
        data = self.paperback_data()
        data.update(
            {
                "trim_size": "custom",
                "custom_trim_width_inches": 4.75,
                "custom_trim_height_inches": 7.25,
                "custom_spine_width_inches": 0.5,
                "custom_bleed_inches": 0.125,
            }
        )
        geometry = calculate_geometry(data)
        self.assertEqual(geometry.front_w_inches, 4.75)
        self.assertEqual(geometry.front_h_inches, 7.25)
        self.assertEqual(geometry.spine_inches, 0.5)
        self.assertAlmostEqual(geometry.total_w_inches, 10.25)


if __name__ == "__main__":
    unittest.main()
