from memory_brain import CreativeProfessional


def test_store_contradictory_ideas_uses_negative_dimensions():
    palace = CreativeProfessional("VOID_ARCHITECT_PRIMUS")
    stored = palace.store_contradictory_ideas(["Idea1", "Idea2"])
    assert stored == {-1: "Idea1", -2: "Idea2"}


def test_separate_internal_universes_assigns_one_belief_each():
    palace = CreativeProfessional("VOID_ARCHITECT_PRIMUS")
    universes = palace.separate_internal_universes(["Belief1", "Belief2"])
    assert universes == {"universe_1": "Belief1", "universe_2": "Belief2"}


def test_govern_geometry_returns_architect_and_structures():
    palace = CreativeProfessional("VOID_ARCHITECT_PRIMUS")
    palace.store_contradictory_ideas(["Idea1"])
    palace.separate_internal_universes(["Belief1"])
    geometry = palace.govern_geometry()
    assert geometry["VOID_ARCHITECT_PRIMUS"] == "VOID_ARCHITECT_PRIMUS"
    assert geometry["negative_hollow_dimensions"] == {-1: "Idea1"}
    assert geometry["internal_universes"] == {"universe_1": "Belief1"}


def test_creative_professional_can_hold_paradoxical_worldviews():
    palace = CreativeProfessional("VOID_ARCHITECT_PRIMUS")
    assert palace.hold_paradoxical_worldviews() is False
    palace.store_contradictory_ideas(["Idea1"])
    palace.separate_internal_universes(["Belief1"])
    assert palace.hold_paradoxical_worldviews() is True
