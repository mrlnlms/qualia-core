"""Testes para os data models do Job."""
import time
from datetime import datetime, timezone

from qualia.core.jobs import Job, JobStatus, JobStep, JobType


class TestJobStatus:
    def test_enum_values(self):
        assert JobStatus.pending == "pending"
        assert JobStatus.running == "running"
        assert JobStatus.completed == "completed"
        assert JobStatus.failed == "failed"
        assert JobStatus.cancelled == "cancelled"

    def test_is_terminal(self):
        assert not JobStatus.pending.is_terminal
        assert not JobStatus.running.is_terminal
        assert JobStatus.completed.is_terminal
        assert JobStatus.failed.is_terminal
        assert JobStatus.cancelled.is_terminal


class TestJobType:
    def test_enum_values(self):
        assert JobType.single == "single"
        assert JobType.pipeline == "pipeline"


class TestJobStep:
    def test_create_pending(self):
        step = JobStep(plugin_id="sentiment")
        assert step.status == JobStatus.pending
        assert step.progress is None
        assert step.result is None
        assert step.error is None

    def test_mark_running(self):
        step = JobStep(plugin_id="sentiment")
        step.status = JobStatus.running
        assert step.status == JobStatus.running

    def test_mark_completed_with_result(self):
        step = JobStep(plugin_id="sentiment")
        step.status = JobStatus.completed
        step.result = {"sentiment_score": 0.85}
        assert step.result == {"sentiment_score": 0.85}

    def test_mark_failed_with_error(self):
        step = JobStep(plugin_id="sentiment")
        step.status = JobStatus.failed
        step.error = "Plugin crashed"
        assert step.error == "Plugin crashed"


class TestJob:
    def test_create_single_job(self):
        job = Job.create_single(plugin_id="sentiment")
        assert job.type == JobType.single
        assert job.status == JobStatus.pending
        assert job.plugin_id == "sentiment"
        assert job.progress == 0.0
        assert job.current_step == 0
        assert job.total_steps == 1
        assert job.steps == []
        assert job.result is None
        assert job.error is None
        assert job.callback_url is None
        assert job.temp_files == []
        assert job.ttl == 3600
        assert len(job.id) == 36  # UUID format

    def test_create_single_with_options(self):
        job = Job.create_single(
            plugin_id="transcription_local",
            callback_url="http://localhost:9000/hook",
            temp_files=["/tmp/audio.wav"],
            ttl=7200,
        )
        assert job.callback_url == "http://localhost:9000/hook"
        assert job.temp_files == ["/tmp/audio.wav"]
        assert job.ttl == 7200

    def test_create_pipeline_job(self):
        plugin_ids = ["transcription_local", "sentiment", "wordcloud"]
        job = Job.create_pipeline(plugin_ids=plugin_ids)
        assert job.type == JobType.pipeline
        assert job.status == JobStatus.pending
        assert job.plugin_id == "transcription_local"
        assert job.total_steps == 3
        assert len(job.steps) == 3
        assert all(s.status == JobStatus.pending for s in job.steps)
        assert [s.plugin_id for s in job.steps] == plugin_ids

    def test_is_expired_false_when_fresh(self):
        job = Job.create_single(plugin_id="sentiment")
        assert not job.is_expired

    def test_is_expired_true_when_old(self):
        job = Job.create_single(plugin_id="sentiment", ttl=0)
        time.sleep(0.01)
        assert job.is_expired

    def test_to_dict_single(self):
        job = Job.create_single(plugin_id="sentiment")
        d = job.to_dict()
        assert d["type"] == "single"
        assert d["status"] == "pending"
        assert d["plugin_id"] == "sentiment"
        assert "id" in d
        assert "created_at" in d
        assert "steps" not in d  # single jobs omit steps

    def test_to_dict_pipeline_includes_steps(self):
        job = Job.create_pipeline(plugin_ids=["a", "b"])
        d = job.to_dict()
        assert "steps" in d
        assert len(d["steps"]) == 2
        assert d["steps"][0]["plugin_id"] == "a"

    def test_calculate_progress_single(self):
        job = Job.create_single(plugin_id="sentiment")
        assert job.progress == 0.0
        job.status = JobStatus.completed
        job.progress = 1.0
        assert job.progress == 1.0

    def test_calculate_progress_pipeline(self):
        job = Job.create_pipeline(plugin_ids=["a", "b", "c", "d", "e"])
        # 2 of 5 completed
        job.steps[0].status = JobStatus.completed
        job.steps[1].status = JobStatus.completed
        job.steps[2].status = JobStatus.running
        job.update_progress()
        assert job.progress == 0.4  # 2/5
