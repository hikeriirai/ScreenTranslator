from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import ImageFont

import main


class OcrTextTests(unittest.TestCase):
    def test_to_first_person_en_contractions_and_subject_pronouns(self) -> None:
        examples = {
            "you're ready.": "I'm ready.",
            "You've got this.": "I've got this.",
            "You'll understand.": "I'll understand.",
            "You'd know.": "I'd know.",
            "You are ready.": "I am ready.",
            "You were right.": "I was right.",
            "You have time.": "I have time.",
            "You has time.": "I have time.",
            "You grab the handle.": "I grab the handle.",
            "You open the door.": "I open the door.",
            "You vanish.": "I vanish.",
            "You can't see anything.": "I can't see anything.",
        }

        for source, expected in examples.items():
            with self.subTest(source=source):
                self.assertEqual(main.to_first_person_en(source), expected)

    def test_to_first_person_en_possessive_and_object_pronouns(self) -> None:
        examples = {
            "Your hand is shaking.": "My hand is shaking.",
            "That book is yours.": "That book is mine.",
            "You should trust yourself.": "I should trust myself.",
            "She looks at you.": "She looks at me.",
            "I saw you.": "I saw me.",
        }

        for source, expected in examples.items():
            with self.subTest(source=source):
                self.assertEqual(main.to_first_person_en(source), expected)

    def test_to_first_person_en_preserves_quoted_and_parenthesized_text(self) -> None:
        examples = (
            ('He said, "You are late."', 'He said, "You are late."'),
            ("He said, “You are late.”", "He said, “You are late.”"),
            ("She replied, «You are late.»", "She replied, «You are late.»"),
            ("彼は「You are late」と言った。", "彼は「You are late」と言った。"),
            ("You (you are late) should leave.", "I (you are late) should leave."),
            (
                '(The word "you)" is quoted) You grab the handle.',
                '(The word "you)" is quoted) I grab the handle.',
            ),
        )

        for source, expected in examples:
            with self.subTest(source=source):
                self.assertEqual(main.to_first_person_en(source), expected)

    def test_to_first_person_en_keeps_inverted_question_unchanged(self) -> None:
        self.assertEqual(main.to_first_person_en("Are you okay?"), "Are you okay?")

    def test_to_first_person_en_returns_non_string_input_unchanged(self) -> None:
        for value in (None, 42, [], {"text": "You are late."}):
            with self.subTest(value=value):
                self.assertIs(main.to_first_person_en(value), value)

    def test_to_first_person_en_returns_original_on_internal_error(self) -> None:
        source = "You are late."
        with patch.object(
            main,
            "_replace_unprotected_first_person",
            side_effect=RuntimeError("unexpected failure"),
        ):
            self.assertEqual(main.to_first_person_en(source), source)

    def test_tk_window_geometry_formats_positive_and_negative_positions(self) -> None:
        self.assertEqual(main.tk_position_geometry(1, 0), "+1+0")
        self.assertEqual(main.tk_position_geometry(-24, 16), "-24+16")
        self.assertEqual(main.tk_position_geometry(-4, -9), "-4-9")

    def test_context_quiet_period_allows_another_ocr_pass(self) -> None:
        self.assertEqual(main.ocr_context_quiet_period(0.2), 0.65)
        self.assertEqual(main.ocr_context_quiet_period(0.8), 1.2)
        self.assertEqual(main.ocr_context_quiet_period(1.5), 1.2)

    def test_translation_overlay_prefers_space_outside_source_text(self) -> None:
        source = {"left": 500, "top": 400, "width": 500, "height": 100}
        monitor = {"left": 0, "top": 0, "width": 1920, "height": 1080}

        x, y = main.place_overlay_away_from_source(
            source,
            420,
            120,
            monitor,
        )

        self.assertEqual((x, y), (500, 516))
        overlap_width = max(
            0,
            min(x + 420, source["left"] + source["width"])
            - max(x, source["left"]),
        )
        overlap_height = max(
            0,
            min(y + 120, source["top"] + source["height"])
            - max(y, source["top"]),
        )
        self.assertEqual(overlap_width * overlap_height, 0)

    def test_translation_overlay_avoids_source_even_near_monitor_edge(self) -> None:
        source = {"left": 500, "top": 900, "width": 500, "height": 100}
        monitor = {"left": 0, "top": 0, "width": 1920, "height": 1080}

        x, y = main.place_overlay_away_from_source(
            source,
            420,
            120,
            monitor,
        )

        overlap_width = max(
            0,
            min(x + 420, source["left"] + source["width"])
            - max(x, source["left"]),
        )
        overlap_height = max(
            0,
            min(y + 120, source["top"] + source["height"])
            - max(y, source["top"]),
        )
        self.assertEqual(overlap_width * overlap_height, 0)
        self.assertGreaterEqual(y, monitor["top"])
        self.assertLessEqual(y + 120, monitor["top"] + monitor["height"])

    def test_balanced_ocr_profile_uses_reduced_frame_and_multiple_threads(self) -> None:
        self.assertEqual(
            main.SPEED_MODES["Сбалансированно · 0,8 с · 3 потока"],
            (0.8, 3, 960),
        )

    def test_background_priority_is_applied_to_current_worker_thread(self) -> None:
        get_current_thread = Mock(return_value=123)
        set_thread_priority = Mock(return_value=1)
        kernel32 = SimpleNamespace(
            GetCurrentThread=get_current_thread,
            SetThreadPriority=set_thread_priority,
        )

        with patch.object(
            main.ctypes,
            "windll",
            SimpleNamespace(kernel32=kernel32),
            create=True,
        ):
            main.lower_current_thread_priority()

        set_thread_priority.assert_called_once_with(123, -1)

    def test_main_window_drag_crosses_virtual_desktop_monitors(self) -> None:
        root = SimpleNamespace(
            winfo_id=lambda: 456,
            winfo_x=lambda: 100,
            winfo_y=lambda: 120,
            winfo_width=lambda: 500,
            winfo_height=lambda: 620,
        )
        app = SimpleNamespace(root=root)

        main.ScreenTranslator._begin_window_drag(
            app,
            SimpleNamespace(x_root=140, y_root=160),
        )
        with (
            patch.object(main, "get_native_toplevel_handle", return_value=456),
            patch.object(main, "set_native_window_pos") as set_position,
        ):
            main.ScreenTranslator._drag_window(
                app,
                SimpleNamespace(x_root=-1100, y_root=250),
            )

        set_position.assert_called_once_with(456, -1140, 210, 500, 620, 0x0014)

    def test_main_window_release_persists_position_on_second_monitor(self) -> None:
        root = SimpleNamespace(winfo_id=lambda: 456)
        app = SimpleNamespace(root=root, status_var=SimpleNamespace(set=Mock()))
        second_monitor_bounds = (-1280, 100, -780, 720)
        with (
            patch.object(main, "get_native_toplevel_handle", return_value=456),
            patch.object(
                main,
                "get_native_window_bounds",
                return_value=second_monitor_bounds,
            ),
            patch.object(main, "save_window_position") as save_position,
        ):
            main.ScreenTranslator._finish_window_drag(
                app,
                SimpleNamespace(),
            )

        save_position.assert_called_once_with(
            main.WINDOW_POSITION_PATH,
            -1280,
            100,
        )
        self.assertIsNone(app._panel_drag_origin)

    def test_saved_panel_position_round_trips_negative_monitor_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ScreenTranslator" / "window.json"
            main.save_window_position(path, -1280, 100)

            self.assertEqual(main.load_saved_window_position(path), (-1280, 100))

    def test_saved_panel_position_is_clamped_to_nearest_available_monitor(self) -> None:
        monitors = [
            {"left": -1280, "top": 100, "width": 1280, "height": 900},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ]

        self.assertEqual(
            main.clamp_window_position_to_monitors(
                -1500,
                100,
                500,
                620,
                monitors,
            ),
            (-1280, 100),
        )

    def test_saved_panel_position_moves_when_its_monitor_is_disconnected(self) -> None:
        monitors = [
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ]

        self.assertEqual(
            main.clamp_window_position_to_monitors(
                -1280,
                100,
                500,
                620,
                monitors,
            ),
            (0, 100),
        )

    def test_cuda_detection_rejects_ct2_device_without_torch_cuda_runtime(self) -> None:
        ctranslate2 = SimpleNamespace(get_cuda_device_count=Mock(return_value=1))
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=Mock(return_value=False)))

        self.assertFalse(main.is_cuda_translation_available(ctranslate2, torch))
        ctranslate2.get_cuda_device_count.assert_not_called()

    def test_cuda_detection_falls_back_if_torch_cuda_probe_raises(self) -> None:
        ctranslate2 = SimpleNamespace(get_cuda_device_count=Mock(return_value=1))
        torch = SimpleNamespace(
            cuda=SimpleNamespace(
                is_available=Mock(side_effect=RuntimeError("CUDA runtime unavailable"))
            )
        )

        self.assertFalse(main.is_cuda_translation_available(ctranslate2, torch))
        ctranslate2.get_cuda_device_count.assert_not_called()

    def test_cuda_detection_falls_back_if_ctranslate2_probe_raises(self) -> None:
        ctranslate2 = SimpleNamespace(
            get_cuda_device_count=Mock(side_effect=OSError("CUDA DLL load failed"))
        )
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=Mock(return_value=True)))

        self.assertFalse(main.is_cuda_translation_available(ctranslate2, torch))

    def test_cuda_detection_requires_ct2_device_and_torch_runtime(self) -> None:
        ctranslate2 = SimpleNamespace(get_cuda_device_count=Mock(return_value=1))
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=Mock(return_value=True)))

        self.assertTrue(main.is_cuda_translation_available(ctranslate2, torch))
        ctranslate2.get_cuda_device_count.assert_called_once_with()

    def test_supported_source_languages_are_explicit_and_limited(self) -> None:
        self.assertEqual(main.LANGUAGES, {"Английский": "en", "Японский": "ja"})
        self.assertEqual(set(main.ARGOS_PATHS), {"en", "ja"})
        self.assertNotIn("auto", main.TRANSLATION_CODES)

    def test_context_buffer_waits_for_stable_complete_text(self) -> None:
        buffer = main.OCRContextBuffer(quiet_period=0.5, clear_period=1.0)
        partial = [
            {
                "text": "The door is",
                "language": "en",
                "bounds": {"left": 10, "top": 10, "width": 100, "height": 20},
            }
        ]
        complete = [
            {
                "text": "The door is open.",
                "language": "en",
                "bounds": {"left": 10, "top": 10, "width": 180, "height": 20},
            }
        ]

        buffer.observe(partial, 0.0)
        buffer.observe(complete, 0.2)
        self.assertIsNone(buffer.poll(0.69))
        self.assertEqual(buffer.poll(0.71), complete)
        self.assertIsNone(buffer.poll(1.2))

    def test_context_buffer_flushes_short_text_when_it_disappears(self) -> None:
        buffer = main.OCRContextBuffer(quiet_period=0.5, clear_period=1.0)
        transient = [
            {
                "text": "New area",
                "language": "en",
                "bounds": {"left": 10, "top": 10, "width": 100, "height": 20},
            }
        ]

        buffer.observe(transient, 0.0)
        buffer.observe([], 0.2)

        self.assertEqual(buffer.poll(0.2), transient)
        self.assertIsNone(buffer.poll(0.8))
        self.assertEqual(buffer.poll(1.21), [])

    def test_context_buffer_does_not_emit_identical_text_repeatedly(self) -> None:
        buffer = main.OCRContextBuffer(quiet_period=0.5, clear_period=1.0)
        same_text = [
            {
                "text": "Same sentence.",
                "language": "ja",
                "bounds": {"left": 10, "top": 10, "width": 100, "height": 20},
            }
        ]

        buffer.observe(same_text, 0.0)
        self.assertEqual(buffer.poll(0.5), same_text)
        buffer.observe(same_text, 1.0)

        self.assertIsNone(buffer.poll(2.0))

    def test_context_buffer_reset_allows_reselected_same_text(self) -> None:
        buffer = main.OCRContextBuffer(quiet_period=0.5, clear_period=1.0)
        same_text = [
            {
                "text": "The gate is open.",
                "language": "en",
                "bounds": {"left": 10, "top": 10, "width": 100, "height": 20},
            }
        ]

        buffer.observe(same_text, 0.0)
        self.assertEqual(buffer.poll(0.5), same_text)
        buffer.reset()
        buffer.observe(same_text, 1.0)

        self.assertEqual(buffer.poll(1.5), same_text)

    def test_argos_install_invalidates_cached_installed_languages(self) -> None:
        package = SimpleNamespace(install_from_path=Mock())
        clear_language_cache = Mock()
        argos_translate = SimpleNamespace(
            get_installed_languages=SimpleNamespace(
                cache_clear=clear_language_cache
            )
        )

        main.install_argos_package(package, "model.argosmodel", argos_translate)

        package.install_from_path.assert_called_once_with("model.argosmodel")
        clear_language_cache.assert_called_once_with()

    def test_normalize_ocr_text_collapses_whitespace_and_case(self) -> None:
        self.assertEqual(main.normalize_ocr_text("  New\tWORLD\n "), "new world")

    def test_translation_retries_recursion_error_with_smaller_text_chunks(self) -> None:
        def translate(text: str) -> str:
            if len(text) > 10:
                raise RecursionError("maximum recursion depth exceeded")
            return text.upper()

        result = main.translate_with_recursion_fallback(
            "alpha beta gamma",
            translate,
            max_chars=8,
        )

        self.assertEqual(result, "ALPHA BETA GAMMA")

    def test_translation_fallback_splits_a_single_long_ocr_token(self) -> None:
        def translate(text: str) -> str:
            if len(text) > 6:
                raise RecursionError("maximum recursion depth exceeded")
            return text.upper()

        result = main.translate_with_recursion_fallback(
            "abcdefghij",
            translate,
            max_chars=4,
        )

        self.assertEqual(result, "ABCD EFGH IJ")

    def test_translation_fallback_propagates_recursion_error_for_one_character(self) -> None:
        with self.assertRaises(RecursionError):
            main.translate_with_recursion_fallback(
                "x",
                lambda _text: (_ for _ in ()).throw(RecursionError("still failing")),
            )

    def test_hud_labels_are_low_value_but_sentence_context_is_kept(self) -> None:
        self.assertTrue(main.is_low_value_game_text("HP 120"))
        self.assertTrue(main.is_low_value_game_text("VIT / STR"))
        self.assertTrue(main.is_low_value_game_text("ARMOR 12"))
        self.assertTrue(main.is_low_value_game_text("CRIT DMG +36%"))
        self.assertTrue(main.is_low_value_game_text("MIN DMG +0%"))
        self.assertTrue(main.is_low_value_game_text("MP COST -0%"))
        self.assertTrue(main.is_low_value_game_text("60 FPS"))
        self.assertFalse(main.is_low_value_game_text("Your HP is low"))
        self.assertFalse(main.is_low_value_game_text("Critical damage can be fatal"))

    def test_bottom_navigation_row_is_filtered_without_removing_story_text(self) -> None:
        lines = [
            ("This is strange...", 0.9, 140, 80, 170, 260),
            ("I feel like I've been through here before.", 0.9, 190, 60, 220, 700),
            ("History", 0.9, 278, 228, 294, 272),
            ("Skip", 0.9, 278, 300, 294, 338),
            ("Automatic", 0.9, 278, 366, 294, 442),
            ("Settings", 0.9, 278, 486, 294, 550),
        ]

        filtered = main.filter_bottom_navigation_lines(lines, frame_height=300)

        self.assertEqual(
            [line[0] for line in filtered],
            ["This is strange...", "I feel like I've been through here before."],
        )

    def test_single_bottom_word_is_not_dropped_without_navigation_row(self) -> None:
        line = ("History", 0.9, 278, 228, 294, 272)

        self.assertEqual(
            main.filter_bottom_navigation_lines([line], frame_height=300),
            [line],
        )

    def test_combined_bottom_menu_labels_are_filtered(self) -> None:
        menu = ("History Skip Automatic Settings", 0.9, 278, 228, 294, 550)
        story = ("I want to skip this.", 0.9, 190, 60, 220, 360)

        self.assertEqual(
            main.filter_bottom_navigation_lines(
                [menu, story],
                frame_height=300,
            ),
            [story],
        )

    def test_standalone_numbers_survive_until_context_grouping(self) -> None:
        self.assertTrue(main.is_ocr_candidate("1955."))
        self.assertTrue(main.is_ocr_candidate("120"))
        self.assertFalse(main.is_ocr_candidate("..."))

        lines = [
            ("opened on seventeenth of July", 0.9, 10, 10, 30, 240),
            ("1955.", 1.0, 10, 245, 30, 300),
        ]
        groups = main.group_ocr_lines(lines)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][0], "opened on seventeenth of July 1955.")

        groups = main.group_ocr_lines(
            [
                ("opened on seventeenth of July", 0.9, 10, 10, 30, 240),
                ("1955.", 1.0, 10, 245, 30, 300),
                ("120", 1.0, 100, 10, 120, 40),
            ]
        )
        translatable_groups = [
            group for group in groups if not main.is_low_value_game_text(group[0])
        ]
        self.assertEqual(len(translatable_groups), 1)
        self.assertIn("1955.", translatable_groups[0][0])

        hud_groups = main.group_ocr_lines(
            [
                ("HP", 0.9, 100, 10, 120, 35),
                ("120", 0.9, 100, 40, 120, 70),
            ]
        )
        self.assertEqual(len(hud_groups), 1)
        self.assertTrue(main.is_low_value_game_text(hud_groups[0][0]))

    def test_overlapping_small_japanese_readings_are_removed(self) -> None:
        lines = [
            ("にほんご", 0.6, 10, 50, 20, 110),
            ("日本語を", 0.99, 16, 48, 40, 130),
            ("話しましょう。", 0.95, 16, 140, 40, 260),
        ]

        filtered = main.remove_overlapping_ruby_readings(lines)

        self.assertEqual([line[0] for line in filtered], ["日本語を", "話しましょう。"])

    def test_grouping_keeps_vertical_menu_items_separate(self) -> None:
        lines = [
            ("LOADOUT", 0.99, 20, 20, 40, 180),
            ("APPEARANCE", 0.98, 70, 20, 90, 190),
            ("INVENTORY", 0.97, 120, 20, 140, 190),
        ]

        groups = main.group_ocr_lines(lines)

        self.assertEqual([group[0] for group in groups], [
            "LOADOUT",
            "APPEARANCE",
            "INVENTORY",
        ])

    def test_grouping_joins_fragments_and_neighboring_lines(self) -> None:
        lines = [
            ("The", 0.9, 10, 10, 30, 60),
            ("ancient", 0.8, 10, 65, 30, 130),
            ("door opens.", 0.95, 35, 10, 55, 120),
        ]

        groups = main.group_ocr_lines(lines)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][0], "The ancient door opens.")

    def test_grouping_keeps_overlapping_lines_in_reading_order(self) -> None:
        lines = [
            ("The first line continues", 0.9, 10, 10, 34, 240),
            ("on the next line.", 0.9, 30, 10, 54, 180),
        ]

        groups = main.group_ocr_lines(lines)

        self.assertEqual(len(groups), 1)
        self.assertEqual(
            groups[0][0],
            "The first line continues on the next line.",
        )

    def test_grouping_keeps_dialogue_context_across_wrapped_lines(self) -> None:
        lines = [
            ("Quite frankly, his voice is the last", 0.9, 10, 70, 54, 610),
            ("thing I want to be hearing right now,", 0.9, 60, 40, 104, 710),
        ]

        groups = main.group_ocr_lines(lines)

        self.assertEqual(len(groups), 1)
        self.assertEqual(
            groups[0][0],
            "Quite frankly, his voice is the last thing I want to be hearing right now,",
        )

    def test_default_paragraph_spacing_keeps_loose_printed_text_together(self) -> None:
        lines = [
            ("A printed paragraph continues", 0.9, 10, 10, 34, 260),
            ("on its next line.", 0.9, 44, 10, 68, 180),
        ]

        groups = main.group_ocr_lines(lines)

        self.assertEqual(len(groups), 1)
        self.assertIn("on its next line.", groups[0][0])

    def test_same_row_name_is_not_joined_to_distant_hud_stats(self) -> None:
        lines = [
            ("HP", 1.0, 324, 258, 354, 304),
            ("100", 1.0, 323, 353, 363, 429),
            ("MP", 1.0, 324, 528, 354, 580),
            ("100", 1.0, 321, 623, 363, 699),
            ("Hikari Irai", 0.63, 302, 935, 343, 1133),
        ]

        groups = main.group_ocr_lines(lines)

        self.assertIn("Hikari Irai", [group[0] for group in groups])
        stat_group = next(group[0] for group in groups if "HP" in group[0])
        self.assertTrue(main.is_low_value_game_text(stat_group))
        self.assertFalse(
            any(
                "Hikari Irai" in group[0] and "HP" in group[0]
                for group in groups
            )
        )

    def test_japanese_grouping_keeps_rules_separate_and_joins_fragments(self) -> None:
        lines = [
            ("教室では", 1.0, 10, 20, 40, 100),
            ("日本語を", 1.0, 10, 110, 40, 190),
            ("話しましょう。", 0.9, 10, 200, 40, 310),
            ("私物を", 1.0, 55, 20, 85, 100),
            ("置いてください。", 0.9, 55, 110, 85, 250),
        ]

        groups = main.group_ocr_lines(
            lines,
            paragraph_gap_ratio=1.25,
            horizontal_gap_ratio=8.0,
            separate_cjk_fragments=True,
        )

        self.assertEqual(
            [group[0] for group in groups],
            ["教室では日本語を話しましょう。", "私物を置いてください。"],
        )

    def test_grouping_does_not_attach_heading_to_body_text(self) -> None:
        lines = [
            ("Strong or Weak", 0.99, 193, 187, 232, 395),
            ("There was a proud teak tree in the forest.", 0.9, 240, 60, 266, 540),
            ("He was tall and strong.", 0.9, 264, 42, 295, 302),
        ]

        groups = main.group_ocr_lines(lines)

        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0][0], "Strong or Weak")
        self.assertEqual(
            groups[1][0],
            "There was a proud teak tree in the forest. He was tall and strong.",
        )


