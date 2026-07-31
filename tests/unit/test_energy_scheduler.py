"""Tests for src.app.core.energy_scheduler — energy-aware task scheduling."""

from src.app.core.energy_scheduler import (
    EnergyBlock,
    format_energy_schedule,
    get_energy_block,
    get_energy_blocks,
    suggest_task_timing,
)

# ---------------------------------------------------------------------------
# get_energy_block
# ---------------------------------------------------------------------------


class TestGetEnergyBlock:
    def test_deep_work_at_9am(self):
        block = get_energy_block(9)
        assert block.label == "deep_work"

    def test_deep_work_at_11am(self):
        block = get_energy_block(11)
        assert block.label == "deep_work"

    def test_low_energy_at_noon(self):
        block = get_energy_block(12)
        assert block.label == "low_energy"

    def test_admin_at_1pm(self):
        block = get_energy_block(13)
        assert block.label == "admin"

    def test_admin_at_2pm(self):
        block = get_energy_block(14)
        assert block.label == "admin"

    def test_creative_at_7pm(self):
        block = get_energy_block(19)
        assert block.label == "creative"

    def test_creative_at_8pm(self):
        block = get_energy_block(20)
        assert block.label == "creative"

    def test_low_energy_late_evening(self):
        block = get_energy_block(22)
        assert block.label == "low_energy"

    def test_free_at_3am(self):
        block = get_energy_block(3)
        assert block.label == "free"

    def test_free_at_4pm(self):
        """4pm is between admin (ends 3pm) and creative (starts 7pm)."""
        block = get_energy_block(16)
        assert block.label == "free"

    def test_boundary_deep_work_end(self):
        """Hour 12 should be low_energy, not deep_work (end is exclusive)."""
        block = get_energy_block(12)
        assert block.label != "deep_work"

    def test_boundary_admin_end(self):
        """Hour 15 should be free, not admin (end is exclusive)."""
        block = get_energy_block(15)
        assert block.label == "free"


# ---------------------------------------------------------------------------
# suggest_task_timing
# ---------------------------------------------------------------------------


class TestSuggestTaskTiming:
    def test_high_complexity_gets_deep_work(self):
        tasks = [{"title": "Refactor auth", "complexity": "high", "tags": []}]
        result = suggest_task_timing(tasks)
        assert result[0]["suggested_block"] == "deep_work"

    def test_email_tag_gets_admin(self):
        tasks = [{"title": "Reply to emails", "complexity": "medium", "tags": ["email"]}]
        result = suggest_task_timing(tasks)
        assert result[0]["suggested_block"] == "admin"

    def test_admin_tag_gets_admin(self):
        tasks = [{"title": "File expenses", "complexity": "medium", "tags": ["admin"]}]
        result = suggest_task_timing(tasks)
        assert result[0]["suggested_block"] == "admin"

    def test_meeting_tag_gets_admin(self):
        tasks = [{"title": "Standup", "complexity": "medium", "tags": ["meeting"]}]
        result = suggest_task_timing(tasks)
        assert result[0]["suggested_block"] == "admin"

    def test_creative_tag_gets_creative(self):
        tasks = [{"title": "Write blog post", "complexity": "medium", "tags": ["creative"]}]
        result = suggest_task_timing(tasks)
        assert result[0]["suggested_block"] == "creative"

    def test_writing_tag_gets_creative(self):
        tasks = [{"title": "Draft RFC", "complexity": "medium", "tags": ["writing"]}]
        result = suggest_task_timing(tasks)
        assert result[0]["suggested_block"] == "creative"

    def test_brainstorm_tag_gets_creative(self):
        tasks = [{"title": "Ideation session", "complexity": "medium", "tags": ["brainstorm"]}]
        result = suggest_task_timing(tasks)
        assert result[0]["suggested_block"] == "creative"

    def test_low_complexity_gets_admin(self):
        tasks = [{"title": "Update README", "complexity": "low", "tags": []}]
        result = suggest_task_timing(tasks)
        assert result[0]["suggested_block"] == "admin"

    def test_medium_complexity_no_tags_gets_free(self):
        tasks = [{"title": "Review PR", "complexity": "medium", "tags": []}]
        result = suggest_task_timing(tasks)
        assert result[0]["suggested_block"] == "free"

    def test_empty_task_list(self):
        result = suggest_task_timing([])
        assert result == []

    def test_high_complexity_overrides_admin_tags(self):
        """High complexity should win even if tags suggest admin."""
        tasks = [{"title": "Complex email migration", "complexity": "high", "tags": ["email"]}]
        result = suggest_task_timing(tasks)
        assert result[0]["suggested_block"] == "deep_work"

    def test_original_task_fields_preserved(self):
        tasks = [{"title": "Task A", "complexity": "low", "tags": ["misc"], "priority": 1}]
        result = suggest_task_timing(tasks)
        assert result[0]["title"] == "Task A"
        assert result[0]["priority"] == 1
        assert "suggested_block" in result[0]

    def test_multiple_tasks(self):
        tasks = [
            {"title": "Deep analysis", "complexity": "high", "tags": []},
            {"title": "Check inbox", "complexity": "low", "tags": ["email"]},
            {"title": "Write essay", "complexity": "medium", "tags": ["writing"]},
        ]
        result = suggest_task_timing(tasks)
        assert len(result) == 3
        assert result[0]["suggested_block"] == "deep_work"
        assert result[1]["suggested_block"] == "admin"
        assert result[2]["suggested_block"] == "creative"

    def test_case_insensitive_tags(self):
        tasks = [{"title": "Check Email", "complexity": "medium", "tags": ["Email"]}]
        result = suggest_task_timing(tasks)
        assert result[0]["suggested_block"] == "admin"


