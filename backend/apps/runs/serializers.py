from rest_framework import serializers


class TriggerSerializer(serializers.Serializer):
    """What started a run. Dagster does not record this directly; it is read
    from the run's tags (context/integrations/dagster.md)."""

    kind = serializers.ChoiceField(["schedule", "sensor", "manual"], read_only=True)
    name = serializers.CharField(read_only=True, allow_null=True)


class RunSerializer(serializers.Serializer):
    """One pipeline run, as the Runs list shows it."""

    id = serializers.CharField(read_only=True)
    short_id = serializers.CharField(read_only=True, help_text="First 8 characters of the id.")
    job_name = serializers.CharField(read_only=True)
    status = serializers.CharField(
        read_only=True,
        help_text=(
            "Dagster's run status, passed through unchanged: QUEUED, NOT_STARTED, "
            "MANAGED, STARTING, STARTED, SUCCESS, FAILURE, CANCELING or CANCELED."
        ),
    )
    created_at = serializers.DateTimeField(read_only=True)
    started_at = serializers.DateTimeField(read_only=True, allow_null=True)
    ended_at = serializers.DateTimeField(read_only=True, allow_null=True)
    duration_seconds = serializers.FloatField(read_only=True, allow_null=True)
    trigger = TriggerSerializer(read_only=True)
    partition = serializers.CharField(read_only=True, allow_null=True)
    steps_succeeded = serializers.IntegerField(read_only=True, allow_null=True)
    steps_failed = serializers.IntegerField(read_only=True, allow_null=True)
    materializations = serializers.IntegerField(read_only=True, allow_null=True)
    assets = serializers.ListField(child=serializers.CharField(), read_only=True)


class RunListSerializer(serializers.Serializer):
    """A page of runs, newest first.

    `next_cursor` is the last run id of this page; pass it back as `cursor` to
    get the next one. It is null on the last page.
    """

    results = RunSerializer(many=True, read_only=True)
    next_cursor = serializers.CharField(read_only=True, allow_null=True)


class RunTagSerializer(serializers.Serializer):
    key = serializers.CharField(read_only=True)
    value = serializers.CharField(read_only=True)


class RunStepSerializer(serializers.Serializer):
    """One step of a run. Its status is a smaller enum than the run's: a step
    is only ever SKIPPED, SUCCESS, FAILURE or IN_PROGRESS."""

    step_key = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True, allow_null=True)
    started_at = serializers.DateTimeField(read_only=True, allow_null=True)
    ended_at = serializers.DateTimeField(read_only=True, allow_null=True)
    duration_seconds = serializers.FloatField(read_only=True, allow_null=True)


class RunDetailSerializer(RunSerializer):
    """One run with its per-step breakdown (specs/runs.md)."""

    tags = RunTagSerializer(many=True, read_only=True)
    steps = RunStepSerializer(many=True, read_only=True)
    failure_summary = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text=(
            "The first error in a failed run's log, or null. Null on a run that "
            "did not fail, and on one whose failure lies beyond the log scan."
        ),
    )


class LogErrorSerializer(serializers.Serializer):
    message = serializers.CharField(read_only=True)
    stack = serializers.ListField(child=serializers.CharField(), read_only=True)


class LogEventSerializer(serializers.Serializer):
    """One line of a run's event log."""

    timestamp = serializers.DateTimeField(read_only=True, allow_null=True)
    level = serializers.CharField(read_only=True, allow_null=True)
    step_key = serializers.CharField(read_only=True, allow_null=True)
    message = serializers.CharField(read_only=True)
    error = LogErrorSerializer(read_only=True, allow_null=True)


class RunLogsSerializer(serializers.Serializer):
    """A page of a run's event log, oldest first."""

    events = LogEventSerializer(many=True, read_only=True)
    next_cursor = serializers.CharField(read_only=True, allow_null=True)
    has_more = serializers.BooleanField(read_only=True)


class LaunchedRunSerializer(serializers.Serializer):
    """The run a trigger started."""

    id = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