class OverlayRegressionTests(unittest.TestCase):
    def test_resize_motion_is_throttled_and_release_renders_exact_size(self) -> None:
        scheduled: list[tuple[int, object]] = []
        window = SimpleNamespace(
            after=Mock(
                side_effect=lambda delay, callback: (
                    scheduled.append((delay, callback)) or "resize-job"
                )
            ),
            after_cancel=Mock(),
        )
        record = {
            "drag_origin": (100, 100, 10, 20, 0, 0, True, 300, 100),
            "resizing": True,
            "size": (300, 100),
            "resize_after_id": None,
            "window": window,
        }
        overlay = SimpleNamespace(
            current_translations=[{"text": "Translated text"}],
            line_windows=[record],
            show_translations=Mock(),
        )
        overlay._render_resized_line = lambda item, preview=True: (
            main.TranslationOverlay._render_resized_line(
                overlay, item, preview=preview
            )
        )

        main.TranslationOverlay.drag_line(
            overlay,
            record,
            SimpleNamespace(x_root=280, y_root=140),
        )
        main.TranslationOverlay.drag_line(
            overlay,
            record,
            SimpleNamespace(x_root=400, y_root=200),
        )

        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0][0], main.OVERLAY_RESIZE_RENDER_DELAY_MS)
        self.assertEqual(record["size"], (600, 200))
        overlay.show_translations.assert_not_called()

        scheduled[0][1]()
        self.assertEqual(record["render_size"], (608, 204))
        overlay.show_translations.assert_called_once_with(
            overlay.current_translations,
            only_record=record,
        )

        main.TranslationOverlay.finish_line_drag(
            overlay, record, SimpleNamespace()
        )

        self.assertEqual(record["render_size"], None)
        self.assertIsNone(record["resize_after_id"])
        self.assertEqual(overlay.show_translations.call_count, 2)

    def test_pointer_poll_does_not_reapply_unchanged_click_through(self) -> None:
        class FakeWindow:
            def winfo_viewable(self) -> bool:
                return True

            def winfo_rootx(self) -> int:
                return 10

            def winfo_rooty(self) -> int:
                return 10

            def winfo_width(self) -> int:
                return 80

            def winfo_height(self) -> int:
                return 40

        point = main.wintypes.POINT(20, 20)

        def get_cursor_pos(pointer: object) -> int:
            target = main.ctypes.cast(
                pointer, main.ctypes.POINTER(main.wintypes.POINT)
            ).contents
            target.x = point.x
            target.y = point.y
            return 1

        updates: list[bool] = []
        overlay = SimpleNamespace(
            enabled=True,
            window=FakeWindow(),
            click_through_enabled=True,
            line_windows=[],
        )

        def set_click_through(enabled: bool) -> None:
            updates.append(enabled)
            overlay.click_through_enabled = enabled

        overlay.set_click_through = set_click_through
        user32 = SimpleNamespace(GetCursorPos=get_cursor_pos)

        with patch.object(
            main.ctypes,
            "windll",
            SimpleNamespace(user32=user32),
            create=True,
        ):
            main.TranslationOverlay.check_pointer(overlay)
            main.TranslationOverlay.check_pointer(overlay)

        self.assertEqual(updates, [False])

    def test_resized_overlay_preserves_box_and_renders_translated_text(self) -> None:
        overlay = SimpleNamespace(
            font_family="Segoe UI",
            font_size=18,
            outline_size=1,
            outline_enabled=False,
            background_enabled=True,
            outline_color="#000000",
            _font=lambda size: ImageFont.load_default(size=max(1, size)),
            _render_cache=main.OrderedDict(),
        )

        image = main.TranslationOverlay._render_translation(
            overlay,
            "Перевод уже готов и должен остаться видимым после изменения размера.",
            240,
            target_size=(240, 100),
        )
        cached_image = main.TranslationOverlay._render_translation(
            overlay,
            "Перевод уже готов и должен остаться видимым после изменения размера.",
            240,
            target_size=(240, 100),
        )

        self.assertEqual(image.size, (240, 100))
        self.assertIs(cached_image, image)
        colors = np.unique(np.asarray(image).reshape(-1, 4), axis=0)
        self.assertGreater(len(colors), 1)

        long_image = main.TranslationOverlay._render_translation(
            overlay,
            "Long translated dialogue " * 30,
            160,
            target_size=(160, 72),
        )

        self.assertEqual(long_image.width, 160)
        self.assertGreater(long_image.height, 72)

    def test_area_selector_is_masked_from_ocr(self) -> None:
        app = SimpleNamespace(
            own_window_handles=(),
            overlay=SimpleNamespace(window_handles=()),
            selector_handle=99,
        )
        source = bytes([200, 200, 200] * 16)
        with patch.object(main, "get_native_window_bounds", return_value=(1, 1, 3, 3)):
            masked = main.ScreenTranslator._mask_own_windows(
                app,
                source,
                4,
                4,
                {"left": 0, "top": 0, "width": 4, "height": 4},
            )

        pixels = np.frombuffer(masked, dtype=np.uint8).reshape(4, 4, 3)
        self.assertEqual(tuple(pixels[1, 1]), (16, 24, 32))
        self.assertEqual(tuple(pixels[0, 0]), (200, 200, 200))

    def test_translation_overlay_windows_are_masked_from_ocr(self) -> None:
        app = SimpleNamespace(
            own_window_handles=(),
            overlay=SimpleNamespace(window_handles=(99,)),
            selector_handle=None,
        )
        source = bytes([200, 200, 200] * 16)
        with patch.object(main, "get_native_window_bounds", return_value=(1, 1, 3, 3)):
            masked = main.ScreenTranslator._mask_own_windows(
                app,
                source,
                4,
                4,
                {"left": 0, "top": 0, "width": 4, "height": 4},
            )

        pixels = np.frombuffer(masked, dtype=np.uint8).reshape(4, 4, 3)
        self.assertEqual(tuple(pixels[1, 1]), (16, 24, 32))
        self.assertEqual(tuple(pixels[0, 0]), (200, 200, 200))

    def test_font_fallback_supports_older_pillow_signature(self) -> None:
        overlay = SimpleNamespace(
            font_family="missing-font",
            font_size=18,
            _font_cache={},
        )
        with (
            patch.object(
                ImageFont,
                "truetype",
                side_effect=OSError("font unavailable"),
            ),
            patch.object(ImageFont, "load_default", return_value="fallback") as fallback,
        ):
            fallback.side_effect = [TypeError("no size parameter"), "fallback"]

            font = main.TranslationOverlay._font(overlay)

        self.assertEqual(font, "fallback")
        self.assertEqual(fallback.call_count, 2)


