from blackboard import Blackboard
from message import MessageBus
from agents.grading_alignment_agent import GradingAlignmentAgent


def test_parse_yaml_weighted_rubric():
    bb = Blackboard(run_id="test_run", topic="speech diarization")
    bus = MessageBus()
    agent = GradingAlignmentAgent(blackboard=bb, bus=bus)

    yaml_rubric = """
categories:
  - name: "Multi-Engine Evidence Depth"
    weight: 0.3
    description: "Must use at least 2 distinct search engines."
  - name: "Technical Feasibility"
    weight: 0.4
    description: "Evaluates hardware and complexity constraints."
  - name: "Architectural Novelty"
    weight: 0.3
    description: "Novelty beyond existing open source."
"""
    criteria = agent.parse_rubric(yaml_rubric)
    assert len(criteria) == 3
    assert criteria[0]["criterion"] == "Multi-Engine Evidence Depth"
    assert criteria[0]["weight"] == 0.3
    assert criteria[1]["criterion"] == "Technical Feasibility"


def test_parse_markdown_checklist_rubric():
    bb = Blackboard(run_id="test_run", topic="speech diarization")
    bus = MessageBus()
    agent = GradingAlignmentAgent(blackboard=bb, bus=bus)

    checklist_rubric = """
# Grading Rubric
- [ ] Source Verification Coverage (weight: 25%)
- [ ] Gap Analysis Specificity (weight: 35%)
- [ ] Tech Stack Layering (weight: 40%)
"""
    criteria = agent.parse_rubric(checklist_rubric)
    assert len(criteria) == 3
    assert criteria[0]["criterion"] == "Source Verification Coverage"
    assert criteria[0]["weight"] == 25.0
    assert criteria[2]["criterion"] == "Tech Stack Layering"
    assert criteria[2]["weight"] == 40.0
