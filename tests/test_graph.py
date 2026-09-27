from unittest.mock import MagicMock

from trainer import graph


def test_route_returns_router_models_decision(monkeypatch):
    decision = MagicMock(target="trainer")
    monkeypatch.setattr(graph, "_router_model", MagicMock(invoke=MagicMock(return_value=decision)))

    result = graph.route({"messages": [("user", "how many steps today?")]})

    assert result == "trainer"


def test_route_can_return_dietician(monkeypatch):
    decision = MagicMock(target="dietician")
    monkeypatch.setattr(graph, "_router_model", MagicMock(invoke=MagicMock(return_value=decision)))

    result = graph.route({"messages": [("user", "how many calories did i eat today?")]})

    assert result == "dietician"