# ---------------------------------------------------------------------------
# format_energy_schedule
# ---------------------------------------------------------------------------


class TestFormatEnergySchedule:
    def test_returns_non_empty_string(self):
        result = format_energy_schedule()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_all_block_labels(self):
        result = format_energy_schedule()
        assert "deep_work" in result
        assert "admin" in result
        assert "creative" in result
        assert "low_energy" in result

    def test_contains_header(self):
        result = format_energy_schedule()
        assert "Energy Schedule" in result

    def test_contains_time_ranges(self):
        result = format_energy_schedule()
        assert "9am" in result
        assert "12pm" in result
        assert "1pm" in result
        assert "7pm" in result


# ---------------------------------------------------------------------------
# Configured energy blocks structure
# ---------------------------------------------------------------------------


class TestConfiguredEnergyBlocks:
    def test_blocks_are_energy_block_instances(self):
        for block in get_energy_blocks():
            assert isinstance(block, EnergyBlock)

    def test_expected_block_count(self):
        assert len(get_energy_blocks()) == 5

    def test_deep_work_covers_9_to_12(self):
        deep = [b for b in get_energy_blocks() if b.label == "deep_work"]
        assert len(deep) == 1
        assert deep[0].start_hour == 9
        assert deep[0].end_hour == 12

    def test_admin_covers_13_to_15(self):
        admin = [b for b in get_energy_blocks() if b.label == "admin"]
        assert len(admin) == 1
        assert admin[0].start_hour == 13
        assert admin[0].end_hour == 15

    def test_creative_covers_19_to_21(self):
        creative = [b for b in get_energy_blocks() if b.label == "creative"]
        assert len(creative) == 1
        assert creative[0].start_hour == 19
        assert creative[0].end_hour == 21

    def test_low_energy_blocks_exist(self):
        low = [b for b in get_energy_blocks() if b.label == "low_energy"]
        assert len(low) == 2

    def test_no_overlapping_blocks(self):
        """Energy blocks should not overlap in their time ranges."""
        sorted_blocks = sorted(get_energy_blocks(), key=lambda b: b.start_hour)
        for i in range(len(sorted_blocks) - 1):
            assert sorted_blocks[i].end_hour <= sorted_blocks[i + 1].start_hour, (
                f"Block {sorted_blocks[i].label} ({sorted_blocks[i].end_hour}) "
                f"overlaps with {sorted_blocks[i + 1].label} ({sorted_blocks[i + 1].start_hour})"
            )

    def test_all_blocks_have_task_types(self):
        for block in get_energy_blocks():
            assert len(block.task_types) > 0, f"Block {block.label} has no task types"