class DialogueBoundsTests(unittest.TestCase):
    def test_combine_dialogue_lines_unites_text_and_bounds(self) -> None:
        dialogue = main.combine_dialogue_lines(
            [
                {
                    "text": "First line",
                    "language": "en",
                    "bounds": {"left": 100, "top": 50, "width": 80, "height": 20},
                },
                {
                    "text": "Second line",
                    "language": "en",
                    "bounds": {"left": 90, "top": 75, "width": 120, "height": 25},
                },
            ]
        )

        self.assertEqual(dialogue["text"], "First line Second line")
        self.assertEqual(
            dialogue["bounds"],
            {"left": 90, "top": 50, "width": 120, "height": 50},
        )
        self.assertTrue(dialogue["dialogue"])

    def test_combine_dialogue_lines_preserves_context_across_visual_lines(self) -> None:
        dialogue = main.combine_dialogue_lines(
            [
                {
                    "text": "Quite frankly, his voice is the last",
                    "language": "en",
                    "bounds": {"left": 100, "top": 50, "width": 300, "height": 30},
                },
                {
                    "text": "thing I want to be hearing right now.",
                    "language": "en",
                    "bounds": {"left": 90, "top": 85, "width": 320, "height": 30},
                },
            ]
        )

        self.assertEqual(
            dialogue["text"],
            "Quite frankly, his voice is the last thing I want to be hearing right now.",
        )
        self.assertNotIn("\n", dialogue["text"])

    def test_combine_dialogue_lines_keeps_so_clause_in_same_sentence(self) -> None:
        dialogue = main.combine_dialogue_lines(
            [
                {
                    "text": "I was there,",
                    "language": "en",
                    "bounds": {"left": 100, "top": 50, "width": 140, "height": 30},
                },
                {
                    "text": "so I know.",
                    "language": "en",
                    "bounds": {"left": 90, "top": 85, "width": 160, "height": 30},
                },
            ]
        )

        self.assertEqual(dialogue["text"], "I was there, so I know.")

    def test_combine_japanese_dialogue_lines_does_not_insert_spaces(self) -> None:
        dialogue = main.combine_dialogue_lines(
            [
                {
                    "text": "教室では",
                    "language": "ja",
                    "bounds": {"left": 100, "top": 50, "width": 100, "height": 30},
                },
                {
                    "text": "日本語を話しましょう。",
                    "language": "ja",
                    "bounds": {"left": 90, "top": 85, "width": 200, "height": 30},
                },
            ]
        )

        self.assertEqual(dialogue["text"], "教室では日本語を話しましょう。")

    def test_combine_dialogue_lines_rejects_empty_input(self) -> None:
        with self.assertRaises(ValueError):
            main.combine_dialogue_lines([])


if __name__ == "__main__":
    unittest.main()
