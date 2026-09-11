"""Unit tests for connection progress step identifiers and labels."""

import pytest

import rdp_client.connection_progress


def test_ordered_connection_steps_include_every_defined_label():
    """Every labeled step appears in the ordered connect sequence."""

    for step_identifier in rdp_client.connection_progress.CONNECTION_STEP_LABELS.keys():
        assert step_identifier in rdp_client.connection_progress.ORDERED_CONNECTION_STEPS


def test_get_connection_step_label_returns_operator_text():
    """Known steps return stable operator-facing labels."""

    label = rdp_client.connection_progress.get_connection_step_label(
        rdp_client.connection_progress.CONNECTION_STEP_AUTHENTICATING)

    assert label == "Authenticating"


def test_get_connection_step_index_orders_preparing_before_ready():
    """Preparing precedes ready in the connect sequence."""

    preparing_index = rdp_client.connection_progress.get_connection_step_index(
        rdp_client.connection_progress.CONNECTION_STEP_PREPARING)

    ready_index = rdp_client.connection_progress.get_connection_step_index(
        rdp_client.connection_progress.CONNECTION_STEP_READY)

    assert preparing_index < ready_index


def test_unknown_step_label_raises_value_error():
    """Unknown step identifiers are rejected."""

    with pytest.raises(ValueError):
        rdp_client.connection_progress.get_connection_step_label("not-a-step")


def test_unknown_step_index_raises_value_error():
    """Unknown step identifiers are rejected for index lookup."""

    with pytest.raises(ValueError):
        rdp_client.connection_progress.get_connection_step_index("not-a-step")
